"""Forecast system: walk-forward splits, calibration, persistence, matching, confidence gates,
promotion gate, API shape, refusal to train on unverified data. Synthetic data is used ONLY to test
logic/invariants - never to claim model performance."""
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from forecast import api, baselines, calibration, config, confidence, dataset, features, inference, registry, store, tracking, walkforward  # noqa: E402
from test_forecast_core import synth_bars  # noqa: E402


@pytest.fixture()
def con(tmp_path):
    return store.connect(str(tmp_path / "t.db"))


# ------------------------------------------------------------ walk-forward / train-test separation
def test_walkforward_folds_are_time_ordered_disjoint_and_expanding():
    sessions = [f"2024-{m:02d}-{d:02d}" for m in range(1, 13) for d in range(1, 29)]
    folds = walkforward.make_folds(sessions, min_train=100, cal=20, test=20)
    assert len(folds) >= 5
    prev_test_end = None
    for fo in folds:
        walkforward.assert_no_overlap(fo)
        assert max(fo["train"]) < min(fo["cal"]) < max(fo["cal"]) < min(fo["test"])
        assert min(fo["test"]) > max(fo["train"])
        if prev_test_end:
            assert min(fo["test"]) > prev_test_end                      # test blocks march forward, never reused
        prev_test_end = max(fo["test"])
    assert len(folds[1]["train"]) > len(folds[0]["train"])             # expanding window
    assert len({s for fo in folds for s in fo["test"]}) == sum(len(fo["test"]) for fo in folds)   # disjoint tests


def test_baselines_use_only_training_statistics():
    rng = np.random.default_rng(0)
    mk = lambda n: pd.DataFrame({"ret6": rng.normal(0, 1e-3, n), "ema21_slope": rng.normal(0, 1e-4, n),
                                 **{f"y_up_{h}": rng.integers(0, 2, n).astype(float) for h in config.HORIZONS}})
    tr, te = mk(500), mk(200)
    a = baselines.baseline_predictions(tr, te)
    te2 = te.copy()
    for h in config.HORIZONS:
        te2[f"y_up_{h}"] = 1.0 - te2[f"y_up_{h}"]                      # change TEST labels only
    b = baselines.baseline_predictions(tr, te2)
    for name in a:
        for h in config.HORIZONS:
            assert np.array_equal(a[name][h]["p_up"], b[name][h]["p_up"])      # nothing learned from test labels


# ------------------------------------------------------------ calibration
def test_conformal_margin_restores_coverage_out_of_sample():
    rng = np.random.default_rng(1)
    n = 6000
    y = rng.normal(0, 1.0, n)
    lo, hi = np.full(n, -0.5), np.full(n, 0.5)                          # badly under-covering intervals (~38%)
    cal, test = slice(0, 3000), slice(3000, n)
    m = calibration.cqr_margin(lo[cal], hi[cal], y[cal], alpha=0.2)
    cov_raw = np.mean((y[test] >= lo[test]) & (y[test] <= hi[test]))
    cov = np.mean((y[test] >= lo[test] - m) & (y[test] <= hi[test] + m))
    assert cov_raw < 0.5 and 0.77 <= cov <= 0.83
    assert calibration.cqr_margin(lo[:10], hi[:10], y[:10], 0.2) is None   # too little data -> no fake calibration


def test_isotonic_probability_calibration_fixes_overconfidence():
    rng = np.random.default_rng(2)
    n = 4000
    p_true = rng.uniform(0.4, 0.6, n)
    y = (rng.uniform(size=n) < p_true).astype(float)
    p_raw = np.clip(0.5 + (p_true - 0.5) * 4, 0.01, 0.99)               # over-confident
    cal = calibration.ProbCalibrator().fit(p_raw[:2000], y[:2000])
    b_raw = np.mean((p_raw[2000:] - y[2000:]) ** 2)
    b_cal = np.mean((cal.predict(p_raw[2000:]) - y[2000:]) ** 2)
    assert b_cal < b_raw


