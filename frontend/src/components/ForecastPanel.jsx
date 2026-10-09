import React from 'react';
import ForecastChart from './ForecastChart.jsx';
import { summarize, rowStatus } from '../lib/forecastView.js';
import { istClock } from '../lib/marketTime.js';

const px = (x) => (Number.isFinite(x) ? `₹${x.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '-');
const pct = (x) => (Number.isFinite(x) ? `${(x * 100).toFixed(0)}%` : '-');

const BADGE = {
  high: 'text-emerald-300 border-emerald-500/50 bg-emerald-500/10',
  medium: 'text-amber-300 border-amber-500/50 bg-amber-500/10',
  low: 'text-slate-200 border-slate-500 bg-slate-500/10',
  range_only: 'text-blue-300 border-blue-500/50 bg-blue-500/10',
  loading: 'text-slate-300 border-slate-600 bg-slate-700/20',
  unavailable: 'text-slate-400 border-slate-700 bg-slate-800/40',
};
const DIR_TONE = { UP: 'text-emerald-300', DOWN: 'text-red-300', UNCERTAIN: 'text-slate-300' };

function Stat({ label, children, testid }) {
  return (
    <div className="min-w-0" data-testid={testid}>
      <div className="text-[9px] font-semibold uppercase tracking-wider text-slate-500">{label}</div>
      <div className="text-[13px] text-slate-100 nv-num">{children}</div>
    </div>
  );
}

// FORECAST panel: summary card (status, direction, expected range, confidence, as-of, model), the forecast
// chart, and a supporting per-horizon table. Presentation only - values come straight from the backend.
export default function ForecastPanel({ resp, loading, error }) {
  const s = summarize(resp, loading, error);
  const st = s.state;
  const rows = resp?.forecast?.forecasts || [];
  const showChart = st.key !== 'loading' && st.key !== 'unavailable';
  return (
    <section className="min-w-0" data-testid="forecast-panel" aria-label="Forecast">
      <div className="mb-1.5">
        <div className="text-[11px] font-bold uppercase tracking-widest text-blue-300">Forecast</div>
        <div className="text-[11px] text-slate-500">Model projection &bull; next 5 &times; 5-minute candles</div>
      </div>

      <div className="rounded-md border border-slate-800 bg-slate-900/50 p-3 mb-2" data-testid="forecast-summary">
        <div className="flex flex-wrap items-center gap-2 mb-2">
          <span className={`rounded border px-2 py-0.5 text-[12px] font-semibold ${BADGE[st.key] || BADGE.unavailable}`} data-testid="forecast-status">
            {st.title}
          </span>
          {st.subtitle && <span className="text-[11px] text-slate-400" data-testid="forecast-substatus">{st.subtitle}</span>}
          {st.detail && <span className="text-[10px] text-slate-500" data-testid="forecast-detail">({st.detail})</span>}
        </div>
        {(st.key === 'loading' || st.key === 'unavailable') ? null : (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2">
            <Stat label="Direction" testid="sum-direction">
              <span className={`font-semibold ${DIR_TONE[s.direction.label]}`}>{s.direction.label}</span>
              {s.direction.detail && <div className="text-[10px] text-slate-500">{s.direction.detail}</div>}
            </Stat>
            <Stat label="Expected range (80%)" testid="sum-range">
              {s.near ? <>{px(s.near.lo)} &ndash; {px(s.near.hi)} <span className="text-[10px] text-slate-500">at +{s.near.h}</span></> : '-'}
              {s.far && <div className="text-[10px] text-slate-500">{px(s.far.lo)} &ndash; {px(s.far.hi)} at +{s.far.h}</div>}
            </Stat>
            <Stat label="Confidence" testid="sum-confidence">{st.key === 'range_only' ? 'Range only' : st.title.replace(' confidence', '')}</Stat>
            <Stat label="Reference price">{px(s.reference)}</Stat>
            <Stat label="As of">{s.asOf != null ? `${istClock(s.asOf)} IST` : '-'}</Stat>
            <Stat label="Model" testid="sum-model"><span className="text-[11px]">{s.model || '-'}</span></Stat>
          </div>
        )}
      </div>

      <div className="relative h-[340px] rounded-md border border-slate-800 bg-slate-900/30" data-testid="forecast-chart-wrap">
        {showChart && <ForecastChart resp={resp} />}
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
          <table className="w-full min-w-[460px] text-[11px] nv-num whitespace-nowrap" data-testid="forecast-table">
            <thead>
              <tr className="text-slate-500 text-left">
                <th className="pr-2 font-normal">Candle</th>
                <th className="pr-2 font-normal">Time</th>
                <th className="pr-2 font-normal">Pred. close</th>
                <th className="pr-2 font-normal">High / Low</th>
                <th className="pr-2 font-normal">P(up)</th>
                <th className="pr-2 font-normal">80% range</th>
                <th className="font-normal">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const rs = rowStatus(r);
                return (
                  <tr key={r.horizon} className="text-slate-300" data-testid={`row-${r.horizon}`}>
                    <td className="pr-2">+{r.horizon}</td>
                    <td className="pr-2">{istClock(r.forecast_timestamp)}</td>
                    <td className="pr-2">{Number.isFinite(r.close) ? px(r.close) : '-'}</td>
                    <td className="pr-2">{Number.isFinite(r.high) && Number.isFinite(r.low) ? `${r.high.toFixed(2)} / ${r.low.toFixed(2)}` : '-'}</td>
                    <td className="pr-2">{Number.isFinite(r.direction_probability) ? pct(r.direction_probability) : '-'}</td>
                    <td className="pr-2">{r.intervals?.['80'] ? `${r.intervals['80'][0].toFixed(2)} - ${r.intervals['80'][1].toFixed(2)}` : '-'}</td>
                    <td><span className={`rounded border px-1.5 py-0.5 ${BADGE[rs.key] || BADGE.unavailable}`}>{rs.text}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {showChart && <div className="mt-1.5 text-[10px] text-slate-500">{resp?.forecast?.disclaimer}</div>}
    </section>
  );
}
