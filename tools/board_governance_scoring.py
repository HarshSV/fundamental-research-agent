"""
C.5.1-C.5.4 - Board composition & independence. Deterministic (no-LLM)
aggregation over NSE's real quarterly Corporate Governance filing data
(tools/governance_scraper.py) - director composition, committee
composition, board/committee meeting attendance. No text regex here (the
source is already structured JSON, not prose), just real-data banding,
generic across every filer's data shape.
"""


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


def _to_int(v, default=0):
    try:
        return int(str(v).strip())
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# C.5.1 - Independent directors' quality.
# ---------------------------------------------------------------------------

def score_independent_director_quality(cobod):
    """Classifies each named Independent Director (per the filing's own
    'category' field) as "High Quality" if they hold at least one
    company-committee membership AND an independent directorship at
    another listed company (real engagement + external-independence
    signals, both explicitly disclosed fields), else "Standard".
    Returns {'high_quality_count','standard_count','independent_count',
    'total_directors','quality_pct','quality_score'} or all-None if no
    directors are listed."""
    if not cobod:
        return {"high_quality_count": None, "standard_count": None, "independent_count": None,
                "total_directors": None, "quality_pct": None, "quality_score": None}
    independents = [d for d in cobod if "independent" in (d.get("category") or "").lower()]
    if not independents:
        return {"high_quality_count": None, "standard_count": None, "independent_count": None,
                "total_directors": None, "quality_pct": None, "quality_score": None}
    high_quality = 0
    for d in independents:
        memberships = _to_int(d.get("noOfMemberships"))
        other_indep_directorships = _to_int(d.get("noOfindpntDirShp"))
        if memberships >= 1 and other_indep_directorships >= 1:
            high_quality += 1
    standard = len(independents) - high_quality
    pct = round(100 * high_quality / len(independents), 1)
    return {
        "high_quality_count": high_quality, "standard_count": standard,
        "independent_count": len(independents), "total_directors": len(cobod),
        "quality_pct": pct, "quality_score": _band_score_pct(pct),
    }


# ---------------------------------------------------------------------------
# C.5.2 / C.5.3 - Committee (Audit / NRC) activity.
# ---------------------------------------------------------------------------

def score_committee_effectiveness(committee_composition, committee_meetings):
    """committee_composition: list of member dicts for one committee (from
    coc[<CommitteeName>]). committee_meetings: list of meeting-attendance
    dicts for that committee (from meetingcomm, filtered by commName).
    Effectiveness = independent-member share in composition x quorum-met
    rate across meetings held this quarter. Returns
    {'independent_members','total_members','independence_pct',
    'meetings_held','meetings_quorum_met','quorum_met_pct',
    'effectiveness_score'} or all-None if no composition AND no meeting
    data exist for this committee."""
    if not committee_composition and not committee_meetings:
        return {"independent_members": None, "total_members": None, "independence_pct": None,
                "meetings_held": None, "meetings_quorum_met": None, "quorum_met_pct": None,
                "effectiveness_score": None}
    independent_members = total_members = None
    independence_pct = None
    if committee_composition:
        total_members = len(committee_composition)
        independent_members = sum(1 for m in committee_composition if "independent" in (m.get("category") or "").lower())
        independence_pct = round(100 * independent_members / total_members, 1) if total_members else None

    meetings_held = meetings_quorum_met = None
    quorum_met_pct = None
    if committee_meetings:
        meetings_held = len(committee_meetings)
        meetings_quorum_met = sum(1 for m in committee_meetings if (m.get("quorumMetReq") or "").strip().lower() == "yes")
        quorum_met_pct = round(100 * meetings_quorum_met / meetings_held, 1) if meetings_held else None

    # Overall effectiveness = the average of whichever signal(s) are
    # actually available this quarter, never fabricating the missing one.
    signals = [p for p in (independence_pct, quorum_met_pct) if p is not None]
    if not signals:
        return {"independent_members": independent_members, "total_members": total_members, "independence_pct": independence_pct,
                "meetings_held": meetings_held, "meetings_quorum_met": meetings_quorum_met, "quorum_met_pct": quorum_met_pct,
                "effectiveness_score": None}
    overall_pct = round(sum(signals) / len(signals), 1)
    return {
        "independent_members": independent_members, "total_members": total_members, "independence_pct": independence_pct,
        "meetings_held": meetings_held, "meetings_quorum_met": meetings_quorum_met, "quorum_met_pct": quorum_met_pct,
        "effectiveness_score": _band_score_pct(overall_pct),
    }


# ---------------------------------------------------------------------------
# C.5.4 - Board attendance and committee participation.
# ---------------------------------------------------------------------------

def score_board_attendance(bodmeeting):
    """Board Participation Score = directors present / directors on
    board, averaged across every board meeting held this quarter (per
    the filing's own noOfdirector [attended] / dirOnDateMeeting [board
    roster size as of that meeting date] fields - confirmed by the
    roster count only ever decreasing as directors' terms end across the
    quarter, and attended count never exceeding it). Returns
    {'total_present','total_possible','attendance_pct',
    'meetings_count','participation_score'} or all-None if no board
    meetings are listed."""
    if not bodmeeting:
        return {"total_present": None, "total_possible": None, "attendance_pct": None,
                "meetings_count": None, "participation_score": None}
    total_present = total_possible = 0
    for m in bodmeeting:
        possible = _to_int(m.get("dirOnDateMeeting"))
        present = _to_int(m.get("noOfdirector"))
        if possible <= 0:
            continue
        total_present += min(present, possible)
        total_possible += possible
    if total_possible == 0:
        return {"total_present": None, "total_possible": None, "attendance_pct": None,
                "meetings_count": None, "participation_score": None}
    pct = round(100 * total_present / total_possible, 1)
    return {
        "total_present": total_present, "total_possible": total_possible, "attendance_pct": pct,
        "meetings_count": len(bodmeeting), "participation_score": _band_score_pct(pct),
    }
