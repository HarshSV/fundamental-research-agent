# Navrist AI: the complete feature list

*Written 12 November 2026. This is the plain-language guide to everything the site does, how each thing is shown, and where its numbers come from. Technical detail is in [`PROJECT_DOCUMENTATION.md`](../PROJECT_DOCUMENTATION.md); the sector pages are explained further in [`SECTOR_AGENT.md`](SECTOR_AGENT.md) and the pattern tests in [`PATTERN_STUDY.md`](PATTERN_STUDY.md).*

**What Navrist AI is:** a research website for Indian (NSE) stocks. You search a company, see its price, charts, results, shareholding and a forecast, scan the whole market for setups, and track the market by sector. It lives at **ai.navrist.com** and asks for one shared password.

**How to read this list**
* **Where** = how to reach it on the site. **How it is shown** = what you see. **Source** = where the numbers come from.
* **Source names used below**

| Name | What it is |
|---|---|
| **Angel One** | The broker's live data feed: live price, today's open, high, low, volume |
| **Yahoo Finance** | Free price history (daily and 5-minute), index levels. Prices are adjusted for splits and bonus issues, not for dividends |
| **NSE** | National Stock Exchange public files and pages: company lists, deals, results dates, corporate announcements, holidays, indices |
| **BSE** | Bombay Stock Exchange: annual reports, company-action records |
| **Screener.in** | Company web pages with quarterly and yearly results, shareholding, ratios, peers, classification |
| **Google News** | Headlines, searched by company or sector name |
| **US Federal Reserve** | The published schedule of its policy meetings |
| **Our own calculation** | Worked out by Navrist from the data above, using rules written in this project |
| **Your browser** | Saved only on the device you use, not on our server |

---

## 1. Everywhere on the site

