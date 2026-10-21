import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { primaryOutcome, flagTipLines, outcomeLine, horizonLabel, setIntradayBarSeconds } from '../src/lib/patternOutcomeView.js';
import { runFirstMap } from '../src/lib/patternCatalog.js';
import { evaluateEvent } from '../src/lib/patternHistory.js';
import { mergeConfig } from '../src/lib/patternOutcomes.js';
import { lastYearWindow, shiftEventsToWindow, clusterByScreen, FLAG_STYLE, HIDDEN_BY_DEFAULT } from '../src/lib/flagClusters.js';
import { flagGeometry, assignLevels, FLAG, FlagLayer } from '../src/lib/flagPrimitive.js';

const DAY = 86400;
const P = (state, ret = null, extra = {}) => ({ state, ret, horizon: 5, ...extra });
const ev = (barIndex, pattern = 'X') => ({ barIndex, pattern, kind: 'pattern', patternType: 'x' });

// ---------------------------------------------------------------- one-year default
test('default window = last 365 days of real bars; shorter history is shown as is, never padded', () => {
  const now = 1_800_000_000;
  const bars = Array.from({ length: 1200 }, (_, i) => ({ time: now - (1199 - i) * DAY, close: 100 + i }));
  const w = lastYearWindow(bars, now);
  assert.equal(w.bars.length, 366); assert.equal(w.from, 1200 - 366); assert.equal(w.complete, true);
  assert.equal(w.bars[0].time, bars[w.from].time);                                            // same objects, no invented candles
  const young = bars.slice(-90);
  const y = lastYearWindow(young, now);
  assert.equal(y.bars.length, 90); assert.equal(y.from, 0); assert.equal(y.complete, false);  // honest: only 90 days exist
  assert.deepEqual(lastYearWindow([], now), { bars: [], from: 0, complete: false });
});

test('daily events map onto the one-year bars; srcIndex keeps pointing at the full series; earlier events are not displayed', () => {
  const full = Array.from({ length: 400 }, (_, i) => ({ time: i * DAY }));
  const w = { bars: full.slice(100), from: 100 };
  const events = [{ barIndex: 50, srcIndex: 50, startIndex: 40, endIndex: 50 }, { barIndex: 150, srcIndex: 150, startIndex: 120, endIndex: 150 }, { barIndex: 399, srcIndex: 399, startIndex: 380, endIndex: 399 }];
  const out = shiftEventsToWindow(events, w.from, w.bars);
  assert.equal(out.length, 2);
  assert.equal(out[0].barIndex, 50); assert.equal(out[0].srcIndex, 150); assert.equal(out[0].time, full[150].time); assert.equal(out[0].startIndex, 20);
  assert.equal(out[1].barIndex, 299); assert.equal(out[1].time, full[399].time);
});

// ---------------------------------------------------------------- colour and side from the realised outcome
test('green = below candle pointing up; red = above candle pointing down; pending blue; flat/unavailable optional', () => {
  assert.equal(FLAG_STYLE.positive.above, false); assert.match(FLAG_STYLE.positive.fill, /16,185,129/);
  assert.equal(FLAG_STYLE.negative.above, true); assert.match(FLAG_STYLE.negative.fill, /239,68,68/);
  assert.equal(FLAG_STYLE.pending.above, false); assert.match(FLAG_STYLE.pending.fill, /59,130,246/);
  assert.notEqual(FLAG_STYLE.pending.fill, FLAG_STYLE.flat.fill);
  assert.deepEqual(HIDDEN_BY_DEFAULT.sort(), ['flat', 'not_evaluable']);
  assert.equal(new Set(Object.values(FLAG_STYLE).map((s) => s.fill)).size, 5);
});

test('placement ignores bias: a bullish pattern with a negative outcome is a red flag above; same state -> same flag', () => {
  const bull = { classification: { bias: 'bullish' }, outcomes: { 5: P('negative', -0.03) } };
  const bear = { classification: { bias: 'bearish' }, outcomes: { 5: P('negative', -0.03) } };
  assert.equal(primaryOutcome(bull).state, primaryOutcome(bear).state);
  const c = clusterByScreen([{ event: ev(10), state: primaryOutcome(bull).state }], 10)[0];
  assert.equal(c.above, true); assert.equal(c.state, 'negative');
});

