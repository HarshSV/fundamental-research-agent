/**
 * The market-list scanners (patterns/market_lists.py on the backend) and the app-wide navigation events.
 * The backend is the source of truth for what each scanner computes; the names and definitions here are the same text, used by the
 * top menu, the home page and the results page before any request returns. Keep them in step with `SCANNERS` in market_lists.py.
 */
export const MULTI_ID = "multi";

export interface ListScanner {
  id: string;
  name: string;
  group: "Market lists" | "Volume" | "Gaps" | "Setups" | "Strength" | "Weakness";
  definition: string;
  /** which way "strongest first" runs for this scanner */
  note?: string;
}

export const LIST_SCANNERS: ListScanner[] = [
  { id: "top-gainers", name: "Top Gainers", group: "Market lists", definition: "Stocks that rose in the latest session, biggest gain first." },
  { id: "top-losers", name: "Top Losers", group: "Market lists", definition: "Stocks that fell in the latest session, biggest fall first." },
  { id: "volume-gainers", name: "Volume Gainers", group: "Volume", definition: "Latest session's volume at least 2x the average of the 20 sessions before it." },
  { id: "high-volume", name: "High Volume Stocks", group: "Volume", definition: "Stocks ranked by the value traded in the latest session (price x volume)." },
  { id: "gap-up", name: "Gap Up", group: "Gaps", definition: "Opened at least 2% above the previous close in the latest session." },
  { id: "gap-filling", name: "Gap Filling", group: "Gaps", definition: "Gapped up at least 2% in the last 15 sessions and has since come back into the gap without closing it completely." },
  { id: "inside-bar", name: "Inside Bar (daily)", group: "Setups", definition: "The latest session traded inside the previous session's high and low." },
  { id: "inside-bar-weekly", name: "Inside Bar (weekly)", group: "Setups", definition: "This week has traded inside last week's high and low." },
  { id: "inside-bar-filtered", name: "Filtered Inside Bar (daily)", group: "Setups", definition: "An inside bar whose range is at most 60% of the previous session's, with the price above its 50-day average." },
  { id: "inside-bar-weekly-filtered", name: "Filtered Inside Bar (weekly)", group: "Setups", definition: "A weekly inside bar at most 60% of last week's range, with the price above its 50-day average." },
  { id: "tight-setup", name: "Tight Setup (daily)", group: "Setups", definition: "The last 5 closes are within 2.5% of each other and the price is above its 50-day average." },
  { id: "tight-setup-weekly", name: "Tight Setup (weekly)", group: "Setups", definition: "The last 3 weekly closes are within 4% of each other and the price is above its 50-day average." },
  { id: "momentum", name: "Momentum", group: "Strength", definition: "Above the 50 and 200-day averages (50 over 200), RS rating 80+, within 15% of the 52-week high and up 20%+ in 3 months." },
  { id: "rs-high-before-price-high", name: "RS High Before Price High", group: "Strength", definition: "The relative-strength line (against the Nifty 500) is at a 52-week high while the price is still at least 2% under its own 52-week high." },
  { id: "shorting", name: "Shorting Scanner", group: "Weakness", definition: "Below the 50 and 200-day averages (50 under 200), RS rating 30 or less and within 15% of the 52-week low." },
];

export const LIST_SCANNER_IDS = new Set(LIST_SCANNERS.map((s) => s.id));
export const isListScanner = (id: string) => LIST_SCANNER_IDS.has(id);
export const scannerName = (id: string) => LIST_SCANNERS.find((s) => s.id === id)?.name ?? (id === "horizontal-resistance" ? "Horizontal Resistance" : id.replace(/-and-/g, " & ").replace(/-/g, " ").replace(/\b[a-z]/g, (c) => c.toUpperCase()));

// ---- navigation: the top bar and the page talk through one window event ----------------------------------------------------
export const OPEN_NAV_EVENT = "navrist-nav";
export type NavTarget =
  | { type: "scanner"; id: string }
  | { type: "multi" }
  | { type: "analytics"; tab: "sectors" | "rrg" | "breadth" }
  | { type: "sector"; name: string }
  | { type: "home"; scroll?: "patterns" };

export function navigateTo(target: NavTarget) {
  window.dispatchEvent(new CustomEvent(OPEN_NAV_EVENT, { detail: target }));
}
