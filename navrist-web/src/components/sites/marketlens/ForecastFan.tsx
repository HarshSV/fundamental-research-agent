"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Forecast } from "./forecast";

const PAD_L = 40;
const INTRO = 450;       // ms: the orb at the origin
const SWEEP = 1700;      // ms: the scan line crosses and the lines draw in behind it
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const inr = (v: number) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const pct = (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
const day = (iso: string) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}`;
const reducedMotion = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

interface Band { k: number; p10: number; med: number; p90: number; low: number; mid: number; high: number }

/**
 * The forecast as a small "flow" chart: every line is something that really happened, the next 20 sessions after one of this stock's own past
 * days that looked like today. All start at zero on the left and fan out to the right; the range the forecast gives (where the middle 80 % of
 * those outcomes ended) is marked over the fan at 5 and at 20 sessions, its prices written in the margin so no text sits on the lines.
 * It fills the box it is given, and draws in again each time `play` changes (when its panel slides into view).
 */
export function ForecastFan({ data, play }: { data: Forecast; play: number }) {
  const fan = data.fan;
  const wrap = useRef<HTMLDivElement>(null);
  const cv = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [tip, setTip] = useState<{ x: number; y: number; i: number } | null>(null);
  const live = useRef({ t0: 0, done: false, hover: -1 });

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const measure = () => setSize({ w: Math.round(el.clientWidth), h: Math.round(el.clientHeight) });
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    measure();
    return () => ro.disconnect();
  }, [fan]);

  const bands = useMemo<Band[]>(() => {
    const out: Band[] = [];
    for (const h of data.outlook) {
      const k = h.id === "week" ? 5 : h.id === "month" ? 20 : 0;
      if (k && h.p10 != null && h.median != null && h.p90 != null && h.price_low != null && h.price_mid != null && h.price_high != null) {
        out.push({ k, p10: h.p10, med: h.median, p90: h.p90, low: h.price_low, mid: h.price_mid, high: h.price_high });
      }
    }
    return out.sort((a, b) => a.k - b.k);
  }, [data]);

  const width = size.w;
  const H = Math.max(140, size.h);
  const wide = width >= 520;
  const padR = wide ? 150 : 10;
  const plotW = Math.max(10, width - PAD_L - padR);
  const mid = H / 2;
  const steps = fan ? fan.h : 20;
  // vertical scale: the widest forecast range with room round it; stranger past outcomes run off the frame rather than shrink everything
  const span = useMemo(() => Math.max(5, ...bands.flatMap((b) => [Math.abs(b.p10), Math.abs(b.p90)])) * 1.45, [bands]);
  const X = (k: number) => PAD_L + (k / steps) * plotW;
  const Y = (v: number) => mid - (Math.max(-span * 3, Math.min(span * 3, v)) / span) * (mid - 14);

  useEffect(() => {
    const c = cv.current;
    if (!c || !width || !fan) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    c.width = width * dpr;
    c.height = H * dpr;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const gain = "#10b981";
    const loss = "#ef4444";
    const axis = "#8a93a6";
    const s = live.current;
    s.t0 = performance.now();
    s.done = reducedMotion();
    s.hover = -1;
    const clamp = (v: number) => Math.max(0, Math.min(1, v));
    const inOut = (t: number) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);
    let raf = 0;

    const draw = (now: number) => {
      const el = s.done ? INTRO + SWEEP + 400 : now - s.t0;
      const orb = clamp(el / 350);
      const p = clamp((el - INTRO) / SWEEP);
      const xk = inOut(p);
      const settled = clamp((el - INTRO - SWEEP) / 400);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, H);
      const gu = ctx.createLinearGradient(0, 0, 0, mid);
      gu.addColorStop(0, gain + "1a");
      gu.addColorStop(1, gain + "00");
      ctx.fillStyle = gu;
      ctx.fillRect(PAD_L, 0, plotW, mid);
      const gd = ctx.createLinearGradient(0, mid, 0, H);
      gd.addColorStop(0, loss + "00");
      gd.addColorStop(1, loss + "1a");
      ctx.fillStyle = gd;
      ctx.fillRect(PAD_L, mid, plotW, mid);
      ctx.font = "500 10px system-ui, sans-serif";
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      const step = span > 40 ? 20 : span > 16 ? 10 : 5;
      for (let g = step; g < span * 1.2; g += step) {
        for (const sg of [1, -1]) {
          const y = Y(g * sg);
          if (y < 6 || y > H - 6) continue;
          ctx.strokeStyle = axis + "26";
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(PAD_L, y);
          ctx.lineTo(PAD_L + plotW, y);
          ctx.stroke();
          ctx.fillStyle = axis;
          ctx.fillText(`${sg > 0 ? "+" : "-"}${g}%`, PAD_L - 5, y);
        }
      }
      ctx.save();
      ctx.beginPath();
      ctx.rect(PAD_L, 1, plotW + 1, H - 2);
      ctx.clip();
      const trace = (path: number[], tt: number) => {
        const n = Math.min(steps, Math.floor(tt));
        const pts: [number, number][] = [];
        for (let i = 0; i <= n; i++) pts.push([X(i), Y(path[i])]);
        if (n < steps && tt > n) pts.push([X(tt), Y(path[n] + (path[n + 1] - path[n]) * (tt - n))]);
        ctx.moveTo(pts[0][0], pts[0][1]);
        for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
      };
      const hv = s.hover;
      const tt = steps * xk;
      ctx.globalCompositeOperation = "lighter";
      for (const up of [true, false]) {
        ctx.beginPath();
        fan.paths.forEach((path, i) => {
          if (i !== hv && (path[steps] > 0) === up && tt > 0.01) trace(path, tt);
        });
        ctx.strokeStyle = (up ? gain : loss) + (hv >= 0 ? "14" : "38");
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      ctx.globalCompositeOperation = "source-over";
      if (hv >= 0) {
        ctx.beginPath();
        trace(fan.paths[hv], steps);
        ctx.strokeStyle = fan.paths[hv][steps] >= 0 ? gain : loss;
        ctx.lineWidth = 2.4;
        ctx.stroke();
      }
      ctx.restore();
      ctx.strokeStyle = "rgba(255,255,255,0.75)";
      ctx.lineWidth = 1.3;
      ctx.beginPath();
      ctx.moveTo(PAD_L, mid);
      ctx.lineTo(PAD_L + plotW * clamp(xk + 0.02), mid);
      ctx.stroke();
      if (p > 0 && p < 1) {
        const hx = X(tt);
        const fade = 1 - clamp((p - 0.9) / 0.1);
        const sg = ctx.createLinearGradient(hx - 34, 0, hx, 0);
        sg.addColorStop(0, "rgba(255,255,255,0)");
        sg.addColorStop(1, `rgba(255,255,255,${0.1 * fade})`);
        ctx.fillStyle = sg;
        ctx.fillRect(hx - 34, 0, 34, H);
      }
      const og = ctx.createRadialGradient(PAD_L, mid, 0, PAD_L, mid, 20);
      og.addColorStop(0, `rgba(255,255,255,${0.8 * orb})`);
      og.addColorStop(1, "rgba(255,255,255,0)");
      ctx.fillStyle = og;
      ctx.fillRect(PAD_L - 24, mid - 24, 48, 48);
      ctx.fillStyle = `rgba(255,255,255,${orb})`;
      ctx.beginPath();
      ctx.arc(PAD_L, mid, 3, 0, Math.PI * 2);
      ctx.fill();

      // the forecast range over the fan: a bar from the low to the high end at 5 and at 20 sessions with a tick at the middle; the prices go in the
      // margin at the right, nudged apart so they never overlap each other or sit on the lines
      if (settled > 0 && bands.length) {
        ctx.globalAlpha = settled;
        const taken: number[] = [];
        for (const b of bands) {
          const x = X(b.k);
          const yh = Y(b.p90);
          const yl = Y(b.p10);
          const ym = Y(b.med);
          const tone = b.med > 0.3 ? gain : b.med < -0.3 ? loss : "#94a3b8";
          ctx.fillStyle = tone + "33";
          ctx.fillRect(x - 6, yh, 12, yl - yh);
          ctx.strokeStyle = tone;
          ctx.lineWidth = 1.5;
          ctx.strokeRect(x - 6, yh, 12, yl - yh);
          ctx.beginPath();
          ctx.moveTo(x - 9, ym);
          ctx.lineTo(x + 9, ym);
          ctx.stroke();
          ctx.setLineDash([3, 4]);
          ctx.strokeStyle = tone + "88";
          ctx.lineWidth = 1;
          for (const yy of [yh, yl]) {
            ctx.beginPath();
            ctx.moveTo(PAD_L, yy);
            ctx.lineTo(x - 6, yy);
            ctx.stroke();
          }
          ctx.setLineDash([]);
          if (wide) {
            let y = ym;
            for (const t of taken) if (Math.abs(y - t) < 48) y = t + 50;
            y = Math.min(y, H - 30);
            taken.push(y);
            ctx.textAlign = "left";
            ctx.textBaseline = "middle";
            ctx.fillStyle = "#e6e8ee";
            ctx.font = "600 11px system-ui, sans-serif";
            ctx.fillText(`${b.k} sessions`, PAD_L + plotW + 12, y - 12);
            ctx.font = "500 11px system-ui, sans-serif";
            ctx.fillStyle = tone;
            ctx.fillText(`${inr(b.low)} to ${inr(b.high)}`, PAD_L + plotW + 12, y + 2);
            ctx.fillStyle = axis;
            ctx.font = "500 10px system-ui, sans-serif";
            ctx.fillText(`middle ${inr(b.mid)}`, PAD_L + plotW + 12, y + 15);
            ctx.strokeStyle = tone + "88";
            ctx.beginPath();
            ctx.moveTo(x + 6, ym);
            ctx.lineTo(PAD_L + plotW + 8, y);
            ctx.stroke();
          }
        }
        ctx.globalAlpha = 1;
      }
      ctx.fillStyle = axis;
      ctx.textBaseline = "alphabetic";
      ctx.textAlign = "left";
      ctx.font = "500 10px system-ui, sans-serif";
      ctx.fillText("today", PAD_L + 4, H - 4);
      ctx.textAlign = "right";
      ctx.fillText(`+${steps} sessions`, PAD_L + plotW - 2, H - 4);
      if (el < INTRO + SWEEP + 400) raf = requestAnimationFrame(draw);
      else s.done = true;
    };
    raf = requestAnimationFrame(draw);
    (c as HTMLCanvasElement & { redraw?: () => void }).redraw = () => {
      if (s.done) draw(performance.now());
    };
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fan, bands, width, H, span, plotW, play]);

  if (!fan || fan.paths.length < 20) return null;
  const redraw = () => (cv.current as (HTMLCanvasElement & { redraw?: () => void }) | null)?.redraw?.();
  const onMove = (e: React.PointerEvent) => {
    const c = cv.current;
    const s = live.current;
    if (!c || !s.done) return;
    const r = c.getBoundingClientRect();
    const px = e.clientX - r.left;
    const py = e.clientY - r.top;
    const idx = Math.round(((px - PAD_L) / plotW) * steps);
    let best = -1;
    if (idx >= 1 && idx <= steps) {
      let bd = 10;
      fan.paths.forEach((path, i) => {
        const d = Math.abs(Y(path[idx]) - py);
        if (d < bd) { bd = d; best = i; }
      });
    }
    if (best !== s.hover) {
      s.hover = best;
      redraw();
    }
    setTip(best >= 0 ? { x: px, y: py, i: best } : null);
  };
  const onLeave = () => {
    live.current.hover = -1;
    setTip(null);
    redraw();
  };
  const tipPath = tip ? fan.paths[tip.i] : null;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 text-xs" style={{ color: "var(--text-secondary)" }}>
        <span className="font-semibold uppercase tracking-wide">How {fan.paths.length} similar past days played out</span>
        <span style={{ color: "var(--text-tertiary)" }}>the next {fan.h} sessions after each · hover a line</span>
      </div>
      <div ref={wrap} className="relative min-h-[160px] w-full flex-1 select-none overflow-hidden rounded-lg" style={{ background: "#0b0d12" }} onPointerMove={onMove} onPointerLeave={onLeave}
        role="img" aria-label="The next 20 sessions after each of this stock's similar past days, with the forecast range marked at 5 and 20 sessions">
        <canvas ref={cv} style={{ width: "100%", height: "100%", display: "block", position: "absolute", inset: 0 }} />
        {tip && tipPath && (
          <div className="pointer-events-none absolute z-10 w-[170px] rounded-lg border px-2.5 py-1.5 text-xs shadow-lg"
            style={{ left: Math.max(4, Math.min(width - 176, tip.x + 12)), top: Math.max(4, tip.y - 52), background: "var(--surface-1)", borderColor: "var(--border-default)" }}>
            <div className="font-semibold">From {day(fan.dates[tip.i])}</div>
            <div style={{ color: tipPath[fan.h] >= 0 ? "var(--gain)" : "var(--loss)" }}>{pct(tipPath[fan.h])} after {fan.h} sessions</div>
          </div>
        )}
      </div>
      {!wide && (
        <div className="mt-2 space-y-0.5 text-xs" style={{ color: "var(--text-secondary)" }}>
          {bands.map((b) => <div key={b.k}><b style={{ color: "var(--text-primary)" }}>{b.k} sessions</b> · {inr(b.low)} to {inr(b.high)} · middle {inr(b.mid)}</div>)}
        </div>
      )}
      <p className="mt-2 text-[11px]" style={{ color: "var(--text-tertiary)" }}>
        {fan.basis === "state" ? "Days when the stock was in the same trend state as today." : "All of the stock's past days (too few were in today's exact state)."} The marked range is where the middle 80 % of them ended.
      </p>
    </div>
  );
}
