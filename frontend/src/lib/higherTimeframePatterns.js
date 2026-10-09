// Daily / weekly chart-pattern detectors.
//
// These structures are defined in trading days / weeks (a "flat base" is
// 5+ WEEKS, a "cup" 7-65 weeks, "three weeks tight" is three WEEKLY closes),
// so they are run on daily or weekly OHLCV - never on 5-minute bars relabelled
// as "days". Each detector takes a bar array (ascending, same shape as the
// intraday candles) and evaluates it AS OF ITS LAST BAR, exactly like the
// intraday detectors, so the same bar-by-bar replay works for all timeframes.
// Rules are explicit below and company-agnostic (no per-ticker logic).
// Anything that cannot be read from OHLCV alone returns no event - never a
// guessed one.

import { swingPoints } from './technicalAnalysis.js';
import { mk, locOf, linRegSlope } from './chartPatterns.js';

const sma = (bars, n, end = bars.length - 1) => {
  if (end + 1 < n) return null;
  let sum = 0;
  for (let i = end - n + 1; i <= end; i++) sum += bars[i].close;
  return sum / n;
};
const maxHigh = (bars, a, b) => Math.max(...bars.slice(a, b + 1).map((c) => c.high));
const minLow = (bars, a, b) => Math.min(...bars.slice(a, b + 1).map((c) => c.low));
const avgVol = (bars, a, b) => {
  const v = bars.slice(a, b + 1).map((c) => c.volume || 0);
  return v.length ? v.reduce((x, y) => x + y, 0) / v.length : 0;
};
const P = (x) => `${(x * 100).toFixed(1)}%`;

// --- Flat Base (daily) -----------------------------------------------------
// >= 25 days (5 weeks) of trading within a <= 15% high-to-low range, price
// still in the top 5% of that range, after a >= 20% advance in the 50 days
// before the base began.
export function flatBaseDaily(bars) {
  const n = bars.length;
  for (const len of [65, 45, 35, 25]) {
    if (n < len + 50) continue;
    const s = n - len;
    const hi = maxHigh(bars, s, n - 1);
    const lo = minLow(bars, s, n - 1);
    const depth = (hi - lo) / hi;
    const prior = bars[s - 1].close / bars[s - 50].close - 1;
    if (depth <= 0.15 && prior >= 0.2 && bars[n - 1].close >= hi * 0.95) {
      return [mk('Flat Base', bars[n - 1].time, 'neutral', 0.7, `${P(depth)} deep over ${len} days after a ${P(prior)} advance`, locOf(bars, s, n - 1, n - 1, bars[n - 1].close))];
    }
  }
  return [];
}

// --- Cup geometry shared by Cup & Handle / Cup Base ---------------------------
// Left rim = highest swing high 30-250 days before the right rim; rims within
// 10% of each other; depth 12-35%; the low sits in the middle 50% of the cup
// (U-shaped: >=40% of closes in the lowest third of the depth, not a V or a one-sided slide); nothing in the cup pokes >3%
// above the left rim.
function cupGeometry(bars, highs, right) {
  const cands = highs.filter((h) => h.index <= right.index - 30 && h.index >= right.index - 250);
  if (!cands.length) return null;
  const left = cands.reduce((m, h) => (h.price > m.price ? h : m));
  if (Math.abs(left.price - right.price) / left.price > 0.1) return null;
  const seg = bars.slice(left.index, right.index + 1);
  if (Math.max(...seg.map((c) => c.high)) > left.price * 1.03) return null;
  const low = Math.min(...seg.map((c) => c.low));
  const lowIdx = left.index + seg.findIndex((c) => c.low === low);
  const depth = (left.price - low) / left.price;
  if (depth < 0.12 || depth > 0.35) return null;
  const frac = (lowIdx - left.index) / (right.index - left.index);
  if (frac < 0.25 || frac > 0.75) return null;
  // Rounded, not a V: at least 40% of the cup's closes sit in the lowest third
  // of its depth (a straight-sided V only spends ~33% there, a U ~55%).
  const floor = low + (left.price - low) / 3;
  const roundShare = seg.filter((c) => c.close <= floor).length / seg.length;
  if (roundShare < 0.4) return null;
  return { left, right, low, lowIdx, depth };
}

