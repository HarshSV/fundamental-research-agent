# NAVRIST AI: what comes from where

Updated 20 November 2026. Every row: what you see, and where it comes from. Unknown values are shown as unavailable, never as 0.

## Sources at a glance

| Source | How it is read | Used for |
|---|---|---|
| Angel One | SmartApi Python client: login with API key, client code, password and time-based code; live quote call; getCandleData for 5-minute and daily bars (about 100 days per call, so fetched in 90-day chunks and each chunk checked) | Live price, day range, volume, VWAP, 5-minute bars for the intraday forecast, stock list |
| Yahoo Finance | yfinance library: Yahoo chart data per ticker, bars adjusted for splits and bonus | Chart history, returns, indices, patterns, forecasts, the whole scanner, industry and figures for BSE-only stocks |
| NSE daily price files | NSE's bhavcopy (nsearchives.nseindia.com, one file per trading day after the close: open, high, low, close, volume) | The newest sessions' bars of NSE-listed stocks in the scanner replace Yahoo Finance's, which can be a mid-session snapshot (Setups, gaps, volume and gainers lists). Not used for BSE-only stocks |
| NSE symbol-change list | nsearchives.nseindia.com/content/equities/symbolchange.csv | Lets the NSE price files be matched to a company renamed on NSE (ICICIPRULI to ICICILIFE) |
| NSE main-board universe | The newest NSE daily price file (EQ and BE series) with the NSE company master (EQUITY_L.csv) | The scanner covers NSE companies outside the Nifty Total Market too (sector shown as unknown); ETFs and SME-board companies are left out |
| Screener.in | Company page fetched and its tables read; consolidated first, standalone when no consolidated table; 2 workers because of rate limits | Market cap, face value, D/E, P/E, results, shareholding, peers, quarterly data, industry classification |
| NSE | Public files and APIs: EQUITY_L.csv, fo_mktlots.csv, daily sec_list files, ASM report, bulk and block deal files, event calendar, corporate announcements and actions, all indices, index constituent lists, Market Lens company profile, shareholding filings, XBRL | Company names, profile, listings, F&O list, price bands, ASM, deals, results dates, orders, indices, holidays |
| BSE | Scrip codes, Annual Report links and PDFs | Annual Report link, EPS, ratios, BSE-only company list (2,642 added) |
| Annual Report PDF | Statement pages located, units detected, table rows read | Core fundamentals, EPS |
| Google News | Search with before and after dates | Stock news headlines, headlines for past sector months |
| Supabase | Postgres tables | Company registry (about 2,409 NSE companies plus BSE-only), ratio values, price tables |
| Browser local storage | Kept on the user's device | Watchlist, journal, saved filters |

## Home and global

| What you see | Where it comes from |
|---|---|
| Landing page with typing headline | Static page |
| Index ticker (NIFTY 50, BANK, NEXT 50, 100, 500, IT, AUTO) | Yahoo Finance |
| Search (NSE and BSE companies) | Angel One stock list + NSE company names + Supabase company table + BSE company list |
| Top bar: Screeners menu, Sector Analytics, Watchlist, theme toggle | Page navigation, no data |
| Hidden for now: Tools menu, Journal link, Popular Screens section | Built, not shown |

## Stock page

