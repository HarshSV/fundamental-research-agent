"""
Section I - Supply chain & operations. Deterministic (no-LLM) scorers over
real Annual Report MD&A / Notes / Risk Management text, mirroring the
established dimension/evidence-counting pattern used for F.2.1/G/H
(tools/entry_barrier_scoring.py, tools/channel_distribution_scoring.py,
tools/product_tech_scoring.py) - generic keyword/regex logic, not
ticker-specific, per CLAUDE.md.

I1.2's framework primary source also lists DGFT (https://www.dgft.gov.in/)
as a secondary cross-check for import policy - consistent with every
other cross-check pathway already in this codebase (e.g. A.2's CRISIL
cross-check, C.5.1's Annual-Report cross-check), that pathway is recorded
as NOT_CHECKED rather than actually invoked; scoring is based on the
primary NSE Annual Report source only. This is not a new precedent - it
matches how every existing cross-check source in A-H is already handled.

I1.1 Single-source suppliers, I1.2 Geographic concentration/China exposure,
I1.3 Inventory buffers, I2.2 Capacity vs demand, I2.3 Capital constraints
to scale, I3.1 Price protection clauses, I3.2 Currency clauses,
I4.1 Lead time/throughput, I4.2 Quality defects/warranty claims.
"""
import re

_SINGLESOURCE_DEPENDENCY_RE = re.compile(
    r"single[\s-]source\s+supplier|sole[\s-]source\s+supplier|sole\s+supplier|"
    r"critical\s+supplier\s+dependen|dependent\s+on\s+a\s+(?:single|sole)\s+supplier",
    re.I,
)
_SINGLESOURCE_MITIGATION_RE = re.compile(
    r"dual\s+sourcing|alternate\s+suppliers?|diversif(?:y|ied|ication)\s+(?:of\s+)?suppliers?|"
    r"multiple\s+suppliers?\s+(?:identified|qualified)|backup\s+suppliers?",
    re.I,
)

_GEO_CONCENTRATION_RE = re.compile(
    r"\bchina\b.{0,40}?(?:sourcing|imports?|procurement|dependency|exposure)|"
    r"geographic(?:al)?\s+concentration|single[\s-]country\s+sourcing|import\s+dependen",
    re.I,
)
_GEO_DIVERSIFICATION_RE = re.compile(
    r"diversif(?:y|ied|ication)\s+(?:of\s+)?(?:sourcing|geograph|supply\s+base)|"
    r"alternate\s+(?:geograph|countr|sourcing)|reduce\s+dependence\s+on\s+china|"
    r"china\s*\+\s*1|de-?risk(?:ing)?\s+(?:from\s+)?china",
    re.I,
)

_INVENTORY_BUFFER_QUALITATIVE_RE = re.compile(
    r"safety\s+stock|buffer\s+stock|strategic\s+inventory|inventory\s+(?:buffer|policy)|"
    r"maintain(?:s|ing)?\s+(?:adequate\s+)?inventory",
    re.I,
)
_INVENTORY_BUFFER_QUANTIFIED_RE = re.compile(
    r"(\d{1,3})\s*(?:days?|months?)\s+(?:of\s+)?(?:inventory|stock|safety\s+stock)",
    re.I,
)

_CAPACITY_UTILIZATION_QUANTIFIED_RE = re.compile(
    r"capacity\s+utili[sz]ation\s+(?:of\s+|was\s+|at\s+)?(\d{1,3})\s*%|"
    r"(\d{1,3})\s*%\s+capacity\s+utili[sz]ation",
    re.I,
)
_CAPACITY_QUALITATIVE_RE = re.compile(
    r"order\s+book|capacity\s+expansion|demand\s+outlook|utili[sz]ation\s+rate",
    re.I,
)

_SCALE_PLAN_SPECIFIC_RE = re.compile(
    r"capex\s+(?:plan|of\s+(?:inr|rs\.?|rupees?|₹))|capital\s+expenditure\s+plan|"
    r"expansion\s+(?:plan|project)\s+of|funded\s+through",
    re.I,
)
_SCALE_CONSTRAINT_RE = re.compile(
    r"capital\s+constraint|funding\s+(?:gap|constraint)|limited\s+(?:capital|funding)\s+availability|"
    r"constrained?\s+(?:by\s+)?(?:capital|funding)",
    re.I,
)

