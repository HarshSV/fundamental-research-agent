"""Forecast core: timestamps, collector verification, quality checks, feature leakage, labels.
Synthetic bars are used ONLY to test invariants (no-leakage, label construction) - never for
performance claims."""
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from forecast import collector, config, quality, timeutil  # noqa: E402
from forecast.features import WARMUP_BARS, compute_features, feature_columns  # noqa: E402
from forecast.labels import build_labels, reconstruct_bars  # noqa: E402


def synth_bars(n_sessions=14, seed=0, start="2025-03-03"):
    rng = np.random.default_rng(seed)
    rows, price = [], 1000.0
    day = dt.date.fromisoformat(start)
    made = 0
    while made < n_sessions:
        if day.weekday() < 5:
            s = day.isoformat()
            for slot in range(75):
                o = price
                c = o * float(np.exp(rng.normal(0, 0.0015)))
                h = max(o, c) * float(np.exp(abs(rng.normal(0, 0.0007))))
                l = min(o, c) * float(np.exp(-abs(rng.normal(0, 0.0007))))
                rows.append((timeutil.slot_ts(s, slot), o, h, l, c, float(rng.lognormal(10, 0.5)), s, slot))
                price = c
            made += 1
        day += dt.timedelta(days=1)
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "session", "slot"])
    df["seg"] = 0
    return df


# ---------------------------------------------------------------- timestamps
def test_parse_angel_ts_is_ist_aware():
    ts = timeutil.parse_angel_ts("2026-09-10T15:25:00+05:30")
    assert timeutil.session_date(ts) == "2026-09-10"
    assert timeutil.slot_of(ts) == 74
    assert ts == dt.datetime(2026, 9, 10, 9, 55, tzinfo=dt.timezone.utc).timestamp()
    with pytest.raises(ValueError):
        timeutil.parse_angel_ts("2026-09-10T15:25:00")        # naive timestamps are refused


def test_slot_roundtrip():
    for slot in (0, 37, 74):
        assert timeutil.slot_of(timeutil.slot_ts("2025-03-03", slot)) == slot


# ---------------------------------------------------------------- collector verification
def test_chunk_grid_covers_range_without_overlap():
    a, b = dt.date(2023, 10, 5), dt.date(2026, 10, 5)
    ch = collector.chunk_grid(a, b)
    assert ch[0][0] == a and ch[-1][1] == b
    for (s0, e0), (s1, e1) in zip(ch, ch[1:]):
        assert s1 == e0 + dt.timedelta(days=1)
    assert all((e - s).days + 1 <= config.CHUNK_DAYS for s, e in ch)


def _ts(day, slot=0):
    return timeutil.slot_ts(day, slot)


def test_verify_chunk_detects_silent_truncation():
    today = dt.date(2026, 10, 5)
    ok = [_ts("2025-03-03"), _ts("2025-05-28")]
    assert collector.verify_chunk(dt.date(2025, 3, 1), dt.date(2025, 5, 29), ok, today)[0] == "ok"
    trunc = [_ts("2025-04-10"), _ts("2025-05-28")]           # oldest ~40 days missing, no error from API
    assert collector.verify_chunk(dt.date(2025, 3, 1), dt.date(2025, 5, 29), trunc, today)[0] == "late_start"
    assert collector.verify_chunk(dt.date(2025, 3, 1), dt.date(2025, 5, 29), [], today)[0] == "empty"
    early = [_ts("2025-03-03"), _ts("2025-04-20")]
    assert collector.verify_chunk(dt.date(2025, 3, 1), dt.date(2025, 5, 29), early, today)[0] == "early_end"


def test_verify_chunk_open_chunk_may_end_early():
    today = dt.date(2025, 5, 29)
    assert collector.verify_chunk(dt.date(2025, 3, 1), dt.date(2025, 5, 29), [_ts("2025-03-03"), _ts("2025-05-27")], today)[0] == "ok"


# ---------------------------------------------------------------- quality
def _flags(df):
    return {f[2] for f in quality.check_bars(quality.frame(
        [tuple(r) for r in df[["ts", "open", "high", "low", "close", "volume"]].itertuples(index=False)]))}


def test_quality_flags_invalid_ohlc_and_zero_volume_and_offgrid():
    df = synth_bars(2)
    assert "ohlc_invalid" not in _flags(df)
    bad = df.copy()
    bad.loc[10, "high"] = bad.loc[10, "low"] - 1          # H < L
    assert "ohlc_invalid" in _flags(bad)
    bad = df.copy(); bad.loc[5, "volume"] = 0.0
    assert "zero_volume" in _flags(bad)
    bad = df.copy(); bad.loc[5, "ts"] += 7
    assert "off_grid" in _flags(bad)
    bad = df.copy(); bad.loc[20, "close"] = bad.loc[19, "close"] * 1.6   # in-session 60% jump
    assert "abnormal_jump" in _flags(bad)
    dup = pd.concat([df, df.iloc[[3]]], ignore_index=True)
    assert "duplicate_ts" in _flags(dup)


def test_quality_flags_unadjusted_corporate_action_gap():
    df = synth_bars(3)
    df.loc[df["session"] == df["session"].unique()[1], ["open", "high", "low", "close"]] *= 0.5   # un-adjusted 1:1 bonus
    assert "possible_unadjusted_corporate_action" in _flags(df)


