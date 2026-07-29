import React, { useEffect, useRef, useState } from 'react';
import { searchSymbols } from '../lib/api.js';

const IconSearch = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
);

// Reusable company/ticker search with autocomplete. onSelect(symbol) runs research.
export default function StockSearch({ onSelect, placeholder = 'Search a company or ticker to analyze…', autoFocus = false, compact = false }) {
  const [q, setQ] = useState('');
  const [matches, setMatches] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef(null);
  const reqId = useRef(0);

  useEffect(() => {
    let live = true;
    if (!q.trim()) { setMatches([]); setOpen(false); return; }
    const id = ++reqId.current;
    const t = setTimeout(async () => {
      const r = await searchSymbols(q);
      if (!live || id !== reqId.current) return;
      setMatches(r.slice(0, 7)); setOpen(true); setActive(0);
    }, 40);
    return () => { live = false; clearTimeout(t); };
  }, [q]);

  useEffect(() => {
    const h = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  const go = (sym) => { if (sym) { setQ(''); setOpen(false); onSelect(String(sym).toUpperCase()); } };
  const onKey = async (e) => {
    if (!open || !matches.length) {
      // No dropdown match yet (e.g. typed and hit Enter faster than the
      // debounced search resolved). Try one direct lookup for the exact
      // symbol/name before falling back to raw text — otherwise a full
      // company name like "Gopal Snacks" gets sent as the "symbol" to the
      // backend instead of the real ticker "GOPAL".
      if (e.key === 'Enter' && q.trim()) {
        const query = q.trim();
        const r = await searchSymbols(query);
        go(r[0]?.symbol || query);
      }
      return;
    }
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((i) => (i + 1) % matches.length); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((i) => (i - 1 + matches.length) % matches.length); }
    else if (e.key === 'Enter') { e.preventDefault(); go(matches[active]?.symbol || q.trim()); }
    else if (e.key === 'Escape') setOpen(false);
  };

  return (
    <div ref={boxRef} className={`relative ${compact ? 'w-full max-w-[260px]' : ''}`}>
      <div className={`flex items-center gap-2 bg-slate-950 border rounded-xl transition-colors ${compact ? 'px-3 h-9' : 'px-4 h-[52px] gap-3'} ${open ? 'border-blue-500' : 'border-slate-800'}`}>
        <span className="text-slate-500 flex-shrink-0"><IconSearch /></span>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKey}
          onFocus={() => matches.length && setOpen(true)}
          autoFocus={autoFocus}
          placeholder={placeholder}
          className={`flex-1 bg-transparent outline-none text-slate-100 placeholder:text-slate-500 min-w-0 ${compact ? 'text-[13px]' : 'text-[15px]'}`}
          aria-label="Search companies"
        />
        {!compact && <button onClick={() => go(matches[active]?.symbol || q.trim())} className="nv-btn nv-btn-primary h-9 px-4 flex-shrink-0 text-[13px]">Analyze</button>}
      </div>

      {/* Always mounted so open/close animates (fade + slide) instead of popping. */}
      <div
        className={`absolute left-0 ${compact ? 'w-[320px]' : 'right-0'} mt-2 z-40 nv-card nv-float2 p-1.5 overflow-hidden transition-all duration-200 ease-out origin-top ${
          open && matches.length > 0 ? 'opacity-100 scale-100 translate-y-0' : 'opacity-0 scale-[0.98] -translate-y-1 pointer-events-none'
        }`}
      >
          {matches.map((m, i) => (
            <button
              key={m.symbol + i}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => { e.preventDefault(); go(m.symbol); }}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-colors ${i === active ? 'bg-slate-850' : ''}`}
            >
              <span className="w-8 h-8 rounded-md bg-slate-950 border border-slate-800 grid place-items-center font-bold text-[12px] text-blue-600 flex-shrink-0">{String(m.symbol).slice(0, 2)}</span>
              <span className="min-w-0 flex-1">
                <span className="block text-[13.5px] font-semibold text-slate-100 truncate">{m.name || m.symbol}</span>
                <span className="block text-[11px] text-slate-500 truncate">{m.symbol} · NSE · Equity</span>
              </span>
            </button>
          ))}
      </div>
    </div>
  );
}
