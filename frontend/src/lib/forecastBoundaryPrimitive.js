// Series primitives for the FORECAST panel.
//  - ForecastBoundary: vertical dashed "NOW" divider at the reference candle, a subtle shaded forecast zone to its
//    right, and "ACTUAL" / "FORECAST" captions so LEFT = what happened, RIGHT = what the model expects.
//  - ForecastBands: nested translucent 95/80/50% uncertainty fan from the reference price through +1..+5, with
//    "+h" labels. Draws only the points the backend supplied.

export class ForecastBoundary {
  constructor() {
    this._time = null;
    this._chart = null;
    this._requestUpdate = null;
    const self = this;
    this._view = {
      zOrder: () => 'bottom',
      renderer: () => ({
        draw(target) {
          if (self._time == null || !self._chart) return;
          const x = self._chart.timeScale().timeToCoordinate(self._time);
          if (x == null) return;
          target.useBitmapCoordinateSpace(({ context, bitmapSize, horizontalPixelRatio: hr, verticalPixelRatio: vr }) => {
            const xb = x * hr;
            context.fillStyle = 'rgba(96,165,250,0.06)';
            context.fillRect(xb, 0, bitmapSize.width - xb, bitmapSize.height);
            context.strokeStyle = 'rgba(203,213,225,0.85)';
            context.lineWidth = Math.max(1, hr);
            context.setLineDash([5 * hr, 4 * hr]);
            context.beginPath();
            context.moveTo(xb, 0);
            context.lineTo(xb, bitmapSize.height);
            context.stroke();
            context.setLineDash([]);
            context.font = `${10 * vr}px ui-sans-serif, system-ui, sans-serif`;
            context.textBaseline = 'top';
            context.textAlign = 'right';
            context.fillStyle = 'rgba(148,163,184,0.9)';
            context.fillText('ACTUAL', xb - 28 * hr, 8 * vr);
            context.textAlign = 'left';
            context.fillStyle = 'rgba(147,197,253,0.95)';
            context.fillText('FORECAST', xb + 28 * hr, 8 * vr);
            // NOW chip
            const w = 30 * hr, h = 14 * vr;
            context.fillStyle = 'rgba(30,41,59,0.95)';
            context.strokeStyle = 'rgba(203,213,225,0.85)';
            context.lineWidth = Math.max(1, hr);
            context.beginPath();
            context.rect(xb - w / 2, 6 * vr, w, h);
            context.fill();
            context.stroke();
            context.fillStyle = 'rgb(226,232,240)';
            context.textAlign = 'center';
            context.textBaseline = 'middle';
            context.fillText('NOW', xb, 6 * vr + h / 2 + vr);
          });
        },
      }),
    };
  }

  attached({ chart, requestUpdate }) {
    this._chart = chart;
    this._requestUpdate = requestUpdate;
  }

  detached() {
    this._chart = null;
    this._requestUpdate = null;
  }

  paneViews() { return [this._view]; }
  updateAllViews() {}

  setTime(time) {
    this._time = time;
    if (this._requestUpdate) this._requestUpdate();
  }
}

const FILL = { 95: 'rgba(96,165,250,0.15)', 80: 'rgba(96,165,250,0.24)', 50: 'rgba(96,165,250,0.40)' };

export class ForecastBands {
  constructor() {
    this._bands = { 95: [], 80: [], 50: [] };
    this._labels = [];
    this._chart = null;
    this._series = null;
    this._requestUpdate = null;
    const self = this;
    this._view = {
      zOrder: () => 'bottom',
      renderer: () => ({
        draw(target) {
          if (!self._chart || !self._series) return;
          const ts = self._chart.timeScale();
          target.useBitmapCoordinateSpace(({ context, horizontalPixelRatio: hr, verticalPixelRatio: vr }) => {
            const pt = (p, key) => {
              const x = ts.timeToCoordinate(p.time);
              const y = self._series.priceToCoordinate(p[key]);
              return x == null || y == null ? null : [x * hr, y * vr];
            };
            for (const lv of [95, 80, 50]) {
              const pts = self._bands[lv];
              if (pts.length < 2) continue;
              const hi = pts.map((p) => pt(p, 'hi'));
              const lo = pts.map((p) => pt(p, 'lo'));
              if (hi.some((v) => !v) || lo.some((v) => !v)) continue;
              context.beginPath();
              hi.forEach(([x, y], i) => (i ? context.lineTo(x, y) : context.moveTo(x, y)));
              [...lo].reverse().forEach(([x, y]) => context.lineTo(x, y));
              context.closePath();
              context.fillStyle = FILL[lv];
              context.fill();
              if (lv === 80) {
                context.strokeStyle = 'rgba(96,165,250,0.75)';
                context.lineWidth = Math.max(1, hr);
                context.setLineDash([4 * hr, 3 * hr]);
                for (const edge of [hi, lo]) {
                  context.beginPath();
                  edge.forEach(([x, y], i) => (i ? context.lineTo(x, y) : context.moveTo(x, y)));
                  context.stroke();
                }
                context.setLineDash([]);
              }
            }
            // horizon labels above the widest band that exists
            context.font = `${10 * vr}px ui-sans-serif, system-ui, sans-serif`;
            context.textAlign = 'center';
            context.textBaseline = 'bottom';
            context.fillStyle = 'rgba(191,219,254,0.95)';
            for (const l of self._labels) {
              const wide = (self._bands[95].find((p) => p.time === l.time) || self._bands[80].find((p) => p.time === l.time) || self._bands[50].find((p) => p.time === l.time));
              const x = ts.timeToCoordinate(l.time);
              const y = wide ? self._series.priceToCoordinate(wide.hi) : null;
              if (x == null) continue;
              context.fillText(`+${l.h}`, x * hr, (y == null ? 24 : Math.max(26, y - 4)) * vr);
            }
          });
        },
      }),
    };
  }

  attached({ chart, series, requestUpdate }) {
    this._chart = chart;
    this._series = series;
    this._requestUpdate = requestUpdate;
  }

  detached() {
    this._chart = null;
    this._series = null;
    this._requestUpdate = null;
  }

  paneViews() { return [this._view]; }
  updateAllViews() {}

  setData(bands, labels) {
    this._bands = bands;
    this._labels = labels;
    if (this._requestUpdate) this._requestUpdate();
  }
}
