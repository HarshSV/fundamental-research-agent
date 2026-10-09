import test from 'node:test';
import assert from 'node:assert/strict';
import { forecastState, rowStatus, summarize, buildForecastChart, friendlyReason } from '../src/lib/forecastView.js';

const T = 1_800_000_000 - (1_800_000_000 % 300);
const iv = (lo, hi) => ({ 50: [lo + 0.3, hi - 0.3], 80: [lo, hi], 95: [lo - 0.5, hi + 0.5] });
const rangeRow = (h, lo = 99, hi = 103) => ({ horizon: h, forecast_timestamp: T + h * 300, status: 'range_only', confidence: 'NO_RELIABLE_FORECAST', intervals: iv(lo, hi) });
const candleRow = (h, conf, p = 0.58) => ({ ...rangeRow(h), status: 'ok', confidence: conf, open: 100, high: 101.2, low: 99.6, close: 100.7, direction_probability: p });
const withheld = (h, reason) => ({ horizon: h, forecast_timestamp: T + h * 300, status: 'withheld', confidence: 'NO_RELIABLE_FORECAST', reasons: [reason] });
const mk = (rows, over = {}, top = {}) => ({
  status: 'X', refreshing: false, actualCandles: [{ time: T - 300, open: 99, high: 100, low: 98.5, close: 99.5 }, { time: T, open: 99.5, high: 100.4, low: 99.2, close: 100 }],
  forecastCandles: rows.filter((r) => r.status === 'ok').map((r) => ({ time: r.forecast_timestamp, open: r.open, high: r.high, low: r.low, close: r.close })),
  forecast: { as_of_ts: T + 300, model_version: 'vTEST', symbol: 'AAA', regime: 'range|normal_vol', current_candle: { time: T, open: 99.5, high: 100.4, low: 99.2, close: 100 }, forecasts: rows, reasons: [], ...top },
  ...over,
});

test('STATE loading: no response yet shows "Generating forecast..." and never "No reliable forecast"', () => {
  const s = forecastState({ resp: null, loading: true });
  assert.equal(s.key, 'loading'); assert.equal(s.title, 'Generating forecast...');
  assert.doesNotMatch(JSON.stringify(s), /No reliable/i);
});

test('STATE loading: backend still fetching the latest candle (withheld + refreshing) is "Generating", not a failure', () => {
  const s = forecastState({ resp: mk([withheld(1, 'data_not_usable: stale')], { refreshing: true }) });
  assert.equal(s.key, 'loading'); assert.equal(s.title, 'Generating forecast...');
});

test('STATE unavailable: request failed / no forecast values exist', () => {
  assert.equal(forecastState({ resp: null, loading: false }).title, 'Forecast unavailable');
  const s = forecastState({ resp: mk([withheld(1, 'model_unavailable: X')], {}, { reasons: [] }) });
  assert.equal(s.key, 'unavailable'); assert.equal(s.title, 'Forecast unavailable');
  assert.equal(s.detail, 'model_unavailable: X');                              // the backend's own reason is passed through
  const none = forecastState({ resp: mk([]) });
  assert.equal(none.detail, 'Model output unavailable');
});

test('STATE range only: valid ranges but no directional candle -> "Range forecast available" / "Directional signal uncertain"', () => {
  const s = forecastState({ resp: mk([1, 2, 3, 4, 5].map((h) => rangeRow(h))) });
  assert.equal(s.key, 'range_only');
  assert.equal(s.title, 'Range forecast available');
  assert.equal(s.subtitle, 'Directional signal uncertain');
  assert.doesNotMatch(JSON.stringify(s), /No reliable/i);
});

test('STATE low / medium / high mirror the backend confidence value exactly', () => {
  assert.equal(forecastState({ resp: mk([candleRow(1, 'LOW')]) }).title, 'Low confidence');
  assert.equal(forecastState({ resp: mk([candleRow(1, 'MEDIUM')]) }).title, 'Medium confidence');
  assert.equal(forecastState({ resp: mk([candleRow(1, 'HIGH')]) }).title, 'High confidence');
  assert.equal(forecastState({ resp: mk([candleRow(1, 'LOW')]) }).key, 'low');
  // directional forecast + ranges: range availability is noted, level untouched
  assert.equal(forecastState({ resp: mk([candleRow(1, 'MEDIUM'), rangeRow(2)]) }).subtitle, 'Range forecast also available');
});

