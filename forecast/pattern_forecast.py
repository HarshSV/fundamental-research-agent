"""Future-pattern interpretation of a forecast, with honest probability handling.

The production forecast gives, per horizon, a point candle (only when confidence permits) and MARGINAL
conformal intervals. It does not give a joint distribution over candle paths, so there are no calibrated
scenarios to count pattern frequencies over. Therefore:

  * `model_implied`  - the deterministic detector run over [recent actual candles + the single predicted
                       path]. A tentative reading of one path. `probability` is ALWAYS None.
  * `unavailable`    - no predicted candle path exists (RANGE_ONLY / withheld forecasts), or too little history.

`aggregate_scenarios` computes frequencies across scenario paths and is only used when a caller supplies
paths drawn from a validated joint distribution (none exists today); it never runs on a single path.
Historical conditional statistics (forecast/pattern_stats.py) describe OBSERVED patterns, never future ones.
"""
from . import candle_patterns as cp

CONTEXT_BARS = 8
METHODOLOGY = ("Deterministic candlestick definitions applied to the single predicted candle path. "
               "Not a statistical probability: the model provides no joint distribution over future candles.")
LIMITATIONS = ["Single point path; the real path will differ.",
               "Predicted candles are produced only when the confidence gate allows a directional call.",
               "A pattern is a description of shape, not a trading signal."]


def leading_path(forecast_candles):
    """Predicted candles from horizon 1 upward with no gap; stops at the first missing horizon."""
    path, want = [], 1
    for c in sorted(forecast_candles or [], key=lambda x: x.get("horizon", 0)):
        if c.get("horizon") != want or any(c.get(k) is None for k in ("open", "high", "low", "close")):
            break
        path.append(c)
        want += 1
    return path


def pattern_forecast(actual_candles, forecast_candles, params=None):
    actual = list(actual_candles or [])
    base = {"methodology": METHODOLOGY, "probability": None, "limitations": LIMITATIONS, "patterns": [], "observed": []}
    path = leading_path(forecast_candles)
    if not path:
        return {**base, "status": "unavailable", "reason": "No predicted candle path (range-only or withheld forecast), so no future pattern can be read."}
    need = cp.DEFAULT_PARAMS["trend_lookback"] + 3
    if len(actual) < need:
        return {**base, "status": "unavailable", "reason": f"Insufficient history: {len(actual)} of {need} candles needed for the trend context."}
    ctx = actual[-CONTEXT_BARS:]
    seq = ctx + path
    first = len(ctx)
    observed = [{**d, "time": seq[d["index"]]["time"], "candles": d["bars"]} for d in cp.detect_all(seq[:first], params, start=max(0, first - 1))]
    patterns = []
    for d in cp.detect_all(seq, params, start=first):
        h0 = d["index"] - first + 1
        span = list(range(d["index"] - d["bars"] + 1, d["index"] + 1))
        patterns.append({
            "pattern": d["pattern"], "direction": d["direction"], "label": "model_implied",
            "formation_horizon": h0, "supporting_horizons": [i - first + 1 for i in span if i >= first],
            "uses_actual_candles": [seq[i]["time"] for i in span if i < first],
            "definition": cp.DEFINITIONS[d["pattern"]], "probability": None,
            "evidence": f"The predicted path completes a {d['pattern'].replace('_', ' ')} at +{h0} "
                        f"({d['bars']}-candle definition; {sum(1 for i in span if i >= first)} predicted).",
        })
    return {**base, "status": "model_implied" if patterns else "none_detected", "reason": None if patterns else "The predicted path completes no defined pattern.",
            "patterns": patterns, "observed": observed}


def aggregate_scenarios(actual_candles, scenario_paths, params=None):
    """Pattern frequency across scenario paths. Valid ONLY when the paths are samples from a validated joint
    distribution; refuses a single path (a frequency of one path is not a probability)."""
    if not scenario_paths or len(scenario_paths) < 2:
        return None
    counts, n = {}, len(scenario_paths)
    ctx = list(actual_candles)[-CONTEXT_BARS:]
    for path in scenario_paths:
        seen = {d["pattern"] for d in cp.detect_all(ctx + list(path), params, start=len(ctx))}
        for name in seen:
            counts[name] = counts.get(name, 0) + 1
    return {name: {"frequency": k / n, "n_scenarios": n} for name, k in sorted(counts.items())}
