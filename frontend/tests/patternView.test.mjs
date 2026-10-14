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
