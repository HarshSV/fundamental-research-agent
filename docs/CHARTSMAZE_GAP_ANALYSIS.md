# ChartsMaze versus Navrist: feature gap and build plan

*Written 2026-11-06. Sources: ChartsMaze's public menu and About page (observed 2026-11-06), the project's earlier note from the owner's
walkthrough-video review (2026-10-30), and the Navrist code. Every ChartsMaze page, including those marked FREE, sits behind a sign-up, so
**what a ChartsMaze page contains was not seen**; only the existence and name of each feature is known. No account was created.*

## 1. What ChartsMaze offers (from its menu)

| Group | Features |
|---|---|
| Screeners | Create/Load Screener, Multiple Scans, Horizontal Resistance, Tight Setup (daily/weekly), IPO Scanner (Recent IPOs, IPO Setups), RS High Before Price High, Momentum Scanner, Volume (Footprint, Gainers, High Volume Stocks), VCP, Flags & Pennants, Earnings (Gap Up, Positive Earnings Reaction), Gap (Filling, Up), Inside Bar (daily/weekly), Templates (named presets), Shorting Scanner, Shakeout (200/50/21/10 EMA) |
| Market analytics | Sector Analytics, Industry Analytics, RRG, Market Breadth, Sector Indices, Top Gainers |
| Personal tools | Watchlist, Journal, Tools |
| Event and list pages | Past Winners, Results Calendar, Circuit Revision List, Order Wins, ASM list, Bulk Deals, Block Deals, Insider Trading, Blogs |
| Product | iOS and Android apps, "AI-powered company insights", charts powered by TradingView |

## 2. Where Navrist stands (2026-11-06)

| ChartsMaze feature | Navrist |
|---|---|
| Create/Load Screener | **Have** (Technicals, Patterns, Fundamentals, Miscellaneous tabs; Save / Load / Share; List and Charts views; CSV; Backtest for chosen patterns) |
| Horizontal Resistance | **Have**, as its own scanner (header button), separate from the screener filters |
| VCP, Flags & Pennants, Shakeout-type setups | **Have** as chart patterns (32 patterns, forming -> confirmed lifecycle) |
| Tight Setup, Inside Bar, IPO setups | **Partly** (Three Weeks Tight and IPO Base patterns exist; no inside-bar or recent-IPO list) |
| Sector analytics, RRG | **Partly** (sector pages; the RRG quadrant engine exists as a filter, no RRG chart page) |
| Templates | **Partly** (Save / Load / Share of filter sets exists; no shared named presets beyond the "Popular Screens" cards) |
| Multiple Scans, Momentum, RS High Before Price High, Shorting, Volume scanners, Gap scanners, Top Gainers, Market Breadth, Industry Analytics | **Missing** |
| Earnings Gap Up, Positive Earnings Reaction, Results Calendar | **Missing** (needs result dates) |
| Watchlist, Journal | **Missing** (needs per-user storage; Navrist has one shared password) |
| Past Winners, Circuit Revision, Order Wins, ASM, Bulk/Block deals, Insider trading | **Missing** (need NSE/BSE feeds) |
| Mobile apps | **Missing** (the web app is responsive; see PROJECT_DOCUMENTATION B.17) |
| AI company insights | **Off by decision** (LLM calls are disabled app-wide) |

Navrist has things ChartsMaze's public pages do not show: audited ratios from Annual Reports (68, with calculation breakdowns), a probabilistic
forecast with buy / stop / target levels, shareholding and pledge detail, and server-side alerts with Telegram.

## 3. How a scanner is added (the recipe)

1. **Measure** - add a pure function in `patterns/features.py` over the stored daily candles (`time, open, high, low, close, volume`). Anything that
   cannot be computed is `None`, never 0 (project rule).
2. **Store** - write the value into the per-stock file in `data/pattern_scan/` from `patterns/scan.py`.
3. **Filter / sort** - add it to `RANGE_FIELDS` / `_stock_passes` / `SORTS` in `patterns/screen_engine.py`; special scanners are listed in `SPECIAL`.
4. **Expose** - add the scanner entry in `HomeScreen.tsx` (and a header or menu button), a column in `PatternScanPage.tsx`, and a tab in
   `PatternFilterModal.tsx` if it has its own options. Results, charts, CSV and backtest are reused.

The universe is the 751 stocks of the Nifty Total Market list, not ChartsMaze's 2000+.

## 4. Build plan

**Group 1 - from candles we already store (no new data):** Top Gainers/Losers; Volume Gainers and High Volume Stocks (volume against the 20-day
average, turnover rank); Gap Up and Gap Filling (open against the previous close, later fill); Inside Bar and Tight Setup (range contraction);
Momentum and RS High Before Price High (existing RS rating and 52-week-high fields); Shorting scanner (bearish mirror); Market Breadth (share of
the 751 above their 20/50/200-day averages, advances/declines); an RRG chart page over the existing quadrant engine; Multiple Scans (combine saved
scanners with AND/OR); named Templates over Save/Load/Share. *Suggested order:* Top Gainers, Volume, Gap, Market Breadth, then the rest.

**Group 2 - needs a new data source:** result announcement dates (for Earnings Gap Up, Positive Earnings Reaction, Results Calendar); NSE feeds for
Bulk/Block deals, ASM, circuit revisions, insider trading and order wins; the recent-IPO list. NSE blocks many non-Indian server addresses, so these
fetchers should run from the Indian-region machine.

**Group 3 - product features:** Watchlist and Journal need per-user storage and therefore real user accounts; Industry Analytics needs an industry
classification finer than the current sector field; Past Winners needs historical results.

**Rules for every new scanner:** generic across all supported stocks (never ticker-specific), unknown values stay unknown, each scanner tested in
the browser at desktop and 375 px width, and each committed on its own.
