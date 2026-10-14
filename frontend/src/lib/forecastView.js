// Presentation logic for the forecast panel. PURE: it only re-labels and re-shapes what the backend already
// returned. It never computes, smooths, defaults or invents a forecast value, and never changes confidence.

const CONF_LABEL = { LOW: 'Low confidence', MEDIUM: 'Medium confidence', HIGH: 'High confidence' };
const CONF_KEY = { LOW: 'low', MEDIUM: 'medium', HIGH: 'high' };

const REASON_TEXT = {
  horizon_beyond_session_end: 'Beyond the session close',
  input_outside_training_distribution: "Input outside the model's supported range",
  confidence_below_threshold: 'Directional signal uncertain',
  direction_not_validated_for_symbol: 'Direction not validated for this symbol',
};

export const SESSION_ENDED_TEXT = 'Market session ended - forecasts cover 09:20 to 15:10 IST on trading days and resume at the next open';

export const friendlyReason = (r) => {
  if (!r) return null;
  const k = String(r).split(':')[0];
  if (k === 'data_not_usable') return 'Latest market data is not up to date yet - the forecast service is catching up and will retry automatically';
  if (k === 'symbol_not_validated') return `Not validated for forecasting - ${String(r).slice(k.length + 1).trim()}`;
  return REASON_TEXT[k] || String(r);
};

const hasInterval = (r) => !!r && r.intervals && Object.values(r.intervals).some((v) => Array.isArray(v) && v.every(Number.isFinite));
const hasCandle = (r) => !!r && r.status === 'ok' && [r.open, r.high, r.low, r.close].every(Number.isFinite);

// The single mapping from the backend response to the status the user sees.
//   key        title                         when
//   loading    Generating forecast...        no response yet, or the backend is still fetching the latest candle
//   unavailable Forecast unavailable         request failed / no forecast values exist (reason shown if the backend gave one)
//   range_only Range forecast available      intervals exist but no directional candle is issued (subtitle: Directional signal uncertain)
//   low|medium|high  <Level> confidence      a directional forecast exists (level = the backend's own confidence)
export function forecastState({ resp, loading = false, error = null } = {}) {
  if (resp?.status === 'ERROR') {
    return { key: 'unavailable', title: 'Forecast unavailable', subtitle: null, detail: `Forecast service error: ${resp.error || 'unknown'}` };
  }
  const f = resp?.forecast;
  const rows = f?.forecasts || [];
  const candleRows = rows.filter(hasCandle);
  const rangeRows = rows.filter(hasInterval);
  if (candleRows.length) {
    const lead = candleRows[0];
    const key = CONF_KEY[lead.confidence];
    if (key) {
      return { key, title: CONF_LABEL[lead.confidence], subtitle: rangeRows.length ? 'Range forecast also available' : null, detail: null };
    }
  }
  if (rangeRows.length) {
    return { key: 'range_only', title: 'Range forecast available', subtitle: 'Directional signal uncertain', detail: null };
  }
  if (!resp) {
    return loading
      ? { key: 'loading', title: 'Generating forecast...', subtitle: null, detail: null }
      : { key: 'unavailable', title: 'Forecast unavailable', subtitle: null, detail: error ? `Forecast service did not respond (${error})` : 'Forecast service did not respond' };
  }
  if (loading || resp.refreshing) {
    return { key: 'loading', title: 'Generating forecast...', subtitle: null, detail: null };
  }
  // Every horizon would run past the last usable bar (15:10 IST): the session is over, not the service broken.
  if (rows.length && rows.every((r) => (r.reasons || []).some((x) => String(x).startsWith('horizon_beyond_session_end')))) {
    return { key: 'unavailable', title: 'Forecast unavailable', subtitle: null, detail: SESSION_ENDED_TEXT };
  }
  const reason = friendlyReason((f?.reasons || [])[0] || (rows[0]?.reasons || [])[0]);
  return { key: 'unavailable', title: 'Forecast unavailable', subtitle: null, detail: reason || 'Model output unavailable' };
}

// Per-horizon wording for the supporting table. Never says "No reliable forecast" for a row that has a range.
export function rowStatus(r) {
  if (hasCandle(r) && CONF_LABEL[r.confidence]) return { key: CONF_KEY[r.confidence], text: CONF_LABEL[r.confidence] };
  if (hasInterval(r)) return { key: 'range_only', text: 'Range only' };
  return { key: 'unavailable', text: friendlyReason((r?.reasons || [])[0]) || 'Unavailable' };
}

const rangeOf = (r, lv = '80') => (r?.intervals?.[lv] && r.intervals[lv].every(Number.isFinite) ? r.intervals[lv] : null);

