// Deterministic SYNTHETIC series, used strictly to unit-test the outcome logic. They are not market data and no result
// here is a statement about real pattern performance.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  OUTCOME, DEFAULT_CONFIG, mergeConfig, forwardOutcome, evaluateOccurrence, referenceIndex, sigmaAt, flatBand, independentSubset,
  summarizeHorizon, baseRate, observeBreakout, closedBars,
} from '../src/lib/patternOutcomes.js';
import { toOccurrences, evaluateEvent, fullHistoryEvents, statsForPattern } from '../src/lib/patternHistory.js';
import { istInstant } from '../src/lib/marketTime.js';

const DAY = 86400;
const D0 = istInstant('2026-01-05', 0, 0);
const daily = (closes, step = DAY) => closes.map((c, i) => ({ time: D0 + i * step, open: c, high: c * 1.001, low: c * 0.999, close: c, volume: 1000 }));
// one 75-bar session per date, 5-minute bars from 09:15 IST
const session = (date, closes) => closes.map((c, i) => ({ time: istInstant(date, 9, 15) + i * 300, open: c, high: c, low: c, close: c, volume: 1 }));
const flat = (n, v = 100) => Array(n).fill(v);
// exact binary fractions so boundary tests are not blurred by float error: no volatility term, floor 25%
const EXACT = mergeConfig({ flat: { k: 0, floor: { daily: 0.25, weekly: 0.25, intraday: 0.25 } } });
const NOW = istInstant('2026-12-31', 12, 0);

function dailyWith(refClose, refIdx, target, h) {
  const c = flat(refIdx + h + 3, 100);
  c[refIdx] = refClose; c[refIdx + h] = target;
  return daily(c);
}

// ---------------------------------------------------------------- formula + threshold boundaries
test('forward return = close[ref+h]/close[ref]-1 with the confirming bar close as reference', () => {
  const s = dailyWith(100, 10, 125, 5);
  const o = forwardOutcome(s, 10, 5, 'daily', EXACT, NOW);
  assert.equal(o.ret, 0.25); assert.equal(o.targetTime, s[15].time);
});

test('threshold boundaries: exactly at the band is Flat; just beyond is Positive / Negative', () => {
  const at = (target) => forwardOutcome(dailyWith(100, 10, target, 5), 10, 5, 'daily', EXACT, NOW).state;
  assert.equal(at(125), OUTCOME.FLAT);          // +25.0% == band
  assert.equal(at(125.01), OUTCOME.POSITIVE);
  assert.equal(at(75), OUTCOME.FLAT);           // -25.0% == band
  assert.equal(at(74.99), OUTCOME.NEGATIVE);
  assert.equal(at(100), OUTCOME.FLAT);
});

test('band = max(floor, k*sigma*sqrt(h)); sigma only from bars up to the reference bar', () => {
  const closes = flat(60); for (let i = 31; i < 60; i++) closes[i] = closes[i - 1] * (i % 2 ? 1.02 : 0.98);   // volatile AFTER bar 30
  const s = daily(closes);
  const cfg = mergeConfig({});
  assert.equal(sigmaAt(s, 30, 'daily', cfg), 0);                     // flat history -> sigma 0 -> floor applies
  assert.equal(flatBand(s, 30, 5, 'daily', cfg).band, cfg.flat.floor.daily);
  const vol = flatBand(s, 55, 5, 'daily', cfg);
  assert.ok(vol.band > cfg.flat.floor.daily && vol.basis === 'volatility');
  const short = flatBand(daily(flat(6)), 5, 5, 'daily', cfg);
  assert.match(short.basis, /no volatility history/); assert.equal(short.band, cfg.flat.floor.daily);
});

