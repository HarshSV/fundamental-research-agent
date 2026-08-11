import React from 'react';

const { useState } = React;

/*
 * Combined 4(+)-ring sunburst for qualitative sub-point A.1 ("Clarity of
 * Business Model"). Replaces what used to be two separate charts:
 *   - Ring 1 (innermost): reported business segments, sized by revenue
 *     share, colored by that segment's own Recurring/Mixed/Cyclical pattern
 *     (never inferred from segment name — see tools/qualitative_engine.py's
 *     compute_business_composition).
 *   - Outer rings: the SAME reconciled Revenue -> ... -> Net Profit P&L
 *     waterfall already used by IncomeIcicle.jsx (nodes/links from
 *     tools/annual_report_financials.py's
 *     fetch_income_statement_flow_from_annual_report), walked level-by-level
 *     so the ring depth self-adapts to whatever that company's Annual Report
 *     actually discloses (e.g. a bank without a COGS split gets fewer rings,
 *     never a fabricated one).
 * All rings share the same 12-o'clock start angle and sweep clockwise. A
 * minimum-angle floor keeps thin slices (e.g. Tax, Finance Costs) readable —
 * the "borrowed" angle is taken proportionally from larger slices in the
 * same ring/sub-arc, and floored slices get an external leader-line label.
 */

const PATTERN_COLOR = {
    recurring: '#22c55e',
    mixed: '#3b82f6',
    cyclical: '#f59e0b',
    unclassified: '#64748b',
};
const PATTERN_LABEL = {
    recurring: 'Recurring',
    mixed: 'Mixed',
    cyclical: 'Cyclical',
    unclassified: 'Unclassified',
};
const FLOW_COLOR = {
    profit: '#22c55e',
    cost: '#ef4444',
    tax: '#b91c1c',
    other: '#60a5fa',
    neutral: '#94a3b8',
};

const FLOOR_DEG = 9;

// Distributes `weights` across `spanDeg`, applying a minimum-angle floor —
// any slice that would fall below the floor is raised to it, and the
// deficit is taken proportionally from the remaining (non-floored) slices.
function anglesWithFloor(weights, spanDeg, floorDeg = FLOOR_DEG) {
    const n = weights.length;
    if (!n) return { angles: [], floored: new Set() };
    const total = weights.reduce((a, b) => a + b, 0) || 1;
    const floored = new Set();
    // Only apply a floor when it's actually achievable (enough slices*floor < span).
    const canFloor = n * floorDeg < spanDeg;
    let angles = weights.map((w) => (w / total) * spanDeg);
    if (canFloor) {
        for (let pass = 0; pass < 3; pass++) {
            angles.forEach((a, i) => { if (a < floorDeg - 1e-6) floored.add(i); });
            const flooredSpan = floored.size * floorDeg;
            const remaining = spanDeg - flooredSpan;
            const nonFlooredTotal = weights.reduce((s, w, i) => (floored.has(i) ? s : s + w), 0) || 1;
            angles = weights.map((w, i) => (floored.has(i) ? floorDeg : (w / nonFlooredTotal) * remaining));
        }
    }
    return { angles, floored };
}

function polar(cx, cy, r, angleDeg) {
    const rad = ((angleDeg - 90) * Math.PI) / 180;
    return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
}

function wedgePath(cx, cy, rInner, rOuter, startDeg, endDeg) {
    const span = Math.max(0.01, endDeg - startDeg);
    const large = span > 180 ? 1 : 0;
    const [ox1, oy1] = polar(cx, cy, rOuter, startDeg);
    const [ox2, oy2] = polar(cx, cy, rOuter, endDeg);
    const [ix1, iy1] = polar(cx, cy, rInner, endDeg);
    const [ix2, iy2] = polar(cx, cy, rInner, startDeg);
    return [
        `M ${ox1} ${oy1}`,
        `A ${rOuter} ${rOuter} 0 ${large} 1 ${ox2} ${oy2}`,
        `L ${ix1} ${iy1}`,
        `A ${rInner} ${rInner} 0 ${large} 0 ${ix2} ${iy2}`,
        'Z',
    ].join(' ');
}

