"use client";

import { CandlestickSeries, ColorType, HistogramSeries, LineSeries, LineStyle, createChart, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { ScanOccurrence } from "./patternScan";

type Bar = [number, number, number, number, number, number]; // t, o, h, l, c, v

const IST = 19800;
// daily bars are stamped at IST midnight: shift to IST before taking the calendar date, or every bar lands a day early
const day = (ts: number): Time => new Date((ts + IST) * 1000).toISOString().slice(0, 10) as Time;
const css = (name: string, fallback: string) =>
  (typeof document !== "undefined" && getComputedStyle(document.documentElement).getPropertyValue(name).trim()) || fallback;

/**
 * TradingView Lightweight Charts candle chart used on the pattern scan cards: candles + volume, the pattern's own
 * drawn lines, and dashed breakout / invalidation levels. Not scrollable or zoomable on purpose (it sits inside a
 * scrolling page); the full interactive chart is one click away on the stock page.
 */
export function TvChart({ bars, occurrence, height = 300 }: { bars: Bar[]; occurrence: ScanOccurrence; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || !bars.length) return;
    const gain = css("--gain", "#10b981");
    const loss = css("--loss", "#ef4444");
    const text = css("--text-tertiary", "#8b8b9a");
    const grid = css("--grid", "rgba(255,255,255,0.06)");
    const chart = createChart(el, {
      width: el.clientWidth,
      height,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: text, fontFamily: "inherit", attributionLogo: false },
      grid: { vertLines: { color: "transparent" }, horzLines: { color: grid } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.22 } },
      timeScale: { borderVisible: false, timeVisible: false, fixLeftEdge: true, fixRightEdge: true },
      handleScroll: false,
      handleScale: false,
      crosshair: { horzLine: { labelVisible: true }, vertLine: { labelVisible: true } },
    });

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: gain, downColor: loss, borderUpColor: gain, borderDownColor: loss, wickUpColor: gain, wickDownColor: loss,
    });
    candles.setData(bars.map(([t, o, h, l, c]) => ({ time: day(t), open: o, high: h, low: l, close: c })));

    const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volume.setData(bars.map(([t, o, , , c, v]) => ({ time: day(t), value: v, color: (c >= o ? gain : loss) + "66" })));

    if (occurrence.breakout != null)
      candles.createPriceLine({ price: occurrence.breakout, color: "#f59e0b", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "Breakout" });
    if (occurrence.invalidation != null)
      candles.createPriceLine({ price: occurrence.invalidation, color: loss, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "Invalid" });

    // the pattern's own lines (neckline, trendlines...), clipped to the visible window
    const t0 = bars[0][0];
    const t1 = bars[bars.length - 1][0];
    for (const ln of occurrence.lines) {
      if (ln.ts1 === ln.ts0) continue;
      const slope = (ln.y1 - ln.y0) / (ln.ts1 - ln.ts0);
      const a = Math.max(ln.ts0, t0);
      const b = Math.min(ln.ts1, t1);
      if (b <= a) continue;
      const ya = ln.y0 + slope * (a - ln.ts0);
      const yb = ln.y0 + slope * (b - ln.ts0);
      const s = chart.addSeries(LineSeries, { color: "#a78bfa", lineWidth: 2, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
      s.setData([{ time: day(a), value: ya }, { time: day(b), value: yb }]);
    }

    chart.timeScale().fitContent();
    const ro = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth }));
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart.remove();
    };
  }, [bars, occurrence, height]);

  return <div ref={ref} style={{ height }} />;
}
