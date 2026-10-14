import test from 'node:test';
import assert from 'node:assert/strict';
import { patternView } from '../src/lib/forecastView.js';

test('no pattern block: unavailable, no invented items', () => {
  const v = patternView(null);
  assert.equal(v.state, 'none'); assert.deepEqual(v.items, []);
});
test('range-only forecast: unavailable with the backend reason', () => {
  const v = patternView({ patternForecast: { status: 'unavailable', reason: 'No predicted candle path', patterns: [], observed: [] } });
  assert.equal(v.state, 'unavailable'); assert.equal(v.reason, 'No predicted candle path'); assert.equal(v.items.length, 0);
});
test('model-implied pattern never gets a probability or reliability', () => {
  const v = patternView({ patternForecast: { status: 'model_implied', patterns: [{ pattern: 'bullish_engulfing', direction: 'bullish', formation_horizon: 2, evidence: 'e', definition: 'd', probability: null }], observed: [] } });
  assert.equal(v.state, 'model_implied');
  assert.equal(v.items[0].name, 'Bullish Engulfing'); assert.equal(v.items[0].within, 2); assert.equal(v.items[0].reliability, null);
  assert.ok(!('probability' in v.items[0]));
});
test('observed-pattern history only when supplied, with the base rate beside it', () => {
  const mk = (historical) => patternView({ patternForecast: { status: 'none_detected', patterns: [], observed: [{ pattern: 'doji', direction: 'neutral', time: 1, historical }] } });
  assert.equal(mk(null).observed[0].history, null);
  const h = mk({ horizons: { 1: { n: 300, p_up: 0.47, base_p_up: 0.476, mean_return: 0 } } }).observed[0].history;
  assert.deepEqual([h.n, h.pUp, h.baseUp], [300, 0.47, 0.476]);
});
import { buildForecastChart } from '../src/lib/forecastView.js';
test('median path candles are mapped separately from issued forecast candles', () => {
  const resp = {
    actualCandles: [{ time: 100, open: 1, high: 2, low: 0.5, close: 1.5 }],
    forecast: { symbol: 'X', as_of_ts: 100, model_version: 'm', current_candle: { time: 100, open: 1, high: 2, low: 0.5, close: 1.5 }, forecasts: [] },
    forecastCandles: [], medianPath: [{ time: 400, open: 1.5, high: 2, low: 1, close: 1.8 }, { time: 50, open: 1, high: 1, low: 1, close: 1 }],
  };
  const d = buildForecastChart(resp);
  assert.equal(d.candles.length, 0); assert.deepEqual(d.medianCandles.map((c) => c.time), [400]);
});
import { plainSummary } from '../src/lib/forecastView.js';
test('plain summary: range in rupees, no-lean wording, null when unavailable', () => {
  const resp = { forecast: { as_of_ts: 1000, current_candle: { time: 700, close: 1176.7 }, status: 'RANGE_ONLY',
    forecasts: [{ horizon: 1, forecast_timestamp: 1000, status: 'range_only', intervals: { 80: [1175.38, 1178.13] } },
      { horizon: 5, forecast_timestamp: 2200, status: 'range_only', intervals: { 80: [1173.99, 1179.98] } }] } };
  const p = plainSummary(resp);
  assert.match(p.headline, /Next 5 candles/); assert.match(p.headline, /1,173\.99/); assert.match(p.headline, /1,179\.98/);
  assert.match(p.lean, /no clear upward or downward lean/);
  assert.equal(plainSummary(null, true), null);
});
import { forecastCandleRows, styledForecastCandles, validOhlc } from '../src/lib/forecastView.js';
import { describeForecastBar } from '../src/lib/forecast.js';
const CC = { time: 1000, open: 100, high: 101, low: 99, close: 100 };
const fr = (h, extra) => ({ horizon: h, forecast_timestamp: 1000 + h * 300, status: 'range_only', intervals: null, ...extra });
test('predicted candles: issued first, median fallback, invalid or overlapping dropped, nothing invented', () => {
  const resp = { forecast: { current_candle: CC, forecasts: [
    fr(1, { close: 100.5, open: 100, high: 101, low: 99.8, status: 'ok' }),
    fr(2, { close: null, median_path: { open: 100.5, high: 101, low: 100, close: 100.2 } }),
    fr(3, { close: null, median_path: { open: 100.2, high: 100.1, low: 99, close: 100 } }),   // high < open: invalid
    fr(4, { close: null }),                                                                  // nothing: no candle
    { ...fr(5, { close: 100, open: 100, high: 100, low: 100, status: 'ok' }), forecast_timestamp: 1000 },  // not after NOW
  ] } };
  const rows = forecastCandleRows(resp);
  assert.deepEqual(rows.map((r) => [r.h, r.kind, r.tone]), [[1, 'issued', 'up'], [2, 'median', 'down']]);
  assert.ok(rows.every((r) => r.time > CC.time && validOhlc(r)));
  assert.deepEqual(forecastCandleRows({ forecast: null }), []);
});
test('OHLC validity rules', () => {
  assert.ok(validOhlc({ open: 1, high: 2, low: 0.5, close: 1.5 }));
  for (const b of [{ open: 1, high: 1.2, low: 0.5, close: 1.5 }, { open: 1, high: 2, low: 1.1, close: 1.5 }, { open: 0, high: 2, low: 0, close: 1 }, { open: 1, high: NaN, low: 1, close: 1 }]) assert.equal(validOhlc(b), false);
});
test('styling: green up, red down, neutral flat; only the selected candle is filled', () => {
  const rows = [{ h: 1, time: 1, open: 1, high: 2, low: 0.5, close: 1.5, tone: 'up' }, { h: 2, time: 2, open: 1.5, high: 2, low: 1, close: 1, tone: 'down' }, { h: 3, time: 3, open: 1, high: 1, low: 1, close: 1, tone: 'flat' }];
  const st = styledForecastCandles(rows, 2);
  assert.match(st[0].borderColor, /52 211 153/); assert.match(st[1].borderColor, /248 113 113/); assert.match(st[2].borderColor, /148 163 184/);
  assert.match(st[1].color, /0\.65/); assert.match(st[0].color, /0\.08/);
});
test('tooltip shows predicted O/H/L/C, time, model, and labels median candles', () => {
  const issued = describeForecastBar({ horizon: 1, forecast_timestamp: 1000, close: 100.5, open: 100, high: 101, low: 99.8, direction_probability: 0.46, status: 'ok', confidence: 'LOW' }, { model: 'vX', asOf: 1000 });
  assert.ok(issued.some((l) => l.includes('Predicted O 100.00  H 101.00  L 99.80  C 100.50')));
  assert.ok(issued.some((l) => l.includes('Model vX')));
  const med = describeForecastBar({ horizon: 2, forecast_timestamp: 1300, close: null, status: 'range_only', median_path: { open: 1, high: 2, low: 0.5, close: 1.5 } });
  assert.ok(med.some((l) => l.includes('Median-return path'))); assert.ok(med.some((l) => l.includes('C 1.50')));
});
