import React from 'react';
import { createPortal } from 'react-dom';

const { useState, useRef } = React;

/*
 * Straight-edge icicle-style flow diagram — shared by the Overview page
 * (via IncomeSankey.jsx's default export) and the Qualitative Analysis
 * page's "Consolidated Income Statement Flow" card, so both render the
 * SAME chart for the SAME nodes/links tree (see IncomeTree in
 * IncomeSankey.jsx for the reconciliation-safe tree-building logic this
 * mirrors). Node and its outgoing flow are drawn as ONE continuous opaque
 * shape (like a single cut of paper) with only a thin darker "stripe" at
 * each node's own x-position — that's what makes adjacent flows read as
 * distinct, sharp-edged ribbons instead of a blocky, disjointed pattern.
 *
 * Column/bar geometry is computed entirely in viewBox units so it can
 * never overflow the card regardless of how many levels or how long
 * labels are. Labels are only drawn inline on a bar when there's room
 * without overlapping a neighbor; blocks too small for that get a
 * leader-line label in a small lane right after their own column
 * (sized to fit the longest such label, no truncation) instead of being
 * left unlabeled. Every bar (labeled or not) exposes its full detail via
 * hover, so no information is ever lost to a bar too small to caption.
 */

const ICICLE_COLOR = {
    profit: 'rgb(34 197 94)',
    cost: 'rgb(239 68 68)',
    tax: 'rgb(185 28 28)',
    other: 'rgb(96 165 250)',
    neutral: 'rgb(100 116 139)',
};
const icicleColorFor = (node) => {
    if (isFiniteNum(node.value) && node.value < 0) return 'rgb(239 68 68)';
    return ICICLE_COLOR[node.category] || ICICLE_COLOR.neutral;
};
const ICICLE_STRIPE_COLOR = {
    profit: 'rgb(21 128 61)',
    cost: 'rgb(153 27 27)',
    tax: 'rgb(127 29 29)',
    other: 'rgb(37 99 235)',
    neutral: 'rgb(51 65 85)',
};
function isFiniteNum(v) { return typeof v === 'number' && Number.isFinite(v); }

export function inrCroreShort(v) {
    const cr = v / 1e7; // v arrives in raw rupees, same convention as IncomeTree
    const abs = Math.abs(cr);
    if (abs >= 100000) return `₹${(cr / 100000).toFixed(2)}L Cr`;
    if (abs >= 1000) return `₹${(cr / 1000).toFixed(2)}K Cr`;
    return `₹${cr.toFixed(0)} Cr`;
}

const IcicleHoverCard = ({ n }) => (
    <div className="bg-slate-900 border border-slate-700 rounded-lg shadow-xl px-3 py-2 max-w-[220px]">
        <div className="flex items-center gap-1.5 mb-0.5">
            <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: icicleColorFor(n) }} />
            <span className="text-[12px] font-bold text-slate-100">{n.label}</span>
        </div>
        <p className="text-[11px] text-slate-300 nv-num">{inrCroreShort(n.value)}</p>
        {n.pctOfRoot != null && (
            <p className="text-[10px] text-slate-500 mt-0.5">{n.pctOfRoot.toFixed(1)}% of Revenue</p>
        )}
        {n.pctOfParent != null && n.parentLabel && (
            <p className="text-[10px] text-slate-500">{n.pctOfParent.toFixed(1)}% of {n.parentLabel}</p>
        )}
    </div>
);

