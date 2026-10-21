// lightweight-charts series primitive that draws FLAG markers: a compact rounded rectangle with a small triangular pointer aimed
// at the candle and an optional count inside. Drawn in the chart's own paint pass, so flags stay glued to their candle during
// zoom, pan, resize, timeframe and date changes. The colour/side are supplied by the caller (realised outcome).
//
// flag: { id, barIndex, anchor (price the pointer touches: bar high when `above`, bar low otherwise), above, fill, textColor,
//         label (count when several patterns share the flag), selected, dim }

export const FLAG = { h: 16, minW: 18, padX: 5, point: 5, gap: 4, radius: 3, levelGap: 2, hitPad: 4 };

// Pure geometry (tested), CSS pixels. `level` > 0 only when a neighbour would overlap: the flag moves away from its candle.
export function flagGeometry({ x, anchorY, above, level = 0, width }) {
  const w = Math.max(FLAG.minW, width || 0);
  const near = FLAG.gap + level * (FLAG.h + FLAG.point + FLAG.levelGap);
  const tipY = above ? anchorY - near : anchorY + near;
  const baseY = above ? tipY - FLAG.point : tipY + FLAG.point;
  const top = above ? baseY - FLAG.h : baseY;
  return {
    body: { x: x - w / 2, y: top, w, h: FLAG.h },
    tip: [[x - 4, baseY], [x + 4, baseY], [x, tipY]],
    bounds: { x1: x - w / 2, x2: x + w / 2, y1: Math.min(top, tipY), y2: Math.max(top + FLAG.h, tipY) },
  };
}

// Greedy collision avoidance per side of the candles; nothing is dropped, a flag only moves outward when it would overlap.
export function assignLevels(items, gap = 2) {
  const levels = new Map();
  for (const above of [true, false]) {
    const placed = [];
    for (const it of items.filter((i) => i.above === above).sort((a, b) => a.x - b.x)) {
      let level = 0;
      while (placed.some((p) => p.level === level && it.x - it.w / 2 < p.x2 + gap && it.x + it.w / 2 > p.x1 - gap)) level += 1;
      placed.push({ level, x1: it.x - it.w / 2, x2: it.x + it.w / 2 });
      levels.set(it.id, level);
    }
  }
  return levels;
}

function flagPath(ctx, g, above) {
  const { x, y, w, h } = g.body;
  const r = FLAG.radius;
  const [tl, tr, tip] = g.tip;
  ctx.moveTo(x + r, y);
  if (!above) { ctx.lineTo(tl[0], tl[1]); ctx.lineTo(tip[0], tip[1]); ctx.lineTo(tr[0], tr[1]); }
  ctx.lineTo(x + w - r, y);
  ctx.arcTo(x + w, y, x + w, y + r, r);
  ctx.lineTo(x + w, y + h - r);
  ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
  if (above) { ctx.lineTo(tr[0], tr[1]); ctx.lineTo(tip[0], tip[1]); ctx.lineTo(tl[0], tl[1]); }
  ctx.lineTo(x + r, y + h);
  ctx.arcTo(x, y + h, x, y + h - r, r);
  ctx.lineTo(x, y + r);
  ctx.arcTo(x, y, x + r, y, r);
}

export class FlagLayer {
  constructor() {
    this._flags = [];
    this._hits = [];
    this._chart = null;
    this._series = null;
    this._requestUpdate = null;
    const self = this;
    this._view = {
      zOrder: () => 'top',
      renderer: () => ({
        draw(target) {
          if (!self._chart || !self._series) return;
          target.useMediaCoordinateSpace(({ context: ctx }) => self._paint(ctx));
        },
      }),
    };
  }

  attached({ chart, series, requestUpdate }) { this._chart = chart; this._series = series; this._requestUpdate = requestUpdate; }

  detached() { this._chart = null; this._series = null; this._requestUpdate = null; this._hits = []; }

  paneViews() { return [this._view]; }

  updateAllViews() {}

  setFlags(flags) {
    this._flags = flags || [];
    if (this._requestUpdate) this._requestUpdate();
  }

  _paint(ctx) {
    const ts = this._chart.timeScale();
    ctx.save();
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.font = '700 10px Inter, system-ui, sans-serif';
    const laid = [];
    for (const f of this._flags) {
      const x = ts.logicalToCoordinate(f.barIndex);
      const ay = this._series.priceToCoordinate(f.anchor);
      if (x == null || ay == null) continue;
      const tw = f.label ? ctx.measureText(f.label).width : 0;
      laid.push({ f, x, ay, w: Math.max(FLAG.minW, tw + FLAG.padX * 2), above: f.above, id: f.id });
    }
    const levels = assignLevels(laid);
    const hits = [];
    for (const l of laid.sort((a, b) => (levels.get(b.id) - levels.get(a.id)) || (a.f.selected ? 1 : 0) - (b.f.selected ? 1 : 0))) {
      const { f, x } = l;
      const g = flagGeometry({ x, anchorY: l.ay, above: f.above, level: levels.get(f.id), width: l.w });
      ctx.globalAlpha = f.dim ? 0.35 : 1;
      ctx.beginPath();
      flagPath(ctx, g, f.above);
      ctx.closePath();
      ctx.fillStyle = f.fill;
      ctx.fill();
      ctx.lineJoin = 'round';
      ctx.strokeStyle = 'rgba(15,23,42,0.9)';
      ctx.lineWidth = 1;
      ctx.stroke();
      if (f.selected) { ctx.strokeStyle = 'rgb(248,250,252)'; ctx.lineWidth = 2; ctx.stroke(); }
      if (f.label) {
        ctx.fillStyle = f.textColor;
        ctx.fillText(f.label, x, g.body.y + g.body.h / 2 + 0.5);
      }
      hits.push({ id: f.id, ...g.bounds });
    }
    ctx.restore();
    this._hits = hits;
  }

  hitTest(px, py, pad = FLAG.hitPad) {
    for (let i = this._hits.length - 1; i >= 0; i--) {
      const b = this._hits[i];
      if (px >= b.x1 - pad && px <= b.x2 + pad && py >= b.y1 - pad && py <= b.y2 + pad) return b.id;
    }
    return null;
  }
}
