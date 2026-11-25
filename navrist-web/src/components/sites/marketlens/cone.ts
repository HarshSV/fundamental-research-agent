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
  anchor: number; // the price the forecast starts from (the last price)
  tone: "up" | "down" | "even";
  points: ConePoint[];
}

export interface ConeStyle {
  gain: string; // "r, g, b"
  loss: string;
  mid: string;  // the middle line's colour, "r, g, b"
  text: string;
  bg: string; // the chart's own background, as a soft backing for the numbers written on the fan
}

const SHOW_MS = 900;      // the fan opens from the last price to the right
const HIDE_MS = 650;      // and closes the same way, back to the last price

/**
 * The forecast drawn the way TradingView draws a price target: from the last price a fan opens to the right, three dotted lines going to the
 * high, middle and low of where the price ended up 20 sessions after similar past days, green between the current price and the high, red
 * between it and the low, and a solid line at the current price. The prices are tagged on the price axis (StockChart adds those) and written at
 * the line ends. It lives on the price series, so it moves and zooms with the chart. Switching it on or off only animates the fan, left to right
 * and back: the price scale always has room for it, so the chart itself never moves when it is switched.
 */
export class ConePrimitive implements ISeriesPrimitive<Time> {
  private param: SeriesAttachedParameter<Time> | null = null;
  private cone: Cone | null = null;
  private lastIndex = 0;
  private style: ConeStyle = { gain: "16, 185, 129", loss: "239, 68, 68", mid: "148, 163, 184", text: "#94a3b8", bg: "rgba(255,255,255,0)" };
  private open = 0;           // 0 closed .. 1 fully open
  private raf = 0;
  private readonly view: IPrimitivePaneView = { zOrder: () => "bottom", renderer: () => this.renderer };

  /** the horizon the fan reaches: the furthest one of 5 sessions or more */
  private far(): ConePoint | null {
    const pts = (this.cone?.points ?? []).filter((q) => q.k >= 5);
    return pts.length ? pts[pts.length - 1] : null;
  }

