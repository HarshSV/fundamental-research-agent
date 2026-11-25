import type { IChartApi, ISeriesApi, Logical, SeriesType } from "lightweight-charts";
import { FIB_LEVELS, distToRay, distToSegment, duration, fibPrices, inRect, measure, snapPrice, type Px } from "./drawGeometry";

/* Interactive drawing tools for the stock chart, ported from the HeatCharting project: trend line, ray, horizontal and vertical line, rectangle,
 * Fibonacci retracement, text note and a measure tool. Drawings are kept in time and price, so they follow zooming and panning; they can be
 * selected, dragged, recoloured and deleted, undone and redone, and snapped to candle highs and lows. */

export type Tool = "cursor" | "trend" | "ray" | "hline" | "vline" | "rect" | "fib" | "text" | "measure";
export type Kind = Exclude<Tool, "cursor" | "measure">;

export interface Pt {
  t: number; // chart seconds (the same clock as the chart's bars: IST wall time read as UTC)
  p: number; // price
}
export interface Drawing {
  id: string;
  kind: Kind;
  pts: Pt[];
  color: string;
  text?: string;
}

export const TOOLS: { id: Tool; label: string; hint: string; points: number }[] = [
  { id: "cursor", label: "Cursor", hint: "Select and move drawings", points: 0 },
  { id: "trend", label: "Trend line", hint: "Drag from one point to another", points: 2 },
  { id: "ray", label: "Ray", hint: "A line that goes on past the second point", points: 2 },
  { id: "hline", label: "Horizontal line", hint: "Click to place a price level", points: 1 },
  { id: "vline", label: "Vertical line", hint: "Click to mark a time", points: 1 },
  { id: "rect", label: "Rectangle", hint: "Drag a box over a zone", points: 2 },
  { id: "fib", label: "Fibonacci retracement", hint: "Drag from the start to the end of a move", points: 2 },
  { id: "text", label: "Text", hint: "Click to add a note", points: 1 },
  { id: "measure", label: "Measure", hint: "Drag to read the price, percentage and time of a move", points: 2 },
];

export const COLORS = ["#3b82f6", "#f59e0b", "#22c55e", "#ef4444", "#a855f7", "#64748b"];

/** Maps between times and positions on a chart whose x axis counts bars. Between bars it interpolates by the bar length; past either end it
 *  carries on at the bar length, so a drawing can sit in the future or before the first bar. */
export class TimeMap {
  barTimes: number[] = [];
  barSec = 86400;

  set(times: number[]) {
    this.barTimes = times;
    const d: number[] = [];
    for (let i = 1; i < times.length; i++) d.push(times[i] - times[i - 1]);
    d.sort((a, b) => a - b);
    this.barSec = d.length ? d[Math.floor(d.length / 2)] || 86400 : 86400;
  }

  logical(sec: number): number | null {
    const b = this.barTimes;
    if (!b.length) return null;
    const last = b.length - 1;
    if (sec >= b[last]) return last + (sec - b[last]) / this.barSec;
    if (sec < b[0]) return (sec - b[0]) / this.barSec;
    let lo = 0;
    let hi = last;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (b[mid] <= sec) lo = mid;
      else hi = mid - 1;
    }
    const span = b[Math.min(last, lo + 1)] - b[lo] || this.barSec;
    return lo + Math.min(1, (sec - b[lo]) / span);
  }

  timeAt(idx: number): number | null {
    const b = this.barTimes;
    if (!b.length) return null;
    const last = b.length - 1;
    if (idx <= 0) return b[0] + idx * this.barSec;
    if (idx >= last) return b[last] + (idx - last) * this.barSec;
    const i = Math.floor(idx);
    return b[i] + (idx - i) * (b[i + 1] - b[i]);
  }
}

export interface DrawHooks {
  /** the drawings changed and should be saved */
  changed(list: Drawing[]): void;
  /** the tool changed (a drawing was finished) */
  tool(t: Tool): void;
  /** ask the user for text; null cancels */
  askText(): string | null;
  /** open, high, low, close of the bar nearest to a chart time, for the magnet */
  ohlcAt(t: number): number[] | null;
}

const HIT = typeof window !== "undefined" && window.matchMedia?.("(pointer: coarse)").matches ? 14 : 7;

