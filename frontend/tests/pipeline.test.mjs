import test from 'node:test';
import assert from 'node:assert/strict';
import { PATTERN_REGISTRY, registryById, runDetectors } from '../src/lib/patternRegistry.js';
import { patternType } from '../src/lib/chartPatterns.js';
import { patternStatus } from '../src/lib/patternStatus.js';
import { sortNewestFirst, replayDayEvents } from '../src/lib/eventReplay.js';
import { collapseRuns } from '../src/lib/patternCatalog.js';
import { stampEvent } from '../src/lib/eventModel.js';
import { computeHigherTimeframeEvents, completedDaily, completedWeekly } from '../src/lib/htfEvents.js';
import { istClock, istDate, istInstant, fmtDate, sessionComplete } from '../src/lib/marketTime.js';
import { wave, barsFrom } from './helpers.mjs';

// ---------------------------------------------------------------- registry
const REQUIRED = [
  'VCP', 'Cup & Handle', 'Double Bottom', 'Double Top', 'Flat Base', 'Ascending Base', 'IPO Base', 'High Tight Flag',
  'Three Weeks Tight', 'Flag', 'Pennant', 'Ascending Triangle', 'Descending Triangle', 'Symmetrical Triangle',
  'Rising Wedge', 'Falling Wedge', 'Rectangle', 'Head & Shoulders', 'Inverse Head & Shoulders', 'Triple Bottom',
  'Triple Top', 'Rounding Bottom', 'Rounding Top', 'Cup Base', 'Saucer Base', 'Pocket Pivot', 'Undercut & Rally',
  'Shakeout', 'Wyckoff Spring', 'Wyckoff Upthrust',
];

test('registry: every requested pattern is registered exactly once', () => {
  const have = PATTERN_REGISTRY.map((p) => p.displayName);
  for (const n of REQUIRED) assert.equal(have.filter((x) => x === n).length, 1, n);
  assert.equal(new Set(PATTERN_REGISTRY.map((p) => p.id)).size, PATTERN_REGISTRY.length, 'ids unique');
});
test('registry: id == patternType(displayName); enabled <=> a real detector', () => {
  for (const p of PATTERN_REGISTRY) {
    assert.equal(p.id, patternType(p.displayName));
    assert.equal(p.enabled, typeof p.detector === 'function', p.displayName);
    assert.equal(p.availabilityReason === null, p.enabled, p.displayName);
    assert.ok(['intraday', 'daily', 'weekly'].includes(p.timeframe));
    assert.ok(p.minBars > 0);
  }
});
test('registry: base/structure patterns run on daily/weekly, not 5m proxies', () => {
  const tf = (n) => PATTERN_REGISTRY.find((p) => p.displayName === n).timeframe;
  for (const n of ['VCP', 'Cup & Handle', 'Cup Base', 'Saucer Base', 'Flat Base', 'Ascending Base', 'IPO Base', 'High Tight Flag', 'Rounding Top', 'Rounding Bottom', 'Triple Top', 'Triple Bottom', 'Shakeout', 'Pennant']) {
    assert.equal(tf(n), 'daily', n);
  }
  assert.equal(tf('Three Weeks Tight'), 'weekly');
});
test('registry: every event type the intraday detectors emit is registered', () => {
  // wavy synthetic series that exercises the swing-based detectors
  const closes = Array.from({ length: 400 }, (_, i) => 100 + 6 * Math.sin(i / 5) + 3 * Math.sin(i / 11) + i * 0.01);
  const bars = barsFrom(closes, { step: 300, vol: (i) => 1000 + (i % 7) * 120 });
  const ev = replayDayEvents(bars, { patternsOnly: true });
  assert.ok(ev.length > 0, 'detectors produced events to check');
  for (const e of ev) {
    const reg = registryById.get(e.patternType);
    assert.ok(reg, `unregistered type ${e.patternType}`);
    assert.equal(reg.timeframe, 'intraday');
  }
});
test('registry: runDetectors drops events when bars < minBars', () => {
  const closes = wave([[0, 50], [130, 110], [140, 90], [150, 108], [156, 98], [165, 107.5], [170, 103], [176, 106]]);
  const bars = barsFrom(closes, { vol: (i) => (i <= 140 ? 1000 : i <= 156 ? 700 : 400) });
  assert.deepEqual(runDetectors('daily', bars).map((e) => e.pattern), ['VCP']);
  assert.deepEqual(runDetectors('daily', bars.slice(0, 100)).filter((e) => e.pattern === 'VCP'), []);
});

