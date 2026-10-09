"""Permanent naive benchmarks. A model is only eligible for promotion if it beats the BEST of these
out-of-sample (see registry.promotion_gate). All use only information available at t.

Each returns, per horizon h, a point forecast of ln(C_{t+h}/C_t) and P(up):
  persistence  : ret = 0 (last price persists); P(up) = training up-frequency (no directional view)
  recent_return: continue the last 6 bars' drift: ret = (ret6/6)*h; P(up) logistic-free: 1 if drift>0 else 0
                 is NOT used (would be a wild probability) -> P(up) = train frequency shifted by sign agreement
                 rate measured on TRAIN only
  trend        : EMA21 slope: ret = ema21_slope*h; same train-only probability treatment
Interval baseline: Gaussian, median = baseline ret, sigma = rv36*sqrt(h) (causal).
"""
import numpy as np
import pandas as pd
from scipy.stats import norm

from . import config

Z = {50: norm.ppf(0.75), 80: norm.ppf(0.90), 95: norm.ppf(0.975)}


def _prob_from_sign(train_sign, train_up, test_sign, floor=0.02):
    """P(up | baseline says up/down) estimated on TRAIN only (so the baseline is as strong as
    its own signal allows, and strictly out-of-sample on test)."""
    out = np.full(len(test_sign), np.nan)
    for s in (-1.0, 1.0):
        m = train_sign == s
        p = np.nanmean(train_up[m]) if m.sum() > 50 else np.nanmean(train_up)
        out[test_sign == s] = np.clip(p, floor, 1 - floor)
    out[np.isnan(test_sign) | (test_sign == 0)] = np.clip(np.nanmean(train_up), floor, 1 - floor)
    return out


def baseline_predictions(train, test, horizons=config.HORIZONS):
    """Returns {name: {h: {'ret': arr, 'p_up': arr}}} for the test frame."""
    res = {}
    for name in ("persistence", "recent_return", "trend"):
        res[name] = {}
        for h in horizons:
            if name == "persistence":
                ret_tr, ret_te = np.zeros(len(train)), np.zeros(len(test))
                sign_tr = sign_te = np.zeros(0)
            elif name == "recent_return":
                ret_tr, ret_te = train["ret6"].values / 6 * h, test["ret6"].values / 6 * h
            else:
                ret_tr, ret_te = train["ema21_slope"].values * h, test["ema21_slope"].values * h
            up_tr = train[f"y_up_{h}"].values
            if name == "persistence":
                p = np.full(len(test), np.clip(np.nanmean(up_tr), 0.02, 0.98))
            else:
                p = _prob_from_sign(np.sign(ret_tr), up_tr, np.sign(ret_te))
            res[name][h] = {"ret": ret_te, "p_up": p}
    return res


def gaussian_intervals(ret_median, sigma, h):
    """{level: (lo, hi)} in log-return units around a baseline median."""
    s = sigma * np.sqrt(h)
    return {lv: (ret_median - z * s, ret_median + z * s) for lv, z in Z.items()}
