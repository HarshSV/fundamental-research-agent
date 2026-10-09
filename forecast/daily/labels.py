"""Direct multi-horizon daily labels (trading-day horizons). Targets are returns / ranges, never raw prices.

For prediction date t (its close is known) and horizon h trading days, with rows ordered within a SEGMENT of
consecutive verified sessions (so the h-th next row IS the h-th next trading session):
  y_ret_h   = ln(close_{t+h} / close_t)                           future return
  y_up_h    = 1 / 0 (NaN if exactly 0)                            direction
  y_range_h = ln(max high_{t+1..t+h} / min low_{t+1..t+h})        future high/low range over the horizon
  y_rv_h    = std of daily log returns over t+1..t+h (h >= 3)     future realised volatility
A label is NaN unless all h future rows exist in the same segment: labels never cross a missing session or a segment
break. Nothing is recursive: each horizon is its own target.
"""
import numpy as np
import pandas as pd

SHORT_H = (1, 3, 5, 10, 20)
LONG_H = (63, 126, 252, 504)       # 3M / 6M / 1Y / 2Y (investigation only)


def build_labels(bars, horizons=SHORT_H):
    out = {"date": bars["date"].values}
    c = bars["close"].astype(float)
    lc = np.log(c)
    r1 = lc.groupby(bars["seg"]).diff()
    g = bars.groupby("seg", sort=False)
    for h in horizons:
        cj = g["close"].shift(-h).astype(float)
        ok = cj.notna()
        out[f"y_ret_{h}"] = np.log(cj / c).where(ok)
        ret = out[f"y_ret_{h}"]
        out[f"y_up_{h}"] = pd.Series(np.where(ret > 0, 1.0, np.where(ret < 0, 0.0, np.nan)), index=bars.index).where(ok)
        # forward window max/min of high/low over t+1..t+h  == rolling(h) on the series shifted by -h, per segment
        hi = g["high"].transform(lambda s: s[::-1].rolling(h, min_periods=h).max()[::-1].shift(-1))
        lo = g["low"].transform(lambda s: s[::-1].rolling(h, min_periods=h).min()[::-1].shift(-1))
        out[f"y_range_{h}"] = np.log(hi / lo).where(ok)
        if h >= 3:
            rv = r1.groupby(bars["seg"]).transform(lambda s: s[::-1].rolling(h, min_periods=h).std()[::-1].shift(-1))
            out[f"y_rv_{h}"] = rv.where(ok)
    return pd.DataFrame(out)
