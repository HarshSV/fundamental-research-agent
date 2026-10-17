// Pattern CLASSIFICATION registry: the conventional technical-analysis bias of every pattern shown in "What's happening".
//
// This is ONLY the textbook expectation, fixed before any outcome is known. It is NOT a prediction, NOT evidence the pattern
// worked, and NOT a model output - realised outcomes are computed separately (patternOutcomes.js) and displayed separately.
//
// Keyed by the same `id` (patternType slug) as PATTERN_REGISTRY in patternRegistry.js, which remains the single source of
// truth for which patterns/detectors exist. tests/patternClassification.test.mjs fails if the two lists diverge.
//
//   bias           'bullish' | 'bearish'  fixed conventional bias
//                  'context'              direction depends on subtype / breakout - never forced
//                  'unknown'              the detector gives no basis for a direction
//   resolvedBy     how a CONTEXT pattern's direction is read from an actual event (never invented):
//                    'detector-tone'  the detector itself emits pos/neg from the structure (Flag, Pennant: pole direction)
//                    'zone-side'      the event carries the order-block side (bull/bear)
//                    'breakout'       direction is only known once price breaks out; the detector does not evaluate that
//                    'none'           nothing in the detector output says (e.g. Harmonic)
//   confirmation   what the textbook says must happen before the bias applies: 'none' | 'breakout' | 'structure'
//   detectorTone   what the detector actually emits today (documents the verification against the code)

import { patternType } from './chartPatterns.js';

export const BIAS = { BULLISH: 'bullish', BEARISH: 'bearish', CONTEXT: 'context', UNKNOWN: 'unknown' };

export const BIAS_LABEL = {
  bullish: 'Bullish bias',
  bearish: 'Bearish bias',
  context: 'Context-dependent',
  unknown: 'Bias unknown',
};

function c(displayName, bias, detectorTone, { resolvedBy = 'fixed', confirmation = 'none', note = '' } = {}) {
  return { id: patternType(displayName), displayName, bias, detectorTone, resolvedBy, confirmation, note };
}

export const PATTERN_CLASSIFICATION = [
  // ---- conventionally bullish --------------------------------------------------------------------------------------
  c('Double Bottom', BIAS.BULLISH, 'pos'),
  c('Cup & Handle', BIAS.BULLISH, 'pos'),
  c('Flat Base', BIAS.BULLISH, 'neutral', { note: 'Detector emits a neutral tone; the textbook base is a bullish continuation setup.' }),
  c('Ascending Base', BIAS.BULLISH, 'pos'),
  c('IPO Base', BIAS.BULLISH, 'pos'),
  c('High Tight Flag', BIAS.BULLISH, 'pos'),
  c('Three Weeks Tight', BIAS.BULLISH, 'pos'),
  c('Inverse Head & Shoulders', BIAS.BULLISH, 'pos'),
  c('Triple Bottom', BIAS.BULLISH, 'pos'),
  c('Rounding Bottom', BIAS.BULLISH, 'pos'),
  c('Cup Base', BIAS.BULLISH, 'pos'),
  c('Saucer Base', BIAS.BULLISH, 'pos'),
  c('Falling Wedge', BIAS.BULLISH, 'pos', { confirmation: 'breakout', note: 'Typically bullish only when confirmed by an upside breakout.' }),
  c('Ascending Triangle', BIAS.BULLISH, 'pos', { confirmation: 'breakout', note: 'Typically bullish only when confirmed by an upside breakout.' }),
  c('Pocket Pivot', BIAS.BULLISH, 'pos'),
  c('Undercut & Rally', BIAS.BULLISH, 'pos'),
  c('Shakeout', BIAS.BULLISH, 'pos'),
  c('Wyckoff Spring', BIAS.BULLISH, 'pos', { note: 'Low reliability from OHLCV alone.' }),

  // ---- conventionally bearish --------------------------------------------------------------------------------------
  c('Double Top', BIAS.BEARISH, 'neg'),
  c('Head & Shoulders', BIAS.BEARISH, 'neg'),
  c('Triple Top', BIAS.BEARISH, 'neg'),
  c('Rising Wedge', BIAS.BEARISH, 'neg', { confirmation: 'breakout', note: 'Typically bearish only when confirmed by a downside breakout.' }),
  c('Descending Triangle', BIAS.BEARISH, 'neg', { confirmation: 'breakout', note: 'Not in the original list; mirror of Ascending Triangle - typically bearish when confirmed by a downside breakout.' }),
  c('Wyckoff Upthrust', BIAS.BEARISH, 'neg', { note: 'Low reliability from OHLCV alone.' }),
  c('Rounding Top', BIAS.BEARISH, 'neg', { confirmation: 'structure', note: 'Conventionally bearish, but the structure and a confirming move must hold; the detector checks the arc fit only.' }),

  // ---- context-dependent / requiring confirmation ------------------------------------------------------------------
  c('VCP', BIAS.CONTEXT, 'pos', { resolvedBy: 'breakout', confirmation: 'breakout', note: 'The detector requires a prior uptrend and shrinking pullbacks but does NOT evaluate a breakout, so direction is unconfirmed.' }),
  c('Flag', BIAS.CONTEXT, 'by-pole', { resolvedBy: 'detector-tone', note: 'Bullish flag after an up-pole, bearish flag after a down-pole (the detector reads the pole).' }),
  c('Pennant', BIAS.CONTEXT, 'by-pole', { resolvedBy: 'detector-tone', note: 'Bullish after an up-pole, bearish after a down-pole (the detector reads the pole).' }),
  c('Symmetrical Triangle', BIAS.CONTEXT, 'neutral', { resolvedBy: 'breakout', confirmation: 'breakout', note: 'Direction depends on the breakout, which the detector does not evaluate.' }),
  c('Rectangle', BIAS.CONTEXT, 'neutral', { resolvedBy: 'breakout', confirmation: 'breakout', note: 'Direction depends on the breakout, which the detector does not evaluate.' }),
  c('Harmonic pattern (Gartley-like)', BIAS.CONTEXT, 'neutral', { resolvedBy: 'none', confirmation: 'structure', note: 'The detector is a coarse ratio fit and does not distinguish bullish from bearish completion, so no direction is claimed.' }),
  c('Bullish Order Block', BIAS.BULLISH, 'pos', { note: 'Zone side is bullish by construction (close above a swing high).' }),
  c('Bearish Order Block', BIAS.BEARISH, 'neg', { note: 'Zone side is bearish by construction (close below a swing low).' }),
  c('Order Block Retest', BIAS.CONTEXT, 'by-side', { resolvedBy: 'zone-side', note: 'Bullish or bearish according to the zone being retested.' }),
  c('Order Block Broken', BIAS.CONTEXT, 'neutral', { resolvedBy: 'none', note: 'An invalidation event: it says the zone failed, not which way price will go.' }),
];

