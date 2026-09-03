"""
A.2 moat rating: peer-relative quintile scoring (a)-(h) + the required
qualitative-evidence score (i), combined into a composite Moat Score (j).

Per the spec: (a)-(h) are the company's own 3-5yr metric ranked against its
PEER SET (tools/peer_universe.py's fixed-universe, market-cap-band protocol)
via quintile/percentile - NOT the absolute-threshold scoring
tools/moat_engine.py uses for the single-company F-20 card (that engine
stays as-is for its own feature; this is a separate, peer-relative score
built specifically for A.2). (i) is sourced from CRISIL's rating rationale
(tools/crisil_scraper.py, PORTAL-07) plus management commentary, scored via
the 1-5 rubric. The HARD RULE: if (i) cannot be sourced, no composite is
shown - the whole rating is flagged QUANT_PROXY_ONLY.
"""

import statistics

from tools.peer_universe import select_peer_set
from tools.screener_scraper import fetch_screener_moat_data

# (metric_key, label, higher_is_better)
QUANT_METRICS = [
    ("roce_level", "ROCE level", True),
    ("roce_consistency", "ROCE consistency", True),
    ("opm_level", "Operating margin level", True),
    ("opm_stability", "Operating margin stability", True),
    ("roe_track", "ROE 3-yr track record", True),
    ("leverage", "Balance-sheet leverage", False),
    ("wc_efficiency", "Working-capital efficiency", False),
    ("growth_durability", "Growth durability", True),
]


def _stability_index(series):
    vals = [v for v in (series or []) if v is not None]
    if len(vals) < 2:
        return None
    m = statistics.mean(vals)
    if m == 0:
        return None
    cov = statistics.pstdev(vals) / abs(m)
    return max(0.0, min(1.0, 1 - cov / 0.5))


def _derive_metrics(screener_data):
    """Screener moat fields -> the 8 raw metric values used for peer ranking."""
    d = screener_data or {}
    roce_hist = d.get("roce_history") or []
    opm_hist = d.get("opm_history") or []
    growth_candidates = [x for x in [d.get("profit_growth_5y"), d.get("sales_growth_5y")] if x is not None]
    return {
        "roce_level": d.get("roce_latest"),
        "roce_consistency": min(roce_hist) if len(roce_hist) >= 2 else None,
        "opm_level": statistics.mean([x for x in opm_hist if x is not None]) if opm_hist else None,
        "opm_stability": _stability_index(opm_hist),
        "roe_track": d.get("roe_3y") or d.get("roe_5y") or d.get("roe_latest"),
        "leverage": d.get("debt_to_equity"),
        "wc_efficiency": d.get("cash_conversion_cycle"),
        "growth_durability": max(growth_candidates) if growth_candidates else None,
    }


def _percentile(population, target, higher_is_better):
    vals = [v for v in population if v is not None]
    if target is None or not vals:
        return None
    if higher_is_better:
        beaten = sum(1 for v in vals if v <= target)
    else:
        beaten = sum(1 for v in vals if v >= target)
    return round(beaten / len(vals) * 100)


def score_quant_pillars(symbol, market_cap_cr=None):
    """
    Locks the peer set (tools.peer_universe), pulls the same-source (Screener)
    fundamentals for target + peers, and quintile-scores each of the 8 (a)-(h)
    sub-metrics 0-5 by the target's percentile standing within that peer set.

    Returns {"status": "OK"/"INSUFFICIENT_PEER_SET"/"NOT_IN_UNIVERSE"/"NOT_CHECKED",
             "peer_set": {...select_peer_set() result...},
             "pillars": [{"key","label","score_0_5","value","percentile"}...] }

    Same guard convention as tools.crisil_scraper.fetch_crisil_rationale:
    in tools.manual_mode's document-only manual workflow, this NEVER
    reaches live screener.in (tools.peer_universe.select_peer_set and
    tools.screener_scraper.fetch_screener_moat_data both fetch peer/target
    fundamentals live) - Screener.in peer data has no uploaded-document
    equivalent, so every caller (A.2's build_moat_rating_breakdown, and the
    direct A.2.C peer-OPM leg already worked around this in
    qualitative_engine.py) gets an honest "NOT_CHECKED", never a fabricated
    percentile/score, and no pillars.
    """
    from tools.manual_mode import is_manual_mode
    if is_manual_mode():
        return {"status": "NOT_CHECKED", "peer_set": None, "pillars": []}
    peer_result = select_peer_set(symbol, market_cap_cr=market_cap_cr)
    if peer_result.get("status") != "OK":
        return {"status": peer_result["status"], "peer_set": peer_result, "pillars": []}

    target_data = fetch_screener_moat_data(symbol) or {}
    target_metrics = _derive_metrics(target_data)

    peer_metrics = {}
    for psym in peer_result["peers"]:
        pdata = fetch_screener_moat_data(psym) or {}
        peer_metrics[psym] = _derive_metrics(pdata)

    pillars = []
    for key, label, hib in QUANT_METRICS:
        population = [target_metrics.get(key)] + [peer_metrics[p].get(key) for p in peer_result["peers"]]
        pct = _percentile(population, target_metrics.get(key), hib)
        pillars.append({
            "key": key,
            "label": label,
            "value": target_metrics.get(key),
            "percentile": pct,
            "score_0_5": round(pct / 100 * 5, 1) if pct is not None else None,
            "peers_with_data": sum(1 for p in peer_result["peers"] if peer_metrics[p].get(key) is not None),
        })

    return {
        "status": "OK",
        "peer_set": peer_result,
        "target_metrics": target_metrics,
        "pillars": pillars,
    }


