import React, { useEffect, useRef, useState } from 'react';
import { searchSymbols } from '../lib/api.js';
import ManualUpload from '../components/ManualUpload.jsx';

/* ---- small inline icon set (stroke, currentColor) ---- */
const I = ({ children, s = 20 }) => (
  <svg viewBox="0 0 24 24" width={s} height={s} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);
const IconSearch = () => (<I><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></I>);
const IconAI = () => (<I><path d="M12 3a3.5 3.5 0 0 1 3.5 3.5c0 .5-.1 1-.3 1.4A3.5 3.5 0 0 1 17 15.9V17a3 3 0 0 1-5 2.2A3 3 0 0 1 7 17v-1.1A3.5 3.5 0 0 1 8.8 7.9 3.5 3.5 0 0 1 12 3z" /></I>);
const IconSector = () => (<I><path d="M3 3v18h18" /><path d="M7 15l3-4 3 2 4-6" /></I>);
const IconStatements = () => (<I><path d="M8 3h8l4 4v14H4V3z" /><path d="M8 12h8M8 16h8M8 8h4" /></I>);
const IconBenchmark = () => (<I><path d="M4 20V8M10 20V4M16 20v-9M22 20H2" /></I>);
const IconTrace = () => (<I><path d="M9 5H5v4M15 5h4v4M9 19H5v-4M15 19h4v-4" /><circle cx="12" cy="12" r="2.4" /></I>);
const IconChart = () => (<I><path d="M3 12h4l3 7 4-14 3 7h4" /></I>);
const IconPeers = () => (<I><rect x="3" y="4" width="7" height="7" rx="1.5" /><rect x="14" y="4" width="7" height="7" rx="1.5" /><rect x="3" y="15" width="7" height="5" rx="1.5" /><rect x="14" y="13" width="7" height="7" rx="1.5" /></I>);
const IconCheck = () => (<I s={16}><path d="M20 6 9 17l-5-5" /></I>);
const IconArrow = () => (<I s={16}><path d="M5 12h14M13 6l6 6-6 6" /></I>);
const IconEdit = () => (<I s={14}><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></I>);
const IconX = () => (<I s={12}><path d="M18 6 6 18M6 6l12 12" /></I>);
const IconPlus = () => (<I s={14}><path d="M12 5v14M5 12h14" /></I>);
const IconUpload = () => (<I s={14}><path d="M12 3v12M8 7l4-4 4 4M4 21h16" /></I>);

// India's top 5 listed companies by market cap.
const DEFAULT_WATCHLIST = ['RELIANCE', 'HDFCBANK', 'TCS', 'BHARTIARTL', 'ICICIBANK'];
// The previous default (10 stocks) - anyone whose stored list still matches
// this exactly never customized it, so switch them to the new 5-stock
// default too rather than leave them stuck on the old list forever.
const PRIOR_DEFAULT_WATCHLIST = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK', 'LT', 'ITC', 'SBIN', 'BHARTIARTL', 'MARUTI'];
const WATCHLIST_KEY = 'nv_watchlist';
const WATCHLIST_MAX = 10;

function loadWatchlist() {
  try {
    const raw = localStorage.getItem(WATCHLIST_KEY);
    if (!raw) return DEFAULT_WATCHLIST;
    const arr = JSON.parse(raw);
    if (Array.isArray(arr) && arr.length) {
      if (arr.length === PRIOR_DEFAULT_WATCHLIST.length && arr.every((s, i) => s === PRIOR_DEFAULT_WATCHLIST[i])) {
        return DEFAULT_WATCHLIST;
      }
      return arr.slice(0, WATCHLIST_MAX);
    }
  } catch (e) { /* ignore */ }
  return DEFAULT_WATCHLIST;
}

const FEATURES = [
  { Icon: IconAI, title: 'AI research', body: 'Executive summaries, growth drivers, moat and risks - reasoned from filings, not guessed.' },
  { Icon: IconSector, title: 'Sector intelligence', body: 'Official NSE classification drives sector-aware ratio tiers and the right peer set.' },
  { Icon: IconStatements, title: 'Financial statements', body: 'Audited annual and quarterly income, balance sheet and cash flow - standalone or consolidated.' },
  { Icon: IconBenchmark, title: 'Benchmarking', body: 'Every ratio graded against verified industry benchmarks with confidence scoring.' },
  { Icon: IconTrace, title: 'Traceable calculations', body: 'Open any number to see its formula and the exact filing, page and line it came from.' },
  { Icon: IconChart, title: 'Interactive charts', body: 'Revenue, margins, returns and cash flow over 5–10 years with hover and compare.' },
  { Icon: IconPeers, title: 'Peer comparison', body: 'Side-by-side metrics, ratios and percentile ranks across the sector cohort.' },
];

