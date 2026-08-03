import React from 'react';
import { inr, inrCrore, pct, num, isNum, signedPct, toneClass } from '../lib/format.js';
import { fetchRatio, fetchQuote } from '../lib/api.js';
import IncomeSankey from '../components/IncomeSankey.jsx';

/* --- tiny sparkline --- */
function Sparkline({ series, tone = 'blue', w = 96, h = 30 }) {
  const pts = (series || []).filter(isNum).map(Number);
  if (pts.length < 2) return <div style={{ width: w, height: h }} />;
  const min = Math.min(...pts), max = Math.max(...pts);
  const span = max - min || 1;
  const stroke = tone === 'pos' ? 'rgb(var(--emerald-500))' : tone === 'neg' ? 'rgb(var(--red-500))' : 'rgb(var(--blue-500))';
  const d = pts.map((v, i) => {
    const x = (i / (pts.length - 1)) * (w - 2) + 1;
    const y = h - 2 - ((v - min) / span) * (h - 4);
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const areaD = `${d} L${w - 1},${h} L1,${h} Z`;
  const id = `sg-${tone}-${Math.random().toString(36).slice(2, 7)}`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} className="overflow-visible">
      <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor={stroke} stopOpacity="0.18" /><stop offset="1" stopColor={stroke} stopOpacity="0" />
      </linearGradient></defs>
      <path d={areaD} fill={`url(#${id})`} />
      <path d={d} className="nv-spark" stroke={stroke} strokeWidth="1.8" />
    </svg>
  );
}

function MetricCard({ label, value, sub, trend, series, seriesTone = 'blue' }) {
  return (
    <div className="nv-card nv-hoverable p-4 flex flex-col justify-between min-h-[118px]">
      <div className="flex items-start justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{label}</span>
        {trend && <span className={`text-[11px] font-semibold nv-num ${toneClass(trend.tone)}`}>{trend.text}</span>}
      </div>
      <div className="mt-2">
        <div className="text-[22px] font-bold text-slate-100 nv-num leading-none">{value}</div>
        {sub && <div className="text-[11px] text-slate-500 mt-1">{sub}</div>}
      </div>
      {series && series.filter(isNum).length > 1 && (
        <div className="mt-2 -mb-1"><Sparkline series={series} tone={seriesTone} w={110} h={26} /></div>
      )}
    </div>
  );
}

// Pull a numeric series for a line item across income-statement dates (chronological).
function stmtSeries(incomeStmt, field) {
  if (!incomeStmt) return [];
  const dates = Object.keys(incomeStmt).sort();
  return dates.map((d) => incomeStmt[d]?.[field]).map((v) => (isNum(v) ? Number(v) : null));
}

// Fetches the metric-grid numbers independently of the slow qualitative
// pipeline (`calculated_metrics`, populated only once /api/v1/generate-report
// resolves — that can take minutes on a cold cache). Every endpoint here is
// the SAME fast, Supabase-precompute-backed path the deeper AI-research
// ratio cards already use (falls back to a live PDF parse only on a genuine
// cache miss), fetched in parallel — so the grid fills in near-instantly for
// any already-precomputed company instead of blocking on the whole report.
function useFastOverviewMetrics(symbol, name) {
  const [fast, setFast] = React.useState(null);
  React.useEffect(() => {
    if (!symbol) { setFast(null); return; }
    let cancelled = false;
    setFast(null);
    Promise.all([
      fetchQuote(symbol),
      fetchRatio('/api/v1/shares-outstanding', symbol, name),
      fetchRatio('/api/v1/revenue-from-operations', symbol, name),
      fetchRatio('/api/v1/net-profit-margin', symbol, name),
      fetchRatio('/api/v1/eps', symbol, name),
      fetchRatio('/api/v1/return-on-equity', symbol, name),
      fetchRatio('/api/v1/return-on-capital-employed', symbol, name),
      fetchRatio('/api/v1/book-value-per-share', symbol, name),
      fetchRatio('/api/v1/ebitda', symbol, name),
      fetchRatio('/api/v1/total-debt', symbol, name),
      fetchRatio('/api/v1/cash-and-equivalents', symbol, name),
    ]).then(([quote, shares, revenue, npm, eps, roe, roce, bvps, ebitda, debt, cash]) => {
      if (!cancelled) setFast({ quote, shares, revenue, npm, eps, roe, roce, bvps, ebitda, debt, cash });
    });
    return () => { cancelled = true; };
  }, [symbol]);
  return fast;
}

