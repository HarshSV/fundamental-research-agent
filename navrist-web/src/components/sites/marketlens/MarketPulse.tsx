"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { fetchJson } from "@/lib/api";
import { navigateTo } from "./scanners";

/** [symbol, name, sector, change today %] */
type PulseRow = [string, string, string, number];
interface PulseRes { as_of?: string; stocks: number; rows: PulseRow[] }

const RANGE = 8;          // the strip spans -8% .. +8%; a bigger move is pinned to the edge
const R = 1.7;            // dot radius
const STEP = 3.9;         // horizontal width of one column of dots
const SWEEP_MS = 1900;
const css = (name: string, fallback: string) =>
  (typeof document !== "undefined" && getComputedStyle(document.documentElement).getPropertyValue(name).trim()) || fallback;
const pct = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
const reducedMotion = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

interface Dot { x: number; y: number; row: PulseRow; delay: number }

/**
 * Every stock's move today as a dot strip: losers on the left in red, gainers on the right in green, stacked like a histogram, with the zero
 * line in the middle. The strip sweeps in from the left (a bright edge leads, each dot pops as it passes, outliers leave a faint trail),
 * and once it has drawn it is fully hoverable: the dot under the pointer shows its company, and a sector picked below lights up its own dots.
 */
function Strip({ rows, focus }: { rows: PulseRow[]; focus: string | null }) {
  const wrap = useRef<HTMLDivElement>(null);
  const cv = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(0);
  const [tip, setTip] = useState<{ x: number; y: number; row: PulseRow } | null>(null);
  const state = useRef({ t0: 0, done: false, hover: -1, focus: null as string | null });
  const H = 190;

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(Math.round(el.clientWidth)));
    ro.observe(el);
    setWidth(Math.round(el.clientWidth));
    return () => ro.disconnect();
  }, []);

  const mid = Math.round(H * 0.5);
  const dots = useMemo<Dot[]>(() => {
    if (!width) return [];
    const pad = 18;
    const usable = width - pad * 2;
    const xOf = (c: number) => pad + ((Math.max(-RANGE, Math.min(RANGE, c)) + RANGE) / (2 * RANGE)) * usable;
    const sorted = [...rows].sort((a, b) => a[3] - b[3]);
    const stack = new Map<number, number>();
    const cap = Math.floor((H / 2 - 22) / (R * 2 + 0.5));
    const out: Dot[] = [];
    for (const row of sorted) {
      const x = xOf(row[3]);
      const bin = Math.round(x / STEP);
      const n = stack.get(bin) ?? 0;
      stack.set(bin, n + 1);
      // a column that would grow past the strip spreads sideways instead, left and right of its own position
      const col = Math.floor(n / cap);
      const lift = 7 + (n % cap) * (R * 2 + 0.5);
      const side = col === 0 ? 0 : (col % 2 ? -1 : 1) * Math.ceil(col / 2);
      const up = row[3] > 0 || (row[3] === 0 && n % 2 === 0);      // unchanged stocks sit on both sides of the line, in grey
      const y = up ? mid - lift : mid + lift;
      out.push({ x: bin * STEP + side * STEP, y, row, delay: x / width });
    }
    return out;
  }, [rows, width, mid]);

  useEffect(() => {
    state.current.focus = focus;
  }, [focus]);

  useEffect(() => {
    const c = cv.current;
    if (!c || !width || !dots.length) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    c.width = width * dpr;
    c.height = H * dpr;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const gain = css("--gain", "#10b981");
    const loss = css("--loss", "#ef4444");
    const axis = css("--text-tertiary", "#8b8b9a");
    const s = state.current;
    s.t0 = performance.now();
    s.done = reducedMotion();
    let raf = 0;
    const ease = (t: number) => 1 - Math.pow(1 - t, 3);

    const frame = (now: number) => {
      const t = s.done ? 1 : Math.min(1, (now - s.t0) / SWEEP_MS);
      const front = ease(t);                     // 0..1 of the width swept so far
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, H);
      // soft tint behind each side, fading in with the sweep
      const g1 = ctx.createLinearGradient(0, 0, width / 2, 0);
      g1.addColorStop(0, loss + "22");
      g1.addColorStop(1, loss + "00");
      const g2 = ctx.createLinearGradient(width / 2, 0, width, 0);
      g2.addColorStop(0, gain + "00");
      g2.addColorStop(1, gain + "22");
      ctx.globalAlpha = Math.min(1, front * 1.4);
      ctx.fillStyle = g1;
      ctx.fillRect(0, 0, width / 2, H);
      ctx.fillStyle = g2;
      ctx.fillRect(width / 2, 0, width / 2, H);
      ctx.globalAlpha = 1;
      // axis and zero line
      ctx.strokeStyle = axis + "55";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, mid + 0.5);
      ctx.lineTo(width * Math.min(1, front + 0.02), mid + 0.5);
      ctx.stroke();
      ctx.setLineDash([2, 4]);
      ctx.beginPath();
      ctx.moveTo(width / 2, 10);
      ctx.lineTo(width / 2, H - 10);
      ctx.stroke();
      ctx.setLineDash([]);

      const hv = s.hover;
      const fo = s.focus;
      for (let i = 0; i < dots.length; i++) {
        const d = dots[i];
        const age = (front - d.delay) * 9;           // 0..1 while the dot pops as the bright edge passes it
        if (age <= 0) continue;
        const k = Math.min(1, age);
        const pop = k < 1 ? 1 + Math.sin(k * Math.PI) * 0.7 : 1;
        const up = d.row[3] > 0;
        const flat = d.row[3] === 0;
        const col = flat ? axis : up ? gain : loss;
        const dim = fo != null && d.row[2] !== fo;
        const on = i === hv;
        ctx.globalAlpha = (dim ? 0.16 : 0.5 + 0.5 * k) * (on ? 1 : 1);
        ctx.fillStyle = col;
        // a faint trail behind the big movers, drawn only while sweeping and when hovered afterwards
        if (Math.abs(d.row[3]) > 3.2 && !dim) {
          const len = Math.min(d.x - 4, 46) * (s.done ? 0.7 : Math.min(1, age));
          const gr = ctx.createLinearGradient(d.x - len, 0, d.x, 0);
          gr.addColorStop(0, col + "00");
          gr.addColorStop(1, col + "66");
          ctx.strokeStyle = gr;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(d.x - len, d.y);
          ctx.lineTo(d.x, d.y);
          ctx.stroke();
        }
        ctx.beginPath();
        ctx.arc(d.x, d.y, (on ? R + 2.4 : R) * pop, 0, Math.PI * 2);
        ctx.fill();
        if (on) {
          ctx.globalAlpha = 0.9;
          ctx.strokeStyle = col;
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.arc(d.x, d.y, R + 6, 0, Math.PI * 2);
          ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;
      // the bright leading edge
      if (t < 1) {
        const x = front * width;
        const lg = ctx.createLinearGradient(x - 26, 0, x, 0);
        lg.addColorStop(0, "rgba(255,255,255,0)");
        lg.addColorStop(1, "rgba(255,255,255,0.22)");
        ctx.fillStyle = lg;
        ctx.fillRect(x - 26, 0, 26, H);
        ctx.fillStyle = "rgba(255,255,255,0.9)";
        ctx.beginPath();
        ctx.arc(x, mid, 3.4, 0, Math.PI * 2);
        ctx.fill();
      } else if (!s.done) {
        s.done = true;
      }
      // axis labels
      ctx.fillStyle = axis;
      ctx.font = "500 11px system-ui, sans-serif";
      ctx.textBaseline = "top";
      ctx.globalAlpha = Math.min(1, front * 1.2);
      ctx.textAlign = "left";
      ctx.fillText(`-${RANGE}% or worse`, 6, H - 16);
      ctx.textAlign = "center";
      ctx.fillText("0%", width / 2, H - 16);
      ctx.textAlign = "right";
      ctx.fillText(`+${RANGE}% or better`, width - 6, H - 16);
      ctx.globalAlpha = 1;
      // keep drawing while sweeping, and as long as something is hovered or focused afterwards
      if (!s.done || t < 1) raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    // redraw on hover / focus changes once the sweep has ended
    const poke = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame((n) => {
        frame(n);
        if (s.done) cancelAnimationFrame(raf);
      });
    };
    (c as HTMLCanvasElement & { poke?: () => void }).poke = poke;
    return () => cancelAnimationFrame(raf);
  }, [dots, width, mid]);

  // redraw after a hover or focus change
  const poke = () => (cv.current as (HTMLCanvasElement & { poke?: () => void }) | null)?.poke?.();
  useEffect(() => { poke(); }, [focus]);

  const onMove = (e: React.PointerEvent) => {
    const c = cv.current;
    if (!c || !state.current.done) return;
    const r = c.getBoundingClientRect();
    const px = e.clientX - r.left;
    const py = e.clientY - r.top;
    let best = -1;
    let bd = 12 * 12;
    for (let i = 0; i < dots.length; i++) {
      const dx = dots[i].x - px;
      if (dx > 12 || dx < -12) continue;
      const dd = dx * dx + (dots[i].y - py) ** 2;
      if (dd < bd) { bd = dd; best = i; }
    }
    if (best !== state.current.hover) {
      state.current.hover = best;
      poke();
    }
    setTip(best >= 0 ? { x: dots[best].x, y: dots[best].y, row: dots[best].row } : null);
  };
  const onLeave = () => {
    state.current.hover = -1;
    setTip(null);
    poke();
  };

  return (
    <div ref={wrap} className="relative w-full select-none" style={{ height: H }} onPointerMove={onMove} onPointerLeave={onLeave}
      onClick={() => tip && navigateTo({ type: "sector", name: tip.row[2] })} role="img" aria-label="Every stock's move today, losers on the left and gainers on the right">
      <canvas ref={cv} style={{ width: "100%", height: H, display: "block", cursor: tip ? "pointer" : "default" }} />
      {tip && (
        <div className="pointer-events-none absolute z-10 rounded-lg border px-2.5 py-1.5 text-xs shadow-lg"
          style={{ left: Math.max(4, Math.min(width - 190, tip.x - 90)), top: tip.y < H / 2 ? tip.y + 14 : tip.y - 62, width: 180, background: "var(--surface-1)", borderColor: "var(--border-default)" }}>
          <div className="truncate font-semibold">{tip.row[1] || tip.row[0]}</div>
          <div className="truncate" style={{ color: "var(--text-tertiary)" }}>{tip.row[0]} · {tip.row[2]}</div>
          <div className="font-semibold" style={{ color: tip.row[3] > 0 ? "var(--gain)" : tip.row[3] < 0 ? "var(--loss)" : "var(--text-tertiary)" }}>{tip.row[3] === 0 ? "Unchanged" : pct(tip.row[3])} today</div>
        </div>
      )}
    </div>
  );
}

