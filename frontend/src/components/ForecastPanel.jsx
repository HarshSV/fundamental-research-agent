import React, { useState } from 'react';
import ForecastChart from './ForecastChart.jsx';
import { summarize, patternView, plainSummary, forecastCandleRows } from '../lib/forecastView.js';
import { istClock } from '../lib/marketTime.js';

const px = (x) => (Number.isFinite(x) ? `₹${x.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '-');


// FORECAST panel: summary card (status, direction, expected range, confidence, as-of, model), the forecast
// chart, and a supporting per-horizon table. Presentation only - values come straight from the backend.
export default function ForecastPanel({ resp, loading, error }) {
  const s = summarize(resp, loading, error);
  const st = s.state;
  const rows = resp?.forecast?.forecasts || [];
  const [viewPick, setViewPick] = useState(null);   // null = automatic default
  const [selectedH, setSelectedH] = useState(null);
  const cand = forecastCandleRows(resp);
  const byH = new Map(cand.map((c) => [c.h, c]));
  const view = viewPick || (cand.length ? 'candles' : 'bands');   // candles by default when valid predicted OHLC exists
  const plain = plainSummary(resp, loading, error);
  const pv = patternView(resp);
  const showChart = st.key !== 'loading' && st.key !== 'unavailable';
  return (
    <section className="min-w-0" data-testid="forecast-panel" aria-label="Forecast">
      <div className="mb-1.5">
        <div className="text-[11px] font-bold uppercase tracking-widest text-blue-300">Forecast</div>
        <div className="text-[11px] text-slate-500">Model projection &bull; next 5 &times; 5-minute candles</div>
      </div>

      {(st.key === 'loading' || st.key === 'unavailable') ? null : (
        <div className="mb-2 text-[10px] text-slate-500" data-testid="forecast-summary">
          As of {s.asOf != null ? `${istClock(s.asOf)} IST` : '-'}{s.model ? ` · model ${s.model}` : ''}
        </div>
      )}
      {plain && (
        <div className="rounded-md border border-blue-500/30 bg-blue-500/5 p-3 mb-2" data-testid="plain-summary">
          <div className="text-[13px] font-semibold text-slate-100">{plain.headline}</div>
          <div className="text-[12px] text-slate-300">{plain.now}. {plain.lean}</div>
          <div className="text-[11px] text-slate-500">{plain.odds}</div>
        </div>
      )}
      {showChart && (
        <div className="mb-1 flex justify-end gap-1" role="tablist" aria-label="Forecast view">
          {[['candles', 'Predicted Candles'], ['bands', 'Uncertainty Bands']].map(([k, label]) => (
            <button key={k} role="tab" aria-selected={view === k} onClick={() => setViewPick(k)} data-testid={`view-${k}`}
              className={`rounded border px-2 py-0.5 text-[10px] ${view === k ? 'border-blue-500/50 bg-blue-500/20 text-blue-300' : 'border-slate-700 text-slate-400 hover:text-slate-200'}`}>
              {label}
            </button>
          ))}
        </div>
      )}
      <div className="relative h-[340px] rounded-md border border-slate-800 bg-slate-900/30" data-testid="forecast-chart-wrap">
        {showChart && <ForecastChart resp={resp} view={view} selectedH={selectedH} />}
        {showChart && view === 'candles' && cand.length === 0 && (
          <div className="absolute inset-x-0 top-2 text-center text-[11px] text-slate-400" data-testid="no-candles">
            No predicted candles for this forecast (the model gave no valid OHLC). Switch to Uncertainty Bands.
          </div>
        )}
        {st.key === 'loading' && (
          <div className="absolute inset-0 flex items-center justify-center text-[12px] text-slate-400 italic" data-testid="forecast-loading">Generating forecast...</div>
        )}
        {st.key === 'unavailable' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-center px-4" data-testid="forecast-unavailable">
            <div className="text-[13px] text-slate-300">Forecast unavailable</div>
            {st.detail && <div className="text-[11px] text-slate-500">{st.detail}</div>}
          </div>
        )}
      </div>

      {showChart && (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[520px] text-[11px] nv-num whitespace-nowrap" data-testid="forecast-table">
            <thead>
              <tr className="text-slate-500 text-left">
                <th className="pr-2 font-normal">Candle</th>
                <th className="pr-2 font-normal">Time</th>
                <th className="pr-2 font-normal">Open</th>
                <th className="pr-2 font-normal">High</th>
                <th className="pr-2 font-normal">Low</th>
                <th className="pr-2 font-normal">Close</th>
                <th className="pr-2 font-normal">80% range</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const c = byH.get(r.horizon);
                const sel = selectedH === r.horizon;
                const v = (x) => (c ? x.toFixed(2) : '-');
                return (
                  <tr key={r.horizon} onClick={() => c && setSelectedH(sel ? null : r.horizon)} data-testid={`row-${r.horizon}`}
                    className={`text-slate-300 ${c ? 'cursor-pointer hover:bg-slate-800/60' : ''} ${sel ? 'bg-blue-500/10' : ''}`}>
                    <td className="pr-2">+{r.horizon}</td>
                    <td className="pr-2">{istClock(r.forecast_timestamp)}</td>
                    <td className="pr-2">{c ? v(c.open) : '-'}</td>
                    <td className="pr-2">{c ? v(c.high) : '-'}</td>
                    <td className="pr-2">{c ? v(c.low) : '-'}</td>
                    <td className="pr-2">{c ? v(c.close) : '-'}{c && c.kind === 'median' && <span className="text-amber-300/80" title="Median-return path: central estimate, not a directional call"> ~</span>}</td>
                    <td className="pr-2">{r.intervals?.['80'] ? `${r.intervals['80'][0].toFixed(2)} - ${r.intervals['80'][1].toFixed(2)}` : '-'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {showChart && cand.length > 0 && (
        <div className="mt-1.5 text-[10px] text-amber-300/80" data-testid="median-note">
          Predicted candles are model estimates, not market prices. Candles marked ~ are the model's median-return path: a central estimate with no validated directional call. Click a table row to highlight its candle.
        </div>
      )}
      {showChart && (
        <div className="mt-2 rounded-md border border-slate-800 bg-slate-900/50 p-3" data-testid="pattern-section">
          <div className="text-[9px] font-semibold uppercase tracking-wider text-slate-500 mb-1">Candlestick patterns</div>
          {pv.items.length === 0 && (
            <div className="text-[11px] text-slate-400" data-testid="pattern-unavailable">{pv.reason || 'Pattern prediction unavailable'}</div>
          )}
          {pv.items.map((p) => (
            <div key={p.key} className="mb-1.5 text-[12px]" data-testid="pattern-item">
              <div className="text-slate-100">
                <span title={p.definition}>{p.name}</span>
                <span className="ml-2 rounded border border-slate-600 px-1.5 text-[10px] text-slate-300" title="One deterministic reading of the single predicted path - not a statistical probability.">{p.pathKind === 'median_return_path' ? 'median-path reading' : 'model-implied'}</span>
                <span className="ml-2 text-[10px] text-slate-500">{p.direction}</span>
              </div>
              <div className="text-[11px] text-slate-400">Expected formation: at candle +{p.within}</div>
              <div className="text-[11px] text-slate-500">{p.evidence}</div>
              <div className="text-[10px] text-slate-600">Reliability: not measured for future patterns.</div>
            </div>
          ))}
          {pv.observed.length > 0 && (
            <div className="mt-1 border-t border-slate-800 pt-1.5" data-testid="pattern-observed">
              <div className="text-[10px] text-slate-500 mb-0.5">Observed on the last actual candle</div>
              {pv.observed.map((o) => (
                <div key={o.key} className="text-[11px] text-slate-300">
                  {o.name} <span className="text-slate-500">({o.direction})</span>
                  {o.history && (
                    <span className="ml-2 text-[10px] text-slate-500" title="Historical, observed patterns only; says nothing about whether a forecast pattern will form.">
                      history (n={o.history.n}): next-candle up {Math.round(o.history.pUp * 100)}% vs {Math.round(o.history.baseUp * 100)}% unconditional
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
          <div className="mt-1.5 text-[10px] text-slate-600">A pattern describes candle shape; it is not a trade signal.</div>
        </div>
      )}
      {showChart && <div className="mt-1.5 text-[10px] text-slate-500">{resp?.forecast?.disclaimer}</div>}
    </section>
  );
}
