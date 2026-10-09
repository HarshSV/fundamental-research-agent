"""CANONICAL feature engine - the only place features are computed (training, backtest, live).

Leakage / identity rules
- Every feature at row t uses bars with ts <= t only (all windows are trailing).
- No recursive smoothing (classic EMA/Wilder carry infinite memory, so the value would depend on
  where the series happens to start - training vs live would differ). Every smoother here is a
  FINITE truncated-weight window (`ewma_fixed`), so feature(t) is a pure function of the last
  N bars. Test: features(full history)[t] == features(history truncated at t)[t].
- Computed per *segment* = run of consecutive verified trading sessions, so no window ever
  straddles an unverified/missing session. Rows with < WARMUP_BARS of segment history have
  `warm == False` and must not be used.
- 15m/1h context uses COMPLETED higher-timeframe bars only (merge_asof backward on completion ts).
- Missing/zero volume is NaN (unknown), never 0.
- Scale-free: prices only enter as log ratios / ratios to ATR / vol - no raw price levels.

Not included (no verified source yet): sector context, market breadth. NIFTY context is optional.
"""
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from . import config

WARMUP_BARS = 450      # 6 sessions: covers the longest window (1h RSI/EMA) incl. completed-HTF history
VOL_WIN = 36


def ewma_fixed(x, alpha, n):
    """Truncated-weight exponential average over exactly the last n values (NaN if any NaN)."""
    x = np.asarray(x, dtype=float)
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    w = (1.0 - alpha) ** np.arange(n)[::-1]
    w /= w.sum()
    out[n - 1:] = sliding_window_view(x, n) @ w
    return out


def ema(x, span):
    return ewma_fixed(x, 2.0 / (span + 1.0), 3 * span)


def wilder(x, n):
    return ewma_fixed(x, 1.0 / n, 5 * n)


def rsi(close, n):
    d = np.diff(close, prepend=np.nan)
    gain = np.where(np.isnan(d), np.nan, np.maximum(d, 0.0))
    loss = np.where(np.isnan(d), np.nan, np.maximum(-d, 0.0))
    ag, al = wilder(gain[1:], n), wilder(loss[1:], n)
    ag, al = np.concatenate([[np.nan], ag]), np.concatenate([[np.nan], al])
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100.0 - 100.0 / (1.0 + ag / al)
    out[(al == 0) & (ag == 0)] = 50.0
    out[(al == 0) & (ag > 0)] = 100.0
    return out


def true_range(h, l, c):
    pc = np.concatenate([[np.nan], c[:-1]])
    return np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0) if len(c) else h - l


def _roll(s, w, fn):
    return getattr(s.rolling(w, min_periods=w), fn)()


def _slope(y, w):
    """Least-squares slope of the last w values vs index (per bar), NaN if any NaN."""
    y = np.asarray(y, float)
    out = np.full(len(y), np.nan)
    if len(y) < w:
        return out
    x = np.arange(w) - (w - 1) / 2.0
    out[w - 1:] = sliding_window_view(y, w) @ x / (x @ x)
    return out


def _htf(g, m):
    """Completed m-bar buckets (within session) of a segment, indexed by completion ts."""
    k = g["slot"] // m
    grp = g.groupby([g["session"], k], sort=False)
    a = grp.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
                volume=("volume", lambda v: v.sum(min_count=len(v))), n=("ts", "size"), end_ts=("ts", "max"),
                end_slot=("slot", "max"))
    a = a[a["n"] == m]
    a = a[(a["end_slot"] % m) == (m - 1)]
    return a.sort_values("end_ts").reset_index(drop=True)


def _htf_features(g, m, tag, rsi_n, ema_span):
    h = _htf(g, m)
    if h.empty:
        return pd.DataFrame({"ts": g["ts"].values}).assign(**{f"{tag}_ret1": np.nan, f"{tag}_rsi": np.nan,
                                                                  f"{tag}_ema_dist": np.nan, f"{tag}_atr": np.nan, f"{tag}_mom3": np.nan})
    c, hi, lo = h["close"].values, h["high"].values, h["low"].values
    f = pd.DataFrame({"ts": h["end_ts"].values})
    f[f"{tag}_ret1"] = np.log(c / np.concatenate([[np.nan], c[:-1]]))
    f[f"{tag}_rsi"] = rsi(c, rsi_n)
    f[f"{tag}_ema_dist"] = np.log(c / ema(c, ema_span))
    f[f"{tag}_atr"] = wilder(true_range(hi, lo, c), 7) / c
    f[f"{tag}_mom3"] = np.log(c / np.concatenate([[np.nan] * 3, c[:-3]]))
    base = pd.DataFrame({"ts": g["ts"].values})
    return pd.merge_asof(base, f, on="ts", direction="backward")   # latest COMPLETED bucket with end_ts <= t


