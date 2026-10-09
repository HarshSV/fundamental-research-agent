"""Print walk-forward results from data/forecast/oos_predictions.parquet.
python -m forecast.report [--models gbm persistence recent_return trend]"""
import argparse
import os

import pandas as pd

from . import config, evaluate

BASELINES = ["persistence", "recent_return", "trend"]


def best_baseline(oos, h, metric="nmae"):
    rep = evaluate.report(oos, BASELINES, (h,))
    return rep.sort_values(metric).iloc[0]["model"]


def main(models, path=None, boot=500):
    pd.set_option("display.width", 220, "display.max_columns", 40, "display.float_format", lambda x: f"{x:.4f}")
    oos = pd.read_parquet(path or os.path.join(config.DATA_DIR, "oos_predictions.parquet"))
    print(f"OOS rows={len(oos)} symbols={oos['symbol'].nunique()} sessions={oos['session'].nunique()} "
          f"folds={oos['fold'].nunique()} range={oos['session'].min()}..{oos['session'].max()}\n")
    rep = evaluate.report(oos, models)
    cols = ["model", "h", "n", "acc", "bal_acc", "prec_up", "rec_up", "brier", "logloss", "base_rate_up", "nmae", "mae_bps", "rmse_bps", "skill_r2"]
    print(rep[[c for c in cols if c in rep]].to_string(index=False))
    print("\nINTERVAL COVERAGE / WIDTH (bps)")
    icols = ["model", "h"] + [c for lv in evaluate.LEVELS for c in (f"cov{lv}", f"width{lv}_bps")]
    print(rep[[c for c in icols if c in rep]].to_string(index=False))
    print("\nMODEL vs BEST BASELINE (negative diff = model better; 95% session-block bootstrap CI)")
    rows = []
    for m in models:
        if m in BASELINES:
            continue
        for h in config.HORIZONS:
            b = best_baseline(oos, h)
            for metric in ("abs", "brier", "err_dir"):
                rows.append(evaluate.paired_bootstrap(oos, m, b, h, metric, B=boot))
    print(pd.DataFrame(rows)[["model", "baseline", "h", "metric", "mean_a", "mean_b", "diff", "ci_lo", "ci_hi", "p_better", "n_blocks"]].to_string(index=False))
    tier_report(oos)
    return oos, rep


def tier_report(oos, model="ens"):
    """Confidence tiers must be MONOTONE: higher tier -> better directional skill. Otherwise the
    confidence engine is not informative and must not be exposed as such."""
    if f"{model}_conf_1" not in oos:
        return
    print("\nCONFIDENCE TIER VALIDATION (ensemble, out-of-sample)")
    rows = []
    for h in config.HORIZONS:
        c = oos[f"{model}_conf_{h}"]; up = oos[f"y_up_{h}"]; p = oos[f"{model}_pup_{h}"]
        base = oos[f"persistence_pup_{h}"]
        for lvl in ["HIGH", "MEDIUM", "LOW", "NO_RELIABLE_FORECAST"]:
            m = (c == lvl) & up.notna()
            if m.sum() == 0:
                rows.append({"h": h, "tier": lvl, "n": 0}); continue
            pred = (p[m] > 0.5)
            rows.append({"h": h, "tier": lvl, "n": int(m.sum()), "share": float(m.sum() / up.notna().sum()),
                         "acc": float((pred == (up[m] == 1)).mean()), "base_rate_up": float(up[m].mean()),
                         "brier_skill_vs_persist": float(1 - ((p[m] - up[m]) ** 2).mean() / ((base[m] - up[m]) ** 2).mean())})
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["gbm"] + BASELINES)
    a = ap.parse_args()
    main(a.models)
