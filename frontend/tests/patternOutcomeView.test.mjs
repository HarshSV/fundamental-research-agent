import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  COUNT_DEFINITION, BIAS_DISCLAIMER, OUTCOME_STYLE, BIAS_STYLE, biasGlyph, chipTitle, outcomeBadge, horizonRow, horizonLabel, fmtRate, fmtReturn,
} from '../src/lib/patternOutcomeView.js';
import { PATTERN_REGISTRY } from '../src/lib/patternRegistry.js';
import { OUTCOME } from '../src/lib/patternOutcomes.js';

const GREEN = /emerald|green/, RED = /red/;
const entry = (name) => PATTERN_REGISTRY.find((p) => p.displayName === name);

// ---------------------------------------------------------------- colour semantics
test('realised outcome colours: green positive, red negative, grey flat; pending and not-evaluable are visually distinct', () => {
  const s = OUTCOME_STYLE;
  assert.match(s.positive.chip + s.positive.dot + s.positive.text, GREEN);
  assert.match(s.negative.chip + s.negative.dot + s.negative.text, RED);
  assert.doesNotMatch(s.flat.chip + s.flat.dot + s.flat.text, /emerald|red|sky/);
  // pending: dashed outline in a colour no other state uses; hollow dot; never the grey of Flat
  assert.match(s.pending.chip, /dashed/); assert.match(s.pending.dot, /dashed/); assert.match(s.pending.chip, /sky/);
  assert.notEqual(s.pending.chip, s.flat.chip); assert.doesNotMatch(s.flat.chip, /dashed/);
  assert.match(s.not_evaluable.text, /italic/);
  const chips = Object.values(s).map((x) => x.chip);
  assert.equal(new Set(chips).size, chips.length);                                                   // five states, five distinct looks
});

test('pattern BIAS is never drawn in the outcome colours: a bullish pattern is not painted green, a bearish one not red', () => {
  for (const [bias, st] of Object.entries(BIAS_STYLE)) {
    assert.doesNotMatch(st.text, GREEN, `${bias} must not use green`);
    assert.doesNotMatch(st.text, RED, `${bias} must not use red`);
  }
  assert.equal(BIAS_STYLE.bullish.glyph, '▲'); assert.equal(BIAS_STYLE.bearish.glyph, '▼'); assert.equal(BIAS_STYLE.context.glyph, '◆');
  assert.equal(biasGlyph('double-bottom').glyph, '▲'); assert.equal(biasGlyph('double-top').glyph, '▼');
  assert.equal(biasGlyph('vcp').glyph, '◆'); assert.equal(biasGlyph('not-a-pattern').glyph, '?');
});

test('outcome badges: pending and not-evaluable are never labelled Flat; completed ones show the realised return', () => {
  const pend = outcomeBadge({ state: OUTCOME.PENDING }, 'daily', 5);
  assert.match(pend.text, /pending/); assert.doesNotMatch(pend.text + pend.label, /flat/i); assert.match(pend.title, /not counted as Flat/); assert.equal(pend.chip, OUTCOME_STYLE.pending.chip);
  const na = outcomeBadge({ state: OUTCOME.NOT_EVALUABLE, reason: 'session_boundary' }, 'intraday', 30);
  assert.match(na.text, /n\/a/); assert.match(na.title, /session close/); assert.match(na.title, /excluded from statistics/);
  const pos = outcomeBadge({ state: OUTCOME.POSITIVE, ret: 0.0234, band: 0.01, bandBasis: 'volatility' }, 'daily', 5);
  assert.equal(pos.text, '5d: +2.34%'); assert.equal(pos.chip, OUTCOME_STYLE.positive.chip); assert.match(pos.title, /Flat band ±1\.00%/);
  assert.equal(outcomeBadge({ state: OUTCOME.NEGATIVE, ret: -0.03, band: 0.01, bandBasis: 'floor' }, 'weekly', 4).text, '4w: -3.00%');
  assert.equal(outcomeBadge({ state: OUTCOME.FLAT, ret: 0.001, band: 0.01, bandBasis: 'floor' }, 'intraday', 15).chip, OUTCOME_STYLE.flat.chip);
});

test('timeframe and horizon are visible wherever an outcome is shown', () => {
  assert.equal(horizonLabel('intraday', 5), '5×5m'); assert.equal(horizonLabel('daily', 15), '15d'); assert.equal(horizonLabel('weekly', 8), '8w');
  assert.match(outcomeBadge({ state: OUTCOME.PENDING }, 'intraday', 5).text, /^5×5m/);
  assert.equal(horizonRow({ horizon: 5, all: { pending: 0, notEvaluable: 0, total: 0 }, independent: { evaluable: 0, positive: 0, negative: 0, flat: 0, positiveRate: null, meanReturn: null, medianReturn: null, skippedOverlap: 0 }, base: null, smallSample: true }, 'daily').label, '5d');
});