// ---------------------------------------------------------------- pending vs flat
test('an incomplete horizon is PENDING, never Flat; it becomes evaluable when the bar arrives', () => {
  const full = dailyWith(100, 10, 100, 5);
  const cut = full.slice(0, 13);                                          // reference at 10, horizon needs bar 15
  const p = forwardOutcome(cut, 10, 5, 'daily', EXACT, NOW);
  assert.equal(p.state, OUTCOME.PENDING); assert.equal(p.ret, null); assert.notEqual(p.state, OUTCOME.FLAT);
  assert.equal(forwardOutcome(full, 10, 5, 'daily', EXACT, NOW).state, OUTCOME.FLAT);   // now genuinely flat
});

test('intraday: pending while the session is open, not evaluable once it ended without the horizon bar', () => {
  const date = '2026-03-02';
  const s = session(date, flat(75));
  const ref = 72;                                                          // 15:15 bar: +5 bars would be past the close
  assert.equal(forwardOutcome(s, ref, 5, 'intraday', EXACT, istInstant(date, 15, 16)).state, OUTCOME.PENDING);       // session still open
  const done = forwardOutcome(s, ref, 5, 'intraday', EXACT, istInstant(date, 16, 0));
  assert.equal(done.state, OUTCOME.NOT_EVALUABLE); assert.equal(done.reason, 'session_boundary');
  assert.equal(forwardOutcome(s, 10, 5, 'intraday', EXACT, istInstant(date, 16, 0)).state, OUTCOME.FLAT);
});

test('intraday horizons never cross the close even if next-day bars exist', () => {
  const s = [...session('2026-03-02', flat(75)), ...session('2026-03-03', flat(75))];
  const o = forwardOutcome(s, 72, 5, 'intraday', EXACT, NOW);
  assert.equal(o.state, OUTCOME.NOT_EVALUABLE); assert.equal(o.reason, 'session_boundary');
});

// ---------------------------------------------------------------- missing / insufficient candles, corporate actions
test('a gap in the forward candles is not evaluable (intraday and daily)', () => {
  const date = '2026-03-02';
  const s = session(date, flat(75)); s.splice(12, 1);                      // drop one forward bar
  assert.equal(forwardOutcome(s, 10, 5, 'intraday', EXACT, NOW).reason, 'missing_candles');
  const d = daily(flat(30)); for (let i = 15; i < d.length; i++) d[i].time += 12 * DAY;     // 12-day hole after bar 14
  const o = forwardOutcome(d, 12, 5, 'daily', EXACT, NOW);
  assert.equal(o.state, OUTCOME.NOT_EVALUABLE); assert.equal(o.reason, 'missing_candles');
});

test('missing reference bar, insufficient history and out-of-range indexes never produce a made-up outcome', () => {
  const s = daily(flat(20));
  assert.equal(forwardOutcome(s, -1, 5, 'daily', EXACT, NOW).reason, 'reference_bar_missing');
  assert.equal(forwardOutcome(s, 99, 5, 'daily', EXACT, NOW).reason, 'reference_bar_missing');
  assert.equal(forwardOutcome([], 0, 5, 'daily', EXACT, NOW).state, OUTCOME.NOT_EVALUABLE);
  const r = evaluateOccurrence(s, { confirmedAt: 123 }, 'daily', undefined, NOW);   // no bar matches that time
  assert.equal(r.refIndex, -1); assert.ok(Object.values(r.outcomes).every((x) => x.state === OUTCOME.NOT_EVALUABLE));
});

test('split-like jumps are excluded, real crashes are kept', () => {
  const half = flat(40); for (let i = 22; i < 40; i++) half[i] = 50;       // un-adjusted 1:2
  assert.equal(forwardOutcome(daily(half), 20, 5, 'daily', EXACT, NOW).reason, 'suspect_corporate_action');
  const crash = flat(40); for (let i = 22; i < 40; i++) crash[i] = 70;     // -30%: a real crash, below the 40% split-suspect threshold
  assert.equal(forwardOutcome(daily(crash), 20, 5, 'daily', EXACT, NOW).state, OUTCOME.NEGATIVE);
});