// Values for the summary card. Missing values stay null (rendered as "-"); a missing probability is never a 50%.
export function summarize(resp, loading = false, error = null) {
  const f = resp?.forecast;
  const rows = f?.forecasts || [];
  const lead = rows.find(hasCandle) || null;
  const near = rows.find((r) => rangeOf(r)) || null;
  const far = [...rows].reverse().find((r) => rangeOf(r)) || null;
  let direction = { label: 'UNCERTAIN', detail: null };
  if (lead && Number.isFinite(lead.direction_probability)) {
    const p = lead.direction_probability;
    direction = { label: p >= 0.5 ? 'UP' : 'DOWN', detail: `P(up) ${(p * 100).toFixed(0)}% at +${lead.horizon}` };
  }
  return {
    state: forecastState({ resp, loading, error }),
    direction,
    near: near ? { h: near.horizon, lo: rangeOf(near)[0], hi: rangeOf(near)[1] } : null,
    far: far && far !== near ? { h: far.horizon, lo: rangeOf(far)[0], hi: rangeOf(far)[1] } : null,
    asOf: f?.as_of_ts ?? null,
    model: f?.model_version ?? null,
    reference: Number.isFinite(f?.current_candle?.close) ? f.current_candle.close : null,
    regime: f?.regime ?? null,
  };
}

// Chart data for the FORECAST panel: a short actual-candle context ending at the reference candle, the NOW
// boundary, predicted candles (only where the backend issued one), and nested 50/80/95% bands (only where it
// issued intervals). Nothing is interpolated or filled in.
export function buildForecastChart(resp, nContext = 5) {
  const f = resp?.forecast;
  const cc = f?.current_candle;
  if (!f || !cc || ![cc.open, cc.high, cc.low, cc.close].every(Number.isFinite)) return null;
  let actual = (resp.actualCandles || [])
    .filter((c) => c.time <= cc.time && [c.open, c.high, c.low, c.close].every(Number.isFinite))
    .slice(-nContext)
    .map((c) => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close }));
  if (!actual.length || actual[actual.length - 1].time !== cc.time) {
    actual = [...actual, { time: cc.time, open: cc.open, high: cc.high, low: cc.low, close: cc.close }];
  }
  const rows = (f.forecasts || []).slice().sort((a, b) => a.horizon - b.horizon);
  const origin = { time: cc.time, price: cc.close };
  const candles = (resp.forecastCandles || [])
    .filter((c) => c.time > cc.time && [c.open, c.high, c.low, c.close].every(Number.isFinite))
    .map((c) => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close }))
    .sort((a, b) => a.time - b.time);
  const medianCandles = (resp.medianPath || [])
    .filter((c) => c.time > cc.time && [c.open, c.high, c.low, c.close].every(Number.isFinite))
    .map((c) => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close }))
    .sort((a, b) => a.time - b.time);
  const band = (lv) => {
    const pts = rows.filter((r) => rangeOf(r, lv)).map((r) => ({ time: r.forecast_timestamp, lo: rangeOf(r, lv)[0], hi: rangeOf(r, lv)[1], h: r.horizon }));
    return pts.length ? [{ time: origin.time, lo: origin.price, hi: origin.price, h: 0 }, ...pts] : [];
  };
  return {
    actual, origin, candles, medianCandles, predicted: forecastCandleRows(resp),
    bands: { 95: band('95'), 80: band('80'), 50: band('50') },
    horizons: rows.map((r) => ({ time: r.forecast_timestamp, h: r.horizon })),
    key: `${f.symbol}|${f.as_of_ts}|${f.model_version}`,
  };
}

// Candlestick-pattern section of the forecast panel. Presentation mapping only: the backend decides what was
// detected. A model-implied pattern never carries a probability; historical statistics (observed patterns only)
// appear only when the backend supplied enough observations.
export function patternView(resp) {
  const pf = resp && resp.patternForecast;
  if (!pf) return { state: 'none', reason: 'Pattern prediction unavailable', items: [], observed: [] };
  const label = (s) => String(s).replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());
  const items = (pf.patterns || []).map((p) => ({
    key: `${p.pattern}-${p.formation_horizon}`, name: label(p.pattern), direction: p.direction,
    within: p.formation_horizon, pathKind: p.path_kind || null, evidence: p.evidence, definition: p.definition,
    reliability: null, // a future pattern has no measured reliability; observed-pattern statistics do not transfer
  }));
  const observed = (pf.observed || []).map((o) => {
    const h = o.historical && o.historical.horizons && o.historical.horizons['1'];
    return {
      key: `${o.pattern}-${o.time}`, name: label(o.pattern), direction: o.direction,
      history: h ? {
        n: h.n, pUp: h.p_up, baseUp: h.base_p_up, meanReturn: h.mean_return,
      } : null,
    };
  });
  const state = pf.status === 'model_implied' ? 'model_implied' : pf.status === 'none_detected' ? 'none_detected' : 'unavailable';
  return { state, reason: pf.reason || null, items, observed, methodology: pf.methodology || null };
}

