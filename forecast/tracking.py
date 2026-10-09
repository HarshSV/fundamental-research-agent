"""Forecast persistence, actual-vs-predicted matching and monitoring statistics.

Forecast rows are append-only: the original prediction is NEVER overwritten (unique key +
INSERT OR IGNORE; a duplicate is reported, not replaced). Evaluations are written once the real
candle that the forecast targeted has completed.
"""
import json
import time
import uuid

import numpy as np

from . import config


def new_forecast_id():
    return uuid.uuid4().hex


def save_forecast(con, fc):
    """fc: output of inference.forecast_payload(). Returns number of newly inserted horizon rows."""
    n = 0
    now = int(time.time())
    with con:
        for f in fc["forecasts"]:
            cur = con.execute(
                "INSERT OR IGNORE INTO forecasts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (fc["forecast_id"], fc["symbol"], fc["timeframe"], now, fc["as_of_ts"], f["forecast_timestamp"], f["horizon"],
                 f.get("open"), f.get("high"), f.get("low"), f.get("close"), f.get("predicted_return"),
                 f.get("direction_probability"), json.dumps(f.get("intervals")), f["confidence"], f.get("confidence_score"),
                 fc.get("regime"), fc.get("model_version"), fc.get("feature_version"), fc.get("ensemble_version"),
                 json.dumps(f.get("evidence"))))
            n += cur.rowcount
    return n


def evaluate_pending(con, symbol=None, interval=config.INTERVAL):
    """Match forecasts to the actual candle that occurred and store errors. Idempotent."""
    q = ("SELECT f.forecast_id,f.symbol,f.as_of_ts,f.forecast_timestamp,f.horizon,f.predicted_close,f.predicted_return,"
         "f.direction_probability,f.intervals_json FROM forecasts f LEFT JOIN forecast_evaluations e "
         "ON e.forecast_id=f.forecast_id AND e.horizon=f.horizon WHERE e.forecast_id IS NULL")
    args = []
    if symbol:
        q += " AND f.symbol=?"; args.append(symbol)
    now = int(time.time())
    done = 0
    for fid, sym, as_of, ts, h, pclose, pret, pup, ints in con.execute(q, args).fetchall():
        if ts + config.BAR_SECONDS > now:
            continue                                            # target candle not complete yet
        a = con.execute("SELECT open,high,low,close FROM candles WHERE symbol=? AND interval=? AND ts=?", (sym, interval, ts)).fetchone()
        # as_of = CLOSE time of the candle the forecast was made from (its open ts is one bar earlier)
        base = con.execute("SELECT close FROM candles WHERE symbol=? AND interval=? AND ts=?", (sym, interval, as_of - config.BAR_SECONDS)).fetchone()
        if a is None or base is None:
            continue                                            # actual candle not (yet) available: stay pending, never guess
        actual_ret = float(np.log(a[3] / base[0]))
        inside = {}
        for lv, iv in (json.loads(ints) or {}).items():
            # stored intervals are PRICE levels for the target bar's close -> compare with the actual close
            inside[lv] = None if iv is None else bool(iv[0] <= a[3] <= iv[1])
        direction_correct = None
        if pup is not None and actual_ret != 0:
            direction_correct = int((pup > 0.5) == (actual_ret > 0))
        with con:
            con.execute("INSERT OR IGNORE INTO forecast_evaluations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (fid, h, now, a[0], a[1], a[2], a[3], None if pret is None else actual_ret - pret,
                         None if pclose is None else a[3] - pclose, direction_correct, json.dumps(inside)))
        done += 1
    return done


def monitoring_stats(con, symbol=None, last_n=500):
    """Rolling realised performance of the LIVE forecasts, by horizon / regime / symbol."""
    where, args = "", []
    if symbol:
        where, args = "WHERE f.symbol=?", [symbol]
    rows = con.execute(
        "SELECT f.symbol,f.horizon,f.regime,f.confidence,f.created_at,f.direction_probability,e.direction_correct,"
        "e.return_error,e.in_interval_json FROM forecasts f JOIN forecast_evaluations e "
        f"ON e.forecast_id=f.forecast_id AND e.horizon=f.horizon {where} ORDER BY f.created_at DESC LIMIT ?", args + [last_n * 5]).fetchall()
    out = {"n_evaluated": len(rows), "by_horizon": {}, "by_regime": {}, "by_symbol": {}, "by_confidence": {}}

    def agg(sub):
        dc = [r[6] for r in sub if r[6] is not None]
        re_ = [abs(r[7]) for r in sub if r[7] is not None]
        cov = {}
        for lv in ("50", "80", "95"):
            vals = [json.loads(r[8]).get(lv) for r in sub if r[8]]
            vals = [v for v in vals if v is not None]
            cov[lv] = float(np.mean(vals)) if vals else None
        return {"n": len(sub), "direction_accuracy": float(np.mean(dc)) if dc else None, "mae_return": float(np.mean(re_)) if re_ else None,
                "interval_coverage": cov}

    for key, idx in (("by_horizon", 1), ("by_regime", 2), ("by_symbol", 0), ("by_confidence", 3)):
        groups = {}
        for r in rows:
            groups.setdefault(r[idx], []).append(r)
        out[key] = {str(k): agg(v) for k, v in groups.items()}
    return out
