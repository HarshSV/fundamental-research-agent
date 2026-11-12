"use client";

import {
  CandlestickSeries, ColorType, CrosshairMode, HistogramSeries, LineSeries, LineStyle, createChart, createSeriesMarkers,
  type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi, type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { ConePrimitive, type Cone } from "./cone";
import { OUTCOME_COLOR, STATUS_COLOR, markerOf, measuredTarget, type MarkerKind, type PatternOcc } from "./patterns";
import type { Resistance, ScanOccurrence } from "./patternScan";
import type { Candle } from "./PriceChart";

export type ChartStyle = "candles" | "line";

/** What a scanner row says about this stock: its pattern's own lines and levels, and any horizontal resistance. */
export interface ScanOverlay {
  occurrence: ScanOccurrence | null;
  resistance: Resistance | null;
}

const IST = 19800;
const SMA_COLORS: Record<number, string> = { 20: "#f59e0b", 50: "#3b82f6", 100: "#a855f7", 200: "#ec4899" };
const KIND_COLOR: Record<MarkerKind, string> = {
  forming: STATUS_COLOR.forming,
  awaiting: STATUS_COLOR.awaiting_breakout,
  positive: OUTCOME_COLOR.positive,
  negative: OUTCOME_COLOR.negative,
  pending: OUTCOME_COLOR.pending,
  flat: OUTCOME_COLOR.flat,
  not_evaluable: OUTCOME_COLOR.not_evaluable,
  invalidated: STATUS_COLOR.invalidated,
};

// intraday bars go on a seconds axis shifted to IST; daily bars on a calendar-day axis (shifted too, or every bar lands a day early)
const toTime = (ts: number, intraday: boolean): Time =>
  intraday ? ((ts + IST) as UTCTimestamp) : (new Date((ts + IST) * 1000).toISOString().slice(0, 10) as Time);
const after = (a: Time, b: Time) => (typeof a === "number" && typeof b === "number" ? a > b : String(a) > String(b));
const css = (name: string, fallback: string) =>
  (typeof document !== "undefined" && getComputedStyle(document.documentElement).getPropertyValue(name).trim()) || fallback;
const price = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

interface Bar { time: Time; open: number; high: number; low: number; close: number; volume?: number }

/** Strictly ascending, de-duplicated bars (the chart library rejects anything else). Live ticks are kept apart. */
function toBars(cs: Candle[], intraday: boolean) {
  const bars: Bar[] = [];
  const ticks: { time: Time; value: number }[] = [];
  for (const c of cs) {
    const t = toTime(c.time, intraday);
    if (c.tick) {
      if ((!bars.length || after(t, bars[bars.length - 1].time)) && (!ticks.length || after(t, ticks[ticks.length - 1].time))) ticks.push({ time: t, value: c.close });
      continue;
    }
    // old history can carry gaps (a missing price): skip those bars rather than invent a value
    if (![c.open, c.high, c.low, c.close].every((v) => typeof v === "number" && Number.isFinite(v))) continue;
    if (bars.length && !after(t, bars[bars.length - 1].time)) continue;
    bars.push({ time: t, open: c.open, high: c.high, low: c.low, close: c.close, volume: c.volume });
  }
  return { bars, ticks };
}

/**
 * The stock page's price chart: TradingView's Lightweight Charts with candles or a line, optional volume, a hover legend
 * (open / high / low / close), trackpad pinch / scroll-wheel zoom and drag to pan, live updating, pattern markers and, when
 * the stock was opened from a scanner, that scan's pattern lines, levels and horizontal resistance.
 */
export function StockChart({
  candles, dataKey, intraday, chartStyle, showVolume, occs, selectedId, onSelect, scan, levels, cone, averages, history, projectFrom, height = 440,
}: {
  candles: Candle[];
  dataKey: string; // changes when the DATASET changes (range switch), not on live updates: refits the view
  intraday: boolean;
  chartStyle: ChartStyle;
  showVolume: boolean;
  occs: PatternOcc[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  scan?: ScanOverlay | null;
  levels?: { price: number; title: string; color: string; dashed?: boolean }[];
  cone?: Cone | null; // the forecast fan drawn to the right of the last bar (daily charts only)
  averages?: number[]; // simple moving averages to draw, in days (daily charts only)
  history?: Candle[]; // the full daily history the averages are worked out from (the shown range alone is too short for a 200-day average)
  projectFrom?: Cone | null; // when set, each average continues to the right as a dashed line, assuming the price follows the forecast's middle
  height?: number;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | ISeriesApi<"Line"> | null>(null);
  const volRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const extraRef = useRef<{ series: ISeriesApi<"Line">[]; lines: IPriceLine[] }>({ series: [], lines: [] });
  const shownKey = useRef("");
  const counts = useRef({ n: 0, first: "", last: "" });
  const byTime = useRef(new Map<string, Bar>());
  const groups = useRef(new Map<string, PatternOcc[]>());
  const onSelectRef = useRef(onSelect);
  const [hover, setHover] = useState<Bar | null>(null);

  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  const data = useMemo(() => toBars(candles, intraday), [candles, intraday]);
  const dataRef = useRef(data);
  useEffect(() => {
    dataRef.current = data;
  }, [data]);

  // 1. the chart itself (rebuilt only when the time axis kind changes: seconds vs calendar days)
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const chart = createChart(el, {
      width: el.clientWidth,
      height,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: css("--text-tertiary", "#8b8b9a"), fontFamily: "inherit", attributionLogo: false },
      grid: { vertLines: { color: "transparent" }, horzLines: { color: css("--grid", "rgba(255,255,255,0.06)") } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.18 } },
      timeScale: { borderVisible: false, timeVisible: intraday, secondsVisible: false, rightOffset: 6, minBarSpacing: 0.02 },
      crosshair: { mode: CrosshairMode.Normal },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true, axisDoubleClickReset: true },
      kineticScroll: { mouse: false, touch: true },
      localization: { priceFormatter: (p: number) => price(p) },
    });
    chartRef.current = chart;
    chart.subscribeCrosshairMove((p) => setHover(p.time ? byTime.current.get(String(p.time)) ?? null : null));
    chart.subscribeClick((p) => {
      const g = p.time ? groups.current.get(String(p.time)) : undefined;
      if (g?.length) onSelectRef.current(g[0].occ_id);
    });
    const ro = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth }));
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      volRef.current = null;
      markersRef.current = null;
      extraRef.current = { series: [], lines: [] };
      shownKey.current = "";
    };
  }, [intraday, height]);

  // 2. the price series (candles or line) and the volume bars, rebuilt when the style or volume toggles
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const range = chart.timeScale().getVisibleLogicalRange();
    const gain = css("--gain", "#10b981");
    const loss = css("--loss", "#ef4444");
    const { bars, ticks } = dataRef.current;
    const series = chartStyle === "candles"
      ? chart.addSeries(CandlestickSeries, { upColor: gain, downColor: loss, borderUpColor: gain, borderDownColor: loss, wickUpColor: gain, wickDownColor: loss })
      : chart.addSeries(LineSeries, { color: bars.length > 1 && bars[bars.length - 1].close < bars[0].close ? loss : gain, lineWidth: 2, crosshairMarkerRadius: 4 });
    if (chartStyle === "candles") (series as ISeriesApi<"Candlestick">).setData(bars.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
    else (series as ISeriesApi<"Line">).setData([...bars.map((b) => ({ time: b.time, value: b.close })), ...ticks]);
    seriesRef.current = series;
    markersRef.current = createSeriesMarkers(series, []);
    if (showVolume) {
      const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
      chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
      vol.setData(bars.filter((b) => b.volume != null).map((b) => ({ time: b.time, value: b.volume as number, color: (b.close >= b.open ? gain : loss) + "66" })));
      volRef.current = vol;
    }
    if (range) chart.timeScale().setVisibleLogicalRange(range);
    else chart.timeScale().fitContent();
    return () => {
      try {
        chart.removeSeries(series);
        if (volRef.current) chart.removeSeries(volRef.current);
      } catch {
        /* the chart was already torn down */
      }
      seriesRef.current = null;
      volRef.current = null;
      markersRef.current = null;
    };
  }, [intraday, height, chartStyle, showVolume]);

  // 3. data changes: a new range refits the view; a live refresh only touches the newest bars so zoom and position are kept
  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series) return;
    const { bars, ticks } = data;
    byTime.current = new Map(bars.map((b) => [String(b.time), b]));
    const first = String(bars[0]?.time ?? "");
    const last = String(bars[bars.length - 1]?.time ?? "");
    const prev = counts.current;
    const sameWindow = shownKey.current === dataKey && prev.first === first && bars.length >= prev.n && prev.n > 0;
    const put = (b: Bar) => {
      if (chartStyle === "candles") (series as ISeriesApi<"Candlestick">).update({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close });
      else (series as ISeriesApi<"Line">).update({ time: b.time, value: b.close });
      volRef.current?.update({ time: b.time, value: b.volume ?? 0, color: (b.close >= b.open ? css("--gain", "#10b981") : css("--loss", "#ef4444")) + "66" });
    };
    if (sameWindow) {
      for (const b of bars.slice(Math.max(0, prev.n - 1))) put(b);
      if (chartStyle === "line") for (const t of ticks) (series as ISeriesApi<"Line">).update(t);
    } else {
      if (chartStyle === "candles") (series as ISeriesApi<"Candlestick">).setData(bars.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
      else (series as ISeriesApi<"Line">).setData([...bars.map((b) => ({ time: b.time, value: b.close })), ...ticks]);
      volRef.current?.setData(bars.filter((b) => b.volume != null).map((b) => ({ time: b.time, value: b.volume as number, color: (b.close >= b.open ? css("--gain", "#10b981") : css("--loss", "#ef4444")) + "66" })));
      if (shownKey.current !== dataKey || prev.n === 0) chart.timeScale().fitContent();
    }
    if (chartStyle === "line" && bars.length > 1) {
      (series as ISeriesApi<"Line">).applyOptions({ color: bars[bars.length - 1].close < bars[0].close ? css("--loss", "#ef4444") : css("--gain", "#10b981") });
    }
    shownKey.current = dataKey;
    counts.current = { n: bars.length, first, last };
  }, [data, dataKey, chartStyle, showVolume, intraday, height]);

  // 4. overlays: pattern markers, the selected pattern's lines and levels, and the scan's own lines / resistance
  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    const markers = markersRef.current;
    if (!chart || !series || !markers) return;
    for (const s of extraRef.current.series) {
      try {
        chart.removeSeries(s);
      } catch {
        /* already gone */
      }
    }
    for (const l of extraRef.current.lines) {
      try {
        series.removePriceLine(l);
      } catch {
        /* already gone */
      }
    }
    extraRef.current = { series: [], lines: [] };
    const { bars } = data;
    if (!bars.length) {
      markers.setMarkers([]);
      return;
    }
    const tsOf = (b: Bar) => (typeof b.time === "number" ? b.time - IST : Date.parse(`${b.time}T00:00:00Z`) / 1000 - IST);
    const t0 = tsOf(bars[0]);
    const t1 = tsOf(bars[bars.length - 1]);
    const barAtOrAfter = (ts: number) => {
      let lo = 0;
      let hi = bars.length;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (tsOf(bars[mid]) < ts) lo = mid + 1;
        else hi = mid;
      }
      return lo >= bars.length ? null : bars[lo];
    };
    const addLine = (ts0: number, y0: number, ts1: number, y1: number, color: string, width: 1 | 2 | 3 | 4) => {
      if (ts1 === ts0) return;
      const slope = (y1 - y0) / (ts1 - ts0);
      const a = Math.max(ts0, t0);
      const b = Math.min(ts1, t1);
      if (b <= a) return;
      const ln = chart.addSeries(LineSeries, { color, lineWidth: width, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
      ln.setData([{ time: toTime(a, intraday), value: y0 + slope * (a - ts0) }, { time: toTime(b, intraday), value: y0 + slope * (b - ts0) }]);
      extraRef.current.series.push(ln);
    };
    const level = (p: number, color: string, title: string, style: LineStyle = LineStyle.Dashed) =>
      extraRef.current.lines.push(series.createPriceLine({ price: p, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title }));

    // pattern markers from the pattern agent (only the occurrences the page chose to show)
    const g = new Map<string, PatternOcc[]>();
    const rank = (o: PatternOcc) => ({ awaiting_breakout: 0, forming: 1, confirmed: 2, invalidated: 3 }[o.status]);
    for (const o of occs) {
      const bar = barAtOrAfter(markerOf(o).ts);
      if (!bar) continue;
      const k = String(bar.time);
      g.set(k, [...(g.get(k) ?? []), o]);
    }
    groups.current = g;
    const list: SeriesMarker<Time>[] = [];
    const idxOf = new Map(bars.map((b, i) => [String(b.time), i]));
    const nice = (id: string) => id.replace(/-and-/g, " & ").replace(/-/g, " ");
    for (const [k, items] of g) {
      items.sort((a, b) => rank(a) - rank(b));
      const lead = items[0];
      const bearish = lead.direction === "bearish";
      const live = lead.status === "forming" || lead.status === "awaiting_breakout";
      const recent = bars.length - 1 - (idxOf.get(k) ?? 0) <= 90;
      const picked = items.some((o) => o.occ_id === selectedId);
      list.push({
        time: bars.find((b) => String(b.time) === k)?.time as Time,
        position: bearish ? "aboveBar" : "belowBar",
        shape: bearish ? "arrowDown" : "arrowUp",
        // a developing pattern or a recent one is drawn big and solid; an old one small and faded, so what matters stands out
        color: KIND_COLOR[markerOf(lead).kind] + (live || recent || picked ? "" : "66"),
        size: live || picked ? 3 : recent ? 2 : 1,
        text: live ? `${nice(lead.pattern)}${lead.status === "forming" ? " (forming)" : " (waiting)"}` : items.length > 1 ? String(items.length) : "",
      });
    }
    list.sort((a, b) => (after(a.time, b.time) ? 1 : -1));
    markers.setMarkers(list);

    const sel = occs.find((o) => o.occ_id === selectedId);
    if (sel) {
      for (const ln of sel.lines) addLine(ln.ts0, ln.y0, ln.ts1, ln.y1, "#a78bfa", 2);
      if (sel.breakout_level != null) level(sel.breakout_level, "#f59e0b", "Breakout");
      if (sel.invalidation_level != null) level(sel.invalidation_level, css("--loss", "#ef4444"), "Invalid");
    }

    if (scan?.occurrence) {
      for (const ln of scan.occurrence.lines) addLine(ln.ts0, ln.y0, ln.ts1, ln.y1, "#a78bfa", 2);
      if (scan.occurrence.breakout != null) level(scan.occurrence.breakout, "#f59e0b", "Breakout");
      if (scan.occurrence.invalidation != null) level(scan.occurrence.invalidation, css("--loss", "#ef4444"), "Invalid");
    }
    if (scan?.resistance) {
      const r = scan.resistance;
      addLine(Math.max(r.first_ts, t0), r.level, t1, r.level, "#ef4444", 3);
      level(r.level, "#ef4444", `Resistance ×${r.touches}`, LineStyle.Solid);
    }
    // patterns that are developing now are drawn without being picked: their outline, the breakout, where they fail, and the measured-move target
    const last = bars[bars.length - 1].close;
    const developing = occs
      .filter((o) => (o.status === "forming" || o.status === "awaiting_breakout") && o.occ_id !== selectedId && o.breakout_level != null)
      .sort((a, b) => Math.abs((a.breakout_level as number) - last) - Math.abs((b.breakout_level as number) - last))
      .slice(0, 2); // the two nearest the price: more would bury the chart
    for (const o of developing) {
      const col = o.direction === "bearish" ? css("--loss", "#ef4444") : o.direction === "bullish" ? css("--gain", "#10b981") : "#f59e0b";
      for (const ln of o.lines) addLine(ln.ts0, ln.y0, ln.ts1, ln.y1, col, 1);
      const nm = o.pattern.replace(/-and-/g, " & ").replace(/-/g, " ");
      level(o.breakout_level as number, "#f59e0b", `${nm}: ${o.direction === "bearish" ? "breakdown" : "breakout"}`);
      if (o.invalidation_level != null) level(o.invalidation_level, css("--loss", "#ef4444"), `${nm}: fails`);
      const tg = measuredTarget(o);
      if (tg != null) level(tg, col, `${nm}: target (rule)`);
    }
    for (const lv of levels ?? []) level(lv.price, lv.color, lv.title, lv.dashed ? LineStyle.Dashed : LineStyle.Solid);
  }, [data, occs, selectedId, scan, levels, chartStyle, showVolume, intraday, height]);

  // 5. the forecast fan: a primitive on the price series, with room on the right of the last bar for it
  const coneOn = Boolean(cone) && !intraday && data.bars.length > 0;
  const lastIndex = data.bars.length - 1 + (chartStyle === "line" ? data.ticks.length : 0);
  useEffect(() => {
    const chart = chartRef.current;
    const series = seriesRef.current;
    if (!chart || !series || !coneOn || !cone) return;
    const prim = new ConePrimitive();
    series.attachPrimitive(prim);
    const gain = css("--gain", "#10b981");
    const loss = css("--loss", "#ef4444");
    const rgb = cone.tone === "up" ? "16, 185, 129" : cone.tone === "down" ? "239, 68, 68" : "148, 163, 184";
    prim.set(cone, lastIndex, { fill: rgb, text: cone.tone === "up" ? gain : cone.tone === "down" ? loss : css("--text-secondary", "#94a3b8") });
    return () => {
      try {
        series.detachPrimitive(prim);
      } catch {
        /* the series was already removed */
      }
    };
  }, [cone, coneOn, lastIndex, chartStyle, showVolume, intraday, height]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const room = coneOn ? 24 : 6;
    chart.timeScale().applyOptions({ rightOffset: room });
    const r = chart.timeScale().getVisibleLogicalRange();
    if (coneOn && r && r.to < lastIndex + room) chart.timeScale().setVisibleLogicalRange({ from: r.from, to: lastIndex + room });
    // only when the fan appears or the dataset changes: a live tick must not undo the user's panning
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [coneOn, dataKey, intraday, height]);

  // 6. moving averages, and where each would go if the price follows the middle of the forecast
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || intraday || !averages?.length || !history?.length || !data.bars.length) return;
    const hist = toBars(history, false).bars;
    const lastShown = String(data.bars[data.bars.length - 1].time);
    const firstShown = String(data.bars[0].time);
    const upto = hist.filter((b) => String(b.time) <= lastShown);
    if (!upto.length) return;
    const closes = upto.map((b) => b.close);
    const made: ISeriesApi<"Line">[] = [];
    const nextDays = (from: string, n: number) => {
      const out: string[] = [];
      const d = new Date(`${from}T00:00:00Z`);
      while (out.length < n) {
        d.setUTCDate(d.getUTCDate() + 1);
        if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) out.push(d.toISOString().slice(0, 10));
      }
      return out;
    };
    // the price path the projection assumes: a straight line from the last price to the forecast's middle at each horizon
    let path: number[] = [];
    if (projectFrom && projectFrom.points.length) {
      const knots = [{ k: 0, v: projectFrom.anchor }, ...projectFrom.points.map((p) => ({ k: p.k, v: p.mid }))];
      const kMax = knots[knots.length - 1].k;
      for (let k = 1; k <= kMax; k++) {
        const i = knots.findIndex((q) => q.k >= k);
        const a = knots[i - 1];
        const b = knots[i];
        path.push(a.v + ((b.v - a.v) * (k - a.k)) / (b.k - a.k));
      }
    }
    const future = path.length ? nextDays(lastShown, path.length) : [];
    for (const n of averages) {
      if (closes.length < n) continue;
      const color = SMA_COLORS[n] ?? "#94a3b8";
      const pts: { time: Time; value: number }[] = [];
      let sum = 0;
      for (let i = 0; i < closes.length; i++) {
        sum += closes[i];
        if (i >= n) sum -= closes[i - n];
        if (i >= n - 1 && String(upto[i].time) >= firstShown) pts.push({ time: upto[i].time, value: sum / n });
      }
      if (!pts.length) continue;
      const ln = chart.addSeries(LineSeries, { color, lineWidth: 1, title: `SMA ${n}`, priceLineVisible: false, crosshairMarkerVisible: false });
      ln.setData(pts);
      made.push(ln);
      if (path.length) {
        const run = [...closes];
        const proj: { time: Time; value: number }[] = [pts[pts.length - 1]];
        path.forEach((p, k) => {
          run.push(p);
          const tail = run.slice(-n);
          proj.push({ time: future[k] as Time, value: tail.reduce((a, b) => a + b, 0) / n });
        });
        const pl = chart.addSeries(LineSeries, { color, lineWidth: 1, lineStyle: LineStyle.Dashed, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
        pl.setData(proj);
        made.push(pl);
      }
    }
    return () => {
      for (const s of made) {
        try {
          chart.removeSeries(s);
        } catch {
          /* the chart was already torn down */
        }
      }
    };
  }, [averages, history, projectFrom, data, intraday, chartStyle, showVolume, height]);

  const last = data.bars[data.bars.length - 1];
  const shown = hover ?? last ?? null;
  const up = shown ? shown.close >= shown.open : true;
  const tone = up ? "var(--gain)" : "var(--loss)";

  return (
    <div className="relative">
      {shown && (
        <div className="pointer-events-none absolute left-1 top-1 z-10 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs" style={{ color: "var(--text-tertiary)" }}>
          <span className="font-medium" style={{ color: "var(--text-secondary)" }}>Price</span>
          {chartStyle === "candles" ? (
            <>
              <span>O <b className="nv-num" style={{ color: tone }}>{price(shown.open)}</b></span>
              <span>H <b className="nv-num" style={{ color: tone }}>{price(shown.high)}</b></span>
              <span>L <b className="nv-num" style={{ color: tone }}>{price(shown.low)}</b></span>
              <span>C <b className="nv-num" style={{ color: tone }}>{price(shown.close)}</b></span>
            </>
          ) : (
            <b className="nv-num" style={{ color: tone }}>{price(shown.close)}</b>
          )}
        </div>
      )}
      <div ref={boxRef} style={{ height }} />
    </div>
  );
}
