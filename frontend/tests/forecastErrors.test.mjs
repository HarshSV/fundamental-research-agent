import test from 'node:test';
import assert from 'node:assert/strict';
import { forecastState, summarize, SESSION_ENDED_TEXT } from '../src/lib/forecastView.js';
import { describeForecastBar } from '../src/lib/forecast.js';

test('request failures say why; a structured backend error is shown; neither is "No reliable forecast"', () => {
  const s = forecastState({ resp: null, loading: false, error: 'HTTP 500' });
  assert.equal(s.title, 'Forecast unavailable');
  assert.match(s.detail, /\(HTTP 500\)/);
  const e = forecastState({ resp: { status: 'ERROR', error: 'OSError: model file missing', forecast: null } });
  assert.equal(e.key, 'unavailable');
  assert.match(e.detail, /Forecast service error: OSError/);
  assert.doesNotMatch(JSON.stringify([s, e]), /No reliable/i);
  assert.equal(summarize({ status: 'ERROR', error: 'x', forecast: null }).direction.label, 'UNCERTAIN'); // no crash on a null forecast
});

test('session expiry and network errors are distinguishable', () => {
  assert.match(forecastState({ resp: null, error: 'session expired - sign in again' }).detail, /session expired/);
  assert.match(forecastState({ resp: null, error: 'network error' }).detail, /network error/);
  assert.equal(forecastState({ resp: null, loading: true }).title, 'Generating forecast...');
});

test('after the session every horizon is beyond the close: explained as "session ended", not a mystery code', () => {
  const T = 1_800_000_000;
  const rows = [1, 2, 3, 4, 5].map((h) => ({ horizon: h, forecast_timestamp: T + h * 300, status: 'withheld', confidence: 'NO_RELIABLE_FORECAST', reasons: ['horizon_beyond_session_end'] }));
  const s = forecastState({ resp: { status: 'NO_RELIABLE_FORECAST', refreshing: false, forecast: { forecasts: rows, reasons: [] } } });
  assert.equal(s.title, 'Forecast unavailable');
  assert.equal(s.detail, SESSION_ENDED_TEXT);
  assert.match(s.detail, /resume at the next open/);
  assert.doesNotMatch(s.detail, /Beyond the session close/);
});

test('hover tooltip never says "No reliable forecast" for a range row', () => {
  const range = { horizon: 1, status: 'range_only', confidence: 'NO_RELIABLE_FORECAST', intervals: { 80: [99, 103] } };
  const t = describeForecastBar(range).join(' | ');
  assert.match(t, /Range forecast available/);
  assert.match(t, /Directional signal uncertain/);
  assert.doesNotMatch(t, /No reliable/i);
  const none = describeForecastBar({ horizon: 2, status: 'withheld', confidence: 'NO_RELIABLE_FORECAST', reasons: ['horizon_beyond_session_end'] }).join(' | ');
  assert.match(none, /Forecast unavailable/);
  assert.doesNotMatch(none, /No reliable/i);
  const low = describeForecastBar({ horizon: 1, status: 'ok', confidence: 'LOW', open: 1, high: 2, low: 0.5, close: 1.5, direction_probability: 0.55 }).join(' | ');
  assert.match(low, /Confidence: Low confidence/);
});