| What you see | Where it comes from |
|---|---|
| Forecast Highlights (live indicator, forecast cards) | Yahoo Finance daily history for the next session, 5 and 20 sessions; Angel One 5-minute bars for the next 1 to 5 candles |
| Price chart (1D, 1W, 1M, 3M, 6M, 1Y, 5Y, All), line or candles | Yahoo Finance |
| Live price beside Price Range, second-by-second points on hover | Angel One, stamped in the browser as each price arrives |
| Forecast fan, predicted candles, 50/80/95% bands | Calculated from Angel One 5-minute bars (LightGBM and GRU models, calibrated ranges) and Yahoo daily history |
| Chart lines: entry, stop, targets, range, 52-week, 20/50/100/200-day averages | Calculated from Yahoo Finance prices and the pattern results |
| Chart Patterns (32) and Active setups | Yahoo Finance prices, rule-based detectors, history kept in patterns.db |
| Candlestick patterns (13) | Candle rules on price bars, past outcomes counted from history |
| When to buy / reasoning, trade plan, odds | Calculated from the forecast and pattern results |
| Backtest tab | Confirmed pattern occurrences over 5 years, measured 5, 10, 20, 40, 60 bars later, Yahoo Finance prices |
| News | NSE filings, BSE, Google News |
| Open, High, Low, Prev Close, Volume, VWAP, Today's Range | Angel One (Yahoo Finance if Angel has no answer) |
| 52 Week Range, All Time High / Low | Yahoo Finance |
| Returns Performance (1W to 5Y) | Yahoo Finance past prices against the live Angel One price |
| Market Cap, Face Value, Debt / Equity | Screener.in (Yahoo Finance figures for BSE-only stocks when Screener has none) |
| EPS | TTM: sum of the last four reported quarters (Screener.in, period-aware); Annual: latest Annual Report (BSE, NSE as backup) |
| P/E Ratio | Live price divided by the EPS of the chosen basis (TTM or Annual); no P/E when that EPS is negative |
| Financial Result (quarter cards, EPS, PAT, Free Cash Flow) | Screener.in consolidated |
| Shareholding Pattern | Screener.in |
| Peer Comparison (with ROCE) | Screener.in, Yahoo Finance industry as fallback |
| About, Headquarters, Year of Incorporation, MD / CEO, Website | NSE Market Lens (Yahoo Finance if NSE has nothing) |
| Annual Report link | BSE (NSE as backup) |

## Screeners

| What you see | Where it comes from |
|---|---|
| Create Screener (about 40 filters, save, load, share, CSV, list and chart results) | Stored scan files (see below) |
| Technicals: EMA / DMA, MA order, MA uptrend age, 52-week and all-time distances, new-high days, ADR, price, 30-day traded value | Calculated from Yahoo Finance daily prices |
| RS rating (1-99) | 40% 3-month + 20% each 6, 9, 12-month return, ranked across scanned stocks |
| Sector rotation filter | Equal-weighted sector index against Nifty 50 or Nifty 500 (Yahoo ^NSEI, ^CRSLDX), z-score approximation |
| Fundamentals: P/E, EPS growth, D/E, promoter holding, dividend yield, net profit, free float | Screener.in (free float = 100 minus promoter; stocks without a value are left out of that filter) |
| Quarterly growth, OPM, ROE, ROCE, PEG, streaks, FII change | Screener.in quarterly page per stock (12 quarters) |
| Market cap | Screener.in, else Yahoo share count x latest close |
| Miscellaneous: returns, average volume, volatility | Yahoo Finance daily prices |
| Index filter (Large / Mid / Small / Micro cap) | NSE constituent lists: Nifty 100, Midcap 150, Smallcap 250, Microcap 250 |
| Horizontal resistance toggle | A level touched by at least 3 pivot highs within 2%, price up to 5% under it or just through it |
| Preset filters: close spread, inside bar, RS line near high, traded value, gap fill, earnings reaction, match-either group | Stored daily candles, NSE results filing times |
| Flags: F&O only, exclude ASM, price band, block deal, results soon | NSE files |
| Pattern filter (32 patterns, status) | Pattern detectors on Yahoo Finance prices |
| Multiple Scans | Stocks found by every chosen scanner |
| Setups: tight setup, inside bar (daily, weekly, filtered) | Stored daily and weekly candles |
| Volume and gaps: volume gainers, high volume, gap up, gap filling | Stored daily candles |
| Strength and weakness: momentum, RS high before price high, shorting | Stored daily candles, RS rating |

How scanner data is built: universe of the Nifty Total Market stocks (751) plus the BSE-only companies, about 2,970 stocks stored on 20 November 2026; full daily history from Yahoo Finance, measures and patterns computed, one file per stock in `data/pattern_scan/symbols/`. BSE-only stocks have no NSE sector or index, so those filters are blank for them. Fundamentals from Screener.in saved in `data/screens/universe.json` (3,105 companies, 2,927 with P/E or EPS), quarterly data in `data/screens/quarterly.json`. Nothing is fetched while filtering.