// --- Cup & Handle (daily) ----------------------------------------------------
// Valid cup, then a 5-25 day handle after the right rim that pulls back 1% to
// min(15%, half the cup depth).
export function cupAndHandleDaily(bars) {
  const n = bars.length;
  if (n < 80) return [];
  const { highs } = swingPoints(bars, 3);
  for (const right of highs.slice(-4).reverse()) {
    const handleLen = n - 1 - right.index;
    if (handleLen < 5 || handleLen > 25) continue;
    const cup = cupGeometry(bars, highs, right);
    if (!cup) continue;
    const handleLow = minLow(bars, right.index, n - 1);
    const handleDepth = (right.price - handleLow) / right.price;
    if (handleDepth < 0.01 || handleDepth > Math.min(0.15, cup.depth / 2)) continue;
    if (maxHigh(bars, right.index + 1, n - 1) > right.price * 1.02) continue; // already broke out
    return [mk('Cup & Handle', bars[n - 1].time, 'pos', 0.7, `${P(cup.depth)} cup over ${right.index - cup.left.index} days, ${P(handleDepth)} handle over ${handleLen} days`, locOf(bars, cup.left.index, n - 1, n - 1, bars[n - 1].close))];
  }
  return [];
}

// --- Cup Base (daily) ----------------------------------------------------------
// Valid cup whose right rim is the highest high of the last 8 days, with no
// handle yet (no pullback beyond 3% from that rim) and price within 8% of
// the left rim.
export function cupBaseDaily(bars) {
  const n = bars.length;
  if (n < 80) return [];
  const { highs } = swingPoints(bars, 3);
  let ri = n - 1;
  for (let i = n - 8; i < n; i++) if (bars[i].high > bars[ri].high) ri = i;
  const right = { index: ri, price: bars[ri].high };
  const cup = cupGeometry(bars, highs, right);
  if (!cup) return [];
  const pullback = (right.price - minLow(bars, ri, n - 1)) / right.price;
  if (pullback > 0.03) return [];
  if (bars[n - 1].close < cup.left.price * 0.92) return [];
  return [mk('Cup Base', bars[n - 1].time, 'pos', 0.6, `${P(cup.depth)} cup over ${ri - cup.left.index} days, no handle yet`, locOf(bars, cup.left.index, n - 1, n - 1, bars[n - 1].close))];
}

// --- Rounding bottom / top / saucer (daily) --------------------------------
// Least-squares parabola through the closes of the last `len` days. Bottom:
// opens upward, vertex in the middle 40%, R^2 >= 0.75, >= 8% sag, and the
// right end has recovered to within 10% of the left level. Top is the mirror.
function parabolaFit(closes) {
  const m = closes.length;
  const xs = closes.map((_, i) => i / (m - 1));
  let s0 = m, s1 = 0, s2 = 0, s3 = 0, s4 = 0, t0 = 0, t1 = 0, t2 = 0;
  xs.forEach((x, i) => {
    const y = closes[i];
    s1 += x; s2 += x * x; s3 += x ** 3; s4 += x ** 4;
    t0 += y; t1 += x * y; t2 += x * x * y;
  });
  // Solve [s4 s3 s2; s3 s2 s1; s2 s1 s0][a b c]^T = [t2 t1 t0]^T (Cramer's rule)
  const det = (a, b, c, d, e, f, g, h, i) => a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
  const D = det(s4, s3, s2, s3, s2, s1, s2, s1, s0);
  if (Math.abs(D) < 1e-12) return null;
  const a = det(t2, s3, s2, t1, s2, s1, t0, s1, s0) / D;
  const b = det(s4, t2, s2, s3, t1, s1, s2, t0, s0) / D;
  const c = det(s4, s3, t2, s3, s2, t1, s2, s1, t0) / D;
  const mean = t0 / m;
  let ssRes = 0, ssTot = 0;
  xs.forEach((x, i) => {
    const fit = a * x * x + b * x + c;
    ssRes += (closes[i] - fit) ** 2;
    ssTot += (closes[i] - mean) ** 2;
  });
  const r2 = ssTot === 0 ? 0 : 1 - ssRes / ssTot;
  return { a, b, c, r2, vertex: a === 0 ? null : -b / (2 * a), fitAt: (x) => a * x * x + b * x + c };
}

