"""Daily-bar collector (Angel SmartAPI ONE_DAY). Throttled, resumable, checkpointed, idempotent, duplicate-safe.

Measured provider behaviour this is built around:
 - one request returns at most ~1,375 daily rows and, beyond that, SILENTLY drops the OLDEST rows -> requests are
   3.8-year chunks (~960 rows) on a fixed grid, and every chunk's first/last returned date is verified against the
   requested range (see verify_chunk).
 - the provider timestamp ('2015-01-02T00:00:00+05:30', IST midnight) is preserved verbatim in raw_ts; `date` is
   its IST calendar date.
 - an in-progress session's bar is never stored: today's bar is accepted only after 15:45 IST.
Nothing is repaired or interpolated: a bar is in the store only if the provider returned it.
"""
import datetime as dt
import time

from .. import config, store
from ..collector import AngelHistory, RateLimited  # noqa: F401  (shared throttled client)

CHUNK_DAYS = 1400
SLACK_DAYS = 7                       # weekends + holidays between a requested edge and the first/last session
_ANCHOR = dt.date(2000, 1, 3)
_IST = dt.timezone(dt.timedelta(seconds=config.IST_OFFSET_SEC))


def chunk_grid(start: dt.date, end: dt.date, days=CHUNK_DAYS):
    k0, k1 = (start - _ANCHOR).days // days, (end - _ANCHOR).days // days
    out = []
    for k in range(k0, k1 + 1):
        cs = _ANCHOR + dt.timedelta(days=k * days)
        out.append((max(cs, start), min(cs + dt.timedelta(days=days - 1), end)))
    return out


def verify_chunk(req_start: dt.date, req_end: dt.date, dates, today: dt.date, listed_before=False):
    """-> (status, detail). status: ok | empty | late_start | early_end | off_range | suspect_truncated
    late_start is only informational when the symbol simply was not listed yet (no earlier chunk had data)."""
    if not dates:
        return "empty", "no bars returned"
    first, last = min(dates), max(dates)
    notes, status = [], "ok"
    if (req_end - req_start).days + 1 > CHUNK_DAYS + 1:
        return "suspect_truncated", "requested span exceeds the safe chunk size"
    if (first - req_start).days > SLACK_DAYS:
        # A late first bar is legitimate only before the listing date (no earlier chunk had data). After earlier data
        # it means the provider silently dropped the oldest part of the range -> NOT acceptable, never skipped on resume.
        status = "suspect_truncated" if listed_before else "late_start"
        notes.append(f"requested start {req_start} but first bar {first}" + (" (TRUNCATION)" if listed_before else " (possible listing date)"))
    if req_end < today and (req_end - last).days > SLACK_DAYS:
        status = "early_end" if status == "ok" else status
        notes.append(f"requested end {req_end} but last bar {last}")
    if first < req_start or last > req_end:
        status = "off_range"
        notes.append(f"bars {first}..{last} outside requested {req_start}..{req_end}")
    return status, "; ".join(notes) or f"{first}..{last}"


def _rows(data, today_ist: dt.date, now_ist: dt.datetime):
    rows = []
    for r in data:
        raw = r[0]
        d = dt.datetime.fromisoformat(raw)
        if d.tzinfo is None:
            raise ValueError(f"naive provider timestamp {raw!r}")
        day = d.astimezone(_IST).date()
        if day == today_ist and now_ist.time() < dt.time(15, 45):
            continue                                            # session still open: bar is not final
        vals = [None if x is None else float(x) for x in r[1:6]]
        rows.append((day.isoformat(), raw, *vals))
    return rows


