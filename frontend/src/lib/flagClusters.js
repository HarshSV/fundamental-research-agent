// Pure helpers for the outcome flags and the default one-year view. Nothing here knows about the chart library.

// ---- One-year default window ------------------------------------------------------------------------------------------
// The bars of `bars` (oldest first) inside the last `days` calendar days. If less history exists the available period is
// returned as is (never padded, never invented). `from` = index of the first returned bar in `bars`.
export function lastYearWindow(bars, nowSec = Date.now() / 1000, days = 365) {
  if (!bars || !bars.length) return { bars: [], from: 0, complete: false };
  const cutoff = nowSec - days * 86400;
  let from = bars.findIndex((b) => b.time >= cutoff);
  if (from < 0) from = bars.length - 1;
  const complete = bars[0].time <= cutoff + 7 * 86400;      // history reaches back about a year (within a week)
  return { bars: from === 0 ? bars : bars.slice(from), from, complete };
}

// Daily-pattern events (indexes into the FULL daily series) -> events on the displayed one-year bars. `srcIndex` (the
// confirming bar in the full series, used for the outcome reference) is preserved; display indexes are shifted. Events that
// confirm before the window starts are dropped from the display only (the caller still has the full list).
export function shiftEventsToWindow(events, from, windowBars) {
  const out = [];
  for (const e of events || []) {
    const barIndex = e.barIndex - from;
    if (barIndex < 0 || barIndex >= windowBars.length) continue;
    out.push({
      ...e,
      barIndex,
      startIndex: Math.max(0, (e.startIndex ?? e.barIndex) - from),
      endIndex: Math.max(0, (e.endIndex ?? e.barIndex) - from),
      time: windowBars[barIndex].time,
    });
  }
  return out;
}

// ---- Outcome -> flag placement ---------------------------------------------------------------------------------------
// Placement and colour come from the REALISED outcome only (never the pattern's bullish/bearish bias):
//   positive -> green, BELOW the candle, pointer UP        negative -> red, ABOVE the candle, pointer DOWN
//   pending  -> blue, below, up                            flat -> grey, above, down        unavailable -> muted slate, above, down
export const FLAG_STYLE = {
  positive: { fill: 'rgb(16,185,129)', above: false, text: 'rgb(255,255,255)' },
  negative: { fill: 'rgb(239,68,68)', above: true, text: 'rgb(255,255,255)' },
  pending: { fill: 'rgb(59,130,246)', above: false, text: 'rgb(255,255,255)' },
  flat: { fill: 'rgb(148,163,184)', above: true, text: 'rgb(15,23,42)' },
  not_evaluable: { fill: 'rgba(100,116,139,0.7)', above: true, text: 'rgb(241,245,249)' },
};
export const HIDDEN_BY_DEFAULT = ['flat', 'not_evaluable'];      // optional markers; the occurrences themselves are never removed

// Zoom-aware grouping in SCREEN space. `items` = [{ event, state }]. Events of the SAME outcome whose candles are closer than
// `spacingPx` on screen share one flag (anchored on the latest one); different outcomes are never merged, so a group can never
// imply a uniform result. pxPerBar = chart width / visible bars, so the grouping follows zoom, panning and timeframe.
export function clusterByScreen(items, pxPerBar, spacingPx = 22) {
  const byState = new Map();
  for (const it of items) {
    if (!byState.has(it.state)) byState.set(it.state, []);
    byState.get(it.state).push(it);
  }
  const span = pxPerBar > 0 ? spacingPx / pxPerBar : 1;       // bars covered by one flag
  const out = [];
  for (const [state, list] of byState) {
    list.sort((a, b) => a.event.barIndex - b.event.barIndex);
    let cur = null;
    for (const it of list) {
      if (cur && it.event.barIndex - cur.start < span) { cur.events.push(it.event); } else {
        cur = { state, start: it.event.barIndex, events: [it.event] };
        out.push(cur);
      }
    }
  }
  return out.map((c) => {
    const at = c.events.reduce((m, e) => (e.barIndex > m.barIndex ? e : m), c.events[0]);
    return { state: c.state, events: c.events, at, above: FLAG_STYLE[c.state].above };
  }).sort((a, b) => a.at.barIndex - b.at.barIndex);
}
