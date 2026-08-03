import React from 'react';
import { inrCrore, pct, isNum } from '../lib/format.js';
import { fetchRatio } from '../lib/api.js';

/*
 * Income-statement Sankey for the stock Overview page. Renders a nodes/links
 * graph (see `buildNodesFromFlow` / `buildShallowFallback`) as a generic,
 * variable-depth waterfall — never a fixed Apple-shaped schema. Node depth
 * and count adapt to whatever the source data actually discloses.
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
const DARK_RED = 'rgb(var(--red-500))';
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

function ribbonPath(x1, y1Top, y1Bot, x2, y2Top, y2Bot) {
  const cx = (x1 + x2) / 2;
  return [
    `M${x1},${y1Top}`,
    `C${cx},${y1Top} ${cx},${y2Top} ${x2},${y2Top}`,
    `L${x2},${y2Bot}`,
    `C${cx},${y2Bot} ${cx},${y1Bot} ${x1},${y1Bot}`,
    'Z',
  ].join(' ');
}

// Recursive proportional-partition layout: a node's [y0,y1] span is divided
// among its children by each child link's share of the node's own value —
// works for any depth/branching since every node in this graph has exactly
// one parent (a tree, never a merge).
function layoutTree(nodeId, nodesById, childrenOf, x0, xStep, y0, y1, depth, out) {
  const node = nodesById[nodeId];
  const h = Math.max(y1 - y0, 0);
  out.bars.push({ node, x: x0, y0, y1, depth });

  const kids = childrenOf[nodeId] || [];
  if (!kids.length || h <= 0) return;
  const parentVal = Math.abs(node.value) || kids.reduce((s, k) => s + Math.abs(k.link.value), 0) || 1;
  let cursor = y0;
  for (const { link, childId } of kids) {
    const frac = Math.min(Math.max(Math.abs(link.value) / parentVal, 0), 1);
    const childH = h * frac;
    const cy0 = cursor, cy1 = cursor + childH;
    out.ribbons.push({ x1: x0 + xStep.barW, y1Top: cy0, y1Bot: cy1, x2: x0 + xStep.col, color: colorFor(nodesById[childId]) });
    layoutTree(childId, nodesById, childrenOf, x0 + xStep.col, xStep, cy0, cy1, depth + 1, out);
    cursor = cy1;
  }
}

function IncomeFlowChart({ nodes, links, revenue, width = 900, height = 320 }) {
  const nodesById = {};
  nodes.forEach((n) => { nodesById[n.id] = n; });
  const childrenOf = {};
  const hasParent = new Set();
  links.forEach((l) => {
    if (!childrenOf[l.source]) childrenOf[l.source] = [];
    childrenOf[l.source].push({ link: l, childId: l.target });
    hasParent.add(l.target);
  });
  const rootId = nodes.find((n) => !hasParent.has(n.id))?.id;
  if (!rootId) return null;

  let maxDepth = 0;
  (function findDepth(id, d) {
    maxDepth = Math.max(maxDepth, d);
    (childrenOf[id] || []).forEach(({ childId }) => findDepth(childId, d + 1));
  })(rootId, 0);

  const pad = 24;
  const barW = 9;
  const usableW = width - pad * 2 - barW;
  const col = maxDepth > 0 ? usableW / maxDepth : usableW;
  const usableH = height - pad * 2;

  const out = { bars: [], ribbons: [] };
  layoutTree(rootId, nodesById, childrenOf, pad, { barW, col }, pad, pad + usableH, 0, out);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} className="min-w-[680px]">
      {out.ribbons.map((r, i) => (
        <path key={i} d={ribbonPath(r.x1, r.y1Top, r.y1Bot, r.x2, r.y1Top, r.y1Bot)} fill={r.color} opacity="0.16" />
      ))}
      {out.bars.map(({ node, x, y0, y1, depth }, i) => {
        const h = Math.max(y1 - y0, 1.5);
        const align = depth === maxDepth ? 'right' : 'left';
        const textX = align === 'left' ? x - 10 : x + barW + 10;
        const anchor = align === 'left' ? 'end' : 'start';
        const revPct = isNum(revenue) && revenue > 0 ? (Math.abs(node.value) / revenue) * 100 : null;
        const tooltip = [
          node.label,
          inrCrore(node.value),
          isNum(revPct) ? `${revPct.toFixed(1)}% of Revenue` : null,
          node.note || null,
        ].filter(Boolean).join('\n');
        return (
          <g key={node.id + i}>
            <rect x={x} y={y0} width={barW} height={h} fill={colorFor(node)} rx="1.5">
              <title>{tooltip}</title>
            </rect>
            <text x={textX} y={y0 + h / 2 - 6} textAnchor={anchor} className="fill-slate-200 text-[11px] font-semibold">
              {node.label}{node.value < 0 ? ' (loss)' : ''}
            </text>
            <text x={textX} y={y0 + h / 2 + 9} textAnchor={anchor} className="fill-slate-500 text-[10px] nv-num">
              {inrCrore(node.value)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export default function IncomeSankey({ incomeStmt, symbol, companyName }) {
  const flow = useIncomeFlow(symbol, companyName);

  const apiReady = flow && flow.applicable && Array.isArray(flow.nodes) && flow.nodes.length;
  const graph = apiReady ? fromApiFlow(flow) : buildShallowFallback(incomeStmt);
  if (!graph) return null;

  const revenueNode = graph.nodes.find((n) => n.id === 'revenue' || n.category === 'neutral');
  const revenue = revenueNode ? revenueNode.value : null;
  const year = apiReady ? flow.fiscal_year : graph.year;
  const basisLabel = apiReady
    ? `${flow.basis === 'standalone' ? 'Standalone' : 'Consolidated'} · Annual Report`
    : 'Estimated · latest filed statements';

  return (
    <div className="nv-card p-4">
      <div className="flex items-baseline justify-between mb-2 flex-wrap gap-1">
        <h2 className="nv-h2 text-[15px] text-slate-200">
          {companyName ? `${companyName} ` : ''}Income Statement
        </h2>
        <span className="text-[11px] text-slate-500">
          Revenue → Profit &amp; Cost Flow{year ? ` · FY${year}` : ''} · {basisLabel}
        </span>
      </div>
      <div className="w-full overflow-x-auto">
        <IncomeFlowChart nodes={graph.nodes} links={graph.links} revenue={revenue} />
      </div>
    </div>
  );
}
