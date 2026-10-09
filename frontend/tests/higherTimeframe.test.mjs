// Each daily/weekly detector must fire on a constructed instance of its
// pattern and stay silent on shapes that do not match.
import test from 'node:test';
import assert from 'node:assert/strict';
import * as H from '../src/lib/higherTimeframePatterns.js';
import { wave, barsFrom } from './helpers.mjs';

const names = (ev) => ev.map((e) => e.pattern);

test('Flat Base: tight 35-day range after a 30% advance', () => {
  const closes = [...wave([[0, 70], [59, 100]]), ...Array.from({ length: 30 }, (_, i) => 100 + (i % 2 ? 2 : -2))];
  assert.deepEqual(names(H.flatBaseDaily(barsFrom(closes))), ['Flat Base']);
});
test('Flat Base: silent without a prior advance', () => {
  const closes = Array.from({ length: 120 }, (_, i) => 100 + (i % 2 ? 2 : -2));
  assert.deepEqual(H.flatBaseDaily(barsFrom(closes)), []);
});
test('Flat Base: silent when the range is too deep', () => {
  const closes = [...wave([[0, 70], [59, 100]]), ...Array.from({ length: 30 }, (_, i) => 100 + (i % 2 ? 12 : -12))];
  assert.deepEqual(H.flatBaseDaily(barsFrom(closes)), []);
});

function cupCloses(handle) {
  const pre = wave([[0, 80], [20, 100]]).slice(0, 20);
  const cup = Array.from({ length: 81 }, (_, i) => 100 - 22 * Math.sin((Math.PI * i) / 80)); // idx 20..100
  return [...pre, ...cup, ...handle];
}
const HANDLE = [99, 97, 95, 94, 93, 93.5, 94, 94.5, 95, 95.5, 96, 96];
test('Cup & Handle: 80-day U cup + 12-day shallow handle', () => {
  const ev = H.cupAndHandleDaily(barsFrom(cupCloses(HANDLE)));
  assert.deepEqual(names(ev), ['Cup & Handle']);
  assert.ok(ev[0].startIndex >= 15 && ev[0].startIndex <= 25, 'starts at the left rim');
});
test('Cup & Handle: silent for a V-shaped dip', () => {
  const pre = wave([[0, 80], [20, 100]]).slice(0, 20);
  const v = wave([[20, 100], [60, 78], [100, 100]]);
  assert.deepEqual(H.cupAndHandleDaily(barsFrom([...pre, ...v.slice(0, 81), ...HANDLE])), []);
});
test('Cup Base: valid cup, no handle yet', () => {
  const closes = cupCloses([99.5, 100, 100.2, 100]);
  assert.deepEqual(names(H.cupBaseDaily(barsFrom(closes))), ['Cup Base']);
});

const parab = (n, lo, hi, dir) => Array.from({ length: n }, (_, i) => {
  const t = i / (n - 1);
  return dir === 'bottom' ? lo + (hi - lo) * (2 * t - 1) ** 2 : hi - (hi - lo) * (2 * t - 1) ** 2;
});
test('Rounding Bottom: 40-day parabola, 20% sag', () => {
  assert.deepEqual(names(H.roundingBottomDaily(barsFrom(parab(40, 80, 100, 'bottom')))), ['Rounding Bottom']);
});
test('Rounding Top: mirror shape', () => {
  assert.deepEqual(names(H.roundingTopDaily(barsFrom(parab(40, 100, 120, 'top')))), ['Rounding Top']);
});
test('Rounding: silent on a straight line', () => {
  const closes = wave([[0, 100], [60, 130]]);
  assert.deepEqual(H.roundingBottomDaily(barsFrom(closes)), []);
  assert.deepEqual(H.roundingTopDaily(barsFrom(closes)), []);
});
test('Saucer Base: 60-day shallow rounded base', () => {
  assert.deepEqual(names(H.saucerBaseDaily(barsFrom(parab(60, 88, 100, 'bottom')))), ['Saucer Base']);
});
test('Saucer Base: a deep (30%) rounded base is not a saucer', () => {
  assert.deepEqual(H.saucerBaseDaily(barsFrom(parab(60, 70, 100, 'bottom'))), []);
});

test('Triple Top: three equal peaks with 10% reactions', () => {
  const closes = wave([[0, 90], [10, 100], [17, 90], [24, 100], [31, 90], [38, 100], [44, 95]]);
  assert.deepEqual(names(H.tripleTopDaily(barsFrom(closes))), ['Triple Top']);
});
test('Triple Top: silent when the third peak is lower', () => {
  const closes = wave([[0, 90], [10, 100], [17, 90], [24, 100], [31, 90], [38, 94], [44, 90]]);
  assert.deepEqual(H.tripleTopDaily(barsFrom(closes)), []);
});
test('Triple Bottom: three equal troughs', () => {
  const closes = wave([[0, 110], [10, 100], [17, 110], [24, 100], [31, 110], [38, 100], [44, 105]]);
  assert.deepEqual(names(H.tripleBottomDaily(barsFrom(closes))), ['Triple Bottom']);
});

