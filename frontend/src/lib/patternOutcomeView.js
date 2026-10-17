// Presentation rules for pattern BIAS and realised OUTCOMES. Pure; tested in tests/patternOutcomeView.test.mjs.
//
// Colour semantics (kept deliberately separate):
//   REALISED OUTCOME  green = positive, red = negative, grey = flat, dashed sky-blue = pending, dim italic = not evaluable
//   PATTERN BIAS      a neutral glyph (sky ▲ bullish, amber ▼ bearish, slate ◆ context-dependent) - NEVER green or red,
//                     so a bullish-biased pattern is not painted green merely because of the textbook expectation.

import { BIAS, BIAS_LABEL, classificationById, biasText } from './patternClassification.js';
import { OUTCOME } from './patternOutcomes.js';

export const COUNT_DEFINITION =
  'Counts are formation runs detected for THIS stock in the loaded window (repeated firings of one formation count once). '
  + 'They are detections - not successes, and not a number of distinct stocks.';

export const BIAS_DISCLAIMER = 'Conventional technical-analysis expectation only - not a prediction and not evidence that the pattern worked.';

export const OUTCOME_STYLE = {
  [OUTCOME.POSITIVE]: { label: 'Positive', dot: 'bg-emerald-500', text: 'text-emerald-300', chip: 'border border-emerald-500/40 bg-emerald-500/10 text-emerald-300' },
  [OUTCOME.NEGATIVE]: { label: 'Negative', dot: 'bg-red-500', text: 'text-red-300', chip: 'border border-red-500/40 bg-red-500/10 text-red-300' },
  [OUTCOME.FLAT]: { label: 'Flat', dot: 'bg-slate-500', text: 'text-slate-400', chip: 'border border-slate-600 bg-slate-700/30 text-slate-300' },
  [OUTCOME.PENDING]: { label: 'Pending', dot: 'bg-transparent border border-dashed border-sky-400', text: 'text-sky-300', chip: 'border border-dashed border-sky-400/70 text-sky-300' },
  [OUTCOME.NOT_EVALUABLE]: { label: 'Not evaluable', dot: 'bg-transparent border border-slate-600', text: 'text-slate-500 italic', chip: 'border border-slate-700 text-slate-500 italic' },
};

export const BIAS_STYLE = {
  [BIAS.BULLISH]: { glyph: '▲', text: 'text-sky-300', label: BIAS_LABEL.bullish },
  [BIAS.BEARISH]: { glyph: '▼', text: 'text-amber-300', label: BIAS_LABEL.bearish },
  [BIAS.CONTEXT]: { glyph: '◆', text: 'text-slate-300', label: BIAS_LABEL.context },
  [BIAS.UNKNOWN]: { glyph: '?', text: 'text-slate-500', label: BIAS_LABEL.unknown },
};

const REASON_TEXT = {
  session_boundary: 'horizon would cross the session close',
  missing_candles: 'missing candles in the forward window',
  suspect_corporate_action: 'split-like price jump in the forward window',
  reference_bar_missing: 'reference bar not in the data',
};

export const HORIZON_UNIT = { intraday: '×5m', daily: 'd', weekly: 'w' };
// The intraday bar length follows the chart interval (1m/5m/15m/1h); LiveChart sets it before rendering any outcome label.
export const INTRADAY_UNIT_LABEL = { 60: '×1m', 300: '×5m', 900: '×15m', 3600: '×1h' };
export const setIntradayBarSeconds = (sec) => { HORIZON_UNIT.intraday = INTRADAY_UNIT_LABEL[sec] || '×5m'; };
export const horizonLabel = (timeframe, h) => `${h}${HORIZON_UNIT[timeframe] || ' bars'}`;
export const TIMEFRAME_BARS = { intraday: '5-minute bars', daily: 'daily bars', weekly: 'weekly bars' };

export const fmtReturn = (r) => (Number.isFinite(r) ? `${r >= 0 ? '+' : ''}${(r * 100).toFixed(2)}%` : '-');
export const fmtRate = (x) => (x == null || !Number.isFinite(x) ? '-' : `${(x * 100).toFixed(0)}%`);

// One horizon of one occurrence -> what the badge shows. Pending and not-evaluable are NEVER shown as Flat.
export function outcomeBadge(outcome, timeframe, h) {
  const s = OUTCOME_STYLE[outcome?.state] || OUTCOME_STYLE[OUTCOME.NOT_EVALUABLE];
  const unit = horizonLabel(timeframe, h);
  let text;
  if (outcome?.state === OUTCOME.PENDING) text = `${unit}: pending`;
  else if (outcome?.state === OUTCOME.NOT_EVALUABLE) text = `${unit}: n/a`;
  else text = `${unit}: ${fmtReturn(outcome.ret)}`;
  const title = outcome?.state === OUTCOME.NOT_EVALUABLE
    ? `${s.label} (${REASON_TEXT[outcome.reason] || outcome.reason || 'unknown reason'}) - excluded from statistics`
    : outcome?.state === OUTCOME.PENDING
      ? 'Pending - the horizon bar does not exist yet; not counted as Flat'
      : `${s.label}: close ${unit} later vs the detection bar close; Flat band ±${(outcome.band * 100).toFixed(2)}% (${outcome.bandBasis})`;
  return { state: outcome?.state, text, title, chip: s.chip, dot: s.dot, textClass: s.text, label: s.label };
}

