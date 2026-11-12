import { fetchJson } from "@/lib/api";
import type { Cone } from "./cone";

export type Call = "up" | "down" | "even" | null;

/** Odds for one horizon, from the stock's own history. */
export interface Horizon {
  id: "session" | "week" | "month";
  label: string;
  call: Call;
  conviction?: "strong" | "moderate" | "slight" | null;
  price_low?: number;
  price_mid?: number;
  price_high?: number;
  up?: number;
  flat?: number;
  down?: number;
  p10?: number;
  median?: number;
  p90?: number;
  samples?: number;
  flat_band_pct?: number;
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
  trend_rule?: boolean;
  session_rule?: boolean;
}

export interface TradeBlock {
  decision: { action: string; reason: string | null };
  edge?: { value: number; label: "favourable" | "against" | "even" } | null;
  note?: string | null;
  basis?: "orb" | "range";
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
  session_late?: boolean; // under 45 minutes left: the plan looks to the next session
  session: string | null;
  adr20_pct: number | null;
  segment: string | null;
  outlook: Horizon[];
  today: TradeBlock;
  swing: TradeBlock;
  evidence: EvidenceRow[];
  levels?: { label: string; value: string; tone: "good" | "bad" | null }[];
  sizing?: { entry: number; stop: number; risk_per_share: number; basis: string } | null;
  liquidity: { turnover_cr: number | null; max_position_inr: number | null };
  source?: string;
}

export type FcWindow = "max" | "5y";
export const fetchForecast = (symbol: string, window: FcWindow = "max") => fetchJson<Forecast>(`/api/v1/outlook/${symbol}?window=${window}`, { retries: 1 });

/** Horizontal levels the forecast draws on the price chart: red / green / grey only. */
export interface ChartLevel {
  price: number;
  title: string;
  color: string;
  dashed?: boolean;
  group: "today" | "range" | "swing" | "wk52";
}

/** A price for a line label: paise for cheap stocks, whole rupees for dear ones. */
const lvl = (v: number) => `₹${v.toLocaleString("en-IN", { maximumFractionDigits: v < 100 ? 2 : 0 })}`;

/** All the forecast's lines, each tagged with its group so the page can show only the ones asked for. */
export function forecastLevels(f: Forecast | null): ChartLevel[] {
  const out: ChartLevel[] = [];
  if (!f) return out;
  const s = f.today?.setup;
  if (s?.range_high != null && s.range_low != null) {
    out.push({ price: s.range_high, title: `Range high ${lvl(s.range_high)}`, color: "#8b8b9a", dashed: true, group: "range" });
    out.push({ price: s.range_low, title: `Range low ${lvl(s.range_low)}`, color: "#8b8b9a", dashed: true, group: "range" });
  }
  for (const b of [f.today, f.swing]) {
    const p = b?.plan;
    if (!p) continue;
    const tag = b === f.swing ? "Swing " : "";
    const group = b === f.swing ? "swing" : "today";
    out.push({ price: p.entry, title: `${tag}Entry ${lvl(p.entry)}`, color: "#e5e7eb", group });
    out.push({ price: p.stop, title: `${tag}Stop ${lvl(p.stop)}`, color: "#ef4444", dashed: true, group });
    // every target of the plan, the nearer one brighter: "Target 1 (1x the risk)", "Target 2 (2x)"
    p.targets.slice(0, 2).forEach((t, i) => out.push({ price: t.price, title: `${tag}Target ${i + 1} (${t.r}x) ${lvl(t.price)}`, color: i === 0 ? "#10b981" : "#34d399", dashed: true, group }));
  }
  return out;
}

/** Sessions ahead for each outlook horizon. */
export const HORIZON_SESSIONS: Record<Horizon["id"], number> = { session: 1, week: 5, month: 20 };

/** The forecast as a fan for the price chart: where the price should land at each horizon, from the last price. Null when
 *  there is no price range to draw (too little history). The colour follows the week's lean, else the month's. */
export function forecastCone(f: Forecast | null): Cone | null {
  if (!f || f.price == null || !f.outlook) return null;
  const points = f.outlook
    .filter((h) => h.price_low != null && h.price_mid != null && h.price_high != null)
    .map((h) => ({ k: HORIZON_SESSIONS[h.id], low: h.price_low as number, mid: h.price_mid as number, high: h.price_high as number }))
    .sort((a, b) => a.k - b.k);
  if (points.length === 0 || points[points.length - 1].k < 5) return null;
  const lead = f.outlook.find((h) => h.id === "week" && h.call) ?? f.outlook.find((h) => h.id === "month" && h.call);
  return { anchor: f.price, tone: lead?.call === "up" ? "up" : lead?.call === "down" ? "down" : "even", points };
}
