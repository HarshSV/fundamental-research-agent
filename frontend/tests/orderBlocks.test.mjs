import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { detectOrderBlocks, deriveSessionMeta, currentZones, zoneEvents, DEFAULT_OB_PARAMS, OB_PARAMS_VERSION } from '../src/lib/orderBlocks.js';
import { PATTERN_REGISTRY, registryById, runDetectors } from '../src/lib/patternRegistry.js';
import { replayDayEvents } from '../src/lib/eventReplay.js';
import { istInstant } from '../src/lib/marketTime.js';
import { wave } from './helpers.mjs';

const DAY = '2026-01-05';
const T0 = istInstant(DAY, 9, 15);
const META = { sessionStart: T0, sessionEnd: istInstant(DAY, 15, 30), tickSize: null, prevDayHigh: null, prevDayLow: null };
const near = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-6 * Math.max(1, Math.abs(b)), `${msg}: ${a} vs ${b}`);

// Bullish fixture in price units of `px`. Bars 0-29 are a zigzag (swing highs at 3/11/19/27, lows at 7/15/23),
// bar 30 is the down-close block with the lowest low, bar 31 the break (variant-controlled), then `tail` bars.
function bullBars({ px = 100, peaks = [1.020, 1.020, 1.012], bar31 = null, tail = [], vol = 1000 } = {}) {
  const knots = [[0, 1.0], [3, peaks[0]], [7, 0.996], [11, peaks[1]], [15, 0.997], [19, peaks[2]], [23, 0.998], [27, 1.007], [29, 1.002]];
  const closes = wave(knots);
  const rows = closes.map((c, i) => [i ? closes[i - 1] : c, c + 0.001, c - 0.001, c]);
  rows.push([1.001, 1.002, 0.990, 0.9985]); // 30: block (down close, lowest low)
  rows.push(bar31 || [0.9985, 1.012, 0.991, 1.010]); // 31: break + displacement
  for (const t of tail) rows.push(t);
  return rows.map(([o, h, l, c], i) => ({
    time: T0 + i * 300, open: o * px, high: h * px, low: l * px, close: c * px, volume: typeof vol === 'function' ? vol(i) : vol,
  }));
}
const mirror = (bars, pivot = 2) => bars.map((b) => ({ ...b, open: pivot - b.open, high: pivot - b.low, low: pivot - b.high, close: pivot - b.close }));
// the fixture block is bar 30; other zones may form on the zigzag when peaks are lowered
const NO_WICK = [0.9985, 1.010, 0.991, 1.010]; // break bar with no upper wick: the session high is then not above price
const bullOf = (zs) => zs.filter((z) => z.side === 'bull' && z.startIndex === 30);
const bearOf = (zs) => zs.filter((z) => z.side === 'bear');

test('params are versioned and single-sourced', () => {
  assert.equal(OB_PARAMS_VERSION, 1);
  assert.equal(DEFAULT_OB_PARAMS.paramsVersion, 1);
  assert.equal(detectOrderBlocks(bullBars(), META)[0].paramsVersion, 1);
});

test('bullish: basic order block with liquidity levels and Room:Risk', () => {
  const zs = bullOf(detectOrderBlocks(bullBars(), META));
  assert.equal(zs.length, 1);
  const z = zs[0];
  assert.equal(z.startIndex, 30); assert.equal(z.bosIndex, 31);
  near(z.zoneLow, 99.0, 'low'); near(z.zoneHigh, 100.2, 'high');
  near(z.z, 100.2, 'Z = near edge'); near(z.inv, 99.0, 'INV = block low, no buffer');
  near(z.level1, 101.3, 'L1 swing'); near(z.level2, 102.1, 'L2 equal highs');
  assert.equal(z.level2Kind, 'equal');
  near(z.rr, (102.1 - 100.2) / (100.2 - 99.0), 'rr');
  assert.equal(z.lowRoom, false);
  assert.equal(z.state, 'formed');
  assert.equal(z.formedAt, T0 + 31 * 300); assert.equal(z.confirmedAt, z.formedAt);
  assert.ok(z.vwapSide === 'above' || z.vwapSide === 'below'); assert.ok(Number.isFinite(z.vwap));
});

