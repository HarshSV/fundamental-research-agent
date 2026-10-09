"""Permanent daily baselines. A daily model is only eligible for promotion if it beats the relevant one out-of-sample.
All use information available at t only; every statistic that is "learned" comes from the TRAIN block.

  persistence    : ret = 0 (price persists); P(up) = train up-frequency (no directional view)
  recent_return  : continue the last h-day return (ret = ln(c_t / c_{t-h})); P(up) from train-only sign statistics
  trend          : sign of the 50/200-day MA spread; ret = train conditional mean of y given that sign; P(up) likewise
  hist_vol       : the standard volatility/range baseline: median 0, Gaussian with sigma = rv20 * sqrt(h)
Interval baseline for all four: Gaussian around the baseline's median with sigma = rv20 * sqrt(h) (the one every model
must beat for the RANGE claim); hist_vol is that baseline in its purest form.
"""
import numpy as np
import pandas as pd
from scipy.stats import norm

Z = {50: norm.ppf(0.75), 80: norm.ppf(0.90), 95: norm.ppf(0.975)}
NAMES = ("persistence", "recent_return", "trend", "hist_vol")


def _p_from_sign(train_sign, train_up, test_sign, floor=0.02):
    base = np.clip(np.nanmean(train_up), floor, 1 - floor)
    out = np.full(len(test_sign), base)
    for s in (-1.0, 1.0):
        m = train_sign == s
        if m.sum() > 100:
            out[test_sign == s] = np.clip(np.nanmean(train_up[m]), floor, 1 - floor)
    return out


def baseline_wide(train, test, horizons):
    cols = {}
    sig = test["rv20"].values
    for h in horizons:
        up_tr, y_tr = train[f"y_up_{h}"].values, train[f"y_ret_{h}"].values
        base_p = np.clip(np.nanmean(up_tr), 0.02, 0.98)
        sgn_tr, sgn_te = np.sign(train["sma50_200"].values), np.sign(test["sma50_200"].values)
        cond = {s: np.nanmean(y_tr[sgn_tr == s]) if (sgn_tr == s).sum() > 100 else np.nanmean(y_tr) for s in (-1.0, 1.0)}
        trend_ret = np.where(sgn_te == 1.0, cond[1.0], np.where(sgn_te == -1.0, cond[-1.0], np.nanmean(y_tr)))
        past_tr, past_te = train[f"bl_pastret_{h}"].values, test[f"bl_pastret_{h}"].values
        spec = {
            "persistence": (np.zeros(len(test)), np.full(len(test), base_p)),
            "recent_return": (past_te, _p_from_sign(np.sign(past_tr), up_tr, np.sign(past_te))),
            "trend": (trend_ret, _p_from_sign(sgn_tr, up_tr, sgn_te)),
            "hist_vol": (np.zeros(len(test)), np.full(len(test), base_p)),
        }
        s = sig * np.sqrt(h)
        for name, (ret, p) in spec.items():
            cols[f"{name}_ret_{h}"], cols[f"{name}_pup_{h}"] = ret, p
            for lv, z in Z.items():
                cols[f"{name}_lo{lv}_{h}"], cols[f"{name}_hi{lv}_{h}"] = ret - z * s, ret + z * s
    return pd.DataFrame(cols, index=test.index)
