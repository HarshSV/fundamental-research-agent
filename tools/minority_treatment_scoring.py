"""
C.8.1/C.8.2/C.8.4 - Track record on minority shareholder treatment and
disclosure habits. Deterministic (no-LLM) scorers over real Annual
Report text (RPT/Contingent Liabilities/Commitments disclosures), real
AGM/Postal Ballot scrutinizer report PDFs, and NSE's own corporate-
announcements timestamp data. Generic vocabulary, not ticker-specific.

C.8.3 is intentionally absent - not defined in the spec table this
codebase was given (a genuine gap in the source spec, not an oversight
here).
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
# C.8.1 - Disclosure quality.
# ---------------------------------------------------------------------------

_DISCLOSURE_KEYWORD = re.compile(
    r"related party transaction|contingent liabilit|\bcommitment\b|corporate governance report", re.I
)
_QUANTIFIED_MARKER = re.compile(
    r"\d+(?:\.\d+)?\s*%|₹\s*\d|\$\s*\d|\bcrore\b|\bmillion\b|\bbillion\b|"
    r"\b\d{1,3}(?:,\d{2,3})+(?:\.\d+)?\b", re.I
)
_GENERIC_DISCLOSURE_BOILERPLATE = re.compile(
    r"in the ordinary course of business|no assurance can be given|"
    r"may adversely affect|various risks and uncertainties|"
    r"factors beyond (?:the|our|its) control|"
    r"no materially significant related party transactions|"
    r"possible obligation|not practicable to estimate|"
    r"does not expect any reimbursement|adequately provided for|"
    r"as and when required|as applicable, in its (?:standalone|consolidated) financial", re.I
)


def score_disclosure_quality(text):
    """A disclosure-keyword sentence (RPT / Contingent Liabilities /
    Commitments / Corporate Governance Report) is "Detailed" if it names
    a quantified figure in the same sentence, "Limited" if it matches
    known generic boilerplate with no specifics. Returns
    {'detailed_count','limited_count','detailed_pct',
    'disclosure_quality_score'} or all-None if no disclosure-keyword
    sentence carries either signal."""
    if not text:
        return {"detailed_count": None, "limited_count": None, "detailed_pct": None, "disclosure_quality_score": None}
    detailed = limited = 0
    for sent in _sentences(text):
        if not _DISCLOSURE_KEYWORD.search(sent):
            continue
        if _QUANTIFIED_MARKER.search(sent):
            detailed += 1
        elif _GENERIC_DISCLOSURE_BOILERPLATE.search(sent):
            limited += 1
    total = detailed + limited
    if total == 0:
        return {"detailed_count": None, "limited_count": None, "detailed_pct": None, "disclosure_quality_score": None}
    pct = round(100 * detailed / total, 1)
    return {"detailed_count": detailed, "limited_count": limited, "detailed_pct": pct, "disclosure_quality_score": _band_score_pct(pct)}


# ---------------------------------------------------------------------------
# C.8.2 - Minority shareholder voting and treatment.
# ---------------------------------------------------------------------------

_RESOLUTION_OUTCOME = re.compile(r"resolution is (Pass|Fail|Not Passed|Rejected)", re.I)


def score_minority_voting(scrutinizer_text):
    """Counts resolutions explicitly marked "Pass" vs not-passed
    (Fail/Not Passed/Rejected) in the AGM/Postal Ballot Scrutinizer's
    Report - real per-resolution outcomes, not an estimated approval
    rate (the report's own precise per-category vote-% table is present
    but its column layout doesn't survive PDF text extraction reliably
    enough to parse per-resolution For/Against percentages without risk
    of misattribution across different filers' table layouts - the
    binary Pass/Not-Passed outcome is the one figure that extracts
    cleanly and unambiguously). Returns {'passed_count','contested_count',
    'pass_pct','minority_treatment_score'} or all-None if no resolution
    outcome was found."""
    if not scrutinizer_text:
        return {"passed_count": None, "contested_count": None, "pass_pct": None, "minority_treatment_score": None}
    outcomes = [m.group(1).lower() for m in _RESOLUTION_OUTCOME.finditer(scrutinizer_text)]
    if not outcomes:
        return {"passed_count": None, "contested_count": None, "pass_pct": None, "minority_treatment_score": None}
    passed = sum(1 for o in outcomes if o == "pass")
    contested = len(outcomes) - passed
    pct = round(100 * passed / len(outcomes), 1)
    return {"passed_count": passed, "contested_count": contested, "pass_pct": pct, "minority_treatment_score": _band_score_pct(pct)}


# ---------------------------------------------------------------------------
# C.8.4 - Disclosure consistency and timeliness.
# ---------------------------------------------------------------------------

def _parse_hms_seconds(s):
    try:
        parts = [int(p) for p in s.strip().split(":")]
        while len(parts) < 3:
            parts.insert(0, 0)
        h, m, sec = parts[-3:]
        return h * 3600 + m * 60 + sec
    except (ValueError, AttributeError):
        return None


def score_disclosure_timeliness(announcements):
    """announcements: NSE corporate-announcements rows, each carrying
    the exchange's own "difference" field - the real, disclosed gap
    between the event/broadcast time and the exchange's own recorded
    disclosure time (an NSE-computed field, not derived here). Returns
    {'avg_gap_seconds','max_gap_seconds','events_count',
    'timeliness_score'} or all-None if no announcement has a parseable
    gap. Never raises."""
    gaps = []
    for row in (announcements or []):
        secs = _parse_hms_seconds(row.get("difference") or "")
        if secs is not None:
            gaps.append({"an_dt": row.get("an_dt"), "gap_seconds": secs, "desc": row.get("desc")})
    if not gaps:
        return {"avg_gap_seconds": None, "max_gap_seconds": None, "events_count": None, "timeliness_score": None, "by_event": None}
    avg_gap = round(sum(g["gap_seconds"] for g in gaps) / len(gaps), 1)
    max_gap = max(g["gap_seconds"] for g in gaps)
    # Timeliness bands on the AVERAGE disclosure gap across recent
    # material events - a real, NSE-recorded promptness signal. Bands
    # are generous (minutes, not seconds) since even a same-day filing
    # is normal/compliant under SEBI LODR Reg. 30's 24-hour window.
    if avg_gap <= 300:
        score = 5
    elif avg_gap <= 3600:
        score = 4
    elif avg_gap <= 21600:
        score = 3
    elif avg_gap <= 86400:
        score = 2
    else:
        score = 1
    return {"avg_gap_seconds": avg_gap, "max_gap_seconds": max_gap, "events_count": len(gaps),
            "timeliness_score": score, "by_event": gaps}
