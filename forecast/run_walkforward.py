"""Walk-forward evaluation driver (pooled across symbols, time-ordered folds).

python -m forecast.run_walkforward --symbols RELIANCE TCS ... [--max-folds 6]
Writes data/forecast/oos_predictions.parquet and prints the report. Nothing here is synthetic: it
only runs on verified bars from the store.
"""
import argparse
import os
import time

import numpy as np
import pandas as pd

from . import baselines, config, dataset, regimes, store, walkforward
from . import confidence, evidence
from .ensemble import Ensemble
from .models_gbm import GBMForecaster
from .models_gru import GRUForecaster


def wide_predictions(test, preds, prefix, horizons):
    cols = {}
    for h in horizons:
        p = preds[h]
        cols[f"{prefix}_ret_{h}"] = p["ret_med"]
        cols[f"{prefix}_pup_{h}"] = p["p_up"]
        for lv, iv in p["intervals"].items():
            if iv is not None:
                cols[f"{prefix}_lo{lv}_{h}"], cols[f"{prefix}_hi{lv}_{h}"] = iv
        if "wick_up" in p:
            cols[f"{prefix}_wup_{h}"], cols[f"{prefix}_wdn_{h}"] = p["wick_up"], p["wick_dn"]
    return pd.DataFrame(cols, index=test.index)


def baseline_wide(train, test, horizons):
    res = baselines.baseline_predictions(train, test, horizons)
    cols = {}
    sig = test["rv36"].values
    for name, per_h in res.items():
        for h in horizons:
            cols[f"{name}_ret_{h}"] = per_h[h]["ret"]
            cols[f"{name}_pup_{h}"] = per_h[h]["p_up"]
            for lv, (lo, hi) in baselines.gaussian_intervals(per_h[h]["ret"], sig, h).items():
                cols[f"{name}_lo{lv}_{h}"], cols[f"{name}_hi{lv}_{h}"] = lo, hi
    return pd.DataFrame(cols, index=test.index)


def regime_stability(M, k=5):
    """1.0 if the trend|vol regime was unchanged over the last k bars (same symbol & segment), else 0.0."""
    same = np.ones(len(M), bool)
    for j in range(1, k + 1):
        ok = (M["symbol"].shift(j).values == M["symbol"].values) & (M["seg_pos"].shift(j).values == M["seg_pos"].values - j)             & (M["regime"].shift(j).values == M["regime"].values)
        same &= ok
    return same.astype(float)


def confidence_columns(ens, gbm, tr, ca, te, horizons, fcols):
    """Per-horizon confidence (level, score) for the ensemble on the TEST block; every input is
    available at prediction time or estimated on train/cal only."""
    env = {c: (float(np.nanpercentile(tr[c], 0.5)), float(np.nanpercentile(tr[c], 99.5))) for c in fcols}
    in_dist = confidence.in_distribution(te, env)
    cal_pred = ens.predict(ca, ca["trend"])
    te_pred = ens.predict(te, te["trend"])
    cols = {}
    sig_te = te["rv36"].values
    for h in horizons:
        yu = ca[f"y_up_{h}"].values
        ok = ~np.isnan(yu)
        p = cal_pred[h]["p_up"]
        base = np.nanmean(tr[f"y_up_{h}"].values)
        skill = 1 - np.mean((p[ok] - yu[ok]) ** 2) / np.mean((base - yu[ok]) ** 2)      # recent OOS skill (cal block)
        agree_shap, _ = evidence.shap_evidence(gbm, te, h, top=0)
        pm = [v["p_up"] for v in te_pred[h]["per_model"].values()]
        rm = [v["ret_med"] for v in te_pred[h]["per_model"].values()]
        lo, hi = te_pred[h]["intervals"][80]
        slot_gate = (te["slot"].values + h) > (config.USABLE_SLOTS - 1)
        data_ok = 1.0 - 0.3 * te["rel_vol"].isna().values
        a = confidence.assess(te_pred[h]["p_up"], pm, rm, te_pred[h]["ret_med"], (hi - lo) / np.where(sig_te > 0, sig_te, np.nan),
                              te["regime_stable"].values, agree_shap, skill, data_ok, gated=(~in_dist) | slot_gate)
        cols[f"ens_conf_{h}"] = a["level"]
        cols[f"ens_confscore_{h}"] = a["score"]
        cols[f"ens_perfskill_{h}"] = np.full(len(te), skill)
    return pd.DataFrame(cols, index=te.index)


