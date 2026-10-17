// Leakage-safe REALISED outcome tracking for detected chart patterns. Pure functions, no network, no state.
//
// WHAT AN OUTCOME IS
//   An occurrence is evaluated from its REFERENCE BAR = the bar at which the detector first had enough data to report it
//   (event.confirmedAt). The reference price is that bar's CLOSE. Forward candles are strictly AFTER the reference bar.
//   For horizon h (in bars of the occurrence's own timeframe):
//        forward return  r_h = close[ref + h] / close[ref] - 1                       (simple return, no dividends)
//   Classification uses a symmetric neutral band that is known AT the reference bar (never from future data):
//        band_h = max( floor_tf , k * sigma_ref * sqrt(h) )
//        sigma_ref = sample std-dev of the last `volLookback` one-bar log returns up to and including the reference bar
//                    (intraday: same-session returns only)
//        Positive : r_h >  band_h          Negative : r_h < -band_h          Flat : -band_h <= r_h <= band_h
//   k and the floors are configuration, NOT tuned on outcomes (DEFAULT_CONFIG). Boundary values count as Flat.
//
// STATES (never conflated)
//   positive | negative | flat   completed, valid observation
//   pending                      the horizon bar does not exist YET (live data can still arrive) - never Flat
//   not_evaluable                can never be evaluated reliably; EXCLUDED from statistics and reported separately:
//                                  reference_bar_missing | session_boundary (intraday horizon would cross the close)
//                                  | missing_candles (gap in the forward bars) | suspect_corporate_action
//
// LEAKAGE RULES
//   - outcome code reads only closes AT/AFTER the reference bar for the return and only bars AT/BEFORE it for sigma;
//   - nothing computed here feeds back into detection or into any feature;
//   - the occurrence's reference time is the original (first) detection and is never moved.
//
// STATISTICS count each formation once (see patternHistory.toOccurrences) and additionally report an INDEPENDENT subset in
// which occurrences whose forward windows overlap an earlier one are skipped, so overlapping windows cannot inflate results.

import { istDate, sessionComplete } from './marketTime.js';

export const OUTCOME = {
  POSITIVE: 'positive', NEGATIVE: 'negative', FLAT: 'flat', PENDING: 'pending', NOT_EVALUABLE: 'not_evaluable',
};

export const DEFAULT_CONFIG = {
  horizons: { intraday: [5, 15, 30], daily: [5, 15, 30], weekly: [5, 15, 30] }, // in bars of that timeframe
  barSeconds: { intraday: 300 },
  flat: {
    k: 0.5,                    // band = k * sigma * sqrt(h); NOT tuned on outcomes
    volLookback: 20,           // one-bar returns used for sigma
    minReturns: 10,            // fewer than this -> sigma unavailable -> floor only
    floor: { intraday: 0.001, daily: 0.005, weekly: 0.01 }, // minimum half-width of the Flat band (fraction)
  },
  maxGapDays: { daily: 7, weekly: 14 },   // larger calendar gaps between consecutive forward bars = missing candles
  suspectJump: 0.4,                        // |ln move| in one bar that looks like a clean split/bonus ratio -> not evaluable
  minIndependent: 30,                      // below this many independent evaluable occurrences the sample is flagged small
};

export const mergeConfig = (over = {}) => ({
  ...DEFAULT_CONFIG, ...over,
  horizons: { ...DEFAULT_CONFIG.horizons, ...(over.horizons || {}) },
  flat: { ...DEFAULT_CONFIG.flat, ...(over.flat || {}), floor: { ...DEFAULT_CONFIG.flat.floor, ...(over.flat?.floor || {}) } },
  maxGapDays: { ...DEFAULT_CONFIG.maxGapDays, ...(over.maxGapDays || {}) },
  barSeconds: { ...DEFAULT_CONFIG.barSeconds, ...(over.barSeconds || {}) },
});

const DAY = 86400;
// Inner functions accept a raw/undefined config as well as an already-merged one (merging is cheap but not free in loops).
const ensureCfg = (c) => (c && c.flat && c.barSeconds && c.horizons ? c : mergeConfig(c));
const SPLIT_RATIOS = [2, 3, 4, 5, 10, 20, 1.5, 2.5, 8];
const looksLikeSplit = (lnMove, cfg) => {
  if (Math.abs(lnMove) <= cfg.suspectJump) return false;
  const r = Math.exp(lnMove);
  return SPLIT_RATIOS.some((k) => Math.abs(r * k - 1) < 0.05 || Math.abs(r / k - 1) < 0.05);
};

// Intraday series must contain CLOSED bars only (the still-forming candle has no final close).
export function closedBars(bars, barSec, nowSec) {
  return (bars || []).filter((b) => b.time + barSec <= nowSec);
}

