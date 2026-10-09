import React, { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, CandlestickSeries, LineSeries, LineStyle } from 'lightweight-charts';
import { ForecastBoundary, ForecastBands } from '../lib/forecastBoundaryPrimitive.js';
import { buildForecastChart } from '../lib/forecastView.js';
import { forecastBarByTime, describeForecastBar } from '../lib/forecast.js';
import { IST, istClock } from '../lib/marketTime.js';

// Separate chart for the model projection. Left of NOW = a short actual-candle context (solid); right of NOW =
// predicted candles (hollow, only where the backend issued one) and nested 50/80/95% uncertainty bands.
export default function ForecastChart({ resp }) {
  const ref = useRef(null);
  const api = useRef(null);
  const respRef = useRef(null);
  const actualRef = useRef([]);
  const lastKey = useRef(null);
  const [tip, setTip] = useState(null);

  useEffect(() => {
    if (!ref.current) return undefined;
    const chart = createChart(ref.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: 'rgb(148 163 184)' },
      grid: { vertLines: { color: 'rgba(148,163,184,0.08)' }, horzLines: { color: 'rgba(148,163,184,0.08)' } },
      rightPriceScale: { borderColor: 'rgba(148,163,184,0.15)', scaleMargins: { top: 0.18, bottom: 0.12 } },
      localization: { timeFormatter: (t) => istClock(t, { hour12: false }) },
      timeScale: {
        borderColor: 'rgba(148,163,184,0.15)', timeVisible: true, secondsVisible: false, rightOffset: 1,
        tickMarkFormatter: (t) => istClock(t, { hour12: false }),
      },
      autoSize: true,
    });
    const actual = chart.addSeries(CandlestickSeries, {
      upColor: 'rgb(16 185 129)', downColor: 'rgb(239 68 68)', borderVisible: false,
      wickUpColor: 'rgb(16 185 129)', wickDownColor: 'rgb(239 68 68)', priceLineVisible: false, lastValueVisible: false,
    });
    // Predicted candles: hollow with a coloured outline - never confusable with solid actual candles.
    const forecast = chart.addSeries(CandlestickSeries, {
      upColor: 'rgba(16,185,129,0.06)', downColor: 'rgba(239,68,68,0.06)', borderVisible: true,
      borderUpColor: 'rgb(52 211 153)', borderDownColor: 'rgb(248 113 113)',
      wickUpColor: 'rgb(52 211 153)', wickDownColor: 'rgb(248 113 113)', priceLineVisible: false, lastValueVisible: false,
    });
    const edge = (color, style) => chart.addSeries(LineSeries, {
      color, lineWidth: 1, lineStyle: style, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    // The 95% edges are drawn faintly: they also make the price scale include the whole uncertainty fan.
    const hi95 = edge('rgba(96,165,250,0.35)', LineStyle.Dotted);
    const lo95 = edge('rgba(96,165,250,0.35)', LineStyle.Dotted);
    const boundary = new ForecastBoundary();
    const bands = new ForecastBands();
    // Attached to the ACTUAL series: it always has data, so price->pixel conversion works even when the
    // forecast candle series is empty (range-only state).
    actual.attachPrimitive(boundary);
    actual.attachPrimitive(bands);
    api.current = { chart, actual, forecast, hi95, lo95, boundary, bands };
    chart.subscribeCrosshairMove((p) => {
      if (p.time == null || !p.point) { setTip(null); return; }
      const f = forecastBarByTime(respRef.current, p.time);
      if (f) { setTip({ x: p.point.x, y: p.point.y, lines: describeForecastBar(f) }); return; }
      const a = actualRef.current.find((c) => c.time === p.time);
      setTip(a ? { x: p.point.x, y: p.point.y, lines: ['Actual candle (market data)', `${istClock(a.time)}  O ${a.open.toFixed(2)}  H ${a.high.toFixed(2)}  L ${a.low.toFixed(2)}  C ${a.close.toFixed(2)}`] } : null);
    });
    return () => { chart.remove(); api.current = null; };
  }, []);

  useEffect(() => {
    const a = api.current;
    if (!a) return;
    respRef.current = resp;
    const d = buildForecastChart(resp);
    if (!d) {
      a.actual.setData([]); a.forecast.setData([]); a.hi95.setData([]); a.lo95.setData([]);
      a.boundary.setTime(null); a.bands.setData({ 95: [], 80: [], 50: [] }, []);
      actualRef.current = [];
      lastKey.current = null;
      return;
    }
    actualRef.current = d.actual;
    a.actual.setData(d.actual);
    a.forecast.setData(d.candles);
    a.hi95.setData((d.bands[95].length ? d.bands[95] : d.bands[80]).map((p) => ({ time: p.time, value: p.hi })));
    a.lo95.setData((d.bands[95].length ? d.bands[95] : d.bands[80]).map((p) => ({ time: p.time, value: p.lo })));
    a.boundary.setTime(d.origin.time);
    a.bands.setData(d.bands, d.horizons);
    // Re-fit only when a NEW forecast arrives, so a user's zoom/pan isn't reset by each poll.
    if (lastKey.current !== d.key) {
      lastKey.current = d.key;
      a.chart.timeScale().fitContent();
    }
  }, [resp]);

  return (
    <div className="relative w-full h-full">
      <div ref={ref} className="w-full h-full" data-testid="forecast-chart" />
      {tip && (
        <div
          className="pointer-events-none absolute z-10 max-w-[300px] rounded border border-slate-600 bg-slate-900/95 px-2 py-1.5 text-[10px] text-slate-200"
          style={{ left: Math.min(tip.x + 12, (ref.current?.clientWidth || 600) - 310), top: Math.max(tip.y - 40, 0) }}
        >
          {tip.lines.map((l, i) => <div key={i} className={i === 0 ? 'font-semibold text-blue-300' : ''}>{l}</div>)}
        </div>
      )}
    </div>
  );
}

export { IST };