| Feature | How it is shown | Source |
|---|---|---|
| **Login** | A password box before anything else. One shared site password; wrong guesses are limited | Our own (`auth.py`) |
| **Index ticker** | A moving strip at the very top: NIFTY 50, BANK, NEXT 50, 100, 500, IT, AUTO with the day's change in green or red | Yahoo Finance |
| **Top bar** | Navrist blue (#04295D) with the logo, then menus: **Screeners**, **Market Analytics**, **Tools**, **Watchlist**, **Journal**, a search box and a light / dark switch | Our own design |
| **Light and dark mode** | Opens in light mode; your choice is remembered on your device only | Your browser |
| **Phone layout** | The menus fold into a slide-in drawer; pages fit narrow screens | Our own design |
| **Search** | Type a company name, symbol or sector; results appear as you type | Angel One stock list, NSE company names, our company table |
| **Recent searches** | Your last stocks under the search box | Your browser |

## 2. The landing page

| Feature | How it is shown | Source |
|---|---|---|
| **Headline and big search box** | "NAVRIST AI." with a typing line, and a search box with example names | Our own |
| **Browse by pattern** | Nine chips in a grid plus a **More (23)** button that reveals the rest with an animation. Green = bullish, red = bearish, white = either way depending on the shape. Tap a chip to open the filter for that pattern | Pattern rules: our own (32 patterns) |
| **Popular Screens** | Ready-made stock lists grouped as Growth at a Discount, Income + Safety, Momentum + Breakout, Quality & Safety and Value Growth, each a pair of conditions (for example "High EPS + Low P/E") | Screener.in, Yahoo Finance, calculated by us |

## 3. A stock's page

Open any company from search. The page runs top to bottom like this.

| Section | How it is shown | Source |
|---|---|---|
| **Header** | Name, symbol, live price and the day's change, a Watchlist star, a Back button | Angel One (Yahoo if Angel has nothing) |
| **Forecast strip** | Three cards above the chart: next session, next 5 sessions, next 20 sessions. Each says "Leans up", "Leans down" or "Too close to call", gives the % chance of a clear rise and fall and the likely price range | Our own calculation from Yahoo daily history (the stock's whole adjusted history) |
| **Price chart** | Candles or a line. Range buttons 1D, 1W, 1M, 3M, 6M, 1Y, 3Y, 5Y, All. A **Live** mode refreshes during market hours and adds second-by-second points | Yahoo Finance history; live points from Angel One |
| **Top row of the chart** | Switches for **Patterns**, **Forecast** and **Volume**, and the **Chart lines** button | Our own |
| **Forecast fan** | A shaded fan to the right of the last candle showing where price is likely to be over the next 5 and 20 sessions | Our own calculation |
| **Chart lines (filter)** | Lets you pick the lines on the chart. Default is **today's plan** only: entry, stop-loss, target 1 and target 2, each with its price. Extra choices: swing plan, opening range, 52-week high and low, and 20 / 50 / 100 / 200-day moving averages. Each average continues as a dashed line inside the fan, assuming price follows the middle of the forecast | Our own calculation |
| **Patterns toggle** | Arrows on the chart: ▲ bullish below the candle, ▼ bearish above. Colour shows what happened 5 sessions later (green gained, red fell, blue too recent, grey flat). Big labelled arrows are patterns developing now; small faded ones are old. Developing patterns also draw their outline, breakout level, "fails" level and a rule-of-thumb target | Our own pattern rules on Yahoo prices |
| **Active setups** | Cards under the chart for each forming pattern: breakout, invalidation, measured-move target, and a line saying how that pattern has actually performed in our test ("small proven edge", "no proven edge" or "went the other way") | Our own pattern rules and our own pattern study |
| **Forecast section** | A fuller version of the forecast: the lean and odds for 1 day, 1 week, 1 month; "Full history / Last 5 years" toggle; "When to buy and when to get out" with a today plan and a swing plan (entry, stop, targets, odds of hitting them); alerts button; "See the reasoning" with the evidence the forecast rests on | Our own calculation (Yahoo 5-minute and daily data, the market scan, Screener quarterly results) |
| **News button** | Beside the Forecast title; opens recent company filings and headlines | NSE filings, BSE filings, Google News |
| **Key Metrics** | Cards: Market Cap, P/E, EPS (TTM), Face Value, All-Time High and Low, Debt/Equity, ROE, Price to Book, Dividend Yield, Promoter Holding, Net Profit Margin, Revenue Growth. Some can be switched between TTM and Annual. Green and red show whether a figure is favourable | Screener.in; EPS from the company's latest annual report (BSE, NSE as backup); P/E = live price over that EPS; all-time high and low from Yahoo's full history |
| **Price Range** | Today's range, 52-week range (or "since listing" for new stocks), open, previous close, volume, VWAP | Angel One and Yahoo Finance |
| **Returns Performance** | 1 week, 1, 3, 6 months, 1, 3, 5 years (and "since listing" for new stocks) | Yahoo past prices against the live price |
| **Shareholding Pattern** | A donut chart of Promoter, FII, DII and Public for the last five quarters; tap a slice for its history and promoter pledge | Screener.in; pledge from NSE |
| **Financial Result** | Last four quarters as tappable cards. Tabs: **Results** (income, profit before tax, net profit, free cash flow, with EPS on its own scale), **Earnings Per Share**, **PAT**, **Free Cash Flow** (by year). Tap a card for its detail | Screener.in (consolidated; standalone when there are no consolidated accounts) |
| **About** | Company description, headquarters, year of incorporation, MD / CEO, website, a link to the latest annual report | NSE Market Lens (Yahoo as backup); annual report link from BSE |
| **Peer Comparison** | A table of similar companies: price, market cap, P/E, ROCE | Screener.in |

## 4. The Screeners menu

| Feature | How it is shown | Source |
|---|---|---|
| **Create Screener** | A popup with four tabs: **Technicals**, **Patterns**, **Fundamentals**, **Miscellaneous**. About 28 number ranges (price, market cap, RS rating, distance from highs, volume ratios, growth, P/E, ROE and more) and about a dozen yes/no filters (for example "Code 33", "F&O only", "exclude ASM", "results due in 7 days", "profit turnaround"), industry and index pickers. Every pattern row is tinted green, red or grey with an arrow for its direction. You can Save, Load and Share filters. Results appear as a list with a chart view and a **Backtest** tab | Yahoo daily history (our own measures stored per stock), Screener.in fundamentals and quarterly results, NSE lists |
| **Multiple Scans** | Shows the stocks that appear in all the scanners you pick | Our own |
| **Horizontal Resistance** | Stocks pressing on a level that three highs have touched (price within 5% under it or just through it) | Our own calculation |
| **Chart Patterns** | Scrolls to the pattern chips | Our own |
| **Setups** | Tight Setup, Inside Bar and Filtered Inside Bar, each daily and weekly | Our own calculation |
| **Volume and gaps** | Volume Gainers, High Volume Stocks, Gap Up, Gap Filling | Our own calculation |
| **Strength and weakness** | Momentum, RS High Before Price High, Shorting Scanner | Our own calculation |
| **Earnings and IPOs** | Earnings Gap Up and Positive Earnings Reaction (latest and previous quarter), IPO Setups | NSE results dates, Screener.in, our own calculation |
| **Result lists** | Each scan shows a table (symbol, price, change, matched value, industry and small markers for ASM, price band, block deal, results soon) and opens a chart for any row | As above |

## 5. The Market Analytics menu

| Feature | How it is shown | Source |
|---|---|---|
| **Sector Analytics** | A table of every sector's returns (1 day to 1 year), how many stocks are above their 50 and 200-day averages, RS rating and rotation quadrant | Our own calculation from stored prices |
| **Sector History** | Every sector since about 1996 (market from Dec 1995): yearly growth, best and worst year, years up, deepest fall and recovery time, rolling returns, month-by-month averages, and a "What moved this sector" panel. **Full history / Last 5 years** toggle | Yahoo adjusted history of the scanned stocks; events from our own hand-written list; headlines from Google News; current company events from NSE |
| **Sector Outlook** | Odds for each sector over the next month and 3 months, how they differ from the sector's usual, the facts beside them (trend, results this quarter, deals, results due), and two buttons: **How far can this be trusted?** and **Scheduled events ahead** | Our own calculation; US Federal Reserve dates, NSE holidays and company actions, a few dates kept by hand |
| **Industry Analytics** | The strongest of 143 industry groups, equal or market-cap weighted | Screener.in classification, our own calculation |
| **RRG** | A rotation chart placing sectors in Leading, Improving, Weakening or Lagging | Our own calculation |
| **Market Breadth** | How many stocks advance and decline, how many are above their moving averages, new 52-week highs and lows, with history charts | Our own calculation |
| **Sector Indices** | Every NSE index today | NSE |
| **Top Gainers / Top Losers** | The day's movers | Our own calculation |

## 6. The Tools menu

| Feature | How it is shown | Source |
|---|---|---|
| **Results Calendar** | Who has filed results and who is due, with growth against the last quarter and last year | NSE board-meeting announcements, Screener.in |
| **Order Wins** | Companies announcing orders and contracts in the last two weeks, with a link to the filing | NSE corporate announcements |
| **Past Winners** | The best performers of the last full year and the year to date | Our own calculation from stored prices |
| **Recent IPOs** | Everything listed in the last year | NSE listings file |
| **Circuit Revision List** | Price-band changes (for example 20% to 10%) | NSE daily price-band files |
| **ASM List** | Stocks under additional surveillance | NSE |
| **Bulk Deals / Block Deals** | The large trades of the day, who bought and sold | NSE (kept for 120 days from when we first read them) |

## 7. Your own tools

| Feature | How it is shown | Source |
|---|---|---|
| **Watchlist** | Stars on stocks, priorities, notes, share by a text code, and a scan of the list. Saved in your browser | Your browser |
| **Journal** | Log trades with notes and a chart image; see statistics and export to CSV. Saved in your browser | Your browser |
| **Alerts** | From a trade plan, set alerts for entry, stop, target and the 15:25 exit; a browser notification and an optional **Telegram** message | Our own; Telegram bot |
| **Saved filters** | Create Screener filters you can save, load and share | Your browser |

## 8. Built but not on the website you see at ai.navrist.com

These exist in the backend and the older dashboard (`frontend/`, `frontend-dashboard/`), and are described in the main documentation:

| Feature | What it does | Source | Status |
|---|---|---|---|
| **68 financial ratios** | Efficiency, liquidity, profitability, leverage, valuation, cash-flow, growth and bank ratios, each with a formula and a "Calculation Breakdown" of the inputs and pages used | Annual-report PDFs (BSE, NSE), NSE XBRL filings, Screener.in as a cross-check | Built; not on the Next.js site |
| **Qualitative analysis A-U** | Topics scored from filings with evidence, with confidence tags | Annual reports and filings | Built with rules; **AI calls are switched off** |
| **Manual document upload** | Upload an annual report and other filings and analyse them | Your files | Built; not on the Next.js site |
| **PDF report** | A downloadable research report | Our own | Built |
| **Ask Navrist chatbot** | A chat assistant | An AI model | **Switched off on purpose** |
| **5-minute forecast pilot** | A calibrated range for the next five 5-minute bars | Angel One history | Pilot only |

## 9. What the site does not have (so you do not look for it)

* **No AI-written text.** Every sentence on the sector and forecast pages is a template filled with numbers.
* **No price before about 1996.** BSE has yearly prices from 1991, but they are not adjusted for splits and bonus issues, so they are not used.
* **No Volume Footprint, no insider-trading list, no Templates** (shared presets), and no index-based rotation graph. These came from a comparison with another site and are listed as not built.
* **No future macro calendar beyond what is published:** US Fed dates, NSE holidays, company actions and results dates. RBI policy dates are not listed because no readable source gives them.
* **Not a trading engine:** nothing places orders.
* **About 750 stocks are scanned** (not the whole market), and only stocks listed today, so long-run figures look better than an investor actually earned.

## 10. How reliable is it?

* **Forecast and sector outlook:** tested on the past. The edge is small: the odds are a lean, not a call. The Sector Outlook page shows its own test results.
* **Chart patterns:** tested on 100,541 past confirmations. Four bullish patterns have a small average gain (about 1% over 20 sessions after costs), most trades still lose, and bearish patterns gave no selling edge. See `PATTERN_STUDY.md`.
* **Data can be late or missing.** Yahoo, NSE and Screener are free public sources; a source that fails shows "unavailable", never a made-up number. A missing value is shown as "—", never as zero.
* **The site runs from the owner's PC** through a Cloudflare tunnel, so it is down whenever that PC is off.

## 11. Where each source is read in the code (for the team)

| Source | Main code |
|---|---|
| Angel One | `tools/angel_scraper.py`, `app.py` (`/api/quote`, live chart) |
| Yahoo Finance | `tools/live_chart_yf.py` (`get_candles`), the market scan `patterns/scan.py` |
| NSE | `patterns/exchange_data.py`, `patterns/market_feeds.py`, `tools/nse_xbrl.py` |
| BSE | `tools/bse_scraper.py`, `setups/events.py` |
| Screener.in | `tools/screener_scraper.py`, `tools/screener_fcf.py`, `screens/quarterly.py` |
| Google News | `setups/events.py`, `patterns/sector_events.py`, `patterns/upcoming.py` |
| US Federal Reserve | `patterns/upcoming.py` |
| Pattern rules | `patterns/` (`registry.py`, `engine.py`, `detectors/`), stored in `data/patterns/patterns.db` |
| Forecast | `setups/outlook.py`, `setups/api.py` |
| Sector pages | `patterns/sector_history.py`, `sector_events.py`, `sector_outlook.py` |
| Website pages | `navrist-web/src/components/sites/marketlens/` |
