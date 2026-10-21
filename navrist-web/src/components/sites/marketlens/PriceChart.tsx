"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  OUTCOME_COLOR, OUTCOME_LABEL, STATUS_COLOR, STATUS_LABEL, displayName, markerOf,
  type CatalogueEntry, type MarkerKind, type PatternOcc,
} from "./patterns";

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

const DAY = 86400;
const H = 320;
const PAD_L = 60;
const PAD_B = 28;

const fmt = (v: number | null | undefined, d = 2) =>
  v == null ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtDate = (ts: number) =>
  new Date(ts * 1000).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

const KIND_COLOR: Record<MarkerKind, string> = {
  forming: STATUS_COLOR.forming,
  awaiting: STATUS_COLOR.awaiting_breakout,
  positive: OUTCOME_COLOR.positive,
  negative: OUTCOME_COLOR.negative,
  pending: OUTCOME_COLOR.pending,
  flat: OUTCOME_COLOR.flat,
  not_evaluable: OUTCOME_COLOR.not_evaluable,
  invalidated: STATUS_COLOR.invalidated,
};

/** index of the first candle at or after ts (binary search); -1 when ts is after the last candle */
function idxAtOrAfter(candles: Candle[], ts: number): number {
  let lo = 0;
  let hi = candles.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (candles[mid].time < ts) lo = mid + 1;
    else hi = mid;
  }
  return lo >= candles.length ? -1 : lo;
}

interface Group {
  kind: MarkerKind;
  i: number; // anchor candle (latest in the group)
  items: PatternOcc[];
}

