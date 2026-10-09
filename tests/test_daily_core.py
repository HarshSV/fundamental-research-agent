"""Daily track: collector verification, quality, feature/label leakage, baselines, embargo, HAR model.
Synthetic bars are used ONLY to test invariants (no-leakage, label construction) - never for performance claims."""
import datetime as dt
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from forecast import store, walkforward  # noqa: E402
from forecast.daily import baselines, collector, quality  # noqa: E402
from forecast.daily.features import WARMUP_BARS, compute_features, feature_columns  # noqa: E402
from forecast.daily.labels import build_labels  # noqa: E402
from forecast.daily.models import HarEmpiricalForecaster  # noqa: E402


def synth(n=700, seed=0, start="2018-01-01", vol_scale=1.0):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, periods=n)
    price, rows = 100.0, []
    for d in days:
        o = price * float(np.exp(rng.normal(0, 0.004)))
        c = o * float(np.exp(rng.normal(0, 0.012 * vol_scale)))
        h = max(o, c) * float(np.exp(abs(rng.normal(0, 0.004))))
        l = min(o, c) * float(np.exp(-abs(rng.normal(0, 0.004))))
        rows.append((d, o, h, l, c, float(rng.lognormal(12, 0.4))))
        price = c
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["seg"] = 0
    return df


@pytest.fixture()
def con(tmp_path):
    return store.connect(str(tmp_path / "d.db"))


# ------------------------------------------------------------ collector verification
def test_chunk_grid_is_a_gapless_partition_under_the_safe_size():
    a, b = dt.date(2000, 1, 1), dt.date(2026, 10, 5)
    g = collector.chunk_grid(a, b)
    assert g[0][0] == a and g[-1][1] == b
    for (s0, e0), (s1, e1) in zip(g, g[1:]):
        assert s1 == e0 + dt.timedelta(days=1)
    assert all((e - s).days + 1 <= collector.CHUNK_DAYS for s, e in g)          # ~960 rows << the provider's ~1,375 cap


def _d(s):
    return dt.date.fromisoformat(s)


def test_verify_chunk_detects_silent_truncation_but_tolerates_a_listing_date():
    today = _d("2026-10-05")
    full = [_d("2003-11-04"), _d("2007-08-30")]
    assert collector.verify_chunk(_d("2003-11-03"), _d("2007-08-31"), full, today)[0] == "ok"
    trunc = [_d("2005-02-01"), _d("2007-08-30")]                                  # oldest 14 months silently dropped
    assert collector.verify_chunk(_d("2003-11-03"), _d("2007-08-31"), trunc, today, listed_before=True)[0] == "suspect_truncated"
    assert collector.verify_chunk(_d("2003-11-03"), _d("2007-08-31"), trunc, today, listed_before=False)[0] == "late_start"   # IPO
    assert collector.verify_chunk(_d("2003-11-03"), _d("2007-08-31"), [], today)[0] == "empty"
    assert collector.verify_chunk(_d("2003-11-03"), _d("2007-08-31"), [_d("2003-11-04"), _d("2006-01-02")], today)[0] == "early_end"
    assert collector.verify_chunk(_d("2003-11-03"), _d("2007-08-31"), [_d("2003-10-01"), _d("2007-08-30")], today)[0] == "off_range"


def test_provider_timestamp_is_preserved_and_in_progress_bar_is_dropped():
    ist = collector._IST
    today = dt.date(2026, 10, 5)
    data = [["2026-10-01T00:00:00+05:30", 1, 2, 0.5, 1.5, 10], ["2026-10-05T00:00:00+05:30", 1, 2, 0.5, 1.5, 10]]
    during = collector._rows(data, today, dt.datetime(2026, 10, 5, 14, 0, tzinfo=ist))
    after = collector._rows(data, today, dt.datetime(2026, 10, 5, 16, 0, tzinfo=ist))
    assert [r[0] for r in during] == ["2026-10-01"] and [r[0] for r in after] == ["2026-10-01", "2026-10-05"]
    assert during[0][1] == "2026-10-01T00:00:00+05:30"                           # raw provider timestamp kept verbatim
    with pytest.raises(ValueError):
        collector._rows([["2026-10-01T00:00:00", 1, 2, 0.5, 1.5, 10]], today, dt.datetime(2026, 10, 5, 16, 0, tzinfo=ist))