  private readonly renderer: IPrimitivePaneRenderer = {
    draw: (target: CanvasRenderingTarget2D) => {
      const p = this.param;
      const c = this.cone;
      const q = this.far();
      if (!p || !c || !q || this.open <= 0) return;
      const ts = p.chart.timeScale();
      const x0 = ts.logicalToCoordinate(this.lastIndex as Logical);
      const x1 = ts.logicalToCoordinate((this.lastIndex + q.k) as Logical);
      const y0 = p.series.priceToCoordinate(c.anchor);
      const yh = p.series.priceToCoordinate(q.high);
      const ym = p.series.priceToCoordinate(q.mid);
      const yl = p.series.priceToCoordinate(q.low);
      if (x0 == null || x1 == null || y0 == null || yh == null || ym == null || yl == null) return;
      const e = this.open < 0.5 ? 4 * this.open ** 3 : 1 - (-2 * this.open + 2) ** 3 / 2;      // eased, so it starts and ends softly
      const reach = x0 - 6 + (x1 - x0 + 12) * e;                                              // the fan is shown up to here
      target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
        ctx.save();
        ctx.beginPath();
        ctx.rect(0, 0, reach, mediaSize.height);
        ctx.clip();
        // green between the current price and the high, red between it and the low
        ctx.fillStyle = `rgba(${this.style.gain}, 0.16)`;
        ctx.beginPath();
        ctx.moveTo(x0, y0);
        ctx.lineTo(x1, yh);
        ctx.lineTo(x1, y0);
        ctx.closePath();
        ctx.fill();
        ctx.fillStyle = `rgba(${this.style.loss}, 0.16)`;
        ctx.beginPath();
        ctx.moveTo(x0, y0);
        ctx.lineTo(x1, yl);
        ctx.lineTo(x1, y0);
        ctx.closePath();
        ctx.fill();
        // the solid line at the current price, and the three dotted lines of the fan
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = "rgba(59, 130, 246, 0.95)";
        ctx.beginPath();
        ctx.moveTo(x0, y0);
        ctx.lineTo(x1, y0);
        ctx.stroke();
        ctx.setLineDash([2, 3]);
        ctx.lineWidth = 1.4;
        for (const [y, rgb] of [[yh, this.style.gain], [ym, this.style.mid], [yl, this.style.loss]] as [number, string][]) {
          ctx.strokeStyle = `rgba(${rgb}, 0.95)`;
          ctx.beginPath();
          ctx.moveTo(x0, y0);
          ctx.lineTo(x1, y);
          ctx.stroke();
        }
        ctx.setLineDash([]);
        ctx.fillStyle = "rgba(59, 130, 246, 1)";
        ctx.beginPath();
        ctx.arc(x0, y0, 3.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
        // the numbers of the range and the caption appear once the fan has opened (and go as it starts to close)
        const a = Math.max(0, Math.min(1, (this.open - 0.8) / 0.2));
        if (a <= 0) return;
        ctx.save();
        ctx.globalAlpha = a;
        if (x1 - x0 > 84) {
          const placed: { y0: number; y1: number }[] = [];
          const fp = (v: number) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })} · ${v >= c.anchor ? "+" : "-"}${Math.abs((v / c.anchor - 1) * 100).toFixed(1)}%`;
          ctx.font = "600 10px system-ui, sans-serif";
          ctx.textAlign = "right";
          ctx.textBaseline = "middle";
          const rows: [number, number, string][] = [
            [q.high, yh + 11, this.style.gain],
            [q.low, yl - 11, this.style.loss],
            [q.mid, ym + (ym < y0 ? -10 : 10), this.style.mid],
          ];
          for (const [v, yy, rgb] of rows) {
            let y = yy;
            for (let t = 0; t < 6 && placed.some((r) => y - 8 < r.y1 && y + 8 > r.y0); t++) y += yy > y0 ? 16 : -16;
            const txt = fp(v);
            const w = ctx.measureText(txt).width;
            placed.push({ y0: y - 8, y1: y + 8 });
            ctx.fillStyle = this.style.bg;
            ctx.fillRect(x1 - 6 - w - 3, y - 8, w + 6, 16);
            ctx.fillStyle = `rgb(${rgb})`;
            ctx.fillText(txt, x1 - 6, y);
          }
        }
        const cap = `NEXT ${q.k} SESSIONS`;
        ctx.font = "600 10px system-ui, sans-serif";
        const tw = ctx.measureText(cap).width;
        const cx = x0 + (x1 - x0) / 2;
        if (x1 - x0 > tw + 8) {
          ctx.fillStyle = "rgba(148, 163, 184, 0.16)";
          ctx.fillRect(cx - tw / 2 - 6, mediaSize.height - 44, tw + 12, 16);
          ctx.fillStyle = this.style.text;
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText(cap, cx, mediaSize.height - 36);
        }
        ctx.restore();
      });
    },
  };

  /** Hand the forecast its data. `lastIndex` is the logical index of the last bar on the series. */
  set(cone: Cone | null, lastIndex: number, style: ConeStyle) {
    this.cone = cone;
    this.lastIndex = lastIndex;
    this.style = style;
    this.param?.requestUpdate();
  }

  /** Open the fan from the last price to the right, or close it back the same way. `done` runs when the move has finished. */
  setVisible(v: boolean, done?: () => void) {
    cancelAnimationFrame(this.raf);
    const from = this.open;
    const to = v ? 1 : 0;
    const reduced = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced || from === to) {
      this.open = to;
      this.param?.requestUpdate();
      done?.();
      return;
    }
    const ms = (v ? SHOW_MS : HIDE_MS) * Math.abs(to - from);
    const t0 = performance.now();
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / ms);
      this.open = from + (to - from) * k;
      this.param?.requestUpdate();
      if (k < 1) this.raf = requestAnimationFrame(step);
      else done?.();
    };
    this.raf = requestAnimationFrame(step);
  }

  attached(param: SeriesAttachedParameter<Time>) {
    this.param = param;
  }

  detached() {
    cancelAnimationFrame(this.raf);
    this.param = null;
  }

  updateAllViews() {}

  paneViews(): readonly IPrimitivePaneView[] {
    return [this.view];
  }

  /** The price scale always has room for the whole fan, shown or not, so switching the forecast never rescales the chart. */
  autoscaleInfo(_start: Logical, end: Logical): AutoscaleInfo | null {
    const q = this.far();
    const c = this.cone;
    if (!q || !c || end < this.lastIndex) return null;
    return { priceRange: { minValue: Math.min(c.anchor, q.low), maxValue: Math.max(c.anchor, q.high) } };
  }
}
