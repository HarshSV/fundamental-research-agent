// lightweight-charts series primitive that draws order-block zones: a shaded
// band from the block candle to the right edge (or to the bar that broke it),
// the invalidation line, and (optionally) liquidity Level 1 / Level 2 and the
// dotted opposite-side ladder. Only the current zone per side is labelled;
// earlier zones are drawn faded and unlabelled. Colours come from the theme
// tokens (tokens.css) so light and dark both work.
//
// Geometry is computed in place on pre-allocated records (no per-frame
// allocation); coordinates are re-read from the chart on every draw, so pan /
// zoom / resize need no extra bookkeeping.

const RGB_VARS = { bull: '--emerald-500', bear: '--red-500', amber: '--amber-400' };
const FALLBACK = { bull: '34 197 94', bear: '239 68 68', amber: '251 191 36' };

const fmt = (v) => (Number.isFinite(v) ? v.toFixed(2) : '—');

export class ZoneOverlay {
  constructor() {
    this._zones = [];
    this._geo = [];
    this._showLiquidity = true;
    this._narrow = false;
    this._chart = null;
    this._series = null;
    this._requestUpdate = null;
    this._themeKey = null;
    this._rgb = { ...FALLBACK };
    const self = this;
    const view = (layer) => ({
      zOrder: () => (layer === 'fill' ? 'bottom' : 'top'),
      renderer: () => ({ draw: (target) => self._draw(target, layer) }),
    });
    this._views = [view('fill'), view('line')];
  }

  attached({ chart, series, requestUpdate }) { this._chart = chart; this._series = series; this._requestUpdate = requestUpdate; }
  detached() { this._chart = null; this._series = null; this._requestUpdate = null; }
  paneViews() { return this._views; }
  updateAllViews() {}

  // zones: [{ id, bull, startIdx, endIdx|null, zoneLow, zoneHigh, inv, level1, level2, ladder[], rr, current, selected }]
  // Indexes are bar indexes of the displayed series. Null prices are skipped, never drawn at 0.
  setData({ zones, showLiquidity = true, narrow = false }) {
    this._zones = zones || [];
    this._showLiquidity = showLiquidity;
    this._narrow = narrow;
    this._geo = this._zones.map((z) => ({
      id: z.id, x1: 0, x2: 0, yTop: 0, yBot: 0, ok: false,
      labels: z.current ? {
        z: this._narrow ? 'Z' : `Z ${fmt(z.z ?? (z.bull ? z.zoneHigh : z.zoneLow))}`,
        inv: this._narrow ? 'INV' : `INV ${fmt(z.inv)}`,
        l1: this._narrow ? 'L1' : `L1 ${fmt(z.level1)}`,
        l2: this._narrow ? 'L2' : `L2 ${fmt(z.level2)}`,
        rr: this._narrow ? `R:R ${z.rr == null ? '—' : z.rr.toFixed(1)}` : `Room:Risk ${z.rr == null ? '—' : z.rr.toFixed(2)}`,
      } : null,
    }));
    if (this._requestUpdate) this._requestUpdate();
  }

  // Zone id under a media-space point, or null.
  hitTest(x, y) {
    for (let i = this._geo.length - 1; i >= 0; i--) {
      const g = this._geo[i];
      if (g.ok && x >= g.x1 && x <= g.x2 && y >= g.yTop && y <= g.yBot) return g.id;
    }
    return null;
  }

  _colors() {
    if (typeof document === 'undefined') return this._rgb;
    const key = document.documentElement.className;
    if (key !== this._themeKey) {
      this._themeKey = key;
      const cs = getComputedStyle(document.documentElement);
      for (const k of Object.keys(RGB_VARS)) this._rgb[k] = cs.getPropertyValue(RGB_VARS[k]).trim() || FALLBACK[k];
    }
    return this._rgb;
  }

