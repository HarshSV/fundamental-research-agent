// Canonical pattern registry - the ONE source of truth for which chart
// patterns exist, what timeframe they are detected on, how much history they
// need and whether a real detector backs them. The selector chips, the
// detector runners and the audit all derive from this list; nothing else
// keeps its own list of patterns.
//
//   id                 stable slug, derived from displayName (= event.patternType)
//   displayName        label shown on the chip / chart
//   timeframe          'intraday' (live 5m candles) | 'daily' | 'weekly'
//   minBars            minimum bars of THAT timeframe the detector needs
//   category           grouping only (no behaviour)
//   detector           function(bars, meta) -> events, or null = not implemented
//   enabled            a real detector exists
//   availabilityReason why it is unavailable (null when enabled)
//   definition         the rule the detector actually applies
//
// A pattern is "supported" only when `detector` is a real function that can
// emit events with this patternType. `scripts/auditPatterns.mjs` and
// `tests/registry.test.mjs` fail if a detector emits a type that is not
// registered or a registered, enabled type has no detector.

import { patternType, detectChartPatterns } from './chartPatterns.js';
import { dailyDetectors as D, weeklyDetectors as W } from './higherTimeframePatterns.js';

const NOT_IMPLEMENTED = 'Detector not available yet';

function entry(displayName, timeframe, minBars, category, detector, definition) {
  return {
    id: patternType(displayName),
    displayName,
    timeframe,
    minBars,
    category,
    detector: detector || null,
    enabled: !!detector,
    availabilityReason: detector ? null : NOT_IMPLEMENTED,
    definition,
  };
}

const I = (name, cat, def) => entry(name, 'intraday', 30, cat, detectChartPatterns, def);

export const PATTERN_REGISTRY = [
  // Daily structures (O'Neil / Minervini style bases)
  entry('VCP', 'daily', 150, 'base', D.vcpDaily, 'Stage-2 uptrend; >=2 shrinking pullbacks (first 8-40%, last <=12%); volume drying up; near pivot'),
  entry('Cup & Handle', 'daily', 80, 'base', D.cupAndHandleDaily, 'Cup 30-250d, 12-35% deep, rims within 10%, U-shaped; 5-25d handle <= min(15%, half the cup)'),
  entry('Flat Base', 'daily', 75, 'base', D.flatBaseDaily, '>=25d range <=15% after a >=20% advance, price in top 5% of range'),
  entry('Ascending Base', 'daily', 100, 'base', D.ascendingBaseDaily, '3 pullbacks of 8-25% with rising highs and lows over >=45d'),
  entry('IPO Base', 'daily', 25, 'base', D.ipoBaseDaily, 'Needs the listing date; 25-250 sessions old with a 15-25d base <=35% deep'),
  entry('High Tight Flag', 'daily', 50, 'continuation', D.highTightFlagDaily, '>=100% advance in <=40d then a 5-25d flag <=25% deep'),
  entry('Cup Base', 'daily', 80, 'base', D.cupBaseDaily, 'Valid cup (see Cup & Handle) with no handle yet, price within 8% of the left rim'),
  entry('Saucer Base', 'daily', 60, 'base', D.saucerBaseDaily, 'Rounding bottom that is >=60d long and <=20% deep'),
  entry('Rounding Bottom', 'daily', 40, 'reversal', D.roundingBottomDaily, 'Parabolic fit R2>=0.75, vertex mid-window, >=8% sag, right end recovered to within 10% of left'),
  entry('Rounding Top', 'daily', 40, 'reversal', D.roundingTopDaily, 'Mirror of Rounding Bottom'),
  entry('Triple Top', 'daily', 40, 'reversal', D.tripleTopDaily, 'Three swing highs within 2.5%, >=5d apart, >=3% reactions between'),
  entry('Triple Bottom', 'daily', 40, 'reversal', D.tripleBottomDaily, 'Three swing lows within 2.5%, >=5d apart, >=3% reactions between'),
  entry('Shakeout', 'daily', 25, 'specialized', D.shakeoutDaily, 'Undercuts the prior 20d low by >=1.5% then closes back above it on >=1.5x volume'),
  entry('Pennant', 'daily', 30, 'continuation', D.pennantDaily, '>=10% pole then a 5-15d converging flag at most half the pole height'),
  // Weekly structures
  entry('Three Weeks Tight', 'weekly', 13, 'base', W.threeWeeksTightWeekly, '3 consecutive completed weekly closes within 1% in an uptrend'),
  // Intraday geometry (scale-free swing / range detectors on the live candles)
  I('Double Bottom', 'reversal', 'Two swing lows within 3%, 5-60 bars apart, with a >=rebound between'),
  I('Double Top', 'reversal', 'Two swing highs within 3%, 5-60 bars apart'),
  I('Flag', 'continuation', '>=8% pole over 10 bars then a tight 8-bar counter-drift'),
  I('Ascending Triangle', 'continuation', 'Flat swing highs, rising swing lows'),
  I('Descending Triangle', 'continuation', 'Flat swing lows, falling swing highs'),
  I('Symmetrical Triangle', 'continuation', 'Falling highs, rising lows (converging)'),
  I('Rising Wedge', 'reversal', 'Both bounds rising, lows rising faster'),
  I('Falling Wedge', 'reversal', 'Both bounds falling, highs falling faster'),
  I('Rectangle', 'continuation', 'Flat highs and flat lows'),
  I('Head & Shoulders', 'reversal', 'Three swing highs, middle highest, shoulders within 10%'),
  I('Inverse Head & Shoulders', 'reversal', 'Three swing lows, middle lowest, shoulders within 10%'),
  I('Pocket Pivot', 'specialized', 'Up bar whose volume exceeds the largest down-bar volume of the prior 10'),
  I('Undercut & Rally', 'specialized', 'Bar undercuts the prior swing low then closes back above it'),
  I('Wyckoff Spring', 'specialized', 'False breakdown below support closing back above (low reliability)'),
  I('Wyckoff Upthrust', 'specialized', 'False breakout above resistance closing back below (low reliability)'),
  I('Harmonic pattern (Gartley-like)', 'harmonic', 'Coarse XABCD ratio fit on the last 4 swings (low reliability)'),
];