def load_pooled(con, symbols, index_symbol):
    mats, fcols = [], None
    for s in symbols:
        m, fc = dataset.build_matrix(con, s, index_symbol=index_symbol)
        mats.append(m)
        fcols = fc if fcols is None else [c for c in fcols if c in fc]
        print(f"[data] {s}: {len(m)} warm rows, {m['session'].nunique()} sessions", flush=True)
    return pd.concat(mats, ignore_index=True), fcols


def run(symbols, index_symbol="NIFTY 50", min_train=150, cal=20, test=20, max_folds=None, use_gru=True):
    con = store.connect()
    M, fcols = load_pooled(con, symbols, index_symbol)
    reg = regimes.classify(M)
    M = pd.concat([M, reg], axis=1)
    M["regime_stable"] = regime_stability(M)
    Mfull = M                                   # includes the pre-warm-up sequence-history rows (GRU input only)
    M = Mfull[Mfull["warm"]]                    # the ONLY rows that are trained on / scored; index labels = positions in Mfull
    folds = walkforward.make_folds(M["session"].unique(), min_train, cal, test, max_folds=max_folds)
    if not folds:
        raise SystemExit("not enough verified sessions for even one walk-forward fold")
    horizons = config.HORIZONS
    out, weights = [], []
    for k, fo in enumerate(folds):
        walkforward.assert_no_overlap(fo)
        tr, ca, te = (M[M["session"].isin(fo[x])] for x in ("train", "cal", "test"))
        t0 = time.time()
        gbm = GBMForecaster(fcols).fit(tr, ca)
        parts = [wide_predictions(te, gbm.predict(te), "gbm", horizons)]
        fitted = {"gbm": gbm}
        if use_gru:
            gru = GRUForecaster(fcols).attach(Mfull).fit(tr, ca)
            fitted["gru"] = gru
            parts.append(wide_predictions(te, gru.predict(te), "gru", horizons))
            for tag, ra in (("ens", False), ("ensr", True)):
                ens = Ensemble(fitted, regime_aware=ra).fit_weights(ca, M.loc[ca.index, "trend"])
                ep = ens.predict(te, te["trend"])
                parts.append(wide_predictions(te, ep, tag, horizons))
                for h in horizons:
                    weights.append({"fold": k, "tag": tag, "h": h, **ep[h]["weights"]})
                if tag == "ens":
                    parts.append(confidence_columns(ens, gbm, tr, ca, te, horizons, fcols))
        pw = pd.concat(parts, axis=1)
        bw = baseline_wide(tr, te, horizons)
        base_cols = ["symbol", "session", "ts", "slot", "regime", "trend", "vol", "breakout", "reversal_risk", "rv36", "close"] + \
                    [c for c in te.columns if c.startswith("y_")]
        o = pd.concat([te[base_cols], pw, bw], axis=1)
        o["fold"] = k
        out.append(o)
        print(f"[fold {k}] train {fo['train'][0]}..{fo['train'][-1]} | test {fo['test'][0]}..{fo['test'][-1]} | "
              f"rows tr/ca/te {len(tr)}/{len(ca)}/{len(te)} | {time.time() - t0:.0f}s", flush=True)
    oos = pd.concat(out, ignore_index=True)
    path = os.path.join(config.DATA_DIR, "oos_predictions.parquet")
    oos.to_parquet(path)
    pd.DataFrame(weights).to_csv(os.path.join(config.DATA_DIR, "ensemble_weights.csv"), index=False)
    print(f"[saved] {path} ({len(oos)} rows)")
    return oos


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", required=True)
    ap.add_argument("--index", default="NIFTY 50")
    ap.add_argument("--min-train", type=int, default=150)
    ap.add_argument("--max-folds", type=int, default=None)
    ap.add_argument("--no-gru", action="store_true")
    ap.add_argument("--cal", type=int, default=20)
    ap.add_argument("--test", type=int, default=20)
    a = ap.parse_args()
    run(a.symbols, a.index, a.min_train, cal=a.cal, test=a.test, max_folds=a.max_folds, use_gru=not a.no_gru)
