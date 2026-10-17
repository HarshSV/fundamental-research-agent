// Order Block + liquidity zone detector (original algorithm, params version 1).
//
// Pure and deterministic: no DOM, network or clock. One forward pass over the
// CLOSED 5-minute bars; the state at bar t depends only on bars with time <= t,
// so live polling, incremental evaluation and full replay give identical zones.
//
// Rules, exactly as implemented (every number lives in DEFAULT_OB_PARAMS):
//  Bars     closed bars only. If meta.nowSec is given, trailing bars whose period
//           end (time + barSec) is after nowSec are still forming and are dropped
//           (same rule as forecast.js lastCompletedTime). Bars before
//           meta.sessionStart only supply context (ATR, swings); zones are formed
//           by bars inside [sessionStart, sessionEnd).
//  Swings   swingPoints(bars, swingWing): a swing at k is confirmed at bar
//           k + swingWing. Only same-session swings are BOS levels.
//  ATR/body ATR = mean true range of the atrLen bars BEFORE the test bar; bodyAvg =
//           mean |close-open| of the bodyLen bars before it. With fewer bars the
//           test is null and no zone is emitted (insufficient history is not a
//           detection).
//  BOS      bullish at bar j: close[j] > the latest confirmed same-session swing
//           high (confirmed before j) AND no earlier close since that swing
//           exceeded it. If the session has no confirmed swing high yet, the
//           opening-range high (bars in the first openingRangeMin minutes) is
//           used once the range is complete. Bearish mirrors with lows.
//           A wick through the level is not a break.
//  Displace any of: range[j] >= dispMult*ATR; close beyond the broken level by
//           >= bodyAvg; or a fair-value gap low[j+1] > high[j-1] (bearish:
//           high[j+1] < low[j-1]). Only the gap needs bar j+1, so such a zone is
//           confirmed one bar after the BOS bar (confirmedAt >= formedAt).
//  OB       bullish: the last down-close candle at or before the leg origin (the
//           lowest low in the last obLookback bars up to j), searched back at most
//           obLookback bars and not past the previous confirmed swing low, inside
//           the session. Bearish mirrors. Zone = that candle's [low, high].
//  Z / INV  Z = nearest zone edge (zMode 'edge') or midpoint ('mid'). INV = block
//           low (bear: block high) -/+ invBufferTicks*tickSize ONLY when tickSize
//           is known. Broken when a bar CLOSES beyond INV (a wick does not).
//  State    formed (on the confirming bar) -> untouched -> retested -> broken.
//           A retest bar overlaps the zone and closes beyond it on the trend side;
//           touchCount counts separate excursions (consecutive retest bars = one).
//  Levels   (snapshot at confirmation) candidates strictly beyond Z and the close,
//           never closed through since they were set: confirmed swing highs/lows
//           (last liqLookbackBars bars), equal highs/lows (>=2 swings within
//           eqTolPct), prior-day high/low (only if in meta), session high/low,
//           session open. level1/level2 = nearest two. ladderOpposite = up to
//           ladderMax levels on the other side of INV. Missing => null + reason.
//  Room:Risk |level2 - Z| / |Z - INV|; null if level2 is null or the divisor is 0.
//           lowRoom only when rr is a number < rrFloor.
//  VWAP     cumulative session VWAP (typical price) at confirmation; null if any
//           session bar so far lacks volume (null/NaN/<=0; none is treated as 0).
//  Same-session zones are all kept; "current" = latest non-broken zone per side.

import { swingPoints } from './technicalAnalysis.js';
import { istDate, istInstant } from './marketTime.js';
import { mk } from './chartPatterns.js';

export const OB_PARAMS_VERSION = 1;
export const DEFAULT_OB_PARAMS = Object.freeze({
  paramsVersion: OB_PARAMS_VERSION,
  barSec: 300,
  swingWing: 2,
  atrLen: 14,
  bodyLen: 20,
  dispMult: 1.2,
  obLookback: 10,
  zMode: 'edge', // 'edge' | 'mid'
  invBufferTicks: 1,
  eqTolPct: 0.05,
  rrFloor: 1.5,
  openingRangeMin: 15,
  liqLookbackBars: 300,
  ladderMax: 3,
});

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const hasVol = (v) => isNum(v) && v > 0; // the provider reports a missing volume as 0, so 0 is "unknown", not a count