  _draw(target, layer) {
    const chart = this._chart, series = this._series;
    if (!chart || !series || !this._zones.length) return;
    const ts = chart.timeScale();
    const rgb = this._colors();
    target.useBitmapCoordinateSpace(({ context: ctx, bitmapSize, horizontalPixelRatio: hr, verticalPixelRatio: vr }) => {
      const W = bitmapSize.width / hr;
      ctx.save();
      ctx.beginPath(); ctx.rect(0, 0, bitmapSize.width, bitmapSize.height); ctx.clip();
      ctx.font = `${Math.round(10 * vr)}px sans-serif`;
      ctx.textBaseline = 'bottom';
      const lw = Math.max(1, hr);
      for (let i = 0; i < this._zones.length; i++) {
        const z = this._zones[i], g = this._geo[i];
        const xa = ts.logicalToCoordinate(z.startIdx);
        const xb = z.endIdx == null ? W : ts.logicalToCoordinate(z.endIdx);
        const yH = series.priceToCoordinate(z.zoneHigh), yL = series.priceToCoordinate(z.zoneLow);
        g.ok = false;
        if (xa == null || xb == null || yH == null || yL == null) continue;
        g.x1 = Math.max(xa, 0); g.x2 = Math.min(xb, W); g.yTop = Math.min(yH, yL); g.yBot = Math.max(yH, yL);
        if (g.x2 <= g.x1) continue; // fully outside the visible range
        g.ok = true;
        const side = z.bull ? rgb.bull : rgb.bear;
        const faint = !z.current && !z.selected;
        const x1 = g.x1 * hr, x2 = g.x2 * hr;
        if (layer === 'fill') {
          ctx.fillStyle = `rgb(${side} / ${faint ? 0.07 : z.selected ? 0.26 : 0.17})`;
          ctx.fillRect(x1, g.yTop * vr, x2 - x1, Math.max((g.yBot - g.yTop) * vr, 2));
          ctx.strokeStyle = `rgb(${side} / ${faint ? 0.25 : 0.7})`;
          ctx.lineWidth = lw; ctx.setLineDash([]);
          ctx.strokeRect(x1, g.yTop * vr, x2 - x1, Math.max((g.yBot - g.yTop) * vr, 2));
          continue;
        }
        const amber = (a) => `rgb(${rgb.amber} / ${a})`;
        const hline = (price, a, dash, label) => {
          if (price == null) return;
          const y = series.priceToCoordinate(price);
          if (y == null) return;
          ctx.strokeStyle = amber(a); ctx.lineWidth = lw; ctx.setLineDash(dash ? [dash * hr, 3 * hr] : []);
          ctx.beginPath(); ctx.moveTo(x1, y * vr); ctx.lineTo(x2, y * vr); ctx.stroke();
          if (label) { ctx.fillStyle = amber(0.95); ctx.fillText(label, Math.max(x1 + 2 * hr, x2 - (label.length * 5.8 + 4) * hr), y * vr - 2 * vr); }
        };
        hline(z.inv, faint ? 0.3 : 0.85, 5, g.labels && g.labels.inv);
        if (z.current && g.labels) {
          ctx.fillStyle = `rgb(${side} / 0.95)`;
          const zEdge = z.bull ? g.yTop : g.yBot;
          ctx.fillText(g.labels.z, Math.max(x1 + 2 * hr, x2 - (g.labels.z.length * 5.8 + 4) * hr), zEdge * vr - 2 * vr);
          if (this._showLiquidity) {
            hline(z.level1, 0.8, 0, g.labels.l1);
            hline(z.level2, 0.8, 0, g.labels.l2);
            if (z.ladder) for (let q = 0; q < z.ladder.length; q++) hline(z.ladder[q], 0.5, 1.5, null);
          }
          // Room:Risk badge anchored to the zone's far side from price, inside the band's left end
          ctx.fillStyle = `rgb(${rgb.amber} / 0.95)`;
          ctx.fillText(g.labels.rr, x1 + 3 * hr, (z.bull ? g.yBot : g.yTop) * vr + (z.bull ? 12 : -2) * vr);
        }
      }
      ctx.restore();
    });
  }
}
