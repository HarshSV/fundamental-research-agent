"""
C.7.1-C.7.5 - Capital allocation decisions. Deterministic (no-LLM) regex/
structural scorers over real Annual Report text (MD&A capex commentary,
Board's Report acquisition/divestment notes, Cash Flow Statement's
financing-activities table) and the already-real multi-year cash-flow
mix (tools.qualitative_engine's compute_c7_capital_allocation /
tools.annual_report_financials.fetch_multi_year_cash_flow_items). Generic
keyword sets, not ticker-specific.
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
# C.7.1 - Capital expenditure (Growth vs Maintenance/Other).
# ---------------------------------------------------------------------------

_CAPEX_KEYWORD = re.compile(r"capital expenditure|\bcapex\b", re.I)
_GROWTH_CAPEX_MARKER = re.compile(
    r"expand(?:ing|s|ed)? capacity|build(?:ing)? infrastructure|greenfield|brownfield|"
    r"de-bottleneck|new (?:factory|factories|plant|facility|manufacturing)|"
    r"capacity addition|new capacity", re.I
)
_MAINTENANCE_CAPEX_MARKER = re.compile(
    r"maintenance capex|replacement of (?:assets|equipment|machinery)|upkeep|"
    r"repair(?:s)? and maintenance|routine maintenance", re.I
)


def score_capex_type(capex_text):
    """A capex-keyword sentence is "Growth" if it names expansion/new-
    capacity language, "Maintenance/Other" if it names replacement/
    upkeep language. Returns {'growth_count','maintenance_count',
    'growth_pct','capex_execution_score'} or all-None if no capex-
    keyword sentence carries either signal."""
    if not capex_text:
        return {"growth_count": None, "maintenance_count": None, "growth_pct": None, "capex_execution_score": None}
    growth = maintenance = 0
    for sent in _sentences(capex_text):
        if not _CAPEX_KEYWORD.search(sent) and not _GROWTH_CAPEX_MARKER.search(sent) and not _MAINTENANCE_CAPEX_MARKER.search(sent):
            continue
        if _GROWTH_CAPEX_MARKER.search(sent):
            growth += 1
        elif _MAINTENANCE_CAPEX_MARKER.search(sent):
            maintenance += 1
    total = growth + maintenance
    if total == 0:
        return {"growth_count": None, "maintenance_count": None, "growth_pct": None, "capex_execution_score": None}
    pct = round(100 * growth / total, 1)
    return {"growth_count": growth, "maintenance_count": maintenance, "growth_pct": pct, "capex_execution_score": _band_score_pct(pct)}


# ---------------------------------------------------------------------------
# C.7.2 - Acquisitions (Strategic vs Non-core/Related-party).
# ---------------------------------------------------------------------------

_ACQUISITION_KEYWORD = re.compile(r"\bacquisition\b|\bacquired\b|business combination", re.I)
_STRATEGIC_MARKER = re.compile(
    r"strategic fit|strengthen(?:s|ing)? (?:our |the )?(?:presence|portfolio|position)|"
    r"complementary|synerg|expand(?:s|ing)? (?:our |the )?presence|"
    r"in line with (?:our |the )?strategy|growth (?:journey|segment|category)", re.I
)
_NONCORE_RP_MARKER = re.compile(
    r"related party|promoter group|non-core|divestment|ceased to be a (?:subsidiary|joint venture)", re.I
)


def score_acquisition_discipline(acquisition_text):
    """An acquisition-keyword sentence is "Strategic" if it names
    strategic-fit/synergy/portfolio language, "Non-core/Related-party"
    if it names a related-party or divestment/non-core signal. Returns
    {'strategic_count','noncore_count','strategic_pct',
    'acquisition_discipline_score'} or all-None if no acquisition-
    keyword sentence carries either signal."""
    if not acquisition_text:
        return {"strategic_count": None, "noncore_count": None, "strategic_pct": None, "acquisition_discipline_score": None}
    strategic = noncore = 0
    for sent in _sentences(acquisition_text):
        if not _ACQUISITION_KEYWORD.search(sent):
            continue
        if _NONCORE_RP_MARKER.search(sent):
            noncore += 1
        elif _STRATEGIC_MARKER.search(sent):
            strategic += 1
    total = strategic + noncore
    if total == 0:
        return {"strategic_count": None, "noncore_count": None, "strategic_pct": None, "acquisition_discipline_score": None}
    pct = round(100 * strategic / total, 1)
    return {"strategic_count": strategic, "noncore_count": noncore, "strategic_pct": pct, "acquisition_discipline_score": _band_score_pct(pct)}


# ---------------------------------------------------------------------------
# C.7.5 - Capital allocation rationale (debt-repayment extraction).
# ---------------------------------------------------------------------------

_DEBT_REPAYMENT_TABLE = re.compile(
    r"repayment of (?:long-?term )?borrowings\s*\n\s*\(?([\d,]+(?:\.\d+)?)\)?", re.I
)


def extract_debt_repayment_cr(cash_flow_text):
    """The Cash Flow Statement's own "Repayment of borrowings" financing-
    activities line item (table-row format: label then a parenthesised
    outflow figure on the next line, unit stated once in the table's own
    "₹ in crores" header). Returns a float (₹ crore) or None if not
    found."""
    if not cash_flow_text:
        return None
    m = _DEBT_REPAYMENT_TABLE.search(cash_flow_text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except (ValueError, TypeError):
        return None
