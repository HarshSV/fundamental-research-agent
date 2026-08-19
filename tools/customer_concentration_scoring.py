"""
E.2.1-E.2.2 - Customer concentration: top customers percentage &
dependency. Deterministic (no-LLM) regex scorers over real Annual
Report text (Ind AS 108 "Information about major customers" note +
MD&A commentary). Generic keyword/regex logic, not ticker-specific.

Ind AS 108 mandates a standard disclosure form across every Indian
filer: either a NEGATIVE statement ("No single customer represents 10%
or more of the Company's/Group's total revenue") when revenue is
genuinely diversified, or a POSITIVE one naming the actual % when a
single customer DOES cross the threshold. Both are real, decision-
useful disclosures - the negative form is not "no data", it's a real
upper-bound fact (<10% concentration), and is handled as such rather
than being discarded as unavailable.
"""
import re

_NUM = r"\d[\d,]*\.?\d*"


def _to_float(s):
    try:
        return float(s.replace(",", ""))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# E.2.1 - Top customer revenue concentration.
# ---------------------------------------------------------------------------

# PDF text extraction commonly renders a possessive apostrophe as a
# curly/smart quote (U+2019 "'") rather than the ASCII "'" - confirmed
# real on TCS's own Annual Report ("Group's total revenue" with a curly
# apostrophe), which silently failed to match a straight-apostrophe-only
# pattern. Accepts either, or none (e.g. "Groups").
_APOS = "['’]?"

# The standard Ind AS 108 NEGATIVE disclosure - "No single customer
# represents/represented 10% or more of ... total revenue" - a real,
# disclosed upper bound (concentration < the stated threshold), not an
# absence of data. Two real word-order variants confirmed across
# filers: "...represents 10% OR MORE of..." (TCS) and "...accounted
# for MORE THAN 10% of..." (WIPRO) - the qualifier can precede or
# follow the number. WIPRO also combines the receivables and revenue
# concentration into one sentence via "or" ("...10% of the accounts
# receivable ... or revenues for the year...") rather than a tight
# "...% of ... revenue" phrase, so this only anchors on the % clause
# and separately confirms "revenue(s)" appears nearby (not necessarily
# immediately adjacent).
_NO_CONCENTRATION_LEAD = re.compile(
    rf"no (?:single|one) customer\s+(?:represents?|represented|account(?:s|ed)?\s+for|contribut(?:es|ing|ed)?)\s+"
    rf"(?:more\s+than\s+)?({_NUM})%(?:\s*or\s*more)?",
    re.I,
)
_REVENUE_WORD = re.compile(r"\brevenues?\b", re.I)
# The standard Ind AS 108 POSITIVE disclosure - an actual customer (or
# "a single customer") crossing the threshold, with the real % stated.
_HAS_CONCENTRATION = re.compile(
    rf"(?:a\s+)?single customer\s+(?:represents?|represented|account(?:s|ed)?\s+for|contribut(?:es|ing|ed)?)\s+({_NUM})%\s+of\s+(?:the\s+)?"
    rf"(?:Company{_APOS}s|Group{_APOS}s|consolidated|standalone)?\s*(?:total\s+)?revenue",
    re.I,
)
# A named-customer form some filers use instead ("Customer X contributed
# Y% of revenue" / "our largest customer accounted for Y% of revenue").
_NAMED_CUSTOMER_PCT = re.compile(
    rf"(?:largest|top|single largest|biggest)\s+customer\s+(?:contributed|accounted\s+for|represented)\s+({_NUM})%",
    re.I,
)
# A "Revenue from top N customers: X%" table figure (confirmed real on
# INFY: "Revenue from top five customers 12.7"). The spec's own formula
# says "Largest Customer(s)" (plural allowed), so a top-5/top-10
# concentration figure is a real, direct answer to this sub-point, not
# a proxy - takes the smallest N disclosed (tightest, most concentrated
# real figure) when multiple are given.
_TOP_N_CUSTOMERS_PCT = re.compile(
    rf"revenue from top\s+(five|ten|\d+)\s+customers\D{{0,15}}({_NUM})",
    re.I,
)


