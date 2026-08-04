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

import time

from tools.qualitative_db import write_qualitative, read_qualitative

CACHE_TTL = 30 * 24 * 3600  # business-model classification changes slowly


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
    """A.1 — Clarity of business model: single product vs portfolio; cyclical vs
    recurring revenue.

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
            "title": "Clarity of business model: single product vs portfolio; cyclical vs recurring revenue",
            "available": False,
            "reason": "No business description or concall corpus available to ground AR-13.",
            "pathway_results": pathway_results,
            "recurring_revenue_pct": None,
        }
        write_qualitative(sym, subpoint_id, payload, "NOT_FOUND")
        payload["confidence_tag"] = "NOT_FOUND"
        payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return payload

    segment_schema = (
        '  "segment_patterns": [{"label": "<EXACT segment label from the REPORTED BUSINESS SEGMENTS list>", '
        '"revenue_pattern": "recurring" | "cyclical" | "mixed"}],\n'
        if segments_pct else ""
    )
    segment_instruction = (
        "\nThe REPORTED BUSINESS SEGMENTS list above gives REAL, audited revenue shares. For EACH one, "
        "classify its revenue_pattern using the same definitions as the overall business — label ONLY the "
        "segments listed, using their exact label text, one entry per segment, in the same order.\n"
        if segments_pct else ""
    )
    prompt = (
        "You are an equity analyst assessing BUSINESS MODEL CLARITY for an Indian listed company, "
        "using ONLY the grounded context below. Do not invent facts not supported by the context. "
        "If the context does not clearly support a judgment, say so explicitly rather than guessing.\n"
        f"{segment_instruction}\n"
        "Return ONLY JSON:\n"
        "{\n"
        '  "model_type": "single_product" | "portfolio" | "unclear",\n'
        '  "revenue_pattern": "recurring" | "cyclical" | "mixed" | "unclear",\n'
        '  "rationale": "2-4 sentences citing what in the context supports this, or noting it is unclear",\n'
        '  "segments_mentioned": ["short segment/product names mentioned in the context, if any"],\n'
        f"{segment_schema}"
        "}\n\n"
        f"=== CONTEXT ===\n{context}"
    )
    try:
        from tools.groq_client import groq_chat, parse_json_loose
        raw = groq_chat(
            messages=[
                {"role": "system", "content": "You are a precise equity analyst. Reply with strict JSON only. Never fabricate."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=700, temperature=0.1,
        )
        data = parse_json_loose(raw) or {}
    except Exception as e:
        print(f"[qualitative_engine] A.1 LLM call failed for {sym}: {e}")
        data = {}

    model_type = str(data.get("model_type") or "unclear").strip().lower()
    if model_type not in ("single_product", "portfolio", "unclear"):
        model_type = "unclear"
    revenue_pattern = str(data.get("revenue_pattern") or "unclear").strip().lower()
    if revenue_pattern not in ("recurring", "cyclical", "mixed", "unclear"):
        revenue_pattern = "unclear"
    rationale = str(data.get("rationale") or "").strip()
    segments = [str(s).strip() for s in (data.get("segments_mentioned") or []) if str(s).strip()][:10]

    # Combine REAL revenue shares (segments_pct, deterministic from the AR)
    # with the LLM's per-segment pattern judgment, matched by exact label —
    # a segment's % is never something the LLM can alter, only its
    # recurring/cyclical/mixed classification. A segment the LLM didn't
    # classify (or classified inconsistently) defaults to "mixed" rather
    # than being dropped, since the revenue share itself is still real data
    # worth showing.
    segment_shares = None
    recurring_revenue_pct = None
    if segments_pct:
        pattern_by_label = {}
        for sp in (data.get("segment_patterns") or []):
            lbl = str(sp.get("label") or "").strip()
            pat = str(sp.get("revenue_pattern") or "").strip().lower()
            if lbl and pat in ("recurring", "cyclical", "mixed"):
                pattern_by_label[lbl.lower()] = pat
        segment_shares = [
            {"label": s["label"], "pct": s["pct"], "revenue_pattern": pattern_by_label.get(s["label"].lower(), "mixed")}
            for s in segments_pct
        ]
        recurring_revenue_pct = round(sum(s["pct"] for s in segment_shares if s["revenue_pattern"] == "recurring"), 1)

    # Only one of the two Sourcing Sequence pathways (AR-13) was actually checked;
    # AR-14 is a recorded gap, not an independent second source — so this is
    # SINGLE_SOURCE per the cross-verification rule, never VERIFIED.
    confidence_tag = "SINGLE_SOURCE" if rationale else "SEARCH_INCONCLUSIVE"

    payload = {
        "subpoint_id": subpoint_id,
        "title": "Clarity of business model: single product vs portfolio; cyclical vs recurring revenue",
        "available": True,
        "model_type": model_type,
        "revenue_pattern": revenue_pattern,
        "rationale": rationale,
        "segments_mentioned": segments,
        "segment_shares": segment_shares,  # [{label, pct, revenue_pattern}] from the real AR-14 segment note, or None
        "recurring_revenue_pct": recurring_revenue_pct,
        "pathway_results": pathway_results,
        "grounded": bool(digest),
    }
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload


def compute_a2_competitive_moat(symbol, name=None, description="", force=False):
    """A.2 — Competitive advantage / moats: brand, distribution, cost leadership,
    network effects, switching costs. N/A formula — a qualitative 1-5 rating based
    on an evidence checklist, per the spec.

    Sourcing Sequence: PORTAL-07 (rating-agency rationale, e.g. CRISIL/ICRA) ->
    AGG-01 (Screener.in / Tijori peer-moat comparison, fallback/cross-check only).

    PORTAL-07 has no fetcher built in this codebase (no CRISIL/ICRA rationale
    scraper) — recorded as NOT_DISCLOSED. AGG-01 (Screener.in) IS wired: this
    reuses tools/moat_engine.py's existing data-driven moat scorer, which turns
    Screener.in's published fundamentals (ROCE level+consistency, operating-margin
    level+stability, ROE track record, balance-sheet leverage, working-capital
    efficiency, growth durability) into a transparent, threshold-based 0-100 score
    — every pillar traceable to a real number, never an LLM guess. Since only ONE
    of the two Sourcing Sequence pathways was checked, this is SINGLE_SOURCE at
    best, never VERIFIED (cross-verification rule) — and if the Screener scrape
    itself fails or returns too few inputs, this falls back to SEARCH_INCONCLUSIVE
    rather than show a low-confidence number as if it were solid.
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

    pathway_results = [
        {
            "pathway_id": "PORTAL-07",
            "source": "Rating Agency Rationale (CRISIL/ICRA/CARE)",
            "result": "NOT_DISCLOSED",
            "note": "No rating-agency rationale fetcher is wired into this codebase yet — cannot confirm UNRATED vs. a rationale simply not being fetched.",
        },
    ]

    moat_result = None
    try:
        from tools.screener_scraper import fetch_screener_moat_data
        from tools.moat_engine import compute_moat
        screener_data = fetch_screener_moat_data(sym, name) or {}
        moat_result = compute_moat(screener_data, name or sym)
    except Exception as e:
        print(f"[qualitative_engine] A.2 Screener moat fetch failed for {sym}: {e}")

    n_pillars = len(moat_result.get("pillars") or []) if moat_result else 0
    if not moat_result or n_pillars < 3 or moat_result.get("moat_strength") == "Unrated":
        pathway_results.append({
            "pathway_id": "AGG-01",
            "source": "Screener.in — data-driven moat scorer (tools/moat_engine.py)",
            "result": "NOT_DISCLOSED",
            "note": "Screener.in scrape failed or returned too few inputs (<3 of 8 pillars) to score reliably.",
        })
        payload = {
            "subpoint_id": subpoint_id,
            "title": "Competitive advantage / moats: brand, distribution, cost leadership, network effects, switching costs",
            "available": True,
            "moat_rating": None,
            "moat_pillars_bar": [],
            "rationale": "Rating not computed — PORTAL-07 not wired, and the AGG-01 (Screener.in) scrape returned too few inputs this run.",
            "pathway_results": pathway_results,
        }
        confidence_tag = "SEARCH_INCONCLUSIVE"
    else:
        pathway_results.append({
            "pathway_id": "AGG-01",
            "source": "Screener.in — data-driven moat scorer (tools/moat_engine.py)",
            "result": "CHECKED",
            "note": f"{n_pillars} pillars scored from real Screener.in fundamentals (ROCE, OPM, ROE, leverage, working capital, growth) — see breakdown below.",
        })
        moat_rating = round(moat_result["moat_score"] / 100 * 5, 1)
        pillars_bar = [
            {"label": p["label"], "value": round((p["score"] / p["max"]) * 5, 1) if p.get("max") else 0}
            for p in moat_result.get("pillars") or [] if p.get("max")
        ]
        payload = {
            "subpoint_id": subpoint_id,
            "title": "Competitive advantage / moats: brand, distribution, cost leadership, network effects, switching costs",
            "available": True,
            "moat_rating": moat_rating,
            "moat_strength": moat_result.get("moat_strength"),
            "moat_pillars_bar": pillars_bar,
            "rationale": moat_result.get("memo_text") or "",
            "pathway_results": pathway_results,
        }
        confidence_tag = "SINGLE_SOURCE"

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
    try:
        from tools.groq_client import groq_chat, parse_json_loose
        raw = groq_chat(
            messages=[
                {"role": "system", "content": "You are a precise equity analyst. Reply with strict JSON only. Never fabricate."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=600, temperature=0.1,
        )
        data = parse_json_loose(raw) or {}
    except Exception as e:
        print(f"[qualitative_engine] A.4 LLM call failed for {sym}: {e}")
        data = {}

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
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
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
    try:
        from tools.groq_client import groq_chat, parse_json_loose
        raw = groq_chat(
            messages=[
                {"role": "system", "content": "You are a precise equity analyst. Reply with strict JSON only. Never fabricate."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=600, temperature=0.1,
        )
        data = parse_json_loose(raw) or {}
    except Exception as e:
        print(f"[qualitative_engine] A.5 LLM call failed for {sym}: {e}")
        data = {}

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
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
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
    try:
        from tools.groq_client import groq_chat, parse_json_loose
        raw = groq_chat(
            messages=[
                {"role": "system", "content": "You are a precise equity analyst. Reply with strict JSON only. Never fabricate."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=700, temperature=0.1,
        )
        data = parse_json_loose(raw) or {}
    except Exception as e:
        print(f"[qualitative_engine] A.6 LLM call failed for {sym}: {e}")
        data = {}

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
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
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
    try:
        from tools.groq_client import groq_chat, parse_json_loose
        raw = groq_chat(
            messages=[
                {"role": "system", "content": "You are a precise extraction assistant. Reply with strict JSON only. Never infer or invent a name."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=300, temperature=0.0,
        )
        data = parse_json_loose(raw) or {}
    except Exception as e:
        print(f"[qualitative_engine] B.1 LLM call failed for {sym}: {e}")
        data = {}

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
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
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
    try:
        from tools.groq_client import groq_chat, parse_json_loose
        raw = groq_chat(
            messages=[
                {"role": "system", "content": "You are a precise extraction assistant. Reply with strict JSON only. Never infer or invent a number not explicitly in the text."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=600, temperature=0.0,
        )
        data = parse_json_loose(raw) or {}
    except Exception as e:
        print(f"[qualitative_engine] B.2 LLM call failed for {sym}: {e}")
        data = {}

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
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
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
    try:
        from tools.groq_client import groq_chat, parse_json_loose
        raw = groq_chat(
            messages=[
                {"role": "system", "content": "You are a precise, skeptical extraction assistant. Reply with strict JSON only. Never force-fit unrelated text into the requested category."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=400, temperature=0.0,
        )
        data = parse_json_loose(raw) or {}
    except Exception as e:
        print(f"[qualitative_engine] B.3 LLM call failed for {sym}: {e}")
        data = {}

    is_relevant = bool(data.get("is_kmp_changes_content"))
    kmp_change_facts = [str(x).strip() for x in (data.get("kmp_change_facts") or []) if str(x).strip()][:3] if is_relevant else []
    summary = str(data.get("summary") or "").strip()

    if not is_relevant:
        payload = {
            "subpoint_id": subpoint_id,
            "title": "Depth of management bench: ability to replace key execs without disruption",
            "available": True,
            "bench_depth_rating": None,
            "kmp_attrition_rate_pct": None,
            "kmp_change_facts": [],
            "rationale": (
                "A \"Key Managerial Personnel\" mention was found in the Annual Report, but it does not "
                "describe KMP appointments/resignations/attrition (" + (summary or "different context") +
                ") — no genuine bench-depth information was located this run."
            ),
            "pathway_results": pathway_results,
            "source_pdf_url": pdf_url,
        }
        write_qualitative(sym, subpoint_id, payload, "SEARCH_INCONCLUSIVE")
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
    try:
        from tools.groq_client import groq_chat, parse_json_loose
        raw = groq_chat(
            messages=[
                {"role": "system", "content": "You are a precise equity analyst. Reply with strict JSON only. Never fabricate."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=500, temperature=0.1,
        )
        data = parse_json_loose(raw) or {}
    except Exception as e:
        print(f"[qualitative_engine] B.4 LLM call failed for {sym}: {e}")
        data = {}

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
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
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
    try:
        from tools.groq_client import groq_chat, parse_json_loose
        raw = groq_chat(
            messages=[
                {"role": "system", "content": "You are a precise equity analyst. Reply with strict JSON only. Never fabricate."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=600, temperature=0.1,
        )
        data = parse_json_loose(raw) or {}
    except Exception as e:
        print(f"[qualitative_engine] B.5 LLM call failed for {sym}: {e}")
        data = {}

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
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
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
    try:
        from tools.groq_client import groq_chat, parse_json_loose
        raw = groq_chat(
            messages=[
                {"role": "system", "content": "You are a precise equity analyst. Reply with strict JSON only. Never fabricate."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=600, temperature=0.1,
        )
        data = parse_json_loose(raw) or {}
    except Exception as e:
        print(f"[qualitative_engine] A.3 LLM call failed for {sym}: {e}")
        data = {}

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
    write_qualitative(sym, subpoint_id, payload, confidence_tag)
    payload["confidence_tag"] = confidence_tag
    payload["retrieved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return payload
