"""Direct multi-horizon labels for the bar that completes at t+h, h = 1..5.

For prediction time t (bar t has just closed) and horizon h, with j = the h-th bar after t:
  y_ret_h   = ln(close_j / close_t)                       future return (the primary target)
  y_up_h    = 1 if y_ret_h > 0, 0 if < 0, NaN if exactly 0   (flat = no direction, not "down")
  y_wup_h   = ln(high_j / max(open_j, close_j))  >= 0     upper wick
  y_wdn_h   = ln(min(open_j, close_j) / low_j)   >= 0     lower wick
  y_range_h = ln(high_j / low_j)                 >= 0     bar range (volatility target)
  y_open_h  = ln(open_j / close_t)                         open of the target bar (gap evidence)

OHLC reconstruction of a predicted bar is valid by construction:
  O_h = C_{h-1} (C_0 = close_t), C_h = close_t * exp(ret_h),
  H_h = max(O_h, C_h) * exp(wick_up_h) >= max(O_h, C_h),  L_h = min(O_h, C_h) * exp(-wick_dn_h) <= min(O_h, C_h).

A label is NaN unless bar j exists in the SAME session, in the same verified segment, and exactly
h*300s after t - labels never cross a session close, a gap, or an unverified session.
Targets are NOT normalised here; the trainer divides by the causal volatility scale (rv36 at t),
a feature known at t. No statistic of the future ever enters a feature or a scale.
"""
import numpy as np
import pandas as pd

from . import config


def build_labels(bars, horizons=config.HORIZONS):
    out = {"ts": bars["ts"].values}
    g = bars.groupby("seg", sort=False)
    c0 = bars["close"].astype(float)
    for h in horizons:
        sh = lambda col: g[col].shift(-h).astype(float)
        ts_j, sess_j = g["ts"].shift(-h), g["session"].shift(-h)
        ok = (ts_j - bars["ts"] == h * config.BAR_SECONDS) & (sess_j == bars["session"])
        oj, hj, lj, cj = sh("open"), sh("high"), sh("low"), sh("close")
        ret = np.log(cj / c0)
        up = pd.Series(np.where(ret > 0, 1.0, np.where(ret < 0, 0.0, np.nan)), index=bars.index)
        out[f"y_ret_{h}"] = ret.where(ok)
        out[f"y_up_{h}"] = up.where(ok)
        out[f"y_wup_{h}"] = np.log(hj / np.maximum(oj, cj)).where(ok)
        out[f"y_wdn_{h}"] = np.log(np.minimum(oj, cj) / lj).where(ok)
        out[f"y_range_{h}"] = np.log(hj / lj).where(ok)
        out[f"y_open_{h}"] = np.log(oj / c0).where(ok)
    return pd.DataFrame(out)


def reconstruct_bars(last_close, ret, wick_up, wick_dn):
    """Valid OHLC path from per-horizon direct forecasts (NOT recursion: each ret_h is its own
    direct forecast of ln(C_h / C_0); O_h is just the previous horizon's forecast close)."""
    bars, prev = [], float(last_close)
    for r, wu, wd in zip(ret, wick_up, wick_dn):
        o = prev
        c = float(last_close) * float(np.exp(r))
        hi = max(o, c) * float(np.exp(max(wu, 0.0)))
        lo = min(o, c) * float(np.exp(-max(wd, 0.0)))
        bars.append({"open": o, "high": hi, "low": lo, "close": c})
        prev = c
    return bars