/** the sector tiles: name, average move today and one small segment per stock, in the order of the move */
function Tiles({ rows, focus, setFocus }: { rows: PulseRow[]; focus: string | null; setFocus: (s: string | null) => void }) {
  const sectors = useMemo(() => {
    const by = new Map<string, number[]>();
    for (const r of rows) by.set(r[2], [...(by.get(r[2]) ?? []), r[3]]);
    return [...by.entries()]
      .map(([name, v]) => ({ name, v: v.sort((a, b) => a - b), avg: v.reduce((a, b) => a + b, 0) / v.length }))
      .sort((a, b) => b.avg - a.avg);
  }, [rows]);
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
      {sectors.map((s, i) => (
        <button key={s.name} type="button" onMouseEnter={() => setFocus(s.name)} onMouseLeave={() => setFocus(null)} onFocus={() => setFocus(s.name)} onBlur={() => setFocus(null)}
          onClick={() => navigateTo({ type: "sector", name: s.name })}
          className="pulse-tile rounded-lg border px-3 py-2 text-left transition-colors hover:bg-[var(--overlay-weak)]"
          style={{ borderColor: focus === s.name ? "var(--border-strong)" : "var(--border-subtle)", backgroundColor: "var(--surface-1)", animationDelay: `${1500 + i * 40}ms` }}>
          <div className="flex items-baseline justify-between gap-2">
            <span className="truncate text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-secondary)" }}>{s.name}</span>
            <span className="text-xs font-semibold tabular-nums" style={{ color: s.avg >= 0 ? "var(--gain)" : "var(--loss)" }}>{pct(s.avg)}</span>
          </div>
          <div className="mt-2 flex h-1.5 gap-px overflow-hidden rounded-sm" aria-label={`${s.v.length} stocks`}>
            {segments(s.v).map((c, k) => <span key={k} className="h-full flex-1" style={{ background: c >= 0 ? "var(--gain)" : "var(--loss)", opacity: 0.85 }} />)}
          </div>
          <div className="mt-1 text-[10px]" style={{ color: "var(--text-tertiary)" }}>{s.v.length} stocks · {s.v.filter((c) => c > 0).length} up · {s.v.filter((c) => c < 0).length} down</div>
        </button>
      ))}
    </div>
  );
}

