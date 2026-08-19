"""
E.4.2, E.4.3 - High or growing receivables with limited disclosure -
revenue recognition risk. Deterministic (no-LLM) scorers over real
Annual Report text. Generic keyword/regex logic, not ticker-specific.

E.4.1 (receivables growth) is NOT here - it's computed directly in
tools/qualitative_engine.py from the same real Trade Receivables
(current, prior) figures already extracted for the Receivables
Turnover ratio (tools.annual_report_financials._get_extracted_financials),
no separate scoring module needed for a single arithmetic formula.
"""
import re

# ---------------------------------------------------------------------------
# E.4.2 - Receivables aging / overdue quality.
# ---------------------------------------------------------------------------

# Ind AS 107's mandated Trade Receivables ageing schedule always ends in
# a "TOTAL (A)" row (or a bare "Total" row when a filer skips the "(A)"
# label) with exactly 7 numbers in order: Not due, <6 months, 6m-1y,
# 1-2y, 2-3y, >3y, Total - confirmed real on HINDUNILVR ("TOTAL (A)
# 2,325 425 115 52 110 66 3,093"). Overdue = every bucket except "Not
# due", i.e. Total - Not-due.
_AGEING_TOTAL_ROW = re.compile(
    r"TOTAL\s*(?:\(A\))?\s*((?:[\d,]+\s+){6}[\d,]+)", re.I,
)


def _to_float(s):
    try:
        return float(s.replace(",", ""))
    except (TypeError, ValueError):
        return None


def score_receivables_ageing(text):
    """E.4.2 - Overdue Concentration = Overdue Receivables / Total
    Trade Receivables x 100, read directly from the Ind AS 107 Trade
    Receivables ageing schedule's own TOTAL row. Returns
    {'not_due_cr','total_cr','overdue_pct','classification'} or
    all-None if no ageing TOTAL row was located (a real gap - not
    every filer's PDF linearizes this table the same way, and very
    small companies sometimes have no ageing note at all)."""
    if not text:
        return {"not_due_cr": None, "total_cr": None, "overdue_pct": None, "classification": None}
    for m in _AGEING_TOTAL_ROW.finditer(text):
        nums = [_to_float(n) for n in m.group(1).split()]
        if any(n is None for n in nums) or len(nums) != 7:
            continue
        not_due, total = nums[0], nums[6]
        if total is None or total <= 0 or not_due is None or not_due > total:
            continue
        overdue = total - not_due
        overdue_pct = round(100 * overdue / total, 2)
        classification = "Low" if overdue_pct < 10 else ("Moderate" if overdue_pct <= 30 else "High")
        return {"not_due_cr": not_due, "total_cr": total, "overdue_pct": overdue_pct, "classification": classification}
    return {"not_due_cr": None, "total_cr": None, "overdue_pct": None, "classification": None}


# ---------------------------------------------------------------------------
# E.4.3 - Revenue-recognition disclosure risk.
# ---------------------------------------------------------------------------

_CONTRACT_ASSETS = re.compile(r"\bcontract assets?\b", re.I)
_UNBILLED_REVENUE = re.compile(r"\bunbilled revenue\b|\bunbilled receivables?\b", re.I)
_VARIABLE_CONSIDERATION = re.compile(r"\bvariable consideration\b", re.I)
_SIGNIFICANT_JUDGEMENT = re.compile(
    r"significant (?:judgement|judgment|estimates?)\b[^.]{0,80}revenue|"
    r"revenue recognition[^.]{0,80}significant (?:judgement|judgment|estimates?)", re.I,
)


def score_revenue_recognition_risk(text):
    """E.4.3 - Revenue Recognition Risk Score (1-5) based on complexity
    and disclosure clarity: counts how many of the three real Ind AS
    115 complexity indicators (contract assets, unbilled revenue,
    variable consideration) are explicitly named in the Significant
    Accounting Policies text, plus whether the company itself flags
    revenue recognition as requiring significant management judgement/
    estimates (a real, mandated Ind AS 1 disclosure when true). More
    named complexity indicators AND an explicit judgement flag together
    score HIGHEST - not because complexity itself is good, but because
    a company that clearly discloses its own complexity and judgement
    areas carries less residual (undisclosed) risk than one that stays
    silent about it, consistent with this session's established
    "more transparency scores higher" convention. Returns
    {'contract_assets_disclosed','unbilled_revenue_disclosed',
    'variable_consideration_disclosed','judgement_disclosed',
    'risk_score'} or all-None if none of the three indicators appear at
    all (a real, common case for simple, single-performance-obligation
    businesses - e.g. straightforward goods-at-point-of-sale revenue)."""
    if not text:
        return {"contract_assets_disclosed": None, "unbilled_revenue_disclosed": None,
                "variable_consideration_disclosed": None, "judgement_disclosed": None, "risk_score": None}
    contract_assets = bool(_CONTRACT_ASSETS.search(text))
    unbilled_revenue = bool(_UNBILLED_REVENUE.search(text))
    variable_consideration = bool(_VARIABLE_CONSIDERATION.search(text))
    judgement = bool(_SIGNIFICANT_JUDGEMENT.search(text))
    count = sum([contract_assets, unbilled_revenue, variable_consideration])
    if count == 0 and not judgement:
        return {"contract_assets_disclosed": None, "unbilled_revenue_disclosed": None,
                "variable_consideration_disclosed": None, "judgement_disclosed": None, "risk_score": None}
    if count >= 2 and judgement:
        score = 5
    elif count >= 2:
        score = 4
    elif count == 1 and judgement:
        score = 3
    elif count == 1 or judgement:
        score = 2
    else:
        score = 1
    return {
        "contract_assets_disclosed": contract_assets, "unbilled_revenue_disclosed": unbilled_revenue,
        "variable_consideration_disclosed": variable_consideration, "judgement_disclosed": judgement,
        "risk_score": score,
    }
