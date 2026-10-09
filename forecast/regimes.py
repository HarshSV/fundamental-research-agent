"""Market-regime classification from CAUSAL features only (same function in training and live).

Thresholds are fixed a priori (never tuned on test data):
- trend: `trend_slope20` is the 20-bar log-price slope in units of trailing vol. Under a pure
  random walk its std is ~ 1/sqrt(sum x^2) = 0.039, so |slope| > 0.08 is a ~2-sigma trend.
- volatility: `rv36_rel` = rv36 / its own mean over the last 5 sessions; >1.25 high, <0.8 low.
- breakout: close beyond the prior 20-bar high/low. reversal_risk: RSI14 extreme against the trend.
Whether regime-aware weighting actually helps out-of-sample is MEASURED in the ensemble stage,
not assumed.
"""
import numpy as np
import pandas as pd

TREND_T = 0.08
VOL_HI, VOL_LO = 1.25, 0.8


def classify(f: pd.DataFrame) -> pd.DataFrame:
    slope = f["trend_slope20"]
    trend = np.where(slope > TREND_T, "trend_up", np.where(slope < -TREND_T, "trend_down", "range"))
    trend = pd.Series(trend, index=f.index).where(slope.notna(), "unknown")
    rel = f["rv36_rel"]
    vol = pd.Series(np.where(rel > VOL_HI, "high_vol", np.where(rel < VOL_LO, "low_vol", "normal_vol")), index=f.index).where(rel.notna(), "unknown")
    out = pd.DataFrame({"trend": trend, "vol": vol})
    out["breakout"] = np.where(f["breakout_up20"] > 0, "up", np.where(f["breakout_dn20"] < 0, "down", "none"))
    out.loc[f["breakout_up20"].isna(), "breakout"] = "unknown"
    rsi = f["rsi14"]
    out["reversal_risk"] = ((trend == "trend_up") & (rsi > 70)) | ((trend == "trend_down") & (rsi < 30))
    out["regime"] = out["trend"] + "|" + out["vol"]
    return out