export function closedBars(bars, nowSec, barSec = DEFAULT_OB_PARAMS.barSec) {
  if (!bars) return [];
  if (nowSec == null) return bars;
  let n = bars.length;
  while (n > 0 && bars[n - 1].time + barSec > nowSec) n--;
  return n === bars.length ? bars : bars.slice(0, n);
}

// Session context derived from the bars alone (generic for any instrument).
// prevDayHigh/Low come from the nearest earlier IST date, only when that
// session is complete in the data (09:15 bar through the 15:25 bar), else null.
export function deriveSessionMeta(bars, { nowSec = null, tickSize = null, date = null, barSec = DEFAULT_OB_PARAMS.barSec } = {}) {
  const closed = closedBars(bars, nowSec, barSec);
  const base = { sessionStart: null, sessionEnd: null, tickSize: isNum(tickSize) && tickSize > 0 ? tickSize : null, prevDayHigh: null, prevDayLow: null, nowSec };
  if (!closed.length) return base;
  const day = date || istDate(closed[closed.length - 1].time);
  const sessionStart = istInstant(day, 9, 15);
  const sessionEnd = istInstant(day, 15, 30);
  let prevDate = null;
  for (const b of closed) {
    if (b.time >= sessionStart) break;
    prevDate = istDate(b.time);
  }
  let prevDayHigh = null, prevDayLow = null;
  if (prevDate) {
    const pb = closed.filter((b) => istDate(b.time) === prevDate);
    const open = istInstant(prevDate, 9, 15), close = istInstant(prevDate, 15, 30);
    if (pb.length && pb[0].time < open + barSec && pb[pb.length - 1].time >= close - barSec) {
      prevDayHigh = Math.max(...pb.map((b) => b.high));
      prevDayLow = Math.min(...pb.map((b) => b.low));
    }
  }
  return { ...base, sessionStart, sessionEnd, prevDayHigh, prevDayLow };
}

const PRIORITY = { prevDay: 4, equal: 3, swing: 2, session: 1, open: 0 };

