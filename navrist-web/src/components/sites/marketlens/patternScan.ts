import { fetchJson } from "@/lib/api";
import type { PatternStatus } from "./patterns";
import { MULTI_ID, isListScanner, scannerName } from "./scanners";

export type Tab = "technicals" | "fundamentals" | "misc";

/** The scanners that are not one chart pattern. */
export const SCREENER_ID = "all";
export const RESISTANCE_ID = "horizontal-resistance";
export const isSpecial = (id: string) => id === SCREENER_ID || id === RESISTANCE_ID || id === MULTI_ID || isListScanner(id);

export interface RangeState {
  on: boolean;
  min: number | null;
  max: number | null;
}

/** One numeric range filter: its label, which tab it lives on and what it measures. `minOnly` filters are a single lower bound. */
export interface RangeDef {
  key: string;
  label: string;
  tab: Tab;
  unit?: string;
  minOnly?: boolean;
  hint?: string;
}

export const RANGE_DEFS: RangeDef[] = [
  { key: "pct_52w_low", label: "% from 52W low", tab: "technicals", unit: "%", hint: "How far above its 52-week low the price is" },
  { key: "pct_52w_high", label: "% from 52W high", tab: "technicals", unit: "%", hint: "How far below its 52-week high the price is" },
  { key: "pct_ath", label: "% from all-time high", tab: "technicals", unit: "%" },
  { key: "rs", label: "Overall RS rating", tab: "technicals", hint: "1-99: the stock's 3/6/9/12-month performance ranked against every scanned stock" },
  { key: "price", label: "Stock price", tab: "technicals", unit: "₹" },
  { key: "turnover", label: "Avg price × volume, 30 days", tab: "technicals", unit: "₹ Cr", minOnly: true, hint: "Average daily traded value: at least" },
  { key: "free_float", label: "Free float", tab: "technicals", unit: "%", hint: "100 minus promoter holding" },
  { key: "pe", label: "P/E ratio", tab: "fundamentals" },
  { key: "eps_growth", label: "EPS growth (annual CAGR)", tab: "fundamentals", unit: "%" },
  { key: "debt_equity", label: "Debt / Equity", tab: "fundamentals" },
  { key: "promoter", label: "Promoter holding", tab: "fundamentals", unit: "%" },
  { key: "div_yield", label: "Dividend yield", tab: "fundamentals", unit: "%" },
  { key: "net_profit", label: "Net profit (latest year)", tab: "fundamentals", unit: "₹ Cr" },
  { key: "ret_1m", label: "1 month return", tab: "misc", unit: "%" },
  { key: "ret_3m", label: "3 month return", tab: "misc", unit: "%" },
  { key: "ret_6m", label: "6 month return", tab: "misc", unit: "%" },
  { key: "ret_1y", label: "1 year return", tab: "misc", unit: "%" },
  { key: "ret_3y", label: "3 year return", tab: "misc", unit: "%" },
  { key: "ret_5y", label: "5 year return", tab: "misc", unit: "%" },
  { key: "avg_volume", label: "Avg volume, 30 days (shares)", tab: "misc", minOnly: true },
  { key: "volatility", label: "Volatility (annualised)", tab: "misc", unit: "%" },
  { key: "rvol", label: "Relative volume (RVOL)", tab: "misc", unit: "x", hint: "Latest session's volume divided by the average of the 20 sessions before it" },
  { key: "gap_pct", label: "Gap up % (open vs previous close)", tab: "misc", unit: "%", minOnly: true, hint: "How far the latest session opened above the previous close: at least" },
  { key: "range_20d", label: "20-day range", tab: "misc", unit: "%", hint: "Highest high over lowest low of the last 20 sessions, in %" },
  { key: "rs_1m", label: "1-month RS (1-99)", tab: "misc", hint: "The stock's 1-month return ranked against every scanned stock" },
  { key: "rs_3m", label: "3-month RS (1-99)", tab: "misc", hint: "The stock's 3-month return ranked against every scanned stock" },
  { key: "vs_ema10", label: "Price vs 10-day EMA", tab: "technicals", unit: "%", hint: "How far the price is above (+) or below (-) its 10-day EMA" },
];
export const MCAP_KEY = "mcap";

export type Quadrant = "leading" | "improving" | "weakening" | "lagging";

/** What the user ticked in the filter popup. Within one list a stock matches when it satisfies at least one ticked option;
 *  an empty selection / an unticked row means no restriction. */