// ---------------------------------------------------------------- count definitions
test('a count is defined as detections, not successes and not stocks', () => {
  assert.match(COUNT_DEFINITION, /formation runs/);
  assert.match(COUNT_DEFINITION, /THIS stock/);
  assert.match(COUNT_DEFINITION, /not successes/);
  assert.match(COUNT_DEFINITION, /not a number of distinct stocks/);
  const t = chipTitle(entry('Double Bottom'), 7);
  assert.match(t, /Count 7: formation runs/); assert.match(t, /detections, not successes/);
  assert.match(t, /Conventional bias: Bullish bias/); assert.match(t, new RegExp(BIAS_DISCLAIMER.slice(0, 30)));
  assert.match(t, /intraday timeframe/);
  assert.match(chipTitle(entry('Rectangle'), 3), /Context-dependent - direction unconfirmed/);
  assert.match(chipTitle(entry('Ascending Triangle'), 0), /needs confirmation/);
  assert.doesNotMatch(chipTitle(entry('Rectangle'), null), /Count/);                                // no invented count when none is supplied
});

test('every registered pattern gets a chip title that states a bias and the timeframe', () => {
  for (const p of PATTERN_REGISTRY) {
    const t = chipTitle(p, 1);
    assert.match(t, /Conventional bias:/, p.displayName);
    assert.match(t, new RegExp(`${p.timeframe} timeframe`), p.displayName);
  }
});

// ---------------------------------------------------------------- statistics wording: sample size, no invented numbers
test('stats rows: sample-size language, "-" for missing rates, nothing invented', () => {
  const hz = (ind, extra = {}) => ({ horizon: 5, all: { total: 4, pending: 1, notEvaluable: 2 }, independent: { skippedOverlap: 0, ...ind }, base: { positiveRate: 0.3 }, smallSample: false, ...extra });
  const none = horizonRow(hz({ evaluable: 0, positive: 0, negative: 0, flat: 0, positiveRate: null, meanReturn: null, medianReturn: null }), 'daily');
  assert.equal(none.positiveRate, '-'); assert.equal(none.mean, '-'); assert.equal(none.median, '-'); assert.match(none.warning, /No completed observations/);
  const small = horizonRow(hz({ evaluable: 6, positive: 3, negative: 2, flat: 1, positiveRate: 0.5, meanReturn: 0.012, medianReturn: -0.004 }, { smallSample: true }), 'daily');
  assert.equal(small.positiveRate, '50%'); assert.equal(small.baseRate, '30%'); assert.equal(small.mean, '+1.20%'); assert.equal(small.median, '-0.40%');
  assert.match(small.warning, /Small sample \(6 independent observations\)/);
  assert.equal(small.pending, 1); assert.equal(small.notEvaluable, 2);                                // reported separately
  assert.equal(horizonRow(hz({ evaluable: 40, positive: 20, negative: 10, flat: 10, positiveRate: 0.5, meanReturn: 0, medianReturn: 0 }), 'daily').warning, null);
  assert.equal(fmtRate(null), '-'); assert.equal(fmtRate(0), '0%'); assert.equal(fmtReturn(NaN), '-');
});

// ---------------------------------------------------------------- UI wiring (static checks on the component source)
test('What\'s happening wiring: pattern rows are not tone-coloured; chips, count definition and outcome panel are present', () => {
  const src = fs.readFileSync(new URL('../src/views/LiveChart.jsx', import.meta.url), 'utf8');
  assert.match(src, /isPattern \? 'bg-slate-500'/);                         // a bullish/bearish tone never colours a pattern row's dot
  assert.match(src, /isPattern \? 'text-slate-300' : toneClass\(e\.tone\)/);
  assert.match(src, /data-testid="count-definition"/);
  assert.match(src, /biasGlyph\(p\.id\)/);
  assert.match(src, /<PatternOutcomePanel/);
  assert.match(src, /rowOutcome\(e\)/);
  const panel = fs.readFileSync(new URL('../src/components/PatternOutcomePanel.jsx', import.meta.url), 'utf8');
  assert.match(panel, /data-testid="pattern-bias"/); assert.match(panel, /data-testid="outcome-table"/);
  assert.match(panel, /Pending and not-evaluable/);
  assert.doesNotMatch(panel, /accuracy of|guaranteed|will rise|will fall/i);
});
