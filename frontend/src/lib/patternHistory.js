// Glue between the EXISTING detectors (patternRegistry.runDetectors) and outcome tracking. No new detector lives here:
// patterns are detected by the same functions the chart already uses, then turned into deduplicated OCCURRENCES whose
// realised outcomes are measured by patternOutcomes.js.
//
// Detection is bar-by-bar on prefixes (each detector only ever sees bars up to the bar being evaluated), so a historical
// occurrence is exactly what the live detector would have reported at that moment.

import { runDetectors } from './patternRegistry.js';
import { collapseRuns } from './patternCatalog.js';
import { classifyEvent } from './patternClassification.js';
import { istDate, istInstant } from './marketTime.js';
import { completedDaily, completedWeekly } from './htfEvents.js';
import {
  OUTCOME, baseRate, closedBars, evaluateOccurrence, mergeConfig, summarizeHorizon,
} from './patternOutcomes.js';

const LISTING_KNOWN_BELOW = 1200;       // same rule as htfEvents.js: fewer daily bars than this means the data starts at the listing
const MIN_DAILY_BARS = 25;              // smallest minBars of any daily detector (registry); avoids hopeless prefixes

const sessionClose = (bar) => istInstant(istDate(bar.time), 15, 30);

// Detections over the WHOLE available daily and weekly history. Returns events tagged with their own timeframe, the index of
// the confirming bar in that timeframe's series (srcIndex) and a confirmation time = that session's/week's close.
export function fullHistoryEvents({ dailyBars, weeklyBars, nowSec = Date.now() / 1000 }) {
  const out = { daily: { series: [], events: [] }, weekly: { series: [], events: [] } };
  if (dailyBars && dailyBars.length) {
    const daily = completedDaily(dailyBars, nowSec);
    const meta = { listingKnown: dailyBars.length < LISTING_KNOWN_BELOW };
    out.daily.series = daily;
    for (let i = MIN_DAILY_BARS - 1; i < daily.length; i++) {
      const window = daily.slice(0, i + 1);
      for (const ev of runDetectors('daily', window, meta)) {
        const formBar = window[Math.min(ev.endIndex ?? i, i)];
        out.daily.events.push({ ...ev, timeframe: 'daily', srcIndex: i, barIndex: i, formedAt: sessionClose(formBar), confirmedAt: sessionClose(window[i]) });
      }
    }
  }
  if (weeklyBars && weeklyBars.length) {
    const weekly = completedWeekly(weeklyBars, nowSec);
    out.weekly.series = weekly;
    for (let j = 0; j < weekly.length; j++) {
      const window = weekly.slice(0, j + 1);
      for (const ev of runDetectors('weekly', window)) {
        const weekClose = (b) => istInstant(istDate(b.time), 15, 30) + 4 * 86400;      // Friday 15:30 IST
        out.weekly.events.push({ ...ev, timeframe: 'weekly', srcIndex: j, barIndex: j, formedAt: weekClose(window[Math.min(ev.endIndex ?? j, j)]), confirmedAt: weekClose(window[j]) });
      }
    }
  }
  return out;
}

// ONE event -> classification + realised outcomes. Shared by the occurrence statistics and the feed rows.
// A confirming intraday bar that has not closed yet is PENDING (its close is not final), never "missing".
export function evaluateEvent(e, { timeframe, series, config, nowSec = Date.now() / 1000 }) {
  const cfg = mergeConfig(config);
  const occ = { confirmedAt: e.confirmedAt, srcIndex: e.srcIndex, rangeLow: e.rangeLow, rangeHigh: e.rangeHigh };
  const ev = evaluateOccurrence(series, occ, timeframe, cfg, nowSec);
  if (ev.refIndex < 0 && timeframe === 'intraday' && e.confirmedAt + cfg.barSeconds.intraday > nowSec) {
    const pend = {};
    for (const h of cfg.horizons[timeframe]) pend[h] = { state: OUTCOME.PENDING, reason: 'reference bar has not closed yet', ret: null, band: null, bandBasis: null, targetTime: null };
    return { classification: classifyEvent(e), ...ev, outcomes: pend };
  }
  return { classification: classifyEvent(e), ...ev };
}

// Events -> occurrences. Each FORMATION (run of consecutive re-firings) becomes ONE occurrence, represented by its FIRST event
// so the reference time is the original detection; later re-firings never add occurrences or move the reference.
export function toOccurrences(events, { symbol, timeframe, series, config, nowSec = Date.now() / 1000 }) {
  const firsts = collapseRuns((events || []).filter((e) => e.timeframe === timeframe && e.kind === 'pattern'), 2, 'first');
  return firsts.map((e) => ({
    id: `${symbol}|${timeframe}|${e.patternType}|${e.confirmedAt}`,
    symbol, patternType: e.patternType, pattern: e.pattern, timeframe, text: e.text,
    formedAt: e.formedAt, confirmedAt: e.confirmedAt, srcIndex: e.srcIndex,
    rangeLow: e.rangeLow, rangeHigh: e.rangeHigh, detectionPrice: e.price ?? null,
    ...evaluateEvent(e, { timeframe, series, config, nowSec }),
  })).sort((x, y) => x.confirmedAt - y.confirmedAt);
}

// Statistics for one pattern on one timeframe: per horizon, with the unconditional base rate beside it. `series` is the same
// array the occurrences were evaluated on (closed bars only).
export function statsForPattern(occurrences, { patternId, timeframe, series, config, nowSec = Date.now() / 1000, withBase = true }) {
  const cfg = mergeConfig(config);
  const mine = occurrences.filter((o) => o.patternType === patternId && o.timeframe === timeframe);
  return {
    patternId, timeframe, occurrences: mine,
    sample: { bars: series.length, from: series.length ? series[0].time : null, to: series.length ? series[series.length - 1].time : null },
    horizons: cfg.horizons[timeframe].map((h) => ({
      ...summarizeHorizon(mine, h, cfg),
      base: withBase ? baseRate(series, timeframe, h, cfg, nowSec) : null,
    })),
    config: { k: cfg.flat.k, volLookback: cfg.flat.volLookback, floor: cfg.flat.floor[timeframe], minIndependent: cfg.minIndependent },
  };
}

// Intraday series used for outcome evaluation: closed bars only.
export const intradaySeries = (bars, config, nowSec = Date.now() / 1000) => closedBars(bars, mergeConfig(config).barSeconds.intraday, nowSec);
