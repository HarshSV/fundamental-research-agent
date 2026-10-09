"""Long-horizon (3M / 6M / 1Y / 2Y) investigation: is there enough GENUINELY INDEPENDENT evidence to validate each horizon?

Overlapping labels and cross-sectional correlation make the raw row count meaningless, so evidence is counted in
independent units:
  * non-overlapping calendar windows of length h (market-wide: stocks move together),
  * the effective number of independent stocks, N_eff = N / (1 + (N-1) * rho_bar), with rho_bar the mean pairwise
    correlation of non-overlapping h-day returns.

A horizon is SUPPORTED only if, pre-registered here:
  (1) >= MIN_WINDOWS non-overlapping OUT-OF-SAMPLE windows of length h in the walk-forward test blocks, AND
  (2) pooled OOS coverage of the 50/80/95% intervals: the 95% window-block bootstrap CI of coverage contains nominal,
      and the point estimate is within TOL of nominal, AND
  (3) the 80% interval score (Winkler) is not worse than the volatility baseline (CI lower bound of the difference <= 0
      ... reported; "skill" additionally requires the CI upper bound < 0), AND
  (4) calibration is stable: >= 70% of folds have 80% coverage within 0.65-0.92.
Failing (1)-(4) means that horizon is NOT validated, whatever the chart would look like.
"""
import numpy as np
import pandas as pd

from .. import evaluate

MIN_WINDOWS = 8
TOL = {50: 0.10, 80: 0.08, 95: 0.04}
STABLE_SHARE = 0.70
HORIZON_DAYS = {63: "3M", 126: "6M", 252: "1Y", 504: "2Y"}


def independence_report(M, horizons):
    """M: pooled matrix (columns symbol, date, y_ret_h). Returns one row per horizon."""
    rows = []
    dates = pd.to_datetime(M["date"])
    span_years = (dates.max() - dates.min()).days / 365.25
    for h in horizons:
        y = M[["symbol", "date", f"y_ret_{h}"]].dropna()
        lab = y.groupby("symbol").size()
        # non-overlapping windows: sample every h-th trading date market-wide
        ud = sorted(y["date"].unique())
        pick = ud[::h]
        W = y[y["date"].isin(pick)].pivot(index="date", columns="symbol", values=f"y_ret_{h}")
        W = W.dropna(axis=1, thresh=max(3, int(len(W) * 0.6)))
        rho = np.nan
        if W.shape[0] >= 4 and W.shape[1] >= 3:
            c = W.corr(min_periods=4).values
            rho = float(np.nanmean(c[np.triu_indices_from(c, 1)]))
        n = W.shape[1]
        n_eff = n / (1 + (n - 1) * rho) if np.isfinite(rho) and n > 1 else np.nan
        rows.append({"h": h, "label": HORIZON_DAYS.get(h, str(h)), "symbols": int(lab.shape[0]), "labelled_rows": int(lab.sum()),
                     "median_rows_per_symbol": int(lab.median()), "market_windows_nonoverlap": len(pick), "history_years": round(span_years, 1),
                     "mean_pairwise_corr": round(rho, 3) if np.isfinite(rho) else None, "effective_independent_stocks": round(n_eff, 1) if np.isfinite(n_eff) else None,
                     "independent_obs_total": round(len(pick) * n_eff, 0) if np.isfinite(n_eff) else None})
    return pd.DataFrame(rows)


def _window_ids(oos, h):
    ud = sorted(oos["date"].unique())
    pos = {d: i // h for i, d in enumerate(ud)}
    return oos["date"].map(pos)


def coverage_ci(oos, m, h, lv, blocks, B=2000, seed=0):
    lo, hi, y = oos[f"{m}_lo{lv}_{h}"].values, oos[f"{m}_hi{lv}_{h}"].values, oos[f"y_ret_{h}"].values
    ok = ~(np.isnan(lo) | np.isnan(hi) | np.isnan(y))
    hit = ((y >= lo) & (y <= hi))[ok].astype(float)
    g = pd.DataFrame({"b": blocks.values[ok], "hit": hit}).groupby("b").agg(s=("hit", "sum"), n=("hit", "size"))
    s, n = g["s"].values, g["n"].values
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), size=(B, len(g)))
    boot = s[idx].sum(1) / n[idx].sum(1)
    return {"cov": float(s.sum() / n.sum()), "ci_lo": float(np.percentile(boot, 2.5)), "ci_hi": float(np.percentile(boot, 97.5)), "blocks": int(len(g))}


def assess(oos, models, horizons, sig_col="rv20", base="hist_vol"):
    """Apply the pre-registered criteria to the long-horizon walk-forward output."""
    rows = []
    for h in horizons:
        blocks = _window_ids(oos, h)
        # independent OOS windows = distinct non-overlapping h-windows that have any test row
        n_win = int(blocks.nunique())
        for m in models:
            covs = {lv: coverage_ci(oos, m, h, lv, blocks) for lv in evaluate.LEVELS}
            wb = evaluate.paired_bootstrap(oos.assign(_blk=blocks), m, base, h, "winkler80", B=2000, sig_col=sig_col, block_col="_blk")
            per_fold = []
            for _, g in oos.groupby("fold"):
                lo, hi, y = g[f"{m}_lo80_{h}"].values, g[f"{m}_hi80_{h}"].values, g[f"y_ret_{h}"].values
                ok = ~(np.isnan(lo) | np.isnan(hi) | np.isnan(y))
                per_fold.append(float(((y >= lo) & (y <= hi))[ok].mean()) if ok.any() else np.nan)
            stable = float(np.mean([0.65 <= c <= 0.92 for c in per_fold if np.isfinite(c)])) if per_fold else 0.0
            c1 = n_win >= MIN_WINDOWS
            c2 = all(covs[lv]["ci_lo"] <= lv / 100 <= covs[lv]["ci_hi"] and abs(covs[lv]["cov"] - lv / 100) <= TOL[lv] for lv in covs)
            c3 = wb["ci_lo"] <= 0                                   # not demonstrably worse than the volatility baseline
            c4 = stable >= STABLE_SHARE
            rows.append({"h": h, "label": HORIZON_DAYS.get(h, str(h)), "model": m, "oos_windows": n_win, "cov50": round(covs[50]["cov"], 3),
                         "cov80": round(covs[80]["cov"], 3), "cov80_ci": f"[{covs[80]['ci_lo']:.2f},{covs[80]['ci_hi']:.2f}]", "cov95": round(covs[95]["cov"], 3),
                         "winkler_diff_vs_base": round(wb["diff"], 4), "wink_ci": f"[{wb['ci_lo']:.3f},{wb['ci_hi']:.3f}]", "beats_baseline": bool(wb["ci_hi"] < 0),
                         "fold_stability": round(stable, 2), "c1_windows": c1, "c2_calibrated": bool(c2), "c3_not_worse": bool(c3), "c4_stable": bool(c4),
                         "SUPPORTED": bool(c1 and c2 and c3 and c4)})
    return pd.DataFrame(rows)
