"""Daily-bar data quality. Flags only - NOTHING is repaired, interpolated or filled.

Trading calendar: derived by consensus across the reference equities (a date is a trading session iff >= 50% of the
references that existed that day have a bar). No hard-coded holiday list. Per symbol, every consensus trading session
between its first and last bar that has no bar is a `missing_session` (fatal: it breaks the contiguous segment that
features and labels are computed on). A day is `verified` iff it has a bar and no FATAL flag.
"""
import time

import numpy as np
import pandas as pd

from .. import store

FATAL, WARN = "fatal", "warn"
CONSENSUS = 0.5
MIN_REFS = 3
UNADJUSTED_JUMP = 0.30      # |ln(close/prev close)| -> possible unadjusted split/bonus (fatal until reviewed)
LARGE_MOVE = 0.18           # warn only (circuit-limit sized move)


SPLIT_RATIOS = (2, 3, 4, 5, 10, 20, 1.5, 2.5, 8)
SPLIT_TOL = 0.05


def _looks_like_split(v):
    """A corporate action that the provider failed to adjust shows up as a CLEAN ratio (1/2, 1/3, 1/5, ...)."""
    r = float(np.exp(v))
    return abs(v) > 0.40 and any(abs(r * k - 1) < SPLIT_TOL or abs(r / k - 1) < SPLIT_TOL for k in SPLIT_RATIOS)


def frame(rows):
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_bars(con, symbol):
    return frame(con.execute("SELECT date, open, high, low, close, volume FROM daily_candles WHERE symbol=? ORDER BY date", (symbol,)).fetchall())


def derive_calendar(con, ref_symbols):
    spans, dates = {}, {}
    for s in ref_symbols:
        d = [r[0] for r in con.execute("SELECT date FROM daily_candles WHERE symbol=? ORDER BY date", (s,))]
        if d:
            spans[s], dates[s] = (d[0], d[-1]), set(d)
    if len(spans) < MIN_REFS:
        return {"ok": False, "reason": f"only {len(spans)} reference symbols with data (need {MIN_REFS})"}
    all_dates = sorted(set().union(*dates.values()))
    rng = pd.date_range(all_dates[0], all_dates[-1], freq="D").strftime("%Y-%m-%d")
    out = []
    for day in rng:
        active = [s for s, (a, b) in spans.items() if a <= day <= b]
        present = sum(1 for s in active if day in dates[s])
        trading = bool(active) and present / len(active) >= CONSENSUS and present >= 1
        weekday = pd.Timestamp(day).weekday() < 5
        if not weekday and not present:
            continue
        note = None
        if trading and not weekday:
            note = "weekend_session"
        elif present and not trading:
            note = "minority_bars_on_non_trading_day"
        if len(active) < MIN_REFS:
            note = (note + "; " if note else "") + "weak_consensus"
        out.append((day, int(trading), len(active), present, note))
    with store.tx(con):
        con.execute("DELETE FROM daily_calendar")
        con.executemany("INSERT INTO daily_calendar VALUES (?,?,?,?,?)", out)
    return {"ok": True, "days": len(out), "trading": sum(r[1] for r in out), "first": out[0][0], "last": out[-1][0]}


def load_calendar(con):
    return {d: t for d, t in con.execute("SELECT date, is_trading FROM daily_calendar")}


