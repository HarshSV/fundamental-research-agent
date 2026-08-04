import React from 'react';
import { inrCrore, isNum } from '../lib/format.js';
import { fetchRatio } from '../lib/api.js';

/*
 * Income-statement hierarchy tree for the stock Overview page. Renders a
 * nodes/links graph (see `fromApiFlow` / `buildShallowFallback`) as an
 * indented tree — replaces an earlier Sankey-ribbon rendering, which kept
 * overflowing its card (min-width forcing horizontal scroll, labels running
 * past the card edge) no matter how much the ribbon geometry was tuned. A
 * tree is a strictly better fit here: it's a block layout, so it can never
 * exceed the card's own width — rows wrap/truncate like normal text instead
 * of a fixed-viewBox SVG canvas needing its own scroll area.
 *
 * Primary data source: /api/v1/income-statement-flow — built entirely from
 * the company's own Annual Report P&L (tools/annual_report_financials.py's
 * fetch_income_statement_flow_from_annual_report), every value either a
 * reported line item or a deterministic subtraction of two reported figures.
 * No LLM, no Groq, no estimation.
 *
 * Fallback: when the AR-based flow isn't applicable (report not parseable,
 * PBT/PAT not found, etc.), falls back to the shallower Revenue -> Total
 * Expenses/Operating Profit -> Interest & D&A/PBT -> Tax/Net Profit view
 * built from `income_stmt` (Screener-sourced, already loaded on Overview) —
 * a simpler truthful chart beats a richer fabricated one.
 */

const GREEN = 'rgb(var(--emerald-500))';
const RED = 'rgb(var(--red-500))';
const DARK_RED = 'rgb(var(--red-600, var(--red-500)))';
const SLATE = 'rgb(var(--slate-500))';
const BLUE = 'rgb(var(--blue-500))';

function colorFor(node) {
  if (isNum(node.value) && node.value < 0) return RED;
  if (node.category === 'tax') return DARK_RED;
  if (node.category === 'cost') return RED;
  if (node.category === 'profit') return GREEN;
  if (node.category === 'other') return BLUE;
  return SLATE;
}

function useIncomeFlow(symbol, name) {
  const [flow, setFlow] = React.useState(undefined); // undefined = loading, null = fetched-but-inapplicable
  React.useEffect(() => {
    if (!symbol) { setFlow(undefined); return; }
    let cancelled = false;
    setFlow(undefined);
    fetchRatio('/api/v1/income-statement-flow', symbol, name).then((r) => {
      if (cancelled) return;
      setFlow(r && r.applicable ? r : null);
    });
    return () => { cancelled = true; };
  }, [symbol, name]);
  return flow;
}

// AR-based flow response -> {nodes, links} in raw rupees (endpoint reports ₹ Cr).
function fromApiFlow(flow) {
  const nodes = flow.nodes.map((n) => ({ ...n, value: n.value * 1e7 }));
  const links = flow.links.map((l) => ({ ...l, value: l.value * 1e7 }));
  return { nodes, links };
}