// ---------------------------------------------------------------- timeframe + horizon handling
test('horizons are configurable per timeframe and every outcome is keyed by its horizon', () => {
  const s = daily(flat(60));
  const d = evaluateOccurrence(s, { srcIndex: 10 }, 'daily', { horizons: { daily: [2, 7] } }, NOW);
  assert.deepEqual(Object.keys(d.outcomes), ['2', '7']);
  assert.deepEqual(Object.keys(evaluateOccurrence(s, { srcIndex: 10 }, 'daily', undefined, NOW).outcomes), ['5', '15', '30']);
  assert.deepEqual(DEFAULT_CONFIG.horizons.intraday, [5, 15, 30]);
  const w = evaluateOccurrence(daily(flat(60), 7 * DAY), { srcIndex: 5 }, 'weekly', undefined, NOW);
  assert.deepEqual(Object.keys(w.outcomes), ['5', '15', '30']);
});

test('reference bar lookup: srcIndex wins; intraday by exact time; daily by IST date; weekly by containing week', () => {
  const s = daily(flat(30));
  assert.equal(referenceIndex(s, { srcIndex: 7, confirmedAt: s[3].time }, 'daily'), 7);
  assert.equal(referenceIndex(s, { confirmedAt: s[9].time + 9 * 3600 }, 'daily'), 9);              // same IST date
  const i = session('2026-03-02', flat(75));
  assert.equal(referenceIndex(i, { confirmedAt: i[20].time }, 'intraday'), 20);
  assert.equal(referenceIndex(i, { confirmedAt: i[20].time + 1 }, 'intraday'), -1);                // not on a bar boundary -> missing, never guessed
  const w = daily(flat(10), 7 * DAY);
  assert.equal(referenceIndex(w, { confirmedAt: w[4].time + 4 * DAY }, 'weekly'), 4);
});

test('closedBars drops the still-forming candle', () => {
  const s = session('2026-03-02', flat(10));
  const now = s[9].time + 120;                                                                       // 2 minutes into bar 9
  assert.equal(closedBars(s, 300, now).length, 9);
});

// ---------------------------------------------------------------- no future-data leakage
test('outcome at horizon h depends only on bars up to ref+h; the band only on bars up to the reference', () => {
  const rng = (a) => () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const r = rng(7);
  const closes = [100]; for (let i = 1; i < 80; i++) closes.push(closes[i - 1] * (1 + (r() - 0.5) * 0.02));
  const base = daily(closes);
  const ref = 30, h = 5;
  const a = forwardOutcome(base, ref, h, 'daily', undefined, NOW);
  const later = base.map((b, i) => (i > ref + h ? { ...b, close: b.close * 3, high: b.high * 3, low: b.low * 3 } : b));   // corrupt only bars after the horizon
  assert.deepEqual(forwardOutcome(later, ref, h, 'daily', undefined, NOW), a);
  const atH = base.map((b, i) => (i === ref + h ? { ...b, close: b.close * 1.2 } : b));                                       // the horizon bar itself matters
  assert.notEqual(forwardOutcome(atH, ref, h, 'daily', undefined, NOW).ret, a.ret);
  const afterRef = base.map((b, i) => (i > ref ? { ...b, close: b.close * (1 + (i % 3) * 0.01) } : b));                      // future bars cannot move the band
  assert.equal(flatBand(afterRef, ref, h, 'daily', mergeConfig({})).band, flatBand(base, ref, h, 'daily', mergeConfig({})).band);
  const beforeRef = base.map((b, i) => (i < ref - 3 ? { ...b, close: b.close * 1.05 * (1 + (i % 2) * 0.03) } : b));
  assert.notEqual(flatBand(beforeRef, ref, h, 'daily', mergeConfig({})).sigma, flatBand(base, ref, h, 'daily', mergeConfig({})).sigma);   // sanity: sigma does use history
});

