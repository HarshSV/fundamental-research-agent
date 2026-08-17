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
    classify_initiatives: a sentence must carry both an initiative keyword
    (commissioning/expansion/acquisition/restructuring/etc) AND a
    classifiable outcome keyword (success/delayed/failed/ongoing) to count;
    a sentence naming an initiative with no matched outcome is skipped, not
    guessed. Sourcing: Chairman/MD message across the last up to 5 Annual
    Reports (fetch_founder_milestones_multi_year). The NSE Corporate
    Announcements cross-check the spec also calls for has no fetcher wired -
    see the PORTAL-02 gap in pathway_results; this score is AR-narrative-
    only, not a full announced-vs-actual reconciliation.
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

    pathway_results = [
        {
            "pathway_id": "AR-13",
            "source": "Chairman & MD message across the last 5 Annual Reports",
            "result": "CHECKED" if year_texts else "NOT_DISCLOSED",
            "note": (f"Chairman/MD message located in {len(year_texts)} of the last 5 Annual Reports."
                     if year_texts else "Chairman/MD message section not located in any of the last 5 Annual Reports this run."),
        },
        _NSE_ANNOUNCEMENTS_GAP,
    ]
    pdf_url = year_texts[0]["pdf_url"] if year_texts else None

    from tools.founder_track_record_scoring import score_initiative_success_rate
    result = score_initiative_success_rate(year_texts)

    if result["execution_score"] is None:
        reason = ("No Chairman/MD message was located in any of the last 5 Annual Reports this run." if not year_texts else
                   "The Chairman/MD messages across the last 5 Annual Reports were read, but none name a major "
                   "strategic initiative (commissioning/expansion/acquisition/restructuring) with a matched "
                   "outcome keyword - no track-record evidence was located this run, not a clean record.")
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
            "cashflow": ["cash flow from investing activities", "purchase of property, plant and equipment"],
            "board_report": ["board's report", "directors' report", "capital expenditure"],
        }, max_pages_per_key=6)
        result = score_capital_execution(texts.get("cashflow", ""), texts.get("board_report", ""))
    except Exception as e:
        print(f"[qualitative_engine] B.5.2 fetch failed for {sym}: {e}")
        result = {"actual_capex_cr": None, "planned_capex_cr": None, "execution_pct": None, "capital_execution_score": None}

    pathway_results = [{
        "pathway_id": "AR-15",
        "source": "NSE Corporate Filings - Annual Reports - Cash Flow Statement / Board's Report - Capex & Acquisition Updates",
        "result": "CHECKED" if result["capital_execution_score"] is not None else "NOT_DISCLOSED",
        "note": None if result["capital_execution_score"] is not None else "No explicitly-stated planned capex figure (Board's Report) alongside an actual capex figure (Cash Flow Statement) was located this run — most companies don't disclose a specific capex plan/budget number.",
    }]

    if result["capital_execution_score"] is None:
        payload = {
            "subpoint_id": subpoint_id, "title": "Capital allocation execution", "available": True, **result,
            "rationale": "No explicitly-stated planned-vs-actual capex comparison was located in the latest Annual Report this run.",
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


def compute_b6_culture(symbol, name=None, force=False):
    """B.6 — Culture: innovation focus, compliance orientation, employee morale,
    attrition evidence. Formula: Employee attrition rate = Employees exited /
    Average employee headcount.

    Sourcing Sequence: AR-15 (ESG/BRSR) -> QUAL-01 (Glassdoor/AmbitionBox,
    corroborative only).

    Same situation as B.2/B.3: no Glassdoor fetcher, no AmbitionBox fetcher, and
    no AR-15 BRSR-section parser. Employee attrition rate and culture review
    themes don't legitimately appear in a generic business-description paragraph
    or concall transcript, so — same guardrail as B.2/B.3 — that text is not used
    as a stand-in here. Honest full gap, no LLM call.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.6"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    pathway_results = [
        {
            "pathway_id": "AR-15",
            "source": "Business Responsibility and Sustainability Report (ESG/BRSR) — HR/CSR section",
            "result": "NOT_DISCLOSED",
            "note": "No AR-15/BRSR section parser is wired into this codebase yet — also NOT_APPLICABLE for companies outside SEBI's top-1000-by-market-cap mandate.",
        },
        {
            "pathway_id": "QUAL-01",
            "source": "Glassdoor / AmbitionBox reviews (corroborative only)",
            "result": "NOT_DISCLOSED",
            "note": "No Glassdoor/AmbitionBox fetcher is wired into this codebase yet.",
        },
    ]

    payload = {
        "subpoint_id": subpoint_id,
        "title": "Culture: innovation focus, compliance orientation, employee morale, attrition evidence",
        "available": True,
        "culture_rating": None,
        "employee_attrition_rate_pct": None,
        "rationale": "Not computed — AR-15 (BRSR HR/CSR section) has no parser wired, and QUAL-01 (Glassdoor/AmbitionBox) has no fetcher wired.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SEARCH_INCONCLUSIVE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c1_promoter_shareholding(symbol, name=None, force=False):
    """C.1 — Promoter shareholding patterns: control levels, changes over time,
    direction (buying/selling). Formula: QoQ change in promoter holding =
    Promoter % (Qt) - Promoter % (Qt-1).

    Sourcing Sequence: PORTAL-02 (BSE/NSE Shareholding Pattern — promoter %/pledge)
    -> AGG-01 (fallback/cross-check only).

    PORTAL-02 IS wired (tools/shareholding_scraper.py — the same NSE endpoint that
    already powers Promoter Pledge % / Sr No 67), real data, no LLM. QoQ change is
    only computed when NSE's live endpoint actually returns 2+ quarters for this
    symbol — it often returns just the current quarter, which is a genuine API
    limitation, not a guess; when that happens, the current % is still reported
    but the QoQ change is honestly NOT_DISCLOSED rather than assumed zero.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.1"

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
        trend = get_provider().fetch_promoter_holding_trend(sym) or []
    except Exception as e:
        print(f"[qualitative_engine] C.1 shareholding fetch failed for {sym}: {e}")
        trend = []

    pathway_results = [
        {
            "pathway_id": "PORTAL-02",
            "source": "NSE Shareholding Pattern (promoter %, live endpoint)",
            "result": "CHECKED" if trend else "NOT_DISCLOSED",
            "note": None if trend else "NSE's live endpoint returned no data for this symbol this run.",
        },
        {
            "pathway_id": "AGG-01",
            "source": "Trendlyne / Screener.in — shareholding trend (fallback/cross-check only)",
            "result": "NOT_CHECKED",
            "note": "Cross-check pathway, only used if primary is unavailable or conflicting — not invoked this run.",
        },
    ]

    if not trend:
        payload = {
            "subpoint_id": subpoint_id,
            "title": "Promoter shareholding patterns: control levels, changes over time, direction (buying/selling)",
            "available": False,
            "reason": "NSE's live Shareholding Pattern endpoint returned no data for this symbol.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    latest = trend[-1]
    qoq_change_pct = None
    if len(trend) >= 2:
        prev = trend[-2]
        qoq_change_pct = round(latest["promoter_holding_pct"] - prev["promoter_holding_pct"], 2)

    holding_pct = latest["promoter_holding_pct"]
    if holding_pct >= 50:
        control_level = "Majority control"
    elif holding_pct >= 25:
        control_level = "Significant minority control"
    else:
        control_level = "Below significant-influence threshold"

    if qoq_change_pct is None:
        direction = "unclear"
    elif qoq_change_pct > 0.05:
        direction = "increasing"
    elif qoq_change_pct < -0.05:
        direction = "decreasing"
    else:
        direction = "stable"

    payload = {
        "subpoint_id": subpoint_id,
        "title": "Promoter shareholding patterns: control levels, changes over time, direction (buying/selling)",
        "available": True,
        "promoter_holding_pct": holding_pct,
        "as_of_quarter": latest.get("quarter"),
        "control_level": control_level,
        "qoq_change_pct": qoq_change_pct,
        "direction": direction,
        "quarters_available": len(trend),
        "trend": trend,
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c2_promoter_pledging(symbol, name=None, force=False):
    """C.2 — Promoter pledging of shares: presence, size, trend and risk if margin
    calls occur. Formula: Pledge % = Shares pledged / Total promoter shareholding.

    Sourcing Sequence: PORTAL-02 (promoter %/pledge) -> AGG-01 (fallback/cross-
    check only).

    Same real NSE endpoint as C.1 and the existing Promoter Pledge % (Sr No 67)
    ratio card — reuses tools/shareholding_scraper.py's fetch_pledge() directly
    rather than re-implementing. NSE only lists pledged scrips, so an endpoint
    response with no row overwhelmingly means a real 0% — but if the endpoint
    itself was unreachable, that is NOT the same claim (DON'T/DO INSTEAD rule #4:
    a blocked/failed source is ACCESS_RESTRICTED-equivalent, not a confirmed
    clean result), so this distinguishes "status=zero" (confirmed 0%, real) from
    "status=assumed_zero" (endpoint failure, defaulted, lower confidence).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.2"

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
        pledge = get_provider().fetch_pledge(sym) or {}
    except Exception as e:
        print(f"[qualitative_engine] C.2 pledge fetch failed for {sym}: {e}")
        pledge = {}

    status = pledge.get("status")
    pathway_results = [
        {
            "pathway_id": "PORTAL-02",
            "source": "NSE Shareholding Pattern — Pledge/Encumbrance column (live endpoint)",
            "result": "CHECKED" if status in ("ok", "zero") else "NOT_DISCLOSED",
            "note": None if status in ("ok", "zero") else "NSE's live pledge endpoint was unreachable or returned nothing this run — a real 0% cannot be confirmed, only assumed.",
        },
        {
            "pathway_id": "AGG-01",
            "source": "Trendlyne — pledge trend (fallback/cross-check only)",
            "result": "NOT_CHECKED",
            "note": "Cross-check pathway, only used if primary is unavailable or conflicting — not invoked this run.",
        },
    ]

    if status not in ("ok", "zero"):
        payload = {
            "subpoint_id": subpoint_id,
            "title": "Promoter pledging of shares: presence, size, trend and risk if margin calls occur",
            "available": True,
            "pledge_pct": None,
            "risk_level": None,
            "assumed_zero": True,
            "rationale": "NSE's live pledge endpoint was unreachable this run — a 0% pledge is assumed but not confirmed.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    pledge_pct = pledge.get("promoter_pledge_pct") or 0.0
    if pledge_pct < 10:
        risk_level = "Low"
    elif pledge_pct <= 25:
        risk_level = "Moderate"
    else:
        risk_level = "High"

    payload = {
        "subpoint_id": subpoint_id,
        "title": "Promoter pledging of shares: presence, size, trend and risk if margin calls occur",
        "available": True,
        "pledge_pct": pledge_pct,
        "as_of_quarter": pledge.get("as_of_quarter"),
        "risk_level": risk_level,
        "assumed_zero": (status == "zero" and pledge.get("promoter_pledge_pct") is None),
        "rationale": (
            f"{pledge_pct:.2f}% of promoter shareholding is pledged as of {pledge.get('as_of_quarter') or 'the latest quarter'} "
            f"(NSE Shareholding Pattern, confirmed {'zero' if status == 'zero' else 'non-zero'} — not assumed). "
            f"Risk level: {risk_level}."
        ),
        "pathway_results": pathway_results,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
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


def compute_c3_related_party_transactions(symbol, name=None, force=False):
    """C.3 — Related-party transactions (RPTs): frequency, counterparty identity,
    pricing and rationale. Formula: RPT intensity = Total RPT value / Total
    revenue.

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
    subpoint_id = "C.3"

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


def compute_c4_group_structural_complexity(symbol, name=None, force=False):
    """C.4 — Use of complex group entities: off-balance-sheet vehicles, SPVs,
    subsidiaries abroad. N/A formula — a structural complexity score (count of
    entities, layers), per the spec.

    Sourcing Sequence: AR-05 (group structure) -> PORTAL-05 (director registry,
    NOT bio) -> AGG-01 (Tofler, fallback/cross-check only).

    Same gap as C.3: no AR-05 subsidiary-list parser, no PORTAL-05 MCA fetcher,
    no Tofler fetcher. Subsidiary counts, entity layers, and unclear-purpose flags
    don't legitimately appear in a generic business-description paragraph or
    concall transcript — same guardrail as B.2/B.3/B.6/C.3, that text is not used
    as a stand-in here. Honest full gap, no LLM call.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.4"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    pathway_results = [
        {
            "pathway_id": "AR-05",
            "source": "Subsidiaries / group structure (Form AOC-1 + Consolidated Notes)",
            "result": "NOT_DISCLOSED",
            "note": "No AR-05 group-structure parser is wired into this codebase yet.",
        },
        {
            "pathway_id": "PORTAL-05",
            "source": "MCA Company/Director Master Data (group/company master data, NOT bio)",
            "result": "NOT_DISCLOSED",
            "note": "No MCA director-master-data fetcher is wired into this codebase yet.",
        },
        {
            "pathway_id": "AGG-01",
            "source": "Tofler — group structure mapping (fallback/cross-check only)",
            "result": "NOT_CHECKED",
            "note": "Cross-check pathway, only used if primary is unavailable or conflicting — not invoked this run.",
        },
    ]

    payload = {
        "subpoint_id": subpoint_id,
        "title": "Use of complex group entities: off-balance-sheet vehicles, SPVs, subsidiaries abroad",
        "available": True,
        "subsidiary_count": None,
        "structural_layers": None,
        "unclear_purpose_flags": [],
        "rationale": "Not computed — AR-05 (subsidiary/group-structure list) and PORTAL-05 (MCA group/company master data) both require fetchers this codebase doesn't have yet.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SEARCH_INCONCLUSIVE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c5_board_composition(symbol, name=None, force=False):
    """C.5 — Board composition & independence: independent directors' quality,
    committee activity. Formula: Independent director % = Independent directors /
    Total board size.

    Sourcing Sequence: AR-06 (Report on Corporate Governance) -> PORTAL-01 (get
    the AR PDF).

    No AR-06 Corporate Governance Report parser is wired into this codebase. The
    PREVIOUS implementation of this field explicitly instructed the LLM to "give
    your best ESTIMATE — never null" for independent_director_pct/board_size —
    exactly the kind of fabrication the sourcing-pathway guardrails prohibit
    (DON'T/DO INSTEAD rule #12: a guessed number is worse than a visible gap).
    This sub-point does not do that: board size and independent-director % are
    real, structured facts a filing either states or doesn't — never appropriate
    to estimate from general knowledge. Honest full gap, no LLM call.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.5"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    pathway_results = [
        {
            "pathway_id": "AR-06",
            "source": "Report on Corporate Governance (board composition, committee attendance)",
            "result": "NOT_DISCLOSED",
            "note": "No AR-06 Corporate Governance Report parser is wired into this codebase yet.",
        },
        {
            "pathway_id": "PORTAL-01",
            "source": "BSE Corporate Announcements -> Annual Report PDF",
            "result": "NOT_DISCLOSED",
            "note": "Fetching the PDF alone doesn't help without a structured AR-06 section parser to read it.",
        },
    ]

    payload = {
        "subpoint_id": subpoint_id,
        "title": "Board composition & independence: independent directors' quality, committee activity",
        "available": True,
        "independent_director_pct": None,
        "board_size": None,
        "committee_activity_rating": None,
        "governance_flags": [],
        "rationale": "Not computed — AR-06 (Report on Corporate Governance) has no parser wired. Board size and independent-director % are structured facts that must be read from the filing, never estimated.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SEARCH_INCONCLUSIVE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_c6_auditor_relationships(symbol, name=None, force=False):
    """C.6 — Auditor relationships: long/short tenure, auditor switches,
    qualifications/reservations. Formula: Auditor tenure (years) = Current year -
    Year of appointment.

    Sourcing Sequence: AR-07 (Independent Auditor's Report — opinion type, Key
    Audit Matters, Emphasis of Matter) -> PORTAL-01 (get the AR PDF) -> PORTAL-05
    (director registry, NOT bio — Form ADT-1/ADT-3 appointment filings).

    No AR-07 Auditor's Report parser is wired into this codebase, and no MCA
    ADT-1/ADT-3 fetcher exists either. Auditor name, appointment year, opinion
    type (clean/qualified/emphasis of matter) are all structured facts that must
    be read from the filing — never estimated. Honest full gap, no LLM call.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.6"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    pathway_results = [
        {
            "pathway_id": "AR-07",
            "source": "Independent Auditor's Report (opinion type, Key Audit Matters, Emphasis of Matter)",
            "result": "NOT_DISCLOSED",
            "note": "No AR-07 Auditor's Report parser is wired into this codebase yet.",
        },
        {
            "pathway_id": "PORTAL-01",
            "source": "BSE Corporate Announcements -> Annual Report PDF",
            "result": "NOT_DISCLOSED",
            "note": "Fetching the PDF alone doesn't help without a structured AR-07 section parser to read it.",
        },
        {
            "pathway_id": "PORTAL-05",
            "source": "MCA Company/Director Master Data (Form ADT-1/ADT-3 auditor appointment filings, NOT bio)",
            "result": "NOT_DISCLOSED",
            "note": "No MCA director-master-data fetcher is wired into this codebase yet.",
        },
    ]

    payload = {
        "subpoint_id": subpoint_id,
        "title": "Auditor relationships: long/short tenure, auditor switches, qualifications/reservations",
        "available": True,
        "auditor_name": None,
        "auditor_tenure_years": None,
        "qualification_rating": None,
        "auditor_flags": [],
        "rationale": "Not computed — AR-07 (Independent Auditor's Report) has no parser wired, and no MCA ADT-1/ADT-3 fetcher exists either. Auditor name, tenure and opinion type are structured facts that must be read from the filing, never estimated.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SEARCH_INCONCLUSIVE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


_C7_SCHEMA_VERSION = 1  # v1: real deterministic multi-year capital-allocation-mix build, replacing the "Not computed" stub


def compute_c7_capital_allocation(symbol, name=None, force=False):
    """C.7 — Capital allocation decisions: history of cash deployment and
    rationale. Formula: Capital allocation mix % = Each use of cash / Total cash
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
    subpoint_id = "C.7"
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


def compute_c8_minority_shareholder_treatment(symbol, name=None, force=False):
    """C.8 — Track record on minority shareholder treatment and disclosure
    habits. N/A formula — a qualitative flag count of adverse governance events,
    per the spec.

    Sourcing Sequence: PORTAL-01 (get the AR PDF) -> PORTAL-06 (SEBI enforcement
    orders) -> NICHE-20 (proxy advisory, IiAS/InGovern) + FOUNDER-03 (SEBI/
    exchange debarment, by individual name, for named directors).

    No SEBI enforcement-order fetcher (PORTAL-06), no IiAS/InGovern fetcher
    (NICHE-20 — a paid subscription product by design), no AGM voting/scrutinizer-
    result fetcher, and no FOUNDER-03 individual-name debarment search are wired
    in this codebase. This is exactly the category the verification protocol's
    HUMAN SIGN-OFF GATE exists for: an adverse-finding search (SEBI orders,
    debarment) must never be silently skipped or reported as "clean" when it was
    never actually checked — recorded as an explicit, uninvestigated gap, not a
    finding of no adverse events. A named analyst must run PORTAL-06/NICHE-20/
    FOUNDER-03 manually before this factors into any investment decision.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.8"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    pathway_results = [
        {
            "pathway_id": "PORTAL-01",
            "source": "BSE Corporate Announcements -> Annual Report PDF",
            "result": "NOT_DISCLOSED",
            "note": "No structured AR section parser relevant to this sub-point is wired.",
        },
        {
            "pathway_id": "PORTAL-06",
            "source": "SEBI Enforcement Orders / SCORES",
            "result": "NOT_DISCLOSED",
            "note": "No SEBI enforcement-order fetcher is wired into this codebase yet.",
        },
        {
            "pathway_id": "NICHE-20",
            "source": "Proxy Advisory — IiAS / InGovern (AGM resolution commentary)",
            "result": "NOT_DISCLOSED",
            "note": "IiAS/InGovern proxy research is a paid subscription product by design — no fetcher wired.",
        },
        {
            "pathway_id": "FOUNDER-03",
            "source": "SEBI orders + exchange debarred-entities list, by named director",
            "result": "NOT_DISCLOSED",
            "note": "No fetcher wired — requires director names from AR-01/AR-06, which are themselves not extracted yet.",
        },
    ]

    payload = {
        "subpoint_id": subpoint_id,
        "title": "Track record on minority shareholder treatment and disclosure habits",
        "available": True,
        "adverse_event_flag_count": None,
        "adverse_flags": [],
        "rationale": (
            "NOT INVESTIGATED — no SEBI enforcement-order search, no proxy-advisory (IiAS/InGovern) check, "
            "and no AGM voting/scrutinizer-result check have been run for this company. This is NOT the same "
            "as a clean record; per the verification protocol's human sign-off gate, an adverse-finding "
            "search of this kind must be run manually by a named analyst before it can inform any "
            "investment decision."
        ),
        "pathway_results": pathway_results,
    }
    confidence_tag = "SEARCH_INCONCLUSIVE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
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