export function detectOrderBlocks(bars5m, meta, params = DEFAULT_OB_PARAMS) {
  const P = { ...DEFAULT_OB_PARAMS, ...(params || {}) };
  const m = meta || {};
  const b = closedBars(bars5m, m.nowSec, P.barSec);
  const n = b.length;
  if (!n || m.sessionStart == null) return [];
  const sessionEnd = m.sessionEnd ?? Infinity;
  const sIdx = b.findIndex((x) => x.time >= m.sessionStart && x.time < sessionEnd);
  if (sIdx < 0) return [];
  let eIdx = n - 1;
  while (eIdx > sIdx && b[eIdx].time >= sessionEnd) eIdx--;
  const tick = isNum(m.tickSize) && m.tickSize > 0 ? m.tickSize : null;
  const wing = P.swingWing;

  const sw = swingPoints(b, wing);
  const highs = sw.highs.map((s) => ({ ...s, confirmIdx: s.index + wing }));
  const lows = sw.lows.map((s) => ({ ...s, confirmIdx: s.index + wing }));

  // prefix sums for the trailing ATR / body means
  const trSum = [0], bodySum = [0];
  for (let j = 0; j < n; j++) {
    const tr = j === 0 ? b[j].high - b[j].low : Math.max(b[j].high - b[j].low, Math.abs(b[j].high - b[j - 1].close), Math.abs(b[j].low - b[j - 1].close));
    trSum.push(trSum[j] + tr);
    bodySum.push(bodySum[j] + Math.abs(b[j].close - b[j].open));
  }
  const atrAt = (j) => (j >= P.atrLen + 1 ? (trSum[j] - trSum[j - P.atrLen]) / P.atrLen : null);
  const bodyAt = (j) => (j >= P.bodyLen ? (bodySum[j] - bodySum[j - P.bodyLen]) / P.bodyLen : null);

  const orEnd = m.sessionStart + P.openingRangeMin * 60;

  // BOS at bar j for `side` (+1 bull / -1 bear). Uses only bars <= j.
  const bosAt = (j, side) => {
    const pool = side > 0 ? highs : lows;
    let sw0 = null;
    for (let q = pool.length - 1; q >= 0; q--) {
      if (pool[q].confirmIdx <= j - 1 && pool[q].index >= sIdx) { sw0 = pool[q]; break; }
    }
    let level, origin, source;
    if (sw0) { level = sw0.price; origin = sw0.index + 1; source = 'swing'; }
    else {
      if (b[j].time < orEnd) return null;
      let v = null;
      for (let q = sIdx; q <= j && b[q].time < orEnd; q++) v = v == null ? (side > 0 ? b[q].high : b[q].low) : (side > 0 ? Math.max(v, b[q].high) : Math.min(v, b[q].low));
      if (v == null) return null;
      level = v; origin = sIdx; source = 'openingRange';
    }
    for (let q = origin; q < j; q++) if (side > 0 ? b[q].close > level : b[q].close < level) return null; // level already taken out
    if (!(side > 0 ? b[j].close > level : b[j].close < level)) return null;
    return { level, source };
  };

  const zones = [];
  const seen = new Set();
  let sessHigh = -Infinity, sessLow = Infinity, pv = 0, vv = 0, volMissing = 0;
  const sessOpen = b[sIdx].open;

  // liquidity candidates beyond z on the move side (+1 up / -1 down), as of bar ci
  const levelsAt = (side, edge, ci, sh, sl) => {
    const c = b[ci].close;
    const lo = ci - P.liqLookbackBars;
    const beyond = (p) => (side > 0 ? p > edge && p > c : p < edge && p < c);
    const untested = (p, from) => { for (let q = from + 1; q <= ci; q++) if (side > 0 ? b[q].close > p : b[q].close < p) return false; return true; };
    const out = [];
    const pool = (side > 0 ? highs : lows).filter((s) => s.confirmIdx <= ci && s.index >= lo);
    for (const s of pool) if (beyond(s.price) && untested(s.price, s.index)) out.push({ price: s.price, kind: 'swing' });
    // equal highs/lows: chained swings within eqTolPct
    const sorted = [...pool].sort((x, y) => x.price - y.price);
    let cl = [];
    const flush = () => {
      if (cl.length >= 2) {
        const pr = side > 0 ? Math.max(...cl.map((s) => s.price)) : Math.min(...cl.map((s) => s.price));
        if (beyond(pr) && untested(pr, Math.max(...cl.map((s) => s.index)))) out.push({ price: pr, kind: 'equal' });
      }
      cl = [];
    };
    for (const s of sorted) {
      if (cl.length && Math.abs(s.price - cl[cl.length - 1].price) / cl[cl.length - 1].price * 100 > P.eqTolPct) flush();
      cl.push(s);
    }
    flush();
    const pd = side > 0 ? m.prevDayHigh : m.prevDayLow;
    if (isNum(pd) && beyond(pd) && untested(pd, sIdx - 1)) out.push({ price: pd, kind: 'prevDay' });
    const ss = side > 0 ? sh : sl;
    if (beyond(ss) && untested(ss, sIdx - 1)) out.push({ price: ss, kind: 'session' });
    if (beyond(sessOpen) && untested(sessOpen, sIdx - 1)) out.push({ price: sessOpen, kind: 'open' });
    // merge levels within eqTolPct (one level); keep the higher-priority kind
    out.sort((x, y) => (side > 0 ? x.price - y.price : y.price - x.price));
    const merged = [];
    for (const l of out) {
      const prev = merged[merged.length - 1];
      if (prev && Math.abs(l.price - prev.price) / prev.price * 100 <= P.eqTolPct) { if (PRIORITY[l.kind] > PRIORITY[prev.kind]) merged[merged.length - 1] = l; }
      else merged.push(l);
    }
    return merged;
  };

  const tryZone = (j, ci, side, viaGap, sh, sl) => {
    const bos = bosAt(j, side);
    if (!bos) return;
    const atr = atrAt(j), body = bodyAt(j);
    if (atr == null || body == null) return; // insufficient history: no detection
    let disp;
    if (viaGap) disp = side > 0 ? b[j + 1].low > b[j - 1].high : b[j + 1].high < b[j - 1].low;
    else disp = (b[j].high - b[j].low) >= P.dispMult * atr || (side > 0 ? b[j].close - bos.level : bos.level - b[j].close) >= body;
    if (!disp) return;
    // leg origin = extreme bar of the last obLookback bars up to j
    const lb = Math.max(0, j - P.obLookback);
    let leg = j;
    for (let q = j; q >= lb; q--) if (side > 0 ? b[q].low < b[leg].low : b[q].high > b[leg].high) leg = q;
    const prevSw = (side > 0 ? lows : highs).filter((s) => s.index < leg && s.confirmIdx <= j).pop();
    const bound = Math.max(lb, prevSw ? prevSw.index : 0, sIdx);
    let k = -1;
    for (let q = leg; q >= bound; q--) if (side > 0 ? b[q].close < b[q].open : b[q].close > b[q].open) { k = q; break; }
    if (k < 0) return;
    const key = `${side}|${k}`;
    if (seen.has(key)) return;
    seen.add(key);

    const zoneLow = b[k].low, zoneHigh = b[k].high;
    const z = P.zMode === 'mid' ? (zoneLow + zoneHigh) / 2 : (side > 0 ? zoneHigh : zoneLow);
    const buf = tick != null ? P.invBufferTicks * tick : 0;
    const inv = side > 0 ? zoneLow - buf : zoneHigh + buf;
    const reasons = [];
    if (tick == null) reasons.push('tick size unknown: no invalidation buffer applied');
    const up = levelsAt(side, z, ci, sh, sl);
    const level1 = up[0] ? up[0].price : null;
    const level2 = up[1] ? up[1].price : null;
    if (up.length === 0) reasons.push(`no untested liquidity level ${side > 0 ? 'above' : 'below'} the zone in range`);
    else if (up.length === 1) reasons.push('only 1 liquidity level in range');
    if (!isNum(side > 0 ? m.prevDayHigh : m.prevDayLow)) reasons.push('prior-day high/low unavailable');
    const down = levelsAt(-side, inv, ci, sh, sl);
    const risk = Math.abs(z - inv);
    let rr = null;
    if (level2 == null) reasons.push('Room:Risk unavailable: level 2 missing');
    else if (!(risk > 0)) reasons.push('Room:Risk unavailable: zero risk distance');
    else rr = Math.abs(level2 - z) / risk;
    let vwapSide = null, vwap = null;
    if (volMissing > 0) reasons.push(`VWAP unavailable: volume missing on ${volMissing} session bar(s)`);
    else if (vv > 0) {
      const vw = pv / vv;
      vwap = vw;
      if (b[ci].close > vw) vwapSide = 'above'; else if (b[ci].close < vw) vwapSide = 'below';
      else reasons.push('close equals VWAP');
    }
    zones.push({
      id: `ob-${side > 0 ? 'bull' : 'bear'}-${b[k].time}`,
      side: side > 0 ? 'bull' : 'bear',
      formedAt: b[j].time, confirmedAt: b[ci].time, time: b[j].time,
      startIndex: k, endIndex: ci, bosIndex: j, confirmIndex: ci,
      zoneLow, zoneHigh, z, inv,
      level1, level2, level1Kind: up[0]?.kind ?? null, level2Kind: up[1]?.kind ?? null,
      ladderOpposite: down.slice(0, P.ladderMax).map((l) => l.price),
      rr, lowRoom: isNum(rr) && rr < P.rrFloor,
      state: 'formed', touchCount: 0, firstRetestTime: null, retestTimes: [], brokenAt: null,
      vwap, vwapSide, bosLevelSource: bos.source, paramsVersion: P.paramsVersion, reasons,
      _prevRetest: false, _brokenIdx: null,
    });
  };

  for (let i = sIdx; i <= eIdx; i++) {
    const bar = b[i];
    // 1) advance zones confirmed on earlier bars
    for (const zn of zones) {
      if (zn.brokenAt != null || zn.confirmIndex >= i) continue;
      const bull = zn.side === 'bull';
      if (bull ? bar.close < zn.inv : bar.close > zn.inv) { zn.brokenAt = bar.time; zn._brokenIdx = i; continue; }
      const overlap = bar.low <= zn.zoneHigh && bar.high >= zn.zoneLow;
      const retest = overlap && (bull ? bar.close > zn.zoneHigh : bar.close < zn.zoneLow);
      if (retest && !zn._prevRetest) {
        zn.touchCount++;
        zn.retestTimes.push(bar.time);
        if (zn.firstRetestTime == null) zn.firstRetestTime = bar.time;
      }
      zn._prevRetest = retest;
    }
    // 2) session running stats through bar i
    sessHigh = Math.max(sessHigh, bar.high); sessLow = Math.min(sessLow, bar.low);
    if (hasVol(bar.volume)) { const tp = (bar.high + bar.low + bar.close) / 3; pv += tp * bar.volume; vv += bar.volume; } else volMissing++;
    // 3) new zones: BOS on this bar (range / body displacement), and last bar's BOS confirmed by a gap
    for (const side of [1, -1]) {
      if (i - 1 >= sIdx) tryZone(i - 1, i, side, true, sessHigh, sessLow);
      tryZone(i, i, side, false, sessHigh, sessLow);
    }
  }

  return zones.map((zn) => {
    const { _prevRetest, _brokenIdx, ...pub } = zn;
    const last = eIdx;
    const state = pub.brokenAt != null ? 'broken' : pub.touchCount > 0 ? 'retested' : pub.confirmIndex === last ? 'formed' : 'untouched';
    return { ...pub, state, endIndex: _brokenIdx ?? last };
  }).sort((x, y) => x.confirmIndex - y.confirmIndex || x.startIndex - y.startIndex);
}

