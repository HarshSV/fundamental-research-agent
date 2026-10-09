"""Train, register and (only if the gate passes) promote a production ensemble.

python -m forecast.train_production --symbols RELIANCE TCS ...        # reads data/forecast/gate.json
python -m forecast.train_production --gate-only                       # (re)run the gate on oos_predictions.parquet

The gate is evaluated on the walk-forward OOS file (run_walkforward). The final model is fit on ALL
verified sessions except the last 20 (which form the calibration block) - the same recipe the
walk-forward validated. Nothing is promoted unless registry.promotion_gate passes.
"""
import argparse
import json
import os
import pickle
import time

import numpy as np
import pandas as pd

from . import config, regimes, registry, store
from .ensemble import Ensemble
from .models_gbm import GBMForecaster, PARAMS as GBM_PARAMS, ROUNDS
from .models_gru import GRUForecaster
from .run_walkforward import load_pooled, regime_stability

GATE_PATH = os.path.join(config.DATA_DIR, "gate.json")


def run_gate(oos_path=None, model="ens"):
    oos = pd.read_parquet(oos_path or os.path.join(config.DATA_DIR, "oos_predictions.parquet"))
    gate = registry.promotion_gate(oos, model=model)
    gate["oos_range"] = [oos["session"].min(), oos["session"].max()]
    gate["oos_symbols"] = sorted(oos["symbol"].unique())
    gate["oos_rows"] = int(len(oos))
    gate["created_at"] = int(time.time())
    with open(GATE_PATH, "w") as f:
        json.dump(gate, f, indent=1, default=str)
    return gate


def train(symbols, index_symbol="NIFTY 50", cal_sessions=20):
    con = store.connect()
    M, fcols = load_pooled(con, symbols, index_symbol)
    M = pd.concat([M, regimes.classify(M)], axis=1)
    M["regime_stable"] = regime_stability(M)
    Mfull = M
    M = Mfull[Mfull["warm"]]
    sessions = sorted(M["session"].unique())
    cal_s, tr_s = sessions[-cal_sessions:], sessions[: -cal_sessions - 1]          # 1-session embargo
    tr, ca = M[M["session"].isin(tr_s)], M[M["session"].isin(cal_s)]
    gbm = GBMForecaster(fcols).fit(tr, ca)
    gru = GRUForecaster(fcols).attach(Mfull).fit(tr, ca)
    ens = Ensemble({"gbm": gbm, "gru": gru}).fit_weights(ca, ca["trend"])
    envelope = {c: (float(np.nanpercentile(tr[c], 0.5)), float(np.nanpercentile(tr[c], 99.5))) for c in fcols}
    for m in (gru,):                         # drop the big pooled arrays before pickling
        m.ch = m.st = m.seq_ok = None
        m.attached = False
    version = time.strftime("v%Y%m%d%H%M%S")
    d = os.path.join(config.MODEL_DIR, version)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "ensemble.pkl")
    gate = json.load(open(GATE_PATH)) if os.path.exists(GATE_PATH) else None
    meta = {"feature_cols": fcols, "envelope": envelope, "validated_symbols": sorted(symbols), "index_symbol": index_symbol,
            "feature_version": config.FEATURE_VERSION, "usable_slots": config.USABLE_SLOTS,
            "train_sessions": [tr_s[0], tr_s[-1]], "cal_sessions": [cal_s[0], cal_s[-1]],
            "weights": {"dir": ens.w_dir, "ret": ens.w_q}, "gate": gate}
    with open(path, "wb") as f:
        pickle.dump({"ensemble": ens, "meta": meta}, f)
    hp = {"gbm": dict(GBM_PARAMS, rounds=ROUNDS), "gru": {"hidden": 32, "L": 24, "epochs": gru.epochs, "batch": gru.batch}}
    registry.register(con, version, "ensemble(lightgbm+gru_numpy)", config.FEATURE_VERSION, tr_s[0], tr_s[-1], hp, meta, path)
    promoted = False
    if gate is None:
        print("[registry] no gate result -> model stays CANDIDATE (not eligible for live forecasts)")
    else:
        promoted = registry.promote(con, version, gate)
    print(f"[registry] {version}: {'PROMOTED to production' if promoted else 'NOT promoted'}")
    if gate and not gate["pass"]:
        print("  reasons:", *gate["reasons"], sep="\n   - ")
    return version, promoted


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+")
    ap.add_argument("--gate-only", action="store_true")
    a = ap.parse_args()
    if a.gate_only:
        g = run_gate()
        print(json.dumps({k: g[k] for k in ("pass", "range_validated", "direction_validated", "fold_win_share", "reasons")}, indent=1, default=str))
    else:
        train(a.symbols)