// Plain-English reading of the forecast for non-specialists. Wording only - every number comes from `summarize`.
export function plainSummary(resp, loading = false, error = null) {
  const s = summarize(resp, loading, error);
  if (s.state.key === 'loading' || s.state.key === 'unavailable' || !s.reference) return null;
  const rows = resp?.forecast?.forecasts || [];
  const end = s.far || s.near;
  if (!end) return null;
  const rs = rows.find((r) => r.horizon === end.h);
  const rupee = (x) => `₹${x.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const upto = Number.isFinite(rs?.forecast_timestamp) ? ` (by ${new Date((rs.forecast_timestamp + 300) * 1000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata', hour12: true }).toUpperCase()})` : '';
  const lean = s.direction.label === 'UP' ? 'The model leans slightly upward.'
    : s.direction.label === 'DOWN' ? 'The model leans slightly downward.'
      : 'The model sees no clear upward or downward lean.';
  const fb = resp?.forecast?.fallback;
  const madeAt = fb && Number.isFinite(fb.as_of_ts) ? new Date(fb.as_of_ts * 1000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata', hour12: true }).toUpperCase() : null;
  return {
    experimentalNote: resp?.forecast?.experimental ? `Experimental: this stock has not passed forecast validation (${(resp.forecast.experimental.reasons || []).join('; ') || 'insufficient clean data'}). The range comes from the general model and has not been checked for this company - it may be too narrow or too wide.` : null,
    fallbackNote: fb ? `Showing the last forecast made at ${madeAt} IST. Live forecasts run 09:20 to 15:10 IST and resume at the next market open.` : null,
    headline: `${fb ? `Last forecast (made ${madeAt}): next` : 'Next'} ${end.h} candle${end.h > 1 ? 's' : ''}${upto}: most likely between ${rupee(end.lo)} and ${rupee(end.hi)}`,
    now: `Now ${rupee(s.reference)}`,
    lean,
    odds: resp?.forecast?.experimental
      ? 'Nominal 80% range from the general model - NOT verified for this stock, so the real chance may be lower.'
      : 'About 8 in 10 chance the price stays inside this range (measured on past data).',
  };
}


// ---- predicted candles (one unified, validated list per horizon) ------------------------------------------
export function validOhlc(c) {
  if (!c) return false;
  const { open: o, high: h, low: l, close: cl } = c;
  return [o, h, l, cl].every((v) => Number.isFinite(v) && v > 0) && h >= Math.max(o, cl) && l <= Math.min(o, cl) && h >= l;
}

// One predicted candle per horizon: the model-issued candle when the confidence gate allowed it, else the model's
// median-return candle (kind 'median'). Invalid OHLC and anything not strictly after the last actual candle is dropped -
// nothing is ever invented to fill a gap.
export function forecastCandleRows(resp) {
  const f = resp?.forecast;
  const cc = f?.current_candle;
  if (!f || !cc) return [];
  const out = [];
  for (const r of f.forecasts || []) {
    const kind = Number.isFinite(r.close) ? 'issued' : (r.median_path ? 'median' : null);
    if (!kind) continue;
    const src = kind === 'issued' ? r : r.median_path;
    const c = { open: src.open, high: src.high, low: src.low, close: src.close };
    if (!validOhlc(c) || !(r.forecast_timestamp > cc.time)) continue;
    out.push({ h: r.horizon, time: r.forecast_timestamp, ...c, kind, status: r.status, intervals: r.intervals || null,
      tone: c.close > c.open ? 'up' : c.close < c.open ? 'down' : 'flat' });
  }
  return out.sort((a, b) => a.time - b.time);
}

const TONE = { up: ['52,211,153', 'rgb(52 211 153)'], down: ['248,113,113', 'rgb(248 113 113)'], flat: ['148,163,184', 'rgb(148 163 184)'] };
// Chart data points with per-candle colours: green up, red down, grey flat; hollow (outlined) so they never look like
// actual candles; the selected one is filled.
export function styledForecastCandles(rows, selectedH = null) {
  return rows.map((r) => {
    const [fill, edge] = TONE[r.tone];
    return { time: r.time, open: r.open, high: r.high, low: r.low, close: r.close,
      color: `rgba(${fill},${r.h === selectedH ? 0.65 : 0.08})`, borderColor: edge, wickColor: edge };
  });
}
