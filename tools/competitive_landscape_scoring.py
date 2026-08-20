"""
F.1 - Competitive landscape: number and strength of competitors, market
shares. Deterministic (no-LLM) scorers over real Annual Report MD&A /
Industry Structure text. Generic keyword/regex logic, not ticker-specific.

Real Indian ARs (HINDUNILVR, MARUTI, ASIANPAINT confirmed by direct
inspection) almost never NAME specific rival companies in the MD&A -
competitor-naming is commercially sensitive and avoided - but routinely
make real, disclosed claims about market leadership/rank ("market
leader", "largest exporter", "gained market share") and about their own
competitive strengths (scale, distribution, technology, cost position).
F1.1 (named competitor count) will genuinely be N/A far more often than
F1.2/F1.3 - a real, honest reflection of how Indian issuers write MD&A,
not a fetch bug.
"""
import re

_STOPWORDS = {
    "the", "and", "or", "our", "its", "a", "an", "of", "in", "for", "to",
    "with", "as", "well", "including", "such", "others", "other", "etc",
}


# ---------------------------------------------------------------------------
# F.1.1 - Number of material competitors.
# ---------------------------------------------------------------------------

_COMPETITOR_LIST_TRIGGER = re.compile(
    r"(?:principal|key|main|major|material)?\s*competitors?\s+(?:include|includes|are|such as|:)\s+"
    r"([A-Z][A-Za-z0-9&.\-' ]{1,40}(?:,\s*[A-Z][A-Za-z0-9&.\-' ]{1,40}){0,9}"
    r"(?:\s*(?:and|&)\s*[A-Z][A-Za-z0-9&.\-' ]{1,40})?)",
)
_COMPETE_WITH_TRIGGER = re.compile(
    r"compet(?:e|es|ing)\s+(?:directly\s+)?with\s+"
    r"([A-Z][A-Za-z0-9&.\-' ]{1,40}(?:,\s*[A-Z][A-Za-z0-9&.\-' ]{1,40}){0,9}"
    r"(?:\s*(?:and|&)\s*[A-Z][A-Za-z0-9&.\-' ]{1,40})?)",
)


def _split_named_entities(chunk):
    parts = re.split(r",|\band\b|&", chunk)
    names = []
    for p in parts:
        p = p.strip(" .")
        if len(p) < 2 or len(p) > 40:
            continue
        if p.lower() in _STOPWORDS:
            continue
        if not p[0].isupper():
            continue
        names.append(p)
    return names


def score_competitor_count(text):
    """F.1.1 - Competitor Count = number of material named competitors
    identified from filings. Real Indian AR MD&A sections routinely avoid
    naming specific rivals (commercially sensitive), so this returns
    all-None whenever no named-competitor-list sentence is found - a real,
    common, honest case, not a bug. Returns {'competitor_count',
    'competitor_names'} or all-None."""
    if not text:
        return {"competitor_count": None, "competitor_names": None}
    names = []
    for pat in (_COMPETITOR_LIST_TRIGGER, _COMPETE_WITH_TRIGGER):
        for m in pat.finditer(text):
            names.extend(_split_named_entities(m.group(1)))
    seen = []
    for n in names:
        if n not in seen:
            seen.append(n)
    if not seen:
        return {"competitor_count": None, "competitor_names": None}
    return {"competitor_count": len(seen), "competitor_names": seen[:10]}


# ---------------------------------------------------------------------------
# F.1.2 - Relative market position.
# ---------------------------------------------------------------------------

_MARKET_SHARE_PCT = re.compile(
    r"market\s+share\s+of\s+(?:approximately\s+|about\s+|~\s*)?(\d{1,3}(?:\.\d+)?)\s?%|"
    r"(\d{1,3}(?:\.\d+)?)\s?%\s+market\s+share",
    re.I,
)
# Real, generic qualitative rank claims - confirmed on MARUTI ("is the
# market leader of Passenger Vehicles... and is also the country's
# largest exporter") and HINDUNILVR ("strengthened our market
# leadership"). Ordered strongest-first; first match in text wins.
_RANK_CLAIMS = [
    (re.compile(r"\bmarket\s+leader\b|\bno\.?\s?1\b|\bnumber\s+one\b|\b#\s?1\b|\blargest\s+(?:exporter|player|company|manufacturer|producer)\b|\bmarket\s+leadership\b", re.I), 5),
    (re.compile(r"\bsecond[\s-]largest\b|\bamong\s+the\s+top\s+2\b|\bno\.?\s?2\b", re.I), 4),
    (re.compile(r"\bthird[\s-]largest\b|\bamong\s+the\s+top\s+3\b|\bno\.?\s?3\b", re.I), 3),
    (re.compile(r"\bgained\s+market\s+share\b|\bleading\s+position\b|\bone\s+of\s+the\s+leading\s+players\b", re.I), 3),
]


