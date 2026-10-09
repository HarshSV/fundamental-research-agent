// Pure helpers for the forecast overlay. No ML here: the backend returns the forecast, the
// frontend only maps it onto chart series. Forecast data never touches the actual-candle series.

import { rowStatus } from './forecastView.js';

export const FORECAST_COLORS = {
  up: 'rgb(16,185,129)',
  down: 'rgb(239,68,68)',
  neutral: 'rgb(148,163,184)',
  band80: 'rgba(96,165,250,0.85)',
  band50: 'rgba(96,165,250,0.5)',
};

const CONF_ORDER = { HIGH: 3, MEDIUM: 2, LOW: 1, NO_RELIABLE_FORECAST: 0 };
export const confidenceRank = (level) => CONF_ORDER[level] ?? 0;

export const confidenceLabel = (level) => ({
  HIGH: 'High', MEDIUM: 'Medium', LOW: 'Low', NO_RELIABLE_FORECAST: 'No reliable forecast',
}[level] || 'No reliable forecast');

// Time of the last COMPLETED candle on the chart. The provider's series includes the still-forming
// candle, which a forecast made "as of the last close" must not be anchored to.
export function lastCompletedTime(candles, nowSec = Date.now() / 1000, barSec = 300) {
  for (let i = (candles?.length || 0) - 1; i >= 0; i--) {
    if (candles[i].time + barSec <= nowSec) return candles[i].time;
  }
  return null;
}

// The forecast is only drawn when it was made from the chart's own last completed candle. Otherwise the
// boundary would be wrong and the forecast could imply a stale future.
export function forecastAligned(resp, lastActualTime) {
  const t = resp?.forecast?.current_candle?.time;
  return t != null && lastActualTime != null && t === lastActualTime;
}

// Maps an API response to chart series data. `candles` are predicted bars; `bands` are the
// uncertainty envelope lines. Returns empty arrays (never invented values) when nothing is usable.
export function toForecastSeries(resp, lastActualTime) {
  const empty = { candles: [], upper80: [], lower80: [], upper50: [], lower50: [], boundary: null, aligned: false };
  if (!resp || !Array.isArray(resp.forecastCandles)) return empty;
  const aligned = forecastAligned(resp, lastActualTime);
  if (!aligned) return empty;
  const strictlyAfter = (t) => t > lastActualTime;
  const candles = resp.forecastCandles
    .filter((c) => strictlyAfter(c.time) && [c.open, c.high, c.low, c.close].every(Number.isFinite))
    .map((c) => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close }))
    .sort((a, b) => a.time - b.time);
  const env = (resp.forecastEnvelope || []).filter((e) => strictlyAfter(e.time)).sort((a, b) => a.time - b.time);
  const line = (lv, idx) => env.filter((e) => Array.isArray(e.intervals?.[lv]) && Number.isFinite(e.intervals[lv][idx]))
    .map((e) => ({ time: e.time, value: e.intervals[lv][idx] }));
  return {
    candles,
    upper80: line('80', 1), lower80: line('80', 0),
    upper50: line('50', 1), lower50: line('50', 0),
    boundary: lastActualTime,
    aligned: true,
  };
}

export function forecastBarByTime(resp, time) {
  return (resp?.forecast?.forecasts || []).find((f) => f.forecast_timestamp === time) || null;
}

const pct = (x) => (x == null || !Number.isFinite(x) ? 'n/a' : `${(x * 100).toFixed(1)}%`);
const px = (x) => (x == null || !Number.isFinite(x) ? 'n/a' : x.toFixed(2));

// Tooltip lines for one forecast horizon. Wording never states a future price as fact.
export function describeForecastBar(f) {
  if (!f) return [];
  const lines = [`+${f.horizon} candle - FORECAST (not a historical value)`];
  if (f.close != null) {
    lines.push(`Predicted O ${px(f.open)}  H ${px(f.high)}  L ${px(f.low)}  C ${px(f.close)}`);
    lines.push(`P(close above current close): ${pct(f.direction_probability)}`);
  } else {
    lines.push(f.status === 'withheld' ? 'No forecast issued' : 'No directional call (range only)');
  }
  if (f.intervals) {
    for (const lv of ['50', '80', '95']) {
      if (f.intervals[lv]) lines.push(`${lv}% range: ${px(f.intervals[lv][0])} - ${px(f.intervals[lv][1])}`);
    }
  }
  // State-aware wording: a row with a range is NEVER "no reliable forecast".
  const rs = rowStatus(f);
  if (rs.key === 'range_only') lines.push('Range forecast available', 'Directional signal uncertain');
  else if (rs.key === 'unavailable') lines.push(`Forecast unavailable${rs.text && rs.text !== 'Unavailable' ? ` - ${rs.text}` : ''}`);
  else lines.push(`Confidence: ${rs.text}`);
  if (f.direction_validated === false) lines.push('Direction not validated out-of-sample for this horizon');
  if (f.reasons && f.reasons.length) lines.push(`Note: ${f.reasons.join(', ')}`);
  return lines;
}