def upsert(con, symbol, rows, source="angel_smartapi_1d"):
    """INSERT OR IGNORE: never overwrites; a re-fetch that disagrees is flagged as `revised_bar`."""
    now = int(time.time())
    ins = same = rev = 0
    with store.tx(con):
        for day, raw, o, h, l, c, v in rows:
            cur = con.execute("INSERT OR IGNORE INTO daily_candles VALUES (?,?,?,?,?,?,?,?,?,?)", (symbol, day, raw, o, h, l, c, v, source, now))
            if cur.rowcount:
                ins += 1
                continue
            old = con.execute("SELECT open,high,low,close,volume FROM daily_candles WHERE symbol=? AND date=?", (symbol, day)).fetchone()
            if tuple(old) == (o, h, l, c, v):
                same += 1
            else:
                rev += 1
                con.execute("INSERT OR IGNORE INTO daily_quality_flags VALUES (?,?,?,?,?,?)",
                            (symbol, day, "revised_bar", "warn", f"stored={tuple(old)} refetched={(o, h, l, c, v)}", now))
    return ins, same, rev


def backfill_daily(client: AngelHistory, con, symbol, start="2000-01-01", today=None):
    """Fetch every missing/open 3.8-year chunk for one symbol. Safe to interrupt and re-run."""
    now_ist = dt.datetime.now(_IST)
    today = today or now_ist.date()
    inst = con.execute("SELECT exch, token FROM instruments WHERE symbol=?", (symbol,)).fetchone()
    if inst is None:
        m = client.resolve(symbol)
        if m is None:
            return {"symbol": symbol, "error": "no Angel instrument token"}
        with store.tx(con):
            con.execute("INSERT OR REPLACE INTO instruments VALUES (?,?,?,?,?,?)",
                        (symbol, m["exch"], m["token"], m["trading_symbol"], m["kind"], int(time.time())))
        inst = (m["exch"], m["token"])
    exch, token = inst
    summary = {"symbol": symbol, "chunks": 0, "fetched": 0, "skipped": 0, "bars_new": 0, "problems": []}
    had_earlier = False
    for d0, d1 in chunk_grid(dt.date.fromisoformat(start), today):
        summary["chunks"] += 1
        key = (symbol, str(d0), str(d1))
        row = con.execute("SELECT status, n_bars FROM daily_fetch_log WHERE symbol=? AND chunk_start=? AND chunk_end=?", key).fetchone()
        if row and row[0] in ("ok", "late_start", "empty", "early_end") and d1 < today:
            summary["skipped"] += 1
            had_earlier = had_earlier or (row[1] or 0) > 0
            continue
        data, attempts, err = client.candles(exch, token, "1d", d0, d1)
        summary["fetched"] += 1
        if data is None:
            status, detail, rows = "error", err, []
        else:
            rows = _rows(data, today, now_ist)
            status, detail = verify_chunk(d0, d1, [dt.date.fromisoformat(r[0]) for r in rows], today, listed_before=had_earlier)
            ins, same, rev = upsert(con, symbol, rows)
            summary["bars_new"] += ins
            if rev:
                detail += f"; {rev} revised bars"
        had_earlier = had_earlier or bool(rows)
        if status != "ok":
            summary["problems"].append((str(d0), str(d1), status, detail))
        with store.tx(con):
            con.execute("INSERT OR REPLACE INTO daily_fetch_log VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (*key, status, len(rows), min((r[0] for r in rows), default=None), max((r[0] for r in rows), default=None),
                         attempts, detail, int(time.time())))
    return summary


def main(argv=None):
    import argparse
    import json
    from . import universe
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", help="override the configured universe")
    ap.add_argument("--min-delay", type=float, default=1.5)
    a = ap.parse_args(argv)
    cfg = universe.load()
    syms = a.symbols or (cfg["indices"] + cfg["symbols"])
    con = store.connect()
    client = AngelHistory(min_delay=a.min_delay, max_delay=3.0, cooldown=6.0)
    client.login()
    for s in syms:
        print(json.dumps(backfill_daily(client, con, s, cfg["start"]), default=str), flush=True)
    print(f"[done] requests={client.requests} rate_limit_hits={client.rate_limit_hits}", flush=True)


if __name__ == "__main__":
    main()
