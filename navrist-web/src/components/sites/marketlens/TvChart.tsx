"use client";

import { CandlestickSeries, ColorType, HistogramSeries, LineSeries, LineStyle, createChart, createSeriesMarkers, type SeriesMarker, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { ChartLine, Resistance, ScanOccurrence, SetupLevel } from "./patternScan";
import { removeChartSafely } from "./chartDispose";

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
export function TvChart({
  bars, occurrence, resistance, height = 300, marks, lines, levels,
}: {
  bars: Bar[]; occurrence: ScanOccurrence | null; resistance?: Resistance | null; height?: number; marks?: { t: number; label: string }[];
  lines?: { fast?: ChartLine; slow?: ChartLine; vol?: ChartLine }; levels?: SetupLevel[];
}) {
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
      timeScale: { borderVisible: false, timeVisible: false, fixLeftEdge: true, fixRightEdge: false },
      // touch: pinch to zoom, drag sideways to move along the chart (a vertical drag still scrolls the page); mouse: drag to move, drag the time axis to zoom.
      // The mouse wheel is left to scroll the page; a trackpad pinch (a wheel event with ctrl) zooms, below.
      handleScroll: { pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false, mouseWheel: false },
      handleScale: { pinch: true, mouseWheel: false, axisPressedMouseMove: { time: true, price: false }, axisDoubleClickReset: { time: true, price: false } },
      crosshair: { horzLine: { labelVisible: true }, vertLine: { labelVisible: true } },
    });

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: gain, downColor: loss, borderUpColor: gain, borderDownColor: loss, wickUpColor: gain, wickDownColor: loss,
    });
    candles.setData(bars.map(([t, o, h, l, c]) => ({ time: day(t), open: o, high: h, low: l, close: c })));

    const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volume.setData(bars.map(([t, o, , , c, v]) => ({ time: day(t), value: v, color: (c >= o ? gain : loss) + "66" })));

    if (occurrence?.breakout != null)
      candles.createPriceLine({ price: occurrence.breakout, color: "#f59e0b", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "Breakout" });
    if (occurrence?.invalidation != null)
      candles.createPriceLine({ price: occurrence.invalidation, color: loss, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "Invalid" });

    // the pattern's own lines (neckline, trendlines...), clipped to the visible window
    const t0 = bars[0][0];
    const t1 = bars[bars.length - 1][0];
    for (const ln of occurrence?.lines ?? []) {
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

    // horizontal resistance: a solid red line across the chart at the level the highs keep failing at
    if (resistance) {
      const from = Math.max(resistance.first_ts, t0);
      if (t1 > from) {
        const line = chart.addSeries(LineSeries, { color: "#ef4444", lineWidth: 3, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
        line.setData([{ time: day(from), value: resistance.level }, { time: day(t1), value: resistance.level }]);
        candles.createPriceLine({ price: resistance.level, color: "#ef4444", lineWidth: 1, lineStyle: LineStyle.Solid, axisLabelVisible: true, title: `Resistance ×${resistance.touches}` });
      }
    }

    // moving averages (MarketSmith-style: 50 / 200 day, or 10 / 40 week) and the volume's own average, each only where it is really worked out
    const ma = (l: ChartLine | undefined, color: string, scale?: string) => {
      if (!l || l.pts.length < 2) return;
      const s = chart.addSeries(LineSeries, { color, lineWidth: scale ? 1 : 2, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false, ...(scale ? { priceScaleId: scale } : {}) });
      s.setData(l.pts.map(([t, v]) => ({ time: day(t), value: v })));
    };
    ma(lines?.slow, "#d4a72c");
    ma(lines?.fast, "#f0613d");
    ma(lines?.vol, "#f59e0b", "vol");

    // the levels the setup is about, as real lines from the bar they start at to the last bar
    const lastT = bars[bars.length - 1][0];
    for (const lv of levels ?? []) {
      const from = Math.max(lv.t0 ?? bars[0][0], bars[0][0]);
      if (lastT <= from) continue;
      const hi = /high|breakout/i.test(lv.label);
      const ln = chart.addSeries(LineSeries, { color: hi ? gain : loss, lineWidth: 2, lineStyle: LineStyle.Dashed, lastValueVisible: true, priceLineVisible: false, crosshairMarkerVisible: false, title: lv.label });
      ln.setData([{ time: day(from), value: lv.price }, { time: day(lastT), value: lv.price }]);
    }

    // the bars a setup scanner is about (the mother and inside bar of an inside bar, the closes of a tight setup): a dot under each, labelled;
    // and the highest high / lowest low shown, with their prices (as MarketSmith labels its swing points)
    const have = new Set(bars.map((b) => b[0]));
    const flags: SeriesMarker<Time>[] = (marks ?? []).filter((m) => have.has(m.t)).map((m) => ({ time: day(m.t), position: m.label === "Inside" ? "aboveBar" : "belowBar", shape: "circle", color: "#a78bfa", text: m.label || undefined }));
    const priceText = (v: number) => v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
    let hiBar = bars[0], loBar = bars[0];
    for (const b of bars) {
      if (b[2] > hiBar[2]) hiBar = b;
      if (b[3] < loBar[3]) loBar = b;
    }
    flags.push({ time: day(hiBar[0]), position: "aboveBar", shape: "square", color: text, size: 0.1, text: priceText(hiBar[2]) });
    flags.push({ time: day(loBar[0]), position: "belowBar", shape: "square", color: text, size: 0.1, text: priceText(loBar[3]) });
    if (flags.length) createSeriesMarkers(candles, flags.sort((a, b) => String(a.time).localeCompare(String(b.time))));

    // all the bars, with a little room after the last one so its label ("Inside", "Mother") is not cut off
    // all the bars, with a little room after the last one so its label ("Inside", "Mother") is not cut off; double-click the chart to come back to this view
    const showAll = () => {
      if (flags.length) chart.timeScale().setVisibleLogicalRange({ from: -0.5, to: bars.length - 1 + Math.max(3, Math.round(bars.length * 0.04)) });
      else chart.timeScale().fitContent();
    };
    showAll();
    // trackpad pinch arrives as a wheel event with ctrl held: zoom towards the latest bars (never closer than 6 bars)
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      const r = chart.timeScale().getVisibleLogicalRange();
      if (!r) return;
      // anchored at the right edge: the setup is on the latest bars
      const width = Math.min(bars.length * 1.5, Math.max(6, (r.to - r.from) * Math.exp(e.deltaY * 0.01)));
      chart.timeScale().setVisibleLogicalRange({ from: r.to - width, to: r.to });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("dblclick", showAll);
    // a resize callback already queued when the chart is removed would touch a disposed chart ("Object is disposed")
    let gone = false;
    const ro = new ResizeObserver(() => {
      if (!gone) chart.applyOptions({ width: el.clientWidth });
    });
    ro.observe(el);
    return () => {
      gone = true;
      ro.disconnect();
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("dblclick", showAll);
      removeChartSafely(chart);
    };
  }, [bars, occurrence, resistance, height, marks, lines, levels]);

  return <div ref={ref} style={{ height }} />;
}
