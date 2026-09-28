// Reconstructs the full "What's happening" timeline for an already-closed
// trading day. analyzeCandles/detectChartPatterns only ever look at the
// LAST bar of whatever candle array they're given (that's all the live
// view needs, one poll at a time) - so replaying a full day means running
// them again at every bar as if that bar had just closed, not once over
// the whole array.
import { analyzeCandles } from './technicalAnalysis.js';
import { detectChartPatterns } from './chartPatterns.js';

const MIN_CANDLES = 30; // same floor analyzeCandles/detectChartPatterns use

export function replayDayEvents(candles) {
  if (!candles || candles.length < MIN_CANDLES) return [];
  const seen = new Set();
  const timeline = [];
  for (let i = MIN_CANDLES; i <= candles.length; i++) {
    const window = candles.slice(0, i);
    const found = [...analyzeCandles(window), ...detectChartPatterns(window)];
    for (const e of found) {
      const key = `${e.time}|${e.text}`;
      if (seen.has(key)) continue;
      seen.add(key);
      timeline.push(e);
    }
  }
  return timeline.sort((a, b) => a.time - b.time);
}