function roundingCore(bars, kind) {
  const n = bars.length;
  const bottom = kind === 'bottom';
  const lens = [120, 90, 60, 40];
  for (const len of lens) {
    if (n < len) continue;
    const seg = bars.slice(n - len);
    const closes = seg.map((c) => c.close);
    const fit = parabolaFit(closes);
    if (!fit || fit.r2 < 0.75) continue;
    if (bottom ? fit.a <= 0 : fit.a >= 0) continue;
    if (fit.vertex < 0.3 || fit.vertex > 0.7) continue;
    const leftLevel = closes.slice(0, 5).reduce((x, y) => x + y, 0) / 5;
    const extreme = fit.fitAt(fit.vertex);
    const depth = bottom ? (leftLevel - extreme) / leftLevel : (extreme - leftLevel) / extreme;
    if (depth < 0.08) continue;
    const last = closes[len - 1];
    const recovered = bottom ? last >= leftLevel * 0.9 : last <= leftLevel * 1.1;
    if (!recovered) continue;
    return { len, depth, r2: fit.r2, start: n - len };
  }
  return null;
}

export function roundingBottomDaily(bars) {
  const r = roundingCore(bars, 'bottom');
  if (!r) return [];
  const n = bars.length;
  return [mk('Rounding Bottom', bars[n - 1].time, 'pos', Math.min(1, r.r2), `${P(r.depth)} sag over ${r.len} days, curve fit R2 ${r.r2.toFixed(2)}`, locOf(bars, r.start, n - 1, n - 1, bars[n - 1].close))];
}

export function roundingTopDaily(bars) {
  const r = roundingCore(bars, 'top');
  if (!r) return [];
  const n = bars.length;
  return [mk('Rounding Top', bars[n - 1].time, 'neg', Math.min(1, r.r2), `${P(r.depth)} arc over ${r.len} days, curve fit R2 ${r.r2.toFixed(2)}`, locOf(bars, r.start, n - 1, n - 1, bars[n - 1].close))];
}

// Saucer base = a rounding bottom that is long (>= 60 days / 12 weeks) and
// shallow (<= 20%).
export function saucerBaseDaily(bars) {
  const r = roundingCore(bars, 'bottom');
  if (!r || r.len < 60 || r.depth > 0.2) return [];
  const n = bars.length;
  return [mk('Saucer Base', bars[n - 1].time, 'pos', Math.min(1, r.r2), `${P(r.depth)} shallow rounded base over ${r.len} days`, locOf(bars, r.start, n - 1, n - 1, bars[n - 1].close))];
}

// --- Triple Top / Triple Bottom (daily) -------------------------------------
// Last three swing highs (lows) within 2.5% of each other, >= 5 days apart,
// spanning <= 120 days, separated by >= 3% reactions, third one formed in the
// last 8 days.
function triple(bars, kind) {
  const n = bars.length;
  const top = kind === 'top';
  const { highs, lows } = swingPoints(bars, 3);
  const pts = (top ? highs : lows).slice(-3);
  if (pts.length < 3) return null;
  const [p1, p2, p3] = pts;
  if (p2.index - p1.index < 5 || p3.index - p2.index < 5 || p3.index - p1.index > 120) return null;
  if (p3.index < n - 9) return null;
  const prices = pts.map((p) => p.price);
  if ((Math.max(...prices) - Math.min(...prices)) / Math.max(...prices) > 0.025) return null;
  const level = prices.reduce((x, y) => x + y, 0) / 3;
  const between = (a, b) => (top ? minLow(bars, a.index, b.index) : maxHigh(bars, a.index, b.index));
  const react = [between(p1, p2), between(p2, p3)].map((v) => Math.abs(level - v) / level);
  if (react.some((r) => r < 0.03)) return null;
  return { p1, p3, level };
}

export function tripleTopDaily(bars) {
  const t = triple(bars, 'top');
  if (!t) return [];
  return [mk('Triple Top', bars[t.p3.index].time, 'neg', 0.65, `three peaks near ${t.level.toFixed(2)}`, locOf(bars, t.p1.index, t.p3.index, t.p3.index, t.p3.price))];
}

export function tripleBottomDaily(bars) {
  const t = triple(bars, 'bottom');
  if (!t) return [];
  return [mk('Triple Bottom', bars[t.p3.index].time, 'pos', 0.65, `three troughs near ${t.level.toFixed(2)}`, locOf(bars, t.p1.index, t.p3.index, t.p3.index, t.p3.price))];
}

// --- Pullbacks (high -> following low), used by VCP / Ascending Base --------
function pullbacks(bars, wing, minIndex) {
  const { highs, lows } = swingPoints(bars, wing);
  const out = [];
  highs.filter((h) => h.index >= minIndex).forEach((h, i, arr) => {
    const nextHigh = arr[i + 1];
    const low = lows.find((l) => l.index > h.index && (!nextHigh || l.index < nextHigh.index));
    if (low) out.push({ high: h, low, depth: (h.price - low.price) / h.price });
  });
  return out;
}

