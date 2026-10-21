import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts';
import { inr, signedPct, toneClass, isNum } from '../lib/format.js';
import { fetchLiveChartCandles, fetchLiveChartLatest, fetchLiveChartDay, fetchChartForecast } from '../lib/api.js';
import { analyzeCandles } from '../lib/technicalAnalysis.js';
import { runDetectors, PATTERN_REGISTRY, registryById } from '../lib/patternRegistry.js';
import { patternStatus } from '../lib/patternStatus.js';
import { stampEvent } from '../lib/eventModel.js';
import { computeHigherTimeframeEvents } from '../lib/htfEvents.js';
import { IST, istDate, todayISO, istClock, fmtDate, fmtTime, fmtDayMonth } from '../lib/marketTime.js';
import { replayDayEvents, sortNewestFirst } from '../lib/eventReplay.js';
import { latestOccurrence, collapseRuns, runFirstMap } from '../lib/patternCatalog.js';
import { RangeBox } from '../lib/rangeBoxPrimitive.js';
import { FlagLayer } from '../lib/flagPrimitive.js';
import { lastYearWindow, shiftEventsToWindow, clusterByScreen, FLAG_STYLE, HIDDEN_BY_DEFAULT } from '../lib/flagClusters.js';
import { ZoneOverlay } from '../lib/zoneOverlayPrimitive.js';
import { detectOrderBlocks, deriveSessionMeta, closedBars, zoneEvents, currentZones } from '../lib/orderBlocks.js';
import ForecastPanel from '../components/ForecastPanel.jsx';
import PatternOutcomePanel from '../components/PatternOutcomePanel.jsx';
import { completedDaily, completedWeekly } from '../lib/htfEvents.js';
import { fullHistoryEvents, toOccurrences, statsForPattern, evaluateEvent, intradaySeries } from '../lib/patternHistory.js';
import { BIAS_STYLE, COUNT_DEFINITION, OUTCOME_STYLE, CHART_OUTCOME_COLOR, biasGlyph, chipTitle, outcomeBadge, primaryOutcome, flagTipLines, setIntradayBarSeconds } from '../lib/patternOutcomeView.js';
import { mergeConfig } from '../lib/patternOutcomes.js';
import { biasText } from '../lib/patternClassification.js';
import OrderBlockCard from '../components/OrderBlockCard.jsx';

const KIND_LABEL = {
  momentum: 'Momentum', volatility: 'Volatility', volume: 'Volume',
  candlestick: 'Candlestick', structure: 'Structure', breakout: 'Breakout',
  pattern: 'Pattern',
};

// Polling cadence for "live" updates. yfinance has no push feed - this is a
// stand-in until Axis Direct's RAPID API (or ICICI Breeze) WebSocket feed
// is provisioned, at which point this polling loop is replaced by a
// persistent socket and the interval below goes away entirely.
const POLL_MS = 5000;

const INTERVALS = [
  { key: '1d', label: '1D' },
  { key: '1m', label: '1m' },
  { key: '5m', label: '5m' },
  { key: '15m', label: '15m' },
  { key: '60m', label: '1h' },
];

// Realised-outcome badges (green/red/grey/pending) for one evaluated formation, one per configured horizon.
function OutcomeChips({ res, tf }) {
  if (!res || !res.outcomes) return <span className="mt-0.5 block text-[10px] italic text-slate-500">Outcome unavailable</span>;
  return (
    <span className="mt-0.5 flex flex-wrap gap-1" data-testid="popover-outcomes">
      {Object.entries(res.outcomes).map(([h, x]) => {
        const b = outcomeBadge(x, tf, Number(h));
        return <span key={h} title={b.title} data-testid={`pop-outcome-${b.state}`} className={`rounded px-1.5 py-px text-[10px] nv-num ${b.chip}`}>{b.text}</span>;
      })}
    </span>
  );
}

// Small flag icon matching the chart flags (pointer up = below the candle, pointer down = above it).
function FlagIcon({ color, up }) {
  const d = up ? 'M1.5 6.5 H5.5 L7 3 L8.5 6.5 H12.5 V13.5 H1.5 Z' : 'M1.5 2.5 H12.5 V9.5 H8.5 L7 13 L5.5 9.5 H1.5 Z';
  return (
    <svg width="14" height="16" viewBox="0 0 14 16" className="mr-1 inline-block align-middle" aria-hidden="true">
      <path d={d} fill={color} stroke="rgba(15,23,42,0.9)" strokeLinejoin="round" />
    </svg>
  );
}

// Colour key shared by the chart legend and the cluster popup. Flag colour AND side = realised outcome at the first horizon.
function OutcomeLegend({ compact = false, showNeutral = false, onToggleNeutral = null }) {
  const item = (st, text, up) => <span className="mr-3 whitespace-nowrap"><FlagIcon color={FLAG_STYLE[st].fill} up={up} />{text}</span>;
  return (
    <div className="text-[10px] text-slate-400" data-testid="outcome-legend">
      {item('positive', 'Positive (below candle, points up)', true)}
      {item('negative', 'Negative (above candle, points down)', false)}
      {item('pending', 'Pending (horizon not complete - not Flat)', true)}
      {item('flat', 'Flat', false)}
      {item('not_evaluable', 'Unavailable', false)}
      {onToggleNeutral && (
        <label className="mr-3 cursor-pointer whitespace-nowrap text-slate-300">
          <input type="checkbox" className="mr-1 align-middle" checked={showNeutral} onChange={(e) => onToggleNeutral(e.target.checked)} data-testid="toggle-neutral-flags" />
          Show flat &amp; unavailable flags
        </label>
      )}
      <div className="text-slate-500">
        {compact ? 'Realised price move after detection, first horizon.' : 'Flag colour and side = realised price move after the pattern was first detected, at the first horizon (5 bars of the pattern\u2019s own timeframe) vs a volatility-based flat band - not the bullish/bearish bias. A number = several patterns with the same outcome nearby; click it to list each one. Flat and unavailable flags are hidden by default (the occurrences are kept).'}
      </div>
    </div>
  );
}

const NO_EVENTS = [];

function EventRow({ e, onOpen, outcome }) {
  const isPattern = e.kind === 'pattern' && !!outcome;
  return (
    <div
      className={`flex items-start gap-2 text-[12px] flex-wrap ${onOpen ? 'cursor-pointer hover:bg-slate-800/60 rounded' : ''}`}
      onClick={onOpen || undefined}
      data-testid={onOpen ? 'ob-feed-row' : undefined}
    >
      {/* Pattern rows: neutral dot (bias is NOT an outcome). Other signals keep their tone dot. */}
      <span className={`mt-1 w-1.5 h-1.5 rounded-full flex-shrink-0 ${isPattern ? 'bg-slate-500' : e.tone === 'pos' ? 'bg-emerald-500' : e.tone === 'neg' ? 'bg-red-500' : 'bg-slate-500'}`} />
      <span className="text-slate-500 flex-shrink-0 nv-num">
        {e.timeframe && e.timeframe !== 'intraday'
          ? `${fmtDayMonth(e.time)} (${e.timeframe})`
          : istClock(e.time)}
      </span>
      <span className="text-slate-500 flex-shrink-0">{KIND_LABEL[e.kind] || e.kind}</span>
      <span className={isPattern ? 'text-slate-300' : toneClass(e.tone)}>{e.text}</span>
      {isPattern && (
        <>
          <span className={`flex-shrink-0 ${BIAS_STYLE[outcome.classification.bias].text}`} title={`${outcome.classification.basis}. Conventional expectation, not an outcome.`} data-testid="row-bias">
            {BIAS_STYLE[outcome.classification.bias].glyph} {biasText(outcome.classification)}
          </span>
          {Object.entries(outcome.outcomes).map(([h, x]) => {
            const b = outcomeBadge(x, e.timeframe || 'intraday', Number(h));
            return <span key={h} title={b.title} className={`flex-shrink-0 rounded px-1.5 py-px nv-num ${b.chip}`} data-testid={`row-outcome-${b.state}`}>{b.text}</span>;
          })}
        </>
      )}
    </div>
  );
}

