"""Verified-bar loading and training-matrix assembly.

The model may only ever see bars from sessions the quality pipeline marked `verified`.
A segment id increments at every unverified trading session, so no rolling window and no
label ever spans an unverified/missing session.
"""
import numpy as np
import pandas as pd

from . import config, quality, store
from .features import WARMUP_BARS, compute_features, feature_columns
from .labels import build_labels


class UnverifiedDataError(RuntimeError):
    pass


def load_verified_bars(con, symbol, interval=config.INTERVAL):
    cal = quality.load_calendar(con)
    if not cal:
        raise UnverifiedDataError("no session calendar - run forecast.quality.run first")
    ver = quality.verified_sessions(con, symbol, interval)
    if not ver:
        raise UnverifiedDataError(f"{symbol}: no verified sessions (quality pipeline not run or all sessions failed)")
    df = quality.frame(store.load_candles(con, symbol, interval))
    df = df[df["on_grid"] & df["slot"].between(0, config.USABLE_SLOTS - 1) & df["session"].isin(ver)]
    df = df.sort_values("ts").reset_index(drop=True)
    seg_of, seg = {}, 0
    for day in sorted(d for d, v in cal.items() if v["is_trading"]):
        if day in ver:
            seg_of[day] = seg
        elif day >= df["session"].min():
            seg += 1                       # an unverified trading session breaks continuity
    df["seg"] = df["session"].map(seg_of)
    return df.dropna(subset=["seg"]).astype({"seg": int}).reset_index(drop=True)


def build_matrix(con, symbol, interval=config.INTERVAL, index_symbol=None, horizons=config.HORIZONS):
    """Returns (frame, feature_cols). Rows with `warm == True` are the only ones usable for training/scoring.
    The SEQ_LEN-1 rows BEFORE warm-up are also kept (warm == False) purely as sequence history for the
    GRU's first warm rows - they are never trained on or evaluated. Label columns may be NaN for horizons
    crossing the session close."""
    bars = load_verified_bars(con, symbol, interval)
    idx = None
    if index_symbol:
        try:
            idx = load_verified_index(con, index_symbol, interval)
        except UnverifiedDataError:
            idx = None
    feats = compute_features(bars, idx)
    labels = build_labels(bars, horizons)
    m = pd.concat([feats, labels.drop(columns=["ts"])], axis=1)
    m["symbol"] = symbol
    m["close"] = bars["close"].values
    m["high"], m["low"], m["open"] = bars["high"].values, bars["low"].values, bars["open"].values
    keep = m["seg_pos"] >= WARMUP_BARS - (config.SEQ_LEN - 1)
    return m[keep].reset_index(drop=True), feature_columns(feats)


def load_verified_index(con, index_symbol, interval=config.INTERVAL):
    """Index bars have no volume; only structural checks apply (it is not a training target)."""
    df = quality.frame(store.load_candles(con, index_symbol, interval))
    if df.empty:
        raise UnverifiedDataError(f"{index_symbol}: no index data")
    return df[df["on_grid"] & df["slot"].between(0, config.USABLE_SLOTS - 1)].reset_index(drop=True)
