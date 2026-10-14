"""Deterministic candlestick definitions, future-pattern interpretation and leak-free historical stats."""
import copy

from forecast import candle_patterns as cp, pattern_forecast as pf, pattern_stats as ps, config

T0 = 1_800_000_000


def bar(i, o, h, l, c):
    return {"time": T0 + i * 300, "open": o, "high": h, "low": l, "close": c}


def prefix(direction, n=7):
    out = []
    for i in range(n):
        c = 100 - i if direction == "down" else 94 + i
        o = c + 1 if direction == "down" else c - 1
        out.append(bar(i, o, max(o, c) + 0.2, min(o, c) - 0.2, c))
    return out


def seq(direction, rows):
    base = prefix(direction)
    return base + [bar(len(base) + k, *r) for k, r in enumerate(rows)]


def mirror(candles):
    return [bar(int((c["time"] - T0) / 300), 200 - c["open"], 200 - c["low"], 200 - c["high"], 200 - c["close"]) for c in candles]


def names(candles, i=None):
    i = len(candles) - 1 if i is None else i
    return {d["pattern"] for d in cp.detect_at(candles, i)}


FIXTURES = {  # (down-trend sequence, expected, mirrored expected)
    "hammer": (seq("down", [(94.0, 94.25, 93.0, 94.2)]), "hammer", "shooting_star"),
    "inverted_hammer": (seq("down", [(94.0, 95.4, 93.95, 94.2)]), "inverted_hammer", "hanging_man"),
    "engulfing": (seq("down", [(94.1, 94.2, 93.5, 93.6), (93.5, 94.4, 93.4, 94.3)]), "bullish_engulfing", "bearish_engulfing"),
    "piercing": (seq("down", [(94.2, 94.25, 92.95, 93.0), (92.8, 93.85, 92.75, 93.8)]), "piercing_pattern", "dark_cloud_cover"),
    "morning": (seq("down", [(94.2, 94.25, 92.95, 93.0), (92.8, 93.0, 92.7, 92.9), (92.95, 93.95, 92.9, 93.9)]), "morning_star", "evening_star"),
}


def test_each_pattern_and_its_mirror_are_detected():
    for key, (s, up_name, mirror_name) in FIXTURES.items():
        assert up_name in names(s), key
        assert mirror_name in names(mirror(s)), key


def test_three_soldiers_and_crows():
    s = [bar(0, 100, 101.05, 99.95, 101), bar(1, 100.5, 102.05, 100.45, 102), bar(2, 101.5, 103.05, 101.45, 103)]
    assert "three_white_soldiers" in names(s)
    assert "three_black_crows" in names(mirror(s))
    assert "three_white_soldiers" not in names(mirror(s))


def test_context_dependent_patterns_need_the_trend():
    flat = [bar(i, 100, 100.2, 99.8, 100) for i in range(7)]
    hammer = flat + [bar(7, 100.0, 100.25, 99.0, 100.2)]
    assert not ({"hammer", "hanging_man"} & names(hammer))          # no trend context -> not that pattern
    up = seq("up", [(100.0, 100.25, 99.0, 100.2)])
    assert "hanging_man" in names(up) and "hammer" not in names(up)
    eng = flat + [bar(7, 100.1, 100.2, 99.5, 99.6), bar(8, 99.5, 100.4, 99.4, 100.3)]
    assert "bullish_engulfing" not in names(eng)


def test_insufficient_history_is_not_a_detection():
    s = seq("down", [(94.0, 94.25, 93.0, 94.2)])[-3:]
    assert not ({"hammer", "hanging_man"} & names(s))


def test_doji_edges_and_zero_range():
    assert "doji" in names([bar(0, 100, 101, 99, 100.1)])               # body 5% of range
    assert "doji" not in names([bar(0, 100, 101, 99, 100.5)])           # 25%
    assert names([bar(0, 100, 100, 100, 100)]) == set()                   # zero range matches nothing
    assert names([{"open": None, "high": 1, "low": 0, "close": 0.5, "time": 0}]) == set()   # unknown value, no pattern


def test_detection_has_no_lookahead():
    s = FIXTURES["engulfing"][0]
    i = len(s) - 1
    before = cp.detect_at(s, i)
    extended = s + [bar(len(s), 94.3, 120, 50, 60), bar(len(s) + 1, 60, 200, 1, 150)]
    assert cp.detect_at(extended, i) == before


# --- future-pattern interpretation ---------------------------------------------------------------
def fc(h, o, hi, lo, c, **kw):
    return {"horizon": h, "time": T0 + (100 + h) * 300, "open": o, "high": hi, "low": lo, "close": c, **kw}


ACTUAL = seq("down", [(94.1, 94.2, 93.5, 93.6)])           # ends with a bearish candle in a downtrend


def test_range_only_forecast_has_no_pattern_reading():
    r = pf.pattern_forecast(ACTUAL, [])
    assert r["status"] == "unavailable" and r["probability"] is None and r["patterns"] == []


def test_single_path_is_model_implied_never_a_probability():
    r = pf.pattern_forecast(ACTUAL, [fc(1, 93.5, 94.4, 93.4, 94.3)])
    assert r["status"] == "model_implied"
    p = r["patterns"][0]
    assert p["pattern"] == "bullish_engulfing" and p["formation_horizon"] == 1 and p["label"] == "model_implied"
    assert p["probability"] is None and r["probability"] is None
    assert p["supporting_horizons"] == [1] and p["uses_actual_candles"]


def test_path_stops_at_the_first_missing_horizon():
    path = pf.leading_path([fc(1, 1, 2, 0.5, 1.5), fc(3, 1, 2, 0.5, 1.5)])
    assert [c["horizon"] for c in path] == [1]
    assert pf.leading_path([fc(2, 1, 2, 0.5, 1.5)]) == []


