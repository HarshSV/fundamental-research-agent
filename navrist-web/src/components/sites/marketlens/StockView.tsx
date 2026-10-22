"use client";

import { ArrowLeft, Eye, EyeOff, TrendingDown, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { fetchJson, searchSymbols, type CompanyHit } from "@/lib/api";
import { ActiveSetups } from "./ActiveSetups";
import { Dropdown } from "./Dropdown";
import { About, PeerTable, QuarterlyResults, ShareholdingPattern, Unavailable, type FinTab, type Overview, type Profile } from "./OverviewSections";
import {
  STATUS_COLOR, STATUS_LABEL, displayName, fetchCatalogue, fetchPatterns,
  type CatalogueEntry, type PatternOcc, type PatternStatus, type PatternsResponse,
} from "./patterns";
import { Detail as PatternDetail, PriceChart, type Candle } from "./PriceChart";

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

const RANGES = ["1D", "1W", "1M", "3M", "6M", "1Y", "5Y"] as const;
type Range = (typeof RANGES)[number];

const DAY = 86400;
const RANGE_DAYS: Record<string, number> = { "1M": 30, "3M": 91, "6M": 182, "1Y": 365, "5Y": 1826 };

/** What to load for a range. `tf` is the pattern-agent timeframe that matches the bars drawn, so the
 *  flags always sit on the same candles. `days` = daily bars sliced to that many days (null = intraday).
 *  LIVE keeps the same range but polls; for 1M it also switches to finer (hourly) bars. */
interface Spec { interval: string; period: string; tf: string; everyMs: number | null; days: number | null }
function specFor(range: Range, live: boolean): Spec {
  // 1D uses 1-minute bars and 1W 5-minute bars (about 375 points a session, like the reference site's
  // roughly-per-minute series). The pattern agent still runs on 5m / 15m bars; those timestamps are a
  // subset of the finer bars, so the flags land on the same candles.
  if (range === "1D") return { interval: "1m", period: "1d", tf: "5m", everyMs: live ? 5000 : null, days: null };
  if (range === "1W") return { interval: "5m", period: "5d", tf: "15m", everyMs: live ? 5000 : null, days: null };
  if (range === "1M" && live) return { interval: "60m", period: "1mo", tf: "60m", everyMs: 15000, days: null };
  return { interval: "1d", period: "5y", tf: "1d", everyMs: live ? 30000 : null, days: RANGE_DAYS[range] };
}
const BAR_SECONDS: Record<string, number> = { "1m": 60, "5m": 300, "15m": 900, "60m": 3600, "1d": 86400 };

/** NSE cash-market hours: Mon-Fri 09:15-15:30 IST. */
function marketOpen(now = new Date()): boolean {
  const ist = new Date(now.getTime() + (330 + now.getTimezoneOffset()) * 60000);
  const day = ist.getDay();
  const mins = ist.getHours() * 60 + ist.getMinutes();
  return day >= 1 && day <= 5 && mins >= 9 * 60 + 15 && mins <= 15 * 60 + 30;
}

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
const inr = (v: number | null | undefined) => (v == null ? "—" : `₹${fmt(v)}`);

// All data calls retry transient failures (network error, 5xx, provider returning nothing) before giving up.
const getJson = <T,>(path: string) => fetchJson<T>(path);

async function getCandles(sym: string, interval: string, period: string): Promise<Candle[]> {
  const d = await fetchJson<{ candles?: Candle[] }>(`/api/live-chart/${sym}?interval=${interval}&period=${period}`, {
    usable: (x) => (x.candles?.length ?? 0) > 1,
  });
  return d.candles ?? [];
}

function SectionTitle({ children, aside }: { children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <div className="h-6 w-1 rounded-full" style={{ background: "var(--accent-muted, #635ec8)" }} />
        <h2 className="text-xl font-semibold">{children}</h2>
      </div>
      {aside}
    </div>
  );
}

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={`rounded-xl border p-4 ${className}`}
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

export function StockView({ stock, onBack, onOpenStock }: { stock: CompanyHit; onBack: () => void; onOpenStock?: (s: CompanyHit) => void }) {
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
  const [live, setLive] = useState(false);
  const [liveAt, setLiveAt] = useState<Date | null>(null);
  const [error, setError] = useState("");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [finTab, setFinTab] = useState<FinTab>("results");
  const [profile, setProfile] = useState<Profile | null>(null);
  // Basic (non-TTM) EPS from the latest Annual Report. undefined = still loading, null eps = not available.
  const [annualEps, setAnnualEps] = useState<{ eps: number | null; period: string | null; basis?: string | null } | undefined>(undefined);
  const [showPatterns, setShowPatterns] = useState(true);
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
    getJson<Overview>(`/api/v1/stock-overview/${sym}`).then((o) => live && setOverview(o)).catch(fail);
    getJson<Profile>(`/api/v1/stock-profile/${sym}`).then((p) => live && setProfile(p)).catch(() => {});
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
            if (spec.days === null && marketOpen()) {
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

  // Pattern agent (backend): occurrences with their status lifecycle, per timeframe. The first run
  // for a stock/timeframe replays its history and can take ~10-30s; later requests come from the store.
  const [patternsByTf, setPatternsByTf] = useState<Record<string, PatternsResponse>>({});
  const [patternErrors, setPatternErrors] = useState<Record<string, string>>({});
  const [catalogue, setCatalogue] = useState<Record<string, CatalogueEntry>>({});
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
  const [patternFilter, setPatternFilter] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    fetchCatalogue().then((c) => alive && setCatalogue(c)).catch(() => {});
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
    const timer = live && spec.days === null ? setInterval(run, 60000) : null;
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [sym, spec.tf, spec.days, live]);

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

  const isIntraday = spec.days === null;
  const series = useMemo(() => {
    if (isIntraday) {
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
  }, [isIntraday, bars, specKey, daily, spec.days, live, ticks, spec.interval]);

  // While a new range loads, keep the previous chart on screen (with a spinner) so the switch can morph
  // from the old shape to the new one instead of flashing a blank "Loading…" box. This is React's
  // "adjust state while rendering" pattern: guarded, so it settles in one extra pass.
  const seriesKey = isIntraday ? specKey : `d${spec.days}`;
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
    return RETURNS.map(([label, key]) => {
      const b = bases[key];
      return { label, pct: end != null && b ? (end / b.price - 1) * 100 : null };
    });
  })();

  const week52 = useMemo(() => {
    if (!daily?.length) return null;
    const cutoff = daily[daily.length - 1].time - 365 * DAY;
    if (daily[0].time > cutoff + 7 * DAY) return null;
    const win = daily.filter((c) => c.time >= cutoff);
    return { low: Math.min(...win.map((c) => c.low)), high: Math.max(...win.map((c) => c.high)) };
  }, [daily]);

  // All-time extremes come from the backend's FULL price history (split/bonus-adjusted, not
  // dividend-adjusted), not from the 5-year chart window.
  const allTime =
    overview?.all_time_high && overview?.all_time_low
      ? { low: overview.all_time_low.price, high: overview.all_time_high.price }
      : null;

  const pct = quote?.change_pct;
  const up = (pct ?? 0) >= 0;
  const ltp = quote?.ltp ?? null;
  // P/E = live price / Basic EPS (non-TTM) from the latest audited Annual Report, only when that EPS is positive
  // (negative or unknown earnings give "—", never a made-up number).
  const annEps = annualEps?.eps ?? null;
  const pe = annEps != null && annEps > 0 && ltp ? ltp / annEps : null;
  const arYear = annualEps?.period?.slice(-4);

  return (
    <div className="w-full">
      <section className="mx-auto w-full max-w-7xl px-4 pb-8 pt-8">
        <button onClick={onBack} className="mb-5 flex items-center gap-2 text-sm hover:text-[var(--accent)]" style={{ color: "var(--text-secondary)" }}>
          <ArrowLeft className="h-4 w-4" /> Back to search
        </button>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-bold tracking-tight">{name}</h1>
          {stock.primary_exchange ? (
            <span className="rounded-full border px-3 py-0.5 text-xs" style={{ color: "var(--text-tertiary)", borderColor: "var(--border-default)" }}>
              {String(stock.primary_exchange)}
            </span>
          ) : null}
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
                <button
                  onClick={() => setLive((v) => !v)}
                  title={live ? "Live updates on — click to turn off" : "Turn on live updates for the selected range"}
                  className="flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-semibold transition-colors"
                  style={{ background: live ? "#dc2626" : "transparent", color: live ? "#fff" : "var(--text-secondary)" }}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${live ? "animate-pulse" : ""}`} style={{ background: live ? "#fff" : "#ef4444" }} />
                  LIVE
                </button>
                {RANGES.map((r) => {
                  const active = range === r;
                  return (
                    <button
                      key={r}
                      onClick={() => setRange(r)}
                      className="rounded-full px-3.5 py-1.5 text-xs font-medium transition-colors"
                      style={{ background: active ? "#b7b4e7" : "transparent", color: active ? "var(--on-accent)" : "var(--text-secondary)" }}
                    >
                      {r}
                    </button>
                  );
                })}
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
          <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
            <button
              onClick={() => {
                setShowPatterns((v) => !v);
                setSelectedId(null);
              }}
              aria-pressed={showPatterns}
              title={showPatterns ? "Hide pattern markers" : "Show pattern markers"}
              className="flex items-center gap-1.5 rounded-full border px-3 py-1 font-semibold transition-colors"
              style={{
                borderColor: showPatterns ? "#b7b4e7" : "var(--border-default)",
                color: showPatterns ? "#b7b4e7" : "var(--text-tertiary)",
                background: showPatterns ? "#b7b4e71a" : "transparent",
              }}
            >
              {showPatterns ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
              Patterns {showPatterns ? "on" : "off"}
            </button>
            {showPatterns && (Object.keys(STATUS_LABEL) as PatternStatus[]).map((s) => (
              <button
                key={s}
                onClick={() => setStatusOn((cur) => ({ ...cur, [s]: !cur[s] }))}
                className="rounded-full border px-2.5 py-1 transition-colors"
                style={{
                  borderColor: statusOn[s] ? STATUS_COLOR[s] : "var(--border-default)",
                  color: statusOn[s] ? STATUS_COLOR[s] : "var(--text-tertiary)",
                  background: statusOn[s] ? `${STATUS_COLOR[s]}1a` : "transparent",
                }}
              >
                {STATUS_LABEL[s]}
                {patterns?.counts.by_status?.[s] != null ? ` (${patterns.counts.by_status[s]})` : ""}
              </button>
            ))}
            {showPatterns && (
              <Dropdown
                ariaLabel="Filter by pattern"
                value={patternFilter}
                onChange={setPatternFilter}
                options={[
                  { value: "all", label: "All patterns" },
                  ...Object.entries(patterns?.counts.by_pattern ?? {})
                    .map(([id, n]) => ({ value: id, label: displayName(catalogue, id), hint: String(n) }))
                    .sort((a, b) => a.label.localeCompare(b.label)),
                ]}
              />
            )}
            {showPatterns && (
              <span className="ml-auto" style={{ color: "var(--text-tertiary)" }}>
                {patterns !== null
                  ? `${shownOccs.length} shown · ${spec.tf} bars`
                  : patternError
                    ? `Pattern agent unavailable (${patternError}) — it will retry; or switch range and back`
                    : `Pattern agent running on ${spec.tf} bars… (first run can take up to ~30s)`}
              </span>
            )}
          </div>
          {shown === null ? (
            <div className="flex h-[320px] items-center justify-center text-sm" style={{ color: "var(--text-tertiary)" }}>Loading chart…</div>
          ) : shown.length > 1 ? (
            <div className="relative">
            <PriceChart
              candles={shown}
              dataKey={shownKey}
              intraday={isIntraday}
              live={live}
              occs={showPatterns ? shownOccs : []}
              catalogue={catalogue}
              selectedId={selectedId}
              onSelect={setSelectedId}
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
          {showPatterns && selectedOcc && (
            <Card className="mt-4">
              <div className="flex items-start justify-between gap-3">
                <div className="text-base font-semibold">
                  {displayName(catalogue, selectedOcc.pattern)}
                  <span className="ml-2 text-xs font-normal" style={{ color: STATUS_COLOR[selectedOcc.status] }}>{STATUS_LABEL[selectedOcc.status]}</span>
                </div>
                <button onClick={() => setSelectedId(null)} aria-label="Close details" className="px-1 text-lg leading-none" style={{ color: "var(--text-tertiary)" }}>×</button>
              </div>
              <PatternDetail o={selectedOcc} catalogue={catalogue} />
            </Card>
          )}
          {showPatterns && <ActiveSetups occs={activeOccs} catalogue={catalogue} ltp={ltp} selectedId={selectedId} onSelect={setSelectedId} />}
        </div>
      </section>

      <section className="border-t py-10" style={{ background: "var(--surface-1)", borderColor: "var(--border-subtle)" }}>
        <div className="mx-auto w-full max-w-7xl px-4">
          <SectionTitle>Key Metrics</SectionTitle>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
            {[
              ["Market Cap", overview?.market_cap_cr != null ? `₹${fmt(overview.market_cap_cr)} Cr` : null],
              ["P/E Ratio", annualEps === undefined ? "…" : pe != null ? fmt(pe) : null],
              [`${arYear ? `EPS (FY${arYear.slice(-2)}` : "EPS (annual"}${annualEps?.basis === "standalone" ? ", standalone" : ""})`, annualEps === undefined ? "…" : annEps != null ? `₹${fmt(annEps)}` : null],
              ["Face Value", overview?.face_value != null ? `₹${fmt(overview.face_value, overview.face_value % 1 ? 2 : 0)}` : null],
              ["All Time High", allTime ? inr(allTime.high) : null],
              ["All Time Low", allTime ? inr(allTime.low) : null],
              ["Debt/Equity", overview?.debt_to_equity != null ? fmt(overview.debt_to_equity) : null],
            ].map(([label, value]) => (
              <Card key={label as string}>
                <div className="text-xs" style={{ color: "var(--text-tertiary)" }}>{label}</div>
                <div className="mt-1 text-lg font-semibold">{value ?? "—"}</div>
              </Card>
            ))}
          </div>
        </div>
      </section>

      <section className="border-t py-10" style={{ background: "var(--surface-0)", borderColor: "var(--border-subtle)" }}>
        <div className="mx-auto w-full max-w-7xl px-4">
          <SectionTitle>Price Range</SectionTitle>
          <div className="mb-4 grid gap-4 md:grid-cols-2">
            <RangeBar title="Today's Range" low={quote?.low ?? null} high={quote?.high ?? null} now={ltp} lowLabel={inr(quote?.low)} highLabel={inr(quote?.high)} />
            <RangeBar title="52 Week Range" low={week52?.low ?? null} high={week52?.high ?? null} now={ltp} lowLabel={inr(week52?.low)} highLabel={inr(week52?.high)} />
          </div>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            {[
              ["Open", inr(quote?.open)],
              ["Prev Close", inr(quote?.close)],
              ["Volume", quote?.volume == null ? "—" : quote.volume.toLocaleString("en-IN")],
              ["VWAP", vwap != null ? inr(vwap) : "—"],
            ].map(([label, value]) => (
              <Card key={label}>
                <div className="text-sm" style={{ color: "var(--text-secondary)" }}>{label}</div>
                <div className="mt-1 text-lg font-semibold">{value}</div>
              </Card>
            ))}
          </div>
        </div>
      </section>

      <section className="border-t py-10" style={{ background: "var(--surface-1)", borderColor: "var(--border-subtle)" }}>
        <div className="mx-auto w-full max-w-7xl px-4">
          <SectionTitle>Returns Performance</SectionTitle>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4 lg:grid-cols-7">
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
          <Card className="p-6">
            <SectionTitle>Shareholding Pattern (in %)</SectionTitle>
            {overview === null ? <Loading /> : overview.shareholding ? <ShareholdingPattern data={overview.shareholding} /> : <Unavailable what="Shareholding pattern" />}
          </Card>
          <Card className="p-6">
            <SectionTitle>{finTab === "results" ? "Financial Result (Amount in ₹ Lakhs)" : "Financial Result"}</SectionTitle>
            {overview === null ? <Loading /> : overview.quarterly?.length ? <QuarterlyResults quarters={overview.quarterly} tab={finTab} onTab={setFinTab} /> : <Unavailable what="Quarterly financial results" />}
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
          {overview === null ? <Loading /> : overview.peers?.length ? <PeerTable peers={overview.peers} current={stock.symbol} onSelect={onOpenStock ? openPeer : undefined} /> : <Card><Unavailable what="Peer comparison" /></Card>}
        </div>
      </section>
    </div>
  );
}
