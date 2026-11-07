import type { CanvasRenderingTarget2D } from "fancy-canvas";
import type { AutoscaleInfo, IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesPrimitive, Logical, SeriesAttachedParameter, Time } from "lightweight-charts";

/** One horizon of the forecast: the price range the stock should land in `k` sessions after the last bar. */
export interface ConePoint {
  k: number;
  low: number;
  mid: number;
  high: number;
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
      if (!p || !c || c.points.length === 0) return;
      const ts = p.chart.timeScale();
      const kMax = c.points[c.points.length - 1].k;
      const hi = [{ k: 0, v: c.anchor }, ...c.points.map((q) => ({ k: q.k, v: q.high }))];
      const mid = [{ k: 0, v: c.anchor }, ...c.points.map((q) => ({ k: q.k, v: q.mid }))];
      const lo = [{ k: 0, v: c.anchor }, ...c.points.map((q) => ({ k: q.k, v: q.low }))];
      // the chart only converts whole bar indexes; the points in between are interpolated along the bar spacing
      const xa = ts.logicalToCoordinate(this.lastIndex as Logical);
      const xb = ts.logicalToCoordinate((this.lastIndex + kMax) as Logical);
      if (xa == null || xb == null) return;
      const X = (k: number) => xa + ((xb - xa) * k) / kMax;
      const Y = (v: number) => p.series.priceToCoordinate(v);
      const steps: number[] = [];
      for (let k = 0; k <= kMax; k += 0.5) steps.push(k);
      const top = steps.map((k) => ({ x: X(k), y: Y(at(hi, k)) }));
      const bot = steps.map((k) => ({ x: X(k), y: Y(at(lo, k)) }));
      const med = steps.map((k) => ({ x: X(k), y: Y(at(mid, k)) }));
      if ([...top, ...bot, ...med].some((q) => q.x == null || q.y == null)) return;
      target.useMediaCoordinateSpace(({ context: ctx }) => {
        const T = top as { x: number; y: number }[];
        const B = bot as { x: number; y: number }[];
        const M = med as { x: number; y: number }[];
        const x0 = T[0].x;
        const x1 = T[T.length - 1].x;
        const g = ctx.createLinearGradient(x0, 0, x1, 0);
        g.addColorStop(0, `rgba(${this.style.fill}, 0.34)`);
        g.addColorStop(1, `rgba(${this.style.fill}, 0.08)`);
        ctx.save();
        ctx.beginPath();
        T.forEach((q, i) => (i === 0 ? ctx.moveTo(q.x, q.y) : ctx.lineTo(q.x, q.y)));
        for (let i = B.length - 1; i >= 0; i--) ctx.lineTo(B[i].x, B[i].y);
        ctx.closePath();
        ctx.fillStyle = g;
        ctx.fill();

        ctx.lineWidth = 1;
        ctx.strokeStyle = `rgba(${this.style.fill}, 0.55)`;
        for (const edge of [T, B]) {
          ctx.beginPath();
          edge.forEach((q, i) => (i === 0 ? ctx.moveTo(q.x, q.y) : ctx.lineTo(q.x, q.y)));
          ctx.stroke();
        }
        ctx.setLineDash([5, 4]);
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = `rgba(${this.style.fill}, 0.95)`;
        ctx.beginPath();
        M.forEach((q, i) => (i === 0 ? ctx.moveTo(q.x, q.y) : ctx.lineTo(q.x, q.y)));
        ctx.stroke();
        ctx.setLineDash([]);

        // the prices where the fan ends, inside its right edge
        const last = c.points[c.points.length - 1];
        ctx.font = "600 11px system-ui, sans-serif";
        ctx.fillStyle = this.style.text;
        ctx.textAlign = "right";
        ctx.textBaseline = "bottom";
        ctx.fillText(inr(last.high), x1 - 6, T[T.length - 1].y - 3);
        ctx.textBaseline = "middle";
        ctx.fillText(inr(last.mid), x1 - 6, M[M.length - 1].y);
        ctx.textBaseline = "top";
        ctx.fillText(inr(last.low), x1 - 6, B[B.length - 1].y + 3);

        // faint markers for the horizons in between
        ctx.font = "500 10px system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillStyle = `rgba(${this.style.fill}, 0.9)`;
        for (const q of c.points) {
          if (q.k === kMax || q.k < 3) continue;
          const xx = X(q.k);
          const yy = Y(q.low);
          if (xx == null || yy == null) continue;
          ctx.fillText(`${q.k} sessions`, xx, yy + 5);
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
        maxValue: Math.max(c.anchor, ...c.points.map((q) => q.high)),
      },
    };
  }
}
