import React from 'react';
import { inrCrore, pct, isNum } from '../lib/format.js';

/*
 * Multi-Year Financial Comparison — grouped vertical bar chart, sits beside
 * IncomeSankey on the Overview page (does not touch or depend on it).
 *
 * Data sources — no mock values, nothing new fetched:
 *  - `incomeStmt`  : F-01 income_stmt (same prop already passed to IncomeSankey)
 *    -> Revenue / Cost / Net Profit / EBITDA / Operating Profit, per year.
 *  - `ratios`      : F-02_Ratio_Analysis array (already computed in Overview.jsx)
 *    -> ROE / ROCE / EBITDA Margin, per year.
 *  - `peer`        : data.peer_synthesis_data (tools/peer_synthesis.py), a
 *    CURRENT-YEAR-ONLY sector snapshot. Only 'roe' has a matching, unit-
 *    consistent peer figure (sector_averages.roe, a fraction — same
 *    convention as ratios[].ROE) — every other metric here has no real peer
 *    benchmark in the codebase, so no Peer Average bar is fabricated for
 *    them; the metric selector just omits a peer series in that case rather
 *    than inventing one.
 */

function stmtSeries(incomeStmt, field, fallbackFields = []) {
  if (!incomeStmt) return {};
  const out = {};
  Object.keys(incomeStmt).forEach((date) => {
    let v = incomeStmt[date]?.[field];
    if (!isNum(v)) {
      for (const f of fallbackFields) {
        if (isNum(incomeStmt[date]?.[f])) { v = incomeStmt[date][f]; break; }
      }
    }
    if (isNum(v)) out[date] = Number(v);
  });
  return out;
}

function ratioSeries(ratios, field) {
  const out = {};
  (ratios || []).forEach((r) => { if (isNum(r?.[field]) && r?.date) out[r.date] = Number(r[field]); });
  return out;
}

const RUPEE_COLOR = 'rgb(var(--blue-500))';
const COST_COLOR = 'rgb(var(--red-500))';
const PROFIT_COLOR = 'rgb(var(--emerald-500))';
const PEER_COLOR = 'rgb(var(--amber-500))';

function buildMetrics(incomeStmt, ratios, peer) {
  const peerRoe = isNum(peer?.sector_averages?.roe) ? peer.sector_averages.roe : null;
  const metrics = [
    {
      id: 'revenue', label: 'Revenue', unit: 'inr', bars: [
        { key: 'company', label: 'Revenue', color: RUPEE_COLOR, byDate: stmtSeries(incomeStmt, 'Total Revenue') },
      ],
    },
    {
      id: 'cost', label: 'Cost', unit: 'inr', bars: [
        { key: 'company', label: 'Total Expenses', color: COST_COLOR, byDate: stmtSeries(incomeStmt, 'Total Expenses') },
      ],
    },
    {
      id: 'net_profit', label: 'Net Profit', unit: 'inr', bars: [
        { key: 'company', label: 'Net Profit', color: PROFIT_COLOR, byDate: stmtSeries(incomeStmt, 'Net Income') },
      ],
    },
    {
      id: 'ebitda', label: 'EBITDA', unit: 'inr', bars: [
        { key: 'company', label: 'EBITDA', color: RUPEE_COLOR, byDate: stmtSeries(incomeStmt, 'EBITDA') },
      ],
    },
    {
      id: 'operating_profit', label: 'Operating Profit', unit: 'inr', bars: [
        { key: 'company', label: 'Operating Profit', color: RUPEE_COLOR, byDate: stmtSeries(incomeStmt, 'EBIT', ['Operating Income']) },
      ],
    },
    {
      id: 'ebitda_margin', label: 'EBITDA Margin', unit: 'pct', bars: [
        { key: 'company', label: 'EBITDA Margin', color: RUPEE_COLOR, byDate: ratioSeries(ratios, 'EBITDA_Margin') },
      ],
    },
    {
      id: 'roe', label: 'ROE', unit: 'pct', bars: [
        { key: 'company', label: 'ROE', color: RUPEE_COLOR, byDate: ratioSeries(ratios, 'ROE') },
        ...(isNum(peerRoe) ? [{ key: 'peer', label: 'Peer Avg ROE (current)', color: PEER_COLOR, constant: peerRoe }] : []),
      ],
    },
    {
      id: 'roce', label: 'ROCE', unit: 'pct', bars: [
        { key: 'company', label: 'ROCE', color: RUPEE_COLOR, byDate: ratioSeries(ratios, 'ROCE') },
      ],
    },
  ];
  // Only offer metrics that actually have >=2 real data points — never show
  // an empty/near-empty chart for a metric this company's filings don't support.
  return metrics.filter((m) => {
    const primary = m.bars.find((b) => b.key === 'company');
    return primary && Object.keys(primary.byDate || {}).length >= 2;
  });
}

