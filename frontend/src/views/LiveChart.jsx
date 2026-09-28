import React, { useEffect, useRef, useState } from 'react';
import { createChart, ColorType, CandlestickSeries } from 'lightweight-charts';
import { inr, signedPct, toneClass, isNum } from '../lib/format.js';
import { fetchLiveChartCandles, fetchLiveChartLatest, fetchLiveChartDay } from '../lib/api.js';
import { analyzeCandles } from '../lib/technicalAnalysis.js';
import { detectChartPatterns } from '../lib/chartPatterns.js';
import { replayDayEvents } from '../lib/eventReplay.js';

const KIND_LABEL = {
  momentum: 'Momentum', volatility: 'Volatility', volume: 'Volume',
  candlestick: 'Candlestick', structure: 'Structure', breakout: 'Breakout',
  pattern: 'Pattern',
};

const CONFIDENCE_CLASS = {
  High: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  Medium: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  Low: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
};

// Polling cadence for "live" updates. yfinance has no push feed - this is a
// stand-in until Axis Direct's RAPID API (or ICICI Breeze) WebSocket feed
// is provisioned, at which point this polling loop is replaced by a
// persistent socket and the interval below goes away entirely.
const POLL_MS = 5000;

const INTERVALS = [
  { key: '1m', label: '1m' },
  { key: '5m', label: '5m' },
  { key: '15m', label: '15m' },
  { key: '60m', label: '1h' },
];

const todayISO = () => new Date().toISOString().slice(0, 10);

function EventRow({ e }) {
  return (
    <div className="flex items-start gap-2 text-[12px] flex-wrap">
      <span className={`mt-1 w-1.5 h-1.5 rounded-full flex-shrink-0 ${e.tone === 'pos' ? 'bg-emerald-500' : e.tone === 'neg' ? 'bg-red-500' : 'bg-slate-500'}`} />
      <span className="text-slate-500 flex-shrink-0 nv-num">
        {new Date(e.time * 1000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
      </span>
      <span className="text-slate-500 flex-shrink-0">{KIND_LABEL[e.kind] || e.kind}</span>
      <span className={toneClass(e.tone)}>{e.text}</span>
      {e.confidence && (
        <span className={`flex-shrink-0 px-1.5 py-0.5 rounded border text-[10px] font-semibold ${CONFIDENCE_CLASS[e.confidence] || CONFIDENCE_CLASS.Low}`}>
          {e.confidence} confidence
        </span>
      )}
    </div>
  );
}

export default function LiveChart({ symbol, name }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const [interval, setInterval_] = useState('5m');
  const [latest, setLatest] = useState(null);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);
  const [events, setEvents] = useState([]);
  const seenRef = useRef(new Set()); // "time|text" keys already logged, so re-polling the same closed candle doesn't duplicate an event

  // Day History: replays a single past trading day's 9:15-3:30 candles
  // through the same detectors as the live feed, so "what happened all
  // day" isn't limited to whatever's still in the rolling live window.
  const [historyDate, setHistoryDate] = useState(todayISO());
  const [historyEvents, setHistoryEvents] = useState(null); // null = not loaded yet
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyUnavailable, setHistoryUnavailable] = useState(false);

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
      setHistoryEvents(replayDayEvents(candles));
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
      timeScale: { borderColor: 'rgba(148,163,184,0.15)', timeVisible: true, secondsVisible: false },
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
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Runs the technical-analysis pass over a freshly-fetched candle series
  // and appends only events for closed bars not already logged, so
  // re-polling the same unchanged history doesn't spam duplicates.
  const applyCandles = (candles) => {
    if (seriesRef.current) {
      seriesRef.current.setData(candles.map((c) => ({
        time: c.time, open: c.open, high: c.high, low: c.low, close: c.close,
      })));
    }
    const found = [...analyzeCandles(candles), ...detectChartPatterns(candles)];
    const fresh = found.filter((e) => {
      const key = `${e.time}|${e.text}`;
      if (seenRef.current.has(key)) return false;
      seenRef.current.add(key);
      return true;
    });
    if (fresh.length) {
      setEvents((prev) => [...prev, ...fresh].slice(-100));
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
    setEvents([]);
    seenRef.current = new Set();

    const loadCandles = (isFirst) => {
      fetchLiveChartCandles(symbol, interval).then((resp) => {
        if (cancelled) return;
        if (isFirst) setLoading(false);
        const candles = resp && resp.candles;
        if (!candles || !candles.length) {
          if (isFirst) setUnavailable(true);
          return;
        }
        applyCandles(candles);
        if (isFirst) chartRef.current?.timeScale().fitContent();
      });
    };
    const loadLatest = () => {
      fetchLiveChartLatest(symbol).then((resp) => {
        if (!cancelled && resp && isNum(resp.ltp)) setLatest(resp);
      });
    };

    loadCandles(true);
    loadLatest();
    const id = window.setInterval(() => { loadCandles(false); loadLatest(); }, POLL_MS);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [symbol, interval]);

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

      <div className="relative h-[420px]">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center text-[12px] text-slate-500 italic">Loading chart...</div>
        )}
        {!loading && unavailable && (
          <div className="absolute inset-0 flex items-center justify-center text-[12px] text-slate-500 italic">
            Live chart data unavailable for this symbol right now.
          </div>
        )}
        <div ref={containerRef} className="w-full h-full" />
      </div>

      <div className="mt-4 border-t border-slate-800 pt-3">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">What's happening</div>
        <div className="max-h-[220px] overflow-y-auto space-y-1.5 pr-1">
          {events.length === 0 && (
            <div className="text-[12px] text-slate-500 italic py-2">
              No notable moves yet - RSI/MACD crossovers, volume spikes, candlestick patterns, breakouts and swing-structure changes will appear here as new candles close.
            </div>
          )}
          {[...events].reverse().map((e, i) => (
            <EventRow key={`${e.time}-${e.text}-${i}`} e={e} />
          ))}
        </div>
      </div>

      <div className="mt-4 border-t border-slate-800 pt-3">
        <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Day history</div>
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
          </div>
        </div>
        <div className="text-[10px] text-slate-600 mb-2">
          Replays that date's full 9:15-3:30 session (5m bars) through the same detectors above - not just what's still in the live rolling window.
        </div>
        <div className="max-h-[280px] overflow-y-auto space-y-1.5 pr-1">
          {historyLoading && (
            <div className="text-[12px] text-slate-500 italic py-2">Loading {historyDate}...</div>
          )}
          {!historyLoading && historyUnavailable && (
            <div className="text-[12px] text-slate-500 italic py-2">
              No trading data for {historyDate} - it may be a weekend/holiday, or beyond yfinance's intraday history window for this interval (60 days for 5m bars).
            </div>
          )}
          {!historyLoading && historyEvents && historyEvents.length === 0 && (
            <div className="text-[12px] text-slate-500 italic py-2">No notable moves detected for {historyDate}.</div>
          )}
          {!historyLoading && historyEvents && historyEvents.length > 0 && (
            [...historyEvents].reverse().map((e, i) => (
              <EventRow key={`hist-${e.time}-${e.text}-${i}`} e={e} />
            ))
          )}
          {!historyLoading && historyEvents === null && !historyUnavailable && (
            <div className="text-[12px] text-slate-500 italic py-2">Pick a date and click Load to see that day's full timeline.</div>
          )}
        </div>
      </div>
    </div>
  );
}
