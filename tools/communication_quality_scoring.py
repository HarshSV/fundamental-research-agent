"""
B.4.1-B.4.3 - Communication quality: deterministic (no-LLM) scorers.

Same design as the other B-section modules: regex/keyword pattern matching
against real Annual Report / earnings-call-transcript text only, no LLM
call. B.4.1 sources the Annual Report's Risk disclosures; B.4.2/B.4.3
source the company's own real earnings-call transcript (BSE-filed PDF,
already fetched elsewhere in this codebase for F-14 - see
tools/screener_scraper.py's fetch_concall_list/download_transcript).
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
# B.4.1 - Transparency in disclosures (Annual Report Risk section).
# ---------------------------------------------------------------------------

_RISK_KEYWORD = re.compile(r"\brisk\b|\buncertaint(?:y|ies)\b|\bexposure\b", re.I)
_QUANTIFIED_MARKER = re.compile(r"\d+(?:\.\d+)?\s*%|₹\s*\d|\$\s*\d|\bcrore\b|\bmillion\b|\bbillion\b", re.I)
_GENERIC_BOILERPLATE_RISK = re.compile(
    r"in the ordinary course of business|no assurance can be given|"
    r"may adversely affect|various risks and uncertainties|"
    r"factors beyond (?:the|our|its) control|forward[- ]looking statements? .{0,40}involve", re.I
)


def score_disclosure_transparency(risk_text):
    """A risk-related sentence is "detailed" if it names a QUANTIFIED
    figure (a %, currency amount, or magnitude word) within the same
    sentence - not just generic risk-exists language. "Generic" if it
    matches known boilerplate risk phrasing with no specifics. Every other
    risk-keyword sentence is left unclassified (neither bucket) - not
    forced into "generic" just for lacking a number, since plenty of real
    qualitative risk detail (a named risk factor, a specific mitigation
    action) is detailed without a number. Detailed vs Generic bucket
    counts drive the score; sentences that are neither aren't counted
    either way. Returns {'detailed_count','generic_count',
    'detailed_pct','transparency_score'} or all-None if no risk-keyword
    sentence carries either signal."""
    if not risk_text:
        return {"detailed_count": None, "generic_count": None, "detailed_pct": None, "transparency_score": None}
    detailed, generic = 0, 0
    for sent in _sentences(risk_text):
        if not _RISK_KEYWORD.search(sent):
            continue
        if _QUANTIFIED_MARKER.search(sent):
            detailed += 1
        elif _GENERIC_BOILERPLATE_RISK.search(sent):
            generic += 1
    total = detailed + generic
    if total == 0:
        return {"detailed_count": None, "generic_count": None, "detailed_pct": None, "transparency_score": None}
    pct = round(100 * detailed / total, 1)
    return {"detailed_count": detailed, "generic_count": generic, "detailed_pct": pct, "transparency_score": _band_score_pct(pct)}


# ---------------------------------------------------------------------------
# B.4.2 - Clarity in guidance (earnings-call prepared remarks).
# ---------------------------------------------------------------------------

_NO_GUIDANCE_DISCLAIMER = re.compile(
    r"(?:don'?t|do not|won'?t|will not)\s+provide[^.]{0,60}?guidance|"
    r"no\s+specific\s+guidance", re.I
)
_QUANTIFIED_OUTLOOK = re.compile(
    r"(?:expect|guidance|target|forecast|project)[a-z]*\s+(?:of\s+)?[^.]{0,40}?\d+(?:\.\d+)?\s*%|"
    r"\d+(?:\.\d+)?\s*%\s*(?:to|-)\s*\d+(?:\.\d+)?\s*%", re.I
)
_VAGUE_OUTLOOK = re.compile(
    r"remain(?:s)? optimistic|several (?:growth )?opportunit|continue to focus|"
    r"cautiously optimistic|well[- ]positioned|confident (?:about|in) (?:the|our)|"
    r"remain (?:around|in line with|steady|stable)|current guided range", re.I
)


def score_guidance_clarity(prepared_remarks_text):
    """If the company EXPLICITLY states it does not provide specific
    guidance, that is itself a direct, honest signal - classified
    "Ambiguous" (a real and common policy, e.g. most large Indian IT
    services firms) rather than treated as missing data. Otherwise counts
    quantified forward-looking statements ("we expect X% growth",
    "guidance of X-Y%") against vague ones ("remain optimistic", "several
    opportunities ahead" with no number). Returns
    {'quantified_count','vague_count','clarity_pct','clarity_score',
    'explicit_no_guidance'} or all-None if none of these signals appear."""
    if not prepared_remarks_text:
        return {"quantified_count": None, "vague_count": None, "clarity_pct": None, "clarity_score": None, "explicit_no_guidance": None}
    if _NO_GUIDANCE_DISCLAIMER.search(prepared_remarks_text):
        return {"quantified_count": 0, "vague_count": 1, "clarity_pct": 0.0, "clarity_score": 1, "explicit_no_guidance": True}
    quantified = len(_QUANTIFIED_OUTLOOK.findall(prepared_remarks_text))
    vague = len(_VAGUE_OUTLOOK.findall(prepared_remarks_text))
    total = quantified + vague
    if total == 0:
        return {"quantified_count": None, "vague_count": None, "clarity_pct": None, "clarity_score": None, "explicit_no_guidance": None}
    pct = round(100 * quantified / total, 1)
    return {"quantified_count": quantified, "vague_count": vague, "clarity_pct": pct, "clarity_score": _band_score_pct(pct), "explicit_no_guidance": False}


# ---------------------------------------------------------------------------
# B.4.3 - Openness in investor communication (earnings-call Q&A section).
# ---------------------------------------------------------------------------

_QA_SECTION_MARKER = re.compile(r"question[-\s]*and[-\s]*answer|q\s*&\s*a\s+session", re.I)
_ANALYST_INTRO = re.compile(r"from the line of ([A-Z][A-Za-z.]+(?:\s+[A-Z][A-Za-z.]+){0,2})\s+(?:from|with)\b", re.I)
_EVASIVE_ANSWER = re.compile(
    r"(?:don'?t|do not|won'?t|will not|can'?t|cannot)\s+(?:comment|share|disclose|quantify|provide)|"
    r"not\s+(?:in a position|able)\s+to\s+(?:comment|share|disclose|quantify)|"
    r"(?:won'?t|will not)\s+be able to\s+(?:share|comment|quantify)", re.I
)


def score_investor_openness(qa_text):
    """Counts unique named analysts asking questions (breadth of access -
    "from the line of <Name> from <Firm>", the standard transcript
    phrasing) and evasive-answer phrases ("we don't comment on that
    specifically", "not in a position to share") within the Q&A section
    only. Open vs Defensive is banded on how RARE evasive phrases are
    relative to the number of analyst turns (fewer evasions per analyst =
    more open). Returns {'unique_analysts','evasive_answer_count',
    'openness_pct','openness_score'} or all-None if no Q&A section marker
    is found at all."""
    if not qa_text or not _QA_SECTION_MARKER.search(qa_text):
        return {"unique_analysts": None, "evasive_answer_count": None, "openness_pct": None, "openness_score": None}
    analysts = {m.group(1).strip().lower() for m in _ANALYST_INTRO.finditer(qa_text)}
    if not analysts:
        return {"unique_analysts": None, "evasive_answer_count": None, "openness_pct": None, "openness_score": None}
    evasive = len(_EVASIVE_ANSWER.findall(qa_text))
    total_turns = len(analysts)
    open_turns = max(0, total_turns - evasive)
    pct = round(100 * open_turns / total_turns, 1)
    return {
        "unique_analysts": len(analysts), "evasive_answer_count": evasive,
        "openness_pct": pct, "openness_score": _band_score_pct(pct),
    }