def _segment_features(g, idx=None):
    g = g.reset_index(drop=True)
    o, h, l, c = (g[k].values.astype(float) for k in ("open", "high", "low", "close"))
    v = g["volume"].values.astype(float)
    v = np.where(v > 0, v, np.nan)                       # 0/missing volume = unknown
    n = len(g)
    f = pd.DataFrame({"ts": g["ts"].values})
    sess = g["session"].values
    first_in_sess = np.concatenate([[True], sess[1:] != sess[:-1]])
    prev_c = np.concatenate([[np.nan], c[:-1]])
    lc = np.log(c)
    # --- price / return
    ri = np.where(first_in_sess, np.log(c / o), np.log(c / prev_c))      # intraday-only 1-bar return
    f["ret1"] = ri
    for k in (2, 3, 6, 12, 36):
        f[f"ret{k}"] = lc - np.concatenate([[np.nan] * k, lc[:-k]])
    # overnight gap: known at the session open, constant across that session's bars
    f["gap_open"] = pd.Series(np.where(first_in_sess, np.log(o / prev_c), np.nan)).groupby(sess).ffill().values
    f["body"] = np.log(c / o)
    f["range"] = np.log(h / l)
    f["wick_up"] = np.log(h / np.maximum(o, c))
    f["wick_dn"] = np.log(np.minimum(o, c) / l)
    sri = pd.Series(ri)
    rv12, rv36 = _roll(sri, 12, "std"), _roll(sri, VOL_WIN, "std")
    f["rv12"], f["rv36"] = rv12.values, rv36.values
    f["rv_ratio"] = (rv12 / rv36).values
    f["rv36_rel"] = (rv36 / _roll(rv36, 375, "mean")).values       # vol vs its own last 5 sessions (regime input)
    f["ret1_z"] = (sri / rv36).values
    f["ret6_z"] = (pd.Series(f["ret6"]) / (rv36 * np.sqrt(6))).values
    # --- trend
    for sp in (9, 21, 50):
        f[f"ema{sp}_dist"] = np.log(c / ema(c, sp))
    sma20 = _roll(pd.Series(c), 20, "mean"); sd20 = _roll(pd.Series(c), 20, "std")
    f["sma20_dist"] = np.log(c / sma20.values)
    e9, e21 = ema(c, 9), ema(c, 21)
    f["ema9_21"] = np.log(e9 / e21)
    f["ema21_slope"] = _slope(np.log(e21), 5)
    f["trend_slope20"] = _slope(lc, 20) / np.where(rv36 > 0, rv36, np.nan)       # slope in vol units
    f["up_frac10"] = _roll(pd.Series((ri > 0).astype(float)).where(~np.isnan(ri)), 10, "mean").values
    # --- momentum
    f["rsi14"] = rsi(c, 14)
    macd = ema(c, 12) - ema(c, 26)
    sig = ewma_fixed(np.nan_to_num(macd, nan=np.nan), 2 / 10, 27)   # 9-span signal over the macd series
    f["macd"] = macd / c
    f["macd_hist"] = (macd - sig) / c
    f["roc5"] = lc - np.concatenate([[np.nan] * 5, lc[:-5]])
    f["roc10"] = lc - np.concatenate([[np.nan] * 10, lc[:-10]])
    # --- volatility
    atr = wilder(true_range(h, l, c), 14)
    f["atr14"] = atr / c
    f["bb_width"] = (4 * sd20 / sma20).values
    f["bb_z"] = ((c - sma20) / sd20.replace(0, np.nan)).values
    f["range_vs_atr"] = (h - l) / atr
    # --- volume (NaN where unknown)
    sv = pd.Series(v)
    vma20 = _roll(sv, 20, "mean")
    f["rel_vol"] = (sv / vma20).values
    f["vol_chg"] = np.log(sv / sv.shift(1)).values
    f["vol_ma_ratio"] = (_roll(sv, 5, "mean") / vma20).values
    sign = np.sign(np.where(np.isnan(ri), 0, ri))
    sv12 = _roll(pd.Series(sign * v), 12, "sum"); av12 = _roll(pd.Series(v), 12, "sum")
    f["signed_vol12"] = (sv12 / av12).values
    tp = (h + l + c) / 3.0
    pv = pd.Series(tp * v).groupby(sess).cumsum(); cv = pd.Series(v).groupby(sess).cumsum()
    f["vwap_dist"] = np.log(c / (pv / cv).values)
    # --- structure
    for w in (20, 60):
        hh = _roll(pd.Series(h), w, "max"); ll = _roll(pd.Series(l), w, "min")
        f[f"dist_hi{w}"] = np.log(c / hh.values)
        f[f"dist_lo{w}"] = np.log(c / ll.values)
        f[f"range_pos{w}"] = ((c - ll) / (hh - ll).replace(0, np.nan)).values
    prior_hi20 = _roll(pd.Series(h).shift(1), 20, "max"); prior_lo20 = _roll(pd.Series(l).shift(1), 20, "min")
    f["breakout_up20"] = np.log(c / prior_hi20.values)
    f["breakout_dn20"] = np.log(c / prior_lo20.values)
    s_open = pd.Series(o).groupby(sess).transform("first")
    f["ret_from_open"] = np.log(c / s_open.values)
    f["dist_sess_hi"] = np.log(c / pd.Series(h).groupby(sess).cummax().values)
    f["dist_sess_lo"] = np.log(c / pd.Series(l).groupby(sess).cummin().values)
    # previous-session levels (known at t: that session is complete)
    last_close = pd.Series(c).groupby(sess).last(); day_hi = pd.Series(h).groupby(sess).max(); day_lo = pd.Series(l).groupby(sess).min()
    order = list(dict.fromkeys(sess))
    prev = {s: (order[i - 1] if i else None) for i, s in enumerate(order)}
    ps = pd.Series([prev[s] for s in sess])
    f["dist_prev_close"] = np.log(c / ps.map(last_close).astype(float).values)
    f["dist_prev_hi"] = np.log(c / ps.map(day_hi).astype(float).values)
    f["dist_prev_lo"] = np.log(c / ps.map(day_lo).astype(float).values)
    # --- time
    slot = g["slot"].values.astype(float)
    f["slot"] = slot
    f["session_progress"] = slot / (config.BARS_PER_SESSION - 1)
    f["slot_sin"], f["slot_cos"] = np.sin(2 * np.pi * slot / 75), np.cos(2 * np.pi * slot / 75)
    f["dow"] = pd.to_datetime(g["ts"], unit="s", utc=True).dt.tz_convert("Asia/Kolkata").dt.dayofweek.values.astype(float)
    f["is_open_30m"] = (slot < 6).astype(float)
    f["is_close_30m"] = (slot >= 69).astype(float)
    # --- multi-timeframe (completed buckets only)
    for m, tag, rn, es in ((3, "m15", 14, 20), (12, "h1", 7, 5)):
        hf = _htf_features(g, m, tag, rn, es)
        for col in hf.columns:
            if col != "ts":
                f[col] = hf[col].values
    # --- market context (optional NIFTY frame already feature-ised by index_context)
    if idx is not None:
        j = f[["ts"]].merge(idx, on="ts", how="left")
        for col in idx.columns:
            if col != "ts":
                f[col] = j[col].values
        f["rel_strength6"] = f["ret6"] - f["idx_ret6"]
        f["rel_strength12"] = f["ret12"] - f["idx_ret12"]
    return f


