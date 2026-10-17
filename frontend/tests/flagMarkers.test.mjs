import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { CHART_OUTCOME_COLOR, primaryOutcome, groupMarker, horizonLabel, setIntradayBarSeconds } from '../src/lib/patternOutcomeView.js';
import { runFirstMap } from '../src/lib/patternCatalog.js';
import { evaluateEvent } from '../src/lib/patternHistory.js';
import { mergeConfig } from '../src/lib/patternOutcomes.js';

// On-chart arrow markers (lightweight-charts markers with "N patterns +22" style labels), coloured by REALISED outcome.

test('marker colour comes from the realised outcome only; pending/not-evaluable are never grey Flat', () => {
  const P = (state, ret = null) => ({ state, ret });
  assert.equal(groupMarker([P('positive', 0.02)]).color, CHART_OUTCOME_COLOR.positive);
  assert.equal(groupMarker([P('negative', -0.02)]).color, CHART_OUTCOME_COLOR.negative);
  assert.equal(groupMarker([P('flat', 0.0005)]).color, CHART_OUTCOME_COLOR.flat);
  const pend = groupMarker([P('pending')]);
  assert.equal(pend.color, CHART_OUTCOME_COLOR.pending); assert.notEqual(pend.color, CHART_OUTCOME_COLOR.flat); assert.match(pend.suffix, /…/);
  assert.equal(groupMarker([null]).state, 'not_evaluable');                       // unknown result is never converted to Flat
  assert.notEqual(groupMarker([null]).color, CHART_OUTCOME_COLOR.flat);
  const mixed = groupMarker([P('positive', 0.02), P('negative', -0.02), P('pending'), P('flat', 0)]);
  assert.equal(mixed.state, 'mixed'); assert.equal(mixed.color, CHART_OUTCOME_COLOR.mixed); assert.match(mixed.suffix, /\+1 −1 ~1 …1/);
  assert.deepEqual(mixed.parts.map((p) => p.state), ['positive', 'negative', 'flat', 'pending']);   // one stacked marker per outcome
  assert.equal(new Set(mixed.parts.map((p) => p.color)).size, 4);
  assert.equal(new Set(Object.values(CHART_OUTCOME_COLOR)).size, 6);
});

test('marker colour is independent of conventional bias', () => {
  const res = { classification: { bias: 'bullish' }, outcomes: { 5: { state: 'negative', ret: -0.03 }, 15: { state: 'pending' } } };
  const bear = { ...res, classification: { bias: 'bearish' } };
  assert.equal(groupMarker([primaryOutcome(res)]).color, groupMarker([primaryOutcome(bear)]).color);
  assert.equal(primaryOutcome(res).horizon, 5);
  assert.equal(primaryOutcome({ outcomes: {} }), null);
});

test('runFirstMap sends every firing of a formation to its FIRST detection (original timestamp)', () => {
  const mk = (i, type = 'a') => ({ kind: 'pattern', patternType: type, timeframe: 'intraday', barIndex: i, time: i * 300, formedAt: i * 300 });
  const evs = [mk(10), mk(11), mk(12), mk(30), mk(31), mk(11, 'b')];
  const m = runFirstMap(evs);
  assert.equal(m.get(evs[2]), evs[0]); assert.equal(m.get(evs[1]), evs[0]);
  assert.equal(m.get(evs[4]), evs[3]); assert.equal(m.get(evs[5]), evs[5]);
});

test('chart wiring: arrow markers + labels via createSeriesMarkers, outcome-coloured, popup badges + legend present', () => {
  const src = fs.readFileSync(new URL('../src/views/LiveChart.jsx', import.meta.url), 'utf8');
  assert.match(src, /createSeriesMarkers\(series, \[\]\)/); assert.match(src, /groupMarker\(events\.map/);
  assert.match(src, /color: dimmed \? MARKER_COLOR_DIM : p\.color/); assert.match(src, /shape: above \? 'arrowDown' : 'arrowUp'/);
  assert.match(src, /text: i === 0 \? `\$\{text\}\$\{p\.suffix\}`/);
  assert.match(src, /data-testid="popover-legend"/); assert.match(src, /data-testid="chart-outcome-legend"/);
  assert.match(src, /<OutcomeChips res=\{formationOutcome\(t\.evs\[0\]\)\}/);
  assert.doesNotMatch(src, /FlagLayer|flagPrimitive/);
});

test('outcomes follow the chart interval: 15-minute bars are evaluable with a 900s config, labels say x15m', () => {
  const t0 = Date.UTC(2026, 9, 14, 4, 0) / 1000;            // 09:30 IST
  const bars = Array.from({ length: 14 }, (_, i) => { const c = 100 + i * 0.3; return { time: t0 + i * 900, open: c, high: c + 0.2, low: c - 0.2, close: c, volume: 1 }; });
  const ev = { kind: 'pattern', patternType: 'double-bottom', pattern: 'Double Bottom', timeframe: 'intraday', confirmedAt: bars[2].time, barIndex: 2, srcIndex: 2, time: bars[2].time, formedAt: bars[2].time };
  const now = t0 + 86400;
  const ok = evaluateEvent(ev, { timeframe: 'intraday', series: bars, config: mergeConfig({ barSeconds: { intraday: 900 } }), nowSec: now });
  assert.equal(ok.outcomes[5].state, 'positive');
  const wrong = evaluateEvent(ev, { timeframe: 'intraday', series: bars, nowSec: now });
  assert.equal(wrong.outcomes[5].state, 'not_evaluable'); assert.equal(wrong.outcomes[5].reason, 'missing_candles');
  setIntradayBarSeconds(900); assert.equal(horizonLabel('intraday', 5), '5×15m');
  setIntradayBarSeconds(300); assert.equal(horizonLabel('intraday', 5), '5×5m');
});