export function inrCroreShort(v) {
    if (v == null) return '—';
    const abs = Math.abs(v);
    if (abs >= 100000) return `₹${(v / 100000).toFixed(2)}L Cr`;
    if (abs >= 1000) return `₹${(v / 1000).toFixed(2)}K Cr`;
    return `₹${v.toFixed(0)} Cr`;
}

// Walks the income-statement-flow nodes/links tree level by level so ring
// depth self-adapts to whatever the company's Annual Report discloses —
// mirrors IncomeIcicle.jsx's frontier walk, just producing angle levels
// instead of x-columns.
function buildFlowLevels(nodes, links) {
    if (!nodes?.length || !links?.length) return { root: null, levels: [] };
    const nodesById = {};
    nodes.forEach((n) => { nodesById[n.id] = n; });
    const childrenOf = {};
    const hasParent = new Set();
    links.forEach((l) => {
        (childrenOf[l.source] ||= []).push(l.target);
        hasParent.add(l.target);
    });
    const rootCandidates = nodes.filter((n) => !hasParent.has(n.id));
    let rootId = null;
    if (rootCandidates.length > 1) rootId = childrenOf[rootCandidates[0].id]?.[0];
    else if (rootCandidates.length === 1) rootId = rootCandidates[0].id;
    if (!rootId || !nodesById[rootId]) return { root: null, levels: [] };
    const root = nodesById[rootId];

    const levels = [];
    let frontier = [{ id: rootId, startDeg: 0, endDeg: 360 }];
    while (true) {
        const nextLevel = [];
        frontier.forEach((parent) => {
            const kidIds = (childrenOf[parent.id] || []).filter((cid) => nodesById[cid]);
            if (!kidIds.length) return;
            const weights = kidIds.map((cid) => Math.max(0, Math.abs(nodesById[cid].value)));
            const span = parent.endDeg - parent.startDeg;
            const { angles, floored } = anglesWithFloor(weights, span);
            let cur = parent.startDeg;
            kidIds.forEach((cid, i) => {
                const startDeg = cur, endDeg = cur + angles[i];
                cur = endDeg;
                nextLevel.push({
                    id: cid, node: nodesById[cid], startDeg, endDeg,
                    floored: floored.has(i), parentId: parent.id,
                });
            });
        });
        if (!nextLevel.length) break;
        levels.push(nextLevel);
        frontier = nextLevel;
        if (levels.length >= 4) break; // Ring 2/3/4 — never render more than 3 outer rings
    }
    return { root, levels };
}

const HoverCard = ({ item }) => (
    <div className="bg-slate-900 border border-slate-700 rounded-lg shadow-xl px-3 py-2 max-w-[240px]">
        <div className="flex items-center gap-1.5 mb-0.5">
            <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: item.color }} />
            <span className="text-[12px] font-bold text-slate-100">{item.label}</span>
        </div>
        {item.value != null && <p className="text-[11px] text-slate-300 nv-num">{inrCroreShort(item.value)}</p>}
        {item.pct != null && <p className="text-[10px] text-slate-500 mt-0.5">{item.pct.toFixed(1)}% of total</p>}
        {item.detail && <p className="text-[10px] text-slate-400 mt-1 leading-snug">{item.detail}</p>}
        {item.reasonPoints?.length > 0 && (
            <ul className="mt-1 space-y-0.5">
                {item.reasonPoints.map((p, i) => (
                    <li key={i} className="text-[10px] text-slate-400 leading-snug">• {p}</li>
                ))}
            </ul>
        )}
    </div>
);