# ------------------------------------------------------------ store idempotency / revisions
def test_store_upsert_is_idempotent_and_flags_revisions_without_overwriting(con):
    rows = [(1_700_000_100, 10.0, 11.0, 9.0, 10.5, 100.0), (1_700_000_400, 10.5, 11.0, 10.0, 10.7, 50.0)]
    assert store.upsert_candles(con, "AAA", "5m", rows) == (2, 0, 0)
    assert store.upsert_candles(con, "AAA", "5m", rows) == (0, 2, 0)                       # duplicate-safe
    changed = [(rows[0][0], 10.0, 11.0, 9.0, 99.0, 100.0)]
    assert store.upsert_candles(con, "AAA", "5m", changed) == (0, 0, 1)
    assert store.load_candles(con, "AAA")[0][4] == 10.5                                     # original kept
    assert con.execute("SELECT count(*) FROM quality_flags WHERE flag='revised_bar'").fetchone()[0] == 1


def test_dataset_refuses_unverified_data(con):
    store.upsert_candles(con, "AAA", "5m", [(1_700_000_100, 10, 11, 9, 10.5, 1.0)])
    with pytest.raises(dataset.UnverifiedDataError):
        dataset.load_verified_bars(con, "AAA")


# ------------------------------------------------------------ forecast persistence + matching
def _payload(as_of, sym="AAA", fid=None):
    fid = fid or tracking.new_forecast_id()
    mk = lambda h: {"horizon": h, "forecast_timestamp": as_of + (h - 1) * 300, "open": 10.0, "high": 10.3, "low": 9.9, "close": 10.1,
                    "predicted_return": float(np.log(10.1 / 10.0)), "direction_probability": 0.6, "confidence": "LOW", "confidence_score": 0.3,
                    "intervals": {"50": [9.95, 10.2], "80": [9.9, 10.3], "95": [9.8, 10.4]}}
    return {"forecast_id": fid, "symbol": sym, "timeframe": "5m", "as_of_ts": as_of, "regime": "range|normal_vol",
            "model_version": "vT", "feature_version": "f1", "ensemble_version": "vT", "forecasts": [mk(h) for h in (1, 2)]}


def test_forecasts_are_append_only_and_matched_to_actual_candles(con):
    as_of = 1_700_000_400_000 // 1000 // 300 * 300 - 86400 * 3
    p = _payload(as_of)
    assert tracking.save_forecast(con, p) == 2
    # a second forecast for the same key must NOT overwrite the original
    p2 = _payload(as_of)
    p2["forecasts"][0]["close"] = 99.0
    assert tracking.save_forecast(con, p2) == 0
    assert con.execute("SELECT predicted_close FROM forecasts WHERE horizon=1").fetchone()[0] == 10.1
    # nothing evaluated while the actual candle is absent
    assert tracking.evaluate_pending(con) == 0
    base_ts = as_of - 300                       # candle the forecast was made from (its CLOSE is as_of)
    store.upsert_candles(con, "AAA", "5m", [(base_ts, 10.0, 10.0, 10.0, 10.0, 5.0),
                                            (as_of, 10.0, 10.4, 9.95, 10.2, 7.0),         # horizon 1 target
                                            (as_of + 300, 10.2, 10.3, 10.0, 10.05, 7.0)])  # horizon 2 target
    assert tracking.evaluate_pending(con) == 2
    r = con.execute("SELECT horizon,actual_close,direction_correct,in_interval_json,return_error FROM forecast_evaluations ORDER BY horizon").fetchall()
    assert r[0][1] == 10.2 and r[0][2] == 1                                   # predicted up, actual up
    assert json.loads(r[0][3]) == {"50": True, "80": True, "95": True}
    assert r[1][2] == 1                                                       # h2: actual ln(10.05/10) > 0 and p>0.5
    assert tracking.evaluate_pending(con) == 0                                # idempotent
    st = tracking.monitoring_stats(con)
    assert st["n_evaluated"] == 2 and st["by_horizon"]["1"]["direction_accuracy"] == 1.0