function formatVal(v, unit) {
  if (!isNum(v)) return '—';
  return unit === 'pct' ? pct(v) : inrCrore(v);
}

const TOOLTIP_W = 240;

function ComparisonTooltip({ hover }) {
  if (!hover) return null;
  const { bar, year, value, yoy, peerDiff, unit, clientX, clientY } = hover;
  let left = clientX + 16;
  if (left + TOOLTIP_W > window.innerWidth - 8) left = clientX - 16 - TOOLTIP_W;
  left = Math.max(8, left);
  let top = clientY + 16;
  if (top > window.innerHeight - 140) top = clientY - 130;
  return (
    <div className="pointer-events-none fixed z-50 nv-card px-3 py-2 shadow-lg border border-slate-800" style={{ left, top, width: TOOLTIP_W }}>
      <div className="text-[11px] font-semibold text-slate-200">{bar.label}</div>
      <div className="text-[10px] text-slate-500">{year}</div>
      <div className="text-[13px] font-bold nv-num text-slate-100 mt-1">{formatVal(value, unit)}</div>
      {isNum(yoy) && (
        <div className={`text-[10px] mt-0.5 ${yoy >= 0 ? 'nv-pos' : 'nv-neg'}`}>{yoy >= 0 ? '+' : ''}{(yoy * 100).toFixed(1)}% YoY</div>
      )}
      {isNum(peerDiff) && (
        <div className="text-[10px] text-slate-500 mt-0.5">{peerDiff >= 0 ? '+' : ''}{(peerDiff * 100).toFixed(1)}pp vs peer avg</div>
      )}
    </div>
  );
}

