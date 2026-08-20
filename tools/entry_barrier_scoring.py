"""
F.2.1 - Threat from new entrants or substitute technologies: entry
barriers. Deterministic (no-LLM) scorer over real Annual Report MD&A /
Industry Structure / Risk Factors text. Generic keyword/regex logic, not
ticker-specific.

Direct inspection of MARUTI, ULTRACEMCO, and CIPLA ARs confirms Indian
issuers almost never explicitly discuss "entry barriers"/"barriers to
entry" in MD&A - it will genuinely be N/A far more often than most
other sub-points built this session. Where real barrier-type language
does appear (e.g. ULTRACEMCO's "capital intensive... cement sector",
"economies of scale"), this counts how many of five distinct, generic
barrier TYPES (regulatory/licensing, capital intensity, distribution,
technology/IP, scale) are explicitly claimed - the same
dimension-counting pattern used for F.1.3 competitor strength - rather
than requiring the literal phrase "entry barrier" itself, which almost
never appears.
"""
import re

_BARRIER_DIMENSIONS = {
    "regulatory_licensing": re.compile(
        r"licen[cs]es?\s+(?:are\s+)?required\s+to\s+(?:operate|manufacture|enter)|"
        r"regulatory\s+approvals?\s+(?:are\s+)?required|"
        r"stringent\s+regulatory\s+requirements?|regulatory\s+barriers?|"
        r"extensive\s+regulatory\s+compliance",
        re.I,
    ),
    "capital_intensity": re.compile(
        r"capital[\s-]intensive\s+(?:industry|business|sector|nature)|"
        r"(?:significant|substantial|large|high)\s+capital\s+(?:investment|expenditure)\s+(?:is\s+)?required|"
        r"high\s+capital\s+requirements?",
        re.I,
    ),
    "distribution": re.compile(
        r"extensive\s+distribution\b|wide(?:st)?\s+distribution\s+network|"
        r"pan[\s-]india\s+(?:network|presence|reach)|deep(?:est)?\s+(?:market\s+)?reach",
        re.I,
    ),
    "technology_ip": re.compile(
        r"proprietary\s+technology|patents?\s+(?:protect|held|granted)|"
        r"technology\s+barrier|high\s+technology\s+intensity|r&d[\s-]intensive",
        re.I,
    ),
    "scale": re.compile(
        r"economies\s+of\s+scale|scale\s+advantage|significant\s+scale\s+(?:is\s+)?required|"
        r"large[\s-]scale\s+operations?\s+(?:are\s+)?(?:required|necessary)",
        re.I,
    ),
}


def score_entry_barriers(text):
    """F.2.1 - Entry Barrier Score (1-5), counted across five real,
    generic barrier dimensions (regulatory/licensing, capital intensity,
    distribution, technology/IP, scale) rather than a fabricated
    all-purpose "entry barrier" phrase this codebase confirmed almost
    never appears verbatim in real Indian AR MD&A text. Returns
    {'barrier_dimensions','entry_barrier_score'} or all-None if none of
    the five dimensions were found (a real, common case)."""
    if not text:
        return {"barrier_dimensions": None, "entry_barrier_score": None}
    found = [dim for dim, pat in _BARRIER_DIMENSIONS.items() if pat.search(text)]
    if not found:
        return {"barrier_dimensions": None, "entry_barrier_score": None}
    score = {1: 2, 2: 3, 3: 4}.get(len(found), 5)
    return {"barrier_dimensions": found, "entry_barrier_score": score}
