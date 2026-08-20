"""
Qualitative analysis (A-U spec, 121 sub-points total) — built one sub-point at a
time per the sourcing-pathway workbook. Each sub-point:
  1. Follows its own Sourcing Sequence (an ordered list of Pathway IDs from the
     Document Pathway Reference tab), in order, recording an explicit result for
     EACH step attempted — never stopping at the first one that returned something
     (DON'T/DO INSTEAD rule #22).
  2. Tags the final value with exactly one confidence tag: VERIFIED (2+ independent
     pathways agreed), SINGLE_SOURCE (only one pathway exists/was checked),
     CONFLICT_UNRESOLVED (pathways disagreed — must not feed a decision unreviewed),
     or a terminal negative-result code (NOT_DISCLOSED etc — never silently zero).
  3. Never fabricates: a pathway not wired into this codebase yet is recorded as
     NOT_DISCLOSED for that step, not skipped silently.
  4. Is timestamped at read time via `qualitative_db.write_qualitative`.

LLM calls go through `groq_client.groq_chat`, which already tries the OpenRouter
free-model chain BEFORE falling back to the Groq API key (see groq_client.py) — so
using it here does not add extra Groq-key load beyond what every other feature
already does.
"""

import re
import time

from tools.qualitative_db import write_qualitative, read_qualitative

CACHE_TTL = 30 * 24 * 3600  # business-model classification changes slowly


def _llm_json(sym, label, system_msg, user_prompt, max_tokens, temperature):
    """Shared LLM-call-then-parse step for every A/B sub-point below. Returns
    (data, failed) where `failed=True` means the classifier genuinely never
    produced a usable answer — either groq_chat raised (network/rate limit),
    or it returned something that isn't a JSON object.

    This distinction matters because every caller feeds `data` straight into
    a payload it then hands to `write_qualitative` for a 30-day cache. Before
    this helper existed, every one of these ~12 sub-points called
    `parse_json_loose(raw) or {}` and cached the result unconditionally —
    confirmed on A.1.3 (business composition): a transient failure produced
    an all-"unclassified"/empty payload that got cached for a month and
    rendered as "the company didn't disclose this", which is a claim about
    the filings we had no evidence for; the real story was our own call
    never landing. `failed=True` tells the caller to skip the cache write and
    let the next request retry, instead of freezing a non-answer into a
    month of wrong output. `failed=False` with an empty-ish `data` (e.g. the
    model validly answered "unclear"/"not disclosed") is a REAL finding and
    should still be cached — this only guards against the call never having
    produced a usable answer at all.
    """
    try:
        from tools.groq_client import groq_chat, parse_json_loose
        raw = groq_chat(
            messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": user_prompt}],
            max_tokens=max_tokens, temperature=temperature,
        )
        data = parse_json_loose(raw)
        if not isinstance(data, dict):
            print(f"[qualitative_engine] {label} LLM reply for {sym} had no usable JSON object "
                  f"(raw[:200]={(raw or '')[:200]!r})")
            return {}, True
        return data, False
    except Exception as e:
        print(f"[qualitative_engine] {label} LLM call failed for {sym}: {e}")
        return {}, True


def _concall_digest(symbol, name):
    """Proxy for the AR-13 (MD&A) narrative pathway — reuses the same grounded
    concall corpus digest business_evolution.py builds from, since MD&A and concall
    commentary cover overlapping ground (segment performance, outlook, mix)."""
    try:
        from tools.concall_intelligence import build_concall_intelligence
        ci = build_concall_intelligence(symbol, name=name)
        if not ci.get("available"):
            return ""
        parts = []
        for c in (ci.get("calls") or [])[:8]:
            seg = f"{c.get('date')}: {c.get('one_line', '')}"
            extra = (c.get("commitments") or []) + (c.get("positives") or [])
            if extra:
                seg += " | " + "; ".join(str(x) for x in extra[:4])
            parts.append(seg)
        return "\n".join(parts)[:3500]
    except Exception as e:
        print(f"[qualitative_engine] concall digest failed: {e}")
        return ""


_MONTH_ABBR = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
               "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _concall_date_to_iso(date_str):
    """screener_scraper/concall_intelligence dates are formatted 'Mon YYYY'
    (e.g. 'Feb 2026') — NOT the ISO 'YYYY-MM-DD' FRED series use. Used by
    A.5 to align a concall quarter to the right point in a commodity price
    series without a raw string compare silently misaligning the two
    different date formats. Returns None (not a guess) if unparseable."""
    m = re.match(r"([A-Za-z]{3})\w*\s+(\d{4})", (date_str or "").strip())
    if not m:
        return None
    mon = _MONTH_ABBR.get(m.group(1).lower())
    if not mon:
        return None
    return f"{m.group(2)}-{mon:02d}-01"


def _fetch_segment_revenue_context(sym, name):
    """AR-14 pathway: real, self-validated business-segment revenue shares
    for the current year (see tools/annual_report_financials.py's
    `_extract_segment_revenue` — only returned when the segments reconcile
    to the P&L's own Revenue within 6%, so this is either real audited data
    or nothing, never a guess). Returns (segments_pct, fiscal_year) where
    segments_pct is [{'label', 'pct'}] summing to ~100, or (None, None) if
    no reconciled segment note was found for this company/year. Never raises."""
    try:
        from tools.annual_report_financials import list_annual_report_years, _get_extracted_financials
        years = list_annual_report_years(sym, name) or []
        if not years:
            return None, None
        fy = years[0]
        parsed = _get_extracted_financials(sym, name, fy, consolidated=True)
        if not parsed or "error" in parsed:
            return None, None
        segments = parsed.get("segments")
        revenue = parsed.get("revenue")
        if not segments or len(segments) < 2 or not revenue or not revenue[0]:
            return None, None
        total = revenue[0]
        return [{"label": s["label"], "pct": round(s["value_cr"] / total * 100, 1)} for s in segments], fy
    except Exception as e:
        print(f"[qualitative_engine] AR-14 segment fetch failed for {sym}: {e}")
        return None, None


# Bumped whenever the payload shape or sourcing methodology changes — same
# cache-invalidation pattern as _A12_SCHEMA_VERSION/_BIZ_COMP_SCHEMA_VERSION
# below. A.1 previously had no explicit version, relying only on the
# old-field-name heuristic a few lines down; that heuristic still runs for
# rows written before this constant existed, but every methodology change
# from here on bumps this instead.
_A1_SCHEMA_VERSION = 1


def compute_a1_business_model_clarity(symbol, name=None, description="", force=False):
    """A.1.1 — Clarity of business model: single product vs portfolio (business
    diversification). Cyclical vs recurring revenue is a SEPARATE analysis, see
    `compute_a1_2_revenue_characteristics` below — the two must not be merged.

    Sourcing Sequence: AR-13 (MD&A narrative) -> AR-14 (revenue/segment note) ->
    AGG-01 (Screener.in, fallback/cross-check only).

    AR-13 is approximated here via the company's business description (from the
    report) plus the grounded concall digest — both are narrative/MD&A-adjacent
    text already in this codebase. AR-14 (the structured segment-revenue note
    inside the Annual Report) is NOT wired into this codebase yet, so that pathway
    step is recorded as NOT_DISCLOSED rather than guessed — per the DON'T/DO
    INSTEAD guardrails, a missing pathway is never silently skipped or faked.
    Because only one of the two Sourcing Sequence pathways was actually checked,
    the result is tagged SINGLE_SOURCE, not VERIFIED (cross-verification rule).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "A.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        # A cached row written by the old methodology (which classified
        # per-segment recurring/cyclical revenue from segment NAMES and
        # carried 'revenue_pattern'/'recurring_revenue_pct') is stale schema —
        # treat it as a cache miss so no invalid recurring-revenue conclusion
        # can keep being served just because the TTL hasn't expired. Revenue
        # recurringness/cyclicality now live entirely in
        # compute_a1_2_revenue_characteristics.
        if (cached is not None and "revenue_pattern" not in cached and "recurring_revenue_pct" not in cached
                and cached.get("schema_version") == _A1_SCHEMA_VERSION):
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    pathway_results = []

    digest = _concall_digest(sym, name)
    company = name or sym
    context = f"COMPANY: {company}\n"
    if description:
        context += f"\nBUSINESS DESCRIPTION (from filings):\n{description[:2500]}\n"
    if digest:
        context += f"\nRECENT EARNINGS-CALL HIGHLIGHTS (MD&A-adjacent, newest first):\n{digest}\n"

    ar13_checked = bool(description or digest)
    pathway_results.append({
        "pathway_id": "AR-13",
        "source": "MD&A narrative (business description + concall digest proxy)",
        "result": "CHECKED" if ar13_checked else "NOT_DISCLOSED",
    })
    # AR-14: real, self-validated segment revenue shares (see
    # tools/annual_report_financials.py's `_extract_segment_revenue`) — only
    # present when the segments reconcile to the P&L's own Revenue, so this
    # is genuinely CHECKED (real data) or NOT_DISCLOSED (nothing found/didn't
    # reconcile), never a guess.
    segments_pct, segments_fy = _fetch_segment_revenue_context(sym, name)
    if segments_pct:
        context += (f"\nREPORTED BUSINESS SEGMENTS (FY{segments_fy} Annual Report, revenue share of total):\n"
                     + "\n".join(f"- {s['label']}: {s['pct']}%" for s in segments_pct) + "\n")
        pathway_results.append({
            "pathway_id": "AR-14",
            "source": "Revenue/segment note (Annual Report)",
            "result": "CHECKED",
        })
    else:
        pathway_results.append({
            "pathway_id": "AR-14",
            "source": "Revenue/segment note (Annual Report)",
            "result": "NOT_DISCLOSED",
            "note": "No segment-revenue note was found, or its figures didn't reconcile to reported Revenue within tolerance.",
        })
    pathway_results.append({
        "pathway_id": "AGG-01",
        "source": "Screener.in (fallback/cross-check only)",
        "result": "NOT_CHECKED",
        "note": "Cross-check pathway, only used if primary+secondary conflict or are unavailable — not invoked this run.",
    })

    if not ar13_checked:
        payload = {
            "subpoint_id": subpoint_id,
            "schema_version": _A1_SCHEMA_VERSION,
            "title": "Clarity of business model: single product vs portfolio (business diversification)",
            "available": False,
            "reason": "No business description or concall corpus available to ground AR-13.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    # NOTE: this function intentionally does NOT classify per-segment revenue
    # as recurring/cyclical from segment names/descriptions — a segment's
    # revenue composition (e.g. "Retail", "Services") does not establish
    # whether that revenue is recurring. Recurring-vs-cyclical revenue
    # characteristics are handled separately by
    # `compute_a1_2_revenue_characteristics`, grounded in explicit Annual
    # Report evidence (subscriptions, AMC/maintenance contracts, renewal
    # rates, demand-cycle disclosures), never inferred from a business/
    # product label.
    prompt = (
        "You are an equity analyst assessing BUSINESS MODEL CLARITY (single product vs diversified "
        "portfolio) for an Indian listed company, using ONLY the grounded context below. Do not invent "
        "facts not supported by the context. If the context does not clearly support a judgment, say so "
        "explicitly rather than guessing. Do not comment on whether revenue is recurring or cyclical here "
        "— that is assessed elsewhere from different evidence.\n"
        "Return ONLY JSON:\n"
        "{\n"
        '  "model_type": "single_product" | "portfolio" | "unclear",\n'
        '  "rationale": "2-4 sentences citing what in the context supports this, or noting it is unclear",\n'
        '  "segments_mentioned": ["short segment/product names mentioned in the context, if any"]\n'
        "}\n\n"
        f"=== CONTEXT ===\n{context}"
    )
    data, llm_failed = _llm_json(
        sym, "A.1", "You are a precise equity analyst. Reply with strict JSON only. Never fabricate.",
        prompt, max_tokens=700, temperature=0.1,
    )

    model_type = str(data.get("model_type") or "unclear").strip().lower()
    if model_type not in ("single_product", "portfolio", "unclear"):
        model_type = "unclear"
    rationale = str(data.get("rationale") or "").strip()
    segments = [str(s).strip() for s in (data.get("segments_mentioned") or []) if str(s).strip()][:10]

    # Real revenue shares only (segments_pct, deterministic from the AR) —
    # no recurring/cyclical classification is attached here; that dimension
    # is computed separately (see module docstring above) from real evidence,
    # never from a segment's name.
    segment_shares = [{"label": s["label"], "pct": s["pct"]} for s in segments_pct] if segments_pct else None

    # Only one of the two Sourcing Sequence pathways (AR-13) was actually checked;
    # AR-14 is a recorded gap, not an independent second source — so this is
    # SINGLE_SOURCE per the cross-verification rule, never VERIFIED.
    confidence_tag = "SINGLE_SOURCE" if rationale else "SEARCH_INCONCLUSIVE"

    payload = {
        "subpoint_id": subpoint_id,
        "schema_version": _A1_SCHEMA_VERSION,
        "title": "Clarity of business model: single product vs portfolio (business diversification)",
        "available": True,
        "model_type": model_type,
        "rationale": rationale,
        "segments_mentioned": segments,
        "segment_shares": segment_shares,  # [{label, pct}] from the real AR-14 segment note, or None
        "pathway_results": pathway_results,
        "grounded": bool(digest),
    }
    if not llm_failed:
        write_qualitative(sym, subpoint_id, payload, confidence_tag)
    else:
        print(f"[qualitative_engine] A.1 NOT cached for {sym} — LLM call did not run; will retry next request.")
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


_RECURRING_STATUS = ("reported", "calculated", "qualitative_only", "not_disclosed", "unable_to_determine")
_CYCLICALITY_CLASS = ("low", "moderate", "high", "unable_to_determine")
# Bump whenever the payload shape or classification rules change materially —
# a cached row written by an older schema version is treated as a cache miss
# and recomputed, so a methodology change (e.g. this one, which replaced the
# old segment-name-based recurring % with evidence-gated extraction) can never
# keep serving stale results just because the TTL hasn't expired yet.
# v8: a transient LLM failure (rate limit/network) no longer gets cached as a
# real "unable_to_determine"/"not_disclosed" finding — same class of bug fixed
# for A.1.3's business-composition classifier, confirmed to affect this
# sub-point too since it shares the identical `parse_json_loose(raw) or {}`
# pattern. Bumped to invalidate any stale all-punted payload already cached
# under v7.
_A12_SCHEMA_VERSION = 8
# A recurring-revenue conclusion requires an EXPLICIT repeat/renewal signal —
# the mere presence of "contract asset(s)", "contract liabilit(y/ies)",
# "customer contract(s)", "order book", "maintenance", "service(s)" or
# "software" is NOT evidence of recurring revenue on its own (those are
# accounting/business terms that appear in almost every annual report
# regardless of revenue model). Only used as a secondary safety net on top of
# the LLM prompt rules below — defense in depth, same pattern as never
# trusting the LLM to do numerator/denominator division itself.
_RECURRING_SIGNAL_RE = re.compile(
    r"recurr|subscript|renew|annuity\b|\bamc\b|annual maintenance|repeat (purchase|custom)|"
    r"long[- ]term contract|contracted revenue|repeat(ing)? revenue",
    re.I,
)


def compute_a1_2_revenue_characteristics(symbol, name=None, force=False):
    """A.1.2 — Revenue characteristics: how recurring/predictable is revenue, and
    how sensitive is the business to economic/industry cycles. A SEPARATE
    analysis from A.1.1 (business diversification) — see module note on
    `compute_a1_business_model_clarity`. Two independent dimensions, never
    forced onto one recurring<->cyclical spectrum: a business can have
    recurring revenue while still operating in a cyclical industry.

    Sourcing Sequence: AR-14b (Annual Report narrative evidence — revenue
    recognition, subscription/AMC/contract/renewal language, demand-cycle
    risk disclosures) -> AR-13 (MD&A/concall digest, secondary corroboration).

    Hard rules (do not weaken without explicit approval):
      - Revenue-pattern (recurring/cyclical) is NEVER inferred from a segment
        or product NAME — only from explicit textual evidence about how that
        revenue is earned (contracts, subscriptions, renewals, etc).
      - A recurring-revenue PERCENTAGE is only ever populated when either (a)
        the company explicitly states it (`status="reported"`), or (b) both a
        numerator and a relevant-total denominator are explicitly disclosed in
        the evidence text, in which case Navrist computes the ratio itself
        deterministically (`status="calculated"`) — the LLM is never trusted
        to do the division. Every other case leaves pct=None.
      - Zero is a real, evidence-backed value, not a default: pct=0 can only
        occur via the above two paths, never as a stand-in for missing data.
      - `confidence_tag` (retrieval quality: SINGLE_SOURCE/SEARCH_INCONCLUSIVE/
        NOT_FOUND) is a SEPARATE concept from `recurring.status`/
        `cyclicality.classification` (business-evidence quality) — a
        SEARCH_INCONCLUSIVE run must never render as a 0% result.
      - Cyclicality is classified independently, never as `100 - recurring%`.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "A.1.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None and cached.get("schema_version") == _A12_SCHEMA_VERSION:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    pathway_results = []
    company = name or sym

    try:
        from tools.annual_report_financials import fetch_revenue_characteristics_evidence
        evidence = fetch_revenue_characteristics_evidence(sym, name)
    except Exception as e:
        print(f"[qualitative_engine] A.1.2 evidence fetch failed for {sym}: {e}")
        evidence = {"error": str(e)}

    if evidence.get("error"):
        pathway_results.append({
            "pathway_id": "AR-14b", "source": "Annual Report (revenue recognition / recurring / cyclicality text)",
            "result": "NOT_DISCLOSED", "note": evidence["error"],
        })
        payload = {
            "subpoint_id": subpoint_id,
            "schema_version": _A12_SCHEMA_VERSION,
            "available": False,
            "reason": evidence["error"],
            "recurring": {"status": "unable_to_determine", "pct": None, "calc": None, "evidence_bullets": [], "sources": []},
            "cyclicality": {"classification": "unable_to_determine", "drivers": [], "mitigants": [], "sources": []},
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    recurring_excerpts = evidence.get("recurring_excerpts") or []
    cyclicality_excerpts = evidence.get("cyclicality_excerpts") or []
    pathway_results.append({
        "pathway_id": "AR-14b", "source": "Annual Report (revenue recognition / recurring / cyclicality text)",
        "result": "CHECKED" if (recurring_excerpts or cyclicality_excerpts) else "NOT_DISCLOSED",
    })

    digest = _concall_digest(sym, name)
    if digest:
        pathway_results.append({"pathway_id": "AR-13", "source": "Concall digest (secondary corroboration)", "result": "CHECKED"})
    else:
        pathway_results.append({"pathway_id": "AR-13", "source": "Concall digest (secondary corroboration)", "result": "NOT_DISCLOSED"})

    if not recurring_excerpts and not cyclicality_excerpts:
        payload = {
            "subpoint_id": subpoint_id,
            "schema_version": _A12_SCHEMA_VERSION,
            "available": True,
            "recurring": {"status": "not_disclosed", "pct": None, "calc": None, "evidence_bullets": [], "sources": []},
            "cyclicality": {"classification": "unable_to_determine", "drivers": [], "mitigants": [], "sources": []},
            "fiscal_year": evidence.get("fiscal_year"),
            "pdf_url": evidence.get("pdf_url"),
            "pathway_results": pathway_results,
            "grounded": False,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    def _fmt_excerpts(items):
        return "\n".join(f"[p.{e['page']}] ...{e['text']}..." for e in items) or "(none found)"

    context = (
        f"COMPANY: {company}\n\n"
        f"=== ANNUAL REPORT EXCERPTS — RECURRING/CONTRACT/SUBSCRIPTION LANGUAGE ===\n{_fmt_excerpts(recurring_excerpts)}\n\n"
        f"=== ANNUAL REPORT EXCERPTS — CYCLICALITY/DEMAND-SENSITIVITY LANGUAGE ===\n{_fmt_excerpts(cyclicality_excerpts)}\n"
    )
    if digest:
        context += f"\n=== RECENT CONCALL HIGHLIGHTS (secondary) ===\n{digest[:2000]}\n"

    prompt = (
        "You are an equity analyst assessing REVENUE PREDICTABILITY and CYCLICALITY for an Indian listed "
        "company, using ONLY the grounded Annual Report excerpts below. These are two SEPARATE dimensions — "
        "a company can have recurring revenue while still operating in a cyclical industry; do not force one "
        "into the other, and do not compute cyclicality as the inverse of recurring revenue.\n\n"
        "STRICT RULES:\n"
        "- Never infer a revenue-pattern from a product/segment NAME alone — only from explicit statements "
        "about how revenue is earned.\n"
        "- IMPORTANT FALSE-POSITIVE GUARD: the mere presence of the words/phrases \"contract asset(s)\", "
        "\"contract liabilit(y/ies)\", \"customer contract(s)\", \"order book\", \"maintenance\", \"service(s)\", "
        "or \"software\" does NOT by itself prove recurring revenue — these are routine accounting/business terms "
        "that appear in almost every annual report regardless of revenue model. \"Contract liabilities\" is a "
        "standard Ind AS 115 balance-sheet line (deferred revenue not yet earned) and does NOT mean that revenue "
        "repeats/renews. \"Order book\" describes revenue VISIBILITY (future revenue already contracted/booked) — "
        "a different concept from RECURRINGNESS (whether revenue repeats from the same customers over time); a "
        "large order book alone is NOT recurring revenue. Only conclude a revenue stream is recurring when the "
        "text explicitly indicates it REPEATS or RENEWS — e.g. subscriptions, annual maintenance contracts (AMC), "
        "renewal rates, annuity income, repeat/recurring customer relationships, long-term recurring service "
        "agreements. If all you have is contract-asset/liability, order-book, or generic maintenance/service/"
        "software language WITHOUT an explicit repeat/renewal statement, do not use \"qualitative_only\" — use "
        "\"not_disclosed\" instead.\n"
        "- Only set recurring_status to \"reported\" if the excerpts contain an EXPLICIT company-stated "
        "recurring-revenue percentage AND that percentage is semantically tied to recurring/subscription revenue "
        "in the same sentence (e.g. \"recurring revenue represented 72% of revenue\", \"subscription revenue "
        "accounted for 64% of total revenue\") — never a percentage that merely appears near recurring-revenue "
        "language but describes something else (e.g. a margin, growth rate, or unrelated metric). Copy the exact "
        "sentence into recurring_reported_quote.\n"
        "- Only set recurring_status to \"calculated\" if the excerpts contain BOTH an explicit recurring-type "
        "revenue rupee value (numerator, clearly described as recurring/subscription/AMC/renewal revenue) AND an "
        "explicit total/relevant revenue rupee value (denominator) from the SAME reporting period and SAME "
        "consolidated/standalone scope — extract both numbers exactly as stated (with units, e.g. crore) into "
        "calc_numerator_cr/calc_denominator_cr and their source labels; do NOT do the division yourself, Navrist "
        "will calculate it deterministically. If you are not confident the numerator and denominator are from the "
        "same period/scope, or that the denominator is the relevant total revenue, do not use \"calculated\".\n"
        "- If recurring characteristics are described with an explicit repeat/renewal signal but not quantifiable, "
        "use \"qualitative_only\" and leave numeric fields null — actively look for this before giving up. Signals "
        "include: renewal-based contracts, maintenance/AMC arrangements, annuity-style income, long-term recurring "
        "service commitments, repeat-customer relationships, or management describing revenue as committed/steady/"
        "predictable. If the excerpts contain ANY such signal, even a brief one, use \"qualitative_only\" rather "
        "than \"not_disclosed\" — \"not_disclosed\" is for excerpts with NO repeat/renewal signal at all (pure "
        "accounting boilerplate about contract assets/liabilities/order book with no repeat/renewal language).\n"
        "- If nothing relevant is disclosed, use \"not_disclosed\". If you genuinely cannot tell, use "
        "\"unable_to_determine\". NEVER guess a percentage to fill a gap, and NEVER report 0% unless the "
        "company explicitly states recurring revenue is zero/none.\n"
        "- Classify cyclicality (low/moderate/high) from actual DESCRIBED sensitivity, resilience, or impact on "
        "demand/revenue — the mere presence of a word like \"commodity\", \"cycle\", or \"interest rate\" is NOT "
        "itself evidence; the text must describe how conditions actually affect (or don't affect) the business. "
        "This cuts both ways: a statement that the business has maintained stability/resilience through economic "
        "cycles over many years IS real evidence supporting LOW cyclicality — don't discard it just because it's "
        "phrased as reassurance rather than a warning. Weigh mitigants (long-term contracts, regulated revenue, "
        "essential consumption, stable renewals, demonstrated multi-year resilience) against drivers (discretionary "
        "demand, commodity/rate/credit sensitivity actually described as affecting results). USE \"unable_to_"
        "determine\" ONLY when the excerpts contain no real discussion of economic/demand sensitivity or "
        "resilience either way — if they discuss it at all, even briefly, commit to your best-supported "
        "classification (low/moderate/high) rather than defaulting to unable_to_determine.\n\n"
        "Return ONLY JSON with EXACTLY these field names (do not rename, nest, or omit any of them):\n"
        "{\n"
        '  "recurring_status": "reported" | "calculated" | "qualitative_only" | "not_disclosed" | "unable_to_determine",\n'
        '  "recurring_reported_pct": <number or null>,\n'
        '  "recurring_reported_quote": "<exact sentence containing the % or null>",\n'
        '  "calc_numerator_cr": <number or null>,\n'
        '  "calc_numerator_label": "<string or null>",\n'
        '  "calc_denominator_cr": <number or null>,\n'
        '  "calc_denominator_label": "<string or null>",\n'
        '  "recurring_evidence_bullets": ["short, evidence-grounded statements, each traceable to the excerpts, each describing an explicit repeat/renewal signal"],\n'
        '  "cyclicality_classification": "low" | "moderate" | "high" | "unable_to_determine",\n'
        '  "cyclicality_drivers": ["short evidence-grounded statements explaining why"],\n'
        '  "cyclicality_mitigants": ["short evidence-grounded statements, if any, that reduce cyclicality"]\n'
        "}\n\n"
        f"=== CONTEXT ===\n{context}"
    )

    def _call_llm(user_prompt, temperature):
        from tools.groq_client import groq_chat, parse_json_loose
        raw = groq_chat(
            messages=[
                {"role": "system", "content": "You are a precise equity analyst. Reply with strict JSON only. Never fabricate numbers."},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=900, temperature=temperature,
        )
        data = parse_json_loose(raw)
        if not isinstance(data, dict):
            raise ValueError(f"no usable JSON object (raw[:200]={(raw or '')[:200]!r})")
        return data

    # Tracks the FIRST call only — the retry below is a best-effort attempt
    # to improve a punted answer, not the thing that determines whether this
    # sub-point produced a real result worth caching.
    try:
        data = _call_llm(prompt, 0.1)
        llm_failed = False
    except Exception as e:
        print(f"[qualitative_engine] A.1.2 LLM call failed for {sym}: {e}")
        data = {}
        llm_failed = True

    def _recurring_punted(d):
        rs = str(d.get("recurring_status") or "").strip().lower()
        return rs in ("", "not_disclosed", "unable_to_determine")

    def _cyclicality_punted(d):
        cc = d.get("cyclicality_classification")
        if cc is None and isinstance(d.get("cyclicality"), dict):
            cc = d["cyclicality"].get("classification")
        cc = str(cc or d.get("cyclicality") or "").strip().lower()
        return cc in ("", "unable_to_determine")

    # A rate-limited free-tier fallback model sometimes punts on a dimension
    # ("not_disclosed"/"unable_to_determine") even when the retrieved
    # excerpts genuinely contain repeat/renewal or cyclicality language —
    # this is a model-quality gap, not evidence absence. Give it ONE more
    # attempt with a more directive nudge before accepting the punt, but
    # only for a dimension that actually has retrieved excerpts to re-read
    # (never retries into fabricating something from nothing), and merge in
    # only the retry's improvement for that specific dimension — a
    # borderline recurring call on the first pass is not a license to let a
    # second, higher-temperature pass silently overwrite a good cyclicality
    # answer with a worse one.
    retry_recurring = _recurring_punted(data) and bool(recurring_excerpts)
    retry_cyclicality = _cyclicality_punted(data) and bool(cyclicality_excerpts)
    if retry_recurring or retry_cyclicality:
        try:
            nudge = (
                "\n\nIMPORTANT: your first attempt at this defaulted to not_disclosed/unable_to_determine. Before "
                "doing that again, re-read the excerpts above carefully — real annual reports rarely say NOTHING "
                "relevant. If there is ANY genuine repeat/renewal signal (however brief) or ANY genuine discussion "
                "of economic/demand sensitivity or resilience (however brief), you MUST use it and commit to a "
                "non-default classification for that dimension. Only keep not_disclosed/unable_to_determine if, "
                "after this re-read, the excerpts truly contain nothing on-topic for that specific dimension."
            )
            retry_data = _call_llm(prompt + nudge, 0.3)
            if retry_recurring and not _recurring_punted(retry_data):
                for k in ("recurring_status", "recurring_reported_pct", "recurring_reported_quote",
                          "calc_numerator_cr", "calc_numerator_label", "calc_denominator_cr",
                          "calc_denominator_label", "recurring_evidence_bullets",
                          "recurring_description", "recurring_evidence", "rationale"):
                    if k in retry_data:
                        data[k] = retry_data[k]
            if retry_cyclicality and not _cyclicality_punted(retry_data):
                for k in ("cyclicality_classification", "cyclicality_drivers", "cyclicality_mitigants", "cyclicality",
                          "cyclicality_description", "cyclicality_rationale"):
                    if k in retry_data:
                        data[k] = retry_data[k]
        except Exception as e:
            print(f"[qualitative_engine] A.1.2 retry LLM call failed for {sym}: {e}")

    recurring_status = str(data.get("recurring_status") or "unable_to_determine").strip().lower()
    if recurring_status not in _RECURRING_STATUS:
        recurring_status = "unable_to_determine"

    recurring_pct = None
    calc = None
    if recurring_status == "reported":
        quote = str(data.get("recurring_reported_quote") or "").strip()
        try:
            v = float(data.get("recurring_reported_pct"))
        except (TypeError, ValueError):
            v = None
        # Safety net on top of the prompt rule: the claimed quote must (a)
        # actually exist, (b) contain a real recurring/subscription/renewal
        # signal word — not just sit near one — and (c) contain the same
        # number being reported, so a nearby-but-unrelated % (e.g. an EBITDA
        # margin mentioned in the same paragraph) can never be captured as
        # the recurring-revenue figure.
        num_in_quote = v is not None and (
            re.search(re.escape(str(int(v))), quote) or re.search(re.escape(f"{v:.1f}"), quote)
        )
        if v is not None and 0 <= v <= 100 and quote and _RECURRING_SIGNAL_RE.search(quote) and num_in_quote:
            recurring_pct = round(v, 1)
        else:
            recurring_status = "unable_to_determine"  # claimed reported but quote didn't substantiate it — don't trust it
    elif recurring_status == "calculated":
        num_label = str(data.get("calc_numerator_label") or "")
        den_label = str(data.get("calc_denominator_label") or "")
        try:
            num = float(data.get("calc_numerator_cr"))
            den = float(data.get("calc_denominator_cr"))
        except (TypeError, ValueError):
            num = den = None
        # The numerator's own label must carry a real recurring signal —
        # otherwise a contract-liability or order-book figure could slip in
        # as if it were recurring revenue just because it's a number near the
        # right keywords.
        if num is not None and den is not None and num >= 0 and den > 0 and _RECURRING_SIGNAL_RE.search(num_label):
            recurring_pct = round(max(0.0, min(100.0, num / den * 100)), 1)
            calc = {
                "numerator_cr": num, "numerator_label": num_label.strip(),
                "denominator_cr": den, "denominator_label": den_label.strip(),
            }
        else:
            recurring_status = "unable_to_determine"  # claimed calculable but didn't substantiate it — don't trust it
    # qualitative_only / not_disclosed / unable_to_determine: pct stays None — never defaulted to 0.

    # Tolerate the weak fallback model dropping the exact list field and
    # instead returning a free-form description string under a differently
    # named key — wrap it as a single bullet rather than losing the evidence
    # entirely (the false-positive signal-word gate right below still applies
    # to whatever text ends up here, so this doesn't weaken that guard).
    _rec_bullets_raw = data.get("recurring_evidence_bullets")
    if not _rec_bullets_raw:
        _fallback_desc = data.get("recurring_description") or data.get("recurring_evidence") or data.get("rationale")
        _rec_bullets_raw = [_fallback_desc] if isinstance(_fallback_desc, str) and _fallback_desc.strip() else []
    recurring_bullets = [str(b).strip() for b in (_rec_bullets_raw or []) if str(b).strip()][:6]
    if recurring_status == "qualitative_only":
        # Second false-positive guard: qualitative_only requires at least one
        # bullet to actually carry a repeat/renewal signal — a bullet that
        # only mentions "contract liabilities"/"order book"/"maintenance"/
        # "services"/"software" without a recur/subscribe/renew/annuity word
        # is not evidence of recurring revenue, per the hard rule above.
        if not any(_RECURRING_SIGNAL_RE.search(b) for b in recurring_bullets):
            recurring_status = "not_disclosed"
            recurring_bullets = []

    # Weaker fallback models (the free-tier chain in groq_client can bottom
    # out at a small model under heavy rate limiting) sometimes echo a
    # differently-named or nested key instead of the exact schema field —
    # e.g. a bare "cyclicality": "low" instead of "cyclicality_classification".
    # Tolerate the common variants rather than silently discarding a real
    # answer and falling back to "unable_to_determine".
    _cyc_raw = data.get("cyclicality_classification")
    if _cyc_raw is None:
        _cyc_raw = data.get("cyclicality")
    if isinstance(_cyc_raw, dict):
        _cyc_raw = _cyc_raw.get("classification") or _cyc_raw.get("cyclicality_classification")
    cyclicality_class = str(_cyc_raw or "unable_to_determine").strip().lower()
    if cyclicality_class not in _CYCLICALITY_CLASS:
        cyclicality_class = "unable_to_determine"
    _cyc_dict = data.get("cyclicality") if isinstance(data.get("cyclicality"), dict) else {}
    _drivers_raw = data.get("cyclicality_drivers") or _cyc_dict.get("drivers") or []
    _mitigants_raw = data.get("cyclicality_mitigants") or _cyc_dict.get("mitigants") or []
    # Same free-form-description tolerance as recurring_evidence_bullets
    # above — a model that answers with "cyclicality_description": "..."
    # instead of the drivers/mitigants list fields shouldn't lose its
    # reasoning entirely; fold it in as a driver bullet.
    if not _drivers_raw and not _mitigants_raw:
        _fallback_cyc_desc = (
            data.get("cyclicality_description") or data.get("cyclicality_rationale")
            or _cyc_dict.get("description") or _cyc_dict.get("rationale")
        )
        if isinstance(_fallback_cyc_desc, str) and _fallback_cyc_desc.strip():
            _drivers_raw = [_fallback_cyc_desc]
    cyclicality_drivers = [str(b).strip() for b in _drivers_raw if str(b).strip()][:6]
    cyclicality_mitigants = [str(b).strip() for b in _mitigants_raw if str(b).strip()][:6]

    recurring_sources = [{"page": e["page"], "anchor": e["anchor"], "excerpt": e["text"]} for e in recurring_excerpts[:4]]
    cyclicality_sources = [{"page": e["page"], "anchor": e["anchor"], "excerpt": e["text"]} for e in cyclicality_excerpts[:4]]

    has_real_judgment = bool(recurring_bullets or cyclicality_drivers or recurring_pct is not None)
    confidence_tag = "SINGLE_SOURCE" if has_real_judgment else "SEARCH_INCONCLUSIVE"

    payload = {
        "subpoint_id": subpoint_id,
        "schema_version": _A12_SCHEMA_VERSION,
        "available": True,
        "recurring": {
            "status": recurring_status,
            "pct": recurring_pct,
            "calc": calc,
            "evidence_bullets": recurring_bullets,
            "sources": recurring_sources,
        },
        "cyclicality": {
            "classification": cyclicality_class,
            "drivers": cyclicality_drivers,
            "mitigants": cyclicality_mitigants,
            "sources": cyclicality_sources,
        },
        "fiscal_year": evidence.get("fiscal_year"),
        "pdf_url": evidence.get("pdf_url"),
        "pathway_results": pathway_results,
        "grounded": bool(digest),
    }
    if not llm_failed:
        write_qualitative(sym, subpoint_id, payload, confidence_tag)
    else:
        print(f"[qualitative_engine] A.1.2 NOT cached for {sym} — LLM call did not run; will retry next request.")
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


_SEGMENT_PATTERN = ("recurring", "mixed", "cyclical", "unclassified")
_PATTERN_SCORE = {"recurring": 0.0, "mixed": 0.5, "cyclical": 1.0}
# Broader than _RECURRING_SIGNAL_RE — accepts general, well-established
# business-model reasoning as valid grounds for a "recurring" classification
# (per-segment classifier only), not just literal repeat/renewal language
# quoted from a filing. Still excludes bare order-book/contract-asset/
# contract-liability citations, which remain revenue visibility, not
# recurringness.
_GENERAL_RECURRING_REASONING_RE = re.compile(
    r"consumer staple|everyday|essential (consumption|demand|product)|household consumption|repeat purchase|"
    r"membership|deposits?\b|\bloans?\b|insurance premium|maintenance contract|service contract|warranty|"
    r"repeat custom|habitual|non-?discretionary|fmcg|daily use|routine (purchase|consumption)",
    re.I,
)
# v8: the Ind AS 108 segment parser was fixed (see
# annual_report_financials._extract_segment_revenue_matrix), so companies that
# previously fell back to the single-block "Focused / Single Business" view
# purely because their segment note failed to parse — Reliance among them — now
# resolve real reportable segments.
# v9: a classifier reply that fails to parse as usable JSON (no exception, just
# an empty/malformed structure) is now treated as a failed run rather than
# silently cached as "every segment unclassified" — confirmed on ITC, which
# had exactly that result cached with no error ever recorded. Bumped so that
# stale all-unclassified payload (and any sibling from the same silent gap)
# gets recomputed instead of being served for another month.
# v10: added `pattern_sources` (the actual AR excerpts + concall-used flag
# fed to the classifier) so the UI can show a real source trail under each
# segment's classification instead of just the model's prose reasoning.
# Bumped so every cached payload picks up the new field rather than the UI
# silently having nothing to show for stocks generated before this.
# v11 (1B): the classifier now sees each segment's OWN AR excerpts (windows
# whose text actually names that segment) as PRIMARY evidence, falling back
# to the shared company-wide excerpt pool + general business-type reasoning
# only when no segment-named excerpt exists — previously every segment was
# classified from the same shared pool regardless of whether it actually
# mentioned that segment. Added `segment_sourced` per segment. Bumped so
# already-cached companies get reclassified under the corrected sourcing
# instead of keeping a shared-pool classification for up to 30 days.
# v12: the single-block fallback (no reconciled segment note -> one block
# labelled with the COMPANY NAME) is no longer run through the
# Recurring/Cyclical classifier at all. v11 and earlier persisted the noise
# it produced — confirmed live: LT="recurring", SUNPHARMA="cyclical", both
# effectively backwards, each shown as a confident 100% mix. Every such
# payload must be recomputed, so this bump is mandatory, not cosmetic.
_BIZ_COMP_SCHEMA_VERSION = 12

# Per-fiscal-year cache for _classify_segments_pattern's LLM result — see
# that function's cache_subpoint block below for why this exists (shared
# Groq/OpenRouter daily quota exhaustion, confirmed on HINDUNILVR: 3 of 5
# historical years failed with HTTP 429 on one run, forcing
# compute_a1_2_pattern_trend to report NOT_FOUND even though 2 years HAD
# genuinely classified successfully moments earlier in the SAME run — without
# per-year caching, the next retry burns quota re-classifying those same 2
# already-successful years all over again instead of only retrying the ones
# that actually failed).
# v2: MUST be bumped past every v1 entry. v1 was written before the
# single-block fallback was removed from compute_a1_2_pattern_trend and
# before unrequested/hallucinated labels were rejected, so v1 entries can
# hold exactly the garbage this cache then FROZE for 30 days — confirmed on
# HINDUNILVR, whose v1 entries were {FY22: "hindunilvr"=recurring, FY23:
# "hindunilvr"=mixed, FY24: "hindunilvr"=cyclical + hallucinated "water"/
# "home care"/"beauty & wellbeing" labels}. Bumping makes every one of those
# a cache miss so they are recomputed under the corrected rules.
_SEGMENT_PATTERN_YEAR_CACHE_VERSION = 2


def _classify_segments_pattern(sym, name, company, segments_for_calc, fiscal_year=None):
    """Shared segment-pattern (Recurring/Mixed/Cyclical/Unclassified)
    classifier — extracted out of `compute_business_composition` so the same
    grounded, per-segment-sourced (1B) classification logic can be reused for
    a SPECIFIC historical fiscal year too (see `compute_a1_2_pattern_trend`
    below), not only the latest Annual Report. `fiscal_year=None` keeps the
    original latest-year behaviour.

    Returns (patterns_by_label, classification_error, evidence):
      - patterns_by_label: {label.lower(): {pattern, reason_points, brands,
        segment_sourced}}, only for segments the classifier actually returned.
      - classification_error: the exception if the LLM call never produced
        usable JSON (a transient failure, never persisted as a real result —
        same "ITC postmortem" guardrail as compute_business_composition), else None.
      - evidence: the raw fetch_revenue_characteristics_evidence() result,
        for callers that also want the excerpts themselves.
    """
    # Per-year result cache — only for a SPECIFIC historical fiscal_year
    # (compute_a1_2_pattern_trend's multi-year loop). fiscal_year=None (the
    # "latest year" case used by compute_business_composition) is
    # deliberately always freshly classified, unchanged — that call site
    # already has its own subpoint-level cache/TTL and calling it once per
    # request isn't the quota-burning multi-year retry pattern this exists
    # to fix. A cached entry is only ever WRITTEN below after a genuine
    # successful classification (classification_error is None), never for a
    # rate-limited/failed run — same "never persist a fake result" guardrail
    # as the rest of this function.
    cache_subpoint = f"A.1.2y_{fiscal_year}" if fiscal_year is not None else None
    if cache_subpoint:
        cached = read_qualitative(sym, cache_subpoint)
        if cached is not None and cached.get("schema_version") == _SEGMENT_PATTERN_YEAR_CACHE_VERSION:
            return cached.get("patterns_by_label") or {}, None, cached.get("evidence") or {}

    try:
        from tools.annual_report_financials import fetch_revenue_characteristics_evidence
        evidence = fetch_revenue_characteristics_evidence(sym, name, fiscal_year=fiscal_year)
    except Exception as e:
        print(f"[qualitative_engine] segment-pattern evidence fetch failed for {sym} FY{fiscal_year}: {e}")
        evidence = {"error": str(e)}

    def _fmt_excerpts(items):
        return "\n".join(f"[p.{e['page']}] ...{e['text']}..." for e in (items or [])) or "(none found)"

    # 1B requires each segment's pattern to be grounded in that segment's OWN
    # AR/MD&A description — never a single company-wide impression. The
    # underlying excerpt scan (`fetch_revenue_characteristics_evidence`) is
    # not segment-aware, so filter its excerpts here: a window whose text
    # actually names the segment is that segment's OWN evidence (primary); a
    # segment with no name-matched window falls back to the shared/company-
    # wide excerpts, but tagged as fallback so the prompt (and the classifier)
    # never treats it as equivalent to a segment-specific citation.
    def _mentions_segment(text, seg_label):
        tl = (text or "").lower()
        # A multi-word label (e.g. "Consumer Care") must match as a whole
        # phrase or by its most distinctive word (>=4 chars) — matching any
        # short/common word (e.g. "and", "the") would false-positive on
        # nearly every excerpt.
        label_l = seg_label.lower().strip()
        if label_l and label_l in tl:
            return True
        words = [w for w in re.split(r"[^a-z0-9]+", label_l) if len(w) >= 4]
        return any(w in tl for w in words)

    def _own_and_fallback_excerpts(seg_label):
        own = {"recurring": [], "cyclicality": []}
        for family in ("recurring", "cyclicality"):
            for e in (evidence.get(f"{family}_excerpts") or []):
                if _mentions_segment(e.get("text"), seg_label):
                    own[family].append(e)
        return own

    # Concall commentary is already an approved, existing Navrist source (same
    # grounded corpus digest used by A.1's business-model-clarity judgment and
    # elsewhere) — wiring it in here too gives the segment classifier real
    # management commentary to work from (e.g. management describing a
    # specific segment's contracts/demand pattern) in addition to the Annual
    # Report excerpts, without adding any new external source. Generic across
    # every company: `_concall_digest` is symbol-driven, no per-company logic.
    digest = _concall_digest(sym, name)

    seg_names = [s["label"] for s in segments_for_calc]
    patterns_by_label = {}
    seg_sourced_by_label = {}
    # Always attempt classification — the classifier is explicitly allowed to
    # reason from well-established business-model/sector knowledge (e.g.
    # "FMCG household/personal-care products are repeat-purchase, driven by
    # everyday consumer demand" or "auto manufacturing is capex/demand
    # cyclical") even without a literal quote, not only when AR/concall text
    # happened to contain matching language. Still grounded reasoning, not a
    # blind guess — the order-book-only false-positive guard below still
    # applies regardless of source.
    per_segment_blocks = []
    for seg_label in seg_names:
        own = _own_and_fallback_excerpts(seg_label)
        has_own = bool(own["recurring"] or own["cyclicality"])
        seg_sourced_by_label[seg_label.lower()] = has_own
        if has_own:
            per_segment_blocks.append(
                f"--- SEGMENT: {seg_label} (own AR excerpts naming this segment — PRIMARY for this segment) ---\n"
                f"Recurring/contract language: {_fmt_excerpts(own['recurring'])}\n"
                f"Cyclicality/demand language: {_fmt_excerpts(own['cyclicality'])}\n"
            )
        else:
            per_segment_blocks.append(
                f"--- SEGMENT: {seg_label} (NO own-named excerpt found — no segment-specific AR text located; "
                f"classify from general company-wide excerpts below plus well-established business-type "
                f"reasoning, per the rules above) ---\n"
            )
    context = (
        f"COMPANY: {company}\n"
        f"REPORTED SEGMENTS: {', '.join(seg_names)}\n\n"
        + "\n".join(per_segment_blocks) + "\n"
        f"=== COMPANY-WIDE AR EXCERPTS (fallback only — use ONLY for a segment with no own-named excerpt above) ===\n"
        f"Recurring/contract language: {_fmt_excerpts(evidence.get('recurring_excerpts'))}\n"
        f"Cyclicality/demand language: {_fmt_excerpts(evidence.get('cyclicality_excerpts'))}\n"
        + (f"\n=== RECENT CONCALL / MANAGEMENT COMMENTARY (secondary corroboration, newest first) ===\n{digest}\n" if digest else "")
    )
    prompt = (
        "You are an equity analyst classifying the REVENUE PATTERN of each individually reported business "
        "segment for an Indian listed company. For each segment, the excerpts under that SEGMENT's own heading "
        "above (if any) are its PRIMARY evidence and must be used first — never substitute the company-wide "
        "impression for a segment that has its own named excerpts. Only fall back to the company-wide excerpts "
        "and/or well-established general business-type knowledge for a segment explicitly marked 'NO own-named "
        "excerpt found'. The concall/management commentary (if present) is SECONDARY corroboration for any "
        "segment. When neither a segment-specific nor a company-wide source discusses a segment, you MUST STILL "
        "classify it using well-established, general knowledge of how that kind of business actually earns "
        "revenue — e.g. FMCG household/personal-care/food products are repeat-purchase, driven by everyday "
        "consumer demand (typically Cyclical or Mixed, not purely discretionary); auto/industrial manufacturing "
        "is capex- and demand-cycle sensitive (typically Cyclical); IT services delivery is often Mixed "
        "(project-based plus renewing maintenance); banking/lending interest income and insurance premiums are "
        "typically Recurring. Reserve \"unclassified\" for the rare case where you genuinely cannot reason about "
        "the segment's business model at all — it should be UNUSUAL, not the default outcome.\n\n"
        "FALSE-POSITIVE GUARD (still applies regardless of source): order book, contract assets, contract "
        "liabilities, customer contracts, or the mere existence of a contract do NOT by themselves prove "
        "recurring revenue — order book reflects revenue VISIBILITY (future revenue already booked), a DIFFERENT "
        "concept from RECURRINGNESS (whether revenue repeats from the same customers over time). Never cite an "
        "order book figure, alone, as your reason for \"recurring\" — if that is genuinely your only evidence, use "
        "\"cyclical\" or \"unclassified\" instead, or pair it with real reasoning about repeat/renewal.\n\n"
        "Only use \"mixed\" when the segment demonstrably has BOTH meaningful recurring/stable AND cyclical/"
        "transactional characteristics, and you can state both reasons — never as a stand-in for uncertainty, "
        "and never default to \"mixed\" just because the pattern is unclear (use \"unclassified\" instead).\n\n"
        "For EACH segment also provide:\n"
        "- reason_points: 2-3 short bullet points (not a paragraph) explaining the classification — what the "
        "segment's business actually does, and why that supports the pattern chosen. If based on that segment's "
        "own named excerpts, say so; if based on company-wide/general reasoning because no own-named excerpt "
        "existed, make that clear too.\n"
        "- example_brands: 2-4 well-known, real brand/product names commonly associated with that segment for "
        "this company, from general public knowledge (e.g. for an FMCG 'Beauty & Wellbeing' segment: real, "
        "well-known personal-care brand names). ONLY include names you are confident are real and genuinely "
        "associated with this company — leave the list empty rather than guessing or inventing a name.\n\n"
        "Return ONLY JSON:\n"
        '{ "segments": [ {"label": "<EXACT segment label from REPORTED SEGMENTS, one entry per segment, same order>", '
        '"pattern": "recurring" | "mixed" | "cyclical" | "unclassified", '
        '"reason_points": ["point 1", "point 2"], "example_brands": ["Brand A", "Brand B"]} ] }\n\n'
        f"=== CONTEXT ===\n{context}"
    )
    # Distinguishes "the classifier ran and genuinely could not classify" from
    # "the classifier never ran" (rate limit / network). Only the first is a
    # real finding; the second must not be persisted as one.
    classification_error = None
    try:
        from tools.groq_client import groq_chat, parse_json_loose
        raw = groq_chat(
            messages=[
                {"role": "system", "content": "You are a precise equity analyst. Reply with strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1400, temperature=0.1,
        )
        data = parse_json_loose(raw)
        # A model can return a reply that fails to parse as JSON at all (or
        # parses but without a "segments" list) without groq_chat itself
        # raising — that's structurally the same "the classifier didn't
        # actually run" case as a network/rate-limit exception (confirmed:
        # ITC's cache held all-"unclassified" from exactly this, with no
        # exception ever thrown), so it must be treated the same way rather
        # than silently defaulting to {} and letting every segment fall
        # through as "unclassified" for real judgment reasons it never gave.
        # A genuine "the model classified every segment as unclassified" is
        # NOT this case — that's a valid segments list where each entry's
        # own pattern value happens to be "unclassified", handled normally
        # below.
        if data is None or not isinstance(data.get("segments"), list):
            raise ValueError(f"Classifier reply had no usable 'segments' array (raw[:200]={(raw or '')[:200]!r})")
        # Only labels that were ACTUALLY REQUESTED are accepted. The model
        # does sometimes return segments that were never in the input —
        # confirmed on HINDUNILVR FY2024, where a single requested segment
        # came back as four ("water", "home care", "beauty & wellbeing", plus
        # the requested one). Previously every returned label was stored, and
        # a requested segment the model simply omitted got NO classification
        # and then silently dropped out of the percentage base downstream —
        # so a year where only 1 of 5 real segments came back would render
        # that one segment's pattern as ~100% of the mix. Unrequested labels
        # are now discarded and low coverage is treated as a failed run.
        requested_norm = {lbl.lower(): lbl for lbl in seg_names}
        for s in (data.get("segments") or []):
            lbl = str(s.get("label") or "").strip()
            pat = str(s.get("pattern") or "").strip().lower()
            if not lbl or pat not in _SEGMENT_PATTERN:
                continue
            if lbl.lower() not in requested_norm:
                print(f"[qualitative_engine] segment-pattern: discarding unrequested label "
                      f"{lbl!r} for {sym} FY{fiscal_year} (not in {seg_names})")
                continue
            reason_points = [str(p).strip() for p in (s.get("reason_points") or []) if str(p).strip()][:4]
            if not reason_points:
                # Tolerate a model that ignores the list field and answers
                # with the older free-form "reason" string instead.
                fallback = str(s.get("reason") or "").strip()
                reason_points = [fallback] if fallback else []
            brands = [str(b).strip() for b in (s.get("example_brands") or []) if str(b).strip() and len(str(b).strip()) < 60][:4]
            reason_text = " ".join(reason_points)
            # Broadened false-positive gate: a "recurring" claim must be
            # backed by either a literal repeat/renewal signal word OR
            # general, well-established business-model reasoning (consumer
            # staple, essential/everyday demand, membership, deposits/loans,
            # insurance premiums, maintenance/service contracts, warranty) —
            # NOT trusted when the reasoning cites only order-book/contract-
            # asset/contract-liability language with nothing else, which is
            # revenue visibility, not recurringness.
            if pat == "recurring" and not _RECURRING_SIGNAL_RE.search(reason_text) and not _GENERAL_RECURRING_REASONING_RE.search(reason_text):
                pat, reason_points, brands = "unclassified", [], []
            patterns_by_label[lbl.lower()] = {
                "pattern": pat, "reason_points": reason_points, "brands": brands,
                "segment_sourced": seg_sourced_by_label.get(lbl.lower(), False),
            }
        # Zero requested segments came back usable -> the classifier did not
        # really run on THIS company's segments, structurally the same as a
        # rate-limit/parse failure. Raising here (rather than returning an
        # empty dict) routes it through the caller's transient-failure path,
        # which refuses to persist it as a real finding.
        if not patterns_by_label:
            raise ValueError(
                f"Classifier returned no usable classification for any requested segment "
                f"{seg_names} (raw[:200]={(raw or '')[:200]!r})")
    except Exception as e:
        classification_error = e
        print(f"[qualitative_engine] segment-pattern classification failed for {sym} FY{fiscal_year}: {e}")

    if cache_subpoint and classification_error is None and patterns_by_label:
        write_qualitative(sym, cache_subpoint, {
            "schema_version": _SEGMENT_PATTERN_YEAR_CACHE_VERSION,
            "patterns_by_label": patterns_by_label, "evidence": evidence,
        }, "SINGLE_SOURCE")

    return patterns_by_label, classification_error, evidence


def compute_business_composition(symbol, name=None, description="", force=False):
    """Business-model composition (Graph 1): a 100%-stacked, revenue-weighted
    view of the company's reported segments, each classified Recurring/Mixed/
    Cyclical/Unclassified from real evidence — never from the segment's name
    or the company's sector alone. Replaces the older split
    business-diversification / revenue-characteristics presentation with one
    unified, evidence-grounded composition view.

    Everything except the per-segment pattern classification is deterministic:
      - segment revenue shares: real, reconciled Ind AS 108 figures from
        `_extract_segment_revenue` (see `tools/annual_report_financials.py`),
        never LLM-estimated.
      - business-model tag: single segment, or one segment >= 90% of revenue
        -> Focused/Single Business; otherwise Portfolio/Diversified.
      - residual/unallocated: consolidated revenue minus the sum of reported
        segment revenue — shown neutrally, never assigned a pattern unless
        explicit evidence exists for it.
      - the portfolio-level Recurring<->Cyclical position is a revenue-
        weighted average of the segment classifications (Recurring=0,
        Mixed=0.5, Cyclical=1), computed in Python — the LLM never outputs
        this position directly, only the per-segment classification + reason.
    Only the per-segment classification is LLM-assisted, grounded in the same
    Annual Report evidence extraction used for A.1.2 (recurring/cyclicality
    narrative excerpts), and defaults to "unclassified" (not "mixed") when
    evidence is insufficient — uncertainty is never mixed.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "A.1.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None and cached.get("schema_version") == _BIZ_COMP_SCHEMA_VERSION:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    company = name or sym

    # --- Step 1-4: real segment + consolidated revenue, same FY/scope ------
    try:
        from tools.annual_report_financials import list_annual_report_years, _get_extracted_financials
        years = list_annual_report_years(sym, name) or []
        fiscal_year = years[0] if years else None
        parsed = _get_extracted_financials(sym, name, fiscal_year, consolidated=True) if fiscal_year else {"error": "No Annual Report found."}
    except Exception as e:
        print(f"[qualitative_engine] business_composition financials fetch failed for {sym}: {e}")
        parsed = {"error": str(e)}

    if not parsed or "error" in parsed:
        payload = {
            "subpoint_id": subpoint_id, "schema_version": _BIZ_COMP_SCHEMA_VERSION,
            "available": False, "reason": (parsed or {}).get("error", "Annual Report data unavailable."),
        }
        write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    revenue_pair = parsed.get("revenue")
    consolidated_revenue = revenue_pair[0] if revenue_pair else None
    raw_segments = parsed.get("segments")  # [{'label','value_cr'}] or None, only when reconciled within 6%
    pl_page = parsed.get("pl_page")
    pdf_url = parsed.get("source_url")

    if not consolidated_revenue:
        payload = {
            "subpoint_id": subpoint_id, "schema_version": _BIZ_COMP_SCHEMA_VERSION,
            "available": False, "reason": "Could not find consolidated Revenue from Operations on the P&L page.",
        }
        write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    # No reconciled multi-segment note -> treat the whole business as one
    # reported block (still real data: total consolidated revenue), tagged
    # via the existing business-model-clarity judgment (grounded in the
    # business description/concall digest) as a graceful fallback rather
    # than an empty graph. This is NOT the same as inventing segments.
    #
    # CRITICAL: that single block must NOT be run through the
    # Recurring/Cyclical pattern classifier. Its "label" is the company name,
    # so the classifier is being asked to pattern-classify a bare ticker
    # string, and it answers with noise — confirmed live: L&T (engineering &
    # construction, textbook project-cyclical) came back "recurring" and Sun
    # Pharma (pharmaceuticals, textbook defensive) came back "cyclical",
    # each then rendered as a confident "100% Recurring"/"100% Cyclical"
    # current-year mix. Roughly a third of large caps sampled have no
    # reconciled segment note in their latest AR, so this was mislabelling
    # a large slice of the universe. A revenue PATTERN is measured from
    # reported segments or it is not measured at all.
    single_block_fallback = not raw_segments or len(raw_segments) < 2
    if single_block_fallback:
        a1 = compute_a1_business_model_clarity(sym, name, description, force=force)
        model_type = a1.get("model_type") if a1.get("available") else None
        segments_for_calc = [{"label": company, "value_cr": consolidated_revenue}]
    else:
        model_type = None
        segments_for_calc = raw_segments

    # --- Step 5: deterministic revenue shares -------------------------------
    segments_for_calc = sorted(segments_for_calc, key=lambda s: -s["value_cr"])  # largest -> smallest
    reported_sum = sum(s["value_cr"] for s in segments_for_calc)
    residual = consolidated_revenue - reported_sum
    residual_pct = round(max(0.0, residual) / consolidated_revenue * 100, 1) if consolidated_revenue else 0.0

    # --- Step 6-7: segment-specific pattern classification, evidence-grounded ---
    # Skipped entirely in the single-block case (see the comment above) —
    # every segment stays "unclassified", which the pattern-mix code below
    # already handles by excluding it from the base, so no mix is shown
    # rather than a fabricated one.
    if single_block_fallback:
        patterns_by_label, classification_error, evidence = {}, None, {}
    else:
        patterns_by_label, classification_error, evidence = _classify_segments_pattern(
            sym, name, company, segments_for_calc, fiscal_year=fiscal_year)

    segments_out = []
    for s in segments_for_calc:
        pct = round(s["value_cr"] / consolidated_revenue * 100, 1) if consolidated_revenue else 0.0
        cls = patterns_by_label.get(s["label"].lower()) or {"pattern": "unclassified", "reason_points": [], "brands": [], "segment_sourced": False}
        segments_out.append({
            "name": s["label"],
            "external_revenue_cr": round(s["value_cr"], 1),
            "share_pct": pct,
            "pattern": cls["pattern"],
            "pattern_reason_points": cls.get("reason_points") or [],
            "example_brands": cls.get("brands") or [],
            # True only when an AR excerpt actually NAMES this segment (1B:
            # "each segment's OWN business description... never the
            # company-wide description") — False means the classification
            # fell back to company-wide excerpts + general business-type
            # reasoning, which the UI should show as a weaker sourcing basis.
            "segment_sourced": cls.get("segment_sourced", False),
        })

    # --- Step 10: business-model tag (deterministic) ------------------------
    segment_count = len(segments_out)
    top_share = segments_out[0]["share_pct"] if segments_out else 0.0
    if segment_count <= 1 or top_share >= 90.0:
        business_model_tag = "focused_single_business"
        tag_label = "Focused / Single Business"
    else:
        business_model_tag = "portfolio_diversified"
        tag_label = "Portfolio / Diversified"
    composition_note = (f"{tag_label} · {segment_count} reported segment{'s' if segment_count != 1 else ''}")

    # --- Step 11: revenue-weighted portfolio pattern position ---------------
    classified = [s for s in segments_out if s["pattern"] in _PATTERN_SCORE]
    classified_share = sum(s["share_pct"] for s in classified)
    if classified_share > 0:
        weighted_pattern_score = round(
            sum(s["share_pct"] * _PATTERN_SCORE[s["pattern"]] for s in classified) / classified_share, 3
        )
        if weighted_pattern_score < 0.33:
            weighted_pattern_label = "recurring_leaning"
        elif weighted_pattern_score > 0.67:
            weighted_pattern_label = "cyclical_leaning"
        else:
            weighted_pattern_label = "mixed"
    else:
        weighted_pattern_score = None
        weighted_pattern_label = "unclassified"

    # Recomputed here (cheap/cached) since the classification helper now
    # owns its own local `digest` — this call just needs the same bool for
    # the payload's `used_concall`/`grounded` flags below.
    digest = _concall_digest(sym, name)

    # --- Step 12: deterministic plain-English footer (no invented trend) ----
    if model_type == "single_product" and segment_count <= 1:
        biz_clause = "a focused, single business"
    elif business_model_tag == "focused_single_business":
        biz_clause = "a focused business"
    else:
        biz_clause = "a diversified portfolio"
    if weighted_pattern_label == "recurring_leaning":
        pattern_clause = "with revenue that is mostly recurring"
    elif weighted_pattern_label == "cyclical_leaning":
        pattern_clause = "with revenue that is mostly cyclical"
    elif weighted_pattern_label == "mixed":
        pattern_clause = "with a mix of recurring and cyclical revenue"
    elif classification_error:
        pattern_clause = "though its revenue pattern could not be classified on this run"
    elif single_block_fallback:
        pattern_clause = ("though its Annual Report has no reconciled segment note for this year, so the "
                          "recurring-vs-cyclical split is not measured (it is only ever derived from reported "
                          "segments, never inferred from the company as a whole)")
    else:
        pattern_clause = "though its revenue pattern could not be reliably classified from available disclosures"
    footer_readline = f"{company} is {biz_clause}, {pattern_clause}."

    confidence_tag = "SINGLE_SOURCE" if patterns_by_label else "SEARCH_INCONCLUSIVE"

    payload = {
        "subpoint_id": subpoint_id,
        "schema_version": _BIZ_COMP_SCHEMA_VERSION,
        "available": True,
        "fiscal_year": fiscal_year,
        "pdf_url": pdf_url,
        "pl_page": pl_page,
        "business_model_tag": business_model_tag,
        "composition_note": composition_note,
        "total_revenue_cr": round(consolidated_revenue, 1),
        "segment_count": segment_count,
        "segments": segments_out,
        "residual_pct": residual_pct if residual_pct > 0.5 else 0.0,
        "residual_cr": round(max(0.0, residual), 1) if residual > 0.5 else 0.0,
        "weighted_pattern_score": weighted_pattern_score,
        "weighted_pattern_label": weighted_pattern_label,
        "footer_readline": footer_readline,
        # True only when the classifier could not be reached at all. Lets the
        # UI say "couldn't be classified this run" instead of asserting the
        # company failed to disclose something, which would be a claim we have
        # no evidence for.
        "pattern_classification_failed": bool(classification_error),
        # The full company-wide excerpt pool the classifier drew from — each
        # segment above additionally carries its own `segment_sourced` flag
        # (True when at least one of these excerpts actually names that
        # segment and was used as its PRIMARY evidence; False means that
        # segment fell back to this shared pool + general reasoning).
        # `used_concall` tells the UI whether management commentary was part
        # of the grounding too, since a segment's own reason_points can cite
        # either source without saying which.
        "pattern_sources": {
            "recurring_excerpts": [
                {"page": e["page"], "anchor": e.get("anchor"), "excerpt": e["text"]}
                for e in (evidence.get("recurring_excerpts") or [])[:4]
            ],
            "cyclicality_excerpts": [
                {"page": e["page"], "anchor": e.get("anchor"), "excerpt": e["text"]}
                for e in (evidence.get("cyclicality_excerpts") or [])[:4]
            ],
            "used_concall": bool(digest),
        },
    }
    # A transient LLM failure (rate limit, network) leaves every segment
    # "unclassified" — persisting that would bake a non-finding into a
    # 30-day cache and render it as though the filings lacked the disclosure.
    # Same convention as _get_extracted_financials_impl, which deliberately
    # does not cache transient download failures.
    if not classification_error:
        write_qualitative(sym, subpoint_id, payload, confidence_tag)
    else:
        print(f"[qualitative_engine] business_composition NOT cached for {sym} — "
              f"segment classification did not run; will retry next request.")
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


# v2: the single-block "classify the company name as one segment" fallback
# was removed (see the long comment in compute_a1_2_pattern_trend). Every v1
# payload may contain trend points that measured nothing, including
# VERIFIED-badged 3-point trends built entirely from company-name coin
# flips, so no v1 payload may be served as current.
_A12_TREND_SCHEMA_VERSION = 2
_A12_TREND_MAX_YEARS = 5


def compute_a1_2_pattern_trend(symbol, name=None, description="", force=False):
    """1B, current-year + multi-year view: revenue-weighted Recurring vs
    Cyclical % for the latest Annual Report ("current year mix") and for as
    many of the up-to-5 most recent Annual Reports as actually have a
    reconciled segment note ("N-year trend") — real per-year classification,
    reusing the SAME segment-pattern classifier as `compute_business_composition`
    (`_classify_segments_pattern`), just run once per historical filing
    instead of only the latest. A year with no usable segment/revenue data is
    skipped from the trend rather than filled with a guess.

    Mixed-pattern segments split 50/50 between Recurring and Cyclical for
    this two-way % (the 3-way Recurring/Mixed/Cyclical view lives on the A.1
    sunburst); Unclassified segments' revenue is excluded from the base a
    year's % is computed over — never silently folded into either side.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "A.1.2b"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None and cached.get("schema_version") == _A12_TREND_SCHEMA_VERSION:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    company = name or sym
    try:
        from tools.annual_report_financials import list_annual_report_years, _get_extracted_financials
        years = (list_annual_report_years(sym, name) or [])[:_A12_TREND_MAX_YEARS]
    except Exception as e:
        print(f"[qualitative_engine] a1_2_pattern_trend year list failed for {sym}: {e}")
        years = []

    if not years:
        payload = {
            "subpoint_id": subpoint_id, "schema_version": _A12_TREND_SCHEMA_VERSION,
            "available": False, "reason": "No Annual Report found for this company.",
        }
        write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    trend = []
    skipped_years = []
    any_llm_failure = False
    for fy in sorted(years):  # oldest -> newest, matching the reference chart's left-to-right order
        try:
            parsed = _get_extracted_financials(sym, name, fy, consolidated=True)
        except Exception as e:
            print(f"[qualitative_engine] a1_2_pattern_trend financials fetch failed for {sym} FY{fy}: {e}")
            skipped_years.append({"fiscal_year": fy, "reason": "ANNUAL_REPORT_FETCH_FAILED"})
            continue
        if not parsed or "error" in parsed:
            skipped_years.append({"fiscal_year": fy, "reason": "ANNUAL_REPORT_UNREADABLE"})
            continue
        revenue_pair = parsed.get("revenue")
        consolidated_revenue = revenue_pair[0] if revenue_pair else None
        raw_segments = parsed.get("segments")
        if not consolidated_revenue:
            skipped_years.append({"fiscal_year": fy, "reason": "NO_REVENUE_ON_PL_PAGE"})
            continue

        # A year WITHOUT a reconciled multi-segment note contributes NOTHING
        # to this trend. There used to be a "graceful single-block fallback"
        # here that classified the whole company as one segment labelled with
        # the COMPANY NAME — that was actively harmful, not graceful:
        # confirmed on HINDUNILVR, whose segment note only reconciles for
        # FY2026, so FY2022/23/24 each fell back to asking the classifier to
        # label the bare string "HINDUNILVR". It answered recurring / mixed /
        # cyclical on three different years — three independent coin flips on
        # a company name, rendered to the user as a real 3-year
        # Recurring-vs-Cyclical TREND (FY24 showing "0% Recurring" for an
        # FMCG staples business) and awarded a VERIFIED badge purely because
        # three such points existed. A revenue-PATTERN trend has to be
        # measured from actual reported segments or not shown at all; a
        # missing segment note is missing data, never a data point.
        if not raw_segments or len(raw_segments) < 2:
            skipped_years.append({"fiscal_year": fy, "reason": "NO_RECONCILED_SEGMENT_NOTE"})
            continue
        segments_for_calc = raw_segments

        patterns_by_label, classification_error, _evidence = _classify_segments_pattern(
            sym, name, company, segments_for_calc, fiscal_year=fy)
        if classification_error:
            any_llm_failure = True
            skipped_years.append({"fiscal_year": fy, "reason": "CLASSIFIER_UNREACHABLE"})
            continue

        recurring_rev = cyclical_rev = classified_rev = 0.0
        for s in segments_for_calc:
            cls = patterns_by_label.get(s["label"].lower())
            pat = (cls or {}).get("pattern")
            if pat == "recurring":
                recurring_rev += s["value_cr"]
                classified_rev += s["value_cr"]
            elif pat == "cyclical":
                cyclical_rev += s["value_cr"]
                classified_rev += s["value_cr"]
            elif pat == "mixed":
                recurring_rev += s["value_cr"] * 0.5
                cyclical_rev += s["value_cr"] * 0.5
                classified_rev += s["value_cr"]
            # "unclassified" (or missing) segments are excluded from the base.
        if classified_rev <= 0:
            skipped_years.append({"fiscal_year": fy, "reason": "NO_SEGMENT_CLASSIFIED"})
            continue  # nothing usable this year — skip rather than guess

        trend.append({
            "fiscal_year": fy,
            "recurring_pct": round(recurring_rev / classified_rev * 100, 1),
            "cyclical_pct": round(cyclical_rev / classified_rev * 100, 1),
            "classified_coverage_pct": round(classified_rev / consolidated_revenue * 100, 1),
        })

    if not trend:
        no_segment_years = [s["fiscal_year"] for s in skipped_years if s["reason"] == "NO_RECONCILED_SEGMENT_NOTE"]
        if any_llm_failure:
            reason = "Classifier could not be reached for any year this run — will retry next request."
        elif no_segment_years:
            reason = (f"No Annual Report year on file has a reconciled multi-segment revenue note "
                      f"(checked FY{', FY'.join(str(y) for y in sorted(no_segment_years))}). A "
                      f"Recurring-vs-Cyclical split is measured from reported segments — without a segment "
                      f"note there is nothing to measure, and this is reported as unavailable rather than "
                      f"inferred from the company as a single block.")
        else:
            reason = "No year had both a reconciled segment note and revenue on the P&L page."
        payload = {
            "subpoint_id": subpoint_id, "schema_version": _A12_TREND_SCHEMA_VERSION,
            "available": False,
            "reason": reason,
            "skipped_years": skipped_years,
        }
        # A run where every year failed purely on a transient LLM error must
        # not be cached as a real "no data" finding — same guardrail as
        # compute_business_composition's classification_error handling.
        if not any_llm_failure:
            write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    current = trend[-1]
    # VERIFIED requires 3+ years that were each measured from a real reported
    # segment note. Before the single-block fallback was removed above, three
    # company-name coin flips satisfied this and earned a VERIFIED badge on
    # data that measured nothing (see the HINDUNILVR case in that comment) —
    # every entry in `trend` is now genuinely segment-derived, so the count
    # means what the badge claims it means.
    confidence_tag = "VERIFIED" if len(trend) >= 3 else "SINGLE_SOURCE"
    payload = {
        "subpoint_id": subpoint_id,
        "schema_version": _A12_TREND_SCHEMA_VERSION,
        "available": True,
        "current_year_mix": {"fiscal_year": current["fiscal_year"], "recurring_pct": current["recurring_pct"], "cyclical_pct": current["cyclical_pct"]},
        "trend": trend,
        "years_attempted": len(years),
        "years_resolved": len(trend),
        # Surfaced so a short/1-point trend is self-explaining ("4 of 5 years
        # had no reconciled segment note") instead of looking like the app
        # silently lost data.
        "skipped_years": skipped_years,
    }
    if not any_llm_failure:
        write_qualitative(sym, subpoint_id, payload, confidence_tag)
    else:
        print(f"[qualitative_engine] a1_2_pattern_trend partially NOT cached for {sym} — "
              f"{len(years) - len(trend)}/{len(years)} year(s) hit a classifier failure; will retry next request.")
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_a2_competitive_moat(symbol, name=None, description="", market_cap_cr=None, force=False, skip_llm=False):
    """A.2 — Competitive advantage / moats: brand, distribution, cost leadership,
    network effects, switching costs. Composite Moat Rating Breakdown per spec:
    8 peer-quintile-ranked quant pillars (a-h) + a required qualitative-evidence
    score (i) sourced from CRISIL's rating rationale + management commentary.

    Sourcing Sequence: PORTAL-07 (CRISIL rating rationale — tools/crisil_scraper.py,
    verified live) -> AGG-01 (Screener.in fundamentals — fallback/cross-check only,
    also the same-source basis for the peer-quintile pillars).

    HARD RULE (per spec): if the qualitative-evidence score (i) cannot be sourced,
    no composite is shown — the whole rating is flagged QUANT_PROXY_ONLY rather
    than presented as a full moat assessment. Peers are drawn ONLY from the fixed,
    auditable universe in tools/peer_universe.py (NSE sector map + market-cap-band
    widening) — never an open search or free-text "similar companies" guess.

    skip_llm=True: never calls any LLM API (Groq direct key or OpenRouter) — for
    bulk runs where the shared LLM quota must not be touched. This skips BOTH the
    qualitative-evidence classifier AND `_concall_digest` (which itself calls
    groq_chat to summarize concalls) — result is always QUANT_PROXY_ONLY with the
    8 quant pillars + CRISIL rating rationale text populated, ready for a later
    LLM-enabled pass to score without re-scraping.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "A.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    from tools.crisil_scraper import fetch_crisil_rationale
    from tools.moat_peer_scoring import build_moat_rating_breakdown

    crisil_result = fetch_crisil_rationale(name or sym, symbol=sym)
    digest = "" if skip_llm else _concall_digest(sym, name)

    breakdown = build_moat_rating_breakdown(
        sym, name=name, market_cap_cr=market_cap_cr,
        crisil_result=crisil_result, concall_digest=digest, skip_llm=skip_llm,
    )

    pathway_results = list(breakdown["qualitative_evidence"].get("pathway_results") or [])
    peer_status = breakdown.get("peer_set_status")
    if peer_status == "OK":
        peers = breakdown["peer_set"]["peers"]
        pathway_results.append({
            "pathway_id": "AGG-01",
            "source": "Screener.in fundamentals — peer-quintile scoring (tools/moat_peer_scoring.py)",
            "result": "CHECKED",
            "note": f"Scored against {len(peers)} peers in sector '{breakdown['peer_set']['sector']}' "
                    f"(fixed NSE-universe, market-cap band {breakdown['peer_set']['band']}).",
        })
    else:
        pathway_results.append({
            "pathway_id": "AGG-01",
            "source": "Screener.in fundamentals — peer-quintile scoring (tools/moat_peer_scoring.py)",
            "result": "NOT_DISCLOSED",
            "note": (breakdown.get("peer_set") or {}).get("reason", "Peer set could not be built."),
        })

    if peer_status != "OK" and breakdown["qualitative_evidence"].get("score") is None:
        payload = {
            "subpoint_id": subpoint_id,
            "title": "Competitive advantage / moats: brand, distribution, cost leadership, network effects, switching costs",
            "available": True,
            "quant_proxy_only": True,
            "composite_score": None,
            "pillars": breakdown["pillars"],
            "peer_set": breakdown.get("peer_set"),
            "qualitative_evidence": breakdown["qualitative_evidence"],
            "rationale": "Neither the peer-quintile quant pillars nor the qualitative evidence score "
                         "could be sourced this run — see peer_set/qualitative_evidence for the specific reason.",
            "pathway_results": pathway_results,
        }
        confidence_tag = "SEARCH_INCONCLUSIVE"
    else:
        payload = {
            "subpoint_id": subpoint_id,
            "title": "Competitive advantage / moats: brand, distribution, cost leadership, network effects, switching costs",
            "available": True,
            "quant_proxy_only": breakdown["quant_proxy_only"],
            "composite_score": breakdown["composite_score"],
            "pillars": breakdown["pillars"],
            "peer_set": breakdown.get("peer_set"),
            "qualitative_evidence": breakdown["qualitative_evidence"],
            "rationale": (
                "QUANT_PROXY_ONLY - the qualitative-evidence score could not be sourced from CRISIL/ICRA "
                "or management commentary this run, so per the hard rule no composite moat rating is shown, "
                "only the peer-relative quant pillars."
                if breakdown["quant_proxy_only"] else
                f"Composite Moat Score {breakdown['composite_score']}/5, combining {len(breakdown['pillars']) - 1} "
                f"peer-quintile quant pillars with a qualitative-evidence score of "
                f"{breakdown['qualitative_evidence'].get('score')}/5 "
                f"({breakdown['qualitative_evidence'].get('source')})."
            ),
            "pathway_results": pathway_results,
        }
        # PORTAL-07 (qualitative evidence) and AGG-01 (quant peer score) feed
        # DIFFERENT parts of the composite, not the same fact — so even when
        # both succeed this is never VERIFIED (VERIFIED requires 2+ pathways
        # corroborating the SAME value, per the cross-verification rule).
        # SINGLE_SOURCE whenever at least one produced usable data.
        crisil_ok = crisil_result.get("result") == "CHECKED"
        agg_ok = peer_status == "OK"
        confidence_tag = "SINGLE_SOURCE" if (crisil_ok or agg_ok) else "SEARCH_INCONCLUSIVE"

    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


# Bumped whenever the AR-13 pathway's actual data source changes materially —
# v2 replaced the thin yfinance business-description proxy for AR-13 with a
# real Annual Report MD&A/Business Overview text extraction
# (fetch_brand_evidence_from_annual_report), which was causing near-universal
# "Missing" scores: a one-paragraph factual company blurb almost never
# contains brand-marketing language, regardless of how strong the company's
# real brand evidence is. Bumped so every already-cached company gets
# rescored against the real AR text instead of keeping a stale
# proxy-sourced "Missing" for up to CACHE_TTL.
# v3: fetch_brand_evidence_from_annual_report now filters out director/KMP
# biography text (confirmed false-positive on HGINFRA, whose only match was
# an Independent Director's civil-service career bio, not a company brand
# claim) and dropped the overly-generic "leadership position" anchor.
_A2A_SCHEMA_VERSION = 4  # v4: fixed _sentences() splitting mid-phrase terms across PDF line-wraps


def compute_a2a_brand_moat(symbol, name=None, description="", force=False):
    """A.2.A ("2A" in the sheet) — Brand moat: 0-5 score based on pricing
    power, customer preference, premium positioning, repeat business, and
    market-share evidence.

    Sources: CRISIL/ICRA rating rationale (PORTAL-07, tools/crisil_scraper.py),
    Annual Report MD&A (AR-13, tools/annual_report_financials.py's
    fetch_brand_evidence_from_annual_report — the REAL MD&A/Business Overview
    narrative, not a proxy), Earnings call — NOT_CHECKED this run (see below).

    Deliberately deterministic (tools/moat_brand_scoring.py) rather than
    LLM-scored: every score traces to a literal matched sentence, fully
    reproducible, and avoids the shared Groq/OpenRouter quota entirely —
    chosen for the 2,409-company bulk pass. The earnings-call pathway is
    marked NOT_CHECKED (deliberately not attempted), not NOT_DISCLOSED,
    because this codebase's only earnings-call digest
    (tools/concall_intelligence.py) itself calls an LLM to summarize —
    using it here would defeat the point of avoiding LLM calls.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "A.2.A"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None and cached.get("schema_version") == _A2A_SCHEMA_VERSION:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    from tools.crisil_scraper import fetch_crisil_rationale
    from tools.moat_brand_scoring import score_brand_moat
    from tools.annual_report_financials import fetch_brand_evidence_from_annual_report

    crisil_result = fetch_crisil_rationale(name or sym, symbol=sym)
    crisil_text = crisil_result.get("key_rating_drivers", "") if crisil_result.get("result") == "CHECKED" else ""

    try:
        ar_evidence = fetch_brand_evidence_from_annual_report(sym, name)
    except Exception as e:
        print(f"[qualitative_engine] A.2.A AR brand-evidence fetch failed for {sym}: {e}")
        ar_evidence = {"error": str(e)}
    ar_excerpts = ar_evidence.get("excerpts") or []
    ar_mdna_text = "\n".join(e["text"] for e in ar_excerpts)

    scored = score_brand_moat(crisil_text=crisil_text, business_description=description or "", ar_mdna_text=ar_mdna_text)

    if ar_excerpts:
        ar13_result, ar13_note = "CHECKED", None
    elif "error" in ar_evidence:
        ar13_result, ar13_note = "NOT_DISCLOSED", ar_evidence["error"]
    else:
        ar13_result, ar13_note = "NOT_DISCLOSED", "Annual Report fetched but no brand-evidence language located in its MD&A/Business Overview text."

    pathway_results = [
        {
            "pathway_id": "PORTAL-07", "source": "CRISIL/ICRA Rating Rationale",
            "result": "CHECKED" if crisil_text else crisil_result.get("result", "NOT_DISCLOSED"),
            "note": crisil_result.get("note") if crisil_result.get("result") != "CHECKED" else
                    f"Rated {crisil_result.get('rating')}, {crisil_result.get('rationale_date')}.",
        },
        {
            "pathway_id": "AR-13", "source": "Annual Report MD&A (Business Overview)",
            "result": ar13_result, "note": ar13_note,
        },
        {
            "pathway_id": "QUAL-01", "source": "Earnings call commentary",
            "result": "NOT_CHECKED",
            "note": "Deliberately skipped — this codebase's earnings-call digest itself requires an "
                    "LLM call, which this deterministic sub-point avoids by design.",
        },
    ]

    payload = {
        "subpoint_id": subpoint_id,
        "schema_version": _A2A_SCHEMA_VERSION,
        "title": "Brand",
        "available": True,
        "score": scored["score"],
        "categories_covered": scored["categories_covered"],
        "numeric_anchor": scored["numeric_anchor"],
        "evidence_quote": scored["evidence_quote"],
        "evidence_source": scored["source"],
        "rationale": scored["reasoning"],
        "pathway_results": pathway_results,
    }

    # Only one pathway ever feeds the actual score (CRISIL OR the company's own
    # words, never both corroborating) — SINGLE_SOURCE whenever a score exists, per
    # the cross-verification rule; SEARCH_INCONCLUSIVE when nothing was found at all.
    confidence_tag = "SEARCH_INCONCLUSIVE" if scored["score"] is None else "SINGLE_SOURCE"

    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


_A2B_SCHEMA_VERSION = 2  # v2: fixed _sentences() splitting mid-phrase terms across PDF line-wraps


def compute_a2b_distribution_moat(symbol, name=None, description="", force=False):
    """A.2.B ("2B" in the sheet) — Distribution moat: 0-5 score based on
    distribution-network reach, exclusivity, and channel depth vs named
    competitors.

    Sources, PRIMARY-first (unlike A.2.A/Brand): Annual Report MD&A/Business
    Overview (AR-13, tools/annual_report_financials.py's
    fetch_distribution_evidence_from_annual_report) is PRIMARY — a specific,
    numeric, dated AR claim (dealer/outlet/state counts, exclusivity terms)
    can reach 5/5 on its own, since operational distribution stats in a
    regulated filing are verifiable facts, not marketing prose. CRISIL/ICRA
    rating rationale (PORTAL-07) is SECONDARY, scored the same way as a
    fallback. Earnings call — NOT_CHECKED this run, same reason as A.2.A
    (the only earnings-call digest requires an LLM call).

    Deliberately deterministic (tools/moat_distribution_scoring.py), same
    rationale as A.2.A: reproducible, auditable, avoids the shared
    Groq/OpenRouter quota for the 2,409-company bulk pass.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "A.2.B"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None and cached.get("schema_version") == _A2B_SCHEMA_VERSION:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    from tools.crisil_scraper import fetch_crisil_rationale
    from tools.moat_distribution_scoring import score_distribution_moat
    from tools.annual_report_financials import fetch_distribution_evidence_from_annual_report

    crisil_result = fetch_crisil_rationale(name or sym, symbol=sym)
    crisil_text = crisil_result.get("key_rating_drivers", "") if crisil_result.get("result") == "CHECKED" else ""

    try:
        ar_evidence = fetch_distribution_evidence_from_annual_report(sym, name)
    except Exception as e:
        print(f"[qualitative_engine] A.2.B AR distribution-evidence fetch failed for {sym}: {e}")
        ar_evidence = {"error": str(e)}
    ar_excerpts = ar_evidence.get("excerpts") or []
    ar_mdna_text = "\n".join(e["text"] for e in ar_excerpts)

    scored = score_distribution_moat(ar_mdna_text=ar_mdna_text, crisil_text=crisil_text, business_description=description or "")

    if ar_excerpts:
        ar13_result, ar13_note = "CHECKED", None
    elif "error" in ar_evidence:
        ar13_result, ar13_note = "NOT_DISCLOSED", ar_evidence["error"]
    else:
        ar13_result, ar13_note = "NOT_DISCLOSED", "Annual Report fetched but no distribution-evidence language located in its MD&A/Business Overview text."

    pathway_results = [
        {
            "pathway_id": "AR-13", "source": "Annual Report MD&A (Business Overview) — PRIMARY",
            "result": ar13_result, "note": ar13_note,
        },
        {
            "pathway_id": "PORTAL-07", "source": "CRISIL/ICRA Rating Rationale — SECONDARY",
            "result": "CHECKED" if crisil_text else crisil_result.get("result", "NOT_DISCLOSED"),
            "note": crisil_result.get("note") if crisil_result.get("result") != "CHECKED" else
                    f"Rated {crisil_result.get('rating')}, {crisil_result.get('rationale_date')}.",
        },
        {
            "pathway_id": "QUAL-01", "source": "Earnings call commentary",
            "result": "NOT_CHECKED",
            "note": "Deliberately skipped — this codebase's earnings-call digest itself requires an "
                    "LLM call, which this deterministic sub-point avoids by design.",
        },
    ]

    payload = {
        "subpoint_id": subpoint_id,
        "schema_version": _A2B_SCHEMA_VERSION,
        "title": "Distribution",
        "available": True,
        "score": scored["score"],
        "categories_covered": scored["categories_covered"],
        "numeric_anchor": scored["numeric_anchor"],
        "evidence_quote": scored["evidence_quote"],
        "evidence_source": scored["source"],
        "rationale": scored["reasoning"],
        "pathway_results": pathway_results,
    }

    # Only one pathway ever feeds the actual score — SINGLE_SOURCE whenever a
    # score exists, per the cross-verification rule; SEARCH_INCONCLUSIVE when
    # nothing was found at all.
    confidence_tag = "SEARCH_INCONCLUSIVE" if scored["score"] is None else "SINGLE_SOURCE"

    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


_A2C_SCHEMA_VERSION = 2  # v2: fixed _sentences() splitting mid-phrase terms across PDF line-wraps


def compute_a2c_cost_leadership_moat(symbol, name=None, description="", market_cap_cr=None, force=False):
    """A.2.C ("2C" in the sheet) — Cost leadership moat: 0-5 score combining
    a QUANT proxy (operating margin vs the peer set, identical Peer Set
    Protocol as the main A.2 Moat row, reusing
    tools/moat_peer_scoring.score_quant_pillars's `opm_level` pillar — never
    text-scanned) with a QUALITATIVE requirement that CRISIL/ICRA or the AR
    MD&A NAME the source of the cost advantage (scale, captive input,
    proprietary technology) — a margin lead alone, with no stated reason,
    scores lower per the rubric (see tools/moat_cost_leadership_scoring.py).

    Sources, PRIMARY-first for the qualitative leg (same ordering as A.2.B):
    Annual Report MD&A (AR-13) is PRIMARY, CRISIL/ICRA rationale (PORTAL-07)
    is SECONDARY. The peer cost-structure comparison (PEER-01) is the quant
    leg, sourced via the same fixed-universe/market-cap-band protocol used
    by the main A.2 Moat row (tools/peer_universe.py) — never re-derived
    here. Earnings call — NOT_CHECKED this run, same reason as A.2.A/A.2.B.

    Deliberately deterministic for the qualitative leg (no LLM), same
    rationale as A.2.A/A.2.B: reproducible, auditable, avoids the shared
    Groq/OpenRouter quota for the 2,409-company bulk pass.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "A.2.C"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None and cached.get("schema_version") == _A2C_SCHEMA_VERSION:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    from tools.crisil_scraper import fetch_crisil_rationale
    from tools.moat_cost_leadership_scoring import score_cost_leadership_moat
    from tools.annual_report_financials import fetch_cost_leadership_evidence_from_annual_report
    from tools.moat_peer_scoring import score_quant_pillars

    crisil_result = fetch_crisil_rationale(name or sym, symbol=sym)
    crisil_text = crisil_result.get("key_rating_drivers", "") if crisil_result.get("result") == "CHECKED" else ""

    try:
        ar_evidence = fetch_cost_leadership_evidence_from_annual_report(sym, name)
    except Exception as e:
        print(f"[qualitative_engine] A.2.C AR cost-leadership evidence fetch failed for {sym}: {e}")
        ar_evidence = {"error": str(e)}
    ar_excerpts = ar_evidence.get("excerpts") or []
    ar_mdna_text = "\n".join(e["text"] for e in ar_excerpts)

    # Quant leg — same peer-set machinery as the main A.2 composite, not
    # re-derived: just pull the `opm_level` pillar's percentile.
    try:
        quant = score_quant_pillars(sym, market_cap_cr=market_cap_cr)
    except Exception as e:
        print(f"[qualitative_engine] A.2.C peer OPM lookup failed for {sym}: {e}")
        quant = {"status": "ERROR", "pillars": []}
    opm_pillar = next((p for p in (quant.get("pillars") or []) if p.get("key") == "opm_level"), None)
    opm_percentile = opm_pillar.get("percentile") if opm_pillar else None
    peer_status = quant.get("status")

    scored = score_cost_leadership_moat(
        ar_mdna_text=ar_mdna_text, crisil_text=crisil_text, business_description=description or "",
        opm_percentile=opm_percentile,
    )

    if ar_excerpts:
        ar13_result, ar13_note = "CHECKED", None
    elif "error" in ar_evidence:
        ar13_result, ar13_note = "NOT_DISCLOSED", ar_evidence["error"]
    else:
        ar13_result, ar13_note = "NOT_DISCLOSED", "Annual Report fetched but no named cost-advantage source located in its MD&A/Business Overview text."

    pathway_results = [
        {
            "pathway_id": "AR-13", "source": "Annual Report MD&A (Business Overview) — PRIMARY (qualitative)",
            "result": ar13_result, "note": ar13_note,
        },
        {
            "pathway_id": "PORTAL-07", "source": "CRISIL/ICRA Rating Rationale — SECONDARY (qualitative)",
            "result": "CHECKED" if crisil_text else crisil_result.get("result", "NOT_DISCLOSED"),
            "note": crisil_result.get("note") if crisil_result.get("result") != "CHECKED" else
                    f"Rated {crisil_result.get('rating')}, {crisil_result.get('rationale_date')}.",
        },
        {
            "pathway_id": "PEER-01", "source": "Peer operating-margin comparison (quant proxy)",
            "result": "CHECKED" if opm_percentile is not None else peer_status,
            "note": None if opm_percentile is not None else
                    f"Peer Set Protocol status: {peer_status}." if peer_status else "Operating-margin history unavailable.",
        },
        {
            "pathway_id": "QUAL-01", "source": "Earnings call commentary",
            "result": "NOT_CHECKED",
            "note": "Deliberately skipped — this codebase's earnings-call digest itself requires an "
                    "LLM call, which this deterministic sub-point avoids by design.",
        },
    ]

    payload = {
        "subpoint_id": subpoint_id,
        "schema_version": _A2C_SCHEMA_VERSION,
        "title": "Cost Leadership",
        "available": True,
        "score": scored["score"],
        "categories_covered": scored["categories_covered"],
        "numeric_anchor": scored["numeric_anchor"],
        "evidence_quote": scored["evidence_quote"],
        "evidence_source": scored["source"],
        "opm_percentile": opm_percentile,
        "rationale": scored["reasoning"],
        "pathway_results": pathway_results,
    }

    # A score built from BOTH a named qualitative source AND a supporting
    # quant percentile is the only case genuinely corroborated by two
    # independent legs — everything else (named-source-only, or
    # margin-lead-only) is a single pathway feeding the score.
    if scored["score"] is None:
        confidence_tag = "SEARCH_INCONCLUSIVE"
    elif (scored["source"] not in ("none", "peer margin comparison (quant only)")
          and opm_percentile is not None and opm_percentile > 50):
        # A named qualitative source (AR/CRISIL) whose claim is ALSO backed
        # by an actual above-average peer-relative margin — two independent
        # legs genuinely corroborating each other, not just one pathway
        # feeding the score.
        confidence_tag = "VERIFIED"
    else:
        confidence_tag = "SINGLE_SOURCE"

    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


# v2: dropped bare "platform"/"ecosystem" from the applicability gate —
# confirmed (HGINFRA) they matched generic corporate boilerplate ("SAP
# S/4HANA Enterprise platform") with zero marketplace meaning, making
# nearly every non-platform company incorrectly "applicable". Bumped so
# every already-cached company re-evaluates under the tightened gate.
# v4: fixed _sentences() splitting mid-phrase terms across PDF line-wraps
# v5: added "network of merchants"/"merchant engagement"/"expanding customer
# base" anchors — confirmed false-negative N/A on RELIANCE, whose AR
# genuinely describes JioMart Digital (a real platform business connecting a
# merchant network to a growing customer base) but used retail-tech
# vocabulary none of the v4 anchors matched, so the whole factor wrongly
# fell through to Not Applicable instead of a real (if presence-only) score.
# v6: max_excerpts raised 8->20 in the AR fetcher — the new v5 anchors alone
# weren't enough on RELIANCE because 8 pages of digit-dense "transaction
# value" RPT-boilerplate false positives filled the entire default excerpt
# cap before the genuine "network of merchants" sentence was ever reached.
# v7: max_per_page raised 1->3 — the default of 1 excerpt/page was still
# discarding "network of merchants" in favour of a same-page, higher-
# digit-scoring "merchant engagement" sentence 30-40 words later.
_A2D_SCHEMA_VERSION = 7


def compute_a2d_network_effects_moat(symbol, name=None, description="", force=False):
    """A.2.D ("2D" in the sheet) — Network effects moat: 0-5 score, or "N/A"
    for a business with no platform/marketplace element at all (see
    tools/moat_network_effects_scoring.py — N/A is NOT a low score, it means
    the factor doesn't apply to this business model).

    Requires an actual GROWTH-LINKAGE figure (a value metric like GMV/
    transaction value tracked AGAINST a user/seller/buyer-base metric) — mere
    platform/marketplace existence is explicitly insufficient per the spec.

    Sources: Annual Report MD&A (AR-13) is PRIMARY. Industry reports
    (INDUSTRY-01) are SECONDARY per the spec but have no fetcher wired in
    this codebase yet — recorded as NOT_CHECKED, not NOT_DISCLOSED, since it
    was never attempted (never silently skipped without saying so).
    Management commentary/investor presentation is approximated via the
    business description, same AR-13-adjacent proxy convention used
    elsewhere, capped at MANAGEMENT_CLAIM tier. Earnings call — NOT_CHECKED,
    same reason as A.2.A-C (the only digest tool requires an LLM call).

    Deliberately deterministic (no LLM), same rationale as the other A.2.x
    factors.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "A.2.D"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None and cached.get("schema_version") == _A2D_SCHEMA_VERSION:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    from tools.moat_network_effects_scoring import score_network_effects_moat
    from tools.annual_report_financials import fetch_network_effects_evidence_from_annual_report

    try:
        ar_evidence = fetch_network_effects_evidence_from_annual_report(sym, name)
    except Exception as e:
        print(f"[qualitative_engine] A.2.D AR network-effects evidence fetch failed for {sym}: {e}")
        ar_evidence = {"error": str(e)}
    ar_excerpts = ar_evidence.get("excerpts") or []
    ar_mdna_text = "\n".join(e["text"] for e in ar_excerpts)

    scored = score_network_effects_moat(ar_mdna_text=ar_mdna_text, business_description=description or "")

    if ar_excerpts:
        ar13_result, ar13_note = "CHECKED", None
    elif "error" in ar_evidence:
        ar13_result, ar13_note = "NOT_DISCLOSED", ar_evidence["error"]
    else:
        ar13_result, ar13_note = "NOT_DISCLOSED", "Annual Report fetched but no platform/network-effects language located in its MD&A/Business Overview text."

    pathway_results = [
        {
            "pathway_id": "AR-13", "source": "Annual Report MD&A (Business Overview) — PRIMARY",
            "result": ar13_result, "note": ar13_note,
        },
        {
            "pathway_id": "INDUSTRY-01", "source": "Industry reports — SECONDARY",
            "result": "NOT_CHECKED",
            "note": "No industry-report source is wired into this codebase yet — never silently skipped without saying so.",
        },
        {
            "pathway_id": "QUAL-01", "source": "Earnings call commentary",
            "result": "NOT_CHECKED",
            "note": "Deliberately skipped — this codebase's earnings-call digest itself requires an "
                    "LLM call, which this deterministic sub-point avoids by design.",
        },
    ]

    payload = {
        "subpoint_id": subpoint_id,
        "schema_version": _A2D_SCHEMA_VERSION,
        "title": "Network Effects",
        "available": True,
        "applicable": scored["applicable"],
        "score": scored["score"],
        "categories_covered": scored["categories_covered"],
        "numeric_anchor": scored["numeric_anchor"],
        "evidence_quote": scored["evidence_quote"],
        "evidence_source": scored["source"],
        "rationale": scored["reasoning"],
        "pathway_results": pathway_results,
    }

    if not scored["applicable"]:
        confidence_tag = "NOT_APPLICABLE"
    elif scored["score"] is None:
        confidence_tag = "SEARCH_INCONCLUSIVE"
    else:
        confidence_tag = "SINGLE_SOURCE"

    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


# v2: added "persistency ratio" (the insurance-sector term of art for a
# renewal rate) — confirmed HDFCLIFE had real, disclosed renewal-equivalent
# data that "renewal rate" alone missed entirely. Bumped so cached
# insurers reclassify under the corrected anchors.
_A2E_SCHEMA_VERSION = 2


def compute_a2e_switching_costs_moat(symbol, name=None, description="", force=False):
    """A.2.E ("2E" in the sheet) — Switching costs moat: 0-5 score based on
    contract lock-in term length, renewal rate, and regulatory/certification
    switching barriers (see tools/moat_switching_costs_scoring.py). The 5/5
    tier specifically requires BOTH a contract-term length AND a
    renewal-rate percentage cited together — either alone caps at 4.

    Sources: CRISIL/ICRA rationale (PORTAL-07) and Annual Report MD&A
    (AR-13) are BOTH PRIMARY per spec — whichever has the stronger evidence
    wins, neither is ordered ahead of the other. SECONDARY is the Ind AS 115
    revenue-recognition note's contract-balance/performance-obligation
    disclosures (CONTRACT-01), approximated by scanning the same AR text for
    its characteristic phrasing rather than parsing the note's structured
    table — consistent with every other A.2.x factor's text-anchor approach.
    Earnings call — NOT_CHECKED, same reason as A.2.A-D (the only digest
    tool requires an LLM call).

    Deliberately deterministic (no LLM), same rationale as the other A.2.x
    factors.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "A.2.E"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None and cached.get("schema_version") == _A2E_SCHEMA_VERSION:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    from tools.crisil_scraper import fetch_crisil_rationale
    from tools.moat_switching_costs_scoring import score_switching_costs_moat
    from tools.annual_report_financials import fetch_switching_costs_evidence_from_annual_report

    crisil_result = fetch_crisil_rationale(name or sym, symbol=sym)
    crisil_text = crisil_result.get("key_rating_drivers", "") if crisil_result.get("result") == "CHECKED" else ""

    try:
        ar_evidence = fetch_switching_costs_evidence_from_annual_report(sym, name)
    except Exception as e:
        print(f"[qualitative_engine] A.2.E AR switching-costs evidence fetch failed for {sym}: {e}")
        ar_evidence = {"error": str(e)}
    ar_excerpts = ar_evidence.get("excerpts") or []
    ar_mdna_text = "\n".join(e["text"] for e in ar_excerpts)

    scored = score_switching_costs_moat(ar_mdna_text=ar_mdna_text, crisil_text=crisil_text, business_description=description or "")

    if ar_excerpts:
        ar13_result, ar13_note = "CHECKED", None
    elif "error" in ar_evidence:
        ar13_result, ar13_note = "NOT_DISCLOSED", ar_evidence["error"]
    else:
        ar13_result, ar13_note = "NOT_DISCLOSED", "Annual Report fetched but no contract-term/renewal/switching-cost language located in its MD&A/Business Overview text."

    pathway_results = [
        {
            "pathway_id": "AR-13", "source": "Annual Report MD&A — PRIMARY",
            "result": ar13_result, "note": ar13_note,
        },
        {
            "pathway_id": "PORTAL-07", "source": "CRISIL/ICRA Rating Rationale — PRIMARY",
            "result": "CHECKED" if crisil_text else crisil_result.get("result", "NOT_DISCLOSED"),
            "note": crisil_result.get("note") if crisil_result.get("result") != "CHECKED" else
                    f"Rated {crisil_result.get('rating')}, {crisil_result.get('rationale_date')}.",
        },
        {
            "pathway_id": "CONTRACT-01", "source": "Ind AS 115 revenue-recognition note — SECONDARY",
            "result": "CHECKED" if ar_excerpts else "NOT_DISCLOSED",
            "note": None if ar_excerpts else "Approximated via the same AR MD&A text scan (no dedicated note-table parser); nothing located.",
        },
        {
            "pathway_id": "QUAL-01", "source": "Earnings call commentary",
            "result": "NOT_CHECKED",
            "note": "Deliberately skipped — this codebase's earnings-call digest itself requires an "
                    "LLM call, which this deterministic sub-point avoids by design.",
        },
    ]

    payload = {
        "subpoint_id": subpoint_id,
        "schema_version": _A2E_SCHEMA_VERSION,
        "title": "Switching Costs",
        "available": True,
        "score": scored["score"],
        "categories_covered": scored["categories_covered"],
        "numeric_anchor": scored["numeric_anchor"],
        "evidence_quote": scored["evidence_quote"],
        "evidence_source": scored["source"],
        "rationale": scored["reasoning"],
        "pathway_results": pathway_results,
    }

    confidence_tag = "SEARCH_INCONCLUSIVE" if scored["score"] is None else "SINGLE_SOURCE"

    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def _fetch_company_growth_and_margin(sym):
    """Company-level 3yr revenue CAGR + chronological EBITDA-margin history
    for A.4's single-segment fallback and its Commoditisation margin leg.
    Reuses the SAME live yfinance-backed pipeline as the main research run
    (tools/angel_scraper.AngelDataScraper -> tools/metrics_engine's F-05/F-06)
    rather than a second hand-rolled fetch — fast/live, not an AR PDF fetch.
    Returns (cagr_3y_revenue: float|None, margins_annual: list). Never
    raises; an empty/failed fetch returns (None, [])."""
    try:
        from tools.angel_scraper import AngelDataScraper
        from tools.metrics_engine import FundamentalMetricsEngine
        raw_data = AngelDataScraper().fetch_fundamental_payload(sym)
        metrics = FundamentalMetricsEngine.calculate_all_metrics(raw_data)
        growth = metrics.get("F-05_Growth_Summary") or {}
        margin = metrics.get("F-06_Margin_Analysis") or {}
        return growth.get("cagr_3y_revenue"), (margin.get("margins_annual") or [])
    except Exception as e:
        print(f"[qualitative_engine] A.4 company-level growth/margin fetch failed for {sym}: {e}")
        return None, []


_LIFECYCLE_STAGE_LABEL = {
    "growth": "Growth", "maturity": "Maturity",
    "commoditisation": "Commoditisation", "decline": "Decline / obsolescence risk",
}

# v1: initial deterministic rewrite (replaces the old LLM-narrative stub,
# which had no schema_version key at all — old payloads are correctly
# treated as a cache miss).
# v2: company_margin_trend_compressing now excludes the trailing "TTM" entry
# from margins_annual before applying the N-year lookback (see that
# function's docstring) — confirmed on RELIANCE, the lookback previously
# landed on FY2024 instead of FY2023 because TTM occupied the "latest" slot.
_A4_SCHEMA_VERSION = 2


def compute_a4_product_lifecycle_stage(symbol, name=None, description="", force=False):
    """A.4 — Product lifecycle stage: growth, maturity, commoditisation,
    obsolescence risk. Formula: Relative growth = Segment revenue CAGR -
    Sector-median revenue CAGR (see tools/sector_cagr_universe.py).

    Sourcing Sequence: AR-14 (multi-year revenue/segment note, via
    tools.annual_report_financials.fetch_multi_year_segment_revenue) ->
    SECTOR-CAGR-01 (this company's own NSE sector's peer-median 3yr revenue
    CAGR, via tools.sector_cagr_universe) -> PORTAL-07 (rating-agency
    rationale) -> QUAL-01 (news/analyst commentary), both NOT_CHECKED — no
    fetcher for either is wired into this codebase.

    Deliberately deterministic (no LLM), same rationale as A.2.x/A.3 — see
    tools/product_lifecycle_scoring.py for the segment classifier itself.

    IMPORTANT — a diversified company must NEVER get a single-word lifecycle
    label. (Institutional knowledge carried over from the old LLM-stub
    version of this function, which discovered this the hard way: "Reliance
    mismatch found 1-Aug-2026" — a single-word "Growth"/"Maturity" label for
    a genuinely multi-segment conglomerate like Reliance is actively
    misleading, since different segments can be in completely different
    lifecycle stages at once.) This version enforces that by construction:
    when 2+ segments are classified, the payload's `blend_summary` is always
    a revenue-weighted composite string (e.g. "Mature core (62.3% of
    revenue) + Growth segments (28.1% of revenue)"), never collapsed to one
    word — only a genuinely single-segment company gets a single-stage
    summary.

    DOCUMENTED SCOPING LIMITATIONS (surfaced in the payload, not hidden):
      - Sector benchmark is COMPANY-level (this company's one NSE sector's
        peer-median CAGR), applied to every segment — not a genuine
        per-segment sector reclassification (this codebase has no
        segment-level sector taxonomy).
      - Commoditisation's margin-compression leg uses the COMPANY-LEVEL
        EBITDA margin trend, not true segment-level margin (not extractable
        from this codebase's AR parsing today).
      - Segment CAGR requires the SAME normalized segment label to appear in
        both the oldest and newest fetched Annual Report years — a company
        that renamed/restructured a segment mid-window shows that segment
        as unclassified (`unclassified_pct`), never a guessed CAGR.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "A.4"
    title = "Product lifecycle stage: growth, maturity, commoditisation, obsolescence risk"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None and cached.get("schema_version") == _A4_SCHEMA_VERSION:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    from tools.product_lifecycle_scoring import (
        classify_segment_lifecycle_stage, company_margin_trend_compressing,
        compute_segment_cagr_from_multi_year, normalize_segment_label,
    )
    from tools.annual_report_financials import fetch_multi_year_segment_revenue
    from tools.nse_sector_map import get_nse_sector
    from tools.sector_cagr_universe import get_sector_median_cagr

    pathway_results = []

    # --- AR-14: multi-year segment revenue (own-company CAGR input) -------
    try:
        multi_year_segments = fetch_multi_year_segment_revenue(sym, name, n_years=4)
    except Exception as e:
        print(f"[qualitative_engine] A.4 multi-year segment fetch failed for {sym}: {e}")
        multi_year_segments = {}
    segment_cagrs = compute_segment_cagr_from_multi_year(multi_year_segments)
    ar14_checked = bool(multi_year_segments)
    pathway_results.append({
        "pathway_id": "AR-14",
        "source": "Revenue/segment note — multi-year Annual Report segment revenue",
        "result": "CHECKED" if ar14_checked else "NOT_DISCLOSED",
        "note": None if ar14_checked else "No Annual Report segment note reconciled for any of the latest fiscal years on file.",
    })

    # --- SECTOR-CAGR-01: this company's sector peer-median CAGR -----------
    sector = get_nse_sector(sym)
    sector_result = get_sector_median_cagr(sector) if sector else {
        "status": "NOT_IN_UNIVERSE", "reason": f"{sym} has no NSE sector tag in the fixed universe.",
    }
    sector_median_cagr = sector_result.get("median_cagr") if sector_result.get("status") == "OK" else None
    pathway_results.append({
        "pathway_id": "SECTOR-CAGR-01",
        "source": "Sector-median 3yr revenue CAGR (fixed NSE sector universe, tools/sector_cagr_universe.py)",
        "result": "CHECKED" if sector_median_cagr is not None else sector_result.get("status", "NOT_DISCLOSED"),
        "note": sector_result.get("reason"),
    })
    pathway_results.append({
        "pathway_id": "PORTAL-07",
        "source": "Rating Agency Rationale (CRISIL/ICRA/CARE) — industry growth context",
        "result": "NOT_CHECKED",
        "note": "No rating-agency rationale fetcher is wired into this codebase yet.",
    })
    pathway_results.append({
        "pathway_id": "QUAL-01",
        "source": "News / analyst research (Moneycontrol etc, corroborative only)",
        "result": "NOT_CHECKED",
        "note": "Corroborative-only pathway — not invoked this run.",
    })

    # --- Company-level revenue CAGR + margin trend (fallback + Commoditisation leg) ---
    company_cagr, margins_annual = _fetch_company_growth_and_margin(sym)
    margin_trend = company_margin_trend_compressing(margins_annual)

    # --- Segment revenue weights (latest year), same AR-14 fetch A.1/A.3 reuse ---
    segments_pct, segments_fy = _fetch_segment_revenue_context(sym, name)

    classified_segments = []
    if segments_pct and len(segments_pct) >= 2:
        norm_cagr_lookup = {normalize_segment_label(lbl): v for lbl, v in segment_cagrs.items()}
        for s in segments_pct:
            entry = norm_cagr_lookup.get(normalize_segment_label(s["label"]))
            seg_cagr = entry.get("cagr") if entry else None
            result = classify_segment_lifecycle_stage(seg_cagr, sector_median_cagr, margin_trend)
            classified_segments.append({
                "label": s["label"],
                "share_pct": s["pct"],
                "segment_cagr": seg_cagr,
                "stage": result["stage"],
                "stage_label": _LIFECYCLE_STAGE_LABEL.get(result["stage"]),
                "relative_growth_pct": result["relative_growth_pct"],
                "reasoning": result["reasoning"],
                "matched_across_years": bool(entry and entry.get("matched_across_years")),
            })
    elif company_cagr is not None:
        # Single-segment (or no reconciled segment note) company — classify
        # at company level directly, as ONE 100%-weight "segment" so the
        # same blend machinery below still applies uniformly.
        result = classify_segment_lifecycle_stage(company_cagr, sector_median_cagr, margin_trend)
        classified_segments.append({
            "label": "Company (single-segment)",
            "share_pct": 100.0,
            "segment_cagr": company_cagr,
            "stage": result["stage"],
            "stage_label": _LIFECYCLE_STAGE_LABEL.get(result["stage"]),
            "relative_growth_pct": result["relative_growth_pct"],
            "reasoning": result["reasoning"],
            "matched_across_years": None,
        })

    stage_weight = {}
    unclassified_pct = 0.0
    for seg in classified_segments:
        if seg["stage"] is None:
            unclassified_pct += seg["share_pct"]
        else:
            stage_weight[seg["stage"]] = stage_weight.get(seg["stage"], 0.0) + seg["share_pct"]
    unclassified_pct = round(unclassified_pct, 1)

    # Company-level blend string — NEVER a single word once there are 2+
    # segments (see docstring's "Reliance mismatch" note). A genuinely
    # single-segment company naturally produces a one-term blend, which is
    # correct (there is nothing to diversify across), not a violation of
    # the rule.
    blend_parts = []
    for stg in ("growth", "maturity", "commoditisation", "decline"):
        w = round(stage_weight.get(stg, 0.0), 1)
        if w > 0.05:
            label = "Mature core" if stg == "maturity" else f"{_LIFECYCLE_STAGE_LABEL[stg]} segments"
            blend_parts.append(f"{label} ({w}% of revenue)")
    if unclassified_pct > 0.05:
        blend_parts.append(f"Unclassified ({unclassified_pct}% of revenue — segment label not matched across fiscal years, or CAGR/sector-median unavailable)")
    blend_summary = " + ".join(blend_parts) if blend_parts else None

    available = bool(classified_segments)
    if not available:
        payload = {
            "subpoint_id": subpoint_id,
            "schema_version": _A4_SCHEMA_VERSION,
            "title": title,
            "available": False,
            "reason": "No multi-year segment revenue note and no company-level revenue CAGR could be computed.",
            "pathway_results": pathway_results,
            "relative_growth_pct": None,
        }
        write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    # Rationale sentence for the card's "finding" field — deterministic,
    # built from the same classified data, never LLM-authored.
    if blend_parts:
        rationale = f"{sym}: {blend_summary}."
        if sector_median_cagr is not None:
            rationale += f" Benchmarked against sector '{sector}' peer-median 3yr revenue CAGR of {sector_median_cagr * 100:.1f}%."
        else:
            rationale += f" Sector-median CAGR benchmark unavailable ({sector_result.get('status')}) — classification limited to what the Decline (negative-CAGR) check alone could determine."
    else:
        rationale = "Segment revenue history was found but none could be classified — see 'unclassified_pct' and per-segment reasoning."

    confidence_tag = "SINGLE_SOURCE" if any(s["stage"] is not None for s in classified_segments) else "SEARCH_INCONCLUSIVE"

    payload = {
        "subpoint_id": subpoint_id,
        "schema_version": _A4_SCHEMA_VERSION,
        "title": title,
        "available": True,
        "segments": classified_segments,
        "unclassified_pct": unclassified_pct,
        "blend_summary": blend_summary,
        "sector": sector,
        "sector_median_cagr_pct": round(sector_median_cagr * 100, 2) if sector_median_cagr is not None else None,
        "sector_benchmark_status": sector_result.get("status"),
        "company_margin_trend_compressing": (margin_trend or {}).get("compressing") if margin_trend else None,
        "segment_fiscal_year": segments_fy,
        "relative_growth_pct": (classified_segments[0]["relative_growth_pct"]
                                 if len(classified_segments) == 1 else None),
        "rationale": rationale,
        "limitations": [
            "Sector benchmark is company-level (this company's own single NSE sector's peer-median CAGR), "
            "applied uniformly to every segment — not a genuine per-segment sector reclassification.",
            "Commoditisation's margin-compression check uses the company-level EBITDA margin trend, not "
            "true segment-level margin.",
        ],
        "pathway_results": pathway_results,
    }
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


# v2: full deterministic rewrite (replaces the old pure-LLM-guess stub).
# v3: pricing_realisation_extractor's quote-verification guardrail tightened
# (whitespace-normalized FULL quote match instead of a 40-char prefix check)
# — bumped so a v2 A.5 payload built on the weaker guardrail is never served
# as current.
_A5_SCHEMA_VERSION = 3


def compute_a5_pricing_power(symbol, name=None, description="", force=False):
    """A.5 — Pricing power: ability to raise prices without losing customers;
    pass-through of cost inflation. Formula: Price pass-through ratio = Change in
    realisation % / Change in input cost %.

    Sourcing Sequence: QUAL-02 (concall transcripts, realisation/volume numeric
    extraction — tools.pricing_realisation_extractor) -> NICHE-14 (MCX/LME
    commodity input-cost index, FRED proxy — tools.commodity_price_fetcher) ->
    AR-13 (MD&A narrative, LLM narrative fallback ONLY when the ratio genuinely
    can't be computed) -> AGG-01 (fallback/cross-check only, not invoked).

    Deliberately deterministic for the CLASSIFICATION itself (see
    tools/pricing_power_scoring.py) — same rationale as A.2.x/A.3/A.4: a
    pricing-power label built on a bare LLM guess is exactly the anti-pattern
    the spec's own guardrail #23 forbids ("if the pass-through ratio cannot be
    computed, the result MUST be Insufficient Data — never default to
    Moderate"). The ONLY LLM call in this pipeline is the upstream
    realisation/volume NUMBER extraction (tools.pricing_realisation_extractor),
    and even that is gated by a numeric-anchor-in-quote guardrail — every
    accepted number carries a verbatim transcript quote. A short LLM-authored
    narrative is still produced as a clearly-labeled qualitative supplement
    (never blended into the rating itself), using AR-13/QUAL-02 context, same
    SINGLE_SOURCE-at-most convention as before.

    DOCUMENTED SCOPING LIMITATIONS (surfaced in the payload, not hidden):
      - NICHE-14 is a FRED-published IMF commodity price INDEX used as an
        explicitly-labeled PROXY for MCX/LME — neither offers a free,
        programmatic, historical spot-price feed (see
        tools/commodity_price_fetcher.py's module docstring). Every source
        field referencing it says so; never claim it's literally MCX/LME.
      - The company->commodity mapping is a static, sector-level lookup
        (tools/commodity_price_fetcher.py's `_SECTOR_COMMODITY_MAP`), generic
        across every company in a sector — a company with no mapped sector, or
        a sector this pass didn't map, honestly gets Insufficient Data for 5B
        rather than a guessed commodity.
      - 5A (realisation/volume) requires a transcript to have EXPLICITLY
        stated numbers with a verbatim quote; quarters without one are simply
        absent from the trend, never guessed.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "A.5"
    title = "Pricing power: ability to raise prices without losing customers; pass-through of cost inflation"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None and cached.get("schema_version") == _A5_SCHEMA_VERSION:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    from tools.pricing_power_scoring import classify_pricing_power, compute_pass_through_ratio
    from tools.pricing_realisation_extractor import extract_realisation_volume_series
    from tools.commodity_price_fetcher import get_company_commodity, fetch_commodity_price_series
    from tools.nse_sector_map import get_nse_sector

    pathway_results = []

    # --- QUAL-02: realisation/volume numeric extraction (5A) ---------------
    try:
        rv_result = extract_realisation_volume_series(sym, name)
    except Exception as e:
        print(f"[qualitative_engine] A.5 realisation/volume extraction failed for {sym}: {e}")
        rv_result = {"status": "NOT_DISCLOSED", "quarters": [], "reason": str(e)}
    rv_quarters = rv_result.get("quarters") or []
    qual02_checked = rv_result.get("status") == "OK"
    pathway_results.append({
        "pathway_id": "QUAL-02",
        "source": "Concall Transcript — realisation/volume numeric extraction (verbatim-quote-anchored)",
        "result": "CHECKED" if qual02_checked else "NOT_DISCLOSED",
        "note": rv_result.get("reason"),
    })

    # --- NICHE-14: MCX/LME-proxy commodity input-cost index (5B) -----------
    sector = get_nse_sector(sym)
    commodity = get_company_commodity(sym, sector)
    commodity_series_result = None
    if commodity:
        try:
            commodity_series_result = fetch_commodity_price_series(commodity["fred_series_id"])
        except Exception as e:
            print(f"[qualitative_engine] A.5 commodity fetch failed for {sym}: {e}")
            commodity_series_result = {"status": "ERROR", "reason": str(e)}
    niche14_checked = bool(commodity_series_result and commodity_series_result.get("status") == "OK")
    if not commodity:
        niche14_note = (f"No commodity mapping for sector '{sector}'." if sector
                         else f"{sym} has no NSE sector tag in the fixed universe — cannot infer an input commodity.")
    elif not niche14_checked:
        niche14_note = commodity_series_result.get("reason") if commodity_series_result else "Fetch did not run."
    else:
        niche14_note = None
    pathway_results.append({
        "pathway_id": "NICHE-14",
        "source": commodity_series_result.get("source") if niche14_checked else "MCX / LME — commodity input-cost index (FRED proxy; no free historical MCX/LME feed exists)",
        "result": "CHECKED" if niche14_checked else "NOT_IN_UNIVERSE" if not commodity else "NOT_DISCLOSED",
        "note": niche14_note,
        "commodity_name": commodity.get("commodity_name") if commodity else None,
    })

    # --- AR-13 / AGG-01: narrative context (fallback-only, see docstring) --
    digest = _concall_digest(sym, name)
    ar13_checked = bool(description)
    pathway_results.append({
        "pathway_id": "AR-13",
        "source": "MD&A narrative (business description proxy) — narrative supplement only, never feeds the rating",
        "result": "CHECKED" if ar13_checked else "NOT_DISCLOSED",
    })
    pathway_results.append({
        "pathway_id": "AGG-01",
        "source": "Screener.in (fallback/cross-check only)",
        "result": "NOT_CHECKED",
        "note": "Cross-check pathway, only used if primary is unavailable or conflicting — not invoked this run.",
    })

    # --- 5A confirmation + 5B pass-through ratio (both deterministic) ------
    realisation_change_pct = None
    input_cost_change_pct = None
    pass_through_ratio = None
    if qual02_checked and niche14_checked:
        usable_rv = [q for q in rv_quarters if q.get("realisation_per_unit") is not None]
        if len(usable_rv) >= 2:
            r0, r1 = usable_rv[0]["realisation_per_unit"], usable_rv[-1]["realisation_per_unit"]
            if r0:
                realisation_change_pct = round((r1 - r0) / r0 * 100, 2)
            # Align the commodity series to the SAME quarter window. Concall
            # dates come from screener_scraper as "Mon YYYY" (e.g. "Feb 2026"),
            # NOT the FRED series' ISO "YYYY-MM-DD" — a raw string compare
            # between the two formats would silently misalign every lookup
            # (e.g. "Feb 2026" > "2026-01-01" lexicographically is FALSE even
            # though Feb 2026 is chronologically later), so convert to ISO
            # first rather than comparing the raw strings.
            series = commodity_series_result["series"]
            start_iso = _concall_date_to_iso(usable_rv[0].get("date"))
            end_iso = _concall_date_to_iso(usable_rv[-1].get("date"))
            windowed = [p for p in series if (not start_iso or p["date"] <= start_iso)] or series[:1]
            windowed_end = [p for p in series if (not end_iso or p["date"] <= end_iso)] or series[-1:]
            c0 = windowed[-1]["value"] if windowed else None
            c1 = windowed_end[-1]["value"] if windowed_end else None
            if c0 and c1:
                input_cost_change_pct = round((c1 - c0) / c0 * 100, 2)
        pass_through_ratio = compute_pass_through_ratio(realisation_change_pct, input_cost_change_pct)

    classification = classify_pricing_power(rv_quarters, pass_through_ratio)
    pricing_power_rating = classification["pricing_power_rating"]

    # --- Optional narrative supplement (LLM), never overrides the rating ---
    rationale = None
    llm_failed = False
    if ar13_checked or digest:
        company = name or sym
        context = f"COMPANY: {company}\n"
        if description:
            context += f"\nBUSINESS DESCRIPTION (from filings):\n{description[:2500]}\n"
        if digest:
            context += f"\nRECENT EARNINGS-CALL HIGHLIGHTS (newest first):\n{digest}\n"
        prompt = (
            "You are an equity analyst writing a SHORT supplementary narrative on PRICING POWER for an Indian "
            "listed company, using ONLY the grounded context below. Do not invent facts not supported by the "
            "context. This narrative is a supplement to an already-computed quantitative rating — do not assign "
            "your own rating, just describe what the context shows about price hikes taken / realization trends / "
            "cost pass-through commentary in 2-4 sentences.\n\n"
            'Return ONLY JSON: {"narrative": "2-4 sentences"}\n\n'
            f"=== CONTEXT ===\n{context}"
        )
        data, llm_failed = _llm_json(
            sym, "A.5", "You are a precise equity analyst. Reply with strict JSON only. Never fabricate.",
            prompt, max_tokens=400, temperature=0.1,
        )
        rationale = str(data.get("narrative") or "").strip() or None

    if not rationale:
        rationale = classification["reasoning"]

    available = qual02_checked or niche14_checked or ar13_checked
    if not available:
        payload = {
            "subpoint_id": subpoint_id,
            "schema_version": _A5_SCHEMA_VERSION,
            "title": title,
            "available": False,
            "reason": "No concall realisation/volume data, no commodity input-cost series, and no business "
                      "description available to ground any pathway.",
            "pathway_results": pathway_results,
            "price_pass_through_ratio": None,
            "pricing_power_rating": "Insufficient Data",
        }
        write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    confidence_tag = "SINGLE_SOURCE" if (qual02_checked or niche14_checked) else "SEARCH_INCONCLUSIVE"

    payload = {
        "subpoint_id": subpoint_id,
        "schema_version": _A5_SCHEMA_VERSION,
        "title": title,
        "available": True,
        "pricing_power_rating": pricing_power_rating,
        "price_pass_through_ratio": pass_through_ratio,
        "realisation_change_pct": realisation_change_pct,
        "input_cost_change_pct": input_cost_change_pct,
        "commodity_name": commodity.get("commodity_name") if commodity else None,
        "commodity_source": commodity_series_result.get("source") if niche14_checked else None,
        "realisation_volume_quarters": rv_quarters,
        "realisation_volume_confirmation": classification["confirmation"],
        "rationale": rationale,
        "pathway_results": pathway_results,
        "grounded": bool(digest),
        "limitations": [
            "NICHE-14 (input-cost leg) uses FRED's published IMF commodity price index as an explicitly-labeled "
            "PROXY for MCX/LME — neither offers a free, programmatic, historical spot-price feed.",
            "The company->commodity mapping is a static, sector-level lookup (generic across every company in a "
            "sector), not a company-specific input-cost basket.",
            "5A realisation/volume figures only include quarters where a transcript EXPLICITLY stated the number "
            "with a verbatim quote — quarters without one are simply absent from the trend, never guessed.",
        ],
    }
    if not llm_failed:
        write_qualitative(sym, subpoint_id, payload, confidence_tag)
    else:
        print(f"[qualitative_engine] A.5 NOT cached for {sym} — LLM narrative call did not run; will retry next request.")
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_a6_margin_sustainability(symbol, name=None, description="", force=False,
                                      ebitda_margin_series=None, margin_volatility=None):
    """A.6 — Margin sustainability: structurally defensible margins vs temporary
    tailwinds. Formula: Margin volatility = Std dev of EBITDA margin (5Y) / Mean
    EBITDA margin (5Y).

    Sourcing Sequence: AR-10 (one-off items) -> AR-15 (ESG/BRSR) -> PORTAL-01 (get
    the AR PDF) -> AGG-01 (fallback/cross-check only) -> QUAL-02 (concall color).

    Unlike A.1-A.5, the FORMULA here is not an LLM estimate at all: `margin_volatility`
    and `ebitda_margin_series` are computed upstream (agent/stock_agent.py) directly
    from the company's own audited annual/quarterly EBITDA margins (the same
    financial-statement pipeline every Sr 1-92 ratio card uses) and passed in here —
    real numbers, sourced via PORTAL-01 (the AR PDF fetch) and AR-10 (the same filing's
    Exceptional Items line, which is what a real one-off flag should be checked
    against). Only the STRUCTURAL-vs-temporary judgment and the one-off-year flags
    are an LLM call, grounded in the real margin series (not blind guessing) plus
    the concall digest (QUAL-02). AR-15 (ESG/BRSR) has no fetcher wired and isn't
    actually margin-relevant, but is recorded per the Sourcing Sequence rather than
    silently dropped. Even with a real, audited quantitative figure, this stays
    SINGLE_SOURCE — PORTAL-01 and AR-10 both read the SAME annual report (not two
    independent tiers), so the cross-verification rule for VERIFIED isn't met.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "A.6"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    pathway_results = []
    has_series = bool(ebitda_margin_series) and len(ebitda_margin_series) >= 3
    pathway_results.append({
        "pathway_id": "PORTAL-01",
        "source": "BSE Corporate Announcements -> Annual/Quarterly filing PDF",
        "result": "CHECKED" if has_series else "NOT_DISCLOSED",
        "note": None if has_series else "Fewer than 3 years of EBITDA margin history available — cannot compute a meaningful volatility figure.",
    })
    pathway_results.append({
        "pathway_id": "AR-10",
        "source": "Exceptional Items note (one-off P&L flags)",
        "result": "CHECKED" if has_series else "NOT_DISCLOSED",
        "note": "One-off years are flagged by the LLM against the real margin series below, not detected from a structured Exceptional Items extraction — treat flagged years as a lead to verify against the actual AR note, not a citable fact on its own.",
    })
    pathway_results.append({
        "pathway_id": "AR-15",
        "source": "Business Responsibility and Sustainability Report (ESG/BRSR)",
        "result": "NOT_APPLICABLE",
        "note": "ESG/BRSR disclosures are not margin-relevant in practice — listed in the Sourcing Sequence but not queried for this sub-point.",
    })
    pathway_results.append({
        "pathway_id": "AGG-01",
        "source": "Screener.in — 5-8Y margin trend (fallback/cross-check only)",
        "result": "NOT_CHECKED",
        "note": "Cross-check pathway, only used if the primary filing is unavailable or conflicting — not invoked this run.",
    })

    digest = _concall_digest(sym, name)
    pathway_results.append({
        "pathway_id": "QUAL-02",
        "source": "Concall Transcript (grounded digest)",
        "result": "CHECKED" if digest else "NOT_HELD",
        "note": None if digest else "No transcript found for a recent quarter — do not assume one happened unseen.",
    })

    if not has_series:
        payload = {
            "subpoint_id": subpoint_id,
            "title": "Margin sustainability: structurally defensible margins vs temporary tailwinds",
            "available": False,
            "reason": "Fewer than 3 years of audited EBITDA margin history available.",
            "pathway_results": pathway_results,
            "margin_volatility": margin_volatility,
        }
        write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    company = name or sym
    series_txt = "; ".join(f"{r['label']}: {r['value']}%" for r in ebitda_margin_series)
    context = f"COMPANY: {company}\n\nEBITDA MARGIN BY YEAR (real, from audited filings):\n{series_txt}\n"
    if description:
        context += f"\nBUSINESS DESCRIPTION (from filings):\n{description[:1500]}\n"
    if digest:
        context += f"\nRECENT EARNINGS-CALL HIGHLIGHTS (newest first):\n{digest}\n"

    prompt = (
        "You are an equity analyst assessing MARGIN SUSTAINABILITY for an Indian listed company, "
        "using ONLY the real EBITDA margin series and grounded context below. Do not invent facts. "
        "If a year's margin looks like an outlier, you may flag it as a possible one-off — but say so "
        "as a lead to verify, not a confirmed fact, since you have no direct visibility into the "
        "Exceptional Items note itself.\n\n"
        "Return ONLY JSON:\n"
        "{\n"
        '  "structural_defensibility": "Structurally defensible" | "Partially temporary tailwinds" | "Largely temporary tailwinds" | "unclear",\n'
        '  "one_off_flags": ["short flag naming the year/event, e.g. \'FY23: margin spike may be a one-off, verify against Exceptional Items note\' - 0 to 3 items, empty list if none evident"],\n'
        '  "rationale": "2-4 sentences citing the actual margin trend and any concall commentary"\n'
        "}\n\n"
        f"=== CONTEXT ===\n{context}"
    )
    data, llm_failed = _llm_json(
        sym, "A.6", "You are a precise equity analyst. Reply with strict JSON only. Never fabricate.",
        prompt, max_tokens=700, temperature=0.1,
    )

    structural_defensibility = str(data.get("structural_defensibility") or "unclear").strip()
    if structural_defensibility not in ("Structurally defensible", "Partially temporary tailwinds", "Largely temporary tailwinds"):
        structural_defensibility = "unclear"
    one_off_flags = [str(x).strip() for x in (data.get("one_off_flags") or []) if str(x).strip()][:3]
    rationale = str(data.get("rationale") or "").strip()

    confidence_tag = "SINGLE_SOURCE" if rationale else "SEARCH_INCONCLUSIVE"

    payload = {
        "subpoint_id": subpoint_id,
        "title": "Margin sustainability: structurally defensible margins vs temporary tailwinds",
        "available": True,
        "structural_defensibility": structural_defensibility,
        "one_off_flags": one_off_flags,
        "rationale": rationale,
        "margin_volatility": margin_volatility,
        "ebitda_margin_series": ebitda_margin_series,
        "pathway_results": pathway_results,
        "grounded": bool(digest),
    }
    if not llm_failed:
        write_qualitative(sym, subpoint_id, payload, confidence_tag)
    else:
        print(f"[qualitative_engine] A.6 NOT cached for {sym} — LLM call did not run; will retry next request.")
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def _band_score_pct(pct):
    """Shared banding for a 0-100% ratio into a 1-5 score, per the spec's
    fixed thresholds (>=80=5, 65-79=4, 50-64=3, 30-49=2, <30=1). Returns
    None if pct is None (nothing to score)."""
    if pct is None:
        return None
    if pct >= 80:
        return 5
    if pct >= 65:
        return 4
    if pct >= 50:
        return 3
    if pct >= 30:
        return 2
    return 1


_NSE_ANNOUNCEMENTS_GAP = {
    "pathway_id": "PORTAL-02",
    "source": "NSE Corporate Announcements - major initiative announcements, cross-checked against actual outcomes",
    "result": "NOT_WIRED",
    "note": "No NSE corporate-announcements scraper is wired in this codebase yet - initiative/outcome evidence below comes from the Annual Report narrative only, not cross-checked against the original announcement.",
}


def compute_b1_1_past_track_record(symbol, name=None, force=False):
    """B.1.1 - Past successes/failures. Spec formula: Initiative Success Rate
    = Successfully Completed Strategic Initiatives / Total Major Strategic
    Initiatives Announced in Last 5 Years x 100, banded to a 1-5 score.

    Deterministic (no LLM) - see tools/founder_track_record_scoring.py's
    classify_initiatives / classify_initiatives_from_announcements: a
    sentence (or NSE announcement desc/attachment title) must carry both an
    initiative keyword (commissioning/expansion/acquisition/restructuring/
    etc) AND a classifiable outcome keyword (success/delayed/failed/
    ongoing) to count; a sentence naming an initiative with no matched
    outcome is skipped, not guessed. Sourcing: BOTH the Chairman/MD message
    across the last up to 5 Annual Reports (fetch_founder_milestones_multi_
    year, pathway AR-13) AND NSE Corporate Announcements from the same
    5-year window (fetch_announcements, pathway PORTAL-02), merged into one
    initiative list with a same-year/same-initiative-keyword dedup so a
    corporate action narrated in both the AR and its own NSE filing isn't
    double-counted.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.1.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import fetch_founder_milestones_multi_year
        year_texts = fetch_founder_milestones_multi_year(sym, name, n_years=5) or []
    except Exception as e:
        print(f"[qualitative_engine] B.1.1 multi-year AR text fetch failed for {sym}: {e}")
        year_texts = []

    try:
        from tools.nse_announcements import fetch_announcements
        from tools.founder_track_record_scoring import classify_initiatives_from_announcements
        _all_announcements = fetch_announcements(sym) or []
        _cutoff_year = time.localtime().tm_year - 5

        def _an_dt_year(a):
            # an_dt is "DD-Mon-YYYY HH:MM:SS" - the year is the last
            # segment of the DATE part, not the last 4 characters of the
            # whole string (those are seconds/minutes digits).
            try:
                return int(a.get("an_dt", "").split()[0].split("-")[-1])
            except (ValueError, IndexError, AttributeError):
                return None

        _recent_announcements = [a for a in _all_announcements if (_an_dt_year(a) or 0) >= _cutoff_year]
        announcement_initiatives = classify_initiatives_from_announcements(_recent_announcements)
    except Exception as e:
        print(f"[qualitative_engine] B.1.1 NSE announcements cross-check failed for {sym}: {e}")
        announcement_initiatives = []

    pathway_results = [
        {
            "pathway_id": "AR-13",
            "source": "Chairman & MD message across the last 5 Annual Reports",
            "result": "CHECKED" if year_texts else "NOT_DISCLOSED",
            "note": (f"Chairman/MD message located in {len(year_texts)} of the last 5 Annual Reports."
                     if year_texts else "Chairman/MD message section not located in any of the last 5 Annual Reports this run."),
        },
        {
            "pathway_id": "PORTAL-02",
            "source": "NSE Corporate Announcements - major initiative announcements, cross-checked against actual outcomes",
            "result": "CHECKED" if announcement_initiatives else "NOT_DISCLOSED",
            "note": (f"{len(announcement_initiatives)} classifiable initiative announcement(s) with a stated outcome found in the last 5 years of NSE Corporate Announcements."
                     if announcement_initiatives else "No NSE Corporate Announcement in the last 5 years named a major initiative with a classifiable outcome this run."),
        },
    ]
    pdf_url = year_texts[0]["pdf_url"] if year_texts else None

    from tools.founder_track_record_scoring import score_initiative_success_rate
    result = score_initiative_success_rate(year_texts, announcement_initiatives)

    if result["execution_score"] is None:
        if not year_texts and not announcement_initiatives:
            reason = "No Chairman/MD message was located in any of the last 5 Annual Reports, and no NSE Corporate Announcement in the same window named a classifiable initiative, this run."
        else:
            reason = ("The Chairman/MD messages across the last 5 Annual Reports were read and the last 5 years of NSE "
                       "Corporate Announcements were checked, but neither names a major strategic initiative "
                       "(commissioning/expansion/acquisition/restructuring) with a matched outcome keyword - no "
                       "track-record evidence was located this run, not a clean record.")
        payload = {
            "subpoint_id": subpoint_id, "title": "Past successes / failures",
            "available": True, **result,
            "rationale": reason, "pathway_results": pathway_results, "source_pdf_url": pdf_url,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Past successes / failures",
        "available": True, **result,
        "rationale": f"{result['successful_count']} of {len(result['initiatives'])} major strategic initiatives named across the last "
                     f"{len(year_texts)} Annual Report(s) were explicitly described as completed successfully "
                     f"({result['initiative_success_rate_pct']}% -> score {result['execution_score']}/5).",
        "pathway_results": pathway_results, "source_pdf_url": pdf_url,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b1_2_management_tenure(symbol, name=None, force=False):
    """B.1.2 - Management tenure. Spec formula: Average Leadership Tenure =
    (CEO Tenure + CFO Tenure + Executive Director Tenure) / Number of Key
    Executives identified, banded to a 1-5 score.

    Deterministic (no LLM) - see tools/founder_track_record_scoring.py's
    extract_key_executive_tenure: only counts a named CEO/CFO/Managing
    Director/Executive Director with an EXPLICIT appointment date nearby
    ("since <year>" / "w.e.f. <date>" / "appointed ... <year>") - a bare
    "N years of experience" phrase is deliberately NOT used (career
    experience before joining is not company tenure). Sourcing: Corporate
    Governance Report - Board of Directors / KMP section of the latest
    Annual Report. The NSE Corporate Announcements appointment/resignation
    cross-check the spec also calls for has no fetcher wired - see the
    PORTAL-02 gap in pathway_results.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.1.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import fetch_founder_track_record_text
        ft = fetch_founder_track_record_text(sym, name) or {}
    except Exception as e:
        print(f"[qualitative_engine] B.1.2 AR text fetch failed for {sym}: {e}")
        ft = {"error": str(e)}

    tenure_text = ft.get("tenure_text")
    fiscal_year = ft.get("fiscal_year")
    pdf_url = ft.get("pdf_url")
    pathway_results = [
        {
            "pathway_id": "AR-06",
            "source": "Corporate Governance Report - Board of Directors / Key Managerial Personnel",
            "result": "CHECKED" if tenure_text else "NOT_DISCLOSED",
            "note": None if tenure_text else "Director appointment/tenure detail not located in the latest Annual Report PDF this run.",
        },
        {**_NSE_ANNOUNCEMENTS_GAP, "source": "NSE Corporate Announcements - board appointment/resignation announcements, to verify appointment dates"},
    ]

    # STRUCTURAL pass first: reads a real detected table by column/value
    # pattern (tools/ar_table_extractor.py) rather than exact wording in
    # flowing text — this generalizes across companies that disclose the
    # SAME information with different headings/phrasing than the sample
    # filings the regex patterns below were tuned against. Falls back to
    # the regex-window pass only when no table-based match is found (the
    # two strategies catch different, overlapping subsets of companies —
    # confirmed live neither alone covers every filing format).
    result = {"average_tenure_years": None, "tenure_score": None, "executives": []}
    try:
        from tools.ar_table_extractor import extract_tables_near_anchors
        from tools.founder_track_record_scoring import extract_key_executive_tenure_from_tables, score_management_tenure
        anchors = {
            "tenure": ["date of appointment", "appointment", "designation"],
            "roles": ["non-executive director", "independent,", "executive director", "managing director"],
        }
        tabs = extract_tables_near_anchors(sym, name, anchors, fiscal_year=fiscal_year)
        tbl_fy = tabs.get("fiscal_year") or fiscal_year
        if tbl_fy:
            execs = extract_key_executive_tenure_from_tables(tabs.get("tenure", []), tbl_fy, role_tables=tabs.get("roles", []))
            if execs:
                avg = round(sum(e["tenure_years"] for e in execs) / len(execs), 1)
                score = 5 if avg > 10 else 4 if avg >= 7 else 3 if avg >= 4 else 2 if avg >= 2 else 1
                result = {"average_tenure_years": avg, "tenure_score": score, "executives": execs}
                pathway_results.insert(0, {
                    "pathway_id": "AR-06-TABLE",
                    "source": "Corporate Governance Report — structural table extraction (pdfplumber)",
                    "result": "CHECKED",
                    "note": f"{len(execs)} executive(s) found via real table structure, cross-referenced against a board-role table.",
                })
    except Exception as e:
        print(f"[qualitative_engine] B.1.2 structural table pass failed for {sym}: {e}")

    if result["tenure_score"] is None:
        from tools.founder_track_record_scoring import score_management_tenure
        result = score_management_tenure(tenure_text, fiscal_year) if tenure_text else {"average_tenure_years": None, "tenure_score": None, "executives": []}

    if result["tenure_score"] is None:
        reason = (ft.get("error") or "No director appointment/tenure detail was located in the latest Annual Report PDF this run.") if not tenure_text else (
            "A director/KMP section was found in the Annual Report, but no named CEO/CFO/Executive Director "
            "with an explicit appointment date (\"since <year>\" / \"w.e.f. <date>\") was located - a bare "
            "years-of-experience phrase is not counted as company tenure, so no score can be computed this run."
        )
        payload = {
            "subpoint_id": subpoint_id, "title": "Management tenure",
            "available": True, **result,
            "rationale": reason, "pathway_results": pathway_results, "source_pdf_url": pdf_url,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Management tenure",
        "available": True, **result,
        "rationale": f"Average tenure across {len(result['executives'])} identified key executive(s) "
                     f"({', '.join(e['role'] for e in result['executives'])}) is {result['average_tenure_years']} years "
                     f"-> score {result['tenure_score']}/5.",
        "pathway_results": pathway_results, "source_pdf_url": pdf_url,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b1_3_strategy_relevance(symbol, name=None, force=False):
    """B.1.3 - Relevance to current strategy. Spec formula: Strategy
    Alignment Score = (Leadership Experience Areas Matching Current
    Strategic Priorities / Total Current Strategic Priorities) x 100,
    banded to a 1-5 score, labelled High (score>=4) / Moderate (score 3) /
    Low (score<=2).

    Deterministic (no LLM) - see tools/founder_track_record_scoring.py's
    classify_strategy_alignment: a fixed, auditable taxonomy of common
    strategic-priority areas (digital/tech, retail, manufacturing, exports,
    energy transition, capacity expansion, finance/M&A, brand/marketing,
    R&D/innovation, route-to-market), each with a "priority" pattern (the
    company stating it as a current focus) and an "experience" pattern (a
    director's background explicitly in that area) - a category counts as
    matched only when BOTH fire in the text. Sourcing: MD&A Business
    Strategy + director profiles from the latest Annual Report. The spec's
    Investor Presentation / Earnings Call Transcript cross-check has no
    fetcher wired for this sub-point - see the PORTAL-03 gap in
    pathway_results; priorities here are read from the AR's own MD&A only.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.1.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import fetch_founder_track_record_text
        ft = fetch_founder_track_record_text(sym, name) or {}
    except Exception as e:
        print(f"[qualitative_engine] B.1.3 AR text fetch failed for {sym}: {e}")
        ft = {"error": str(e)}

    strategy_text = ft.get("strategy_text")
    pdf_url = ft.get("pdf_url")
    pathway_results = [
        {
            "pathway_id": "AR-13",
            "source": "MD&A Business Strategy + director profiles",
            "result": "CHECKED" if strategy_text else "NOT_DISCLOSED",
            "note": None if strategy_text else "Business Strategy / director-profile section not located in the latest Annual Report PDF this run.",
        },
        {
            "pathway_id": "PORTAL-03",
            "source": "NSE Corporate Announcements - Investor Presentation / Earnings Call Transcript current strategic priorities",
            "result": "NOT_WIRED",
            "note": "No investor-presentation/transcript fetcher is wired for this sub-point - strategic priorities are read from the Annual Report's own MD&A only.",
        },
    ]

    from tools.founder_track_record_scoring import score_strategy_alignment
    result = score_strategy_alignment(strategy_text) if strategy_text else {
        "strategy_alignment_pct": None, "alignment_score": None, "alignment": None,
        "strategic_priorities": [], "matched_areas": [],
    }

    if not result["alignment"]:
        reason = (ft.get("error") or "No Business Strategy or director-profile section was located in the latest Annual Report PDF this run.") if not strategy_text else (
            "A Business Strategy section was found, but it does not name a strategic priority from the fixed "
            "evidence taxonomy (digital, retail, manufacturing, exports, energy transition, capacity expansion, "
            "finance/M&A, brand/marketing, R&D, route-to-market) - no alignment evidence was located this run."
        )
        payload = {
            "subpoint_id": subpoint_id, "title": "Relevance to current strategy",
            "available": True, **result,
            "rationale": reason, "pathway_results": pathway_results, "source_pdf_url": pdf_url,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Relevance to current strategy",
        "available": True, **result,
        "rationale": f"Leadership background explicitly matches {len(result['matched_areas'])} of {len(result['strategic_priorities'])} "
                     f"stated strategic priorities ({result['strategy_alignment_pct']}% -> {result['alignment']} alignment).",
        "pathway_results": pathway_results, "source_pdf_url": pdf_url,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b1_founder_ceo_track_record(symbol, name=None, description="", force=False):
    """B.1 - Founders / CEO track record: combines the three sub-points
    (B.1.1 past successes/failures, B.1.2 management tenure, B.1.3 relevance
    to current strategy) into a single grounded payload, each sourced from
    real Annual Report text (see fetch_founder_track_record_text) rather than
    an ungrounded LLM guess - every score/classification traces back to an
    explicit statement in the filing, and any sub-point the AR doesn't
    explicitly cover is surfaced as unavailable rather than defaulted.

    This does NOT run the FOUNDER-01..07 independent background-check
    pathways (MCA directorship history, disqualification/debarment,
    defaulter, litigation, negative-news search) - none have fetchers wired
    in this codebase. Those remain a human-analyst gap noted in the combined
    rationale; this sub-point's AR-sourced scores must not be read as a
    substitute for that verification before an investment decision.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    b11 = compute_b1_1_past_track_record(sym, name, force=force)
    b12 = compute_b1_2_management_tenure(sym, name, force=force)
    b13 = compute_b1_3_strategy_relevance(sym, name, force=force)

    parts = []
    if b11.get("execution_score") is not None:
        parts.append(f"Initiative success rate: {b11['initiative_success_rate_pct']}% ({b11['successful_count']}/{len(b11['initiatives'])} initiatives, score {b11['execution_score']}/5).")
    if b12.get("tenure_score") is not None:
        parts.append(f"Average leadership tenure: {b12['average_tenure_years']} years across {len(b12['executives'])} key executive(s) (score {b12['tenure_score']}/5).")
    if b13.get("alignment"):
        parts.append(f"Strategy alignment: {b13['alignment']} ({b13['strategy_alignment_pct']}%).")
    if not parts:
        parts.append("None of the three sub-points (past initiatives, director tenure, strategy alignment) were explicitly covered in the latest Annual Report this run.")
    parts.append(
        "Independent background verification (MCA directorship history, disqualification/debarment status, "
        "defaulter search, litigation search, negative-news search) has not been run - route to an analyst "
        "before this factors into an investment decision."
    )

    _tags = [t.get("confidence_tag") for t in (b11, b12, b13)]
    if all(t == "SEARCH_INCONCLUSIVE" for t in _tags):
        combined_tag = "SEARCH_INCONCLUSIVE"
    elif any(t == "SINGLE_SOURCE" for t in _tags):
        combined_tag = "SINGLE_SOURCE"
    else:
        combined_tag = "SEARCH_INCONCLUSIVE"

    retrieved_ats = [t.get("retrieved_at") for t in (b11, b12, b13) if t.get("retrieved_at")]
    payload = {
        "subpoint_id": "B.1",
        "title": "Founders / CEO track record: past successes/failures, tenure, relevance to current strategy",
        "available": True,
        "b1_1": b11, "b1_2": b12, "b1_3": b13,
        "rationale": " ".join(parts),
        "pathway_results": (b11.get("pathway_results") or []) + (b12.get("pathway_results") or []) + (b13.get("pathway_results") or []),
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload



def compute_b2_1_pay_structure(symbol, name=None, force=False):
    """B.2.1 - Pay structure. Spec formula: Fixed vs Variable Compensation
    Mix. Deterministic (no LLM) - see
    tools/management_incentives_scoring.py's extract_pay_mix: finds every
    explicit "Fixed <Commission/Pay/Salary>" and "Variable/Performance-
    linked <Commission/Pay/Bonus>" label with a real amount figure nearby,
    sums each bucket. Sourcing: Corporate Governance Report - Remuneration
    to Directors/KMP (falls back to the Remuneration Policy text when the
    KMP table itself has no fixed/variable split, which is common - many
    AR remuneration tables only show a remuneration-to-median-employee
    ratio, not a fixed/variable breakdown).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.2.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import fetch_governance_text_sections
        gov = fetch_governance_text_sections(sym, name) or {}
    except Exception as e:
        print(f"[qualitative_engine] B.2.1 AR text fetch failed for {sym}: {e}")
        gov = {"error": str(e)}

    remuneration_text = gov.get("remuneration_text")
    policy_text = gov.get("remuneration_policy_text")
    pdf_url = gov.get("pdf_url")
    pathway_results = [{
        "pathway_id": "AR-02",
        "source": "Corporate Governance Report - Remuneration to Directors/KMP",
        "result": "CHECKED" if (remuneration_text or policy_text) else "NOT_DISCLOSED",
        "note": None if (remuneration_text or policy_text) else "Remuneration table/policy section not located in the latest Annual Report PDF this run.",
    }]

    # STRUCTURAL pass first: a KMP/Director remuneration table's own column
    # headers routinely name the pay components directly (e.g. "Basic/
    # Consolidated Salary" | "Perquisites/Other Benefits" | "Performance
    # Bonus/Long Term Incentives/Commission" - confirmed real on ITC) - far
    # more reliable than searching for the literal words "Fixed"/"Variable",
    # which many companies never use for KMP pay (only for NED sitting
    # fees/commission, a different, smaller disclosure).
    result = {"fixed_amount": None, "variable_amount": None, "fixed_pct": None}
    try:
        from tools.ar_table_extractor import extract_tables_near_anchors
        from tools.management_incentives_scoring import extract_pay_mix_from_tables
        fiscal_year = gov.get("fiscal_year")
        tabs = extract_tables_near_anchors(sym, name, {"remun": ["salary", "perquisites", "commission", "gross remuneration", "stock options"]}, fiscal_year=fiscal_year, max_pages_per_key=6, max_tables_per_key=6)
        table_result = extract_pay_mix_from_tables(tabs.get("remun", []))
        if table_result["fixed_pct"] is not None:
            result = table_result
            pathway_results.insert(0, {
                "pathway_id": "AR-02-TABLE",
                "source": "KMP Remuneration table — Salary/Perquisites vs Bonus/Commission columns (structural table extraction)",
                "result": "CHECKED",
                "note": f"Fixed {table_result['fixed_amount']} vs Variable {table_result['variable_amount']} summed from real table columns.",
            })
    except Exception as e:
        print(f"[qualitative_engine] B.2.1 structural table pass failed for {sym}: {e}")

    if result["fixed_pct"] is None:
        from tools.management_incentives_scoring import extract_pay_mix
        result = extract_pay_mix(remuneration_text) if remuneration_text else {"fixed_amount": None, "variable_amount": None, "fixed_pct": None}
        if result["fixed_pct"] is None and policy_text:
            result = extract_pay_mix(policy_text)

    if result["fixed_pct"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Pay structure", "available": True, **result,
            "rationale": (gov.get("error") or "No explicit Fixed and Variable compensation component amounts were located in the latest Annual Report this run."),
            "pathway_results": pathway_results, "source_pdf_url": pdf_url,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Pay structure", "available": True, **result,
        "rationale": f"Fixed component {result['fixed_amount']} vs Variable component {result['variable_amount']} explicitly stated "
                     f"({result['fixed_pct']}% fixed).",
        "pathway_results": pathway_results, "source_pdf_url": pdf_url,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b2_2_equity_ownership(symbol, name=None, force=False):
    """B.2.2 - Equity ownership. Spec formula: Management Ownership Score
    (1-5). Deterministic (no LLM) - see
    tools/management_incentives_scoring.py's score_equity_ownership: sums
    every explicit "X% of total/paid-up shares" figure tied to a named
    Director/KMP role (never a promoter-group holding, a different
    section). Sourcing: Corporate Governance Report - Shareholding of
    Directors and KMP.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.2.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import fetch_governance_text_sections
        gov = fetch_governance_text_sections(sym, name) or {}
    except Exception as e:
        print(f"[qualitative_engine] B.2.2 AR text fetch failed for {sym}: {e}")
        gov = {"error": str(e)}

    shareholding_text = gov.get("shareholding_kmp_text")
    pdf_url = gov.get("pdf_url")
    pathway_results = [{
        "pathway_id": "AR-02",
        "source": "Corporate Governance Report - Shareholding of Directors and KMP",
        "result": "CHECKED" if shareholding_text else "NOT_DISCLOSED",
        "note": None if shareholding_text else "Shareholding of Directors/KMP section not located in the latest Annual Report PDF this run.",
    }]

    # STRUCTURAL pass first: each director's Corporate Governance profile
    # in a standard AR carries a "Number of Equity Shares held in the
    # Company" field with an absolute share COUNT - far more reliably
    # disclosed than an explicit "X% of total shares" figure, which many
    # companies simply never state per-director (confirmed live: TCS has
    # no such % anywhere, but does disclose the per-director share count).
    # Divides by the company's own total shares outstanding to get %.
    result = {"management_ownership_pct": None, "ownership_score": None}
    try:
        from tools.ar_table_extractor import extract_tables_near_anchors
        from tools.management_incentives_scoring import score_equity_ownership_from_tables
        from tools.nse_xbrl import fetch_shares_outstanding
        fiscal_year = gov.get("fiscal_year")
        # Each director's profile is its own page, so the anchor phrase
        # scores identically (1 hit) on every one of them — the usual
        # top-3-pages cap would arbitrarily keep only a few directors.
        # Raised to capture a full board (typically well under 25 people).
        tabs = extract_tables_near_anchors(sym, name, {"profiles": ["number of equity shares held in the"]}, fiscal_year=fiscal_year, max_tables_per_key=25, max_pages_per_key=25)
        shares_info = fetch_shares_outstanding(sym, name)
        total_shares = shares_info.get("value") if shares_info and shares_info.get("applicable") else None
        table_result = score_equity_ownership_from_tables(tabs.get("profiles", []), total_shares)
        if table_result["ownership_score"] is not None:
            result = table_result
            pathway_results.insert(0, {
                "pathway_id": "AR-02-TABLE",
                "source": "Director Corporate Governance profiles — Number of Equity Shares held (structural table extraction)",
                "result": "CHECKED",
                "note": f"{table_result.get('director_share_count')} shares summed across director profiles, vs {total_shares} total shares outstanding.",
            })
    except Exception as e:
        print(f"[qualitative_engine] B.2.2 structural table pass failed for {sym}: {e}")

    if result["ownership_score"] is None:
        from tools.management_incentives_scoring import score_equity_ownership
        result = score_equity_ownership(shareholding_text) if shareholding_text else {"management_ownership_pct": None, "ownership_score": None}

    # Third tier: PROMOTER holding % from the NSE Shareholding Pattern
    # (the same real, live-verified source already powering C.1 — see
    # compute_c1_promoter_shareholding). Per the updated sourcing
    # direction ("use promoter holding, director holdings, and KMP
    # holdings from shareholding tables") - for most Indian listed
    # companies the promoter group IS the founding/controlling management
    # (a subsidiary's parent, a founder-family holding entity), so it's a
    # legitimate "management-owned" proxy when neither director-profile
    # share counts nor an explicit Director/KMP % are disclosed at all
    # (confirmed real gap: HINDUNILVR discloses neither, but does disclose
    # 61.9% promoter holding via the standard, NSE-mandated Shareholding
    # Pattern filing every listed company files).
    promoter_used = False
    if result["ownership_score"] is None:
        try:
            from tools.shareholding_scraper import get_provider
            trend = get_provider().fetch_promoter_holding_trend(sym) or []
            if trend:
                promoter_pct = trend[-1].get("promoter_holding_pct")
                if promoter_pct is not None:
                    score = 5 if promoter_pct >= 5 else 4 if promoter_pct >= 2 else 3 if promoter_pct >= 1 else 2 if promoter_pct >= 0.1 else 1
                    result = {"management_ownership_pct": promoter_pct, "ownership_score": score}
                    promoter_used = True
                    pathway_results.insert(0, {
                        "pathway_id": "PORTAL-02",
                        "source": "NSE Shareholding Pattern — Promoter and Promoter Group holding (live endpoint)",
                        "result": "CHECKED",
                        "note": f"Promoter/promoter-group holding used as the management-ownership proxy — no per-director share count or % was separately disclosed this run.",
                    })
        except Exception as e:
            print(f"[qualitative_engine] B.2.2 promoter-holding fallback failed for {sym}: {e}")

    if result["ownership_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Equity ownership", "available": True, **result,
            "rationale": (gov.get("error") or "No explicit Director/KMP shareholding percentage, director share count, or promoter holding was located this run."),
            "pathway_results": pathway_results, "source_pdf_url": pdf_url,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Equity ownership", "available": True, **result,
        "rationale": (f"Promoter/promoter-group (the controlling entity) holds {result['management_ownership_pct']}% of total shares -> score {result['ownership_score']}/5 "
                      f"(no separate director/KMP-specific figure was disclosed this run)."
                      if promoter_used else
                      f"Directors/KMP explicitly hold {result['management_ownership_pct']}% of total shares -> score {result['ownership_score']}/5."),
        "pathway_results": pathway_results, "source_pdf_url": pdf_url,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b2_3_vesting_structure(symbol, name=None, force=False):
    """B.2.3 - Vesting structure. Spec formula: Long-term Incentive Score
    (1-5). Deterministic (no LLM) - see
    tools/management_incentives_scoring.py's score_vesting_structure: sums
    explicit "vested"/"unvested" option-count figures from the ESOP
    disclosure. Score bands on the unvested share of total options (this
    engine's own documented interpretation - more unvested means more
    forward-looking retention pull; the spec doesn't state a direction).
    Sourcing: Corporate Governance Report - ESOP/Stock Option Scheme
    Vesting Schedule.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.2.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import fetch_governance_text_sections
        gov = fetch_governance_text_sections(sym, name) or {}
    except Exception as e:
        print(f"[qualitative_engine] B.2.3 AR text fetch failed for {sym}: {e}")
        gov = {"error": str(e)}

    esop_text = gov.get("esop_text")
    pdf_url = gov.get("pdf_url")
    pathway_results = [{
        "pathway_id": "AR-03",
        "source": "ESOP / Stock Option Scheme Vesting Schedule",
        "result": "CHECKED" if esop_text else "NOT_DISCLOSED",
        "note": None if esop_text else "ESOP disclosure section not located in the latest Annual Report PDF this run - may indicate no ESOP scheme exists, not confirmed either way.",
    }]

    # STRUCTURAL pass first: a standard Ind AS 102 ESOP reconciliation
    # table states "Options Outstanding at the end of the year" (total)
    # and "Options exercisable at the end of the year" (already vested) -
    # far more reliably disclosed than a literal "vested"/"unvested" label
    # pair (confirmed real: ITC uses "exercisable", never says "vested").
    result = {"vested_count": None, "unvested_count": None, "unvested_pct": None, "vesting_score": None}
    try:
        from tools.ar_table_extractor import extract_tables_near_anchors
        from tools.management_incentives_scoring import score_vesting_structure_from_tables
        fiscal_year = gov.get("fiscal_year")
        tabs = extract_tables_near_anchors(sym, name, {"esop": ["vesting", "grant date", "exercise period", "exercise price", "options vested", "vesting schedule", "outstanding"]}, fiscal_year=fiscal_year, max_pages_per_key=8, max_tables_per_key=8)
        table_result = score_vesting_structure_from_tables(tabs.get("esop", []))
        if table_result["vesting_score"] is not None:
            result = table_result
            pathway_results.insert(0, {
                "pathway_id": "AR-03-TABLE",
                "source": "ESOP reconciliation table — Options Outstanding vs Exercisable (structural table extraction)",
                "result": "CHECKED",
                "note": f"{table_result['vested_count']} exercisable (vested) vs {table_result['unvested_count']} unvested, from a real Ind AS 102 table.",
            })
    except Exception as e:
        print(f"[qualitative_engine] B.2.3 structural table pass failed for {sym}: {e}")

    # Second tier: some ESOP grant-schedule tables (Date of Grant / Options
    # Granted / Vesting Conditions / Exercise Period) have real column
    # structure but NO visible cell rulings in the PDF, so pdfplumber's
    # geometry-based table detector above finds nothing at all (confirmed
    # real: HINDUNILVR). Parses the raw page text directly instead, and
    # infers vested/unvested from elapsed time since each tranche's grant
    # vs its own stated vesting period.
    if result["vesting_score"] is None:
        try:
            from tools.ar_table_extractor import extract_text_near_anchors
            from tools.management_incentives_scoring import extract_esop_grant_schedule, score_vesting_structure_from_grant_schedule
            fiscal_year = gov.get("fiscal_year")
            texts = extract_text_near_anchors(sym, name, {"esop": ["vesting schedule", "grant date", "exercise period", "esos", "employee stock option scheme", "date of grant"]}, fiscal_year=fiscal_year, max_pages_per_key=8)
            tranches = extract_esop_grant_schedule(texts.get("esop", ""), texts.get("fiscal_year"))
            grant_result = score_vesting_structure_from_grant_schedule(tranches, texts.get("fiscal_year"))
            if grant_result["vesting_score"] is not None:
                result = grant_result
                pathway_results.insert(0, {
                    "pathway_id": "AR-03-GRANT",
                    "source": "ESOP grant schedule — Date of Grant / Options Granted / Vesting Conditions (raw-text extraction, no ruled table lines)",
                    "result": "CHECKED",
                    "note": f"{len(tranches)} grant tranche(s) found; vested/unvested inferred from elapsed time since each grant vs its own stated vesting period.",
                })
        except Exception as e:
            print(f"[qualitative_engine] B.2.3 grant-schedule pass failed for {sym}: {e}")

    if result["vesting_score"] is None:
        from tools.management_incentives_scoring import score_vesting_structure
        result = score_vesting_structure(esop_text) if esop_text else {"vested_count": None, "unvested_count": None, "unvested_pct": None, "vesting_score": None}

    if result["vesting_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Vesting structure", "available": True, **result,
            "rationale": (gov.get("error") or "No explicit vested/unvested option counts were located in the latest Annual Report this run."),
            "pathway_results": pathway_results, "source_pdf_url": pdf_url,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Vesting structure", "available": True, **result,
        "rationale": f"{result['vested_count']} vested vs {result['unvested_count']} unvested options explicitly stated "
                     f"({result['unvested_pct']}% unvested -> score {result['vesting_score']}/5).",
        "pathway_results": pathway_results, "source_pdf_url": pdf_url,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b2_4_long_term_orientation(symbol, name=None, force=False):
    """B.2.4 - Long-term orientation. Spec formula: Long-term Alignment
    Score (1-5). Deterministic (no LLM) - see
    tools/management_incentives_scoring.py's score_long_term_orientation:
    classifies Remuneration Policy sentences into long-term-incentive
    keywords (LTIP/ESOP/stock options/deferred pay/performance shares) vs
    short-term-incentive keywords (annual bonus/STI/cash bonus). Sourcing:
    Remuneration Policy - Performance-linked Long-term Incentives.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.2.4"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import fetch_governance_text_sections
        gov = fetch_governance_text_sections(sym, name) or {}
    except Exception as e:
        print(f"[qualitative_engine] B.2.4 AR text fetch failed for {sym}: {e}")
        gov = {"error": str(e)}

    policy_text = gov.get("remuneration_policy_text")
    pdf_url = gov.get("pdf_url")
    pathway_results = [{
        "pathway_id": "AR-02",
        "source": "Remuneration Policy - Performance-linked Long-term Incentives",
        "result": "CHECKED" if policy_text else "NOT_DISCLOSED",
        "note": None if policy_text else "Remuneration Policy section not located in the latest Annual Report PDF this run.",
    }]

    # STRUCTURAL pass first: infer long-term orientation from the ESOP's
    # OWN disclosed vesting horizon (longest "completion of N months/years
    # from grant" figure in its Vesting Schedule note) plus whether vesting
    # is explicitly performance-linked - per the updated sourcing
    # direction ("infer from ESOP duration, vesting horizon, and
    # performance-linked incentives") rather than counting LTIP/STI
    # keyword mentions in the Remuneration Policy prose, which many
    # companies' policies don't discuss in those exact terms at all.
    result = {"long_term_count": None, "short_term_count": None, "long_term_pct": None, "alignment_score": None,
              "vesting_horizon_years": None, "performance_linked": None}
    try:
        from tools.ar_table_extractor import extract_tables_near_anchors
        from tools.management_incentives_scoring import score_long_term_orientation_from_esop_text
        fiscal_year = gov.get("fiscal_year")
        tabs = extract_tables_near_anchors(sym, name, {"esop": ["vesting schedule", "vesting period"]}, fiscal_year=fiscal_year, max_pages_per_key=8, max_tables_per_key=8)
        vesting_text = None
        for t in tabs.get("esop", []):
            for row in t or []:
                if row and any("vesting schedule" in str(c or "").lower() or "vesting period" in str(c or "").lower() for c in row):
                    vesting_text = " ".join(str(c or "") for c in row)
                    break
            if vesting_text:
                break
        table_result = score_long_term_orientation_from_esop_text(vesting_text)
        if table_result["alignment_score"] is not None:
            result = {**result, **table_result}
            pathway_results.insert(0, {
                "pathway_id": "AR-03-TABLE",
                "source": "ESOP Vesting Schedule note — vesting horizon + performance-linkage (structural table extraction)",
                "result": "CHECKED",
                "note": f"{table_result['vesting_horizon_years']}-year vesting horizon, performance-linked={table_result['performance_linked']}.",
            })
    except Exception as e:
        print(f"[qualitative_engine] B.2.4 structural table pass failed for {sym}: {e}")

    # Second tier: same grant-schedule raw-text extraction B.2.3 uses (a
    # real table with no visible cell rulings, so the geometry-based table
    # pass above finds nothing - confirmed real: HINDUNILVR).
    if result["alignment_score"] is None:
        try:
            from tools.ar_table_extractor import extract_text_near_anchors
            from tools.management_incentives_scoring import extract_esop_grant_schedule, score_long_term_orientation_from_grant_schedule
            fiscal_year = gov.get("fiscal_year")
            texts = extract_text_near_anchors(sym, name, {"esop": ["vesting schedule", "grant date", "exercise period", "esos", "employee stock option scheme", "date of grant"]}, fiscal_year=fiscal_year, max_pages_per_key=8)
            tranches = extract_esop_grant_schedule(texts.get("esop", ""), texts.get("fiscal_year"))
            grant_result = score_long_term_orientation_from_grant_schedule(tranches)
            if grant_result["alignment_score"] is not None:
                result = {**result, **grant_result}
                pathway_results.insert(0, {
                    "pathway_id": "AR-03-GRANT",
                    "source": "ESOP grant schedule — vesting horizon + performance-linkage (raw-text extraction, no ruled table lines)",
                    "result": "CHECKED",
                    "note": f"{len(tranches)} grant tranche(s) found; {grant_result['vesting_horizon_years']}-year horizon, performance-linked={grant_result['performance_linked']}.",
                })
        except Exception as e:
            print(f"[qualitative_engine] B.2.4 grant-schedule pass failed for {sym}: {e}")

    if result["alignment_score"] is None:
        from tools.management_incentives_scoring import score_long_term_orientation
        result = score_long_term_orientation(policy_text) if policy_text else {"long_term_count": None, "short_term_count": None, "long_term_pct": None, "alignment_score": None}

    if result["alignment_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Long-term orientation", "available": True, **result,
            "rationale": (gov.get("error") or "No explicit long-term or short-term incentive language was located in the latest Annual Report's Remuneration Policy this run."),
            "pathway_results": pathway_results, "source_pdf_url": pdf_url,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    if result.get("vesting_horizon_years") is not None:
        rationale = (
            f"ESOP vests over {result['vesting_horizon_years']} year(s) from grant"
            + (", explicitly performance-linked" if result.get("performance_linked") else ", time-based (not performance-linked)")
            + f" -> score {result['alignment_score']}/5."
        )
    else:
        rationale = (f"{result['long_term_count']} long-term vs {result['short_term_count']} short-term incentive mention(s) "
                      f"explicitly found ({result['long_term_pct']}% long-term -> score {result['alignment_score']}/5).")

    payload = {
        "subpoint_id": subpoint_id, "title": "Long-term orientation", "available": True, **result,
        "rationale": rationale,
        "pathway_results": pathway_results, "source_pdf_url": pdf_url,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b2_management_incentives(symbol, name=None, force=False):
    """B.2 - Management incentives: combines the four sub-points (B.2.1 pay
    structure, B.2.2 equity ownership, B.2.3 vesting structure, B.2.4
    long-term orientation) into a single grounded payload, each sourced
    from real Annual Report text and scored deterministically (regex/
    keyword pattern matching, no LLM call - see
    tools/management_incentives_scoring.py) - every figure traces to a
    literal matched amount/percentage/count in the filing, and any
    sub-point the AR doesn't explicitly cover is surfaced as unavailable
    rather than defaulted.

    This does NOT run PORTAL-05 (MCA director registry) - no fetcher wired
    in this codebase; stays SINGLE_SOURCE at best even when AR text is found.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    b21 = compute_b2_1_pay_structure(sym, name, force=force)
    b22 = compute_b2_2_equity_ownership(sym, name, force=force)
    b23 = compute_b2_3_vesting_structure(sym, name, force=force)
    b24 = compute_b2_4_long_term_orientation(sym, name, force=force)

    parts = []
    if b21.get("fixed_pct") is not None:
        parts.append(f"Pay structure: {b21['fixed_pct']}% fixed vs {round(100 - b21['fixed_pct'], 1)}% variable.")
    if b22.get("ownership_score") is not None:
        parts.append(f"Equity ownership: {b22['management_ownership_pct']}% (score {b22['ownership_score']}/5).")
    if b23.get("vesting_score") is not None:
        parts.append(f"Vesting: {b23['unvested_pct']}% of options unvested (score {b23['vesting_score']}/5).")
    if b24.get("vesting_horizon_years") is not None:
        parts.append(f"Long-term orientation: {b24['vesting_horizon_years']}-year ESOP vesting horizon (score {b24['alignment_score']}/5).")
    elif b24.get("alignment_score") is not None:
        parts.append(f"Long-term orientation: {b24['long_term_pct']}% long-term incentive language (score {b24['alignment_score']}/5).")
    if not parts:
        parts.append("None of the four sub-points (pay structure, equity ownership, vesting, long-term orientation) were explicitly covered in the latest Annual Report this run.")
    parts.append("MCA director/KMP cross-check (PORTAL-05) has not been run - route to an analyst before this factors into an investment decision.")

    _tags = [t.get("confidence_tag") for t in (b21, b22, b23, b24)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"

    retrieved_ats = [t.get("retrieved_at") for t in (b21, b22, b23, b24) if t.get("retrieved_at")]
    payload = {
        "subpoint_id": "B.2",
        "title": "Management incentives: pay structure, equity ownership, vesting, long-term orientation",
        "available": True,
        "b2_1": b21, "b2_2": b22, "b2_3": b23, "b2_4": b24,
        "rationale": " ".join(parts),
        "pathway_results": (b21.get("pathway_results") or []) + (b22.get("pathway_results") or []) + (b23.get("pathway_results") or []) + (b24.get("pathway_results") or []),
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


def compute_b3_1_leadership_depth(symbol, name=None, force=False):
    """B.3.1 - Leadership depth. Spec formula: Leadership Depth Score (1-5).
    Deterministic (no LLM) - see tools/management_bench_scoring.py's
    score_leadership_depth_from_text: counts named [Name, Designation]
    pairs in the Senior Management Personnel / Executive Leadership Team
    section (or falls back to an explicit "Committee comprises N Members"
    sentence). Sourcing: Annual Report - Senior Management Personnel /
    Executive Leadership Team.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.3.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.ar_table_extractor import extract_text_near_anchors
        from tools.management_bench_scoring import score_leadership_depth_from_text
        texts = extract_text_near_anchors(sym, name, {"smp": ["senior management personnel", "executive leadership team", "senior management team"]}, max_pages_per_key=4)
        pdf_url = None
        result = score_leadership_depth_from_text(texts.get("smp", ""))
    except Exception as e:
        print(f"[qualitative_engine] B.3.1 fetch failed for {sym}: {e}")
        result = {"member_count": None, "depth_score": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-06",
        "source": "Annual Report - Senior Management Personnel / Executive Leadership Team",
        "result": "CHECKED" if result["depth_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["depth_score"] is not None else "Senior Management Personnel / Executive Leadership Team listing not located in the latest Annual Report PDF this run.",
    }]

    if result["depth_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Leadership depth", "available": True, **result,
            "rationale": "No Senior Management Personnel / Executive Leadership Team listing was located in the latest Annual Report this run.",
            "pathway_results": pathway_results, "source_pdf_url": pdf_url,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Leadership depth", "available": True, **result,
        "rationale": f"{result['member_count']} named senior management personnel/executive leadership members explicitly listed -> score {result['depth_score']}/5.",
        "pathway_results": pathway_results, "source_pdf_url": pdf_url,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b3_2_succession_readiness(symbol, name=None, force=False):
    """B.3.2 - Succession readiness. Spec formula: Succession Readiness
    Score (1-5). Deterministic (no LLM) - see
    tools/management_bench_scoring.py's score_succession_readiness:
    classifies from either (a) explicit evidence the succession-planning
    process is actively reviewed/in place, or (b) a concrete completed
    transition explicitly naming a successor ("appointed ... in
    succession to ..."). Sourcing: Nomination & Remuneration Committee
    Report - Succession Planning.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.3.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.ar_table_extractor import extract_text_near_anchors
        from tools.management_bench_scoring import score_succession_readiness
        texts = extract_text_near_anchors(sym, name, {"succession": ["succession plan", "in succession to"]}, max_pages_per_key=4)
        pdf_url = None
        result = score_succession_readiness(texts.get("succession", ""))
    except Exception as e:
        print(f"[qualitative_engine] B.3.2 fetch failed for {sym}: {e}")
        result = {"succession_transitions": None, "active_process_evidence": None, "readiness": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-06",
        "source": "Nomination & Remuneration Committee Report - Succession Planning",
        "result": "CHECKED" if result["readiness"] is not None else "NOT_DISCLOSED",
        "note": None if result["readiness"] is not None else "No succession-planning evidence (an active process, or a named completed transition) was located in the latest Annual Report PDF this run.",
    }]

    if result["readiness"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Succession readiness", "available": True, **result,
            "rationale": "No succession-planning evidence was located in the latest Annual Report this run.",
            "pathway_results": pathway_results, "source_pdf_url": pdf_url,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Succession readiness", "available": True, **result,
        "rationale": (f"{result['succession_transitions']} named completed leadership transition(s) explicitly described" if result["succession_transitions"] else "")
                     + (" and " if result["succession_transitions"] and result["active_process_evidence"] else "")
                     + ("explicit evidence the succession-planning process is actively reviewed/in place" if result["active_process_evidence"] else "")
                     + f" -> {result['readiness']}.",
        "pathway_results": pathway_results, "source_pdf_url": pdf_url,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b3_3_key_person_dependency(symbol, name=None, force=False):
    """B.3.3 - Key executive dependency. Spec formula: Key-person
    Dependency Score (1-5). Deterministic (no LLM) - see
    tools/management_bench_scoring.py's score_key_person_dependency: uses
    the leadership bench size (B.3.1's member_count) as the dependency
    signal - responsibility spread across many named senior executives is
    structurally distributed; a thin bench concentrates authority in very
    few hands. (A named-Chairman-vs-CEO role-code comparison was tried
    first but produced a confirmed wrong result live - the "(C)" code
    used in board-composition tables is ambiguous with a COMMITTEE's own
    chair, not just the company Chairman - so this reuses the
    unambiguous, already-validated B.3.1 count instead.) Sourcing:
    Corporate Governance Report - Management Structure.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.3.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    b31 = compute_b3_1_leadership_depth(sym, name, force=force)
    from tools.management_bench_scoring import score_key_person_dependency
    result = score_key_person_dependency(b31.get("member_count"))

    pathway_results = [{
        "pathway_id": "AR-06",
        "source": "Corporate Governance Report - Management Structure (via B.3.1's leadership-bench count)",
        "result": "CHECKED" if result["dependency_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["dependency_score"] is not None else "No leadership-bench count was available to derive this from (see B.3.1).",
    }]

    if result["dependency_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Key executive dependency", "available": True, **result,
            "rationale": "No leadership-bench count was available this run to assess responsibility concentration.",
            "pathway_results": pathway_results, "source_pdf_url": None,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Key executive dependency", "available": True, **result,
        "rationale": f"{b31.get('member_count')} named senior executives explicitly listed -> {result['dependency_level']} responsibility (score {result['dependency_score']}/5).",
        "pathway_results": pathway_results, "source_pdf_url": None,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b3_management_bench_depth(symbol, name=None, force=False):
    """B.3 - Depth of management bench: combines the three sub-points
    (B.3.1 leadership depth, B.3.2 succession readiness, B.3.3 key
    executive dependency) into a single grounded payload, each sourced
    from real Annual Report text and scored deterministically (no LLM
    call - see tools/management_bench_scoring.py). Any sub-point the AR
    doesn't explicitly cover is surfaced as unavailable rather than
    defaulted.

    This does NOT run QUAL-01 (LinkedIn org mapping) or FOUNDER-01 (MCA
    struck-off cross-check) - neither has a fetcher wired in this codebase.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    b31 = compute_b3_1_leadership_depth(sym, name, force=force)
    b32 = compute_b3_2_succession_readiness(sym, name, force=force)
    b33 = compute_b3_3_key_person_dependency(sym, name, force=force)

    parts = []
    if b31.get("depth_score") is not None:
        parts.append(f"Leadership depth: {b31['member_count']} named senior executives (score {b31['depth_score']}/5).")
    if b32.get("readiness") is not None:
        parts.append(f"Succession readiness: {b32['readiness']}.")
    if b33.get("dependency_score") is not None:
        parts.append(f"Key executive dependency: {b33['dependency_level']} (score {b33['dependency_score']}/5).")
    if not parts:
        parts.append("None of the three sub-points (leadership depth, succession readiness, key executive dependency) were explicitly covered in the latest Annual Report this run.")
    parts.append(
        "LinkedIn org mapping and MCA struck-off cross-check have not been run - route to an analyst "
        "before this factors into an investment decision."
    )

    _tags = [t.get("confidence_tag") for t in (b31, b32, b33)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"

    retrieved_ats = [t.get("retrieved_at") for t in (b31, b32, b33) if t.get("retrieved_at")]
    payload = {
        "subpoint_id": "B.3",
        "title": "Depth of management bench: ability to replace key execs without disruption",
        "available": True,
        "b3_1": b31, "b3_2": b32, "b3_3": b33,
        "rationale": " ".join(parts),
        "pathway_results": (b31.get("pathway_results") or []) + (b32.get("pathway_results") or []) + (b33.get("pathway_results") or []),
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


def compute_b4_1_disclosure_transparency(symbol, name=None, force=False):
    """B.4.1 - Transparency in disclosures. Spec formula: Disclosure
    Transparency Score (1-5). Deterministic (no LLM) - see
    tools/communication_quality_scoring.py's score_disclosure_transparency:
    a risk-related sentence is "detailed" if it names a quantified figure,
    "generic" if it matches known risk-boilerplate phrasing with no
    specifics. Sourcing: Annual Report - MD&A / Notes to Accounts / Risk
    Disclosures.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.4.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.ar_table_extractor import extract_text_near_anchors
        from tools.communication_quality_scoring import score_disclosure_transparency
        texts = extract_text_near_anchors(sym, name, {"risk": ["risk factors", "principal risks", "risks and concerns", "risk management"]}, max_pages_per_key=4)
        result = score_disclosure_transparency(texts.get("risk", ""))
    except Exception as e:
        print(f"[qualitative_engine] B.4.1 fetch failed for {sym}: {e}")
        result = {"detailed_count": None, "generic_count": None, "detailed_pct": None, "transparency_score": None}

    pathway_results = [{
        "pathway_id": "AR-13",
        "source": "Annual Report - MD&A / Notes to Accounts / Risk Disclosures",
        "result": "CHECKED" if result["transparency_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["transparency_score"] is not None else "No quantified or clearly-generic risk-disclosure sentence was located in the latest Annual Report PDF this run.",
    }]

    if result["transparency_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Transparency in disclosures", "available": True, **result,
            "rationale": "No risk-disclosure text with a clear detailed/generic signal was located in the latest Annual Report this run.",
            "pathway_results": pathway_results, "source_pdf_url": None,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Transparency in disclosures", "available": True, **result,
        "rationale": f"{result['detailed_count']} detailed (quantified) vs {result['generic_count']} generic risk-disclosure sentence(s) explicitly found -> score {result['transparency_score']}/5.",
        "pathway_results": pathway_results, "source_pdf_url": None,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b4_2_guidance_clarity(symbol, name=None, force=False):
    """B.4.2 - Clarity in guidance. Spec formula: Guidance Clarity Score
    (1-5). Deterministic (no LLM) - see
    tools/communication_quality_scoring.py's score_guidance_clarity: an
    explicit "we don't provide guidance" statement is classified
    "Ambiguous" directly (a real, common policy); otherwise counts
    quantified forward-looking statements against vague ones. Sourcing:
    the company's own real earnings-call transcript (Investor
    Presentation / Earnings Call Transcript - Outlook & Guidance), same
    real BSE-filed source already used for F-14 elsewhere in this codebase.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.4.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.nse_announcements import fetch_transcript_url, download_pdf_text
        from tools.screener_scraper import fetch_concall_list, download_transcript
        from tools.communication_quality_scoring import score_guidance_clarity
        prepared = ""
        transcript_url = fetch_transcript_url(sym, name)
        full = download_pdf_text(transcript_url, max_chars=40000, max_pages=30) if transcript_url else ""
        if not full:
            # NSE corporate-filings-announcements had no locatable transcript
            # this run (or the PDF didn't extract) - fall back to the same
            # real BSE-filed transcript via Screener's Concalls index rather
            # than surfacing N/A when a usable filing does exist elsewhere.
            lst = fetch_concall_list(sym, name)
            if lst:
                transcript_url = lst[0].get("url")
                full = download_transcript(transcript_url, max_chars=40000, max_pages=30)
        if full:
            # Split on the actual Q&A-session transition ("...begin the
            # question-and-answer session"), not an earlier generic mention
            # of "Q&A session" in the moderator's opening remarks (e.g. "45
            # minutes for the Q&A session") which would truncate prepared
            # remarks before management's outlook commentary.
            qa_m = re.search(r"question[-\s]*and[-\s]*answer\s+session", full, re.I)
            prepared = full[:qa_m.start()] if qa_m else full[:8000]
        result = score_guidance_clarity(prepared)
    except Exception as e:
        print(f"[qualitative_engine] B.4.2 fetch failed for {sym}: {e}")
        result = {"quantified_count": None, "vague_count": None, "clarity_pct": None, "clarity_score": None, "explicit_no_guidance": None}
        transcript_url = None

    pathway_results = [{
        "pathway_id": "QUAL-02",
        "source": "NSE Corporate Announcements - Investor Presentation / Earnings Call Transcript, Outlook & Guidance",
        "result": "CHECKED" if result["clarity_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["clarity_score"] is not None else "No earnings-call transcript with an identifiable outlook/guidance signal was located this run.",
    }]

    if result["clarity_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Clarity in guidance", "available": True, **result,
            "rationale": "No earnings-call transcript outlook/guidance section with a clear quantified/vague signal was located this run.",
            "pathway_results": pathway_results, "source_pdf_url": transcript_url,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Clarity in guidance", "available": True, **result,
        "rationale": ("The company explicitly states it does not provide specific guidance -> Ambiguous (score 1/5)." if result["explicit_no_guidance"]
                      else f"{result['quantified_count']} quantified vs {result['vague_count']} vague forward-looking statement(s) explicitly found -> score {result['clarity_score']}/5."),
        "pathway_results": pathway_results, "source_pdf_url": transcript_url,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b4_3_investor_openness(symbol, name=None, force=False):
    """B.4.3 - Openness in investor communication. Spec formula: Investor
    Communication Score (1-5). Deterministic (no LLM) - see
    tools/communication_quality_scoring.py's score_investor_openness:
    counts unique named analysts asking questions and evasive-answer
    phrases within the Q&A section of the company's own real earnings-call
    transcript. Sourcing: Earnings Call Transcript - Q&A Discussion.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.4.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.nse_announcements import fetch_transcript_url, download_pdf_text
        from tools.screener_scraper import fetch_concall_list, download_transcript
        from tools.communication_quality_scoring import score_investor_openness
        full = ""
        transcript_url = fetch_transcript_url(sym, name)
        if transcript_url:
            full = download_pdf_text(transcript_url, max_chars=40000, max_pages=30)
        if not full:
            lst = fetch_concall_list(sym, name)
            if lst:
                transcript_url = lst[0].get("url")
                full = download_transcript(transcript_url, max_chars=40000, max_pages=30)
        result = score_investor_openness(full)
    except Exception as e:
        print(f"[qualitative_engine] B.4.3 fetch failed for {sym}: {e}")
        result = {"unique_analysts": None, "evasive_answer_count": None, "openness_pct": None, "openness_score": None}
        transcript_url = None

    pathway_results = [{
        "pathway_id": "QUAL-02",
        "source": "Earnings Call Transcript - Q&A Discussion",
        "result": "CHECKED" if result["openness_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["openness_score"] is not None else "No earnings-call transcript with an identifiable analyst Q&A section was located this run.",
    }]

    if result["openness_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Openness in investor communication", "available": True, **result,
            "rationale": "No earnings-call transcript Q&A section with named analysts was located this run.",
            "pathway_results": pathway_results, "source_pdf_url": transcript_url,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Openness in investor communication", "available": True, **result,
        "rationale": f"{result['unique_analysts']} named analyst(s) asked questions, {result['evasive_answer_count']} evasive answer phrase(s) explicitly found -> score {result['openness_score']}/5.",
        "pathway_results": pathway_results, "source_pdf_url": transcript_url,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b4_communication_quality(symbol, name=None, force=False):
    """B.4 - Communication quality: combines the three sub-points (B.4.1
    transparency in disclosures, B.4.2 clarity in guidance, B.4.3 openness
    in investor communication) into a single grounded payload, each
    sourced from real Annual Report / earnings-call-transcript text and
    scored deterministically (no LLM call - see
    tools/communication_quality_scoring.py). Any sub-point the source text
    doesn't explicitly cover is surfaced as unavailable rather than
    defaulted.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    b41 = compute_b4_1_disclosure_transparency(sym, name, force=force)
    b42 = compute_b4_2_guidance_clarity(sym, name, force=force)
    b43 = compute_b4_3_investor_openness(sym, name, force=force)

    parts = []
    if b41.get("transparency_score") is not None:
        parts.append(f"Disclosure transparency: {b41['detailed_pct']}% detailed (score {b41['transparency_score']}/5).")
    if b42.get("clarity_score") is not None:
        parts.append(("Guidance clarity: explicit no-guidance policy (score 1/5)." if b42.get("explicit_no_guidance") else f"Guidance clarity: {b42['clarity_pct']}% quantified (score {b42['clarity_score']}/5)."))
    if b43.get("openness_score") is not None:
        parts.append(f"Investor openness: {b43['openness_pct']}% of analyst turns answered without evasion (score {b43['openness_score']}/5).")
    if not parts:
        parts.append("None of the three sub-points (disclosure transparency, guidance clarity, investor openness) were explicitly covered this run.")

    _tags = [t.get("confidence_tag") for t in (b41, b42, b43)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"

    retrieved_ats = [t.get("retrieved_at") for t in (b41, b42, b43) if t.get("retrieved_at")]
    payload = {
        "subpoint_id": "B.4",
        "title": "Communication quality: transparency in disclosures, clarity in guidance, openness in meetings",
        "available": True,
        "b4_1": b41, "b4_2": b42, "b4_3": b43,
        "rationale": " ".join(parts),
        "pathway_results": (b41.get("pathway_results") or []) + (b42.get("pathway_results") or []) + (b43.get("pathway_results") or []),
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


_B5_MAX_YEARS = 5


def _fetch_mda_by_year(sym, name, max_years=_B5_MAX_YEARS):
    """Up to the 5 most recent Annual Reports' MD&A text, oldest->newest -
    same multi-year-loop pattern as compute_a1_2_pattern_trend. A year with
    no extractable MD&A text is skipped, not filled with a guess."""
    from tools.annual_report_financials import list_annual_report_years
    from tools.ar_table_extractor import extract_text_near_anchors
    years = sorted((list_annual_report_years(sym, name) or [])[:max_years])
    out = []
    for fy in years:
        try:
            texts = extract_text_near_anchors(
                sym, name, {"mda": ["management discussion and analysis", "management's discussion and analysis"]},
                fiscal_year=fy, max_pages_per_key=8)
            t = texts.get("mda", "")
            if t:
                out.append({"fiscal_year": fy, "text": t})
        except Exception as e:
            print(f"[qualitative_engine] B.5 MD&A fetch failed for {sym} FY{fy}: {e}")
    return out


def compute_b5_1_milestone_execution(symbol, name=None, force=False):
    """B.5.1 - Delivered vs stated milestones. Spec formula: Execution
    Ratio = Achieved / Announced. Deterministic (no LLM) - see
    tools/execution_credibility_scoring.py's score_milestone_execution:
    counts forward-commitment sentences across the earlier of up to 5
    years' MD&A text as "announced" and completion-confirmation sentences
    in later years as "achieved". Sourcing: NSE Corporate Filings -
    Annual Reports (latest 3-5 years) - MD&A.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.5.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.execution_credibility_scoring import score_milestone_execution
        years_texts = _fetch_mda_by_year(sym, name)
        result = score_milestone_execution(years_texts)
        years_covered = [y["fiscal_year"] for y in years_texts]
    except Exception as e:
        print(f"[qualitative_engine] B.5.1 fetch failed for {sym}: {e}")
        result = {"announced_count": None, "achieved_count": None, "pending_count": None,
                   "execution_ratio": None, "execution_ratio_pct": None, "milestone_score": None}
        years_covered = []

    pathway_results = [{
        "pathway_id": "AR-14",
        "source": "NSE Corporate Filings - Annual Reports (latest 3-5 years) - MD&A",
        "result": "CHECKED" if result["milestone_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["milestone_score"] is not None else "No forward-commitment / completion-confirmation milestone language was located across the available Annual Reports this run.",
    }]

    if result["milestone_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Delivered vs stated milestones", "available": True, **result,
            "years_covered": years_covered,
            "rationale": "No clear announced-vs-achieved milestone signal was located across the available Annual Reports' MD&A this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Delivered vs stated milestones", "available": True, **result,
        "years_covered": years_covered,
        "rationale": f"{result['achieved_count']} of {result['announced_count']} stated milestone(s) explicitly confirmed delivered across FY{years_covered[0] if years_covered else '?'}-FY{years_covered[-1] if years_covered else '?'} (Execution Ratio {result['execution_ratio']}).",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b5_2_capital_execution(symbol, name=None, force=False):
    """B.5.2 - Capital allocation execution. Spec formula: Capital
    Execution Score (1-5). Deterministic (no LLM) - see
    tools/execution_credibility_scoring.py's score_capital_execution:
    compares an explicitly-stated actual capex figure (Cash Flow
    Statement) against an explicitly-stated planned/budgeted capex figure
    (Board's Report). Sourcing: NSE Corporate Filings - Annual Reports -
    Cash Flow Statement / Board's Report.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.5.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.ar_table_extractor import extract_text_near_anchors
        from tools.execution_credibility_scoring import score_capital_execution
        texts = extract_text_near_anchors(sym, name, {
            "cashflow": ["cash flow from investing activities", "purchase of property, plant and equipment", "capital expenditure"],
            "board_report": ["board's report", "directors' report", "capital expenditure"],
        }, max_pages_per_key=6)
        # A company's capex GUIDANCE for a year is often stated a year
        # ahead (in the PRIOR Annual Report's Board's Report/MD&A), not
        # alongside the actual spend it's being compared to - so the
        # planned-capex search spans every available year, not just the
        # latest report.
        board_report_texts = [texts.get("board_report", "")]
        try:
            board_report_texts += [y["text"] for y in _fetch_mda_by_year(sym, name)]
        except Exception:
            pass
        result = score_capital_execution(texts.get("cashflow", ""), board_report_texts)
    except Exception as e:
        print(f"[qualitative_engine] B.5.2 fetch failed for {sym}: {e}")
        result = {"actual_capex_cr": None, "planned_capex_cr": None, "execution_pct": None, "capital_execution_score": None}

    if result["capital_execution_score"] is not None:
        _pathway_note = None
    elif result.get("actual_capex_cr") is not None:
        _pathway_note = f"Actual capex of ₹{result['actual_capex_cr']} cr was located, but no explicitly-stated planned/budgeted capex figure was found across the available Annual Reports this run — an absolute-₹ capex plan/target is genuinely rare in Indian filings."
    else:
        _pathway_note = "No explicitly-stated planned capex figure (Board's Report) alongside an actual capex figure (Cash Flow Statement) was located this run."
    pathway_results = [{
        "pathway_id": "AR-15",
        "source": "NSE Corporate Filings - Annual Reports - Cash Flow Statement / Board's Report - Capex & Acquisition Updates",
        "result": "CHECKED" if result["capital_execution_score"] is not None else "NOT_DISCLOSED",
        "note": _pathway_note,
    }]

    if result["capital_execution_score"] is None:
        if result.get("actual_capex_cr") is not None:
            rationale = (f"Actual capex of ₹{result['actual_capex_cr']} cr was located, but no explicitly-stated "
                         "planned/budgeted/guided capex figure was found across the available Annual Reports this run "
                         "— an absolute-₹ capex plan/target is genuinely rare in Indian filings.")
        else:
            rationale = "No explicitly-stated planned-vs-actual capex comparison was located across the available Annual Reports this run."
        payload = {
            "subpoint_id": subpoint_id, "title": "Capital allocation execution", "available": True, **result,
            "rationale": rationale,
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Capital allocation execution", "available": True, **result,
        "rationale": f"Actual capex of ₹{result['actual_capex_cr']} cr vs planned ₹{result['planned_capex_cr']} cr ({result['execution_pct']}% of plan) -> score {result['capital_execution_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b5_3_strategic_consistency(symbol, name=None, force=False):
    """B.5.3 - Strategic execution consistency. Spec formula: Consistency
    Score (1-5). Deterministic (no LLM) - see
    tools/execution_credibility_scoring.py's score_strategic_consistency:
    detects a fixed set of generic strategic-priority themes in each of up
    to 5 years' MD&A text, then bands year-over-year theme overlap.
    Sourcing: NSE Corporate Filings - Annual Reports (latest 3-5 years) -
    MD&A (strategy statements compared across years).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.5.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.execution_credibility_scoring import score_strategic_consistency
        years_texts = _fetch_mda_by_year(sym, name)
        result = score_strategic_consistency(years_texts)
    except Exception as e:
        print(f"[qualitative_engine] B.5.3 fetch failed for {sym}: {e}")
        result = {"theme_trend": None, "avg_overlap_pct": None, "consistency_score": None}

    pathway_results = [{
        "pathway_id": "AR-14",
        "source": "NSE Corporate Filings - Annual Reports (latest 3-5 years) - MD&A (strategy statements compared across years)",
        "result": "CHECKED" if result["consistency_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["consistency_score"] is not None else "Fewer than 2 years of MD&A with an identifiable strategic-priority theme were located this run.",
    }]

    if result["consistency_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Strategic execution consistency", "available": True, **result,
            "rationale": "No year-over-year strategic-theme comparison was possible across the available Annual Reports this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Strategic execution consistency", "available": True, **result,
        "rationale": f"Strategic priority themes overlapped {result['avg_overlap_pct']}% year-over-year across {len(result['theme_trend'])} year(s) of MD&A -> score {result['consistency_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b5_execution_credibility(symbol, name=None, force=False):
    """B.5 — Execution credibility: combines the three sub-points (B.5.1
    delivered vs stated milestones, B.5.2 capital allocation execution,
    B.5.3 strategic execution consistency) into a single grounded payload,
    each sourced from real, multi-year Annual Report text and scored
    deterministically (no LLM call - see
    tools/execution_credibility_scoring.py). Any sub-point the source text
    doesn't explicitly cover is surfaced as unavailable rather than
    defaulted.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    b51 = compute_b5_1_milestone_execution(sym, name, force=force)
    b52 = compute_b5_2_capital_execution(sym, name, force=force)
    b53 = compute_b5_3_strategic_consistency(sym, name, force=force)

    parts = []
    if b51.get("milestone_score") is not None:
        parts.append(f"Delivered vs stated milestones: {b51['achieved_count']}/{b51['announced_count']} confirmed (Execution Ratio {b51['execution_ratio']}, score {b51['milestone_score']}/5).")
    if b52.get("capital_execution_score") is not None:
        parts.append(f"Capital allocation execution: {b52['execution_pct']}% of planned capex (score {b52['capital_execution_score']}/5).")
    if b53.get("consistency_score") is not None:
        parts.append(f"Strategic execution consistency: {b53['avg_overlap_pct']}% year-over-year theme overlap (score {b53['consistency_score']}/5).")
    if not parts:
        parts.append("None of the three sub-points (delivered vs stated milestones, capital allocation execution, strategic execution consistency) were explicitly covered this run.")

    _tags = [t.get("confidence_tag") for t in (b51, b52, b53)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"

    retrieved_ats = [t.get("retrieved_at") for t in (b51, b52, b53) if t.get("retrieved_at")]
    payload = {
        "subpoint_id": "B.5",
        "title": "Execution credibility: delivered vs stated milestones historically",
        "available": True,
        "b5_1": b51, "b5_2": b52, "b5_3": b53,
        "rationale": " ".join(parts),
        "pathway_results": (b51.get("pathway_results") or []) + (b52.get("pathway_results") or []) + (b53.get("pathway_results") or []),
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


def compute_b6_1_innovation_focus(symbol, name=None, force=False):
    """B.6.1 - Innovation focus. Spec formula: Innovation Score (1-5).
    Deterministic (no LLM) - see tools/culture_scoring.py's
    score_innovation_focus: an innovation-keyword sentence is
    "Innovation-led" if it names a quantified figure (R&D spend, patent
    count, new-product count), "Traditional" if it matches generic
    innovation boilerplate with no specifics. Sourcing: NSE Corporate
    Filings - Annual Reports - R&D / Innovation / Digital Transformation
    sections.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.6.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.ar_table_extractor import extract_text_near_anchors
        from tools.culture_scoring import score_innovation_focus
        texts = extract_text_near_anchors(sym, name, {"innovation": ["research and development", "innovation", "digital transformation"]}, max_pages_per_key=6)
        result = score_innovation_focus(texts.get("innovation", ""))
    except Exception as e:
        print(f"[qualitative_engine] B.6.1 fetch failed for {sym}: {e}")
        result = {"innovation_led_count": None, "traditional_count": None, "innovation_pct": None, "innovation_score": None}

    pathway_results = [{
        "pathway_id": "AR-16",
        "source": "NSE Corporate Filings - Annual Reports - R&D / Innovation / Digital Transformation sections",
        "result": "CHECKED" if result["innovation_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["innovation_score"] is not None else "No quantified or clearly-generic innovation-focus sentence was located in the latest Annual Report PDF this run.",
    }]

    if result["innovation_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Innovation focus", "available": True, **result,
            "rationale": "No innovation-focus text with a clear innovation-led/traditional signal was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Innovation focus", "available": True, **result,
        "rationale": f"{result['innovation_led_count']} innovation-led (quantified) vs {result['traditional_count']} traditional (generic) innovation statement(s) explicitly found -> score {result['innovation_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b6_2_compliance_orientation(symbol, name=None, force=False):
    """B.6.2 - Compliance orientation. Spec formula: Compliance Score
    (1-5). Deterministic (no LLM) - see tools/culture_scoring.py's
    score_compliance_orientation: a compliance-keyword sentence is
    "Strong" if it explicitly confirms an established/operating vigil
    mechanism or internal-controls system, "Weak" if it names a material
    weakness/deficiency/qualified opinion. Sourcing: NSE Corporate
    Filings - Annual Reports - Corporate Governance Report - Vigil
    Mechanism / Internal Controls.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.6.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.ar_table_extractor import extract_text_near_anchors
        from tools.culture_scoring import score_compliance_orientation
        texts = extract_text_near_anchors(sym, name, {"compliance": ["vigil mechanism", "internal financial controls", "whistle blower"]}, max_pages_per_key=6)
        result = score_compliance_orientation(texts.get("compliance", ""))
    except Exception as e:
        print(f"[qualitative_engine] B.6.2 fetch failed for {sym}: {e}")
        result = {"strong_count": None, "weak_count": None, "compliance_pct": None, "compliance_score": None}

    pathway_results = [{
        "pathway_id": "AR-17",
        "source": "NSE Corporate Filings - Annual Reports - Corporate Governance Report - Vigil Mechanism / Internal Controls",
        "result": "CHECKED" if result["compliance_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["compliance_score"] is not None else "No explicit vigil-mechanism/internal-controls confirmation or weakness disclosure was located in the latest Annual Report PDF this run.",
    }]

    if result["compliance_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Compliance orientation", "available": True, **result,
            "rationale": "No vigil-mechanism/internal-controls text with a clear strong/weak signal was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Compliance orientation", "available": True, **result,
        "rationale": f"{result['strong_count']} strong (established/operating) vs {result['weak_count']} weak (deficiency/weakness) compliance statement(s) explicitly found -> score {result['compliance_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b6_3_employee_morale(symbol, name=None, force=False):
    """B.6.3 - Employee morale. Spec formula: Employee Engagement Score
    (1-5). Deterministic (no LLM) - see tools/culture_scoring.py's
    score_employee_morale: an HR-keyword sentence is "Engaged" if it
    names a quantified figure (engagement survey score, training
    coverage %, headcount metric), "Disengaged" only inferred from known
    generic people-culture boilerplate with no specifics. Sourcing: NSE
    Corporate Filings - Annual Reports - Human Resources section -
    employee engagement initiatives.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.6.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.ar_table_extractor import extract_text_near_anchors
        from tools.culture_scoring import score_employee_morale
        texts = extract_text_near_anchors(sym, name, {"hr": ["human resources", "employee engagement", "human capital"]}, max_pages_per_key=6)
        result = score_employee_morale(texts.get("hr", ""))
    except Exception as e:
        print(f"[qualitative_engine] B.6.3 fetch failed for {sym}: {e}")
        result = {"engaged_count": None, "disengaged_count": None, "engagement_pct": None, "engagement_score": None}

    pathway_results = [{
        "pathway_id": "AR-18",
        "source": "NSE Corporate Filings - Annual Reports - Human Resources section - employee engagement initiatives",
        "result": "CHECKED" if result["engagement_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["engagement_score"] is not None else "No quantified or clearly-generic employee-engagement sentence was located in the latest Annual Report PDF this run.",
    }]

    if result["engagement_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Employee morale", "available": True, **result,
            "rationale": "No HR/employee-engagement text with a clear engaged/disengaged signal was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Employee morale", "available": True, **result,
        "rationale": f"{result['engaged_count']} evidence-backed (quantified) vs {result['disengaged_count']} generic employee-culture statement(s) explicitly found -> score {result['engagement_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b6_4_attrition_evidence(symbol, name=None, force=False):
    """B.6.4 - Attrition evidence. Spec formula: Attrition Stability
    Score (1-5). Deterministic (no LLM) - see tools/culture_scoring.py's
    score_attrition_evidence: extracts the company's own disclosed
    employee turnover/attrition rate, preferring BRSR's mandated
    structured Voluntary+Involuntary breakdown ("Turnover rate for
    permanent employees and workers"). Sourcing: NSE Corporate Filings -
    Annual Reports - Human Resources section - attrition / retention
    disclosures.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.6.4"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.ar_table_extractor import extract_text_near_anchors
        from tools.culture_scoring import score_attrition_evidence
        texts = extract_text_near_anchors(sym, name, {
            "attrition": ["turnover rate for permanent employees", "attrition rate", "employee turnover"],
        }, max_pages_per_key=15)
        result = score_attrition_evidence(texts.get("attrition", ""))
    except Exception as e:
        print(f"[qualitative_engine] B.6.4 fetch failed for {sym}: {e}")
        result = {"turnover_rate_pct": None, "retained_pct": None, "attrition_stability_score": None}

    pathway_results = [{
        "pathway_id": "AR-19",
        "source": "NSE Corporate Filings - Annual Reports - Human Resources section - attrition / retention disclosures (BRSR turnover-rate table)",
        "result": "CHECKED" if result["attrition_stability_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["attrition_stability_score"] is not None else "No explicit employee turnover/attrition rate percentage was located in the latest Annual Report PDF this run.",
    }]

    if result["attrition_stability_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Attrition evidence", "available": True, **result,
            "rationale": "No explicit employee turnover/attrition rate was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Attrition evidence", "available": True, **result,
        "rationale": f"{result['turnover_rate_pct']}% employee turnover rate explicitly disclosed -> {result['retained_pct']}% retained, score {result['attrition_stability_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b6_culture(symbol, name=None, force=False):
    """B.6 — Culture: combines the four sub-points (B.6.1 innovation
    focus, B.6.2 compliance orientation, B.6.3 employee morale, B.6.4
    attrition evidence) into a single grounded payload, each sourced from
    real Annual Report text and scored deterministically (no LLM call -
    see tools/culture_scoring.py). Any sub-point the source text doesn't
    explicitly cover is surfaced as unavailable rather than defaulted.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    b61 = compute_b6_1_innovation_focus(sym, name, force=force)
    b62 = compute_b6_2_compliance_orientation(sym, name, force=force)
    b63 = compute_b6_3_employee_morale(sym, name, force=force)
    b64 = compute_b6_4_attrition_evidence(sym, name, force=force)

    parts = []
    if b61.get("innovation_score") is not None:
        parts.append(f"Innovation focus: {b61['innovation_pct']}% innovation-led (score {b61['innovation_score']}/5).")
    if b62.get("compliance_score") is not None:
        parts.append(f"Compliance orientation: {b62['compliance_pct']}% strong (score {b62['compliance_score']}/5).")
    if b63.get("engagement_score") is not None:
        parts.append(f"Employee morale: {b63['engagement_pct']}% evidence-backed engagement (score {b63['engagement_score']}/5).")
    if b64.get("attrition_stability_score") is not None:
        parts.append(f"Attrition evidence: {b64['turnover_rate_pct']}% turnover rate (score {b64['attrition_stability_score']}/5).")
    if not parts:
        parts.append("None of the four sub-points (innovation focus, compliance orientation, employee morale, attrition evidence) were explicitly covered this run.")

    _tags = [t.get("confidence_tag") for t in (b61, b62, b63, b64)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"

    retrieved_ats = [t.get("retrieved_at") for t in (b61, b62, b63, b64) if t.get("retrieved_at")]
    payload = {
        "subpoint_id": "B.6",
        "title": "Culture: innovation focus, compliance orientation, employee morale, attrition evidence",
        "available": True,
        "b6_1": b61, "b6_2": b62, "b6_3": b63, "b6_4": b64,
        "rationale": " ".join(parts),
        "pathway_results": (b61.get("pathway_results") or []) + (b62.get("pathway_results") or []) + (b63.get("pathway_results") or []) + (b64.get("pathway_results") or []),
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


def _fetch_promoter_history(sym, max_quarters=8):
    from tools.shareholding_scraper import get_provider
    return get_provider().fetch_promoter_holding_history(sym, max_quarters=max_quarters) or []


def compute_c1_1_control_levels(symbol, name=None, force=False):
    """C.1.1 - Control levels. Spec formula: Promoter Control Score (1-5).
    Deterministic (no LLM) - the latest quarter's Promoter vs Public
    holding split, banded by promoter %. Sourcing: NSE Corporate Filings
    - Shareholding Pattern - latest quarterly filing - Promoter and
    Promoter Group Holding.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.1.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        history = _fetch_promoter_history(sym, max_quarters=8)
    except Exception as e:
        print(f"[qualitative_engine] C.1.1 fetch failed for {sym}: {e}")
        history = []

    pathway_results = [{
        "pathway_id": "PORTAL-02",
        "source": "NSE Corporate Filings - Shareholding Pattern - latest quarterly filing - Promoter and Promoter Group Holding",
        "result": "CHECKED" if history else "NOT_DISCLOSED",
        "note": None if history else "NSE's live Shareholding Pattern endpoint returned no data for this symbol this run.",
    }]

    if not history:
        payload = {
            "subpoint_id": subpoint_id, "title": "Control levels", "available": True,
            "promoter_pct": None, "public_pct": None, "as_of_quarter": None,
            "control_level": None, "control_score": None,
            "rationale": "NSE's live Shareholding Pattern endpoint returned no data for this symbol this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    latest = history[-1]
    promoter_pct, public_pct = latest["promoter_pct"], latest.get("public_pct")
    if promoter_pct >= 75:
        control_level, control_score = "Majority control", 5
    elif promoter_pct >= 50:
        control_level, control_score = "Majority control", 4
    elif promoter_pct >= 25:
        control_level, control_score = "Significant minority control", 3
    elif promoter_pct >= 10:
        control_level, control_score = "Below significant-influence threshold", 2
    else:
        control_level, control_score = "Below significant-influence threshold", 1

    payload = {
        "subpoint_id": subpoint_id, "title": "Control levels", "available": True,
        "promoter_pct": promoter_pct, "public_pct": public_pct, "as_of_quarter": latest.get("quarter"),
        "control_level": control_level, "control_score": control_score,
        "rationale": f"Promoter holding of {promoter_pct}% as of {latest.get('quarter')} -> {control_level} (score {control_score}/5).",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c1_2_changes_over_time(symbol, name=None, force=False):
    """C.1.2 - Changes over time. Spec formula: Promoter Trend Score
    (1-5). Deterministic (no LLM) - compares promoter holding across up
    to the last 8 quarters (net change, oldest to newest); a
    stable/non-declining trend scores higher than a declining one.
    Sourcing: NSE Corporate Filings - Shareholding Pattern - last 8
    quarters.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.1.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        history = _fetch_promoter_history(sym, max_quarters=8)
    except Exception as e:
        print(f"[qualitative_engine] C.1.2 fetch failed for {sym}: {e}")
        history = []

    pathway_results = [{
        "pathway_id": "PORTAL-02",
        "source": "NSE Corporate Filings - Shareholding Pattern - last 8 quarters",
        "result": "CHECKED" if len(history) >= 2 else "NOT_DISCLOSED",
        "note": None if len(history) >= 2 else "Fewer than 2 quarters of Shareholding Pattern data were available from NSE's live endpoint this run.",
    }]

    if len(history) < 2:
        payload = {
            "subpoint_id": subpoint_id, "title": "Changes over time", "available": True,
            "trend": history or None, "net_change_pct": None, "trend_score": None,
            "rationale": "Fewer than 2 quarters of promoter-holding data were available to compute a trend this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE" if history else "NOT_FOUND")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE" if history else "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    net_change = round(history[-1]["promoter_pct"] - history[0]["promoter_pct"], 2)
    if net_change >= 0:
        trend_score = 5
    elif net_change > -2:
        trend_score = 4
    elif net_change > -5:
        trend_score = 3
    elif net_change > -10:
        trend_score = 2
    else:
        trend_score = 1

    payload = {
        "subpoint_id": subpoint_id, "title": "Changes over time", "available": True,
        "trend": history, "quarters_available": len(history), "net_change_pct": net_change, "trend_score": trend_score,
        "rationale": f"Promoter holding moved {net_change:+.2f} percentage points across the last {len(history)} quarters ({history[0]['quarter']} -> {history[-1]['quarter']}) -> score {trend_score}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c1_3_direction(symbol, name=None, force=False):
    """C.1.3 - Direction (buying/selling). Spec formula: Buying/Selling
    Direction Score (1-5). Deterministic (no LLM) - counts quarter-over-
    quarter increases vs reductions in promoter holding across up to the
    last 8 quarters. A promoter holding perfectly unchanged across every
    available quarter is reported as "Stable" (a real, common signal for
    a large/mature promoter group) rather than forced into a fabricated
    Increased/Reduced split. Sourcing: NSE Corporate Filings -
    Shareholding Pattern - quarterly changes in promoter holding.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.1.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        history = _fetch_promoter_history(sym, max_quarters=8)
    except Exception as e:
        print(f"[qualitative_engine] C.1.3 fetch failed for {sym}: {e}")
        history = []

    pathway_results = [{
        "pathway_id": "PORTAL-02",
        "source": "NSE Corporate Filings - Shareholding Pattern - quarterly changes in promoter holding",
        "result": "CHECKED" if len(history) >= 2 else "NOT_DISCLOSED",
        "note": None if len(history) >= 2 else "Fewer than 2 quarters of Shareholding Pattern data were available from NSE's live endpoint this run.",
    }]

    if len(history) < 2:
        payload = {
            "subpoint_id": subpoint_id, "title": "Direction (buying/selling)", "available": True,
            "increased_count": None, "reduced_count": None, "unchanged_count": None,
            "direction": None, "direction_score": None,
            "rationale": "Fewer than 2 quarters of promoter-holding data were available to determine a direction this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE" if history else "NOT_FOUND")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE" if history else "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    increased = reduced = unchanged = 0
    for i in range(1, len(history)):
        diff = history[i]["promoter_pct"] - history[i - 1]["promoter_pct"]
        if diff > 0.01:
            increased += 1
        elif diff < -0.01:
            reduced += 1
        else:
            unchanged += 1

    if increased + reduced == 0:
        direction, direction_score = "Stable", 3
        rationale = f"Promoter holding was unchanged across all {len(history)} available quarters -> Stable, no buying/selling signal to report (score 3/5)."
    else:
        pct_increased = round(100 * increased / (increased + reduced), 1)
        direction = "Increased" if increased > reduced else ("Reduced" if reduced > increased else "Mixed")
        direction_score = _band_direction_score(pct_increased)
        rationale = f"Promoter holding increased in {increased} vs reduced in {reduced} of {increased + reduced} quarter-over-quarter comparisons ({unchanged} unchanged) -> {direction} (score {direction_score}/5)."

    payload = {
        "subpoint_id": subpoint_id, "title": "Direction (buying/selling)", "available": True,
        "increased_count": increased, "reduced_count": reduced, "unchanged_count": unchanged,
        "direction": direction, "direction_score": direction_score,
        "rationale": rationale,
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def _band_direction_score(pct_increased):
    if pct_increased >= 80:
        return 5
    if pct_increased >= 60:
        return 4
    if pct_increased >= 40:
        return 3
    if pct_increased >= 20:
        return 2
    return 1


def compute_c1_promoter_shareholding(symbol, name=None, force=False):
    """C.1 — Promoter shareholding patterns: combines the three
    sub-points (C.1.1 control levels, C.1.2 changes over time, C.1.3
    direction) into a single grounded payload, each sourced from NSE's
    real Shareholding Pattern filing (corporate-share-holdings-master —
    the actual per-quarter master, not the pledge-data byproduct
    previously used, which was silently empty for zero-pledge
    companies).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    c11 = compute_c1_1_control_levels(sym, name, force=force)
    c12 = compute_c1_2_changes_over_time(sym, name, force=force)
    c13 = compute_c1_3_direction(sym, name, force=force)

    if not c11.get("promoter_pct") and not c12.get("trend") and c13.get("direction") is None:
        payload = {
            "subpoint_id": "C.1",
            "title": "Promoter shareholding patterns: control levels, changes over time, direction (buying/selling)",
            "available": False,
            "reason": "NSE's live Shareholding Pattern endpoint returned no data for this symbol.",
            "pathway_results": (c11.get("pathway_results") or []) + (c12.get("pathway_results") or []) + (c13.get("pathway_results") or []),
        }
        write_qualitative(sym, "C.1", payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    parts = []
    if c11.get("control_score") is not None:
        parts.append(f"Control levels: {c11['promoter_pct']}% promoter holding ({c11['control_level']}, score {c11['control_score']}/5).")
    if c12.get("trend_score") is not None:
        parts.append(f"Changes over time: {c12['net_change_pct']:+.2f}pp over {c12['quarters_available']} quarters (score {c12['trend_score']}/5).")
    if c13.get("direction_score") is not None:
        parts.append(f"Direction: {c13['direction']} (score {c13['direction_score']}/5).")
    if not parts:
        parts.append("None of the three sub-points (control levels, changes over time, direction) were explicitly covered this run.")

    _tags = [t.get("confidence_tag") for t in (c11, c12, c13)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (c11, c12, c13) if t.get("retrieved_at")]

    # Backward-compatible top-level fields (existing callers like C.2 don't
    # depend on these, but keep the shape stable for anything that does).
    payload = {
        "subpoint_id": "C.1",
        "title": "Promoter shareholding patterns: control levels, changes over time, direction (buying/selling)",
        "available": True,
        "promoter_holding_pct": c11.get("promoter_pct"),
        "as_of_quarter": c11.get("as_of_quarter"),
        "control_level": c11.get("control_level"),
        "c1_1": c11, "c1_2": c12, "c1_3": c13,
        "rationale": " ".join(parts),
        "pathway_results": (c11.get("pathway_results") or []) + (c12.get("pathway_results") or []) + (c13.get("pathway_results") or []),
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


def _fetch_current_pledge(sym):
    from tools.shareholding_scraper import get_provider
    return get_provider().fetch_pledge(sym) or {}


def compute_c2_1_presence(symbol, name=None, force=False):
    """C.2.1 - Presence of pledging. Spec formula: Pledge Presence Score
    (1-5). Deterministic (no LLM) - a confirmed 0% pledge scores highest;
    any confirmed non-zero pledge is banded down by how much of the
    promoter holding is pledged. Sourcing: NSE Corporate Filings -
    Shareholding Pattern - Promoter and Promoter Group - Pledged /
    Encumbered Shares.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.2.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        pledge = _fetch_current_pledge(sym)
    except Exception as e:
        print(f"[qualitative_engine] C.2.1 fetch failed for {sym}: {e}")
        pledge = {}

    status = pledge.get("status")
    pathway_results = [{
        "pathway_id": "PORTAL-02",
        "source": "NSE Corporate Filings - Shareholding Pattern - Promoter and Promoter Group - Pledged / Encumbered Shares",
        "result": "CHECKED" if status in ("ok", "zero") else "NOT_DISCLOSED",
        "note": None if status in ("ok", "zero") else "NSE's live pledge endpoint was unreachable or returned nothing this run — a real 0% cannot be confirmed, only assumed.",
    }]

    if status not in ("ok", "zero"):
        payload = {
            "subpoint_id": subpoint_id, "title": "Presence of pledging", "available": True,
            "pledge_pct": None, "unpledged_pct": None, "presence_score": None,
            "rationale": "NSE's live pledge endpoint was unreachable this run — presence of pledging cannot be confirmed.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    pledge_pct = pledge.get("promoter_pledge_pct") or 0.0
    if pledge_pct <= 0:
        presence_score = 5
    elif pledge_pct <= 2:
        presence_score = 4
    elif pledge_pct <= 5:
        presence_score = 3
    elif pledge_pct <= 10:
        presence_score = 2
    else:
        presence_score = 1

    payload = {
        "subpoint_id": subpoint_id, "title": "Presence of pledging", "available": True,
        "pledge_pct": round(pledge_pct, 2), "unpledged_pct": round(100 - pledge_pct, 2), "presence_score": presence_score,
        "as_of_quarter": pledge.get("as_of_quarter"),
        "rationale": f"{pledge_pct:.2f}% of promoter shareholding is pledged as of {pledge.get('as_of_quarter') or 'the latest quarter'} (confirmed {'zero' if status == 'zero' else 'non-zero'} — not assumed) -> score {presence_score}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c2_2_size(symbol, name=None, force=False):
    """C.2.2 - Size of pledged shares. Spec formula: Pledge Size Score
    (1-5). Deterministic (no LLM) - the same disclosed pledge % of
    promoter holding, classified Low (<25%) vs High (>=25%) per the
    common analyst threshold. Sourcing: NSE Corporate Filings -
    Shareholding Pattern - pledged shares as % of promoter holding.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.2.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        pledge = _fetch_current_pledge(sym)
    except Exception as e:
        print(f"[qualitative_engine] C.2.2 fetch failed for {sym}: {e}")
        pledge = {}

    status = pledge.get("status")
    pathway_results = [{
        "pathway_id": "PORTAL-02",
        "source": "NSE Corporate Filings - Shareholding Pattern - pledged shares as % of promoter holding",
        "result": "CHECKED" if status in ("ok", "zero") else "NOT_DISCLOSED",
        "note": None if status in ("ok", "zero") else "NSE's live pledge endpoint was unreachable or returned nothing this run.",
    }]

    if status not in ("ok", "zero"):
        payload = {
            "subpoint_id": subpoint_id, "title": "Size of pledged shares", "available": True,
            "pledge_pct": None, "size_classification": None, "size_score": None,
            "rationale": "NSE's live pledge endpoint was unreachable this run — pledge size cannot be confirmed.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    pledge_pct = pledge.get("promoter_pledge_pct") or 0.0
    size_classification = "Low" if pledge_pct < 25 else "High"
    if pledge_pct <= 5:
        size_score = 5
    elif pledge_pct <= 15:
        size_score = 4
    elif pledge_pct <= 25:
        size_score = 3
    elif pledge_pct <= 50:
        size_score = 2
    else:
        size_score = 1

    payload = {
        "subpoint_id": subpoint_id, "title": "Size of pledged shares", "available": True,
        "pledge_pct": round(pledge_pct, 2), "size_classification": size_classification, "size_score": size_score,
        "as_of_quarter": pledge.get("as_of_quarter"),
        "rationale": f"{pledge_pct:.2f}% of promoter holding pledged -> {size_classification} (score {size_score}/5).",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c2_3_trend(symbol, name=None, force=False):
    """C.2.3 - Trend in pledging. Spec formula: Pledge Trend Score (1-5).
    Deterministic (no LLM) - compares pledged % across every quarter NSE
    has an on-record pledge for. NSE only lists a row for quarters where
    SOME pledge existed, so a company with no pledge history at all
    genuinely has no trend to show — reported as unavailable, not a
    fabricated flat-zero line. Sourcing: NSE Corporate Filings -
    Shareholding Pattern - pledged % across multiple quarters.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.2.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.shareholding_scraper import get_provider
        trend = get_provider().fetch_pledge_trend(sym) or []
    except Exception as e:
        print(f"[qualitative_engine] C.2.3 fetch failed for {sym}: {e}")
        trend = []

    pathway_results = [{
        "pathway_id": "PORTAL-02",
        "source": "NSE Corporate Filings - Shareholding Pattern - pledged % across multiple quarters",
        "result": "CHECKED" if len(trend) >= 2 else "NOT_DISCLOSED",
        "note": None if len(trend) >= 2 else "Fewer than 2 quarters with an on-record pledge were available from NSE's live endpoint this run — a company with no pledge history has no trend to show.",
    }]

    if len(trend) < 2:
        payload = {
            "subpoint_id": subpoint_id, "title": "Trend in pledging", "available": True,
            "trend": trend or None, "net_change_pct": None, "trend_score": None,
            "rationale": "Fewer than 2 quarters with an on-record pledge were available to compute a trend this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    net_change = round(trend[-1]["pledge_pct"] - trend[0]["pledge_pct"], 2)
    if net_change <= 0:
        trend_score = 5
    elif net_change <= 2:
        trend_score = 4
    elif net_change <= 5:
        trend_score = 3
    elif net_change <= 10:
        trend_score = 2
    else:
        trend_score = 1

    payload = {
        "subpoint_id": subpoint_id, "title": "Trend in pledging", "available": True,
        "trend": trend, "quarters_available": len(trend), "net_change_pct": net_change, "trend_score": trend_score,
        "rationale": f"Pledge % moved {net_change:+.2f} percentage points across {len(trend)} quarters ({trend[0]['quarter']} -> {trend[-1]['quarter']}) -> score {trend_score}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c2_4_margin_call_risk(symbol, name=None, force=False):
    """C.2.4 - Margin-call risk. Spec formula: Margin-call Risk Score
    (1-5). Deterministic (no LLM) - the same disclosed pledge % of
    promoter holding, classified Low (<25%) vs High (>=25%) margin-call
    risk. Sourcing: NSE Corporate Filings - Shareholding Pattern -
    pledged share disclosures and encumbrance details.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.2.4"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        pledge = _fetch_current_pledge(sym)
    except Exception as e:
        print(f"[qualitative_engine] C.2.4 fetch failed for {sym}: {e}")
        pledge = {}

    status = pledge.get("status")
    pathway_results = [{
        "pathway_id": "PORTAL-02",
        "source": "NSE Corporate Filings - Shareholding Pattern - pledged share disclosures and encumbrance details",
        "result": "CHECKED" if status in ("ok", "zero") else "NOT_DISCLOSED",
        "note": None if status in ("ok", "zero") else "NSE's live pledge endpoint was unreachable or returned nothing this run.",
    }]

    if status not in ("ok", "zero"):
        payload = {
            "subpoint_id": subpoint_id, "title": "Margin-call risk", "available": True,
            "pledge_pct": None, "risk_level": None, "risk_score": None,
            "rationale": "NSE's live pledge endpoint was unreachable this run — margin-call risk cannot be confirmed.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    pledge_pct = pledge.get("promoter_pledge_pct") or 0.0
    risk_level = "Low" if pledge_pct < 25 else "High"
    if pledge_pct < 10:
        risk_score = 5
    elif pledge_pct < 25:
        risk_score = 4
    elif pledge_pct < 50:
        risk_score = 2
    else:
        risk_score = 1

    payload = {
        "subpoint_id": subpoint_id, "title": "Margin-call risk", "available": True,
        "pledge_pct": round(pledge_pct, 2), "risk_level": risk_level, "risk_score": risk_score,
        "as_of_quarter": pledge.get("as_of_quarter"),
        "rationale": f"{pledge_pct:.2f}% of promoter holding pledged -> {risk_level} margin-call risk (score {risk_score}/5).",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c2_promoter_pledging(symbol, name=None, force=False):
    """C.2 — Promoter pledging of shares: combines the four sub-points
    (C.2.1 presence, C.2.2 size, C.2.3 trend, C.2.4 margin-call risk)
    into a single grounded payload, all sourced from NSE's real
    Shareholding Pattern pledge disclosure (tools/shareholding_scraper.py).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    c21 = compute_c2_1_presence(sym, name, force=force)
    c22 = compute_c2_2_size(sym, name, force=force)
    c23 = compute_c2_3_trend(sym, name, force=force)
    c24 = compute_c2_4_margin_call_risk(sym, name, force=force)

    parts = []
    if c21.get("presence_score") is not None:
        parts.append(f"Presence: {c21['pledge_pct']}% pledged (score {c21['presence_score']}/5).")
    if c22.get("size_score") is not None:
        parts.append(f"Size: {c22['size_classification']} (score {c22['size_score']}/5).")
    if c23.get("trend_score") is not None:
        parts.append(f"Trend: {c23['net_change_pct']:+.2f}pp over {c23['quarters_available']} quarters (score {c23['trend_score']}/5).")
    if c24.get("risk_score") is not None:
        parts.append(f"Margin-call risk: {c24['risk_level']} (score {c24['risk_score']}/5).")
    if not parts:
        parts.append("None of the four sub-points (presence, size, trend, margin-call risk) were explicitly covered this run.")

    _tags = [t.get("confidence_tag") for t in (c21, c22, c23, c24)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (c21, c22, c23, c24) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "C.2",
        "title": "Promoter pledging of shares: presence, size, trend and risk if margin calls occur",
        "available": True,
        "pledge_pct": c21.get("pledge_pct"),
        "risk_level": c24.get("risk_level"),
        "assumed_zero": False,
        "c2_1": c21, "c2_2": c22, "c2_3": c23, "c2_4": c24,
        "rationale": " ".join(parts),
        "pathway_results": (c21.get("pathway_results") or []) + (c22.get("pathway_results") or []) + (c23.get("pathway_results") or []) + (c24.get("pathway_results") or []),
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


_C3_SCHEMA_VERSION = 1

# Relationship-type substrings that flag a counterparty as promoter/KMP-
# adjacent. Ind AS 24 vocabulary only (generic across every filer, per
# CLAUDE.md's no-ticker-specific-logic rule) — this ROUTES the row to a
# human analyst as a flag, it never asserts wrongdoing or a conclusion
# (same precedent as C.8's minority-shareholder-treatment handling).
_C3_PROMOTER_KMP_RELATIONSHIP_MARKERS = [
    "promoter", "key management personnel", "kmp", "director", "relative of",
    "managing director", "whole-time director", "chairman", "chief executive",
    "chief financial officer", "company secretary", "enterprise controlled by",
    "enterprise significantly influenced by", "firm in which",
]


def _compute_c3_rpt_records(symbol, name=None, force=False):
    """Internal: LLM-extracted + verbatim-verified RPT rows, shared by
    C.3.1 (frequency) and C.3.2 (counterparty identity) so both sub-
    points reuse the SAME extraction run (and its DB cache) instead of
    re-invoking the LLM row-extraction step twice per report. Formula
    context: RPT intensity = Total RPT value / Total revenue.

    Sourcing Sequence: AR-04 (RPT note) -> AR-05 (group structure) -> PORTAL-05
    (director registry, NOT bio — counterparty cross-check) -> AGG-01 (Tofler,
    fallback/cross-check only).

    AR-04 is now backed by a real fetcher: tools.annual_report_financials.
    fetch_rpt_evidence_from_annual_report locates the Ind AS 24 "Related
    Party Disclosures" note text, and tools.rpt_extractor LLM-extracts
    counterparty/relationship/transaction/amount rows with a mandatory
    verbatim-quote + numeric-anchor guardrail (a row failing either check is
    dropped, never guessed — per CLAUDE.md).

    AR-05 (group structure — subsidiary list / Form AOC-1) has NO parser in
    this codebase; that's a separate, deliberately untouched future build
    (see C.4, the adjacent group-structural-complexity sub-point). Left
    NOT_DISCLOSED here, honestly.

    PORTAL-05 (MCA Company/Director Master Data) has no free, programmatic
    path: the public MCA Company/LLP Master Data search now returns 403
    Forbidden (MCA locked down no-login access in Dec 2025), and no MCA API
    exists. Left NOT_DISCLOSED with that explanation — same class of honest
    limitation as NICHE-14/MCX-LME for A.5's pricing power. No fetcher was
    built for it (there is nothing free to build against).

    AGG-01 (Tofler) stays NOT_CHECKED — fallback/cross-check only, never
    invoked, same as every other fallback-only pathway in this codebase.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.3.records"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None and cached.get("schema_version") == _C3_SCHEMA_VERSION:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    from tools.rpt_extractor import extract_rpt_records

    try:
        rpt_result = extract_rpt_records(sym, name)
    except Exception as e:
        print(f"[qualitative_engine] C.3 RPT extraction failed for {sym}: {e}")
        rpt_result = {"status": "NOT_DISCLOSED", "records": [], "reason": f"Extraction failed: {e}"}

    records = rpt_result.get("records") or []
    ar04_result = "CHECKED" if records else "NOT_DISCLOSED"
    ar04_note = None if records else rpt_result.get("reason")

    # --- Deterministic aggregation (LLM touched only the row extraction
    # step above, same architecture split as A.5's pricing power) ----------
    amounts = [r["amount_cr"] for r in records if r.get("amount_cr") is not None]
    total_rpt_value_cr = round(sum(amounts), 2) if amounts else None

    # Total revenue — reuse the SAME cached AR P&L extraction every other
    # AR-sourced ratio in this codebase uses (_get_extracted_financials),
    # not a second hand-rolled fetch. Only computed if a real fiscal-year
    # figure is available; never estimated.
    total_revenue_cr = None
    try:
        from tools.annual_report_financials import list_annual_report_years, _get_extracted_financials
        years = list_annual_report_years(sym, name) or []
        fy = rpt_result.get("fiscal_year") or (years[0] if years else None)
        if fy:
            parsed = _get_extracted_financials(sym, name, fy, consolidated=True)
            revenue = parsed.get("revenue") if isinstance(parsed, dict) else None
            if revenue and revenue[0]:
                total_revenue_cr = float(revenue[0])
    except Exception as e:
        print(f"[qualitative_engine] C.3 total-revenue fetch failed for {sym}: {e}")

    # RPT intensity % — only when BOTH numerator and denominator are real
    # numbers (per CLAUDE.md: unknown/not-quantifiable values are never
    # converted to zero or a fabricated estimate).
    rpt_intensity_pct = None
    if total_rpt_value_cr is not None and total_revenue_cr:
        rpt_intensity_pct = round((total_rpt_value_cr / total_revenue_cr) * 100, 2)

    # rpt_frequency — a qualitative bucket (None/Occasional/Frequent) rather
    # than the raw validated-row count. Chosen because the raw count is a
    # function of how many distinct rows the AR note happens to enumerate
    # (which varies hugely by filer's disclosure granularity — one filer
    # might list 3 aggregated line items, another 30 individually-named
    # counterparties, for genuinely comparable underlying activity), so a
    # bare count isn't comparable across companies the way a bucket is.
    # This mirrors the existing downstream contract already baked into
    # agent/stock_agent.py's _enum(f36.get('rpt_frequency'), ['None',
    # 'Occasional', 'Frequent']). The raw count is still reported
    # separately (rpt_row_count) for full auditability/testing.
    row_count = len(records)
    if row_count == 0:
        rpt_frequency = None  # not "None" the bucket — genuinely not computed, distinct from a confirmed-zero count
    elif row_count <= 3:
        rpt_frequency = "Occasional"
    else:
        rpt_frequency = "Frequent"

    # counterparty_flags — routes promoter/KMP-adjacent counterparties to a
    # human analyst; never asserts wrongdoing (same precedent as C.8).
    counterparty_flags = []
    seen_flags = set()
    for r in records:
        rel = (r.get("relationship_type") or "").lower()
        if any(m in rel for m in _C3_PROMOTER_KMP_RELATIONSHIP_MARKERS):
            label = f"{r['counterparty']} ({r.get('relationship_type')})"
            if label not in seen_flags:
                seen_flags.add(label)
                counterparty_flags.append(label)

    if records:
        rationale = (
            f"{row_count} related-party transaction row(s) verified against verbatim Annual Report quotes "
            f"({'FY' + str(rpt_result.get('fiscal_year')) if rpt_result.get('fiscal_year') else 'latest available year'}). "
            + (f"RPT intensity ~{rpt_intensity_pct}% of total revenue ({total_rpt_value_cr} Cr of {total_revenue_cr} Cr). "
               if rpt_intensity_pct is not None else
               "RPT intensity not computed — either total RPT value or total revenue could not be confirmed as a real number. ")
            + (f"{len(counterparty_flags)} counterparty flag(s) for human review." if counterparty_flags else "No promoter/KMP-adjacent counterparties flagged among verified rows.")
        )
    else:
        rationale = (
            "Not computed — the Related Party Disclosures note could not be located and/or no row could be "
            "extracted and verified against a verbatim quote in this Annual Report."
            + (f" ({ar04_note})" if ar04_note else "")
        )

    pathway_results = [
        {
            "pathway_id": "AR-04",
            "source": "Related Party Transactions note (Notes to Financial Statements)",
            "result": ar04_result,
            "note": ar04_note,
        },
        {
            "pathway_id": "AR-05",
            "source": "Subsidiaries / group structure (Form AOC-1 + Consolidated Notes)",
            "result": "NOT_DISCLOSED",
            "note": "No AR-05 group-structure parser is wired into this codebase yet (separate future build, tracked under C.4).",
        },
        {
            "pathway_id": "PORTAL-05",
            "source": "MCA Company/Director Master Data (counterparty cross-check, NOT bio)",
            "result": "NOT_DISCLOSED",
            "note": "MCA's public Company/LLP Master Data search returns 403 Forbidden (MCA locked down no-login access, Dec 2025) — no free, programmatic path exists. No fetcher was built; there is nothing free to build against.",
        },
        {
            "pathway_id": "AGG-01",
            "source": "Tofler — Company/Director Search (fallback/cross-check only)",
            "result": "NOT_CHECKED",
            "note": "Cross-check pathway, only used if primary is unavailable or conflicting — not invoked this run.",
        },
    ]

    payload = {
        "subpoint_id": subpoint_id,
        "schema_version": _C3_SCHEMA_VERSION,
        "title": "Related-party transactions (RPTs): frequency, counterparty identity, pricing and rationale",
        "available": True,
        "rpt_intensity_pct": rpt_intensity_pct,
        "rpt_frequency": rpt_frequency,
        "rpt_row_count": row_count,
        "total_rpt_value_cr": total_rpt_value_cr,
        "total_revenue_cr": total_revenue_cr,
        "counterparty_flags": counterparty_flags,
        "records": records,  # {counterparty, relationship_type, transaction_type, amount_cr, quote, fiscal_year}
        "rationale": rationale,
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE" if records else "SEARCH_INCONCLUSIVE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c3_1_frequency(symbol, name=None, force=False):
    """C.3.1 - Frequency of RPTs. Spec formula: RPT Frequency Score
    (1-5). Deterministic (no LLM) - see tools/rpt_disclosure_scoring.py's
    score_rpt_frequency: counts how many DISTINCT canonical Ind AS 24
    transaction-type labels (purchase/sale of goods, remuneration,
    rent, dividends, loans, etc.) appear in the Related Party
    Disclosures note text - a real proxy for RPT frequency/breadth that
    doesn't need per-row counterparty attribution (unlike C.3.2, which
    still needs the LLM row extraction). Sourcing: NSE Corporate Filings
    - Annual Reports - Notes to Accounts - Related Party Disclosures
    (Ind AS 24).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.3.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import fetch_rpt_evidence_from_annual_report
        from tools.rpt_disclosure_scoring import score_rpt_frequency
        evidence = fetch_rpt_evidence_from_annual_report(sym, name)
        excerpt_text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or [])) if isinstance(evidence, dict) else ""
        result = score_rpt_frequency(excerpt_text)
    except Exception as e:
        print(f"[qualitative_engine] C.3.1 fetch failed for {sym}: {e}")
        result = {"distinct_transaction_types": None, "matched_types": None, "frequency_bucket": None, "frequency_score": None}

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Notes to Accounts - Related Party Disclosures (Ind AS 24)",
        "result": "CHECKED" if result["frequency_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["frequency_score"] is not None else "No Related Party Disclosures note with an identifiable Ind AS 24 transaction-type label was located in the latest Annual Report this run.",
    }]

    if result["frequency_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Frequency of RPTs", "available": True, **result,
            "rationale": "No Related Party Disclosures note with an identifiable Ind AS 24 transaction-type label was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Frequency of RPTs", "available": True, **result,
        "rationale": f"{result['distinct_transaction_types']} distinct Ind AS 24 transaction-type(s) explicitly disclosed -> {result['frequency_bucket']} (score {result['frequency_score']}/5).",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c3_2_counterparty_identity(symbol, name=None, force=False):
    """C.3.2 - Counterparty identity. Spec formula: Counterparty Risk
    Score (1-5). Deterministic (no LLM) - see
    tools/rpt_disclosure_scoring.py's score_counterparty_identity: counts
    distinct promoter-group-adjacent (Holding Company, KMP, Senior
    Management, Non-Executive Directors, entities significantly
    influenced by a director) vs independent (Subsidiaries, Associates,
    Joint Ventures, employee-benefit trusts) Ind AS 24 counterparty-
    category labels disclosed in the Related Party Disclosures note - a
    real proxy that doesn't need the LLM's per-row extraction (unlike
    the individual counterparty names in _compute_c3_rpt_records).
    Sourcing: NSE Corporate Filings - Annual Reports - Related Party
    Disclosures - promoter group / subsidiaries / associates.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.3.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import fetch_rpt_evidence_from_annual_report
        from tools.rpt_disclosure_scoring import score_counterparty_identity
        evidence = fetch_rpt_evidence_from_annual_report(sym, name)
        excerpt_text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or [])) if isinstance(evidence, dict) else ""
        result = score_counterparty_identity(excerpt_text)
    except Exception as e:
        print(f"[qualitative_engine] C.3.2 fetch failed for {sym}: {e}")
        result = {"promoter_group_count": None, "independent_count": None, "counterparty_risk_pct": None, "counterparty_risk_score": None}

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Related Party Disclosures - promoter group / subsidiaries / associates",
        "result": "CHECKED" if result["counterparty_risk_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["counterparty_risk_score"] is not None else "No Related Party Disclosures note with an identifiable counterparty-category label was located in the latest Annual Report this run.",
    }]

    if result["counterparty_risk_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Counterparty identity", "available": True, **result,
            "rationale": "No Related Party Disclosures note with an identifiable counterparty-category label was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Counterparty identity", "available": True, **result,
        "rationale": f"{result['independent_count']} independent vs {result['promoter_group_count']} promoter/KMP-adjacent counterparty categor(y/ies) explicitly disclosed -> score {result['counterparty_risk_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c3_3_pricing_fairness(symbol, name=None, force=False):
    """C.3.3 - Pricing and commercial rationale. Spec formula: Pricing
    Fairness Score (1-5). Deterministic (no LLM) - see
    tools/rpt_disclosure_scoring.py's score_pricing_fairness: counts
    sentences in the Related Party Disclosures note explicitly confirming
    arm's-length pricing vs explicitly stating otherwise. Sourcing: NSE
    Corporate Filings - Annual Reports - Related Party Disclosures -
    transaction descriptions and pricing basis.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.3.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import fetch_rpt_evidence_from_annual_report
        from tools.rpt_disclosure_scoring import score_pricing_fairness
        evidence = fetch_rpt_evidence_from_annual_report(sym, name)
        excerpt_text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or [])) if isinstance(evidence, dict) else ""
        result = score_pricing_fairness(excerpt_text)
    except Exception as e:
        print(f"[qualitative_engine] C.3.3 fetch failed for {sym}: {e}")
        result = {"arms_length_count": None, "non_arms_length_count": None, "pricing_fairness_pct": None, "pricing_fairness_score": None}

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Related Party Disclosures - transaction descriptions and pricing basis",
        "result": "CHECKED" if result["pricing_fairness_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["pricing_fairness_score"] is not None else "No explicit arm's-length pricing confirmation or contradiction was located in the Related Party Disclosures note this run — most notes don't restate the pricing basis in prose per line item.",
    }]

    if result["pricing_fairness_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Pricing and commercial rationale", "available": True, **result,
            "rationale": "No explicit arm's-length pricing statement was located in the Related Party Disclosures note this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Pricing and commercial rationale", "available": True, **result,
        "rationale": f"{result['arms_length_count']} statement(s) explicitly confirmed arm's-length pricing vs {result['non_arms_length_count']} stating otherwise -> score {result['pricing_fairness_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c3_4_disclosure_quality(symbol, name=None, force=False):
    """C.3.4 - Disclosure quality of RPTs. Spec formula: RPT Disclosure
    Score (1-5). Deterministic (no LLM) - see
    tools/rpt_disclosure_scoring.py's score_disclosure_quality: an Audit
    Committee / RPT-approval sentence is "Transparent" if it explicitly
    names an approval process (omnibus approval, RPT materiality policy),
    "Opaque" if it flags a red flag (no policy, delayed/missing
    approval). Sourcing: NSE Corporate Filings - Annual Reports - Audit
    Committee Report - Related Party Approval Process.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.3.4"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.ar_table_extractor import extract_text_near_anchors
        from tools.rpt_disclosure_scoring import score_disclosure_quality
        texts = extract_text_near_anchors(sym, name, {"governance": ["audit committee", "related party transactions policy", "omnibus approval"]}, max_pages_per_key=6)
        result = score_disclosure_quality(texts.get("governance", ""))
    except Exception as e:
        print(f"[qualitative_engine] C.3.4 fetch failed for {sym}: {e}")
        result = {"transparent_count": None, "opaque_count": None, "disclosure_quality_pct": None, "disclosure_quality_score": None}

    pathway_results = [{
        "pathway_id": "AR-06",
        "source": "NSE Corporate Filings - Annual Reports - Audit Committee Report - Related Party Approval Process",
        "result": "CHECKED" if result["disclosure_quality_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["disclosure_quality_score"] is not None else "No explicit RPT-approval-process confirmation or red flag was located in the Audit Committee Report this run.",
    }]

    if result["disclosure_quality_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Disclosure quality of RPTs", "available": True, **result,
            "rationale": "No explicit RPT-approval-process disclosure was located in the Audit Committee Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Disclosure quality of RPTs", "available": True, **result,
        "rationale": f"{result['transparent_count']} transparent (approval-process named) vs {result['opaque_count']} opaque (red flag) statement(s) explicitly found -> score {result['disclosure_quality_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c3_related_party_transactions(symbol, name=None, force=False):
    """C.3 — Related-party transactions (RPTs): combines the four
    sub-points (C.3.1 frequency, C.3.2 counterparty identity, C.3.3
    pricing fairness, C.3.4 disclosure quality) into a single grounded
    payload. C.3.1/C.3.2 reuse the same LLM-extracted, verbatim-quote-
    verified RPT rows (_compute_c3_rpt_records); C.3.3/C.3.4 are fully
    deterministic regex scorers over real Annual Report text (no LLM).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    c31 = compute_c3_1_frequency(sym, name, force=force)
    c32 = compute_c3_2_counterparty_identity(sym, name, force=force)
    c33 = compute_c3_3_pricing_fairness(sym, name, force=force)
    c34 = compute_c3_4_disclosure_quality(sym, name, force=force)

    parts = []
    if c31.get("frequency_score") is not None:
        parts.append(f"Frequency: {c31['distinct_transaction_types']} transaction type(s) -> {c31['frequency_bucket']} (score {c31['frequency_score']}/5).")
    if c32.get("counterparty_risk_score") is not None:
        parts.append(f"Counterparty identity: {c32['independent_count']} independent vs {c32['promoter_group_count']} promoter-adjacent (score {c32['counterparty_risk_score']}/5).")
    if c33.get("pricing_fairness_score") is not None:
        parts.append(f"Pricing fairness: {c33['pricing_fairness_pct']}% confirmed arm's length (score {c33['pricing_fairness_score']}/5).")
    if c34.get("disclosure_quality_score") is not None:
        parts.append(f"Disclosure quality: {c34['disclosure_quality_pct']}% transparent (score {c34['disclosure_quality_score']}/5).")
    if not parts:
        parts.append("None of the four sub-points (frequency, counterparty identity, pricing fairness, disclosure quality) were explicitly covered this run.")

    _tags = [t.get("confidence_tag") for t in (c31, c32, c33, c34)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (c31, c32, c33, c34) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "C.3",
        "title": "Related-party transactions (RPTs): frequency, counterparty identity, pricing and rationale",
        "available": True,
        "c3_1": c31, "c3_2": c32, "c3_3": c33, "c3_4": c34,
        "rationale": " ".join(parts),
        "pathway_results": (c31.get("pathway_results") or []) + (c32.get("pathway_results") or []) + (c33.get("pathway_results") or []) + (c34.get("pathway_results") or []),
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


def _fetch_group_entities(sym, name):
    """Internal: the Related Party Disclosures note's own "Subsidiaries
    (Extent of holding)" listing, shared by C.4.2/C.4.3/C.4.4 so all
    three reuse the same AR fetch instead of re-downloading the PDF
    three times per report."""
    from tools.annual_report_financials import fetch_rpt_evidence_from_annual_report
    from tools.group_structure_scoring import extract_group_entities
    evidence = fetch_rpt_evidence_from_annual_report(sym, name)
    text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or [])) if isinstance(evidence, dict) else ""
    return extract_group_entities(text)


def compute_c4_1_offbalance_sheet_vehicles(symbol, name=None, force=False):
    """C.4.1 - Off-balance-sheet vehicles. Spec formula: Off-balance-
    sheet Risk Score (1-5): 5 = no material opaque arrangements
    identified. Deterministic (no LLM) - see
    tools/group_structure_scoring.py's score_offbalance_sheet_risk:
    contingent-liability/commitment/guarantee sentences that name a
    quantified figure are "Disclosed", ones explicitly stating the
    amount cannot be estimated are "Opaque". Sourcing: NSE Corporate
    Filings - Annual Reports - Notes to Accounts - Contingent
    Liabilities & Commitments / Guarantees.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.4.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.ar_table_extractor import extract_text_near_anchors
        from tools.group_structure_scoring import score_offbalance_sheet_risk
        texts = extract_text_near_anchors(sym, name, {"contingent": ["contingent liabilities and commitments", "corporate guarantee", "capital commitments"]}, max_pages_per_key=6)
        result = score_offbalance_sheet_risk(texts.get("contingent", ""))
    except Exception as e:
        print(f"[qualitative_engine] C.4.1 fetch failed for {sym}: {e}")
        result = {"disclosed_count": None, "opaque_count": None, "transparency_pct": None, "offbalance_risk_score": None}

    pathway_results = [{
        "pathway_id": "AR-08",
        "source": "NSE Corporate Filings - Annual Reports - Notes to Accounts - Contingent Liabilities & Commitments / Guarantees",
        "result": "CHECKED" if result["offbalance_risk_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["offbalance_risk_score"] is not None else "No Contingent Liabilities & Commitments note with a quantified or explicitly-unquantifiable figure was located in the latest Annual Report this run.",
    }]

    if result["offbalance_risk_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Off-balance-sheet vehicles", "available": True, **result,
            "rationale": "No Contingent Liabilities & Commitments note with a clear disclosed/opaque signal was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Off-balance-sheet vehicles", "available": True, **result,
        "rationale": f"{result['disclosed_count']} quantified vs {result['opaque_count']} explicitly-unquantifiable off-balance-sheet item(s) found -> score {result['offbalance_risk_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c4_2_spvs(symbol, name=None, force=False):
    """C.4.2 - Special purpose vehicles (SPVs). Spec formula: SPV
    Complexity Score (1-5). Deterministic (no LLM) - see
    tools/group_structure_scoring.py's score_spv_complexity: classifies
    each named group entity in the Subsidiaries listing as an operating
    entity vs an SPV-like Trust/Foundation/Fund. Sourcing: NSE Corporate
    Filings - Annual Reports - List of Subsidiaries / Related Party
    Disclosures - SPV / special-purpose entities.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.4.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.group_structure_scoring import score_spv_complexity
        entities = _fetch_group_entities(sym, name)
        result = score_spv_complexity(entities)
    except Exception as e:
        print(f"[qualitative_engine] C.4.2 fetch failed for {sym}: {e}")
        result = {"operating_count": None, "spv_count": None, "operating_pct": None, "spv_complexity_score": None}

    pathway_results = [{
        "pathway_id": "AR-05",
        "source": "NSE Corporate Filings - Annual Reports - List of Subsidiaries / Related Party Disclosures - SPV / special-purpose entities",
        "result": "CHECKED" if result["spv_complexity_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["spv_complexity_score"] is not None else "No Subsidiaries (Extent of holding) listing with named entities was located in the latest Annual Report this run.",
    }]

    if result["spv_complexity_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Special purpose vehicles (SPVs)", "available": True, **result,
            "rationale": "No Subsidiaries listing with named entities was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Special purpose vehicles (SPVs)", "available": True, **result,
        "rationale": f"{result['operating_count']} operating entities vs {result['spv_count']} SPV-like (Trust/Foundation/Fund) entities explicitly named -> score {result['spv_complexity_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c4_3_subsidiaries_abroad(symbol, name=None, force=False):
    """C.4.3 - Subsidiaries abroad. Spec formula: Offshore Structure
    Score (1-5). Deterministic (no LLM) - see
    tools/group_structure_scoring.py's score_offshore_structure:
    classifies each named group entity as domestic vs overseas (country-
    name hint or a distinctly non-Indian corporate suffix). Sourcing:
    NSE Corporate Filings - Annual Reports - List of Subsidiaries -
    foreign subsidiaries, country of incorporation.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.4.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.group_structure_scoring import score_offshore_structure
        entities = _fetch_group_entities(sym, name)
        result = score_offshore_structure(entities)
    except Exception as e:
        print(f"[qualitative_engine] C.4.3 fetch failed for {sym}: {e}")
        result = {"domestic_count": None, "overseas_count": None, "domestic_pct": None, "offshore_structure_score": None}

    pathway_results = [{
        "pathway_id": "AR-05",
        "source": "NSE Corporate Filings - Annual Reports - List of Subsidiaries - foreign subsidiaries, country of incorporation",
        "result": "CHECKED" if result["offshore_structure_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["offshore_structure_score"] is not None else "No Subsidiaries (Extent of holding) listing with named entities was located in the latest Annual Report this run.",
    }]

    if result["offshore_structure_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Subsidiaries abroad", "available": True, **result,
            "rationale": "No Subsidiaries listing with named entities was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Subsidiaries abroad", "available": True, **result,
        "rationale": f"{result['domestic_count']} domestic vs {result['overseas_count']} overseas group entities explicitly named -> score {result['offshore_structure_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c4_4_group_complexity(symbol, name=None, force=False):
    """C.4.4 - Complexity / transparency of group structure. Spec
    formula: Group Structure Complexity Score (1-5), banded on entity
    count (per tools/group_structure_scoring.py's
    score_group_complexity). Sourcing: NSE Corporate Filings - Annual
    Reports - Corporate Information / Notes to Accounts - Group
    Structure / Subsidiaries / Associates / JVs.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.4.4"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.group_structure_scoring import score_group_complexity
        entities = _fetch_group_entities(sym, name)
        result = score_group_complexity(entities)
    except Exception as e:
        print(f"[qualitative_engine] C.4.4 fetch failed for {sym}: {e}")
        result = {"entity_count": None, "domestic_count": None, "overseas_count": None, "trust_count": None, "group_complexity_score": None}

    pathway_results = [{
        "pathway_id": "AR-05",
        "source": "NSE Corporate Filings - Annual Reports - Corporate Information / Notes to Accounts - Group Structure / Subsidiaries / Associates / JVs",
        "result": "CHECKED" if result["group_complexity_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["group_complexity_score"] is not None else "No Subsidiaries (Extent of holding) listing with named entities was located in the latest Annual Report this run.",
    }]

    if result["group_complexity_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Complexity / transparency of group structure", "available": True, **result,
            "rationale": "No Subsidiaries listing with named entities was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Complexity / transparency of group structure", "available": True, **result,
        "rationale": f"{result['entity_count']} distinct group entities explicitly named ({result['domestic_count']} domestic, {result['overseas_count']} overseas, {result['trust_count']} trust/foundation) -> score {result['group_complexity_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c4_group_structural_complexity(symbol, name=None, force=False):
    """C.4 — Use of complex group entities: combines the four sub-points
    (C.4.1 off-balance-sheet vehicles, C.4.2 SPVs, C.4.3 subsidiaries
    abroad, C.4.4 group structure complexity) into a single grounded
    payload, each sourced from real Annual Report text and scored
    deterministically (no LLM call - see
    tools/group_structure_scoring.py).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    c41 = compute_c4_1_offbalance_sheet_vehicles(sym, name, force=force)
    c42 = compute_c4_2_spvs(sym, name, force=force)
    c43 = compute_c4_3_subsidiaries_abroad(sym, name, force=force)
    c44 = compute_c4_4_group_complexity(sym, name, force=force)

    parts = []
    if c41.get("offbalance_risk_score") is not None:
        parts.append(f"Off-balance-sheet vehicles: {c41['transparency_pct']}% disclosed/quantified (score {c41['offbalance_risk_score']}/5).")
    if c42.get("spv_complexity_score") is not None:
        parts.append(f"SPVs: {c42['operating_pct']}% operating entities (score {c42['spv_complexity_score']}/5).")
    if c43.get("offshore_structure_score") is not None:
        parts.append(f"Subsidiaries abroad: {c43['domestic_pct']}% domestic (score {c43['offshore_structure_score']}/5).")
    if c44.get("group_complexity_score") is not None:
        parts.append(f"Group structure: {c44['entity_count']} entities (score {c44['group_complexity_score']}/5).")
    if not parts:
        parts.append("None of the four sub-points (off-balance-sheet vehicles, SPVs, subsidiaries abroad, group structure complexity) were explicitly covered this run.")

    _tags = [t.get("confidence_tag") for t in (c41, c42, c43, c44)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (c41, c42, c43, c44) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "C.4",
        "title": "Use of complex group entities: off-balance-sheet vehicles, SPVs, subsidiaries abroad",
        "available": True,
        "c4_1": c41, "c4_2": c42, "c4_3": c43, "c4_4": c44,
        "rationale": " ".join(parts),
        "pathway_results": (c41.get("pathway_results") or []) + (c42.get("pathway_results") or []) + (c43.get("pathway_results") or []) + (c44.get("pathway_results") or []),
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


def _fetch_governance_filing(sym):
    from tools.governance_scraper import fetch_latest_governance_filing
    return fetch_latest_governance_filing(sym) or {}


def compute_c5_1_independent_director_quality(symbol, name=None, force=False):
    """C.5.1 - Independent directors' quality. Spec formula: Independent
    Director Quality Score (1-5). Deterministic (no LLM) - see
    tools/board_governance_scoring.py's score_independent_director_quality:
    real board-composition data from NSE's quarterly Corporate Governance
    filing (SEBI LODR Reg. 27), never estimated. Sourcing: NSE Corporate
    Filings - Corporate Governance - Composition of Board of Directors.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.5.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.board_governance_scoring import score_independent_director_quality
        filing = _fetch_governance_filing(sym)
        result = score_independent_director_quality(filing.get("cobod"))
        as_of_quarter = filing.get("as_of_quarter")
    except Exception as e:
        print(f"[qualitative_engine] C.5.1 fetch failed for {sym}: {e}")
        result = {"high_quality_count": None, "standard_count": None, "independent_count": None, "total_directors": None, "quality_pct": None, "quality_score": None}
        as_of_quarter = None

    pathway_results = [{
        "pathway_id": "PORTAL-03",
        "source": "NSE Corporate Filings - Corporate Governance - Composition of Board of Directors",
        "result": "CHECKED" if result["quality_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["quality_score"] is not None else "NSE's live Corporate Governance filing endpoint returned no board-composition data for this symbol this run.",
    }]

    if result["quality_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Independent directors' quality", "available": True, **result,
            "as_of_quarter": as_of_quarter,
            "rationale": "NSE's live Corporate Governance filing endpoint returned no board-composition data for this symbol this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Independent directors' quality", "available": True, **result,
        "as_of_quarter": as_of_quarter,
        "rationale": f"{result['high_quality_count']} of {result['independent_count']} independent director(s) (as of {as_of_quarter}) hold both a committee membership and an independent directorship elsewhere -> score {result['quality_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def _compute_committee_subpoint(sym, subpoint_id, title, committee_name, pathway_source, force):
    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.board_governance_scoring import score_committee_effectiveness
        filing = _fetch_governance_filing(sym)
        composition = (filing.get("coc") or {}).get(committee_name) or []
        meetings = [m for m in (filing.get("meetingcomm") or []) if m.get("commName") == committee_name]
        result = score_committee_effectiveness(composition, meetings)
        as_of_quarter = filing.get("as_of_quarter")
    except Exception as e:
        print(f"[qualitative_engine] {subpoint_id} fetch failed for {sym}: {e}")
        result = {"independent_members": None, "total_members": None, "independence_pct": None,
                  "meetings_held": None, "meetings_quorum_met": None, "quorum_met_pct": None, "effectiveness_score": None}
        as_of_quarter = None

    pathway_results = [{
        "pathway_id": "PORTAL-03",
        "source": pathway_source,
        "result": "CHECKED" if result["effectiveness_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["effectiveness_score"] is not None else f"NSE's live Corporate Governance filing endpoint had no {committee_name} composition or meeting data for this quarter.",
    }]

    if result["effectiveness_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": title, "available": True, **result,
            "as_of_quarter": as_of_quarter,
            "rationale": f"No {committee_name} composition or meeting data was located in NSE's live Corporate Governance filing this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    parts = []
    if result["independence_pct"] is not None:
        parts.append(f"{result['independent_members']}/{result['total_members']} members independent ({result['independence_pct']}%)")
    if result["quorum_met_pct"] is not None:
        parts.append(f"quorum met in {result['meetings_quorum_met']}/{result['meetings_held']} meeting(s) ({result['quorum_met_pct']}%)")
    payload = {
        "subpoint_id": subpoint_id, "title": title, "available": True, **result,
        "as_of_quarter": as_of_quarter,
        "rationale": f"{title} as of {as_of_quarter}: " + "; ".join(parts) + f" -> score {result['effectiveness_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c5_2_audit_committee_activity(symbol, name=None, force=False):
    """C.5.2 - Audit committee activity. Spec formula: Audit Committee
    Effectiveness Score (1-5). Deterministic (no LLM) - see
    tools/board_governance_scoring.py's score_committee_effectiveness,
    real Audit Committee composition + meeting-attendance data from
    NSE's quarterly Corporate Governance filing. Sourcing: NSE Corporate
    Filings - Corporate Governance - Audit Committee.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    return _compute_committee_subpoint(
        sym, "C.5.2", "Audit committee activity", "Audit Committee",
        "NSE Corporate Filings - Corporate Governance - Audit Committee", force)


def compute_c5_3_nrc_activity(symbol, name=None, force=False):
    """C.5.3 - Nomination & remuneration committee activity. Spec
    formula: NRC Effectiveness Score (1-5). Deterministic (no LLM) - see
    tools/board_governance_scoring.py's score_committee_effectiveness,
    real NRC composition + meeting-attendance data from NSE's quarterly
    Corporate Governance filing. Sourcing: NSE Corporate Filings -
    Corporate Governance - Nomination and Remuneration Committee.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    return _compute_committee_subpoint(
        sym, "C.5.3", "Nomination & remuneration committee activity", "Nomination and Remuneration Committee",
        "NSE Corporate Filings - Corporate Governance - Nomination and Remuneration Committee", force)


def compute_c5_4_board_attendance(symbol, name=None, force=False):
    """C.5.4 - Board attendance and committee participation. Spec
    formula: Board Participation Score = meetings attended / meetings
    held. Deterministic (no LLM) - see
    tools/board_governance_scoring.py's score_board_attendance: real
    per-meeting director-present / board-roster-size data from NSE's
    quarterly Corporate Governance filing. Sourcing: NSE Corporate
    Filings - Annual Reports - Corporate Governance Report - Board
    Meetings / Attendance.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.5.4"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.board_governance_scoring import score_board_attendance
        filing = _fetch_governance_filing(sym)
        result = score_board_attendance(filing.get("bodmeeting"))
        as_of_quarter = filing.get("as_of_quarter")
    except Exception as e:
        print(f"[qualitative_engine] C.5.4 fetch failed for {sym}: {e}")
        result = {"total_present": None, "total_possible": None, "attendance_pct": None, "meetings_count": None, "participation_score": None}
        as_of_quarter = None

    pathway_results = [{
        "pathway_id": "PORTAL-03",
        "source": "NSE Corporate Filings - Corporate Governance - Board Meetings / Attendance",
        "result": "CHECKED" if result["participation_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["participation_score"] is not None else "NSE's live Corporate Governance filing endpoint had no board-meeting attendance data for this symbol this run.",
    }]

    if result["participation_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Board attendance and committee participation", "available": True, **result,
            "as_of_quarter": as_of_quarter,
            "rationale": "No board-meeting attendance data was located in NSE's live Corporate Governance filing this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Board attendance and committee participation", "available": True, **result,
        "as_of_quarter": as_of_quarter,
        "rationale": f"{result['total_present']} of {result['total_possible']} director-attendances explicitly recorded across {result['meetings_count']} board meeting(s) as of {as_of_quarter} ({result['attendance_pct']}%) -> score {result['participation_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c5_board_composition(symbol, name=None, force=False):
    """C.5 — Board composition & independence: combines the four sub-
    points (C.5.1 independent directors' quality, C.5.2 audit committee
    activity, C.5.3 NRC activity, C.5.4 board attendance) into a single
    grounded payload, all sourced from NSE's real quarterly Corporate
    Governance filing (tools/governance_scraper.py) - never estimated.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    c51 = compute_c5_1_independent_director_quality(sym, name, force=force)
    c52 = compute_c5_2_audit_committee_activity(sym, name, force=force)
    c53 = compute_c5_3_nrc_activity(sym, name, force=force)
    c54 = compute_c5_4_board_attendance(sym, name, force=force)

    parts = []
    if c51.get("quality_score") is not None:
        parts.append(f"Independent director quality: {c51['quality_pct']}% high-quality (score {c51['quality_score']}/5).")
    if c52.get("effectiveness_score") is not None:
        parts.append(f"Audit committee: score {c52['effectiveness_score']}/5.")
    if c53.get("effectiveness_score") is not None:
        parts.append(f"NRC: score {c53['effectiveness_score']}/5.")
    if c54.get("participation_score") is not None:
        parts.append(f"Board attendance: {c54['attendance_pct']}% (score {c54['participation_score']}/5).")
    if not parts:
        parts.append("None of the four sub-points (independent director quality, audit committee, NRC, board attendance) were explicitly covered this run.")

    _tags = [t.get("confidence_tag") for t in (c51, c52, c53, c54)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (c51, c52, c53, c54) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "C.5",
        "title": "Board composition & independence: independent directors' quality, committee activity",
        "available": True,
        "c5_1": c51, "c5_2": c52, "c5_3": c53, "c5_4": c54,
        "rationale": " ".join(parts),
        "pathway_results": (c51.get("pathway_results") or []) + (c52.get("pathway_results") or []) + (c53.get("pathway_results") or []) + (c54.get("pathway_results") or []),
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


_C6_MAX_YEARS = 5


def _fetch_years_auditors(sym, name, max_years=_C6_MAX_YEARS):
    """Up to the 5 most recent Annual Reports' auditor signature (the
    Independent Auditor's Report's own "For <Firm>\\nChartered
    Accountants" block), oldest->newest. Shared by C.6.1/C.6.2 so both
    reuse the same multi-year fetch. A year with no resolvable auditor
    name is skipped, not filled with a guess."""
    from tools.annual_report_financials import list_annual_report_years
    from tools.ar_table_extractor import extract_text_near_anchors
    from tools.auditor_scoring import extract_auditor_name
    years = sorted((list_annual_report_years(sym, name) or [])[:max_years])
    out = []
    for fy in years:
        try:
            texts = extract_text_near_anchors(sym, name, {"audit": ["independent auditors report", "chartered accountants", "opinion"]}, fiscal_year=fy, max_pages_per_key=8)
            aname = extract_auditor_name(texts.get("audit", ""))
            if aname:
                out.append({"fiscal_year": fy, "auditor_name": aname})
        except Exception as e:
            print(f"[qualitative_engine] C.6 auditor-name fetch failed for {sym} FY{fy}: {e}")
    return out


def _fetch_latest_audit_opinion_text(sym, name):
    from tools.ar_table_extractor import extract_text_near_anchors
    texts = extract_text_near_anchors(sym, name, {"audit_opinion": ["independent auditors report", "opinion", "basis for opinion", "emphasis of matter", "key audit matters"]}, max_pages_per_key=8)
    return texts.get("audit_opinion", "")


def compute_c6_1_auditor_tenure(symbol, name=None, force=False):
    """C.6.1 - Auditor tenure. Spec formula: Auditor Tenure = continuous
    years of current statutory auditor engagement; classify Long /
    Moderate / Short. Deterministic (no LLM) - see
    tools/auditor_scoring.py's score_auditor_tenure: counts consecutive
    most-recent years with the same auditor firm name in the Independent
    Auditor's Report's own signature block. Sourcing: NSE Corporate
    Filings - Annual Reports - Independent Auditor's Report - Auditor
    name.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.6.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.auditor_scoring import score_auditor_tenure
        years_auditors = _fetch_years_auditors(sym, name)
        result = score_auditor_tenure(years_auditors)
    except Exception as e:
        print(f"[qualitative_engine] C.6.1 fetch failed for {sym}: {e}")
        result = {"current_auditor": None, "tenure_years": None, "tenure_classification": None, "tenure_score": None}
        years_auditors = []

    pathway_results = [{
        "pathway_id": "AR-07",
        "source": "NSE Corporate Filings - Annual Reports - Independent Auditor's Report - Auditor name",
        "result": "CHECKED" if result["tenure_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["tenure_score"] is not None else "No auditor signature block was located across the available Annual Reports this run.",
    }]

    if result["tenure_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Auditor tenure", "available": True, **result,
            "years_covered": [y["fiscal_year"] for y in years_auditors],
            "rationale": "No auditor signature block was located across the available Annual Reports this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Auditor tenure", "available": True, **result,
        "years_covered": [y["fiscal_year"] for y in years_auditors],
        "rationale": f"{result['current_auditor']} has been the statutory auditor for {result['tenure_years']} consecutive year(s) -> {result['tenure_classification']} (score {result['tenure_score']}/5).",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c6_2_auditor_switches(symbol, name=None, force=False):
    """C.6.2 - Auditor switches. Spec formula: Auditor Switch Frequency =
    number of statutory auditor changes over the available multi-year
    window. Deterministic (no LLM) - see tools/auditor_scoring.py's
    score_auditor_switches: counts year-over-year auditor-name changes
    across up to 5 years (a real, if shorter than the spec's 10-year
    ask, window — NSE's Annual Report archive doesn't reliably go back
    further). Sourcing: NSE Corporate Filings - Annual Reports -
    Independent Auditor's Report - Auditor name across years.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.6.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.auditor_scoring import score_auditor_switches
        years_auditors = _fetch_years_auditors(sym, name)
        result = score_auditor_switches(years_auditors)
    except Exception as e:
        print(f"[qualitative_engine] C.6.2 fetch failed for {sym}: {e}")
        result = {"switch_count": None, "years_covered": None, "switch_by_year": None, "switch_score": None}

    pathway_results = [{
        "pathway_id": "AR-07",
        "source": "NSE Corporate Filings - Annual Reports - Independent Auditor's Report - Auditor name across years",
        "result": "CHECKED" if result["switch_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["switch_score"] is not None else "Fewer than 2 years of resolvable auditor-name data were available across the available Annual Reports this run.",
    }]

    if result["switch_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Auditor switches", "available": True, **result,
            "rationale": "Fewer than 2 years of resolvable auditor-name data were available to detect switches this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Auditor switches", "available": True, **result,
        "rationale": f"{result['switch_count']} auditor change(s) detected across {result['years_covered']} year(s) -> score {result['switch_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c6_3_audit_qualifications(symbol, name=None, force=False):
    """C.6.3 - Qualifications in audit reports. Spec formula: Audit
    Qualification Score (1-5): unmodified opinion = highest. Deterministic
    (no LLM) - see tools/auditor_scoring.py's score_audit_opinion:
    classifies the Independent Auditor's Report's own opinion section
    heading ("Basis for Opinion" = clean vs "Basis for Qualified/
    Adverse Opinion" / "Disclaimer of Opinion" = modified). Sourcing:
    NSE Corporate Filings - Annual Reports - Independent Auditor's
    Report - Opinion / Basis for Opinion.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.6.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.auditor_scoring import score_audit_opinion
        opinion_text = _fetch_latest_audit_opinion_text(sym, name)
        result = score_audit_opinion(opinion_text)
    except Exception as e:
        print(f"[qualitative_engine] C.6.3 fetch failed for {sym}: {e}")
        result = {"opinion_type": None, "audit_qualification_score": None}

    pathway_results = [{
        "pathway_id": "AR-07",
        "source": "NSE Corporate Filings - Annual Reports - Independent Auditor's Report - Opinion / Basis for Opinion",
        "result": "CHECKED" if result["audit_qualification_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["audit_qualification_score"] is not None else "No 'Basis for Opinion'-type heading was located in the latest Annual Report this run.",
    }]

    if result["audit_qualification_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Qualifications in audit reports", "available": True, **result,
            "rationale": "No explicit opinion-type heading was located in the latest Annual Report's Independent Auditor's Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Qualifications in audit reports", "available": True, **result,
        "rationale": f"Independent Auditor's Report opinion explicitly classified as {result['opinion_type']} -> score {result['audit_qualification_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c6_4_audit_observations(symbol, name=None, force=False):
    """C.6.4 - Reservations / emphasis of matter. Spec formula: Audit
    Observation Score (1-5): frequency, materiality and recurrence of
    emphasis/reservation matters. Deterministic (no LLM) - see
    tools/auditor_scoring.py's score_audit_observations: counts Key
    Audit Matters and flags an explicit Emphasis of Matter / Material
    Uncertainty paragraph. Sourcing: NSE Corporate Filings - Annual
    Reports - Independent Auditor's Report - Emphasis of Matter /
    Material Uncertainty / Key Audit Matters.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.6.4"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.auditor_scoring import score_audit_observations
        opinion_text = _fetch_latest_audit_opinion_text(sym, name)
        result = score_audit_observations(opinion_text)
    except Exception as e:
        print(f"[qualitative_engine] C.6.4 fetch failed for {sym}: {e}")
        result = {"kam_count": None, "has_emphasis_of_matter": None, "observation_classification": None, "audit_observation_score": None}

    pathway_results = [{
        "pathway_id": "AR-07",
        "source": "NSE Corporate Filings - Annual Reports - Independent Auditor's Report - Emphasis of Matter / Material Uncertainty / Key Audit Matters",
        "result": "CHECKED" if result["audit_observation_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["audit_observation_score"] is not None else "No Key Audit Matters or Emphasis of Matter section was located in the latest Annual Report this run.",
    }]

    if result["audit_observation_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Reservations / emphasis of matter", "available": True, **result,
            "rationale": "No Key Audit Matters or Emphasis of Matter section was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Reservations / emphasis of matter", "available": True, **result,
        "rationale": f"{result['kam_count']} Key Audit Matter(s) explicitly identified; Emphasis of Matter {'present' if result['has_emphasis_of_matter'] else 'not present'} -> {result['observation_classification']} (score {result['audit_observation_score']}/5).",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c6_auditor_relationships(symbol, name=None, force=False):
    """C.6 — Auditor relationships: combines the four sub-points (C.6.1
    auditor tenure, C.6.2 auditor switches, C.6.3 audit qualifications,
    C.6.4 reservations/emphasis of matter) into a single grounded
    payload, each sourced from real, multi-year Annual Report text and
    scored deterministically (no LLM call - see tools/auditor_scoring.py).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    c61 = compute_c6_1_auditor_tenure(sym, name, force=force)
    c62 = compute_c6_2_auditor_switches(sym, name, force=force)
    c63 = compute_c6_3_audit_qualifications(sym, name, force=force)
    c64 = compute_c6_4_audit_observations(sym, name, force=force)

    parts = []
    if c61.get("tenure_score") is not None:
        parts.append(f"Auditor tenure: {c61['tenure_years']} year(s) ({c61['tenure_classification']}, score {c61['tenure_score']}/5).")
    if c62.get("switch_score") is not None:
        parts.append(f"Auditor switches: {c62['switch_count']} over {c62['years_covered']} years (score {c62['switch_score']}/5).")
    if c63.get("audit_qualification_score") is not None:
        parts.append(f"Opinion: {c63['opinion_type']} (score {c63['audit_qualification_score']}/5).")
    if c64.get("audit_observation_score") is not None:
        parts.append(f"Observations: {c64['observation_classification']} (score {c64['audit_observation_score']}/5).")
    if not parts:
        parts.append("None of the four sub-points (auditor tenure, switches, qualifications, observations) were explicitly covered this run.")

    _tags = [t.get("confidence_tag") for t in (c61, c62, c63, c64)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (c61, c62, c63, c64) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "C.6",
        "title": "Auditor relationships: long/short tenure, auditor switches, qualifications/reservations",
        "available": True,
        "c6_1": c61, "c6_2": c62, "c6_3": c63, "c6_4": c64,
        "rationale": " ".join(parts),
        "pathway_results": (c61.get("pathway_results") or []) + (c62.get("pathway_results") or []) + (c63.get("pathway_results") or []) + (c64.get("pathway_results") or []),
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


_C7_SCHEMA_VERSION = 1  # v1: real deterministic multi-year capital-allocation-mix build, replacing the "Not computed" stub


def _compute_c7_cash_flow_mix(symbol, name=None, force=False):
    """Internal: the real multi-year capex/M&A/buyback/dividend cash-flow
    mix, shared by C.7.1-C.7.5 so all five sub-points reuse the SAME
    multi-year fetch (and its DB cache) instead of re-downloading Annual
    Report PDFs five times per report.

    Formula: Capital allocation mix % = Each use of cash / Total cash
    deployed, over a 5-8 year table of capex, M&A spend, buybacks and dividends
    from the Cash Flow Statement.

    Sourcing Sequence: AR-08 (Statement of Cash Flows) -> AGG-01 (fallback/
    cross-check only, NOT invoked).

    Deterministic (no LLM) — same convention as every other C-section row
    built this session. Reuses
    tools.annual_report_financials.fetch_multi_year_cash_flow_items (new,
    mirrors fetch_multi_year_segment_revenue's pattern) for the raw per-year
    capex/dividend/buyback/acquisition figures, then computes each year's
    mix % here.

    Missing-category handling (CLAUDE.md: never convert unknown to zero) —
    per year, `total_deployed` is the sum ONLY over categories that have a
    real (non-None) parsed value that year; a category legitimately absent
    from the filing that year is recorded in `missing_categories` for that
    year and EXCLUDED from both the numerator and denominator, never treated
    as a 0% contributor. This means the mix percentages for a year with a
    missing category describe the mix AMONG the categories that WERE found,
    not a true 4-way split — `missing_categories` makes that limitation
    explicit rather than hiding it.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.7.mix"
    title = "Capital allocation decisions: history of cash deployment and rationale"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None and cached.get("schema_version") == _C7_SCHEMA_VERSION:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    from tools.annual_report_financials import fetch_multi_year_cash_flow_items

    try:
        multi_year = fetch_multi_year_cash_flow_items(sym, name, n_years=6)
    except Exception as e:
        print(f"[qualitative_engine] C.7 multi-year cash-flow fetch failed for {sym}: {e}")
        multi_year = {}

    ar08_checked = bool(multi_year)
    pathway_results = [
        {
            "pathway_id": "AR-08",
            "source": "Statement of Cash Flows (5-8yr capex/M&A/buybacks/dividends breakdown)",
            "result": "CHECKED" if ar08_checked else "NOT_DISCLOSED",
            "note": None if ar08_checked else "No year in the latest fiscal-year window on file yielded a parseable capex/dividend/buyback/acquisition figure from the Cash Flow Statement.",
        },
        {
            "pathway_id": "AGG-01",
            "source": "Screener.in — Cash Flow tab (fallback/cross-check only)",
            "result": "NOT_CHECKED",
            "note": "Cross-check pathway, only used if primary is unavailable or conflicting — not invoked this run.",
        },
    ]

    if not multi_year:
        payload = {
            "subpoint_id": subpoint_id,
            "schema_version": _C7_SCHEMA_VERSION,
            "title": title,
            "available": False,
            "reason": "No Cash Flow Statement year in the latest fiscal-year window on file yielded any of capex/dividend/buyback/acquisition figures.",
            "capital_allocation_mix": None,
            "years_covered": None,
            "rationale": None,
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    categories = ("capex", "acquisition_outflow", "buyback_spend", "dividend_paid")
    category_label = {
        "capex": "Capex", "acquisition_outflow": "M&A", "buyback_spend": "Buybacks", "dividend_paid": "Dividends",
    }

    by_year = []
    for fy in sorted(multi_year.keys()):
        row = multi_year[fy]
        present = {c: row.get(c) for c in categories if row.get(c) is not None}
        missing = [category_label[c] for c in categories if row.get(c) is None]
        total = sum(present.values())
        mix_pct = {c: round((v / total) * 100.0, 1) if total > 0 else None for c, v in present.items()}
        by_year.append({
            "fiscal_year": fy,
            "amounts_cr": {category_label[c]: round(v, 2) for c, v in present.items()},
            "mix_pct": {category_label[c]: mix_pct[c] for c in present},
            "total_deployed_cr": round(total, 2) if total > 0 else None,
            "missing_categories": missing,
        })

    years_covered = [r["fiscal_year"] for r in by_year]

    # Multi-year averages — averaged only over years where that category had
    # a real parsed value (never imputing 0 for a missing year), same
    # "exclude, don't zero" rule as the per-year mix above.
    avg_mix = {}
    buyback_years = []
    acquisition_years = []
    for c in categories:
        vals = [r["mix_pct"].get(category_label[c]) for r in by_year if category_label[c] in r["mix_pct"]]
        vals = [v for v in vals if v is not None]
        avg_mix[category_label[c]] = round(sum(vals) / len(vals), 1) if vals else None
        if c == "buyback_spend":
            buyback_years = [r["fiscal_year"] for r in by_year if r["amounts_cr"].get("Buybacks", 0) and r["amounts_cr"]["Buybacks"] > 0]
        if c == "acquisition_outflow":
            acquisition_years = [r["fiscal_year"] for r in by_year if r["amounts_cr"].get("M&A", 0) and r["amounts_cr"]["M&A"] > 0]

    # Deterministic rationale sentence — built entirely from the computed
    # numbers above, never LLM-authored (matches this build's constraint and
    # every other deterministic C-row this session).
    yr_lo, yr_hi = min(years_covered), max(years_covered)
    parts = [f"Over FY{yr_lo}-FY{yr_hi} ({len(years_covered)} fiscal years with data)"]
    avg_fragments = []
    for c in categories:
        lbl = category_label[c]
        v = avg_mix.get(lbl)
        if v is not None:
            avg_fragments.append(f"{lbl.lower()} averaged {v}% of cash deployed")
    if avg_fragments:
        parts.append(", ".join(avg_fragments))
    if buyback_years:
        parts.append(f"buybacks occurred in FY{', FY'.join(str(y) for y in buyback_years)}")
    if acquisition_years:
        parts.append(f"M&A/acquisition outflow occurred in FY{', FY'.join(str(y) for y in acquisition_years)}")
    rationale = "; ".join(parts) + "."
    if any(r["missing_categories"] for r in by_year):
        rationale += " Note: at least one category was not parseable from the filing in one or more years (see per-year 'missing_categories') — those years' mix % reflects only the categories that WERE found, not a true 4-way split."

    confidence_tag = "SINGLE_SOURCE"

    payload = {
        "subpoint_id": subpoint_id,
        "schema_version": _C7_SCHEMA_VERSION,
        "title": title,
        "available": True,
        "capital_allocation_mix": by_year,
        "years_covered": years_covered,
        "avg_mix_pct": avg_mix,
        "buyback_years": buyback_years,
        "acquisition_years": acquisition_years,
        "rationale": rationale,
        "pathway_results": pathway_results,
    }
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c7_1_capex(symbol, name=None, force=False):
    """C.7.1 - Capital expenditure (capex). Spec formula: Capex
    Execution Score (1-5). Deterministic (no LLM) - see
    tools/capital_allocation_scoring.py's score_capex_type: an MD&A
    capex sentence is "Growth" if it names expansion/new-capacity
    language, "Maintenance/Other" otherwise. Sourcing: NSE Corporate
    Filings - Annual Reports - Cash Flow Statement / Board's Report /
    MD&A - capex plans and rationale.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.7.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.ar_table_extractor import extract_text_near_anchors
        from tools.capital_allocation_scoring import score_capex_type
        texts = extract_text_near_anchors(sym, name, {"capex": ["capital expenditure", "expansion", "greenfield", "de-bottlenecking", "new factory"]}, max_pages_per_key=6)
        result = score_capex_type(texts.get("capex", ""))
    except Exception as e:
        print(f"[qualitative_engine] C.7.1 fetch failed for {sym}: {e}")
        result = {"growth_count": None, "maintenance_count": None, "growth_pct": None, "capex_execution_score": None}

    pathway_results = [{
        "pathway_id": "AR-08",
        "source": "NSE Corporate Filings - Annual Reports - Cash Flow Statement / Board's Report / MD&A - capex plans and rationale",
        "result": "CHECKED" if result["capex_execution_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["capex_execution_score"] is not None else "No capex-related MD&A text with a clear growth/maintenance signal was located in the latest Annual Report this run.",
    }]

    if result["capex_execution_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Capital expenditure (capex)", "available": True, **result,
            "rationale": "No capex-related MD&A text with a clear growth/maintenance signal was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Capital expenditure (capex)", "available": True, **result,
        "rationale": f"{result['growth_count']} growth-oriented vs {result['maintenance_count']} maintenance/other capex statement(s) explicitly found -> score {result['capex_execution_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c7_2_acquisitions(symbol, name=None, force=False):
    """C.7.2 - Acquisitions. Spec formula: Acquisition Discipline Score
    (1-5). Deterministic (no LLM) - see
    tools/capital_allocation_scoring.py's score_acquisition_discipline:
    an acquisition-note sentence is "Strategic" if it names strategic-
    fit/synergy language, "Non-core/Related-party" if it names a
    related-party or divestment signal. Sourcing: NSE Corporate Filings
    - Annual Reports - Business Combination / Acquisition Note.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.7.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.ar_table_extractor import extract_text_near_anchors
        from tools.capital_allocation_scoring import score_acquisition_discipline
        texts = extract_text_near_anchors(sym, name, {"acquisition": ["acquisition", "business combination", "acquired"]}, max_pages_per_key=6)
        result = score_acquisition_discipline(texts.get("acquisition", ""))
    except Exception as e:
        print(f"[qualitative_engine] C.7.2 fetch failed for {sym}: {e}")
        result = {"strategic_count": None, "noncore_count": None, "strategic_pct": None, "acquisition_discipline_score": None}

    pathway_results = [{
        "pathway_id": "AR-09",
        "source": "NSE Corporate Filings - Annual Reports - Business Combination / Acquisition Note",
        "result": "CHECKED" if result["acquisition_discipline_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["acquisition_discipline_score"] is not None else "No acquisition-note text with a clear strategic/non-core signal was located in the latest Annual Report this run — many years have no acquisition activity at all.",
    }]

    if result["acquisition_discipline_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Acquisitions", "available": True, **result,
            "rationale": "No acquisition-note text with a clear strategic/non-core signal was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Acquisitions", "available": True, **result,
        "rationale": f"{result['strategic_count']} strategic vs {result['noncore_count']} non-core/related-party acquisition statement(s) explicitly found -> score {result['acquisition_discipline_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c7_3_buybacks(symbol, name=None, force=False):
    """C.7.3 - Buybacks. Spec formula: Buyback Policy Score (1-5).
    Deterministic (no LLM) - real buyback vs dividend cash outflow mix
    from _compute_c7_cash_flow_mix's multi-year Cash Flow Statement
    data. Sourcing: NSE Corporate Filings - Corporate Actions - Buyback
    / Annual Report - Equity / Buyback disclosures.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.7.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        mix = _compute_c7_cash_flow_mix(sym, name, force=force)
        by_year = mix.get("capital_allocation_mix") or []
        total_buyback = sum(r["amounts_cr"].get("Buybacks", 0) or 0 for r in by_year)
        total_dividend = sum(r["amounts_cr"].get("Dividends", 0) or 0 for r in by_year)
        buyback_years = mix.get("buyback_years") or []
    except Exception as e:
        print(f"[qualitative_engine] C.7.3 fetch failed for {sym}: {e}")
        total_buyback = total_dividend = 0
        buyback_years = []
        by_year = []

    pathway_results = [{
        "pathway_id": "AR-08",
        "source": "NSE Corporate Filings - Corporate Actions - Buyback / Annual Report - Equity / Buyback disclosures",
        "result": "CHECKED" if by_year else "NOT_DISCLOSED",
        "note": None if by_year else "No Cash Flow Statement data was available across the available Annual Reports this run.",
    }]

    if not by_year:
        payload = {
            "subpoint_id": subpoint_id, "title": "Buybacks", "available": True,
            "total_buyback_cr": None, "total_other_returns_cr": None, "buyback_years": None, "buyback_score": None,
            "rationale": "No Cash Flow Statement data was available across the available Annual Reports this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    if not buyback_years:
        # A real, confirmed absence (the multi-year Cash Flow Statement
        # data was checked and no buyback outflow was found) - not the
        # same as "couldn't check". No universal "good/bad" direction:
        # many disciplined capital allocators simply never buy back
        # shares, so this is reported as a fact, not penalized.
        payload = {
            "subpoint_id": subpoint_id, "title": "Buybacks", "available": True,
            "total_buyback_cr": 0.0, "total_other_returns_cr": round(total_dividend, 2), "buyback_years": [], "buyback_score": None,
            "rationale": f"No share buyback outflow was found across the {len(by_year)}-year Cash Flow Statement window on file — {sym} returned capital via dividends only in this window.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SINGLE_SOURCE")
        payload["confidence_tag"] = "SINGLE_SOURCE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    total_returns = total_buyback + total_dividend
    buyback_pct = round(100 * total_buyback / total_returns, 1) if total_returns else None
    # Real, disclosed buyback activity with at least one executed round is
    # itself a policy-consistency signal - banded on how much of total
    # shareholder-return spend it represents.
    buyback_score = _band_score_pct(buyback_pct) if buyback_pct is not None else None

    payload = {
        "subpoint_id": subpoint_id, "title": "Buybacks", "available": True,
        "total_buyback_cr": round(total_buyback, 2), "total_other_returns_cr": round(total_dividend, 2),
        "buyback_years": buyback_years, "buyback_pct": buyback_pct, "buyback_score": buyback_score,
        "rationale": f"₹{round(total_buyback, 2)} cr in buybacks (FY{', FY'.join(str(y) for y in buyback_years)}) vs ₹{round(total_dividend, 2)} cr in dividends over the window -> score {buyback_score}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c7_4_dividends(symbol, name=None, force=False):
    """C.7.4 - Dividends. Spec formula: Dividend Consistency Score (1-5).
    Deterministic (no LLM) - real dividend-paid vs reinvestment/other-
    uses cash outflow mix from _compute_c7_cash_flow_mix's multi-year
    Cash Flow Statement data; consistency = fraction of years in the
    window with a disclosed non-zero dividend payment. Sourcing: NSE
    Corporate Filings - Corporate Actions - Dividend / Annual Report -
    Board's Report - Dividend / Dividend Policy.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.7.4"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        mix = _compute_c7_cash_flow_mix(sym, name, force=force)
        by_year = mix.get("capital_allocation_mix") or []
    except Exception as e:
        print(f"[qualitative_engine] C.7.4 fetch failed for {sym}: {e}")
        by_year = []

    pathway_results = [{
        "pathway_id": "AR-08",
        "source": "NSE Corporate Filings - Corporate Actions - Dividend / Annual Report - Board's Report - Dividend / Dividend Policy",
        "result": "CHECKED" if by_year else "NOT_DISCLOSED",
        "note": None if by_year else "No Cash Flow Statement data was available across the available Annual Reports this run.",
    }]

    if not by_year:
        payload = {
            "subpoint_id": subpoint_id, "title": "Dividends", "available": True,
            "total_dividend_cr": None, "total_reinvestment_cr": None, "years_paid": None, "years_covered": None,
            "consistency_pct": None, "dividend_consistency_score": None,
            "rationale": "No Cash Flow Statement data was available across the available Annual Reports this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    total_dividend = sum(r["amounts_cr"].get("Dividends", 0) or 0 for r in by_year)
    total_reinvestment = sum((r["amounts_cr"].get("Capex", 0) or 0) + (r["amounts_cr"].get("M&A", 0) or 0) for r in by_year)
    years_paid = [r["fiscal_year"] for r in by_year if (r["amounts_cr"].get("Dividends") or 0) > 0]
    consistency_pct = round(100 * len(years_paid) / len(by_year), 1) if by_year else None

    payload = {
        "subpoint_id": subpoint_id, "title": "Dividends", "available": True,
        "total_dividend_cr": round(total_dividend, 2), "total_reinvestment_cr": round(total_reinvestment, 2),
        "years_paid": years_paid, "years_covered": len(by_year),
        "consistency_pct": consistency_pct, "dividend_consistency_score": _band_score_pct(consistency_pct),
        "rationale": f"Dividends paid in {len(years_paid)} of {len(by_year)} year(s) ({consistency_pct}%) -> score {_band_score_pct(consistency_pct)}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c7_5_capital_allocation_rationale(symbol, name=None, force=False):
    """C.7.5 - Capital allocation rationale. Spec formula: Capital
    Allocation Quality Score (1-5). Deterministic (no LLM) - real
    latest-year Growth Investment (capex + M&A) vs Shareholder Return
    (dividends + buybacks) vs Debt Reduction (Cash Flow Statement's own
    "Repayment of borrowings" line) split. Sourcing: NSE Corporate
    Filings - Annual Reports - Board's Report / MD&A - Capital
    Allocation / Dividend / Expansion / Acquisition commentary.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.7.5"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.ar_table_extractor import extract_text_near_anchors
        from tools.capital_allocation_scoring import extract_debt_repayment_cr
        mix = _compute_c7_cash_flow_mix(sym, name, force=force)
        by_year = mix.get("capital_allocation_mix") or []
        latest = by_year[-1] if by_year else None
        growth_investment = None
        shareholder_return = None
        if latest:
            growth_investment = (latest["amounts_cr"].get("Capex", 0) or 0) + (latest["amounts_cr"].get("M&A", 0) or 0)
            shareholder_return = (latest["amounts_cr"].get("Dividends", 0) or 0) + (latest["amounts_cr"].get("Buybacks", 0) or 0)
        texts = extract_text_near_anchors(sym, name, {"debt": ["repayment of borrowings", "repayment of long-term borrowings", "proceeds from borrowings"]}, max_pages_per_key=6)
        debt_reduction = extract_debt_repayment_cr(texts.get("debt", ""))
    except Exception as e:
        print(f"[qualitative_engine] C.7.5 fetch failed for {sym}: {e}")
        growth_investment = shareholder_return = debt_reduction = None
        latest = None

    pathway_results = [{
        "pathway_id": "AR-08",
        "source": "NSE Corporate Filings - Annual Reports - Board's Report / MD&A - Capital Allocation / Dividend / Expansion / Acquisition commentary",
        "result": "CHECKED" if latest else "NOT_DISCLOSED",
        "note": None if latest else "No Cash Flow Statement data was available for the latest fiscal year this run.",
    }]

    if latest is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Capital allocation rationale", "available": True,
            "growth_investment_cr": None, "shareholder_return_cr": None, "debt_reduction_cr": None,
            "fiscal_year": None, "capital_allocation_quality_score": None,
            "rationale": "No Cash Flow Statement data was available for the latest fiscal year this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    # Quality banded on how many of the three real categories were
    # actually disclosed/computable this year - completeness of the
    # capital-allocation picture, not a judgement on the allocation
    # itself (there's no universal "right" split across growth/returns/
    # debt reduction).
    categories_found = sum(1 for v in (growth_investment, shareholder_return, debt_reduction) if v is not None and v > 0)
    completeness_pct = round(100 * categories_found / 3, 1)
    quality_score = _band_score_pct(completeness_pct)

    payload = {
        "subpoint_id": subpoint_id, "title": "Capital allocation rationale", "available": True,
        "growth_investment_cr": round(growth_investment, 2) if growth_investment is not None else None,
        "shareholder_return_cr": round(shareholder_return, 2) if shareholder_return is not None else None,
        "debt_reduction_cr": debt_reduction,
        "fiscal_year": latest["fiscal_year"], "capital_allocation_quality_score": quality_score,
        "rationale": f"FY{latest['fiscal_year']}: ₹{round(growth_investment, 2) if growth_investment is not None else 'N/A'} cr growth investment, ₹{round(shareholder_return, 2) if shareholder_return is not None else 'N/A'} cr shareholder return, ₹{debt_reduction if debt_reduction is not None else 'N/A'} cr debt reduction -> score {quality_score}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c7_capital_allocation(symbol, name=None, force=False):
    """C.7 — Capital allocation decisions: combines the five sub-points
    (C.7.1 capex, C.7.2 acquisitions, C.7.3 buybacks, C.7.4 dividends,
    C.7.5 capital allocation rationale) into a single grounded payload,
    all sourced from real Annual Report text and the real multi-year
    Cash Flow Statement mix (_compute_c7_cash_flow_mix), scored
    deterministically (no LLM call - see
    tools/capital_allocation_scoring.py).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    c71 = compute_c7_1_capex(sym, name, force=force)
    c72 = compute_c7_2_acquisitions(sym, name, force=force)
    c73 = compute_c7_3_buybacks(sym, name, force=force)
    c74 = compute_c7_4_dividends(sym, name, force=force)
    c75 = compute_c7_5_capital_allocation_rationale(sym, name, force=force)

    parts = []
    if c71.get("capex_execution_score") is not None:
        parts.append(f"Capex: {c71['growth_pct']}% growth-oriented (score {c71['capex_execution_score']}/5).")
    if c72.get("acquisition_discipline_score") is not None:
        parts.append(f"Acquisitions: {c72['strategic_pct']}% strategic (score {c72['acquisition_discipline_score']}/5).")
    if c73.get("buyback_score") is not None:
        parts.append(f"Buybacks: {c73.get('buyback_pct')}% of shareholder returns (score {c73['buyback_score']}/5).")
    elif c73.get("buyback_years") == []:
        parts.append("Buybacks: none in the available window (dividends only).")
    if c74.get("dividend_consistency_score") is not None:
        parts.append(f"Dividends: paid in {c74['consistency_pct']}% of years (score {c74['dividend_consistency_score']}/5).")
    if c75.get("capital_allocation_quality_score") is not None:
        parts.append(f"Rationale: FY{c75['fiscal_year']} split disclosed (score {c75['capital_allocation_quality_score']}/5).")
    if not parts:
        parts.append("None of the five sub-points (capex, acquisitions, buybacks, dividends, rationale) were explicitly covered this run.")

    _tags = [t.get("confidence_tag") for t in (c71, c72, c73, c74, c75)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (c71, c72, c73, c74, c75) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "C.7",
        "title": "Capital allocation decisions: history of cash deployment and rationale",
        "available": True,
        "c7_1": c71, "c7_2": c72, "c7_3": c73, "c7_4": c74, "c7_5": c75,
        "rationale": " ".join(parts),
        "pathway_results": (c71.get("pathway_results") or []) + (c72.get("pathway_results") or []) + (c73.get("pathway_results") or []) + (c74.get("pathway_results") or []) + (c75.get("pathway_results") or []),
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


def compute_c8_1_disclosure_quality(symbol, name=None, force=False):
    """C.8.1 - Disclosure quality. Spec formula: Disclosure Quality
    Score (1-5): completeness, specificity, timeliness and consistency
    of material disclosures. Deterministic (no LLM) - see
    tools/minority_treatment_scoring.py's score_disclosure_quality: a
    disclosure-keyword sentence (RPT / Contingent Liabilities /
    Commitments / Corporate Governance Report) is "Detailed" if it names
    a quantified figure, "Limited" if it matches generic boilerplate.
    Sourcing: NSE Corporate Filings - Annual Reports - Corporate
    Governance Report / Notes to Accounts - RPT / Contingent Liabilities
    / Commitments.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.8.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.ar_table_extractor import extract_text_near_anchors
        from tools.minority_treatment_scoring import score_disclosure_quality
        texts = extract_text_near_anchors(sym, name, {"disclosures": ["related party transactions", "contingent liabilities", "commitments", "corporate governance report"]}, max_pages_per_key=8)
        result = score_disclosure_quality(texts.get("disclosures", ""))
    except Exception as e:
        print(f"[qualitative_engine] C.8.1 fetch failed for {sym}: {e}")
        result = {"detailed_count": None, "limited_count": None, "detailed_pct": None, "disclosure_quality_score": None}

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Corporate Governance Report / Notes to Accounts - RPT / Contingent Liabilities / Commitments",
        "result": "CHECKED" if result["disclosure_quality_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["disclosure_quality_score"] is not None else "No RPT/Contingent Liabilities/Commitments text with a clear detailed/limited signal was located in the latest Annual Report this run.",
    }]

    if result["disclosure_quality_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Disclosure quality", "available": True, **result,
            "rationale": "No RPT/Contingent Liabilities/Commitments text with a clear detailed/limited signal was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Disclosure quality", "available": True, **result,
        "rationale": f"{result['detailed_count']} detailed (quantified) vs {result['limited_count']} limited (generic) disclosure statement(s) explicitly found -> score {result['disclosure_quality_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c8_2_minority_voting(symbol, name=None, force=False):
    """C.8.2 - Minority shareholder voting and treatment. Spec formula:
    Minority Treatment Score (1-5): assess contested resolutions, voting
    outcomes. Deterministic (no LLM) - see
    tools/minority_treatment_scoring.py's score_minority_voting: counts
    resolutions explicitly marked Pass vs not-passed in the company's
    own latest AGM/Postal Ballot Scrutinizer's Report. The precise per-
    resolution For/Against vote-% table exists in the same PDF but its
    column layout doesn't survive text extraction reliably enough to
    parse without risk of cross-company misattribution — the Pass/Not-
    Passed outcome is the one figure that extracts unambiguously.
    Sourcing: NSE Corporate Filings - Shareholders' Meetings - Notice /
    Voting Results / Scrutinizer Report.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.8.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.nse_announcements import fetch_announcements, download_pdf_text
        from tools.minority_treatment_scoring import score_minority_voting
        rows = fetch_announcements(sym)
        scrutinizer_url = None
        for row in rows:
            blob = f"{row.get('attchmntText') or ''} {row.get('desc') or ''}".lower()
            url = (row.get("attchmntFile") or "").strip()
            if not url.lower().endswith(".pdf"):
                continue
            if "scrutinizer" in blob and ("result" in blob or "outcome" in blob or "voting" in blob or "postal ballot" in blob or "agm" in blob):
                scrutinizer_url = url
                break
        text = download_pdf_text(scrutinizer_url, max_chars=30000, max_pages=30) if scrutinizer_url else ""
        result = score_minority_voting(text)
    except Exception as e:
        print(f"[qualitative_engine] C.8.2 fetch failed for {sym}: {e}")
        result = {"passed_count": None, "contested_count": None, "pass_pct": None, "minority_treatment_score": None}
        scrutinizer_url = None

    pathway_results = [
        {
            "pathway_id": "PORTAL-03",
            "source": "NSE Corporate Filings - Shareholders' Meetings - Notice / Voting Results / Scrutinizer Report",
            "result": "CHECKED" if result["minority_treatment_score"] is not None else "NOT_DISCLOSED",
            "note": None if result["minority_treatment_score"] is not None else "No resolution outcome was located in the latest AGM/Postal Ballot Scrutinizer's Report this run.",
        },
        {
            "pathway_id": "PORTAL-06",
            "source": "SEBI Enforcement Orders / SCORES (fallback/cross-check only)",
            "result": "NOT_CHECKED",
            "note": "Not invoked this run — a named analyst must run this manually before minority-treatment findings inform any investment decision (human sign-off gate).",
        },
        {
            "pathway_id": "NICHE-20",
            "source": "Proxy Advisory — IiAS / InGovern (fallback/cross-check only)",
            "result": "NOT_CHECKED",
            "note": "IiAS/InGovern proxy research is a paid subscription product by design — not invoked this run.",
        },
    ]

    if result["minority_treatment_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Minority shareholder voting and treatment", "available": True, **result,
            "source_pdf_url": scrutinizer_url,
            "rationale": "No resolution outcome was located in the latest AGM/Postal Ballot Scrutinizer's Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Minority shareholder voting and treatment", "available": True, **result,
        "source_pdf_url": scrutinizer_url,
        "rationale": f"{result['passed_count']} of {result['passed_count'] + result['contested_count']} resolution(s) explicitly passed in the latest Scrutinizer's Report -> score {result['minority_treatment_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c8_4_disclosure_timeliness(symbol, name=None, force=False):
    """C.8.4 - Disclosure consistency and timeliness. Spec formula:
    Disclosure Timeliness Score (1-5): promptness, consistency and
    absence of unexplained disclosure gaps. Deterministic (no LLM) - see
    tools/minority_treatment_scoring.py's score_disclosure_timeliness:
    uses NSE's own "difference" field on each corporate announcement -
    the exchange-recorded gap between the event and its disclosure, a
    real field NSE computes and publishes, not derived here. Sourcing:
    NSE Corporate Filings - Corporate Announcements - material event
    announcements and their timing.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.8.4"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.nse_announcements import fetch_announcements
        from tools.minority_treatment_scoring import score_disclosure_timeliness
        rows = fetch_announcements(sym)[:20]
        result = score_disclosure_timeliness(rows)
    except Exception as e:
        print(f"[qualitative_engine] C.8.4 fetch failed for {sym}: {e}")
        result = {"avg_gap_seconds": None, "max_gap_seconds": None, "events_count": None, "timeliness_score": None, "by_event": None}

    pathway_results = [{
        "pathway_id": "PORTAL-03",
        "source": "NSE Corporate Filings - Corporate Announcements - material event announcements and their timing",
        "result": "CHECKED" if result["timeliness_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["timeliness_score"] is not None else "No corporate announcement with a parseable disclosure-timing gap was located this run.",
    }]

    if result["timeliness_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Disclosure consistency and timeliness", "available": True, **result,
            "rationale": "No corporate announcement with a parseable disclosure-timing gap was located this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Disclosure consistency and timeliness", "available": True, **result,
        "rationale": f"Average disclosure gap of {result['avg_gap_seconds']}s across {result['events_count']} recent material event(s) -> score {result['timeliness_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c8_minority_shareholder_treatment(symbol, name=None, force=False):
    """C.8 — Track record on minority shareholder treatment and
    disclosure habits: combines the three defined sub-points (C.8.1
    disclosure quality, C.8.2 minority voting, C.8.4 disclosure
    timeliness — C.8.3 is intentionally absent, not defined in the spec
    this codebase was given) into a single grounded payload, all sourced
    from real Annual Report text, real AGM Scrutinizer's Report PDFs,
    and NSE's own corporate-announcements timing data (no LLM call - see
    tools/minority_treatment_scoring.py). A SEBI-enforcement-order /
    proxy-advisory search remains an uninvestigated human-sign-off gate
    (see C.8.2's PORTAL-06/NICHE-20 pathway entries) - never silently
    reported as "clean".
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    c81 = compute_c8_1_disclosure_quality(sym, name, force=force)
    c82 = compute_c8_2_minority_voting(sym, name, force=force)
    c84 = compute_c8_4_disclosure_timeliness(sym, name, force=force)

    parts = []
    if c81.get("disclosure_quality_score") is not None:
        parts.append(f"Disclosure quality: {c81['detailed_pct']}% detailed (score {c81['disclosure_quality_score']}/5).")
    if c82.get("minority_treatment_score") is not None:
        parts.append(f"Minority voting: {c82['pass_pct']}% resolutions passed (score {c82['minority_treatment_score']}/5).")
    if c84.get("timeliness_score") is not None:
        parts.append(f"Disclosure timeliness: avg {c84['avg_gap_seconds']}s gap (score {c84['timeliness_score']}/5).")
    parts.append("SEBI enforcement-order and proxy-advisory (IiAS/InGovern) checks have not been run — route to a named analyst before adverse-finding conclusions inform any investment decision.")
    if len(parts) == 1:
        parts.insert(0, "None of the three defined sub-points (disclosure quality, minority voting, disclosure timeliness) were explicitly covered this run.")

    _tags = [t.get("confidence_tag") for t in (c81, c82, c84)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (c81, c82, c84) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "C.8",
        "title": "Track record on minority shareholder treatment and disclosure habits",
        "available": True,
        "c8_1": c81, "c8_2": c82, "c8_4": c84,
        "rationale": " ".join(parts),
        "pathway_results": (c81.get("pathway_results") or []) + (c82.get("pathway_results") or []) + (c84.get("pathway_results") or []),
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


# Fixed 0-100 scale positions per the spec's SPECTRUM_BAR output (e), same
# order/zones for every company — never company-specific. Mixed is a
# CALCULATED outcome of the blend formula, never assigned directly, so it
# has no fixed anchor position of its own.
_CONTRACT_TYPE_POSITION = {
    "transactional": 0, "recurring": 25, "annuity": 50, "long_term_contract": 75,
}
_CONTRACT_TYPE_LABEL = {
    "transactional": "Transactional", "recurring": "Recurring", "annuity": "Annuity",
    "long_term_contract": "Long-term Contract",
}

# v1: full deterministic rewrite of A.3 (previously an ungrounded LLM
# classification with no schema_version at all) — old cached LLM-based
# payloads (revenue_model/contract_dynamics fields, no
# contract_type_label/blend_position) must never be served as if they were
# the new evidence-grounded shape. Same bump-guard pattern as
# _A2E_SCHEMA_VERSION.
# v2: classify_contract_type rewritten to classify off the first matching
# sentence in real document order instead of a fixed Annuity>Recurring>
# Transactional category priority, several anchor/pattern recall fixes
# (paraphrase-robust point-in-time/over-time matching), and the Annuity
# AMC/O&M patterns now require a same-sentence "revenue" co-occurrence to
# reject narrative/case-study mentions — confirmed on MARUTI (previously
# missed its real point-in-time policy entirely) and L&T (previously
# misclassified Annuity off an ESG case-study O&M mention). Old v1 payloads
# reflect the pre-fix logic and must not be served as current.
# v3: excludes the generic Ind AS 115 "satisfied at a point in time OR over
# a period of time" framework/judgement sentence every company's policy
# note includes — confirmed false positive on TCS, which matched that
# boilerplate framework sentence as a definitive Transactional
# classification even though TCS's real revenue is predominantly recognised
# over time. See _GENERIC_FRAMEWORK_RE.
# v4: adds the "recognised when control ... transferred to the customer"
# point-in-time pattern family — confirmed ITC, SUNPHARMA and RELIANCE were
# all returning SEARCH_INCONCLUSIVE even though their real Notes to
# Accounts revenue-recognition text was already being fetched correctly;
# the classifier simply didn't recognize this (extremely common) IFRS
# 15/Ind AS 115 default point-in-time phrasing, which never says "point in
# time" or "over time" literally.
# v5: drops the "control" requirement from the delivery-anchored
# point-in-time pattern — confirmed on ITC, whose real evidence clause had
# "control" clipped off by the AR-scan window boundary, leaving only
# "...is transferred to the customer, which is mainly upon delivery",
# which is unambiguous on its own.
# v6: strips a "<Company Name> Limited/Ltd" page-footer fragment glued onto
# a quote's prefix by the newline-collapse merge — cosmetic-only fix,
# confirmed on ITC ("...2026 ITC Limited same is transferred...").
# v7: when the AR discloses an EXPLICIT Ind AS 115 revenue-timing
# disaggregation table (point-in-time vs over-time, in rupee amounts), that
# numeric split now wins outright instead of falling into the generic
# per-sentence anchor scan — confirmed on CAMS, whose AR literally states
# ~99.3% of revenue is point-in-time, but the old per-sentence scan
# returned Recurring purely because the over-time PHRASE happened to
# co-occur in the same table-derived text, without ever reading the
# figures. See _extract_disaggregation_split.
# v8: adds "transferred to the customer" fetcher anchor + "when...
# delivered/dispatched/shipped" classifier pattern — confirmed on VIP
# Industries (small-cap), whose real point-in-time policy note was never
# even fetched because no existing anchor happened to land near it, and
# used a verb-form phrasing ("...transferred to the customer when the
# products are delivered...") the noun-form "upon delivery" pattern missed.
_A3_SCHEMA_VERSION = 8


def compute_a3_revenue_model_quality(symbol, name=None, description="", force=False):
    """A.3 — Revenue model quality: transactional, recurring, annuity, contract
    length & renewal dynamics. Formula: Contract renewal rate = Contracts renewed /
    Contracts up for renewal.

    Sourcing Sequence: AR-14 (revenue/segment note, reusing the SAME segment
    weights already pulled for A.1 via `_fetch_segment_revenue_context`, plus
    the Ind AS 115 revenue-recognition note text scanned for recognition-
    timing/contract-type language) -> AGG-01 (Screener.in, fallback/
    cross-check only, NOT_CHECKED — same convention as every other A.2.x/A.3
    sub-point that never actually invokes the cross-check pathway).

    Deliberately deterministic (no LLM), same rationale as the A.2.x moat
    factors — reproducible, auditable, avoids the shared Groq/OpenRouter
    quota. See tools/revenue_model_scoring.py for the 3A/3B/3C classifier.

    IMPORTANT DOCUMENTED GAP (same as A.1's AR-13 proxy and A.2.E's
    switching-costs approximation): this codebase has NO structured
    per-segment revenue-recognition-note text extractor. When a company
    reports 2+ segments (via `_fetch_segment_revenue_context`), the SAME
    company-wide AR text-anchor classification is applied to every segment
    — this is a documented best-effort limitation, not genuine per-segment
    differentiation, and is surfaced explicitly in the payload
    (`segment_classification_note`) rather than silently implied. Segments
    are used only for their REVENUE WEIGHTS in the blend formula, never for
    a segment-specific contract-type claim this codebase cannot actually
    substantiate.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "A.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None and cached.get("schema_version") == _A3_SCHEMA_VERSION:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    from tools.revenue_model_scoring import classify_contract_type, extract_renewal_rate_pct
    from tools.annual_report_financials import fetch_revenue_model_evidence_from_annual_report

    try:
        ar_evidence = fetch_revenue_model_evidence_from_annual_report(sym, name)
    except Exception as e:
        print(f"[qualitative_engine] A.3 AR revenue-model evidence fetch failed for {sym}: {e}")
        ar_evidence = {"error": str(e)}
    ar_excerpts = ar_evidence.get("excerpts") or []
    ar_text = "\n".join(e["text"] for e in ar_excerpts)

    classified = classify_contract_type(ar_text)
    renewal = extract_renewal_rate_pct(ar_text)

    if ar_excerpts:
        ar14_result, ar14_note = "CHECKED", None
    elif "error" in ar_evidence:
        ar14_result, ar14_note = "NOT_DISCLOSED", ar_evidence["error"]
    else:
        ar14_result, ar14_note = "NOT_DISCLOSED", ("Annual Report fetched but no Ind AS 115 recognition-timing / "
                                                     "AMC-O&M contract-tenure language located in its text.")

    pathway_results = [
        {
            "pathway_id": "AR-14", "source": "Revenue/segment note — Ind AS 115 revenue recognition policy — PRIMARY",
            "result": ar14_result, "note": ar14_note,
        },
        {
            "pathway_id": "AGG-01", "source": "Screener.in Documents/Financials (fallback/cross-check only)",
            "result": "NOT_CHECKED",
            "note": "Cross-check pathway, only used if primary is unavailable or conflicting — not invoked this run.",
        },
    ]

    # AR-14 segment revenue weights — the SAME reconciled figures used for
    # A.1 row 2, reused here per the spec's explicit "REUSE it, do not
    # rebuild segment extraction" instruction.
    segments_pct, segments_fy = _fetch_segment_revenue_context(sym, name)

    contract_type = classified["contract_type"]
    segment_classification_note = None
    per_segment = None
    if segments_pct and len(segments_pct) >= 2:
        segment_classification_note = (
            "SEGMENT_LEVEL_PROXY: this company reports 2+ segments but no per-segment revenue-recognition-note "
            "text extractor exists in this codebase — the same company-wide Annual Report classification below is "
            "applied to every segment for the revenue-weighted blend. This is a documented best-effort proxy, not "
            "genuine per-segment differentiation (same gap as A.1's AR-13 proxy and A.2.E's switching-costs "
            "approximation)."
        )
        per_segment = [{"label": s["label"], "pct": s["pct"], "contract_type": contract_type} for s in segments_pct]
    else:
        segment_classification_note = "SINGLE_SEGMENT: no reconciled multi-segment revenue note found; classified at company level directly."

    # Revenue-weighted blend (d): sum(segment revenue x segment type
    # position) / total revenue. With the same classification applied to
    # every segment (the documented proxy above), this necessarily collapses
    # to that single type's fixed position when a type WAS classified — the
    # formula is still computed explicitly (not hardcoded to the fixed
    # value) so it stays correct once/if a real per-segment extractor is
    # ever added.
    blend_position = None
    contract_type_label = None
    if contract_type is not None:
        weights = segments_pct if (segments_pct and len(segments_pct) >= 2) else [{"label": "Company", "pct": 100.0}]
        total_weight = sum(s["pct"] for s in weights) or 100.0
        pos = _CONTRACT_TYPE_POSITION[contract_type]
        blend_position = round(sum(s["pct"] * pos for s in weights) / total_weight, 1)

        # Mixed-detection rule (e): Mixed only if the blend isn't within
        # +/-12 of any fixed type position AND no single classified type
        # carries >60% of the revenue-weighted mass. With one classification
        # applied uniformly, mass is always 100% on that type, so this
        # always resolves to the nearest single label today — the check is
        # still run explicitly per the spec rather than skipped, since a
        # future real per-segment extractor could produce a genuine mix.
        nearest_type, nearest_dist = min(
            ((t, abs(blend_position - p)) for t, p in _CONTRACT_TYPE_POSITION.items()), key=lambda x: x[1]
        )
        dominant_mass_pct = 100.0  # single classification applied to all weight, per the documented proxy above
        if nearest_dist <= 12 or dominant_mass_pct > 60:
            contract_type_label = _CONTRACT_TYPE_LABEL[nearest_type]
        else:
            contract_type_label = "Mixed"
            blend_position = 100  # Mixed's own fixed marker position on the 5-zone bar

    confidence_tag = "SEARCH_INCONCLUSIVE" if contract_type is None else "SINGLE_SOURCE"

    payload = {
        "subpoint_id": subpoint_id,
        "schema_version": _A3_SCHEMA_VERSION,
        "title": "Revenue model quality: transactional, recurring, annuity, contract length & renewal dynamics",
        "available": True,
        "contract_type": contract_type,
        "contract_type_label": contract_type_label,
        "blend_position": blend_position,
        "evidence_quote": classified["evidence_quote"],
        "evidence_source": classified["source"],
        "rationale": classified["reasoning"],
        "contract_renewal_rate_pct": renewal["renewal_rate_pct"],
        "renewal_rate_evidence_quote": renewal["evidence_quote"],
        "segments": per_segment,
        "segment_fiscal_year": segments_fy,
        "segment_classification_note": segment_classification_note,
        "pathway_results": pathway_results,
    }

    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


# ---------------------------------------------------------------------------
# D.1 - Promoter / insider activity & market signalling. Deterministic
# (no-LLM) - all four sub-points source from NSE's real Regulation 7(2)
# insider-trading disclosure feed (tools/insider_trading_scraper.py), with
# D.1.2 additionally cross-checking sell dates against real NSE Corporate
# Announcements (tools/nse_announcements.py). See
# tools/insider_activity_scoring.py for the scoring logic.
# ---------------------------------------------------------------------------

def compute_d1_1_selling_frequency(symbol, name=None, force=False):
    """D.1.1 - Frequency of insider selling. Spec formula: number of
    insider sale events per 8 quarters, banded 1-5 (5=none/rare,
    1=frequent/repeated). Sourcing: NSE Corporate Filings - Insider
    Trading - Regulation 7(2) disclosures, last 8 quarters.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "D.1.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.insider_trading_scraper import fetch_insider_trades
        from tools.insider_activity_scoring import score_selling_frequency
        rows = fetch_insider_trades(sym, quarters=8)
        result = score_selling_frequency(rows if rows else None)
    except Exception as e:
        print(f"[qualitative_engine] D.1.1 fetch failed for {sym}: {e}")
        result = {"sell_count": None, "quarter_trend": None, "frequency_score": None}
        rows = []

    pathway_results = [{
        "pathway_id": "PORTAL-07",
        "source": "NSE Corporate Filings - Insider Trading - Regulation 7(2) disclosures",
        "result": "CHECKED" if rows else "NOT_DISCLOSED",
        "note": None if rows else "No Regulation 7(2) insider-trading disclosure was located for the last 8 quarters this run.",
    }]

    if result["frequency_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Frequency of insider selling", "available": True, **result,
            "rationale": "No Regulation 7(2) insider-trading disclosure was located for the last 8 quarters this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Frequency of insider selling", "available": True, **result,
        "rationale": f"{result['sell_count']} insider sell disclosure(s) explicitly recorded across the last 8 quarters -> score {result['frequency_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_d1_2_selling_timing(symbol, name=None, force=False):
    """D.1.2 - Timing of insider selling. Spec formula: Timing Risk Score
    (1-5) - assesses whether sales cluster around sensitive periods
    (financial results, M&A, buyback, etc), never inferring intent
    without evidence - purely a date-proximity check against real, dated
    NSE Corporate Announcements. Sourcing: NSE Corporate Filings -
    Insider Trading - Regulation 7(2), cross-checked against NSE
    Corporate Announcements over the same window.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "D.1.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.insider_trading_scraper import fetch_insider_trades
        from tools.nse_announcements import fetch_announcements
        from tools.insider_activity_scoring import score_selling_timing, _sell_rows
        rows = fetch_insider_trades(sym, quarters=8)
        sells = _sell_rows(rows)
        announcements = fetch_announcements(sym) if sells else []
        result = score_selling_timing(sells, announcements)
    except Exception as e:
        print(f"[qualitative_engine] D.1.2 fetch failed for {sym}: {e}")
        result = {"near_sensitive_count": None, "total_sells": None, "timing_events": None, "timing_risk_score": None}
        sells = []

    pathway_results = [
        {
            "pathway_id": "PORTAL-07",
            "source": "NSE Corporate Filings - Insider Trading - Regulation 7(2) disclosures",
            "result": "CHECKED" if sells else "NOT_DISCLOSED",
            "note": None if sells else "No insider sell disclosure was located for the last 8 quarters this run.",
        },
        {
            "pathway_id": "PORTAL-02",
            "source": "NSE Corporate Announcements - financial results / M&A / buyback events, cross-checked by date against insider sell disclosures",
            "result": "CHECKED" if result["timing_risk_score"] is not None else "NOT_DISCLOSED",
            "note": None,
        },
    ]

    if result["timing_risk_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Timing of insider selling", "available": True, **result,
            "rationale": "No insider sell disclosure with a parseable transaction date was located for the last 8 quarters this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Timing of insider selling", "available": True, **result,
        "rationale": f"{result['near_sensitive_count']} of {result['total_sells']} insider sell(s) explicitly fell within 7 days of a real financial-results/M&A/buyback announcement -> score {result['timing_risk_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_d1_3_selling_size(symbol, name=None, force=False):
    """D.1.3 - Size of insider selling. Spec formula: Insider Sale Size %
    = Shares Sold / Insider Holding Before Sale x 100, classified Low/
    Moderate/High relative to holding. Sourcing: NSE Corporate Filings -
    Insider Trading - Regulation 7(2) disclosures, shares sold and
    before-holding figures.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "D.1.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.insider_trading_scraper import fetch_insider_trades
        from tools.insider_activity_scoring import score_selling_size, _sell_rows
        rows = fetch_insider_trades(sym, quarters=8)
        sells = _sell_rows(rows)
        result = score_selling_size(sells)
    except Exception as e:
        print(f"[qualitative_engine] D.1.3 fetch failed for {sym}: {e}")
        result = {"avg_sale_size_pct": None, "classification": None, "size_score": None, "events_used": 0}
        sells = []

    pathway_results = [{
        "pathway_id": "PORTAL-07",
        "source": "NSE Corporate Filings - Insider Trading - Regulation 7(2) disclosures - shares sold vs holding before sale",
        "result": "CHECKED" if result["size_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["size_score"] is not None else "No insider sell disclosure with a usable before-holding figure was located this run.",
    }]

    if result["size_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Size of insider selling", "available": True, **result,
            "rationale": "No insider sell disclosure with a usable before-holding figure was located for the last 8 quarters this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Size of insider selling", "available": True, **result,
        "rationale": f"Insider sell(s) explicitly averaged {result['avg_sale_size_pct']}% of the seller's pre-sale holding across {result['events_used']} disclosure(s) -> {result['classification']} (score {result['size_score']}/5).",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_d1_4_selling_rationale(symbol, name=None, force=False):
    """D.1.4 - Rationale for insider selling. Spec formula: Rationale
    Score (1-5) - a documented liquidity/tax/diversification rationale in
    the disclosure's own remarks field scores higher than unexplained or
    repeated sales. Sourcing: NSE Corporate Filings - Insider Trading -
    Regulation 7(2) disclosure attachment - transaction remarks/reason.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "D.1.4"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.insider_trading_scraper import fetch_insider_trades
        from tools.insider_activity_scoring import score_selling_rationale, _sell_rows
        rows = fetch_insider_trades(sym, quarters=8)
        sells = _sell_rows(rows)
        result = score_selling_rationale(sells)
    except Exception as e:
        print(f"[qualitative_engine] D.1.4 fetch failed for {sym}: {e}")
        result = {"documented_count": None, "unexplained_count": None, "documented_pct": None, "rationale_score": None}
        sells = []

    pathway_results = [{
        "pathway_id": "PORTAL-07",
        "source": "NSE Corporate Filings - Insider Trading - Regulation 7(2) disclosure attachment - transaction remarks/reason",
        "result": "CHECKED" if result["rationale_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["rationale_score"] is not None else "No insider sell disclosure was located for the last 8 quarters this run.",
    }]

    if result["rationale_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Rationale for insider selling", "available": True, **result,
            "rationale": "No insider sell disclosure was located for the last 8 quarters this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Rationale for insider selling", "available": True, **result,
        "rationale": f"{result['documented_count']} of {result['documented_count'] + result['unexplained_count']} insider sell(s) explicitly documented a liquidity/tax/diversification-type reason in the disclosure's own remarks field -> score {result['rationale_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_d1_insider_activity(symbol, name=None, force=False):
    """D.1 - Promoter/insider activity & market signalling: combines the
    four defined sub-points (D.1.1 frequency, D.1.2 timing, D.1.3 size,
    D.1.4 rationale) into a single grounded payload, all sourced from
    NSE's real Regulation 7(2) insider-trading disclosure feed and (for
    D.1.2) NSE's own Corporate Announcements - no LLM call, see
    tools/insider_activity_scoring.py.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    d1_1 = compute_d1_1_selling_frequency(sym, name, force=force)
    d1_2 = compute_d1_2_selling_timing(sym, name, force=force)
    d1_3 = compute_d1_3_selling_size(sym, name, force=force)
    d1_4 = compute_d1_4_selling_rationale(sym, name, force=force)

    parts = []
    if d1_1.get("frequency_score") is not None:
        parts.append(f"Frequency: {d1_1['sell_count']} sell(s) in 8 quarters (score {d1_1['frequency_score']}/5).")
    if d1_2.get("timing_risk_score") is not None:
        parts.append(f"Timing: {d1_2['near_sensitive_count']}/{d1_2['total_sells']} near a sensitive period (score {d1_2['timing_risk_score']}/5).")
    if d1_3.get("size_score") is not None:
        parts.append(f"Size: avg {d1_3['avg_sale_size_pct']}% of holding, {d1_3['classification']} (score {d1_3['size_score']}/5).")
    if d1_4.get("rationale_score") is not None:
        parts.append(f"Rationale: {d1_4['documented_pct']}% documented (score {d1_4['rationale_score']}/5).")
    if not parts:
        parts.append("No Regulation 7(2) insider-trading disclosure was located for this company across the last 8 quarters this run.")

    _tags = [t.get("confidence_tag") for t in (d1_1, d1_2, d1_3, d1_4)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (d1_1, d1_2, d1_3, d1_4) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "D.1",
        "title": "Promoter / insider activity & market signalling",
        "available": True,
        "d1_1": d1_1, "d1_2": d1_2, "d1_3": d1_3, "d1_4": d1_4,
        "rationale": " ".join(parts),
        "pathway_results": (d1_1.get("pathway_results") or []) + (d1_2.get("pathway_results") or [])[-1:] + (d1_3.get("pathway_results") or []) + (d1_4.get("pathway_results") or []),
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


# ---------------------------------------------------------------------------
# D.2 - Insider buying: sign of conviction. Deterministic (no-LLM) - all
# three sub-points source from the same real NSE Regulation 7(2) feed as
# D.1 (tools/insider_trading_scraper.py), filtered to Buy-direction rows.
# See tools/insider_activity_scoring.py for the scoring logic.
# ---------------------------------------------------------------------------

def compute_d2_1_buying_frequency(symbol, name=None, force=False):
    """D.2.1 - Frequency of insider buying. Spec formula: Buying
    Frequency Score (1-5) based on the number and consistency of insider
    purchases. Sourcing: NSE Corporate Filings - Insider Trading -
    Regulation 7(2) disclosures, acquisition/purchase transactions, last
    8 quarters.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "D.2.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.insider_trading_scraper import fetch_insider_trades
        from tools.insider_activity_scoring import score_buying_frequency, _buy_rows
        rows = fetch_insider_trades(sym, quarters=8)
        buys = _buy_rows(rows)
        result = score_buying_frequency(buys if rows else None)
    except Exception as e:
        print(f"[qualitative_engine] D.2.1 fetch failed for {sym}: {e}")
        result = {"buy_count": None, "distinct_quarters": None, "frequency_score": None}
        rows = []

    pathway_results = [{
        "pathway_id": "PORTAL-07",
        "source": "NSE Corporate Filings - Insider Trading - Regulation 7(2) disclosures - acquisition/purchase transactions",
        "result": "CHECKED" if rows else "NOT_DISCLOSED",
        "note": None if rows else "No Regulation 7(2) insider-trading disclosure was located for the last 8 quarters this run.",
    }]

    if result["frequency_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Frequency of insider buying", "available": True, **result,
            "rationale": "No Regulation 7(2) insider-trading disclosure was located for the last 8 quarters this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Frequency of insider buying", "available": True, **result,
        "rationale": f"{result['buy_count']} insider buy disclosure(s) explicitly recorded across {result['distinct_quarters']} distinct quarter(s) in the last 8 quarters -> score {result['frequency_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_d2_2_buying_size(symbol, name=None, force=False):
    """D.2.2 - Size of insider buying. Spec formula: Buying Size % =
    Shares Acquired / Insider Holding Before Purchase x 100 where data
    permits. Sourcing: NSE Corporate Filings - Insider Trading -
    Regulation 7(2) disclosures, shares acquired and value.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "D.2.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.insider_trading_scraper import fetch_insider_trades
        from tools.insider_activity_scoring import score_buying_size, _buy_rows
        rows = fetch_insider_trades(sym, quarters=8)
        buys = _buy_rows(rows)
        result = score_buying_size(buys)
    except Exception as e:
        print(f"[qualitative_engine] D.2.2 fetch failed for {sym}: {e}")
        result = {"avg_buy_size_pct": None, "acquired_shares_total": None, "remaining_holding_pct": None,
                  "classification": None, "size_score": None, "events_used": 0}

    pathway_results = [{
        "pathway_id": "PORTAL-07",
        "source": "NSE Corporate Filings - Insider Trading - Regulation 7(2) disclosures - shares acquired vs holding before purchase",
        "result": "CHECKED" if result["size_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["size_score"] is not None else "No insider buy disclosure with a usable before-holding figure was located this run.",
    }]

    if result["size_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Size of insider buying", "available": True, **result,
            "rationale": "No insider buy disclosure with a usable before-holding figure was located for the last 8 quarters this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Size of insider buying", "available": True, **result,
        "rationale": f"Insider buy(s) explicitly averaged {result['avg_buy_size_pct']}% of the buyer's pre-purchase holding across {result['events_used']} disclosure(s) -> {result['classification']} (score {result['size_score']}/5).",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_d2_3_buying_conviction(symbol, name=None, force=False):
    """D.2.3 - Repeat buying / conviction pattern. Spec formula:
    Conviction Score (1-5) - repeated open-market buying by relevant
    insiders scores higher than isolated/nominal purchases. Sourcing:
    NSE Corporate Filings - Insider Trading - Regulation 7(2)
    disclosures, repeated purchases by the same insider across quarters.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "D.2.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.insider_trading_scraper import fetch_insider_trades
        from tools.insider_activity_scoring import score_buying_conviction, _buy_rows
        rows = fetch_insider_trades(sym, quarters=8)
        buys = _buy_rows(rows)
        result = score_buying_conviction(buys if rows else None)
    except Exception as e:
        print(f"[qualitative_engine] D.2.3 fetch failed for {sym}: {e}")
        result = {"repeat_buyer_count": None, "repeat_buyers": None, "conviction_score": None}
        rows = []

    pathway_results = [{
        "pathway_id": "PORTAL-07",
        "source": "NSE Corporate Filings - Insider Trading - Regulation 7(2) disclosures - repeated purchases by the same insider across quarters",
        "result": "CHECKED" if rows else "NOT_DISCLOSED",
        "note": None if rows else "No Regulation 7(2) insider-trading disclosure was located for the last 8 quarters this run.",
    }]

    if result["conviction_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Repeat buying / conviction pattern", "available": True, **result,
            "rationale": "No Regulation 7(2) insider-trading disclosure was located for the last 8 quarters this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Repeat buying / conviction pattern", "available": True, **result,
        "rationale": f"{result['repeat_buyer_count']} named insider(s) explicitly repeated an open-market/off-market purchase across different quarters in the last 8 quarters -> score {result['conviction_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_d2_insider_buying(symbol, name=None, force=False):
    """D.2 - Insider buying: sign of conviction: combines the three
    defined sub-points (D.2.1 frequency, D.2.2 size, D.2.3 repeat/
    conviction pattern) into a single grounded payload, all sourced from
    the same real NSE Regulation 7(2) insider-trading disclosure feed as
    D.1, filtered to Buy-direction rows - no LLM call, see
    tools/insider_activity_scoring.py.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    d2_1 = compute_d2_1_buying_frequency(sym, name, force=force)
    d2_2 = compute_d2_2_buying_size(sym, name, force=force)
    d2_3 = compute_d2_3_buying_conviction(sym, name, force=force)

    parts = []
    if d2_1.get("frequency_score") is not None:
        parts.append(f"Frequency: {d2_1['buy_count']} buy(s) across {d2_1['distinct_quarters']} quarter(s) (score {d2_1['frequency_score']}/5).")
    if d2_2.get("size_score") is not None:
        parts.append(f"Size: avg {d2_2['avg_buy_size_pct']}% of holding, {d2_2['classification']} (score {d2_2['size_score']}/5).")
    if d2_3.get("conviction_score") is not None:
        parts.append(f"Conviction: {d2_3['repeat_buyer_count']} repeat buyer(s) (score {d2_3['conviction_score']}/5).")
    if not parts:
        parts.append("No Regulation 7(2) insider-trading disclosure was located for this company across the last 8 quarters this run.")

    _tags = [t.get("confidence_tag") for t in (d2_1, d2_2, d2_3)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (d2_1, d2_2, d2_3) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "D.2",
        "title": "Insider buying: sign of conviction",
        "available": True,
        "d2_1": d2_1, "d2_2": d2_2, "d2_3": d2_3,
        "rationale": " ".join(parts),
        "pathway_results": (d2_1.get("pathway_results") or []) + (d2_2.get("pathway_results") or []) + (d2_3.get("pathway_results") or []),
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


# ---------------------------------------------------------------------------
# D.3 - Secondary transactions: placements, preferential allotments -
# dilution concerns. Deterministic (no-LLM) - all three sub-points share one
# real-source lookup: the most recent NSE Corporate Announcement (last 5
# years) whose own desc/attachment-title names a real equity-dilution-type
# transaction (QIP/preferential/private placement - excluding routine
# ESOP/ESPS employee allotments), then its PDF text (the formal "Closure and
# Pricing" / outcome-of-issue SEBI LODR intimation, which routinely states
# issue price, floor price, discount, dilution % and allottee class
# explicitly). See tools/dilution_scoring.py.
# ---------------------------------------------------------------------------

def _find_latest_dilutive_announcement(sym):
    """Shared lookup for all of D.3: scans the last 10 years of NSE
    Corporate Announcements for the most recent one whose own desc/
    attachment-title names a real QIP/preferential/placement transaction
    (not a routine ESOP/ESPS allotment), downloads its PDF text. Returns
    (text, source_url, desc) - text is '' and source_url/desc are None if
    none was found. Never raises."""
    from tools.nse_announcements import fetch_announcements, download_pdf_text
    from tools.dilution_scoring import is_dilutive_announcement
    rows = fetch_announcements(sym) or []
    # D.3 has no spec-mandated lookback window (unlike D.1/D.2's explicit
    # "8 quarters") - widened from an earlier 5-year cutoff to 10, since a
    # material dilution event (confirmed real: HINDUNILVR's 2020 GSK
    # Consumer Healthcare merger, a real ~7.86% dilution) is exactly the
    # kind of history this sub-point should surface, not silently miss
    # for being a year or two outside an arbitrary short window.
    cutoff_year = time.localtime().tm_year - 10
    for row in rows:
        an_dt = row.get("an_dt") or ""
        try:
            yr = int(an_dt.split()[0].split("-")[-1])
        except (ValueError, IndexError):
            yr = None
        if yr is not None and yr < cutoff_year:
            break  # rows are newest-first; nothing older is worth scanning
        if not is_dilutive_announcement(row.get("desc"), row.get("attchmntText")):
            continue
        url = (row.get("attchmntFile") or "").strip()
        text = ""
        # download_pdf_text now handles NSE's .zip wrapper (extracts the
        # first .pdf member) - many older filings are zip-wrapped, so
        # excluding them here would silently skip real, extractable text.
        if url.lower().endswith(".pdf") or url.lower().endswith(".zip"):
            text = download_pdf_text(url, max_chars=15000, max_pages=15)
        if not text:
            # Real fallback, not a last resort hack: NSE's own
            # attchmntText field is often the FULL announcement body, not
            # just a summary - confirmed real: SUZLON's 2014 preferential-
            # issue lock-in clause is a complete, self-contained 784-char
            # paragraph in attchmntText alone, while its attached PDF is a
            # scanned image with zero extractable text (common for older
            # filings). Using it means a scanned/undownloadable PDF no
            # longer silently loses real, already-available text.
            text = (row.get("attchmntText") or "").strip()
            if len(text) < 200:
                text = ""
        if text:
            # Collapse the PDF's own line-wrap newlines to single spaces -
            # confirmed real: a phrase this module's regexes need to match
            # in one span (e.g. "...shareholders who were holding shares
            # of the \nGlaxoSmithKline...") routinely wraps across a real
            # PDF line break, which a raw multi-line string silently
            # breaks any non-DOTALL regex spanning it.
            text = re.sub(r"\s+", " ", text)
            return text, url, row.get("desc")
    return "", None, None


def compute_d3_1_transaction_type(symbol, name=None, force=False):
    """D.3.1 - Placements / preferential allotments. Spec formula:
    Transaction Type Score - classifies as QIP / preferential /
    placement / other and identifies recipient class. Sourcing: NSE
    Corporate Filings - Corporate Announcements - Preferential Issue /
    QIP / Placement / Allotment, last 10 years.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "D.3.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.dilution_scoring import score_transaction_type
        text, source_url, desc = _find_latest_dilutive_announcement(sym)
        result = score_transaction_type(text)
    except Exception as e:
        print(f"[qualitative_engine] D.3.1 fetch failed for {sym}: {e}")
        result = {"transaction_type": None, "recipient_class": None, "disclosure_score": None}
        source_url = None

    pathway_results = [{
        "pathway_id": "PORTAL-02",
        "source": "NSE Corporate Filings - Corporate Announcements - Preferential Issue / QIP / Placement / Allotment, last 10 years",
        "result": "CHECKED" if result["disclosure_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["disclosure_score"] is not None else "No QIP/preferential/private-placement announcement was located for the last 10 years this run.",
    }]

    if result["disclosure_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Placements / preferential allotments", "available": True, **result,
            "rationale": "No QIP/preferential/private-placement announcement was located for the last 10 years this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Placements / preferential allotments", "available": True, **result,
        "source_pdf_url": source_url,
        "rationale": f"Most recent secondary transaction explicitly classified as {result['transaction_type']}"
                     + (f", allotted to {result['recipient_class']}" if result['recipient_class'] else ", recipient class not explicitly stated")
                     + f" -> disclosure score {result['disclosure_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_d3_2_dilution(symbol, name=None, force=False):
    """D.3.2 - Dilution to existing shareholders. Spec formula: Dilution
    % = New Shares Issued / Post-Issue Shares x 100. Sourcing: NSE
    Corporate Filings - Annual Reports - Notes to Equity/Share Capital;
    NSE Corporate Announcements - issue terms and allotment. Reads the
    dilution % directly where the filing itself explicitly states it
    (SEBI ICDR closure/pricing intimations routinely do), rather than
    computing it from two possibly-mismatched share-count sources.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "D.3.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.dilution_scoring import score_dilution
        text, source_url, desc = _find_latest_dilutive_announcement(sym)
        result = score_dilution(text)
    except Exception as e:
        print(f"[qualitative_engine] D.3.2 fetch failed for {sym}: {e}")
        result = {"dilution_pct": None, "shares_issued": None, "classification": None}
        source_url = None

    pathway_results = [{
        "pathway_id": "PORTAL-02",
        "source": "NSE Corporate Filings - Corporate Announcements - issue terms and allotment (dilution % as explicitly stated in the filing)",
        "result": "CHECKED" if result["dilution_pct"] is not None else "NOT_DISCLOSED",
        "note": None if result["dilution_pct"] is not None else "No QIP/preferential/private-placement announcement explicitly stating a dilution % was located for the last 10 years this run.",
    }]

    if result["dilution_pct"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Dilution to existing shareholders", "available": True, **result,
            "rationale": "No QIP/preferential/private-placement announcement explicitly stating a dilution % was located for the last 10 years this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Dilution to existing shareholders", "available": True, **result,
        "source_pdf_url": source_url,
        "rationale": f"Most recent secondary transaction explicitly diluted existing shareholders by {result['dilution_pct']}% of share capital -> {result['classification']}.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_d3_3_pricing_rationale(symbol, name=None, force=False):
    """D.3.3 - Pricing / discount and rationale. Spec formula: Pricing &
    Rationale Score (1-5) based on pricing transparency, purpose and
    investor class. Sourcing: NSE Corporate Filings - Corporate
    Announcements - issue announcement (price, floor/premium, purpose,
    allottee details) and shareholder approval attachment.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "D.3.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.dilution_scoring import score_pricing_rationale
        text, source_url, desc = _find_latest_dilutive_announcement(sym)
        result = score_pricing_rationale(text)
    except Exception as e:
        print(f"[qualitative_engine] D.3.3 fetch failed for {sym}: {e}")
        result = {"issue_price": None, "floor_price": None, "discount_pct": None,
                  "purpose_stated": None, "pricing_rationale_score": None}
        source_url = None

    pathway_results = [{
        "pathway_id": "PORTAL-02",
        "source": "NSE Corporate Filings - Corporate Announcements - issue announcement (price, floor/premium, purpose, allottee details)",
        "result": "CHECKED" if result["pricing_rationale_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["pricing_rationale_score"] is not None else "No QIP/preferential/private-placement announcement was located for the last 10 years this run.",
    }]

    if result["pricing_rationale_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Pricing / discount and rationale", "available": True, **result,
            "rationale": "No QIP/preferential/private-placement announcement was located for the last 10 years this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Pricing / discount and rationale", "available": True, **result,
        "source_pdf_url": source_url,
        "rationale": (f"Issue price ₹{result['issue_price']}" if result['issue_price'] else "Issue price not explicitly stated")
                     + (f" (floor ₹{result['floor_price']}, {result['discount_pct']}% discount)" if result['floor_price'] else "")
                     + (f"; purpose explicitly stated ({result['purpose_stated']})" if result['purpose_stated'] else "; purpose not explicitly stated")
                     + f" -> score {result['pricing_rationale_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_d3_secondary_transactions(symbol, name=None, force=False):
    """D.3 - Secondary transactions: placements, preferential allotments -
    dilution concerns: combines the three defined sub-points (D.3.1
    transaction type, D.3.2 dilution %, D.3.3 pricing/rationale) into a
    single grounded payload, all sourced from the same real NSE Corporate
    Announcement PDF (the formal closure/pricing SEBI LODR intimation) -
    no LLM call, see tools/dilution_scoring.py.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    d3_1 = compute_d3_1_transaction_type(sym, name, force=force)
    d3_2 = compute_d3_2_dilution(sym, name, force=force)
    d3_3 = compute_d3_3_pricing_rationale(sym, name, force=force)

    parts = []
    if d3_1.get("disclosure_score") is not None:
        parts.append(f"Type: {d3_1['transaction_type']} (score {d3_1['disclosure_score']}/5).")
    if d3_2.get("dilution_pct") is not None:
        parts.append(f"Dilution: {d3_2['dilution_pct']}% of share capital ({d3_2['classification']}).")
    if d3_3.get("pricing_rationale_score") is not None:
        parts.append(f"Pricing/rationale: score {d3_3['pricing_rationale_score']}/5.")
    if not parts:
        parts.append("No QIP/preferential/private-placement (equity dilution) announcement was located for this company across the last 10 years this run.")

    _tags = [t.get("confidence_tag") for t in (d3_1, d3_2, d3_3)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (d3_1, d3_2, d3_3) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "D.3",
        "title": "Secondary transactions: placements, preferential allotments — dilution concerns",
        "available": True,
        "d3_1": d3_1, "d3_2": d3_2, "d3_3": d3_3,
        "rationale": " ".join(parts),
        "pathway_results": (d3_1.get("pathway_results") or [])[:1] + (d3_2.get("pathway_results") or [])[:1] + (d3_3.get("pathway_results") or [])[:1],
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


# ---------------------------------------------------------------------------
# D.4 - Lock-in expiries or block share releases: large scheduled sellable
# holdings. Deterministic (no-LLM) - both sub-points share one real-source
# lookup: the most recent NSE Corporate Announcement (no cutoff - full available history) whose
# own text mentions a lock-in clause (an allotment/preferential-issue/IPO-
# related filing). NSE doesn't file a distinct "lock-in expiry" announcement
# type of its own - genuinely sparse, honestly reported N/A when no clause
# with a resolvable date is found, never guessed. See tools/lockin_scoring.py.
# ---------------------------------------------------------------------------

def _find_latest_lockin_announcement(sym):
    """Shared lookup for D.4: scans the company's FULL available NSE
    Corporate Announcements history for the most recent one whose own
    text mentions a lock-in clause, downloads its PDF text. No cutoff
    window (unlike an earlier 5-year version) - D.4 has no spec-mandated
    lookback, and a real lock-in clause is often several years old by the
    time anyone asks about it (confirmed real: SUZLON's only-ever lock-in
    disclosure, a real 2014 preferential-issue lock-in, was silently
    missed under the old 5-year cutoff even though the extraction logic
    itself correctly resolves it to "Expired" - the exact same class of
    bug found and fixed in D.3's lookback window). Returns (text,
    source_url, desc) - text is '' and source_url/desc are None if none
    was found. Never raises."""
    from tools.nse_announcements import fetch_announcements, download_pdf_text
    from tools.lockin_scoring import is_lockin_announcement
    rows = fetch_announcements(sym) or []
    for row in rows:
        if not is_lockin_announcement(row.get("desc"), row.get("attchmntText")):
            continue
        url = (row.get("attchmntFile") or "").strip()
        text = ""
        # download_pdf_text now handles NSE's .zip wrapper (extracts the
        # first .pdf member) - confirmed real: SUZLON's only lock-in
        # disclosure is zip-wrapped, and excluding zips here silently
        # missed it even after the cutoff-window fix.
        if url.lower().endswith(".pdf") or url.lower().endswith(".zip"):
            text = download_pdf_text(url, max_chars=15000, max_pages=15)
        if not text:
            # Real fallback, not a last resort hack: SUZLON's 2014
            # lock-in clause is a complete, self-contained paragraph in
            # NSE's own attchmntText field, while its attached PDF is a
            # scanned image with zero extractable text - see D.3's lookup
            # for the same, first-discovered instance of this gap.
            text = (row.get("attchmntText") or "").strip()
            if len(text) < 200:
                text = ""
        if text:
            # Collapse the PDF's own line-wrap newlines to single spaces -
            # confirmed real: a phrase this module's regexes need to match
            # in one span (e.g. "...shareholders who were holding shares
            # of the \nGlaxoSmithKline...") routinely wraps across a real
            # PDF line break, which a raw multi-line string silently
            # breaks any non-DOTALL regex spanning it.
            text = re.sub(r"\s+", " ", text)
            return text, url, row.get("desc")
    return "", None, None


def compute_d4_1_lockin_status(symbol, name=None, force=False):
    """D.4.1 - Lock-in expiry date. Spec formula: Lock-in Status =
    Upcoming / Expired / Not Applicable; record exact date when
    disclosed. Sourcing: NSE Corporate Filings - Corporate Announcements
    - lock-in/release/listing/allotment/preferential-issue/IPO-related
    filings, full available announcement history.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "D.4.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.lockin_scoring import score_lockin_status
        text, source_url, desc = _find_latest_lockin_announcement(sym)
        result = score_lockin_status(text)
    except Exception as e:
        print(f"[qualitative_engine] D.4.1 fetch failed for {sym}: {e}")
        result = {"lockin_status": None, "lockin_expiry_date": None}
        source_url = None

    pathway_results = [{
        "pathway_id": "PORTAL-02",
        "source": "NSE Corporate Filings - Corporate Announcements - lock-in/release/listing/allotment/preferential-issue/IPO-related filings, full available announcement history",
        "result": "CHECKED" if result["lockin_status"] is not None else "NOT_DISCLOSED",
        "note": None if result["lockin_status"] is not None else "No lock-in clause with a resolvable date was located across NSE Corporate Announcements' full available history this run - NSE files no distinct \"lock-in expiry\" announcement type of its own, so this is a genuinely sparse source, not necessarily evidence of no lock-in event.",
    }]

    if result["lockin_status"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Lock-in expiry date", "available": True, **result,
            "rationale": "No lock-in clause with a resolvable date was located across NSE Corporate Announcements' full available history this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Lock-in expiry date", "available": True, **result,
        "source_pdf_url": source_url,
        "rationale": f"Most recent lock-in clause found explicitly names an expiry date of {result['lockin_expiry_date']} -> {result['lockin_status']}.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_d4_2_sellable_block(symbol, name=None, force=False):
    """D.4.2 - Potential sellable block size. Spec formula: Potential
    Release % = Shares Becoming Saleable / Total Shares Outstanding x
    100 where data permits. Sourcing: NSE Corporate Filings -
    Shareholding Patterns - Promoter/Public Shareholder tables
    (locked/encumbered/available holdings where disclosed); NSE
    Corporate Announcements - release details. Reads the release %
    directly where the same lock-in filing states it explicitly (the
    same pattern used for D.3.2's dilution %).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "D.4.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.lockin_scoring import score_sellable_block
        text, source_url, desc = _find_latest_lockin_announcement(sym)
        result = score_sellable_block(text)
    except Exception as e:
        print(f"[qualitative_engine] D.4.2 fetch failed for {sym}: {e}")
        result = {"release_pct": None, "shares_released": None, "classification": None}
        source_url = None

    pathway_results = [{
        "pathway_id": "PORTAL-02",
        "source": "NSE Corporate Filings - Corporate Announcements - release details (Potential Release % as explicitly stated in the filing); Shareholding Patterns - Promoter/Public Shareholder tables cross-check",
        "result": "CHECKED" if result["release_pct"] is not None else "NOT_DISCLOSED",
        "note": None if result["release_pct"] is not None else "No lock-in/release filing explicitly stating a release % of share capital was located across NSE Corporate Announcements' full available history this run.",
    }]

    if result["release_pct"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Potential sellable block size", "available": True, **result,
            "rationale": "No lock-in/release filing explicitly stating a release % of share capital was located across NSE Corporate Announcements' full available history this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Potential sellable block size", "available": True, **result,
        "source_pdf_url": source_url,
        "rationale": f"The matched lock-in filing explicitly states a release of {result['release_pct']}% of share capital -> {result['classification']}.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_d4_lockin_releases(symbol, name=None, force=False):
    """D.4 - Lock-in expiries or block share releases: large scheduled
    sellable holdings: combines the two defined sub-points (D.4.1
    lock-in status, D.4.2 sellable block size) into a single grounded
    payload, both sourced from the same real NSE Corporate Announcement
    PDF - no LLM call, see tools/lockin_scoring.py.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    d4_1 = compute_d4_1_lockin_status(sym, name, force=force)
    d4_2 = compute_d4_2_sellable_block(sym, name, force=force)

    parts = []
    if d4_1.get("lockin_status") is not None:
        parts.append(f"Status: {d4_1['lockin_status']} ({d4_1['lockin_expiry_date']}).")
    if d4_2.get("release_pct") is not None:
        parts.append(f"Sellable block: {d4_2['release_pct']}% of share capital ({d4_2['classification']}).")
    if not parts:
        parts.append("No lock-in clause with a resolvable date, or release % figure, was located for this company in NSE Corporate Announcements across the full available announcement history this run - a genuinely sparse source (NSE files no distinct lock-in-expiry announcement type), not necessarily evidence of no lock-in event.")

    _tags = [t.get("confidence_tag") for t in (d4_1, d4_2)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (d4_1, d4_2) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "D.4",
        "title": "Lock-in expiries or block share releases: large scheduled sellable holdings",
        "available": True,
        "d4_1": d4_1, "d4_2": d4_2,
        "rationale": " ".join(parts),
        "pathway_results": (d4_1.get("pathway_results") or [])[:1] + (d4_2.get("pathway_results") or [])[:1],
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


# ---------------------------------------------------------------------------
# D.5 - Promoter loans to/from company or group entities; interest rates
# and repayment terms. Deterministic (no-LLM) - all three sub-points source
# from the same real Annual Report Ind AS 24 Related Party Disclosures note
# already fetched for C.3 (tools.annual_report_financials.
# fetch_rpt_evidence_from_annual_report). D.5.3's denominator reuses the
# real Total Equity figure already extracted for the D/E ratio (Sr No 23),
# never a separately-invented number. See tools/promoter_loan_scoring.py.
# ---------------------------------------------------------------------------

def _fetch_rpt_text_for_loans(sym, name):
    """Shared RPT-note text fetch for all of D.5 - same real source as
    C.3, kept as one helper so the three sub-points don't each pay for a
    separate PDF fetch. Merges the main Related Party Disclosures note
    with the dedicated Loans/Advances-to-related-parties note, since
    filers frequently split the latter into its own note and only
    cross-reference it from the RPT note (e.g. HINDUNILVR's Note 44:
    "Refer note 43 for terms and conditions of loans given to
    subsidiaries" - Note 43 itself, with the real amounts/rates/terms,
    is a separate note the plain RPT-note fetch alone never captured).
    Returns (text, pdf_url)."""
    from tools.annual_report_financials import fetch_rpt_evidence_from_annual_report, fetch_loans_advances_evidence_from_annual_report
    evidence = fetch_rpt_evidence_from_annual_report(sym, name)
    rpt_text = ""
    pdf_url = None
    if isinstance(evidence, dict):
        rpt_text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or []))
        pdf_url = evidence.get("pdf_url")
    loans_evidence = fetch_loans_advances_evidence_from_annual_report(sym, name)
    loans_text = ""
    if isinstance(loans_evidence, dict):
        loans_text = " ".join((ex.get("text") or "") for ex in (loans_evidence.get("excerpts") or []))
        if not pdf_url:
            pdf_url = loans_evidence.get("pdf_url")
    text = " ".join(t for t in (rpt_text, loans_text) if t)
    return text, pdf_url


def compute_d5_1_loan_direction(symbol, name=None, force=False):
    """D.5.1 - Promoter/company loan direction. Spec formula: Direction
    classification: Company -> Promoter/Group, Promoter/Group -> Company,
    Both, or None. Sourcing: NSE Corporate Filings - Annual Reports -
    Notes to Accounts - Loans / Advances / Other Receivables - Related
    Party Disclosures (Ind AS 24).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "D.5.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.promoter_loan_scoring import score_loan_direction
        text, pdf_url = _fetch_rpt_text_for_loans(sym, name)
        result = score_loan_direction(text)
    except Exception as e:
        print(f"[qualitative_engine] D.5.1 fetch failed for {sym}: {e}")
        result = {"direction": None, "evidence_sentences": None}
        pdf_url = None

    has_evidence = bool(result.get("evidence_sentences"))
    not_disclosed_note = (
        "A promoter/group/KMP-adjacent loan or advance sentence was located, but no directional "
        "verb phrase (given to/taken from, etc.) could be classified from it this run."
        if has_evidence else
        "No promoter/group/KMP-adjacent loan or advance sentence was located in the Related Party Disclosures note this run."
    )
    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Notes to Accounts - Loans/Advances - Related Party Disclosures (Ind AS 24)",
        "result": "CHECKED" if result["direction"] is not None else "NOT_DISCLOSED",
        "note": None if result["direction"] is not None else not_disclosed_note,
    }]

    if result["direction"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Promoter/company loan direction", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": not_disclosed_note,
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Promoter/company loan direction", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": f"The Related Party Disclosures note explicitly describes loan/advance direction as {result['direction']}.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_d5_2_loan_terms(symbol, name=None, force=False):
    """D.5.2 - Interest rate and terms. Spec formula: Terms Score (1-5):
    arm's-length rate, documented maturity and repayment terms score
    higher. Sourcing: NSE Corporate Filings - Annual Reports - Related
    Party Disclosures - loans/advances - interest rate, maturity and
    repayment terms.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "D.5.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.promoter_loan_scoring import score_loan_terms
        text, pdf_url = _fetch_rpt_text_for_loans(sym, name)
        result = score_loan_terms(text)
    except Exception as e:
        print(f"[qualitative_engine] D.5.2 fetch failed for {sym}: {e}")
        result = {"interest_rate_pct": None, "repayment_term": None, "arms_length_confirmed": None, "terms_score": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Related Party Disclosures - loans/advances - interest rate, maturity and repayment terms",
        "result": "CHECKED" if result["terms_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["terms_score"] is not None else "No promoter/group/KMP-adjacent loan or advance sentence was located in the Related Party Disclosures note this run.",
    }]

    if result["terms_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Interest rate and terms", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No promoter/group/KMP-adjacent loan or advance sentence was located in the Related Party Disclosures note this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Interest rate and terms", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": (f"Interest rate {result['interest_rate_pct']}% p.a." if result['interest_rate_pct'] is not None else "Interest rate not explicitly stated")
                     + (f", repayable {result['repayment_term']}" if result['repayment_term'] else ", repayment term not explicitly stated")
                     + f" (score {result['terms_score']}/5).",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_d5_3_loan_concentration(symbol, name=None, force=False):
    """D.5.3 - Outstanding balance / concentration. Spec formula:
    Exposure % = Promoter/Group Loan Balance / Net Worth or Total
    Assets, using the most relevant disclosed denominator. Sourcing: NSE
    Corporate Filings - Annual Reports - Balance Sheet / Notes -
    related-party receivables, loans and advances. The denominator
    (Net Worth) reuses the SAME real Total Equity figure already
    extracted for the D/E ratio (Sr No 23) - never a separately-invented
    number.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "D.5.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    net_worth_cr = None
    try:
        from tools.annual_report_financials import list_annual_report_years, fetch_debt_to_equity_from_annual_report
        years = list_annual_report_years(sym, name)
        if years:
            de = fetch_debt_to_equity_from_annual_report(sym, name, years[0])
            if de.get("applicable"):
                net_worth_cr = (de.get("denominator") or {}).get("value_cr")
    except Exception as e:
        print(f"[qualitative_engine] D.5.3 net-worth fetch failed for {sym}: {e}")

    try:
        from tools.promoter_loan_scoring import score_loan_concentration
        text, pdf_url = _fetch_rpt_text_for_loans(sym, name)
        result = score_loan_concentration(text, net_worth_cr=net_worth_cr)
    except Exception as e:
        print(f"[qualitative_engine] D.5.3 fetch failed for {sym}: {e}")
        result = {"loan_balance_cr": None, "denominator_used": None, "exposure_pct": None, "classification": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Balance Sheet / Notes - related-party receivables, loans and advances",
        "result": "CHECKED" if result["loan_balance_cr"] is not None else "NOT_DISCLOSED",
        "note": None if result["loan_balance_cr"] is not None else "No promoter/group/KMP-adjacent loan balance figure was located in the Related Party Disclosures note this run.",
    }]

    if result["loan_balance_cr"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Outstanding balance / concentration", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No promoter/group/KMP-adjacent loan balance figure was located in the Related Party Disclosures note this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    if result["exposure_pct"] is None:
        rationale = f"₹{result['loan_balance_cr']} cr promoter/group-adjacent loan balance explicitly found, but no Net Worth/Total Assets denominator could be computed this run."
    else:
        rationale = f"₹{result['loan_balance_cr']} cr promoter/group-adjacent loan balance is {result['exposure_pct']}% of {result['denominator_used']} -> {result['classification']}."
    payload = {
        "subpoint_id": subpoint_id, "title": "Outstanding balance / concentration", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": rationale,
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_d5_promoter_loans(symbol, name=None, force=False):
    """D.5 - Promoter loans to/from company or group entities; interest
    rates and repayment terms: combines the three defined sub-points
    (D.5.1 direction, D.5.2 terms, D.5.3 concentration) into a single
    grounded payload, all sourced from the same real Annual Report Ind
    AS 24 Related Party Disclosures note - no LLM call, see
    tools/promoter_loan_scoring.py.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    d5_1 = compute_d5_1_loan_direction(sym, name, force=force)
    d5_2 = compute_d5_2_loan_terms(sym, name, force=force)
    d5_3 = compute_d5_3_loan_concentration(sym, name, force=force)

    parts = []
    if d5_1.get("direction") is not None:
        parts.append(f"Direction: {d5_1['direction']}.")
    if d5_2.get("terms_score") is not None:
        parts.append(f"Terms: score {d5_2['terms_score']}/5.")
    if d5_3.get("loan_balance_cr") is not None:
        if d5_3.get("exposure_pct") is not None:
            parts.append(f"Balance: ₹{d5_3['loan_balance_cr']} cr ({d5_3['exposure_pct']}% of {d5_3['denominator_used']}).")
        else:
            parts.append(f"Balance: ₹{d5_3['loan_balance_cr']} cr.")
    if not parts:
        parts.append("No promoter/group/KMP-adjacent loan or advance was located in the Related Party Disclosures note for this company this run.")

    _tags = [t.get("confidence_tag") for t in (d5_1, d5_2, d5_3)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (d5_1, d5_2, d5_3) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "D.5",
        "title": "Promoter loans to/from company or group entities; interest rates and repayment terms",
        "available": True,
        "d5_1": d5_1, "d5_2": d5_2, "d5_3": d5_3,
        "rationale": " ".join(parts),
        "pathway_results": (d5_1.get("pathway_results") or [])[:1] + (d5_2.get("pathway_results") or [])[:1] + (d5_3.get("pathway_results") or [])[:1],
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


def compute_d6_1_pledge_unwinding(symbol, name=None, force=False):
    """D.6.1 - Pledge release / unwinding. Spec formula: Pledge
    Unwinding = Previous Pledged % - Current Pledged %; a positive
    decline is a release, but the spec explicitly says not to assume a
    reason for it. Deterministic (no LLM) - reads every quarter NSE's
    own corporate-pledgedata endpoint has an on-record pledge for
    (same real source already built for C.2.3's pledge trend).
    Sourcing: NSE Corporate Filings - Shareholding Pattern - Promoter &
    Promoter Group - Pledged/Encumbered Shares, compared quarter over
    quarter.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "D.6.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.shareholding_scraper import get_provider
        trend = get_provider().fetch_pledge_trend(sym) or []
    except Exception as e:
        print(f"[qualitative_engine] D.6.1 fetch failed for {sym}: {e}")
        trend = []

    pathway_results = [{
        "pathway_id": "PORTAL-02",
        "source": "NSE Corporate Filings - Shareholding Pattern - Promoter & Promoter Group - Pledged/Encumbered Shares",
        "result": "CHECKED" if trend else "NOT_DISCLOSED",
        "note": None if trend else "No on-record pledge was available from NSE's live endpoint this run.",
    }]

    if not trend:
        payload = {
            "subpoint_id": subpoint_id, "title": "Pledge release / unwinding", "available": True,
            "trend": None, "previous_pledge_pct": None, "current_pledge_pct": None,
            "unwinding_pct": None, "direction": None,
            "rationale": "No on-record pledge was available from NSE's live endpoint this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    if len(trend) < 2:
        # Real current pledge % IS available even though NSE's live
        # endpoint isn't currently exposing a prior quarter to diff
        # against (confirmed real, not a bug: NSE's corporate-pledgedata
        # endpoint is presently returning only the single latest
        # disclosure for every symbol checked, including companies with
        # large, long-standing pledges like ZEEL/SUZLON - not specific
        # to any one company). Surface the real current % as a known
        # data point rather than discarding it into a blank N/A -
        # unwinding itself (which needs a prior quarter to diff against)
        # is correctly left uncomputed, not fabricated.
        payload = {
            "subpoint_id": subpoint_id, "title": "Pledge release / unwinding", "available": True,
            "trend": trend, "quarters_available": len(trend),
            "previous_pledge_pct": None, "current_pledge_pct": trend[-1]["pledge_pct"],
            "previous_quarter": None, "current_quarter": trend[-1]["quarter"],
            "unwinding_pct": None, "direction": None,
            "rationale": f"Current pledge: {trend[-1]['pledge_pct']}% (as of {trend[-1]['quarter']}). NSE's live endpoint has not yet exposed a prior quarter to compute quarter-over-quarter unwinding against this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    previous_pct = trend[-2]["pledge_pct"]
    current_pct = trend[-1]["pledge_pct"]
    unwinding_pct = round(previous_pct - current_pct, 2)
    if unwinding_pct > 0:
        direction = "Release"
    elif unwinding_pct < 0:
        direction = "Increase"
    else:
        direction = "Unchanged"

    payload = {
        "subpoint_id": subpoint_id, "title": "Pledge release / unwinding", "available": True,
        "trend": trend, "quarters_available": len(trend),
        "previous_pledge_pct": previous_pct, "current_pledge_pct": current_pct,
        "previous_quarter": trend[-2]["quarter"], "current_quarter": trend[-1]["quarter"],
        "unwinding_pct": unwinding_pct, "direction": direction,
        "rationale": f"Pledged % moved from {previous_pct}% ({trend[-2]['quarter']}) to {current_pct}% ({trend[-1]['quarter']}) -> {direction} of {abs(unwinding_pct)} percentage points. Reason not disclosed - not assumed.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_d6_2_forced_sale_signals(symbol, name=None, force=False):
    """D.6.2 - Forced-sale / invocation signals. Spec formula: Risk
    classification: No evidence / Possible / Confirmed based only on
    disclosed evidence. Deterministic (no LLM) - scans real NSE
    Corporate Announcements for pledge-invocation/default language
    (tools.forced_sale_scoring), cross-checked against the real pledge-%
    trend (tools.shareholding_scraper, same source as D.6.1) and real
    Regulation 7(2) insider-trading disclosures
    (tools.insider_trading_scraper, same source as D.1/D.2). Sourcing:
    NSE Corporate Filings - Corporate Announcements (keyword search) +
    Shareholding Pattern + Insider Trading Regulation 7(2).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "D.6.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.nse_announcements import fetch_announcements
        from tools.shareholding_scraper import get_provider
        from tools.insider_trading_scraper import fetch_insider_trades
        from tools.forced_sale_scoring import classify_pledge_announcements, classify_insider_invocation, score_forced_sale_signals

        announcements = fetch_announcements(sym) or []
        announcement_matches = classify_pledge_announcements(announcements)
        pledge_trend = get_provider().fetch_pledge_trend(sym) or []
        trades = fetch_insider_trades(sym, quarters=8) or []
        insider_matches = classify_insider_invocation(trades)
        result = score_forced_sale_signals(announcement_matches, insider_matches, pledge_trend)
    except Exception as e:
        print(f"[qualitative_engine] D.6.2 fetch failed for {sym}: {e}")
        result = {"classification": None, "confirmed_count": 0, "possible_count": 0, "evidence": []}

    pathway_results = [{
        "pathway_id": "PORTAL-02",
        "source": "NSE Corporate Filings - Corporate Announcements (pledge invocation/default keyword search), cross-checked with Shareholding Pattern and Insider Trading Regulation 7(2)",
        "result": "CHECKED" if result.get("classification") is not None else "NOT_DISCLOSED",
        "note": None if result.get("classification") is not None else "NSE's live endpoints were unreachable this run.",
    }]

    if result.get("classification") is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Forced-sale / invocation signals", "available": True,
            **result,
            "rationale": "NSE's live endpoints were unreachable this run - forced-sale/invocation risk could not be checked.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    classification = result["classification"]
    if classification == "Confirmed":
        rationale = f"{result['confirmed_count']} real NSE filing(s) explicitly disclose pledge invocation, default, or a lender-forced sale -> Confirmed."
    elif classification == "Possible":
        rationale = f"{result['possible_count']} real pledge/encumbrance disclosure filing(s) exist alongside a corroborated on-record pledge, but none singularly confirms invocation as the reason -> Possible."
    else:
        rationale = "No pledge-invocation, default, or forced-sale evidence was located in NSE Corporate Announcements, Insider Trading (Reg 7(2)), or the pledge-% trend this run -> No evidence."

    payload = {
        "subpoint_id": subpoint_id, "title": "Forced-sale / invocation signals", "available": True,
        **result,
        "rationale": rationale,
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE" if classification in ("Confirmed", "Possible") else "SEARCH_INCONCLUSIVE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_d6_pledge_signals(symbol, name=None, force=False):
    """D.6 - Pledge release/unwinding and forced-sale/invocation signals:
    combines the two defined sub-points (D.6.1 unwinding, D.6.2 forced-
    sale signals) into a single grounded payload, sourced from the same
    real NSE Shareholding Pattern pledge data, Corporate Announcements,
    and Regulation 7(2) insider-trading disclosures already built for
    C.2, D.1/D.2 and D.5 - no LLM call.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    d6_1 = compute_d6_1_pledge_unwinding(sym, name, force=force)
    d6_2 = compute_d6_2_forced_sale_signals(sym, name, force=force)

    parts = []
    if d6_1.get("direction") is not None:
        parts.append(f"Pledge: {d6_1['direction']} of {abs(d6_1['unwinding_pct'])}pp ({d6_1['previous_quarter']} -> {d6_1['current_quarter']}).")
    if d6_2.get("classification") is not None:
        parts.append(f"Forced-sale signals: {d6_2['classification']}.")
    if not parts:
        parts.append("No pledge trend or forced-sale/invocation evidence was located for this company this run.")

    _tags = [t.get("confidence_tag") for t in (d6_1, d6_2)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (d6_1, d6_2) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "D.6",
        "title": "Pledge release/unwinding and forced-sale/invocation signals",
        "available": True,
        "d6_1": d6_1, "d6_2": d6_2,
        "rationale": " ".join(parts),
        "pathway_results": (d6_1.get("pathway_results") or [])[:1] + (d6_2.get("pathway_results") or [])[:1],
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


def compute_e1_1_payment_frequency(symbol, name=None, force=False):
    """E.1.1 - Related-party payment frequency. Spec formula: Frequency
    Score (1-5) based on recurring nature and number of material
    counterparties. Deterministic (no LLM) - see
    tools.rpt_leakage_scoring.score_payment_frequency: counts DISTINCT
    named (not category-label) counterparties with a real amount
    attached in the Related Party Disclosures note, same real source
    already built for C.3/D.5. Sourcing: NSE Corporate Filings - Annual
    Reports - Notes to Accounts - Related Party Disclosures -
    transactions with promoter/group entities.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "E.1.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import fetch_rpt_evidence_from_annual_report
        from tools.rpt_leakage_scoring import score_payment_frequency
        evidence = fetch_rpt_evidence_from_annual_report(sym, name) or {}
        text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or []))
        result = score_payment_frequency(text)
    except Exception as e:
        print(f"[qualitative_engine] E.1.1 fetch failed for {sym}: {e}")
        result = {"material_counterparty_count": None, "recurring_disclosed": None, "frequency_score": None}

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Notes to Accounts - Related Party Disclosures - transactions with promoter/group entities",
        "result": "CHECKED" if result["frequency_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["frequency_score"] is not None else "No named, amount-attached related-party counterparty was located in the Related Party Disclosures note this run.",
    }]

    if result["frequency_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Related-party payment frequency", "available": True, **result,
            "rationale": "No named, amount-attached related-party counterparty was located in the Related Party Disclosures note this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Related-party payment frequency", "available": True, **result,
        "rationale": f"{result['material_counterparty_count']} named related-party counterpart(y/ies) with a disclosed amount" + (", recurring/ongoing nature disclosed" if result["recurring_disclosed"] else "") + f" -> score {result['frequency_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_e1_3_payment_rationale(symbol, name=None, force=False):
    """E.1.3 - Payment rationale / arm's-length basis. Spec formula:
    Rationale Score (1-5): documented commercial purpose and arm's-
    length basis score higher. Deterministic (no LLM) - see
    tools.rpt_leakage_scoring.score_payment_rationale: arm's-length
    pricing confirmation AND Audit Committee approval language, same
    real Related Party Disclosures note text as E.1.1/C.3/D.5.
    Sourcing: NSE Corporate Filings - Annual Reports - Related Party
    Disclosures - nature, terms, pricing basis and Audit Committee
    approval.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "E.1.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import fetch_rpt_evidence_from_annual_report
        from tools.rpt_leakage_scoring import score_payment_rationale
        evidence = fetch_rpt_evidence_from_annual_report(sym, name) or {}
        text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or []))
        result = score_payment_rationale(text)
    except Exception as e:
        print(f"[qualitative_engine] E.1.3 fetch failed for {sym}: {e}")
        result = {"arms_length_confirmed": None, "audit_committee_approved": None, "opaque_flag": None, "rationale_score": None}

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Related Party Disclosures - nature, terms, pricing basis and Audit Committee approval",
        "result": "CHECKED" if result["rationale_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["rationale_score"] is not None else "No explicit arm's-length pricing statement or Audit Committee approval language was located in the Related Party Disclosures note this run.",
    }]

    if result["rationale_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Payment rationale / arm's-length basis", "available": True, **result,
            "rationale": "No explicit arm's-length pricing statement or Audit Committee approval language was located in the Related Party Disclosures note this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    if result["opaque_flag"]:
        rationale = "An explicit non-arm's-length pricing statement or Audit Committee approval gap was found -> score 1/5."
    else:
        rationale = f"Arm's-length pricing {'confirmed' if result['arms_length_confirmed'] else 'not explicitly confirmed'}; Audit Committee approval {'documented' if result['audit_committee_approved'] else 'not explicitly documented'} -> score {result['rationale_score']}/5."
    payload = {
        "subpoint_id": subpoint_id, "title": "Payment rationale / arm's-length basis", "available": True, **result,
        "rationale": rationale,
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_e1_business_integrity_signals(symbol, name=None, force=False):
    """E.1 - Unexpected related-party payments to opaque vendors or
    consultants: combines the two defined sub-points (E.1.1 payment
    frequency, E.1.3 payment rationale) into a single grounded payload
    (E.1.2 is not defined in the spec workbook, so no sub-point is
    fabricated for it), sourced from the same real Related Party
    Disclosures note already built for C.3/D.5 - no LLM call.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    e1_1 = compute_e1_1_payment_frequency(sym, name, force=force)
    e1_3 = compute_e1_3_payment_rationale(sym, name, force=force)

    parts = []
    if e1_1.get("frequency_score") is not None:
        parts.append(f"Payment frequency: {e1_1['material_counterparty_count']} named counterpart(y/ies) (score {e1_1['frequency_score']}/5).")
    if e1_3.get("rationale_score") is not None:
        parts.append(f"Payment rationale: score {e1_3['rationale_score']}/5.")
    if not parts:
        parts.append("No named, amount-attached related-party counterparty or payment-rationale language was located for this company this run.")

    _tags = [t.get("confidence_tag") for t in (e1_1, e1_3)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (e1_1, e1_3) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "E.1",
        "title": "Unexpected related-party payments to opaque vendors or consultants",
        "available": True,
        "e1_1": e1_1, "e1_3": e1_3,
        "rationale": " ".join(parts),
        "pathway_results": (e1_1.get("pathway_results") or [])[:1] + (e1_3.get("pathway_results") or [])[:1],
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


_CUSTOMER_CONCENTRATION_ANCHORS = [
    "single customer", "single external customer", "major customer", "revenue from customer",
    "customer concentration", "top customer", "largest customer", "diversified customer", "dependent on",
]


def _fetch_customer_concentration_text(sym, name):
    """Shared evidence fetch for E.2 - real Annual Report text near Ind
    AS 108 'Information about major customers' note and MD&A customer-
    concentration/dependency language. Returns (text, pdf_url)."""
    from tools.annual_report_financials import _fetch_ar_evidence_excerpts
    evidence = _fetch_ar_evidence_excerpts(
        sym, name, _CUSTOMER_CONCENTRATION_ANCHORS, "ar_custconc_text_v1",
        max_per_page=3, max_excerpts=15, fetch_label="customer-concentration",
    )
    if not isinstance(evidence, dict):
        return "", None
    text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or []))
    return text, evidence.get("pdf_url")


def compute_e2_1_customer_concentration(symbol, name=None, force=False):
    """E.2.1 - Top customer revenue concentration. Spec formula: Top
    Customer Concentration % = Revenue from Largest Customer(s) / Total
    Revenue x 100 where disclosed. Deterministic (no LLM) - see
    tools.customer_concentration_scoring.score_customer_concentration:
    handles both the standard Ind AS 108 negative disclosure form ("no
    single customer represents 10%+ of revenue" - a real disclosed
    upper bound) and the positive form naming an actual %. Sourcing:
    NSE Corporate Filings - Annual Reports - Notes to Accounts -
    Revenue from Customers / Segment Information / Major Customer
    disclosures.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "E.2.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.customer_concentration_scoring import score_customer_concentration
        text, pdf_url = _fetch_customer_concentration_text(sym, name)
        result = score_customer_concentration(text)
    except Exception as e:
        print(f"[qualitative_engine] E.2.1 fetch failed for {sym}: {e}")
        result = {"concentration_pct": None, "is_upper_bound": None, "classification": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Notes to Accounts - Revenue from Customers / Segment Information / Major Customer disclosures",
        "result": "CHECKED" if result["concentration_pct"] is not None else "NOT_DISCLOSED",
        "note": None if result["concentration_pct"] is not None else "No Ind AS 108 major-customer revenue-concentration disclosure was located in the latest Annual Report this run.",
    }]

    if result["concentration_pct"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Top customer revenue concentration", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No Ind AS 108 major-customer revenue-concentration disclosure was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    if result["is_upper_bound"]:
        rationale = f"No single customer represents {result['concentration_pct']}% or more of total revenue (real disclosed upper bound) -> {result['classification']}."
    else:
        rationale = f"Largest customer represents {result['concentration_pct']}% of total revenue -> {result['classification']}."
    payload = {
        "subpoint_id": subpoint_id, "title": "Top customer revenue concentration", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": rationale,
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_e2_2_customer_dependency(symbol, name=None, force=False):
    """E.2.2 - Customer dependency. Spec formula: Dependency Score
    (1-5): diversified recurring customer base scores higher than
    reliance on one/few customers. Deterministic (no LLM) - see
    tools.customer_concentration_scoring.score_customer_dependency:
    cross-checks E.2.1's own disclosed concentration % first (the most
    concrete real signal), falling back to explicit MD&A/risk-factor
    diversification/dependency language. Sourcing: NSE Corporate
    Filings - Annual Reports - MD&A - customer concentration, contract
    dependence, major customer commentary.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "E.2.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.customer_concentration_scoring import score_customer_dependency
        text, pdf_url = _fetch_customer_concentration_text(sym, name)
        concentration = compute_e2_1_customer_concentration(sym, name, force=force)
        result = score_customer_dependency(text, concentration)
    except Exception as e:
        print(f"[qualitative_engine] E.2.2 fetch failed for {sym}: {e}")
        result = {"dependency_score": None, "basis": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - MD&A - customer concentration, contract dependence, major customer commentary",
        "result": "CHECKED" if result["dependency_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["dependency_score"] is not None else "No disclosed concentration % or explicit customer-diversification/dependency language was located in the latest Annual Report this run.",
    }]

    if result["dependency_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Customer dependency", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No disclosed concentration % or explicit customer-diversification/dependency language was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    basis_label = "the disclosed concentration %" if result["basis"] == "concentration_pct" else "MD&A/risk-factor language"
    payload = {
        "subpoint_id": subpoint_id, "title": "Customer dependency", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": f"Dependency score {result['dependency_score']}/5, based on {basis_label}.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_e2_customer_concentration(symbol, name=None, force=False):
    """E.2 - Customer concentration: top customers percentage &
    dependency: combines the two defined sub-points (E.2.1 concentration,
    E.2.2 dependency) into a single grounded payload, sourced from the
    same real Annual Report Ind AS 108 major-customer note and MD&A text
    - no LLM call.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    e2_1 = compute_e2_1_customer_concentration(sym, name, force=force)
    e2_2 = compute_e2_2_customer_dependency(sym, name, force=force)

    parts = []
    if e2_1.get("concentration_pct") is not None:
        parts.append(f"Top customer concentration: {'<' if e2_1.get('is_upper_bound') else ''}{e2_1['concentration_pct']}% ({e2_1['classification']}).")
    if e2_2.get("dependency_score") is not None:
        parts.append(f"Dependency: score {e2_2['dependency_score']}/5.")
    if not parts:
        parts.append("No customer-concentration or dependency evidence was located for this company this run.")

    _tags = [t.get("confidence_tag") for t in (e2_1, e2_2)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (e2_1, e2_2) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "E.2",
        "title": "Customer concentration: top customers percentage & dependency",
        "available": True,
        "e2_1": e2_1, "e2_2": e2_2,
        "rationale": " ".join(parts),
        "pathway_results": (e2_1.get("pathway_results") or [])[:1] + (e2_2.get("pathway_results") or [])[:1],
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


_SUPPLIER_CONCENTRATION_ANCHORS = [
    "single source", "single-source", "sole supplier", "single supplier", "concentration of suppliers",
    "diversified supplier", "alternative supplier", "dependent on suppliers", "credit period",
    "supply agreement", "key suppliers", "raw material price",
    # ESG sustainable-sourcing-% anchors - used only as a fallback
    # diversification proxy (see score_supplier_concentration's
    # 'esg_proxy' basis) when no direct MD&A risk-factor statement is
    # found; confirmed real on HINDUNILVR ("64.5% of key crops sourced
    # sustainably ... tea, palm oil, paper and board, cereal, sugar,
    # dairy, cocoa, coconut oil, soy, starches").
    "sourced sustainably", "sustainable sourcing", "responsible sourcing",
]


def _fetch_supplier_concentration_text(sym, name):
    """Shared evidence fetch for E.3 - real Annual Report MD&A/Risk
    Factors and Notes to Accounts text near supplier-concentration/
    single-source and supplier-terms language. Returns (text, pdf_url)."""
    from tools.annual_report_financials import _fetch_ar_evidence_excerpts
    evidence = _fetch_ar_evidence_excerpts(
        sym, name, _SUPPLIER_CONCENTRATION_ANCHORS, "ar_suppconc_text_v2",
        max_per_page=3, max_excerpts=15, fetch_label="supplier-concentration",
    )
    if not isinstance(evidence, dict):
        return "", None
    text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or []))
    return text, evidence.get("pdf_url")


def compute_e3_1_supplier_concentration(symbol, name=None, force=False):
    """E.3.1 - Supplier concentration. Spec formula: Supplier
    Concentration Score (1-5) based on disclosed single-source
    dependence. Deterministic (no LLM) - see
    tools.supplier_concentration_scoring.score_supplier_concentration.
    Sourcing: NSE Corporate Filings - Annual Reports - MD&A - Risk
    Factors / Supply Chain - major suppliers, single-source
    dependencies and concentration disclosures.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "E.3.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.supplier_concentration_scoring import score_supplier_concentration
        text, pdf_url = _fetch_supplier_concentration_text(sym, name)
        result = score_supplier_concentration(text)
    except Exception as e:
        print(f"[qualitative_engine] E.3.1 fetch failed for {sym}: {e}")
        result = {"single_source_disclosed": None, "diversified_disclosed": None, "concentration_score": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-01",
        "source": "NSE Corporate Filings - Annual Reports - MD&A - Risk Factors / Supply Chain - major suppliers, single-source dependencies and concentration disclosures",
        "result": "CHECKED" if result["concentration_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["concentration_score"] is not None else "No single-source-supplier risk statement or diversified-supplier-base language was located in the latest Annual Report this run.",
    }]

    if result["concentration_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Supplier concentration", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No single-source-supplier risk statement or diversified-supplier-base language was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    if result.get("basis") == "esg_proxy":
        rationale = f"No direct MD&A risk-factor statement was found, but an ESG sustainable-sourcing disclosure (multiple raw-material categories sourced sustainably) is used as an indirect diversification proxy -> score {result['concentration_score']}/5."
    else:
        rationale = ("Single-source/limited-supplier dependence disclosed" if result["single_source_disclosed"] else "Diversified supplier base explicitly disclosed") + f" -> score {result['concentration_score']}/5."
    payload = {
        "subpoint_id": subpoint_id, "title": "Supplier concentration", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": rationale,
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_e3_3_supplier_terms(symbol, name=None, force=False):
    """E.3.3 - Supplier terms / dependence. Spec formula: Supplier
    Terms Score (1-5): transparent commercial terms and diversified
    procurement score higher. Deterministic (no LLM) - see
    tools.supplier_concentration_scoring.score_supplier_terms.
    Sourcing: NSE Corporate Filings - Annual Reports - Notes to
    Accounts - trade payables / commitments; MD&A - procurement terms
    and supply contracts.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "E.3.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.supplier_concentration_scoring import score_supplier_terms
        text, pdf_url = _fetch_supplier_concentration_text(sym, name)
        result = score_supplier_terms(text)
    except Exception as e:
        print(f"[qualitative_engine] E.3.3 fetch failed for {sym}: {e}")
        result = {"transparent_terms_disclosed": None, "dependence_risk_disclosed": None, "terms_score": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Notes to Accounts - trade payables / commitments; MD&A - procurement terms and supply contracts",
        "result": "CHECKED" if result["terms_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["terms_score"] is not None else "No transparent-supplier-terms or supplier-dependence-risk language was located in the latest Annual Report this run.",
    }]

    if result["terms_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Supplier terms / dependence", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No transparent-supplier-terms or supplier-dependence-risk language was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Supplier terms / dependence", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": ("Transparent commercial terms (long-term/multi-year supply agreement or a stated credit period) disclosed" if result["transparent_terms_disclosed"] else "Supplier-dependence risk language disclosed") + f" -> score {result['terms_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_e3_supplier_concentration_terms(symbol, name=None, force=False):
    """E.3 - Supplier concentration and terms: single-sourced inputs or
    tied suppliers: combines the two defined sub-points (E.3.1
    concentration, E.3.3 terms) into a single grounded payload (E.3.2
    is not defined in the spec workbook, so no sub-point is fabricated
    for it), sourced from the same real Annual Report MD&A/Risk Factors
    and Notes to Accounts text - no LLM call.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    e3_1 = compute_e3_1_supplier_concentration(sym, name, force=force)
    e3_3 = compute_e3_3_supplier_terms(sym, name, force=force)

    parts = []
    if e3_1.get("concentration_score") is not None:
        parts.append(f"Supplier concentration: score {e3_1['concentration_score']}/5.")
    if e3_3.get("terms_score") is not None:
        parts.append(f"Supplier terms: score {e3_3['terms_score']}/5.")
    if not parts:
        parts.append("No supplier-concentration or supplier-terms evidence was located for this company this run.")

    _tags = [t.get("confidence_tag") for t in (e3_1, e3_3)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (e3_1, e3_3) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "E.3",
        "title": "Supplier concentration and terms: single-sourced inputs or tied suppliers",
        "available": True,
        "e3_1": e3_1, "e3_3": e3_3,
        "rationale": " ".join(parts),
        "pathway_results": (e3_1.get("pathway_results") or [])[:1] + (e3_3.get("pathway_results") or [])[:1],
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


def compute_e4_1_receivables_growth(symbol, name=None, force=False):
    """E.4.1 - Receivables growth. Spec formula: Receivables Growth =
    Current Trade Receivables / Prior-period Trade Receivables - 1.
    Deterministic (no LLM) - reuses the SAME real Annual Report Balance
    Sheet Trade Receivables figures already extracted for the
    Receivables Turnover ratio (tools.annual_report_financials.
    _get_extracted_financials - no separate fetch/parse).

    IMPORTANT DEVIATION FROM SPEC'S SOURCING PATH: the spec's own
    sourcing path asks for a QUARTERLY (8-quarter) NSE XBRL Financial
    Results trend. No such fetcher exists anywhere in this codebase
    (confirmed: this app's only "8 quarter" trend fetchers are for
    shareholding/pledge data, not balance-sheet line items; NSE's
    quarterly XBRL results endpoint has never been wired up here) and
    building one from scratch is a substantial undertaking outside a
    single sub-point's scope. Rather than fabricate quarterly points or
    silently mislabel annual data as quarterly, this computes the SAME
    growth formula on real ANNUAL (year-over-year) Trade Receivables
    from the Balance Sheet - each real result explicitly labelled
    'period_type': 'annual' so no caller can present it as the
    8-quarter chart the spec describes without knowing that's not what
    it is.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "E.4.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import list_annual_report_years, _get_extracted_financials
        years = list_annual_report_years(sym, name)
        trend = []
        pdf_url = None
        if years:
            fiscal_year = years[0]
            parsed = _get_extracted_financials(sym, name, fiscal_year, consolidated=True)
            pdf_url = parsed.get("source_url")
            receivables = parsed.get("receivables")
            if receivables and receivables[0] is not None and receivables[1] is not None:
                trend = [
                    {"period": f"FY{str(fiscal_year - 1)[-2:]}", "receivables_cr": receivables[1]},
                    {"period": f"FY{str(fiscal_year)[-2:]}", "receivables_cr": receivables[0]},
                ]
    except Exception as e:
        print(f"[qualitative_engine] E.4.1 fetch failed for {sym}: {e}")
        trend = []
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Balance Sheet - Trade Receivables (annual, not the 8-quarter XBRL trend the spec describes - no quarterly balance-sheet fetcher exists in this codebase)",
        "result": "CHECKED" if trend else "NOT_DISCLOSED",
        "note": None if trend else "Trade Receivables could not be located on the Balance Sheet page of the latest Annual Report this run.",
    }]

    if not trend:
        payload = {
            "subpoint_id": subpoint_id, "title": "Receivables growth", "available": True,
            "trend": None, "period_type": None, "current_receivables_cr": None, "prior_receivables_cr": None,
            "growth_pct": None,
            "source_pdf_url": pdf_url,
            "rationale": "Trade Receivables could not be located on the Balance Sheet page of the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    prior_cr, current_cr = trend[0]["receivables_cr"], trend[1]["receivables_cr"]
    growth_pct = round(100 * (current_cr / prior_cr - 1), 2) if prior_cr else None
    payload = {
        "subpoint_id": subpoint_id, "title": "Receivables growth", "available": True,
        "trend": trend, "period_type": "annual",
        "current_receivables_cr": current_cr, "prior_receivables_cr": prior_cr, "growth_pct": growth_pct,
        "source_pdf_url": pdf_url,
        "rationale": f"Trade Receivables moved from Rs{prior_cr} cr ({trend[0]['period']}) to Rs{current_cr} cr ({trend[1]['period']}) -> {growth_pct:+.2f}% YoY (annual, not quarterly - see rationale note)." if growth_pct is not None else f"Trade Receivables: Rs{current_cr} cr ({trend[1]['period']}); prior-year figure unusable for a growth %.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


_RECEIVABLES_AGEING_ANCHORS = [
    "trade receivables ageing", "ageing schedule", "not due", "undisputed trade receivables",
    "ageing for trade receivables",
]
_REVENUE_RECOGNITION_ANCHORS = [
    "revenue recognition", "contract asset", "unbilled revenue", "variable consideration", "performance obligation",
]


def compute_e4_2_receivables_ageing(symbol, name=None, force=False):
    """E.4.2 - Receivables aging / overdue quality. Spec formula:
    Overdue Concentration = Overdue Receivables / Total Trade
    Receivables x 100. Deterministic (no LLM) - see
    tools.receivables_risk_scoring.score_receivables_ageing: reads the
    real Ind AS 107 Trade Receivables ageing schedule's own TOTAL row.
    Sourcing: NSE Corporate Filings - Annual Reports - Notes to
    Accounts - Trade Receivables Ageing / Expected Credit Loss.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "E.4.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import _fetch_ar_evidence_excerpts
        from tools.receivables_risk_scoring import score_receivables_ageing
        evidence = _fetch_ar_evidence_excerpts(
            sym, name, _RECEIVABLES_AGEING_ANCHORS, "ar_recvageing_text_v1",
            max_per_page=4, max_excerpts=15, fetch_label="receivables-ageing",
        )
        text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or [])) if isinstance(evidence, dict) else ""
        pdf_url = evidence.get("pdf_url") if isinstance(evidence, dict) else None
        result = score_receivables_ageing(text)
    except Exception as e:
        print(f"[qualitative_engine] E.4.2 fetch failed for {sym}: {e}")
        result = {"not_due_cr": None, "total_cr": None, "overdue_pct": None, "classification": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Notes to Accounts - Trade Receivables Ageing / Expected Credit Loss",
        "result": "CHECKED" if result["overdue_pct"] is not None else "NOT_DISCLOSED",
        "note": None if result["overdue_pct"] is not None else "No Trade Receivables ageing TOTAL row was located in the latest Annual Report this run.",
    }]

    if result["overdue_pct"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Receivables aging / overdue quality", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No Trade Receivables ageing TOTAL row was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Receivables aging / overdue quality", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": f"{result['overdue_pct']}% of total Trade Receivables (Rs{result['total_cr']} cr) is overdue past the due date -> {result['classification']}.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_e4_3_revenue_recognition_risk(symbol, name=None, force=False):
    """E.4.3 - Revenue-recognition disclosure risk. Spec formula:
    Revenue Recognition Risk Score (1-5) based on complexity and
    disclosure clarity. Deterministic (no LLM) - see
    tools.receivables_risk_scoring.score_revenue_recognition_risk.
    Sourcing: NSE Corporate Filings - Annual Reports - Significant
    Accounting Policies - Revenue Recognition (Ind AS 115) - contract
    assets / unbilled revenue / variable consideration.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "E.4.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import _fetch_ar_evidence_excerpts
        from tools.receivables_risk_scoring import score_revenue_recognition_risk
        evidence = _fetch_ar_evidence_excerpts(
            sym, name, _REVENUE_RECOGNITION_ANCHORS, "ar_revrec_text_v1",
            max_per_page=3, max_excerpts=15, fetch_label="revenue-recognition",
        )
        text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or [])) if isinstance(evidence, dict) else ""
        pdf_url = evidence.get("pdf_url") if isinstance(evidence, dict) else None
        result = score_revenue_recognition_risk(text)
    except Exception as e:
        print(f"[qualitative_engine] E.4.3 fetch failed for {sym}: {e}")
        result = {"contract_assets_disclosed": None, "unbilled_revenue_disclosed": None,
                  "variable_consideration_disclosed": None, "judgement_disclosed": None, "risk_score": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Significant Accounting Policies - Revenue Recognition (Ind AS 115) - contract assets / unbilled revenue / variable consideration",
        "result": "CHECKED" if result["risk_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["risk_score"] is not None else "No contract-assets/unbilled-revenue/variable-consideration language was located in the Revenue Recognition accounting policy this run.",
    }]

    if result["risk_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Revenue-recognition disclosure risk", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No contract-assets/unbilled-revenue/variable-consideration language was located in the Revenue Recognition accounting policy this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    disclosed = [k.replace("_disclosed", "").replace("_", " ") for k in ("contract_assets_disclosed", "unbilled_revenue_disclosed", "variable_consideration_disclosed") if result[k]]
    payload = {
        "subpoint_id": subpoint_id, "title": "Revenue-recognition disclosure risk", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": (f"Discloses {', '.join(disclosed)}" if disclosed else "No specific complexity indicators disclosed") + (" with an explicit significant-judgement/estimate flag" if result["judgement_disclosed"] else "") + f" -> score {result['risk_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_e4_receivables_disclosure_risk(symbol, name=None, force=False):
    """E.4 - High or growing receivables with limited disclosure -
    revenue recognition risk: combines the three defined sub-points
    (E.4.1 growth, E.4.2 ageing, E.4.3 revenue-recognition risk) into a
    single grounded payload, sourced from the same real Annual Report
    Balance Sheet / Notes to Accounts / Significant Accounting Policies
    text - no LLM call.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    e4_1 = compute_e4_1_receivables_growth(sym, name, force=force)
    e4_2 = compute_e4_2_receivables_ageing(sym, name, force=force)
    e4_3 = compute_e4_3_revenue_recognition_risk(sym, name, force=force)

    parts = []
    if e4_1.get("growth_pct") is not None:
        parts.append(f"Receivables growth: {e4_1['growth_pct']:+.2f}% YoY.")
    if e4_2.get("overdue_pct") is not None:
        parts.append(f"Overdue: {e4_2['overdue_pct']}% ({e4_2['classification']}).")
    if e4_3.get("risk_score") is not None:
        parts.append(f"Revenue-recognition disclosure: score {e4_3['risk_score']}/5.")
    if not parts:
        parts.append("No receivables growth, ageing, or revenue-recognition-disclosure evidence was located for this company this run.")

    _tags = [t.get("confidence_tag") for t in (e4_1, e4_2, e4_3)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (e4_1, e4_2, e4_3) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "E.4",
        "title": "High or growing receivables with limited disclosure - revenue recognition risk",
        "available": True,
        "e4_1": e4_1, "e4_2": e4_2, "e4_3": e4_3,
        "rationale": " ".join(parts),
        "pathway_results": (e4_1.get("pathway_results") or [])[:1] + (e4_2.get("pathway_results") or [])[:1] + (e4_3.get("pathway_results") or [])[:1],
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


def _fetch_inventory_and_revenue(sym, name):
    """Shared fetch for E.5.1/E.5.2 - real Annual Report Balance Sheet
    Inventory and P&L Revenue (both current, prior), reusing the SAME
    cached PDF extraction already built for Inventory Turnover/
    Receivables Turnover (tools.annual_report_financials.
    _get_extracted_financials - no new fetch/parse). Returns
    (inventory_tuple_or_None, revenue_tuple_or_None, fiscal_year, pdf_url)."""
    from tools.annual_report_financials import list_annual_report_years, _get_extracted_financials
    years = list_annual_report_years(sym, name)
    if not years:
        return None, None, None, None
    fiscal_year = years[0]
    parsed = _get_extracted_financials(sym, name, fiscal_year, consolidated=True)
    return parsed.get("inventory"), parsed.get("revenue"), fiscal_year, parsed.get("source_url")


def compute_e5_1_inventory_trend(symbol, name=None, force=False):
    """E.5.1 - Inventory trend. Spec formula: Inventory Growth =
    Current Inventory / Prior Inventory - 1. Deterministic (no LLM) -
    reuses the SAME real Annual Report Balance Sheet Inventory figures
    already extracted for the Inventory Turnover ratio.

    Same explicitly documented deviation as E.4.1: the spec's own
    sourcing path asks for an 8-quarter NSE XBRL Financial Results
    trend; no quarterly Balance Sheet fetcher exists anywhere in this
    codebase, so this uses the same real growth formula on real ANNUAL
    (year-over-year) Inventory instead, tagged 'period_type':'annual'
    throughout - never presented as the quarterly chart the spec
    describes.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "E.5.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        inventory, _revenue, fiscal_year, pdf_url = _fetch_inventory_and_revenue(sym, name)
        trend = []
        if inventory and inventory[0] is not None and inventory[1] is not None:
            trend = [
                {"period": f"FY{str(fiscal_year - 1)[-2:]}", "inventory_cr": inventory[1]},
                {"period": f"FY{str(fiscal_year)[-2:]}", "inventory_cr": inventory[0]},
            ]
    except Exception as e:
        print(f"[qualitative_engine] E.5.1 fetch failed for {sym}: {e}")
        trend = []
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Balance Sheet - Inventories (annual, not the 8-quarter XBRL trend the spec describes - no quarterly balance-sheet fetcher exists in this codebase)",
        "result": "CHECKED" if trend else "NOT_DISCLOSED",
        "note": None if trend else "Inventory could not be located on the Balance Sheet page of the latest Annual Report this run.",
    }]

    if not trend:
        payload = {
            "subpoint_id": subpoint_id, "title": "Inventory trend", "available": True,
            "trend": None, "period_type": None, "current_inventory_cr": None, "prior_inventory_cr": None,
            "growth_pct": None,
            "source_pdf_url": pdf_url,
            "rationale": "Inventory could not be located on the Balance Sheet page of the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    prior_inv, current_inv = trend[0]["inventory_cr"], trend[1]["inventory_cr"]
    growth_pct = round(100 * (current_inv / prior_inv - 1), 2) if prior_inv else None
    payload = {
        "subpoint_id": subpoint_id, "title": "Inventory trend", "available": True,
        "trend": trend, "period_type": "annual",
        "current_inventory_cr": current_inv, "prior_inventory_cr": prior_inv, "growth_pct": growth_pct,
        "source_pdf_url": pdf_url,
        "rationale": f"Inventory moved from Rs{prior_inv} cr ({trend[0]['period']}) to Rs{current_inv} cr ({trend[1]['period']}) -> {growth_pct:+.2f}% YoY (annual, not quarterly - see rationale note)." if growth_pct is not None else f"Inventory: Rs{current_inv} cr ({trend[1]['period']}); prior-year figure unusable for a growth %.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_e5_2_inventory_vs_demand(symbol, name=None, force=False):
    """E.5.2 - Inventory vs demand. Spec formula: Inventory-Demand
    Divergence = Inventory Growth - Revenue Growth. Deterministic (no
    LLM) - reuses the SAME real Annual Report Inventory AND Revenue
    figures already extracted together in one PDF parse (no second
    fetch). A positive divergence (inventory growing faster than
    revenue) is a real channel-stuffing/build-up signal; a negative one
    (inventory growing slower than or shrinking against revenue) is
    healthy. Same annual-not-quarterly deviation as E.5.1/E.4.1.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "E.5.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        inventory, revenue, fiscal_year, pdf_url = _fetch_inventory_and_revenue(sym, name)
        inv_growth = None
        rev_growth = None
        if inventory and inventory[0] is not None and inventory[1] not in (None, 0):
            inv_growth = round(100 * (inventory[0] / inventory[1] - 1), 2)
        if revenue and revenue[0] is not None and revenue[1] not in (None, 0):
            rev_growth = round(100 * (revenue[0] / revenue[1] - 1), 2)
    except Exception as e:
        print(f"[qualitative_engine] E.5.2 fetch failed for {sym}: {e}")
        inv_growth = rev_growth = None
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Balance Sheet Inventories vs P&L Revenue (annual, not the quarterly XBRL comparison the spec describes)",
        "result": "CHECKED" if (inv_growth is not None and rev_growth is not None) else "NOT_DISCLOSED",
        "note": None if (inv_growth is not None and rev_growth is not None) else "Inventory and/or Revenue could not both be located in the latest Annual Report this run.",
    }]

    if inv_growth is None or rev_growth is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Inventory vs demand", "available": True,
            "inventory_growth_pct": inv_growth, "revenue_growth_pct": rev_growth, "divergence_pct": None, "classification": None,
            "source_pdf_url": pdf_url,
            "rationale": "Inventory and/or Revenue could not both be located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    divergence = round(inv_growth - rev_growth, 2)
    classification = "Low" if divergence <= 5 else ("Moderate" if divergence <= 15 else "High")
    payload = {
        "subpoint_id": subpoint_id, "title": "Inventory vs demand", "available": True,
        "inventory_growth_pct": inv_growth, "revenue_growth_pct": rev_growth, "divergence_pct": divergence, "classification": classification,
        "source_pdf_url": pdf_url,
        "rationale": f"Inventory grew {inv_growth:+.2f}% vs Revenue {rev_growth:+.2f}% YoY -> divergence {divergence:+.2f}pp -> {classification}.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


_INVENTORY_OBSOLESCENCE_ANCHORS = [
    "write-down", "write down", "provision for slow moving", "obsolete",
    "net realisable value", "slow moving inventory", "inventory provision",
]


def compute_e5_3_inventory_obsolescence(symbol, name=None, force=False):
    """E.5.3 - Obsolete / slow-moving inventory. Spec formula:
    Obsolescence Risk Score (1-5) based on write-downs, ageing and
    management commentary. Deterministic (no LLM) - see
    tools.inventory_risk_scoring.score_inventory_obsolescence: reads
    the real Ind AS 2 inventory write-down-to-NRV disclosure (current
    and prior-year charge). Sourcing: NSE Corporate Filings - Annual
    Reports - Notes to Accounts - Inventories - write-down / provision
    / NRV disclosures.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "E.5.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import _fetch_ar_evidence_excerpts
        from tools.inventory_risk_scoring import score_inventory_obsolescence
        evidence = _fetch_ar_evidence_excerpts(
            sym, name, _INVENTORY_OBSOLESCENCE_ANCHORS, "ar_invobs_text_v1",
            max_per_page=3, max_excerpts=10, fetch_label="inventory-obsolescence",
        )
        text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or [])) if isinstance(evidence, dict) else ""
        pdf_url = evidence.get("pdf_url") if isinstance(evidence, dict) else None
        result = score_inventory_obsolescence(text)
    except Exception as e:
        print(f"[qualitative_engine] E.5.3 fetch failed for {sym}: {e}")
        result = {"writedown_cr": None, "writedown_prior_cr": None, "writedown_trend": None, "obsolescence_score": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Notes to Accounts - Inventories - write-down / provision / NRV disclosures",
        "result": "CHECKED" if result["obsolescence_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["obsolescence_score"] is not None else "No inventory write-down/slow-moving-inventory disclosure was located in the latest Annual Report this run.",
    }]

    if result["obsolescence_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Obsolete / slow-moving inventory", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No inventory write-down/slow-moving-inventory disclosure was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    if result.get("writedown_cr") is not None:
        rationale = f"Inventory write-down of Rs{result['writedown_cr']} cr (prior: Rs{result['writedown_prior_cr']} cr) -> {result['writedown_trend']} -> score {result['obsolescence_score']}/5."
    else:
        rationale = f"Obsolete/slow-moving inventory language disclosed without a distinct write-down figure -> score {result['obsolescence_score']}/5."
    payload = {
        "subpoint_id": subpoint_id, "title": "Obsolete / slow-moving inventory", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": rationale,
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_e5_inventory_demand_risk(symbol, name=None, force=False):
    """E.5 - Inventory build vs demand: potential channel stuffing or
    obsolete inventory: combines the three defined sub-points (E.5.1
    trend, E.5.2 vs-demand divergence, E.5.3 obsolescence) into a
    single grounded payload, sourced from the same real Annual Report
    Balance Sheet / P&L / Notes to Accounts text - no LLM call.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    e5_1 = compute_e5_1_inventory_trend(sym, name, force=force)
    e5_2 = compute_e5_2_inventory_vs_demand(sym, name, force=force)
    e5_3 = compute_e5_3_inventory_obsolescence(sym, name, force=force)

    parts = []
    if e5_1.get("growth_pct") is not None:
        parts.append(f"Inventory growth: {e5_1['growth_pct']:+.2f}% YoY.")
    if e5_2.get("divergence_pct") is not None:
        parts.append(f"Vs demand: {e5_2['divergence_pct']:+.2f}pp divergence ({e5_2['classification']}).")
    if e5_3.get("obsolescence_score") is not None:
        parts.append(f"Obsolescence: score {e5_3['obsolescence_score']}/5.")
    if not parts:
        parts.append("No inventory trend, demand-divergence, or obsolescence evidence was located for this company this run.")

    _tags = [t.get("confidence_tag") for t in (e5_1, e5_2, e5_3)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (e5_1, e5_2, e5_3) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "E.5",
        "title": "Inventory build vs demand: potential channel stuffing or obsolete inventory",
        "available": True,
        "e5_1": e5_1, "e5_2": e5_2, "e5_3": e5_3,
        "rationale": " ".join(parts),
        "pathway_results": (e5_1.get("pathway_results") or [])[:1] + (e5_2.get("pathway_results") or [])[:1] + (e5_3.get("pathway_results") or [])[:1],
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


def compute_e6_1_off_market_transactions(symbol, name=None, force=False):
    """E.6.1 - Off-market transactions. Spec formula: Transaction Risk
    Score (1-5) based on disclosure, counterparty and commercial
    rationale. Deterministic (no LLM) - see
    tools.off_market_scoring.score_off_market_transactions: scans real
    NSE Corporate Announcements for off-market/block-deal/bulk-deal/
    inter-se-transfer/preferential-issue language, cross-checked
    against the same Related Party Disclosures note text used for
    E.1/D.5. Sourcing: NSE Corporate Filings - Corporate Announcements
    (keyword search) + Annual Reports - Notes to Accounts.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "E.6.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.nse_announcements import fetch_announcements
        from tools.annual_report_financials import fetch_rpt_evidence_from_annual_report
        from tools.off_market_scoring import classify_off_market_announcements, score_off_market_transactions
        announcements = fetch_announcements(sym) or []
        matches = classify_off_market_announcements(announcements)
        evidence = fetch_rpt_evidence_from_annual_report(sym, name) or {}
        rpt_text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or []))
        result = score_off_market_transactions(matches, rpt_text)
    except Exception as e:
        print(f"[qualitative_engine] E.6.1 fetch failed for {sym}: {e}")
        result = {"transaction_count": None, "named_counterparty_count": None, "rationale_disclosed_count": None, "risk_score": None}

    pathway_results = [{
        "pathway_id": "PORTAL-02",
        "source": "NSE Corporate Filings - Corporate Announcements (off-market/block-deal/inter-se-transfer keyword search) + Annual Reports - Notes to Accounts",
        "result": "CHECKED" if result["risk_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["risk_score"] is not None else "No off-market/block-deal/inter-se-transfer/preferential-issue disclosure was located this run.",
    }]

    if result["risk_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Off-market transactions", "available": True, **result,
            "rationale": "No off-market/block-deal/inter-se-transfer/preferential-issue disclosure was located this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Off-market transactions", "available": True, **result,
        "rationale": f"{result['transaction_count']} real off-market/block-deal-type disclosure(s) found, {result['named_counterparty_count']} naming a counterparty and {result['rationale_disclosed_count']} stating a commercial rationale -> score {result['risk_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_e6_2_non_arms_length_contracts(symbol, name=None, force=False):
    """E.6.2 - Non-arm's-length contracts. Spec formula: Arm's-length
    Evidence Score (1-5). Deterministic (no LLM) - reuses
    tools.rpt_leakage_scoring.score_payment_rationale directly (the
    same real arm's-length/Audit-Committee-approval signal already
    built for E.1.3), since the spec's own sourcing path for E.6.2
    ("Related Party Disclosures - contractual terms, pricing basis and
    approval") is identical to E.1.3's. Sourcing: NSE Corporate
    Filings - Annual Reports - Related Party Disclosures - contractual
    terms, pricing basis and approval.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "E.6.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import fetch_rpt_evidence_from_annual_report
        from tools.rpt_leakage_scoring import score_payment_rationale
        evidence = fetch_rpt_evidence_from_annual_report(sym, name) or {}
        text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or []))
        result = score_payment_rationale(text)
        result = {"arms_length_confirmed": result.get("arms_length_confirmed"), "audit_committee_approved": result.get("audit_committee_approved"),
                  "opaque_flag": result.get("opaque_flag"), "evidence_score": result.get("rationale_score")}
    except Exception as e:
        print(f"[qualitative_engine] E.6.2 fetch failed for {sym}: {e}")
        result = {"arms_length_confirmed": None, "audit_committee_approved": None, "opaque_flag": None, "evidence_score": None}

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Related Party Disclosures - contractual terms, pricing basis and approval",
        "result": "CHECKED" if result["evidence_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["evidence_score"] is not None else "No explicit arm's-length pricing statement or Audit Committee approval language was located in the Related Party Disclosures note this run.",
    }]

    if result["evidence_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Non-arm's-length contracts", "available": True, **result,
            "rationale": "No explicit arm's-length pricing statement or Audit Committee approval language was located in the Related Party Disclosures note this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    if result["opaque_flag"]:
        rationale = "An explicit non-arm's-length pricing statement or Audit Committee approval gap was found -> score 1/5."
    else:
        rationale = f"Arm's-length pricing {'confirmed' if result['arms_length_confirmed'] else 'not explicitly confirmed'}; Audit Committee approval {'documented' if result['audit_committee_approved'] else 'not explicitly documented'} -> score {result['evidence_score']}/5."
    payload = {
        "subpoint_id": subpoint_id, "title": "Non-arm's-length contracts", "available": True, **result,
        "rationale": rationale,
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_e6_off_market_arms_length(symbol, name=None, force=False):
    """E.6 - Off-market transactions, non-arm's length contracts, side-
    letters or sweetheart deals: combines the two defined sub-points
    (E.6.1 off-market transactions, E.6.2 non-arm's-length contracts)
    into a single grounded payload (E.6.3 is not defined in the spec
    workbook, so no sub-point is fabricated for it), sourced from the
    same real NSE Corporate Announcements and Related Party Disclosures
    note already built for D.1-D.3/E.1 - no LLM call.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    e6_1 = compute_e6_1_off_market_transactions(sym, name, force=force)
    e6_2 = compute_e6_2_non_arms_length_contracts(sym, name, force=force)

    parts = []
    if e6_1.get("risk_score") is not None:
        parts.append(f"Off-market transactions: score {e6_1['risk_score']}/5.")
    if e6_2.get("evidence_score") is not None:
        parts.append(f"Non-arm's-length contracts: score {e6_2['evidence_score']}/5.")
    if not parts:
        parts.append("No off-market-transaction or non-arm's-length-contract evidence was located for this company this run.")

    _tags = [t.get("confidence_tag") for t in (e6_1, e6_2)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (e6_1, e6_2) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "E.6",
        "title": "Off-market transactions, non-arm's length contracts, side-letters or sweetheart deals",
        "available": True,
        "e6_1": e6_1, "e6_2": e6_2,
        "rationale": " ".join(parts),
        "pathway_results": (e6_1.get("pathway_results") or [])[:1] + (e6_2.get("pathway_results") or [])[:1],
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


_ACCOUNTING_POLICY_ANCHORS = [
    "change in accounting policy", "change in accounting policies", "change in accounting estimate",
    "prospective application", "revised its estimate", "reassessed",
    "new standards, interpretations and amendments", "new and amended standards",
    "amendments adopted", "notified amendments", "standards issued but not yet effective",
    "amendments to ind as", "mca notified", "ministry of corporate affairs (“mca”) notifies",
]
_EXCEPTIONAL_ITEMS_ANCHORS = ["exceptional item", "other income"]


def compute_e7_1_policy_changes(symbol, name=None, force=False):
    """E.7.1 - Accounting policy changes. Spec formula: Policy Change
    Count = material policy changes over review period. Deterministic
    (no LLM) - see tools.accounting_policy_scoring.score_policy_changes.

    Same explicitly documented deviation as E.4.1/E.5.1: the spec's own
    sourcing path asks to "compare last 5 years"; no multi-year AR
    history fetcher exists in this codebase. Ind AS 8 mandates every
    policy change be disclosed in the YEAR it's made, so this reads the
    CURRENT year's real disclosure (what changed this year), not a
    fabricated 5-year retrospective. Sourcing: NSE Corporate Filings -
    Annual Reports - Significant Accounting Policies - Changes in
    Accounting Policies / estimates.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "E.7.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import _fetch_ar_evidence_excerpts
        from tools.accounting_policy_scoring import score_policy_changes
        evidence = _fetch_ar_evidence_excerpts(
            sym, name, _ACCOUNTING_POLICY_ANCHORS, "ar_policychg_text_v4",
            max_per_page=8, max_excerpts=25, fetch_label="accounting-policy-changes",
        )
        text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or [])) if isinstance(evidence, dict) else ""
        pdf_url = evidence.get("pdf_url") if isinstance(evidence, dict) else None
        result = score_policy_changes(text)
    except Exception as e:
        print(f"[qualitative_engine] E.7.1 fetch failed for {sym}: {e}")
        result = {"policy_change_count": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Significant Accounting Policies - Changes in Accounting Policies / estimates (current year only - no multi-year AR history fetcher exists in this codebase)",
        "result": "CHECKED" if result["policy_change_count"] is not None else "NOT_DISCLOSED",
        "note": None if result["policy_change_count"] is not None else "No accounting-policy-change or standard-amendment-adoption language was located in the latest Annual Report this run.",
    }]

    if result["policy_change_count"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Accounting policy changes", "available": True, **result,
            "source_pdf_url": pdf_url, "period_type": None,
            "rationale": "No accounting-policy-change or standard-amendment-adoption language was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Accounting policy changes", "available": True, **result,
        "source_pdf_url": pdf_url, "period_type": "current_year",
        "rationale": f"{result['policy_change_count']} accounting policy change(s)/standard amendment adoption(s) disclosed this year (current year only, not the 5-year comparison the spec describes).",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_e7_2_estimate_changes(symbol, name=None, force=False):
    """E.7.2 - Changes in accounting estimates. Spec formula: Estimate
    Change Score (1-5) based on frequency, magnitude and explanation.
    Deterministic (no LLM) - see
    tools.accounting_policy_scoring.score_estimate_changes. Same
    current-year-only deviation as E.7.1. Sourcing: NSE Corporate
    Filings - Annual Reports - Significant Accounting Judgements /
    Estimates.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "E.7.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import _fetch_ar_evidence_excerpts
        from tools.accounting_policy_scoring import score_estimate_changes
        evidence = _fetch_ar_evidence_excerpts(
            sym, name, _ACCOUNTING_POLICY_ANCHORS, "ar_policychg_text_v4",
            max_per_page=8, max_excerpts=25, fetch_label="accounting-estimate-changes",
        )
        text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or [])) if isinstance(evidence, dict) else ""
        pdf_url = evidence.get("pdf_url") if isinstance(evidence, dict) else None
        result = score_estimate_changes(text)
    except Exception as e:
        print(f"[qualitative_engine] E.7.2 fetch failed for {sym}: {e}")
        result = {"estimate_change_count": None, "explained_count": None, "estimate_change_score": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Annual Reports - Significant Accounting Judgements / Estimates (current year only - no multi-year AR history fetcher exists in this codebase)",
        "result": "CHECKED" if result["estimate_change_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["estimate_change_score"] is not None else "No accounting-estimate-change language was located in the latest Annual Report this run.",
    }]

    if result["estimate_change_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Changes in accounting estimates", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No accounting-estimate-change language was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Changes in accounting estimates", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": f"{result['estimate_change_count']} estimate change(s) disclosed, {result['explained_count']} with a stated reason -> score {result['estimate_change_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def _fetch_exceptional_items_text_and_pbt(sym, name):
    """Shared fetch for E.7.3/E.7.4 - real P&L Exceptional Items text
    plus the real current-year Profit Before Tax (reused from the same
    cached PDF extraction as E.4/E.5's Receivables/Inventory Turnover,
    no new fetch/parse). Returns (text, pdf_url, current_pbt_cr)."""
    from tools.annual_report_financials import _fetch_ar_evidence_excerpts, list_annual_report_years, _get_extracted_financials
    evidence = _fetch_ar_evidence_excerpts(
        sym, name, _EXCEPTIONAL_ITEMS_ANCHORS, "ar_exceptionalitems_text_v2",
        max_per_page=3, max_excerpts=10, fetch_label="exceptional-items",
    )
    text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or [])) if isinstance(evidence, dict) else ""
    pdf_url = evidence.get("pdf_url") if isinstance(evidence, dict) else None
    current_pbt = None
    try:
        years = list_annual_report_years(sym, name)
        if years:
            parsed = _get_extracted_financials(sym, name, years[0], consolidated=True)
            pbt = parsed.get("pbt")
            if pbt and pbt[0] is not None:
                current_pbt = pbt[0]
    except Exception:
        pass
    return text, pdf_url, current_pbt


def compute_e7_3_oneoff_adjustments(symbol, name=None, force=False):
    """E.7.3 - One-off adjustments / special items. Spec formula:
    Recurring One-off Flag = count of repeated exceptional/special
    items over review period. Deterministic (no LLM) - see
    tools.accounting_policy_scoring.score_oneoff_adjustments: reads
    the real P&L Exceptional Items line (current + immediately
    preceding year - not a fabricated 5-year series this codebase has
    no quarterly/multi-year source for). Sourcing: NSE Corporate
    Filings - Financial Results - Statement of Profit & Loss -
    exceptional items / other income / other expenses.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "E.7.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.accounting_policy_scoring import score_oneoff_adjustments
        text, pdf_url, _pbt = _fetch_exceptional_items_text_and_pbt(sym, name)
        result = score_oneoff_adjustments(text)
    except Exception as e:
        print(f"[qualitative_engine] E.7.3 fetch failed for {sym}: {e}")
        result = {"current_exceptional_cr": None, "prior_exceptional_cr": None, "recurring_flag": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Financial Results - Statement of Profit & Loss - exceptional items / other income / other expenses (current + prior year only - no multi-year XBRL fetcher exists in this codebase)",
        "result": "CHECKED" if result["current_exceptional_cr"] is not None else "NOT_DISCLOSED",
        "note": None if result["current_exceptional_cr"] is not None else "No Exceptional Items P&L line was located in the latest Annual Report this run.",
    }]

    if result["current_exceptional_cr"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "One-off adjustments / special items", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No Exceptional Items P&L line was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "One-off adjustments / special items", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": f"Exceptional items: Rs{result['current_exceptional_cr']} cr this year (Rs{result['prior_exceptional_cr']} cr prior year) -> " + ("Recurring (non-zero in both years)" if result["recurring_flag"] else "Not recurring"),
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_e7_4_earnings_smoothing(symbol, name=None, force=False):
    """E.7.4 - Earnings smoothing signals. Spec formula: Smoothing
    Risk Score (1-5) based on repeated adjustments that materially
    change reported earnings. Deterministic (no LLM) - see
    tools.accounting_policy_scoring.score_earnings_smoothing: combines
    E.7.3's real recurring-exceptional-item flag with the item's real
    magnitude relative to Profit Before Tax. Sourcing: NSE Corporate
    Filings - Financial Results - operating profit / exceptional items
    / other income comparison; Annual Reports - accounting policy
    notes.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "E.7.4"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.accounting_policy_scoring import score_oneoff_adjustments, score_earnings_smoothing
        text, pdf_url, current_pbt = _fetch_exceptional_items_text_and_pbt(sym, name)
        oneoff = score_oneoff_adjustments(text)
        result = score_earnings_smoothing(oneoff, current_pbt_cr=current_pbt)
    except Exception as e:
        print(f"[qualitative_engine] E.7.4 fetch failed for {sym}: {e}")
        result = {"exceptional_pct_of_pbt": None, "smoothing_risk_score": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-04",
        "source": "NSE Corporate Filings - Financial Results - operating profit / exceptional items / other income comparison; Annual Reports - accounting policy notes",
        "result": "CHECKED" if result["smoothing_risk_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["smoothing_risk_score"] is not None else "No Exceptional Items P&L line was located in the latest Annual Report this run.",
    }]

    if result["smoothing_risk_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Earnings smoothing signals", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No Exceptional Items P&L line was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Earnings smoothing signals", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": (f"Recurring exceptional item is {result['exceptional_pct_of_pbt']}% of PBT" if result.get("exceptional_pct_of_pbt") is not None else "Recurring exceptional item found, PBT unavailable for magnitude context") + f" -> score {result['smoothing_risk_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_e7_accounting_policy_risk(symbol, name=None, force=False):
    """E.7 - Unusual accounting policies or frequent changes in
    accounting estimates: combines the four defined sub-points (E.7.1
    policy changes, E.7.2 estimate changes, E.7.3 one-off adjustments,
    E.7.4 earnings smoothing) into a single grounded payload, sourced
    from the same real Annual Report Significant Accounting Policies /
    P&L Notes text - no LLM call.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    e7_1 = compute_e7_1_policy_changes(sym, name, force=force)
    e7_2 = compute_e7_2_estimate_changes(sym, name, force=force)
    e7_3 = compute_e7_3_oneoff_adjustments(sym, name, force=force)
    e7_4 = compute_e7_4_earnings_smoothing(sym, name, force=force)

    parts = []
    if e7_1.get("policy_change_count") is not None:
        parts.append(f"Policy changes: {e7_1['policy_change_count']} this year.")
    if e7_2.get("estimate_change_score") is not None:
        parts.append(f"Estimate changes: score {e7_2['estimate_change_score']}/5.")
    if e7_3.get("recurring_flag") is not None:
        parts.append(f"One-off items: {'recurring' if e7_3['recurring_flag'] else 'not recurring'}.")
    if e7_4.get("smoothing_risk_score") is not None:
        parts.append(f"Smoothing risk: score {e7_4['smoothing_risk_score']}/5.")
    if not parts:
        parts.append("No accounting-policy-change, estimate-change, or exceptional-item evidence was located for this company this run.")

    _tags = [t.get("confidence_tag") for t in (e7_1, e7_2, e7_3, e7_4)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (e7_1, e7_2, e7_3, e7_4) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "E.7",
        "title": "Unusual accounting policies or frequent changes in accounting estimates",
        "available": True,
        "e7_1": e7_1, "e7_2": e7_2, "e7_3": e7_3, "e7_4": e7_4,
        "rationale": " ".join(parts),
        "pathway_results": (e7_1.get("pathway_results") or [])[:1] + (e7_2.get("pathway_results") or [])[:1] + (e7_3.get("pathway_results") or [])[:1] + (e7_4.get("pathway_results") or [])[:1],
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


_COMPETITIVE_LANDSCAPE_ANCHORS = [
    "market share", "market leader", "market leadership", "competitors", "competition",
    "industry structure", "competitive landscape", "largest exporter", "compete with",
    "principal competitors", "key competitors",
]


def _fetch_competitive_landscape_text(sym, name):
    from tools.annual_report_financials import _fetch_ar_evidence_excerpts
    evidence = _fetch_ar_evidence_excerpts(
        sym, name, _COMPETITIVE_LANDSCAPE_ANCHORS, "ar_complandscape_text_v1",
        max_per_page=5, max_excerpts=25, fetch_label="competitive-landscape",
    )
    text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or [])) if isinstance(evidence, dict) else ""
    pdf_url = evidence.get("pdf_url") if isinstance(evidence, dict) else None
    return text, pdf_url


def compute_f1_1_competitor_count(symbol, name=None, force=False):
    """F.1.1 - Number of material competitors. Deterministic (no LLM) -
    see tools.competitive_landscape_scoring.score_competitor_count. Real
    Indian AR MD&A sections almost never name specific rival companies
    (commercially sensitive), confirmed by direct inspection of
    HINDUNILVR, MARUTI, and ASIANPAINT ARs - none name a single
    competitor - so this is honestly N/A far more often than F.1.2/F.1.3.
    Sourcing: NSE Corporate Filings - Annual Reports - MD&A - Industry
    Structure / Competition.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "F.1.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.competitive_landscape_scoring import score_competitor_count
        text, pdf_url = _fetch_competitive_landscape_text(sym, name)
        result = score_competitor_count(text)
    except Exception as e:
        print(f"[qualitative_engine] F.1.1 fetch failed for {sym}: {e}")
        result = {"competitor_count": None, "competitor_names": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-05",
        "source": "NSE Corporate Filings - Annual Reports - MD&A - Industry Structure / Competition",
        "result": "CHECKED" if result["competitor_count"] is not None else "NOT_DISCLOSED",
        "note": None if result["competitor_count"] is not None else "No named-competitor list was located in the latest Annual Report this run (Indian issuers routinely avoid naming rivals).",
    }]

    if result["competitor_count"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Number of material competitors", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No named-competitor list was located in the latest Annual Report this run (Indian issuers routinely avoid naming rivals in MD&A).",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Number of material competitors", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": f"{result['competitor_count']} named competitor(s) identified in the latest Annual Report MD&A.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_f1_2_market_position(symbol, name=None, force=False):
    """F.1.2 - Relative market position. Spec: Market Position Score
    (1-5) from disclosed market share/rank; do not estimate when not
    disclosed. Deterministic (no LLM) - see
    tools.competitive_landscape_scoring.score_market_position. Sourcing:
    NSE Corporate Filings - Annual Reports - MD&A - Industry Overview /
    Market Share.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "F.1.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.competitive_landscape_scoring import score_market_position
        text, pdf_url = _fetch_competitive_landscape_text(sym, name)
        result = score_market_position(text)
    except Exception as e:
        print(f"[qualitative_engine] F.1.2 fetch failed for {sym}: {e}")
        result = {"market_share_pct": None, "market_position_score": None, "basis": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-05",
        "source": "NSE Corporate Filings - Annual Reports - MD&A - Industry Overview / Market Share",
        "result": "CHECKED" if result["market_position_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["market_position_score"] is not None else "No disclosed market share % or leadership/rank claim was located in the latest Annual Report this run.",
    }]

    if result["market_position_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Relative market position", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No disclosed market share % or leadership/rank claim was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    if result["basis"] == "disclosed_market_share_pct":
        rationale = f"Disclosed market share: {result['market_share_pct']}% (score {result['market_position_score']}/5)."
    elif result["basis"] == "disclosed_segment_market_share_pct":
        rationale = f"Disclosed SEGMENT-level market share: {result['market_share_pct']}% (not overall market share; score {result['market_position_score']}/5)."
    else:
        rationale = f"Disclosed market leadership/rank claim (no numeric % given; score {result['market_position_score']}/5)."

    payload = {
        "subpoint_id": subpoint_id, "title": "Relative market position", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": rationale,
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_f1_3_competitor_strength(symbol, name=None, force=False):
    """F.1.3 - Competitor strength. Spec: Competitive Strength Score
    (1-5) based on disclosed peer advantages. Deterministic (no LLM) -
    see tools.competitive_landscape_scoring.score_competitor_strength.
    Sourcing: NSE Corporate Filings - Annual Reports - MD&A -
    competitive advantages / peer comparison.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "F.1.3"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.competitive_landscape_scoring import score_competitor_strength
        text, pdf_url = _fetch_competitive_landscape_text(sym, name)
        result = score_competitor_strength(text)
    except Exception as e:
        print(f"[qualitative_engine] F.1.3 fetch failed for {sym}: {e}")
        result = {"strength_dimensions": None, "competitive_strength_score": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-05",
        "source": "NSE Corporate Filings - Annual Reports - MD&A - competitive advantages / peer comparison",
        "result": "CHECKED" if result["competitive_strength_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["competitive_strength_score"] is not None else "No disclosed scale/distribution/technology/cost advantage language was located in the latest Annual Report this run.",
    }]

    if result["competitive_strength_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Competitor strength", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No disclosed scale/distribution/technology/cost advantage language was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    dims = ", ".join(result["strength_dimensions"])
    payload = {
        "subpoint_id": subpoint_id, "title": "Competitor strength", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": f"Disclosed competitive advantage(s): {dims} (score {result['competitive_strength_score']}/5).",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_f1_competitive_landscape(symbol, name=None, force=False):
    """F.1 - Competitive landscape: number and strength of competitors,
    market shares. Combines F.1.1-F.1.3 into a single grounded payload,
    sourced from the same real Annual Report MD&A text - no LLM call.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    f1_1 = compute_f1_1_competitor_count(sym, name, force=force)
    f1_2 = compute_f1_2_market_position(sym, name, force=force)
    f1_3 = compute_f1_3_competitor_strength(sym, name, force=force)

    parts = []
    if f1_1.get("competitor_count") is not None:
        parts.append(f"Named competitors: {f1_1['competitor_count']}.")
    if f1_2.get("market_position_score") is not None:
        parts.append(f"Market position: score {f1_2['market_position_score']}/5.")
    if f1_3.get("competitive_strength_score") is not None:
        parts.append(f"Competitive strength: score {f1_3['competitive_strength_score']}/5.")
    if not parts:
        parts.append("No named-competitor, market-share/rank, or competitive-advantage evidence was located for this company this run.")

    _tags = [t.get("confidence_tag") for t in (f1_1, f1_2, f1_3)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (f1_1, f1_2, f1_3) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "F.1",
        "title": "Competitive landscape: number and strength of competitors, market shares",
        "available": True,
        "f1_1": f1_1, "f1_2": f1_2, "f1_3": f1_3,
        "rationale": " ".join(parts),
        "pathway_results": (f1_1.get("pathway_results") or [])[:1] + (f1_2.get("pathway_results") or [])[:1] + (f1_3.get("pathway_results") or [])[:1],
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


_ENTRY_BARRIER_ANCHORS = [
    "entry barrier", "barriers to entry", "capital intensive", "capital intensity",
    "licences required", "regulatory approvals", "economies of scale", "new entrants",
    "distribution network", "proprietary technology", "patents",
]


def compute_f2_1_entry_barriers(symbol, name=None, force=False):
    """F.2.1 - Entry barriers. Spec: Entry Barrier Score (1-5).
    Deterministic (no LLM) - see
    tools.entry_barrier_scoring.score_entry_barriers. Real Indian AR
    MD&A text almost never uses the literal phrase "entry barrier" -
    confirmed by direct inspection of MARUTI, ULTRACEMCO, and CIPLA ARs
    - so this counts real, generic barrier-type language (regulatory/
    licensing, capital intensity, distribution, technology/IP, scale)
    instead, and will genuinely be N/A more often than most sub-points.
    Sourcing: NSE Corporate Filings - Annual Reports - MD&A - Industry
    Structure / Risk Factors.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "F.2.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import _fetch_ar_evidence_excerpts
        from tools.entry_barrier_scoring import score_entry_barriers
        evidence = _fetch_ar_evidence_excerpts(
            sym, name, _ENTRY_BARRIER_ANCHORS, "ar_entrybarrier_text_v1",
            max_per_page=5, max_excerpts=25, fetch_label="entry-barriers",
        )
        text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or [])) if isinstance(evidence, dict) else ""
        pdf_url = evidence.get("pdf_url") if isinstance(evidence, dict) else None
        result = score_entry_barriers(text)
    except Exception as e:
        print(f"[qualitative_engine] F.2.1 fetch failed for {sym}: {e}")
        result = {"barrier_dimensions": None, "entry_barrier_score": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-05",
        "source": "NSE Corporate Filings - Annual Reports - MD&A - Industry Structure / Risk Factors",
        "result": "CHECKED" if result["entry_barrier_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["entry_barrier_score"] is not None else "No regulatory/licensing, capital-intensity, distribution, technology/IP, or scale barrier language was located in the latest Annual Report this run.",
    }]

    if result["entry_barrier_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Entry barriers", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No regulatory/licensing, capital-intensity, distribution, technology/IP, or scale barrier language was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    dims = ", ".join(result["barrier_dimensions"])
    payload = {
        "subpoint_id": subpoint_id, "title": "Entry barriers", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": f"Disclosed entry-barrier dimension(s): {dims} (score {result['entry_barrier_score']}/5).",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_f2_new_entrant_threat(symbol, name=None, force=False):
    """F.2 - Threat from new entrants or substitute technologies.
    Currently wraps F.2.1 (Entry barriers) - the only sub-point
    supplied so far; combiner shape kept consistent with every other
    F/E-series topic so later sub-points (F.2.2/F.2.3, if supplied) can
    be added without changing this function's signature or callers.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    f2_1 = compute_f2_1_entry_barriers(sym, name, force=force)

    parts = []
    if f2_1.get("entry_barrier_score") is not None:
        parts.append(f"Entry barriers: score {f2_1['entry_barrier_score']}/5.")
    if not parts:
        parts.append("No entry-barrier evidence was located for this company this run.")

    payload = {
        "subpoint_id": "F.2",
        "title": "Threat from new entrants or substitute technologies",
        "available": True,
        "f2_1": f2_1,
        "rationale": " ".join(parts),
        "pathway_results": (f2_1.get("pathway_results") or [])[:1],
        "confidence_tag": f2_1.get("confidence_tag") or "SEARCH_INCONCLUSIVE",
        "retrieved_at": f2_1.get("retrieved_at") or time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


def compute_f3_2_price_war_evidence(symbol, name=None, force=False, margins_annual=None):
    """F.3.2 - Price-war evidence. Spec formula: Margin Pressure =
    Current Margin - Prior-period Margin; interpret alongside management
    commentary. Deterministic (no LLM) - `margins_annual` is computed
    upstream (agent/stock_agent.py) directly from the company's own
    audited annual gross/operating margins (the same financial-statement
    pipeline every Sr 1-92 ratio card and A.6 margin sustainability use)
    and passed in here - real numbers from the XBRL Financial Results
    the spec's own sourcing path names, not text-mined from the AR.
    F.3.1 was left blank in the spec table supplied - not built.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "F.3.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    rows = [r for r in (margins_annual or []) if str(r.get("date", "")).upper() != "TTM"]
    op_rows = [r for r in rows if r.get("ebit_margin") is not None]
    gross_rows = [r for r in rows if r.get("gross_margin") is not None]

    pathway_results = [{
        "pathway_id": "XBRL-01",
        "source": "NSE Corporate Filings - Financial Results - XBRL/attachment - gross/operating margin trend",
        "result": "CHECKED" if len(op_rows) >= 2 else "NOT_DISCLOSED",
        "note": None if len(op_rows) >= 2 else "Fewer than two years of real operating-margin data were available for this company.",
    }]

    if len(op_rows) < 2:
        payload = {
            "subpoint_id": subpoint_id, "title": "Price-war evidence", "available": True,
            "op_margin_pressure_pp": None, "gross_margin_pressure_pp": None, "classification": None,
            "op_margin_series": None,
            "rationale": "Fewer than two years of real operating-margin data were available for this company.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    current, prior = op_rows[-1], op_rows[-2]
    op_pressure_pp = round((current["ebit_margin"] - prior["ebit_margin"]) * 100, 2)
    gross_pressure_pp = None
    if len(gross_rows) >= 2:
        gcurrent, gprior = gross_rows[-1], gross_rows[-2]
        gross_pressure_pp = round((gcurrent["gross_margin"] - gprior["gross_margin"]) * 100, 2)

    if op_pressure_pp <= -2.0:
        classification = "Price-war evidence (significant compression)"
    elif op_pressure_pp <= -0.5:
        classification = "Margin pressure"
    elif op_pressure_pp >= 0.5:
        classification = "Margin expansion"
    else:
        classification = "Stable"

    op_margin_series = [
        {"label": str(r.get("date", ""))[:7], "value": round(r["ebit_margin"] * 100, 2)}
        for r in op_rows[-8:]
    ]

    parts = [f"Operating margin {op_pressure_pp:+.2f}pp YoY ({prior['ebit_margin']*100:.2f}% -> {current['ebit_margin']*100:.2f}%) -> {classification}."]
    if gross_pressure_pp is not None:
        parts.append(f"Gross margin {gross_pressure_pp:+.2f}pp YoY.")

    payload = {
        "subpoint_id": subpoint_id, "title": "Price-war evidence", "available": True,
        "op_margin_pressure_pp": op_pressure_pp, "gross_margin_pressure_pp": gross_pressure_pp,
        "classification": classification, "op_margin_series": op_margin_series,
        "rationale": " ".join(parts),
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_f3_price_dynamics(symbol, name=None, force=False, margins_annual=None):
    """F.3 - Pricing dynamics in sector: margin pressure or price wars.
    Wraps F.3.2 (Price-war evidence) - F.3.1 was left blank in the spec
    table supplied, so not built.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    f3_2 = compute_f3_2_price_war_evidence(sym, name, force=force, margins_annual=margins_annual)

    payload = {
        "subpoint_id": "F.3",
        "title": "Pricing dynamics in sector: margin pressure or price wars",
        "available": True,
        "f3_2": f3_2,
        "rationale": f3_2.get("rationale") or "No margin-trend evidence was located for this company this run.",
        "pathway_results": (f3_2.get("pathway_results") or [])[:1],
        "confidence_tag": f3_2.get("confidence_tag") or "SEARCH_INCONCLUSIVE",
        "retrieved_at": f3_2.get("retrieved_at") or time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


_FOREIGN_COMPETITION_ANCHORS = [
    "excessive imports", "import pressure", "cheap imports", "cheaper imports", "anti-dumping", "anti dumping",
    "dumping duty", "safeguard duty", "import quota", "import duty", "import policy", "ITC(HS)",
    "chinese imports", "import substitution", "global players", "multinational compan", "international competitor",
    "foreign compan",
]


def _fetch_foreign_competition_text(sym, name):
    from tools.annual_report_financials import _fetch_ar_evidence_excerpts
    evidence = _fetch_ar_evidence_excerpts(
        sym, name, _FOREIGN_COMPETITION_ANCHORS, "ar_foreigncomp_text_v2",
        max_per_page=5, max_excerpts=25, fetch_label="foreign-competition",
    )
    text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or [])) if isinstance(evidence, dict) else ""
    pdf_url = evidence.get("pdf_url") if isinstance(evidence, dict) else None
    return text, pdf_url


def compute_f5_1_foreign_competitor_presence(symbol, name=None, force=False):
    """F.5.1 - Foreign competitor presence. Spec: Foreign Competition
    Score (1-5). Deterministic (no LLM) - see
    tools.foreign_competition_scoring.score_foreign_competitor_presence.
    Real Indian AR MD&A coverage of foreign/import competition is
    genuinely sector-driven - confirmed by direct inspection: TATASTEEL
    explicitly discusses excessive imports and China's export volumes;
    ULTRACEMCO (cement, not economically tradable over long distances)
    barely mentions it. Sourcing: NSE Corporate Filings - Annual
    Reports - MD&A - Competition / Industry Overview.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "F.5.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.foreign_competition_scoring import score_foreign_competitor_presence
        text, pdf_url = _fetch_foreign_competition_text(sym, name)
        result = score_foreign_competitor_presence(text)
    except Exception as e:
        print(f"[qualitative_engine] F.5.1 fetch failed for {sym}: {e}")
        result = {"presence_dimensions": None, "foreign_competition_score": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-05",
        "source": "NSE Corporate Filings - Annual Reports - MD&A - Competition / Industry Overview",
        "result": "CHECKED" if result["foreign_competition_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["foreign_competition_score"] is not None else "No named international competitor, global/multinational player, export-competition, or import-pressure language was located in the latest Annual Report this run.",
    }]

    if result["foreign_competition_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Foreign competitor presence", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No named international competitor, global/multinational player, export-competition, or import-pressure language was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    dims = ", ".join(result["presence_dimensions"])
    payload = {
        "subpoint_id": subpoint_id, "title": "Foreign competitor presence", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": f"Disclosed foreign-competitor-presence dimension(s): {dims} (score {result['foreign_competition_score']}/5).",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_f5_2_import_competition(symbol, name=None, force=False):
    """F.5.2 - Import competition. Spec: Import Competition Score (1-5).
    Deterministic (no LLM) - see
    tools.foreign_competition_scoring.score_import_competition. Sourcing:
    NSE Corporate Filings - Annual Reports - MD&A - imports / raw
    materials / competition; DGFT - ITC(HS) import policy.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "F.5.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.foreign_competition_scoring import score_import_competition
        text, pdf_url = _fetch_foreign_competition_text(sym, name)
        result = score_import_competition(text)
    except Exception as e:
        print(f"[qualitative_engine] F.5.2 fetch failed for {sym}: {e}")
        result = {"import_dimensions": None, "import_competition_score": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-05",
        "source": "NSE Corporate Filings - Annual Reports - MD&A - imports / raw materials / competition; DGFT - ITC(HS) import policy",
        "result": "CHECKED" if result["import_competition_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["import_competition_score"] is not None else "No cheap-imports, anti-dumping/safeguard-duty, import duty/quota/policy, or import-pressure language was located in the latest Annual Report this run.",
    }]

    if result["import_competition_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Import competition", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No cheap-imports, anti-dumping/safeguard-duty, import duty/quota/policy, or import-pressure language was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    dims = ", ".join(result["import_dimensions"])
    payload = {
        "subpoint_id": subpoint_id, "title": "Import competition", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": f"Disclosed import-competition dimension(s): {dims} (score {result['import_competition_score']}/5).",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_f5_foreign_competition(symbol, name=None, force=False):
    """F.5 - Foreign competitors: ability of global players to enter
    India or export competition. Combines F.5.1-F.5.2 into a single
    grounded payload, sourced from the same real Annual Report MD&A
    text - no LLM call.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    f5_1 = compute_f5_1_foreign_competitor_presence(sym, name, force=force)
    f5_2 = compute_f5_2_import_competition(sym, name, force=force)

    parts = []
    if f5_1.get("foreign_competition_score") is not None:
        parts.append(f"Foreign competitor presence: score {f5_1['foreign_competition_score']}/5.")
    if f5_2.get("import_competition_score") is not None:
        parts.append(f"Import competition: score {f5_2['import_competition_score']}/5.")
    if not parts:
        parts.append("No foreign-competitor-presence or import-competition evidence was located for this company this run.")

    _tags = [t.get("confidence_tag") for t in (f5_1, f5_2)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (f5_1, f5_2) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "F.5",
        "title": "Foreign competitors: ability of global players to enter India or export competition",
        "available": True,
        "f5_1": f5_1, "f5_2": f5_2,
        "rationale": " ".join(parts),
        "pathway_results": (f5_1.get("pathway_results") or [])[:1] + (f5_2.get("pathway_results") or [])[:1],
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


_REGULATORY_TRADE_BARRIER_ANCHORS = [
    "USFDA", "regulatory approval", "licence to operate", "mining lease", "BIS certif", "quality control order",
    "tariff", "import duty", "export duty", "anti-dumping", "anti dumping", "safeguard duty",
    "foreign trade policy", "ITC(HS)", "export incentive", "import quota",
]


def _fetch_regulatory_trade_barrier_text(sym, name):
    from tools.annual_report_financials import _fetch_ar_evidence_excerpts
    evidence = _fetch_ar_evidence_excerpts(
        sym, name, _REGULATORY_TRADE_BARRIER_ANCHORS, "ar_regtrade_text_v1",
        max_per_page=5, max_excerpts=25, fetch_label="regulatory-trade-barriers",
    )
    text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or [])) if isinstance(evidence, dict) else ""
    pdf_url = evidence.get("pdf_url") if isinstance(evidence, dict) else None
    return text, pdf_url


def compute_f4_1_regulatory_barriers(symbol, name=None, force=False):
    """F.4.1 - Regulatory barriers. Spec: Barrier Score (1-5): strength
    and durability of regulatory barriers. Deterministic (no LLM) - see
    tools.regulatory_trade_barrier_scoring.score_regulatory_barriers.
    Sourcing: NSE Corporate Filings - Annual Reports - MD&A -
    Regulation / Licensing / Industry Structure.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "F.4.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.regulatory_trade_barrier_scoring import score_regulatory_barriers
        text, pdf_url = _fetch_regulatory_trade_barrier_text(sym, name)
        result = score_regulatory_barriers(text)
    except Exception as e:
        print(f"[qualitative_engine] F.4.1 fetch failed for {sym}: {e}")
        result = {"regulatory_barrier_dimensions": None, "regulatory_barrier_score": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-05",
        "source": "NSE Corporate Filings - Annual Reports - MD&A - Regulation / Licensing / Industry Structure",
        "result": "CHECKED" if result["regulatory_barrier_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["regulatory_barrier_score"] is not None else "No regulatory-approval-regime, licence-to-operate, mining/resource-lease, or mandatory-standards language was located in the latest Annual Report this run.",
    }]

    if result["regulatory_barrier_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Regulatory barriers", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No regulatory-approval-regime, licence-to-operate, mining/resource-lease, or mandatory-standards language was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    dims = ", ".join(result["regulatory_barrier_dimensions"])
    payload = {
        "subpoint_id": subpoint_id, "title": "Regulatory barriers", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": f"Disclosed regulatory-barrier dimension(s): {dims} (score {result['regulatory_barrier_score']}/5).",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_f4_2_trade_barriers(symbol, name=None, force=False):
    """F.4.2 - Trade barriers. Spec: Trade Barrier Exposure Score
    (1-5). Deterministic (no LLM) - see
    tools.regulatory_trade_barrier_scoring.score_trade_barriers.
    Sourcing: NSE Corporate Filings - Annual Reports - MD&A -
    imports/exports, tariffs and duties; DGFT - Foreign Trade Policy /
    ITC(HS) relevant product policy.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "F.4.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.regulatory_trade_barrier_scoring import score_trade_barriers
        text, pdf_url = _fetch_regulatory_trade_barrier_text(sym, name)
        result = score_trade_barriers(text)
    except Exception as e:
        print(f"[qualitative_engine] F.4.2 fetch failed for {sym}: {e}")
        result = {"trade_barrier_dimensions": None, "trade_barrier_score": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-05",
        "source": "NSE Corporate Filings - Annual Reports - MD&A - imports/exports, tariffs and duties; DGFT - Foreign Trade Policy / ITC(HS)",
        "result": "CHECKED" if result["trade_barrier_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["trade_barrier_score"] is not None else "No tariff, import/export duty, anti-dumping/safeguard duty, or trade-policy language was located in the latest Annual Report this run.",
    }]

    if result["trade_barrier_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Trade barriers", "available": True, **result,
            "source_pdf_url": pdf_url,
            "rationale": "No tariff, import/export duty, anti-dumping/safeguard duty, or trade-policy language was located in the latest Annual Report this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    dims = ", ".join(result["trade_barrier_dimensions"])
    payload = {
        "subpoint_id": subpoint_id, "title": "Trade barriers", "available": True, **result,
        "source_pdf_url": pdf_url,
        "rationale": f"Disclosed trade-barrier dimension(s): {dims} (score {result['trade_barrier_score']}/5).",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_f4_regulatory_trade_barriers(symbol, name=None, force=False):
    """F.4 - Regulatory or trade barriers protecting or exposing the
    company. Combines F.4.1-F.4.2 into a single grounded payload,
    sourced from the same real Annual Report MD&A text - no LLM call.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    f4_1 = compute_f4_1_regulatory_barriers(sym, name, force=force)
    f4_2 = compute_f4_2_trade_barriers(sym, name, force=force)

    parts = []
    if f4_1.get("regulatory_barrier_score") is not None:
        parts.append(f"Regulatory barriers: score {f4_1['regulatory_barrier_score']}/5.")
    if f4_2.get("trade_barrier_score") is not None:
        parts.append(f"Trade barriers: score {f4_2['trade_barrier_score']}/5.")
    if not parts:
        parts.append("No regulatory-barrier or trade-barrier evidence was located for this company this run.")

    _tags = [t.get("confidence_tag") for t in (f4_1, f4_2)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (f4_1, f4_2) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "F.4",
        "title": "Regulatory or trade barriers protecting or exposing the company",
        "available": True,
        "f4_1": f4_1, "f4_2": f4_2,
        "rationale": " ".join(parts),
        "pathway_results": (f4_1.get("pathway_results") or [])[:1] + (f4_2.get("pathway_results") or [])[:1],
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


# =============================================================================
# Section G - Customers, channels & distribution
# =============================================================================
# All G sub-points are AR/MD&A-based (Business Model / Distribution Network /
# Related Party Disclosures) - same evidence path as E-series/F.2.1, so this
# reuses _fetch_ar_evidence_excerpts (which already routes through
# tools/ar_document_cache.py) rather than any new retrieval infrastructure.
# G2.2 is blank/undefined in the framework - no compute_ function exists for
# it, matching E.1.2's precedent (never fabricated).

_CHANNEL_MIX_ANCHORS = [
    "channel mix", "distribution channel", "direct sales", "retail channel",
    "distributors", "dealers", "e-commerce", "online channel", "franchisee",
    "wholesale", "exports",
]
_CHANNEL_CONTROL_ANCHORS = [
    "company-owned stores", "own retail network", "captive distribution",
    "third-party distributors", "independent distributors", "appointed distributors",
    "franchise model", "distribution network",
]
_CHANNEL_CONFLICT_ANCHORS = [
    "group companies", "related party", "promoter group", "associate company",
    "subsidiary distributor", "arm's length", "audit committee approv",
    "conflict of interest", "competitive bidding",
]
_CONTRACT_QUALITY_ANCHORS = [
    "contract period", "contract term", "long-term agreement", "multi-year contract",
    "renewal rate", "contracts renewed", "order book", "repeat orders", "repeat business",
]
_CUSTOMER_RETENTION_ANCHORS = [
    "customer retention", "retention rate", "churn rate", "repeat customers",
    "customer attrition", "repeat purchase",
]
_DISTRIBUTION_REACH_ANCHORS = [
    "dealers", "distributors", "retail outlets", "stores", "touchpoints",
    "service centers", "service centres", "pan-india", "nationwide network",
]
_PEER_DISTRIBUTION_ANCHORS = [
    "largest distribution network", "widest network", "wider network",
    "broader reach", "deepest reach", "compared to peers", "compared to competitors",
    "among its peers",
]


def compute_g1_1_channel_mix(symbol, name=None, force=False):
    """G.1.1 - Channel mix. Spec formula: Channel Mix % = Revenue by
    Channel / Total Revenue where disclosed. Deterministic (no LLM) -
    see tools.channel_distribution_scoring.score_channel_mix: counts
    distinct named channel types (direct/retail/distributor/e-commerce/
    exports/franchisee) actually evidenced in real MD&A / Business Model
    text - a clean per-channel revenue % table is essentially never
    disclosed in Indian AR prose (same documented limitation as A.1.2/
    A.3's segment-revenue text), so this counts real disclosed channels
    rather than fabricate a percentage the source doesn't contain.
    Sourcing: NSE Corporate Filings - Annual Reports - MD&A - Business
    Model / Distribution.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "G.1.1"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import _fetch_ar_evidence_excerpts
        from tools.channel_distribution_scoring import score_channel_mix
        evidence = _fetch_ar_evidence_excerpts(
            sym, name, _CHANNEL_MIX_ANCHORS, "ar_channelmix_text_v1",
            max_per_page=4, max_excerpts=20, fetch_label="channel-mix",
        )
        text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or [])) if isinstance(evidence, dict) else ""
        pdf_url = evidence.get("pdf_url") if isinstance(evidence, dict) else None
        result = score_channel_mix(text)
    except Exception as e:
        print(f"[qualitative_engine] G.1.1 fetch failed for {sym}: {e}")
        result = {"channels_identified": None, "channel_mix_score": None}
        pdf_url = None

    pathway_results = [{
        "pathway_id": "AR-06",
        "source": "NSE Corporate Filings - Annual Reports - MD&A - Business Model / Distribution",
        "result": "CHECKED" if result["channel_mix_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["channel_mix_score"] is not None else "No named distribution channel was located in MD&A / Business Model text this run.",
    }]

    if result["channel_mix_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Channel mix", "available": True, **result,
            "rationale": "No named distribution channel was located in MD&A / Business Model text this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Channel mix", "available": True, **result,
        "rationale": f"{len(result['channels_identified'])} distinct channel(s) disclosed ({', '.join(result['channels_identified'])}) -> score {result['channel_mix_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_g1_2_channel_control(symbol, name=None, force=False):
    """G.1.2 - Channel control. Spec formula: Channel Control Score
    (1-5): assess owned vs third-party channel dependence. Deterministic
    (no LLM) - see tools.channel_distribution_scoring.score_channel_control.
    Sourcing: NSE Corporate Filings - Annual Reports - MD&A - Distribution
    Network / Business Model.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "G.1.2"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    try:
        from tools.annual_report_financials import _fetch_ar_evidence_excerpts
        from tools.channel_distribution_scoring import score_channel_control
        evidence = _fetch_ar_evidence_excerpts(
            sym, name, _CHANNEL_CONTROL_ANCHORS, "ar_channelcontrol_text_v1",
            max_per_page=4, max_excerpts=20, fetch_label="channel-control",
        )
        text = " ".join((ex.get("text") or "") for ex in (evidence.get("excerpts") or [])) if isinstance(evidence, dict) else ""
        result = score_channel_control(text)
    except Exception as e:
        print(f"[qualitative_engine] G.1.2 fetch failed for {sym}: {e}")
        result = {"control_basis": None, "channel_control_score": None}

    pathway_results = [{
        "pathway_id": "AR-06",
        "source": "NSE Corporate Filings - Annual Reports - MD&A - Distribution Network / Business Model",
        "result": "CHECKED" if result["channel_control_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["channel_control_score"] is not None else "No owned-vs-third-party channel dependence language was located this run.",
    }]

    if result["channel_control_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Channel control", "available": True, **result,
            "rationale": "No owned-vs-third-party channel dependence language was located this run.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id, "title": "Channel control", "available": True, **result,
        "rationale": f"Channel control basis: {result['control_basis']} -> score {result['channel_control_score']}/5.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_g1_channel_mix_and_control(symbol, name=None, force=False):
    """G.1 - Channel mix: direct, retail, distributors, e-commerce;
    control over channel. Combines G.1.1-G.1.2 into a single grounded
    payload, sourced from the same real Annual Report MD&A text - no
    LLM call.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    g1_1 = compute_g1_1_channel_mix(sym, name, force=force)
    g1_2 = compute_g1_2_channel_control(sym, name, force=force)

    parts = []
    if g1_1.get("channel_mix_score") is not None:
        parts.append(f"Channel mix: {len(g1_1['channels_identified'])} channel(s) disclosed (score {g1_1['channel_mix_score']}/5).")
    if g1_2.get("channel_control_score") is not None:
        parts.append(f"Channel control: {g1_2['control_basis']} basis (score {g1_2['channel_control_score']}/5).")
    if not parts:
        parts.append("No channel-mix or channel-control evidence was located for this company this run.")

    _tags = [t.get("confidence_tag") for t in (g1_1, g1_2)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    retrieved_ats = [t.get("retrieved_at") for t in (g1_1, g1_2) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "G.1",
        "title": "Channel mix: direct, retail, distributors, e-commerce; control over channel",
        "available": True,
        "g1_1": g1_1, "g1_2": g1_2,
        "rationale": " ".join(parts),
        "pathway_results": (g1_1.get("pathway_results") or [])[:1] + (g1_2.get("pathway_results") or [])[:1],
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload



def compute_f6_1_switching_costs(symbol, name=None, a2e_result=None):
    """F.6.1 - Switching costs. Spec: Switching Cost Score (1-5).
    Deterministic (no LLM) - this is NOT a new fetch/score. A.2.E
    (compute_a2e_switching_costs_moat) already computes exactly this
    real, evidenced score (contract lock-in term length, renewal rate,
    regulatory/certification switching barriers, sourced from CRISIL/
    ICRA rationale and Annual Report MD&A) for the moat-factor topic -
    F.6.1 just re-surfaces that same real result under its own
    subpoint_id/title rather than re-fetching and re-scoring the same
    evidence a second time. `a2e_result` must be the already-computed
    A.2.E payload (agent/stock_agent.py's `_a2e`).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    a2e = a2e_result or {}
    score = a2e.get("score")
    payload = {
        "subpoint_id": "F.6.1", "title": "Switching costs", "available": True,
        "switching_cost_score": score,
        "rationale": a2e.get("rationale") or "No contract lock-in term, renewal rate, or switching-barrier evidence was located for this company this run.",
        "evidence_quote": a2e.get("evidence_quote"),
        "pathway_results": a2e.get("pathway_results") or [],
        "confidence_tag": a2e.get("confidence_tag") or "SEARCH_INCONCLUSIVE",
        "retrieved_at": a2e.get("retrieved_at") or time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


def compute_f6_2_network_effects(symbol, name=None, a2d_result=None):
    """F.6.2 - Network effects. Spec: Network Effect Score (1-5).
    Deterministic (no LLM) - this is NOT a new fetch/score. A.2.D
    (compute_a2d_network_effects_moat) already computes exactly this
    real, evidenced score (a real growth-linkage figure - a value
    metric like GMV/transaction value tracked against a user/seller/
    buyer-base metric, sourced from Annual Report MD&A) for the
    moat-factor topic - F.6.2 just re-surfaces that same real result.
    N/A here means the business has no platform/marketplace element at
    all, not a failed search. `a2d_result` must be the already-computed
    A.2.D payload (agent/stock_agent.py's `_a2d`).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    a2d = a2d_result or {}
    score = a2d.get("score")
    payload = {
        "subpoint_id": "F.6.2", "title": "Network effects", "available": True,
        "network_effect_score": score,
        "applicable": a2d.get("applicable"),
        "rationale": a2d.get("rationale") or "No platform/network-effects growth-linkage evidence was located for this company this run.",
        "evidence_quote": a2d.get("evidence_quote"),
        "pathway_results": a2d.get("pathway_results") or [],
        "confidence_tag": a2d.get("confidence_tag") or "SEARCH_INCONCLUSIVE",
        "retrieved_at": a2d.get("retrieved_at") or time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload


def compute_f6_customer_lockin(symbol, name=None, a2e_result=None, a2d_result=None):
    """F.6 - Customer switching costs and network effects that lock
    customers in. Wraps F.6.1 (Switching costs) and F.6.2 (Network
    effects) - both re-surface the already-computed A.2.E/A.2.D moat
    scores rather than re-fetching/re-scoring the same real evidence.
    """
    f6_1 = compute_f6_1_switching_costs(symbol, name, a2e_result=a2e_result)
    f6_2 = compute_f6_2_network_effects(symbol, name, a2d_result=a2d_result)

    parts = []
    if f6_1.get("switching_cost_score") is not None:
        parts.append(f"Switching costs: score {f6_1['switching_cost_score']}/5.")
    if f6_2.get("applicable") is False:
        parts.append("Network effects: not applicable (no platform/marketplace element).")
    elif f6_2.get("network_effect_score") is not None:
        parts.append(f"Network effects: score {f6_2['network_effect_score']}/5.")
    if not parts:
        parts.append("No switching-cost or network-effects evidence was located for this company this run.")

    _tags = [t.get("confidence_tag") for t in (f6_1, f6_2)]
    combined_tag = "SINGLE_SOURCE" if any(t == "SINGLE_SOURCE" for t in _tags) else (
        "NOT_APPLICABLE" if any(t == "NOT_APPLICABLE" for t in _tags) else "SEARCH_INCONCLUSIVE"
    )
    retrieved_ats = [t.get("retrieved_at") for t in (f6_1, f6_2) if t.get("retrieved_at")]

    payload = {
        "subpoint_id": "F.6",
        "title": "Customer switching costs and network effects that lock customers in",
        "available": True,
        "f6_1": f6_1, "f6_2": f6_2,
        "rationale": " ".join(parts),
        "pathway_results": (f6_1.get("pathway_results") or [])[:1] + (f6_2.get("pathway_results") or [])[:1],
        "confidence_tag": combined_tag,
        "retrieved_at": max(retrieved_ats) if retrieved_ats else time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return payload