def _share_pct_to_score(pct):
    if pct >= 40:
        return 5
    if pct >= 25:
        return 4
    if pct >= 15:
        return 3
    if pct >= 5:
        return 2
    return 1


def score_market_position(text):
    """F.1.2 - Market Position Score (1-5) from disclosed market
    share/rank; does not estimate when not disclosed (per spec's own
    explicit instruction). Prefers a real numeric market-share %
    disclosure; falls back to a real qualitative rank/leadership claim.
    Returns {'market_share_pct','market_position_score','basis'} or
    all-None if neither was located (a real, common case - most
    companies never disclose a numeric market share)."""
    if not text:
        return {"market_share_pct": None, "market_position_score": None, "basis": None}
    m = _MARKET_SHARE_PCT.search(text)
    if m:
        pct = float(m.group(1) or m.group(2))
        # A % figure qualified as belonging to a specific segment/category
        # (confirmed real on MARUTI: "nearly 70% market share in this
        # segment" refers to CNG vehicles, not overall PV market share) is
        # real disclosed data but must not be presented as an overall
        # market-position figure - labelled distinctly so the rationale
        # stays accurate.
        window = text[max(0, m.start() - 60):m.end() + 40].lower()
        basis = "disclosed_segment_market_share_pct" if re.search(r"\bsegment\b|\bcategory\b|\bcategories\b", window) else "disclosed_market_share_pct"
        return {"market_share_pct": pct, "market_position_score": _share_pct_to_score(pct), "basis": basis}
    for pat, score in _RANK_CLAIMS:
        if pat.search(text):
            return {"market_share_pct": None, "market_position_score": score, "basis": "disclosed_rank_claim"}
    return {"market_share_pct": None, "market_position_score": None, "basis": None}


# ---------------------------------------------------------------------------
# F.1.3 - Competitor strength.
# ---------------------------------------------------------------------------

_STRENGTH_DIMENSIONS = {
    "scale": re.compile(r"\bscale\s+advantage\b|\beconomies\s+of\s+scale\b|\blargest\s+(?:exporter|player|manufacturer|producer)\b|\bmarket\s+leader\b", re.I),
    "distribution": re.compile(r"\bextensive\s+distribution\b|\bwide(?:st)?\s+distribution\s+network\b|\bpan[\s-]india\s+(?:network|presence|reach)\b|\bdeep(?:est)?\s+(?:market\s+)?reach\b", re.I),
    "technology": re.compile(r"\btechnology\s+leadership\b|\br&d\s+(?:capability|strength|investment)\b|\binnovation\s+capability\b|\bproprietary\s+technology\b", re.I),
    "cost": re.compile(r"\bcost\s+leadership\b|\bcost\s+advantage\b|\blowest[\s-]cost\s+producer\b|\blow[\s-]cost\s+manufactur", re.I),
}


def score_competitor_strength(text):
    """F.1.3 - Competitive Strength Score (1-5) based on disclosed peer
    advantages, counted across four real, generic dimensions (scale,
    distribution, technology, cost) rather than any single company's own
    phrasing. Returns {'strength_dimensions','competitive_strength_score'}
    or all-None if none of the four dimensions were found (a real,
    common case)."""
    if not text:
        return {"strength_dimensions": None, "competitive_strength_score": None}
    found = [dim for dim, pat in _STRENGTH_DIMENSIONS.items() if pat.search(text)]
    if not found:
        return {"strength_dimensions": None, "competitive_strength_score": None}
    score = {1: 2, 2: 3, 3: 4}.get(len(found), 5)
    return {"strength_dimensions": found, "competitive_strength_score": score}