export class DrawLayer {
  tool: Tool = "cursor";
  magnet = false;
  hidden = false;
  selected: string | null = null;
  readonly tm = new TimeMap();
  private list: Drawing[] = [];
  private ctx: CanvasRenderingContext2D;
  private dirty = true;
  private sig = "";
  private draft: { kind: Kind | "measure"; pts: Pt[]; waiting: boolean } | null = null;
  private drag: { id: string; handle: number | null; start: Px; orig: Pt[] } | null = null;
  private undo: string[] = [];
  private redo: string[] = [];
  private measureShown: { a: Pt; b: Pt } | null = null;
  private series: ISeriesApi<SeriesType> | null = null;
  private color = COLORS[0];
  private draftStart: Px = { x: 0, y: 0 };
  private over = false;
  private raf = 0;
  private off: (() => void)[] = [];

  constructor(private canvas: HTMLCanvasElement, private host: HTMLElement, private chart: IChartApi, private hooks: DrawHooks) {
    this.ctx = canvas.getContext("2d")!;
    const on = (el: HTMLElement | Window | Document, type: string, fn: (e: never) => void, capture = false, passive = true) => {
      el.addEventListener(type, fn as EventListener, { capture, passive });
      this.off.push(() => el.removeEventListener(type, fn as EventListener, capture));
    };
    // a touch is turned into the same call a mouse press makes, so one set of rules serves both
    const tp = (e: TouchEvent) => {
      const t = e.touches[0] ?? e.changedTouches[0];
      return { clientX: t.clientX, clientY: t.clientY, button: 0, target: e.target, preventDefault: () => e.preventDefault(), stopPropagation: () => e.stopPropagation() } as unknown as MouseEvent;
    };
    // the time axis moves (pan, zoom, new bars): repaint inside the same frame, so the drawings never trail the candles
    const rangeCb = () => this.draw();
    chart.timeScale().subscribeVisibleLogicalRangeChange(rangeCb);
    this.off.push(() => {
      try {
        chart.timeScale().unsubscribeVisibleLogicalRangeChange(rangeCb);
      } catch {
        /* the chart is already gone */
      }
    });
    // everything else (dragging a drawing, the price axis being dragged or autoscaled) is caught once per animation frame, and only repainted when it changed
    const loop = () => {
      const s = this.series ? `${this.series.coordinateToPrice(0)}|${this.series.coordinateToPrice(this.h)}` : "";
      if (s !== this.sig) {
        this.sig = s;
        this.dirty = true;
      }
      if (this.dirty) this.draw();
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
    on(host, "mousemove", (e: MouseEvent) => this.onHover(e));
    on(host, "mouseenter", () => (this.over = true));
    on(host, "mouseleave", () => (this.over = false));
    on(host, "mousedown", (e: MouseEvent) => this.onHostDown(e), true); // capture: decide before the chart starts a pan
    on(canvas, "mousedown", (e: MouseEvent) => this.onDown(e));
    on(window, "mousemove", (e: MouseEvent) => this.onMove(e));
    on(window, "mouseup", () => this.onUp());
    on(document, "keydown", (e: KeyboardEvent) => this.onKey(e));
    // touch: a finger on a drawing picks it up (the chart does not pan), a finger on the chart with a tool chosen draws; otherwise the chart pans and pinches as usual
    on(host, "touchstart", (e: TouchEvent) => { if (e.touches.length === 1) this.onHostDown(tp(e)); }, true, false);
    on(canvas, "touchstart", (e: TouchEvent) => {
      if (e.touches.length !== 1) return;
      e.preventDefault();      // no scrolling and no echoed mouse press
      this.onDown(tp(e));
    }, false, false);
    on(window, "touchmove", (e: TouchEvent) => {
      if (!this.drag && !this.draft) return;
      e.preventDefault();
      this.onMove(tp(e));
    }, false, false);
    on(window, "touchend", () => this.onUp());
    on(window, "touchcancel", () => this.onUp());
  }

  destroy() {
    cancelAnimationFrame(this.raf);
    for (const f of this.off) f();
    this.off = [];
  }

  private get w() {
    return parseFloat(this.canvas.style.width) || 0;
  }
  private get h() {
    return parseFloat(this.canvas.style.height) || 0;
  }

  setSeries(s: ISeriesApi<SeriesType> | null) {
    this.series = s;
    this.invalidate();
  }
  invalidate() {
    this.dirty = true;
  }
  resize(w: number, h: number) {
    const r = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(w * r);
    this.canvas.height = Math.round(h * r);
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
    this.ctx.setTransform(r, 0, 0, r, 0, 0);
    this.invalidate();
  }

  // ------------------------------------------------------------------ state
  get drawings() {
    return this.list;
  }
  setDrawings(l: Drawing[]) {
    this.list = l;
    this.selected = null;
    this.undo = [];
    this.redo = [];
    this.invalidate();
  }
  setTool(t: Tool) {
    this.tool = t;
    this.draft = null;
    if (t !== "measure") this.measureShown = null;
    this.canvas.style.pointerEvents = t === "cursor" ? "none" : "auto";
    this.canvas.style.touchAction = t === "cursor" ? "auto" : "none";
    this.canvas.style.cursor = t === "cursor" ? "default" : "crosshair";
    if (t !== "cursor") this.selected = null;
    this.invalidate();
  }
  setHidden(h: boolean) {
    this.hidden = h;
    this.invalidate();
  }
  setColor(c: string) {
    this.color = c;
    const d = this.list.find((x) => x.id === this.selected);
    if (d) {
      this.commit();
      d.color = c;
      this.save();
    }
  }
  clear() {
    if (!this.list.length) return;
    this.commit();
    this.list = [];
    this.selected = null;
    this.save();
  }
  deleteSelected() {
    if (!this.selected) return;
    this.commit();
    this.list = this.list.filter((d) => d.id !== this.selected);
    this.selected = null;
    this.save();
  }
  private commit() {
    this.undo.push(JSON.stringify(this.list));
    if (this.undo.length > 60) this.undo.shift();
    this.redo = [];
  }
  private save() {
    this.hooks.changed(this.list);
    this.invalidate();
  }
  undoDrawing() {
    const prev = this.undo.pop();
    if (prev === undefined) return;
    this.redo.push(JSON.stringify(this.list));
    this.list = JSON.parse(prev) as Drawing[];
    this.selected = null;
    this.save();
  }
  redoDrawing() {
    const next = this.redo.pop();
    if (next === undefined) return;
    this.undo.push(JSON.stringify(this.list));
    this.list = JSON.parse(next) as Drawing[];
    this.selected = null;
    this.save();
  }

  // ------------------------------------------------------------------ coordinates
  private toPx(p: Pt): Px | null {
    const l = this.tm.logical(p.t);
    if (l == null || !this.series) return null;
    const x = this.chart.timeScale().logicalToCoordinate(l as Logical);
    const y = this.series.priceToCoordinate(p.p);
    return x == null || y == null ? null : { x: x as number, y: y as number };
  }
  private fromPx(x: number, y: number): Pt | null {
    if (!this.series) return null;
    const l = this.chart.timeScale().coordinateToLogical(x);
    const price = this.series.coordinateToPrice(y);
    if (l == null || price == null) return null;
    const t = this.tm.timeAt(l as number);
    return t == null ? null : { t, p: price as number };
  }
  private evPx(e: MouseEvent): Px {
    const r = this.canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }
  private point(e: MouseEvent): Pt | null {
    const px = this.evPx(e);
    const pt = this.fromPx(px.x, px.y);
    if (!pt || !this.magnet || !this.series) return pt;
    const o = this.hooks.ohlcAt(pt.t);
    const perPx = Math.abs((this.series.coordinateToPrice(px.y + 1) as number) - (pt.p as number));
    return o ? { t: pt.t, p: snapPrice(pt.p, o, 14 * (perPx || 0)) } : pt;
  }
  private right() {
    return this.w - (this.chart.priceScale("right").width() || 0);
  }

  // ------------------------------------------------------------------ hit testing
  private pxs(d: Drawing): Px[] {
    return d.pts.map((p) => this.toPx(p)).filter((p): p is Px => p != null);
  }
  private hit(d: Drawing, p: Px): number | null {
    const ps = this.pxs(d);
    if (!ps.length) return null;
    const rt = this.right();
    switch (d.kind) {
      case "hline":
        return Math.abs(p.y - ps[0].y) <= HIT ? 0 : null;
      case "vline":
        return Math.abs(p.x - ps[0].x) <= HIT ? 0 : null;
      case "text":
        return Math.abs(p.x - ps[0].x) < 80 && Math.abs(p.y - ps[0].y) < 12 ? 0 : null;
      case "trend":
        return ps.length === 2 && distToSegment(p, ps[0], ps[1]) <= HIT ? 0 : null;
      case "ray":
        return ps.length === 2 && distToRay(p, ps[0], ps[1]) <= HIT ? 0 : null;
      case "rect":
        return ps.length === 2 && inRect(p, ps[0], ps[1], HIT) ? 0 : null;
      case "fib": {
        if (ps.length < 2) return null;
        const x0 = Math.min(ps[0].x, ps[1].x);
        if (p.x < x0 - HIT || p.x > rt) return null;
        return d.pts.length === 2 && fibPrices(d.pts[0].p, d.pts[1].p).some((f) => {
          const y = this.series!.priceToCoordinate(f.price);
          return y != null && Math.abs(p.y - (y as number)) <= HIT;
        }) ? 0 : null;
      }
    }
  }
  private handleAt(d: Drawing, p: Px): number | null {
    const ps = this.pxs(d);
    for (let i = 0; i < ps.length; i++) if (Math.hypot(p.x - ps[i].x, p.y - ps[i].y) <= HIT + 2) return i;
    return null;
  }
  private pick(p: Px): Drawing | null {
    for (let i = this.list.length - 1; i >= 0; i--) if (this.hit(this.list[i], p) != null) return this.list[i];
    return null;
  }

  // ------------------------------------------------------------------ mouse and keys
  private onHover(e: MouseEvent) {
    if (this.hidden || this.tool !== "cursor" || this.drag) return;
    const r = this.canvas.getBoundingClientRect();
    const p = { x: e.clientX - r.left, y: e.clientY - r.top };
    const sel = this.list.find((d) => d.id === this.selected);
    const over = (sel && this.handleAt(sel, p) != null) || this.pick(p);
    this.canvas.style.pointerEvents = over ? "auto" : "none";
    this.canvas.style.cursor = over ? "move" : "default";
  }
  private onHostDown(e: MouseEvent) {
    if (e.target === this.canvas) return; // the drawing layer handles its own presses
    if (this.hidden || this.tool !== "cursor" || e.button !== 0) return;
    const px = this.evPx(e);
    const sel = this.list.find((d) => d.id === this.selected);
    const h = sel ? this.handleAt(sel, px) : null;
    const d = h != null && sel ? sel : this.pick(px);
    if (!d) {
      // a press on empty chart clears the selection and lets the chart pan as usual
      if (this.selected) {
        this.selected = null;
        this.invalidate();
      }
      return;
    }
    e.stopPropagation(); // the press is for the drawing, not for the chart
    e.preventDefault();
    this.canvas.style.touchAction = "none";
    this.grab(d, h != null && d === sel ? h : null, px);
  }
  private grab(d: Drawing, handle: number | null, px: Px) {
    this.selected = d.id;
    this.commit();
    this.drag = { id: d.id, handle, start: px, orig: d.pts.map((p) => ({ ...p })) };
    this.invalidate();
  }
  private onDown(e: MouseEvent) {
    if (e.button !== 0) return;
    const px = this.evPx(e);
    if (this.tool === "cursor") {
      const sel = this.list.find((d) => d.id === this.selected);
      const h = sel ? this.handleAt(sel, px) : null;
      const d = h != null && sel ? sel : this.pick(px);
      if (!d) return;
      this.grab(d, h != null && d === sel ? h : null, px);
      e.preventDefault();
      return;
    }
    const pt = this.point(e);
    if (!pt) return;
    const info = TOOLS.find((t) => t.id === this.tool)!;
    if (this.draft?.waiting) {
      this.draft.pts[1] = pt;
      this.finish();
      return;
    }
    if (info.points === 1) {
      let text: string | undefined;
      if (this.tool === "text") {
        const t = this.hooks.askText();
        if (!t) return;
        text = t;
      }
      this.commit();
      const d: Drawing = { id: `${Date.now()}${Math.round(Math.random() * 1e4)}`, kind: this.tool as Kind, pts: [pt], color: this.color, text };
      this.list.push(d);
      this.selected = d.id;
      this.setTool("cursor");
      this.hooks.tool("cursor");
      this.save();
      return;
    }
    this.draft = { kind: this.tool as Kind | "measure", pts: [pt, pt], waiting: false };
    this.draftStart = px;
    this.invalidate();
  }
  private onMove(e: MouseEvent) {
    if (this.drag) {
      const d = this.list.find((x) => x.id === this.drag!.id);
      if (!d) return;
      const px = this.evPx(e);
      if (this.drag.handle != null) {
        const pt = this.point(e);
        if (pt) d.pts[this.drag.handle] = pt;
      } else {
        const a = this.fromPx(this.drag.start.x, this.drag.start.y);
        const b = this.fromPx(px.x, px.y);
        if (a && b) d.pts = this.drag.orig.map((p) => ({ t: p.t + (b.t - a.t), p: p.p + (b.p - a.p) }));
      }
      this.draw();
      return;
    }
    if (this.draft) {
      const pt = this.point(e);
      if (pt) this.draft.pts[1] = pt;
      this.draw();
    }
  }
  private onUp() {
    this.canvas.style.touchAction = this.tool === "cursor" ? "auto" : "none";
    if (this.drag) {
      this.drag = null;
      this.save();
      return;
    }
    if (!this.draft || this.draft.waiting) return;
    const moved = this.toPx(this.draft.pts[1]);
    const far = moved ? Math.hypot(moved.x - this.draftStart.x, moved.y - this.draftStart.y) > 5 : false;
    if (far) this.finish();
    else this.draft.waiting = true; // a click without a drag: the next click sets the second point
  }
  private finish() {
    const dr = this.draft;
    if (!dr) return;
    this.draft = null;
    if (dr.kind === "measure") {
      this.measureShown = { a: dr.pts[0], b: dr.pts[1] };
      this.invalidate();
      return;
    }
    this.commit();
    const d: Drawing = { id: `${Date.now()}${Math.round(Math.random() * 1e4)}`, kind: dr.kind, pts: dr.pts, color: this.color };
    this.list.push(d);
    this.selected = d.id;
    this.setTool("cursor");
    this.hooks.tool("cursor");
    this.save();
  }
  private onKey(e: KeyboardEvent) {
    const tag = (e.target as HTMLElement)?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    if (e.key === "Escape") {
      if (!this.draft && !this.measureShown && !this.selected && this.tool === "cursor") return;
      this.draft = null;
      this.measureShown = null;
      this.selected = null;
      if (this.tool !== "cursor") {
        this.setTool("cursor");
        this.hooks.tool("cursor");
      }
      this.invalidate();
    } else if ((e.key === "Delete" || e.key === "Backspace") && this.selected) {
      e.preventDefault();
      this.deleteSelected();
    } else if ((e.ctrlKey || e.metaKey) && this.over && e.key.toLowerCase() === "z") {
      e.preventDefault();
      if (e.shiftKey) this.redoDrawing();
      else this.undoDrawing();
    } else if ((e.ctrlKey || e.metaKey) && this.over && e.key.toLowerCase() === "y") {
      e.preventDefault();
      this.redoDrawing();
    }
  }

  // ------------------------------------------------------------------ painting
  draw() {
    this.dirty = false;
    const { ctx } = this;
    ctx.clearRect(0, 0, this.w, this.h);
    if (this.hidden || !this.series) return;
    const paneH = this.chart.panes()[0]?.getHeight() ?? this.h;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, this.right(), paneH);
    ctx.clip();
    for (const d of this.list) this.paint(d, d.id === this.selected);
    if (this.draft && this.draft.kind !== "measure") this.paint({ id: "draft", kind: this.draft.kind, pts: this.draft.pts, color: this.color }, false, true);
    const m = this.draft?.kind === "measure" ? { a: this.draft.pts[0], b: this.draft.pts[1] } : this.measureShown;
    if (m) this.paintMeasure(m.a, m.b);
    ctx.restore();
  }

