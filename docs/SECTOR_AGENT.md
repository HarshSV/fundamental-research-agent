# Sector specialist agent

Built 2026-11-12 in three phases. It answers three questions about each sector: how it has behaved over the years, what moved it, and what its odds look like
for the next one and three months. **No language model writes any of it** (LLM calls are switched off project-wide): every number is computed from prices and exchange
data, and every sentence on the pages is a template filled with those numbers.

## Where it is

| Where | What |
|---|---|
| Top bar -> **Market Analytics** -> **Sector History** | Phase 1 and 2: history, then "What moved this sector" inside each sector's detail |
| Top bar -> **Market Analytics** -> **Sector Outlook** | Phase 3: odds for the next month and 3 months, the facts beside them, scheduled events, and the replay of the method |
| The tabs on the Market Analytics page | Sectors, **Sector History**, **Sector Outlook**, Industries, RRG, Breadth |

Code: `patterns/sector_history.py`, `patterns/sector_events.py` (+ `sector_events.json`), `patterns/sector_outlook.py`, `patterns/upcoming.py` (+ `upcoming_events.json`);
routes in `patterns/scan_api.py`; pages `SectorHistory.tsx`, `SectorOutlook.tsx` in `navrist-web/src/components/sites/marketlens/`; tests `tests/test_sector_history.py`.

## How it works

```
Price provider (adjusted daily closes, whole history)         NSE feeds (orders, deals, board meetings, holidays, company actions)
        |                                                       Screener.in quarterly results       US Fed calendar       editorial lists
        v                                                                      |
data/sector_history/monthly.json  (month-end closes per stock, refreshed when older than 7 days)
        |
        v   equal-weighted monthly return of each sector's stocks, compounded -> sector index; same for "All stocks"
Sector History  ---------->  Sector events  ---------->  Sector outlook
yearly returns, falls,       biggest months vs market,    odds from similar past situations,
rolling returns, seasons     dated events around them,   tilt against the sector's usual,
                             reaction to each event      current facts, scheduled events, replay
```

### Phase 1 - Sector History (`sector_history.py`)
* `refresh()` reads each scanned stock's full adjusted history (about 3 minutes for 751 stocks, 4 threads) and keeps its month-end closes. It is resumable and runs in the background. A page request that finds the store older than 7 days starts it automatically (stocks younger than 7 days are skipped); `POST /api/v1/market/sector-history/refresh` starts it by hand.
* A sector's monthly return is the average of its stocks' returns that month. A month counts only when at least **5** stocks have a return. Headline figures start once about **half of the sector's stocks (at least 5, at most 8)** have a price, so a sector is never an index of two or three survivors. "All stocks" (every scanned stock, same method) is the yardstick.
* Statistics: yearly growth, best and worst full calendar year, years up, years that beat all stocks, the deepest fall (peak, trough, months to recover), distance from its own peak, rolling 1/3/5/10-year returns (worst, median, best, share positive), average return and share of up-months for each calendar month, and a growth-of-100 curve. **Full history / Last 5 years** toggle.
* Route: `GET /api/v1/market/sector-history?window=full|5y`.

