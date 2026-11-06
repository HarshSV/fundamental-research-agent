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

## 1c. What the signed-in site shows (read 2026-11-06 in a session the owner signed in to; screens read only, no data downloaded)

*Observed facts only. Where a label's meaning is not stated on the page it is marked "unknown". Their numbers are theirs; this section records which features and fields exist.*

**Top bar (desktop):** Screeners, Market Analytics, Watchlist (badge FREE), Journal (FREE), Tools (FREE), Help, then a notification bell and the profile icon. On narrow screens it collapses to Screener, Analytics, Watchlist, More, Login. Footer links to ASM List, Bulk Deals, Block Deals and Insider Trading currently open a 404 page, although the stock list shows markers for them (below).
**Multiple Scans has moved:** its page now says the pattern-scanner filter is inside Create/Load Screener. There, "Predefined Chart Patterns" is a multi-select of their scanners with an AND/OR choice between them (the OR option carries a crown icon, a premium marker).

**Screener results page.** Universe "2000+" (the page said 2,517 results); columns Stock Name, RS Rating, **Basic Industry**, Market Cap, 1 Month Returns, 3 Month Returns, % from 52W High; per row a star/hash marker legend (long-term ASM, short-term ASM, negative / positive circuit-limit revision, block deal, insider trading, "quarterly results coming soon") and two small per-row buttons (B and S, purpose unknown); List and Charts views; Technicals and Fundamentals column sets; a search box; CSV download; a "Deep Dive" button (unknown); toolbar icons for filters, a pie chart (unknown), save/load, and settings; one or two charts per screen.

**Filter list (all three tabs).**
*Technicals:* price above/below moving averages; predefined chart patterns (AND/OR); overall RS range; near new highs; % from 52-week high; % from 52-week low; % from 3-year high; market cap; average price x volume over 30 days; industries that are Leading/Improving/... on the rotation graph (daily or weekly, against Nifty 50); free float; stock price; moving-average order (20 >= 50 >= 200); moving average rising for at least N months; ADR over N days; 200-day MA turn-around; Basic Industry; Sector; Index.
*Fundamentals:* QoQ and YoY growth of EPS, net profit, sales and OPM; 5-year sales growth; ROE; ROCE; OPM TTM; P/E range; D/E; PEG; EPS last year above the year before; net profit positive for the last N quarters; EPS, net profit, sales and OPM increasing for N quarters; quarterly net-profit turn-around (negative to positive); only stocks with the latest quarter's results; only stocks with a positive FII (QoQ) change; "Code 33" (acceleration in EPS, sales and OPM); historical 5-year P/E above current or forward P/E.
*Miscellaneous:* return range over a chosen period; price relative to multiples of the 10 EMA; 1-month and 3-month RS above a value; industry 1W / 1M / 3M rank below a value; exclude ASM stocks (short or long term); exclude stocks on a 5% or 2% circuit limit; N-day average turnover; volume against its 20-day average and price x 20-day volume; RVOL range; gap-up % (open against previous close); N-day range; float shares range; "dense volume" % (unknown); listing date after; F&O stocks only; FVG (fair value gap) in a chosen timeframe.
*Predefined scanner list inside the filter:* Horizontal Resistance (D), Tight Setup (D, W), Volume Footprint, Volume Gainers, HVE, HVY, HVQ (not explained; probably highest volume ever / year / quarter, unverified), Shakeout 200/21/50/10 EMA, Basic and Filtered Inside Bar (D, W), Flags & Pennants, Gap Filling, Earnings Gap Up and Positive Earnings Reaction for each results quarter (Sep 2026, Jun 2026), Gap Up, VCP, RS High Before Price High, Momentum Scanner.

