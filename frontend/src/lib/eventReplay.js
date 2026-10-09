// Reconstructs the full "What's happening" timeline for an already-closed
// trading day. analyzeCandles/detectChartPatterns only ever look at the
// LAST bar of whatever candle array they're given (that's all the live
// view needs, one poll at a time) - so replaying a full day means running
// them again at every bar as if that bar had just closed, not once over
// the whole array.
import { analyzeCandles } from './technicalAnalysis.js';
import { runDetectors } from './patternRegistry.js';
import { stampEvent } from './eventModel.js';

const MIN_CANDLES = 30;

// One canonical ordering for every event list (live feed, day replay,
// per-pattern feed): by the event's own candle `time`, never by detector,
// arrival or processing order. Events on the same candle stay together and
// break ties deterministically by kind, then text.
const KIND_RANK = ['pattern', 'breakout', 'structure', 'momentum', 'volume', 'volatility', 'candlestick'];
const rank = (k) => { const i = KIND_RANK.indexOf(k); return i < 0 ? KIND_RANK.length : i; };
const tieBreak = (a, b) => rank(a.kind) - rank(b.kind) || String(a.text).localeCompare(String(b.text));
export const sortNewestFirst = (events) => [...events].sort((a, b) => b.time - a.time || tieBreak(a, b));
export const sortOldestFirst = (events) => [...events].sort((a, b) => a.time - b.time || tieBreak(a, b)); // same floor analyzeCandles/detectChartPatterns use

// patternsOnly skips the indicator pass (used for the live rolling window,
// where only chart-pattern occurrences are needed for the selector).
//
// sessionStart: index of the first DISPLAYED bar when `candles` begins with
// prior-session warm-up bars (the detectors' calculation window). Replay
// starts at the session's first bar, only events at/after it are kept, and
// bar indexes are re-based so they index the session candles alone. Indicator
// warm-up and session start are different things: without warm-up, nothing
// can be detected until MIN_CANDLES bars (~2.5h of 5m) into the session.
export function replayDayEvents(candles, { patternsOnly = false, sessionStart = 0 } = {}) {
  if (!candles || candles.length < MIN_CANDLES) return [];
  const seen = new Set();
  const timeline = [];
  for (let i = Math.max(MIN_CANDLES, sessionStart + 1); i <= candles.length; i++) {
    const window = candles.slice(0, i);
    const found = patternsOnly
      ? runDetectors('intraday', window)
      : [...analyzeCandles(window), ...runDetectors('intraday', window)];
    const evalBar = window[window.length - 1];
    for (const raw of found) {
      const e = stampEvent(raw, evalBar);
      const key = `${e.time}|${e.text}`;
      if (seen.has(key)) continue;
      seen.add(key);
      timeline.push(e);
    }
  }
  const t0 = sessionStart > 0 ? candles[sessionStart].time : -Infinity;
  const rebase = (e) => (sessionStart > 0 && e.barIndex != null
    ? { ...e, barIndex: e.barIndex - sessionStart, startIndex: e.startIndex - sessionStart, endIndex: e.endIndex - sessionStart }
    : e);
  return sortOldestFirst(timeline.filter((e) => e.time >= t0).map(rebase));
}
