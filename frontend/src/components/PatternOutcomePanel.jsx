import React from 'react';
import { BIAS_STYLE, BIAS_DISCLAIMER, TIMEFRAME_BARS, horizonRow, outcomeBadge, horizonLabel } from '../lib/patternOutcomeView.js';
import { biasText, classificationById } from '../lib/patternClassification.js';
import { fmtDate, fmtDayMonth } from '../lib/marketTime.js';

const BREAKOUT_TEXT = {
  up: 'Closed above the pattern range', down: 'Closed below the pattern range', none: 'No close beyond the pattern range',
  pending: 'Breakout check pending', unavailable: 'Breakout check unavailable',
};

// Selected-pattern detail: conventional BIAS (stated separately) + realised OUTCOME statistics + recent occurrences.
// Every number comes from real candles via patternHistory/patternOutcomes; nothing here is computed from the bias.
export default function PatternOutcomePanel({ entry, stats, symbol, loading }) {
  const cls = classificationById.get(entry.id);
  const bias = BIAS_STYLE[cls ? cls.bias : 'unknown'];
  const tf = entry.timeframe;
  const fmtDay = (t) => (tf === 'intraday' ? `${fmtDate(t)}` : fmtDayMonth(t));
  return (
    <div className="mt-2 rounded-md border border-slate-800 bg-slate-900/40 px-3 py-2 text-[11px]" data-testid="pattern-outcomes">
      <div className="flex flex-wrap items-baseline gap-x-2" data-testid="pattern-bias">
        <span className="text-[9px] font-semibold uppercase tracking-wider text-slate-500">Pattern bias</span>
        <span className={`font-semibold ${bias.text}`}>{bias.glyph} {cls ? biasText({ bias: cls.bias, requiresConfirmation: cls.confirmation !== 'none' }) : 'Bias unknown'}</span>
        <span className="text-slate-500">{BIAS_DISCLAIMER}</span>
      </div>
      {cls?.note && <div className="text-slate-500" data-testid="pattern-bias-note">{cls.note}</div>}

      <div className="mt-2 text-[9px] font-semibold uppercase tracking-wider text-slate-500">Realised historical outcomes</div>
      {loading && <div className="italic text-slate-500">Computing outcomes from {tf} history...</div>}
      {!loading && !stats && <div className="italic text-slate-500">No {tf} data loaded for this stock, so no outcomes can be calculated.</div>}
      {!loading && stats && (
        <>
          <div className="text-slate-500" data-testid="outcome-basis">
            {symbol} only - {TIMEFRAME_BARS[tf]}: {stats.sample.bars.toLocaleString('en-IN')} bars
            {stats.sample.from != null && <> ({fmtDate(stats.sample.from)} to {fmtDate(stats.sample.to)})</>}.
            {' '}Outcome = close[t+h] / close[t] − 1, t = the bar where the pattern was first detected. Flat band = max({(stats.config.floor * 100).toFixed(2)}%, {stats.config.k} × σ{stats.config.volLookback} × √h).
          </div>
          {tf !== 'intraday' && (
            <div className="text-slate-500" data-testid="window-note">
              The chip count above only covers formations inside the loaded intraday window; these statistics use this stock's full {tf} history, so they can be larger.
            </div>
          )}
          <div className="mt-1.5 overflow-x-auto">
            <table className="w-full whitespace-nowrap nv-num" data-testid="outcome-table">
              <thead>
                <tr className="text-left text-slate-500">
                  <th className="pr-3 font-normal">Horizon</th>
                  <th className="pr-3 font-normal" title="Independent (non-overlapping) completed observations">n</th>
                  <th className="pr-3 font-normal text-emerald-400/80">Positive</th>
                  <th className="pr-3 font-normal text-red-400/80">Negative</th>
                  <th className="pr-3 font-normal text-slate-400">Flat</th>
                  <th className="pr-3 font-normal" title="Positive / evaluable">Pos. rate</th>
                  <th className="pr-3 font-normal" title="Same rule applied to every bar of the series">Base rate</th>
                  <th className="pr-3 font-normal">Avg</th>
                  <th className="pr-3 font-normal">Median</th>
                  <th className="pr-3 font-normal text-sky-300/80">Pending</th>
                  <th className="font-normal text-slate-500">Not evaluable</th>
                </tr>
              </thead>
              <tbody>
                {stats.horizons.map((hz) => {
                  const r = horizonRow(hz, tf);
                  return (
                    <React.Fragment key={hz.horizon}>
                      <tr className="text-slate-300" data-testid={`outcome-row-${hz.horizon}`}>
                        <td className="pr-3">{r.label}</td>
                        <td className="pr-3">{r.n}</td>
                        <td className="pr-3 text-emerald-300">{r.positive}</td>
                        <td className="pr-3 text-red-300">{r.negative}</td>
                        <td className="pr-3 text-slate-400">{r.flat}</td>
                        <td className="pr-3">{r.positiveRate}</td>
                        <td className="pr-3 text-slate-500">{r.baseRate}</td>
                        <td className="pr-3">{r.mean}</td>
                        <td className="pr-3">{r.median}</td>
                        <td className="pr-3 text-sky-300">{r.pending}</td>
                        <td className="text-slate-500 italic">{r.notEvaluable}</td>
                      </tr>
                      {r.warning && (
                        <tr><td colSpan={11} className="pb-1 text-[10px] text-amber-300/80" data-testid={`outcome-warning-${hz.horizon}`}>{r.label}: {r.warning}</td></tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="mt-1 text-[10px] text-slate-500">
            n counts independent observations only (a later occurrence whose forward window overlaps an earlier one is skipped). Pending and not-evaluable
            occurrences are excluded from every rate and average. These are historical frequencies for one stock - not accuracy or a forecast.
          </div>

          <div className="mt-2 text-[9px] font-semibold uppercase tracking-wider text-slate-500">Recent occurrences</div>
          {stats.occurrences.length === 0 && <div className="italic text-slate-500">No {entry.displayName} detected in the loaded {tf} history.</div>}
          <div className="space-y-1">
            {[...stats.occurrences].reverse().slice(0, 8).map((o) => (
              <div key={o.id} className="flex flex-wrap items-center gap-x-2 gap-y-0.5" data-testid="occurrence-row">
                <span className="text-slate-400 nv-num">{fmtDay(o.confirmedAt)}</span>
                <span className={BIAS_STYLE[o.classification.bias].text} title={o.classification.basis}>{BIAS_STYLE[o.classification.bias].glyph} {biasText(o.classification)}</span>
                {Object.entries(o.outcomes).map(([h, x]) => {
                  const b = outcomeBadge(x, tf, Number(h));
                  return <span key={h} title={b.title} className={`rounded px-1.5 py-px nv-num ${b.chip}`} data-testid={`occ-outcome-${b.state}`}>{b.text}</span>;
                })}
                <span className="text-slate-500" title="Observed AFTER detection (realised), not part of the bias">{BREAKOUT_TEXT[o.breakout?.state] || ''}</span>
              </div>
            ))}
          </div>
          {stats.occurrences.length > 8 && <div className="mt-0.5 text-[10px] text-slate-500">Showing the 8 most recent of {stats.occurrences.length} formations.</div>}
        </>
      )}
    </div>
  );
}

export { horizonLabel };
