"""
Concall-window evidence retrieval — layer 2/3 of the event-grounded reasoning
pipeline (see memory "event-grounded-reasoning-scope"). Given a flagged price
move window (from move_detection.py), filter the company's already-extracted
concall records (tools/concall_intelligence.py) down to the calls that fall
near that window, so a "why did X move" answer can be grounded in what
management actually said around that time instead of LLM narrative-guessing.

Deliberately NOT a vector DB — per the rework decision this project keeps
retrieval to keyword/date-window filtering, which is exactly what a "which
calls happened around this date" filter is. Never raises.
"""

import re
from datetime import date, timedelta

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

NEARBY_BUFFER_DAYS = 30  # a call up to ~1 month before/after the window still counts as "near"


def _parse_call_date(date_str):
    """'Jul 2026' -> date(2026, 7, 1); None on parse failure."""
    m = re.match(r"([A-Za-z]{3})\w*\s+(\d{4})", (date_str or "").strip())
    if not m:
        return None
    mo = _MONTHS.get(m.group(1).lower()[:3])
    if not mo:
        return None
    try:
        return date(int(m.group(2)), mo, 1)
    except Exception:
        return None


def evidence_for_window(symbol: str, date_from: str, date_to: str, name: str = None) -> dict:
    """
    Returns {available, calls: [...]} — the concall records (from
    concall_intelligence, already-cached per symbol) whose date falls within
    NEARBY_BUFFER_DAYS of [date_from, date_to] (ISO strings). Each call entry
    keeps only the fields useful as evidence: date, one_line, guidance,
    commitments, positives, risks, sentiment. Empty `calls` means genuinely no
    evidence was found — callers/LLM must say so rather than fabricate.
    """
    try:
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
    except Exception:
        return {"available": False, "calls": [], "reason": "Invalid date window."}

    lo = d_from - timedelta(days=NEARBY_BUFFER_DAYS)
    hi = d_to + timedelta(days=NEARBY_BUFFER_DAYS)

    try:
        from tools.concall_intelligence import build_concall_intelligence
        intel = build_concall_intelligence(symbol, name=name)
    except Exception as e:
        return {"available": False, "calls": [], "reason": f"Concall data unavailable: {e}"}

    if not intel or not intel.get("available"):
        return {"available": False, "calls": [], "reason": intel.get("reason", "No concall data.") if intel else "No concall data."}

    matched = []
    for call in intel.get("calls", []):
        cd = _parse_call_date(call.get("date"))
        if cd is None:
            continue
        if lo <= cd <= hi:
            matched.append({
                "date": call.get("date"),
                "sentiment": call.get("sentiment"),
                "one_line": call.get("one_line"),
                "guidance": call.get("guidance", []),
                "commitments": call.get("commitments", []),
                "positives": call.get("positives", []),
                "risks": call.get("risks", []),
                "capital_allocation": call.get("capital_allocation", ""),
            })

    return {"available": True, "calls": matched}


def news_for_window(symbol: str, date_from: str, date_to: str, name: str = None) -> dict:
    """Same idea as evidence_for_window but for scraped news headlines
    (tools/news_sentiment.py) instead of concall records. Returns
    {available, headlines: [{title, source, published, sentiment}]}."""
    try:
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
    except Exception:
        return {"available": False, "headlines": [], "reason": "Invalid date window."}

    lo = d_from - timedelta(days=NEARBY_BUFFER_DAYS)
    hi = d_to + timedelta(days=NEARBY_BUFFER_DAYS)

    try:
        from tools.news_sentiment import get_news_sentiment
        result = get_news_sentiment(symbol, name)
    except Exception as e:
        return {"available": False, "headlines": [], "reason": f"News fetch failed: {e}"}

    if not result.get("available"):
        return {"available": False, "headlines": [], "reason": result.get("reason", "No news available.")}

    matched = []
    for h in result.get("headlines", []):
        try:
            pub_dt = parsedate_to_datetime_safe(h.get("published"))
        except Exception:
            pub_dt = None
        if pub_dt is None or (lo <= pub_dt.date() <= hi):
            matched.append({
                "title": h.get("title"), "source": h.get("source"),
                "published": h.get("published"), "sentiment": h.get("sentiment"),
            })

    return {"available": True, "headlines": matched}


def parsedate_to_datetime_safe(raw):
    from email.utils import parsedate_to_datetime
    return parsedate_to_datetime(raw) if raw else None


if __name__ == "__main__":
    import sys
    import json
    sym = sys.argv[1] if len(sys.argv) > 1 else "TATASTEEL"
    df = sys.argv[2] if len(sys.argv) > 2 else "2026-05-01"
    dt = sys.argv[3] if len(sys.argv) > 3 else "2026-06-01"
    print(json.dumps(evidence_for_window(sym, df, dt), indent=2, default=str))