test('bearish mirror of the same fixture', () => {
  const zs = bearOf(detectOrderBlocks(mirror(bullBars({ px: 1 })), META));
  assert.equal(zs.length, 1);
  assert.equal(zs[0].startIndex, 30);
  near(zs[0].z, 2 - 1.002, 'Z = block low'); near(zs[0].inv, 2 - 0.990, 'INV = block high');
  assert.ok(zs[0].level2 < zs[0].level1);
});

test('no BOS: no zone', () => {
  assert.equal(detectOrderBlocks(bullBars({ bar31: [0.9985, 1.004, 0.998, 1.003] }), META).length, 0);
});
test('BOS without displacement: no zone', () => {
  const tail = [[1.009, 1.0095, 1.001, 1.002]]; // no gap above the block either
  assert.equal(bullOf(detectOrderBlocks(bullBars({ bar31: [1.0, 1.0095, 1.004, 1.009], tail }), META)).length, 0);
});
test('wick-only break: no zone', () => {
  assert.equal(bullOf(detectOrderBlocks(bullBars({ bar31: [0.9985, 1.012, 0.991, 1.0075] }), META)).length, 0);
});

const RETEST_TAIL = [
  [1.010, 1.012, 1.009, 1.011], // 32 away
  [1.011, 1.012, 1.001, 1.006], // 33 overlaps zone, closes above -> touch 1
  [1.006, 1.012, 1.005, 1.011], // 34 away
  [1.011, 1.012, 1.000, 1.005], // 35 touch 2
  [1.005, 1.008, 1.001, 1.004], // 36 contiguous retest bar: same excursion
];
test('retest counting (separate excursions only)', () => {
  const z = bullOf(detectOrderBlocks(bullBars({ tail: RETEST_TAIL }), META))[0];
  assert.equal(z.touchCount, 2);
  assert.equal(z.state, 'retested');
  assert.equal(z.firstRetestTime, T0 + 33 * 300);
  assert.equal(z.brokenAt, null);
});
test('broken only on a CLOSE beyond INV; a wick through is not broken', () => {
  const wick = bullOf(detectOrderBlocks(bullBars({ tail: [[1.011, 1.011, 0.985, 0.995]] }), META))[0];
  assert.equal(wick.brokenAt, null); assert.notEqual(wick.state, 'broken');
  const closed = bullOf(detectOrderBlocks(bullBars({ tail: [[1.011, 1.011, 0.985, 0.989]] }), META))[0];
  assert.equal(closed.state, 'broken'); assert.equal(closed.brokenAt, T0 + 32 * 300);
  assert.equal(currentZones([closed]).bull, undefined);
});

