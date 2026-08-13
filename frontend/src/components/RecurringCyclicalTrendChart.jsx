import React from 'react';

const { useState } = React;

/*
 * 1B — "Current year mix" donut + "N-year trend" stacked bar, real
 * revenue-weighted Recurring/Cyclical % per year from
 * tools/qualitative_engine.py's compute_a1_2_pattern_trend (never a fixed
 * 5-year mockup — the trend only shows years that actually had a
 * reconciled segment note; a company with fewer resolvable years just
 * shows fewer bars).
 */

const RECURRING_COLOR = '#3b82f6'; // matches PATTERN_COLOR.mixed in SunburstChart for palette consistency
const CYCLICAL_COLOR = '#f59e0b';

function polar(cx, cy, r, angleDeg) {
    const rad = ((angleDeg - 90) * Math.PI) / 180;
    return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}

function donutArcPath(cx, cy, rInner, rOuter, startDeg, endDeg) {
    const span = Math.max(0.01, Math.min(359.99, endDeg - startDeg));
    const large = span > 180 ? 1 : 0;
    const [ox1, oy1] = polar(cx, cy, rOuter, startDeg);
    const [ox2, oy2] = polar(cx, cy, rOuter, startDeg + span);
    const [ix1, iy1] = polar(cx, cy, rInner, startDeg + span);
    const [ix2, iy2] = polar(cx, cy, rInner, startDeg);
    return [
        `M ${ox1} ${oy1}`, `A ${rOuter} ${rOuter} 0 ${large} 1 ${ox2} ${oy2}`,
        `L ${ix1} ${iy1}`, `A ${rInner} ${rInner} 0 ${large} 0 ${ix2} ${iy2}`, 'Z',
    ].join(' ');
}

const CurrentYearDonut = ({ mix }) => {
    const [hover, setHover] = useState(null);
    if (!mix) return null;
    const recurring = mix.recurring_pct ?? 0;
    const cyclical = mix.cyclical_pct ?? 0;
    const cx = 90, cy = 90, rIn = 52, rOut = 82;
    const recurringEnd = (recurring / 100) * 360;
    const slices = [
        { key: 'recurring', label: 'Recurring', pct: recurring, color: RECURRING_COLOR, start: 0, end: recurringEnd },
        { key: 'cyclical', label: 'Cyclical', pct: cyclical, color: CYCLICAL_COLOR, start: recurringEnd, end: 360 },
    ].filter((s) => s.pct > 0);

    return (
        <div className="flex flex-col items-center">
            <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">
                Current Year Mix{mix.fiscal_year ? ` · FY${String(mix.fiscal_year).slice(-2)}` : ''}
            </div>
            <svg viewBox="0 0 180 180" className="w-full max-w-[180px]">
                {slices.map((s) => (
                    <path key={s.key} d={donutArcPath(cx, cy, rIn, rOut, s.start, s.end)} fill={s.color}
                        opacity={hover && hover !== s.key ? 0.5 : 0.95} stroke="#0f172a" strokeWidth="1.5"
                        onMouseEnter={() => setHover(s.key)} onMouseLeave={() => setHover(null)} style={{ cursor: 'default' }} />
                ))}
                <text x={cx} y={cy - 4} textAnchor="middle" fontSize="18" fontWeight="800" fill="#e2e8f0">
                    {Math.round(recurring)}%
                </text>
                <text x={cx} y={cy + 14} textAnchor="middle" fontSize="9" fill="#94a3b8">Recurring</text>
            </svg>
            <div className="flex items-center gap-4 mt-2">
                <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ background: RECURRING_COLOR }} />
                    <span className="text-[11px] text-slate-300">Recurring {recurring.toFixed(0)}%</span>
                </div>
                <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ background: CYCLICAL_COLOR }} />
                    <span className="text-[11px] text-slate-300">Cyclical {cyclical.toFixed(0)}%</span>
                </div>
            </div>
        </div>
    );
};

