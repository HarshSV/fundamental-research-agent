"""
Section A gap-fill: A.1.A/A.1.B (business model clarity sub-points) and
A.5.A/A.5.B, A.6.A/A.6.B (pricing power / margin sustainability
sub-points) - built as independent, deterministic (no-LLM) scorers rather
than thin wrappers around compute_a1_business_model_clarity/
compute_a5_pricing_power/compute_a6_margin_sustainability, because those
three parents call the shared LLM helper (_llm_json), which is disabled
app-wide (see memory: LLM Disabled 2026-08) - reusing them would silently
return nothing. These sub-points' own Excel formulas do not actually
require an LLM: A.1.A/B are segment-revenue-share arithmetic and A.5/A.6's
formulas are text-evidence/quantitative-series based, same pattern as
every other deterministic A.2.x-J.5.x sub-point.
"""
import re
from tools.qualitative_evidence_scoring import score_evidence_tier

_PRICING_POWER_CONFIRMED_RE = re.compile(
    r"(?:price|realisation|realization)\s+(?:increase|hike)\s+of\s+\d+(?:\.\d+)?%.{0,80}"
    r"(?:volume|sales\s+volume)\s+(?:held|grew|increased|stable)",
    re.I,
)
_PRICING_POWER_GENERIC_RE = re.compile(r"pricing\s+power|ability\s+to\s+pass\s+on\s+(?:cost\s+)?(?:increases?|inflation)", re.I)

_PASSTHROUGH_QUANTIFIED_RE = re.compile(
    r"pass(?:ed|-)?\s*(?:on|through)\s+(?:approximately\s+|about\s+)?\d{1,3}(?:\.\d+)?%\s+of\s+(?:the\s+)?(?:cost\s+)?(?:increase|inflation)",
    re.I,
)
_PASSTHROUGH_GENERIC_RE = re.compile(r"pass[- ]through\s+of\s+cost\s+inflation|cost\s+inflation\s+(?:was\s+)?passed\s+on", re.I)

_EXCEPTIONAL_ITEM_SPECIFIC_RE = re.compile(
    r"exceptional\s+item\w*\s+(?:of|comprising|relating\s+to)\s+[\w\s]{3,80}",
    re.I,
)
_EXCEPTIONAL_ITEM_GENERIC_RE = re.compile(r"exceptional\s+items?", re.I)


def classify_single_product_vs_portfolio(segments_pct):
    """A.1.A - Spec formula: 1 segment OR one segment >=90% of revenue =
    Single Product; otherwise = Portfolio/Diversified. Pure arithmetic on
    the already-reconciled segment revenue shares this codebase already
    extracts for A.1/A.3/A.4 (tools.annual_report_financials._fetch_
    segment_revenue_context) - never a guess, never LLM-derived."""
    if not segments_pct:
        return {"classification": None, "dominant_segment_pct": None}
    if len(segments_pct) == 1:
        return {"classification": "Single Product", "dominant_segment_pct": segments_pct[0]["pct"]}
    top = max(segments_pct, key=lambda s: s["pct"])
    if top["pct"] >= 90.0:
        return {"classification": "Single Product", "dominant_segment_pct": top["pct"]}
    return {"classification": "Portfolio/Diversified", "dominant_segment_pct": top["pct"]}


def classify_cyclical_vs_recurring(segments_pct, contract_type):
    """A.1.B - Spec formula: revenue-weighted blend of segment
    classifications; Recurring = subscription/annuity/long-term serviced
    contracts; Cyclical = commodity/order-book/discretionary-spend
    linked. This codebase has no per-segment Ind AS 115 extractor (same
    documented limitation as A.3/A.4's segment-level proxy), so the SAME
    company-wide contract_type classification already computed for A.3
    (tools.revenue_model_scoring.classify_contract_type) is applied to
    every segment for the revenue weighting - a documented best-effort
    proxy, not genuine per-segment differentiation."""
    if contract_type is None:
        return {"classification": None, "blend_note": "No revenue-recognition-timing evidence available to classify."}
    label = "Recurring" if contract_type in ("recurring", "annuity") else "Cyclical" if contract_type == "transactional" else None
    if label is None:
        return {"classification": None, "blend_note": "Mixed/unclassified contract type - cannot assign a single blend label."}
    weight = "single-segment" if not segments_pct or len(segments_pct) < 2 else "SEGMENT_LEVEL_PROXY: same company-wide classification applied to every segment"
    return {"classification": label, "blend_note": weight}


def score_pricing_power_ability(text):
    specific, score = score_evidence_tier(text, _PRICING_POWER_CONFIRMED_RE, _PRICING_POWER_GENERIC_RE, high_score=5, mid_score=3)
    return {"confirmed": specific, "pricing_power_score": score}


def score_cost_passthrough(text):
    if not text:
        return {"pass_through_pct": None}
    m = _PASSTHROUGH_QUANTIFIED_RE.search(text)
    if m:
        pct_match = re.search(r"\d{1,3}(?:\.\d+)?", m.group(0))
        return {"pass_through_pct": float(pct_match.group(0)) if pct_match else None}
    if _PASSTHROUGH_GENERIC_RE.search(text):
        return {"pass_through_pct": None, "generic_disclosure": True}
    return {"pass_through_pct": None}


def score_margin_defensibility(ebitda_margin_series):
    """A.6.A - Spec formula: Margin Volatility = Std Dev of EBITDA Margin
    (5Y) / Mean EBITDA Margin (5Y). Defensible only when volatility is
    low AND margin is flat/rising. Computed directly from the real,
    audited margin series (same series agent/stock_agent.py already
    supplies to compute_a6_margin_sustainability) - no LLM judgment call
    needed for this specific, numeric leg of the formula."""
    if not ebitda_margin_series or len(ebitda_margin_series) < 3:
        return {"margin_volatility": None, "trend": None, "defensible": None}
    values = [r["value"] for r in ebitda_margin_series]
    n = len(values)
    mean = sum(values) / n
    if mean == 0:
        return {"margin_volatility": None, "trend": None, "defensible": None}
    variance = sum((v - mean) ** 2 for v in values) / n
    std_dev = variance ** 0.5
    volatility = abs(std_dev / mean)
    trend_rising_or_flat = values[-1] >= values[0] - 0.5
    defensible = bool(volatility < 0.25 and trend_rising_or_flat)
    return {"margin_volatility": round(volatility, 3), "trend": "flat_or_rising" if trend_rising_or_flat else "declining",
            "defensible": defensible}


def score_exceptional_items(text):
    specific, score = score_evidence_tier(text, _EXCEPTIONAL_ITEM_SPECIFIC_RE, _EXCEPTIONAL_ITEM_GENERIC_RE, high_score=4, mid_score=2)
    return {"item_disclosed": specific, "exceptional_items_score": score}
