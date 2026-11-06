# ChartsMaze versus Navrist: feature gap and build plan

*Written 2026-11-06, extended the same day. Sources: ChartsMaze's public landing page, menu and About page, **the "ChartsMaze Product
Walkthrough" video embedded on its landing page** (9:26, read through its transcript, so spoken content only, not the on-screen visuals), the
project's earlier note from the owner's walkthrough review (2026-10-30), and the Navrist code. Every ChartsMaze feature page, including those
marked FREE, sits behind a sign-up, so **the pages' own tables and columns were not seen**; what is recorded is what the landing page and the
video say each feature does. No account was created and nothing was copied from behind the login. Summaries are in our own words.*

## 1. What ChartsMaze offers (from its menu)

| Group | Features |
|---|---|
| Screeners | Create/Load Screener, Multiple Scans, Horizontal Resistance, Tight Setup (daily/weekly), IPO Scanner (Recent IPOs, IPO Setups), RS High Before Price High, Momentum Scanner, Volume (Footprint, Gainers, High Volume Stocks), VCP, Flags & Pennants, Earnings (Gap Up, Positive Earnings Reaction), Gap (Filling, Up), Inside Bar (daily/weekly), Templates (named presets), Shorting Scanner, Shakeout (200/50/21/10 EMA) |
| Market analytics | Sector Analytics, Industry Analytics, RRG, Market Breadth, Sector Indices, Top Gainers |
| Personal tools | Watchlist, Journal, Tools |
| Event and list pages | Past Winners, Results Calendar, Circuit Revision List, Order Wins, ASM list, Bulk Deals, Block Deals, Insider Trading, Blogs |
| Product | iOS and Android apps, "AI-powered company insights", charts powered by TradingView |

## 1b. What the landing page and the walkthrough video add

**Product shape.** Two ways in: the **Screener** section (bottom-up: pick stocks by maths filters, earnings criteria or chart-pattern criteria) and
**Market Analytics** (top-down: find where money is flowing, then drill to stocks). Their own advice is to start top-down. Landing tiles:
Predefined Scanner with Backtest, Create Screener, Market Analytics, Watchlist; a free Trade Journal.

| Feature | What it does (per the video / landing page) |
|---|---|
| Create Screener | Build a rule set (for example price above the 50 EMA, volume above 5 lakh, price between Rs 100 and Rs 2,000), scan the whole market, get only stocks matching every condition; **save the screener and re-run it daily** |
| Predefined scanners with a **Backtest Data tab** | Horizontal Resistance, Flags & Pennants, VCP, Tight Setup: each shows historical performance - win rate, average return, sample size |
| Earnings scanners | **Earnings Gap Up**: stocks that reported results and gapped up significantly. **Positive Earnings Reaction**: gapped up and kept performing on the result day or within a few days after. Updated regularly; the menu labels them by results month |
| **Multiple Scans** | Run several scanners together and show only stocks present in **all** of them (the intersection), e.g. Horizontal Resistance AND Tight Setup |
| Sector Analytics | Which sectors out- or under-perform the broader market, "in real time" |
| Industry Analytics | One level below sectors (example: FMCG splits into agro products, personal care, food products, sugar, tea and coffee; auto into tyres, auto ancillaries, manufacturers); find the strongest industry group, then go through its stocks and filter for price strength ("macro to micro in under 5 minutes") |
| **RRG** (Relative Rotation Graph) | Each sector drawn as a trail on four quadrants - Leading, Improving, Weakening, Lagging; the trail moves over time, so a sector rotating from Improving toward Leading is visible early. They publish a separate video on it |
| Market Breadth | Share of stocks participating in a move (their example: index up with only 20% of stocks rising = narrow, fragile; 70% = broad, healthy) |
| Sector Indices | Daily performance of each sector index, as a quick reference |
| Watchlist | Save the stocks you filtered and follow them over time |
| Trade Journal | Free and unlimited: log trades with metrics, attach charts and notes, reflect on mistakes; custom scanners |
| Charts | TradingView charts; one or two charts per screen (a layout setting); they recommend Chrome because charts load faster |
| Account and price | Free sign-up with a 14-day trial of premium features; plans Rs 499 monthly, Rs 2,499 for six months, Rs 3,299 yearly (landing page); mobile apps for iOS and Android |

*Note:* the landing page's own scanner cards repeat descriptions across different scanners (a copy error on their side), so card text was not used as evidence.

## 2. Where Navrist stands (2026-11-06)

| ChartsMaze feature | Navrist |
|---|---|
| Create/Load Screener (price, volume, EMA/DMA, returns, fundamentals, indices, sectors, patterns; save/load/share) | **Have** (Technicals, Patterns, Fundamentals, Miscellaneous tabs; Save / Load / Share; List and Charts views; CSV; Backtest for chosen patterns) |
| Horizontal Resistance | **Have**, as its own scanner (header button), separate from the screener filters |
| VCP, Flags & Pennants, Shakeout-type setups | **Have** as chart patterns (32 patterns, forming -> confirmed lifecycle) |
| Tight Setup, Inside Bar, IPO setups | **Partly** (Three Weeks Tight and IPO Base patterns exist; no inside-bar or recent-IPO list) |
| Sector analytics, RRG (and the video's "macro to micro" workflow) | **Partly** (sector pages; the RRG quadrant engine exists as a filter, no RRG chart page) |
| Templates | **Partly** (Save / Load / Share of filter sets exists; no shared named presets beyond the "Popular Screens" cards) |
| Multiple Scans (intersection of scanners) and Momentum, RS High Before Price High, Shorting, Volume scanners, Gap scanners, Top Gainers, Market Breadth, Industry Analytics | **Missing** |
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

**Group 1 - from candles we already store (no new data); the video suggests this order of value: Multiple Scans, RRG chart, Market Breadth, Sector analytics view, then the single-purpose scanners:** Top Gainers/Losers; Volume Gainers and High Volume Stocks (volume against the 20-day
average, turnover rank); Gap Up and Gap Filling (open against the previous close, later fill); Inside Bar and Tight Setup (range contraction);
Momentum and RS High Before Price High (existing RS rating and 52-week-high fields); Shorting scanner (bearish mirror); Market Breadth (share of
the 751 above their 20/50/200-day averages, advances/declines); an RRG chart page over the existing quadrant engine; Multiple Scans (combine saved
scanners with AND/OR); named Templates over Save/Load/Share. *Suggested order:* Top Gainers, Volume, Gap, Market Breadth, then the rest.

**Group 2 - needs a new data source:** result announcement dates (for Earnings Gap Up, Positive Earnings Reaction, Results Calendar); NSE feeds for
Bulk/Block deals, ASM, circuit revisions, insider trading and order wins; the recent-IPO list. NSE blocks many non-Indian server addresses, so these
fetchers should run from the Indian-region machine.

**Sector and industry analytics.** Sector strength can be computed from the stored candles by averaging stocks per sector (we already have a sector for every
scanned stock and the RRG quadrant engine). *Industry* analytics needs an industry field finer than sector; whether our NSE list carries one must be checked
before promising it. Both views would show each group's return over several periods, breadth inside the group and a ranked list, then link to the group's stocks.

**Group 3 - product features:** Watchlist and Journal need per-user storage and therefore real user accounts; Industry Analytics needs an industry
classification finer than the current sector field; Past Winners needs historical results.

**Rules for every new scanner:** generic across all supported stocks (never ticker-specific), unknown values stay unknown, each scanner tested in
the browser at desktop and 375 px width, and each committed on its own.
