"""Symbol onboarding: extend range forecasts to any NSE equity WITHOUT retraining, but only on evidence.

For a new symbol: fetch ~60 days of 5m bars (1-2 provider requests), run the data-quality pipeline, then
FORWARD-validate the production model on that symbol's bars from sessions AFTER the model's weight-training
window (meta.train_sessions[1]). Nothing is fitted. A symbol is `validated` only if, on those forward rows:
  - >= MIN_ROWS scored rows and >= MIN_SESSIONS sessions (enough clean data),
  - conformal coverage at 50/80/95% within COV_TOL_MEAN (mean over horizons) and COV_TOL_EACH (each horizon),
  - mean Winkler(80%) no worse than the Gaussian persistence baseline,
  - zero-volume bars <= MAX_ZERO_VOL of bars and >= MIN_VERIFIED_FRAC of sessions verified.
Otherwise it is `failed` with explicit reasons (e.g. illiquid, too little data) and no forecast is issued.
Validated non-pilot symbols receive RANGE forecasts only: the directional edge was validated on the pilot
universe and is not extended to symbols without their own evidence.
"""
import copy
import json
import pickle
import queue
import threading
import time

import numpy as np
import pandas as pd

from . import collector, config, dataset, evaluate, quality, regimes, registry, store

MIN_ROWS = 1000
MIN_SESSIONS = 15
COV_TOL_MEAN = 0.05
COV_TOL_EACH = 0.08
MAX_ZERO_VOL = 0.05
MIN_VERIFIED_FRAC = 0.90
FETCH_DAYS = 70
RETRY_FAILED_AFTER = 24 * 3600


def _load(prod):
    from .inference import _load_artifact
    return _load_artifact(prod)


def symbol_status(con, symbol, prod, meta):
    """-> (state, reasons): pilot | validated | failed | unknown"""
    if symbol in meta.get("validated_symbols", []):
        return "pilot", []
    r = con.execute("SELECT status, reasons_json, validated_at FROM symbol_validation WHERE symbol=? AND model_version=?",
                    (symbol, prod["model_version"])).fetchone()
    if r is None:
        return "unknown", []
    reasons = json.loads(r[1] or "[]")
    if r[0] == "failed" and time.time() - r[2] > RETRY_FAILED_AFTER:
        return "unknown", []                           # allow a fresh attempt after a day
    return r[0], reasons


def _gaussian_cols(oos_rows, horizons):
    from scipy.stats import norm
    cols = {}
    sig = oos_rows["rv36"].values
    for h in horizons:
        cols[f"persistence_ret_{h}"] = np.zeros(len(oos_rows))
        for lv in (50, 80, 95):
            z = norm.ppf(0.5 + lv / 200.0)
            cols[f"persistence_lo{lv}_{h}"], cols[f"persistence_hi{lv}_{h}"] = -z * sig * np.sqrt(h), z * sig * np.sqrt(h)
    return pd.DataFrame(cols, index=oos_rows.index)


def validate_forward(con, symbol, art):
    """Returns (ok, reasons, metrics). Raises nothing for data problems - they become failure reasons."""
    from .run_walkforward import regime_stability, wide_predictions
    meta, ens0 = art["meta"], art["ensemble"]
    horizons = config.HORIZONS
    try:
        M, fcols = dataset.build_matrix(con, symbol, index_symbol=meta.get("index_symbol"))
    except dataset.UnverifiedDataError as e:
        return False, [f"no_verified_data: {e}"], {}
    M = pd.concat([M, regimes.classify(M)], axis=1)
    M["regime_stable"] = regime_stability(M)
    Mfull = M
    warm = Mfull[Mfull["warm"]]
    test = warm[warm["session"] > meta["train_sessions"][1]]
    n_sess = int(test["session"].nunique())
    ver = len(quality.verified_sessions(con, symbol))
    tot = con.execute("SELECT count(*) FROM session_quality WHERE symbol=? AND interval=?", (symbol, config.INTERVAL)).fetchone()[0]
    nbars = con.execute("SELECT count(*) FROM candles WHERE symbol=? AND interval=?", (symbol, config.INTERVAL)).fetchone()[0]
    nzero = con.execute("SELECT count(*) FROM quality_flags WHERE symbol=? AND flag='zero_volume'", (symbol,)).fetchone()[0]
    metrics = {"forward_rows": int(len(test)), "forward_sessions": n_sess, "verified_frac": ver / max(tot, 1), "zero_volume_frac": nzero / max(nbars, 1)}
    reasons = []
    if len(test) < MIN_ROWS or n_sess < MIN_SESSIONS:
        reasons.append(f"insufficient_forward_data: {len(test)} rows / {n_sess} sessions (need {MIN_ROWS} / {MIN_SESSIONS})")
    if metrics["verified_frac"] < MIN_VERIFIED_FRAC:
        reasons.append(f"data_quality: only {metrics['verified_frac']:.0%} of sessions verified")
    if metrics["zero_volume_frac"] > MAX_ZERO_VOL:
        reasons.append(f"illiquid: {metrics['zero_volume_frac']:.1%} of bars have zero/missing volume")
    if reasons and len(test) < 200:
        return False, reasons, metrics
    ens = copy.copy(ens0)
    ens.models = {n: copy.copy(m) for n, m in ens0.models.items()}
    ens.models["gru"].attach(Mfull)
    pred = ens.predict(test, test["trend"])
    oos = pd.concat([test[["symbol", "session", "rv36"] + [c for c in test.columns if c.startswith("y_")]],
                     wide_predictions(test, pred, "ens", horizons)], axis=1)
    oos = pd.concat([oos, _gaussian_cols(oos, horizons)], axis=1)
    cov = {lv: [] for lv in (50, 80, 95)}
    wink_m, wink_b = [], []
    for h in horizons:
        sc = evaluate.score(oos, "ens", h)
        for lv in cov:
            cov[lv].append(sc.get(f"cov{lv}", np.nan))
        y, sig = oos[f"y_ret_{h}"].values, oos["rv36"].values
        ok = ~np.isnan(y) & (sig > 0) & oos[f"ens_lo80_{h}"].notna().values
        wink_m.append(float(np.mean(evaluate.winkler(oos[f"ens_lo80_{h}"].values[ok], oos[f"ens_hi80_{h}"].values[ok], y[ok], 0.2) / sig[ok])))
        wink_b.append(float(np.mean(evaluate.winkler(oos[f"persistence_lo80_{h}"].values[ok], oos[f"persistence_hi80_{h}"].values[ok], y[ok], 0.2) / sig[ok])))
    for lv, vals in cov.items():
        vals = np.array(vals, float)
        metrics[f"coverage{lv}"] = [round(float(v), 4) for v in vals]
        if np.isnan(vals).any():
            reasons.append(f"coverage{lv}: intervals unavailable")
            continue
        if abs(vals.mean() - lv / 100.0) > COV_TOL_MEAN or np.abs(vals - lv / 100.0).max() > COV_TOL_EACH:
            reasons.append(f"coverage_off: {lv}% intervals covered {vals.mean():.1%} (nominal {lv}%)")
    metrics["winkler80_model"], metrics["winkler80_gaussian"] = round(float(np.mean(wink_m)), 4), round(float(np.mean(wink_b)), 4)
    if np.mean(wink_m) > np.mean(wink_b):
        reasons.append("interval_score: not better than a Gaussian baseline")
    return (not reasons), reasons, metrics


