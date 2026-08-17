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
# C.3.1 - Frequency of RPTs (distinct Ind AS 24 transaction-type count).
# ---------------------------------------------------------------------------

# Canonical Ind AS 24 transaction-type labels - the standard categories every
# Indian filer's Related Party Disclosures note is built from (generic
# vocabulary, not any one company's specific wording, per CLAUDE.md). Counting
# how many DISTINCT types a company discloses is a real, deterministic proxy
# for RPT frequency/breadth, without needing per-row counterparty attribution
# (which score_pricing_fairness's sibling sub-point, C.3.2, still needs an
# LLM extraction pass for).
_RPT_TRANSACTION_TYPES = [
    "purchase of goods", "sale of goods", "rendering of services", "receiving of services",
    "interest paid", "interest received", "interest income", "interest expense",
    "short-term employee benefits", "post-employment benefits", "share-based payments",
    "commission paid", "commission received", "rent paid", "rent received", "rent expense", "rent income",
    "dividend paid", "dividend received", "loans given", "loans taken", "loans granted", "loans availed",
    "investments made", "investments sold", "guarantee",
    "reimbursement of expenses", "sale of fixed assets", "purchase of fixed assets",
    "sale of assets", "purchase of assets", "professional fees", "sitting fees",
    "trade receivables", "trade payables", "intellectual property rights",
    "corporate social responsibility", "donation", "managerial remuneration",
]
_RPT_NOTE_HEADING = re.compile(r"related party disclosures?", re.I)


def score_rpt_frequency(rpt_text):
    """Counts how many DISTINCT canonical Ind AS 24 transaction-type labels
    appear in the Related Party Disclosures note text - a real, fully
    deterministic proxy for RPT frequency/breadth (no LLM row-extraction
    needed). Returns {'distinct_transaction_types','matched_types',
    'frequency_bucket','frequency_score'} or all-None if the Related
    Party Disclosures note itself can't be confirmed present in the text."""
    if not rpt_text or not _RPT_NOTE_HEADING.search(rpt_text):
        return {"distinct_transaction_types": None, "matched_types": None, "frequency_bucket": None, "frequency_score": None}
    lowered = rpt_text.lower()
    matched = [t for t in _RPT_TRANSACTION_TYPES if t in lowered]
    n = len(matched)
    if n == 0:
        return {"distinct_transaction_types": None, "matched_types": None, "frequency_bucket": None, "frequency_score": None}
    if n <= 3:
        bucket, score = "Limited", 5
    elif n <= 6:
        bucket, score = "Frequent", 4
    elif n <= 10:
        bucket, score = "Frequent", 3
    elif n <= 15:
        bucket, score = "Frequent", 2
    else:
        bucket, score = "Frequent", 1
    return {"distinct_transaction_types": n, "matched_types": matched, "frequency_bucket": bucket, "frequency_score": score}


# ---------------------------------------------------------------------------
# C.3.2 - Counterparty identity (promoter-group vs independent categories).
# ---------------------------------------------------------------------------

# Standard Ind AS 24 counterparty-CATEGORY labels (generic vocabulary every
# Indian filer's RPT note is built from - a company's OWN promoter/holding
# entity and its management vs its own controlled/joint entities and
# employee-benefit trusts). Classifying which category LABELS a company
# discloses (not itemized individual counterparty names, which still needs
# the LLM row extraction in _compute_c3_rpt_records) is a real, deterministic
# proxy for C.3.2.
_PROMOTER_ADJACENT_CATEGORY = re.compile(
    r"holding company|key management personnel|\bkmp\b|senior management(?:\s+remuneration)?|"
    r"non-executive directors?(?:\s+remuneration)?|entity in which director|relative of (?:a )?director|"
    r"enterprise (?:controlled|significantly influenced) by", re.I
)
_INDEPENDENT_CATEGORY = re.compile(
    r"\bsubsidiar(?:y|ies)\b|\bassociate\b|joint venture|fellow subsidiar|"
    r"post[- ]employment benefit|provident fund|superannuation fund|gratuity fund|retirement benefit trust", re.I
)
_RPT_NOTE_BLOCK = re.compile(r"(?:note\s+\d+\s+)?related party disclosures?", re.I)


def _isolate_rpt_note_blocks(text, block_chars=4000, max_blocks=3):
    """Related Party Disclosures notes are usually one distinct section
    (sometimes two - standalone + consolidated). Scanning only the text
    starting at each such heading (rather than the whole multi-page AR
    excerpt blob, which also carries unrelated Corporate Governance/Audit
    Committee prose that legitimately uses words like "subsidiary" or
    "director" elsewhere) avoids false-positive category matches."""
    if not text:
        return ""
    blocks = []
    for m in list(_RPT_NOTE_BLOCK.finditer(text))[:max_blocks]:
        blocks.append(text[m.start():m.start() + block_chars])
    return " ".join(blocks) if blocks else text


def score_counterparty_identity(rpt_text):
    """Counts DISTINCT promoter-group-adjacent vs independent Ind AS 24
    counterparty-category labels disclosed in the Related Party
    Disclosures note (isolated to the note's own section, not the whole
    AR excerpt blob). Returns {'promoter_group_count',
    'independent_count','counterparty_risk_pct',
    'counterparty_risk_score'} or all-None if neither category signal
    appears."""
    block = _isolate_rpt_note_blocks(rpt_text)
    if not block:
        return {"promoter_group_count": None, "independent_count": None, "counterparty_risk_pct": None, "counterparty_risk_score": None}
    promoter_matches = set(m.group(0).lower() for m in _PROMOTER_ADJACENT_CATEGORY.finditer(block))
    independent_matches = set(m.group(0).lower() for m in _INDEPENDENT_CATEGORY.finditer(block))
    promoter_group = len(promoter_matches)
    independent = len(independent_matches)
    total = promoter_group + independent
    if total == 0:
        return {"promoter_group_count": None, "independent_count": None, "counterparty_risk_pct": None, "counterparty_risk_score": None}
    pct_independent = round(100 * independent / total, 1)
    return {
        "promoter_group_count": promoter_group, "independent_count": independent,
        "counterparty_risk_pct": pct_independent, "counterparty_risk_score": _band_score_pct(pct_independent),
    }


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