// ---------------------------------------------------------------- zoom-aware grouping
test('grouping follows screen spacing: zoomed out merges nearby same-outcome flags, zoomed in splits them, nothing is lost', () => {
  const items = [10, 11, 12, 13, 40, 41].map((b) => ({ event: ev(b), state: 'positive' }));
  const out = clusterByScreen(items, 1, 22);                    // 1px per bar: 22 bars share a flag
  assert.deepEqual(out.map((g) => g.events.length), [4, 2]);
  const mid = clusterByScreen(items, 10, 22);                   // 10px per bar: ~2 bars share a flag
  assert.ok(mid.length > out.length);
  const zoomed = clusterByScreen(items, 40, 22);                // 40px per bar: every occurrence has its own flag
  assert.equal(zoomed.length, 6); assert.ok(zoomed.every((g) => g.events.length === 1));
  for (const o of [out, mid, zoomed]) assert.equal(o.reduce((n, g) => n + g.events.length, 0), 6);   // occurrences preserved
  assert.equal(out[0].at.barIndex, 13);                         // anchored on the latest candle of the group
});

test('different outcomes are never merged into one flag, so a group can not imply a uniform result', () => {
  const items = [{ event: ev(10), state: 'positive' }, { event: ev(10), state: 'negative' }, { event: ev(11), state: 'positive' }, { event: ev(11), state: 'pending' }];
  const out = clusterByScreen(items, 1, 22);
  assert.deepEqual(out.map((g) => g.state).sort(), ['negative', 'pending', 'positive']);
  assert.equal(out.find((g) => g.state === 'positive').events.length, 2);
  for (const g of out) assert.ok(g.events.length >= 1);
  assert.equal(out.find((g) => g.state === 'positive').above, false); assert.equal(out.find((g) => g.state === 'negative').above, true);
});

// ---------------------------------------------------------------- geometry, overlap, painting
test('flag geometry: pointer touches the candle; overlaps move a flag outward by a flag height', () => {
  const up = flagGeometry({ x: 100, anchorY: 200, above: true, width: 20 });
  assert.equal(up.tip[2][1], 200 - FLAG.gap); assert.ok(up.body.y + up.body.h < up.tip[2][1]);
  const down = flagGeometry({ x: 100, anchorY: 200, above: false, width: 20 });
  assert.equal(down.tip[2][1], 200 + FLAG.gap); assert.ok(down.body.y > down.tip[2][1]);
  assert.ok(flagGeometry({ x: 100, anchorY: 200, above: true, level: 1, width: 20 }).bounds.y2 < up.bounds.y1);
  assert.ok(FLAG.h <= 18);                                                                  // compact
});

test('assignLevels offsets only overlapping flags and keeps every flag', () => {
  const lv = assignLevels([
    { id: 'a', x: 100, w: 20, above: false }, { id: 'b', x: 110, w: 20, above: false }, { id: 'c', x: 200, w: 20, above: false }, { id: 'd', x: 105, w: 20, above: true },
  ]);
  assert.equal(lv.size, 4); assert.equal(lv.get('a'), 0); assert.equal(lv.get('b'), 1); assert.equal(lv.get('c'), 0); assert.equal(lv.get('d'), 0);
});

test('painting: each flag is filled with its outcome colour, selection keeps the fill, hit-test uses the painted rectangles', () => {
  const log = [];
  const ctx = new Proxy({}, {
    get: (t, k) => (k === 'fill' ? () => log.push({ fill: t.fillStyle, sel: false, text: null }) : k === 'stroke' ? () => { if (t.lineWidth === 2) log[log.length - 1].sel = true; }
      : k === 'fillText' ? (txt) => { log[log.length - 1].text = txt; } : k === 'measureText' ? () => ({ width: 6 }) : k in t ? t[k] : () => {}),
    set: (t, k, v) => { t[k] = v; return true; },
  });
  const layer = new FlagLayer();
  layer._chart = { timeScale: () => ({ logicalToCoordinate: (i) => 50 + i * 40 }) };
  layer._series = { priceToCoordinate: () => 100 };
  const mk = (id, i, st, extra = {}) => ({ id, barIndex: i, anchor: 1, above: FLAG_STYLE[st].above, fill: FLAG_STYLE[st].fill, textColor: FLAG_STYLE[st].text, label: '', ...extra });
  layer.setFlags([mk('p', 0, 'positive'), mk('n', 1, 'negative', { selected: true, label: '3' }), mk('w', 2, 'pending'), mk('f', 3, 'flat'), mk('u', 4, 'not_evaluable')]);
  layer._paint(ctx);
  for (const st of ['positive', 'negative', 'pending', 'flat', 'not_evaluable']) assert.ok(log.some((l) => l.fill === FLAG_STYLE[st].fill), st);
  const sel = log.filter((l) => l.sel); assert.equal(sel.length, 1); assert.equal(sel[0].fill, FLAG_STYLE.negative.fill);   // still red
  assert.equal(log.find((l) => l.fill === FLAG_STYLE.negative.fill).text, '3');
  assert.equal(layer.hitTest(50, 100 + FLAG.gap + 8), 'p');                                    // green flag sits BELOW its candle (y grows downward)
  assert.equal(layer.hitTest(90, 100 - FLAG.gap - 8), 'n');                                    // red flag sits ABOVE its candle
  assert.equal(layer.hitTest(900, 100), null);
});