test('VCP: uptrend with 18% -> 9% -> 4% contractions and drying volume', () => {
  const closes = wave([[0, 50], [130, 110], [140, 90], [150, 108], [156, 98], [165, 107.5], [170, 103], [176, 106]]);
  const bars = barsFrom(closes, { vol: (i) => (i <= 140 ? 1000 : i <= 156 ? 700 : 400) });
  const ev = H.vcpDaily(bars);
  assert.deepEqual(names(ev), ['VCP']);
  assert.match(ev[0].text, /3 contractions/);
});
test('VCP: silent when contractions are not shrinking', () => {
  const closes = wave([[0, 50], [130, 110], [140, 99], [150, 108], [156, 90], [165, 107.5], [170, 84], [176, 100]]);
  const bars = barsFrom(closes, { vol: (i) => (i <= 140 ? 1000 : 400) });
  assert.deepEqual(H.vcpDaily(bars), []);
});
test('VCP: silent below the 150-bar minimum', () => {
  assert.deepEqual(H.vcpDaily(barsFrom(wave([[0, 50], [100, 100]]))), []);
});

test('High Tight Flag: 120% pole in 30 days then a 10% flag', () => {
  const closes = [...Array(40).fill(50), ...wave([[40, 50], [69, 110]]).slice(0, 29), ...wave([[0, 110], [9, 100]]).slice(0, 9), 100];
  assert.deepEqual(names(H.highTightFlagDaily(barsFrom(closes))), ['High Tight Flag']);
});
test('High Tight Flag: silent for a 40% pole', () => {
  const closes = [...Array(40).fill(50), ...wave([[40, 50], [69, 70]]).slice(0, 29), ...Array(11).fill(69)];
  assert.deepEqual(H.highTightFlagDaily(barsFrom(closes)), []);
});

test('Ascending Base: three 12% pullbacks with rising highs and lows', () => {
  const closes = wave([[0, 80], [20, 100], [35, 88], [55, 110], [70, 97], [90, 120], [105, 106], [115, 118]]);
  assert.deepEqual(names(H.ascendingBaseDaily(barsFrom(closes))), ['Ascending Base']);
});
test('Ascending Base: silent when lows fall', () => {
  const closes = wave([[0, 80], [20, 100], [35, 88], [55, 110], [70, 85], [90, 120], [105, 80], [115, 118]]);
  assert.deepEqual(H.ascendingBaseDaily(barsFrom(closes)), []);
});

test('IPO Base: only when the listing date is known', () => {
  const closes = [...wave([[0, 100], [30, 130]]).slice(0, 30), ...Array.from({ length: 25 }, (_, i) => 128 + (i % 2 ? 2 : 0))];
  assert.deepEqual(names(H.ipoBaseDaily(barsFrom(closes), { listingKnown: true })), ['IPO Base']);
  assert.deepEqual(H.ipoBaseDaily(barsFrom(closes), { listingKnown: false }), []);
});

test('Shakeout: undercut then close back above on 3x volume', () => {
  const bars = barsFrom(Array(30).fill(100));
  bars[29] = { ...bars[29], low: 97, close: 100, volume: 3000 };
  assert.deepEqual(names(H.shakeoutDaily(bars)), ['Shakeout']);
  const quiet = barsFrom(Array(30).fill(100));
  quiet[29] = { ...quiet[29], low: 97, close: 100, volume: 1000 };
  assert.deepEqual(H.shakeoutDaily(quiet), [], 'needs the volume spike');
});

test('Pennant: 15% pole then a converging 10-day flag', () => {
  const pole = [...Array(20).fill(100), ...wave([[0, 100], [12, 115]]).slice(1)];
  const closes = [...pole, ...Array(10).fill(113)];
  const bars = barsFrom(closes);
  const n = pole.length;
  for (let i = 0; i < 10; i++) {
    bars[n + i] = { ...bars[n + i], high: 116 - i * 0.33, low: 110 + i * 0.22, close: 113, open: 113 };
  }
  assert.deepEqual(names(H.pennantDaily(bars)), ['Pennant']);
});

test('Three Weeks Tight (weekly): 3 closes within 1% in an uptrend', () => {
  const closes = [...wave([[0, 80], [16, 99]]).slice(0, 16), 100, 100.4, 100.2];
  assert.deepEqual(names(H.threeWeeksTightWeekly(barsFrom(closes, { step: 7 * 86400 }))), ['Three Weeks Tight']);
});
test('Three Weeks Tight (weekly): silent when closes spread 3%', () => {
  const closes = [...wave([[0, 80], [16, 99]]).slice(0, 16), 100, 103, 101];
  assert.deepEqual(H.threeWeeksTightWeekly(barsFrom(closes, { step: 7 * 86400 })), []);
});
test('Three Weeks Tight (weekly): needs >= 13 weekly bars', () => {
  assert.deepEqual(H.threeWeeksTightWeekly(barsFrom([100, 100, 100, 100, 100], { step: 7 * 86400 })), []);
});