// Latest non-broken zone on each side.
export function currentZones(zones) {
  const cur = {};
  for (const zn of zones || []) if (zn.state !== 'broken') cur[zn.side] = zn;
  return cur;
}

// --- events (registry integration) -----------------------------------------
export const OB_EVENT_NAMES = ['Bullish Order Block', 'Bearish Order Block', 'Order Block Retest', 'Order Block Broken'];

const f2 = (v) => v.toFixed(2);
function evt(name, time, tone, text, zn, barIndex, extra) {
  return {
    ...mk(name, time, tone, 0, null, { barIndex, startIndex: zn.startIndex, endIndex: barIndex, price: zn.z, rangeLow: zn.zoneLow, rangeHigh: zn.zoneHigh }),
    text, confidence: null, // fit quality is not defined for this structure: never a made-up tier
    zoneId: zn.id, side: zn.side, ...extra,
  };
}

// All events implied by a zone list, oldest first. `bars` is the same array the
// zones were detected on (indexes refer to it).
export function zoneEvents(zones, bars) {
  const idxOf = new Map();
  bars.forEach((x, i) => idxOf.set(x.time, i));
  const out = [];
  for (const zn of zones) {
    const bull = zn.side === 'bull';
    const range = `${f2(zn.zoneLow)}-${f2(zn.zoneHigh)}`;
    out.push(evt(bull ? 'Bullish Order Block' : 'Bearish Order Block', zn.time, bull ? 'pos' : 'neg',
      `${bull ? 'Bullish' : 'Bearish'} Order Block - zone ${range}, invalidation ${f2(zn.inv)}`, zn, zn.bosIndex, { confirmedAt: zn.confirmedAt }));
    zn.retestTimes.forEach((t, q) => out.push(evt('Order Block Retest', t, bull ? 'pos' : 'neg',
      `Order Block Retest - ${bull ? 'bullish' : 'bearish'} zone ${range}, touch ${q + 1}`, zn, idxOf.get(t), { confirmedAt: t })));
    if (zn.brokenAt != null) out.push(evt('Order Block Broken', zn.brokenAt, 'neutral',
      `Order Block Broken - ${bull ? 'bullish' : 'bearish'} zone ${range} closed beyond invalidation ${f2(zn.inv)}`, zn, idxOf.get(zn.brokenAt), { confirmedAt: zn.brokenAt }));
  }
  return out.sort((x, y) => x.time - y.time);
}

// Registry detector: events that fire on the LAST closed bar (the same contract
// as the other intraday detectors; replay stitches the timeline bar by bar).
export function detectOrderBlockEvents(bars, meta) {
  const m = meta || {};
  const b = closedBars(bars, m.nowSec);
  if (!b.length) return [];
  const sm = m.sessionStart != null ? m : { ...deriveSessionMeta(b, { tickSize: m.tickSize }), nowSec: m.nowSec };
  const zones = detectOrderBlocks(b, sm, m.params);
  const lastT = b[b.length - 1].time;
  return zoneEvents(zones, b).filter((e) => e.confirmedAt === lastT);
}