const WORKFLOW = [
  'Search company', 'AI identifies company', 'Detects sector', 'Collects filings',
  'Calculates ratios', 'Benchmarks peers', 'Generates AI insights', 'Produces investment research',
];

const TRUST = [
  'Official NSE classification', 'Audited annual reports', 'Exchange filings',
  'Investor presentations', 'Verified industry benchmarks', 'Explainable AI',
];

export default function Landing({ onSelect, onOpenManual, onLogout }) {
  const [q, setQ] = useState('');
  const [matches, setMatches] = useState([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const boxRef = useRef(null);
  const searchInputRef = useRef(null);

  const [showManual, setShowManual] = useState(false);
  const [manualSymbol, setManualSymbol] = useState('');

  const [watchlist, setWatchlist] = useState(loadWatchlist);
  const [editing, setEditing] = useState(false);
  const [wq, setWq] = useState('');
  const [wMatches, setWMatches] = useState([]);
  const editRef = useRef(null);

  useEffect(() => {
    localStorage.setItem(WATCHLIST_KEY, JSON.stringify(watchlist));
  }, [watchlist]);

  useEffect(() => {
    if (!editing) return;
    const h = (e) => { if (editRef.current && !editRef.current.contains(e.target)) setEditing(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [editing]);

  useEffect(() => {
    let live = true;
    if (!wq.trim()) { setWMatches([]); return; }
    const t = setTimeout(async () => {
      const r = await searchSymbols(wq);
      if (!live) return;
      setWMatches(r.slice(0, 6));
    }, 130);
    return () => { live = false; clearTimeout(t); };
  }, [wq]);

  const addToWatchlist = (sym) => {
    const s = String(sym).toUpperCase();
    setWatchlist((w) => (w.includes(s) || w.length >= WATCHLIST_MAX ? w : [...w, s]));
    setWq(''); setWMatches([]);
  };
  const removeFromWatchlist = (sym) => setWatchlist((w) => w.filter((s) => s !== sym));

  useEffect(() => {
    let live = true;
    if (!q.trim()) { setMatches([]); setOpen(false); return; }
    const t = setTimeout(async () => {
      const r = await searchSymbols(q);
      if (!live) return;
      setMatches(r.slice(0, 8)); setOpen(true); setActive(0);
    }, 130);
    return () => { live = false; clearTimeout(t); };
  }, [q]);

  useEffect(() => {
    const h = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  const go = (sym) => { if (sym) onSelect(String(sym).toUpperCase()); };
  // No company needs to be picked first - the Annual Report itself says
  // who it's for; ManualUpload detects and resolves it after upload.
  const openManual = () => {
    const sym = matches[active]?.symbol || q.trim();
    setManualSymbol(sym ? String(sym).toUpperCase() : '');
    setShowManual(true);
  };
  const onKey = async (e) => {
    if (!open || !matches.length) {
      // No dropdown match yet (typed faster than the debounced search
      // resolved) - try one direct lookup before sending the raw text as
      // the "symbol", otherwise a full company name like "Gopal Snacks"
      // reaches the backend instead of its real ticker "GOPAL".
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
    <div className="nv-landing-bg min-h-screen">
      {/* top bar */}
      <header className="relative z-20 max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-600 text-white grid place-items-center font-extrabold text-sm">N</div>
          <span className="font-heading font-bold text-slate-100 tracking-tight">Navrist<span className="text-blue-600"> AI</span></span>
        </div>
        <div className="flex items-center gap-2">
          <span className="nv-eyebrow text-slate-500 hidden sm:inline">Equity research terminal</span>
          {onLogout && (
            <button onClick={onLogout} className="nv-btn nv-btn-ghost h-9 px-3 text-[13px]">Sign out</button>
          )}
        </div>
      </header>

      {/* hero */}
      <section className="nv-grid-bg nv-glow relative">
        <div className="max-w-4xl mx-auto px-6 pt-16 md:pt-24 pb-10 text-center">
          <div className="nv-rise inline-flex items-center gap-2 nv-chip mb-7 text-[12px]">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" /> Institutional-grade · Indian markets
          </div>
          <h1 className="nv-rise nv-rise-1 nv-display text-slate-100 text-[40px] sm:text-[56px] md:text-[64px]">
            AI powered<br className="hidden sm:block" /> equity research
          </h1>
          <p className="nv-rise nv-rise-2 mt-6 text-[16px] md:text-[18px] leading-relaxed text-slate-400 max-w-2xl mx-auto">
            Analyze any Indian listed company using AI reasoning, audited financial statements,
            sector-aware ratios and fully traceable calculations.
          </p>

          {/* search */}
          <div ref={boxRef} className="nv-rise nv-rise-3 relative mt-9 max-w-2xl mx-auto text-left">
            <div className={`flex items-center gap-3 bg-slate-900 border rounded-2xl px-4 h-[60px] transition-colors ${open ? 'border-blue-500' : 'border-slate-800'} nv-elev`}>
              <span className="text-slate-500"><IconSearch /></span>
              <input
                ref={searchInputRef}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={onKey}
                onFocus={() => matches.length && setOpen(true)}
                placeholder="Search a company or ticker"
                className="flex-1 bg-transparent outline-none text-slate-100 placeholder:text-slate-500 text-[16px] min-w-0"
                aria-label="Search companies"
              />
              <button onClick={() => go(matches[active]?.symbol || q.trim())} className="nv-btn nv-btn-primary h-10 px-5 flex-shrink-0">
                Analyze <IconArrow />
              </button>
            </div>

            <div className="flex items-center justify-center gap-2 mt-3">
              <span className="nv-eyebrow text-slate-500 self-center">Automatic search</span>
              <button
                onClick={openManual}
                className="nv-btn nv-btn-ghost h-8 px-3.5 text-[12.5px] font-semibold"
                title="Upload the company's Annual Report and NSE/BSE XBRL filing instead of relying on automatic fetch"
              >
                <IconUpload /> Upload Documents
              </button>
            </div>

            {/* Always mounted so open/close animates (fade + slide) instead of
                popping; pointer-events off while hidden so it never blocks clicks. */}
            <div
              className={`absolute left-0 right-0 mt-2 z-30 nv-card nv-float2 p-1.5 overflow-hidden transition-all duration-200 ease-out origin-top ${
                open && matches.length > 0 ? 'opacity-100 scale-100 translate-y-0' : 'opacity-0 scale-[0.98] -translate-y-1 pointer-events-none'
              }`}
            >
              {matches.map((m, i) => (
                <button
                  key={m.symbol + i}
                  onMouseEnter={() => setActive(i)}
                  onMouseDown={(e) => { e.preventDefault(); go(m.symbol); }}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-left transition-colors ${i === active ? 'bg-slate-850' : ''}`}
                >
                  <span className="w-9 h-9 rounded-lg bg-slate-950 border border-slate-800 grid place-items-center font-bold text-[13px] text-blue-600 flex-shrink-0">
                    {String(m.symbol).slice(0, 2)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[14px] font-semibold text-slate-100 truncate">{m.name || m.symbol}</span>
                    <span className="block text-[11px] text-slate-500 truncate">{m.symbol} · NSE · Equity</span>
                  </span>
                  <span className="nv-eyebrow text-slate-600">Open</span>
                </button>
              ))}
            </div>
          </div>

        </div>

        {/* watchlist */}
        <div ref={editRef} className={`max-w-3xl mx-auto px-6 pb-16 transition-opacity duration-200 ${open && matches.length > 0 ? 'opacity-0 pointer-events-none' : 'opacity-100'}`}>
          <div className="flex items-center justify-center gap-2 mb-3">
            <span className="nv-eyebrow text-slate-500">Your watchlist</span>
            <button
              onClick={() => setEditing((v) => !v)}
              className="nv-icon-btn w-6 h-6 !border-0 text-slate-500 hover:text-blue-600"
              title="Edit watchlist"
            >
              <IconEdit />
            </button>
          </div>

          <div className="flex flex-wrap items-center justify-center gap-2">
            {watchlist.map((t) => (
              <span key={t} className="nv-chip font-mono text-[12px] py-1.5 pr-1.5 group">
                <button onClick={() => go(t)} className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />{t}
                </button>
                {editing && (
                  <button
                    onClick={() => removeFromWatchlist(t)}
                    className="ml-1 w-4 h-4 rounded-full grid place-items-center text-slate-500 hover:text-red-400 hover:bg-red-500/10"
                    title={`Remove ${t}`}
                  >
                    <IconX />
                  </button>
                )}
              </span>
            ))}
            {watchlist.length === 0 && (
              <span className="text-[12.5px] text-slate-600">No stocks yet - add up to {WATCHLIST_MAX}.</span>
            )}
          </div>

          {editing && (
            <div className="nv-card p-3 max-w-sm mx-auto mt-4 text-left">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-semibold text-slate-400">Add a stock ({watchlist.length}/{WATCHLIST_MAX})</span>
                <button onClick={() => setEditing(false)} className="text-slate-500 hover:text-slate-300"><IconX /></button>
              </div>
              <div className="flex items-center gap-2 bg-slate-950 border border-slate-800 rounded-xl px-3 h-10">
                <IconSearch />
                <input
                  value={wq}
                  onChange={(e) => setWq(e.target.value)}
                  disabled={watchlist.length >= WATCHLIST_MAX}
                  placeholder={watchlist.length >= WATCHLIST_MAX ? 'Limit reached - remove one first' : 'Search company or ticker…'}
                  className="flex-1 bg-transparent outline-none text-slate-100 placeholder:text-slate-500 text-[13px] min-w-0"
                />
              </div>
              {wMatches.length > 0 && (
                <div className="mt-2 space-y-0.5">
                  {wMatches.map((m) => (
                    <button
                      key={m.symbol}
                      onClick={() => addToWatchlist(m.symbol)}
                      disabled={watchlist.includes(String(m.symbol).toUpperCase())}
                      className="w-full flex items-center justify-between gap-2 px-2.5 py-2 rounded-lg text-left hover:bg-slate-850 disabled:opacity-40"
                    >
                      <span className="text-[13px] text-slate-100 truncate">{m.name || m.symbol} <span className="text-slate-500 font-mono text-[11px]">{m.symbol}</span></span>
                      <IconPlus />
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      {/* features */}
      <section className="max-w-7xl mx-auto px-6 py-16 border-t border-slate-800/60">
        <div className="max-w-2xl">
          <div className="nv-eyebrow text-blue-600">Capabilities</div>
          <h2 className="nv-h2 text-[26px] text-slate-100 mt-2">Everything to understand a company in 30 seconds</h2>
          <p className="text-slate-400 mt-3">Progressive disclosure - headline first, evidence one click away.</p>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 mt-9">
          {FEATURES.map((f) => (
            <div key={f.title} className="nv-card nv-hoverable p-6">
              <div className="w-11 h-11 rounded-xl bg-blue-500/10 text-blue-600 grid place-items-center border border-blue-500/15">
                <f.Icon />
              </div>
              <h3 className="nv-h2 text-[16px] text-slate-100 mt-4">{f.title}</h3>
              <p className="text-[13.5px] leading-relaxed text-slate-400 mt-1.5">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* workflow */}
      <section className="max-w-7xl mx-auto px-6 py-16 border-t border-slate-800/60">
        <div className="max-w-2xl">
          <div className="nv-eyebrow text-blue-600">How it works</div>
          <h2 className="nv-h2 text-[26px] text-slate-100 mt-2">From ticker to investment research</h2>
        </div>
        <ol className="grid sm:grid-cols-2 lg:grid-cols-4 gap-x-4 gap-y-8 mt-10">
          {WORKFLOW.map((step, i) => (
            <li key={step} className="relative">
              <div className="flex items-center gap-3">
                <span className="w-8 h-8 rounded-full bg-slate-900 border border-slate-800 grid place-items-center text-[13px] font-bold text-blue-600 flex-shrink-0">{i + 1}</span>
                <span className="h-px flex-1 bg-slate-800" />
              </div>
              <p className="text-[14px] font-semibold text-slate-200 mt-3">{step}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* trust */}
      <section className="max-w-7xl mx-auto px-6 py-16 border-t border-slate-800/60">
        <div className="nv-card p-8 md:p-10">
          <div className="grid md:grid-cols-[1fr_1.4fr] gap-8 items-center">
            <div>
              <div className="nv-eyebrow text-blue-600">Grounded in evidence</div>
              <h2 className="nv-h2 text-[24px] text-slate-100 mt-2">Every claim is sourced and verifiable</h2>
              <p className="text-slate-400 mt-3 text-[14px] leading-relaxed">
                Not a screener. A research terminal that shows its work - official classifications,
                audited filings and explainable AI.
              </p>
            </div>
            <div className="grid sm:grid-cols-2 gap-3">
              {TRUST.map((t) => (
                <div key={t} className="flex items-center gap-3 nv-inset px-4 py-3">
                  <span className="w-6 h-6 rounded-full bg-emerald-500/12 text-emerald-500 grid place-items-center flex-shrink-0"><IconCheck /></span>
                  <span className="text-[13.5px] font-medium text-slate-200">{t}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <footer className="max-w-7xl mx-auto px-6 py-10 border-t border-slate-800/60 flex flex-col sm:flex-row items-center justify-between gap-2 text-[12px]">
        <p className="text-slate-500 font-medium">© 2026 Navrist · Research Terminal</p>
        <p className="text-slate-600">For internal research use only. Not investment advice.</p>
      </footer>

      {showManual && (
        <ManualUpload
          symbol={manualSymbol || null}
          onClose={() => setShowManual(false)}
          onOpenDashboard={(sym, name) => onOpenManual?.(sym || manualSymbol, name)}
        />
      )}
    </div>
  );
}