// Index of the reference bar: prefers the source-timeframe index stamped on the event, else the bar whose time equals
// confirmedAt (intraday) / whose IST date equals the confirming session (daily, weekly: the bar containing it).
export function referenceIndex(series, occ, timeframe) {
  if (Number.isInteger(occ.srcIndex) && occ.srcIndex >= 0 && occ.srcIndex < series.length) return occ.srcIndex;
  const t = occ.confirmedAt;
  if (!Number.isFinite(t)) return -1;
  if (timeframe === 'intraday') return series.findIndex((b) => b.time === t);
  if (timeframe === 'weekly') return series.findIndex((b) => t >= b.time && t < b.time + 7 * DAY);
  const d = istDate(t);
  return series.findIndex((b) => istDate(b.time) === d);
}

// Sample std-dev of one-bar log returns over the last `lookback` returns ending AT `ref` (information up to ref only).
export function sigmaAt(series, ref, timeframe, cfg) {
  const lb = cfg.flat.volLookback;
  const rets = [];
  for (let i = ref; i > 0 && rets.length < lb; i--) {
    const a = series[i - 1].close, b = series[i].close;
    if (timeframe === 'intraday' && istDate(series[i - 1].time) !== istDate(series[i].time)) break;   // no overnight returns
    if (!(a > 0 && b > 0)) continue;
    rets.push(Math.log(b / a));
  }
  if (rets.length < cfg.flat.minReturns) return null;
  const m = rets.reduce((s, x) => s + x, 0) / rets.length;
  return Math.sqrt(rets.reduce((s, x) => s + (x - m) ** 2, 0) / (rets.length - 1));
}

export function flatBand(series, ref, h, timeframe, cfg) {
  const floor = cfg.flat.floor[timeframe];
  const sigma = sigmaAt(series, ref, timeframe, cfg);
  const vol = sigma == null ? 0 : cfg.flat.k * sigma * Math.sqrt(h);
  const band = Math.max(floor, vol);
  return { band, basis: sigma == null ? 'floor (no volatility history)' : vol > floor ? 'volatility' : 'floor', sigma };
}

const classify = (r, band) => (r > band ? OUTCOME.POSITIVE : r < -band ? OUTCOME.NEGATIVE : OUTCOME.FLAT);

// Outcome of ONE horizon. Returns { state, ret, band, bandBasis, reason, targetTime }.
export function forwardOutcome(series, ref, h, timeframe, config, nowSec) {
  const cfg = ensureCfg(config);
  const na = (reason) => ({ state: OUTCOME.NOT_EVALUABLE, reason, ret: null, band: null, bandBasis: null, targetTime: null });
  if (!(ref >= 0 && ref < series.length) || !(series[ref].close > 0)) return na('reference_bar_missing');
  const target = ref + h;
  const last = Math.min(target, series.length - 1);
  const barSec = cfg.barSeconds.intraday;
  // Validate every forward bar that exists (up to the horizon): spacing, session, split-like jumps.
  for (let i = ref + 1; i <= last; i++) {
    const prev = series[i - 1], cur = series[i];
    if (timeframe === 'intraday') {
      if (istDate(cur.time) !== istDate(series[ref].time)) return na('session_boundary');
      if (cur.time - prev.time !== barSec) return na('missing_candles');
    } else if (cur.time - prev.time > cfg.maxGapDays[timeframe] * DAY) {
      return na('missing_candles');
    }
    if (prev.close > 0 && cur.close > 0 && looksLikeSplit(Math.log(cur.close / prev.close), cfg)) return na('suspect_corporate_action');
  }
  if (target > series.length - 1) {
    // Horizon bar not in the data. Intraday: still pending only while the reference session is open.
    if (timeframe === 'intraday' && sessionComplete(istDate(series[ref].time), nowSec)) return na('session_boundary');
    return { state: OUTCOME.PENDING, reason: 'horizon bar not available yet', ret: null, band: null, bandBasis: null, targetTime: null };
  }
  const ret = series[target].close / series[ref].close - 1;
  const { band, basis } = flatBand(series, ref, h, timeframe, cfg);
  return { state: classify(ret, band), ret, band, bandBasis: basis, reason: null, targetTime: series[target].time };
}

