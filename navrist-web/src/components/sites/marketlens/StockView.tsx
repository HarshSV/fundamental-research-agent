"use client";

import { WatchStar } from "./WatchlistPage";
import { ArrowLeft, ChartCandlestick, ChartLine, ChevronDown, TrendingDown, TrendingUp } from "lucide-react";
import { SlidingTabs, Switch } from "./controls";
import { useEffect, useMemo, useRef, useState } from "react";
import { fetchJson, searchSymbols, type CompanyHit } from "@/lib/api";
import { ActiveSetups } from "./ActiveSetups";
import { Dropdown } from "./Dropdown";
import { About, PeerTable, QuarterlyResults, ShareholdingPattern, Unavailable, type FinTab, type Overview, type Profile } from "./OverviewSections";
import {
  STATUS_LABEL, displayName, fetchCatalogue, fetchEvidence, fetchPatterns,
  type CatalogueEntry, type EvidenceRes, type PatternOcc, type PatternStatus, type PatternsResponse,
} from "./patterns";
import { marketOpen } from "./marketHours";
import { ForecastCard, News } from "./ForecastCard";
import { ForecastStrip } from "./ForecastStrip";
import { ChartLinesMenu, type LineGroup } from "./ChartLinesMenu";
import { fetchForecast, forecastCone, forecastLevels, type FcWindow, type Forecast } from "./forecast";
import type { ScanContext } from "./patternScan";
import { Detail as PatternDetail, type Candle } from "./PriceChart";
import { StockChart, type ChartStyle, type ScanOverlay } from "./StockChart";

interface Quote {
  ltp: number | null;
  change?: number | null;
  change_pct?: number | null;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close?: number | null;
  volume?: number | null;
  avg_price?: number | null; // exchange-computed day VWAP (average traded price)
}

const RANGES = ["1D", "1W", "1M", "3M", "6M", "1Y", "3Y", "5Y", "All"] as const;
type Range = (typeof RANGES)[number];

const DAY = 86400;
const RANGE_DAYS: Record<string, number> = { "1M": 30, "3M": 91, "6M": 182, "1Y": 365, "3Y": 1096, "5Y": 1826 };

/** What to load for a range. `tf` is the pattern-agent timeframe that matches the bars drawn, so the
 *  flags always sit on the same candles. `days` = daily bars sliced to that many days (null = intraday).
 *  LIVE keeps the same range but polls; for 1M it also switches to finer (hourly) bars. */
interface Spec { interval: string; period: string; tf: string; everyMs: number | null; days: number | null; intraday: boolean }
function specFor(range: Range, live: boolean): Spec {
  // 1D uses 1-minute bars and 1W 5-minute bars (about 375 points a session, like the reference site's
  // roughly-per-minute series). The pattern agent still runs on 5m / 15m bars; those timestamps are a
  // subset of the finer bars, so the flags land on the same candles.
  if (range === "1D") return { interval: "1m", period: "1d", tf: "5m", everyMs: live ? 5000 : null, days: null, intraday: true };
  if (range === "1W") return { interval: "5m", period: "5d", tf: "15m", everyMs: live ? 5000 : null, days: null, intraday: true };
  if (range === "1M" && live) return { interval: "60m", period: "1mo", tf: "60m", everyMs: 15000, days: null, intraday: true };
  // "All": the stock's whole daily history (loaded on its own; the daily set kept for the page is five years)
  if (range === "All") return { interval: "1d", period: "max", tf: "1d", everyMs: live ? 30000 : null, days: null, intraday: false };
  return { interval: "1d", period: "5y", tf: "1d", everyMs: live ? 30000 : null, days: RANGE_DAYS[range], intraday: false };
}
const BAR_SECONDS: Record<string, number> = { "1m": 60, "5m": 300, "15m": 900, "60m": 3600, "1d": 86400 };

// label shown -> key of the backend's return_bases
const RETURNS: [string, string][] = [
  ["1 Week", "1W"],
  ["1 Month", "1M"],
  ["3 Months", "3M"],
  ["6 Months", "6M"],
  ["1 Year", "1Y"],
  ["3 Years", "3Y"],
  ["5 Years", "5Y"],
];

const GAIN = "var(--gain)";
const LOSS = "#f93c65";

function fmt(v: number | null | undefined, digits = 2) {
  return v == null ? "—" : v.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
const SMA_PERIODS = [20, 50, 100, 200];
const SMA_COLORS: Record<number, string> = { 20: "#f59e0b", 50: "#3b82f6", 100: "#a855f7", 200: "#ec4899" };
const inr = (v: number | null | undefined) => (v == null ? "—" : `₹${fmt(v)}`);

// All data calls retry transient failures (network error, 5xx, provider returning nothing) before giving up.
const getJson = <T,>(path: string) => fetchJson<T>(path);

async function getCandles(sym: string, interval: string, period: string): Promise<Candle[]> {
  const d = await fetchJson<{ candles?: Candle[] }>(`/api/live-chart/${sym}?interval=${interval}&period=${period}`, {
    usable: (x) => (x.candles?.length ?? 0) > 1,
  });
  return d.candles ?? [];
}

function SectionTitle({ children, aside, beside }: { children: React.ReactNode; aside?: React.ReactNode; beside?: React.ReactNode }) {
  return (
    <div className="relative mb-5 flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <div className="h-6 w-1 rounded-full" style={{ background: "var(--accent-muted, #635ec8)" }} />
        <h2 className="text-xl font-semibold">{children}</h2>
        {beside}
      </div>
      {aside}
    </div>
  );
}

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={`min-w-0 rounded-xl border p-4 ${className}`}
      style={{ background: "var(--surface-1)", borderColor: "var(--border-subtle)", boxShadow: "var(--shadow-md)" }}
    >
      {children}
    </div>
  );
}

function Loading() {
  return (
    <div className="flex h-40 items-center justify-center text-sm" style={{ color: "var(--text-tertiary)" }}>
      Loading…
    </div>
  );
}