test('detection leakage: events found on a prefix equal the events the full history reports for those bars', () => {
  const rng = (a) => () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const r = rng(11);
  const closes = [100]; for (let i = 1; i < 520; i++) closes.push(Math.max(5, closes[i - 1] * (1 + (r() - 0.5) * 0.05 + 0.0004)));
  const bars = closes.map((c, i) => ({ time: D0 + i * DAY, open: c * (1 + (r() - 0.5) * 0.01), high: c * 1.01, low: c * 0.99, close: c, volume: 1000 + Math.floor(r() * 500) }));
  const full = fullHistoryEvents({ dailyBars: bars, weeklyBars: [], nowSec: NOW }).daily.events;
  const cut = 400;
  const part = fullHistoryEvents({ dailyBars: bars.slice(0, cut + 1), weeklyBars: [], nowSec: NOW }).daily.events;
  const key = (e) => `${e.patternType}|${e.srcIndex}|${e.confirmedAt}|${e.text}`;
  const fullHead = new Set(full.filter((e) => e.srcIndex < cut).map(key));
  const partHead = new Set(part.filter((e) => e.srcIndex < cut).map(key));
  assert.ok(fullHead.size > 0, 'fixture must produce events or this test proves nothing');
  assert.deepEqual([...partHead].sort(), [...fullHead].sort());
});

// ---------------------------------------------------------------- duplicates, overlap, statistics
const mkEvent = (series, i, type = 'double-bottom', tf = 'intraday') => ({
  kind: 'pattern', patternType: type, pattern: type, timeframe: tf, tone: 'pos', barIndex: i, text: `${type} #${i}`,
  confirmedAt: series[i].time, formedAt: series[i].time, time: series[i].time,
});

test('one formation = ONE occurrence, referenced at its FIRST detection; a separate run is a new occurrence', () => {
  const s = session('2026-03-02', flat(75));
  const events = [mkEvent(s, 10), mkEvent(s, 11), mkEvent(s, 12), mkEvent(s, 40), mkEvent(s, 41)];
  const occ = toOccurrences(events, { symbol: 'TST', timeframe: 'intraday', series: s, nowSec: istInstant('2026-03-02', 16, 0) });
  assert.equal(occ.length, 2);
  assert.deepEqual(occ.map((o) => o.refIndex), [10, 40]);                               // first firing of each run, never a later one
  assert.deepEqual(occ.map((o) => o.confirmedAt), [s[10].time, s[40].time]);
  assert.equal(new Set(occ.map((o) => o.id)).size, 2);
  assert.ok(occ.every((o) => o.classification.bias === 'bullish'));
});

test('overlapping forward windows are removed from the independent statistics', () => {
  const occs = [10, 12, 30, 34, 60].map((refIndex) => ({ refIndex }));
  assert.deepEqual(independentSubset(occs, 5).map((o) => o.refIndex), [10, 30, 60]);   // 12 overlaps 10; 34 overlaps 30 (windows are [ref, ref+h])
  assert.deepEqual(independentSubset(occs, 1).map((o) => o.refIndex), [10, 12, 30, 34, 60]);
});

test('statistics use completed observations only; pending / not evaluable are reported separately; empty -> null, never 0', () => {
  const o = (refIndex, state, ret = null) => ({ refIndex, outcomes: { 5: { state, ret } } });
  const occs = [o(10, 'positive', 0.04), o(30, 'negative', -0.03), o(50, 'flat', 0.001), o(70, 'pending'), o(90, 'not_evaluable'), o(12, 'positive', 0.05)];
  const s = summarizeHorizon(occs, 5, undefined);
  assert.equal(s.all.total, 6); assert.equal(s.all.pending, 1); assert.equal(s.all.notEvaluable, 1); assert.equal(s.all.evaluable, 4);
  assert.equal(s.independent.evaluable, 3); assert.equal(s.independent.skippedOverlap, 1);       // the o(12) overlap
  assert.deepEqual([s.independent.positive, s.independent.negative, s.independent.flat], [1, 1, 1]);
  assert.ok(Math.abs(s.independent.positiveRate - 1 / 3) < 1e-12);
  assert.ok(Math.abs(s.independent.meanReturn - (0.04 - 0.03 + 0.001) / 3) < 1e-12);
  assert.equal(s.independent.medianReturn, 0.001);
  assert.equal(s.smallSample, true);                                                              // 3 < minIndependent
  const none = summarizeHorizon([o(1, 'pending'), o(2, 'not_evaluable')], 5, undefined);
  assert.equal(none.independent.evaluable, 0); assert.equal(none.independent.positiveRate, null); assert.equal(none.independent.meanReturn, null);
});

