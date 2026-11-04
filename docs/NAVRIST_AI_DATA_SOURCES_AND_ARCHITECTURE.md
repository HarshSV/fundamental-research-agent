# NAVRIST AI: where our data comes from (architecture, 2026-10-31)

This replaces the older "what comes from where" sheet. It now includes the new **Create Screener / pattern scanner filters**, the scanner stored data, the Popular Screens, and the stock-page data.

**How to read it:** every row says *what you see* and *where it comes from*. "Calculated by us" means we compute it ourselves from raw prices or filings. Nothing here is an AI guess: all AI (Groq/OpenRouter) is switched off.

---

## 1. The big picture

| Layer | What it does | Main things in it |
|---|---|---|
| **1. Outside sources** | Where raw data is born | Angel One, Yahoo Finance, Screener.in, NSE, BSE, company Annual Report PDFs |
| **2. Our collectors** | Download, clean, cache | `tools/` scrapers, `patterns/scan.py`, `screens/build_cli.py`, precompute worker |
| **3. Our storage** | Keep results so pages load fast | Supabase tables, `data/pattern_scan/` (one file per stock), `data/screens/universe.json`, `data/patterns/patterns.db`, `cache/` folders |
| **4. Our calculators** | Turn raw data into numbers | 68-ratio contract, 32 pattern detectors, scanner metrics, RS rating, sector rotation, backtest |
| **5. Our API** | FastAPI `app.py` and routers | `/api/v1/patterns/...`, scan API, screens API, stock overview, live quote |
| **6. The website** | What the user sees | Next.js app (`navrist-web`): home, stock page, Create Screener, scanner results, backtest |

**Flow in one line:** outside sources, collectors, storage, calculators, API, website. A login (our own password and token) guards the API.

---

## 2. The outside sources and what each is used for

| Source | Used for | Notes |
|---|---|---|
| **Angel One** (SmartAPI) | Live price, day range, volume, VWAP, 5-minute and daily bars for forecasts | Needs login every session; history calls are limited and can silently cut data |
| **Yahoo Finance** | Chart history, 52-week and all-time measures, returns, indices, patterns, **everything in the scanner** | Newest candle can be empty (NaN), which breaks some charts |
| **Screener.in** | Market cap, face value, D/E, P/E, EPS, promoter holding, dividend yield, financial results, shareholding, peers | Rate limited. We fetch slowly (2 workers). Many stocks return nothing |
| **NSE** | Index membership lists, sector list, company names, About/profile (Market Lens), shareholding and pledge filings, XBRL results | Blocks cloud IPs; XBRL list is old |
| **BSE** | Annual Report links and PDFs, scrip codes | Filings are PDFs |
| **Company Annual Report PDF** | All 68 ratios, EPS | Our main audited source |
| **Our Supabase company table** | Company registry (~2,409 companies) for search | |

Not used: Dhan (not integrated), Upstox and Axis (test scaffolding only), any AI model.

---

## 3. Home page and global parts

| What you see | Where it comes from |
|---|---|
| Index ticker (NIFTY 50, BANK, NEXT 50, 100, 500, IT, AUTO) | Yahoo Finance |
| Search (list of stocks) | Angel One stock list + NSE company names + our Supabase company table |
| Popular Screens (23 named screens in 5 groups) | Screener.in fundamentals + Yahoo Finance prices, **calculated by us** (see section 7) |
| Scanner tiles (Create Screener, Horizontal Resistance, Browse by Pattern) | Our scanner data (section 5) |
| Sector pages | NSE sector list stored in our code (`frontend/src/lib/nseSectorMap.js`, and `tools/nse_sector_map`) |
| Login | Our own password and token, no outside source |
| Saved filters (Save / Load / Share) | This browser's local storage only; Share makes a code you can paste |

---

## 4. Stock page

| What you see | Where it comes from |
|---|---|
| Live price | Angel One |
| Open, High, Low, Prev Close, Volume | Angel One (Yahoo if Angel has no answer) |
| VWAP | Angel One (average traded price) |
| Today's Range | Angel One |
| Second-by-second points on hover (LIVE) | Our own browser: each new live price from Angel is timestamped as it arrives |
| Price chart (1D, 1W, 1M, 3M, 6M, 1Y, 5Y, All) | Yahoo Finance |
| 52 Week Range | Yahoo Finance (last 365 days of daily prices) |
| Returns Performance (1W to 5Y) | Yahoo Finance past prices, divided into the live Angel price |
| All Time High / Low | Yahoo Finance (full price history) |
| Chart Patterns (32) | Yahoo Finance prices; patterns found by our own rules |
| Horizontal resistance line on chart | Calculated by us (section 5.4) |
| Backtest tab | Calculated by us from confirmed pattern occurrences (section 5.6) |
| Market Cap, Face Value, Debt / Equity | Screener.in |
| EPS | Company's latest Annual Report (BSE, NSE as backup), checked against Screener.in; Screener.in is used if they differ |
| P/E Ratio | Live Angel price divided by the EPS above |
| Financial Result (bar chart) | Screener.in (consolidated) |
| Shareholding Pattern | Screener.in |
| Peer Comparison | Screener.in |
| About (description) | NSE Market Lens (Yahoo Finance if NSE has nothing) |
| Headquarters, Year of Incorporation, MD / CEO, Website | NSE Market Lens (Yahoo Finance if NSE has nothing) |
| Annual Report link | BSE (NSE as backup) |