def onboard_symbol(symbol, client=None, con=None, log=print):
    """Fetch, quality-check and forward-validate one symbol. Returns the stored status dict."""
    con = con or store.connect()
    prod = registry.production_model(con)
    if prod is None:
        return {"symbol": symbol, "status": "failed", "reasons": ["no_production_model"]}
    art = _load(prod)
    if symbol in art["meta"]["validated_symbols"]:
        return {"symbol": symbol, "status": "pilot", "reasons": []}
    status, reasons, metrics = "failed", [], {}
    try:
        if client is None:
            from . import live_ingest
            with live_ingest._lock:
                client = live_ingest._get_client()
                res = collector.backfill_symbol(client, con, symbol, years=FETCH_DAYS / 365.25)
        else:
            res = collector.backfill_symbol(client, con, symbol, years=FETCH_DAYS / 365.25)
        if res.get("error"):
            reasons = [f"no_data_source: {res['error']}"]
        else:
            quality.check_symbol(con, symbol, quality.load_calendar(con))
            ok, reasons, metrics = validate_forward(con, symbol, art)
            status = "validated" if ok else "failed"
    except Exception as e:                                       # never let one symbol crash a batch
        reasons = [f"onboarding_error: {type(e).__name__}: {str(e)[:120]}"]
    with con:
        con.execute("INSERT OR REPLACE INTO symbol_validation VALUES (?,?,?,?,?,?)",
                    (symbol, prod["model_version"], status, json.dumps(reasons), json.dumps(metrics), int(time.time())))
    log(f"[onboard] {symbol}: {status} {reasons[:2]}")
    return {"symbol": symbol, "status": status, "reasons": reasons, "metrics": metrics}


# ------------------------------------------------------------------ on-demand queue (API)
_q = queue.Queue()
_pending = set()
_plock = threading.Lock()
_worker = None


def coverage(con, model_version):
    """Counts for the coverage endpoint: how many symbols can currently be forecast."""
    rows = con.execute("SELECT status, count(*) FROM symbol_validation WHERE model_version=? GROUP BY status", (model_version,)).fetchall()
    out = {s: n for s, n in rows}
    with _plock:
        out["pending"] = len(_pending)
    return out


def is_running(symbol):
    with _plock:
        return symbol in _pending


def onboard_async(symbol):
    """Queue a first-time onboarding (single worker: provider calls stay serialized and throttled)."""
    global _worker
    with _plock:
        if symbol in _pending:
            return True
        _pending.add(symbol)
        _q.put(symbol)
        if _worker is None:
            _worker = threading.Thread(target=_run, daemon=True, name="forecast-onboarding")
            _worker.start()
    return True


def _run():
    while True:
        sym = _q.get()
        try:
            onboard_symbol(sym)
        finally:
            with _plock:
                _pending.discard(sym)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--all-nse", action="store_true", help="every NSE name in cache/nse_company_names.json")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    syms = a.symbols or []
    if a.all_nse:
        import re
        names = list(json.load(open(config.ROOT + "/cache/nse_company_names.json")))
        # the app's curated registry (the names users actually open) goes first, then everything else
        seed = re.findall(r'\{"symbol": "([A-Z0-9&\-]+)"', open(config.ROOT + "/app.py", encoding="utf-8").read()[:60000])
        syms += [s for s in dict.fromkeys(seed) if s in set(names)] + [n for n in names if n not in set(seed)]
        syms = list(dict.fromkeys(syms))
    if a.limit:
        syms = syms[: a.limit]
    c = collector.AngelHistory(min_delay=1.5, max_delay=3.0, cooldown=6.0)
    c.login()
    con = store.connect()
    seen = {r[0] for r in con.execute("SELECT symbol FROM symbol_validation WHERE status IN ('validated','failed')")}
    for s in syms:
        if s in seen:
            continue
        onboard_symbol(s, client=c, con=con)