  private paint(d: Drawing, selected: boolean, ghost = false) {
    const { ctx } = this;
    const ps = this.pxs(d);
    if (!ps.length) return;
    const rt = this.right();
    ctx.save();
    ctx.globalAlpha = ghost ? 0.7 : 1;
    ctx.strokeStyle = d.color;
    ctx.fillStyle = d.color;
    ctx.lineWidth = selected ? 2.2 : 1.5;
    ctx.font = "11px system-ui, sans-serif";
    ctx.textBaseline = "middle";
    const line = (a: Px, b: Px) => {
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    };
    const label = (text: string, x: number, y: number) => {
      const w = ctx.measureText(text).width + 8;
      ctx.globalAlpha = 0.92;
      ctx.fillRect(x, y - 8, w, 16);
      ctx.fillStyle = "#ffffff";
      ctx.fillText(text, x + 4, y);
      ctx.fillStyle = d.color;
      ctx.globalAlpha = 1;
    };
    if (d.kind === "hline") {
      line({ x: 0, y: ps[0].y }, { x: rt, y: ps[0].y });
      label(d.pts[0].p.toFixed(2), rt - 62, ps[0].y);
    } else if (d.kind === "vline") {
      line({ x: ps[0].x, y: 0 }, { x: ps[0].x, y: this.h });
    } else if (d.kind === "text") {
      ctx.font = "600 13px system-ui, sans-serif";
      ctx.fillText(d.text ?? "", ps[0].x, ps[0].y);
    } else if (ps.length === 2) {
      if (d.kind === "trend") line(ps[0], ps[1]);
      else if (d.kind === "ray") {
        const dx = ps[1].x - ps[0].x;
        const dy = ps[1].y - ps[0].y;
        const k = dx === 0 ? 0 : (rt - ps[0].x) / dx;
        line(ps[0], dx === 0 ? { x: ps[0].x, y: dy >= 0 ? this.h : 0 } : { x: rt, y: ps[0].y + dy * k });
      } else if (d.kind === "rect") {
        ctx.globalAlpha = 0.14;
        ctx.fillRect(Math.min(ps[0].x, ps[1].x), Math.min(ps[0].y, ps[1].y), Math.abs(ps[1].x - ps[0].x), Math.abs(ps[1].y - ps[0].y));
        ctx.globalAlpha = 1;
        ctx.strokeRect(Math.min(ps[0].x, ps[1].x), Math.min(ps[0].y, ps[1].y), Math.abs(ps[1].x - ps[0].x), Math.abs(ps[1].y - ps[0].y));
      } else if (d.kind === "fib") {
        const x0 = Math.min(ps[0].x, ps[1].x);
        const fp = fibPrices(d.pts[0].p, d.pts[1].p);
        fp.forEach((f, i) => {
          const y = this.series!.priceToCoordinate(f.price);
          if (y == null) return;
          ctx.globalAlpha = 0.85;
          line({ x: x0, y: y as number }, { x: rt, y: y as number });
          ctx.globalAlpha = 1;
          ctx.fillText(`${(FIB_LEVELS[i] * 100).toFixed(1)}%  ${f.price.toFixed(2)}`, x0 + 4, (y as number) - 8);
        });
        ctx.globalAlpha = 0.5;
        line(ps[0], ps[1]);
      }
    }
    if (selected) {
      ctx.globalAlpha = 1;
      ctx.fillStyle = "#ffffff";
      for (const p of ps) {
        ctx.beginPath();
        ctx.rect(p.x - 4, p.y - 4, 8, 8);
        ctx.fill();
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  private paintMeasure(a: Pt, b: Pt) {
    const pa = this.toPx(a);
    const pb = this.toPx(b);
    if (!pa || !pb) return;
    const { ctx } = this;
    const m = measure(a, b, this.tm.barSec);
    const up = m.dPrice >= 0;
    const col = up ? "34,197,94" : "239,68,68";
    ctx.save();
    ctx.fillStyle = `rgba(${col},0.16)`;
    ctx.strokeStyle = `rgb(${col})`;
    ctx.lineWidth = 1;
    ctx.fillRect(Math.min(pa.x, pb.x), Math.min(pa.y, pb.y), Math.abs(pb.x - pa.x), Math.abs(pb.y - pa.y));
    ctx.strokeRect(Math.min(pa.x, pb.x), Math.min(pa.y, pb.y), Math.abs(pb.x - pa.x), Math.abs(pb.y - pa.y));
    const text = `${m.dPrice >= 0 ? "+" : ""}${m.dPrice.toFixed(2)}${m.pct == null ? "" : ` (${m.pct >= 0 ? "+" : ""}${m.pct.toFixed(2)}%)`}  ${m.bars} bars  ${duration(m.seconds)}`;
    ctx.font = "12px system-ui, sans-serif";
    const w = ctx.measureText(text).width + 12;
    const x = Math.min(pa.x, pb.x) + Math.abs(pb.x - pa.x) / 2 - w / 2;
    const y = up ? Math.min(pa.y, pb.y) - 22 : Math.max(pa.y, pb.y) + 8;
    ctx.fillStyle = `rgb(${col})`;
    ctx.fillRect(x, y, w, 18);
    ctx.fillStyle = "#ffffff";
    ctx.textBaseline = "middle";
    ctx.fillText(text, x + 6, y + 9);
    ctx.restore();
  }
}