export function SunburstChart({ chart }) {
    const [hover, setHover] = useState(null); // { item, x, y }
    const segments = chart?.segments || [];
    const { levels } = React.useMemo(() => buildFlowLevels(chart?.nodes, chart?.links), [chart?.nodes, chart?.links]);

    const hasRing1 = segments.length > 0;
    const hasFlow = levels.length > 0;
    if (!hasRing1 && !hasFlow) return null;

    const totalRevenueCr = chart?.totalRevenueCr ?? chart?.flowRevenueCr;
    const CX = 210, CY = 210;
    const RING_W = 34, RING_GAP = 2;
    const R0_IN = 46; // segment ring inner radius (leaves room for center label)

    // --- Ring 1: segments + residual, colored by pattern -------------------
    const segWeights = segments.map((s) => Math.max(0, s.share_pct || 0));
    const residualPct = chart?.residualPct || 0;
    const allWeights = residualPct > 0 ? [...segWeights, residualPct] : segWeights;
    const { angles: segAngles, floored: segFloored } = anglesWithFloor(allWeights, 360);
    let cur = 0;
    const ring1Items = segments.map((s, i) => {
        const startDeg = cur, endDeg = cur + segAngles[i];
        cur = endDeg;
        return {
            key: `seg-${i}`, startDeg, endDeg, floored: segFloored.has(i),
            label: s.name, value: s.external_revenue_cr, pct: s.share_pct,
            color: PATTERN_COLOR[s.pattern] || PATTERN_COLOR.unclassified,
            detail: `${PATTERN_LABEL[s.pattern] || 'Unclassified'} revenue`,
            reasonPoints: s.pattern_reason_points,
        };
    });
    if (residualPct > 0) {
        const i = segments.length;
        const startDeg = cur, endDeg = cur + segAngles[i];
        ring1Items.push({
            key: 'residual', startDeg, endDeg, floored: segFloored.has(i),
            label: 'Unallocated', value: chart?.residualCr, pct: residualPct,
            color: '#334155', detail: 'Consolidated revenue not attributed to a reported segment',
        });
    }

    // --- Outer rings: P&L waterfall levels ----------------------------------
    const outerRings = levels.map((level, li) => {
        const rIn = R0_IN + (RING_W + RING_GAP) * (1 + li);
        const rOut = rIn + RING_W;
        return {
            rIn, rOut,
            items: level.map((it, i) => ({
                key: `flow-${li}-${i}`, startDeg: it.startDeg, endDeg: it.endDeg, floored: it.floored,
                label: it.node.label, value: it.node.value,
                pct: totalRevenueCr ? (Math.abs(it.node.value) / totalRevenueCr) * 100 : null,
                color: FLOW_COLOR[it.node.category] || FLOW_COLOR.neutral,
                detail: it.node.note,
            })),
        };
    });

    const maxR = R0_IN + (RING_W + RING_GAP) * (1 + outerRings.length) + 10;
    const VB = maxR * 2 + 60;
    const centerOffset = VB / 2 - CX;
    const cx = CX + centerOffset, cy = CY + centerOffset;

    const showTip = (item, e) => setHover({ item, x: e.clientX, y: e.clientY });
    const hideTip = () => setHover(null);

    const renderRing = (items, rIn, rOut, leaderLaneR) => items.map((it) => {
        const midDeg = (it.startDeg + it.endDeg) / 2;
        // Single-line label only, sized to the wedge — a stacked name+% label
        // easily overflows a thin ring's radial band at angles far from 12/6
        // o'clock (the text is screen-vertical, not angle-rotated), bleeding
        // into the neighboring ring. Full value/% detail lives in the side
        // legend and the hover card instead, so nothing is lost.
        const canLabel = !it.floored && (it.endDeg - it.startDeg) >= 16;
        const [lx, ly] = polar(cx, cy, (rIn + rOut) / 2, midDeg);
        const maxChars = Math.max(4, Math.floor((it.endDeg - it.startDeg) / 4.2));
        const short = it.label && it.label.length > maxChars ? `${it.label.slice(0, Math.max(3, maxChars - 1))}…` : it.label;
        const pctText = it.pct != null ? `${it.pct.toFixed(1)}%` : null;
        return (
            <g key={it.key} onMouseMove={(e) => showTip(it, e)} onMouseLeave={hideTip} className="cursor-default">
                <path d={wedgePath(cx, cy, rIn, rOut, it.startDeg, it.endDeg)} fill={it.color} opacity={0.9}
                    stroke="#0f172a" strokeWidth="1.4" />
                {canLabel && (
                    <text x={lx} y={ly} textAnchor="middle" dominantBaseline="middle"
                        fontSize="9.5" fontWeight="800" fill="#ffffff" stroke="#0f172a" strokeWidth="2.75"
                        paintOrder="stroke" className="select-none pointer-events-none">
                        {short}
                    </text>
                )}
                {it.floored && (() => {
                    const [fx, fy] = polar(cx, cy, rOut, midDeg);
                    const [tx, ty] = polar(cx, cy, leaderLaneR, midDeg);
                    return (
                        <g className="pointer-events-none">
                            <line x1={fx} y1={fy} x2={tx} y2={ty} stroke="#94a3b8" strokeWidth="1.2" opacity="0.85" />
                            <text x={tx} y={ty} textAnchor={tx > cx ? 'start' : 'end'} dx={tx > cx ? 3 : -3}
                                dominantBaseline="middle" fontSize="9" fontWeight="700" fill="#f1f5f9" className="select-none">
                                {short}{pctText ? ` · ${pctText}` : ''}
                            </text>
                        </g>
                    );
                })()}
            </g>
        );
    });

    const leaderLaneR = maxR + 4;

    // Side data table — every wedge's exact value + %, grouped the same way
    // the rings are, so a reader who doesn't want to hover/decode the chart
    // can just read the numbers straight off the list next to it.
    const legendSections = [
        hasRing1 ? { title: 'Business Segments (Revenue)', items: ring1Items } : null,
        hasFlow ? { title: 'Income Statement Flow', items: outerRings.flatMap((r) => r.items) } : null,
    ].filter(Boolean);

    return (
        <div className="w-full flex flex-col lg:flex-row gap-4 items-start">
            <div className="flex-shrink-0 w-full lg:w-auto mx-auto" style={{ maxWidth: 460 }}>
                <svg viewBox={`0 0 ${VB} ${VB}`} className="w-full h-auto mx-auto block" style={{ maxWidth: 460, maxHeight: 460 }}>
                    {hasRing1 && renderRing(ring1Items, R0_IN, R0_IN + RING_W, leaderLaneR)}
                    {outerRings.map((r, i) => renderRing(r.items, r.rIn, r.rOut, leaderLaneR))}
                    <text x={cx} y={cy - 6} textAnchor="middle" fontSize="12" fontWeight="700" fill="#e2e8f0">
                        {inrCroreShort(totalRevenueCr)}
                    </text>
                    <text x={cx} y={cy + 10} textAnchor="middle" fontSize="8.5" fill="#94a3b8">
                        Total Revenue
                    </text>
                </svg>
                {hasRing1 && (
                    <div className="flex flex-wrap items-center justify-center gap-3 mt-2">
                        {['recurring', 'mixed', 'cyclical'].map((p) => (
                            <div key={p} className="flex items-center gap-1.5">
                                <span className="w-2.5 h-2.5 rounded-full" style={{ background: PATTERN_COLOR[p] }} />
                                <span className="text-[10px] text-slate-400">{PATTERN_LABEL[p]}</span>
                            </div>
                        ))}
                    </div>
                )}
                {!hasFlow && (
                    <p className="text-[10px] text-slate-500 italic text-center mt-2">
                        {chart?.flowUnavailableReason || 'Income statement flow not available for this company/period.'}
                    </p>
                )}
            </div>

            {legendSections.length > 0 && (
                <div className="flex-1 min-w-0 w-full space-y-4">
                    {legendSections.map((sec) => (
                        <div key={sec.title}>
                            <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">{sec.title}</div>
                            <div className="space-y-0.5">
                                {sec.items.map((it) => (
                                    <div key={it.key}
                                        onMouseEnter={(e) => showTip(it, e)} onMouseMove={(e) => showTip(it, e)} onMouseLeave={hideTip}
                                        className="flex items-center justify-between gap-2 px-2 py-1 rounded hover:bg-slate-800/60 cursor-default">
                                        <div className="flex items-center gap-2 min-w-0">
                                            <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: it.color }} />
                                            <span className="text-[12px] font-semibold text-slate-200 truncate">{it.label}</span>
                                        </div>
                                        <div className="flex items-baseline gap-2 flex-shrink-0">
                                            <span className="text-[12px] font-bold text-slate-100 nv-num">{inrCroreShort(it.value)}</span>
                                            <span className="text-[11px] font-semibold text-slate-400 w-12 text-right">
                                                {it.pct != null ? `${it.pct.toFixed(1)}%` : '—'}
                                            </span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {hover && (
                <div className="fixed z-50 pointer-events-none" style={{ left: hover.x + 12, top: hover.y - 8 }}>
                    <HoverCard item={hover.item} />
                </div>
            )}
        </div>
    );
}

export default SunburstChart;