_QUAL_EVIDENCE_SYSTEM = (
    "You are a precise equity analyst scoring the QUALITATIVE EVIDENCE for a company's "
    "competitive moat (brand, distribution, cost leadership, network effects, switching costs), "
    "using ONLY the CRISIL/ICRA rating-rationale text and management commentary provided. "
    "Never invent facts not present in the text. Score 1-5 using EXACTLY this rubric:\n"
    "5 = specific, named, verifiable evidence tied directly to a moat type (e.g. an exclusive "
    "distribution agreement with a named counterparty through a named year, a named patent, a "
    "market-share move with numbers), with source location cited.\n"
    "4 = clear specific evidence but only one supporting data point, or strong evidence from a "
    "rationale more than 2 years old.\n"
    "3 = evidence exists but is generic/qualitative with no specifics (e.g. 'established brand', "
    "'strong market position') and no concrete number/timeframe/mechanism.\n"
    "2 = the only 'evidence' is the company's own management/marketing language with no "
    "independent (CRISIL/ICRA/third-party) corroboration.\n"
    "1 = only vague boilerplate phrasing ('strong brand', 'leading player') with zero specifics "
    "from any source.\n"
    "If NO qualitative commentary of any kind exists in the text (not even vague/boilerplate), "
    "return score null - do NOT assign a 1 in that case; 1 still means evidence was found and was "
    "weak, null means none could be found at all.\n"
    "Reply with STRICT JSON only: "
    '{"score": 1-5 or null, "moat_type": "brand|distribution|cost_leadership|network_effects|'
    'switching_costs|null", "evidence_quote": "short quote or empty string", '
    '"source": "CRISIL rationale|management commentary|none", "reasoning": "one sentence"}'
)


