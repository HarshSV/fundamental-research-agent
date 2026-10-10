import test from 'node:test';
import assert from 'node:assert/strict';
import { summarizeReporting, reportingHeadline } from '../src/lib/reportingPeriod.js';

const row = (rep) => ({ inputs: [{ name: 'x' }, { name: '_metadata', reporting: rep }] });
const base = { period_type: 'annual', ttm: false, fiscal_year_label: 'FY2025-26', statement_basis: 'consolidated' };

test('headline states annual non-TTM, fiscal year and basis', () => {
  const s = summarizeReporting([row(base), row(base)]);
  assert.equal(reportingHeadline(s), 'Annual statements (non-TTM) · FY2025-26 · Consolidated');
});

test('market ratios expose the quote time', () => {
  const s = summarizeReporting([row(base), row({ ...base, price: { quoted_at: '2026-10-10T10:00:00Z' } })]);
  assert.equal(s.marketQuotedAt, '2026-10-10T10:00:00Z');
});

test('disagreeing rows are labelled mixed, never silently merged', () => {
  const s = summarizeReporting([row(base), row({ ...base, statement_basis: 'standalone' })]);
  assert.match(reportingHeadline(s), /Mixed consolidated \/ standalone/);
});

test('no row stating a period gives no headline (nothing is invented)', () => {
  assert.equal(summarizeReporting([{ inputs: [{ name: '_metadata' }] }]), null);
  assert.equal(reportingHeadline(null), null);
});

test('a TTM row is never presented as annual', () => {
  const s = summarizeReporting([row({ ...base, ttm: true })]);
  assert.match(reportingHeadline(s), /Includes TTM/);
});