def score_customer_concentration(text):
    """E.2.1 - Top Customer Concentration % = Revenue from Largest
    Customer(s) / Total Revenue x 100 where explicitly disclosed.
    Handles both the standard Ind AS 108 negative form ("no single
    customer represents 10%+") - a real disclosed UPPER BOUND, reported
    as such - and the positive form naming an actual %. Returns
    {'concentration_pct','is_upper_bound','classification'} or all-None
    if neither disclosure form is present (a real, common gap - many
    filers omit this note entirely, especially non-Ind-AS-108-scoped
    smaller companies)."""
    if not text:
        return {"concentration_pct": None, "is_upper_bound": None, "classification": None}
    m = _HAS_CONCENTRATION.search(text) or _NAMED_CUSTOMER_PCT.search(text)
    if m:
        pct = _to_float(m.group(1))
        if pct is None:
            return {"concentration_pct": None, "is_upper_bound": None, "classification": None}
        classification = "Low" if pct < 10 else ("Moderate" if pct <= 25 else "High")
        return {"concentration_pct": pct, "is_upper_bound": False, "classification": classification}
    m = _TOP_N_CUSTOMERS_PCT.search(text)
    if m:
        pct = _to_float(m.group(2))
        if pct is not None:
            classification = "Low" if pct < 10 else ("Moderate" if pct <= 25 else "High")
            return {"concentration_pct": pct, "is_upper_bound": False, "classification": classification, "customer_count": m.group(1)}
    for m in _NO_CONCENTRATION_LEAD.finditer(text):
        window = text[m.end():m.end() + 150]
        if not _REVENUE_WORD.search(window):
            continue
        threshold = _to_float(m.group(1))
        if threshold is None:
            continue
        return {"concentration_pct": threshold, "is_upper_bound": True, "classification": "Low"}
    return {"concentration_pct": None, "is_upper_bound": None, "classification": None}


# ---------------------------------------------------------------------------
# E.2.2 - Customer dependency.
# ---------------------------------------------------------------------------

_DIVERSIFIED_MARKER = re.compile(
    r"diversified customer base|diversified (?:revenue|client) base|customer base is diversified|"
    r"exposure to customers is diversified|no significant customer concentration|"
    r"broad(?:-|\s)based customer|large and diversified customer", re.I,
)
_DEPENDENCY_MARKER = re.compile(
    r"dependent on (?:a )?(?:few|small number of|limited number of|single|one) customer|"
    r"reliance on (?:a )?(?:few|small number of|limited number of|single|one|major) customer|"
    r"concentration of (?:our |its |the )?(?:revenue|business|sales) (?:with|among|in) (?:a )?(?:few|limited|key)? ?customer|"
    r"loss of (?:any of )?(?:our |its |these )?(?:key|major|significant) customer(?:s)? (?:could|would|may) (?:have a )?(?:material|adverse|significant)",
    re.I,
)


def score_customer_dependency(text, concentration_result=None):
    """E.2.2 - Dependency Score (1-5): a diversified, recurring customer
    base (explicit MD&A/risk-factor language, or a real disclosed
    concentration figure) scores higher than reliance on one/few
    customers. Cross-checks E.2.1's own concentration_result first (the
    most concrete real signal) before falling back to MD&A prose
    language. Returns {'dependency_score','basis'} or all-None if
    neither a concentration figure nor explicit dependency/diversification
    language was found."""
    concentration_result = concentration_result or {}
    pct = concentration_result.get("concentration_pct")
    if pct is not None:
        # An upper-bound disclosure ("no single customer represents X%
        # OR MORE") means actual concentration is confirmed strictly
        # BELOW pct - use <= so the threshold value itself (e.g. TCS's
        # disclosed "10%") correctly falls in the good band, not the
        # boundary-excluded one right above it.
        is_upper_bound = concentration_result.get("is_upper_bound")
        if (pct <= 10 if is_upper_bound else pct < 10):
            return {"dependency_score": 5, "basis": "concentration_pct"}
        if (pct <= 25 if is_upper_bound else pct < 25):
            return {"dependency_score": 3, "basis": "concentration_pct"}
        return {"dependency_score": 1, "basis": "concentration_pct"}
    if not text:
        return {"dependency_score": None, "basis": None}
    diversified = bool(_DIVERSIFIED_MARKER.search(text))
    dependent = bool(_DEPENDENCY_MARKER.search(text))
    if dependent and not diversified:
        return {"dependency_score": 2, "basis": "narrative"}
    if diversified and not dependent:
        return {"dependency_score": 4, "basis": "narrative"}
    if diversified and dependent:
        return {"dependency_score": 3, "basis": "narrative"}
    return {"dependency_score": None, "basis": None}