// ---- Chart marker colours (lightweight-charts markers take one solid colour; pending is sky, mixed clusters are indigo) ----
export const CHART_OUTCOME_COLOR = {
  [OUTCOME.POSITIVE]: 'rgb(16,185,129)',
  [OUTCOME.NEGATIVE]: 'rgb(239,68,68)',
  [OUTCOME.FLAT]: 'rgb(148,163,184)',
  [OUTCOME.PENDING]: 'rgb(56,189,248)',
  [OUTCOME.NOT_EVALUABLE]: 'rgba(100,116,139,0.85)',
  mixed: 'rgb(129,140,248)',
};

// First (shortest) configured horizon of an evaluated occurrence: the one that colours the chart marker.
export function primaryOutcome(result) {
  if (!result || !result.outcomes) return null;
  const hs = Object.keys(result.outcomes).map(Number).sort((a, b) => a - b);
  return hs.length ? { horizon: hs[0], ...result.outcomes[hs[0]] } : null;
}

// Marker for a group of events. `primaries` = primaryOutcome() of each event (null/unknown -> not evaluable, never Flat).
// Mixed clusters are drawn as one stacked marker PER outcome present, each in its own colour with its own count.
export function groupMarker(primaries) {
  const counts = { positive: 0, negative: 0, flat: 0, pending: 0, not_evaluable: 0 };
  for (const p of primaries) counts[p && counts[p.state] !== undefined ? p.state : OUTCOME.NOT_EVALUABLE] += 1;
  const present = Object.keys(counts).filter((k) => counts[k] > 0);
  const state = present.length === 1 ? present[0] : 'mixed';
  const ret = ' ' + fmtReturn(primaries[0] && primaries[0].ret);
  const single = { positive: ret, negative: ret, flat: ret, pending: ' \u2026', not_evaluable: ' n/a' };
  const GLYPH = { positive: '+', negative: '\u2212', flat: '~', pending: '\u2026', not_evaluable: 'n/a ' };
  const tally = ` ${present.map((k) => `${GLYPH[k]}${counts[k]}`).join(' ')}`;
  const suffix = primaries.length === 1 ? single[state] : tally;
  const parts = state === 'mixed'
    ? present.map((k) => ({ state: k, color: CHART_OUTCOME_COLOR[k], suffix: ` ${GLYPH[k]}${counts[k]}` }))
    : [{ state, color: CHART_OUTCOME_COLOR[state], suffix }];
  return { state, color: CHART_OUTCOME_COLOR[state], counts, suffix, parts };
}

export function biasGlyph(patternId) {
  const e = classificationById.get(patternId);
  return BIAS_STYLE[e ? e.bias : BIAS.UNKNOWN];
}

// Title/tooltip of a selector chip: names the timeframe, the conventional bias and what the count means.
export function chipTitle(entry, count) {
  const cls = classificationById.get(entry.id);
  const bias = cls ? `Conventional bias: ${biasText({ bias: cls.bias, requiresConfirmation: cls.confirmation !== 'none' })}. ` : 'Conventional bias: unknown. ';
  const n = count == null ? '' : ` Count ${count}: formation runs for this stock in the loaded window (detections, not successes).`;
  return `${entry.displayName} - ${entry.timeframe} timeframe. ${bias}${BIAS_DISCLAIMER}${n} ${entry.definition}`;
}

// Everything the stats table needs for one horizon, with explicit sample-size language.
export function horizonRow(hz, timeframe) {
  const i = hz.independent;
  return {
    label: horizonLabel(timeframe, hz.horizon),
    n: i.evaluable, positive: i.positive, negative: i.negative, flat: i.flat,
    positiveRate: fmtRate(i.positiveRate), baseRate: fmtRate(hz.base?.positiveRate),
    mean: i.meanReturn == null ? '-' : fmtReturn(i.meanReturn), median: i.medianReturn == null ? '-' : fmtReturn(i.medianReturn),
    pending: hz.all.pending, notEvaluable: hz.all.notEvaluable, skippedOverlap: i.skippedOverlap,
    totalFormations: hz.all.total,
    warning: i.evaluable === 0 ? 'No completed observations yet.' : hz.smallSample ? `Small sample (${i.evaluable} independent observations): too few to judge reliability.` : null,
  };
}