// --- VCP (daily) ------------------------------------------------------------------
// Stage-2 uptrend (close > 50DMA > 150DMA), then >= 2 successive pullbacks
// within the last 120 days that each get shallower (first 8-40%, last <= 12%),
// volume drier in the last pullback than the first, price within 8% of the
// latest pivot high.
export function vcpDaily(bars) {
  const n = bars.length;
  if (n < 150) return [];
  const s50 = sma(bars, 50), s150 = sma(bars, 150);
  const close = bars[n - 1].close;
  if (!(close > s50 && s50 > s150)) return [];
  const pbs = pullbacks(bars, 3, n - 120).slice(-5);
  // Trailing run of strictly shrinking pullbacks (each shallower than the one before).
  const seq = [];
  for (let i = pbs.length - 1; i >= 0; i--) {
    if (!seq.length || pbs[i].depth > seq[0].depth) seq.unshift(pbs[i]);
    else break;
  }
  if (seq.length < 2) return [];
  const first = seq[0], last = seq[seq.length - 1];
  if (first.depth < 0.08 || first.depth > 0.4 || last.depth > 0.12) return [];
  if (close < last.high.price * 0.92) return [];
  const v1 = avgVol(bars, first.high.index, first.low.index);
  const v2 = avgVol(bars, last.high.index, Math.max(last.low.index, last.high.index + 1));
  if (!(v1 > 0 && v2 > 0 && v2 < v1)) return [];
  const span = n - 1 - first.high.index;
  if (span < 15 || span > 120) return [];
  const note = `${seq.length} contractions ${seq.map((x) => P(x.depth)).join(' -> ')}, volume drying up`;
  return [mk('VCP', bars[n - 1].time, 'pos', 0.7, note, locOf(bars, first.high.index, n - 1, n - 1, close))];
}

// --- High Tight Flag (daily) --------------------------------------------------------
// A >= 100% advance within <= 40 days (8 weeks), then a 5-25 day flag that
// has given back <= 25% from its high.
export function highTightFlagDaily(bars) {
  const n = bars.length;
  if (n < 50) return [];
  for (let flagLen = 5; flagLen <= 25; flagLen++) {
    const p = n - 1 - flagLen; // last bar of the pole
    if (p < 40) break;
    const lowSlice = bars.slice(p - 40, p + 1).map((c) => c.close);
    const poleLow = Math.min(...lowSlice);
    const rise = bars[p].close / poleLow - 1;
    if (rise < 1.0) continue;
    const hi = maxHigh(bars, p, n - 1);
    const lo = minLow(bars, p, n - 1);
    const depth = (hi - lo) / hi;
    if (depth > 0.25) continue;
    const poleStart = p - 40 + lowSlice.indexOf(poleLow);
    return [mk('High Tight Flag', bars[n - 1].time, 'pos', 0.7, `${P(rise)} advance then ${P(depth)} flag over ${flagLen} days`, locOf(bars, poleStart, n - 1, n - 1, bars[n - 1].close))];
  }
  return [];
}

// --- Ascending Base (daily) -----------------------------------------------------------
// Three pullbacks of 8-25% in the last 150 days, each with a higher high and a
// higher low than the one before, spanning >= 45 days, the last low within 15
// days and price recovered to within 10% of the latest high.
export function ascendingBaseDaily(bars) {
  const n = bars.length;
  if (n < 100) return [];
  const pbs = pullbacks(bars, 3, n - 150).filter((p) => p.depth >= 0.08 && p.depth <= 0.25);
  if (pbs.length < 3) return [];
  const [a, b, c] = pbs.slice(-3);
  if (!(b.low.price > a.low.price && c.low.price > b.low.price && b.high.price > a.high.price && c.high.price > b.high.price)) return [];
  if (c.low.index - a.high.index < 45 || c.low.index < n - 16) return [];
  if (bars[n - 1].close < c.high.price * 0.9) return [];
  return [mk('Ascending Base', bars[n - 1].time, 'pos', 0.6, `3 pullbacks ${[a, b, c].map((x) => P(x.depth)).join(' / ')} with rising highs and lows`, locOf(bars, a.high.index, n - 1, n - 1, bars[n - 1].close))];
}