### Phase 2 - What moved it (`sector_events.py`)
* **Biggest months.** For each sector the 6 months it beat, and the 6 it lagged, all stocks the most. Each is labelled "mostly moved with the market" or "specific to this sector" (when the excess is at least half the market's move and 3 points). Events from the list within one month either side are shown as "around then"; if there are none it says so.
* **Reaction to each known event.** The sector's move in the event month and the next 3 months, against all stocks.
* **Sensitivity.** Beta, correlation, the share of the market's rises captured and of its falls taken.
* **Headlines for a past month** (on demand): Google News search with `after:` / `before:`, kept only when the title mentions India or the market. Sparse and sometimes loosely related; the page says so.
* **Happening now:** order announcements (2 weeks), bulk and block deals (30 days, bought vs sold), results and board meetings in the next 3 weeks, for the sector's companies, from `patterns/exchange_data.py`.
* The **event list** (`patterns/sector_events.json`) is *editorial*: about 50 well-known events with month precision, written by the assistant from general knowledge and not pulled from a feed. A month could be wrong; correct it in the file. An event beside a move is never presented as its cause.
* Routes: `/api/v1/market/sector-events?sector=`, `/sector-headlines?sector=&month=`, `/sector-recent?sector=`.

### Phase 3 - Sector Outlook (`sector_outlook.py`, `upcoming.py`)
* A sector's **situation** in a month is three yes/no facts known at that month's end: rose over the last 3 months, beat all stocks over the last 6 months, more than 15% below its own peak.
* **The odds** are the shares of past months in the same situation followed by a clear rise, a flat stretch, or a clear fall ("clear" = more than a quarter of the sector's typical move over that horizon, the same rule as the stock forecast). With fewer than 30 such months for the sector, the same situation across all sectors is used, then all of the sector's months (`basis` says which). Also: chance of beating all stocks, and the 10th / 50th / 90th percentile of past outcomes.
* **Tilt** = the situation's chance of a clear rise minus the sector's usual chance (under 5 points: "usual odds"; 5-10 "slightly"; 10 or more "clearly" better or worse). The table is sorted by the 3-month tilt.
* **Replay (`validation()`).** The method is replayed month by month using only outcomes already known at each month (about 4,700 sector-months). Result on 2026-11-12: over 3 months, when the situation made a rise 10+ points more likely the sector rose in **66.6%** of 1,078 months, against **63.1%** in all tested months, and **61.6%** when it made a rise less likely; for beating all stocks, **50.1%** / **42.9%** against **45.7%**. Plain "up" calls were right about 59% of the time over a month, but the sector rose in about 60% of months anyway - no edge. The edge from the tilt is a few percentage points, and the page says to read it as a lean, not a call.
* **Facts beside the odds (not blended in):** trend and strength against all stocks, share of stocks above their 50 and 200-day averages, rotation quadrant, this quarter's results (reported, median sales and profit growth, share with higher profit), order and deal flow, results due, dividends/bonus/splits/buy-backs with ex-dates in 30 days, the usual pattern of the next 3 calendar months, and what the sector did in past 10% market rises and falls (from its capture ratios).
* **Scheduled events ahead (`upcoming.py`):** only events with a published date: US Fed policy decisions (federalreserve.gov, two-day meetings only), NSE trading holidays (NSE holiday-master), dates kept by hand in `patterns/upcoming_events.json` (currently the Union Budget, 1 Feb 2027, marked *expected*), and per-sector company actions (NSE corporate actions) and board meetings. **RBI policy dates are not listed**: RBI does not publish them where we can read them reliably, so the page links to current headlines about the FY27 schedule; add the dates to `upcoming_events.json` once taken from RBI's own calendar. A source that cannot be read is named on the page, never replaced by a guess. The odds are **not adjusted** for these events.
* Route: `GET /api/v1/market/sector-outlook`.

## Limits
* **Not since 1990.** Stock history starts about 1996 (market series: December 1995); sector figures start between 2000 and 2007 or later for sectors that listed later. Official sector indices on the price provider start only in 2007-2011. BSE yearly prices for 1991-1995 exist but are raw (not adjusted for splits and bonuses) and BSE's company-action records start around 2000, so they cannot be joined safely; they are not used.
* **Survivorship.** Only stocks listed today are included, so past returns (and the share of rising months) are flattered. Read comparisons between sectors, not the absolute figures.
* **Equal-weighted** averages of about 750 scanned stocks, not the official indices; dividends excluded.
* Diversified (3 stocks) and Forest Materials (1) have too few stocks and are listed as not shown.
* Overlapping 3-month windows are not independent; the replay's counts overstate how much independent evidence there is.
* The headline-per-month search and the event list are the weakest parts: sparse, and partly editorial.

## Maintaining it
* Refresh the price store: it tops itself up in the background when a page request finds it older than 7 days; by hand use `POST /api/v1/market/sector-history/refresh`, and to rebuild everything run `python -c "from patterns import sector_history as s; s.refresh(max_age_days=0)"`.
* Edit events: `patterns/sector_events.json` (past), `patterns/upcoming_events.json` (future).
* Tests: `python -m pytest tests/test_sector_history.py` (made-up price series for the maths; the Fed parser and the "unreadable source is reported" rule).
