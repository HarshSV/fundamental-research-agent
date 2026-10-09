import React, { useEffect, useRef, useState } from 'react';
import { searchSymbols } from '../lib/api.js';
import { detailLine, chooseCompany, NO_MATCH_TEXT } from '../lib/companySearch.js';

const IconSearch = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
);

// Reusable company/ticker search with autocomplete. onSelect(symbol) runs research.
export default function StockSearch({ onSelect, placeholder = 'Search a company or ticker to analyze…', autoFocus = false, compact = false }) {
  const [q, setQ] = useState('');
  const [matches, setMatches] = useState([]);
  const [noMatch, setNoMatch] = useState(false); // the last completed search found nothing
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef(null);
  const reqId = useRef(0);

  useEffect(() => {
    let live = true;
    if (!q.trim()) { setMatches([]); setNoMatch(false); setOpen(false); return; }
    const id = ++reqId.current;
    const t = setTimeout(async () => {
      const r = await searchSymbols(q);
      if (!live || id !== reqId.current) return;
      setMatches(r.slice(0, 7)); setNoMatch(r.length === 0); setOpen(true); setActive(0);
    }, 40);
    return () => { live = false; clearTimeout(t); };
  }, [q]);

  useEffect(() => {
    const h = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  const go = (sym) => { if (sym) { setQ(''); setNoMatch(false); setOpen(false); onSelect(String(sym).toUpperCase()); } };
  // Enter / Analyze: open the highlighted dropdown company, else look the typed text up
  // once (typed faster than the debounced search resolved). Only a resolved company is
  // ever opened - raw typed text is never sent on as a "symbol"; no match says so.
  const submit = async () => {
    const query = q.trim();
    if (!query) return;
    if (open && matches[active]) { go(matches[active].symbol); return; }
    const r = await searchSymbols(query);
    const pick = chooseCompany(r);
    if (pick) { go(pick.symbol); return; }
    setMatches(r.slice(0, 7)); setNoMatch(r.length === 0); setActive(0); setOpen(true);
  };
  const onKey = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); submit(); return; }
    if (!open || !matches.length) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((i) => (i + 1) % matches.length); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((i) => (i - 1 + matches.length) % matches.length); }
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
          onFocus={() => (matches.length || noMatch) && setOpen(true)}
          autoFocus={autoFocus}
          placeholder={placeholder}
          className={`flex-1 bg-transparent outline-none text-slate-100 placeholder:text-slate-500 min-w-0 ${compact ? 'text-[13px]' : 'text-[15px]'}`}
          aria-label="Search companies"
        />
        {!compact && <button onClick={submit} className="nv-btn nv-btn-primary h-9 px-4 flex-shrink-0 text-[13px]">Analyze</button>}
      </div>

      {/* Always mounted so open/close animates (fade + slide) instead of popping. */}
      <div
        className={`absolute left-0 ${compact ? 'w-[320px]' : 'right-0'} mt-2 z-40 nv-card nv-float2 p-1.5 overflow-hidden transition-all duration-200 ease-out origin-top ${
          open && (matches.length > 0 || noMatch) ? 'opacity-100 scale-100 translate-y-0' : 'opacity-0 scale-[0.98] -translate-y-1 pointer-events-none'
        }`}
      >
          {open && noMatch && (
            <div className="px-3 py-3 text-[13px] text-slate-400">{NO_MATCH_TEXT}</div>
          )}
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
                <span className="block text-[11px] text-slate-500 truncate">{detailLine(m)}</span>
              </span>
            </button>
          ))}
      </div>
    </div>
  );
}