function RangeBar({ low, high, now, lowLabel, highLabel, title }: { low: number | null; high: number | null; now: number | null; lowLabel: string; highLabel: string; title: string }) {
  const known = low != null && high != null && now != null && high > low;
  const pos = known ? Math.min(100, Math.max(0, ((now - low) / (high - low)) * 100)) : null;
  return (
    <Card>
      <div className="mb-3 text-sm" style={{ color: "var(--text-secondary)" }}>{title}</div>
      <div className="flex items-center gap-4">
        <span className="text-sm font-semibold" style={{ color: LOSS }}>{lowLabel}</span>
        <div className="relative h-1 flex-1 rounded-full" style={{ background: "var(--overlay-strong)" }}>
          {pos != null && <span className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${pos}%`, background: "var(--accent)" }} />}
        </div>
        <span className="text-sm font-semibold" style={{ color: GAIN }}>{highLabel}</span>
      </div>
    </Card>
  );
}

/** Eases a displayed number from its previous value to a new target (cubic ease-out); the first value is shown as is. */
function useTween(target: number | null, ms = 480): number | null {
  const [shown, setShown] = useState<number | null>(target);
  const from = useRef<number | null>(target);
  useEffect(() => {
    if (target == null) {
      from.current = null;
      return;
    }
    const start = from.current ?? target;
    const t0 = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / ms);
      const cur = start + (target - start) * (1 - Math.pow(1 - p, 3));
      from.current = cur;
      setShown(cur);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return target == null ? null : shown ?? target;
}

type Basis = "ttm" | "annual";

/** Horizontal TTM | Annual switch for the whole Key Metrics block. `value` is null when the cards disagree. */
function BasisSwitch({ value, onChange }: { value: Basis | null; onChange: (b: Basis) => void }) {
  return (
    <div className="relative grid w-[132px] grid-cols-2 rounded-md p-[3px]" style={{ background: "var(--overlay-weak)" }} role="group" aria-label="All ratios basis" title="Switch every ratio below between the last 12 months and the last annual report">
      <span
        aria-hidden
        className="absolute inset-y-[3px] left-[3px] w-[calc(50%-3px)] rounded-[5px]"
        style={{ background: "var(--text-primary)", opacity: value ? 0.18 : 0, transform: `translateX(${value === "annual" ? 100 : 0}%)`, transition: "transform 320ms cubic-bezier(.22,.61,.36,1), opacity 250ms ease" }}
      />
      {([["ttm", "TTM"], ["annual", "Annual"]] as const).map(([id, text]) => (
        <button
          key={id}
          onClick={() => onChange(id)}
          aria-pressed={value === id}
          className="relative z-10 py-1.5 text-center text-xs font-medium leading-none"
          style={{ color: value === id ? "var(--text-primary)" : "var(--text-tertiary)", transition: "color 250ms ease" }}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

/** Vertical TTM | Annual switch for a Key Metrics card; the highlight slides between the two. */
function BasisToggle({ basis, onChange, title }: { basis: Basis; onChange: (b: Basis) => void; title: string }) {
  return (
    <div
      className="absolute right-3 top-1/2 grid w-[54px] -translate-y-1/2 grid-rows-2 rounded-md p-[3px]"
      style={{ background: "var(--overlay-weak)" }}
      role="group"
      aria-label="Basis"
      title={title}
    >
      <span
        aria-hidden
        className="absolute inset-x-[3px] top-[3px] h-[calc(50%-3px)] rounded-[5px]"
        style={{ background: "var(--text-primary)", opacity: 0.18, transform: `translateY(${basis === "ttm" ? 0 : 100}%)`, transition: "transform 320ms cubic-bezier(.22,.61,.36,1)" }}
      />
      {([["ttm", "TTM"], ["annual", "Annual"]] as const).map(([id, text]) => (
        <button
          key={id}
          onClick={() => onChange(id)}
          aria-pressed={basis === id}
          className="relative z-10 whitespace-nowrap py-[5px] text-center text-[10px] font-medium leading-none"
          style={{ color: basis === id ? "var(--text-primary)" : "var(--text-tertiary)", transition: "color 250ms ease" }}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

export function StockView({
  stock, onBack, onOpenStock, scan,
}: { stock: CompanyHit; onBack: () => void; onOpenStock?: (s: CompanyHit) => void; scan?: ScanContext }) {
  const sym = encodeURIComponent(stock.symbol);
  const name = stock.name ?? stock.company_name ?? stock.symbol;
  // Peer Comparison: clicking a peer opens that company's own page. The peer table carries short names, so look the
  // company up by symbol for its full record (falls back to the short name if the lookup fails).
  const openPeer = async (p: { symbol: string; name: string }) => {
    if (!onOpenStock) return;
    let hit: CompanyHit = { symbol: p.symbol, name: p.name };
    try {
      const found = (await searchSymbols(p.symbol)).find((h) => h.symbol.toUpperCase() === p.symbol.toUpperCase());
      if (found) hit = found;
    } catch {
      /* keep the short record */
    }
    onOpenStock(hit);
  };
  const [quote, setQuote] = useState<Quote | null>(null);
  const [daily, setDaily] = useState<Candle[] | null>(null);
  const [bars, setBars] = useState<{ key: string; data: Candle[] } | null>(null);
  const [ticks, setTicks] = useState<{ key: string; data: Candle[] }>({ key: "", data: [] });
  const [todayBars, setTodayBars] = useState<Candle[] | null>(null);
  const [pickedRange, setRange] = useState<Range>("6M");
  // live from the start while the market is open (Mon-Fri 09:15-15:30 IST, not on exchange holidays)
  const [live, setLive] = useState(() => marketOpen());
  // Is the exchange open right now (Mon-Fri 09:15-15:30 IST, not on holidays)? Re-checked every 30s; LIVE switches itself off at the close.
  const [open, setOpen] = useState(() => marketOpen());
  useEffect(() => {
    const t = setInterval(() => {
      const m = marketOpen();
      setOpen(m);
      if (!m) setLive(false);
    }, 30000);
    return () => clearInterval(t);
  }, []);
  const [liveAt, setLiveAt] = useState<Date | null>(null);
  const [error, setError] = useState("");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [finTab, setFinTab] = useState<FinTab>("results");
  const [profile, setProfile] = useState<Profile | null>(null);
  // Basic (non-TTM) EPS from the latest Annual Report. undefined = still loading, null eps = not available.
  const [annualEps, setAnnualEps] = useState<{ eps: number | null; period: string | null; basis?: string | null } | undefined>(undefined);
  // Patterns are off unless the page was opened from a scanner for that pattern, then its marking is shown straight away.
  const [showPatterns, setShowPatterns] = useState(Boolean(scan?.pattern));
  const [chartStyle, setChartStyle] = useState<ChartStyle>("candles");
  // Forecast: outlook odds, one trade plan or "No trade", replay odds, evidence. Re-read every minute while the market is open.
  const [forecast, setForecast] = useState<{ sym: string; data: Forecast | null; error: boolean } | null>(null);
  // which past the forecast learns from: the stock's whole history, or only the last five years
  const [fcWindow, setFcWindow] = useState<FcWindow>("max");
  // Which lines the chart draws. By default only today's trade plan (entry, stop, two targets); the rest are one tap away in "Chart lines".
  const DEFAULT_LINES: Record<string, boolean> = { today: true };
  const [lineOn, setLineOn] = useState<Record<string, boolean>>(DEFAULT_LINES);
  const toggleLine = (id: string) => setLineOn((m) => ({ ...m, [id]: !m[id] }));
  const showForecastLevels = Boolean(lineOn.today);
  const setShowForecastLevels = (f: (v: boolean) => boolean) => setLineOn((m) => ({ ...m, today: f(Boolean(m.today)) }));
  // Which basis each two-basis Key Metric shows; the switch beside the section title sets them all at once.
  const [views, setViews] = useState<Record<string, Basis>>({});
  const [showMore, setShowMore] = useState(false);
  const [showCone, setShowCone] = useState(true);
  const [showVolume, setShowVolume] = useState(false);
  // A newly listed stock has only a handful of daily bars, so a multi-month chart has nothing to draw.
  // Until it has some history, longer ranges fall back to the intraday 1D view (and say so).
  const MIN_DAILY_BARS = 5;
  const thinHistory = daily !== null && daily.length < MIN_DAILY_BARS;
  const range: Range = thinHistory && pickedRange !== "1D" && pickedRange !== "1W" ? "1D" : pickedRange;
  const spec = useMemo(() => specFor(range, live), [range, live]);
  const specKey = `${spec.interval}|${spec.period}`;

  const [reloadTick, setReloadTick] = useState(0); // bumped by the Retry button

  useEffect(() => {
    let live = true;
    let epsTimer: ReturnType<typeof setTimeout> | undefined;
    const fail = (e: Error) => live && setError(e.message);
    getJson<Overview>(`/api/v1/stock-overview/${sym}`)
      .then((o) => live && setOverview(o))
      .catch((e: Error) => {
        fail(e);
        if (live) setOverview((prev) => prev ?? { source: "unavailable" }); // nothing came back: say so instead of "Loading…"
      });
    getJson<Profile>(`/api/v1/stock-profile/${sym}`)
      .then((p) => live && setProfile(p))
      .catch(() => live && setProfile((prev) => prev ?? { paragraphs: [], headquarters: null, incorporation_year: null, leader: null, website: null, annual_report: null }));
    // First read of a company's Annual Report can take minutes: the backend answers `pending` and we poll.
    const pollEps = (tries: number) =>
      getJson<{ eps: number | null; period: string | null; basis?: string | null; pending?: boolean }>(`/api/v1/stock-eps/${sym}`)
        .then((e) => {
          if (!live) return;
          if (e.pending && tries < 120) epsTimer = setTimeout(() => pollEps(tries + 1), 5000);
          else setAnnualEps({ eps: e.eps, period: e.period, basis: e.basis });
        })
        .catch(() => live && setAnnualEps({ eps: null, period: null }));
    pollEps(0);
    getJson<Quote>(`/api/quote?symbol=${sym}`).then((q) => live && setQuote((prev) => (q.ltp != null ? q : prev ?? q))).catch(fail);
    // Never replace data we already have with an empty answer.
    getCandles(sym, "1d", "5y").then((c) => live && setDaily((prev) => (c.length ? c : prev ?? c))).catch(fail);
    // Today's 5-minute bars: used for VWAP (the headline range views load their own).
    getCandles(sym, "5m", "1d").then((c) => live && setTodayBars(c)).catch(() => {});
    return () => {
      live = false;
      clearTimeout(epsTimer);
    };
  }, [sym, reloadTick]);

  // VWAP: the exchange's own average traded price when the quote carries it; otherwise an approximation from today's
  // bars = sum(typical price x volume) / sum(volume), only from bars that carry volume.
  const barVwap = useMemo(() => {
    let pv = 0;
    let v = 0;
    for (const b of todayBars ?? []) {
      if (b.volume != null && b.volume > 0) {
        pv += ((b.high + b.low + b.close) / 3) * b.volume;
        v += b.volume;
      }
    }
    return v > 0 ? pv / v : null;
  }, [todayBars]);
  const vwap = quote?.avg_price ?? barVwap;

  // Bars for the selected range. Intraday ranges load their own bars; daily ranges slice `daily`.
  // LIVE re-fetches on a timer (the backend has no push feed, so this polls) and refreshes the
  // headline price on the same tick.
  useEffect(() => {
    let alive = true;
    const load = () => {
      if (live) {
        getJson<Quote>(`/api/quote?symbol=${sym}`)
          .then((q) => {
            if (!alive || q.ltp == null) return;
            setQuote(q);
            // LIVE on an intraday range: keep every distinct price we see, stamped to the second, so the
            // chart (and its hover) gets finer than the candles. Only while the market is open - after the
            // close the quote does not change and a stamp would claim a trade at a time none happened.
            if (spec.intraday && marketOpen()) {
              const price = q.ltp;
              const nowSec = Math.floor(Date.now() / 1000);
              setTicks((prev) => {
                const base = prev.key === specKey ? prev.data : [];
                if (base.length && base[base.length - 1].close === price) return prev.key === specKey ? prev : { key: specKey, data: base };
                return { key: specKey, data: [...base, { time: nowSec, open: price, high: price, low: price, close: price, tick: true as const }].slice(-1500) };
              });
            }
          })
          .catch(() => {});
      }
      getCandles(sym, spec.interval, spec.period)
        .then((c) => {
          if (!alive) return;
          // A poll that comes back empty must not wipe the chart: keep the last good bars.
          if (spec.days === null) setBars((prev) => (c.length || prev?.key !== specKey ? { key: specKey, data: c } : prev));
          else if (c.length) setDaily(c);
          if (c.length) setLiveAt(new Date());
        })
        .catch((e: Error) => alive && setError(e.message));
    };
    // Intraday ranges load their own bars. Turning LIVE on also fetches straight away, so "connecting…"
    // never waits for the first timer tick.
    if (spec.days === null || live) load();
    const timer = live && spec.everyMs ? setInterval(load, spec.everyMs) : null;
    return () => {
      alive = false;
      if (timer) clearInterval(timer);
    };
  }, [sym, spec, specKey, live, reloadTick]);

  useEffect(() => {
    let alive = true;
    const run = () =>
      fetchForecast(sym, fcWindow)
        .then((d) => alive && setForecast({ sym: `${sym}|${fcWindow}`, data: d, error: false }))
        .catch(() => alive && setForecast((prev) => (prev?.sym === `${sym}|${fcWindow}` && prev.data ? prev : { sym: `${sym}|${fcWindow}`, data: null, error: true })));
    run();
    const t = open ? setInterval(run, 60000) : null;
    return () => {
      alive = false;
      if (t) clearInterval(t);
    };
  }, [sym, open, fcWindow]);
  const forecastData = forecast?.sym === `${sym}|${fcWindow}` ? forecast : null;
  const coneData = useMemo(() => forecastCone(forecastData?.data ?? null), [forecastData]);

  // Pattern agent (backend): occurrences with their status lifecycle, per timeframe. The first run
  // for a stock/timeframe replays its history and can take ~10-30s; later requests come from the store.
  const [patternsByTf, setPatternsByTf] = useState<Record<string, PatternsResponse>>({});
  const [patternErrors, setPatternErrors] = useState<Record<string, string>>({});
  const [catalogue, setCatalogue] = useState<Record<string, CatalogueEntry>>({});
  const [evidence, setEvidence] = useState<EvidenceRes | null>(null);
  const requestedTf = useRef(new Set<string>());
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const patternKey = `${sym}|${spec.tf}`;
  const patterns: PatternsResponse | null = patternsByTf[patternKey] ?? null;
  const patternError = patternErrors[patternKey] ?? "";
  const [statusOn, setStatusOn] = useState<Record<PatternStatus, boolean>>({
    forming: true, awaiting_breakout: true, confirmed: true, invalidated: false,
  });
  const [patternFilter, setPatternFilter] = useState(scan?.pattern ?? "all");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchCatalogue().then((c) => alive && setCatalogue(c)).catch(() => {});
    fetchEvidence().then((e) => alive && setEvidence(e)).catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const tf = spec.tf;
    const key = `${sym}|${tf}`;
    // Results are applied while this component is mounted (not per effect run): React strict mode runs
    // effects twice in dev, and a per-run guard would discard the one request we deduplicate to.
    const run = () =>
      fetchPatterns(sym, tf)
        .then((p) => mounted.current && setPatternsByTf((cur) => ({ ...cur, [key]: p })))
        .catch((e: Error) => {
          requestedTf.current.delete(key); // allow a later attempt (range switch, LIVE tick, Retry)
          if (mounted.current) setPatternErrors((cur) => ({ ...cur, [key]: e.message }));
        });
    if (!requestedTf.current.has(key)) {
      requestedTf.current.add(key);
      run();
    }
    // LIVE on an intraday timeframe: pick up newly closed bars once a minute.
    const timer = live && spec.intraday ? setInterval(run, 60000) : null;
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [sym, spec.tf, spec.intraday, live]);

  const shownOccs = useMemo<PatternOcc[]>(
    () => (patterns?.occurrences ?? []).filter((o) => statusOn[o.status] && (patternFilter === "all" || o.pattern === patternFilter)),
    [patterns, statusOn, patternFilter],
  );
  const selectedOcc = useMemo(
    () => (patterns?.occurrences ?? []).find((o) => o.occ_id === selectedId) ?? null,
    [patterns, selectedId],
  );
  const activeOccs = useMemo(
    () => (patterns?.occurrences ?? []).filter((o) => o.status === "forming" || o.status === "awaiting_breakout"),
    [patterns],
  );

  const isIntraday = spec.intraday;
  const ownBars = spec.days === null; // intraday ranges and "All" load their own bars; the rest slice the daily set
  const series = useMemo(() => {
    if (ownBars) {
      const b = bars?.key === specKey ? bars.data : null;
      if (!b || !live || ticks.key !== specKey || !ticks.data.length) return b;
      // live ticks that fall after the last candle's bucket extend the line with second-level points
      const after = (b[b.length - 1]?.time ?? 0) + BAR_SECONDS[spec.interval];
      const extra = ticks.data.filter((t) => t.time > after);
      return extra.length ? [...b, ...extra] : b;
    }
    if (!daily) return null;
    const cutoff = daily.length ? daily[daily.length - 1].time - (spec.days as number) * DAY : 0;
    return daily.filter((c) => c.time >= cutoff);
  }, [ownBars, bars, specKey, daily, spec.days, live, ticks, spec.interval]);

  // While a new range loads, keep the previous chart on screen (with a spinner) so the switch can morph
  // from the old shape to the new one instead of flashing a blank "Loading…" box. This is React's
  // "adjust state while rendering" pattern: guarded, so it settles in one extra pass.
  const seriesKey = ownBars ? specKey : `d${spec.days}`;
  const [held, setHeld] = useState<{ key: string; data: Candle[] } | null>(null);
  if (series && series !== held?.data) setHeld({ key: seriesKey, data: series });
  const shown = series ?? held?.data ?? null;
  const shownKey = series ? seriesKey : held?.key ?? seriesKey;
  const switching = series === null && held !== null;

  // Returns = live price / the close on the latest trading day on or before (today - period), minus 1 - the exchange's
  // Market Lens definition. The base closes come from the backend's full history (calendar arithmetic); a period the
  // history does not reach is "—", never extrapolated.
  const returns = (() => {
    const bases = overview?.return_bases;
    if (!bases) return null;
    const end = quote?.ltp ?? daily?.[daily.length - 1]?.close ?? null;
    const rows = RETURNS.map(([label, key]) => {
      const b = bases[key];
      return { label, pct: end != null && b ? (end / b.price - 1) * 100 : null };
    });
    // Listed less than a year ago: the periods it has not lived through stay "—", and the return since the first close is added.
    if (!bases["1Y"] && daily?.length && daily[0].close && end != null) rows.push({ label: "Since listing", pct: (end / daily[0].close - 1) * 100 });
    return rows;
  })();

  const week52 = useMemo(() => {
    if (!daily?.length) return null;
    const cutoff = daily[daily.length - 1].time - 365 * DAY;
    // A stock listed less than a year ago has no 52-week window: its range since listing is shown instead, and labelled so.
    const sinceListing = daily[0].time > cutoff + 7 * DAY;
    const win = sinceListing ? daily : daily.filter((c) => c.time >= cutoff);
    return { low: Math.min(...win.map((c) => c.low)), high: Math.max(...win.map((c) => c.high)), sinceListing };
  }, [daily]);

  // All-time extremes come from the backend's FULL price history (split/bonus-adjusted, not
  // dividend-adjusted), not from the 5-year chart window.
  const allTime =
    overview?.all_time_high && overview?.all_time_low
      ? { low: overview.all_time_low.price, high: overview.all_time_high.price }
      : null;

  const scanOverlay: ScanOverlay | null = scan ? { occurrence: scan.occurrence, resistance: scan.showResistance ? scan.resistance : null } : null;

  // the lines the chart can draw, and the ones switched on
  const allLevels = forecastLevels(forecastData?.data ?? null);
  const has = (g: string) => allLevels.some((l) => l.group === g);
  const noPlan = forecastData?.data ? "No plan for this stock right now" : "Waiting for the forecast";
  const chartLevels = [
    ...allLevels.filter((l) => lineOn[l.group]),
    ...(lineOn.wk52 && week52 ? [{ price: week52.high, title: `52-week high ${inr(week52.high)}`, color: "#f59e0b", dashed: true, group: "wk52" as const }, { price: week52.low, title: `52-week low ${inr(week52.low)}`, color: "#f59e0b", dashed: true, group: "wk52" as const }] : []),
  ];
  const lineGroups: LineGroup[] = [
    {
      title: "Trade plan (from the forecast)",
      options: [
        { id: "today", label: "Today's plan", hint: "Entry, stop-loss, targets 1 and 2", color: "#10b981", disabled: has("today") ? undefined : noPlan },
        { id: "swing", label: "Swing plan", hint: "Entry, stop-loss, targets, up to 10 sessions", color: "#34d399", disabled: has("swing") ? undefined : noPlan },
        { id: "range", label: "Opening range", hint: "Today's range high and low", color: "#8b8b9a", disabled: has("range") ? undefined : noPlan },
      ],
    },
    { title: "Price levels", options: [{ id: "wk52", label: "52-week high/low", color: "#f59e0b", disabled: week52 ? undefined : "Not enough history" }] },
    {
      title: "Moving averages (daily chart)",
      note: "Dashed continuation: where the average goes if the price follows the middle of the forecast.",
      options: SMA_PERIODS.map((n) => ({ id: `sma${n}`, label: `${n}-day`, color: SMA_COLORS[n], disabled: isIntraday ? "Switch to a daily range" : !daily || daily.length < n ? "Not enough history" : undefined })),
    },
  ];

  const pct = quote?.change_pct;
  const up = (pct ?? 0) >= 0;
  const ltp = quote?.ltp ?? null;
  // P/E = live price / Basic EPS (non-TTM) from the latest audited Annual Report, only when that EPS is positive
  // (negative or unknown earnings give "—", never a made-up number).
  const annEps = annualEps?.eps ?? null;
  const pe = annEps != null && annEps > 0 && ltp ? ltp / annEps : null;
  const arYear = annualEps?.period?.slice(-4);

  // Colours of the Key Metrics: green = favourable, red = unfavourable, plain = no judgement (a level or a label).
  //   P/E (TTM)      Screener's trailing-12-month P/E against the sector median: more than 20% under it green, more than double it red.
  //                  The headline P/E uses the last annual report's EPS, which can be a year old, so it is not coloured.
  //   EPS            positive earnings green, a loss red
  //   Debt / equity  at most 0.5 green, 1.5 or more red (the figure is left out for banks and lenders, where it means little)
  //   All time high  within 10% of it green, less than half of it red
  const sectorPe = Number(forecastData?.data?.evidence.find((e) => e.label.startsWith("P/E"))?.label.match(/median ([\d.]+)/)?.[1]);
  const ttmPe = overview?.pe ?? null;
  const toneOf = (v: number | null): "good" | "bad" | null => (!sectorPe || v == null || v <= 0 ? null : v < 0.8 * sectorPe ? "good" : v > 2 * sectorPe ? "bad" : null);
  // Every two-basis metric: shown on its own basis (set by the cards' switches or the block switch); when only one basis
  // exists that one is shown, with no switch.
  const basisOf = (k: string, ttm: number | null, annual: number | null) => {
    const both = ttm != null && annual != null;
    const basis: Basis = both ? views[k] ?? "ttm" : annual != null ? "annual" : "ttm";
    return { both, basis, value: basis === "ttm" ? ttm : annual };
  };
  const R = overview?.ratios ?? null;
  const fy = R?.annual_label ?? (arYear ? `FY${arYear.slice(-2)}` : "the last annual report");
  const peM = basisOf("pe", ttmPe, pe);
  const epsM = basisOf("eps", overview?.eps_ttm ?? null, annEps);
  const roeM = basisOf("roe", R?.roe.ttm ?? null, R?.roe.annual ?? null);
  const marginM = basisOf("margin", R?.net_margin.ttm ?? null, R?.net_margin.annual ?? null);
  const growthM = basisOf("growth", R?.revenue_growth.ttm ?? null, R?.revenue_growth.annual ?? null);
  const covM = basisOf("cov", R?.interest_coverage?.ttm ?? null, R?.interest_coverage?.annual ?? null);
  const peTween = useTween(peM.value);
  const epsTween = useTween(epsM.value);
  const roeTween = useTween(roeM.value);
  const marginTween = useTween(marginM.value);
  const growthTween = useTween(growthM.value);
  const covTween = useTween(covM.value);
  const switchable = [peM, epsM, roeM, marginM, growthM, covM].filter((m) => m.both);
  const allBasis: Basis | null = switchable.length && switchable.every((m) => m.basis === switchable[0].basis) ? switchable[0].basis : null;
  const setAll = (b: Basis) => setViews(Object.fromEntries(["pe", "eps", "roe", "margin", "growth", "cov"].map((k) => [k, b])));
  const setOne = (k: string) => (b: Basis) => setViews((v) => ({ ...v, [k]: b }));
  const epsTone: "good" | "bad" | null = epsM.value == null ? null : epsM.value > 0 ? "good" : "bad";
  const level = (v: number | null, good: number, bad: number): "good" | "bad" | null => (v == null ? null : v >= good ? "good" : v < bad ? "bad" : null);
  const deTone: "good" | "bad" | null = overview?.debt_to_equity == null ? null : overview.debt_to_equity <= 0.5 ? "good" : overview.debt_to_equity >= 1.5 ? "bad" : null;
  const athTone: "good" | "bad" | null =
    allTime && ltp ? (ltp >= 0.9 * allTime.high ? "good" : ltp < 0.5 * allTime.high ? "bad" : null) : null;

  return (
    <div className="w-full">
      <section className="mx-auto w-full max-w-7xl px-4 pb-8 pt-8">
        <button onClick={onBack} className="mb-3 flex min-h-[44px] items-center gap-2 text-sm hover:text-[var(--accent)] sm:mb-5 sm:min-h-0" style={{ color: "var(--text-secondary)" }}>
          <ArrowLeft className="h-4 w-4" /> Back to search
        </button>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-bold tracking-tight">{name}</h1>
          {stock.primary_exchange ? (
            <span className="rounded-full border px-3 py-0.5 text-xs" style={{ color: "var(--text-tertiary)", borderColor: "var(--border-default)" }}>
              {String(stock.primary_exchange)}
            </span>
          ) : null}
          {stock.status === "Suspended" ? (
            <span className="rounded-full border px-3 py-0.5 text-xs" title="Listed on BSE but not trading. The chart and figures are the last available ones." style={{ color: "#e5a54b", borderColor: "#e5a54b" }}>
              Suspended
            </span>
          ) : null}
          <WatchStar symbol={stock.symbol} name={String(name)} />
        </div>
        <div className="mt-2 text-sm" style={{ color: "var(--text-tertiary)" }}>{stock.symbol}</div>
        <div className="mt-6 flex flex-wrap items-center gap-4">
          <span className="text-4xl font-bold">{quote ? inr(ltp) : "Loading…"}</span>
          {pct != null && (
            <span className="flex items-center gap-1 text-base font-medium" style={{ color: up ? GAIN : LOSS }}>
              {up ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
              {up ? "+" : ""}{fmt(quote?.change)} ({up ? "+" : ""}{fmt(pct)}%)
            </span>
          )}
        </div>
        {error && <p className="mt-3 text-sm" style={{ color: "#f5a9a9" }}>{error}</p>}
      </section>

      <section className="border-t py-10" style={{ background: "var(--surface-0)", borderColor: "var(--border-subtle)" }}>
        <div className="mx-auto w-full max-w-7xl px-4">
          <SectionTitle
            aside={
              <div className="flex gap-1 rounded-full p-1" style={{ background: "var(--surface-1)" }}>
                {open ? (
                  <button
                    onClick={() => setLive((v) => !v)}
                    title={live ? "Live updates on. Click to turn off" : "Turn on live updates for the selected range"}
                    className="flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-semibold transition-colors"
                    style={{ background: live ? "#dc2626" : "transparent", color: live ? "#fff" : "var(--text-secondary)" }}
                  >
                    <span className={`h-1.5 w-1.5 rounded-full ${live ? "animate-pulse" : ""}`} style={{ background: live ? "#fff" : "#ef4444" }} />
                    LIVE
                  </button>
                ) : (
                  <span
                    className="flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-semibold"
                    style={{ color: "var(--text-tertiary)" }}
                    title="NSE trades Monday to Friday, 9:15 am to 3:30 pm IST. Prices shown are from the last session."
                  >
                    <span className="h-1.5 w-1.5 rounded-full" style={{ background: "var(--text-tertiary)" }} />
                    Market closed
                  </span>
                )}
              </div>
            }
          >
            Price Chart
            {live && (
              <span className="ml-3 align-middle text-xs font-normal" style={{ color: "#f87171" }}>
                ● Live · {liveAt ? `updated ${liveAt.toLocaleTimeString("en-IN", { hour12: false })}` : "connecting…"}
              </span>
            )}
          </SectionTitle>
          {thinHistory && daily && (
            <p className="mb-3 rounded-lg border px-3 py-2 text-xs" style={{ borderColor: "#f59e0b55", background: "#f59e0b12", color: "#f5c46a" }}>
              Recently listed: only {daily.length} trading day{daily.length === 1 ? "" : "s"} of price history so far, so
              longer ranges, returns and the 52-week range can&apos;t be calculated yet. Showing today&apos;s intraday chart;
              they fill in as history builds up.
            </p>
          )}
          <ForecastStrip data={forecastData?.data ?? null} />
          <div className="mb-3">
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
              <Switch
                on={showPatterns}
                onChange={() => {
                  setShowPatterns((v) => !v);
                  setSelectedId(null);
                }}
                label="Patterns"
                title={showPatterns ? "Hide pattern markers" : "Show pattern markers"}
              />
              <div className="ml-auto flex flex-wrap items-center gap-x-5 gap-y-2">
                {!isIntraday && coneData && <Switch on={showCone} onChange={() => setShowCone((v) => !v)} label="Forecast" title="Shade where the price is likely to be over the next 5 and 20 sessions" />}
                <Switch on={showVolume} onChange={() => setShowVolume((v) => !v)} label="Volume" />
                <ChartLinesMenu groups={lineGroups} on={lineOn} onToggle={toggleLine} onReset={() => setLineOn(DEFAULT_LINES)} count={Object.entries(lineOn).filter(([k, v]) => v && !(isIntraday && k.startsWith("sma"))).length} />
              </div>
              {showPatterns && (
                <span className="nv-rise text-xs" style={{ color: "var(--text-tertiary)" }}>
                  {patterns !== null
                    ? `${shownOccs.length} shown · ${spec.tf} bars`
                    : patternError
                      ? `Pattern agent unavailable (${patternError}). It will retry; or switch range and back`
                      : `Pattern agent running on ${spec.tf} bars… (first run can take up to ~30s)`}
                </span>
              )}
            </div>
            {showPatterns && (
              <p className="nv-rise mt-3 text-[11px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
                ▲ bullish below the candle, ▼ bearish above it. Colour shows what happened 5 sessions later:
                <b style={{ color: "#10b981" }}> green</b> gained, <b style={{ color: "#ef4444" }}>red</b> fell, <b style={{ color: "#3b82f6" }}>blue</b> too recent to know, grey flat.
                Big, labelled arrows are patterns developing now; small faded ones are old. Developing patterns also draw their outline, breakout, fail level and a rule-of-thumb target.
              </p>
            )}
            {showPatterns && (
              <div className="nv-rise mt-3 flex flex-wrap items-center gap-2 text-xs">
                {(Object.keys(STATUS_LABEL) as PatternStatus[]).map((st) => (
                  <button
                    key={st}
                    onClick={() => setStatusOn((cur) => ({ ...cur, [st]: !cur[st] }))}
                    aria-pressed={statusOn[st]}
                    className="rounded-md border px-2.5 py-1 font-medium"
                    style={{
                      borderColor: statusOn[st] ? "var(--text-tertiary)" : "var(--border-subtle)",
                      color: statusOn[st] ? "var(--text-primary)" : "var(--text-tertiary)",
                      background: statusOn[st] ? "var(--overlay)" : "transparent",
                      transition: "background 250ms ease, color 250ms ease, border-color 250ms ease",
                    }}
                  >
                    {STATUS_LABEL[st]}
                    {patterns?.counts.by_status?.[st] != null ? <span className="ml-1.5 opacity-60">{patterns.counts.by_status[st]}</span> : null}
                  </button>
                ))}
                <Dropdown
                  ariaLabel="Filter by pattern"
                  value={patternFilter}
                  onChange={setPatternFilter}
                  options={[
                    { value: "all", label: "All patterns" },
                    ...Object.entries(patterns?.counts.by_pattern ?? {})
                      .map(([id, n]) => ({ value: id, label: displayName(catalogue, id), hint: String(n) }))
                      .sort((x, y) => x.label.localeCompare(y.label)),
                  ]}
                />
              </div>
            )}
          </div>
          {shown === null && !error ? (
            <div className="flex h-[320px] items-center justify-center text-sm" style={{ color: "var(--text-tertiary)" }}>Loading chart…</div>
          ) : shown && shown.length > 1 ? (
            <div className="relative">
            <StockChart
              candles={shown}
              dataKey={shownKey}
              intraday={isIntraday}
              chartStyle={chartStyle}
              showVolume={showVolume}
              occs={showPatterns ? shownOccs : []}
              selectedId={selectedId}
              onSelect={setSelectedId}
              scan={scanOverlay}
              levels={chartLevels}
              cone={showCone && !isIntraday ? coneData : null}
              averages={isIntraday ? undefined : SMA_PERIODS.filter((n) => lineOn[`sma${n}`])}
              history={daily ?? undefined}
              projectFrom={coneData}
            />
            {switching && (
              <span
                className="pointer-events-none absolute left-1/2 top-1/2 h-6 w-6 -translate-x-1/2 -translate-y-1/2 animate-spin rounded-full border-2"
                style={{ borderColor: "var(--accent)", borderTopColor: "transparent" }}
                role="status"
                aria-label="Loading chart"
              />
            )}
            </div>
          ) : (
            <div className="flex h-[320px] flex-col items-center justify-center gap-3 text-sm" style={{ color: "var(--text-tertiary)" }}>
              <span>No chart data came back for this range. This is usually a temporary hiccup from the data provider.</span>
              <button
                onClick={() => {
                  requestedTf.current.clear();
                  setReloadTick((n) => n + 1);
                }}
                className="rounded-full border px-4 py-1.5 text-xs font-semibold transition-colors hover:bg-[#b7b4e71a]"
                style={{ borderColor: "#b7b4e7", color: "#b7b4e7" }}
              >
                Retry
              </button>
            </div>
          )}
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <div className="flex max-w-full flex-wrap items-center gap-3">
              <div className="max-w-full overflow-x-auto"><SlidingTabs ariaLabel="Chart range" options={RANGES.map((r) => ({ id: r, label: r }))} value={range} onChange={setRange} /></div>
              <SlidingTabs
                ariaLabel="Chart style"
                size="icon"
                value={chartStyle}
                onChange={setChartStyle}
                options={[
                  { id: "candles", label: <ChartCandlestick className="h-4 w-4" />, title: "Candlestick chart" },
                  { id: "line", label: <ChartLine className="h-4 w-4" />, title: "Line chart" },
                ]}
              />
            </div>
          </div>
          {showPatterns && selectedOcc && (
            <Card className="mt-4">
              <div className="flex items-start justify-between gap-3">
                <div className="text-base font-semibold">
                  {displayName(catalogue, selectedOcc.pattern)}
                  
                </div>
                <button onClick={() => setSelectedId(null)} aria-label="Close details" className="px-1 text-lg leading-none" style={{ color: "var(--text-tertiary)" }}>×</button>
              </div>
              <PatternDetail o={selectedOcc} catalogue={catalogue} />
            </Card>
          )}
          {showPatterns && <ActiveSetups occs={activeOccs} catalogue={catalogue} ltp={ltp} selectedId={selectedId} onSelect={setSelectedId} evidence={evidence} />}
        </div>
      </section>

      <section className="border-t py-10" style={{ background: "var(--surface-0)", borderColor: "var(--border-subtle)" }}>
        <div className="mx-auto w-full max-w-7xl px-4">
          <SectionTitle
            beside={<News symbol={stock.symbol} />}
            aside={
              <div className="flex items-center gap-2 text-xs" style={{ color: "var(--text-tertiary)" }}>
                <span className="hidden sm:inline">Learns from</span>
                <SlidingTabs
                  ariaLabel="Forecast history"
                  size="sm"
                  value={fcWindow}
                  onChange={setFcWindow}
                  options={[{ id: "max", label: "Full history" }, { id: "5y", label: "Last 5 years" }]}
                />
              </div>
            }
          >
            Forecast
          </SectionTitle>
          <ForecastCard
            data={forecastData?.data ?? null}
            error={Boolean(forecastData?.error)}
            showLevels={showForecastLevels}
            onToggleLevels={() => setShowForecastLevels((v) => !v)}
          />
        </div>
      </section>

      <section className="border-t py-10" style={{ background: "var(--surface-1)", borderColor: "var(--border-subtle)" }}>
        <div className="mx-auto w-full max-w-7xl px-4">
          <SectionTitle aside={switchable.length ? <BasisSwitch value={allBasis} onChange={setAll} /> : null}>Key Metrics</SectionTitle>
          {(() => {
            const wait = overview === null ? "…" : null;
            const x = (v: number | null, f: (n: number) => string) => (v != null ? f(v) : wait);
            type Metric = { id: string; label: string; value: string | null; tone: "good" | "bad" | null; sw?: { m: { both: boolean; basis: Basis }; set: (b: Basis) => void; title: string } };
            const primary: Metric[] = [
              { id: "mcap", label: "Market Cap", value: overview?.market_cap_cr != null ? `₹${fmt(overview.market_cap_cr)} Cr` : null, tone: null },
              { id: "pe", label: "P/E Ratio", value: peTween != null ? fmt(peTween) : annualEps === undefined ? "…" : null, tone: peM.basis === "ttm" ? toneOf(ttmPe) : null,
                sw: { m: peM, set: setOne("pe"), title: peM.basis === "ttm" ? `Last 12 months${sectorPe ? ` · sector median ${fmt(sectorPe)}` : ""}` : `On the ${fy} annual report` } },
              { id: "eps", label: epsM.basis === "ttm" ? "EPS (TTM)" : `${arYear ? `EPS (FY${arYear.slice(-2)}` : "EPS (annual"}${annualEps?.basis === "standalone" ? ", standalone" : ""})`,
                value: epsTween != null ? `₹${fmt(epsTween)}` : annualEps === undefined ? "…" : null, tone: epsTone,
                sw: { m: epsM, set: setOne("eps"), title: epsM.basis === "ttm" ? "Sum of the last four reported quarters" : `Basic EPS on the ${fy} annual report` } },
              { id: "fv", label: "Face Value", value: overview?.face_value != null ? `₹${fmt(overview.face_value, overview.face_value % 1 ? 2 : 0)}` : null, tone: null },
              { id: "ath", label: "All Time High", value: allTime ? inr(allTime.high) : null, tone: athTone },
              { id: "atl", label: "All Time Low", value: allTime ? inr(allTime.low) : null, tone: null },
              { id: "de", label: "Debt/Equity", value: overview?.debt_to_equity != null ? fmt(overview.debt_to_equity) : null, tone: deTone },
            ];
            const book = R?.book_value ?? null;
            const more: Metric[] = [
              { id: "roe", label: "ROE", value: x(roeTween, (n) => `${fmt(n)}%`), tone: level(roeM.value, 15, 8),
                sw: { m: roeM, set: setOne("roe"), title: roeM.basis === "ttm" ? "Last 12 months profit on the latest equity" : `${fy} profit on ${fy} year-end equity` } },
              { id: "pb", label: "Price to Book", value: ltp && book ? (ltp / book <= 300 ? `${fmt(ltp / book)}x` : null) : wait, tone: null },     // beyond 300x the book value is not a real net worth
              { id: "dy", label: "Dividend Yield", value: x(R?.dividend_yield ?? null, (n) => `${fmt(n)}%`), tone: null },
              { id: "promoter", label: "Promoter Holding", value: x(R?.promoter ?? null, (n) => `${fmt(n)}%`), tone: level(R?.promoter ?? null, 50, 25) },
              { id: "margin", label: "Net Profit Margin", value: x(marginTween, (n) => `${fmt(n)}%`), tone: level(marginM.value, 10, 0),
                sw: { m: marginM, set: setOne("margin"), title: marginM.basis === "ttm" ? "Last 12 months net profit on sales" : `${fy} net profit on ${fy} sales` } },
              { id: "growth", label: "Revenue Growth", value: x(growthTween, (n) => `${n > 0 ? "+" : ""}${fmt(n)}%`), tone: level(growthM.value, 10, 0),
                sw: { m: growthM, set: setOne("growth"), title: growthM.basis === "ttm" ? "Last four quarters of sales against the four before" : `${fy} sales against the year before` } },
              ...(R && R.interest_coverage === null ? [] : [{ id: "cov", label: "Interest Coverage", value: x(covTween, (n) => `${fmt(n)}x`), tone: level(covM.value, 3, 1.5),
                sw: { m: covM, set: setOne("cov"), title: covM.basis === "ttm" ? "Last 12 months operating profit over interest paid" : `${fy} operating profit over interest paid` } } as Metric]),
            ];
            const card = (c: Metric) => (
              <Card key={c.id} className={c.sw?.m.both ? "relative" : ""}>
                <div className="flex items-center justify-between gap-2 text-xs" style={{ color: "var(--text-tertiary)" }}>
                  <span>{c.label}</span>
                </div>
                <div className="mt-1 text-lg font-semibold" style={{ color: c.tone === "good" ? GAIN : c.tone === "bad" ? LOSS : undefined, transition: "color 350ms ease" }}>{c.value ?? "—"}</div>
                {c.id === "pe" && peM.value == null && epsM.value != null && epsM.value <= 0 && (
                  <div className="mt-0.5 text-xs" style={{ color: "var(--text-tertiary)" }}>Negative earnings, so no P/E</div>
                )}
                {c.id === "pe" && peM.value != null && !peM.both && (
                  <div className="mt-0.5 text-xs" style={{ color: "var(--text-tertiary)" }}>
                    {peM.basis === "ttm" ? "Last 12 months" : `On the ${fy} annual report`}
                    {sectorPe && peM.basis === "ttm" ? <> · sector median <span className="nv-num">{fmt(sectorPe)}</span></> : null}
                  </div>
                )}
                {c.sw?.m.both && <BasisToggle basis={c.sw.m.basis} onChange={c.sw.set} title={c.sw.title} />}
              </Card>
            );
            return (
              <>
                <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">{primary.map(card)}</div>
                <div className="grid transition-[grid-template-rows] duration-500 ease-out" style={{ gridTemplateRows: showMore ? "1fr" : "0fr" }}>
                  <div className="-mx-1 overflow-hidden px-1" inert={!showMore}>
                    <div className="grid grid-cols-2 gap-4 pb-1 pt-4 transition-opacity duration-500 md:grid-cols-3 lg:grid-cols-5" style={{ opacity: showMore ? 1 : 0 }}>{more.map(card)}</div>
                  </div>
                </div>
                <div className="mt-4 flex justify-center">
                  <button
                    onClick={() => setShowMore((v) => !v)}
                    aria-expanded={showMore}
                    className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium"
                    style={{ color: "var(--text-secondary)", background: "var(--overlay-weak)" }}
                  >
                    {showMore ? "Show less" : "Show more"}
                    <ChevronDown className="h-3.5 w-3.5 transition-transform duration-500" style={{ transform: showMore ? "rotate(180deg)" : "none" }} />
                  </button>
                </div>
              </>
            );
          })()}
        </div>
      </section>

      <section className="border-t py-10" style={{ background: "var(--surface-0)", borderColor: "var(--border-subtle)" }}>
        <div className="mx-auto w-full max-w-7xl px-4">
          <SectionTitle>Price Range</SectionTitle>
          <div className="mb-4 grid gap-4 md:grid-cols-2">
            <RangeBar title="Today's Range" low={quote?.low ?? null} high={quote?.high ?? null} now={ltp} lowLabel={inr(quote?.low)} highLabel={inr(quote?.high)} />
            <RangeBar title={week52?.sinceListing ? "Range since listing (under 52 weeks of history)" : "52 Week Range"} low={week52?.low ?? null} high={week52?.high ?? null} now={ltp} lowLabel={inr(week52?.low)} highLabel={inr(week52?.high)} />
          </div>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            {([
              // Open: green when the stock opened above yesterday's close (a gap up), red below it
              ["Open", inr(quote?.open), quote?.open != null && quote?.close != null && quote.open !== quote.close ? (quote.open > quote.close ? "good" : "bad") : null],
              ["Prev Close", inr(quote?.close), null],
              ["Volume", quote?.volume == null ? "—" : quote.volume.toLocaleString("en-IN"), null],
              // VWAP: green when the price is above the day's volume-weighted average, red below it
              ["VWAP", vwap != null ? inr(vwap) : "—", vwap != null && ltp != null && ltp !== vwap ? (ltp > vwap ? "good" : "bad") : null],
            ] as [string, string, "good" | "bad" | null][]).map(([label, value, tone]) => (
              <Card key={label}>
                <div className="text-sm" style={{ color: "var(--text-secondary)" }}>{label}</div>
                <div className="mt-1 text-lg font-semibold" style={{ color: tone === "good" ? GAIN : tone === "bad" ? LOSS : undefined }}>{value}</div>
              </Card>
            ))}
          </div>
        </div>
      </section>

      <section className="border-t py-10" style={{ background: "var(--surface-1)", borderColor: "var(--border-subtle)" }}>
        <div className="mx-auto w-full max-w-7xl px-4">
          <SectionTitle>Returns Performance</SectionTitle>
          <div className={`grid grid-cols-2 gap-4 md:grid-cols-4 ${(returns?.length ?? 7) > 7 ? "xl:grid-cols-8" : "lg:grid-cols-7"}`}>
            {(returns ?? RETURNS.map(([label]) => ({ label, pct: null as number | null }))).map((r) => (
              <Card key={r.label} className="text-center">
                <div className="text-xs" style={{ color: "var(--text-secondary)" }}>{r.label}</div>
                <div className="mt-2 text-base font-semibold" style={{ color: r.pct == null ? "var(--text-tertiary)" : r.pct >= 0 ? GAIN : LOSS }}>
                  {r.pct == null ? "—" : `${r.pct >= 0 ? "+" : ""}${fmt(r.pct)}%`}
                </div>
              </Card>
            ))}
          </div>
        </div>
      </section>

      <section className="border-t py-10" style={{ background: "var(--surface-0)", borderColor: "var(--border-subtle)" }}>
        <div className="mx-auto grid w-full max-w-7xl gap-6 px-4 lg:grid-cols-2">
          <Card className="p-4 sm:p-6">
            <SectionTitle>Shareholding Pattern (in %)</SectionTitle>
            {overview === null ? <Loading /> : overview.shareholding ? <ShareholdingPattern data={overview.shareholding} symbol={sym} /> : <Unavailable what="Shareholding pattern" />}
          </Card>
          <Card className="p-4 sm:p-6">
            <SectionTitle>{finTab === "results" || finTab === "pat" ? "Financial Result (Amount in ₹ Lakhs)" : finTab === "fcf" ? "Financial Result (Amount in ₹ Crore)" : "Financial Result"}</SectionTitle>
            {overview === null ? <Loading /> : overview.quarterly?.length ? <QuarterlyResults quarters={overview.quarterly} tab={finTab} onTab={setFinTab} standalone={overview.basis === "standalone"} symbol={sym} fromYahoo={overview.source === "yahoo"} periodMonths={overview.period_months ?? null} /> : <Unavailable what="Quarterly financial results" />}
          </Card>
        </div>
      </section>

      <section className="border-t py-10" style={{ background: "var(--surface-1)", borderColor: "var(--border-subtle)" }}>
        <div className="mx-auto w-full max-w-7xl px-4">
          <SectionTitle>About {name}</SectionTitle>
          {overview === null && profile === null ? <Loading /> : <About profile={profile} fallbackText={overview?.about ?? null} />}
        </div>
      </section>

      <section className="border-t py-10" style={{ background: "var(--surface-0)", borderColor: "var(--border-subtle)" }}>
        <div className="mx-auto w-full max-w-7xl px-4">
          <SectionTitle>Peer Comparison</SectionTitle>
          {overview === null ? <Loading /> : overview.peers?.length ? (
            <>
              <PeerTable peers={overview.peers} current={stock.symbol} onSelect={onOpenStock ? openPeer : undefined} />
              {overview.peers_source === "mixed" && (
                <p className="mt-3 text-xs" style={{ color: "var(--text-tertiary)" }}>
                  Screener.in has no peer table for this company, so these are companies that {overview.peers_used?.length ? overview.peers_used.join(", ") : "several sources"} group with it, those that more sources agree on first and then closest in market cap. ROCE is Screener.in's where we have read it, otherwise worked out from Yahoo's latest annual statements (EBIT over total assets less current liabilities); a dash means neither is available.
                </p>
              )}
              {overview.peers_source === "sector" && (
                <p className="mt-3 text-xs" style={{ color: "var(--text-tertiary)" }}>
                  Screener.in has no peer table for this company, so these are companies in the same NSE sector closest in market cap. ROCE is Screener.in's where we have read it, otherwise worked out from Yahoo's latest annual statements; a dash means neither is available.
                </p>
              )}
            </>
          ) : (
            <Card>
              <Unavailable what="Peer comparison" />
              <p className="px-4 pb-4 text-center text-xs" style={{ color: "var(--text-tertiary)" }}>
                Peers come from Screener.in, our NSE sector list, or other companies in the same industry. This company has none of these yet: a very recent listing, or a BSE-listed company whose industry has not been classified yet (that runs in the background and can take hours).
              </p>
            </Card>
          )}
        </div>
      </section>
    </div>
  );
}