test('base rate applies the same rule to every bar of the series', () => {
  const up = daily(Array.from({ length: 80 }, (_, i) => 100 * 1.01 ** i));               // +1%/day: every 5-day forward return is ~+5.1%
  const b = baseRate(up, 'daily', 5, mergeConfig({ flat: { k: 0, floor: { daily: 0.02 } } }), NOW);
  assert.equal(b.negative, 0); assert.equal(b.flat, 0); assert.ok(b.n > 50); assert.equal(b.positiveRate, 1);
  assert.equal(baseRate(daily(flat(10)), 'daily', 5, undefined, NOW).positiveRate, null);     // nothing evaluable -> null, not 0
});

test('breakout observation is realised information after detection: up / down / none / pending', () => {
  const c = flat(60, 100);
  const occ = { rangeLow: 95, rangeHigh: 105 };
  assert.equal(observeBreakout(daily(c), 10, occ, 'daily', undefined, NOW).state, 'none');          // 30 bars, never leaves the range
  const up = [...c]; up[14] = 106;
  assert.deepEqual(observeBreakout(daily(up), 10, occ, 'daily', undefined, NOW), { state: 'up', barsAfter: 4, time: D0 + 14 * DAY });
  const dn = [...c]; dn[12] = 94;
  assert.equal(observeBreakout(daily(dn), 10, occ, 'daily', undefined, NOW).state, 'down');
  assert.equal(observeBreakout(daily(c).slice(0, 20), 10, occ, 'daily', undefined, NOW).state, 'pending');   // horizon not complete yet
  assert.equal(observeBreakout(daily(c), 10, {}, 'daily', undefined, NOW).state, 'unavailable');
});

test('an intraday confirming bar that has not closed yet is PENDING, not missing', () => {
  const s = session('2026-03-02', flat(40));
  const closed = closedBars(s, 300, s[39].time + 60);                                    // bar 39 still forming
  const e = mkEvent(s, 39);
  const r = evaluateEvent(e, { timeframe: 'intraday', series: closed, nowSec: s[39].time + 60 });
  assert.ok(Object.values(r.outcomes).every((x) => x.state === OUTCOME.PENDING));
});

test('statsForPattern wires horizons, base rate, sample and config together with the timeframe visible', () => {
  const s = daily(Array.from({ length: 120 }, (_, i) => 100 + Math.sin(i / 5) * 3));
  const events = [20, 50, 80].map((i) => mkEvent(s, i, 'triple-top', 'daily')).map((e, k) => ({ ...e, srcIndex: [20, 50, 80][k], formedAt: s[[20, 50, 80][k]].time }));
  const occ = toOccurrences(events, { symbol: 'TST', timeframe: 'daily', series: s, nowSec: NOW });
  const st = statsForPattern(occ, { patternId: 'triple-top', timeframe: 'daily', series: s, nowSec: NOW });
  assert.equal(st.timeframe, 'daily'); assert.deepEqual(st.horizons.map((h) => h.horizon), [5, 15, 30]);
  assert.equal(st.sample.bars, 120); assert.ok(st.horizons.every((h) => h.base && h.smallSample));
  assert.equal(st.occurrences.length, 3);
});