def index_context(idx_bars):
    """Causal NIFTY context features (same-session windows only -> NaN in the first k bars of a day)."""
    d = idx_bars.sort_values("ts").reset_index(drop=True)
    c = d["close"].astype(float).values
    out = pd.DataFrame({"ts": d["ts"].values})
    for k in (1, 6, 12):
        pc = pd.Series(c).shift(k).values
        same = (d["ts"].values - pd.Series(d["ts"]).shift(k).values) == k * config.BAR_SECONDS
        out[f"idx_ret{k}"] = np.where(same, np.log(c / pc), np.nan)
    r1 = pd.Series(out["idx_ret1"])
    out["idx_rv12"] = r1.rolling(12, min_periods=12).std().values
    out["idx_rsi14"] = rsi(c, 14)
    return out


def compute_features(bars, idx_bars=None):
    """bars: DataFrame[ts, open, high, low, close, volume, session, slot, seg] ascending, verified-only.
    Returns feature frame (one row per input bar) with columns ts, session, seg, warm + features."""
    idx = index_context(idx_bars) if idx_bars is not None and len(idx_bars) else None
    parts = []
    for seg, g in bars.groupby("seg", sort=True):
        f = _segment_features(g, idx)
        f["session"] = g["session"].values
        f["seg"] = seg
        f["seg_pos"] = np.arange(len(g))
        f["warm"] = f["seg_pos"] >= WARMUP_BARS
        parts.append(f)
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    return out.replace([np.inf, -np.inf], np.nan)


NON_FEATURE = {"ts", "session", "seg", "seg_pos", "warm"}


def feature_columns(df):
    return [c for c in df.columns if c not in NON_FEATURE]