// A single data point is NOT a trend — labelling one bar "1-Year Trend" (or,
// worse, padding the chart with years that were never actually measured) is
// how this card previously showed a fabricated 3-year swing for HINDUNILVR.
// One plottable year is labelled as a single year and says why the others
// are missing; the bars themselves only ever come from real segment notes.
const SKIP_REASON_TEXT = {
    NO_RECONCILED_SEGMENT_NOTE: 'no reconciled segment note in that filing',
    CLASSIFIER_UNREACHABLE: 'classifier unavailable this run',
    ANNUAL_REPORT_UNREADABLE: 'Annual Report not machine-readable',
    ANNUAL_REPORT_FETCH_FAILED: 'Annual Report could not be fetched',
    NO_REVENUE_ON_PL_PAGE: 'revenue not found on the P&L page',
    NO_SEGMENT_CLASSIFIED: 'no segment could be classified',
};

const SkippedYearsNote = ({ skippedYears }) => {
    if (!skippedYears?.length) return null;
    const byReason = {};
    skippedYears.forEach((s) => {
        (byReason[s.reason] = byReason[s.reason] || []).push(s.fiscal_year);
    });
    return (
        <p className="text-[10px] text-slate-500 leading-relaxed mt-2">
            {Object.entries(byReason).map(([reason, yrs], i) => (
                <span key={reason}>
                    {i > 0 && ' '}
                    {`FY${yrs.sort().map((y) => String(y).slice(-2)).join(', FY')} not plotted — ${SKIP_REASON_TEXT[reason] || reason}.`}
                </span>
            ))}
        </p>
    );
};

const TrendBars = ({ trend, skippedYears }) => {
    const [hover, setHover] = useState(null);
    if (!trend?.length) return null;
    const W = 320, H = 190, PAD_T = 16, PAD_B = 26, PAD_L = 4, PAD_R = 4;
    const bodyH = H - PAD_T - PAD_B;
    const n = trend.length;
    const gap = 10;
    const barW = Math.min(46, (W - PAD_L - PAD_R - gap * (n - 1)) / n);
    const totalW = barW * n + gap * (n - 1);
    const startX = PAD_L + (W - PAD_L - PAD_R - totalW) / 2;

    return (
        <div className="flex-1 min-w-0">
            <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">
                {n === 1 ? `FY${String(trend[0].fiscal_year).slice(-2)} only — single year, not a trend` : `${n}-Year Trend`}
            </div>
            <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" style={{ maxHeight: 200 }}>
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
                    const recH = bodyH * (t.recurring_pct / 100);
                    const cycH = bodyH * (t.cyclical_pct / 100);
                    const key = t.fiscal_year;
                    return (
                        <g key={key} onMouseEnter={() => setHover(key)} onMouseLeave={() => setHover(null)} style={{ cursor: 'default' }}>
                            <rect x={x} y={PAD_T + bodyH - recH} width={barW} height={Math.max(0, recH)}
                                fill={RECURRING_COLOR} opacity={hover && hover !== key ? 0.55 : 0.95} rx="1.5" />
                            <rect x={x} y={PAD_T + bodyH - recH - cycH} width={barW} height={Math.max(0, cycH)}
                                fill={CYCLICAL_COLOR} opacity={hover && hover !== key ? 0.55 : 0.95} rx="1.5" />
                            <text x={x + barW / 2} y={H - 8} textAnchor="middle" fontSize="9" fontWeight="700" fill="#94a3b8">
                                FY{String(t.fiscal_year).slice(-2)}
                            </text>
                            {hover === key && (
                                <g className="pointer-events-none">
                                    <text x={x + barW / 2} y={PAD_T + bodyH - recH - cycH - 6} textAnchor="middle"
                                        fontSize="9" fontWeight="800" fill="#e2e8f0">
                                        {t.recurring_pct.toFixed(0)}% / {t.cyclical_pct.toFixed(0)}%
                                    </text>
                                </g>
                            )}
                        </g>
                    );
                })}
            </svg>
            <SkippedYearsNote skippedYears={skippedYears} />
        </div>
    );
};

export function RecurringCyclicalTrendChart({ chart, unavailableReason }) {
    const mix = chart?.currentYearMix;
    const trend = chart?.trend || [];
    if (!mix && !trend.length) {
        return (
            <p className="text-xs text-slate-500 italic">
                {unavailableReason || 'Not enough resolvable Annual Report years to build this view.'}
            </p>
        );
    }
    return (
        <div className="flex flex-col md:flex-row gap-6 items-center md:items-start">
            <CurrentYearDonut mix={mix} />
            <TrendBars trend={trend} skippedYears={chart?.skippedYears} />
        </div>
    );
}

export default RecurringCyclicalTrendChart;