_PRICE_PROTECTION_RE = re.compile(
    r"price\s+escalation\s+clause|pass[\s-]through\s+(?:clause|mechanism|arrangement)|"
    r"price\s+protection|cost\s+pass[\s-]through",
    re.I,
)
_FIXED_PRICE_ONLY_RE = re.compile(r"fixed[\s-]price\s+(?:contract|basis|terms)", re.I)

_CURRENCY_HEDGE_RE = re.compile(
    r"forward\s+contracts?|hedg(?:e|ing)\s+(?:policy|instrument|contract)|natural\s+hedge|"
    r"currency\s+(?:swap|option)s?",
    re.I,
)
_CURRENCY_RISK_ONLY_RE = re.compile(r"foreign\s+currency\s+risk|currency\s+fluctuation\s+risk|exchange\s+rate\s+risk", re.I)

_LEADTIME_QUANTIFIED_RE = re.compile(
    r"lead\s+time\s+of\s+(\d{1,3})\s*(?:days?|weeks?)|(\d{1,3})\s*(?:days?|weeks?)\s+lead\s+time",
    re.I,
)
_LEADTIME_QUALITATIVE_RE = re.compile(r"lead\s+time|throughput|production\s+(?:rate|efficiency)|turnaround\s+time", re.I)

_QUALITY_METRIC_QUANTIFIED_RE = re.compile(
    r"warranty\s+(?:provision|claims?)\s+of\s+(?:inr|rs\.?|₹)?\s*[\d,]+|"
    r"defect\s+rate\s+of\s+(\d+(?:\.\d+)?)\s*%",
    re.I,
)
_QUALITY_LANGUAGE_RE = re.compile(r"warranty\s+(?:provision|claims?)|quality\s+defects?|customer\s+complaints?", re.I)


def score_single_source_risk(text):
    """I.1.1 - Single-source suppliers. Disclosed mitigation (dual/
    alternate sourcing) scores highest; disclosed dependency WITHOUT
    mitigation scores lowest (real, evidenced risk); both scores mid;
    neither returns None."""
    if not text:
        return {"dependency_disclosed": None, "mitigation_disclosed": None, "single_source_risk_score": None}
    dep = bool(_SINGLESOURCE_DEPENDENCY_RE.search(text))
    mit = bool(_SINGLESOURCE_MITIGATION_RE.search(text))
    if not dep and not mit:
        return {"dependency_disclosed": None, "mitigation_disclosed": None, "single_source_risk_score": None}
    if dep and mit:
        score = 3
    elif mit:
        score = 5
    else:
        score = 2
    return {"dependency_disclosed": dep, "mitigation_disclosed": mit, "single_source_risk_score": score}


def score_geographic_concentration(text):
    """I.1.2 - Geographic concentration / China exposure. Disclosed
    diversification-away-from-concentration language scores highest;
    disclosed concentration WITHOUT diversification scores lowest;
    both scores mid; neither returns None."""
    if not text:
        return {"concentration_disclosed": None, "diversification_disclosed": None, "geographic_concentration_score": None}
    conc = bool(_GEO_CONCENTRATION_RE.search(text))
    div = bool(_GEO_DIVERSIFICATION_RE.search(text))
    if not conc and not div:
        return {"concentration_disclosed": None, "diversification_disclosed": None, "geographic_concentration_score": None}
    if conc and div:
        score = 3
    elif div:
        score = 5
    else:
        score = 2
    return {"concentration_disclosed": conc, "diversification_disclosed": div, "geographic_concentration_score": score}


def score_inventory_buffers(text):
    """I.1.3 - Inventory buffers. A quantified buffer (e.g. "45 days of
    inventory") scores highest; qualitative buffer-policy language
    without a number scores mid; neither returns None."""
    if not text:
        return {"buffer_quantified": None, "inventory_buffer_score": None}
    if _INVENTORY_BUFFER_QUANTIFIED_RE.search(text):
        return {"buffer_quantified": True, "inventory_buffer_score": 5}
    if _INVENTORY_BUFFER_QUALITATIVE_RE.search(text):
        return {"buffer_quantified": False, "inventory_buffer_score": 3}
    return {"buffer_quantified": None, "inventory_buffer_score": None}


