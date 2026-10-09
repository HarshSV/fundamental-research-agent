"""Reusable data-quality pipeline. NOTHING is silently repaired: every anomaly becomes a flag,
and a session is `verified` (usable for training) only if it has no FATAL flag.

Transformations applied to the data: none. The pipeline reads candles and writes only
`quality_flags`, `session_calendar` and `session_quality` rows.

Trading calendar: no holiday list is hard-coded (none is verified available). It is derived
by consensus across reference equities: a date is a trading session iff >= 50% of reference
symbols that existed on that date have bars; the expected bar grid of a session is the set of
slots where >= 50% of present references have a bar. This adapts to NSE session-structure
changes (e.g. the 73-bar sessions seen since 2026-08-03) without code changes, and marks
sessions where consensus is weak.
"""
import json
import time

import numpy as np
import pandas as pd

from . import config, store
from .timeutil import _IST  # noqa: F401  (tz constant kept in one place)

FATAL = "fatal"
WARN = "warn"
INFO = "info"

JUMP_BAR = 0.10          # |ln(open/prev close)| inside a session
RANGE_BAR = 0.20         # (high-low)/close
CORP_ACTION_GAP = 0.30   # overnight |ln(open/prev close)| -> possible unadjusted split/bonus
MIN_REFS = 3
CONSENSUS = 0.5


