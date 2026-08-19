"""
E.7.1-E.7.4 - Unusual accounting policies or frequent changes in
accounting estimates. Deterministic (no-LLM) scorers over real Annual
Report Significant Accounting Policies / P&L Notes text. Generic
keyword/regex logic, not ticker-specific.

IMPORTANT DEVIATION FROM SPEC'S SOURCING PATH: E.7.1/E.7.2 ask to
"compare last 5 years" and E.7.3/E.7.4 ask to "compare 5 years" of
XBRL Financial Results. No multi-year Balance-Sheet/P&L history
fetcher exists in this codebase (same confirmed gap as E.4.1/E.5.1),
and Ind AS 8 requires every Annual Report to disclose ANY accounting
policy/estimate change made DURING the current reporting year in that
year's own AR - so this reads the CURRENT year's real disclosure
(what changed this year, not a 5-year retrospective) rather than
fabricate a multi-year series or silently mislabel current-year data
as a 5-year trend.
"""
import re

_NUM = r"\(?-?[\d,]+\.?\d*\)?"


def _to_float(s):
    if s is None:
        return None
    s = s.strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "")
    try:
        v = float(s)
        return -v if neg else v
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# E.7.1 - Accounting policy changes.
# ---------------------------------------------------------------------------

# Ind AS 8 mandates disclosure of any accounting policy change made
# during the year, whether voluntary or from adopting an amended
# standard - confirmed real generic phrasing across filers: "amendments
# to Ind AS N", "retrospective application under Ind AS 8", "applied
# retrospectively". A distinct standard number (N in "Ind AS N")
# de-duplicates repeated mentions of the SAME amendment within one AR.
_POLICY_CHANGE = re.compile(
    r"change(?:s)?\s+in\s+accounting\s+polic(?:y|ies)|"
    r"amendments?\s+to:?\s*(?:[a-z]\.\s*)?ind\s*as\s*(\d+)|"
    r"retrospective application under ind as\s*(\d+)|applied retrospectively",
    re.I,
)
# Real MCA-amendment notes commonly list each affected standard as a
# lettered sub-item ("a. Ind AS 1...", "b. Ind AS 7...", "c. Ind AS 12...")
# under a single shared "notified the following amendments to:" lead-in,
# so only the first letter's standard is caught by the pattern above.
# Confirmed on HINDUNILVR: Ind AS 7/107/12 all follow as separate lettered
# items with no repeated "amendments to" immediately before them. Only
# scanned when the trigger phrase is present somewhere in the same text
# (score_policy_changes checks this before using these matches), so this
# stays scoped to genuine amendment-listing sections, not arbitrary
# lettered lists elsewhere in the report.
_POLICY_CHANGE_TRIGGER = re.compile(r"notified\s+(?:the\s+following\s+)?amendments?\s+to", re.I)
_LETTERED_STANDARD_ITEM = re.compile(r"\b[a-z]\.\s*ind\s*as\s*(\d+)\b", re.I)


def score_policy_changes(text):
    """E.7.1 - Policy Change Count = material policy changes disclosed
    in the CURRENT year's Annual Report (Ind AS 8 mandates disclosure
    of every policy change made during the year - real, current-year
    data, not a fabricated 5-year retrospective this codebase has no
    source for). Counts distinct standard numbers named (or distinct
    change statements when no standard number is given). Returns
    {'policy_change_count'} or all-None if no policy-change/standard-
    amendment language was located (a real, common case - most years,
    most companies adopt no new mandatory amendments with any real
    effect)."""
    if not text:
        return {"policy_change_count": None}
    standards = set()
    generic_count = 0
    for m in _POLICY_CHANGE.finditer(text):
        std = m.group(1) or m.group(2)
        if std:
            standards.add(std)
        else:
            generic_count += 1
    if _POLICY_CHANGE_TRIGGER.search(text):
        for m in _LETTERED_STANDARD_ITEM.finditer(text):
            standards.add(m.group(1))
    count = len(standards) + (1 if generic_count else 0)
    if count == 0:
        return {"policy_change_count": None}
    return {"policy_change_count": count}


# ---------------------------------------------------------------------------
# E.7.2 - Changes in accounting estimates.
# ---------------------------------------------------------------------------

_ESTIMATE_CHANGE = re.compile(
    r"change\s+in\s+accounting\s+estimate|"
    r"revis(?:ed|ion)\s+(?:its|the|of)\s+(?:estimate|useful life)|"
    r"reassess(?:ed|ment)\s+(?:of\s+)?(?:the\s+)?(?:useful life|estimate)|"
    r"changed\s+its\s+estimate", re.I,
)
_ESTIMATE_EXPLAINED = re.compile(
    r"(?:due to|on account of|as a result of|reflecting)\s+[a-z]", re.I,
)