// ---------------------------------------------------------------- tooltip text, missing / pending
test('tooltip carries name, symbol, detection time, timeframe, bias and outcome; unavailable/pending are never 0%', () => {
  const item = { name: 'Double Top', symbol: 'TCS', detected: '16 Oct, 10:15', timeframe: 'daily', bias: 'Bearish bias', primary: P('negative', -0.0123) };
  const t = flagTipLines([item]).join(' | ');
  for (const need of ['Double Top', 'TCS', '16 Oct, 10:15', 'daily', 'Bearish bias', 'Negative -1.23% after 5d']) assert.ok(t.includes(need), need);
  assert.match(outcomeLine(P('pending'), 'daily'), /pending \(5d horizon not complete\)/);
  assert.match(outcomeLine(P('not_evaluable', null, { reason: 'missing_candles' }), 'daily'), /unavailable \(missing candles/);
  assert.doesNotMatch(outcomeLine(P('pending'), 'daily') + outcomeLine(null, 'daily'), /0\.00%|0%/);
  const multi = flagTipLines([item, { ...item, name: 'Rectangle', primary: P('pending') }]).join(' | ');
  assert.match(multi, /2 patterns/); assert.match(multi, /pending/);
});

// ---------------------------------------------------------------- wiring
test('chart wiring: 1D default, flag layer, hide-by-default toggle, daily history reused, no arrow markers', () => {
  const src = fs.readFileSync(new URL('../src/views/LiveChart.jsx', import.meta.url), 'utf8');
  assert.match(src, /useState\('1d'\)/); assert.match(src, /\{ key: '1d', label: '1D' \}/);
  assert.match(src, /lastYearWindow\(dailyBars/); assert.match(src, /fullHistoryEvents\(\{ dailyBars, weeklyBars: \[\] \}\)/);
  assert.match(src, /new FlagLayer\(\)/); assert.match(src, /clusterByScreen\(items, pxPerBar\)/);
  assert.match(src, /HIDDEN_BY_DEFAULT\.includes\(state\)/); assert.match(src, /data-testid="toggle-neutral-flags"/);
  assert.match(src, /useState\(false\); \/\/ flat/);
  assert.doesNotMatch(src, /createSeriesMarkers/);
  assert.match(src, /lastFitKeyRef\.current !== key/);                                         // zoom is fitted once per dataset, not on every update
  assert.match(src, /<OutcomeChips res=\{formationOutcome\(t\.evs\[0\]\)\}/);
  const prim = fs.readFileSync(new URL('../src/lib/flagPrimitive.js', import.meta.url), 'utf8');
  assert.doesNotMatch(prim, /251,\s*191,\s*36|yellow/i);
  assert.match(prim, /logicalToCoordinate\(f\.barIndex\)/); assert.match(prim, /priceToCoordinate\(f\.anchor\)/);
});

// ---------------------------------------------------------------- kept behaviour
test('runFirstMap sends every firing of a formation to its FIRST detection (original timestamp)', () => {
  const mk = (i, type = 'a') => ({ kind: 'pattern', patternType: type, timeframe: 'intraday', barIndex: i, time: i * 300, formedAt: i * 300 });
  const evs = [mk(10), mk(11), mk(12), mk(30), mk(31), mk(11, 'b')];
  const m = runFirstMap(evs);
  assert.equal(m.get(evs[2]), evs[0]); assert.equal(m.get(evs[4]), evs[3]); assert.equal(m.get(evs[5]), evs[5]);
});

test('outcomes follow the chart interval: 15-minute bars are evaluable with a 900s config, labels say x15m', () => {
  const t0 = Date.UTC(2026, 9, 14, 4, 0) / 1000;
  const bars = Array.from({ length: 14 }, (_, i) => { const c = 100 + i * 0.3; return { time: t0 + i * 900, open: c, high: c + 0.2, low: c - 0.2, close: c, volume: 1 }; });
  const e = { kind: 'pattern', patternType: 'double-bottom', pattern: 'Double Bottom', timeframe: 'intraday', confirmedAt: bars[2].time, barIndex: 2, srcIndex: 2, time: bars[2].time, formedAt: bars[2].time };
  const now = t0 + 86400;
  assert.equal(evaluateEvent(e, { timeframe: 'intraday', series: bars, config: mergeConfig({ barSeconds: { intraday: 900 } }), nowSec: now }).outcomes[5].state, 'positive');
  assert.equal(evaluateEvent(e, { timeframe: 'intraday', series: bars, nowSec: now }).outcomes[5].reason, 'missing_candles');
  setIntradayBarSeconds(900); assert.equal(horizonLabel('intraday', 5), '5×15m');
  setIntradayBarSeconds(300); assert.equal(horizonLabel('intraday', 5), '5×5m');
});
