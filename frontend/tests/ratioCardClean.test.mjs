import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// UI guard: the Fundamental ratio card renders name + value only (no status / DIRECT-DERIVED / Stale badges) and no yellow
// warning or reason box. The statuses, calculation type and warnings stay in the API payload; the card just does not draw them.
const src = readFileSync(new URL('../src/views/DocumentAnalysis.jsx', import.meta.url), 'utf8');
const card = src.slice(src.indexOf('function FundamentalCard'), src.indexOf('function FundamentalTab'));

test('card draws no status / classification badge', () => {
  for (const banned of ['FUND_STATUS', 'r.status', 'calcType', 'r.stale', 'Needs Review', 'Verified']) {
    assert.ok(!card.includes(banned), `FundamentalCard must not reference ${banned}`);
  }
});

test('card has no yellow (amber) warning / context box', () => {
  assert.ok(!/amber-/.test(card), 'no amber styling in the card');
  assert.ok(!card.includes('<ul'), 'no warnings list is rendered');
});

test('card still renders the label, the value and the calculation breakdown / formula', () => {
  assert.ok(card.includes('{r.label}') && card.includes('fmtRatioValue(r)'));
  assert.ok(card.includes('Formula') || card.includes('CalculationBreakdown'));
});

test('an unavailable ratio still explains itself in plain (non-yellow) text', () => {
  assert.match(card, /reason && r\.value == null/);
});
