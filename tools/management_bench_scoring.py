"""
B.3.1-B.3.3 - Depth of management bench: deterministic (no-LLM) scorers.

Same design as tools/founder_track_record_scoring.py (B.1) and
tools/management_incentives_scoring.py (B.2): regex/table pattern matching
against real Annual Report text only, no LLM call.
"""

import re

_NUM = r"\d[\d,]*\.?\d*"


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
# B.3.1 - Leadership depth: Senior Management Personnel / Management
# Committee / Executive Leadership Team.
# ---------------------------------------------------------------------------

# A standard AR's Senior Management Personnel (SMP) / Management Committee
# table is a simple [Name, Designation] pair list - counting real named
# rows is the most reliable, format-independent measure of bench size (an
# explicit "Committee comprises N Members" sentence is a fallback, not
# every filer states one).
_SMP_HEADER_KEYWORDS = ["name of smp", "name of the member", "name of members", "name"]
_DESIGNATION_HEADER_KEYWORDS = ["designation", "position"]
_COMPRISES_N_MEMBERS = re.compile(r"comprises?\s+(\d+)\s+members?", re.I)


def score_leadership_depth_from_table(table):
    """Counts real [Name, Designation] rows in a Senior Management
    Personnel / Management Committee table. Returns
    {'member_count','depth_score'} or all-None if the table doesn't look
    like a name+designation listing (fewer than 2 usable rows)."""
    from tools.ar_table_extractor import find_column
    if not table or len(table) < 2:
        return {"member_count": None, "depth_score": None}
    header = table[0]
    name_col = find_column(header, _SMP_HEADER_KEYWORDS)
    desig_col = find_column(header, _DESIGNATION_HEADER_KEYWORDS)
    if name_col is None or desig_col is None:
        return {"member_count": None, "depth_score": None}
    count = 0
    for row in table[1:]:
        if max(name_col, desig_col) >= len(row):
            continue
        name = (row[name_col] or "").strip()
        desig = (row[desig_col] or "").strip()
        if name and desig and len(name) >= 3 and not name.lower().startswith(("total", "name")):
            count += 1
    if count < 2:
        return {"member_count": None, "depth_score": None}
    score = 5 if count >= 10 else 4 if count >= 7 else 3 if count >= 5 else 2 if count >= 3 else 1
    return {"member_count": count, "depth_score": score}


_SMP_SECTION_HEADER = re.compile(r"name\s+of\s+(?:smp|the\s+members?|members?)\s*\n?\s*designation", re.I)
_BOILERPLATE_LINE = re.compile(
    r"^(statutory reports|corporate overview|financial statements|corporate governance report|"
    r"integrated annual report|declaration regarding|\d+)$", re.I
)
_DESIGNATION_HINT = re.compile(
    r"officer|head|director|president|secretary|counsel|chief|manager|business|"
    r"cfo|ceo|coo|cto|chro|cio|controller", re.I
)


def score_leadership_depth_from_text(text):
    """PRIMARY text-based extractor - a standard AR's Senior Management
    Personnel / Management Committee section is a real [Name, Designation]
    pair list even when the PDF has no ruled table lines (confirmed real
    on both TCS and HINDUNILVR - pdfplumber's geometry-based table
    detector found nothing on either, but the pairs are right there in
    the extracted text after a "Name of SMP / Designation" style header).
    Walks the text line-by-line pairing a name-shaped line with the
    following designation-shaped line; stops at a boilerplate page-
    header/footer line or after 30 pairs. Falls back to an explicit
    "Committee comprises N Members" sentence if no header/pairs are found
    at all. Returns {'member_count','depth_score'} or all-None."""
    if not text:
        return {"member_count": None, "depth_score": None}
    from tools.founder_track_record_scoring import _looks_like_person_name

    m = _SMP_SECTION_HEADER.search(text)
    if m:
        lines = [ln.strip() for ln in text[m.end():m.end() + 4000].split("\n") if ln.strip()]
        count = 0
        i = 0
        while i < len(lines) - 1 and count < 30:
            ln, nxt = lines[i], lines[i + 1]
            if _BOILERPLATE_LINE.match(ln) or _BOILERPLATE_LINE.match(nxt):
                break
            if _looks_like_person_name(ln) and (_DESIGNATION_HINT.search(nxt) or _looks_like_person_name(nxt) is False):
                count += 1
                i += 2
            else:
                i += 1
        if count >= 2:
            score = 5 if count >= 10 else 4 if count >= 7 else 3 if count >= 5 else 2 if count >= 3 else 1
            return {"member_count": count, "depth_score": score}

    m2 = _COMPRISES_N_MEMBERS.search(text)
    if m2:
        count = int(m2.group(1))
        score = 5 if count >= 10 else 4 if count >= 7 else 3 if count >= 5 else 2 if count >= 3 else 1
        return {"member_count": count, "depth_score": score}

    return {"member_count": None, "depth_score": None}


