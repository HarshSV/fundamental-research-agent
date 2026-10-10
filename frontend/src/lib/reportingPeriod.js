// Reporting-period summary of the Fundamental ratio table. Every contract ratio carries a `reporting` block inside its `_metadata`
// input (backend tools/ratio_contract.py::reporting_context). This reads it - it never derives or guesses a period.

export function rowReporting(row) {
  const meta = (row?.inputs || []).find((i) => i && i.name === '_metadata');
  return meta?.reporting || null;
}

// -> { fiscalYearLabel, basis, periodType, ttm, marketQuotedAt } or null when no row states its period.
export function summarizeReporting(rows) {
  const seen = (rows || []).map(rowReporting).filter(Boolean);
  if (seen.length === 0) return null;
  const pick = (k) => {
    const vals = [...new Set(seen.map((r) => r[k]).filter((v) => v !== null && v !== undefined))];
    return vals.length === 1 ? vals[0] : vals.length > 1 ? 'mixed' : null;
  };
  const priced = seen.find((r) => r.price && r.price.quoted_at);
  return {
    fiscalYearLabel: pick('fiscal_year_label'),
    basis: pick('statement_basis'),
    periodType: pick('period_type'),
    ttm: seen.some((r) => r.ttm === true),
    marketQuotedAt: priced ? priced.price.quoted_at : null,
    basisNote: (seen.find((r) => r.basis_note) || {}).basis_note || null,
  };
}

export function reportingHeadline(s) {
  if (!s) return null;
  const bits = [];
  bits.push(s.ttm ? 'Includes TTM values' : 'Annual statements (non-TTM)');
  if (s.fiscalYearLabel) bits.push(s.fiscalYearLabel === 'mixed' ? 'Mixed fiscal years' : s.fiscalYearLabel);
  if (s.basis) bits.push(s.basis === 'mixed' ? 'Mixed consolidated / standalone' : s.basis.charAt(0).toUpperCase() + s.basis.slice(1));
  if (s.basisNote) bits.push(s.basisNote);
  return bits.join(' · ');
}
