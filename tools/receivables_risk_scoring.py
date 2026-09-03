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
# label) whose LAST number is the grand total - confirmed real on
# HINDUNILVR's simple single-column shape ("TOTAL (A) 2,325 425 115 52
# 110 66 3,093", 7 numbers: Not due, <6mo, 6m-1y, 1-2y, 2-3y, >3y, Total).
# A separate, EQUALLY common Ind AS 107 shape splits each ageing bucket
# further into (Undisputed-good, Undisputed-doubtful, Disputed-good,
# Disputed-doubtful) sub-columns - confirmed real on Prime Fresh Limited
# ("Total 8,605.31 177.24 - 136.82 8,919.36", 5 numbers: 4 category
# sub-totals + grand total) - a fixed "exactly 7 numbers" requirement
# silently rejected this equally valid, Ind-AS-mandated table shape.
# Generalized to accept ANY row ending in "Total <n1> <n2> ... <nK>" and
# always take the LAST number as the grand total, regardless of K.
_AGEING_TOTAL_ROW = re.compile(
    r"\bTOTAL\s*(?:\(A\))?\s*((?:[\d,]+(?:\.\d+)?|-)(?:\s+(?:[\d,]+(?:\.\d+)?|-)){1,7})", re.I,
)
# The "Not Due" bucket is its own labeled row (not positionally fixed,
# since the total row's column count now varies) - its own last number is
# that bucket's total, matching the same convention as the Total row.
_NOT_DUE_ROW = re.compile(
    r"\bNot\s+Due\s*((?:[\d,]+(?:\.\d+)?|-)(?:\s+(?:[\d,]+(?:\.\d+)?|-)){0,7})", re.I,
)


def _to_float(s):
    try:
        if s == "-":
            return 0.0
        return float(s.replace(",", ""))
    except (TypeError, ValueError):
        return None


# Schedule III (Companies Act 2013) lets a filer state figures "in Lakhs"
# OR "in Crores" - purely a presentation choice, unrelated to company
# size or sector, so this cannot be assumed one way or the other for any
# given filer. This KPI's fields are named '..._cr' (crores) by
# convention; a filer using Lakhs would otherwise have its real number
# silently mislabeled 100x too large (confirmed real on Prime Fresh
# Limited, whose ageing note is captioned "(Amount in Lakhs)").
_LAKHS_UNIT_RE = re.compile(r"amount\s+in\s+lakh|(?:rs\.?|inr|₹)\s*(?:in\s*)?lakh", re.I)


def _lakhs_to_cr_divisor(text):
    return 100.0 if _LAKHS_UNIT_RE.search(text or "") else 1.0


# Some of this KPI's own anchors ("ageing schedule", "not due") are
# generic enough to also match an UNRELATED ageing table on the same
# Annual Report (e.g. Property/Plant & Equipment or Intangible Assets
# ageing schedules use the identical "Ageing Schedule"/bucket-label
# convention) - confirmed real risk on Prime Fresh Limited, whose PPE/
# CWIP ageing schedule sits in the same excerpt set. Scoped explicitly to
# a window STARTING at a receivables-specific phrase, so a same-document,
# differently-themed ageing table's own Total row is never mistaken for
# the receivables one.
_RECEIVABLES_CONTEXT_RE = re.compile(
    r"(?:ageing of trade receivable|trade receivables? ageing|ageing (?:for|of) trade receivable)", re.I,
)


def score_receivables_ageing(text):
    """E.4.2 - Overdue Concentration = Overdue Receivables / Total
    Trade Receivables x 100, read directly from the Ind AS 107 Trade
    Receivables ageing schedule's own TOTAL row (and, when present, its
    own "Not Due" row - see the module comment for why both are now
    parsed generically rather than assuming one fixed column count).
    Returns {'not_due_cr','total_cr','overdue_pct','classification'} or
    all-None if no ageing TOTAL row was located (a real gap - not every
    filer's PDF linearizes this table the same way, and very small
    companies sometimes have no ageing note at all). A schedule with NO
    "Not Due" row at all (confirmed real, not a parsing failure - some
    filers' current-year table starts directly at "Less than 6 months")
    is read as not_due=0, i.e. the schedule's own buckets already
    account for the full total, which is what the numbers themselves
    show (Total of all shown buckets == the grand Total figure). When
    the Total row is the classic 7-number shape, its own first number
    IS the Not Due bucket (see inline comment) - no separate row needed."""
    if not text:
        return {"not_due_cr": None, "total_cr": None, "overdue_pct": None, "classification": None}
    # Only search AFTER the first receivables-specific ageing caption -
    # never the whole excerpt blob, which can contain an unrelated
    # ageing table's own Total row (see module comment).
    ctx = _RECEIVABLES_CONTEXT_RE.search(text)
    if not ctx:
        return {"not_due_cr": None, "total_cr": None, "overdue_pct": None, "classification": None}
    window = text[ctx.end():ctx.end() + 1500]

    total = None
    not_due = 0.0
    for m in re.finditer(_AGEING_TOTAL_ROW, window):
        nums = [_to_float(n) for n in m.group(1).split()]
        if any(n is None for n in nums) or not nums:
            continue
        candidate = nums[-1]
        if candidate and candidate > 0:
            total = candidate
            # Classic Ind AS 107 single-column shape: the Total row
            # itself is (Not due, <6mo, 6m-1y, 1-2y, 2-3y, >3y, Total) -
            # 7 numbers - so its OWN first number is the Not Due bucket,
            # not a separately labeled row (confirmed real on AARTIIND:
            # no standalone "Not Due" row exists, "Not Due" is only a
            # column header, so leaving not_due at the 0.0 default
            # silently forced every such company to a false 100% overdue
            # reading). The 4-sub-column shape (Prime Fresh) never
            # produces exactly 7 numbers here, so this is unambiguous.
            if len(nums) == 7:
                not_due = nums[0]
            break
    if total is None:
        return {"not_due_cr": None, "total_cr": None, "overdue_pct": None, "classification": None}

    m2 = _NOT_DUE_ROW.search(window)
    if m2 and m2.group(1).strip():
        nd_nums = [_to_float(n) for n in m2.group(1).split()]
        if nd_nums and all(n is not None for n in nd_nums):
            not_due = nd_nums[-1]

    if not_due > total:
        return {"not_due_cr": None, "total_cr": None, "overdue_pct": None, "classification": None}
    overdue = total - not_due
    overdue_pct = round(100 * overdue / total, 2)
    classification = "Low" if overdue_pct < 10 else ("Moderate" if overdue_pct <= 30 else "High")
    # Unit caption (e.g. "(Amount in Lakhs)") sits in the page header,
    # ahead of the ageing caption itself - widen the lookback to catch it.
    divisor = _lakhs_to_cr_divisor(text[max(0, ctx.start() - 400):ctx.end() + 1500])
    total, not_due = total / divisor, not_due / divisor
    return {"not_due_cr": not_due, "total_cr": total, "overdue_pct": overdue_pct, "classification": classification}


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