export default function Overview({ data, onOpenSection, onSearch }) {
  const m = data?.calculated_metrics || {};
  const val = m['F-03_Valuation_Metrics'] || {};
  const sol = m['F-08_Solvency_Metrics'] || {};
  const ratios = Array.isArray(m['F-02_Ratio_Analysis']) ? m['F-02_Ratio_Analysis'] : [];
  const growth = m['F-05_Growth_Summary'] || {};
  const inc = m['F-01_Financial_Statements']?.annual?.income_stmt;
  const ai = data?.ai_summary || {};
  const score = isNum(data?.business_score) ? data.business_score : (m['F-19_Business_Quality']?.composite_score);

  const fast = useFastOverviewMetrics(data?.symbol, m.company_name || data?.symbol);

  // latest / series — sparklines/trend arrows still come from the slower
  // multi-year `calculated_metrics` blob (no fast multi-year endpoint exists
  // yet) and simply fade in once that arrives; the headline numbers below
  // don't wait for them.
  const latest = ratios[0] || {}; // F-02 is newest-first
  const roeSeries = [...ratios].reverse().map((r) => r.ROE);
  const roceSeries = [...ratios].reverse().map((r) => r.ROCE);
  const revSeries = stmtSeries(inc, 'Total Revenue');
  const patSeries = stmtSeries(inc, 'Net Income');
  const peSeries = val.pe_band?.series;

  const headline = typeof ai.headline === 'string' ? ai.headline : null;
  const narrative = Array.isArray(ai.narrative) ? ai.narrative[0] : (typeof ai.narrative === 'string' ? ai.narrative : null);
  // investment_view is an object { verdict, invest_score, reason, ... } — never render it directly.
  const iv = ai.investment_view;
  const verdict = iv && typeof iv === 'object' ? iv.verdict : (typeof iv === 'string' ? iv : null);
  const investScore = iv && typeof iv === 'object' && isNum(iv.invest_score) ? iv.invest_score : null;

  // Fast-path values (preferred — ready in ~1s), each falling back to the
  // slower calculated_metrics figure only until/unless the fast fetch itself
  // comes back inapplicable (e.g. a genuinely unlisted/illiquid instrument).
  // The fast /api/v1/* endpoints report money fields in ₹ CRORE ("unit": "₹
  // Cr"), while `calculated_metrics` stores plain RAW RUPEES (that's what
  // `inrCrore()` — which itself divides by 1e7 — expects) — every fast
  // monetary value below is multiplied by 1e7 right at the point of use so
  // the two sources combine/display correctly without a silent 1e7 unit bug.
  const price = fast?.quote?.ltp ?? (isNum(val.last_price) ? val.last_price : null);
  const sharesVal = fast?.shares?.applicable ? fast.shares.value : null;
  const marketCap = (isNum(price) && isNum(sharesVal)) ? price * sharesVal : (isNum(val.MarketCap) ? val.MarketCap : null);

  const revenueVal = fast?.revenue?.applicable ? fast.revenue.value * 1e7
    : (isNum(val.revenue) ? val.revenue : revSeries.filter(isNum).slice(-1)[0]);
  const npmVal = fast?.npm?.applicable ? fast.npm.value : null; // already a %, e.g. 12.34
  const patFast = (isNum(revenueVal) && isNum(npmVal)) ? (revenueVal * npmVal) / 100 : null;
  const patLatest = patFast ?? patSeries.filter(isNum).slice(-1)[0];

  const epsVal = fast?.eps?.applicable ? fast.eps.value : null; // ₹ per share, no Cr conversion
  // ROE/ROCE come back from the fast endpoints already as a %, e.g. 15.23 —
  // divided by 100 here so this variable is always a FRACTION (0.1523),
  // matching calculated_metrics's convention and what `pct()` expects.
  const roeVal = fast?.roe?.applicable ? fast.roe.value / 100 : (isNum(latest.ROE) ? latest.ROE : null);
  const roceVal = fast?.roce?.applicable ? fast.roce.value / 100 : (isNum(latest.ROCE) ? latest.ROCE : null);

  const bvpsVal = fast?.bvps?.applicable ? fast.bvps.value : null; // ₹ per share
  const peVal = (isNum(price) && isNum(epsVal) && epsVal > 0) ? price / epsVal : (isNum(val.PE) ? val.PE : null);
  const pbVal = (isNum(price) && isNum(bvpsVal) && bvpsVal > 0) ? price / bvpsVal : (isNum(val.PB) ? val.PB : null);

  const ebitdaVal = fast?.ebitda?.applicable ? fast.ebitda.value * 1e7 : null;
  const ebitdaMarginVal = (isNum(ebitdaVal) && isNum(revenueVal) && revenueVal > 0) ? ebitdaVal / revenueVal
    : (isNum(latest.EBITDA_Margin) ? latest.EBITDA_Margin : null);

  const debtVal = fast?.debt?.applicable ? fast.debt.value * 1e7 : (isNum(sol.total_debt) ? sol.total_debt : null);
  const cashVal = fast?.cash?.applicable ? fast.cash.value * 1e7 : (isNum(sol.cash_equivalents) ? sol.cash_equivalents : null);
  const ev = isNum(marketCap) ? marketCap + (isNum(debtVal) ? debtVal : 0) - (isNum(cashVal) ? cashVal : 0) : null;

  // No fast Free Cash Flow endpoint exists yet — stays sourced from the
  // slower qualitative blob until one is built.
  const fcfYield = isNum(val.FCF_Yield) ? val.FCF_Yield : null;

  const cards = [
    { label: 'Current price', value: isNum(price) ? inr(price) : '—', sub: 'NSE · live/last' },
    { label: 'Market cap', value: isNum(marketCap) ? inrCrore(marketCap) : '—', sub: 'Total equity value' },
    { label: 'Enterprise value', value: isNum(ev) ? inrCrore(ev) : '—', sub: 'Mkt cap + debt − cash' },
    { label: 'Revenue', value: isNum(revenueVal) ? inrCrore(revenueVal) : '—', sub: 'Latest FY', series: revSeries, seriesTone: 'pos', trend: isNum(growth.cagr_3y_revenue) ? signedPct(growth.cagr_3y_revenue) : null },
    { label: 'Net profit', value: isNum(patLatest) ? inrCrore(patLatest) : '—', sub: 'Latest FY', series: patSeries, seriesTone: 'pos', trend: isNum(growth.cagr_3y_pat) ? signedPct(growth.cagr_3y_pat) : null },
    { label: 'EPS', value: isNum(epsVal) ? num(epsVal, { decimals: 1, suffix: '' }) : '—', sub: 'Net profit / shares' },
    { label: 'ROE', value: isNum(roeVal) ? pct(roeVal) : '—', sub: 'Return on equity', series: roeSeries, seriesTone: 'blue' },
    { label: 'ROCE', value: isNum(roceVal) ? pct(roceVal) : '—', sub: 'Return on capital', series: roceSeries, seriesTone: 'blue' },
    { label: 'P/E', value: isNum(peVal) ? num(peVal, { decimals: 1, suffix: '×' }) : '—', sub: 'Price / earnings', series: peSeries, seriesTone: 'neutral' },
    { label: 'P/B', value: isNum(pbVal) ? num(pbVal, { decimals: 2, suffix: '×' }) : '—', sub: 'Price / book' },
    { label: 'EBITDA margin', value: isNum(ebitdaMarginVal) ? pct(ebitdaMarginVal) : '—', sub: 'Operating profitability' },
    { label: 'FCF yield', value: isNum(fcfYield) ? pct(fcfYield) : '—', sub: 'Free cash flow / mkt cap' },
  ];

  return (
    <div className="space-y-5">
      <IncomeSankey incomeStmt={inc} symbol={data?.symbol} companyName={m.company_name || data?.symbol} />
      {/* metric grid */}
      <div>
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="nv-h2 text-[15px] text-slate-200">Company overview</h2>
          <span className="text-[11px] text-slate-500">Sparklines show multi-year trend</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
          {cards.map((c) => <MetricCard key={c.label} {...c} />)}
        </div>
      </div>
    </div>
  );
}
