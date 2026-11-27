/**
 * The market-list scanners (patterns/market_lists.py on the backend) and the app-wide navigation events.
 * The backend is the source of truth for what each scanner computes; the names and definitions here are the same text, used by the
 * top menu, the home page and the results page before any request returns. Keep them in step with `SCANNERS` in market_lists.py.
 */
export const MULTI_ID = "multi";

export interface ListScanner {
  id: string;
  name: string;
  group: "Market lists" | "Volume" | "Gaps" | "Setups" | "Strength" | "Weakness" | "Earnings" | "IPO";
  definition: string;
  /** which way "strongest first" runs for this scanner */
  note?: string;
}

export const LIST_SCANNERS: ListScanner[] = [
  { id: "top-gainers", name: "Top Gainers", group: "Market lists", definition: "Stocks that rose in the latest session, biggest gain first." },
  { id: "top-losers", name: "Top Losers", group: "Market lists", definition: "Stocks that fell in the latest session, biggest fall first." },
  { id: "volume-gainers", name: "Volume Gainers", group: "Volume", definition: "As NSE (NSE-listed stocks): the latest session's volume at least 2x the average of the 5 sessions before it (the 1-week measure); the 2-week measure (10 sessions) is shown too. Biggest first." },
  { id: "high-volume", name: "High Volume Stocks", group: "Volume", definition: "As NSE's Most Active Equities (by value): NSE-listed stocks ranked by the value traded in the latest session (volume x price, in crores); the shares traded are shown beside it." },
  { id: "gap-up", name: "Gap Up", group: "Gaps", definition: "As Chartink: the latest session opened at least 1% above the previous close. Biggest gap first." },
  { id: "gap-down", name: "Gap Down", group: "Gaps", definition: "As Chartink: the latest session opened at least 1% below the previous close. Biggest gap first." },
  { id: "gap-filling", name: "Gap Filling (Up)", group: "Gaps", definition: "Gapped up at least 2% in the last 15 sessions and has since come back down into the gap without closing it completely." },
  { id: "gap-filling-down", name: "Gap Filling (Down)", group: "Gaps", definition: "Gapped down at least 2% in the last 15 sessions and has since bounced back up into the gap without closing it completely." },
  { id: "inside-bar", name: "Inside Bar (daily)", group: "Setups", definition: "The latest session traded inside the previous session's high and low." },
  { id: "inside-bar-weekly", name: "Inside Bar (weekly)", group: "Setups", definition: "The last finished week traded inside the high and low of the week before it." },
  { id: "inside-bar-filtered", name: "Filtered Inside Bar (daily)", group: "Setups", definition: "An inside bar whose range is at most 60% of the previous session's, with the price above its 50-day average." },
  { id: "inside-bar-weekly-filtered", name: "Filtered Inside Bar (weekly)", group: "Setups", definition: "A finished weekly inside bar at most 60% of the prior week's range, with the price above its 50-day average." },
  { id: "tight-setup", name: "Tight Setup (daily)", group: "Setups", definition: "The last 5 closes are within 2.5% of each other and the price is above its 50-day average." },
  { id: "tight-setup-weekly", name: "Tight Setup (weekly)", group: "Setups", definition: "The last 3 finished weekly closes are each within 1.5% of the week before (the \"three weeks tight\" rule) and the price is above its 50-day average." },
  { id: "momentum", name: "Momentum", group: "Strength", definition: "As Chartink's Momentum Stocks: price 30 or more, above its 50-day and 200-day averages (50 over 200), at least 2x its 52-week low, within 25% of its 52-week high, market cap Rs 1,000 to 20,000 Cr, and the latest volume at least 1.3x its 50-day average." },
  { id: "rs-high-before-price-high", name: "High Low RS Scan", group: "Strength", definition: "As Chartink's High Low RS Scan, with our own rules where its scan is unclear: price above its 50-day and 200-day averages with the 50 over the 200, daily RSI(14) above 60, market cap above Rs 2,000 Cr, weekly and monthly RSI(14) both above 50, and the stock ahead of the Nifty 500 over the same stretch (its close 104 sessions ago against 161 sessions ago, better than the index's)." },
  { id: "earnings-gap-up", name: "Earnings Gap Up (latest quarter)", group: "Earnings", definition: "Opened at least 3% above the pre-results close on the first session after the latest quarter's results." },
  { id: "earnings-gap-up-prev", name: "Earnings Gap Up (previous quarter)", group: "Earnings", definition: "The same, for the quarter before the latest." },
  { id: "positive-earnings-reaction", name: "Positive Earnings Reaction (latest quarter)", group: "Earnings", definition: "Closed at least 5% above the pre-results close within 5 sessions of the latest quarter's results, and is still above it." },
  { id: "positive-earnings-reaction-prev", name: "Positive Earnings Reaction (previous quarter)", group: "Earnings", definition: "The same, for the quarter before the latest." },
  { id: "recent-ipos", name: "Recent IPOs (scanned stocks)", group: "IPO", definition: "Stocks listed in the last 365 days." },
  { id: "ipo-setups", name: "IPO Setups", group: "IPO", definition: "Listed since 2023 and showing a horizontal resistance or a tight setup." },
  { id: "shorting", name: "Shorting Scanner", group: "Weakness", definition: "Below the 50 and 200-day averages (50 under 200), RS rating 30 or less and within 15% of the 52-week low." },
];

export const LIST_SCANNER_IDS = new Set(LIST_SCANNERS.map((s) => s.id));
export const isListScanner = (id: string) => LIST_SCANNER_IDS.has(id);
export const scannerName = (id: string) => LIST_SCANNERS.find((s) => s.id === id)?.name ?? (id === "horizontal-resistance" ? "Horizontal Resistance" : id.replace(/-and-/g, " & ").replace(/-/g, " ").replace(/\b[a-z]/g, (c) => c.toUpperCase()));

// ---- navigation: the top bar and the page talk through one window event ----------------------------------------------------
export type FeedName = "results-calendar" | "circuit-revisions" | "order-wins" | "deals" | "asm" | "sector-indices" | "recent-ipos" | "past-winners";
export const OPEN_NAV_EVENT = "navrist-nav";
export type NavTarget =
  | { type: "scanner"; id: string }
  | { type: "multi" }
  | { type: "analytics"; tab: "sectors" | "history" | "outlook" | "industries" | "rrg" | "breadth" }
  | { type: "feed"; name: FeedName; kind?: "bulk" | "block" }
  | { type: "sector"; name: string }
  | { type: "watchlist" }
  | { type: "journal" }
  | { type: "home"; scroll?: "patterns" };

export function navigateTo(target: NavTarget) {
  window.dispatchEvent(new CustomEvent(OPEN_NAV_EVENT, { detail: target }));
}