# ------------------------------------------------------------ confidence engine
def _assess(p, **kw):
    n = len(p)
    base = dict(p_models=[p, p], ret_models=[np.full(n, 1e-3)] * 2, ret_med=np.full(n, 1e-3), width80=np.full(n, 0.004),
                regime_stable=1.0, shap_agree=np.full(n, 0.9), perf_skill=0.01, data_ok=1.0)
    base.update(kw)
    return confidence.assess(p, **base)


def test_confidence_levels_and_gates():
    p = np.array([0.62, 0.62, 0.50])
    a = _assess(p)
    assert a["level"][0] in ("HIGH", "MEDIUM") and a["level"][2] in ("LOW", "NO_RELIABLE_FORECAST")
    # no demonstrated out-of-sample skill caps confidence regardless of how sharp the probability is
    nsk = _assess(np.array([0.7]), perf_skill=0.0)
    assert nsk["level"][0] in ("LOW", "NO_RELIABLE_FORECAST")
    # a hard gate always withholds
    g = _assess(np.array([0.7]), gated=np.array([True]))
    assert g["level"][0] == "NO_RELIABLE_FORECAST" and g["score"][0] == 0.0
    # NaN inputs never produce a forecast
    assert _assess(np.array([np.nan]))["level"][0] == "NO_RELIABLE_FORECAST"
    # model disagreement lowers the score
    dis = _assess(np.array([0.62]), p_models=[np.array([0.62]), np.array([0.40])])
    assert dis["score"][0] < a["score"][0]


def test_input_distribution_gate():
    env = {"x": (-1.0, 1.0), "y": (0.0, 2.0)}
    df = pd.DataFrame({"x": [0.0, 5.0, np.nan], "y": [1.0, 9.0, 1.0]})
    ok = confidence.in_distribution(df, env, max_outside_frac=0.4)
    assert list(ok) == [True, False, True]


# ------------------------------------------------------------ registry / promotion gate
def test_failed_gate_never_promotes_and_records_reasons(con):
    registry.register(con, "vBad", "x", "f1", "2024-01-01", "2025-01-01", {}, {}, "/nonexistent")
    gate = {"pass": False, "reasons": ["h=1: range gate failed"]}
    assert registry.promote(con, "vBad", gate) is False
    assert con.execute("SELECT status FROM model_registry WHERE model_version='vBad'").fetchone()[0] == "rejected"
    assert registry.production_model(con) is None
    registry.register(con, "vGood", "x", "f1", "2024-01-01", "2025-01-01", {"a": 1}, {"m": 2}, "/p")
    assert registry.promote(con, "vGood", {"pass": True, "reasons": []}) is True
    assert registry.production_model(con)["model_version"] == "vGood"
    registry.register(con, "vNext", "x", "f1", "2024-01-01", "2025-06-01", {}, {}, "/p2")
    registry.promote(con, "vNext", {"pass": True, "reasons": []})
    assert registry.production_model(con)["model_version"] == "vNext"
    assert con.execute("SELECT status FROM model_registry WHERE model_version='vGood'").fetchone()[0] == "retired"