test('rowStatus never calls a row with a range "No reliable forecast"', () => {
  assert.equal(rowStatus(rangeRow(1)).text, 'Range only');
  assert.equal(rowStatus(candleRow(1, 'HIGH')).text, 'High confidence');
  assert.equal(rowStatus(withheld(4, 'horizon_beyond_session_end')).text, 'Beyond the session close');
  assert.equal(friendlyReason('input_outside_training_distribution'), "Input outside the model's supported range");
});

test('summary: missing probability is never turned into 50%; values come straight from the backend', () => {
  const s = summarize(mk([1, 2, 3, 4, 5].map((h) => rangeRow(h, 99 - h * 0.1, 103 + h * 0.1))));
  assert.equal(s.direction.label, 'UNCERTAIN'); assert.equal(s.direction.detail, null);
  assert.deepEqual([s.near.h, s.near.lo, s.near.hi], [1, 98.9, 103.1]);
  assert.deepEqual([s.far.h, s.far.lo, s.far.hi], [5, 98.5, 103.5]);
  assert.equal(s.asOf, T + 300); assert.equal(s.model, 'vTEST'); assert.equal(s.reference, 100);
  const d = summarize(mk([candleRow(1, 'LOW', 0.58)]));
  assert.equal(d.direction.label, 'UP'); assert.match(d.direction.detail, /P\(up\) 58% at \+1/);
  assert.equal(summarize(mk([candleRow(1, 'LOW', 0.41)])).direction.label, 'DOWN');
});

test('chart data: actual context + NOW origin + only issued candles + bands fanning from the reference price', () => {
  const rows = [candleRow(1, 'LOW'), rangeRow(2), rangeRow(3), withheld(4, 'horizon_beyond_session_end'), withheld(5, 'horizon_beyond_session_end')];
  const d = buildForecastChart(mk(rows));
  assert.equal(d.origin.time, T); assert.equal(d.origin.price, 100);
  assert.deepEqual(d.actual.map((c) => c.time), [T - 300, T]);                 // actual context only (no forecast times)
  assert.deepEqual(d.candles.map((c) => c.time), [T + 300]);                     // only horizon 1 has a candle, one bar after the reference
  assert.ok(d.candles.every((c) => c.time > d.origin.time) && d.actual.every((c) => c.time <= d.origin.time));
  assert.deepEqual(d.bands[80].map((p) => p.h), [0, 1, 2, 3]);                   // origin + horizons that have intervals; 4,5 absent (no interpolation)
  assert.deepEqual([d.bands[80][0].lo, d.bands[80][0].hi], [100, 100]);          // the fan starts at the reference price
  assert.equal(d.horizons.length, 5);
});

test('chart data: absent/invalid input yields null, never a made-up chart', () => {
  assert.equal(buildForecastChart(null), null);
  assert.equal(buildForecastChart({ forecast: { current_candle: null, forecasts: [] } }), null);
  const bad = mk([rangeRow(1)]); bad.forecast.current_candle.close = NaN;
  assert.equal(buildForecastChart(bad), null);
});

test('symbol validation reasons are explained, not shown as raw codes or as "No reliable forecast"', () => {
  assert.match(friendlyReason('symbol_not_validated: illiquid: 40% of bars have zero/missing volume'), /^Not validated for forecasting - illiquid/);
  assert.equal(friendlyReason('direction_not_validated_for_symbol'), 'Direction not validated for this symbol');
  const s = forecastState({ resp: mk([withheld(1, 'symbol_onboarding: first-time validation in progress')], { refreshing: true }) });
  assert.equal(s.key, 'loading');                       // first-time validation shows "Generating forecast..."
  const r = rowStatus({ ...rangeRow(1), reasons: ['direction_not_validated_for_symbol'] });
  assert.equal(r.text, 'Range only');
});
