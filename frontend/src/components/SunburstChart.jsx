import React from 'react';

const { useState } = React;

/*
 * Combined 4(+)-ring sunburst for qualitative sub-point A.1 ("Clarity of
 * Business Model"). Replaces what used to be two separate charts:
 *   - Ring 1 (innermost): reported business segments, sized by revenue
 *     share, colored by that segment's own Recurring/Mixed/Cyclical pattern
 *     (never inferred from segment name - see tools/qualitative_engine.py's
 *     compute_business_composition).
 *   - Outer rings: the SAME reconciled Revenue -> ... -> Net Profit P&L
 *     waterfall already used by IncomeIcicle.jsx (nodes/links from
 *     tools/annual_report_financials.py's
 *     fetch_income_statement_flow_from_annual_report), walked level-by-level
 *     so the ring depth self-adapts to whatever that company's Annual Report
 *     actually discloses (e.g. a bank without a COGS split gets fewer rings,
 *     never a fabricated one).
 * All rings share the same 12-o'clock start angle and sweep clockwise. A
 * minimum-angle floor keeps thin slices (e.g. Tax, Finance Costs) readable -
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

// Small standalone donut: current-year Recurring vs Cyclical revenue mix,
// derived from the SAME revenue-weighted pattern score already computed by
// compute_business_composition (0 = fully recurring, 1 = fully cyclical) -
// no new backend computation, just a second, simpler view of it. "Mixed"
// segments aren't a separate slice here (they're already blended into the
// 0-1 score by revenue weight), matching the score's own definition.
function RecurringCyclicalDonut({ score, label }) {
    if (score == null) return null;
    const recurringPct = Math.round((1 - score) * 100);
    const cyclicalPct = 100 - recurringPct;
    const R = 42, CXY = 50, SW = 16;
    const circumference = 2 * Math.PI * R;
    const recurringLen = (recurringPct / 100) * circumference;
    return (
        <div>
            <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">Current Year Mix</div>
            <div className="flex items-center gap-4">
                <svg viewBox="0 0 100 100" className="flex-shrink-0" style={{ width: 90, height: 90 }}>
                    <circle cx={CXY} cy={CXY} r={R} fill="none" stroke={PATTERN_COLOR.cyclical} strokeWidth={SW} />
                    <circle cx={CXY} cy={CXY} r={R} fill="none" stroke={PATTERN_COLOR.recurring} strokeWidth={SW}
                        strokeDasharray={`${recurringLen} ${circumference - recurringLen}`}
                        transform={`rotate(-90 ${CXY} ${CXY})`} strokeLinecap="butt" />
                </svg>
                <div className="space-y-1">
                    <div className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: PATTERN_COLOR.recurring }} />
                        <span className="text-[11px] text-slate-300">Recurring <span className="font-bold text-slate-100">{recurringPct}%</span></span>
                    </div>
                    <div className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: PATTERN_COLOR.cyclical }} />
                        <span className="text-[11px] text-slate-300">Cyclical <span className="font-bold text-slate-100">{cyclicalPct}%</span></span>
                    </div>
                    {label && (
                        <p className="text-[9px] text-slate-500 pt-0.5">
                            {{ recurring_leaning: 'Recurring-leaning', cyclical_leaning: 'Cyclical-leaning', mixed: 'Mixed', unclassified: 'Unclassified' }[label] || label}
                        </p>
                    )}
                </div>
            </div>
        </div>
    );
}

// Distributes `weights` across `spanDeg`, applying a minimum-angle floor -
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
    if (v == null) return '-';
    const abs = Math.abs(v);
    if (abs >= 100000) return `₹${(v / 100000).toFixed(2)}L Cr`;
    if (abs >= 1000) return `₹${(v / 1000).toFixed(2)}K Cr`;
    return `₹${v.toFixed(0)} Cr`;
}

// Walks the income-statement-flow nodes/links tree level by level so ring
// depth self-adapts to whatever the company's Annual Report discloses -
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
        if (levels.length >= 4) break; // Ring 2/3/4 - never render more than 3 outer rings
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
        {item.segmentSourced != null && (
            <p className={`text-[9.5px] mt-1 font-semibold ${item.segmentSourced ? 'text-emerald-400' : 'text-amber-400'}`}>
                {item.segmentSourced ? "Sourced from this segment's own AR text" : 'No segment-specific AR text found - company-wide / general reasoning'}
            </p>
        )}
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
            segmentSourced: s.segment_sourced,
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

    // Rough monospace-ish width estimate for our bold 9.5px label font, used
    // to decide whether a wedge is wide enough (in actual on-screen pixels at
    // its own radius, not just angular degrees) to hold its FULL label
    // inline - never truncated. Anything that doesn't fit gets a leader-line
    // label instead, drawn in a dedicated side lane sized to fit the
    // longest one of those in full (same idea as IncomeIcicle.jsx's overflow
    // lane) so a long name like "Purchases of stock-in-trade" never clips.
    const estTextPx = (label) => (label ? label.length * 5.7 + 4 : 0);
    const needsLeader = (it, rIn, rOut) => {
        const spanDeg = it.endDeg - it.startDeg;
        const midR = (rIn + rOut) / 2;
        // Text renders as a straight horizontal line, not a curved one, so
        // the available width is the wedge's CHORD at its own radius - not
        // the (longer) arc length. Using arc length overestimated how much
        // room a thin/acute wedge actually offered, which let long labels
        // ("Operating Expenses", "Profit Before Tax"...) render inline on
        // slivers too small for them and pile up on top of each other/
        // neighbouring rings. A 1.25x safety margin plus a higher minimum
        // span keeps genuinely-marginal wedges on the leader-line path
        // (which IS collision-checked against every other label) instead.
        const spanRad = (spanDeg * Math.PI) / 180;
        const chordPx = 2 * midR * Math.sin(spanRad / 2);
        return !(spanDeg >= 20 && chordPx >= estTextPx(it.label) * 1.25);
    };
    let maxLeaderLabelPx = 0;
    const _trackMaxLeader = (it) => {
        const px = estTextPx(it.label) + (it.pct != null ? 42 : 0);
        if (px > maxLeaderLabelPx) maxLeaderLabelPx = px;
    };
    if (hasRing1) ring1Items.forEach((it) => { if (needsLeader(it, R0_IN, R0_IN + RING_W)) _trackMaxLeader(it); });
    outerRings.forEach((r) => r.items.forEach((it) => { if (needsLeader(it, r.rIn, r.rOut)) _trackMaxLeader(it); }));
    const labelLaneW = Math.max(40, Math.min(220, maxLeaderLabelPx));

    const maxR = R0_IN + (RING_W + RING_GAP) * (1 + outerRings.length) + 10;
    // BASE_VB is what the viewBox would be with no side label lanes at all -
    // the ring geometry (R0_IN, RING_W...) is defined in these units.
    // BASE_DISPLAY_PX is how big the rings themselves should read on screen;
    // adding the label lanes below only grows VB, and DISPLAY_PX scales the
    // rendered size by the same factor so the rings stay at (at least) that
    // size instead of shrinking inside a now-larger viewBox.
    const BASE_VB = maxR * 2 + 60;
    const VB = BASE_VB + labelLaneW * 2;
    const BASE_DISPLAY_PX = 620;
    const DISPLAY_PX = Math.min(860, Math.round(BASE_DISPLAY_PX * (VB / BASE_VB)));
    const centerOffset = VB / 2 - CX;
    const cx = CX + centerOffset, cy = CY + centerOffset;

    const showTip = (item, e) => setHover({ item, x: e.clientX, y: e.clientY });
    const hideTip = () => setHover(null);

    // The chord-vs-text-width check above only guarantees a label fits
    // WITHIN its own wedge - it says nothing about whether two DIFFERENT
    // rings' inline labels, at nearby angles, end up close enough on screen
    // to collide with each other (this happens often on the "profit" side,
    // where a node's angular position barely moves from one P&L level to
    // the next - e.g. Operating Profit -> Profit Before Tax often sit at
    // almost the same angle, just one ring further out). So: walk every
    // item inner-ring-first, and only keep a candidate inline if its
    // estimated on-screen box doesn't overlap any inline label already
    // accepted; anything that collides gets demoted to a leader-line label,
    // which IS fully collision-checked (both against other leaders and
    // against these accepted inline boxes) in the pass below.
    const finalInlineMap = new Map();
    {
        const accepted = [];
        const PAD = 4;
        // Half-height generous enough to cover the bold font + its 2.75px
        // outline stroke, which getBBox() alone under-reports.
        const HALF_H = 10;
        const decide = (it, rIn, rOut) => {
            if (needsLeader(it, rIn, rOut)) { finalInlineMap.set(it.key, false); return; }
            const midR = (rIn + rOut) / 2;
            const midDeg = (it.startDeg + it.endDeg) / 2;
            const [lx, ly] = polar(cx, cy, midR, midDeg);
            const halfW = estTextPx(it.label) / 2;
            const collides = accepted.some((a) =>
                Math.abs(a.x - lx) < (a.halfW + halfW + PAD) && Math.abs(a.y - ly) < (a.halfH + HALF_H + PAD));
            if (collides) { finalInlineMap.set(it.key, false); }
            else { finalInlineMap.set(it.key, true); accepted.push({ x: lx, y: ly, halfW, halfH: HALF_H }); }
        };
        if (hasRing1) ring1Items.forEach((it) => decide(it, R0_IN, R0_IN + RING_W));
        outerRings.forEach((r) => r.items.forEach((it) => decide(it, r.rIn, r.rOut)));
    }

    const leaderQueue = [];
    // Every INLINE label's (side, y) position, so leader-line labels get
    // laid out around them too - without this, a leader label's collision
    // avoidance only looked at other leader labels and could still land
    // right on top of an inner ring's inline text.
    const inlineObstacles = [];
    // Inline <text> elements are collected here and rendered in ONE pass
    // AFTER every ring's <path>s (see the JSX below) instead of interleaved
    // ring-by-ring. Interleaving meant a later (outer) ring's semi-opaque
    // wedge - drawn after an inner ring's label - could paint over any part
    // of that label that grazed the ring boundary, showing up as a faded/
    // "ghosted" word. Drawing every path first, then every label on top,
    // makes that impossible regardless of how close two rings' geometry
    // happens to sit.
    const inlineLabels = [];

    const renderRing = (items, rIn, rOut) => items.map((it) => {
        const midDeg = (it.startDeg + it.endDeg) / 2;
        const midR = (rIn + rOut) / 2;
        const fitsInline = finalInlineMap.get(it.key) || false;
        const [lx, ly] = polar(cx, cy, midR, midDeg);
        if (!fitsInline) {
            leaderQueue.push({ key: it.key, label: it.label, pct: it.pct, midDeg, outerR: rOut });
        } else {
            inlineObstacles.push({ midDeg, midR });
            inlineLabels.push({ key: it.key, label: it.label, lx, ly });
        }
        return (
            <g key={it.key} onMouseMove={(e) => showTip(it, e)} onMouseLeave={hideTip} className="cursor-default">
                <path d={wedgePath(cx, cy, rIn, rOut, it.startDeg, it.endDeg)} fill={it.color} opacity={0.9}
                    stroke="#0f172a" strokeWidth="1.4" />
            </g>
        );
    });

    const leaderLaneR = maxR + 4;

    // Lays every queued leader-line label out on a per-side (left/right)
    // vertical lane, pushing any label that would collide with the one
    // above/below it - OR with an inline label from a closer-in ring sitting
    // in the same vertical region - further along that lane. Same "no two
    // labels ever overlap" guarantee IncomeIcicle.jsx uses for its own
    // overflow labels, adapted to polar coordinates and extended to treat
    // inline labels as fixed obstacles rather than only spacing leaders
    // against each other.
    const layoutLeaders = (items, obstacles) => {
        const LABEL_H = 13;
        const withPos = items.map((it) => {
            const [nx, ny] = polar(cx, cy, leaderLaneR, it.midDeg);
            return { ...it, nx, ny, labelY: ny, side: nx >= cx ? 'right' : 'left' };
        });
        const obsPos = obstacles.map((o) => {
            const [ox, oy] = polar(cx, cy, o.midR, o.midDeg);
            return { y: oy, side: ox >= cx ? 'right' : 'left' };
        });
        ['left', 'right'].forEach((side) => {
            const combined = [
                ...withPos.filter((it) => it.side === side).map((it) => ({ ref: it, y: it.labelY, fixed: false })),
                ...obsPos.filter((it) => it.side === side).map((it) => ({ ref: null, y: it.y, fixed: true })),
            ].sort((a, b) => a.y - b.y);
            let prevBottom = -Infinity;
            combined.forEach((entry) => {
                let top = entry.y - LABEL_H / 2;
                if (!entry.fixed && top < prevBottom) {
                    entry.y += prevBottom - top;
                    entry.ref.labelY = entry.y;
                }
                prevBottom = Math.max(prevBottom, entry.y + LABEL_H / 2);
            });
        });
        return withPos;
    };

    // Side data table - every wedge's exact value + %, grouped the same way
    // the rings are, so a reader who doesn't want to hover/decode the chart
    // can just read the numbers straight off the list next to it.
    const legendSections = [
        hasRing1 ? { title: 'Business Segments (Revenue)', items: ring1Items } : null,
        hasFlow ? { title: 'Income Statement Flow', items: outerRings.flatMap((r) => r.items) } : null,
    ].filter(Boolean);

    // Capped by vw too, not just a fixed px ceiling - otherwise a wide chart
    // (e.g. 860px) crowds the side legend down to an unreadably narrow
    // column on a typical ~1280px window. min() keeps it as big as
    // DISPLAY_PX allows while always leaving room for the legend next to it.
    const chartMaxWidth = `min(${DISPLAY_PX}px, 56vw)`;

    return (
        <div className="w-full flex flex-col lg:flex-row gap-4 items-start">
            <div className="mx-auto lg:mx-0" style={{ width: '100%', maxWidth: chartMaxWidth, flex: `0 1 ${DISPLAY_PX}px` }}>
                <svg viewBox={`0 0 ${VB} ${VB}`} className="w-full h-auto mx-auto block" style={{ maxWidth: chartMaxWidth, maxHeight: chartMaxWidth }}>
                    {hasRing1 && renderRing(ring1Items, R0_IN, R0_IN + RING_W)}
                    {outerRings.map((r, i) => renderRing(r.items, r.rIn, r.rOut))}
                    {inlineLabels.map((it) => (
                        <text key={it.key} x={it.lx} y={it.ly} textAnchor="middle" dominantBaseline="middle"
                            fontSize="9.5" fontWeight="800" fill="#ffffff" stroke="#0f172a" strokeWidth="2.75"
                            paintOrder="stroke" className="select-none pointer-events-none">
                            {it.label}
                        </text>
                    ))}
                    {layoutLeaders(leaderQueue, inlineObstacles).map((it) => {
                        const [fx, fy] = polar(cx, cy, it.outerR, it.midDeg);
                        const labelX = it.side === 'right' ? cx + leaderLaneR : cx - leaderLaneR;
                        const pctText = it.pct != null ? ` · ${it.pct.toFixed(1)}%` : '';
                        return (
                            <g key={it.key} className="pointer-events-none">
                                <polyline points={`${fx},${fy} ${it.nx},${it.labelY} ${labelX},${it.labelY}`}
                                    fill="none" stroke="#94a3b8" strokeWidth="1" opacity="0.7" />
                                <text x={labelX + (it.side === 'right' ? 4 : -4)} y={it.labelY}
                                    textAnchor={it.side === 'right' ? 'start' : 'end'} dominantBaseline="middle"
                                    fontSize="9" fontWeight="700" fill="#f1f5f9" className="select-none">
                                    {it.label}{pctText}
                                </text>
                            </g>
                        );
                    })}
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
                    {chart?.weightedPatternScore != null && (
                        <RecurringCyclicalDonut score={chart.weightedPatternScore} label={chart.weightedPatternLabel} />
                    )}
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
                                                {it.pct != null ? `${it.pct.toFixed(1)}%` : '-'}
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