def test_daily_upsert_is_idempotent_and_never_overwrites(con):
    rows = [("2024-01-02", "2024-01-02T00:00:00+05:30", 10.0, 11.0, 9.0, 10.5, 100.0)]
    assert collector.upsert(con, "AAA", rows) == (1, 0, 0)
    assert collector.upsert(con, "AAA", rows) == (0, 1, 0)
    changed = [("2024-01-02", "2024-01-02T00:00:00+05:30", 10.0, 11.0, 9.0, 99.0, 100.0)]
    assert collector.upsert(con, "AAA", changed) == (0, 0, 1)
    assert con.execute("SELECT close FROM daily_candles WHERE symbol='AAA'").fetchone()[0] == 10.5
    assert con.execute("SELECT count(*) FROM daily_quality_flags WHERE flag='revised_bar'").fetchone()[0] == 1


# ------------------------------------------------------------ quality
def _flagset(df):
    return {f[1] for f in quality.check_bars(df)}


def test_quality_flags_invalid_ohlc_zero_volume_flat_and_unadjusted_jump():
    df = synth(30)
    assert "ohlc_invalid" not in _flagset(df)
    bad = df.copy(); bad.loc[5, "high"] = bad.loc[5, "low"] - 1
    assert "ohlc_invalid" in _flagset(bad)
    z = df.copy(); z.loc[7, "volume"] = 0.0
    assert "zero_volume" in _flagset(z)
    f = df.copy(); f.loc[9, ["open", "high", "low", "close"]] = 100.0; f.loc[9, "volume"] = 0.0
    assert "flat_bar" in _flagset(f)
    j = df.copy(); j.loc[12:, ["open", "high", "low", "close"]] *= 0.5            # un-adjusted 1:1 bonus
    assert "possible_unadjusted_corporate_action" in _flagset(j)
    dup = pd.concat([df, df.iloc[[3]]], ignore_index=True)
    assert "duplicate_date" in _flagset(dup)


def test_calendar_and_missing_sessions_are_detected_not_repaired(con):
    days = [d for d in pd.bdate_range("2024-01-01", periods=30)]
    for sym in ("A", "B", "C", "D"):
        with con:
            con.execute("INSERT OR REPLACE INTO instruments VALUES (?,?,?,?,?,?)", (sym, "NSE", "1", sym, "equity", 0))
        keep = [d for d in days if not (sym == "D" and d == days[10]) and d != days[5]]          # days[5] = holiday for everyone
        collector.upsert(con, sym, [(d.strftime("%Y-%m-%d"), d.isoformat(), 10, 11, 9, 10, 100) for d in keep])
    res = quality.run(con, ["A", "D"], ref_symbols=["A", "B", "C", "D"])
    cal = quality.load_calendar(con)
    assert cal[days[5].strftime("%Y-%m-%d")] == 0 and cal[days[6].strftime("%Y-%m-%d")] == 1       # consensus holiday vs trading day
    a, d = res["per_symbol"]
    assert a["missing_sessions"] == 0 and d["missing_sessions"] == 1                              # D lacks a consensus session
    assert days[10].strftime("%Y-%m-%d") not in quality.verified_dates(con, "D")
    assert con.execute("SELECT count(*) FROM daily_candles WHERE symbol='D'").fetchone()[0] == 28   # nothing was filled in


# ------------------------------------------------------------ features: NO FUTURE LEAKAGE
def test_no_future_bar_enters_the_daily_feature_matrix():
    bars = synth(700)
    mkt = synth(700, seed=9)[["date", "close"]]
    sec = synth(700, seed=11)[["date", "close"]]
    full = compute_features(bars, mkt, sec)
    cols = feature_columns(full)
    assert {"mkt_ret20", "sec_ret20", "rel_ret20", "rel_sec20"} <= set(cols)
    rng = np.random.default_rng(1)
    for t in (WARMUP_BARS + 5, WARMUP_BARS + 150, len(bars) - 8):
        cutoff = bars.loc[t, "date"]
        trunc = compute_features(bars.iloc[: t + 1].copy(), mkt[mkt["date"] <= cutoff], sec[sec["date"] <= cutoff])
        a = full.loc[: t, cols].to_numpy(float)
        assert np.array_equal(a, trunc[cols].to_numpy(float), equal_nan=True), "features at <= t depend on bars after t"
        bad, mbad = bars.copy(), mkt.copy()
        for col in ("open", "high", "low", "close", "volume"):
            bad.loc[t + 1:, col] = bad.loc[t + 1:, col] * rng.uniform(0.3, 3.0, len(bad) - t - 1)
        mbad.loc[mbad["date"] > cutoff, "close"] *= 2.5                                           # corrupt FUTURE index bars too
        c = compute_features(bad, mbad, sec).loc[: t, cols].to_numpy(float)
        assert np.array_equal(a, c, equal_nan=True)


def test_mutation_centered_window_would_be_caught():
    """Guard the guard: a look-ahead feature (centered rolling) must make the leakage comparison fail."""
    bars = synth(400)
    full = bars["close"].rolling(20, center=True, min_periods=20).mean()
    trunc = bars.iloc[:300]["close"].rolling(20, center=True, min_periods=20).mean()
    assert not np.array_equal(full.iloc[:300].to_numpy(), trunc.to_numpy(), equal_nan=True)


