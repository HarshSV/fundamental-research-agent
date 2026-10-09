"""Daily walk-forward evaluation (pooled across the configured universe, strict chronological folds).

python -m forecast.daily.run_walkforward --horizons short   # +1/+3/+5/+10/+20 trading days
python -m forecast.daily.run_walkforward --horizons long    # 63/126/252/504 (investigation)

Per fold: train < [embargo] < calibration < [embargo] < test, in TRADING DAYS, with embargo >= the longest horizon, so
no label window (which looks h days forward) can overlap a later block. Everything fitted (models, isotonic maps,
conformal margins, ensemble weights, baseline sign statistics) uses the train/calibration blocks only.
"""
import argparse
import os
import time

import numpy as np
import pandas as pd

from .. import config, store, walkforward
from ..ensemble import Ensemble
from . import baselines, dataset, universe
from .labels import LONG_H, SHORT_H
from .models import HarEmpiricalForecaster, make_gbm

PROFILES = {
    # min_train, cal, test, embargo (trading days), gbm stride
    "short": dict(horizons=SHORT_H, min_train=1500, cal=120, test=250, embargo=20, stride=2),
    "long": dict(horizons=LONG_H, min_train=2500, cal=252, test=504, embargo=504, stride=10),
}


def wide(test, preds, prefix, horizons):
    cols = {}
    for h in horizons:
        p = preds[h]
        cols[f"{prefix}_ret_{h}"], cols[f"{prefix}_pup_{h}"] = p["ret_med"], p["p_up"]
        for lv, iv in p["intervals"].items():
            if iv is not None:
                cols[f"{prefix}_lo{lv}_{h}"], cols[f"{prefix}_hi{lv}_{h}"] = iv
    return pd.DataFrame(cols, index=test.index)


def run(profile="short", symbols=None, models=("gbm", "har", "ens"), log=print, overrides=None, tag=None):
    P = dict(PROFILES[profile], **(overrides or {}))
    horizons = P["horizons"]
    con = store.connect()
    cfg = universe.load()
    symbols = symbols or cfg["symbols"]
    M, fcols, skipped = dataset.load_pooled(con, symbols, horizons, log)
    log(f"[daily] pooled rows={len(M)} symbols={M['symbol'].nunique()} features={len(fcols)} skipped={skipped}")
    dates = sorted(M["date"].unique())
    folds = walkforward.make_folds(dates, P["min_train"], P["cal"], P["test"], embargo=P["embargo"])
    if not folds:
        raise SystemExit("not enough verified days for one fold")
    out = []
    for k, fo in enumerate(folds):
        walkforward.assert_no_overlap(fo)
        tr, ca, te = (M[M["date"].isin(fo[x])] for x in ("train", "cal", "test"))
        t0 = time.time()
        fitted, parts = {}, []
        if "gbm" in models or "ens" in models:
            fitted["gbm"] = make_gbm(fcols, horizons, stride=P["stride"]).fit(tr, ca)
        if "har" in models or "ens" in models:
            fitted["har"] = HarEmpiricalForecaster(fcols, horizons).fit(tr, ca)
        for name in ("gbm", "har"):
            if name in models:
                parts.append(wide(te, fitted[name].predict(te), name, horizons))
        if "ens" in models:
            ens = Ensemble(fitted, horizons).fit_weights(ca)
            parts.append(wide(te, ens.predict(te), "ens", horizons))
        parts.append(baselines.baseline_wide(tr, te, horizons))
        keep = ["symbol", "date", "month", "year", "vol_regime", "market_regime", "rv20", "close"] + [c for c in te.columns if c.startswith("y_")]
        o = pd.concat([te[keep]] + parts, axis=1)
        o["fold"] = k
        out.append(o)
        log(f"[fold {k}] train {fo['train'][0]}..{fo['train'][-1]} | test {fo['test'][0]}..{fo['test'][-1]} | rows tr/ca/te "
            f"{len(tr)}/{len(ca)}/{len(te)} | {time.time() - t0:.0f}s")
    oos = pd.concat(out, ignore_index=True)
    path = os.path.join(config.DATA_DIR, f"daily_oos_{tag or profile}.parquet")
    oos.to_parquet(path)
    log(f"[saved] {path} ({len(oos)} rows, {oos['symbol'].nunique()} symbols, {oos['date'].min()}..{oos['date'].max()})")
    return oos


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizons", choices=list(PROFILES), default="short")
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--cal", type=int)
    ap.add_argument("--test", type=int)
    ap.add_argument("--min-train", type=int)
    ap.add_argument("--tag")
    a = ap.parse_args()
    ov = {k: v for k, v in (("cal", a.cal), ("test", a.test), ("min_train", a.min_train)) if v}
    run(a.horizons, a.symbols, overrides=ov, tag=a.tag)
