"""Verified daily bars -> segments -> features + labels + baseline columns (one frame per symbol, then pooled)."""
import numpy as np
import pandas as pd

from .. import store
from . import quality, universe
from .features import WARMUP_BARS, compute_features, feature_columns
from .labels import SHORT_H, build_labels


class UnverifiedDataError(RuntimeError):
    pass


def load_verified_bars(con, symbol):
    cal = quality.load_calendar(con)
    if not cal:
        raise UnverifiedDataError("no daily calendar - run forecast.daily.quality first")
    ver = quality.verified_dates(con, symbol)
    if not ver:
        raise UnverifiedDataError(f"{symbol}: no verified days")
    df = quality.load_bars(con, symbol)
    df["ds"] = df["date"].dt.strftime("%Y-%m-%d")
    first = df["ds"].min()
    seg_of, seg = {}, 0
    for day in sorted(d for d, t in cal.items() if (t or d in ver) and d >= first):
        if day in ver:
            seg_of[day] = seg
        else:
            seg += 1                          # an unverified / missing trading session breaks continuity
    df = df[df["ds"].isin(ver)].copy()
    df["seg"] = df["ds"].map(seg_of)
    return df.dropna(subset=["seg"]).drop(columns="ds").astype({"seg": int}).reset_index(drop=True)


def _index(con, name):
    if name is None:
        return None
    df = quality.load_bars(con, name)
    return df[["date", "close"]] if not df.empty else None


def regime_columns(m):
    """Fixed a-priori regimes from causal features: volatility vs own last year; market state from NIFTY."""
    rel = m["vol_rel"]
    m["vol_regime"] = np.where(rel > 1.25, "high_vol", np.where(rel < 0.8, "low_vol", "normal_vol"))
    m.loc[rel.isna(), "vol_regime"] = "unknown"
    if "mkt_dd252" in m:
        stress = m["mkt_dd252"] < -0.10
        up, dn = m["mkt_ret20"] > 0.02, m["mkt_ret20"] < -0.02
        m["market_regime"] = np.where(stress, "stress", np.where(up, "uptrend", np.where(dn, "downtrend", "range")))
        m.loc[m["mkt_ret20"].isna(), "market_regime"] = "unknown"
    else:
        m["market_regime"] = "unknown"
    return m


def build_matrix(con, symbol, horizons=SHORT_H, cfg=None):
    cfg = cfg or universe.load()
    bars = load_verified_bars(con, symbol)
    mkt = _index(con, universe.MARKET_INDEX)
    sec = _index(con, cfg["sector_map"].get(symbol))
    feats = compute_features(bars, mkt, sec)
    labels = build_labels(bars, horizons)
    m = pd.concat([feats, labels.drop(columns=["date"])], axis=1)
    g = bars.groupby("seg", sort=False)["close"]
    for h in horizons:                                           # baseline-only columns (causal past h-day return)
        m[f"bl_pastret_{h}"] = np.log(bars["close"].astype(float) / g.shift(h).astype(float)).values
    m["symbol"], m["close"] = symbol, bars["close"].values
    m["high"], m["low"] = bars["high"].values, bars["low"].values
    m["month"] = m["date"].dt.strftime("%Y-%m")
    m["year"] = m["date"].dt.year
    m = regime_columns(m)
    return m[m["warm"]].reset_index(drop=True), feature_columns(feats)


def model_features(m, fcols):
    """Model inputs: drop the baseline-only columns and any column that is all-NaN for this pooled frame."""
    return [c for c in fcols if not c.startswith("bl_") and m[c].notna().any()]


def load_pooled(con, symbols, horizons=SHORT_H, log=print):
    cfg = universe.load()
    mats, fcols, skipped = [], None, {}
    for s in symbols:
        try:
            m, fc = build_matrix(con, s, horizons, cfg)
        except UnverifiedDataError as e:
            skipped[s] = str(e)
            continue
        if len(m) < 300:
            skipped[s] = f"only {len(m)} warm rows"
            continue
        mats.append(m)
        fcols = fc if fcols is None else [c for c in fcols if c in fc]
        log(f"[daily data] {s}: {len(m)} warm rows {m['date'].min().date()}..{m['date'].max().date()}")
    M = pd.concat(mats, ignore_index=True)
    M["date"] = M["date"].dt.strftime("%Y-%m-%d")
    return M, model_features(M, fcols), skipped