// Shallow client-side fallback from income_stmt (raw rupees already), used
// only when the AR-based flow isn't applicable. Screener's generic P&L grid
// (Total Expenses/EBITDA/Pretax Income) is built for a manufacturing-style
// statement and is NOT reliable for banks/NBFCs/insurers — their "Expenses"
// row includes Interest Expended in a way that can make the derived
// "Operating Profit" come out negative even in a profitable year. Rather
// than ever show that kind of nonsensical breakdown, this only renders the
// richer Operating Profit / Interest & D&A / Tax levels when the figures
// are internally consistent (revenue >= operating profit >= PBT >= net
// profit, within tolerance); otherwise it collapses to the one split that's
// always true by definition: Revenue -> Costs & Tax (net) -> Net Profit.
function buildShallowFallback(incomeStmt) {
  const dates = incomeStmt ? Object.keys(incomeStmt).sort() : [];
  const latestDate = dates[dates.length - 1];
  const row = latestDate ? incomeStmt[latestDate] : null;
  if (!row) return null;
  const year = latestDate ? new Date(latestDate).getFullYear() : null;

  const revenue = Number(row['Total Revenue']);
  const netProfit = isNum(row['Net Income']) ? Number(row['Net Income']) : null;
  if (!isNum(revenue) || revenue <= 0 || !isNum(netProfit)) return null;
  const tol = Math.max(1e5, revenue * 0.003); // ₹0.3% of revenue or ₹0.1 Cr, whichever larger (raw rupees)

  let ebitda = isNum(row['EBITDA']) ? Number(row['EBITDA']) : null;
  let expenses = isNum(row['Total Expenses']) ? Number(row['Total Expenses']) : null;
  if (!isNum(ebitda) && isNum(revenue) && isNum(expenses)) ebitda = revenue - expenses;
  if (!isNum(expenses) && isNum(revenue) && isNum(ebitda)) expenses = revenue - ebitda;
  const pretax = isNum(row['Pretax Income']) ? Number(row['Pretax Income']) : null;

  const richDataPresent = isNum(ebitda) && isNum(expenses) && isNum(pretax);
  const orderingSane = richDataPresent
    && ebitda >= pretax - tol
    && pretax >= netProfit - tol
    && revenue >= ebitda - tol
    && ebitda > tol;

  if (orderingSane) {
    const interestDep = Math.max(ebitda - pretax, 0);
    const pretaxClamped = Math.min(Math.max(pretax, 0), ebitda);
    const tax = Math.max(pretaxClamped - Math.max(netProfit, 0), 0);
    const nodes = [
      { id: 'revenue', label: 'Revenue', value: revenue, category: 'neutral' },
      { id: 'expenses', label: 'Total Expenses', value: expenses, category: 'cost' },
      { id: 'operating_profit', label: 'Operating Profit', value: ebitda, category: 'profit' },
      { id: 'pbt_bridge', label: 'Interest & D&A', value: interestDep, category: 'cost' },
      { id: 'pbt', label: 'Profit Before Tax', value: pretaxClamped, category: 'profit' },
      { id: 'tax', label: 'Tax', value: tax, category: 'tax' },
      { id: 'net_profit', label: 'Net Profit', value: netProfit, category: 'profit' },
    ];
    const links = [
      { source: 'revenue', target: 'expenses', value: expenses },
      { source: 'revenue', target: 'operating_profit', value: ebitda },
      { source: 'operating_profit', target: 'pbt_bridge', value: interestDep },
      { source: 'operating_profit', target: 'pbt', value: pretaxClamped },
      { source: 'pbt', target: 'tax', value: tax },
      { source: 'pbt', target: 'net_profit', value: netProfit },
    ];
    return { nodes, links, year };
  }

  // Fallback of last resort: a single split that's true by construction
  // regardless of company type, never a fabricated/inconsistent breakdown.
  const costsAndTax = revenue - netProfit;
  if (costsAndTax < -tol) return null; // net profit exceeding revenue — too unusual to chart meaningfully
  const nodes = [
    { id: 'revenue', label: 'Revenue', value: revenue, category: 'neutral' },
    { id: 'costs_tax', label: 'Total Costs & Tax (net)', value: Math.max(costsAndTax, 0), category: 'cost',
      note: 'A detailed operating-profit breakdown is not reliable for this company’s statement format, '
        + 'so all costs and tax between Revenue and Net Profit are shown combined.' },
    { id: 'net_profit', label: 'Net Profit', value: netProfit, category: 'profit' },
  ];
  const links = [
    { source: 'revenue', target: 'costs_tax', value: Math.max(costsAndTax, 0) },
    { source: 'revenue', target: 'net_profit', value: netProfit },
  ];
  return { nodes, links, year };
}

