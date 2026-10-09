// Synthetic OHLCV builders for detector tests.
export const DAY = 86400;
// 2026-01-05 00:00 IST (Monday) as unix seconds
export const T0 = Date.parse('2026-01-04T18:30:00Z') / 1000;

// Piecewise-linear closes through [index, value] knots.
export function wave(knots) {
  const out = [];
  for (let k = 0; k < knots.length - 1; k++) {
    const [i0, v0] = knots[k];
    const [i1, v1] = knots[k + 1];
    for (let i = i0; i < i1; i++) out.push(v0 + ((v1 - v0) * (i - i0)) / (i1 - i0));
  }
  out.push(knots[knots.length - 1][1]);
  return out;
}

// Bars from closes: high/low = close +/- 0.5%, volume optional (number | fn(i)).
export function barsFrom(closes, { vol = 1000, step = DAY, start = T0 } = {}) {
  return closes.map((c, i) => ({
    time: start + i * step,
    open: i ? closes[i - 1] : c,
    high: c * 1.005,
    low: c * 0.995,
    close: c,
    volume: typeof vol === 'function' ? vol(i) : vol,
  }));
}
