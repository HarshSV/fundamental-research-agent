import React from 'react';

const { useState } = React;

/*
 * C.7 — Capital allocation mix by year: a 4-category (Capex / M&A /
 * Buybacks / Dividends) stacked bar chart, one bar per fiscal year with
 * real reconciled Cash Flow Statement data (tools/qualitative_engine.py's
 * compute_c7_capital_allocation -> tools/annual_report_financials.py's
 * fetch_multi_year_cash_flow_items). Reuses the visual layout of
 * RecurringCyclicalTrendChart's TrendBars (stacked-bar-per-year, gap-honest
 * skipped-years handling) recolored for these 4 categories instead of
 * Recurring/Cyclical.
 *
 * A year whose row has one or more `missingCategories` (a category that
 * genuinely could not be parsed from that year's filing, per CLAUDE.md never
 * silently treated as 0%) is flagged via a small marker under that bar
 * rather than hidden — the mix % shown for that bar is only the split AMONG
 * the categories that WERE found that year, not a true 4-way split.
 */

const CATEGORY_COLORS = {
    Capex: '#3b82f6',      // blue — matches RECURRING_COLOR family for palette consistency
    'M&A': '#a855f7',      // purple
    Buybacks: '#f59e0b',   // amber
    Dividends: '#22c55e',  // green
};
const CATEGORY_ORDER = ['Capex', 'M&A', 'Buybacks', 'Dividends'];

const TrendBars = ({ trend }) => {
    const [hover, setHover] = useState(null);
    if (!trend?.length) return null;
    const W = 360, H = 210, PAD_T = 16, PAD_B = 34, PAD_L = 4, PAD_R = 4;
    const bodyH = H - PAD_T - PAD_B;
    const n = trend.length;
    const gap = 10;
    const barW = Math.min(50, (W - PAD_L - PAD_R - gap * (n - 1)) / n);
    const totalW = barW * n + gap * (n - 1);
    const startX = PAD_L + (W - PAD_L - PAD_R - totalW) / 2;

    return (
        <div className="flex-1 min-w-0">
            <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">
                {n === 1 ? `FY${String(trend[0].fiscal_year).slice(-2)} only — single year, not a trend` : `${n}-Year Capital Allocation Mix`}
            </div>
            <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" style={{ maxHeight: 220 }}>
                {[0, 25, 50, 75, 100].map((g) => {
                    const y = PAD_T + bodyH * (1 - g / 100);
                    return (
                        <g key={g}>
                            <line x1={PAD_L} y1={y} x2={W - PAD_R} y2={y} stroke="#1e293b" strokeWidth="1" />
                            <text x={PAD_L} y={y - 2} fontSize="7.5" fill="#64748b">{g}%</text>
                        </g>
                    );
                })}
                {trend.map((t, i) => {
                    const x = startX + i * (barW + gap);
                    const mix = t.mixPct || {};
                    let cursorY = PAD_T + bodyH;
                    const segs = CATEGORY_ORDER.map((cat) => {
                        const pct = mix[cat];
                        if (pct == null) return null;
                        const h = bodyH * (pct / 100);
                        const y = cursorY - h;
                        cursorY = y;
                        return { cat, pct, y, h };
                    }).filter(Boolean);
                    const key = t.fiscal_year;
                    const hasGap = (t.missingCategories || []).length > 0;
                    return (
                        <g key={key} onMouseEnter={() => setHover(key)} onMouseLeave={() => setHover(null)} style={{ cursor: 'default' }}>
                            {segs.map((s) => (
                                <rect key={s.cat} x={x} y={s.y} width={barW} height={Math.max(0, s.h)}
                                    fill={CATEGORY_COLORS[s.cat]} opacity={hover && hover !== key ? 0.55 : 0.95} rx="1.5" />
                            ))}
                            <text x={x + barW / 2} y={H - 20} textAnchor="middle" fontSize="9" fontWeight="700" fill="#94a3b8">
                                FY{String(t.fiscal_year).slice(-2)}
                            </text>
                            {hasGap && (
                                <text x={x + barW / 2} y={H - 8} textAnchor="middle" fontSize="8" fill="#f87171" title={t.missingCategories.join(', ')}>
                                    partial
                                </text>
                            )}
                            {hover === key && (
                                <g className="pointer-events-none">
                                    {segs.map((s, si) => (
                                        <text key={s.cat} x={x + barW / 2} y={PAD_T + 10 + si * 10} textAnchor="middle"
                                            fontSize="8.5" fontWeight="700" fill={CATEGORY_COLORS[s.cat]}>
                                            {s.cat}: {s.pct.toFixed(0)}%
                                        </text>
                                    ))}
                                </g>
                            )}
                        </g>
                    );
                })}
            </svg>
            <div className="flex flex-wrap items-center gap-3 mt-1">
                {CATEGORY_ORDER.map((cat) => (
                    <div key={cat} className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-full" style={{ background: CATEGORY_COLORS[cat] }} />
                        <span className="text-[11px] text-slate-300">{cat}</span>
                    </div>
                ))}
            </div>
            {trend.some((t) => (t.missingCategories || []).length > 0) && (
                <p className="text-[10px] text-slate-500 leading-relaxed mt-2">
                    "partial" years had at least one category (see tooltip data) not parseable from that year's
                    Cash Flow Statement — the mix % shown reflects only the categories that WERE found that year,
                    not a true 4-way split.
                </p>
            )}
        </div>
    );
};

export function CapitalAllocationTrendChart({ chart, unavailableReason }) {
    const trend = chart?.trend || [];
    if (!trend.length) {
        return (
            <p className="text-xs text-slate-500 italic">
                {unavailableReason || 'Not enough resolvable Annual Report years to build this view.'}
            </p>
        );
    }
    return (
        <div className="flex flex-col md:flex-row gap-6 items-center md:items-start">
            <TrendBars trend={trend} />
        </div>
    );
}

export default CapitalAllocationTrendChart;