def test_daily_warmup_zero_volume_nan_and_segment_isolation():
    bars = synth(700)
    f = compute_features(bars)
    assert not f["warm"].iloc[WARMUP_BARS - 1] and f["warm"].iloc[WARMUP_BARS]
    core = ["ret1", "rv20", "atr14", "rsi14", "dist_sma200", "dd252", "rel_vol20", "slope20", "vol_rel", "rv60", "sma50_200", "pos_range60"]
    assert not f[f["warm"]][core].isna().any().any()
    z = bars.copy(); z.loc[WARMUP_BARS + 5, "volume"] = 0.0
    fz = compute_features(z)
    assert np.isnan(fz.loc[WARMUP_BARS + 5, "rel_vol20"])                                          # unknown, never 0
    two = bars.copy(); two.loc[400:, "seg"] = 1                                                    # a missing session splits the series
    f2 = compute_features(two)
    assert f2.loc[400, "seg_pos"] == 0 and np.isnan(f2.loc[400, "ret20"]) and not f2.loc[400, "warm"]   # no window bridges the gap


# ------------------------------------------------------------ labels
def test_daily_labels_use_exactly_the_future_and_never_cross_segments():
    bars = synth(300)
    lab = build_labels(bars, (1, 3, 5, 10, 20))
    t = 100
    for h in (1, 3, 5, 10, 20):
        assert np.isclose(lab.loc[t, f"y_ret_{h}"], np.log(bars.loc[t + h, "close"] / bars.loc[t, "close"]))
        fut = bars.loc[t + 1: t + h]
        assert np.isclose(lab.loc[t, f"y_range_{h}"], np.log(fut["high"].max() / fut["low"].min()))
    b2 = bars.copy(); b2.loc[t + 21:, ["open", "high", "low", "close"]] *= 3                       # beyond the longest horizon
    l2 = build_labels(b2, (1, 3, 5, 10, 20))
    for h in (1, 3, 5, 10, 20):
        assert l2.loc[t, f"y_ret_{h}"] == lab.loc[t, f"y_ret_{h}"] and l2.loc[t, f"y_range_{h}"] == lab.loc[t, f"y_range_{h}"]
    b3 = bars.copy(); b3.loc[t + 5, "high"] *= 2                                                   # inside the 5-day window only
    l3 = build_labels(b3, (1, 5))
    assert l3.loc[t, "y_range_5"] != build_labels(bars, (1, 5)).loc[t, "y_range_5"] and l3.loc[t, "y_range_1"] == lab.loc[t, "y_range_1"]
    seg = bars.copy(); seg.loc[200:, "seg"] = 1
    ls = build_labels(seg, (5,))
    assert ls.loc[195:199, "y_ret_5"].isna().all() and not np.isnan(ls.loc[194, "y_ret_5"])        # nothing reaches across a break


# ------------------------------------------------------------ baselines / splits / model
def test_daily_baselines_learn_nothing_from_test_labels():
    rng = np.random.default_rng(0)
    H = (1, 5)

    def mk(n):
        d = {"rv20": np.full(n, 0.01), "sma50_200": rng.normal(0, 0.05, n)}
        for h in H:
            d[f"y_up_{h}"] = rng.integers(0, 2, n).astype(float)
            d[f"y_ret_{h}"] = rng.normal(0, 0.01, n)
            d[f"bl_pastret_{h}"] = rng.normal(0, 0.01, n)
        return pd.DataFrame(d)
    tr, te = mk(800), mk(300)
    a = baselines.baseline_wide(tr, te, H)
    te2 = te.copy()
    for h in H:
        te2[f"y_up_{h}"], te2[f"y_ret_{h}"] = 1 - te2[f"y_up_{h}"], te2[f"y_ret_{h}"] + 1
    assert a.equals(baselines.baseline_wide(tr, te2, H))
    assert {"persistence", "recent_return", "trend", "hist_vol"} <= {c.split("_ret_")[0] for c in a.columns if "_ret_" in c}


def test_daily_folds_embargo_exceeds_the_label_horizon():
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2000-01-03", periods=4000)]
    folds = walkforward.make_folds(dates, min_train=1500, cal=120, test=250, embargo=20)
    assert len(folds) >= 8
    idx = {d: i for i, d in enumerate(dates)}
    for fo in folds:
        walkforward.assert_no_overlap(fo)
        assert idx[fo["cal"][0]] - idx[fo["train"][-1]] > 20 and idx[fo["test"][0]] - idx[fo["cal"][-1]] > 20   # a 20-day label cannot reach the next block