// ---------------------------------------------------------------- statuses
test('status: four distinct chip states', () => {
  const ctx = (o = {}) => ({ counts: new Map(), barCounts: { intraday: 500, daily: 300, weekly: 100 }, history: { daily: 'ok', weekly: 'ok' }, ...o });
  const vcp = registryById.get('vcp');
  assert.equal(patternStatus(vcp, ctx({ counts: new Map([['vcp', 2]]) })).state, 'found');
  assert.equal(patternStatus(vcp, ctx()).state, 'zero');
  assert.equal(patternStatus(vcp, ctx({ barCounts: { intraday: 500, daily: 90, weekly: 100 } })).state, 'needs-data');
  assert.match(patternStatus(vcp, ctx({ history: { daily: 'failed', weekly: 'ok' } })).reason, /daily history/);
  assert.equal(patternStatus(vcp, ctx({ history: { daily: 'loading', weekly: 'ok' } })).state, 'loading');
  assert.equal(patternStatus({ ...vcp, enabled: false, detector: null, availabilityReason: 'Detector not available yet' }, ctx()).state, 'unavailable');
});

// ------------------------------------------------------------ time / order
test('time: IST display, upper-case, single convention', () => {
  const t = Date.parse('2026-10-01T09:45:00Z') / 1000; // 15:15 IST
  assert.equal(istClock(t), '03:15 PM');
  assert.equal(istDate(t), '2026-10-01');
  assert.equal(fmtDate(t), '01 Oct 2026');
  // a UTC-evening instant that is already the NEXT IST date
  const late = Date.parse('2026-09-30T20:00:00Z') / 1000;
  assert.equal(istDate(late), '2026-10-01');
});
test('time: session completeness is judged at 15:30 IST', () => {
  assert.equal(sessionComplete('2026-10-01', istInstant('2026-10-01', 15, 29)), false);
  assert.equal(sessionComplete('2026-10-01', istInstant('2026-10-01', 15, 30)), true);
});
test('order: newest first, never 15:15 -> 15:05 -> 15:15; same-candle events stay together', () => {
  const T = (h, m) => istInstant('2026-10-01', h, m);
  const evs = [
    { time: T(15, 15), kind: 'momentum', text: 'RSI' }, { time: T(15, 5), kind: 'structure', text: 'swing' },
    { time: T(15, 15), kind: 'pattern', text: 'Rectangle' }, { time: T(15, 10), kind: 'volume', text: 'spike' },
    { time: T(15, 15), kind: 'volatility', text: 'BB' }, { time: T(15, 5), kind: 'pattern', text: 'Flag' },
  ];
  const sorted = sortNewestFirst(evs);
  for (let i = 1; i < sorted.length; i++) assert.ok(sorted[i - 1].time >= sorted[i].time);
  assert.deepEqual(sorted.slice(0, 3).map((e) => e.kind), ['pattern', 'momentum', 'volatility']); // deterministic tie order
  // input order must not matter
  assert.deepEqual(sortNewestFirst([...evs].reverse()), sorted);
});
test('timestamps: explicit fields; pivot time kept as market time, confirmation retained separately', () => {
  const evalBar = { time: 2000 };
  const s = stampEvent({ time: 1700, kind: 'structure', text: 'New swing high' }, evalBar, 99999);
  assert.equal(s.time, 1700);
  assert.equal(s.formedAt, 1700);
  assert.equal(s.confirmedAt, 2000);
  assert.equal(s.candleTime, 2000);
  assert.equal(s.detectedAt, 99999);
  assert.ok(s.id);
});
test('timestamps: replayed events carry the bar they were evaluated on as confirmedAt', () => {
  const closes = Array.from({ length: 150 }, (_, i) => 100 + 6 * Math.sin(i / 5));
  const ev = replayDayEvents(barsFrom(closes, { step: 300 }));
  assert.ok(ev.length);
  for (const e of ev) {
    assert.ok(e.confirmedAt >= e.formedAt, 'confirmed no earlier than formed');
    assert.equal(e.time, e.formedAt);
    assert.ok(typeof e.id === 'string');
  }
});

// ------------------------------------------------------------------ runs
test('collapseRuns: consecutive daily firings across a weekend are ONE formation; ids stay distinct', () => {
  const mk = (formedAt, barIndex) => ({ kind: 'pattern', patternType: 'flat-base', timeframe: 'daily', formedAt, barIndex, time: formedAt, id: `${formedAt}` });
  const D = 86400;
  const ev = [mk(0, 10), mk(D, 85), mk(4 * D, 160), mk(30 * D, 900)];
  const runs = collapseRuns(ev);
  assert.equal(runs.length, 2);
  assert.notEqual(runs[0].id, runs[1].id);
});