// First close beyond the pattern's own range AFTER detection: realised, observed-later information (never a bias).
//   state: 'up' | 'down' | 'none' (horizon complete, no close beyond the range) | 'pending' | 'unavailable'
export function observeBreakout(series, ref, occ, timeframe, config, nowSec) {
  const cfg = ensureCfg(config);
  const hi = occ.rangeHigh, lo = occ.rangeLow;
  if (!(ref >= 0) || !Number.isFinite(hi) || !Number.isFinite(lo)) return { state: 'unavailable' };
  const maxH = Math.max(...cfg.horizons[timeframe]);
  const barSec = cfg.barSeconds.intraday;
  let reachedEnd = true;
  for (let k = 1; k <= maxH; k++) {
    const b = series[ref + k];
    if (!b) { reachedEnd = false; break; }
    if (timeframe === 'intraday' && (istDate(b.time) !== istDate(series[ref].time) || b.time - series[ref + k - 1].time !== barSec)) { reachedEnd = false; break; }
    if (b.close > hi) return { state: 'up', barsAfter: k, time: b.time };
    if (b.close < lo) return { state: 'down', barsAfter: k, time: b.time };
  }
  if (reachedEnd) return { state: 'none' };
  const sessionOver = timeframe === 'intraday' && sessionComplete(istDate(series[ref].time), nowSec);
  return { state: sessionOver ? 'none' : 'pending' };
}

// All horizons for one occurrence.
export function evaluateOccurrence(series, occ, timeframe, config, nowSec = Date.now() / 1000) {
  const cfg = mergeConfig(config);
  const ref = referenceIndex(series, occ, timeframe);
  const outcomes = {};
  for (const h of cfg.horizons[timeframe]) outcomes[h] = forwardOutcome(series, ref, h, timeframe, cfg, nowSec);
  return { refIndex: ref, refTime: ref >= 0 ? series[ref].time : null, refPrice: ref >= 0 ? series[ref].close : null, outcomes,
    breakout: observeBreakout(series, ref, occ, timeframe, cfg, nowSec) };
}

// Greedy independent subset for horizon h: skip an occurrence whose forward window [ref, ref+h] overlaps the last kept one.
export function independentSubset(occs, h) {
  const sorted = [...occs].filter((o) => o.refIndex >= 0).sort((a, b) => a.refIndex - b.refIndex);
  const kept = [];
  let nextFree = -Infinity;
  for (const o of sorted) {
    if (o.refIndex < nextFree) continue;
    kept.push(o);
    nextFree = o.refIndex + h + 1;
  }
  return kept;
}

const median = (a) => {
  if (!a.length) return null;
  const s = [...a].sort((x, y) => x - y), m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

function tally(list, h) {
  const t = { total: list.length, pending: 0, notEvaluable: 0, positive: 0, negative: 0, flat: 0, returns: [] };
  for (const o of list) {
    const x = o.outcomes?.[h];
    if (!x) continue;
    if (x.state === OUTCOME.PENDING) t.pending++;
    else if (x.state === OUTCOME.NOT_EVALUABLE) t.notEvaluable++;
    else { t[x.state]++; t.returns.push(x.ret); }
  }
  const evaluable = t.positive + t.negative + t.flat;
  return {
    total: t.total, pending: t.pending, notEvaluable: t.notEvaluable, evaluable,
    positive: t.positive, negative: t.negative, flat: t.flat,
    // Rates / averages are null (never 0) when nothing was evaluable.
    positiveRate: evaluable ? t.positive / evaluable : null,
    meanReturn: evaluable ? t.returns.reduce((s, x) => s + x, 0) / evaluable : null,
    medianReturn: median(t.returns),
  };
}

// Statistics for ONE pattern / timeframe / horizon. `all` counts every formation once; `independent` additionally removes
// overlapping forward windows. Only completed, valid observations enter rates and averages.
export function summarizeHorizon(occs, h, config) {
  const cfg = mergeConfig(config);
  const all = tally(occs, h);
  const evaluableOccs = occs.filter((o) => o.outcomes?.[h] && ![OUTCOME.PENDING, OUTCOME.NOT_EVALUABLE].includes(o.outcomes[h].state));
  const indep = tally(independentSubset(evaluableOccs, h), h);
  return { horizon: h, all, independent: { ...indep, skippedOverlap: all.evaluable - indep.evaluable }, smallSample: indep.evaluable < cfg.minIndependent };
}

// Unconditional context: the same classification applied to EVERY bar of the series (overlapping, so a rate not a test).
// Lets a reader compare a pattern's rate with what happens after an arbitrary bar.
export function baseRate(series, timeframe, h, config, nowSec = Date.now() / 1000) {
  const cfg = mergeConfig(config);
  const c = { positive: 0, negative: 0, flat: 0 };
  const first = cfg.flat.volLookback;
  for (let i = first; i < series.length; i++) {
    const x = forwardOutcome(series, i, h, timeframe, cfg, nowSec);
    if (c[x.state] != null) c[x.state]++;
  }
  const n = c.positive + c.negative + c.flat;
  return { n, positive: c.positive, negative: c.negative, flat: c.flat, positiveRate: n ? c.positive / n : null, negativeRate: n ? c.negative / n : null };
}