---

## 5. Create Screener / pattern scanner (the new filters)

### 5.1 How the scanner data is built

1. Take the **751-stock universe** (Nifty Total Market, sector-mapped).
2. Download each stock's **full daily history from Yahoo Finance**.
3. Our code (`patterns/features.py`) computes all measures and runs the pattern engine.
4. Results are saved as **one file per stock** in `data/pattern_scan/`, plus `benchmarks.json` (index prices for sector rotation) and `indices.json` (index membership).
5. Fundamentals come separately: `python -m screens.build_cli` fetches Screener.in pages and saves `data/screens/universe.json`.
6. The scan API filters these saved files. Nothing is fetched live while you filter.

### 5.2 Technicals tab

| Filter | Where it comes from |
|---|---|
| EMA / DMA above or below (periods 10, 20, 50, 100, 200) | Calculated by us from Yahoo daily closes. Choosing several periods means ANY one (OR) |
| MA order (e.g. 50 above 200) | Calculated by us from the moving averages |
| MA uptrend age (rising for N months) | Calculated by us: count of consecutive rising days of the average |
| % from 52-week low / high | Calculated by us from Yahoo daily highs and lows over 365 days |
| % from all-time high | Calculated by us from the full Yahoo history |
| New high in last N days | Calculated by us: sessions since the latest new 52-week high |
| ADR (average daily range, N days) | Calculated by us: average of (high / low - 1) in % |
| Overall RS rating (1-99) | Calculated by us: 40% 3-month plus 20% each 6, 9, 12-month performance, ranked against every scanned stock |
| Stock price | Yahoo Finance latest daily close (about a day behind live) |
| Avg price x volume, 30 days (₹ Cr) | Calculated by us: average of close x volume over the last 30 days |
| Free float | 100 minus promoter holding from Screener.in (NSE's own free float is different) |
| Sector rotation (leading / improving / weakening / lagging) | Calculated by us: equal-weighted sector index against Nifty 50 or Nifty 500 (Yahoo `^NSEI`, `^CRSLDX`); a z-score approximation of a rotation graph |

### 5.3 Fundamentals tab

All of these come from **Screener.in**, saved by `screens.build_cli`. **A stock with no value is left out of that filter. It is never treated as 0.**

| Filter | Where it comes from |
|---|---|
| P/E ratio | Screener.in |
| EPS growth (annual CAGR) | Screener.in (needs 3 or more years) |
| Debt / Equity | Screener.in |
| Promoter holding | Screener.in |
| Dividend yield | Screener.in |
| Net profit (latest year, ₹ Cr) | Screener.in |
| Market cap | Screener.in figure when known, else Yahoo share count x latest close |

Current coverage: only **143 of 751** stocks have fundamentals, so these filters hide most of the market.

### 5.4 Miscellaneous tab

| Filter | Where it comes from |
|---|---|
| 1m, 3m, 6m, 1y, 3y, 5y returns | Calculated by us from Yahoo daily closes (calendar-day look-back) |
| Avg volume, 30 days | Calculated by us from Yahoo volume |
| Volatility (annualised) | Calculated by us from Yahoo daily returns |
| Index filter (Large / Mid / Small / Micro cap) | NSE's own constituent lists: Nifty 100, Midcap 150, Smallcap 250, Microcap 250 (`nsearchives.nseindia.com/content/indices/`). 56 stocks belong to none |
| Horizontal resistance | Calculated by us: a level touched by at least 3 pivot highs within 2%; price up to 5% under it or just through it |

### 5.5 Pattern filter

| What | Where it comes from |
|---|---|
| 32 chart patterns and their status (Forming, Awaiting breakout, Confirmed, Invalidated) | Calculated by us from Yahoo daily prices with our own rules (`patterns/detectors/`), history stored in `data/patterns/patterns.db` |
| Neckline, invalidation level on each card | Calculated by us |

### 5.6 Results page

| What you see | Where it comes from |
|---|---|
| List and Charts view, 1 or 2 charts per row | Saved scanner files; charts drawn with TradingView Lightweight Charts on Yahoo candles |
| Technicals / Fundamentals columns | Same as sections 5.2 and 5.3 |
| CSV download | Built in the browser from the shown results |
| Backtest tab | Calculated by us from confirmed occurrences over the last 5 years, measured 5, 10, 20, 40, 60 bars later |

---

## 6. Ratios (68) and fundamentals page

| What you see | Where it comes from |
|---|---|
| All 68 financial ratios | **Audited Annual Report PDF** (BSE, NSE as backup, or uploaded), through one formula contract (`tools/ratio_contract.py`) |
| Basis | Consolidated first; standalone only if no consolidated exists; banks standalone |
| Live-price ratios (P/E, yield, EV) | Live price from Angel One (Yahoo as backup) with the report figures |
| Beta | Yahoo weekly prices, 2 years |
| Promoter pledge, free float | Shareholding Pattern filing / NSE endpoint (marked needs-review if secondary) |
| Inventory turnover cross-check | NSE XBRL standalone filings (when available) |
| Calculation breakdown | Our contract: shows each input, formula and source page |
| Precomputed results | Supabase `ratio_values`, recalculated when version numbers change |
| Qualitative A to G | Rule-based from Annual Report and exchange filings; no AI |

---

## 7. Popular Screens (23 screens)

Built in `screens/definitions.py`. Each screen is a set of simple rules (for example price at or below ₹150 and EPS at or above ₹15). The thresholds are **Navrist's own**, not NSE's.

| Input | Where it comes from |
|---|---|
| Price, returns, volume, volatility | Yahoo Finance daily prices, calculated by us |
| EPS, P/E, promoter, D/E, dividend yield, payout, cover, EPS growth, net profit | Screener.in |
| "Top volume" and "low volatility" | Percentile of the screened universe |

A stock matches only if **every** value the screen needs is known.

---

## 8. Stored data: what lives where

| Place | Holds | Refreshed |
|---|---|---|
| `data/pattern_scan/` | One file per stock: metrics, patterns; plus `benchmarks.json`, `indices.json` | By running a scan (no automatic daily job yet) |
| `data/screens/universe.json` | Screener fundamentals per stock | By `screens.build_cli`; counted stale after 24 hours |
| `data/patterns/patterns.db` | Pattern history with status changes | On each pattern request (cached by last bar) |
| `data/forecast/market.db` | Forecast bars and models (git-ignored) | Forecast scheduler |
| Supabase | Company registry, ratio values, EOD and intraday price tables | Precompute worker |
| `cache/` | Annual Report PDFs (30 days), extracted text and facts (90 days), NSE XBRL, company names | On demand |
| Browser local storage | Login token, saved filters | By the user |

---

## 9. Known limits of the data (be honest in the UI)

| Limit | Effect |
|---|---|
| Scanner universe is **751** stocks, home says 2000+ | Stocks outside it never appear in the scanner |
| Fundamentals exist for **143 of 751** | Fundamentals filters hide about 80% of stocks |
| Failed Screener fetches were counted as "done" | Looks complete when it is not |
| Scanner prices are a day behind the stock page | No daily refresh job and no "as of" label yet |
| Demerged or restructured stocks (for example TMPV) | Wrong P/E, EPS, all-time high |
| Scanner P/E differs from Screener and from the stock page | Different definitions; needs one source of truth |
| Debt / Equity shown for banks and negative-equity firms | Meaningless there; should be "NM" |
| Chart API fails for about 45% of stocks (empty newest candle) | Stock page chart empty for them |
| Free float is 100 minus promoter | Not NSE's free float |
| 21 to 22 new listings lack 52-week and RS data | Silently missing from those filters |
| Patterns are loose and untuned | Too many matches (Double Bottom on 133 stocks) |
| Backtest ignores costs and overlap, uses today's stocks only | Results look better than real life |
| ChartsMaze's own Fundamentals and Miscellaneous filters were not visible | Ours are our own choice |

---

## 10. Source rules we follow

1. The audited filing wins over an aggregator (Screener) when they disagree.
2. Unknown is never turned into 0.
3. Every number should carry its source, basis (consolidated/standalone, TTM/annual) and date.
4. Logic is generic across all stocks; no stock-specific rules.
5. Never ask a source for more than it allows: Screener runs with 2 workers, Angel history is chunked and checked.

*Related:* `docs/DATA_SOURCES.md` (short table), `docs/PATTERNS.md` (32 patterns), `docs/PROJECT_HISTORY_AND_LESSONS.md` (full story), `docs/SITE_REVIEW_2026-10-31.md` (latest review).