def test_insufficient_actual_history():
    r = pf.pattern_forecast(ACTUAL[:3], [fc(1, 93.5, 94.4, 93.4, 94.3)])
    assert r["status"] == "unavailable" and "Insufficient history" in r["reason"]


def test_scenario_aggregation_requires_multiple_paths_and_counts_frequency():
    assert pf.aggregate_scenarios(ACTUAL, [[fc(1, 93.5, 94.4, 93.4, 94.3)]]) is None
    hit = [fc(1, 93.5, 94.4, 93.4, 94.3)]
    miss = [fc(1, 93.5, 93.7, 93.3, 93.6)]
    agg = pf.aggregate_scenarios(ACTUAL, [hit, hit, miss, miss])
    assert agg["bullish_engulfing"] == {"frequency": 0.5, "n_scenarios": 4}


def test_inputs_are_not_mutated():
    a, f = copy.deepcopy(ACTUAL), [fc(1, 93.5, 94.4, 93.4, 94.3)]
    a0, f0 = copy.deepcopy(a), copy.deepcopy(f)
    pf.pattern_forecast(a, f)
    assert a == a0 and f == f0


# --- historical statistics: strictly later outcomes, session-bounded --------------------------------
def session(day_offset, closes=None):
    out = []
    for s in range(config.USABLE_SLOTS):
        c = closes[s] if closes else 100.0
        out.append({"time": T0 + day_offset * 86400 + s * 300, "open": c, "high": c + 0.3, "low": c - 0.3, "close": c})
    return out


def test_outcomes_never_cross_the_session_and_use_only_later_bars():
    s1 = session(0)
    s2 = session(1, [500.0] * config.USABLE_SLOTS)          # huge jump overnight must never enter an outcome
    obs, base = ps.collect([s1, s2])
    assert all(abs(r) < 1e-9 for *_, rets in obs for r in rets.values())
    assert base[1][1] == 2 * (config.USABLE_SLOTS - 1)
    # the last 5 bars of a session have fewer horizons than the first bars
    assert base[5][1] == 2 * (config.USABLE_SLOTS - 5)


def test_wilson_and_display_threshold():
    lo, hi = ps.wilson(50, 100)
    assert 0.39 < lo < 0.41 and 0.59 < hi < 0.61 and ps.wilson(0, 0) is None
    stats = {"symbols": ["X"], "stats": {"doji": {"n": ps.MIN_N - 1, "horizons": {}}, "hammer": {"n": ps.MIN_N, "horizons": {}}}}
    assert ps.historical_for("doji", stats) is None            # too few observations -> not shown
    assert ps.historical_for("hammer", stats)["n"] == ps.MIN_N
    assert ps.historical_for("hammer", None) is None


def test_api_payload_carries_the_pattern_block():
    from forecast import api
    payload = {"symbol": "TEST", "timeframe": "5m", "as_of_ts": T0, "status": "RANGE_ONLY", "forecasts": [], "current_candle": None}
    r = api.build_response(None, payload)
    assert r["patternForecast"]["status"] == "unavailable" and r["patternForecast"]["probability"] is None


def test_median_path_is_used_only_when_no_directional_path_and_is_labelled():
    med = [fc(1, 93.5, 94.4, 93.4, 94.3)]
    r = pf.pattern_forecast(ACTUAL, [], median_candles=med)
    assert r["status"] == "model_implied" and r["path_kind"] == "median_return_path"
    assert r["patterns"][0]["path_kind"] == "median_return_path" and r["patterns"][0]["probability"] is None
    d = pf.pattern_forecast(ACTUAL, med, median_candles=[fc(1, 1, 2, 0.5, 1.5)])
    assert d["path_kind"] == "directional_path"


def test_api_exposes_median_path_without_changing_status():
    from forecast import api
    payload = {"symbol": "T", "timeframe": "5m", "as_of_ts": T0, "status": "RANGE_ONLY", "current_candle": None,
               "forecasts": [{"horizon": 1, "forecast_timestamp": T0, "status": "range_only", "close": None,
                              "median_path": {"open": 1, "high": 2, "low": 0.5, "close": 1.5}}]}
    r = api.build_response(None, payload)
    assert r["status"] == "RANGE_ONLY" and r["forecastCandles"] == [] and r["medianPath"][0]["close"] == 1.5


def test_predicted_candles_must_satisfy_ohlc_constraints():
    from forecast import api
    good = {"open": 10, "high": 12, "low": 9, "close": 11}
    assert api.valid_ohlc(good)
    for bad in ({**good, "high": 10.5}, {**good, "low": 10.5}, {**good, "low": 0}, {**good, "close": None}, {**good, "high": float("nan")}, {"open": 1}):
        assert not api.valid_ohlc(bad)
    payload = {"symbol": "T", "timeframe": "5m", "as_of_ts": T0, "status": "OK", "current_candle": None,
               "forecasts": [{"horizon": 1, "forecast_timestamp": T0, "status": "ok", "confidence": "LOW", **good},
                             {"horizon": 2, "forecast_timestamp": T0 + 300, "status": "ok", "confidence": "LOW", **{**good, "high": 1}},
                             {"horizon": 3, "forecast_timestamp": T0 + 600, "status": "range_only", "close": None, "median_path": {**good, "low": 99}}]}
    r = api.build_response(None, payload)
    assert [c["horizon"] for c in r["forecastCandles"]] == [1]        # invalid issued candle dropped, not repaired
    assert r["medianPath"] == []                                       # invalid median candle dropped
