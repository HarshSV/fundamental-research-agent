"""Live inference: one forecast per COMPLETED candle, through the same feature engine as training.

Safety: every failure mode returns NO_RELIABLE_FORECAST with explicit reasons - a forecast is never
fabricated. Gates: no production model / model artifact missing / validation stale / symbol not in
the validated universe / stale or unverified bars / insufficient contiguous history / features
invalid / input outside the training distribution / nonstandard session / horizon past session end.
"""
import copy
import datetime as dt
import os
import pickle
import time

import numpy as np
import pandas as pd

from . import config, confidence, evidence, quality, regimes, registry, store, tracking
from .features import WARMUP_BARS, compute_features, feature_columns
from .labels import reconstruct_bars
from .run_walkforward import regime_stability
from .timeutil import session_date, slot_ts

VALIDATION_MAX_AGE_DAYS = 45
HISTORY_DAYS = 20
_CACHE = {}


def _load_artifact(prod):
    key = prod["model_version"]
    if key not in _CACHE:
        with open(prod["artifact_path"], "rb") as f:
            _CACHE[key] = pickle.load(f)
    return _CACHE[key]


def expected_last_bar_ts(as_of_ts):
    """Open ts of the bar that must be the newest stored one: the last completed bar, capped at the last USABLE
    slot (bars after it are never used, so after 15:15 IST the newest usable bar stays 15:10)."""
    cur = session_date(as_of_ts - config.BAR_SECONDS)
    return min(as_of_ts - config.BAR_SECONDS, slot_ts(cur, config.USABLE_SLOTS - 1))