export interface ScanFilters {
  indices: { values: string[] };
  sectors: { values: string[] };
  status: { values: PatternStatus[] };
  /** Create Screener only: show stocks that currently show any of these chart patterns (catalogue ids). */
  patterns: { values: string[] };
  /** Multiple Scans: a stock must appear in ALL of these scanners (chart pattern ids, "horizontal-resistance", market-list ids). */
  scans: { values: string[] };
  ema: { periods: number[]; side: "above" | "below" };
  dma: { periods: number[]; side: "above" | "below" };
  ranges: Record<string, RangeState>; // mcap + every RANGE_DEFS key
  nearHigh: { on: boolean; sessions: number };
  maOrder: { on: boolean; kind: "sma" | "ema"; periods: [number, number, number] };
  uptrend: { on: boolean; period: number; months: number };
  /** the 200-day average fell for a while and has just started rising, with the price above it */
  ma200Turn: { on: boolean };
  adr: { on: boolean; days: number; min: number | null };
  rrg: { on: boolean; quadrants: Quadrant[]; timeframe: "daily" | "weekly"; benchmark: "nifty50" | "nifty500" };
  resistance: { on: boolean; states: ("near" | "breakout")[] };
}

const off = (): RangeState => ({ on: false, min: null, max: null });

export const emptyFilters = (): ScanFilters => ({
  indices: { values: [] },
  sectors: { values: [] },
  status: { values: [] },
  patterns: { values: [] },
  scans: { values: [] },
  ema: { periods: [], side: "above" },
  dma: { periods: [], side: "above" },
  ranges: Object.fromEntries([MCAP_KEY, ...RANGE_DEFS.map((d) => d.key)].map((k) => [k, off()])),
  nearHigh: { on: false, sessions: 21 },
  maOrder: { on: false, kind: "sma", periods: [20, 50, 200] },
  uptrend: { on: false, period: 200, months: 1 },
  ma200Turn: { on: false },
  adr: { on: false, days: 5, min: null },
  rrg: { on: false, quadrants: ["leading", "improving"], timeframe: "daily", benchmark: "nifty50" },
  resistance: { on: false, states: ["near", "breakout"] },
});

/** Filters from an older saved copy, filled in with any filter added since. */
export const withDefaults = (f: Partial<ScanFilters> | null | undefined): ScanFilters => {
  const d = emptyFilters();
  if (!f) return d;
  return { ...d, ...f, ranges: { ...d.ranges, ...(f.ranges ?? {}) } };
};

export interface ScanOptions {
  indices: { id: string; label: string }[];
  sectors: string[];
  ma_periods: number[];
  statuses: { id: PatternStatus; label: string }[];
  market_cap_cr: { min: number | null; max: number | null };
  price: { min: number | null; max: number | null };
  near_high_sessions: number[];
  uptrend: { periods: number[]; months: number[] };
  adr_days: number[];
  rrg: { quadrants: Quadrant[]; timeframes: string[]; benchmarks: { id: string; label: string }[]; available: boolean };
  resistance_states: { id: string; label: string }[];
  fundamentals_have: number;
  fundamentals_as_of?: number | null; // when the typical stock's fundamentals were last read (unix seconds)
  fundamentals_yahoo?: number; // stocks whose P/E and dividend yield come from Yahoo Finance (Screener's page had no figures)
  fundamentals_stale?: number; // stocks whose fundamentals are older than 48 hours
}

export interface ScanOccurrence {
  pattern: string;
  status: PatternStatus;
  direction: "bullish" | "bearish" | null;
  start_ts: number | null;
  end_ts: number | null;
  confirmed_ts: number | null;
  breakout: number | null;
  invalidation: number | null;
  lines: { label: string | null; ts0: number; y0: number; ts1: number; y1: number }[];
}

export interface Resistance {
  level: number;
  touches: number;
  state: "near" | "breakout";
  dist_pct: number;
  first_ts: number;
  last_touch_ts: number;
  touch_ts: number[];
}

export interface ScanRow {
  symbol: string;
  name: string;
  sector: string;
  index: string | null;
  price: number | null;
  market_cap_cr: number | null;
  ret_1m: number | null;
  ret_3m: number | null;
  ret_1y: number | null;
  pct_from_52w_high: number | null;
  pct_from_52w_low: number | null;
  pct_from_ath: number | null;
  rs: number | null;
  turnover_30d_cr: number | null;
  adr5: number | null;
  pe: number | null;
  eps_growth: number | null;
  debt_equity: number | null;
  promoter: number | null;
  div_yield: number | null;
  net_profit_cr: number | null;
  free_float: number | null;
  quadrant: Quadrant | null;
  resistance: Resistance | null;
  as_of: number;
  occurrence: ScanOccurrence | null; // null for the pattern-less scanners
  /** market-list scanners: what the scanner measured for this stock */
  signal?: { value: number; text: string; note: string } | null;
  /** Multiple Scans: the scanners this stock appears in */
  matched?: string[] | null;
  occurrence_count: number;
  candles?: [number, number, number, number, number, number][]; // t, o, h, l, c, v
}