export default function LiveChart({ symbol, name }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const [interval, setInterval_] = useState('1d'); // default: the last year of daily candles
  const [latest, setLatest] = useState(null);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);
  const [events, setEvents] = useState([]);
  const flagRef = useRef(null);
  const [showNeutralFlags, setShowNeutralFlags] = useState(false); // flat / unavailable flags are hidden by default
  const [showPatterns, setShowPatterns] = useState(false);
  const [tip, setTip] = useState(null); // hover tooltip: { x, y, lines }
  const [popover, setPopover] = useState(null); // open cluster list: { groupId, events, x, y }
  const [expanded, setExpanded] = useState({}); // pattern name -> occurrences list open
  const [focus, setFocus] = useState(null); // the one detection picked from a cluster
  const popoverRef = useRef(null);
  const groupsByIdRef = useRef(new Map());
  const displayCandlesRef = useRef([]);
  const rangeBoxRef = useRef(null);
  const zoneRef = useRef(null);
  const [showOb, setShowOb] = useState(false); // order-block overlay: default off, existing behaviour unchanged
  const [showLiq, setShowLiq] = useState(true);
  const [obCardId, setObCardId] = useState(null);
  const [narrow, setNarrow] = useState(typeof window !== 'undefined' && window.innerWidth < 640);
  const [warmupBars, setWarmupBars] = useState([]);
  const [visRange, setVisRange] = useState(null); // visible logical (bar-index) range
  const lastFitKeyRef = useRef('');
  // Forecast (backend-driven) lives in its OWN panel beside the live chart; the live chart shows actual candles only.
  const [showForecast, setShowForecast] = useState(false); // default: LIVE only
  const [forecastResp, setForecastResp] = useState(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [forecastError, setForecastError] = useState(null); // why the last request failed (HTTP status / network / session)
  const seenRef = useRef(new Set()); // "time|text" keys already logged, so re-polling the same closed candle doesn't duplicate an event

  // Day History: replays a single past trading day's 9:15-3:30 candles
  // through the same detectors as the live feed, so "what happened all
  // day" isn't limited to whatever's still in the rolling live window.
  const [historyDate, setHistoryDate] = useState(todayISO());
  const [historyEvents, setHistoryEvents] = useState(null); // null = not loaded yet
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyUnavailable, setHistoryUnavailable] = useState(false);
  // 'live' = rolling polled window on the chart; 'history' = the loaded
  // day's bars. The two datasets are never mixed.
  const [mode, setMode] = useState('live');
  const [liveCandles, setLiveCandles] = useState([]);
  const [historyCandles, setHistoryCandles] = useState([]);
  const [warmupLen, setWarmupLen] = useState(0); // prior-session bars fed to the day replay's detectors
  // Daily / weekly history for the base & weekly detectors (loaded once per symbol).
  const [dailyBars, setDailyBars] = useState([]);
  const [weeklyBars, setWeeklyBars] = useState([]);
  const [htfStatus, setHtfStatus] = useState({ daily: 'loading', weekly: 'loading' });
  const [loadedDate, setLoadedDate] = useState(null);
  const [selected, setSelected] = useState('all'); // pattern type slug or 'all'

  const loadHistory = (date) => {
    if (!symbol || !date) return;
    setHistoryLoading(true);
    setHistoryUnavailable(false);
    setHistoryEvents(null);
    fetchLiveChartDay(symbol, date, '5m').then((resp) => {
      setHistoryLoading(false);
      const candles = resp && resp.candles;
      if (!candles || !candles.length) {
        setHistoryUnavailable(true);
        return;
      }
      // `candles` is the display session; `warmup` (prior sessions) only
      // feeds the detectors so indicators are warm from the 09:15 open.
      const warmup = (resp.warmup || []).filter((c) => c.time < candles[0].time);
      setHistoryEvents(replayDayEvents([...warmup, ...candles], { sessionStart: warmup.length }));
      setHistoryCandles(candles);
      setWarmupLen(warmup.length);
      setWarmupBars(warmup);
      // One canonical session_date: the IST date of the loaded bars themselves.
      const sessionDate = istDate(candles[0].time);
      setLoadedDate(sessionDate);
      setHistoryDate(sessionDate);
      setMode('history');
    });
  };

  // Create the chart once per mount.
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: 'rgb(148 163 184)',
      },
      grid: {
        vertLines: { color: 'rgba(148,163,184,0.08)' },
        horzLines: { color: 'rgba(148,163,184,0.08)' },
      },
      rightPriceScale: { borderColor: 'rgba(148,163,184,0.15)' },
      // lightweight-charts formats unix times as UTC by default; pin to IST.
      localization: {
        timeFormatter: (t) => `${new Date(t * 1000).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: IST })} ${istClock(t, { hour12: false })}`,
      },
      timeScale: {
        borderColor: 'rgba(148,163,184,0.15)', timeVisible: true, secondsVisible: false,
        tickMarkFormatter: (t, type) => (type >= 3
          ? istClock(t, { hour12: false })
          : new Date(t * 1000).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: IST })),
      },
      autoSize: true,
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: 'rgb(16 185 129)',
      downColor: 'rgb(239 68 68)',
      borderVisible: false,
      wickUpColor: 'rgb(16 185 129)',
      wickDownColor: 'rgb(239 68 68)',
    });
    chartRef.current = chart;
    seriesRef.current = series;
    flagRef.current = new FlagLayer();
    series.attachPrimitive(flagRef.current);
    rangeBoxRef.current = new RangeBox();
    series.attachPrimitive(rangeBoxRef.current);
    zoneRef.current = new ZoneOverlay();
    series.attachPrimitive(zoneRef.current);
    chart.timeScale().subscribeVisibleLogicalRangeChange((r) => {
      setVisRange(r ? { from: Math.floor(r.from), to: Math.ceil(r.to) } : null);
    });
    // Flags are drawn by FlagLayer (canvas), so hit-testing uses the geometry of the last paint.
    const flagAt = (pt) => {
      const id = pt && flagRef.current ? flagRef.current.hitTest(pt.x, pt.y) : null;
      return id ? groupsByIdRef.current.get(id) || null : null;
    };
    chart.subscribeCrosshairMove((param) => {
      const g = flagAt(param.point);
      const overZone = !g && param.point && zoneRef.current ? zoneRef.current.hitTest(param.point.x, param.point.y) : null;
      if (containerRef.current) containerRef.current.style.cursor = g || overZone ? 'pointer' : '';
      setTip(g && param.point ? { x: param.point.x, y: param.point.y, lines: g.tipLines } : null);
    });
    chart.subscribeClick((param) => {
      if (!param.point) return;
      const g = flagAt(param.point);
      if (!g) {
        const zid = zoneRef.current ? zoneRef.current.hitTest(param.point.x, param.point.y) : null;
        if (zid) setObCardId(zid);
        return;
      }
      if (g.events.length === 1) {
        setFocus(g.events[0]);
        setPopover(null);
      } else {
        setExpanded({});
        setPopover({ groupId: g.id, events: g.events, x: param.point.x, y: param.point.y });
      }
    });
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      flagRef.current = null;
      rangeBoxRef.current = null;
      zoneRef.current = null;
    };
  }, []);

  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < 640);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  // Runs the technical-analysis pass over a freshly-fetched candle series
  // and appends only events for closed bars not already logged, so
  // re-polling the same unchanged history doesn't spam duplicates.
  const applyCandles = (candles) => {
    // Only update state when something actually changed, so the pattern
    // detection memo below isn't re-run on every identical poll.
    setLiveCandles((prev) => {
      const a = prev[prev.length - 1], b = candles[candles.length - 1];
      const same = prev.length === candles.length && a && b
        && a.time === b.time && a.close === b.close && a.high === b.high && a.low === b.low && a.volume === b.volume;
      return same ? prev : candles;
    });
    const evalBar = candles[candles.length - 1];
    const now = Date.now() / 1000;
    const found = [...analyzeCandles(candles), ...runDetectors('intraday', candles)]
      .map((e) => ({ ...stampEvent(e, evalBar, now), receivedAt: now }));
    const fresh = found.filter((e) => {
      const key = `${e.time}|${e.text}`;
      if (seenRef.current.has(key)) return false;
      seenRef.current.add(key);
      return true;
    });
    if (fresh.length) {
      // Globally ordered by candle time (newest first) before trimming, so the
      // cap keeps the 100 most recent events, not the 100 most recently appended.
      setEvents((prev) => sortNewestFirst([...prev, ...fresh]).slice(0, 100));
    }
  };

  // Load candle history whenever symbol/interval changes, and poll for
  // fresh candles + the ticker on the same cadence thereafter. yfinance
  // has no push feed, so "live" event detection here means re-fetching
  // and diffing - swap target once Axis/ICICI is connected.
  useEffect(() => {
    if (!symbol) return;
    let cancelled = false;
    setLoading(true);
    setUnavailable(false);
    setLatest(null); // never show the previous company's price while the new one loads
    setEvents([]);
    setLiveCandles([]);
    setMode('live');
    seenRef.current = new Set();

    const loadCandles = (isFirst) => {
      if (interval === '1d') return;       // 1D renders the daily history loaded below, refreshed once a minute
      fetchLiveChartCandles(symbol, interval).then((resp) => {
        if (cancelled) return;
        if (isFirst) setLoading(false);
        const candles = resp && resp.candles;
        if (!candles || !candles.length) {
          if (isFirst) setUnavailable(true);
          return;
        }
        applyCandles(candles);
      });
    };
    const loadLatest = () => {
      fetchLiveChartLatest(symbol).then((resp) => {
        if (!cancelled && resp && isNum(resp.ltp)) setLatest(resp);
      });
    };

    if (interval === '1d') setLoading(false);
    loadCandles(true);
    loadLatest();
    const id = window.setInterval(() => { loadCandles(false); loadLatest(); }, POLL_MS);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [symbol, interval]);

  // Forecast: fetched from the backend (all ML stays server-side). Only while the split view is open, live 5m.
  const forecastView = showForecast && mode === 'live' && interval === '5m';
  useEffect(() => {
    setForecastResp(null); // never show the previous symbol's forecast
    if (!symbol || !forecastView) return undefined;
    let cancelled = false;
    setForecastLoading(true);
    let timer = null;
    let failures = 0;
    // Re-poll quickly while the backend reports it is still fetching the latest candle (or the request failed,
    // e.g. a server reload); slowly otherwise. Failures back off 4s -> 8s -> 16s and then heal on their own.
    const load = () => fetchChartForecast(symbol, true).then((resp) => {
      if (cancelled) return;
      setForecastLoading(false);
      if (resp && resp.clientError) {
        failures += 1;
        setForecastError(resp.clientError);
        setForecastResp(null);
        timer = window.setTimeout(load, Math.min(16000, 2000 * 2 ** failures));
        return;
      }
      failures = 0;
      setForecastError(null);
      setForecastResp(resp);
      timer = window.setTimeout(load, resp && resp.refreshing ? 4000 : 20000);
    });
    load();
    return () => { cancelled = true; if (timer) window.clearTimeout(timer); };
  }, [symbol, forecastView]);

  // Symbol changed: drop the previous symbol's history + filter.
  useEffect(() => {
    setHistoryEvents(null);
    setHistoryCandles([]);
    setHistoryUnavailable(false);
    setLoadedDate(null);
    setSelected('all');
  }, [symbol]);

  // Daily + weekly history for the base / weekly detectors: loaded once per
  // symbol (not in the 5s poll loop), 5y so the long-lookback detectors have
  // their warm-up and a young listing's real start date is visible.
  useEffect(() => {
    if (!symbol) return undefined;
    let cancelled = false;
    setHtfStatus({ daily: 'loading', weekly: 'loading' });
    setDailyBars([]);
    setWeeklyBars([]);
    const load = (interval, setter, key) => fetchLiveChartCandles(symbol, interval, '5y').then((resp) => {
      if (cancelled) return;
      const c = resp && resp.candles;
      if (c && c.length) {
        setter(c);
        setHtfStatus((s) => ({ ...s, [key]: 'ok' }));
      } else {
        setHtfStatus((s) => ({ ...s, [key]: 'failed' }));
      }
    });
    load('1d', setDailyBars, 'daily');
    load('1wk', setWeeklyBars, 'weekly');
    return () => { cancelled = true; };
  }, [symbol]);

  // 1D view: refresh the daily series once a minute so the forming candle follows the live session.
  useEffect(() => {
    if (!symbol || interval !== '1d') return undefined;
    let cancelled = false;
    const id = window.setInterval(() => {
      fetchLiveChartCandles(symbol, '1d', '5y').then((resp) => {
        const c = resp && resp.candles;
        if (cancelled || !c || !c.length) return;
        setDailyBars((prev) => {
          const a = prev[prev.length - 1], b = c[c.length - 1];
          const same = prev.length === c.length && a && b && a.time === b.time && a.close === b.close && a.high === b.high && a.low === b.low;
          return same ? prev : c;
        });
      });
    }, 60000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [symbol, interval]);

  // Default view = the last ~12 months of REAL daily candles (whatever exists if the listing is younger; nothing is padded).
  const dailyView = mode === 'live' && interval === '1d';
  const oneYear = useMemo(() => (dailyView ? lastYearWindow(dailyBars, Date.now() / 1000) : { bars: [], from: 0, complete: false }), [dailyView, dailyBars]);
  const displayCandles = mode === 'history' ? historyCandles : dailyView ? oneYear.bars : liveCandles;

  // Chart data follows the active mode.
  useEffect(() => {
    if (!seriesRef.current) return;
    seriesRef.current.setData(displayCandles.map((c) => ({
      time: c.time, open: c.open, high: c.high, low: c.low, close: c.close,
    })));
    const key = `${mode}|${symbol}|${mode === 'history' ? loadedDate : interval}`;
    if (displayCandles.length && lastFitKeyRef.current !== key) {
      lastFitKeyRef.current = key;
      chartRef.current?.timeScale().fitContent();
    }
  }, [displayCandles, mode, symbol, interval, loadedDate]);

  // Shared detection model. History: the loaded day's replayed events.
  // Live: the same detectors replayed over the current rolling window.
  // Chip counts need the detections whether or not markers are shown, so this
  // always runs - but only when a bar is added/rolled (the replay is O(n^2)),
  // not on every intra-bar tick.
  const liveCandlesRef = useRef(liveCandles);
  liveCandlesRef.current = liveCandles;
  const liveLast = liveCandles.length ? liveCandles[liveCandles.length - 1].time : 0;
  const livePatternEvents = useMemo(
    () => (mode === 'live' ? replayDayEvents(liveCandlesRef.current, { patternsOnly: true }) : []),
    [mode, liveCandles.length, liveLast],
  );
  // Daily / weekly detections, computed on their own timeframe and placed on a
  // real bar of the loaded intraday dataset (live window or the loaded day).
  const dailyLoading = dailyView && htfStatus.daily === 'loading';
  const displayLast = displayCandles.length ? displayCandles[displayCandles.length - 1].time : 0;
  const htfEvents = useMemo(
    () => (dailyView ? [] : computeHigherTimeframeEvents({ dailyBars, weeklyBars, intradayCandles: displayCandles })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [dailyBars, weeklyBars, mode, loadedDate, displayCandles.length, displayLast, dailyView],
  );
  // 1D view: daily detectors over the FULL daily history (warm-up), shown on the last-year bars. srcIndex keeps pointing at the
  // full series so realised outcomes are measured from the original detection bar.
  const dailyFull = useMemo(() => (dailyView && dailyBars.length ? fullHistoryEvents({ dailyBars, weeklyBars: [] }) : null), [dailyView, dailyBars]);
  const dailyViewEvents = useMemo(() => (dailyFull ? shiftEventsToWindow(dailyFull.daily.events, oneYear.from, oneYear.bars) : NO_EVENTS), [dailyFull, oneYear]);
  // Order blocks: one deterministic forward pass over CLOSED 5m bars (orderBlocks.js). Recomputed only when a
  // bar is added/rolled or the 5-minute clock boundary passes (the forming bar closes) - never on intra-bar ticks.
  const obAvailable = mode === 'history' || interval === '5m';
  const barBoundary = Math.floor(Date.now() / 300000);
  const ob = useMemo(() => {
    if (!showOb || !obAvailable) return null;
    const nowSec = Date.now() / 1000;
    const hist = mode === 'history';
    const bars = hist ? [...warmupBars, ...historyCandles] : liveCandlesRef.current;
    if (!bars.length) return null;
    const offset = hist ? warmupBars.length : 0;
    const meta = deriveSessionMeta(bars, { nowSec, date: hist ? loadedDate : null });
    const zones = detectOrderBlocks(bars, meta);
    const closed = closedBars(bars, nowSec);
    const events = zoneEvents(zones, closed).map((e) => ({
      ...stampEvent(e, { time: e.confirmedAt }),
      barIndex: e.barIndex - offset, startIndex: e.startIndex - offset, endIndex: e.endIndex - offset,
    }));
    return { zones, events, offset, current: currentZones(zones) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showOb, obAvailable, mode, loadedDate, warmupBars, historyCandles, liveCandles.length, liveLast, barBoundary]);
  const obEvents = ob ? ob.events : NO_EVENTS;
  const obCard = ob && obCardId ? ob.zones.find((z) => z.id === obCardId) || null : null;

  const patternEvents = useMemo(() => {
    if (dailyView) return dailyViewEvents;
    const src = mode === 'history' ? (historyEvents || []) : livePatternEvents;
    return [...src.filter((e) => e.kind === 'pattern'), ...htfEvents, ...obEvents];
  }, [mode, historyEvents, livePatternEvents, htfEvents, obEvents, dailyView, dailyViewEvents]);

  const patternCounts = useMemo(() => {
    const m = new Map();
    collapseRuns(patternEvents).forEach((e) => m.set(e.patternType, (m.get(e.patternType) || 0) + 1));
    return m;
  }, [patternEvents]);
  const statusCtx = {
    counts: patternCounts,
    barCounts: { intraday: mode === 'history' ? historyCandles.length + warmupLen : liveCandles.length, daily: dailyBars.length, weekly: weeklyBars.length },
    history: htfStatus,
  };
  const selectedEntry = registryById.get(selected);
  const selectedStatus = selectedEntry ? patternStatus(selectedEntry, statusCtx) : null;
  const selectedLabel = selectedEntry?.displayName;

  // ---- Realised outcomes (calculated from candles AFTER detection; kept separate from the conventional bias) ----------
  // Outcome horizons are counted in bars of the CHART's own intraday interval (history days are always 5-minute bars).
  const outcomeBarSec = mode === 'history' ? 300 : ({ '1m': 60, '5m': 300, '15m': 900, '60m': 3600 }[interval] || 300);
  setIntradayBarSeconds(outcomeBarSec);
  const outcomeCfg = useMemo(() => mergeConfig({ barSeconds: { intraday: outcomeBarSec } }), [outcomeBarSec]);
  const outcomeClock = barBoundary; // pending / closed-bar states refresh once per 5-minute boundary, not on every tick
  const intradayOutcomeSeries = useMemo(
    () => intradaySeries(mode === 'history' ? [...warmupBars, ...historyCandles] : liveCandlesRef.current, outcomeCfg, Date.now() / 1000),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mode, warmupBars, historyCandles, liveCandles.length, liveLast, outcomeClock, outcomeCfg],
  );
  const dailyOutcomeSeries = useMemo(() => completedDaily(dailyBars, Date.now() / 1000), [dailyBars, outcomeClock]); // eslint-disable-line react-hooks/exhaustive-deps
  const weeklyOutcomeSeries = useMemo(() => completedWeekly(weeklyBars, Date.now() / 1000), [weeklyBars, outcomeClock]); // eslint-disable-line react-hooks/exhaustive-deps
  const outcomeSeries = { intraday: intradayOutcomeSeries, daily: dailyOutcomeSeries, weekly: weeklyOutcomeSeries };
  const rowOutcome = useMemo(() => {
    const cache = new Map();
    const now = Date.now() / 1000;
    return (e) => {
      if (e.kind !== 'pattern' || !e.patternType) return null;
      const tf = e.timeframe || 'intraday';
      const key = `${tf}|${e.patternType}|${e.confirmedAt}`;
      if (!cache.has(key)) cache.set(key, evaluateEvent(e, { timeframe: tf, series: outcomeSeries[tf] || [], config: outcomeCfg, nowSec: now }));
      return cache.get(key);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intradayOutcomeSeries, dailyOutcomeSeries, weeklyOutcomeSeries, outcomeCfg]);
  // Outcome of the FORMATION a displayed event belongs to: measured from the run's FIRST detection (original timestamp),
  // while the chart marker sits on the run's last firing.
  const runFirst = useMemo(() => runFirstMap(patternEvents), [patternEvents]);
  const formationOutcome = useMemo(() => (e) => rowOutcome(runFirst.get(e) || e), [rowOutcome, runFirst]);
  // Daily/weekly statistics use the WHOLE available history of that timeframe (same detectors, bar by bar), computed only when a
  // daily/weekly pattern is selected. Intraday statistics use the loaded intraday window.
  const outcomeTf = selectedEntry ? selectedEntry.timeframe : null;
  const htfHistory = useMemo(
    () => (selected !== 'all' && outcomeTf && outcomeTf !== 'intraday' ? fullHistoryEvents({ dailyBars, weeklyBars }) : null),
    [selected, outcomeTf, dailyBars, weeklyBars],
  );
  const patternStats = useMemo(() => {
    if (selected === 'all' || !selectedEntry) return null;
    const tf = selectedEntry.timeframe;
    const series = outcomeSeries[tf];
    if (!series || !series.length) return null;
    const src = tf === 'intraday' ? patternEvents.filter((e) => e.timeframe === 'intraday') : (htfHistory ? htfHistory[tf].events : null);
    if (!src) return null;
    const nowSec = Date.now() / 1000;
    const occ = toOccurrences(src.filter((e) => e.patternType === selected), { symbol, timeframe: tf, series, config: outcomeCfg, nowSec });
    return statsForPattern(occ, { patternId: selected, timeframe: tf, series, config: outcomeCfg, nowSec });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, selectedEntry, patternEvents, htfHistory, intradayOutcomeSeries, dailyOutcomeSeries, weeklyOutcomeSeries, symbol, outcomeCfg]);
  const occurrence = selected === 'all' ? null : latestOccurrence(patternEvents, selected);
  const occTime = occurrence ? occurrence.time : null;

  // Markers come straight from the shared detector events (time, barIndex,
  // rangeLow/High). Chart patterns only - indicator events (volume, NR7,
  // BB squeeze...) never reach the price chart. Hidden entirely unless
  // Show Patterns is on.
  // Show Patterns draws only real detector formations (runs of consecutive
  // firings collapsed to one). To keep a long window readable they are grouped
  // into ~TARGET_GROUPS buckets over the VISIBLE bar range; a bucket with one
  // pattern is labelled with its name, a busier one with a count, and hover
  // lists every pattern in it. Zooming in shrinks the buckets and splits them.
  // Stable cluster id from the real detections' own bar span (not the count).
  const stateOfEvent = (e) => {
    const p = primaryOutcome(formationOutcome(e));
    return p && FLAG_STYLE[p.state] ? p.state : 'not_evaluable';
  };
  const groups = useMemo(() => {
    if (!showPatterns) return [];
    if (selected !== 'all') {
      if (!occurrence) return [];
      const state = stateOfEvent(occurrence);
      return [{ state, events: [occurrence], at: occurrence, above: FLAG_STYLE[state].above, id: `sel-${state}-${occurrence.barIndex}` }];
    }
    const lastBar = displayCandles.length - 1;
    const from = visRange ? Math.max(0, visRange.from) : 0;
    const to = visRange ? Math.min(lastBar, visRange.to) : lastBar;
    const width = containerRef.current?.clientWidth || 800;
    const pxPerBar = width / Math.max(1, to - from + 1);                 // follows zoom, panning, timeframe and resize
    const items = [];
    for (const e of collapseRuns(patternEvents)) {
      if (e.barIndex < from || e.barIndex > to) continue;
      const state = stateOfEvent(e);
      if (!showNeutralFlags && HIDDEN_BY_DEFAULT.includes(state)) continue;   // hidden, not deleted: the events remain in patternEvents
      items.push({ event: e, state });
    }
    return clusterByScreen(items, pxPerBar).map((g) => ({ ...g, id: `${g.state}-${g.at.barIndex}-${g.events.length}` }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showPatterns, selected, occurrence, patternEvents, visRange, displayCandles.length, showNeutralFlags, formationOutcome]);

  useEffect(() => {
    if (!zoneRef.current) return;
    if (!ob) { zoneRef.current.setData({ zones: [] }); return; }
    const curIds = new Set(Object.values(ob.current).map((z) => z.id));
    zoneRef.current.setData({
      showLiquidity: showLiq,
      narrow,
      zones: ob.zones.map((z) => ({
        id: z.id, bull: z.side === 'bull', startIdx: z.startIndex - ob.offset, endIdx: z.brokenAt != null ? z.endIndex - ob.offset : null,
        zoneLow: z.zoneLow, zoneHigh: z.zoneHigh, z: z.z, inv: z.inv, level1: z.level1, level2: z.level2, ladder: z.ladderOpposite, rr: z.rr,
        current: curIds.has(z.id), selected: z.id === obCardId,
      })),
    });
  }, [ob, showLiq, narrow, obCardId]);

  useEffect(() => { setObCardId(null); }, [symbol, mode, loadedDate, showOb]);

  const openObRow = (e) => {
    setObCardId(e.zoneId);
    const z = ob && ob.zones.find((q) => q.id === e.zoneId);
    if (z && chartRef.current) {
      const from = Math.max(0, z.startIndex - ob.offset - 20);
      chartRef.current.timeScale().setVisibleLogicalRange({ from, to: Math.min(displayCandles.length + 2, Math.max(from + 60, e.barIndex + 20)) });
    }
  };

  // Flags: colour AND side come from the realised outcome (green below/up, red above/down, blue pending). Selection is a white
  // outline; the fill never changes.
  useEffect(() => {
    if (!flagRef.current) return;
    const byId = new Map();
    const dimmed = !!focus;
    const selEvent = focus || (selected !== 'all' ? groups[0]?.at : null);
    const flags = [];
    for (const g of groups) {
      const bar = displayCandles[g.at.barIndex];
      if (!bar) continue;
      const style = FLAG_STYLE[g.state];
      const items = g.events.map((e) => {
        const first = runFirst.get(e) || e;
        const res = formationOutcome(e);
        return {
          name: e.pattern, symbol, timeframe: e.timeframe || 'intraday',
          detected: `${fmtDate(first.confirmedAt ?? first.time)}, ${fmtTime(first.confirmedAt ?? first.time)}`,
          bias: res?.classification ? biasText(res.classification) : 'unknown', primary: primaryOutcome(res),
        };
      });
      byId.set(g.id, { ...g, tipLines: flagTipLines(items) });
      const isSel = !!selEvent && g.events.includes(selEvent);
      flags.push({
        id: g.id, barIndex: g.at.barIndex, anchor: g.above ? bar.high : bar.low, above: g.above,
        fill: style.fill, textColor: style.text, label: g.events.length > 1 ? String(g.events.length) : '',
        selected: isSel, dim: dimmed && !isSel,
      });
    }
    groupsByIdRef.current = byId;
    flagRef.current.setFlags(flags);
    // Range box from the detector's own start/end/range for the emphasised detection.
    rangeBoxRef.current?.setRange(selEvent && selEvent.rangeHigh != null && selEvent.rangeLow != null
      ? { startIndex: selEvent.startIndex, endIndex: selEvent.endIndex, rangeHigh: selEvent.rangeHigh, rangeLow: selEvent.rangeLow }
      : null);
    if (!flags.length) setTip(null);
  }, [groups, selected, focus, formationOutcome, displayCandles, symbol, runFirst]);

  displayCandlesRef.current = displayCandles;

  // Leaving the dataset/filter a focus or popover belonged to clears it.
  useEffect(() => {
    setFocus(null);
    setPopover(null);
  }, [mode, symbol, loadedDate, selected, showPatterns, interval]);

  // Close the cluster list on outside click / ESC.
  useEffect(() => {
    if (!popover) return undefined;
    const onDown = (ev) => { if (popoverRef.current && !popoverRef.current.contains(ev.target)) setPopover(null); };
    const onKey = (ev) => { if (ev.key === 'Escape') setPopover(null); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('touchstart', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('touchstart', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [popover]);

  // Pan/zoom just enough to show the focused detection with surrounding price action.
  useEffect(() => {
    if (!focus || !chartRef.current) return;
    const last = displayCandles.length - 1;
    let from = focus.startIndex - 20;
    let to = focus.barIndex + 20;
    const MIN_SPAN = 60;
    if (to - from < MIN_SPAN) {
      const pad = Math.ceil((MIN_SPAN - (to - from)) / 2);
      from -= pad; to += pad;
    }
    chartRef.current.timeScale().setVisibleLogicalRange({ from: Math.max(0, from), to: Math.min(last + 3, to) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus]);

  // Zoom only moves the visible bar range (native timeScale API) - candle
  // data, interval, price scale and detections are untouched. Anchors on the
  // focused/selected pattern when there is one, else the right edge.
  const ZOOM_STEP = 1.3;
  const MIN_VISIBLE_BARS = 20;
  const RIGHT_PAD = 3;
  const zoomBars = (dir) => {
    const ts = chartRef.current?.timeScale();
    const r = ts?.getVisibleLogicalRange();
    const n = displayCandles.length;
    if (!r || n < 2) return;
    const maxSpan = n - 1 + RIGHT_PAD;
    const minSpan = Math.min(MIN_VISIBLE_BARS, maxSpan);
    const span = r.to - r.from;
    const newSpan = Math.min(maxSpan, Math.max(minSpan, dir === 'in' ? span / ZOOM_STEP : span * ZOOM_STEP));
    const anchor = focus || (showPatterns && selected !== 'all' ? occurrence : null);
    let from;
    let to;
    if (anchor) {
      const c = (anchor.startIndex + anchor.barIndex) / 2;
      from = c - newSpan / 2;
      to = c + newSpan / 2;
    } else {
      to = r.to;
      from = to - newSpan;
    }
    if (from < 0) { to -= from; from = 0; }
    if (to > n - 1 + RIGHT_PAD) { from -= to - (n - 1 + RIGHT_PAD); to = n - 1 + RIGHT_PAD; }
    ts.setVisibleLogicalRange({ from: Math.max(0, from), to });
  };
  const visSpan = visRange ? visRange.to - visRange.from : null;
  const canZoomIn = visSpan == null || visSpan > Math.min(MIN_VISIBLE_BARS, displayCandles.length) + 1;
  const canZoomOut = visRange == null || visRange.from > 0 || visRange.to < displayCandles.length - 1;

  const popoverTypes = useMemo(() => {
    if (!popover) return [];
    const m = new Map();
    popover.events.forEach((e) => { if (!m.has(e.pattern)) m.set(e.pattern, []); m.get(e.pattern).push(e); });
    return [...m.entries()]
      .map(([pattern, evs]) => ({ pattern, evs: [...evs].sort((a, b) => b.barIndex - a.barIndex) }))
      .sort((a, b) => b.evs[0].barIndex - a.evs[0].barIndex);
  }, [popover]);

  const pickDetection = (e) => { setFocus(e); setPopover(null); };

  // Scroll the chart to the detected occurrence's real bar range.
  useEffect(() => {
    if (!showPatterns || !occurrence || !chartRef.current) return;
    const from = Math.max(0, occurrence.startIndex - 8);
    const to = Math.min(displayCandles.length - 1, occurrence.barIndex + 8);
    chartRef.current.timeScale().setVisibleLogicalRange({ from, to });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, occTime, mode, loadedDate, showPatterns]);

  const goLive = () => {
    setMode('live');
    setSelected('all');
  };
  const pickPattern = (type) => {
    setSelected(type);
    if (type !== 'all') setShowPatterns(true); // picking a pattern means "show me it"

    if (type === 'all') chartRef.current?.timeScale().fitContent();
  };

  // Feed rows: live feed / loaded-day timeline, or every occurrence of the
  // selected pattern in the currently loaded data.
  // Daily/weekly detections fire on every session a pattern persists; the feed
  // lists one row per formation (same unit as the chip counts).
  const htfFeed = useMemo(() => collapseRuns(htfEvents), [htfEvents]);
  const baseFeed = [...(mode === 'history' ? (historyEvents || []) : events), ...htfFeed, ...obEvents];
  const feed = selected === 'all' ? baseFeed : collapseRuns(patternEvents.filter((e) => e.patternType === selected));

  const change = latest ? signedPct(latest.change_pct, { alreadyPercent: true }) : { text: '-', tone: 'neutral' };

  return (
    <div className="nv-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div>
          <div className="text-sm font-semibold text-slate-200">{name || symbol} - Live chart</div>
          <div className="text-[11px] text-slate-500">
            Source: yfinance (polled every {POLL_MS / 1000}s) - temporary until Axis Direct / ICICI live feed is connected
          </div>
        </div>
        <div className="flex items-center gap-4">
          {latest && (
            <div className="text-right">
              <div className="text-lg font-bold text-slate-100 nv-num">{inr(latest.ltp)}</div>
              <div className={`text-[12px] font-semibold nv-num ${toneClass(change.tone)}`}>{change.text}</div>
            </div>
          )}
          <div className="flex gap-1">
            {[['out', 'Zoom Out', canZoomOut], ['in', 'Zoom In', canZoomIn]].map(([dir, label, enabled]) => (
              <button
                key={dir}
                onClick={() => zoomBars(dir)}
                disabled={!enabled}
                title={label}
                aria-label={label}
                className="flex items-center justify-center w-7 h-7 rounded-md border border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-500 transition-colors disabled:opacity-40 disabled:hover:text-slate-400 disabled:hover:border-slate-700 disabled:cursor-not-allowed"
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                  <circle cx="7" cy="7" r="4.5" />
                  <path d="M10.5 10.5L14 14" />
                  <path d="M5 7h4" />
                  {dir === 'in' && <path d="M7 5v4" />}
                </svg>
              </button>
            ))}
          </div>
          <button
            onClick={() => setShowPatterns((v) => !v)}
            className={`px-2.5 py-1 text-[11px] rounded-md border transition-colors ${
              showPatterns
                ? 'bg-blue-500/20 border-blue-500/40 text-blue-300'
                : 'border-slate-700 text-slate-400 hover:text-slate-200'
            }`}
          >
            {showPatterns ? 'Hide Patterns' : 'Show Patterns'}
          </button>
          {mode === 'live' && interval === '5m' && (
            <button
              onClick={() => setShowForecast((v) => !v)}
              data-testid="forecast-toggle"
              className={`px-2.5 py-1 text-[11px] rounded-md border transition-colors ${
                showForecast
                  ? 'bg-blue-500/20 border-blue-500/40 text-blue-300'
                  : 'border-slate-700 text-slate-400 hover:text-slate-200'
              }`}
            >
              {showForecast ? 'Hide Forecast' : 'Show Forecast'}
            </button>
          )}
          <div className="flex gap-1">
            {INTERVALS.map((iv) => (
              <button
                key={iv.key}
                onClick={() => setInterval_(iv.key)}
                className={`px-2 py-1 text-[11px] rounded-md border transition-colors ${
                  interval === iv.key
                    ? 'bg-blue-500/20 border-blue-500/40 text-blue-300'
                    : 'border-slate-700 text-slate-400 hover:text-slate-200'
                }`}
              >
                {iv.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className={forecastView ? 'grid grid-cols-1 lg:grid-cols-2 gap-4' : ''} data-testid="chart-layout">
      <div className="min-w-0">
      {forecastView && (
        <div className="mb-1.5" data-testid="live-panel-header">
          <div className="text-[11px] font-bold uppercase tracking-widest text-emerald-300">Live</div>
          <div className="text-[11px] text-slate-500">Actual market data</div>
        </div>
      )}
      <div className="relative h-[420px]">
        {(loading || dailyLoading) && (
          <div className="absolute inset-0 flex items-center justify-center text-[12px] text-slate-500 italic">Loading chart...</div>
        )}
        {!loading && unavailable && (
          <div className="absolute inset-0 flex items-center justify-center text-[12px] text-slate-500 italic">
            Live chart data unavailable for this symbol right now.
          </div>
        )}
        <div ref={containerRef} className="w-full h-full" />
        {tip && !popover && (
          <div
            className="pointer-events-none absolute z-10 rounded border border-slate-700 bg-slate-900/95 px-2 py-1 text-[10px] leading-snug whitespace-nowrap text-slate-300"
            style={{ left: tip.x + 10, top: Math.max(tip.y - 26, 0) }}
          >
            {tip.lines.map((l, i) => <div key={i} className={i === 0 ? 'font-semibold text-slate-100' : ''}>{l}</div>)}
          </div>
        )}
        {focus && (
          <div className="absolute left-2 top-2 z-10 flex items-center gap-2 rounded-md border border-amber-500/40 bg-slate-900/95 px-2.5 py-1.5 text-[11px]">
            <div>
              <div className="text-[9px] font-semibold uppercase tracking-wider text-amber-300">Selected</div>
              <div className="font-semibold text-slate-100">{focus.pattern}</div>
              <div className="text-slate-500 nv-num">{fmtDate(focus.time)}, {fmtTime(focus.time)}</div>
            </div>
            <button
              onClick={() => setFocus(null)}
              className="rounded border border-slate-700 px-2 py-1 text-slate-300 hover:text-slate-100 hover:border-slate-500 transition-colors"
            >
              Show all patterns
            </button>
          </div>
        )}
        {obCard && <OrderBlockCard zone={obCard} onClose={() => setObCardId(null)} />}
        {popover && (
          <div
            ref={popoverRef}
            className="absolute z-20 w-72 rounded-md border border-slate-700 bg-slate-900 shadow-lg"
            data-testid="cluster-popover"
            style={{
              left: Math.max(4, Math.min(popover.x - 20, (containerRef.current?.clientWidth || 600) - 292)),
              top: Math.max(4, Math.min(popover.y + 14, (containerRef.current?.clientHeight || 420) - 300)),
            }}
          >
            <div className="flex items-center justify-between border-b border-slate-800 px-3 py-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                {popoverTypes.length} pattern{popoverTypes.length === 1 ? '' : 's'}
              </span>
              <button onClick={() => setPopover(null)} className="px-1 text-slate-500 hover:text-slate-200" aria-label="Close">x</button>
            </div>
            <div className="max-h-[230px] overflow-y-auto py-1">
              {popoverTypes.map((t) => (
                <div key={t.pattern}>
                  <div className="flex items-stretch">
                    <button
                      onClick={() => pickDetection(t.evs[0])}
                      className="flex-1 min-h-[36px] px-3 py-1.5 text-left text-[12px] text-slate-200 hover:bg-slate-800 transition-colors"
                    >
                      {t.pattern}
                      {t.evs.length > 1 && <span className="ml-1.5 text-slate-500">x{t.evs.length}</span>}
                      <OutcomeChips res={formationOutcome(t.evs[0])} tf={t.evs[0].timeframe || 'intraday'} />
                    </button>
                    {t.evs.length > 1 && (
                      <button
                        onClick={() => setExpanded((x) => ({ ...x, [t.pattern]: !x[t.pattern] }))}
                        className="min-w-[36px] px-2 text-[10px] text-slate-500 hover:text-slate-200 hover:bg-slate-800 transition-colors"
                        aria-label={`Show ${t.evs.length} ${t.pattern} detections`}
                      >
                        {expanded[t.pattern] ? '\u25B2' : '\u25BC'}
                      </button>
                    )}
                  </div>
                  {t.evs.length > 1 && expanded[t.pattern] && t.evs.map((e) => (
                    <button
                      key={e.id}
                      onClick={() => pickDetection(e)}
                      className="block w-full min-h-[32px] pl-6 pr-3 py-1 text-left text-[11px] text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors nv-num"
                    >
                      {fmtDate(e.time)}, {fmtTime(e.time)}
                      <OutcomeChips res={formationOutcome(e)} tf={e.timeframe || 'intraday'} />
                    </button>
                  ))}
                </div>
              ))}
            </div>
            <div className="border-t border-slate-800 px-3 py-1.5" data-testid="popover-legend"><OutcomeLegend compact /></div>
          </div>
        )}
      </div>
      {showPatterns && (
        <div className="mt-1.5" data-testid="chart-outcome-legend"><OutcomeLegend showNeutral={showNeutralFlags} onToggleNeutral={setShowNeutralFlags} /></div>
      )}

      </div>
      {forecastView && <ForecastPanel resp={forecastResp} loading={forecastLoading} error={forecastError} />}
      </div>

      <div className="mt-4 border-t border-slate-800 pt-3">
        <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            What's happening
            {mode === 'history' && loadedDate && <span className="ml-2 normal-case tracking-normal text-blue-300">- {loadedDate} session</span>}
          </div>
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={historyDate}
              max={todayISO()}
              onChange={(e) => setHistoryDate(e.target.value)}
              className="bg-slate-900 border border-slate-700 rounded-md px-2 py-1 text-[11px] text-slate-300"
            />
            <button
              onClick={() => loadHistory(historyDate)}
              className="px-2 py-1 text-[11px] rounded-md border border-slate-700 text-slate-300 hover:text-slate-100 hover:border-slate-500 transition-colors"
            >
              Load
            </button>
            {mode === 'history' && (
              <button
                onClick={goLive}
                className="px-2 py-1 text-[11px] rounded-md border border-blue-500/40 bg-blue-500/20 text-blue-300 transition-colors"
              >
                Back to live
              </button>
            )}
          </div>
        </div>

        <div className="flex gap-1.5 overflow-x-auto pb-1.5 mb-2" style={{ scrollbarWidth: 'thin' }}>
          <button
            onClick={() => pickPattern('all')}
            className={`flex-shrink-0 whitespace-nowrap px-2.5 py-1 text-[11px] rounded-full border transition-colors ${
              selected === 'all'
                ? 'bg-blue-500/20 border-blue-500/50 text-blue-300 font-semibold'
                : 'border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-500'
            }`}
          >
            All
          </button>
          <button
            onClick={() => setShowOb((v) => !v)}
            disabled={!obAvailable}
            data-testid="ob-toggle"
            title={obAvailable ? 'Order blocks and liquidity zones on closed 5-minute bars' : 'Order blocks use 5-minute bars: switch the interval to 5m'}
            className={`flex-shrink-0 whitespace-nowrap px-2.5 py-1 text-[11px] rounded-full border transition-colors ${
              showOb && obAvailable ? 'bg-blue-500/20 border-blue-500/50 text-blue-300 font-semibold'
                : obAvailable ? 'border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-500' : 'border-slate-800 text-slate-600 cursor-not-allowed'}`}
          >
            Order Blocks
            {showOb && obAvailable && <span className="ml-1.5 nv-num text-blue-300">{ob ? ob.zones.length : 0}</span>}
          </button>
          {showOb && obAvailable && (
            <button
              onClick={() => setShowLiq((v) => !v)}
              data-testid="liq-toggle"
              className={`flex-shrink-0 whitespace-nowrap px-2.5 py-1 text-[11px] rounded-full border transition-colors ${
                showLiq ? 'bg-blue-500/20 border-blue-500/50 text-blue-300' : 'border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-500'}`}
            >
              Liquidity levels
            </button>
          )}
          {PATTERN_REGISTRY.filter((p) => !p.optIn).map((p) => {
            const st = patternStatus(p, statusCtx);
            const unavailable = st.state === 'unavailable';
            const tone = selected === p.id
              ? 'bg-blue-500/20 border-blue-500/50 text-blue-300 font-semibold'
              : unavailable
                ? 'border-slate-800 text-slate-600 cursor-not-allowed'
                : st.state === 'needs-data'
                  ? 'border-dashed border-slate-600 text-slate-500 hover:text-slate-300'
                  : st.state === 'found'
                    ? 'border-slate-600 text-slate-200 hover:border-slate-400'
                    : 'border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-500';
            return (
              <button
                key={p.id}
                onClick={() => pickPattern(p.id)}
                disabled={unavailable}
                title={st.reason ? `${p.displayName}: ${st.reason}` : chipTitle(p, st.count)}
                className={`flex-shrink-0 whitespace-nowrap px-2.5 py-1 text-[11px] rounded-full border transition-colors ${tone}`}
              >
                <span className={`mr-1 ${biasGlyph(p.id).text}`} data-testid={`bias-${p.id}`} aria-label={biasGlyph(p.id).label}>{biasGlyph(p.id).glyph}</span>
                {p.displayName}
                {(st.state === 'found' || st.state === 'zero') && (
                  <span className={`ml-1.5 nv-num ${st.state === 'found' ? 'text-blue-300' : 'text-slate-600'}`}>{st.count}</span>
                )}
              </button>
            );
          })}
        </div>

        <div className="mb-2 text-[10px] text-slate-500" data-testid="count-definition">
          {COUNT_DEFINITION}{' '}
          Glyphs show the <span className="text-slate-300">conventional bias</span> (<span className={BIAS_STYLE.bullish.text}>▲ bullish</span>, <span className={BIAS_STYLE.bearish.text}>▼ bearish</span>, <span className={BIAS_STYLE.context.text}>◆ context-dependent</span>) - a textbook expectation, not a prediction.
          Outcome colours (realised, after detection): <span className={OUTCOME_STYLE.positive.text}>green positive</span>, <span className={OUTCOME_STYLE.negative.text}>red negative</span>, <span className={OUTCOME_STYLE.flat.text}>grey flat</span>, <span className={OUTCOME_STYLE.pending.text}>dashed blue pending</span>.
        </div>

        {showOb && obAvailable && (
          <div className="mb-2 text-[10px] text-slate-500" data-testid="ob-note">
            Order blocks use closed 5-minute bars from the temporary yfinance feed (no open-interest or volume-at-price data). Analytics only, not investment advice.
            {ob && ob.zones.length === 0 && <span className="ml-1 italic">No order block formed in this session yet (a missing value is never shown as zero).</span>}
          </div>
        )}

        {selected !== 'all' && (
          <div className="mb-2 rounded-md border border-slate-800 bg-slate-900/60 px-3 py-2 text-[12px]">
            {selectedStatus?.state === 'unavailable' ? (
              <span className="text-slate-500 italic">{selectedStatus.reason} - nothing is marked on the chart.</span>
            ) : selectedStatus?.state === 'needs-data' || selectedStatus?.state === 'loading' ? (
              <span className="text-slate-500 italic">{selectedLabel}: {selectedStatus.reason}</span>
            ) : !occurrence ? (
              <span className="text-slate-500 italic">No {selectedLabel} detected in this period</span>
            ) : (
              <div className="space-y-0.5">
                <div className="font-semibold text-slate-200">
                  {occurrence.pattern}
                  {occurrence.timeframe !== 'intraday' && <span className="ml-1.5 text-[10px] font-normal uppercase tracking-wider text-slate-500">{occurrence.timeframe} timeframe</span>}
                </div>
                {occurrence.timeframe === 'intraday' ? (
                  <>
                    <div className="text-slate-400">Formed: <span className="nv-num">{fmtDate(occurrence.formedAt)}, {fmtTime(occurrence.formedAt)}</span></div>
                    {occurrence.confirmedAt > occurrence.formedAt && (
                      <div className="text-slate-400">Confirmed: <span className="nv-num">{fmtTime(occurrence.confirmedAt)}</span></div>
                    )}
                  </>
                ) : (
                  <div className="text-slate-400">Completed on the <span className="nv-num">{fmtDate(occurrence.formedAt)}</span> {occurrence.timeframe} close</div>
                )}
                {occurrence.timeframe === 'intraday' && displayCandles[occurrence.startIndex] && (
                  <div className="text-slate-400">Pattern span: <span className="nv-num">{fmtTime(displayCandles[occurrence.startIndex].time)} - {fmtTime(occurrence.time)}</span> ({occurrence.endIndex - occurrence.startIndex + 1} bars)</div>
                )}
                {occurrence.rangeLow != null && occurrence.rangeHigh != null && (
                  <div className="text-slate-400">Pattern range: <span className="nv-num">{inr(occurrence.rangeLow)} - {inr(occurrence.rangeHigh)}</span></div>
                )}
                {occurrence.price != null && (
                  <div className="text-slate-400">Price at detection: <span className="nv-num">{inr(occurrence.price)}</span></div>
                )}
              </div>
            )}
          </div>
        )}

        {selected !== 'all' && selectedEntry && selectedStatus && !['unavailable', 'needs-data', 'loading'].includes(selectedStatus.state) && (
          <PatternOutcomePanel entry={selectedEntry} stats={patternStats} symbol={symbol} loading={outcomeTf !== 'intraday' && htfStatus[outcomeTf] === 'loading'} />
        )}

        <div className="max-h-[260px] overflow-y-auto space-y-1.5 pr-1 border-t border-slate-800 pt-2">
          {historyLoading && (
            <div className="text-[12px] text-slate-500 italic py-2">Loading {historyDate}...</div>
          )}
          {!historyLoading && historyUnavailable && (
            <div className="text-[12px] text-slate-500 italic py-2">
              No trading data for {historyDate} - it may be a weekend/holiday, or beyond yfinance's intraday history window for this interval (60 days for 5m bars).
            </div>
          )}
          {!historyLoading && feed.length === 0 && selected === 'all' && mode === 'live' && (
            <div className="text-[12px] text-slate-500 italic py-2">
              No notable moves yet - RSI/MACD crossovers, volume spikes, candlestick patterns, breakouts and swing-structure changes will appear here as new candles close.
            </div>
          )}
          {!historyLoading && feed.length === 0 && selected === 'all' && mode === 'history' && (
            <div className="text-[12px] text-slate-500 italic py-2">No notable moves detected for {loadedDate}.</div>
          )}
          {sortNewestFirst(feed).map((e, i) => (
            <EventRow key={`${mode}-${e.time}-${e.text}-${i}`} e={e} outcome={rowOutcome(e)} onOpen={e.zoneId ? () => openObRow(e) : undefined} />
          ))}
        </div>
      </div>
    </div>
  );
}
