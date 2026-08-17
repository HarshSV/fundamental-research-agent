"""
B.5.1-B.5.3 - Execution credibility: deterministic (no-LLM) scorers.

Same design as tools/communication_quality_scoring.py: regex/keyword
pattern matching against real, multi-year Annual Report text (MD&A / Cash
Flow Statement / Board's Report), no LLM call. Generic across any company -
the keyword sets are general business-strategy/execution vocabulary, never
tuned to one company's specific wording.
"""

import re


def _sentences(text):
    if not text:
        return []
    normalized = re.sub(r"\s+", " ", text.replace("\n", " "))
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", normalized) if s.strip()]


def _band_score_pct(pct):
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


# ---------------------------------------------------------------------------
# B.5.1 - Delivered vs stated milestones (multi-year MD&A).
# ---------------------------------------------------------------------------

_ANNOUNCED_MILESTONE = re.compile(
    r"\bwe (?:plan|propose|intend|aim) to\b|\bis expected to (?:commission|commence|launch|complete)\b|"
    r"\b(?:will|to) be commissioned\b|\bwill commence\b|\btargeted? to (?:be )?(?:complete|commission|launch)\b|"
    r"\bproposes? to (?:set up|establish|commission|expand|invest)\b|"
    r"\bplan(?:s|ned)? to (?:commission|launch|expand|set up|invest)\b", re.I
)
_ACHIEVED_MILESTONE = re.compile(
    r"\bsuccessfully (?:commissioned|completed|launched)\b|\bhas been (?:commissioned|completed|launched)\b|"
    r"\bcommenced commercial (?:production|operations)\b|\bwas (?:commissioned|completed|launched)\b|"
    r"\bcompleted the (?:commissioning|construction|expansion)\b|\bachieved (?:the )?(?:target|milestone)\b|"
    r"\bdelivered (?:the )?(?:project|target|milestone)\b", re.I
)


def score_milestone_execution(years_texts):
    """years_texts: [{'fiscal_year', 'text'}] oldest->newest MD&A text.
    Counts forward-commitment sentences ("we plan to commission...") in
    every year EXCEPT the most recent (its promises can't yet be verified
    within this window) as "announced", and completion-confirmation
    sentences ("was successfully commissioned...") in every year AFTER the
    first as "achieved". Execution Ratio = achieved / announced. Returns
    {'announced_count','achieved_count','pending_count','execution_ratio',
    'execution_ratio_pct','milestone_score'} or all-None if fewer than 2
    years of text or no announced-milestone signal at all."""
    years_texts = [y for y in (years_texts or []) if y.get("text")]
    if len(years_texts) < 2:
        return {"announced_count": None, "achieved_count": None, "pending_count": None,
                "execution_ratio": None, "execution_ratio_pct": None, "milestone_score": None}
    announced = sum(len(_ANNOUNCED_MILESTONE.findall(y["text"])) for y in years_texts[:-1])
    achieved = sum(len(_ACHIEVED_MILESTONE.findall(y["text"])) for y in years_texts[1:])
    if announced == 0:
        return {"announced_count": None, "achieved_count": None, "pending_count": None,
                "execution_ratio": None, "execution_ratio_pct": None, "milestone_score": None}
    ratio = round(achieved / announced, 2)
    pct = round(min(100.0, 100 * ratio), 1)
    return {
        "announced_count": announced, "achieved_count": min(achieved, announced),
        "pending_count": max(0, announced - achieved),
        "execution_ratio": ratio, "execution_ratio_pct": pct,
        "milestone_score": _band_score_pct(pct),
    }


# ---------------------------------------------------------------------------
# B.5.2 - Capital allocation execution (Cash Flow Statement + Board's Report).
# ---------------------------------------------------------------------------

_ACTUAL_CAPEX = re.compile(
    r"(?:purchase of property,?\s*plant and equipment|capital expenditure incurred|"
    r"capex incurred)[^.\d]{0,40}?₹?\s*([\d,]+(?:\.\d+)?)\s*(?:crore|cr\b)", re.I
)
_PLANNED_CAPEX = re.compile(
    r"(?:capital expenditure|capex)[^.]{0,60}?(?:plan(?:ned)?|budget(?:ed)?|propose[ds]?|earmark(?:ed)?|guidance)[^.\d]{0,40}?₹?\s*([\d,]+(?:\.\d+)?)\s*(?:crore|cr\b)|"
    r"plan(?:ned)?\s+(?:capital expenditure|capex)[^.\d]{0,40}?₹?\s*([\d,]+(?:\.\d+)?)\s*(?:crore|cr\b)", re.I
)