/** What a scanner row tells the stock page it opens: the pattern, its own lines and levels, and any horizontal resistance. */
export interface ScanContext {
  pattern: string | null; // a real chart pattern id, or null for the screener / resistance scans
  occurrence: ScanOccurrence | null;
  resistance: Resistance | null;
  showResistance: boolean;
}

export interface ScanStatus {
  prices_as_of?: number | null; // the close (unix seconds) most scanned prices belong to
  building: boolean;
  done: number;
  total: number;
  errors: number;
  have: number;
  universe: number;
}

export interface ScanResult {
  pattern: string;
  total: number;
  page: number;
  page_size: number;
  rows: ScanRow[];
  scan: ScanStatus;
}

export interface BacktestStats {
  n: number;
  win_rate?: number;
  avg?: number;
  median?: number;
  best?: number;
  worst?: number;
  avg_win?: number | null;
  avg_loss?: number | null;
  profit_factor?: number | null;
}

export interface BacktestResult {
  pattern: string;
  horizon: number;
  horizons: number[];
  stocks: number;
  stocks_with_trades: number;
  trades_total: number;
  directions: { bullish: number; bearish: number };
  stats: Record<string, BacktestStats>;
  histogram: { lo: number | null; hi: number | null; n: number }[];
  by_year: { year: number; n?: number; win_rate?: number; avg?: number }[];
  page: number;
  page_size: number;
  trades: { symbol: string; name: string; direction: "bullish" | "bearish"; confirmed_ts: number; entry: number; returns: Record<string, number | null> }[];
  scan: ScanStatus;
}

export const fetchScanOptions = () => fetchJson<ScanOptions>("/api/v1/pattern-scan/options");
export const fetchScanStatus = () => fetchJson<ScanStatus>("/api/v1/pattern-scan/status");

/** The request body the backend filter engine expects: only the filters that are switched on. */
export function serialize(f: ScanFilters): Record<string, unknown> {
  const b: Record<string, unknown> = {};
  if (f.indices.values.length) b.indices = f.indices;
  if (f.sectors.values.length) b.sectors = f.sectors;
  if (f.status.values.length) b.status = f.status;
  if (f.patterns.values.length) b.patterns = f.patterns;
  if (f.scans.values.length) b.scans = f.scans;
  if (f.ema.periods.length) b.ema = f.ema;
  if (f.dma.periods.length) b.dma = f.dma;
  for (const [k, r] of Object.entries(f.ranges)) if (r.on && (r.min != null || r.max != null)) b[k] = { min: r.min, max: r.max };
  if (f.nearHigh.on) b.near_high = { sessions: f.nearHigh.sessions };
  if (f.maOrder.on) b.ma_order = { kind: f.maOrder.kind, periods: f.maOrder.periods };
  if (f.uptrend.on) b.ma_uptrend = { period: f.uptrend.period, months: f.uptrend.months };
  if (f.ma200Turn?.on) b.ma200_turn = { require: true };
  if (f.adr.on && f.adr.min != null) b.adr = { days: f.adr.days, min: f.adr.min };
  if (f.rrg.on && f.rrg.quadrants.length) b.rrg = { quadrants: f.rrg.quadrants, timeframe: f.rrg.timeframe, benchmark: f.rrg.benchmark };
  if (f.resistance.on) b.resistance = { require: true, states: f.resistance.states };
  return b;
}

const post = (body: unknown) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const searchScan = (
  pattern: string,
  filters: ScanFilters,
  extra: { q: string; page: number; page_size: number; sort: string },
  includeCandles: boolean,
) =>
  fetchJson<ScanResult>(`/api/v1/pattern-scan/${pattern}/search?include_candles=${includeCandles}`, {
    retries: 1,
    init: post({ ...serialize(filters), ...extra }),
  });

export const fetchBacktest = (pattern: string, filters: ScanFilters, extra: { horizon: number; page: number; page_size: number }) =>
  fetchJson<BacktestResult>(`/api/v1/pattern-scan/${pattern}/backtest`, { retries: 1, init: post({ ...serialize(filters), ...extra }) });

