"""CANONICAL daily feature engine - the only place daily features are computed (training, backtest, live).

Identity / leakage rules (same as the intraday engine):
 - every feature at row t uses bars with date <= t only (all windows trailing; finite windows, no recursive EMA);
 - computed per SEGMENT = run of consecutive verified trading sessions, so no window spans a missing/bad session;
 - rows with < WARMUP_BARS of segment history have warm == False and are never trained on or scored;
 - zero/missing volume is NaN (unknown), never 0;
 - market (NIFTY) and sector-index context are merged on the SAME date (their close is known at the same time);
   anything unavailable stays NaN.
A deliberately conservative set (~32 features).
"""
import numpy as np
import pandas as pd

from ..features import ewma_fixed, rsi, true_range, wilder

WARMUP_BARS = 275           # vol_rel = rv20 / mean(rv20 over 252 bars) needs 20 + 252 - 1 = 271 valid bars
VOL_REGIME_WIN = 252


def _roll(s, w, fn):
    return getattr(s.rolling(w, min_periods=w), fn)()


def _slope(y, w):
    from numpy.lib.stride_tricks import sliding_window_view
    y = np.asarray(y, float)
    out = np.full(len(y), np.nan)
    if len(y) >= w:
        x = np.arange(w) - (w - 1) / 2.0
        out[w - 1:] = sliding_window_view(y, w) @ x / (x @ x)
    return out


def index_context(idx, prefix):
    """Causal context features of an index close series (frame: date, close) - own windows only."""
    d = idx.sort_values("date").reset_index(drop=True)
    c = pd.Series(d["close"].astype(float).values)
    lc = np.log(c)
    r1 = lc.diff()
    out = pd.DataFrame({"date": d["date"].values})
    out[f"{prefix}_ret1"] = r1.values
    out[f"{prefix}_ret5"] = lc.diff(5).values
    out[f"{prefix}_ret20"] = lc.diff(20).values
    out[f"{prefix}_rv20"] = _roll(r1, 20, "std").values
    out[f"{prefix}_dd252"] = (lc - _roll(lc, 252, "max")).values
    return out


def _segment(g, mkt, sec):
    g = g.reset_index(drop=True)
    o, h, l, c = (g[k].values.astype(float) for k in ("open", "high", "low", "close"))
    v = g["volume"].values.astype(float)
    v = np.where(v > 0, v, np.nan)
    lc = np.log(c)
    sc, sh, sl = pd.Series(c), pd.Series(h), pd.Series(l)
    r1 = pd.Series(np.concatenate([[np.nan], np.diff(lc)]))
    f = pd.DataFrame({"date": g["date"].values})
    # returns
    f["ret1"] = r1.values
    for k in (5, 10, 20, 60):
        f[f"ret{k}"] = pd.Series(lc).diff(k).values
    f["gap"] = np.log(o / np.concatenate([[np.nan], c[:-1]]))
    # volatility / range
    for w in (10, 20, 60):
        f[f"rv{w}"] = _roll(r1, w, "std").values
    f["rv_ratio"] = f["rv20"] / f["rv60"]
    f["vol_rel"] = f["rv20"] / _roll(pd.Series(f["rv20"]), VOL_REGIME_WIN, "mean")       # vol vs its own last year (regime)
    f["atr14"] = wilder(true_range(h, l, c), 14) / c
    rng = pd.Series(np.log(h / l))
    f["range1"] = rng.values
    f["range_ratio"] = (rng / _roll(rng, 20, "mean")).values
    # momentum / moving averages / trend
    f["rsi14"] = rsi(c, 14)
    macd = (ewma_fixed(c, 2 / 13, 36) - ewma_fixed(c, 2 / 27, 78)) / c
    f["macd"] = macd
    for w in (20, 50, 200):
        f[f"dist_sma{w}"] = np.log(c / _roll(sc, w, "mean").values)
    f["sma50_200"] = np.log(_roll(sc, 50, "mean").values / _roll(sc, 200, "mean").values)
    f["slope20"] = _slope(lc, 20) / f["rv20"].values
    f["up_frac20"] = _roll((r1 > 0).astype(float).where(~r1.isna()), 20, "mean").values
    hi60, lo60 = _roll(sh, 60, "max"), _roll(sl, 60, "min")
    f["pos_range60"] = ((sc - lo60) / (hi60 - lo60).replace(0, np.nan)).values
    # drawdown / breakout distance
    f["dd252"] = np.log(c / _roll(sh, 252, "max").values)
    f["dist_hi20"] = np.log(c / _roll(sh, 20, "max").values)
    f["dist_lo20"] = np.log(c / _roll(sl, 20, "min").values)
    # volume (unknown stays NaN)
    sv = pd.Series(v)
    f["rel_vol20"] = (sv / _roll(sv, 20, "mean")).values
    f["vol_trend"] = (_roll(sv, 5, "mean") / _roll(sv, 20, "mean")).values
    # market / sector context (same-date join; NaN where unavailable)
    for ctx in (mkt, sec):
        if ctx is not None:
            j = f[["date"]].merge(ctx, on="date", how="left")
            for col in ctx.columns:
                if col != "date":
                    f[col] = j[col].values
    # Stable schema: the same columns exist for EVERY symbol (NaN where a context index is unavailable / unmapped), so the
    # pooled model never silently loses a feature because one symbol lacks a sector index.
    for pre, ctx in (("mkt", mkt), ("sec", sec)):
        if ctx is None:
            for c in ("ret1", "ret5", "ret20", "rv20", "dd252"):
                f[f"{pre}_{c}"] = np.nan
    f["rel_ret20"] = f["ret20"] - f["mkt_ret20"]
    f["rel_sec20"] = f["ret20"] - f["sec_ret20"]
    return f


def compute_features(bars, mkt_bars=None, sec_bars=None):
    """bars: DataFrame[date, open, high, low, close, volume, seg] ascending (verified bars only).
    Returns features with columns date, seg, seg_pos, warm + features."""
    mkt = index_context(mkt_bars, "mkt") if mkt_bars is not None and len(mkt_bars) else None
    sec = index_context(sec_bars, "sec") if sec_bars is not None and len(sec_bars) else None
    parts = []
    for seg, g in bars.groupby("seg", sort=True):
        f = _segment(g, mkt, sec)
        f["seg"] = seg
        f["seg_pos"] = np.arange(len(g))
        f["warm"] = f["seg_pos"] >= WARMUP_BARS
        parts.append(f)
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True).replace([np.inf, -np.inf], np.nan)


NON_FEATURE = {"date", "seg", "seg_pos", "warm"}


def feature_columns(df):
    return [c for c in df.columns if c not in NON_FEATURE]