export function PriceChart({
  candles, intraday, live, occs, catalogue, selectedId, onSelect,
}: {
  candles: Candle[];
  intraday: boolean;
  live: boolean;
  occs: PatternOcc[];
  catalogue: Record<string, CatalogueEntry>;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(1000);
  const [hover, setHover] = useState<number | null>(null);
  const [group, setGroup] = useState<Group | null>(null);

  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth || 1000));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const closes = candles.map((c) => c.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min || 1;
  const x = (i: number) => PAD_L + (i / Math.max(closes.length - 1, 1)) * (w - PAD_L);
  const y = (v: number) => 10 + (1 - (v - min) / span) * (H - PAD_B - 20);
  const yc = (v: number) => Math.min(H - PAD_B, Math.max(2, y(v))); // clamp levels outside the visible range
  const line = closes.map((c, i) => `${x(i)},${y(c)}`).join(" ");
  const area = `${PAD_L},${H - PAD_B} ${line} ${w},${H - PAD_B}`;
  const ticks = [0, 1, 2, 3, 4].map((k) => min + (span * k) / 4);
  const labelIdx = [0, 1, 2, 3, 4].map((k) => Math.round((k / 4) * (candles.length - 1)));
  const shortSpan = candles[candles.length - 1].time - candles[0].time < 2 * DAY;
  const axisLabel = (t: number) => {
    const d = new Date(t * 1000);
    return shortSpan
      ? d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false })
      : d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  };

  // ---- markers: one per occurrence, merged on screen when same-kind markers sit within 16px ------
  const groups = useMemo<Group[]>(() => {
    const placed = occs
      .map((o) => ({ o, ...markerOf(o) }))
      .map((m) => ({ ...m, i: idxAtOrAfter(candles, m.ts) }))
      .filter((m) => m.i >= 0 && candles[m.i].time === m.ts)
      .sort((a, b) => a.i - b.i);
    const perPx = (w - PAD_L) / Math.max(candles.length - 1, 1);
    const out: Group[] = [];
    const lastByKind = new Map<MarkerKind, Group>();
    for (const m of placed) {
      const g = lastByKind.get(m.kind);
      if (g && (m.i - g.i) * perPx <= 16) {
        g.items.push(m.o);
        g.i = m.i;
      } else {
        const ng: Group = { kind: m.kind, i: m.i, items: [m.o] };
        out.push(ng);
        lastByKind.set(m.kind, ng);
      }
    }
    return out;
  }, [occs, candles, w]);

  // ---- outline of the selected occurrence ------------------------------------------------------
  const sel = useMemo(() => occs.find((o) => o.occ_id === selectedId) ?? null, [occs, selectedId]);
  const outline = (() => {
    if (!sel) return null;
    const at = (ts: number) => {
      const i = idxAtOrAfter(candles, ts);
      return i < 0 ? candles.length - 1 : i;
    };
    const clipped = sel.start_ts < candles[0].time;
    const i0 = clipped ? 0 : at(sel.start_ts);
    const i1 = at(Math.max(sel.end_ts, sel.start_ts));
    const prices = [...sel.pivots.map((p) => p.price), ...sel.lines.flatMap((l) => [l.y0, l.y1])];
    const lo = prices.length ? Math.min(...prices) : min;
    const hi = prices.length ? Math.max(...prices) : max;
    const color = STATUS_COLOR[sel.status];
    return {
      clipped, i0, i1, color,
      y0: yc(Math.min(hi, max)),
      y1: yc(Math.max(lo, min)),
      pivots: sel.pivots.filter((p) => p.ts >= candles[0].time).map((p) => ({ ...p, i: at(p.ts) })),
      lines: sel.lines.map((l) => ({ ...l, i0: at(l.ts0), i1: at(l.ts1) })),
    };
  })();

  const onMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const frac = (e.clientX - rect.left - PAD_L) / (w - PAD_L);
    if (frac < 0 || frac > 1) return setHover(null);
    setHover(Math.round(frac * (closes.length - 1)));
  };
  const hc = hover != null ? candles[hover] : null;
  const hx = hover != null ? x(hover) : 0;
  const tip = (t: number) => {
    const d = new Date(t * 1000);
    return intraday
      ? d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false })
      : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  };

  const clear = () => {
    setGroup(null);
    onSelect(null);
  };

  return (
    <div ref={boxRef} className="relative w-full" style={{ height: H }} onMouseMove={onMove} onMouseLeave={() => setHover(null)} onClick={clear}>
      <svg width={w} height={H} className="block">
        <defs>
          <linearGradient id="areaFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#b7b4e7" stopOpacity="0.25" />
            <stop offset="100%" stopColor="#b7b4e7" stopOpacity="0" />
          </linearGradient>
        </defs>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD_L} x2={w} y1={y(t)} y2={y(t)} stroke="var(--grid)" />
            <text x={PAD_L - 8} y={y(t) + 4} textAnchor="end" fontSize="11" style={{ fill: "var(--text-tertiary)" }}>
              ₹{Math.round(t).toLocaleString("en-IN")}
            </text>
          </g>
        ))}
        <polygon points={area} fill="url(#areaFill)" />

        {outline && sel && (
          <g pointerEvents="none">
            <rect x={x(outline.i0)} y={outline.y0} width={Math.max(x(outline.i1) - x(outline.i0), 2)} height={Math.max(outline.y1 - outline.y0, 2)}
              fill={outline.color} fillOpacity="0.1" stroke={outline.color} strokeDasharray="5 4" strokeWidth="1.5" rx="3" />
            <text x={x(outline.i0) + 6} y={outline.y0 + 14} fontSize="11" fontWeight="600" fill={outline.color}>
              {displayName(catalogue, sel.pattern)} · started {fmtDate(sel.start_ts)}
              {outline.clipped ? " (before this view)" : ""}
            </text>
            {sel.breakout_level != null && (
              <>
                <line x1={x(outline.i0)} x2={w} y1={yc(sel.breakout_level)} y2={yc(sel.breakout_level)} stroke="#10b981" strokeDasharray="6 4" strokeWidth="1.2" />
                <text x={w - 6} y={yc(sel.breakout_level) - 4} textAnchor="end" fontSize="10" fill="#10b981">breakout ₹{fmt(sel.breakout_level)}</text>
              </>
            )}
            {sel.invalidation_level != null && (
              <>
                <line x1={x(outline.i0)} x2={w} y1={yc(sel.invalidation_level)} y2={yc(sel.invalidation_level)} stroke="#ef4444" strokeDasharray="6 4" strokeWidth="1.2" />
                <text x={w - 6} y={yc(sel.invalidation_level) + 12} textAnchor="end" fontSize="10" fill="#ef4444">invalidation ₹{fmt(sel.invalidation_level)}</text>
              </>
            )}
            {outline.lines.map((l, k) => (
              <line key={k} x1={x(l.i0)} y1={yc(l.y0)} x2={x(l.i1)} y2={yc(l.y1)} stroke={outline.color} strokeWidth="1.6" opacity="0.9" />
            ))}
          </g>
        )}

        <polyline points={line} fill="none" stroke="#b7b4e7" strokeWidth="2" strokeLinejoin="round" />

        {outline && (
          <g pointerEvents="none">
            {outline.pivots.map((p, k) => (
              <g key={k}>
                <circle cx={x(p.i)} cy={yc(p.price)} r="3.5" fill="var(--on-accent)" stroke={outline.color} strokeWidth="1.6" />
                {outline.pivots.length <= 8 && (
                  <text x={x(p.i)} y={yc(p.price) - 7} textAnchor="middle" fontSize="9" fill={outline.color}>{p.label}</text>
                )}
              </g>
            ))}
          </g>
        )}

        {labelIdx.map((li, k) => (
          <text key={k} x={x(li)} y={H - 8} textAnchor={k === 0 ? "start" : k === 4 ? "end" : "middle"} fontSize="11" style={{ fill: "var(--text-tertiary)" }}>
            {axisLabel(candles[li].time)}
          </text>
        ))}

        {groups.map((g) => {
          const cx = x(g.i);
          const cy = y(candles[g.i].close);
          const color = KIND_COLOR[g.kind];
          const above = g.kind === "negative" || g.kind === "forming" || g.kind === "awaiting" || g.kind === "invalidated";
          const tipY = above ? cy - 9 : cy + 9;
          const baseY = above ? tipY - 14 : tipY + 14;
          const midY = (tipY + baseY) / 2;
          let shape: React.ReactNode;
          if (g.kind === "forming") {
            shape = <circle cx={cx} cy={midY} r="5" fill="var(--on-accent)" stroke={color} strokeWidth="1.6" strokeDasharray="2.5 2" />;
          } else if (g.kind === "awaiting") {
            shape = <rect x={cx - 5} y={midY - 5} width="10" height="10" transform={`rotate(45 ${cx} ${midY})`} fill={`${color}33`} stroke={color} strokeWidth="1.6" />;
          } else if (g.kind === "invalidated") {
            shape = <path d={`M${cx - 4},${midY - 4} L${cx + 4},${midY + 4} M${cx + 4},${midY - 4} L${cx - 4},${midY + 4}`} stroke={color} strokeWidth="1.6" />;
          } else {
            const down = g.kind === "negative";
            shape = <polygon points={`${cx},${tipY} ${cx - 7},${baseY} ${cx + 7},${baseY}`} fill={color} stroke="var(--on-accent)" strokeWidth="1" opacity={down ? 1 : 1} />;
          }
          return (
            <g
              key={`${g.kind}-${g.i}`}
              style={{ cursor: "pointer" }}
              onClick={(e) => {
                e.stopPropagation();
                setGroup(g);
                onSelect(g.items[g.items.length - 1].occ_id);
              }}
            >
              <circle cx={cx} cy={midY} r="13" fill="transparent" />
              {shape}
              {g.items.length > 1 && (
                <text x={cx + 9} y={midY - 6} fontSize="10" fontWeight="700" fill={color} pointerEvents="none">{g.items.length}</text>
              )}
            </g>
          );
        })}

        {live && (
          <g>
            <circle cx={x(closes.length - 1)} cy={y(closes[closes.length - 1])} r="9" fill="#ef4444" opacity="0.25">
              <animate attributeName="r" values="5;12;5" dur="1.6s" repeatCount="indefinite" />
              <animate attributeName="opacity" values="0.5;0;0.5" dur="1.6s" repeatCount="indefinite" />
            </circle>
            <circle cx={x(closes.length - 1)} cy={y(closes[closes.length - 1])} r="4" fill="#ef4444" />
          </g>
        )}
        {hc && (
          <>
            <line x1={hx} x2={hx} y1={0} y2={H - PAD_B} style={{ stroke: "var(--crosshair)" }} />
            <circle cx={hx} cy={y(hc.close)} r="5" fill="#fff" stroke="#b7b4e7" strokeWidth="2" />
          </>
        )}
      </svg>

      {group && (
        <div
          className="absolute z-20 w-72 max-w-[92%] rounded-xl border p-3 text-left text-sm"
          style={{
            // open on the side away from the marker so the formation outline stays visible
            left: x(group.i) > w / 2 ? Math.max(x(group.i) - 300, PAD_L) : Math.min(x(group.i) + 16, Math.max(w - 296, PAD_L)),
            top: 6,
            maxHeight: H - 12,
            overflowY: "auto",
            background: "var(--surface-1)",
            borderColor: KIND_COLOR[group.kind],
            boxShadow: "var(--shadow-md)",
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="mb-2 flex items-start justify-between">
            <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>
              {group.items.length} pattern{group.items.length > 1 ? "s" : ""} · {fmtDate(markerOf(group.items[0]).ts)}
            </div>
            <button onClick={clear} aria-label="Close" className="px-1 text-lg leading-none" style={{ color: "var(--text-tertiary)" }}>×</button>
          </div>
          <ul className="space-y-1">
            {group.items.map((o) => (
              <li key={o.occ_id}>
                <button
                  onClick={() => onSelect(o.occ_id)}
                  className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1 text-left text-xs"
                  style={{ background: selectedId === o.occ_id ? "var(--overlay-strong)" : "transparent", outline: selectedId === o.occ_id ? `1px solid ${STATUS_COLOR[o.status]}` : "none" }}
                >
                  <span className="font-medium">{displayName(catalogue, o.pattern)}{o.direction ? ` · ${o.direction}` : ""}</span>
                  <span style={{ color: STATUS_COLOR[o.status] }}>{STATUS_LABEL[o.status]}</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[10px]" style={{ color: "var(--text-tertiary)" }}>Full details are shown below the chart.</p>
        </div>
      )}

      {hc && !group && (
        <div
          className="pointer-events-none absolute top-6 z-10 rounded-lg border px-3 py-2 text-sm"
          style={{ left: hx > w - 190 ? hx - 170 : hx + 14, background: "var(--surface-1)", borderColor: "var(--border-default)", boxShadow: "var(--shadow-md)" }}
        >
          <div className="font-medium">{tip(hc.time)}</div>
          <div style={{ color: "var(--accent)" }}>Price : ₹{fmt(hc.close)}</div>
        </div>
      )}
    </div>
  );
}

/** Details for one occurrence: rule, levels, what the agent knew when, and realised outcomes. */
export function Detail({ o, catalogue }: { o: PatternOcc; catalogue: Record<string, CatalogueEntry> }) {
  const def = catalogue[o.pattern];
  return (
    <div className="mt-3 space-y-2 border-t pt-3 text-xs" style={{ borderColor: "var(--border-subtle)" }}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full px-2 py-0.5 font-semibold" style={{ background: `${STATUS_COLOR[o.status]}22`, color: STATUS_COLOR[o.status] }}>
          {STATUS_LABEL[o.status]}
        </span>
        {o.direction && <span style={{ color: "var(--text-secondary)" }}>{o.direction}</span>}
        {o.maturity === "experimental" && (
          <span className="rounded-full border px-2 py-0.5" style={{ borderColor: "#f59e0b66", color: "#f59e0b" }} title="Low-reliability definition">experimental</span>
        )}
        {o.reason && <span style={{ color: "var(--text-tertiary)" }}>({o.reason.replace(/_/g, " ")})</span>}
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1" style={{ color: "var(--text-secondary)" }}>
        <span>Started</span><span className="nv-num text-right">{fmtDate(o.start_ts)}</span>
        <span>First seen</span><span className="nv-num text-right">{fmtDate(o.first_seen_ts)}</span>
        {o.confirmed_ts != null && (<><span>Confirmed</span><span className="nv-num text-right">{fmtDate(o.confirmed_ts)} @ ₹{fmt(o.confirmed_price)}</span></>)}
        {o.breakout_level != null && (<><span>Breakout level</span><span className="nv-num text-right">₹{fmt(o.breakout_level)}</span></>)}
        {o.invalidation_level != null && (<><span>Invalidation</span><span className="nv-num text-right">₹{fmt(o.invalidation_level)}</span></>)}
      </div>
      <div>
        <div className="mb-1 font-semibold" style={{ color: "var(--text-secondary)" }}>Status history</div>
        <ol className="space-y-0.5">
          {o.history.map((h, k) => (
            <li key={k} className="flex justify-between gap-2">
              <span style={{ color: STATUS_COLOR[h.status] }}>{STATUS_LABEL[h.status]}</span>
              <span className="nv-num" style={{ color: "var(--text-tertiary)" }}>{fmtDate(h.ts)}{h.price != null ? ` · ₹${fmt(h.price)}` : ""}</span>
            </li>
          ))}
        </ol>
      </div>
      {o.outcomes && (
        <div>
          <div className="mb-1 font-semibold" style={{ color: "var(--text-secondary)" }}>Realised move after confirmation</div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(o.outcomes).map(([h, x]) => (
              <span key={h} className="nv-num rounded px-1.5 py-0.5" style={{ border: `1px solid ${OUTCOME_COLOR[x.state]}66`, color: OUTCOME_COLOR[x.state] }}
                title={`${OUTCOME_LABEL[x.state]} after ${h} bars`}>
                {h}b: {x.ret == null ? OUTCOME_LABEL[x.state] : `${x.ret >= 0 ? "+" : ""}${(x.ret * 100).toFixed(2)}%`}
              </span>
            ))}
          </div>
        </div>
      )}
      {def && <p className="leading-snug" style={{ color: "var(--text-tertiary)" }}>{def.definition}</p>}
      <p className="leading-snug" style={{ color: "var(--text-tertiary)" }}>
        Status describes how the pattern is forming, not whether a trade will make money. Marker colour on confirmed patterns is what price actually did next.
      </p>
    </div>
  );
}
