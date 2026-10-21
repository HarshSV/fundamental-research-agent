import { fetchJson } from "@/lib/api";

export interface UniverseStatus {
  building: boolean;
  done: number;
  total: number;
  have: number; // companies with data
  universe: number; // companies in the screened universe
}

export interface ScreenDef {
  id: string;
  group: string;
  title: string;
  description: string;
  criteria: string[];
  count: number | null; // null until the universe has data
}

export interface ScreensResponse {
  groups: string[];
  universe: UniverseStatus;
  screens: ScreenDef[];
}

export interface StockRow {
  symbol: string;
  name: string;
  price?: number | null;
  market_cap_cr?: number | null;
  pe?: number | null;
  eps?: number | null;
  ret_1y?: number | null;
  matched?: Record<string, number | null>;
  [key: string]: unknown;
}

export interface ScreenResult {
  id: string;
  title: string;
  description: string;
  criteria: string[];
  universe: UniverseStatus;
  stocks: StockRow[];
}

export interface SectorResult {
  name: string;
  count: number;
  stocks: StockRow[];
  universe: UniverseStatus;
}

export interface SectorInfo {
  name: string;
  count: number;
}

export const fetchSectors = () => fetchJson<SectorInfo[]>("/api/v1/sectors");
export const fetchSector = (name: string) => fetchJson<SectorResult>(`/api/v1/sectors/${encodeURIComponent(name)}`);
export const fetchScreens = () => fetchJson<ScreensResponse>("/api/v1/screens");
export const fetchScreen = (id: string) => fetchJson<ScreenResult>(`/api/v1/screens/${id}`);
export async function startUniverseBuild(): Promise<void> {
  await fetchJson("/api/v1/screens/build", { init: { method: "POST" }, retries: 0 });
}

// How each metric a screen can match on is labelled and formatted.
export const METRIC_FMT: Record<string, { label: string; fmt: (v: number) => string }> = {
  price: { label: "Price", fmt: (v) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 2 })}` },
  eps: { label: "EPS (TTM)", fmt: (v) => `₹${v.toFixed(2)}` },
  pe: { label: "P/E", fmt: (v) => v.toFixed(1) },
  promoter: { label: "Promoter", fmt: (v) => `${v.toFixed(1)}%` },
  div_yield: { label: "Div. yield", fmt: (v) => `${v.toFixed(2)}%` },
  payout: { label: "Payout", fmt: (v) => `${v.toFixed(0)}%` },
  cover: { label: "Div. cover", fmt: (v) => `${v.toFixed(1)}x` },
  debt_equity: { label: "Debt/Equity", fmt: (v) => v.toFixed(2) },
  net_profit_cr: { label: "Net profit", fmt: (v) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })} Cr` },
  eps_growth: { label: "EPS growth/yr", fmt: (v) => `${v.toFixed(1)}%` },
  ret_1m: { label: "1M return", fmt: (v) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}%` },
  ret_1y: { label: "1Y return", fmt: (v) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}%` },
  ret_3y: { label: "3Y return", fmt: (v) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}%` },
  ret_5y: { label: "5Y return", fmt: (v) => `${v >= 0 ? "+" : ""}${v.toFixed(1)}%` },
  avg_volume: { label: "Avg volume", fmt: (v) => v.toLocaleString("en-IN", { maximumFractionDigits: 0 }) },
  volatility: { label: "Volatility", fmt: (v) => `${v.toFixed(1)}%` },
  market_cap_cr: { label: "Market cap", fmt: (v) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })} Cr` },
};