export const classificationById = new Map(PATTERN_CLASSIFICATION.map((p) => [p.id, p]));

const DIRECTIONAL = new Set(['pos', 'neg']);
const toneToBias = (t) => (t === 'pos' ? BIAS.BULLISH : t === 'neg' ? BIAS.BEARISH : null);

// Bias of ONE detected event. Never invents a direction: where the detector output does not support one the result is
// 'context' (direction unconfirmed) or 'unknown'.
//   -> { bias, basis, requiresConfirmation, conflict, note }
export function classifyEvent(e) {
  const entry = classificationById.get(e?.patternType);
  if (!entry) return { bias: BIAS.UNKNOWN, basis: 'pattern is not in the classification registry', requiresConfirmation: false, conflict: false, note: '' };
  const base = { requiresConfirmation: entry.confirmation !== 'none', conflict: false, note: entry.note };
  if (entry.bias === BIAS.BULLISH || entry.bias === BIAS.BEARISH) {
    const tb = toneToBias(e.tone);
    // A detector that emits the OPPOSITE direction to the registry is a contradiction: report it, do not pick a side.
    if (DIRECTIONAL.has(e.tone) && tb !== entry.bias) {
      return { ...base, bias: BIAS.CONTEXT, basis: `detector direction (${e.tone}) contradicts the registry bias (${entry.bias})`, conflict: true };
    }
    return { ...base, bias: entry.bias, basis: 'fixed conventional bias' };
  }
  if (entry.bias === BIAS.CONTEXT) {
    if (entry.resolvedBy === 'detector-tone') {
      const tb = toneToBias(e.tone);
      return tb ? { ...base, bias: tb, basis: 'read from the detector (pole direction)' } : { ...base, bias: BIAS.CONTEXT, basis: 'direction unconfirmed' };
    }
    if (entry.resolvedBy === 'zone-side') {
      const tb = e.side === 'bull' ? BIAS.BULLISH : e.side === 'bear' ? BIAS.BEARISH : null;
      return tb ? { ...base, bias: tb, basis: 'read from the order-block side' } : { ...base, bias: BIAS.CONTEXT, basis: 'direction unconfirmed' };
    }
    return { ...base, bias: BIAS.CONTEXT, basis: entry.resolvedBy === 'breakout' ? 'direction depends on the breakout (not evaluated by the detector)' : 'direction unknown' };
  }
  return { ...base, bias: BIAS.UNKNOWN, basis: 'no basis for a direction' };
}

// Human-readable bias line, e.g. "Bullish bias (read from the detector)" / "Context-dependent - direction unconfirmed".
export function biasText(cls) {
  const label = BIAS_LABEL[cls.bias] || BIAS_LABEL.unknown;
  if (cls.bias === BIAS.CONTEXT) return `${label} - direction unconfirmed`;
  return cls.requiresConfirmation ? `${label} (needs confirmation)` : label;
}
