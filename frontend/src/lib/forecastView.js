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
  const band = (lv) => {
    const pts = rows.filter((r) => rangeOf(r, lv)).map((r) => ({ time: r.forecast_timestamp, lo: rangeOf(r, lv)[0], hi: rangeOf(r, lv)[1], h: r.horizon }));
    return pts.length ? [{ time: origin.time, lo: origin.price, hi: origin.price, h: 0 }, ...pts] : [];
  };
  return {
    actual, origin, candles,
    bands: { 95: band('95'), 80: band('80'), 50: band('50') },
    horizons: rows.map((r) => ({ time: r.forecast_timestamp, h: r.horizon })),
    key: `${f.symbol}|${f.as_of_ts}|${f.model_version}`,
  };
}