/** at most 36 segments per sector: a long sector is sampled evenly across its sorted moves */
function segments(v: number[]): number[] {
  if (v.length <= 36) return v;
  return Array.from({ length: 36 }, (_, i) => v[Math.floor((i * (v.length - 1)) / 35)]);
}

export function MarketPulse() {
  const [data, setData] = useState<PulseRes | null>(null);
  const [error, setError] = useState("");
  const [focus, setFocus] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    fetchJson<PulseRes>("/api/v1/market/pulse").then((d) => alive && setData(d)).catch((e: Error) => alive && setError(e.message));
    return () => { alive = false; };
  }, []);
  if (error) return null;                      // the table below still works without the strip
  if (!data || !data.rows.length) return <div className="mb-6 h-[190px]" aria-hidden />;
  const up = data.rows.filter((r) => r[3] > 0).length;
  const down = data.rows.filter((r) => r[3] < 0).length;
  return (
    <section className="mb-6 rounded-xl border p-4" style={{ borderColor: "var(--border-subtle)", backgroundColor: "var(--surface-1)" }}>
      <style>{`
        @keyframes pulseRise { 0% { opacity: 0; transform: translateY(14px); } 100% { opacity: 1; transform: none; } }
        .pulse-tile { opacity: 0; animation: pulseRise 520ms cubic-bezier(0.16, 1, 0.3, 1) forwards; }
        @media (prefers-reduced-motion: reduce) { .pulse-tile { opacity: 1; animation: none; } }
      `}</style>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
        <span className="font-semibold uppercase tracking-wide">Market today · {data.stocks} stocks{data.as_of ? ` · as of ${data.as_of}` : ""}</span>
        <span><span style={{ color: "var(--gain)" }}>▲ {up} up</span> · <span style={{ color: "var(--loss)" }}>▼ {down} down</span> · {data.rows.length - up - down} unchanged</span>
      </div>
      <Strip rows={data.rows} focus={focus} />
      <div className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-secondary)" }}>Sectors · hover to find their stocks above</div>
      <Tiles rows={data.rows} focus={focus} setFocus={setFocus} />
    </section>
  );
}