## Sector Analytics (one button, toggles inside)

| What you see | Where it comes from |
|---|---|
| Sectors | Equal-weighted returns of scanned stocks, Yahoo Finance prices |
| Sector History (since about 1996) | Yahoo Finance adjusted month-end closes per stock, equal-weighted and compounded, kept in `data/sector_history/` |
| What moved a sector | Biggest months against the market, dated event list kept in code, Google News headlines for a past month, NSE orders, deals and board meetings |
| Sector Outlook (1 and 3 month odds) | Shares of past months in a similar situation followed by a rise, flat or fall; replay of the method on the past |
| Scheduled events ahead | NSE holidays, NSE corporate actions, dates kept by hand (Union Budget); RBI dates not listed |
| Industries (143 groups) | Screener.in classification, Yahoo Finance prices |
| RRG | Sector index against Nifty 50 or Nifty 500 |
| Market Breadth | Stored scan: advances, declines, stocks above 50 and 200-day averages |
| Sector Indices | NSE |
| Top Gainers / Top Losers | Stored scan of Yahoo Finance prices |

## Your tools

| What you see | Where it comes from |
|---|---|
| Watchlist (stars, notes, priorities, share) | Browser local storage |
| Journal (hidden) | Browser local storage |
| Alerts (entry, stop, target, 15:25 exit) | Price rules checked by a background worker; Telegram bot for delivery |

## Tools menu (hidden for now)

| What you see | Where it comes from |
|---|---|
| Results Calendar | NSE board-meeting calendar and outcome announcements, Screener.in |
| Order Wins | NSE corporate announcements |
| Past Winners | Stored Yahoo Finance prices |
| Recent IPOs | NSE EQUITY_L.csv listing dates |
| Circuit Revision List | NSE daily sec_list files compared day to day |
| ASM List | NSE ASM report |
| Bulk / Block Deals | NSE deal files, each day appended |

## Fundamental ratios

| What you see | Where it comes from |
|---|---|
| Core fundamentals | Audited Annual Report PDF (BSE, NSE as backup, or uploaded) through one formula contract; consolidated first, banks standalone |
| P/E, yield, EV | Live Angel One price (Yahoo Finance as backup) with Annual Report figures |
| Beta | Yahoo Finance weekly prices, 2 years, against Nifty 50 |
| Promoter pledge, free float | NSE shareholding pattern filing |
| Calculation breakdown | The ratio contract: every input, formula and source page |
| Precomputed results | Supabase `ratio_values`, recalculated when version numbers change |
| Qualitative A to G | Rule-based scoring over Annual Report text and exchange filings, no AI |

## Stored data

| Place | Holds |
|---|---|
| `data/pattern_scan/` | One file per stock: measures and patterns, benchmarks, index membership |
| `data/screens/` | Screener.in fundamentals and quarterly data |
| `data/patterns/patterns.db` | Pattern history with status changes |
| `data/forecast/market.db` | 5-minute bars, forecast models and tracking |
| `data/exchange/` | NSE listings, F&O, price bands, ASM, deals, calendar, results, orders, indices |
| `data/sector_history/` | Month-end closes per stock |
| `cache/` | Annual Report PDFs, extracted text and facts, NSE XBRL, company names |
| Supabase | Company registry, ratio values, price tables |
| Browser local storage | Watchlist, journal, saved filters |

## Hosting

Next.js website (`navrist-web`) and FastAPI backend (`app.py`) run on the office PC, published at ai.navrist.com through a Cloudflare Tunnel; both start at Windows login. An Oracle deployment guide exists but is not live.

## Source rules

1. The audited filing wins over an aggregator when they disagree.
2. Unknown is never turned into 0.
3. Logic is generic across all stocks.
4. Never ask a source for more than it allows: Screener runs with 2 workers, Angel history is chunked and checked.
