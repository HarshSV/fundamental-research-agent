// Number/format helpers for Indian equity data. Raw backend figures are in rupees.

export const isNum = (v) => v !== null && v !== undefined && !isNaN(Number(v)) && isFinite(Number(v));

// Rupees -> compact "₹1,75,462 Cr" style. `raw` is in rupees.
export function inrCrore(raw, { decimals = 0, prefix = '₹', suffix = ' Cr' } = {}) {
  if (!isNum(raw)) return '—';
  const cr = Number(raw) / 1e7;
  const abs = Math.abs(cr);
  const d = abs >= 100 ? 0 : decimals;
  const s = cr.toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d });
  return `${prefix}${s}${suffix}`;
}

// A value already in rupees, formatted with grouping (for a share price etc.).
export function inr(raw, { decimals = 2, prefix = '₹' } = {}) {
  if (!isNum(raw)) return '—';
  return `${prefix}${Number(raw).toLocaleString('en-IN', { maximumFractionDigits: decimals, minimumFractionDigits: decimals })}`;
}

// Fraction (0.152) -> "15.2%"; pass alreadyPercent for values like 15.2.
export function pct(v, { decimals = 1, alreadyPercent = false } = {}) {
  if (!isNum(v)) return '—';
  const n = alreadyPercent ? Number(v) : Number(v) * 100;
  return `${n.toFixed(decimals)}%`;
}

export function num(v, { decimals = 2, suffix = '' } = {}) {
  if (!isNum(v)) return '—';
  return `${Number(v).toFixed(decimals)}${suffix}`;
}

// Signed percentage change with tone.
export function signedPct(v, { decimals = 2, alreadyPercent = false } = {}) {
  if (!isNum(v)) return { text: '—', tone: 'neutral' };
  const n = alreadyPercent ? Number(v) : Number(v) * 100;
  const tone = n > 0.0001 ? 'pos' : n < -0.0001 ? 'neg' : 'neutral';
  const sign = n > 0 ? '+' : '';
  return { text: `${sign}${n.toFixed(decimals)}%`, tone };
}

export const toneClass = (tone) => (tone === 'pos' ? 'nv-pos' : tone === 'neg' ? 'nv-neg' : 'nv-muted');