// -------------------------------------------------------- HTF projection
const fiveMin = (dateStr) => {
  const open = istInstant(dateStr, 9, 15);
  return Array.from({ length: 75 }, (_, i) => ({ time: open + i * 300, open: 100, high: 100.5, low: 99.5, close: 100, volume: 100 }));
};
function dailyEndingOn(dateStr, closes) {
  const end = istInstant(dateStr);
  return barsFrom(closes, { step: 86400, start: end - (closes.length - 1) * 86400 });
}
const FLAT = [...wave([[0, 70], [59, 100]]), ...Array.from({ length: 30 }, (_, i) => 100 + (i % 2 ? 2 : -2))];

test('HTF: a daily detection lands on a REAL intraday bar of its session (not the current candle)', () => {
  const intraday = [...fiveMin('2026-03-02'), ...fiveMin('2026-03-03')];
  const daily = dailyEndingOn('2026-03-03', FLAT);
  const now = istInstant('2026-03-03', 16, 0);
  const ev = computeHigherTimeframeEvents({ dailyBars: daily, weeklyBars: [], intradayCandles: intraday, nowSec: now });
  const fb = ev.filter((e) => e.patternType === 'flat-base');
  assert.ok(fb.length >= 1);
  for (const e of fb) {
    assert.equal(intraday[e.barIndex].time, e.time, 'marker time == that candle');
    assert.equal(e.timeframe, 'daily');
    assert.equal(istDate(e.time), e.formedDate);
    assert.ok(e.startIndex <= e.barIndex);
  }
  const last = fb[fb.length - 1];
  assert.equal(last.formedDate, '2026-03-03');
  assert.equal(last.barIndex, intraday.length - 1);
  assert.equal(last.formedAt, istInstant('2026-03-03', 15, 30));
});
test('HTF: partial (in-session) daily bar is excluded', () => {
  const intraday = fiveMin('2026-03-03');
  const daily = dailyEndingOn('2026-03-03', FLAT);
  const morning = istInstant('2026-03-03', 11, 0);
  assert.equal(completedDaily(daily, morning).length, daily.length - 1);
  const ev = computeHigherTimeframeEvents({ dailyBars: daily, weeklyBars: [], intradayCandles: intraday, nowSec: morning });
  assert.ok(ev.every((e) => e.formedDate !== '2026-03-03'), 'today is not complete yet');
});
test('HTF: a loaded past day never sees later daily bars (no leakage)', () => {
  const daily = dailyEndingOn('2026-03-10', FLAT); // base completes on 03-10 only
  const intradayPast = fiveMin('2026-03-02');
  const ev = computeHigherTimeframeEvents({ dailyBars: daily, weeklyBars: [], intradayCandles: intradayPast, nowSec: istInstant('2026-03-10', 16, 0) });
  for (const e of ev) {
    assert.ok(e.formedDate <= '2026-03-02');
    assert.ok(e.time <= intradayPast[intradayPast.length - 1].time);
  }
});
test('HTF: weekly Three Weeks Tight lands on the last trading day of its week', () => {
  const closes = [...wave([[0, 80], [16, 99]]).slice(0, 16), 100, 100.4, 100.2]; // 19 weeks
  const lastMonday = istInstant('2026-03-02');
  const weekly = barsFrom(closes, { step: 7 * 86400, start: lastMonday - 18 * 7 * 86400 });
  const dailyBars = [];
  for (let w = 0; w < weekly.length; w++) for (let d = 0; d < 5; d++) dailyBars.push({ time: weekly[w].time + d * 86400, open: 1, high: 1, low: 1, close: weekly[w].close, volume: 1 });
  const intraday = fiveMin('2026-03-06'); // that week's Friday
  const ev = computeHigherTimeframeEvents({ dailyBars, weeklyBars: weekly, intradayCandles: intraday, nowSec: istInstant('2026-03-07', 10, 0) });
  const t = ev.filter((e) => e.patternType === 'three-weeks-tight');
  assert.equal(t.length, 1);
  assert.equal(t[0].timeframe, 'weekly');
  assert.equal(t[0].formedDate, '2026-03-06');
  assert.equal(t[0].barIndex, intraday.length - 1);
  // the in-progress week is dropped
  assert.equal(completedWeekly(weekly, istInstant('2026-03-04', 12, 0)).length, weekly.length - 1);
});