def frame(rows):
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    if df.empty:
        return df
    dt_ist = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    df["session"] = dt_ist.dt.strftime("%Y-%m-%d")
    mins = dt_ist.dt.hour * 60 + dt_ist.dt.minute
    df["slot"] = ((mins - config.SESSION_OPEN_MIN) // 5).astype(int)
    df["on_grid"] = ((df["ts"] % config.BAR_SECONDS) == 0) & (((mins - config.SESSION_OPEN_MIN) % 5) == 0)
    return df


# ------------------------------------------------------------------ calendar
def derive_calendar(con, ref_symbols, interval=config.INTERVAL):
    """Consensus trading calendar + expected slot grid from reference equities."""
    per = {}
    for s in ref_symbols:
        df = frame(store.load_candles(con, s, interval))
        if not df.empty:
            df = df[df["on_grid"]]
            per[s] = df
    if len(per) < MIN_REFS:
        return {"ok": False, "reason": f"only {len(per)} reference symbols with data (need {MIN_REFS})", "sessions": {}}
    sessions = sorted(set().union(*[set(d["session"]) for d in per.values()]))
    span = {s: (d["session"].min(), d["session"].max()) for s, d in per.items()}
    out = {}
    all_dates = pd.date_range(sessions[0], sessions[-1], freq="D").strftime("%Y-%m-%d")
    by_sess = {s: {k: g for k, g in d.groupby("session")} for s, d in per.items()}
    for day in all_dates:
        active = [s for s, (a, b) in span.items() if a <= day <= b]
        present = [s for s in active if day in by_sess[s]]
        weekday = pd.Timestamp(day).weekday() < 5
        trading = bool(active) and len(present) / len(active) >= CONSENSUS and len(present) >= 1
        if not present and not weekday:
            continue
        note = None
        slots = None
        if trading:
            cnt = {}
            for s in present:
                g = by_sess[s][day]
                for sl in set(g.loc[g["slot"].between(0, config.BARS_PER_SESSION - 1), "slot"]):
                    cnt[sl] = cnt.get(sl, 0) + 1
            slots = sorted(sl for sl, c in cnt.items() if c / len(present) >= CONSENSUS)
            if len(active) < MIN_REFS:
                note = "weak_consensus"
            if len(slots) != config.BARS_PER_SESSION:
                note = (note + "; " if note else "") + f"nonstandard_session({len(slots)} slots)"
            if not weekday:
                note = (note + "; " if note else "") + "weekend_session"
        elif present:
            note = "minority_bars_on_non_trading_day"
        out[day] = {"is_trading": int(trading), "n_ref": len(active), "n_present": len(present), "slots": slots, "note": note}
    return {"ok": True, "sessions": out, "n_refs": len(per)}


def save_calendar(con, cal):
    now = int(time.time())
    with store.tx(con):
        con.execute("DELETE FROM session_calendar")
        for day, v in cal["sessions"].items():
            con.execute("INSERT INTO session_calendar VALUES (?,?,?,?,?,?,?)",
                        (day, v["is_trading"], v["n_ref"], v["n_present"],
                         json.dumps(v["slots"]) if v["slots"] is not None else None, v["note"], now))


def load_calendar(con):
    cal = {}
    for day, tr, nref, npres, slots, note in con.execute(
            "SELECT session,is_trading,n_reference,n_present,expected_slots,note FROM session_calendar"):
        cal[day] = {"is_trading": tr, "slots": json.loads(slots) if slots else None, "note": note}
    return cal


# ------------------------------------------------------------------ per-bar / per-session checks
def check_bars(df, kind="equity"):
    """Pure per-bar checks on a frame(); returns list of (ts, session, flag, severity, detail)."""
    flags = []
    if df.empty:
        return flags
    price_cols = ["open", "high", "low", "close"]
    for r in df.itertuples():
        t, ss = int(r.ts), r.session
        vals = [getattr(r, c) for c in price_cols]
        if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals):
            flags.append((t, ss, "null_price", FATAL, "null OHLC field")); continue
        if min(vals) <= 0:
            flags.append((t, ss, "nonpositive_price", FATAL, str(vals)))
        o, h, l, c = vals
        if h < max(o, c) or l > min(o, c) or h < l:
            flags.append((t, ss, "ohlc_invalid", FATAL, f"o={o} h={h} l={l} c={c}"))
        if not r.on_grid:
            flags.append((t, ss, "off_grid", FATAL, "timestamp not on the 5-minute grid"))
        if not (0 <= r.slot < config.BARS_PER_SESSION):
            flags.append((t, ss, "off_session", WARN, f"slot {r.slot} outside 09:15-15:30 (excluded from datasets)"))
        if c > 0 and (h - l) / c > RANGE_BAR:
            flags.append((t, ss, "wide_range", WARN, f"(h-l)/c={(h - l) / c:.3f}"))
        if kind == "equity" and (r.volume is None or (isinstance(r.volume, float) and np.isnan(r.volume)) or r.volume == 0):
            flags.append((t, ss, "zero_volume", WARN, "volume missing/0 - treated as UNKNOWN (NaN) in features"))
    # duplicates / ordering (only detectable on raw frames; PK forbids duplicates in the DB)
    if df["ts"].duplicated().any():
        for t in df.loc[df["ts"].duplicated(keep=False), "ts"].unique():
            flags.append((int(t), None, "duplicate_ts", FATAL, "duplicate timestamp"))
    if not df["ts"].is_monotonic_increasing:
        flags.append((int(df["ts"].iloc[0]), None, "unordered_ts", FATAL, "timestamps not ascending"))
    # jumps
    d = df[df["slot"].between(0, config.BARS_PER_SESSION - 1) & df["on_grid"]].sort_values("ts")
    if len(d) > 1 and (d[["open", "close"]] > 0).all().all():
        prev_c = d["close"].shift(1)
        same = d["session"] == d["session"].shift(1)
        lr = np.log(d["open"] / prev_c)
        for r, v, sm in zip(d.itertuples(), lr, same):
            if np.isnan(v):
                continue
            if sm and abs(v) > JUMP_BAR:
                flags.append((int(r.ts), r.session, "abnormal_jump", WARN, f"|ln(open/prev close)|={abs(v):.3f} inside session"))
            if (not sm) and abs(v) > CORP_ACTION_GAP:
                flags.append((int(r.ts), r.session, "possible_unadjusted_corporate_action", FATAL,
                              f"overnight gap {v:+.3f} - review split/bonus adjustment"))
    return flags