def score_capacity_demand_balance(text):
    """I.2.2 - Capacity vs demand. A quantified utilization % scores
    highest; qualitative order-book/expansion language without a number
    scores mid; neither returns None."""
    if not text:
        return {"utilization_pct": None, "capacity_demand_score": None}
    m = _CAPACITY_UTILIZATION_QUANTIFIED_RE.search(text)
    if m:
        pct = next((g for g in m.groups() if g), None)
        return {"utilization_pct": float(pct) if pct else None, "capacity_demand_score": 5}
    if _CAPACITY_QUALITATIVE_RE.search(text):
        return {"utilization_pct": None, "capacity_demand_score": 3}
    return {"utilization_pct": None, "capacity_demand_score": None}


def score_scale_constraints(text):
    """I.2.3 - Capital constraints to scale. A specific, funded capex/
    expansion plan scores highest (clear scale trajectory); explicit
    capital-constraint language scores lowest; neither returns None."""
    if not text:
        return {"specific_plan_disclosed": None, "constraint_disclosed": None, "scale_constraint_score": None}
    plan = bool(_SCALE_PLAN_SPECIFIC_RE.search(text))
    constraint = bool(_SCALE_CONSTRAINT_RE.search(text))
    if not plan and not constraint:
        return {"specific_plan_disclosed": None, "constraint_disclosed": None, "scale_constraint_score": None}
    if plan and constraint:
        score = 3
    elif plan:
        score = 5
    else:
        score = 2
    return {"specific_plan_disclosed": plan, "constraint_disclosed": constraint, "scale_constraint_score": score}


def score_price_protection(text):
    """I.3.1 - Price protection clauses. Disclosed escalation/pass-
    through clause scores highest; disclosed fixed-price-only terms
    (no protection) scores lowest; neither returns None."""
    if not text:
        return {"protection_clause_disclosed": None, "fixed_price_only_disclosed": None, "price_protection_score": None}
    protect = bool(_PRICE_PROTECTION_RE.search(text))
    fixed = bool(_FIXED_PRICE_ONLY_RE.search(text))
    if not protect and not fixed:
        return {"protection_clause_disclosed": None, "fixed_price_only_disclosed": None, "price_protection_score": None}
    if protect:
        score = 5
    else:
        score = 2
    return {"protection_clause_disclosed": protect, "fixed_price_only_disclosed": fixed, "price_protection_score": score}


def score_currency_protection(text):
    """I.3.2 - Currency clauses. Disclosed hedging (forward contracts/
    natural hedge/swaps) scores highest; mere FX-risk disclosure without
    hedging scores lowest; neither returns None."""
    if not text:
        return {"hedging_disclosed": None, "currency_protection_score": None}
    if _CURRENCY_HEDGE_RE.search(text):
        return {"hedging_disclosed": True, "currency_protection_score": 5}
    if _CURRENCY_RISK_ONLY_RE.search(text):
        return {"hedging_disclosed": False, "currency_protection_score": 2}
    return {"hedging_disclosed": None, "currency_protection_score": None}


def score_operational_efficiency(text):
    """I.4.1 - Lead time / throughput. A quantified lead-time/throughput
    metric scores highest; qualitative mention without a number scores
    mid; neither returns None."""
    if not text:
        return {"metric_quantified": None, "operational_efficiency_score": None}
    if _LEADTIME_QUANTIFIED_RE.search(text):
        return {"metric_quantified": True, "operational_efficiency_score": 5}
    if _LEADTIME_QUALITATIVE_RE.search(text):
        return {"metric_quantified": False, "operational_efficiency_score": 3}
    return {"metric_quantified": None, "operational_efficiency_score": None}


def score_quality_risk(text):
    """I.4.2 - Quality defects / warranty claims. The framework's own
    formula asks for a TREND, which this single-year AR-excerpt scan
    cannot compute (no multi-year comparison is performed here) - this
    scores DISCLOSURE presence/specificity for the CURRENT year only,
    the same single-year evidence-presence convention already used by
    every other AR-text KPI-card sub-point in A-H (e.g. G.3.2's
    retention score). A quantified warranty/defect figure scores
    highest; qualitative mention without a number scores mid; neither
    returns None."""
    if not text:
        return {"metric_quantified": None, "quality_risk_score": None}
    if _QUALITY_METRIC_QUANTIFIED_RE.search(text):
        return {"metric_quantified": True, "quality_risk_score": 4}
    if _QUALITY_LANGUAGE_RE.search(text):
        return {"metric_quantified": False, "quality_risk_score": 3}
    return {"metric_quantified": None, "quality_risk_score": None}
