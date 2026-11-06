"""Row sets for the list pages that are not stock scans: Results Calendar, Circuit Revision List, Order Wins, Bulk and Block Deals, ASM
List, Sector Indices, Recent IPOs and Past Winners. Each function returns {"rows": [...], "as_of": ..., "note": ...}; a feed that has not
been read yet returns an empty list and says so in the note (never invented rows)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from . import exchange_data as ex
from . import market_lists, scan
from .screen_engine import DAY, IST

PERIOD_NAMES = {3: "Mar", 6: "Jun", 9: "Sep", 12: "Dec"}


def _scan_rows() -> dict:
    return scan._load_all()


def _info(sym: str, rows: dict) -> dict:
    r = rows.get(sym) or {}
    name = r.get("name") or ((ex.load("listings") or {}).get(sym) or {}).get("name")
    return {"name": name, "sector": r.get("sector"), "market_cap_cr": r.get("market_cap_cr"), "price": r.get("price"), "industry": r.get("industry")}


def _quarter_label(iso: str | None) -> str | None:
    try:
        d = date.fromisoformat(iso)
        return f"{PERIOD_NAMES.get(d.month, d.strftime('%b'))} {d.year}"
    except Exception:
        return None


def results_calendar(start: str | None = None, end: str | None = None) -> dict:
    """Companies that filed (or will file) results in the window. Growth columns come from Screener quarterly data and are filled only
    when that company's latest quarter on Screener is the quarter filed."""
    from screens import quarterly as qt
    rows = _scan_rows()
    market_lists.annotate(rows)
    q = qt.load()
    results, cal = ex.load("results") or {}, ex.load("calendar") or []
    q_latest, _ = market_lists._quarter_ends(results) if results else (None, None)
    label = _quarter_label(q_latest)
    start = start or (date.today() - timedelta(days=3)).isoformat()
    end = end or (date.today() + timedelta(days=7)).isoformat()
    out = []
    for sym, per in results.items():
        ts = per.get(q_latest) if q_latest else None
        if not ts or not (start <= ts[:10] <= end):
            continue
        out.append({"symbol": sym, "date": ts[:10], "time": ts[11:16], "status": "Announced", **_info(sym, rows)})
    have = {x["symbol"] for x in out}
    for c in cal:
        if "result" in (c.get("purpose") or "").lower() and start <= c["date"] <= end and c["symbol"] not in have:
            out.append({"symbol": c["symbol"], "date": c["date"], "time": None, "status": "Upcoming", "name": c.get("name"), **{k: v for k, v in _info(c["symbol"], rows).items() if k != "name"}})
    for x in out:
        rec = q.get(x["symbol"])
        d = qt.derive(rec, label) if rec and rec.get("periods") else {}
        ok = bool(d) and d.get("last_quarter") == label
        for k in ("eps_qoq", "eps_yoy", "sales_qoq", "sales_yoy", "np_qoq", "np_yoy", "opm_qoq_pp", "opm_yoy_pp"):
            x[k] = d.get(k) if ok else None
        x["in_universe"] = x["symbol"] in rows
    out.sort(key=lambda x: (x["date"], x["symbol"]), reverse=True)
    return {"rows": out, "as_of": date.today().isoformat(), "quarter": label, "from": start, "to": end,
            "note": None if results else "Results dates have not been read yet."}


def circuit_revisions(days: int = 30) -> dict:
    b = ex.load("bands")
    rows = _scan_rows()
    if not b:
        return {"rows": [], "note": "Price-band files have not been read yet."}
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    out = [{**_info(x["symbol"], rows), **x} for x in b["revisions"] if x["date"] >= cutoff]
    return {"rows": out, "as_of": b["as_of"], "note": "Revisions are found by comparing NSE's daily price-band files, so the date is the first file that shows the new band."}


