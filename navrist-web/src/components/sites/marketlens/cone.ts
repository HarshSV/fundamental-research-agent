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
  private style: ConeStyle = { fill: "148, 163, 184", text: "#94a3b8" };
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
        let prev = 0;
        for (const q of pts) {
          const x0 = X(prev);
          const x1 = X(q.k);
          const yh = Y(q.high);
          const yl = Y(q.low);
          const ym = Y(q.mid);
          prev = q.k;
          if (x0 == null || x1 == null || yh == null || yl == null || ym == null) continue;
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

          // prices inside the right edge of the block
          ctx.font = "600 11px system-ui, sans-serif";
          ctx.fillStyle = this.style.text;
          ctx.textAlign = "right";
          // inside the band, so the high price never runs into the title above the block
          ctx.textBaseline = "top";
          ctx.fillText(inr(q.high), x1 - 6, yh + 3);
          ctx.textBaseline = "bottom";
          ctx.fillText(inr(q.mid), x1 - 6, ym - 3);
          ctx.fillText(inr(q.low), x1 - 6, yl - 3);

          // the title and the odds at the top of the block
          ctx.textAlign = "center";
          ctx.textBaseline = "top";
          ctx.font = "600 11px system-ui, sans-serif";
          ctx.fillStyle = "rgba(148, 163, 184, 0.95)";
          const cx = x0 + w / 2;
          const narrow = w < 110; // the 5-session block is only a few bars wide: shorter title, odds on two lines
          ctx.fillText(narrow ? `Next ${q.k}` : `Next ${q.k} sessions`, cx, 8);
          if (q.up != null && q.down != null) {
            ctx.font = "500 10px system-ui, sans-serif";
            if (narrow) {
              ctx.fillText(`${q.up}% up`, cx, 22);
              ctx.fillText(`${q.down}% down`, cx, 34);
            } else ctx.fillText(`${q.up}% up · ${q.down}% down`, cx, 22);
          }
        }
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