**Market analytics pages.**
* *Industry Analytics:* 112 "Basic Industries"; columns Basic Industry, 1W / 1M / 3M performance, 1W / 1M / 3M rank, number of stocks, group market cap, rotation quadrant (daily, Nifty 50); toggles Equal Weighted / Market-cap Weighted and List / Charts.
* *Sector Analytics:* tabs Moving Average, Relative Strength, Near 52w High (share of a sector's stocks within 5% of the 52-week high), each sector broken into the industries that contribute to it with their percentage, and the strongest stocks with their RS.
* *RRG:* benchmark (Nifty 50 ...), tail length (5), interval (daily), data mode **Sector Index** (the NSE sector indices such as Nifty Pharma, Auto, Bank, IT, Metals, Realty, Capital Markets, Defence, EV ...; about 30), zone filter, Animate and Center buttons, JdK RS-Ratio / RS-Momentum.
* *Market Breadth:* base index selector (All Stocks ...), 3M / 6M / 12M, charts for share above the 200 / 50 / 20 / 10-day averages; stocks up / down by 4.5% today; 52-week highs and lows; advances and declines; volume above vs below its 20-day average; Nifty 500 share with RSI above 60; List and Charts toggles.
* *Sector Indices:* a table of 36 NSE indices (full-screen option). *Top Gainers:* returns-type selector (1 day ...), a filter, bars of each industry's share of top-gaining stocks, and an overall top-performers list.

**Other pages.** *Watchlist:* priority groups (high, medium, low), Run Scanner, Share, Add, List and Charts views, Technicals and Fundamentals, an RRG view, Load. *Results Calendar:* quarterly results by date range (550 results for the Sep 2026 quarter in the window seen), Table / Card and Summary views, columns QoQ and YoY EPS, sales and OPM. *Circuit Revision List:* effective date, stock, old and new limit (%), basic industry, market cap. *Order Wins:* last week's order announcements (269 seen) with subject, details, an "AI Notes" summary and an attachment link. *Past Winners:* yearly or other winner lists by year. *IPO Setups:* IPOs listed in a date range that show horizontal resistance or tight consolidation, with industry ranks. *Recent IPOs* and *Journal / Help* menus were not opened.

**What this means for Navrist.**
* *We already match or exceed:* the core technical filters (moving averages, RS, distance from highs, market cap, turnover, price, MA order, rising MA, ADR, index, sector, rotation), chart patterns with status, horizontal resistance, backtests, Multiple Scans, RRG, breadth, sector analytics, save/load/share of filters, list and chart views, CSV.
* *Largest gaps by value:* (1) a **Basic Industry** classification (112 groups) which drives Industry Analytics, the industry-rank filters and the stock list column; (2) **quarterly fundamentals** (QoQ/YoY growth, increasing-for-N-quarters, turn-around, Code 33) which drive about a dozen filters, the earnings scanners and the Results Calendar; (3) **exchange-derived markers and lists** (ASM, circuit limits, block deals, insider trading, order wins); (4) **a rotation graph on NSE sector indices** rather than our equal-weighted sector averages; (5) **Watchlist and Journal**.
* *Quick wins from data we already store (computed at query time, no new data):* RVOL, gap-up % as a filter, N-day range, price relative to the 10 EMA, 1-month and 3-month RS, 200-day MA turn-around, % from 3-year high (needs the full history stored), a "volume above / below its 20-day average" and "4.5% up / down" count on the Breadth page, and a Basic vs Filtered inside bar.
* *Needs no accounts:* a Watchlist (with high / medium / low groups) and a Journal can be kept in the browser's local storage like our saved filters, at the cost of being per device.
* *Universe size:* theirs is about 2,500 stocks; ours is the 751-stock Nifty Total Market list. Widening it means scanning every NSE-listed equity (time, rate limits and data gaps), and is a separate decision.
* *Unverified ideas for data sources (to check before promising):* the industry could come from the Screener.in company page we already read for fundamentals; quarterly results from the Screener quarterly table; results dates, ASM, circuit revisions, bulk / block deals and insider trading from NSE's public feeds (NSE blocks many non-Indian addresses); sector-index history from NSE or Yahoo index tickers.

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

## 3b. Built on 2026-11-06 (code in `patterns/market_lists.py`, `patterns/market_analytics.py`, the top menu in `Header.tsx`)

| ChartsMaze feature | Navrist | Definition we use (also shown in the app) |
|---|---|---|
| Multiple Scans | **Built** (`pattern: "multi"`, `filters.scans`) | A stock must appear in ALL ticked scanners (chart patterns, Horizontal Resistance, any market-list scanner) |
| Top Gainers / Losers | **Built** | Latest session's close-to-close change, biggest first |
| Volume Gainers | **Built** | Latest volume at least 2x the average of the 20 sessions before it |
| High Volume Stocks | **Built** | Ranked by the latest session's traded value (price x volume) |
| Gap Up | **Built** | Open at least 2% above the previous close in the latest session |
| Gap Filling | **Built** | A 2%+ gap up in the last 15 sessions that price has since come back into without fully closing it |
| Inside Bar (daily, weekly) | **Built** | Latest session (or week) inside the previous one's high and low |
| Tight Setup (daily, weekly) | **Built** | Last 5 closes within 2.5% (3 weekly closes within 4%), price above the 50-day average |
| Momentum | **Built** | Price > 50-day > 200-day average, RS 80+, within 15% of the 52-week high, 3-month return 20%+ |
| RS High Before Price High | **Built** | Stock/Nifty 500 relative-strength line at a 52-week high while price is 2%+ below its own 52-week high |
| Shorting Scanner | **Built** | Price < 50-day < 200-day average, RS 30 or less, within 15% of the 52-week low |
| Sector Analytics | **Built** (`/api/v1/market/sectors`) | Equal-weighted sector returns (1D to 1Y), 1M against the Nifty 500, share above 50/200-day averages, average RS, rotation quadrant |
| RRG | **Built** (`/api/v1/market/rrg`) | Sector quadrants and trails; open approximation, not the licensed JdK formula |
| Market Breadth | **Built** (`/api/v1/market/breadth`) | Advance/decline, share above 20/50/200-day averages, new 52-week highs and lows, 90-day history |

These definitions are ours. ChartsMaze's exact rules were not visible, so results will differ from theirs. All computations use only the stored scan data
(about 160 daily candles and 520 closes per stock); a value that cannot be computed is None and the stock does not match.

**Still not built:** Industry Analytics (no industry field finer than the 25 sectors), Earnings Gap Up / Positive Earnings Reaction / Results Calendar (need result
dates), Sector Indices page, Watchlist and Journal (need per-user accounts), Past Winners, IPO scanner and recent-IPO list, Circuit Revision, Order Wins, ASM,
Bulk/Block deals, Insider Trading (need exchange feeds), named Templates, mobile apps.

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