def test_promotion_gate_rejects_a_model_equal_to_its_baseline():
    rng = np.random.default_rng(5)
    n = 4000
    sig = np.full(n, 1e-3)
    d = {"symbol": ["A"] * n, "session": [f"2025-01-{1 + i // 200:02d}" for i in range(n)], "rv36": sig, "fold": [i // 1000 for i in range(n)]}
    for h in config.HORIZONS:
        y = rng.normal(0, 1e-3 * np.sqrt(h), n)
        d[f"y_ret_{h}"] = y
        d[f"y_up_{h}"] = (y > 0).astype(float)
        for name in ("persistence", "recent_return", "trend", "ens"):          # model == baseline: zero edge
            d[f"{name}_ret_{h}"] = np.zeros(n)
            d[f"{name}_pup_{h}"] = np.full(n, 0.5)
            for lv, z in ((50, 0.674), (80, 1.2816), (95, 1.96)):
                d[f"{name}_lo{lv}_{h}"], d[f"{name}_hi{lv}_{h}"] = -z * 1e-3 * np.sqrt(h) * np.ones(n), z * 1e-3 * np.sqrt(h) * np.ones(n)
    gate = registry.promotion_gate(pd.DataFrame(d), "ens", boot=200)
    assert gate["pass"] is False and not any(gate["direction_validated"].values())


# ------------------------------------------------------------ live inference safety
def test_inference_never_fabricates_without_a_production_model(con):
    out = inference.forecast_payload(con, "AAA", 1_700_000_100, persist=False)
    assert out["status"] == "NO_RELIABLE_FORECAST"
    assert out["reasons"][0].startswith("no_production_model")
    assert all(f["confidence"] == "NO_RELIABLE_FORECAST" and f.get("close") is None for f in out["forecasts"])


# ------------------------------------------------------------ API shape
def test_api_separates_actual_and_forecast_candles(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    db = str(tmp_path / "api.db")
    monkeypatch.setattr(config, "DB_PATH", db)
    c = store.connect(db)
    as_of = (int(time.time()) // 300) * 300
    base = as_of - 300
    store.upsert_candles(c, "AAA", "5m", [(base - 300 * i, 10.0, 10.2, 9.9, 10.1, 5.0) for i in range(5)])
    payload = _payload(as_of)
    payload.update({"status": "OK", "current_candle": {"time": base, "open": 10, "high": 10.2, "low": 9.9, "close": 10.1, "volume": 5.0}})
    payload["forecasts"][1].update({"close": None, "open": None, "high": None, "low": None, "status": "withheld", "intervals": None, "confidence": "NO_RELIABLE_FORECAST"})
    payload["forecasts"][0]["status"] = "ok"
    monkeypatch.setattr(inference, "forecast_payload", lambda *a, **k: payload)
    app = FastAPI()
    app.include_router(api.make_router(lambda s: s.upper(), lambda: {"ok": True}))
    r = TestClient(app).get("/api/chart/aaa/forecast")
    assert r.status_code == 200
    j = r.json()
    assert j["symbol"] == "AAA" and j["timeframe"] == "5m" and j["as_of"] == as_of
    assert all(c["isForecast"] is False for c in j["actualCandles"]) and j["actualCandles"]
    assert all(c["isForecast"] is True for c in j["forecastCandles"])
    assert [c["horizon"] for c in j["forecastCandles"]] == [1]          # the withheld horizon produced NO candle
    assert j["forecastEnvelope"][0]["intervals"]["80"] == [9.9, 10.3]
    assert j["forecast"]["model_version"] == "vT" and "disclaimer" not in json.dumps(j["forecastCandles"])
    assert {c["time"] for c in j["actualCandles"]}.isdisjoint({c["time"] for c in j["forecastCandles"]})


def test_feature_version_constant_matches_engine():
    assert config.FEATURE_VERSION == "f1" and features.WARMUP_BARS >= 450


# ------------------------------------------------------------ candle aggregation
def test_higher_timeframe_buckets_aggregate_correctly_and_exclude_partials():
    bars = synth_bars(2)
    h = features._htf(bars, 3)                                    # 15m
    first = bars.iloc[:3]
    assert h.iloc[0]["open"] == first["open"].iloc[0] and h.iloc[0]["close"] == first["close"].iloc[-1]
    assert h.iloc[0]["high"] == first["high"].max() and h.iloc[0]["low"] == first["low"].min()
    assert np.isclose(h.iloc[0]["volume"], first["volume"].sum())
    assert h.iloc[0]["end_ts"] == first["ts"].iloc[-1]            # completes on its LAST 5m bar
    assert len(h) == 2 * 25                                       # 75 bars/session -> 25 complete 15m bars
    hourly = features._htf(bars, 12)
    assert len(hourly) == 2 * 6                                   # the trailing 3-bar partial hour is never emitted
    partial = features._htf(bars.iloc[:14], 12)
    assert len(partial) == 1 and partial.iloc[0]["n"] == 12       # an incomplete bucket is excluded


# ------------------------------------------------------------ live window safety
def _fill(con, sessions, current, n_current, skip=None):
    from forecast.timeutil import slot_ts
    rows = []
    for s in sessions:
        rows += [(slot_ts(s, i), 100.0, 100.5, 99.5, 100.2, 10.0) for i in range(75)]
    rows += [(slot_ts(current, i), 100.0, 100.5, 99.5, 100.2, 10.0) for i in range(n_current) if i != skip]
    store.upsert_candles(con, "AAA", "5m", rows)


def test_live_window_accepts_complete_history_and_refuses_stale_or_gappy_current_session(con):
    from forecast.timeutil import slot_ts
    days = ["2025-03-03", "2025-03-04", "2025-03-05", "2025-03-06", "2025-03-07", "2025-03-10", "2025-03-11"]
    cur = "2025-03-12"
    as_of = slot_ts(cur, 30)                                      # slots 0..29 are complete
    _fill(con, days, cur, 30)
    bars, issues = inference.live_window(con, "AAA", as_of, index_symbol=None)
    assert issues == [] and bars["seg"].nunique() == 1 and bars["ts"].iloc[-1] + 300 == as_of
    # stale: latest stored bar is older than the latest completed bar
    bars, issues = inference.live_window(con, "AAA", slot_ts(cur, 33), index_symbol=None)
    assert "current_session_bars_stale_or_gappy" in issues
    con2 = store.connect(str(con.execute("PRAGMA database_list").fetchone()[2]) + ".b")
    _fill(con2, days, cur, 30, skip=12)                           # a missing bar inside the current session
    bars, issues = inference.live_window(con2, "AAA", as_of, index_symbol=None)
    assert "current_session_bars_stale_or_gappy" in issues
    # a partial prior session breaks continuity (segment id changes) instead of being silently bridged
    con3 = store.connect(str(con.execute("PRAGMA database_list").fetchone()[2]) + ".c")
    _fill(con3, days, cur, 30)
    con3.execute("DELETE FROM candles WHERE symbol='AAA' AND ts=?", (slot_ts("2025-03-06", 20),)); con3.commit()
    bars, issues = inference.live_window(con3, "AAA", as_of, index_symbol=None)
    assert bars["seg"].nunique() == 2 and set(bars["session"][bars["seg"] == 0]) == {"2025-03-03", "2025-03-04", "2025-03-05"}


# ------------------------------------------------------------ persistence regression + refresh dedupe
def test_withheld_payload_is_not_persisted_so_it_cannot_block_the_real_forecast(con):
    """A 'stale data' withheld payload must not occupy the (symbol, as_of, horizon, model) key."""
    as_of = (int(time.time()) // 300) * 300
    withheld = inference._withheld("AAA", as_of, ["data_not_usable: stale"], {"model_version": "vT"})
    assert withheld["status"] == "NO_RELIABLE_FORECAST"
    # forecast_payload persists only OK / RANGE_ONLY; emulate the guard directly
    assert con.execute("SELECT count(*) FROM forecasts").fetchone()[0] == 0
    real = _payload(as_of)
    assert tracking.save_forecast(con, real) == 2          # the real forecast for the same bar is stored


def test_live_ingest_knows_when_the_store_is_behind():
    from forecast import live_ingest as li
    from forecast.timeutil import slot_ts
    d = "2025-03-12"                                              # a Wednesday
    now = slot_ts(d, 30) + 20                                     # 20 s after the slot-30 boundary
    exp = li.expected_bar_open(now)
    assert exp == slot_ts(d, 29) and li.in_session(exp)
    assert li.bar_is_behind(slot_ts(d, 28), now) is True          # latest stored is a bar behind
    assert li.bar_is_behind(exp, now) is False                    # current
    assert li.bar_is_behind(None, now) is True                    # nothing stored at all
    assert li.bar_is_behind(slot_ts(d, 10), slot_ts(d, 75) + 20) is False    # after the close: never "behind"
    assert li.bar_is_behind(0, slot_ts("2025-03-15", 20) + 20) is False       # Saturday


def test_scheduler_retries_until_bar_present_then_stops_and_caps_attempts(monkeypatch):
    from forecast import live_ingest as li
    from forecast.timeutil import slot_ts
    now0 = slot_ts("2025-03-12", 30) + 5
    clock = {"t": now0}
    monkeypatch.setattr(li.time, "time", lambda: clock["t"])
    latest = {"v": slot_ts("2025-03-12", 28)}
    monkeypatch.setattr(li, "_latest_open", lambda s: latest["v"])
    calls = []
    monkeypatch.setattr(li, "refresh_symbol", lambda s, *a, **k: calls.append(clock["t"]))
    li._active.clear(); li._attempts.clear()
    li._active["AAA"] = clock["t"]
    li._tick()
    assert len(calls) == 1                                        # behind -> fetch immediately after the boundary
    li._tick()
    assert len(calls) == 1                                        # respects RETRY_GAP
    clock["t"] += li.RETRY_GAP + 0.1
    li._tick()
    assert len(calls) == 2                                        # retries while the bar is missing
    latest["v"] = slot_ts("2025-03-12", 29)                       # the bar arrives
    clock["t"] += li.RETRY_GAP + 0.1
    li._tick()
    assert len(calls) == 2 and not li.bar_is_behind(latest["v"], clock["t"])    # no further fetches
    latest["v"] = slot_ts("2025-03-12", 28)                       # provider never delivers: attempt cap
    li._attempts["AAA"] = (li.expected_bar_open(clock["t"]), li.MAX_ATTEMPTS_PER_BAR, 0)
    n = len(calls); clock["t"] += 10
    li._tick()
    assert len(calls) == n                                        # capped for this boundary (holiday/outage safety)


# ------------------------------------------------------------ symbol onboarding gate
def test_symbol_status_pilot_validated_failed_and_retry(con):
    from forecast import onboarding
    prod, meta = {"model_version": "vT"}, {"validated_symbols": ["PILOT"]}
    assert onboarding.symbol_status(con, "PILOT", prod, meta) == ("pilot", [])
    assert onboarding.symbol_status(con, "NEW", prod, meta) == ("unknown", [])
    def put(sym, status, reasons, age=0):
        con.execute("INSERT OR REPLACE INTO symbol_validation VALUES (?,?,?,?,?,?)", (sym, "vT", status, json.dumps(reasons), "{}", int(time.time()) - age)); con.commit()
    put("GOOD", "validated", [])
    put("BAD", "failed", ["illiquid: 40% of bars have zero/missing volume"])
    assert onboarding.symbol_status(con, "GOOD", prod, meta) == ("validated", [])
    assert onboarding.symbol_status(con, "BAD", prod, meta)[0] == "failed"
    put("OLD", "failed", ["x"], age=onboarding.RETRY_FAILED_AFTER + 10)
    assert onboarding.symbol_status(con, "OLD", prod, meta)[0] == "unknown"       # a failed symbol is re-tried after a day
    assert onboarding.symbol_status(con, "GOOD", {"model_version": "vNEW"}, meta)[0] == "unknown"   # a new model re-validates everyone
    assert onboarding.coverage(con, "vT")["validated"] == 1


def test_gaussian_baseline_columns_are_wider_for_longer_horizons():
    from forecast import onboarding
    df = pd.DataFrame({"rv36": [0.001, 0.002]})
    c = onboarding._gaussian_cols(df, config.HORIZONS)
    assert (c["persistence_hi80_5"] > c["persistence_hi80_1"]).all() and (c["persistence_lo95_1"] < c["persistence_lo80_1"]).all()


def test_expected_last_bar_is_capped_at_the_last_usable_slot():
    from forecast.timeutil import slot_ts
    d = "2025-03-12"
    assert inference.expected_last_bar_ts(slot_ts(d, 30)) == slot_ts(d, 29)               # mid-session: the last completed bar
    assert inference.expected_last_bar_ts(slot_ts(d, 72)) == slot_ts(d, 71)               # 15:15: bar 71 completes at 15:15
    assert inference.expected_last_bar_ts(slot_ts(d, 75)) == slot_ts(d, 71)               # 15:30: still the last USABLE bar (not "stale")