test('forming candle is never used', () => {
  const bars = bullBars();
  const last = bars[bars.length - 1].time;
  assert.equal(detectOrderBlocks(bars, { ...META, nowSec: last + 100 }).length, 0, 'still forming');
  assert.equal(bullOf(detectOrderBlocks(bars, { ...META, nowSec: last + 300 })).length, 1, 'closed');
});
test('insufficient history: no zone (not a zero-valued zone)', () => {
  const bars = bullBars().slice(20);
  assert.deepEqual(detectOrderBlocks(bars, { ...META, sessionStart: bars[0].time }), []);
});
test('fewer than two liquidity candidates: nulls, never 0', () => {
  const none = bullOf(detectOrderBlocks(bullBars({ peaks: [1.004, 1.004, 1.004], bar31: NO_WICK }), META))[0];
  assert.equal(none.level1, null); assert.equal(none.level2, null); assert.equal(none.rr, null); assert.equal(none.lowRoom, false);
  assert.ok(none.reasons.some((r) => /no untested liquidity/.test(r)));
  const one = bullOf(detectOrderBlocks(bullBars({ peaks: [1.004, 1.020, 1.004], bar31: NO_WICK }), META))[0];
  near(one.level1, 102.1, 'single level'); assert.equal(one.level2, null); assert.equal(one.rr, null);
  assert.ok(one.reasons.includes('only 1 liquidity level in range'));
});
test('lowRoom only when rr is a number below the floor', () => {
  const z = bullOf(detectOrderBlocks(bullBars({ peaks: [1.004, 1.0125, 1.0118] }), META))[0];
  assert.ok(z.rr != null && z.rr < DEFAULT_OB_PARAMS.rrFloor); assert.equal(z.lowRoom, true);
});
test('missing volume: vwap null with a reason (not 0)', () => {
  const z = bullOf(detectOrderBlocks(bullBars({ vol: (i) => (i === 10 ? null : 1000) }), META))[0];
  assert.equal(z.vwap, null); assert.equal(z.vwapSide, null);
  assert.ok(z.reasons.some((r) => /VWAP unavailable/.test(r)));
  const zero = bullOf(detectOrderBlocks(bullBars({ vol: 0 }), META))[0];
  assert.equal(zero.vwap, null, 'provider zero = unknown volume, not a real value');
});
test('tick size: buffer only when known; never NaN', () => {
  const k = bullOf(detectOrderBlocks(bullBars(), { ...META, tickSize: 0.05 }))[0];
  near(k.inv, 99.0 - 0.05, 'buffered');
  const u = bullOf(detectOrderBlocks(bullBars(), { ...META, tickSize: null }))[0];
  near(u.inv, 99.0, 'no buffer'); assert.ok(Number.isFinite(u.inv));
  assert.ok(u.reasons.some((r) => /tick size unknown/.test(r)));
});
test('prior-day high is a liquidity candidate only when provided', () => {
  const z = bullOf(detectOrderBlocks(bullBars({ peaks: [1.004, 1.004, 1.004], bar31: NO_WICK }), { ...META, prevDayHigh: 101.5 }))[0];
  near(z.level1, 101.5, 'prev-day high'); assert.equal(z.level1Kind, 'prevDay'); assert.equal(z.level2, null);
});
test('zMode mid', () => {
  const z = bullOf(detectOrderBlocks(bullBars(), META, { ...DEFAULT_OB_PARAMS, zMode: 'mid' }))[0];
  near(z.z, 99.6, 'mid');
});

// --- determinism / look-ahead ------------------------------------------------
const FULL = bullBars({ tail: RETEST_TAIL.concat([[1.004, 1.005, 0.985, 0.989], [0.989, 0.990, 0.975, 0.976]]) });
const IDENT = ['id', 'side', 'formedAt', 'confirmedAt', 'time', 'startIndex', 'zoneLow', 'zoneHigh', 'z', 'inv', 'level1', 'level2', 'ladderOpposite', 'rr', 'vwapSide'];
const pick = (z) => Object.fromEntries(IDENT.map((k) => [k, z[k]]));

test('look-ahead guard: results at bar t ignore future bars', () => {
  const full = detectOrderBlocks(FULL, META);
  assert.ok(full.length >= 1);
  for (let t = 0; t < FULL.length; t++) {
    const prefix = detectOrderBlocks(FULL.slice(0, t + 1), META);
    const expected = full.filter((z) => z.confirmedAt <= FULL[t].time).map(pick);
    assert.deepEqual(prefix.map(pick), expected, `t=${t}`);
    for (const z of prefix) {
      const f = full.find((q) => q.id === z.id);
      assert.equal(z.brokenAt != null, f.brokenAt != null && f.brokenAt <= FULL[t].time, `broken as of ${t}`);
      assert.equal(z.touchCount, f.retestTimes.filter((x) => x <= FULL[t].time).length, `touches as of ${t}`);
    }
  }
});
test('live-incremental (with a forming bar each step) equals full replay', () => {
  const full = detectOrderBlocks(FULL, META);
  let last;
  for (let t = 1; t <= FULL.length; t++) {
    const now = FULL[t - 1].time + 300;
    const withForming = FULL.slice(0, t).concat([{ ...FULL[t - 1], time: FULL[t - 1].time + 300, close: 1 }]);
    last = detectOrderBlocks(withForming, { ...META, nowSec: now });
  }
  assert.deepEqual(last, full);
});
test('registry detector replay == full-pass zone events', () => {
  // 10 flat pre-session warm-up bars so the 40-bar registry floor is met when the block forms
  const warm = Array.from({ length: 10 }, (_, i) => ({ time: T0 - (10 - i) * 300, open: 100, high: 100.1, low: 99.9, close: 100, volume: 1000 }));
  const W = [...warm, ...FULL];
  const direct = zoneEvents(detectOrderBlocks(W, deriveSessionMeta(W)), W).map((e) => `${e.patternType}|${e.time}|${e.text}`).sort();
  const replay = replayDayEvents(W, { patternsOnly: true, meta: { includeOptIn: true } })
    .filter((e) => registryById.get(e.patternType)?.optIn).map((e) => `${e.patternType}|${e.time}|${e.text}`).sort();
  assert.deepEqual(replay, direct);
  assert.ok(direct.length >= 3);
});

