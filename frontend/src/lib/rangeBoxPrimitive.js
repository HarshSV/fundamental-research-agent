// lightweight-charts series primitive that draws one translucent rectangle
// for a detected pattern's real extent: bars startIndex..endIndex horizontally,
// rangeLow..rangeHigh vertically (all taken from the detector event).
export class RangeBox {
  constructor() {
    this._range = null;
    this._chart = null;
    this._series = null;
    this._requestUpdate = null;
    const self = this;
    this._view = {
      zOrder: () => 'bottom',
      renderer: () => ({
        draw(target) {
          const r = self._range;
          if (!r || !self._chart || !self._series) return;
          const ts = self._chart.timeScale();
          const x1 = ts.logicalToCoordinate(r.startIndex);
          const x2 = ts.logicalToCoordinate(r.endIndex);
          const y1 = self._series.priceToCoordinate(r.rangeHigh);
          const y2 = self._series.priceToCoordinate(r.rangeLow);
          if (x1 == null || x2 == null || y1 == null || y2 == null) return;
          target.useBitmapCoordinateSpace(({ context, horizontalPixelRatio: hr, verticalPixelRatio: vr }) => {
            const left = Math.min(x1, x2) * hr;
            const top = Math.min(y1, y2) * vr;
            const w = Math.max(Math.abs(x2 - x1) * hr, 2);
            const h = Math.max(Math.abs(y2 - y1) * vr, 2);
            context.fillStyle = 'rgba(251,191,36,0.10)';
            context.fillRect(left, top, w, h);
            context.strokeStyle = 'rgba(251,191,36,0.65)';
            context.lineWidth = Math.max(1, hr);
            context.setLineDash([4 * hr, 3 * hr]);
            context.strokeRect(left, top, w, h);
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

  setRange(range) {
    this._range = range;
    if (this._requestUpdate) this._requestUpdate();
  }
}