// One row of the tree: color dot, label (truncates, never overflows the
// card — no fixed-width SVG canvas involved), a proportional weight bar,
// and a fixed-width right-aligned value column so numbers line up.
function TreeRow({ node, depth, parentAbsValue, isMergeSource }) {
  const [expanded] = React.useState(true);
  const pctOfParent = isNum(parentAbsValue) && parentAbsValue > 0
    ? Math.min(100, (Math.abs(node.value) / parentAbsValue) * 100)
    : 100;
  const color = colorFor(node);
  const title = node.note ? `${node.label} — ${node.note}` : node.label;

  return (
    <div
      className="flex items-center gap-2 py-1.5 border-b border-slate-800/60 last:border-b-0"
      style={{ paddingLeft: depth * 16 }}
    >
      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: color }} />
      <span className="text-[12px] text-slate-300 truncate shrink min-w-0 max-w-[38%]" title={title}>
        {node.label}{node.value < 0 ? ' (loss)' : ''}
        {isMergeSource && <span className="text-slate-600"> ↳</span>}
      </span>
      <div className="flex-1 min-w-[24px] h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${pctOfParent}%`, background: color, opacity: 0.75 }} />
      </div>
      <span className="text-[11px] nv-num text-slate-400 shrink-0 w-[86px] text-right tabular-nums">
        {inrCrore(node.value)}
      </span>
    </div>
  );
}

function IncomeTree({ nodes, links }) {
  const nodesById = {};
  nodes.forEach((n) => { nodesById[n.id] = n; });
  const childrenOf = {};
  const hasParent = new Set();
  links.forEach((l) => {
    if (!childrenOf[l.source]) childrenOf[l.source] = [];
    childrenOf[l.source].push(l.target);
    hasParent.add(l.target);
  });

  const rootCandidates = nodes.filter((n) => !hasParent.has(n.id));
  if (!rootCandidates.length) return null;
  // Business/geographic segments merging into Revenue (the one legitimate
  // many-to-one case) render as a compact "Revenue sources" list above the
  // tree, rather than forced into a strict parent/child indentation — a
  // tree can't visually represent a merge, so this keeps it honest instead
  // of picking one segment to "own" Revenue.
  const mergeSources = rootCandidates.length > 1 ? rootCandidates : [];
  const treeRootId = mergeSources.length
    ? childrenOf[mergeSources[0].id]?.[0]
    : rootCandidates[0].id;
  if (!treeRootId) return null;

  const rows = [];
  const rank = (id) => (nodesById[id].category === 'profit' ? 0 : nodesById[id].category === 'other' ? 1 : 2);
  (function walk(id, depth, parentAbsValue) {
    const node = nodesById[id];
    rows.push({ node, depth, parentAbsValue });
    const kids = [...(childrenOf[id] || [])].sort((a, b) => rank(a) - rank(b));
    kids.forEach((cid) => walk(cid, depth + 1, Math.abs(node.value) || 1));
  })(treeRootId, 0, null);

  const revenueAbs = Math.abs(nodesById[treeRootId]?.value) || 1;

  return (
    <div className="w-full min-w-0">
      {mergeSources.length > 0 && (
        <div className="mb-2 pb-2 border-b border-slate-700">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1">Revenue sources</div>
          {mergeSources.map((n) => (
            <TreeRow key={n.id} node={n} depth={0} parentAbsValue={revenueAbs} isMergeSource />
          ))}
        </div>
      )}
      <div className="w-full min-w-0">
        {rows.map(({ node, depth, parentAbsValue }, i) => (
          <TreeRow key={node.id + i} node={node} depth={depth} parentAbsValue={parentAbsValue} />
        ))}
      </div>
    </div>
  );
}

export default function IncomeSankey({ incomeStmt, symbol, companyName }) {
  const flow = useIncomeFlow(symbol, companyName);

  const apiReady = flow && flow.applicable && Array.isArray(flow.nodes) && flow.nodes.length;
  const graph = apiReady ? fromApiFlow(flow) : buildShallowFallback(incomeStmt);

  if (!graph) return null;

  const year = apiReady ? flow.fiscal_year : graph.year;
  const basisLabel = apiReady
    ? `${flow.basis === 'standalone' ? 'Standalone' : 'Consolidated'} · Annual Report`
    : 'Estimated · latest filed statements';

  return (
    <div className="nv-card p-4 h-full min-w-0 overflow-hidden">
      <div className="flex items-baseline justify-between mb-2 flex-wrap gap-1">
        <h2 className="nv-h2 text-[15px] text-slate-200 truncate">
          {companyName ? `${companyName} ` : ''}Income Statement
        </h2>
        <span className="text-[11px] text-slate-500 shrink-0">
          {year ? `FY${year}` : ''} · {basisLabel}
        </span>
      </div>
      <IncomeTree nodes={graph.nodes} links={graph.links} />
    </div>
  );
}