def last_complete_boundary(now_ts):
    return int(now_ts // config.BAR_SECONDS) * config.BAR_SECONDS


def live_window(con, symbol, as_of_ts, index_symbol="NIFTY 50"):
    """Completed bars ending at as_of_ts with segment ids; returns (bars, issues)."""
    issues = []
    rows = store.load_candles(con, symbol, config.INTERVAL, as_of_ts - HISTORY_DAYS * 86400, as_of_ts - config.BAR_SECONDS)
    rows = [r for r in rows if r[0] + config.BAR_SECONDS <= as_of_ts]
    df = quality.frame(rows)
    if df.empty:
        return df, ["no_bars"]
    df = df[df["on_grid"] & df["slot"].between(0, config.USABLE_SLOTS - 1)].reset_index(drop=True)
    fatal_sessions = {s for (_, s, f, sev, _) in quality.check_bars(df) if sev == quality.FATAL and s}
    cur = session_date(as_of_ts - config.BAR_SECONDS)
    exp_slot = (as_of_ts - slot_ts(cur, 0)) // config.BAR_SECONDS - 1          # last completed slot of the current session
    cal = quality.load_calendar(con)
    idx_days = {r[0] for r in con.execute("SELECT DISTINCT date(ts+19800,'unixepoch') FROM candles WHERE symbol=? AND interval=? AND ts>=?",
                                          (index_symbol, config.INTERVAL, as_of_ts - HISTORY_DAYS * 86400))} if index_symbol else set()
    by = {k: g for k, g in df.groupby("session")}
    seg_of, seg = {}, 0
    first = min(by)
    day = dt.date.fromisoformat(first)
    end = dt.date.fromisoformat(cur)
    while day <= end:
        d = day.isoformat()
        day += dt.timedelta(days=1)
        if d in cal:
            trading = bool(cal[d]["is_trading"])
        else:
            trading = (d in idx_days) if idx_days else (pd.Timestamp(d).weekday() < 5)
        if not trading and d not in by:
            continue
        g = by.get(d)
        ok = g is not None and d not in fatal_sessions
        if ok and d != cur:
            ok = set(range(config.USABLE_SLOTS)) <= set(g["slot"])
        if ok and d == cur:
            ok = list(g["slot"]) == list(range(len(g))) and (len(g) - 1) == min(exp_slot, config.USABLE_SLOTS - 1)
            if not ok:
                issues.append("current_session_bars_stale_or_gappy")
        if ok:
            seg_of[d] = seg
        else:
            seg += 1
    df["seg"] = df["session"].map(seg_of)
    return df.dropna(subset=["seg"]).astype({"seg": int}).reset_index(drop=True), issues


def _withheld(symbol, as_of_ts, reasons, prod=None, **extra):
    h_rows = [{"horizon": h, "forecast_timestamp": as_of_ts + (h - 1) * config.BAR_SECONDS, "confidence": "NO_RELIABLE_FORECAST",
               "confidence_score": 0.0, "status": "withheld", "reasons": reasons} for h in config.HORIZONS]
    return {"forecast_id": tracking.new_forecast_id(), "symbol": symbol, "timeframe": config.INTERVAL, "as_of_ts": as_of_ts,
            "status": "NO_RELIABLE_FORECAST", "reasons": reasons, "regime": None,
            "model_version": (prod or {}).get("model_version"), "feature_version": config.FEATURE_VERSION,
            "ensemble_version": (prod or {}).get("model_version"), "forecasts": h_rows, **extra}


def forecast_payload(con, symbol, as_of_ts=None, persist=True):
    """Core entry. as_of_ts = close time of the last completed candle (default: latest completed boundary)."""
    now = time.time()
    as_of_ts = int(as_of_ts if as_of_ts is not None else last_complete_boundary(now))
    prod = registry.production_model(con)
    if prod is None:
        return _withheld(symbol, as_of_ts, ["no_production_model: no model has passed the promotion gate"])
    try:
        art = _load_artifact(prod)
    except Exception as e:                                         # missing/corrupt artifact
        return _withheld(symbol, as_of_ts, [f"model_unavailable: {type(e).__name__}"], prod)
    meta, ens0 = art["meta"], art["ensemble"]
    if (now - prod["trained_at"]) / 86400 > VALIDATION_MAX_AGE_DAYS:
        return _withheld(symbol, as_of_ts, [f"validation_stale: model older than {VALIDATION_MAX_AGE_DAYS} days"], prod)
    from . import onboarding
    sym_state, sym_reasons = onboarding.symbol_status(con, symbol, prod, meta)
    if sym_state == "unknown":
        return _withheld(symbol, as_of_ts, ["symbol_onboarding: first-time validation for this symbol is in progress"], prod)
    if sym_state == "failed":
        return _withheld(symbol, as_of_ts, ["symbol_not_validated: " + "; ".join(sym_reasons[:2])], prod)
    # Directional skill was validated on the pilot universe only; other validated symbols get RANGE forecasts only.
    dir_ok = sym_state == "pilot"
    bars, issues = live_window(con, symbol, as_of_ts, meta.get("index_symbol"))
    if bars.empty or issues:
        return _withheld(symbol, as_of_ts, ["data_not_usable: " + ",".join(issues or ["no_bars"])], prod)
    if bars["ts"].iloc[-1] != expected_last_bar_ts(as_of_ts):
        return _withheld(symbol, as_of_ts, ["stale_bars: latest stored completed bar is not the latest expected bar"], prod)
    idx = None
    if meta.get("index_symbol"):
        try:
            from .dataset import load_verified_index
            idx = load_verified_index(con, meta["index_symbol"])
        except Exception:
            idx = None
    if idx is not None and not (idx["ts"] == bars["ts"].iloc[-1]).any():
        # live inputs must match training inputs: the NIFTY context bar for this candle has to exist
        return _withheld(symbol, as_of_ts, ["index_context_stale: NIFTY bar for the latest candle not available yet"], prod)
    feats = compute_features(bars, idx)
    cols = meta["feature_cols"]
    missing = [c for c in cols if c not in feats.columns]
    if missing:
        return _withheld(symbol, as_of_ts, [f"features_invalid: missing {missing[:3]}"], prod)
    last = feats.iloc[-1]
    if not bool(last["warm"]):
        return _withheld(symbol, as_of_ts, [f"insufficient_history: {int(last['seg_pos'])}/{WARMUP_BARS} contiguous verified bars"], prod)
    core = ["rv36", "ret1", "rsi14", "atr14", "ema21_dist"]
    if any(pd.isna(last[c]) for c in core) or not (last["rv36"] > 0):
        return _withheld(symbol, as_of_ts, ["features_invalid: core feature NaN or zero volatility"], prod)

    # ---- model inputs: window frame (GRU needs the previous 23 rows) ----
    W = feats.copy()
    W["symbol"] = symbol
    W = pd.concat([W, regimes.classify(W)], axis=1)
    W["regime_stable"] = regime_stability(W)
    row = W.iloc[[-1]]
    ens = copy.copy(ens0)
    ens.models = {n: copy.copy(m) for n, m in ens0.models.items()}
    ens.models["gru"].attach(W)
    if not ens.models["gru"].seq_ok[-1]:
        return _withheld(symbol, as_of_ts, ["insufficient_history: sequence window incomplete"], prod)
    in_dist = confidence.in_distribution(row, meta["envelope"])
    pred = ens.predict(row, row["trend"])
    gbm = ens.models["gbm"]
    close0 = float(bars["close"].iloc[-1])
    sig = float(last["rv36"])
    slot_now = int(last["slot"])
    valid = (meta.get("gate") or {})
    dirv, perf = valid.get("direction_validated", {}), valid.get("perf_skill", {})
    out_rows, rets, wups, wdns, per_h = [], [], [], [], {}
    for h in config.HORIZONS:
        p = pred[h]
        gate_reasons = []
        if slot_now + h > config.USABLE_SLOTS - 1:
            gate_reasons.append("horizon_beyond_session_end")
        if not bool(in_dist[0]):
            gate_reasons.append("input_outside_training_distribution")
        agree, ev = evidence.shap_evidence(gbm, row, h)
        lo, hi = (p["intervals"][80] if p["intervals"].get(80) else (np.array([np.nan]), np.array([np.nan])))
        a = confidence.assess(p["p_up"], [v["p_up"] for v in p["per_model"].values()], [v["ret_med"] for v in p["per_model"].values()],
                              p["ret_med"], (hi - lo) / sig, row["regime_stable"].values, agree,
                              float(perf.get(str(h), perf.get(h, 0.0))) if (dir_ok and dirv.get(str(h), dirv.get(h, False))) else 0.0,
                              1.0 - 0.3 * row["rel_vol"].isna().values, gated=np.array([bool(gate_reasons)]))
        level = str(a["level"][0]) if dir_ok else "NO_RELIABLE_FORECAST"
        withheld = level == "NO_RELIABLE_FORECAST"
        per_h[h] = {"p": p, "level": level, "score": float(a["score"][0]), "comp": {k: float(v[0]) for k, v in a["components"].items()},
                    "reasons": gate_reasons, "evidence": ev[0], "agree": float(agree[0])}
        rets.append(float(p["ret_med"][0])); wups.append(float(p["wick_up"][0]) if p["wick_up"] is not None else 0.0)
        wdns.append(float(p["wick_dn"][0]) if p["wick_dn"] is not None else 0.0)
    bars_pred = reconstruct_bars(close0, rets, wups, wdns)
    for h in config.HORIZONS:
        d = per_h[h]
        p = d["p"]
        hard = bool(d["reasons"])
        withheld = d["level"] == "NO_RELIABLE_FORECAST"
        intervals = None
        if not hard:
            intervals = {str(lv): [float(np.exp(iv[0][0]) * close0), float(np.exp(iv[1][0]) * close0)]
                         for lv, iv in p["intervals"].items() if iv is not None}
        b = bars_pred[h - 1]
        r = {"horizon": h, "forecast_timestamp": as_of_ts + (h - 1) * config.BAR_SECONDS, "confidence": d["level"],
             "confidence_score": d["score"], "status": "withheld" if hard else ("range_only" if withheld else "ok"),
             "reasons": d["reasons"] or ([] if not withheld else ["confidence_below_threshold" if dir_ok else "direction_not_validated_for_symbol"]),
             "direction_validated": bool(dir_ok and dirv.get(str(h), dirv.get(h, False))),
             "intervals": intervals, "interval_unit": "price", "confidence_components": d["comp"]}
        if not hard and not withheld:
            r.update({"open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"],
                      "predicted_return": float(p["ret_med"][0]), "direction_probability": float(p["p_up"][0]),
                      "model_agreement": {n: float(v["p_up"][0]) for n, v in p["per_model"].items()},
                      "evidence": {"supporting": d["evidence"]["for"], "opposing": d["evidence"]["against"], "shap_agreement": d["agree"],
                                   "note": "attribution of the model output, not causal proof"}})
        out_rows.append(r)
    reg = W.iloc[-1]
    if any(r["status"] == "ok" for r in out_rows):
        status, top_reasons = "OK", []
    elif any(r["status"] == "range_only" for r in out_rows):
        status, top_reasons = "RANGE_ONLY", ["no_directional_edge: confidence below threshold - showing the validated expected range only"]
    else:
        status, top_reasons = "NO_RELIABLE_FORECAST", []
    payload = {"forecast_id": tracking.new_forecast_id(), "symbol": symbol, "timeframe": config.INTERVAL, "as_of_ts": as_of_ts,
               "status": status, "reasons": top_reasons, "regime": str(reg["regime"]), "regime_detail": {"trend": reg["trend"], "vol": reg["vol"], "breakout": reg["breakout"]},
               "model_version": prod["model_version"], "feature_version": config.FEATURE_VERSION, "ensemble_version": prod["model_version"],
               "current_candle": {"time": int(bars["ts"].iloc[-1]), "open": float(bars["open"].iloc[-1]), "high": float(bars["high"].iloc[-1]),
                                  "low": float(bars["low"].iloc[-1]), "close": close0, "volume": None if pd.isna(bars["volume"].iloc[-1]) else float(bars["volume"].iloc[-1])},
               "forecasts": out_rows,
               "disclaimer": "Probabilistic estimate from historical patterns. Not a prediction of certainty; future prices cannot be known."}
    # Only REAL forecasts are persisted. A withheld payload (stale data, etc.) is not a forecast and must not
    # occupy the (symbol, as_of, horizon, model) key that the real forecast will need moments later.
    if persist and status in ("OK", "RANGE_ONLY"):
        tracking.save_forecast(con, payload)
    return payload