const DISPLAY_ORDER = [
  'VCP', 'Cup & Handle', 'Double Bottom', 'Double Top', 'Flat Base', 'Ascending Base', 'IPO Base', 'High Tight Flag',
  'Three Weeks Tight', 'Flag', 'Pennant', 'Ascending Triangle', 'Descending Triangle', 'Symmetrical Triangle',
  'Rising Wedge', 'Falling Wedge', 'Rectangle', 'Head & Shoulders', 'Inverse Head & Shoulders', 'Triple Bottom',
  'Triple Top', 'Rounding Bottom', 'Rounding Top', 'Cup Base', 'Saucer Base', 'Pocket Pivot', 'Undercut & Rally',
  'Shakeout', 'Wyckoff Spring', 'Wyckoff Upthrust',
];
const orderOf = (p) => { const i = DISPLAY_ORDER.indexOf(p.displayName); return i < 0 ? DISPLAY_ORDER.length : i; };
PATTERN_REGISTRY.sort((a, b) => orderOf(a) - orderOf(b)); // chip order only; no behavioural meaning

export const registryById = new Map(PATTERN_REGISTRY.map((p) => [p.id, p]));

export const TIMEFRAME_LABEL = { intraday: 'intraday', daily: 'daily', weekly: 'weekly' };

// Runs every enabled detector registered for `timeframe` over `bars` (as of the
// last bar) and tags the events. A detector shared by several registry entries
// runs once. Events for a pattern whose minBars exceeds the bars supplied are
// dropped (insufficient history is never reported as a detection).
export function runDetectors(timeframe, bars, meta) {
  if (!bars || !bars.length) return [];
  const ran = new Set();
  const out = [];
  for (const p of PATTERN_REGISTRY) {
    if (p.timeframe !== timeframe || !p.detector || ran.has(p.detector)) continue;
    ran.add(p.detector);
    for (const e of p.detector(bars, meta) || []) {
      const reg = registryById.get(e.patternType);
      if (!reg || reg.timeframe !== timeframe || bars.length < reg.minBars) continue;
      out.push({ ...e, timeframe });
    }
  }
  return out;
}
