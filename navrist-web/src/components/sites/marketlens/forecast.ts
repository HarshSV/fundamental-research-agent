import { fetchJson } from "@/lib/api";

export type Call = "up" | "down" | "none" | null;

/** Odds for one horizon, from the stock's own history. */
export interface Horizon {
  id: "session" | "week" | "month";
  label: string;
  call: Call;
  up?: number;
  flat?: number;
  down?: number;
  p10?: number;
  median?: number;
  p90?: number;
  samples?: number;
  basis?: "state" | "all" | "sessions";
  reason?: string;
}

export interface Plan {
  side: "long" | "short";
  action: string; // "Buy above" / "Sell short below" / "Buy at"
  entry: number;
  stop: number;
  risk_per_share: number;
  risk_pct: number;
  targets: { r: number; price: number }[];
  first_target_r: number;
  stop_basis: string;
  exit_rule: string;
  warnings: string[];
}

export interface Odds {
  enters: number;
  target: number | null;
  stop: number | null;
  open: number | null;
  paths: number;
}

export interface Replay {
  // intraday rule replay
  sessions?: number;
  trades?: number;
  target?: number;
  stop?: number;
  open?: number;
  // daily setup replay
  n?: number;
  win?: number | null;
  median?: number | null;
  avg?: number | null;
  horizon?: number;
}

export interface TradeBlock {
  decision: { action: string; reason: string | null };
  plan?: Plan | null;
  odds?: Odds | null;
  replay?: Replay | null;
  setup?: {
    state?: string;
    range_high?: number | null;
    range_low?: number | null;
    label?: string;
    level?: number | null;
  };
}

export interface EvidenceRow {
  label: string;
  value: string;
  tone: "good" | "bad" | null;
}

export interface EventItem {
  ts: string; // local (IST) ISO time
  source: "NSE" | "BSE" | "News";
  category: string;
  title: string;
  link: string | null;
}

export interface Events {
  items: EventItem[];
  upcoming: { date: string; purpose: string; detail: string }[];
  sources: Record<string, "ok" | "unavailable">;
}

export interface Forecast {
  symbol: string;
  price: number | null;
  market_open: boolean;
  session: string | null;
  adr20_pct: number | null;
  segment: string | null;
  outlook: Horizon[];
  today: TradeBlock;
  swing: TradeBlock;
  evidence: EvidenceRow[];
  events?: Events;
  liquidity: { turnover_cr: number | null; max_position_inr: number | null };
  source?: string;
}

export const fetchForecast = (symbol: string) => fetchJson<Forecast>(`/api/v1/outlook/${symbol}`, { retries: 1 });

/** Horizontal levels the forecast draws on the price chart: red / green / grey only. */
export interface ChartLevel {
  price: number;
  title: string;
  color: string;
  dashed?: boolean;
}

export function forecastLevels(f: Forecast | null): ChartLevel[] {
  const out: ChartLevel[] = [];
  if (!f) return out;
  const s = f.today?.setup;
  if (s?.range_high != null && s.range_low != null) {
    out.push({ price: s.range_high, title: "Range high", color: "#8b8b9a", dashed: true });
    out.push({ price: s.range_low, title: "Range low", color: "#8b8b9a", dashed: true });
  }
  for (const b of [f.today, f.swing]) {
    const p = b?.plan;
    if (!p) continue;
    out.push({ price: p.entry, title: "Entry", color: "#e5e7eb" });
    out.push({ price: p.stop, title: "Stop", color: "#ef4444", dashed: true });
    out.push({ price: p.targets.find((t) => t.r === p.first_target_r)?.price ?? p.targets[0].price, title: "Target", color: "#10b981", dashed: true });
  }
  return out;
}