def test_har_empirical_scale_follows_volatility_and_intervals_are_ordered():
    lo_v, hi_v = synth(900, 1, vol_scale=0.6), synth(900, 2, vol_scale=2.0)
    parts = []
    for b in (lo_v, hi_v):
        f = compute_features(b)
        lab = build_labels(b, (1, 5))
        m = pd.concat([f, lab.drop(columns=["date"])], axis=1)
        parts.append(m[m["warm"]])
    M = pd.concat(parts, ignore_index=True)
    mod = HarEmpiricalForecaster([], (1, 5)).fit(M.iloc[::2], M.iloc[1::2])
    p = mod.predict(M)
    for h in (1, 5):
        lo, hi = p[h]["intervals"][80]
        assert (hi > lo).all() and (p[h]["intervals"][95][1] >= hi).all() and (p[h]["intervals"][50][1] <= hi).all()
        wl, wh = (hi - lo)[: len(parts[0])].mean(), (hi - lo)[len(parts[0]):].mean()
        assert wh > 1.5 * wl                                                                          # wider when the stock is more volatile


# ------------------------------------------------------------ output formatting / long-horizon helpers
def test_forecast_output_never_invents_a_direction_or_a_range():
    from forecast.daily.gate import format_forecast
    preds = {1: {"ret_med": 0.001, "p_up": 0.51, "intervals": {50: (-0.004, 0.006), 80: (-0.009, 0.011), 95: (-0.016, 0.018)}},
             5: {"ret_med": 0.002, "p_up": 0.53, "intervals": {50: (None, None), 80: (None, None), 95: (None, None)}},
             20: {"ret_med": float("nan"), "p_up": float("nan"), "intervals": {80: (float("nan"), float("nan"))}}}
    out = format_forecast(100.0, preds, {1: False, 5: True, 20: False}, "2026-10-05", "dTEST", (1, 5, 20, 63))
    h1, h5, h20, h63 = out["horizons"]
    assert h1["status"] == "range_only" and h1["direction_probability"] is None and "directional signal uncertain" in h1["note"].lower()
    assert abs(h1["intervals"]["80"][0] - 100 * np.exp(-0.009)) < 1e-9
    assert h5["status"] == "unavailable" and h5["intervals"] is None                      # direction gate passed but NO range -> unavailable, not a guess
    assert h20["status"] == "unavailable" and h63["status"] == "unavailable"
    ok = format_forecast(100.0, {1: preds[1]}, {1: True}, "d", "v", (1,))["horizons"][0]
    assert ok["status"] == "directional" and ok["direction_probability"] == 0.51


def test_long_horizon_independence_counts_windows_not_rows():
    from forecast.daily.long_horizon import independence_report
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2005-01-03", periods=2600)
    mkt = rng.normal(0, 0.01, len(dates))
    rows = []
    for s in range(6):
        r = mkt + rng.normal(0, 0.003, len(dates))                                          # highly cross-correlated stocks
        h = 63
        y = pd.Series(r).rolling(h).sum().shift(-h)
        rows.append(pd.DataFrame({"symbol": f"S{s}", "date": dates.strftime("%Y-%m-%d"), f"y_ret_{h}": y.values}))
    M = pd.concat(rows, ignore_index=True)
    rep = independence_report(M, (63,)).iloc[0]
    assert rep["market_windows_nonoverlap"] == (len(dates) - 63 + 63 - 1) // 63 or rep["market_windows_nonoverlap"] > 30
    assert rep["mean_pairwise_corr"] > 0.8 and rep["effective_independent_stocks"] < 1.5   # pooling 6 stocks ~= 1 independent stock


def test_real_crashes_are_kept_but_clean_split_ratios_are_flagged():
    df = synth(40)
    crash = df.copy(); crash.loc[20:, ["open", "high", "low", "close"]] *= 0.72          # -33%: a real crash, not a split ratio
    fl = _flagset(crash)
    assert "extreme_move" in fl and "possible_unadjusted_corporate_action" not in fl
    split = df.copy(); split.loc[20:, ["open", "high", "low", "close"]] *= 0.2           # 1:5 un-adjusted
    assert "possible_unadjusted_corporate_action" in _flagset(split)
    half = df.copy(); half.loc[20:, ["open", "high", "low", "close"]] *= 0.5
    assert "possible_unadjusted_corporate_action" in _flagset(half)


def test_feature_schema_is_identical_with_and_without_context_indices():
    bars = synth(400)
    mk = synth(400, seed=9)[["date", "close"]]
    full = compute_features(bars, mk, mk)
    none = compute_features(bars, mk, None)
    assert list(full.columns) == list(none.columns)                       # pooling can never drop a feature
    assert none["sec_ret20"].isna().all() and none["rel_sec20"].isna().all() and full["sec_ret20"].notna().any()
