// Helpers over the shared detector events. The list of patterns itself lives
// ONLY in patternRegistry.js.

// Latest occurrence (by bar time) of a pattern type within a set of shared
// detector events. Returns null when none exists - never a fabricated hit.
export function latestOccurrence(events, type) {
  let best = null;
  for (const e of events || []) {
    if (e.kind !== 'pattern' || e.patternType !== type || e.barIndex == null) continue;
    if (!best || e.time > best.time) best = e;
  }
  return best;
}

// The detectors re-fire on every bar while a pattern's condition holds, so a
// single formation shows up as a run of consecutive events. Collapse each
// run (same patternType, bars within `gap` of each other) to its last event,
// which is the same event latestOccurrence() returns for the newest run.
export function collapseRuns(events, gap = 2) {
  const byType = new Map();
  for (const e of events || []) {
    if (e.kind !== 'pattern' || e.barIndex == null) continue;
    if (!byType.has(e.patternType)) byType.set(e.patternType, []);
    byType.get(e.patternType).push(e);
  }
  // Consecutive firings of one formation: intraday = bars within `gap`;
  // daily / weekly = completed sessions within 4 / 9 calendar days (a weekend
  // or one holiday must not split a run).
  const DAY = 86400;
  const sameRun = (e, next) => {
    if (e.timeframe === 'daily') return next.formedAt - e.formedAt <= 4 * DAY;
    if (e.timeframe === 'weekly') return next.formedAt - e.formedAt <= 9 * DAY;
    return next.barIndex - e.barIndex <= gap;
  };
  const out = [];
  for (const list of byType.values()) {
    list.sort((a, b) => a.barIndex - b.barIndex || a.time - b.time);
    list.forEach((e, i) => {
      const next = list[i + 1];
      if (!next || !sameRun(e, next)) out.push(e);
    });
  }
  return out.sort((a, b) => a.barIndex - b.barIndex);
}