def check_symbol(con, symbol, cal, interval=config.INTERVAL, ref_zero_vol=None):
    kind = (con.execute("SELECT kind FROM instruments WHERE symbol=?", (symbol,)).fetchone() or ("equity",))[0]
    df = frame(store.load_candles(con, symbol, interval))
    flags = check_bars(df, kind)
    sess_flags = {}                      # session -> list of reasons (fatal)
    for t, ss, fl, sev, det in flags:
        if sev == FATAL and ss:
            sess_flags.setdefault(ss, set()).add(fl)
    n_by = df.groupby("session").size().to_dict() if not df.empty else {}
    first_session = min(n_by) if n_by else None
    last_session = max(n_by) if n_by else None
    # chunk-level verification outcome
    bad_chunks = []
    if first_session:
        for cs, ce, st in con.execute("SELECT chunk_start,chunk_end,status FROM fetch_log WHERE symbol=? AND interval=?", (symbol, interval)):
            if st not in ("ok", "empty") and not (st == "late_start" and cs <= first_session <= ce):
                bad_chunks.append((cs, ce, st))
    for cs, ce, st in bad_chunks:
        for day in cal:
            if cs <= day <= ce:
                sess_flags.setdefault(day, set()).add(f"chunk_{st}")
    now = int(time.time())
    extra = []
    sessions_out = []
    bars_by_session = {k: g for k, g in df.groupby("session")} if not df.empty else {}
    for day, c in sorted(cal.items()):
        if first_session is None or day < first_session or day > last_session:
            continue
        got = bars_by_session.get(day)
        reasons = set(sess_flags.get(day, set()))
        if not c["is_trading"]:
            if got is not None and len(got):
                reasons.add("bars_on_closed_session")
                extra.append((int(got["ts"].iloc[0]), day, "bars_on_closed_session", FATAL, "bars on consensus non-trading day"))
            continue
        slots = set(c["slots"] or [])
        if not set(range(config.USABLE_SLOTS)) <= slots:
            reasons.add("nonstandard_session_structure")
            extra.append((int(pd.Timestamp(day, tz="Asia/Kolkata").timestamp()), day, "nonstandard_session_structure", FATAL,
                          f"consensus grid lacks slots in 0..{config.USABLE_SLOTS - 1} ({len(slots)} slots)"))
        have = set(got.loc[got["slot"].between(0, config.BARS_PER_SESSION - 1) & got["on_grid"], "slot"]) if got is not None else set()
        if got is None or not len(got):
            reasons.add("missing_session")
            extra.append((int(pd.Timestamp(day, tz="Asia/Kolkata").timestamp()), day, "missing_session", FATAL, "trading session with no bars"))
        else:
            miss = sorted(slots - have)
            if miss:
                reasons.add("missing_bar")
                extra.append((int(got["ts"].iloc[0]), day, "missing_bar", FATAL, f"{len(miss)} expected bars missing, slots {miss[:8]}"))
        sessions_out.append((symbol, interval, day, int(len(got)) if got is not None else 0,
                             0 if reasons else 1, ",".join(sorted(reasons)) or None, now))
    all_flags = flags + extra
    with store.tx(con):
        con.execute("DELETE FROM quality_flags WHERE symbol=? AND interval=? AND flag!='revised_bar'", (symbol, interval))
        con.executemany("INSERT OR REPLACE INTO quality_flags VALUES (?,?,?,?,?,?,?,?)",
                        [(symbol, interval, t, ss, fl, sev, det, now) for t, ss, fl, sev, det in all_flags])
        con.execute("DELETE FROM session_quality WHERE symbol=? AND interval=?", (symbol, interval))
        con.executemany("INSERT INTO session_quality VALUES (?,?,?,?,?,?,?)", sessions_out)
    nver = sum(r[4] for r in sessions_out)
    counts = {}
    for _, _, fl, sev, _ in all_flags:
        counts[fl] = counts.get(fl, 0) + 1
    return {"symbol": symbol, "sessions": len(sessions_out), "verified": nver, "unverified": len(sessions_out) - nver,
            "flag_counts": counts, "bad_chunks": bad_chunks}


def verified_sessions(con, symbol, interval=config.INTERVAL):
    return {r[0] for r in con.execute("SELECT session FROM session_quality WHERE symbol=? AND interval=? AND verified=1", (symbol, interval))}


def run(con, symbols, ref_symbols=None, interval=config.INTERVAL):
    refs = ref_symbols or [r[0] for r in con.execute("SELECT symbol FROM instruments WHERE kind='equity'")]
    cal = derive_calendar(con, refs, interval)
    if not cal["ok"]:
        return {"ok": False, "reason": cal["reason"]}
    save_calendar(con, cal)
    return {"ok": True, "calendar_sessions": len(cal["sessions"]), "trading_sessions": sum(v["is_trading"] for v in cal["sessions"].values()),
            "per_symbol": [check_symbol(con, s, load_calendar(con), interval) for s in symbols]}