# ---------------------------------------------------------------------------
# B.3.2 - Succession readiness.
# ---------------------------------------------------------------------------

# Positive evidence of an ACTUALLY OPERATING succession process (not just a
# committee's charter DUTY to think about it, which every AR states
# generically regardless of whether a real plan exists).
_SUCCESSION_ACTIVE_CTX = re.compile(
    r"succession\s+plan(?:ning)?\s+(?:is\s+)?(?:periodically\s+)?review(?:ed|s)?|"
    r"robust\s+succession\s+planning|"
    r"succession\s+plan(?:ning)?\s+(?:is\s+)?in\s+place|"
    r"succession\s+plan(?:ning)?\s+(?:has\s+been\s+)?approved|"
    r"deep\s+leadership\s+talent\s+pool", re.I
)
# A completed, NAMED leadership transition ("appointed ... in succession to
# ...") is direct, concrete evidence the company can and does replace key
# executives - stronger evidence than any policy-charter sentence.
_IN_SUCCESSION_TO = re.compile(r"in\s+succession\s+to\s+(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?)?\s*[A-Z][A-Za-z.]+", re.I)


def score_succession_readiness(text):
    """Classifies succession readiness from EITHER (a) explicit evidence
    the succession-planning PROCESS is actually active/reviewed, or (b) a
    concrete completed transition naming a successor. Two independent
    signals summed as evidence count, not one overriding the other - a
    company doing both is more clearly "Ready" than one doing either
    alone. Returns {'succession_transitions','active_process_evidence',
    'readiness'} or all-None if neither signal is found."""
    if not text:
        return {"succession_transitions": None, "active_process_evidence": None, "readiness": None}
    # Dedup by matched text - the same real transition sentence can appear
    # twice when two different anchor phrases both located the page/text
    # region containing it (confirmed real: overlapping anchor hits
    # double-counted the same 3 real transitions as 10).
    transitions = len(set(m.group(0).lower() for m in _IN_SUCCESSION_TO.finditer(text)))
    active_evidence = bool(_SUCCESSION_ACTIVE_CTX.search(text))
    if transitions == 0 and not active_evidence:
        return {"succession_transitions": None, "active_process_evidence": None, "readiness": None}
    readiness = "Ready" if (transitions >= 1 or active_evidence) else "Not Ready"
    return {"succession_transitions": transitions, "active_process_evidence": active_evidence, "readiness": readiness}


# ---------------------------------------------------------------------------
# B.3.3 - Key executive dependency.
# ---------------------------------------------------------------------------

def score_key_person_dependency(member_count):
    """Uses the leadership bench size (member_count, from B.3.1's Senior
    Management Personnel / Management Committee count) as the dependency
    signal: responsibility spread across many named senior executives is
    structurally distributed; a thin bench concentrates day-to-day
    authority in very few hands. (An earlier version tried to compare a
    named Chairman against the top executive via a "(C)" role code, but
    that code is genuinely ambiguous - it also marks a COMMITTEE's own
    chair, not just the company Chairman, and produced a confirmed wrong
    "Concentrated" result live on TCS by picking up an Audit Committee
    chair instead of the real board Chairman. Bench size has no such
    ambiguity - it's the same real count already validated for B.3.1.)
    Returns {'dependency_level','dependency_score'} or all-None if
    member_count itself wasn't found."""
    if member_count is None:
        return {"dependency_level": None, "dependency_score": None}
    if member_count >= 8:
        level, score = "Distributed", 5
    elif member_count >= 5:
        level, score = "Distributed", 4
    elif member_count >= 3:
        level, score = "Concentrated", 2
    else:
        level, score = "Concentrated", 1
    return {"dependency_level": level, "dependency_score": score}