def order_wins() -> dict:
    o = ex.load("orders")
    rows = _scan_rows()
    if o is None:
        return {"rows": [], "note": "Announcements have not been read yet."}
    return {"rows": [{**_info(x["symbol"], rows), **{k: v for k, v in x.items() if v is not None}} for x in o], "as_of": date.today().isoformat(),
            "note": "Announcements of orders and contracts from the last two weeks, as filed with NSE. No AI summary is generated."}


def deals(kind: str) -> dict:
    d = ex.load("deals")
    rows = _scan_rows()
    if d is None:
        return {"rows": [], "note": "Deal files have not been read yet."}
    return {"rows": [{**{k: v for k, v in _info(x["symbol"], rows).items() if k not in ("name", "price")}, **x} for x in d.get(kind, [])], "as_of": date.today().isoformat(),
            "note": "NSE publishes each day's file; Navrist keeps what it has read since it started (up to 120 days)."}


def asm_list() -> dict:
    a = ex.load("asm")
    rows = _scan_rows()
    if a is None:
        return {"rows": [], "note": "The ASM list has not been read yet."}
    return {"rows": [{"symbol": s, **v, **{k: x for k, x in _info(s, rows).items() if k != "name"}} for s, v in sorted(a.items())], "as_of": date.today().isoformat(),
            "note": "Long-term (LTASM) and short-term (STASM) additional surveillance lists from NSE."}


def sector_indices() -> dict:
    i = ex.load("indices")
    if i is None:
        return {"rows": [], "note": "Index data has not been read yet."}
    return {"rows": i, "as_of": date.today().isoformat(), "note": "All NSE indices as published; the day's change is against the previous close."}


def recent_ipos(days: int = 365) -> dict:
    li = ex.load("listings")
    rows = _scan_rows()
    if li is None:
        return {"rows": [], "note": "The listings file has not been read yet."}
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    out = []
    for sym, v in li.items():
        if v["listed"] >= cutoff:
            r = rows.get(sym) or {}
            out.append({"symbol": sym, "listed": v["listed"], "face_value": v.get("face_value"), "series": v.get("series"), "name": r.get("name"),
                        "price": r.get("price"), "market_cap_cr": r.get("market_cap_cr"), "ret_1m": r.get("ret_1m"), "in_universe": sym in rows})
    out.sort(key=lambda x: x["listed"], reverse=True)
    return {"rows": out, "as_of": date.today().isoformat(), "note": "Every NSE listing in the last year. Price and returns are shown for the stocks Navrist scans."}


def past_winners(year: int | None = None, limit: int = 50) -> dict:
    """The best calendar-year (or year-to-date) performers among the scanned stocks, from the stored closes."""
    rows = _scan_rows()
    this_year = date.today().year
    year = year or this_year - 1
    start = datetime(year - 1, 12, 31, tzinfo=timezone.utc).timestamp()
    end = datetime(year, 12, 31, tzinfo=timezone.utc).timestamp() if year < this_year else 10 ** 12
    out = []
    for r in rows.values():
        cl = [(t, c) for t, c in (r.get("closes") or []) if c]
        if not cl or cl[0][0] - IST > start + 7 * DAY:
            continue
        base = max(((t, c) for t, c in cl if t - IST <= start + DAY), default=None, key=lambda x: x[0])
        last = max(((t, c) for t, c in cl if t - IST <= end), default=None, key=lambda x: x[0])
        if not base or not last or base[1] <= 0 or last[0] <= base[0]:
            continue
        out.append({"symbol": r["symbol"], "name": r.get("name"), "sector": r.get("sector"), "return_pct": (last[1] / base[1] - 1.0) * 100.0,
                    "market_cap_cr": r.get("market_cap_cr"), "industry": r.get("industry")})
    out.sort(key=lambda x: -x["return_pct"])
    return {"rows": out[:limit], "year": year, "years": [this_year - 1, this_year], "as_of": date.today().isoformat(),
            "note": f"Return from the last close of {year - 1}" + (" to the last close of the year." if year < this_year else " to the latest close (year to date).") + " Only years covered by the stored closes (about two) are available; stocks listed later are left out."}
