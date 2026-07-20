import React, { useEffect, useState } from 'react';
import { authFetch } from '../../lib/api.js';
import { inr, inrCrore, isNum } from '../../lib/format.js';
import { getNseSector } from '../../lib/nseSectorMap.js';

const I = ({ children, s = 16 }) => (
  <svg viewBox="0 0 24 24" width={s} height={s} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);
const IconRefresh = () => (<I><path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5" /><path d="M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5" /></I>);
const IconExport = () => (<I><path d="M12 3v12M8 11l4 4 4-4M4 21h16" /></I>);
const IconCompare = () => (<I><path d="M4 7h7M4 7l3-3M4 7l3 3M20 17h-7M20 17l-3-3M20 17l-3 3" /></I>);
const IconShare = () => (<I><circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" /><path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4" /></I>);

function useQuote(symbol) {
  const [q, setQ] = useState(null);
  useEffect(() => {
    if (!symbol) return;
    let live = true;
    const poll = () => {
      authFetch(`/api/quote?symbol=${encodeURIComponent(symbol)}`)
        .then((r) => r.json())
        .then((d) => { if (live && d && !d.error) setQ(d); })
        .catch(() => {});
    };
    poll();
    const id = setInterval(poll, 20000);
    return () => { live = false; clearInterval(id); };
  }, [symbol]);
  return q;
}

const Stat = ({ label, value }) => (
  <div className="flex flex-col">
    <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</span>
    <span className="text-[13px] font-semibold text-slate-200 nv-num mt-0.5">{value}</span>
  </div>
);

export default function DashHeader({ symbol, name, data, score, loading, onRefresh, onExport, onCompare }) {
  const quote = useQuote(symbol);
  const val = data?.calculated_metrics?.['F-03_Valuation_Metrics'] || {};
  const peer = data?.peer_synthesis_data || {};
  // Verbatim official NSE industry classification (nseSectorMap.js, ~750
  // Nifty Total Market symbols) takes priority over the AI-guessed/
  // peer-group-derived `peer.sector` label — falls back to that only for
  // symbols outside the Nifty Total Market universe.
  const sectorDisplay = getNseSector(symbol) || peer.sector || '—';

  const price = isNum(quote?.price) ? quote.price : val.last_price;
  const chg = isNum(quote?.change) ? quote.change : null;
  const chgPct = isNum(quote?.change_percent) ? quote.change_percent : (isNum(quote?.changePercent) ? quote.changePercent : null);
  const tone = isNum(chgPct) ? (chgPct > 0 ? 'nv-pos' : chgPct < 0 ? 'nv-neg' : 'nv-muted') : 'nv-muted';

  const share = () => {
    try {
      const url = `${window.location.origin}?symbol=${encodeURIComponent(symbol)}`;
      if (navigator.clipboard) navigator.clipboard.writeText(url);
    } catch (e) { /* ignore */ }
  };

  return (
    <div className="nv-card nv-elev rounded-2xl px-5 py-4">
      <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4">
        {/* identity + price */}
        <div className="flex items-start gap-4 min-w-0">
          <div className="w-11 h-11 rounded-xl bg-slate-950 border border-slate-800 grid place-items-center font-extrabold text-blue-600 flex-shrink-0">
            {String(symbol || '').slice(0, 2)}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="nv-h1 text-[19px] text-slate-100 truncate">{name || symbol}</h1>
              <span className="text-[11px] font-mono font-semibold text-blue-600 bg-blue-500/10 border border-blue-500/15 rounded-md px-1.5 py-0.5">{symbol}</span>
              {peer.cap_tier && <span className="text-[11px] font-semibold text-slate-400 bg-slate-850 border border-slate-800 rounded-md px-1.5 py-0.5">{peer.cap_tier}</span>}
            </div>
            <div className="flex items-baseline gap-2.5 mt-1.5">
              <span className="text-[24px] font-bold text-slate-100 nv-num leading-none">{isNum(price) ? inr(price) : '—'}</span>
              {isNum(chg) && (
                <span className={`text-[13px] font-semibold nv-num ${tone}`}>
                  {chg > 0 ? '+' : ''}{Number(chg).toFixed(2)}
                  {isNum(chgPct) && <span> ({chgPct > 0 ? '+' : ''}{Number(chgPct).toFixed(2)}%)</span>}
                </span>
              )}
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 bg-slate-850 border border-slate-800 rounded px-1.5 py-0.5">{quote ? 'Live' : 'Delayed'}</span>
            </div>
          </div>
        </div>

        {/* meta stats */}
        <div className="flex items-center gap-x-6 gap-y-2 flex-wrap">
          <Stat label="Sector" value={sectorDisplay} />
          <Stat label="Exchange" value="NSE" />
          <Stat label="Market cap" value={inrCrore(val.MarketCap)} />
          <div className="flex flex-col">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Quality</span>
            {loading ? (
              <span className="text-[13px] font-bold text-slate-500 animate-pulse mt-0.5">···</span>
            ) : (
              <span className="text-[13px] font-bold text-blue-600 nv-num mt-0.5">{isNum(score) ? `${score} / 100` : '—'}</span>
            )}
          </div>
        </div>

        {/* actions */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <button onClick={onCompare} className="nv-btn nv-btn-ghost h-9 px-3 text-[13px]" title="Compare"><IconCompare /><span className="hidden sm:inline">Compare</span></button>
          <button onClick={onRefresh} className="nv-icon-btn w-9 h-9" title="Refresh"><IconRefresh /></button>
          <button onClick={share} className="nv-icon-btn w-9 h-9" title="Copy share link"><IconShare /></button>
          <button onClick={onExport} className="nv-btn nv-btn-primary h-9 px-4 text-[13px]" title="Export"><IconExport /><span className="hidden sm:inline">Export</span></button>
        </div>
      </div>
    </div>
  );
}