export default function FinancialComparisonChart({ incomeStmt, ratios, peer, companyName }) {
  const metrics = React.useMemo(() => buildMetrics(incomeStmt, ratios, peer), [incomeStmt, ratios, peer]);
  const [metricId, setMetricId] = React.useState(metrics[0]?.id);
  const [hover, setHover] = React.useState(null);
  React.useEffect(() => {
    if (!metrics.find((m) => m.id === metricId)) setMetricId(metrics[0]?.id);
  }, [metrics]); // eslint-disable-line react-hooks/exhaustive-deps

  const metric = metrics.find((m) => m.id === metricId);
  if (!metric) return null;

  const primaryBar = metric.bars.find((b) => b.key === 'company');
  // Some sources key a trailing-twelve-months column as "TTM" alongside real
  // fiscal-year-end dates — filter to genuinely parseable dates only, or the
  // x-axis renders "FYaN" for that column.
  const dates = Object.keys(primaryBar.byDate).filter((d) => !isNaN(new Date(d).getTime())).sort();
  const years = dates.slice(-6).reverse(); // latest first, up to 6 years

  // Floor prevents a divide-by-zero scale when every value is 0, but must be
  // unit-aware: a flat "1" floor is fine for rupee metrics (₹1 is negligible)
  // but pins percentage metrics (fractions like 0.09) to a 100% axis top.
  const rawMax = Math.max(
    0,
    ...years.flatMap((d) => metric.bars.map((b) => (isNum(b.byDate?.[d]) ? Math.abs(b.byDate[d]) : (isNum(b.constant) ? Math.abs(b.constant) : 0)))),
  );
  const floor = metric.unit === 'pct' ? 0.01 : 1;
  const maxVal = Math.max(rawMax, floor) * 1.12;

  const W = 620, H = 300, pad = { l: 8, r: 8, t: 12, b: 34 };
  const plotH = H - pad.t - pad.b;
  const plotW = W - pad.l - pad.r;
  const clusterW = plotW / years.length;
  const barGap = 4;
  const barW = Math.max(6, (clusterW - barGap * (metric.bars.length + 1)) / metric.bars.length);

  const yTicks = 4;

  return (
    <div className="nv-card p-4 h-full flex flex-col">
      <div className="flex items-baseline justify-between mb-2 flex-wrap gap-1">
        <h2 className="nv-h2 text-[15px] text-slate-200">
          {companyName ? `${companyName} ` : ''}Multi-Year Comparison
        </h2>
        <span className="text-[11px] text-slate-500">Last {years.length} FY · {metric.label}</span>
      </div>

      <div className="flex flex-wrap gap-1.5 mb-3">
        {metrics.map((m) => (
          <button
            key={m.id}
            onClick={() => setMetricId(m.id)}
            className={`text-[10.5px] font-semibold px-2.5 py-1 rounded-full border transition-colors ${
              m.id === metricId
                ? 'bg-blue-500/10 border-blue-500/40 text-blue-500'
                : 'border-slate-800 text-slate-500 hover:text-slate-300 hover:border-slate-700'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      <div className="flex-1 flex items-center justify-center min-h-[260px]">
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} className="max-w-[640px]">
          {/* gridlines */}
          {Array.from({ length: yTicks + 1 }).map((_, i) => {
            const y = pad.t + (plotH / yTicks) * i;
            const val = maxVal * (1 - i / yTicks);
            return (
              <g key={i}>
                <line x1={pad.l} x2={W - pad.r} y1={y} y2={y} stroke="rgb(var(--slate-800))" strokeWidth="1" />
                <text x={pad.l} y={y - 3} className="fill-slate-500 text-[8.5px] nv-num">{formatVal(val, metric.unit)}</text>
              </g>
            );
          })}

          {years.map((d, yi) => {
            const cx0 = pad.l + yi * clusterW;
            const isLatest = yi === 0;
            const fy = `FY${new Date(d).getFullYear().toString().slice(-2)}`;
            return (
              <g key={d}>
                {isLatest && (
                  <rect x={cx0 + 1} y={pad.t} width={clusterW - 2} height={plotH} fill="rgb(var(--blue-500))" opacity="0.06" rx="3" />
                )}
                {metric.bars.map((bar, bi) => {
                  const raw = isNum(bar.byDate?.[d]) ? bar.byDate[d] : (isNum(bar.constant) ? bar.constant : null);
                  if (!isNum(raw)) return null;
                  const h = Math.max((Math.abs(raw) / maxVal) * plotH, 1);
                  const x = cx0 + barGap + bi * (barW + barGap);
                  const y = pad.t + plotH - h;
                  // YoY: previous (older) date relative to this bar's own series
                  const prevDate = dates[dates.indexOf(d) - 1];
                  const prevVal = isNum(bar.byDate?.[prevDate]) ? bar.byDate[prevDate] : null;
                  const yoy = (isNum(prevVal) && prevVal !== 0 && bar.key === 'company') ? (raw - prevVal) / Math.abs(prevVal) : null;
                  const companyVal = primaryBar.byDate?.[d];
                  const peerDiff = (bar.key === 'company' && metric.bars.some((b) => b.key === 'peer'))
                    ? raw - metric.bars.find((b) => b.key === 'peer').constant
                    : null;
                  return (
                    <rect
                      key={bar.key}
                      x={x} y={y} width={barW} height={h} fill={bar.color} rx="2"
                      className="cursor-pointer transition-opacity hover:opacity-80"
                      onMouseEnter={(e) => setHover({ bar, year: fy, value: raw, yoy, peerDiff, unit: metric.unit, clientX: e.clientX, clientY: e.clientY })}
                      onMouseMove={(e) => setHover({ bar, year: fy, value: raw, yoy, peerDiff, unit: metric.unit, clientX: e.clientX, clientY: e.clientY })}
                      onMouseLeave={() => setHover(null)}
                    />
                  );
                })}
                <text
                  x={cx0 + clusterW / 2} y={H - pad.b + 14} textAnchor="middle"
                  className={`text-[10px] nv-num ${isLatest ? 'fill-blue-500 font-bold' : 'fill-slate-500'}`}
                >
                  {fy}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-1 justify-center">
        {metric.bars.map((b) => (
          <div key={b.key} className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-sm" style={{ background: b.color }} />
            <span className="text-[10px] text-slate-500">{b.label}</span>
          </div>
        ))}
      </div>

      <ComparisonTooltip hover={hover} />
    </div>
  );
}
