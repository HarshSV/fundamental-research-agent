"""
C.3.3-C.3.4 - Related-party transactions: pricing fairness and disclosure
quality. Deterministic (no-LLM) regex scorers over real Annual Report text
(the Related Party Disclosures note + Audit Committee Report), same design
as tools/communication_quality_scoring.py / tools/culture_scoring.py.
Generic keyword sets, not ticker-specific.
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
# C.3.3 - Pricing and commercial rationale (arm's-length disclosure).
# ---------------------------------------------------------------------------

_ARMS_LENGTH_CONFIRMED = re.compile(r"\barm'?s[- ]length\b", re.I)
_NON_ARMS_LENGTH = re.compile(
    r"(?:not|other than|were not|was not)\s+(?:conducted\s+|entered\s+into\s+)?(?:at\s+|on\s+)?arm'?s[- ]length", re.I
)


def score_pricing_fairness(rpt_text):
    """Counts sentences in the Related Party Disclosures note that
    explicitly confirm transactions were at arm's length vs sentences
    that explicitly state they were NOT at arm's length (a real,
    reportable disclosure under Ind AS 24 / Companies Act Sec. 188, not
    the common case, but must be checked rather than assumed away).
    Returns {'arms_length_count','non_arms_length_count',
    'pricing_fairness_pct','pricing_fairness_score'} or all-None if
    neither signal appears (most RPT notes don't restate the arm's-length
    determination in prose for every line item - a real gap, not a bug)."""
    if not rpt_text:
        return {"arms_length_count": None, "non_arms_length_count": None, "pricing_fairness_pct": None, "pricing_fairness_score": None}
    confirmed = non_arms = 0
    for sent in _sentences(rpt_text):
        if _NON_ARMS_LENGTH.search(sent):
            non_arms += 1
        elif _ARMS_LENGTH_CONFIRMED.search(sent):
            confirmed += 1
    total = confirmed + non_arms
    if total == 0:
        return {"arms_length_count": None, "non_arms_length_count": None, "pricing_fairness_pct": None, "pricing_fairness_score": None}
    pct = round(100 * confirmed / total, 1)
    return {"arms_length_count": confirmed, "non_arms_length_count": non_arms, "pricing_fairness_pct": pct, "pricing_fairness_score": _band_score_pct(pct)}


# ---------------------------------------------------------------------------
# C.3.4 - Disclosure quality of RPTs (Audit Committee approval process).
# ---------------------------------------------------------------------------

_RPT_APPROVAL_KEYWORD = re.compile(r"audit committee|related party transaction", re.I)
_TRANSPARENT_MARKER = re.compile(
    r"omnibus approval|prior approval of the audit committee|audit committee.{0,60}(?:approv|review)|"
    r"policy on (?:materiality of )?related party transactions|materiality of related party transactions", re.I
)
_OPAQUE_MARKER = re.compile(
    r"no (?:formal |written )?policy|not disclosed|non[- ]compliance with.{0,30}related party|"
    r"delayed approval|approval was not (?:obtained|sought)", re.I
)


def score_disclosure_quality(governance_text):
    """A sentence naming the Audit Committee alongside related-party
    transactions is "Transparent" if it explicitly names an approval
    process (omnibus approval, prior Audit Committee approval, a stated
    RPT materiality policy), "Opaque" if it names a red flag (no policy,
    non-compliance, delayed/missing approval). Returns
    {'transparent_count','opaque_count','disclosure_quality_pct',
    'disclosure_quality_score'} or all-None if no such sentence carries
    either signal."""
    if not governance_text:
        return {"transparent_count": None, "opaque_count": None, "disclosure_quality_pct": None, "disclosure_quality_score": None}
    transparent = opaque = 0
    for sent in _sentences(governance_text):
        if not _RPT_APPROVAL_KEYWORD.search(sent):
            continue
        if _OPAQUE_MARKER.search(sent):
            opaque += 1
        elif _TRANSPARENT_MARKER.search(sent):
            transparent += 1
    total = transparent + opaque
    if total == 0:
        return {"transparent_count": None, "opaque_count": None, "disclosure_quality_pct": None, "disclosure_quality_score": None}
    pct = round(100 * transparent / total, 1)
    return {"transparent_count": transparent, "opaque_count": opaque, "disclosure_quality_pct": pct, "disclosure_quality_score": _band_score_pct(pct)}