// --- IPO Base (daily) -------------------------------------------------------------------
// Needs the real listing date: only evaluated when the loaded history starts
// at the listing (meta.listingKnown). Young issue (25-250 sessions old) with a
// 15-25 day consolidation <= 35% deep, price in the top 10% of it. Stocks whose
// history predates the loaded window are not IPO-base candidates - no event.
export function ipoBaseDaily(bars, meta = {}) {
  const n = bars.length;
  if (!meta.listingKnown || n < 25 || n > 250) return [];
  for (const len of [25, 20, 15]) {
    const hi = maxHigh(bars, n - len, n - 1);
    const lo = minLow(bars, n - len, n - 1);
    if ((hi - lo) / hi <= 0.35 && bars[n - 1].close >= hi * 0.9) {
      return [mk('IPO Base', bars[n - 1].time, 'pos', 0.5, `${P((hi - lo) / hi)} base over ${len} days, ${n} sessions after listing`, locOf(bars, n - len, n - 1, n - 1, bars[n - 1].close))];
    }
  }
  return [];
}

// --- Shakeout (daily) ----------------------------------------------------------------------
// Today's low undercuts the prior 20-day low by >= 1.5% but the day closes back
// above that support, on >= 1.5x the 20-day average volume.
export function shakeoutDaily(bars) {
  const n = bars.length;
  if (n < 25) return [];
  const c = bars[n - 1];
  const support = minLow(bars, n - 21, n - 2);
  const av = avgVol(bars, n - 21, n - 2);
  if (c.low <= support * 0.985 && c.close > support && av > 0 && (c.volume || 0) >= av * 1.5) {
    return [mk('Shakeout', c.time, 'pos', 0.55, `undercut ${support.toFixed(2)} by ${P((support - c.low) / support)} then closed back above on ${((c.volume || 0) / av).toFixed(1)}x volume`, locOf(bars, n - 21, n - 1, n - 1, c.close))];
  }
  return [];
}

// --- Pennant (daily) -------------------------------------------------------------------------
// A >= 10% pole over the 12 days before a 5-15 day consolidation whose highs
// fall and lows rise (converging), with the flag no more than half as tall as
// the pole.
export function pennantDaily(bars) {
  const n = bars.length;
  if (n < 30) return [];
  for (let len = 5; len <= 15; len++) {
    const s = n - len;
    const poleStartIdx = s - 12;
    if (poleStartIdx < 0) break;
    const pole = bars[s].close / bars[poleStartIdx].close - 1;
    if (Math.abs(pole) < 0.1) continue;
    const seg = bars.slice(s);
    const hs = linRegSlope(seg.map((c, i) => ({ index: i, price: c.high }))) / bars[n - 1].close;
    const ls = linRegSlope(seg.map((c, i) => ({ index: i, price: c.low }))) / bars[n - 1].close;
    if (!(hs < -0.0005 && ls > 0.0005)) continue;
    const flagH = (maxHigh(bars, s, n - 1) - minLow(bars, s, n - 1)) / bars[s].close;
    if (flagH > Math.abs(pole) * 0.5) continue;
    return [mk('Pennant', bars[n - 1].time, pole > 0 ? 'pos' : 'neg', 0.6, `${P(Math.abs(pole))} ${pole > 0 ? 'up' : 'down'} pole then ${len}-day converging pennant`, locOf(bars, poleStartIdx, n - 1, n - 1, bars[n - 1].close))];
  }
  return [];
}

// --- Three Weeks Tight (WEEKLY bars) --------------------------------------------------------------
// Three consecutive weekly closes within 1% of each other, in an uptrend
// (latest close at or above the close 10 weeks earlier). Expects COMPLETED
// weekly bars only.
export function threeWeeksTightWeekly(bars) {
  const n = bars.length;
  if (n < 13) return [];
  const [a, b, c] = [bars[n - 3].close, bars[n - 2].close, bars[n - 1].close];
  const spread = (Math.max(a, b, c) - Math.min(a, b, c)) / c;
  if (spread <= 0.01 && c >= bars[n - 11].close) {
    return [mk('Three Weeks Tight', bars[n - 1].time, 'pos', 0.7, `3 weekly closes within ${P(spread)}`, locOf(bars, n - 3, n - 1, n - 1, c))];
  }
  return [];
}

export const dailyDetectors = {
  flatBaseDaily, cupAndHandleDaily, cupBaseDaily, roundingBottomDaily, roundingTopDaily, saucerBaseDaily,
  tripleTopDaily, tripleBottomDaily, vcpDaily, highTightFlagDaily, ascendingBaseDaily, ipoBaseDaily,
  shakeoutDaily, pennantDaily,
};
export const weeklyDetectors = { threeWeeksTightWeekly };