/** A short human description of the active filters, for the chips under the page title. */
export function describeFilters(f: ScanFilters, opts: ScanOptions | null): string[] {
  const out: string[] = [];
  if (f.indices.values.length) out.push(f.indices.values.map((v) => opts?.indices.find((i) => i.id === v)?.label.split(" (")[0] ?? v).join(", "));
  if (f.sectors.values.length) out.push(f.sectors.values.join(", "));
  if (f.scans.values.length) out.push(`In all of: ${f.scans.values.map(scannerName).join(" + ")}`);
  if (f.patterns.values.length) out.push(`Patterns: ${f.patterns.values.map((v) => v.replace(/-and-/g, " & ").replace(/-/g, " ")).join(", ")}`);
  if (f.status.values.length) out.push(f.status.values.join(", ").replace(/_/g, " "));
  if (f.ema.periods.length) out.push(`Price ${f.ema.side} EMA ${f.ema.periods.join(", ")}`);
  if (f.dma.periods.length) out.push(`Price ${f.dma.side} DMA ${f.dma.periods.join(", ")}`);
  const defs = [{ key: MCAP_KEY, label: "Market cap", unit: "₹ Cr", minOnly: false }, ...RANGE_DEFS];
  for (const d of defs) {
    const r = f.ranges[d.key];
    if (!r?.on || (r.min == null && r.max == null)) continue;
    const u = d.unit ? ` ${d.unit}` : "";
    out.push(d.minOnly ? `${d.label} ≥ ${r.min?.toLocaleString("en-IN")}${u}` : `${d.label} ${r.min != null ? r.min.toLocaleString("en-IN") : "…"} – ${r.max != null ? r.max.toLocaleString("en-IN") : "…"}${u}`);
  }
  if (f.nearHigh.on) out.push(`New 52W high within ${f.nearHigh.sessions} sessions`);
  if (f.maOrder.on) out.push(`${f.maOrder.periods.map((p) => `${p}${f.maOrder.kind === "sma" ? "MA" : "EMA"}`).join(" ≥ ")}`);
  if (f.ma200Turn?.on) out.push("200-day average turning up");
  if (f.uptrend.on) out.push(`${f.uptrend.period} MA rising ≥ ${f.uptrend.months} month${f.uptrend.months > 1 ? "s" : ""}`);
  if (f.adr.on && f.adr.min != null) out.push(`${f.adr.days}-day ADR > ${f.adr.min}%`);
  if (f.rrg.on) out.push(`${f.rrg.quadrants.join("/")} sectors (${f.rrg.timeframe}, vs ${f.rrg.benchmark === "nifty50" ? "Nifty 50" : "Nifty 500"})`);
  if (f.resistance.on) out.push(`Horizontal resistance: ${f.resistance.states.join(" / ")}`);
  return out;
}

// ---- saved filters (this browser only)
const SAVED_KEY = "navrist_saved_filters";
export interface SavedFilter {
  name: string;
  pattern: string;
  filters: ScanFilters;
  isDefault: boolean;
}

export function loadSaved(): SavedFilter[] {
  try {
    const raw = JSON.parse(localStorage.getItem(SAVED_KEY) ?? "[]");
    return Array.isArray(raw) ? raw.filter((x) => x && typeof x.name === "string").map((x) => ({ ...x, filters: withDefaults(x.filters) })) : [];
  } catch {
    return [];
  }
}

export function saveFilter(s: SavedFilter) {
  try {
    const all = loadSaved().filter((x) => x.name !== s.name).map((x) => (s.isDefault ? { ...x, isDefault: false } : x));
    localStorage.setItem(SAVED_KEY, JSON.stringify([s, ...all]));
  } catch {
    /* storage unavailable: saving just does not persist */
  }
}

export function deleteSaved(name: string) {
  try {
    localStorage.setItem(SAVED_KEY, JSON.stringify(loadSaved().filter((x) => x.name !== name)));
  } catch {
    /* ignore */
  }
}

/** A code another person can paste into Load > Import to get the same filters. */
export const shareCode = (pattern: string, f: ScanFilters) => btoa(unescape(encodeURIComponent(JSON.stringify({ v: 1, pattern, filters: f }))));
export function parseShareCode(code: string): { pattern: string; filters: ScanFilters } | null {
  try {
    const o = JSON.parse(decodeURIComponent(escape(atob(code.trim()))));
    return o && typeof o.pattern === "string" ? { pattern: o.pattern, filters: withDefaults(o.filters) } : null;
  } catch {
    return null;
  }
}
