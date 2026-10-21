import { fetchJson } from "@/lib/api";

export type PatternStatus = "forming" | "awaiting_breakout" | "confirmed" | "invalidated";

export interface Outcome {
  state: "positive" | "negative" | "flat" | "pending" | "not_evaluable";
  ret: number | null; // realised return after the horizon (fraction); null until it exists
  band: number | null;
}

export interface PatternOcc {
  occ_id: string;
  pattern: string;
  direction: "bullish" | "bearish" | null;
  category: string;
  maturity: "standard" | "experimental";
  status: PatternStatus;
  reason: string | null;
  anchor_ts: number;
  start_ts: number;
  end_ts: number;
  first_seen_ts: number;
  updated_ts: number;
  confirmed_ts: number | null;
  confirmed_price: number | null;
  breakout_level: number | null;
  invalidation_level: number | null;
  pivots: { ts: number; price: number; label: string }[];
  lines: { label: string | null; ts0: number; y0: number; ts1: number; y1: number }[];
  meta: Record<string, unknown>;
  history: { ts: number; status: PatternStatus; price: number | null; breakout_level: number | null; invalidation_level: number | null; reason: string | null }[];
  outcomes: Record<string, Outcome> | null;
}

export interface PatternsResponse {
  source: string;
  version: string;
  n_bars: number;
  note?: string;
  errors: Record<string, string>;
  counts: { by_status?: Record<string, number>; by_pattern?: Record<string, number> };
  occurrences: PatternOcc[];
}

export interface CatalogueEntry {
  id: string;
  name: string;
  category: string;
  maturity: string;
  definition: string;
}

export const STATUS_LABEL: Record<PatternStatus, string> = {
  forming: "Forming",
  awaiting_breakout: "Awaiting breakout",
  confirmed: "Confirmed",
  invalidated: "Invalidated",
};

// Formation status colours (kept apart from the realised-outcome colours on confirmed flags).
export const STATUS_COLOR: Record<PatternStatus, string> = {
  forming: "#94a3b8",
  awaiting_breakout: "#f59e0b",
  confirmed: "#a78bfa",
  invalidated: "#64748b",
};

export const OUTCOME_COLOR: Record<string, string> = {
  positive: "#10b981",
  negative: "#ef4444",
  pending: "#3b82f6",
  flat: "#94a3b8",
  not_evaluable: "#64748b",
};

export const OUTCOME_LABEL: Record<string, string> = {
  positive: "Positive",
  negative: "Negative",
  pending: "Pending",
  flat: "Flat",
  not_evaluable: "Not evaluable",
};

export type MarkerKind = "forming" | "awaiting" | "positive" | "negative" | "pending" | "flat" | "not_evaluable" | "invalidated";

/** Where and how one occurrence is drawn: its time and marker kind. */
export function markerOf(o: PatternOcc): { ts: number; kind: MarkerKind } {
  if (o.status === "confirmed") {
    const first = o.outcomes ? o.outcomes[Object.keys(o.outcomes)[0]] : null;
    return { ts: o.confirmed_ts ?? o.updated_ts, kind: (first?.state ?? "not_evaluable") as MarkerKind };
  }
  if (o.status === "invalidated") return { ts: o.history[o.history.length - 1]?.ts ?? o.updated_ts, kind: "invalidated" };
  return { ts: o.updated_ts, kind: o.status === "forming" ? "forming" : "awaiting" };
}

export function displayName(catalogue: Record<string, CatalogueEntry>, id: string): string {
  return catalogue[id]?.name ?? id.replace(/-and-/g, " & ").replace(/-/g, " ");
}

// A pattern run can take 10-30s the first time; one retry covers a provider hiccup without doubling the wait.
export const fetchPatterns = (sym: string, timeframe = "1d") =>
  fetchJson<PatternsResponse>(`/api/v1/patterns/${sym}?timeframe=${timeframe}`, {
    retries: 1,
    usable: (d) => d.source !== "unavailable" || timeframe !== "1d",
  });

export async function fetchCatalogue(): Promise<Record<string, CatalogueEntry>> {
  const d = await fetchJson<{ patterns: CatalogueEntry[] }>("/api/v1/patterns/catalogue");
  return Object.fromEntries(d.patterns.map((p) => [p.id, p]));
}
