import React, { useEffect, useState } from 'react';
import { getHistory, removeHistory, clearHistory } from '../lib/history.js';
import StockSearch from '../components/StockSearch.jsx';

const IconClock = () => (
  <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></svg>
);
const IconX = () => (
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
);

function timeAgo(ts) {
  const s = Math.max(1, Math.floor((Date.now() - ts) / 1000));
  if (s < 60) return 'just now';
  const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24); if (d < 30) return `${d}d ago`;
  return new Date(ts).toLocaleDateString('en-IN');
}

// Re-reads localStorage each time this view mounts (i.e. each time the sidebar
// selects History), which is all that's needed since entries are only written
// on a successful research fetch.
export default function History({ onSearch }) {
  const [items, setItems] = useState(getHistory);

  useEffect(() => { setItems(getHistory()); }, []);

  const remove = (symbol, e) => {
    e.stopPropagation();
    removeHistory(symbol);
    setItems(getHistory());
  };
  const clearAll = () => { clearHistory(); setItems([]); };

  return (
    <div className="space-y-5">
      <div className="nv-card nv-elev p-4 md:p-5">
        <span className="nv-eyebrow text-blue-600 block mb-2.5">Search a company</span>
        <StockSearch onSelect={onSearch} placeholder="Search a company or ticker — Reliance, TCS, HDFC Bank…" />
      </div>

      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="nv-h2 text-[15px] text-slate-200">Recently analyzed</h2>
          {items.length > 0 && (
            <button onClick={clearAll} className="text-[12px] font-semibold text-slate-500 hover:text-red-500 transition-colors">Clear all</button>
          )}
        </div>

        {items.length === 0 ? (
          <div className="nv-card p-10 text-center">
            <div className="w-12 h-12 rounded-xl bg-slate-850 text-slate-500 grid place-items-center mx-auto mb-3"><IconClock /></div>
            <p className="text-[14px] font-semibold text-slate-200">No history yet</p>
            <p className="text-[12.5px] text-slate-500 mt-1">Companies you analyze will show up here so you don't have to search again.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
            {items.map((h) => (
              <button
                key={h.symbol}
                onClick={() => onSearch(h.symbol)}
                className="nv-card nv-hoverable p-4 text-left flex items-center gap-3 group"
              >
                <span className="w-10 h-10 rounded-lg bg-slate-950 border border-slate-800 grid place-items-center font-bold text-[13px] text-blue-600 flex-shrink-0">
                  {String(h.symbol).slice(0, 2)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[13.5px] font-semibold text-slate-100 truncate">{h.name || h.symbol}</span>
                  <span className="block text-[11px] text-slate-500 truncate">{h.symbol} · {timeAgo(h.ts)}</span>
                </span>
                <span
                  role="button"
                  tabIndex={0}
                  onClick={(e) => remove(h.symbol, e)}
                  className="w-6 h-6 rounded-md flex-shrink-0 flex items-center justify-center text-slate-600 opacity-0 group-hover:opacity-100 hover:text-red-500 hover:bg-red-500/10 transition-all"
                  aria-label={`Remove ${h.symbol} from history`}
                >
                  <IconX />
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
