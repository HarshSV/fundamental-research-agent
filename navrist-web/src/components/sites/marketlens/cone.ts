import type { CanvasRenderingTarget2D } from "fancy-canvas";
import type { AutoscaleInfo, IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, Logical, SeriesAttachedParameter, Time } from "lightweight-charts";

/** One horizon of the forecast: the price range the stock should land in `k` sessions after the last bar. */
export interface ConePoint {
  k: number;
  low: number;
  mid: number;
  high: number;
  up?: number; // chance of closing higher, percent
  down?: number;
}

export interface Cone {
  anchor: number; // the price the fan starts from (the last price)
  tone: "up" | "down" | "even";
  points: ConePoint[];
}

export interface ConeStyle {
  fill: string; // "r, g, b"
  text: string;
  bg: string; // the chart's own background, as a soft backing for labels drawn over candles
}

const inr = (v: number) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

/** Value of an edge at `k` sessions: between the known horizons it follows the square root of time, the way a spread of
 *  prices really widens, so the fan is a smooth curve rather than straight segments. */
function at(pts: { k: number; v: number }[], k: number): number {
  for (let i = 1; i < pts.length; i++) {
    if (k <= pts[i].k) {
      const a = pts[i - 1];
      const b = pts[i];
      const t = (Math.sqrt(k) - Math.sqrt(a.k)) / (Math.sqrt(b.k) - Math.sqrt(a.k));
      return a.v + (b.v - a.v) * t;
    }
  }
  return pts[pts.length - 1].v;
}

/**
 * A chart primitive that draws the forecast as a fan to the right of the last bar: a shaded band between the realistic best
 * and worst price, a dashed middle line and the prices at its far end. It lives on the price series, so it moves and zooms
 * with the chart and widens the price axis to fit itself.
 */
export class ConePrimitive implements ISeriesPrimitive<Time> {
  private param: SeriesAttachedParameter<Time> | null = null;
  private cone: Cone | null = null;
  private lastIndex = 0;
  private style: ConeStyle = { fill: "148, 163, 184", text: "#94a3b8", bg: "rgba(255,255,255,0.0)" };
  private readonly view: IPrimitivePaneView = { zOrder: () => "bottom", renderer: () => this.renderer };

  private readonly renderer: IPrimitivePaneRenderer = {
    draw: (target: CanvasRenderingTarget2D) => {
      const p = this.param;
      const c = this.cone;
      if (!p || !c) return;
      // one block per horizon of 5 sessions or more: the first runs from the last bar to +5, the next from +5 to +20
      const pts = c.points.filter((q) => q.k >= 5);
      if (pts.length === 0) return;
      const ts = p.chart.timeScale();
      const X = (k: number) => ts.logicalToCoordinate((this.lastIndex + k) as Logical);
      const Y = (v: number) => p.series.priceToCoordinate(v);
      target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
        ctx.save();
        // every label is placed through here: it is nudged down until it clears the labels already drawn, and gets a soft backing so it stays
        // readable over candles and lines. Nothing overlaps, so a crowded forecast simply stacks its labels.
        const placed: { x0: number; y0: number; x1: number; y1: number }[] = [];
        const label = (text: string, font: string, color: string, ax: number, cy: number, align: "left" | "right" | "center") => {
          ctx.font = font;
          const tw = ctx.measureText(text).width;
          const h = 14;
          const left = align === "left" ? ax : align === "right" ? ax - tw : ax - tw / 2;
          let top = cy - h / 2;
          for (let tries = 0; tries < 8; tries++) {
            const hit = placed.some((r) => left < r.x1 + 2 && left + tw > r.x0 - 2 && top < r.y1 + 1 && top + h > r.y0 - 1);
            if (!hit) break;
            top += h + 1;
          }
          if (top + h > mediaSize.height - 2) return;
          placed.push({ x0: left, y0: top, x1: left + tw, y1: top + h });
          ctx.fillStyle = this.style.bg;
          ctx.fillRect(left - 3, top, tw + 6, h);
          ctx.fillStyle = color;
          ctx.textAlign = "left";
          ctx.textBaseline = "middle";
          ctx.fillText(text, left, top + h / 2 + 0.5);
        };
        const quiet = "rgba(148, 163, 184, 0.98)";
        const blocks: { q: ConePoint; x0: number; x1: number; yh: number; yl: number; ym: number }[] = [];
        let prev = 0;
        for (const q of pts) {
          const x0 = X(prev);
          const x1 = X(q.k);
          const yh = Y(q.high);
          const yl = Y(q.low);
          const ym = Y(q.mid);
          prev = q.k;
          if (x0 == null || x1 == null || yh == null || yl == null || ym == null) continue;
          blocks.push({ q, x0, x1, yh, yl, ym });
          const w = x1 - x0;
          // the grey future column, full height, with a hairline where it starts
          ctx.fillStyle = "rgba(148, 163, 184, 0.10)";
          ctx.fillRect(x0, 0, w, mediaSize.height);
          ctx.fillStyle = "rgba(148, 163, 184, 0.35)";
          ctx.fillRect(x0, 0, 1, mediaSize.height);
          // the likely range, flat across the block, and the middle price dashed
          ctx.fillStyle = `rgba(${this.style.fill}, 0.22)`;
          ctx.fillRect(x0, yh, w, yl - yh);
          ctx.strokeStyle = `rgba(${this.style.fill}, 0.6)`;
          ctx.lineWidth = 1;
          ctx.strokeRect(x0 + 0.5, yh, w - 1, yl - yh);
          ctx.setLineDash([5, 4]);
          ctx.lineWidth = 1.5;
          ctx.strokeStyle = `rgba(${this.style.fill}, 0.95)`;
          ctx.beginPath();
          ctx.moveTo(x0, ym);
          ctx.lineTo(x1, ym);
          ctx.stroke();
          ctx.setLineDash([]);
        }
        // The blocks are only a few bars wide, so no text goes inside them but a small tag; each horizon's odds, range and middle price are
        // written in the line above the chart (StockView), where nothing can sit on top of the candles.
        for (const b of blocks) label(String(b.q.k), "600 11px system-ui, sans-serif", quiet, b.x0 + (b.x1 - b.x0) / 2, 10, "center");
        ctx.restore();
      });
    },
  };

  /** Hand the fan its data. `lastIndex` is the logical index of the last bar on the series. */
  set(cone: Cone | null, lastIndex: number, style: ConeStyle) {
    this.cone = cone;
    this.lastIndex = lastIndex;
    this.style = style;
    this.param?.requestUpdate();
  }

  attached(param: SeriesAttachedParameter<Time>) {
    this.param = param;
  }

  detached() {
    this.param = null;
  }

  updateAllViews() {}

  paneViews(): readonly IPrimitivePaneView[] {
    return [this.view];
  }

  autoscaleInfo(_start: Logical, end: Logical): AutoscaleInfo | null {
    const c = this.cone;
    if (!c || c.points.length === 0 || end < this.lastIndex) return null;
    return {
      priceRange: {
        minValue: Math.min(c.anchor, ...c.points.map((q) => q.low)),
        // headroom above the highest price for the block titles
        maxValue: (() => {
          const hi = Math.max(c.anchor, ...c.points.map((q) => q.high));
          const lo = Math.min(c.anchor, ...c.points.map((q) => q.low));
          return hi + (hi - lo) * 0.14;
        })(),
      },
    };
  }
}
