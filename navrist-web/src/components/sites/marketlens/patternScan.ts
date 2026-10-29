import { fetchJson } from "@/lib/api";
import type { PatternStatus } from "./patterns";

/** What the user ticked in the filter popup. Within one filter a stock matches when it satisfies at least one ticked
 *  option; an empty selection means no restriction. */
export interface ScanFilters {
  indices: { values: string[] };
  mcap: { min: number | null; max: number | null }; // Rs crore
  ema: { periods: number[]; side: "above" | "below" };
  dma: { periods: number[]; side: "above" | "below" };
  sectors: { values: string[] };
  status: { values: PatternStatus[] };
}

export const EMPTY_FILTERS: ScanFilters = {
  indices: { values: [] },
  mcap: { min: null, max: null },
  ema: { periods: [], side: "above" },
  dma: { periods: [], side: "above" },
  sectors: { values: [] },
  status: { values: [] },
};

export interface ScanOptions {
  indices: { id: string; label: string }[];
  sectors: string[];
  ma_periods: number[];
  statuses: { id: PatternStatus; label: string }[];
  market_cap_cr: { min: number | null; max: number | null };
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

export interface ScanRow {
  symbol: string;
  name: string;
  sector: string;
  index: string | null;
  price: number | null;
  market_cap_cr: number | null;
  ret_1m: number | null;
  ret_3m: number | null;
  pct_from_52w_high: number | null;
  as_of: number;
  occurrence: ScanOccurrence;
  occurrence_count: number;
  candles?: [number, number, number, number, number, number][]; // t, o, h, l, c, v
}

export interface ScanStatus {
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

export const fetchScanOptions = () => fetchJson<ScanOptions>("/api/v1/pattern-scan/options");
export const fetchScanStatus = () => fetchJson<ScanStatus>("/api/v1/pattern-scan/status");

export const searchScan = (
  pattern: string,
  filters: ScanFilters,
  extra: { q: string; page: number; page_size: number; sort: string },
  includeCandles: boolean,
) =>
  fetchJson<ScanResult>(`/api/v1/pattern-scan/${pattern}/search?include_candles=${includeCandles}`, {
    retries: 1,
    init: {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...filters,
        // empty selections mean "no restriction", so they are not sent as filters at all
        indices: filters.indices.values.length ? filters.indices : undefined,
        sectors: filters.sectors.values.length ? filters.sectors : undefined,
        status: filters.status.values.length ? filters.status : undefined,
        ema: filters.ema.periods.length ? filters.ema : undefined,
        dma: filters.dma.periods.length ? filters.dma : undefined,
        ...extra,
      }),
    },
  });

/** A short human description of the active filters, for the chips under the page title. */
export function describeFilters(f: ScanFilters, opts: ScanOptions | null): string[] {
  const out: string[] = [];
  if (f.indices.values.length)
    out.push(f.indices.values.map((v) => opts?.indices.find((i) => i.id === v)?.label.split(" (")[0] ?? v).join(", "));
  if (f.mcap.min != null || f.mcap.max != null)
    out.push(`Market cap ${f.mcap.min != null ? `≥ ₹${f.mcap.min.toLocaleString("en-IN")} Cr` : ""}${f.mcap.min != null && f.mcap.max != null ? " and " : ""}${f.mcap.max != null ? `≤ ₹${f.mcap.max.toLocaleString("en-IN")} Cr` : ""}`);
  if (f.ema.periods.length) out.push(`Price ${f.ema.side} EMA ${f.ema.periods.join(", ")}`);
  if (f.dma.periods.length) out.push(`Price ${f.dma.side} DMA ${f.dma.periods.join(", ")}`);
  if (f.sectors.values.length) out.push(f.sectors.values.join(", "));
  if (f.status.values.length) out.push(f.status.values.join(", ").replace(/_/g, " "));
  return out;
}