def check_bars(df, kind="equity"):
    """Pure per-bar checks -> list of (date_str, flag, severity, detail)."""
    flags = []
    if df.empty:
        return flags
    d = df.reset_index(drop=True)
    for r in d.itertuples():
        day = r.date.strftime("%Y-%m-%d")
        vals = [r.open, r.high, r.low, r.close]
        if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals):
            flags.append((day, "null_price", FATAL, "null OHLC field"))
            continue
        o, h, l, c = (float(v) for v in vals)
        if min(o, h, l, c) <= 0:
            flags.append((day, "nonpositive_price", FATAL, str((o, h, l, c))))
        if h < max(o, c) or l > min(o, c) or h < l:
            flags.append((day, "ohlc_invalid", FATAL, f"o={o} h={h} l={l} c={c}"))
        if kind == "equity":
            vol = r.volume
            if vol is None or (isinstance(vol, float) and np.isnan(vol)) or vol == 0:
                flags.append((day, "zero_volume", WARN, "volume missing/0 (treated as UNKNOWN in features)"))
            if o == h == l == c:
                flags.append((day, "flat_bar", WARN, "open=high=low=close"))
    if d["date"].duplicated().any():
        for x in d.loc[d["date"].duplicated(keep=False), "date"].unique():
            flags.append((pd.Timestamp(x).strftime("%Y-%m-%d"), "duplicate_date", FATAL, "duplicate date"))
    if not d["date"].is_monotonic_increasing:
        flags.append((d["date"].iloc[0].strftime("%Y-%m-%d"), "unordered_dates", FATAL, "dates not ascending"))
    ok = (d[["open", "close"]].astype(float) > 0).all(axis=1)
    lr = np.log(d["close"].astype(float) / d["close"].astype(float).shift(1)).where(ok & ok.shift(1, fill_value=False))
    for day, v in zip(d["date"], lr):
        if np.isnan(v):
            continue
        if abs(v) > UNADJUSTED_JUMP and _looks_like_split(v):
            flags.append((day.strftime("%Y-%m-%d"), "possible_unadjusted_corporate_action", FATAL,
                          f"close-to-close {v:+.3f} matches a clean split/bonus ratio - review adjustment"))
        elif abs(v) > UNADJUSTED_JUMP:
            # A real crash/spike (e.g. 2020-03-23, ADANIENT Feb-2023) must STAY in the data: excluding the worst real days
            # would bias tail calibration. Reported (warn), never dropped.
            flags.append((day.strftime("%Y-%m-%d"), "extreme_move", WARN, f"close-to-close {v:+.3f} (not a split ratio; kept)"))
        elif abs(v) > LARGE_MOVE:
            flags.append((day.strftime("%Y-%m-%d"), "large_move", WARN, f"close-to-close {v:+.3f}"))
    return flags


def check_symbol(con, symbol, cal):
    kind = (con.execute("SELECT kind FROM instruments WHERE symbol=?", (symbol,)).fetchone() or ("equity",))[0]
    df = load_bars(con, symbol)
    if df.empty:
        return {"symbol": symbol, "bars": 0}
    flags = check_bars(df, kind)
    fatal_days = {}
    for day, fl, sev, det in flags:
        if sev == FATAL:
            fatal_days.setdefault(day, set()).add(fl)
    have = {d.strftime("%Y-%m-%d") for d in df["date"]}
    first, last = min(have), max(have)
    sess, extra = [], []
    for day, trading in sorted(cal.items()):
        if day < first or day > last:
            continue
        reasons = set(fatal_days.get(day, set()))
        if trading and day not in have:
            reasons.add("missing_session")
            extra.append((day, "missing_session", FATAL, "consensus trading session with no bar"))
        if not trading and day in have:
            reasons.add("bars_on_closed_session")
            extra.append((day, "bars_on_closed_session", FATAL, "bar on a consensus non-trading day"))
        if trading or day in have:
            sess.append((symbol, day, 0 if reasons else 1, ",".join(sorted(reasons)) or None))
    now = int(time.time())
    with store.tx(con):
        con.execute("DELETE FROM daily_quality_flags WHERE symbol=? AND flag!='revised_bar'", (symbol,))
        con.executemany("INSERT OR REPLACE INTO daily_quality_flags VALUES (?,?,?,?,?,?)", [(symbol, d, f, s, t, now) for d, f, s, t in flags + extra])
        con.execute("DELETE FROM daily_session_quality WHERE symbol=?", (symbol,))
        con.executemany("INSERT INTO daily_session_quality VALUES (?,?,?,?)", sess)
    counts = {}
    for _, f, _, _ in flags + extra:
        counts[f] = counts.get(f, 0) + 1
    expected = sum(1 for d, t in cal.items() if t and first <= d <= last)
    return {"symbol": symbol, "bars": len(df), "first": first, "last": last, "expected_sessions": expected,
            "missing_sessions": counts.get("missing_session", 0), "verified_days": sum(r[2] for r in sess), "flag_counts": counts}


def verified_dates(con, symbol):
    return {r[0] for r in con.execute("SELECT date FROM daily_session_quality WHERE symbol=? AND verified=1", (symbol,))}


def run(con, symbols, ref_symbols=None):
    refs = ref_symbols or [r[0] for r in con.execute("SELECT symbol FROM instruments WHERE kind='equity'")
                           if con.execute("SELECT 1 FROM daily_candles WHERE symbol=? LIMIT 1", (r[0],)).fetchone()]
    cal = derive_calendar(con, refs)
    if not cal["ok"]:
        return {"ok": False, "reason": cal["reason"]}
    c = load_calendar(con)
    return {"ok": True, "calendar": cal, "per_symbol": [check_symbol(con, s, c) for s in symbols]}