def score_qualitative_evidence(symbol, name=None, crisil_result=None, concall_digest="", skip_llm=False):
    """
    (i) Qualitative evidence score - sourced from PORTAL-07 (CRISIL rating
    rationale's Key Rating Drivers) first, management commentary (concall
    digest, an MD&A proxy already used elsewhere in this codebase) second.
    Returns {"score": 1-5|None, "moat_type":..., "evidence_quote":...,
    "source":..., "reasoning":..., "pathway_results":[...]} - score None
    means the HARD RULE fires (QUANT_PROXY_ONLY) upstream.

    skip_llm=True deliberately never calls any LLM API (Groq/OpenRouter) -
    for bulk runs that must not touch a shared, rate-limited quota. CRISIL
    text is still fetched/parsed (that's a plain scrape, no API budget
    shared with other features) and stored so a later, LLM-enabled pass can
    score it without re-scraping. The pathway result is NOT_CHECKED (a
    pathway deliberately not attempted this run), distinct from
    NOT_DISCLOSED/SEARCH_INCONCLUSIVE (attempted, found nothing) - per the
    DON'T/DO INSTEAD guardrails, "not run" must never look like "run and
    empty".
    """
    from tools.qualitative_engine import _llm_json

    pathway_results = []
    crisil_text = ""
    if crisil_result and crisil_result.get("result") == "CHECKED":
        crisil_text = crisil_result.get("key_rating_drivers") or ""
        pathway_results.append({
            "pathway_id": "PORTAL-07", "source": "CRISIL Rating Rationale - Key Rating Drivers",
            "result": "CHECKED", "note": f"Rated {crisil_result.get('rating')}, {crisil_result.get('rationale_date')}.",
        })
    else:
        pathway_results.append({
            "pathway_id": "PORTAL-07", "source": "CRISIL Rating Rationale - Key Rating Drivers",
            "result": (crisil_result or {}).get("result", "NOT_DISCLOSED"),
            "note": (crisil_result or {}).get("note", "No CRISIL rationale available."),
        })

    pathway_results.append({
        "pathway_id": "AR-13",
        "source": "Management commentary (MD&A / earnings-call digest proxy)",
        "result": "CHECKED" if concall_digest else "NOT_DISCLOSED",
    })

    if not crisil_text and not concall_digest:
        return {
            "score": None, "moat_type": None, "evidence_quote": "", "source": "none",
            "reasoning": "No CRISIL rating rationale and no management commentary available.",
            "pathway_results": pathway_results,
        }

    if skip_llm:
        for pr in pathway_results:
            if pr["result"] == "CHECKED":
                pr["result"] = "NOT_CHECKED"
                pr["note"] = (pr.get("note", "") + " Source text fetched but not yet scored - "
                              "LLM scoring deliberately skipped this run (no API quota touched).").strip()
        return {
            "score": None, "moat_type": None, "evidence_quote": "", "source": "none",
            "reasoning": "LLM scoring deliberately skipped this run - source text was fetched and is "
                         "available for a later scoring pass.",
            "pathway_results": pathway_results, "llm_skipped": True,
        }

    company = name or symbol
    context = f"COMPANY: {company}\n"
    if crisil_text:
        context += f"\nCRISIL RATING RATIONALE - Key Rating Drivers:\n{crisil_text[:3000]}\n"
    if concall_digest:
        context += f"\nMANAGEMENT COMMENTARY (recent earnings calls):\n{concall_digest[:2000]}\n"

    data, failed = _llm_json(
        symbol, "A.2 qualitative evidence", _QUAL_EVIDENCE_SYSTEM, context,
        max_tokens=350, temperature=0.1,
    )
    if failed:
        return {
            "score": None, "moat_type": None, "evidence_quote": "", "source": "none",
            "reasoning": "Classifier call failed - treat as not-yet-scored, not as 'no evidence found'.",
            "pathway_results": pathway_results, "llm_failed": True,
        }

    return {
        "score": data.get("score"),
        "moat_type": data.get("moat_type"),
        "evidence_quote": data.get("evidence_quote") or "",
        "source": data.get("source") or ("CRISIL rationale" if crisil_text else "management commentary"),
        "reasoning": data.get("reasoning") or "",
        "pathway_results": pathway_results,
    }


def build_moat_rating_breakdown(symbol, name=None, market_cap_cr=None, crisil_result=None,
                                 concall_digest="", skip_llm=False):
    """
    Composes (a)-(h) peer-quintile pillars + (i) qualitative evidence into the
    full Moat Rating Breakdown payload, enforcing the hard rule: composite (j)
    is only computed/shown when (i) is present; otherwise the whole rating is
    flagged QUANT_PROXY_ONLY. skip_llm=True: see score_qualitative_evidence.
    """
    quant = score_quant_pillars(symbol, market_cap_cr=market_cap_cr)
    qual = score_qualitative_evidence(symbol, name=name, crisil_result=crisil_result,
                                       concall_digest=concall_digest, skip_llm=skip_llm)

    pillars = list(quant.get("pillars") or [])
    pillars.append({
        "key": "qualitative_evidence", "label": "Qualitative evidence score",
        "value": qual.get("score"), "percentile": None,
        "score_0_5": qual.get("score"), "is_qualitative": True,
    })

    composite = None
    quant_proxy_only = qual.get("score") is None
    if not quant_proxy_only:
        scored = [p["score_0_5"] for p in pillars if p.get("score_0_5") is not None]
        if scored:
            composite = round(sum(scored) / len(scored), 1)

    return {
        "quant_proxy_only": quant_proxy_only,
        "composite_score": composite,
        "pillars": pillars,
        "peer_set": quant.get("peer_set"),
        "peer_set_status": quant.get("status"),
        "qualitative_evidence": qual,
    }