// --- genericity ----------------------------------------------------------------
test('same logic on 5 price scales gives scale-free identical zones', () => {
  const ref = detectOrderBlocks(bullBars({ px: 1, tail: RETEST_TAIL }), META);
  for (const px of [50, 120, 800, 1900, 3500]) {
    const zs = detectOrderBlocks(bullBars({ px, tail: RETEST_TAIL, vol: (i) => 500 + px * (i % 3) }), META);
    assert.equal(zs.length, ref.length);
    zs.forEach((z, i) => {
      assert.equal(z.startIndex, ref[i].startIndex); assert.equal(z.state, ref[i].state); assert.equal(z.touchCount, ref[i].touchCount);
      near(z.z / px, ref[i].z, 'z'); near(z.inv / px, ref[i].inv, 'inv');
      if (ref[i].rr != null) near(z.rr, ref[i].rr, 'rr');
    });
  }
});
test('no ticker-specific logic in orderBlocks.js', () => {
  const src = fs.readFileSync(new URL('../src/lib/orderBlocks.js', import.meta.url), 'utf8');
  for (const t of ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK', 'SBIN', 'TITAN', 'ANURAS', 'NIFTY', '.NS', 'symbol']) {
    assert.ok(!src.includes(t), `found "${t}"`);
  }
});

test('deriveSessionMeta: prior-day high/low only from a complete prior session', () => {
  const prev = istInstant('2026-01-02', 9, 15);
  const mkDay = (start, n) => Array.from({ length: n }, (_, i) => ({ time: start + i * 300, open: 100, high: 100 + (i === 5 ? 3 : 1), low: 99 - (i === 7 ? 2 : 0), close: 100, volume: 1 }));
  const m = deriveSessionMeta([...mkDay(prev, 75), ...bullBars()]);
  assert.equal(m.prevDayHigh, 103); assert.equal(m.prevDayLow, 97);
  assert.equal(m.sessionStart, T0);
  const partial = deriveSessionMeta([...mkDay(prev, 30), ...bullBars()]);
  assert.equal(partial.prevDayHigh, null); assert.equal(partial.prevDayLow, null);
});

test('registry: order block types registered, opt-in, intraday, and emitted types are registered', () => {
  for (const n of ['bullish-order-block', 'bearish-order-block', 'order-block-retest', 'order-block-broken']) {
    const r = registryById.get(n);
    assert.ok(r && r.enabled && r.optIn && r.timeframe === 'intraday' && r.minBars === 40 && r.category === 'structure', n);
  }
  assert.equal(runDetectors('intraday', FULL).filter((e) => registryById.get(e.patternType).optIn).length, 0, 'off by default');
  const on = runDetectors('intraday', FULL, { includeOptIn: true });
  for (const e of on) assert.ok(registryById.get(e.patternType), e.patternType);
  assert.equal(PATTERN_REGISTRY.filter((p) => p.optIn).length, 4);
});