# ---------------------------------------------------------------- features: NO FUTURE LEAKAGE
def test_no_future_candle_enters_feature_matrix():
    """For several prediction timestamps t: (a) features computed from history truncated at t equal
    the features computed from the full history, for row t and every earlier row; (b) corrupting
    every bar AFTER t changes no feature at or before t."""
    bars = synth_bars(14)
    full = compute_features(bars)
    cols = feature_columns(full)
    for t_idx in (WARMUP_BARS + 3, WARMUP_BARS + 100, len(bars) - 5):
        trunc = compute_features(bars.iloc[: t_idx + 1].copy())
        a = full.loc[: t_idx, cols].to_numpy(dtype=float)
        b = trunc[cols].to_numpy(dtype=float)
        assert np.array_equal(a, b, equal_nan=True), "features at <= t depend on bars after t"
        corrupted = bars.copy()
        rng = np.random.default_rng(1)
        for col in ("open", "high", "low", "close", "volume"):
            corrupted.loc[t_idx + 1:, col] = corrupted.loc[t_idx + 1:, col] * rng.uniform(0.3, 3.0, len(corrupted) - t_idx - 1)
        c = compute_features(corrupted).loc[: t_idx, cols].to_numpy(dtype=float)
        assert np.array_equal(a, c, equal_nan=True)


def test_warm_rows_have_no_nan_in_core_features():
    full = compute_features(synth_bars(14))
    warm = full[full["warm"]]
    assert len(warm) > 0
    core = ["ret1", "rv36", "ema21_dist", "rsi14", "atr14", "dist_hi60", "h1_rsi", "m15_rsi", "macd_hist", "rel_vol"]
    assert not warm[core].isna().any().any(), warm[core].isna().sum().to_dict()


def test_htf_features_use_only_completed_buckets():
    """h1_ret1 at a bar inside an hour must equal the value from the last COMPLETED hour."""
    bars = synth_bars(10)
    f = compute_features(bars)
    s = bars["session"].unique()[-1]
    sub = f[bars["session"].values == s].reset_index(drop=True)
    # within the first hour (slots 0..10) the h1 value is constant (previous completed hour carried)
    assert sub.loc[:10, "h1_rsi"].nunique() == 1
    assert sub.loc[11, "h1_rsi"] != sub.loc[10, "h1_rsi"]      # hour 0 completes at slot 11


def test_zero_volume_becomes_nan_not_zero():
    bars = synth_bars(10)
    bars.loc[WARMUP_BARS + 5, "volume"] = 0.0
    f = compute_features(bars)
    assert np.isnan(f.loc[WARMUP_BARS + 5, "vol_chg"]) and np.isnan(f.loc[WARMUP_BARS + 5, "rel_vol"])


# ---------------------------------------------------------------- labels
def test_labels_use_exactly_the_future_and_never_cross_session():
    bars = synth_bars(3)
    lab = build_labels(bars)
    i = 40
    for h in config.HORIZONS:
        assert np.isclose(lab.loc[i, f"y_ret_{h}"], np.log(bars.loc[i + h, "close"] / bars.loc[i, "close"]))
    last_slot = bars.index[(bars["slot"] == 74)][0]
    assert np.isnan(lab.loc[last_slot, "y_ret_1"])               # no label across the session close
    assert np.isnan(lab.loc[last_slot - 2, "y_ret_5"]) and not np.isnan(lab.loc[last_slot - 2, "y_ret_2"])


def test_labels_unchanged_by_bars_beyond_horizon_and_features_unchanged_by_labels_window():
    bars = synth_bars(3)
    base = build_labels(bars)
    b2 = bars.copy(); b2.loc[60:, "close"] *= 2          # corrupt bars from index 60
    b2.loc[60:, ["open", "high", "low"]] *= 2
    l2 = build_labels(b2)
    # label at t = 54 with h <= 5 uses bars 55..59 only -> unchanged
    for h in config.HORIZONS:
        assert l2.loc[54, f"y_ret_{h}"] == base.loc[54, f"y_ret_{h}"]
    assert l2.loc[55, "y_ret_5"] != base.loc[55, "y_ret_5"]    # h=5 reaches bar 60


def test_label_gap_in_timestamps_blocks_label():
    bars = synth_bars(2)
    bars = bars.drop(index=30).reset_index(drop=True)            # one missing bar
    lab = build_labels(bars)
    assert np.isnan(lab.loc[29, "y_ret_1"]) and np.isnan(lab.loc[27, "y_ret_3"]) and not np.isnan(lab.loc[24, "y_ret_3"])


def test_flat_return_has_no_direction_label():
    bars = synth_bars(2)
    bars.loc[11, ["open", "high", "low", "close"]] = bars.loc[10, "close"]
    lab = build_labels(bars)
    assert np.isnan(lab.loc[10, "y_up_1"])


def test_ohlc_reconstruction_is_always_valid():
    rng = np.random.default_rng(3)
    for _ in range(200):
        r = rng.normal(0, 0.01, 5); wu = rng.normal(0, 0.005, 5); wd = rng.normal(0, 0.005, 5)   # even negative wicks
        for b in reconstruct_bars(1234.5, r, wu, wd):
            assert b["high"] >= max(b["open"], b["close"]) and b["low"] <= min(b["open"], b["close"])