export function IncomeIcicle({ nodes, links }) {
    const [hover, setHover] = useState(null); // { n, x, y }
    const wrapRef = useRef(null);

    const layout = React.useMemo(() => {
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
        const mergeSources = rootCandidates.length > 1 ? rootCandidates : [];
        const treeRootId = mergeSources.length ? childrenOf[mergeSources[0].id]?.[0] : rootCandidates[0].id;
        if (!treeRootId || !nodesById[treeRootId]) return null;

        const rank = (id) => (nodesById[id].category === 'profit' ? 0 : nodesById[id].category === 'other' ? 1 : 2);
        const depthOffset = mergeSources.length ? 1 : 0;
        // bars: { node, depth, y0, y1 (own rendered slot, WITH a gap
        // before each non-first sibling), height, srcY0, srcY1
        // (the tight, gap-free slice this flow occupies inside its
        // PARENT's slot — used only for the link's parent-side edge),
        // parentId, parentLabel }. mergeLinks handles the reverse,
        // many-to-one case (several segments merging into one
        // Revenue bar) separately since a single "srcY" pair on the
        // child can't represent multiple distinct parents.
        const bars = [];
        const mergeLinks = []; // { fromBar, toY0, toY1 } — segment's own (gapped) slot -> its tight slice inside Revenue

        let rawRootTotal;
        if (mergeSources.length) rawRootTotal = mergeSources.reduce((s, m) => s + (Math.abs(m.value) || 0), 0) || 1;
        else rawRootTotal = Math.abs(nodesById[treeRootId].value) || 1;
        // A small gap between sibling blocks — same convention the
        // reference "straight-edge" icicle uses — is what makes a
        // flow band read as a distinct diagonal ribbon rather than a
        // flat, indistinguishable rectangle: the band has to bridge
        // from its tight (gap-free) slice inside the parent to its
        // own gapped slot, so it necessarily slants.
        const GAP = rawRootTotal * 0.012;

        // Level 0
        if (mergeSources.length) {
            let cur = 0;
            mergeSources.forEach((ms) => {
                const h = Math.abs(ms.value) || 0;
                bars.push({ node: ms, depth: 0, y0: cur, y1: cur + h, height: h, srcY0: null, srcY1: null, parentId: null, parentLabel: null });
                cur += h + GAP;
            });
            // Revenue itself: one bar, no internal gap (it's a single
            // node), fed by every segment above. Each segment's link
            // targets a tight, contiguous slice of Revenue matching
            // segment order — that contiguous-vs-gapped mismatch is
            // what makes the segment->Revenue bands slant too.
            bars.push({ node: nodesById[treeRootId], depth: depthOffset, y0: 0, y1: rawRootTotal, height: rawRootTotal, srcY0: null, srcY1: null, parentId: null, parentLabel: null });
            let slice = 0;
            mergeSources.forEach((ms) => {
                const h = Math.abs(ms.value) || 0;
                const fromBar = bars.find((b) => b.node.id === ms.id);
                mergeLinks.push({ fromBar, toY0: slice, toY1: slice + h });
                slice += h;
            });
        } else {
            bars.push({ node: nodesById[treeRootId], depth: depthOffset, y0: 0, y1: rawRootTotal, height: rawRootTotal, srcY0: null, srcY1: null, parentId: null, parentLabel: null });
        }

        // Walk level by level (not a single DFS) so every sibling's
        // gapped position at depth d is finalized before its own
        // children's positions (depth d+1) are computed from it.
        let frontier = bars.filter((b) => b.depth === depthOffset);
        let depth = depthOffset;
        while (frontier.length) {
            // Collect this level's children first (tight, gap-free
            // slice inside each parent — this is the link's true
            // source-side edge), grouped in parent-frontier order.
            const nextRaw = [];
            frontier.forEach((parentBar) => {
                const kids = [...(childrenOf[parentBar.node.id] || [])].filter((cid) => nodesById[cid]).sort((a, b) => rank(a) - rank(b));
                const total = kids.reduce((s, cid) => s + (Math.abs(nodesById[cid].value) || 0), 0);
                let cur = parentBar.y0;
                kids.forEach((cid) => {
                    const share = total > 0 ? (Math.abs(nodesById[cid].value) || 0) / total : 0;
                    const h = share * (parentBar.y1 - parentBar.y0);
                    nextRaw.push({
                        node: nodesById[cid], depth: depth + 1, height: h,
                        srcY0: cur, srcY1: cur + h,
                        parentId: parentBar.node.id, parentLabel: parentBar.node.label,
                    });
                    cur += h;
                });
            });
            // Now place them top-down in their own column WITH a gap
            // between each — this is what shifts them away from
            // their tight source slice and produces the diagonal.
            let cur = 0;
            nextRaw.forEach((b) => {
                b.y0 = cur; b.y1 = cur + b.height;
                cur += b.height + GAP;
            });
            bars.push(...nextRaw);
            frontier = nextRaw;
            depth += 1;
        }

        // The whole chart's vertical scale must use ONE consistent
        // pixel-per-value ratio across every column (that's what
        // makes narrowing/widening between columns meaningful), so
        // find the tallest column's total gapped extent and scale
        // everything to fit that — columns with fewer/larger gaps
        // just don't use the full height, they don't get stretched.
        const maxDepth = bars.reduce((m, b) => Math.max(m, b.depth), 0);
        let layoutExtent = rawRootTotal;
        for (let d = 0; d <= maxDepth; d++) {
            const colMax = bars.filter((b) => b.depth === d).reduce((m, b) => Math.max(m, b.y1), 0);
            layoutExtent = Math.max(layoutExtent, colMax);
        }

        return { bars, mergeLinks, rootTotal: rawRootTotal, layoutExtent, maxDepth, hasMergeSources: mergeSources.length > 0 };
    }, [nodes, links]);

    if (!layout) return null;
    const { bars, mergeLinks, rootTotal, layoutExtent, maxDepth, hasMergeSources } = layout;

    const COL_W = 180, NODE_LINE_W = 3, HEADER_H = 34, BODY_H = 320, PAD_B = 6;
    const totalH = HEADER_H + BODY_H + PAD_B;
    const yPix = (v) => HEADER_H + (v / layoutExtent) * BODY_H;
    const MIN_LABEL_H = 20;

    // Header per column = the topmost (y0 === 0) bar in that depth —
    // the continuous "spine" (Revenue -> Operating Profit -> PBT ->
    // Net Profit) that every icicle chart anchors at the top edge.
    // Skipped for the leftmost segments column (if any) since those
    // are parallel siblings, not a spine — each already gets its own
    // inline label, same as the reference chart.
    const headerByDepth = {};
    bars.forEach((b) => {
        if (hasMergeSources && b.depth === 0) return;
        if (b.y0 <= 1e-9) {
            const existing = headerByDepth[b.depth];
            if (!existing || b.y1 - b.y0 > existing.y1 - existing.y0) headerByDepth[b.depth] = b;
        }
    });

    const showTip = (b, e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        const parentBar = bars.find(x => x.node.id === b.parentId);
        const n = {
            ...b.node,
            pctOfRoot: (Math.abs(b.node.value) / rootTotal) * 100,
            pctOfParent: parentBar && parentBar.height > 0 ? (b.height / parentBar.height) * 100 : null,
            parentLabel: b.parentLabel,
        };
        setHover({ n, x: rect.left + rect.width / 2, y: rect.top });
    };
    const hideTip = () => setHover(null);

    // First pass, in VALUE-space only (no x yet): find which nodes
    // are too small to caption inline, per depth — used next to
    // decide which columns need a little extra room right after
    // them for a leader-line label. This keeps every label close to
    // the exact block/angle it belongs to instead of parking them
    // all in one far-away margin.
    const rawOverflowByDepth = {}; // depth -> [{ key, bar, fromY(value units) }]
    const noteOverflow = (key, bar, ry0v, ry1v) => {
        const isHeader = headerByDepth[bar.depth] === bar;
        if (isHeader) return;
        const ry0 = yPix(ry0v), ry1 = yPix(ry1v);
        if (ry1 - ry0 >= MIN_LABEL_H) return;
        (rawOverflowByDepth[bar.depth] ||= []).push({ key, bar, fromYv: (ry0v + ry1v) / 2 });
    };
    (mergeLinks || []).forEach((m) => noteOverflow(`merge-${m.fromBar.node.id}`, m.fromBar, m.toY0, m.toY1));
    bars.forEach((b) => {
        if (!b.parentId || b.srcY0 == null) return;
        noteOverflow(`edge-${b.node.id}`, b, b.y0, b.y1);
    });

    // Column x-positions: every column is COL_W wide, plus a small
    // extra lane right after any column that has overflow labels to
    // place — so a label always lands immediately beside the block
    // it describes, never far across the chart. The lane is sized to
    // fit the LONGEST overflow label in full (no truncation) rather
    // than a fixed guess.
    const maxOverflowLabelLen = Object.values(rawOverflowByDepth)
        .flat().reduce((m, it) => Math.max(m, it.bar.node.label.length), 0);
    const LABEL_LANE_W = Math.min(260, Math.max(70, maxOverflowLabelLen * 5.6 + 26));
    const colX = [0];
    for (let d = 0; d <= maxDepth; d++) {
        colX.push(colX[d] + COL_W + (rawOverflowByDepth[d]?.length ? LABEL_LANE_W : 0));
    }
    const totalW = colX[maxDepth + 1];

    // One unified edge list — a real parent->child link, or a
    // segment->Revenue merge link — each rendered as a single opaque
    // trapezoid running from just past the source node's stripe to
    // just before the target node's stripe.
    const edges = [];
    (mergeLinks || []).forEach((m) => {
        edges.push({
            key: `merge-${m.fromBar.node.id}`, bar: m.fromBar,
            x1: colX[m.fromBar.depth] + NODE_LINE_W, x2: colX[m.fromBar.depth + 1],
            ly0: m.fromBar.y0, ly1: m.fromBar.y1, ry0: m.toY0, ry1: m.toY1,
        });
    });
    bars.forEach((b) => {
        if (!b.parentId || b.srcY0 == null) return;
        const parentBar = bars.find(x => x.node.id === b.parentId);
        if (!parentBar) return;
        edges.push({
            key: `edge-${b.node.id}`, bar: b,
            x1: colX[parentBar.depth] + NODE_LINE_W, x2: colX[b.depth],
            ly0: b.srcY0, ly1: b.srcY1, ry0: b.y0, ry1: b.y1,
        });
    });

    // Now place each overflow label within its OWN column's lane
    // (right after that column's node stripe), stacked top-to-bottom
    // so labels sharing a lane never overlap each other.
    const LEADER_ROW_H = 14;
    const overflowGeom = {}; // key -> { fromX, fromY, labelX, labelY }
    Object.entries(rawOverflowByDepth).forEach(([depthStr, items]) => {
        const depth = Number(depthStr);
        const laneX = colX[depth] + COL_W;
        const sorted = [...items].sort((a, b) => a.fromYv - b.fromYv);
        let cur = HEADER_H + LEADER_ROW_H / 2;
        sorted.forEach((it) => {
            const fromY = yPix(it.fromYv);
            const labelY = Math.max(fromY, cur);
            overflowGeom[it.key] = { fromX: colX[depth] + NODE_LINE_W, fromY, labelX: laneX, labelY };
            cur = labelY + LEADER_ROW_H;
        });
    });

    return (
        <div ref={wrapRef} className="w-full overflow-hidden">
            <svg viewBox={`0 0 ${totalW} ${totalH}`} className="w-full h-auto" style={{ maxHeight: 420 }} preserveAspectRatio="xMidYMid meet">
                {edges.map((e) => {
                    const fill = icicleColorFor(e.bar.node);
                    const ly0 = yPix(e.ly0), ly1 = yPix(e.ly1), ry0 = yPix(e.ry0), ry1 = yPix(e.ry1);
                    const isHeader = headerByDepth[e.bar.depth] === e.bar;
                    const minH = Math.min(ly1 - ly0, ry1 - ry0);
                    const canLabel = !isHeader && minH >= MIN_LABEL_H && (e.x2 - e.x1) >= 40;
                    const midX = (e.x1 + e.x2) / 2;
                    const midY = ((ly0 + ly1) / 2 + (ry0 + ry1) / 2) / 2;
                    const maxChars = Math.floor((e.x2 - e.x1) / 6.2);
                    const label = e.bar.node.label.length > maxChars
                        ? e.bar.node.label.slice(0, Math.max(3, maxChars - 1)) + '…' : e.bar.node.label;
                    const leader = !isHeader && !canLabel ? overflowGeom[e.key] : null;
                    return (
                        <g key={e.key} className="cursor-default"
                            onMouseEnter={(ev) => showTip(e.bar, ev)} onMouseLeave={hideTip}>
                            <polygon points={`${e.x1},${ly0} ${e.x1},${ly1} ${e.x2},${ry1} ${e.x2},${ry0}`}
                                fill={fill} opacity={0.82} />
                            {canLabel && (
                                <text x={midX} y={midY} textAnchor="middle" dominantBaseline="middle"
                                    className="select-none" fontSize="10.5" fontWeight="600" fill="white">
                                    {label}
                                </text>
                            )}
                            {leader && (
                                <>
                                    <polyline
                                        points={`${leader.fromX},${leader.fromY} ${leader.labelX - 6},${leader.labelY} ${leader.labelX},${leader.labelY}`}
                                        fill="none" stroke={ICICLE_STRIPE_COLOR[e.bar.node.category] || ICICLE_STRIPE_COLOR.neutral}
                                        strokeWidth="1" opacity={0.75} />
                                    <text x={leader.labelX + 4} y={leader.labelY} dominantBaseline="middle"
                                        className="select-none" fontSize="9.5" fontWeight="600" fill="rgb(203 213 225)">
                                        {e.bar.node.label}
                                    </text>
                                </>
                            )}
                        </g>
                    );
                })}
                {/* thin accent stripe at every node's own x-position —
                    the only visual seam between one flow and the next */}
                {bars.map((b, i) => (
                    <rect key={`stripe-${i}`} x={colX[b.depth]} y={yPix(b.y0)} width={NODE_LINE_W}
                        height={Math.max(1, yPix(b.y1) - yPix(b.y0))}
                        fill={ICICLE_STRIPE_COLOR[b.node.category] || ICICLE_STRIPE_COLOR.neutral}
                        onMouseEnter={(e) => showTip(b, e)} onMouseLeave={hideTip} className="cursor-default" />
                ))}
                {/* column headers — always visible, never overlaps edge labels since it lives in the reserved header band */}
                {Object.values(headerByDepth).map((b, i) => (
                    <g key={`hdr-${i}`}>
                        <text x={colX[b.depth] + NODE_LINE_W / 2} y={HEADER_H - 20} textAnchor="middle"
                            fontSize="10.5" fontWeight="700" fill="rgb(226 232 240)">
                            {b.node.label.length > 18 ? b.node.label.slice(0, 17) + '…' : b.node.label}
                        </text>
                        <text x={colX[b.depth] + NODE_LINE_W / 2} y={HEADER_H - 8} textAnchor="middle"
                            fontSize="9.5" fill="rgb(148 163 184)">
                            {inrCroreShort(b.node.value)}
                        </text>
                    </g>
                ))}
            </svg>
            {hover && createPortal(
                <div className="fixed z-50 pointer-events-none transition-opacity duration-100"
                    style={{ left: hover.x, top: hover.y - 8, transform: 'translate(-50%, -100%)' }}>
                    <IcicleHoverCard n={hover.n} />
                </div>,
                document.body
            )}
        </div>
    );
}