def score_capital_execution(cash_flow_text, board_report_text):
    """Extracts an actual capex figure from the Cash Flow Statement and a
    planned/budgeted capex figure from the Board's Report, both explicitly
    stated in ₹ crore. Capital Execution Score bands how close actual came
    to planned (nearer 100% = stronger execution; over-spend is not
    automatically "better" than under-spend). Returns
    {'actual_capex_cr','planned_capex_cr','execution_pct',
    'capital_execution_score'} or all-None if either figure isn't
    explicitly disclosed (planned capex disclosure is genuinely rare -
    this is expected to be N/A for most companies, not a bug)."""
    if not cash_flow_text or not board_report_text:
        return {"actual_capex_cr": None, "planned_capex_cr": None, "execution_pct": None, "capital_execution_score": None}
    am = _ACTUAL_CAPEX.search(cash_flow_text)
    pm = _PLANNED_CAPEX.search(board_report_text)
    if not am or not pm:
        return {"actual_capex_cr": None, "planned_capex_cr": None, "execution_pct": None, "capital_execution_score": None}
    try:
        actual = float(am.group(1).replace(",", ""))
        planned_raw = pm.group(1) or pm.group(2)
        planned = float(planned_raw.replace(",", ""))
    except (ValueError, TypeError):
        return {"actual_capex_cr": None, "planned_capex_cr": None, "execution_pct": None, "capital_execution_score": None}
    if planned <= 0:
        return {"actual_capex_cr": None, "planned_capex_cr": None, "execution_pct": None, "capital_execution_score": None}
    pct = round(100 * actual / planned, 1)
    deviation = abs(100 - pct)
    if deviation <= 10:
        score = 5
    elif deviation <= 25:
        score = 4
    elif deviation <= 50:
        score = 3
    elif deviation <= 75:
        score = 2
    else:
        score = 1
    return {"actual_capex_cr": actual, "planned_capex_cr": planned, "execution_pct": pct, "capital_execution_score": score}


# ---------------------------------------------------------------------------
# B.5.3 - Strategic execution consistency (multi-year MD&A theme overlap).
# ---------------------------------------------------------------------------

_STRATEGY_THEMES = {
    "Digital/Technology": re.compile(r"digitali[sz]ation|digital transformation|technology[- ]led|e-?commerce", re.I),
    "Cost efficiency": re.compile(r"cost efficienc|cost optimi[sz]ation|cost reduction|operational efficiency", re.I),
    "Premiumisation": re.compile(r"premiumi[sz]ation|premium (?:portfolio|segment|products)", re.I),
    "Sustainability/ESG": re.compile(r"sustainab\w+|\bESG\b|carbon neutral|renewable energy", re.I),
    "Innovation/R&D": re.compile(r"\binnovation\b|research and development|new product develop", re.I),
    "Market expansion": re.compile(r"market share|geographic expansion|new markets", re.I),
    "Capacity expansion": re.compile(r"capacity expansion|capacity addition|new (?:plant|facility)", re.I),
    "Rural/Distribution": re.compile(r"rural (?:markets|reach|distribution)|distribution network|direct reach", re.I),
}


def score_strategic_consistency(years_texts):
    """years_texts: [{'fiscal_year', 'text'}] oldest->newest MD&A text.
    Detects which of a fixed set of generic strategic-priority themes each
    year's MD&A mentions, then measures year-over-year overlap (Jaccard
    similarity of theme sets between consecutive years) as a consistency
    signal - a company that keeps reiterating the same strategic
    priorities scores higher than one whose stated focus swings every
    year. Returns {'theme_trend': [{'fiscal_year','theme_count','themes'}],
    'avg_overlap_pct','consistency_score'} or all-None if fewer than 2
    years have any theme match."""
    per_year = []
    for y in (years_texts or []):
        text = y.get("text") or ""
        if not text:
            continue
        themes = {name for name, rx in _STRATEGY_THEMES.items() if rx.search(text)}
        if themes:
            per_year.append({"fiscal_year": y.get("fiscal_year"), "themes": themes})
    if len(per_year) < 2:
        return {"theme_trend": None, "avg_overlap_pct": None, "consistency_score": None}
    overlaps = []
    for i in range(1, len(per_year)):
        a, b = per_year[i - 1]["themes"], per_year[i]["themes"]
        union = a | b
        overlaps.append(len(a & b) / len(union) if union else 0.0)
    avg_overlap_pct = round(100 * sum(overlaps) / len(overlaps), 1)
    theme_trend = [{"fiscal_year": y["fiscal_year"], "theme_count": len(y["themes"]),
                     "themes": sorted(y["themes"])} for y in per_year]
    return {"theme_trend": theme_trend, "avg_overlap_pct": avg_overlap_pct,
            "consistency_score": _band_score_pct(avg_overlap_pct)}
