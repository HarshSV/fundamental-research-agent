"""
E.1.1, E.1.3 - Unexpected related-party payments to opaque vendors or
consultants. Deterministic (no-LLM) regex scorers over the same real
Related Party Disclosures note text already fetched for C.3/D.5
(tools.annual_report_financials.fetch_rpt_evidence_from_annual_report).
Generic Ind AS 24 vocabulary, not ticker-specific.

Distinct from C.3 (general RPT disclosure quality): E.1 is scoped to
the "business integrity / leakage" question - is there a NAMED
counterparty receiving a real payment, and is that payment's rationale
(commercial purpose, arm's-length pricing, Audit Committee approval)
actually documented, or just a bare disclosed amount with no
justification. Reuses tools.rpt_disclosure_scoring's sentence-splitting
and arm's-length/Audit-Committee-approval regexes rather than
duplicating them.
"""
import re

from tools.rpt_disclosure_scoring import (
    _sentences, _band_score_pct, _ARMS_LENGTH_CONFIRMED, _NON_ARMS_LENGTH,
    _TRANSPARENT_MARKER, _OPAQUE_MARKER,
)

# ---------------------------------------------------------------------------
# E.1.1 - Related-party payment frequency.
# ---------------------------------------------------------------------------

# A named counterparty (capitalized multi-word entity, ending in a common
# Indian corporate suffix or a person's name pattern) immediately followed
# within a short window by a real transaction amount - a real, material,
# individually-identifiable counterparty, not just a category label (that's
# C.3.2's job). Deliberately requires the corporate-suffix anchor so a
# random capitalized phrase (a heading, a policy name) isn't miscounted.
_NAMED_COUNTERPARTY = re.compile(
    r"\b([A-Z][A-Za-z&.\-]+(?:\s+[A-Z][A-Za-z&.\-]+){0,4}\s+"
    r"(?:Private\s+)?(?:Limited|Ltd\.?|LLP|Inc\.?|Corporation|Corp\.?))\b"
)
_HAS_AMOUNT_NEAR = re.compile(r"[\d,]+\.\d+|\d{2,}%|₹\s*[\d,]+", re.I)
_RECURRING_MARKER = re.compile(
    r"\brecurring\b|\bcontinuing\b|\bongoing\b|\bannual(?:ly)?\b|\bevery year\b|"
    r"\bregular(?:ly)?\b|\bin the ordinary course\b", re.I,
)


def score_payment_frequency(rpt_text):
    """E.1.1 - Frequency Score (1-5) based on the recurring nature and
    number of MATERIAL (named, amount-attached) counterparties disclosed
    in the Related Party Disclosures note - not category labels (C.3.2),
    individually named ones. Mirrors C.3.1's scoring direction: MORE
    distinct named counterparties with real payments is a larger
    "leakage" surface, so it scores LOWER, not higher; a recurring/
    ongoing-nature disclosure alongside them lowers it one band further
    (a one-off payment is less of a red flag than a standing arrangement).
    Returns {'material_counterparty_count','recurring_disclosed',
    'frequency_score'} or all-None if no named, amount-attached
    counterparty was found at all."""
    if not rpt_text:
        return {"material_counterparty_count": None, "recurring_disclosed": None, "frequency_score": None}
    names = set()
    for m in _NAMED_COUNTERPARTY.finditer(rpt_text):
        window = rpt_text[m.end():m.end() + 120]
        if _HAS_AMOUNT_NEAR.search(window):
            names.add(m.group(1).strip())
    if not names:
        return {"material_counterparty_count": None, "recurring_disclosed": None, "frequency_score": None}
    n = len(names)
    recurring = bool(_RECURRING_MARKER.search(rpt_text))
    if n <= 3:
        score = 5
    elif n <= 6:
        score = 4
    elif n <= 10:
        score = 3
    elif n <= 15:
        score = 2
    else:
        score = 1
    if recurring and score > 1:
        score -= 1
    return {"material_counterparty_count": n, "recurring_disclosed": recurring, "frequency_score": score}


# ---------------------------------------------------------------------------
# E.1.3 - Payment rationale / arm's-length basis.
# ---------------------------------------------------------------------------

def score_payment_rationale(rpt_text):
    """E.1.3 - Rationale Score (1-5): a documented commercial purpose,
    arm's-length pricing basis, AND Audit Committee approval together
    score highest; any one alone scores mid; an explicit statement of
    NON-arm's-length pricing or a documented approval gap (reusing
    tools.rpt_disclosure_scoring's own opaque-marker regex) scores
    lowest. Returns {'arms_length_confirmed','audit_committee_approved',
    'opaque_flag','rationale_score'} or all-None if none of these
    signals appear at all (most RPT notes don't restate pricing basis
    or approval process in prose for every line item - a real gap, not
    a bug)."""
    if not rpt_text:
        return {"arms_length_confirmed": None, "audit_committee_approved": None, "opaque_flag": None, "rationale_score": None}
    arms_length = non_arms = approved = opaque = 0
    for sent in _sentences(rpt_text):
        if _NON_ARMS_LENGTH.search(sent):
            non_arms += 1
        elif _ARMS_LENGTH_CONFIRMED.search(sent):
            arms_length += 1
        if _OPAQUE_MARKER.search(sent):
            opaque += 1
        elif _TRANSPARENT_MARKER.search(sent):
            approved += 1
    if not (arms_length or non_arms or approved or opaque):
        return {"arms_length_confirmed": None, "audit_committee_approved": None, "opaque_flag": None, "rationale_score": None}
    arms_length_confirmed = arms_length > 0 and non_arms == 0
    audit_committee_approved = approved > 0
    opaque_flag = non_arms > 0 or opaque > 0
    if opaque_flag:
        score = 1
    elif arms_length_confirmed and audit_committee_approved:
        score = 5
    elif arms_length_confirmed or audit_committee_approved:
        score = 3
    else:
        score = 2
    return {
        "arms_length_confirmed": arms_length_confirmed, "audit_committee_approved": audit_committee_approved,
        "opaque_flag": opaque_flag, "rationale_score": score,
    }
