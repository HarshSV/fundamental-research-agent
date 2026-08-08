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
        if cached is not None and "revenue_pattern" not in cached and "recurring_revenue_pct" not in cached:
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
_BIZ_COMP_SCHEMA_VERSION = 10


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
    if not raw_segments or len(raw_segments) < 2:
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
    try:
        from tools.annual_report_financials import fetch_revenue_characteristics_evidence
        evidence = fetch_revenue_characteristics_evidence(sym, name)
    except Exception as e:
        print(f"[qualitative_engine] business_composition evidence fetch failed for {sym}: {e}")
        evidence = {"error": str(e)}

    def _fmt_excerpts(items):
        return "\n".join(f"[p.{e['page']}] ...{e['text']}..." for e in (items or [])) or "(none found)"

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
    # Always attempt classification — the classifier is explicitly allowed to
    # reason from well-established business-model/sector knowledge (e.g.
    # "FMCG household/personal-care products are repeat-purchase, driven by
    # everyday consumer demand" or "auto manufacturing is capex/demand
    # cyclical") even without a literal quote, not only when AR/concall text
    # happened to contain matching language. Still grounded reasoning, not a
    # blind guess — the order-book-only false-positive guard below still
    # applies regardless of source.
    context = (
        f"COMPANY: {company}\n"
        f"REPORTED SEGMENTS: {', '.join(seg_names)}\n\n"
        f"=== ANNUAL REPORT EXCERPTS — RECURRING/CONTRACT/SUBSCRIPTION LANGUAGE ===\n{_fmt_excerpts(evidence.get('recurring_excerpts'))}\n\n"
        f"=== ANNUAL REPORT EXCERPTS — CYCLICALITY/DEMAND-SENSITIVITY LANGUAGE ===\n{_fmt_excerpts(evidence.get('cyclicality_excerpts'))}\n"
        + (f"\n=== RECENT CONCALL / MANAGEMENT COMMENTARY (secondary corroboration, newest first) ===\n{digest}\n" if digest else "")
    )
    prompt = (
        "You are an equity analyst classifying the REVENUE PATTERN of each individually reported business "
        "segment for an Indian listed company. The Annual Report excerpts are the PRIMARY evidence; the concall/"
        "management commentary (if present) is SECONDARY corroboration. When neither source explicitly discusses a "
        "segment, you MUST STILL classify it using well-established, general knowledge of how that kind of "
        "business actually earns revenue — e.g. FMCG household/personal-care/food products are repeat-purchase, "
        "driven by everyday consumer demand (typically Cyclical or Mixed, not purely discretionary); auto/"
        "industrial manufacturing is capex- and demand-cycle sensitive (typically Cyclical); IT services delivery "
        "is often Mixed (project-based plus renewing maintenance); banking/lending interest income and insurance "
        "premiums are typically Recurring. Reserve \"unclassified\" for the rare case where you genuinely cannot "
        "reason about the segment's business model at all — it should be UNUSUAL, not the default outcome.\n\n"
        "FALSE-POSITIVE GUARD (still applies regardless of source): order book, contract assets, contract "
        "liabilities, customer contracts, or the mere existence of a contract do NOT by themselves prove "
        "recurring revenue — order book reflects revenue VISIBILITY (future revenue already booked), a DIFFERENT "
        "concept from RECURRINGNESS (whether revenue repeats from the same customers over time). Never cite an "
        "order book figure, alone, as your reason for \"recurring\" — if that is genuinely your only evidence, use "
        "\"cyclical\" or \"unclassified\" instead, or pair it with real reasoning about repeat/renewal.\n\n"
        "Only use \"mixed\" when the segment demonstrably has BOTH meaningful recurring/stable AND cyclical/"
        "transactional characteristics, and you can state both reasons — never as a stand-in for uncertainty.\n\n"
        "For EACH segment also provide:\n"
        "- reason_points: 2-3 short bullet points (not a paragraph) explaining the classification — what the "
        "segment's business actually does, and why that supports the pattern chosen.\n"
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
        for s in (data.get("segments") or []):
            lbl = str(s.get("label") or "").strip()
            pat = str(s.get("pattern") or "").strip().lower()
            if not lbl or pat not in _SEGMENT_PATTERN:
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
            patterns_by_label[lbl.lower()] = {"pattern": pat, "reason_points": reason_points, "brands": brands}
    except Exception as e:
        classification_error = e
        print(f"[qualitative_engine] business_composition segment classification failed for {sym}: {e}")

    segments_out = []
    for s in segments_for_calc:
        pct = round(s["value_cr"] / consolidated_revenue * 100, 1) if consolidated_revenue else 0.0
        cls = patterns_by_label.get(s["label"].lower()) or {"pattern": "unclassified", "reason_points": [], "brands": []}
        segments_out.append({
            "name": s["label"],
            "external_revenue_cr": round(s["value_cr"], 1),
            "share_pct": pct,
            "pattern": cls["pattern"],
            "pattern_reason_points": cls.get("reason_points") or [],
            "example_brands": cls.get("brands") or [],
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
        # The actual evidence the pattern classifier read — same excerpts fed
        # into the prompt above, not re-fetched or paraphrased. These are
        # shared context across every segment (the classifier reads all of
        # them together, not one excerpt per segment), so the UI shows them
        # once per sub-point rather than duplicated under each segment.
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


def compute_a2_competitive_moat(symbol, name=None, description="", market_cap_cr=None, force=False):
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
    digest = _concall_digest(sym, name)

    breakdown = build_moat_rating_breakdown(
        sym, name=name, market_cap_cr=market_cap_cr,
        crisil_result=crisil_result, concall_digest=digest,
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
                "QUANT_PROXY_ONLY — the qualitative-evidence score could not be sourced from CRISIL/ICRA "
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


def compute_a4_product_lifecycle_stage(symbol, name=None, description="", force=False):
    """A.4 — Product lifecycle stage: growth, maturity, commoditisation,
    obsolescence risk. Formula: Relative growth = Company revenue CAGR - Industry
    revenue CAGR.

    Sourcing Sequence: AR-14 (revenue/segment) -> PORTAL-07 (rating-agency
    rationale) -> QUAL-01 (news/analyst commentary, corroborative only).

    No industry-level revenue CAGR source is wired into this codebase (CRISIL/
    Moneycontrol industry research isn't fetched anywhere), so the Relative Growth
    formula cannot be computed even though the company's own revenue CAGR exists
    elsewhere in the ratio engine — a one-sided subtraction would be worse than no
    number (DON'T/DO INSTEAD rule #12: never guess a missing input). The lifecycle
    STAGE itself is a narrative judgment grounded in the same AR-14 proxy (business
    description + concall digest) used for A.1/A.3 — PORTAL-07 and QUAL-01 are not
    wired either, so this never exceeds SINGLE_SOURCE.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "A.4"

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
    digest = _concall_digest(sym, name)
    company = name or sym
    context = f"COMPANY: {company}\n"
    if description:
        context += f"\nBUSINESS DESCRIPTION (from filings):\n{description[:2500]}\n"
    if digest:
        context += f"\nRECENT EARNINGS-CALL HIGHLIGHTS (newest first):\n{digest}\n"

    ar14_checked = bool(description or digest)
    pathway_results.append({
        "pathway_id": "AR-14",
        "source": "Revenue/segment note (business description + concall digest proxy)",
        "result": "CHECKED" if ar14_checked else "NOT_DISCLOSED",
    })
    pathway_results.append({
        "pathway_id": "PORTAL-07",
        "source": "Rating Agency Rationale (CRISIL/ICRA/CARE) — industry growth context",
        "result": "NOT_DISCLOSED",
        "note": "No rating-agency rationale fetcher is wired into this codebase yet.",
    })
    pathway_results.append({
        "pathway_id": "QUAL-01",
        "source": "News / analyst research (Moneycontrol etc, corroborative only)",
        "result": "NOT_CHECKED",
        "note": "Corroborative-only pathway — not invoked this run.",
    })

    if not ar14_checked:
        payload = {
            "subpoint_id": subpoint_id,
            "title": "Product lifecycle stage: growth, maturity, commoditisation, obsolescence risk",
            "available": False,
            "reason": "No business description or concall corpus available to ground AR-14.",
            "pathway_results": pathway_results,
            "relative_growth_pct": None,
        }
        write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    prompt = (
        "You are an equity analyst assessing PRODUCT LIFECYCLE STAGE for an Indian listed company, "
        "using ONLY the grounded context below. Do not invent facts not supported by the context. "
        "If unclear, say so rather than guessing.\n\n"
        "Return ONLY JSON:\n"
        "{\n"
        '  "lifecycle_stage": "growth" | "maturity" | "commoditisation" | "decline_obsolescence" | "mixed" | "unclear",\n'
        '  "obsolescence_risk": "low" | "medium" | "high" | "unclear",\n'
        '  "rationale": "2-4 sentences citing what in the context supports this"\n'
        "}\n\n"
        f"=== CONTEXT ===\n{context}"
    )
    data, llm_failed = _llm_json(
        sym, "A.4", "You are a precise equity analyst. Reply with strict JSON only. Never fabricate.",
        prompt, max_tokens=600, temperature=0.1,
    )

    lifecycle_stage = str(data.get("lifecycle_stage") or "unclear").strip().lower()
    if lifecycle_stage not in ("growth", "maturity", "commoditisation", "decline_obsolescence", "mixed", "unclear"):
        lifecycle_stage = "unclear"
    obsolescence_risk = str(data.get("obsolescence_risk") or "unclear").strip().lower()
    if obsolescence_risk not in ("low", "medium", "high", "unclear"):
        obsolescence_risk = "unclear"
    rationale = str(data.get("rationale") or "").strip()

    confidence_tag = "SINGLE_SOURCE" if rationale else "SEARCH_INCONCLUSIVE"

    payload = {
        "subpoint_id": subpoint_id,
        "title": "Product lifecycle stage: growth, maturity, commoditisation, obsolescence risk",
        "available": True,
        "lifecycle_stage": lifecycle_stage,
        "obsolescence_risk": obsolescence_risk,
        "rationale": rationale,
        "relative_growth_pct": None,  # requires industry CAGR — not wired
        "pathway_results": pathway_results,
        "grounded": bool(digest),
    }
    if not llm_failed:
        write_qualitative(sym, subpoint_id, payload, confidence_tag)
    else:
        print(f"[qualitative_engine] A.4 NOT cached for {sym} — LLM call did not run; will retry next request.")
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_a5_pricing_power(symbol, name=None, description="", force=False):
    """A.5 — Pricing power: ability to raise prices without losing customers;
    pass-through of cost inflation. Formula: Price pass-through ratio = Change in
    realisation % / Change in input cost %.

    Sourcing Sequence: AR-13 (MD&A narrative) -> AGG-01 (fallback/cross-check
    only) -> QUAL-02 (concall transcripts) -> NICHE-14 (MCX/LME commodity prices).

    AR-13 (business description) and QUAL-02 (the same grounded concall digest
    used elsewhere) both feed ONE combined LLM synthesis call here — they are not
    independently checked and cross-compared, so this stays SINGLE_SOURCE even
    though two pathway IDs are marked CHECKED (cross-verification rule: only
    counts as VERIFIED when 2+ pathways are checked AND agree independently).
    NICHE-14 (MCX/LME commodity price index) has no fetcher wired, so the
    quantitative Price pass-through ratio cannot be computed — recorded
    NOT_DISCLOSED rather than guessed; only a qualitative pricing_power rating is
    produced. AGG-01 is fallback-only and not invoked this run.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "A.5"

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
    digest = _concall_digest(sym, name)
    company = name or sym
    context = f"COMPANY: {company}\n"
    if description:
        context += f"\nBUSINESS DESCRIPTION (from filings):\n{description[:2500]}\n"
    if digest:
        context += f"\nRECENT EARNINGS-CALL HIGHLIGHTS (newest first):\n{digest}\n"

    ar13_checked = bool(description)
    qual02_checked = bool(digest)
    pathway_results.append({
        "pathway_id": "AR-13",
        "source": "MD&A narrative (business description proxy)",
        "result": "CHECKED" if ar13_checked else "NOT_DISCLOSED",
    })
    pathway_results.append({
        "pathway_id": "AGG-01",
        "source": "Screener.in (fallback/cross-check only)",
        "result": "NOT_CHECKED",
        "note": "Cross-check pathway, only used if primary is unavailable or conflicting — not invoked this run.",
    })
    pathway_results.append({
        "pathway_id": "QUAL-02",
        "source": "Concall Transcript (grounded digest)",
        "result": "CHECKED" if qual02_checked else "NOT_HELD",
        "note": None if qual02_checked else "No transcript found for a recent quarter — do not assume one happened unseen.",
    })
    pathway_results.append({
        "pathway_id": "NICHE-14",
        "source": "MCX / LME — commodity input-cost index",
        "result": "NOT_DISCLOSED",
        "note": "No MCX/LME commodity-price fetcher is wired into this codebase yet — Price pass-through ratio cannot be computed without an input-cost index.",
    })

    if not ar13_checked and not qual02_checked:
        payload = {
            "subpoint_id": subpoint_id,
            "title": "Pricing power: ability to raise prices without losing customers; pass-through of cost inflation",
            "available": False,
            "reason": "No business description or concall corpus available to ground AR-13/QUAL-02.",
            "pathway_results": pathway_results,
            "price_pass_through_ratio": None,
        }
        write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    prompt = (
        "You are an equity analyst assessing PRICING POWER for an Indian listed company, "
        "using ONLY the grounded context below. Do not invent facts not supported by the context. "
        "If unclear, say so rather than guessing.\n\n"
        "Return ONLY JSON:\n"
        "{\n"
        '  "pricing_power_rating": "Strong" | "Moderate" | "Weak" | "unclear",\n'
        '  "rationale": "2-4 sentences citing what in the context supports this — price hikes taken, realization trends, cost pass-through commentary"\n'
        "}\n\n"
        f"=== CONTEXT ===\n{context}"
    )
    data, llm_failed = _llm_json(
        sym, "A.5", "You are a precise equity analyst. Reply with strict JSON only. Never fabricate.",
        prompt, max_tokens=600, temperature=0.1,
    )

    pricing_power_rating = str(data.get("pricing_power_rating") or "unclear").strip()
    if pricing_power_rating.lower() not in ("strong", "moderate", "weak"):
        pricing_power_rating = "unclear"
    else:
        pricing_power_rating = pricing_power_rating.capitalize()
    rationale = str(data.get("rationale") or "").strip()

    confidence_tag = "SINGLE_SOURCE" if rationale else "SEARCH_INCONCLUSIVE"

    payload = {
        "subpoint_id": subpoint_id,
        "title": "Pricing power: ability to raise prices without losing customers; pass-through of cost inflation",
        "available": True,
        "pricing_power_rating": pricing_power_rating,
        "rationale": rationale,
        "price_pass_through_ratio": None,  # requires MCX/LME input-cost index — not wired
        "pathway_results": pathway_results,
        "grounded": bool(digest),
    }
    if not llm_failed:
        write_qualitative(sym, subpoint_id, payload, confidence_tag)
    else:
        print(f"[qualitative_engine] A.5 NOT cached for {sym} — LLM call did not run; will retry next request.")
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


def compute_b1_founder_ceo_track_record(symbol, name=None, description="", force=False):
    """B.1 — Founders / CEO track record: past successes/failures, tenure,
    relevance to current strategy. N/A formula — a qualitative track record score
    per the spec.

    Sourcing Sequence: AR-01 (bio/tenure, AR only — THIN, compliance-level only) ->
    FOUNDER-01 (full directorship + company-status history) -> FOUNDER-02
    (disqualification check) -> FOUNDER-03 (SEBI/exchange debarment, by individual
    name) -> FOUNDER-04 (loan default check) -> FOUNDER-05 (litigation, by
    individual name) -> FOUNDER-06 (structured negative-news search) -> FOUNDER-07
    (cross-board reputation) -> QUAL-01 (LinkedIn/general news, corroborative only).

    NONE of FOUNDER-01 through FOUNDER-07 or QUAL-01 have fetchers in this
    codebase — no MCA director-master-data scraper, no SEBI/exchange debarred-
    entity search by individual name, no Experian/CRIF defaulter search, no
    eCourts/NCLT litigation search, no structured news-keyword search, no LinkedIn/
    proxy-advisory access. Per the Document Pathway Reference notes, AR-01 alone
    (a compliance-disclosure bio paragraph) is explicitly NOT sufficient for an
    investment decision on management quality — so unlike A.1-A.6, this sub-point
    does NOT synthesize a track-record RATING from an ungrounded LLM guess (that
    would misrepresent an unperformed background check as a completed one). It
    only reports a CEO/MD name+context IF one is explicitly named in the grounded
    business description, and otherwise surfaces the full 8-pathway gap list so an
    analyst knows exactly what still needs to be manually checked before this
    factors into an investment decision (human sign-off gate).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.1"

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
    ar01_checked = bool(description)
    pathway_results.append({
        "pathway_id": "AR-01",
        "source": "Director bios inside Corporate Governance Report (business description proxy)",
        "result": "CHECKED" if ar01_checked else "NOT_DISCLOSED",
        "note": "Compliance-disclosure level only — a company-stated resume, not an independently verified background check.",
    })
    _founder_gaps = [
        ("FOUNDER-01", "MCA — full directorship + company-status history", "No MCA director-master-data scraper wired (needs a free MCA account + persistent session)."),
        ("FOUNDER-02", "MCA — Disqualified Directors list (Sec. 164(2)(a))", "No fetcher wired for this public list."),
        ("FOUNDER-03", "SEBI Enforcement Orders + exchange debarred-entities list, by individual name", "No fetcher wired."),
        ("FOUNDER-04", "Wilful/large defaulter search (Experian primary, CRIF secondary)", "No fetcher wired."),
        ("FOUNDER-05", "eCourts / NCLT litigation search, by individual name", "No fetcher wired (CAPTCHA-protected portals)."),
        ("FOUNDER-06", "Structured negative-keyword news search", "No news-search API wired."),
        ("FOUNDER-07", "Proxy advisory cross-board commentary (IiAS/InGovern)", "No fetcher wired (paid subscription product)."),
    ]
    for pid, src, note in _founder_gaps:
        pathway_results.append({"pathway_id": pid, "source": src, "result": "NOT_DISCLOSED", "note": note})
    pathway_results.append({
        "pathway_id": "QUAL-01",
        "source": "LinkedIn / general news (corroborative only)",
        "result": "NOT_DISCLOSED",
        "note": "No LinkedIn/news-search fetcher wired (LinkedIn specifically blocks scraping).",
    })

    if not ar01_checked:
        payload = {
            "subpoint_id": subpoint_id,
            "title": "Founders / CEO track record: past successes/failures, tenure, relevance to current strategy",
            "available": False,
            "reason": "No business description available to ground even the thin AR-01 bio proxy.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    prompt = (
        "You are extracting ONLY what is EXPLICITLY stated in the context below about the company's "
        "CEO/MD/founder — do not infer, guess, or rate their track record. If no individual is named, "
        "say so.\n\n"
        "Return ONLY JSON:\n"
        "{\n"
        '  "ceo_name": "name if explicitly stated, else null",\n'
        '  "ceo_title": "title/role if stated, else null",\n'
        '  "context_note": "1-2 sentences quoting/paraphrasing ONLY what the text explicitly says about this person or leadership, or empty string if nothing is named"\n'
        "}\n\n"
        f"=== CONTEXT ===\nCOMPANY: {name or sym}\n\nBUSINESS DESCRIPTION:\n{description[:2500]}\n"
    )
    data, llm_failed = _llm_json(
        sym, "B.1", "You are a precise extraction assistant. Reply with strict JSON only. Never infer or invent a name.",
        prompt, max_tokens=300, temperature=0.0,
    )

    ceo_name = str(data.get("ceo_name") or "").strip() or None
    ceo_title = str(data.get("ceo_title") or "").strip() or None
    context_note = str(data.get("context_note") or "").strip()

    payload = {
        "subpoint_id": subpoint_id,
        "title": "Founders / CEO track record: past successes/failures, tenure, relevance to current strategy",
        "available": True,
        "ceo_name": ceo_name,
        "ceo_title": ceo_title,
        "context_note": context_note,
        "track_record_rating": None,  # deliberately not scored — see docstring; needs FOUNDER-01..07
        "rationale": (
            (context_note + " " if context_note else "") +
            "No independently verified background check has been run (MCA directorship history, "
            "disqualification/debarment status, defaulter search, litigation search, and negative-news "
            "search are all unchecked — see pathway detail). This must not be treated as a clean or "
            "rated track record; route to an analyst for manual FOUNDER-01..07 checks before it "
            "factors into an investment decision."
        ),
        "pathway_results": pathway_results,
    }
    confidence_tag = "SEARCH_INCONCLUSIVE"
    if not llm_failed:
        write_qualitative(sym, subpoint_id, payload, confidence_tag)
    else:
        print(f"[qualitative_engine] B.1 NOT cached for {sym} — LLM call did not run; will retry next request.")
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b2_management_incentives(symbol, name=None, force=False):
    """B.2 — Management incentives: pay structure, equity ownership, vesting,
    long-term orientation. Formula: Fixed:variable pay ratio; ESOP as % of KMP
    compensation = ESOP value / Total KMP pay.

    Sourcing Sequence: AR-02 (KMP remuneration table) -> AR-03 (ESOP disclosure
    note) -> PORTAL-05 (MCA director registry — appointment dates only, NOT bio).

    Now wired to REAL Annual Report text: `annual_report_financials.
    fetch_governance_text_sections` downloads the company's own latest AR PDF
    (same PORTAL-01 pipeline every ratio card uses) and locates the actual
    remuneration-table / ESOP-annexure pages by content (digit-density scoring,
    not just a keyword hit — a real table is numbers-heavy, a passing mention
    isn't). The LLM extraction step is instructed to report ONLY what the given
    excerpt explicitly states — never invent a % or ratio the text doesn't
    contain. PORTAL-05 (MCA registry) still has no fetcher, so this stays
    SINGLE_SOURCE at best even when AR-02/AR-03 text is found.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.2"

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
        print(f"[qualitative_engine] B.2 AR text fetch failed for {sym}: {e}")
        gov = {"error": str(e)}

    remuneration_text = gov.get("remuneration_text")
    esop_text = gov.get("esop_text")
    pdf_url = gov.get("pdf_url")

    pathway_results = [
        {
            "pathway_id": "AR-02",
            "source": "KMP Remuneration table (Board's Report Annexure, Sec. 197(12))",
            "result": "CHECKED" if remuneration_text else "NOT_DISCLOSED",
            "note": None if remuneration_text else "Section not located in the latest Annual Report PDF this run — a differently-worded heading or a separate filing may carry it.",
        },
        {
            "pathway_id": "AR-03",
            "source": "ESOP disclosure note (SEBI SBEB Regulations 2021 Annexure)",
            "result": "CHECKED" if esop_text else "NOT_DISCLOSED",
            "note": None if esop_text else "Section not located in the latest Annual Report PDF this run — may indicate no ESOP scheme exists (NOT_APPLICABLE), not confirmed either way.",
        },
        {
            "pathway_id": "PORTAL-05",
            "source": "MCA Company/Director Master Data (appointment dates only, not remuneration)",
            "result": "NOT_DISCLOSED",
            "note": "No MCA director-master-data fetcher is wired into this codebase yet.",
        },
    ]

    if not remuneration_text and not esop_text:
        payload = {
            "subpoint_id": subpoint_id,
            "title": "Management incentives: pay structure, equity ownership, vesting, long-term orientation",
            "available": True,
            "fixed_variable_pay_ratio": None,
            "esop_pct_of_kmp_comp": None,
            "esop_facts": [],
            "rationale": gov.get("error") or "Neither the remuneration table nor the ESOP note was located in the latest Annual Report PDF this run.",
            "pathway_results": pathway_results,
            "source_pdf_url": pdf_url,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    context = f"COMPANY: {name or sym}\n"
    if remuneration_text:
        context += f"\n=== EXCERPT — REMUNERATION TABLE (real AR page text) ===\n{remuneration_text}\n"
    if esop_text:
        context += f"\n=== EXCERPT — ESOP DISCLOSURE (real AR page text) ===\n{esop_text}\n"

    prompt = (
        "You are extracting ONLY what is EXPLICITLY stated in the real Annual Report excerpts below. "
        "Do not compute a ratio unless the exact inputs are present in the text. Do not infer or estimate. "
        "If a figure is not explicitly stated, say so.\n\n"
        "Return ONLY JSON:\n"
        "{\n"
        '  "fixed_variable_pay_ratio": "e.g. \'70:30\' if explicitly stated or directly computable from stated fixed/variable figures, else null",\n'
        '  "esop_pct_of_kmp_comp": "numeric percent if explicitly stated or directly computable, else null",\n'
        '  "esop_facts": ["short factual items explicitly in the ESOP excerpt, e.g. options granted count, exercise price, vesting years - 0 to 4 items"],\n'
        '  "summary": "1-3 sentences summarizing only what the excerpts explicitly show"\n'
        "}\n\n"
        f"=== CONTEXT ===\n{context}"
    )
    data, llm_failed = _llm_json(
        sym, "B.2", "You are a precise extraction assistant. Reply with strict JSON only. Never infer or invent a number not explicitly in the text.",
        prompt, max_tokens=600, temperature=0.0,
    )

    fixed_variable_pay_ratio = data.get("fixed_variable_pay_ratio") or None
    esop_pct_of_kmp_comp = data.get("esop_pct_of_kmp_comp")
    try:
        esop_pct_of_kmp_comp = round(max(0.0, min(100.0, float(esop_pct_of_kmp_comp))), 1)
    except (TypeError, ValueError):
        esop_pct_of_kmp_comp = None
    esop_facts = [str(x).strip() for x in (data.get("esop_facts") or []) if str(x).strip()][:4]
    summary = str(data.get("summary") or "").strip()

    payload = {
        "subpoint_id": subpoint_id,
        "title": "Management incentives: pay structure, equity ownership, vesting, long-term orientation",
        "available": True,
        "fixed_variable_pay_ratio": fixed_variable_pay_ratio,
        "esop_pct_of_kmp_comp": esop_pct_of_kmp_comp,
        "esop_facts": esop_facts,
        "rationale": summary or "Remuneration/ESOP sections located in the Annual Report, but no directly stated ratio or percentage was found in the excerpt — see facts below.",
        "pathway_results": pathway_results,
        "source_pdf_url": pdf_url,
    }
    confidence_tag = "SINGLE_SOURCE"
    if not llm_failed:
        write_qualitative(sym, subpoint_id, payload, confidence_tag)
    else:
        print(f"[qualitative_engine] B.2 NOT cached for {sym} — LLM call did not run; will retry next request.")
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b3_management_bench_depth(symbol, name=None, force=False):
    """B.3 — Depth of management bench: ability to replace key execs without
    disruption. Formula: KMP attrition rate = KMP exits in period / Average KMP
    headcount.

    Sourcing Sequence: PORTAL-01 (get the AR PDF) -> QUAL-01 (LinkedIn/news,
    corroborative only) + FOUNDER-01 (check if bench members hold directorships
    at struck-off entities).

    PORTAL-01 IS wired: `annual_report_financials.fetch_governance_text_sections`
    (same real AR PDF used for B.2) is scanned for a "Key Managerial Personnel"
    excerpt. That excerpt is NOT guaranteed to be actual KMP appointment/
    resignation history — the phrase "Key Managerial Personnel" also appears in
    unrelated contexts (e.g. Related Party Transaction notes, board-resolution
    authorisations), so the LLM extraction is explicitly instructed to report
    "no bench-depth information" rather than force-fit whatever the excerpt
    contains into a KMP-changes narrative (DON'T/DO INSTEAD: never mis-route a
    pathway's content). QUAL-01 (LinkedIn) and FOUNDER-01 (MCA struck-off cross-
    check) remain unwired — no vendor/scraper for either.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.3"

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
        print(f"[qualitative_engine] B.3 AR text fetch failed for {sym}: {e}")
        gov = {"error": str(e)}

    kmp_text = gov.get("kmp_changes_text")
    pdf_url = gov.get("pdf_url")

    pathway_results = [
        {
            "pathway_id": "PORTAL-01",
            "source": "BSE Corporate Announcements -> Annual Report PDF (Key Managerial Personnel section)",
            "result": "CHECKED" if kmp_text else "NOT_DISCLOSED",
            "note": None if kmp_text else "\"Key Managerial Personnel\" section not located in the latest Annual Report PDF this run.",
        },
        {
            "pathway_id": "QUAL-01",
            "source": "LinkedIn org mapping (corroborative only)",
            "result": "NOT_DISCLOSED",
            "note": "No LinkedIn fetcher wired (LinkedIn specifically blocks scraping — would need a vendor like Proxycurl).",
        },
        {
            "pathway_id": "FOUNDER-01",
            "source": "MCA — check if bench members hold directorships at struck-off entities",
            "result": "NOT_DISCLOSED",
            "note": "No MCA director-master-data fetcher is wired into this codebase yet.",
        },
    ]

    if not kmp_text:
        payload = {
            "subpoint_id": subpoint_id,
            "title": "Depth of management bench: ability to replace key execs without disruption",
            "available": True,
            "bench_depth_rating": None,
            "kmp_attrition_rate_pct": None,
            "kmp_change_facts": [],
            "rationale": gov.get("error") or "No \"Key Managerial Personnel\" section was located in the latest Annual Report PDF this run.",
            "pathway_results": pathway_results,
            "source_pdf_url": pdf_url,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    prompt = (
        "The excerpt below is real Annual Report page text located because it contains the phrase "
        "\"Key Managerial Personnel\" — but that phrase also appears in unrelated contexts (e.g. Related "
        "Party Transaction notes, board-resolution authorisations), so it may NOT actually describe KMP "
        "appointments, resignations, or attrition. Read it carefully.\n\n"
        "Return ONLY JSON:\n"
        "{\n"
        '  "is_kmp_changes_content": true | false,   // true ONLY if this excerpt genuinely describes KMP appointments/resignations/attrition, not e.g. a payment/RPT table\n'
        '  "kmp_change_facts": ["short factual items explicitly stated, e.g. a named appointment/resignation with date - 0 to 3 items, empty if is_kmp_changes_content is false"],\n'
        '  "summary": "1-2 sentences on what the excerpt actually contains"\n'
        "}\n\n"
        f"=== EXCERPT ===\n{kmp_text}"
    )
    data, llm_failed = _llm_json(
        sym, "B.3", "You are a precise, skeptical extraction assistant. Reply with strict JSON only. Never force-fit unrelated text into the requested category.",
        prompt, max_tokens=400, temperature=0.0,
    )

    is_relevant = bool(data.get("is_kmp_changes_content"))
    kmp_change_facts = [str(x).strip() for x in (data.get("kmp_change_facts") or []) if str(x).strip()][:3] if is_relevant else []
    summary = str(data.get("summary") or "").strip()

    if not is_relevant:
        # llm_failed produces the exact same data shape as a genuine "this
        # excerpt isn't about KMP changes" verdict (is_relevant=False from an
        # empty {}) — without the guard below, a rate-limited call would get
        # cached as "the model read this and it does not describe KMP
        # changes", asserting a judgment that was never actually made.
        rationale = (
            "A \"Key Managerial Personnel\" mention was found in the Annual Report, but it does not "
            "describe KMP appointments/resignations/attrition (" + (summary or "different context") +
            ") — no genuine bench-depth information was located this run."
        ) if not llm_failed else "Could not be classified on this run — reload to try again."
        payload = {
            "subpoint_id": subpoint_id,
            "title": "Depth of management bench: ability to replace key execs without disruption",
            "available": True,
            "bench_depth_rating": None,
            "kmp_attrition_rate_pct": None,
            "kmp_change_facts": [],
            "rationale": rationale,
            "pathway_results": pathway_results,
            "source_pdf_url": pdf_url,
        }
        if not llm_failed:
            write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
        else:
            print(f"[qualitative_engine] B.3 NOT cached for {sym} — LLM call did not run; will retry next request.")
        payload["confidence_tag"] = "SEARCH_INCONCLUSIVE"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    payload = {
        "subpoint_id": subpoint_id,
        "title": "Depth of management bench: ability to replace key execs without disruption",
        "available": True,
        "bench_depth_rating": None,
        "kmp_attrition_rate_pct": None,  # requires exit-count + headcount over a period — not computable from a single excerpt
        "kmp_change_facts": kmp_change_facts,
        "rationale": summary or "KMP change details found in the Annual Report — see facts below.",
        "pathway_results": pathway_results,
        "source_pdf_url": pdf_url,
    }
    confidence_tag = "SINGLE_SOURCE"
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b4_communication_quality(symbol, name=None, force=False):
    """B.4 — Communication quality: transparency in disclosures, clarity in
    guidance, openness in meetings. N/A formula — a qualitative rating based on
    transcript review, per the spec.

    Sourcing Sequence: PORTAL-01 (get the AR PDF) -> AGG-01 (fallback/cross-check
    only) -> QUAL-02 (concall color).

    Unlike B.1-B.3, QUAL-02 (concall transcripts) IS wired in this codebase — the
    same grounded digest used for A.1/A.3/A.5 is real transcript content, not a
    guess. PORTAL-01 (AR investor-presentation filings) has no fetcher, so this
    stays SINGLE_SOURCE even with a real transcript-grounded judgment, per the
    cross-verification rule.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.4"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    digest = _concall_digest(sym, name)
    pathway_results = [
        {
            "pathway_id": "PORTAL-01",
            "source": "BSE Corporate Announcements -> investor presentation filings",
            "result": "NOT_DISCLOSED",
            "note": "No investor-presentation-filing fetcher is wired into this codebase yet.",
        },
        {
            "pathway_id": "AGG-01",
            "source": "Screener.in (fallback/cross-check only)",
            "result": "NOT_CHECKED",
            "note": "Cross-check pathway, only used if primary is unavailable or conflicting — not invoked this run.",
        },
        {
            "pathway_id": "QUAL-02",
            "source": "Concall Transcript (grounded digest — real transcript content)",
            "result": "CHECKED" if digest else "NOT_HELD",
            "note": None if digest else "No transcript found for a recent quarter — do not assume one happened unseen.",
        },
    ]

    if not digest:
        payload = {
            "subpoint_id": subpoint_id,
            "title": "Communication quality: transparency in disclosures, clarity in guidance, openness in meetings",
            "available": False,
            "reason": "No concall transcript corpus available for this company.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    company = name or sym
    context = f"COMPANY: {company}\n\nRECENT EARNINGS-CALL HIGHLIGHTS (newest first):\n{digest}\n"
    prompt = (
        "You are an equity analyst assessing MANAGEMENT COMMUNICATION QUALITY (transparency, guidance "
        "clarity, openness) for an Indian listed company, using ONLY the grounded concall context below. "
        "Do not invent facts. If unclear, say so rather than guessing.\n\n"
        "Return ONLY JSON:\n"
        "{\n"
        '  "communication_quality_rating": "Strong" | "Moderate" | "Weak" | "unclear",\n'
        '  "rationale": "2-4 sentences citing tone, specificity of guidance, or Q&A responsiveness evident in the context"\n'
        "}\n\n"
        f"=== CONTEXT ===\n{context}"
    )
    data, llm_failed = _llm_json(
        sym, "B.4", "You are a precise equity analyst. Reply with strict JSON only. Never fabricate.",
        prompt, max_tokens=500, temperature=0.1,
    )

    communication_quality_rating = str(data.get("communication_quality_rating") or "unclear").strip()
    if communication_quality_rating.lower() not in ("strong", "moderate", "weak"):
        communication_quality_rating = "unclear"
    else:
        communication_quality_rating = communication_quality_rating.capitalize()
    rationale = str(data.get("rationale") or "").strip()

    confidence_tag = "SINGLE_SOURCE" if rationale else "SEARCH_INCONCLUSIVE"

    payload = {
        "subpoint_id": subpoint_id,
        "title": "Communication quality: transparency in disclosures, clarity in guidance, openness in meetings",
        "available": True,
        "communication_quality_rating": communication_quality_rating,
        "rationale": rationale,
        "pathway_results": pathway_results,
        "grounded": True,
    }
    if not llm_failed:
        write_qualitative(sym, subpoint_id, payload, confidence_tag)
    else:
        print(f"[qualitative_engine] B.4 NOT cached for {sym} — LLM call did not run; will retry next request.")
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_b5_execution_credibility(symbol, name=None, force=False):
    """B.5 — Execution credibility: delivered vs stated milestones historically.
    Formula: Guidance accuracy % = Actual metric / Guided metric (tracked per
    quarter).

    Sourcing Sequence: PORTAL-01 (get the AR PDF) -> AGG-01 (fallback/cross-check
    only) -> QUAL-02 (concall color).

    Same shape as B.4: QUAL-02 (concall transcripts) is real and wired. The
    quantitative Guidance accuracy % genuinely needs a structured guidance-vs-
    actual tracker (investor-presentation guidance slides matched to each
    quarter's delivered numbers) this codebase doesn't build — recorded
    NOT_DISCLOSED rather than guessed. The qualitative execution_credibility
    rating IS grounded in real concall commentary (management often explicitly
    references prior guidance and what was delivered), so this stays useful even
    without the numeric tracker. SINGLE_SOURCE at best — PORTAL-01 not wired.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "B.5"

    if not force:
        cached = read_qualitative(sym, subpoint_id)
        if cached is not None:
            try:
                age = time.time() - time.mktime(time.strptime(cached["retrieved_at"][:19], "%Y-%m-%dT%H:%M:%S"))
                if age <= CACHE_TTL:
                    return cached
            except Exception:
                return cached

    digest = _concall_digest(sym, name)
    pathway_results = [
        {
            "pathway_id": "PORTAL-01",
            "source": "BSE Corporate Announcements -> investor presentation guidance slides",
            "result": "NOT_DISCLOSED",
            "note": "No guidance-slide fetcher or structured guidance-vs-actual tracker is wired into this codebase yet.",
        },
        {
            "pathway_id": "AGG-01",
            "source": "Screener.in (fallback/cross-check only)",
            "result": "NOT_CHECKED",
            "note": "Cross-check pathway, only used if primary is unavailable or conflicting — not invoked this run.",
        },
        {
            "pathway_id": "QUAL-02",
            "source": "Concall Transcript (grounded digest — real transcript content)",
            "result": "CHECKED" if digest else "NOT_HELD",
            "note": None if digest else "No transcript found for a recent quarter — do not assume one happened unseen.",
        },
    ]

    if not digest:
        payload = {
            "subpoint_id": subpoint_id,
            "title": "Execution credibility: delivered vs stated milestones historically",
            "available": False,
            "reason": "No concall transcript corpus available for this company.",
            "pathway_results": pathway_results,
        }
        write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    company = name or sym
    context = f"COMPANY: {company}\n\nRECENT EARNINGS-CALL HIGHLIGHTS (newest first):\n{digest}\n"
    prompt = (
        "You are an equity analyst assessing EXECUTION CREDIBILITY (delivered vs stated milestones) for "
        "an Indian listed company, using ONLY the grounded concall context below. Look for management "
        "referencing PRIOR guidance/targets and whether they were met, missed, or exceeded. Do not invent "
        "facts. If the context doesn't show a clear guidance-vs-actual comparison, say so rather than "
        "guessing.\n\n"
        "Return ONLY JSON:\n"
        "{\n"
        '  "execution_credibility_rating": "Strong" | "Mixed" | "Weak" | "unclear",\n'
        '  "milestone_track_record": ["short factual items — a guided target and what was delivered, e.g. \'Guided double-digit EBITDA growth, delivered\' - 0 to 3 items, empty list if the context gives no clear guidance-vs-actual comparison"],\n'
        '  "rationale": "2-4 sentences citing what in the context supports this"\n'
        "}\n\n"
        f"=== CONTEXT ===\n{context}"
    )
    data, llm_failed = _llm_json(
        sym, "B.5", "You are a precise equity analyst. Reply with strict JSON only. Never fabricate.",
        prompt, max_tokens=600, temperature=0.1,
    )

    execution_credibility_rating = str(data.get("execution_credibility_rating") or "unclear").strip()
    if execution_credibility_rating.lower() not in ("strong", "mixed", "weak"):
        execution_credibility_rating = "unclear"
    else:
        execution_credibility_rating = execution_credibility_rating.capitalize()
    milestone_track_record = [str(x).strip() for x in (data.get("milestone_track_record") or []) if str(x).strip()][:3]
    rationale = str(data.get("rationale") or "").strip()

    confidence_tag = "SINGLE_SOURCE" if rationale else "SEARCH_INCONCLUSIVE"

    payload = {
        "subpoint_id": subpoint_id,
        "title": "Execution credibility: delivered vs stated milestones historically",
        "available": True,
        "execution_credibility_rating": execution_credibility_rating,
        "milestone_track_record": milestone_track_record,
        "guidance_accuracy_pct": None,  # requires structured guidance-vs-actual tracker — not wired
        "rationale": rationale,
        "pathway_results": pathway_results,
        "grounded": True,
    }
    if not llm_failed:
        write_qualitative(sym, subpoint_id, payload, confidence_tag)
    else:
        print(f"[qualitative_engine] B.5 NOT cached for {sym} — LLM call did not run; will retry next request.")
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
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


def compute_c3_related_party_transactions(symbol, name=None, force=False):
    """C.3 — Related-party transactions (RPTs): frequency, counterparty identity,
    pricing and rationale. Formula: RPT intensity = Total RPT value / Total
    revenue.

    Sourcing Sequence: AR-04 (RPT note) -> AR-05 (group structure) -> PORTAL-05
    (director registry, NOT bio — counterparty cross-check) -> AGG-01 (Tofler,
    fallback/cross-check only).

    Same situation as B.2/B.3/B.6: no AR-04 RPT-note parser, no AR-05 group-
    structure parser, no PORTAL-05 MCA fetcher, no Tofler fetcher. RPT value,
    counterparty names, and pricing/rationale disclosures don't legitimately
    appear in a generic business-description paragraph or concall transcript —
    same guardrail as B.2/B.3/B.6, that text is not used as a stand-in here.
    Honest full gap, no LLM call.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.3"

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
            "pathway_id": "AR-04",
            "source": "Related Party Transactions note (Notes to Financial Statements)",
            "result": "NOT_DISCLOSED",
            "note": "No AR-04 RPT-note parser is wired into this codebase yet.",
        },
        {
            "pathway_id": "AR-05",
            "source": "Subsidiaries / group structure (Form AOC-1 + Consolidated Notes)",
            "result": "NOT_DISCLOSED",
            "note": "No AR-05 group-structure parser is wired into this codebase yet.",
        },
        {
            "pathway_id": "PORTAL-05",
            "source": "MCA Company/Director Master Data (counterparty cross-check, NOT bio)",
            "result": "NOT_DISCLOSED",
            "note": "No MCA director-master-data fetcher is wired into this codebase yet.",
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
        "title": "Related-party transactions (RPTs): frequency, counterparty identity, pricing and rationale",
        "available": True,
        "rpt_intensity_pct": None,
        "rpt_frequency": None,
        "counterparty_flags": [],
        "rationale": "Not computed — AR-04 (RPT note), AR-05 (group structure), and PORTAL-05 (MCA counterparty cross-check) all require fetchers this codebase doesn't have yet.",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SEARCH_INCONCLUSIVE"
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


def compute_c7_capital_allocation(symbol, name=None, force=False):
    """C.7 — Capital allocation decisions: history of cash deployment and
    rationale. Formula: Capital allocation mix % = Each use of cash / Total cash
    deployed (a 5-8 year table of capex, M&A spend, buybacks and dividends from
    the Cash Flow Statement).

    Sourcing Sequence: AR-08 (Statement of Cash Flows) -> AGG-01 (fallback/
    cross-check only).

    AR-08 (the Cash Flow Statement itself) IS parsed elsewhere in this codebase,
    but only for a SINGLE latest year's capex figure (used by a different ratio,
    Free Cash Flow) — not the 5-8 year, 4-line (capex / M&A spend / buybacks /
    dividends) breakdown this sub-point's formula actually requires. Dividends
    paid, buyback spend, and M&A/acquisition cash outflow are not extracted
    anywhere in this codebase at all, for any year. Building a real multi-year
    capital-allocation mix table needs new cash-flow-statement parsing work this
    pass doesn't include — recorded as an honest gap rather than a guessed mix,
    same convention as C.3-C.6.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "C.7"

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
            "pathway_id": "AR-08",
            "source": "Statement of Cash Flows (5-8yr capex/M&A/buybacks/dividends breakdown)",
            "result": "NOT_DISCLOSED",
            "note": "Only a single latest-year capex figure is extracted elsewhere in this codebase (for the Free Cash Flow ratio) — dividends paid, buyback spend, and M&A cash outflow are not extracted for any year, and no multi-year table is built.",
        },
        {
            "pathway_id": "AGG-01",
            "source": "Screener.in — Cash Flow tab (fallback/cross-check only)",
            "result": "NOT_CHECKED",
            "note": "Cross-check pathway, only used if primary is unavailable or conflicting — not invoked this run.",
        },
    ]

    payload = {
        "subpoint_id": subpoint_id,
        "title": "Capital allocation decisions: history of cash deployment and rationale",
        "available": True,
        "capital_allocation_mix": None,
        "years_covered": None,
        "rationale": "Not computed — a 5-8 year, capex/M&A/buybacks/dividends cash-flow breakdown requires new statement parsing this codebase doesn't have yet (only a single latest-year capex figure exists, for a different ratio).",
        "pathway_results": pathway_results,
    }
    confidence_tag = "SEARCH_INCONCLUSIVE"
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


def compute_a3_revenue_model_quality(symbol, name=None, description="", force=False):
    """A.3 — Revenue model quality: transactional, recurring, annuity, contract
    length & renewal dynamics. Formula: Contract renewal rate = Contracts renewed /
    Contracts up for renewal.

    Sourcing Sequence: AR-14 (revenue/segment note -> specifically "Revenue from
    Contracts with Customers" / revenue recognition policy) -> AGG-01 (fallback/
    cross-check only).

    Same gap as A.1: no structured extractor exists for the Notes-to-Accounts
    revenue-recognition policy note or a disclosed contract renewal rate — those
    are numeric/structured AR-14 sub-items this codebase doesn't parse yet. As a
    best-effort proxy (same approach as A.1's AR-13), the business description +
    grounded concall digest are used for a narrative revenue-MODEL classification
    only; the contract renewal rate itself is left NOT_DISCLOSED rather than
    guessed. SINGLE_SOURCE at most (never VERIFIED — AGG-01 fallback not invoked).
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    subpoint_id = "A.3"

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
    digest = _concall_digest(sym, name)
    company = name or sym
    context = f"COMPANY: {company}\n"
    if description:
        context += f"\nBUSINESS DESCRIPTION (from filings):\n{description[:2500]}\n"
    if digest:
        context += f"\nRECENT EARNINGS-CALL HIGHLIGHTS (newest first):\n{digest}\n"

    ar14_checked = bool(description or digest)
    pathway_results.append({
        "pathway_id": "AR-14",
        "source": "Revenue/segment note — revenue recognition policy (business description + concall digest proxy; the structured Notes-to-Accounts extraction itself is not wired)",
        "result": "CHECKED" if ar14_checked else "NOT_DISCLOSED",
    })
    pathway_results.append({
        "pathway_id": "AGG-01",
        "source": "Screener.in (fallback/cross-check only)",
        "result": "NOT_CHECKED",
        "note": "Cross-check pathway, only used if primary is unavailable or conflicting — not invoked this run.",
    })

    if not ar14_checked:
        payload = {
            "subpoint_id": subpoint_id,
            "title": "Revenue model quality: transactional, recurring, annuity, contract length & renewal dynamics",
            "available": False,
            "reason": "No business description or concall corpus available to ground AR-14.",
            "pathway_results": pathway_results,
            "contract_renewal_rate_pct": None,
        }
        write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    prompt = (
        "You are an equity analyst assessing REVENUE MODEL QUALITY for an Indian listed company, "
        "using ONLY the grounded context below. Do not invent facts not supported by the context. "
        "If unclear, say so rather than guessing.\n\n"
        "Return ONLY JSON:\n"
        "{\n"
        '  "revenue_model": "transactional" | "recurring" | "annuity" | "mixed" | "unclear",\n'
        '  "contract_dynamics": "1-3 sentences on contract length / renewal dynamics IF mentioned in the context, else state not disclosed in the given context",\n'
        '  "rationale": "2-4 sentences citing what in the context supports the revenue_model classification"\n'
        "}\n\n"
        f"=== CONTEXT ===\n{context}"
    )
    data, llm_failed = _llm_json(
        sym, "A.3", "You are a precise equity analyst. Reply with strict JSON only. Never fabricate.",
        prompt, max_tokens=600, temperature=0.1,
    )

    revenue_model = str(data.get("revenue_model") or "unclear").strip().lower()
    if revenue_model not in ("transactional", "recurring", "annuity", "mixed", "unclear"):
        revenue_model = "unclear"
    contract_dynamics = str(data.get("contract_dynamics") or "").strip()
    rationale = str(data.get("rationale") or "").strip()

    confidence_tag = "SINGLE_SOURCE" if rationale else "SEARCH_INCONCLUSIVE"

    payload = {
        "subpoint_id": subpoint_id,
        "title": "Revenue model quality: transactional, recurring, annuity, contract length & renewal dynamics",
        "available": True,
        "revenue_model": revenue_model,
        "contract_dynamics": contract_dynamics,
        "rationale": rationale,
        "contract_renewal_rate_pct": None,  # requires a disclosed renewal count — not wired
        "pathway_results": pathway_results,
        "grounded": bool(digest),
    }
    if not llm_failed:
        write_qualitative(sym, subpoint_id, payload, confidence_tag)
    else:
        print(f"[qualitative_engine] A.3 NOT cached for {sym} — LLM call did not run; will retry next request.")
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload
