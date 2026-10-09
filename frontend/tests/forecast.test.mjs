import test from 'node:test';
import assert from 'node:assert/strict';
import { toForecastSeries, forecastAligned, lastCompletedTime, describeForecastBar, forecastBarByTime, confidenceLabel } from '../src/lib/forecast.js';

const T = 1_800_000_000 - (1_800_000_000 % 300);
const mkResp = (over = {}) => ({
  forecast: { current_candle: { time: T }, forecasts: [
    { horizon: 1, forecast_timestamp: T + 300, close: 101, open: 100, high: 101.5, low: 99.8, direction_probability: 0.56, confidence: 'LOW', intervals: { 80: [99, 103] }, status: 'ok' },
    { horizon: 2, forecast_timestamp: T + 600, confidence: 'NO_RELIABLE_FORECAST', status: 'withheld', reasons: ['horizon_beyond_session_end'] },
  ] },
  forecastCandles: [{ time: T + 300, open: 100, high: 101.5, low: 99.8, close: 101 }],
  forecastEnvelope: [{ time: T + 300, intervals: { 80: [99, 103], 50: [99.7, 101.9] } }],
  ...over,
});

test('forecast candles are only drawn when anchored to the last completed chart candle', () => {
  assert.equal(toForecastSeries(mkResp(), T).aligned, true);
  assert.equal(toForecastSeries(mkResp(), T - 300).candles.length, 0); // stale forecast is never drawn
  assert.equal(toForecastSeries(mkResp(), null).candles.length, 0);
});

test('forecast data is strictly after the boundary', () => {
  const resp = mkResp({ forecastCandles: [{ time: T, open: 1, high: 2, low: 0.5, close: 1.5 }, { time: T + 300, open: 100, high: 101, low: 99, close: 100.5 }] });
  const s = toForecastSeries(resp, T);
  assert.deepEqual(s.candles.map((c) => c.time), [T + 300]); // bar at/before the boundary dropped
  assert.equal(s.boundary, T);
});

test('non-finite predicted values are dropped, never drawn', () => {
  const resp = mkResp({ forecastCandles: [{ time: T + 300, open: 100, high: NaN, low: 99, close: 100 }] });
  assert.equal(toForecastSeries(resp, T).candles.length, 0);
  assert.equal(toForecastSeries(null, T).candles.length, 0);
  assert.equal(toForecastSeries({ forecastCandles: 'x' }, T).candles.length, 0);
});

test('envelope maps 80% and 50% bounds to separate lines', () => {
  const s = toForecastSeries(mkResp(), T);
  assert.deepEqual(s.upper80, [{ time: T + 300, value: 103 }]);
  assert.deepEqual(s.lower80, [{ time: T + 300, value: 99 }]);
  assert.deepEqual(s.lower50, [{ time: T + 300, value: 99.7 }]);
});

test('lastCompletedTime ignores the still-forming candle', () => {
  const now = T + 450; // 2.5 min into the candle that opened at T+300
  const candles = [{ time: T - 300 }, { time: T }, { time: T + 300 }];
  assert.equal(lastCompletedTime(candles, now), T);
  assert.equal(lastCompletedTime([], now), null);
});

test('tooltip labels forecasts as forecasts and states withheld horizons plainly', () => {
  const lines = describeForecastBar(forecastBarByTime(mkResp(), T + 300));
  assert.match(lines[0], /FORECAST \(not a historical value\)/);
  assert.ok(lines.some((l) => /Confidence: Low/.test(l)));
  const w = describeForecastBar(forecastBarByTime(mkResp(), T + 600));
  assert.ok(w.some((l) => /No forecast issued/.test(l)));
  assert.equal(confidenceLabel('NO_RELIABLE_FORECAST'), 'No reliable forecast');
  assert.equal(forecastAligned(mkResp(), T), true);
});