def score_estimate_changes(text):
    """E.7.2 - Estimate Change Score (1-5) based on frequency,
    magnitude and explanation. Deterministic (no LLM) - counts real
    "change in accounting estimate"/useful-life-revision statements in
    the CURRENT year's Annual Report (same real, current-year-only
    scope as E.7.1 - Ind AS 8 estimate changes are applied
    prospectively and disclosed in the year they're made). A single,
    well-explained estimate change (a real, normal part of running a
    business - e.g. a useful-life revision with a stated reason) scores
    higher than multiple, unexplained ones. Returns
    {'estimate_change_count','explained_count','estimate_change_score'}
    or all-None if no estimate-change language was located (a real,
    common case)."""
    if not text:
        return {"estimate_change_count": None, "explained_count": None, "estimate_change_score": None}
    matches = list(_ESTIMATE_CHANGE.finditer(text))
    if not matches:
        return {"estimate_change_count": None, "explained_count": None, "estimate_change_score": None}
    explained = 0
    for m in matches:
        window = text[m.end():m.end() + 150]
        if _ESTIMATE_EXPLAINED.search(window):
            explained += 1
    count = len(matches)
    if count <= 1 and explained == count:
        score = 5
    elif count <= 1:
        score = 4
    elif explained == count:
        score = 3
    elif explained > 0:
        score = 2
    else:
        score = 1
    return {"estimate_change_count": count, "explained_count": explained, "estimate_change_score": score}


# ---------------------------------------------------------------------------
# E.7.3 - One-off adjustments / special items.
# ---------------------------------------------------------------------------

# The standard Ind AS P&L "Exceptional items" line, immediately
# followed by the current and prior year's real figures (a zero/absent
# prior-year value is shown as "-", confirmed real on SUZLON's "32.
# Exceptional items ... (70.00) -"). Anchoring on this exact P&L
# summary-line label (not e.g. a segment-wise or ratio-note mention of
# the same phrase) keeps this to the real headline figure. Explicitly
# excludes every real qualifier-word variant confirmed on real filers
# that also literally contains the substring "exceptional items" but
# is actually a DIFFERENT, larger subtotal figure (profit computed
# with exceptional items excluded, not the exceptional-items amount
# itself): HINDUNILVR's "Profit BEFORE exceptional items 13,874
# 13,849" and TCS's "Shareholders of the Company - EXCLUDING
# exceptional items 52,391 48,057" both matched a naive search first,
# since the real qualifier phrase happens to appear earlier in the
# extracted text than the real "Exceptional items [net credit] ..."
# line itself.
_EXCEPTIONAL_QUALIFIER_LOOKBEHIND = r"(?<!before )(?<!excluding )(?<!net of )(?<!after )(?<!less )"
_EXCEPTIONAL_ITEMS_ROW = re.compile(
    rf"{_EXCEPTIONAL_QUALIFIER_LOOKBEHIND}Exceptional items?\s*(?:\[[^\]]{{0,20}}\])?\s*(?:\d{{1,3}}\s+)?({_NUM})\s+({_NUM}|-)\b",
    re.I,
)


def score_oneoff_adjustments(text):
    """E.7.3 - Recurring One-off Flag = count of repeated exceptional/
    special items over the review period. Deterministic (no LLM) -
    reads the real Exceptional Items P&L line (current + prior year,
    both real disclosed figures - the CURRENT and immediately PRECEDING
    year, not a fabricated 5-year series this codebase has no quarterly/
    multi-year source for). A NON-ZERO exceptional item appearing in
    BOTH years is itself real evidence it isn't truly "exceptional"/
    one-off - flagged as recurring. Returns
    {'current_exceptional_cr','prior_exceptional_cr','recurring_flag'}
    or all-None if no Exceptional Items P&L line was located (a real,
    common case - many companies report zero exceptional items)."""
    if not text:
        return {"current_exceptional_cr": None, "prior_exceptional_cr": None, "recurring_flag": None}
    m = _EXCEPTIONAL_ITEMS_ROW.search(text)
    if not m:
        return {"current_exceptional_cr": None, "prior_exceptional_cr": None, "recurring_flag": None}
    current = _to_float(m.group(1))
    prior = _to_float(m.group(2)) if m.group(2) != "-" else 0.0
    if current is None:
        return {"current_exceptional_cr": None, "prior_exceptional_cr": None, "recurring_flag": None}
    recurring = bool(current != 0 and prior not in (None, 0))
    return {"current_exceptional_cr": current, "prior_exceptional_cr": prior, "recurring_flag": recurring}


# ---------------------------------------------------------------------------
# E.7.4 - Earnings smoothing signals.
# ---------------------------------------------------------------------------

def score_earnings_smoothing(oneoff_result, current_pbt_cr=None):
    """E.7.4 - Smoothing Risk Score (1-5) based on repeated adjustments
    that materially change reported earnings. Deterministic (no LLM) -
    combines E.7.3's real recurring-exceptional-item flag with the
    exceptional item's real magnitude relative to Profit Before Tax (a
    recurring exceptional item that's also large relative to PBT is a
    real, meaningful smoothing signal; a recurring but small one is a
    much weaker signal; a genuinely one-off, non-recurring item -
    regardless of size - isn't a smoothing signal at all). Returns
    {'exceptional_pct_of_pbt','smoothing_risk_score'} or all-None if
    E.7.3 itself found nothing (a real, common case)."""
    if not oneoff_result or oneoff_result.get("current_exceptional_cr") is None:
        return {"exceptional_pct_of_pbt": None, "smoothing_risk_score": None}
    current = oneoff_result["current_exceptional_cr"]
    recurring = oneoff_result.get("recurring_flag")
    pct = None
    if current_pbt_cr:
        pct = round(100 * abs(current) / current_pbt_cr, 1)
    if not recurring:
        score = 5
    elif pct is None:
        score = 3
    elif pct >= 15:
        score = 1
    elif pct >= 5:
        score = 2
    else:
        score = 3
    return {"exceptional_pct_of_pbt": pct, "smoothing_risk_score": score}
