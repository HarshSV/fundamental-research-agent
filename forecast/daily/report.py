"""Daily validation report from the walk-forward OOS files. Nothing is aggregated into a single number: every table is
per horizon, and breakdowns are by symbol, period, volatility regime and market regime.

python -m forecast.daily.report --profile short [--out docs/daily_validation_short.md]
"""
import argparse
import os

import numpy as np
import pandas as pd

from .. import config, evaluate

SIG = "rv20"
BASELINES = ["persistence", "recent_return", "trend", "hist_vol"]


def models_in(oos):
    return [m for m in ("gbm", "har", "ens") if f"{m}_ret_{next(iter(_horizons(oos)))}" in oos]


def _horizons(oos):
    return sorted({int(c.split("_")[-1]) for c in oos.columns if c.startswith("y_ret_")})


def best_baseline(oos, h):
    r = evaluate.report(oos, ["persistence", "recent_return", "trend", "hist_vol"], (h,), SIG)
    return r.sort_values("nmae").iloc[0]["model"]


def _fmt(df, cols):
    cols = [c for c in cols if c in df]
    return df[cols].to_string(index=False, float_format=lambda x: f"{x:.4f}")


def calibration_table(oos, m, h, bins=10):
    p, y = oos[f"{m}_pup_{h}"], oos[f"y_up_{h}"]
    ok = p.notna() & y.notna()
    if ok.sum() == 0:
        return pd.DataFrame()
    q = pd.qcut(p[ok], bins, duplicates="drop")
    g = pd.DataFrame({"p": p[ok], "y": y[ok], "bin": q}).groupby("bin", observed=True).agg(mean_pred=("p", "mean"), actual_up=("y", "mean"), n=("y", "size"))
    return g.reset_index(drop=True)


def build(oos, profile):
    H = _horizons(oos)
    mods = models_in(oos)
    allm = mods + BASELINES
    L = []
    add = L.append
    add(f"# Daily walk-forward validation - profile `{profile}`\n")
    add(f"OOS rows={len(oos)} symbols={oos['symbol'].nunique()} folds={oos['fold'].nunique()} "
        f"range={oos['date'].min()}..{oos['date'].max()} horizons={H} models={mods}\n")
    rep = evaluate.report(oos, allm, tuple(H), SIG)
    add("## 1. Point / direction / probability metrics (pooled, per horizon)\n")
    for h in H:
        add(f"### +{h} trading days\n```\n" + _fmt(rep[rep["h"] == h], ["model", "n", "acc", "bal_acc", "prec_up", "rec_up", "brier", "logloss", "base_rate_up", "nmae", "mae_bps", "rmse_bps"]) + "\n```")
    add("## 2. Interval coverage / width (nominal 50 / 80 / 95)\n")
    for h in H:
        add(f"### +{h}\n```\n" + _fmt(rep[rep["h"] == h], ["model"] + [c for lv in evaluate.LEVELS for c in (f"cov{lv}", f"width{lv}_bps")]) + "\n```")
    add("## 3. Models vs best baseline (negative = model better; 95% CI from MONTH-block bootstrap across all symbols)\n")
    rows = []
    for m in mods:
        for h in H:
            b = best_baseline(oos, h)
            for metric in ("abs", "brier", "err_dir", "winkler80"):
                rows.append(evaluate.paired_bootstrap(oos, m, b, h, metric, B=1000, sig_col=SIG, block_col="month"))
    bt = pd.DataFrame(rows)
    add("```\n" + _fmt(bt, ["model", "baseline", "h", "metric", "mean_a", "mean_b", "diff", "ci_lo", "ci_hi", "n_blocks"]) + "\n```")
    add("## 4. Per-symbol (80% coverage, Winkler80 ratio vs hist_vol, Brier skill vs persistence) for the leading model\n")
    lead = "ens" if "ens" in mods else mods[0]
    for h in H:
        rows = []
        for s, g in oos.groupby("symbol"):
            g = g.reset_index(drop=True)
            a, b = evaluate.score(g, lead, h, SIG), evaluate.score(g, "hist_vol", h, SIG)
            y, sg = g[f"y_ret_{h}"].values, g[SIG].values
            ok = ~np.isnan(y) & g[f"{lead}_lo80_{h}"].notna().values & (sg > 0)
            wm = np.mean(evaluate.winkler(g[f"{lead}_lo80_{h}"].values[ok], g[f"{lead}_hi80_{h}"].values[ok], y[ok], 0.2) / sg[ok]) if ok.any() else np.nan
            wb = np.mean(evaluate.winkler(g[f"hist_vol_lo80_{h}"].values[ok], g[f"hist_vol_hi80_{h}"].values[ok], y[ok], 0.2) / sg[ok]) if ok.any() else np.nan
            rows.append({"symbol": s, "n": a.get("n"), "cov80": a.get("cov80"), "wink_ratio": wm / wb if wb else np.nan,
                         "brier_skill": 1 - a["brier"] / b["brier"] if "brier" in a and "brier" in b else np.nan, "acc": a.get("acc")})
        t = pd.DataFrame(rows)
        add(f"### +{h}  ({lead}); symbols with cov80 outside 0.70-0.90: {int(((t['cov80'] < 0.70) | (t['cov80'] > 0.90)).sum())}/{len(t)}; "
            f"wink_ratio<1 (better than baseline): {int((t['wink_ratio'] < 1).sum())}/{len(t)}; brier_skill>0: {int((t['brier_skill'] > 0).sum())}/{len(t)}\n```\n"
            + _fmt(t.sort_values("wink_ratio"), ["symbol", "n", "cov80", "wink_ratio", "brier_skill", "acc"]) + "\n```")
    for title, col in (("5. By validation period (calendar year)", "year"), ("6. By volatility regime", "vol_regime"), ("7. By market regime", "market_regime")):
        add(f"## {title}\n")
        for h in H:
            rows = []
            for key, g in oos.groupby(col):
                g = g.reset_index(drop=True)
                if len(g) < 200:
                    continue
                a, b = evaluate.score(g, lead, h, SIG), evaluate.score(g, "hist_vol", h, SIG)
                rows.append({col: key, "n": a.get("n"), "cov50": a.get("cov50"), "cov80": a.get("cov80"), "cov95": a.get("cov95"),
                             "w80_bps": a.get("width80_bps"), "base_w80_bps": b.get("width80_bps"), "brier": a.get("brier"), "base_brier": b.get("brier"), "acc": a.get("acc")})
            add(f"### +{h} ({lead})\n```\n" + _fmt(pd.DataFrame(rows), [col, "n", "cov50", "cov80", "cov95", "w80_bps", "base_w80_bps", "brier", "base_brier", "acc"]) + "\n```")
    add("## 8. Probability calibration (reliability, deciles of P(up)) for the leading model\n")
    for h in H:
        add(f"### +{h}\n```\n" + _fmt(calibration_table(oos, lead, h), ["mean_pred", "actual_up", "n"]) + "\n```")
    return "\n".join(L), bt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="short")
    ap.add_argument("--out")
    a = ap.parse_args()
    oos = pd.read_parquet(os.path.join(config.DATA_DIR, f"daily_oos_{a.profile}.parquet"))
    text, _ = build(oos, a.profile)
    out = a.out or os.path.join(config.DATA_DIR, f"daily_report_{a.profile}.md")
    open(out, "w", encoding="utf-8").write(text)
    print(f"[report] {out} ({len(text)} chars)")


if __name__ == "__main__":
    main()
