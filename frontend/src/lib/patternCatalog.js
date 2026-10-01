// Pattern selector taxonomy for the Live Chart. `implemented` is true only
// when chartPatterns.js has a real detector that emits events with that
// patternType; everything else is listed so a detector can be added later
// without touching the UI (flip the flag and emit the matching patternType).
import { patternType } from './chartPatterns.js';

const P = (label, implemented) => ({ label, type: patternType(label), implemented });

export const PATTERN_CATALOG = [
  P('VCP', false),
  P('Cup & Handle', true),
  P('Double Bottom', true),
  P('Double Top', true),
  P('Flat Base', true),
  P('Ascending Base', false),
  P('IPO Base', false),
  P('High Tight Flag', true),
  P('Three Weeks Tight', true),
  P('Flag', true),
  P('Pennant', false),
  P('Ascending Triangle', true),
  P('Descending Triangle', true),
  P('Symmetrical Triangle', true),
  P('Rising Wedge', true),
  P('Falling Wedge', true),
  P('Rectangle', true),
  P('Head & Shoulders', true),
  P('Inverse Head & Shoulders', true),
  P('Triple Bottom', false),
  P('Triple Top', false),
  P('Rounding Bottom', false),
  P('Rounding Top', false),
  P('Cup Base', false),
  P('Saucer Base', false),
  P('Pocket Pivot', true),
  P('Undercut & Rally', true),
  P('Shakeout', false),
  P('Wyckoff Spring', true),
  P('Wyckoff Upthrust', true),
];

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
  const out = [];
  for (const list of byType.values()) {
    list.sort((a, b) => a.barIndex - b.barIndex);
    list.forEach((e, i) => {
      const next = list[i + 1];
      if (!next || next.barIndex - e.barIndex > gap) out.push(e);
    });
  }
  return out.sort((a, b) => a.barIndex - b.barIndex);
}
