"""
D.4.1-D.4.2 - Lock-in expiries or block share releases: large scheduled
sellable holdings. Deterministic (no-LLM) scorers over real NSE Corporate
Announcements text (tools/nse_announcements.py) - specifically allotment/
preferential-issue/IPO-related filings that state a lock-in period or an
explicit release/expiry date, a real regulatory disclosure under the SEBI
ICDR Regulations, not free narrative.

Genuinely sparse data source: NSE doesn't file a distinct "lock-in expiry"
announcement type of its own - the lock-in clause is usually a sentence
inside an allotment/preferential-issue announcement (or, for an IPO, lives
in the prospectus/RHP, which this codebase has no fetcher for at all). A
company with no matched clause is honestly reported N/A/SEARCH_INCONCLUSIVE,
never guessed into "Not Applicable" without evidence that it genuinely had
no lock-in event, per this codebase's never-fabricate rule.
"""

import re
import datetime


def _sentences(text):
    if not text:
        return []
    normalized = re.sub(r"\s+", " ", text.replace("\n", " "))
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", normalized) if s.strip()]


_LOCKIN_KEYWORD = re.compile(r"lock-?in", re.I)

_MONTHS = ("Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|"
           "January|February|March|April|May|June|July|August|September|October|November|December")
# Real NSE filing dates appear in BOTH "16 May 2014" (day-month-year) and
# "May 16, 2014" (US month-day-year) order depending on the filer - both
# must match, or a real date like "May 16, 2014" (confirmed real: SUZLON's
# 2014 preferential-issue lock-in filing) silently fails to parse.
_DATE_DMY = rf"\d{{1,2}}[\s,]*(?:{_MONTHS})[\s,]*\d{{4}}"
_DATE_MDY = rf"(?:{_MONTHS})[\s,]*\d{{1,2}}[\s,]*\d{{4}}"
_DATE_PATTERN = re.compile(rf"\b({_DATE_DMY}|{_DATE_MDY})\b", re.I)

_EXPLICIT_EXPIRY = re.compile(
    rf"lock-?in.{{0,40}}?(?:expir(?:y|ing|es|ed)|releas(?:e|ed|ing)|until|up to).{{0,15}}?"
    rf"({_DATE_DMY}|{_DATE_MDY})",
    re.I,
)

_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5}
_DURATION = re.compile(
    r"lock-?in for a period of\s*(\w+)\s*(year|month)s?", re.I,
)
_ALLOTMENT_DATE = re.compile(
    rf"(?:allotted on|allotment.{{0,20}}?(?:held on|dated)|meeting held on|"
    rf"(?:approved )?allotment of.{{0,120}}?(?:held on|dated))\s*"
    rf"({_DATE_DMY}|{_DATE_MDY})",
    re.I,
)


def _parse_date_loose(s):
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip().rstrip(",")
    s = s.replace(",", "")
    for fmt in ("%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def is_lockin_announcement(desc, attchmnt_text):
    """True if a corporate-announcement's own desc/attachment-title
    mentions a lock-in clause at all."""
    blob = f"{desc or ''} {attchmnt_text or ''}"
    return bool(_LOCKIN_KEYWORD.search(blob))


def extract_lockin_expiry(text):
    """D.4.1 - Finds a lock-in expiry/release date directly stated in the
    filing text, or computed from a "lock-in for a period of N
    years/months" clause plus a nearby allotment date. Returns a
    datetime.date or None if neither pattern matches (never guessed)."""
    if not text:
        return None
    m = _EXPLICIT_EXPIRY.search(text)
    if m:
        d = _parse_date_loose(m.group(1))
        if d:
            return d
    dur_m = _DURATION.search(text)
    alloc_m = _ALLOTMENT_DATE.search(text)
    if dur_m and alloc_m:
        base = _parse_date_loose(alloc_m.group(1))
        if base:
            n = _WORD_NUM.get(dur_m.group(1).lower())
            unit = dur_m.group(2).lower()
            if n:
                days = n * 365 if unit == "year" else n * 30
                return base + datetime.timedelta(days=days)
    return None


def score_lockin_status(text, today=None):
    """D.4.1 payload builder: Lock-in Status = Upcoming / Expired,
    with the exact date when found. Returns {'lockin_status',
    'lockin_expiry_date'} or all-None if no lock-in clause with a
    resolvable date was located in the matched announcement text."""
    if not text:
        return {"lockin_status": None, "lockin_expiry_date": None}
    expiry = extract_lockin_expiry(text)
    if expiry is None:
        return {"lockin_status": None, "lockin_expiry_date": None}
    today = today or datetime.date.today()
    status = "Upcoming" if expiry >= today else "Expired"
    return {"lockin_status": status, "lockin_expiry_date": expiry.isoformat()}


# ---------------------------------------------------------------------------
# D.4.2 - Potential sellable block size.
# ---------------------------------------------------------------------------

_RELEASE_PCT = re.compile(
    r"(\d+(?:\.\d+)?)\s*%\s*of the (?:(?:total|paid-?up)\s*)?(?:issued\s*and\s*)?(?:paid-?up )?"
    r"(?:equity\s*)?share capital", re.I,
)
_RELEASE_SHARES = re.compile(
    r"(?:release of|releasing)\s*([\d,]+)\s*(?:equity )?shares", re.I,
)


def score_sellable_block(text):
    """D.4.2 - Potential Release % = Shares Becoming Saleable / Total
    Shares Outstanding x 100, read directly where the filing states the
    percentage itself (the same pattern used for D.3.2's dilution %),
    since a reliable independent locked/encumbered-holdings field isn't
    exposed by NSE's shareholding-pattern API this codebase already uses.
    Returns {'release_pct','shares_released','classification'} or
    all-None if the filing doesn't state the percentage explicitly."""
    if not text:
        return {"release_pct": None, "shares_released": None, "classification": None}
    pct_m = _RELEASE_PCT.search(text)
    shares_m = _RELEASE_SHARES.search(text)
    shares_released = None
    if shares_m:
        try:
            shares_released = int(shares_m.group(1).replace(",", ""))
        except ValueError:
            shares_released = None
    if not pct_m:
        return {"release_pct": None, "shares_released": shares_released, "classification": None}
    pct = float(pct_m.group(1))
    if pct < 2:
        classification = "Low"
    elif pct <= 5:
        classification = "Moderate"
    else:
        classification = "High"
    return {"release_pct": pct, "shares_released": shares_released, "classification": classification}
