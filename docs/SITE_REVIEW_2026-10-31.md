# NAVRIST AI – full site review (2026-10-31)

Method: logged in to the local build, called the scanner/stock APIs for the whole 751-stock universe, re-computed filters
independently, compared 24 stocks' numbers with Screener.in (live pages, same day), checked stock page, scanner, popup,
backtest, mobile width. Market was closed (Saturday), so all prices are Friday's close.

## 1. What is correct (verified)
| Area | Result |
|---|---|
| Range filters (mcap, price, RS, %52w low/high, %ATH, free float, turnover, P/E, EPS growth, D/E, promoter, div yield, net profit, 1m/3m/1y returns) | 17 filters tested with a range each: server count == independent count, 0 rows outside range |
| EMA/DMA 200 above/below | Matches my own SMA/EMA from chart candles (RELIANCE, TCS, HDFCBANK, INFY, SBIN, MARUTI, ONGC, HUDCO). TITAN/ITC differ only because scan price is a day older than live |
| Price, market cap vs Screener | Within 0.1–0.5 % (RELIANCE 1,574,584 vs 1,576,405 Cr; TCS, INFY, HDFCBANK, SBIN, ITC, MARUTI, HUDCO, SAMHI all within rounding) |
| 52-week position | Reliance 0.59 % above 52w low (1,152) – matches Screener |
| Dividend yield | Matches Screener (RELIANCE 0.51/0.52, TCS 2.56, HDFCBANK 1.90/1.88, INFY 4.13/4.05, ITC 5.44/5.46) |
| Full-history "All" chart | Fixed today (1995 onward loads) |

## 2. Critical (wrong numbers / broken)
1. **Chart API returns HTTP 500 for ~45 % of stocks** (20 of 44 sampled: ABB, BIOCON, RADICO, PAGEIND, BLUESTARCO, MRPL, DEVYANI, LEMONTREE, …).
   Cause in backend log: `ValueError: Out of range float values are not JSON compliant: nan` on `candles[last].close` –
   the newest candle is NaN (weekend/after-hours row from the data provider) and `/api/live-chart` serialises it.
   Effect: the stock page chart, patterns and every 1D/5Y chart for those stocks is empty.
2. **Fundamentals exist for only 143 of 751 stocks (19 %)**. `data/screens/universe.json` has `pe=None` for BAJFINANCE, TITAN, SUNPHARMA,
   ONGC, STLTECH, CUPID… The build log says "done 751, errors 0" so failed Screener fetches are silently counted as done.
   Every fundamentals filter (P/E, EPS growth, D/E, promoter, div yield, net profit, free float) therefore hides ~80 % of the market.
3. **Wrong P/E in the scanner for demerged / restructured / quarter-basis cases**:
   | Stock | Navrist scanner | Screener |
   |---|---|---|
   | TMPV | 1.19 | 98.1 |
   | JSWDULUX | 6.14 | 31.4 |
   | ASHOKA | 1.10 | 4.00 |
   | ABB | 45.4 | 88.2 |
   | BIOCON | 104.9 | 78.8 |
   | RELIANCE | 21.1 | 19.2 (stock page says 19.52 – three different values) |
   | TCS / INFY | 17.5 / 15.6 | 16.6 / 15.2 |
   TMPV also shows net profit ₹82,378 Cr and EPS 223.7 (pre-demerger Tata Motors numbers).
4. **Same metric, different value on different screens**: TMPV Debt/Equity 0.115 in scanner vs 0.71 on stock page; P/E 3 values for Reliance (above).
5. **Debt/Equity is shown for banks/NBFCs/negative-equity companies** (HDFCBANK 0.98, SBIN 1.30, CHOLAHLDNG 13.6, ALOKINDS 15.1 with book value −44). It is meaningless there; Screener leaves it blank. Filter "D/E < 0.5" will mis-rank these.
6. **Horizontal-resistance Backtest tab 404s** (`Unknown pattern 'horizontal-resistance'`).
7. **Stock page P/E and EPS stay "…" forever** for stocks without a parsed annual report (TMPV: `/stock-eps` returns `pending:true` after 6 s every time).

## 3. Data quality / methodology issues
- Scanner prices are a day behind the stock page (RELIANCE 1,159 vs live 1,164.90; as_of mixes 28 and 29 Oct). No daily refresh job.
- Universe is 751 stocks ("Nifty Total Market") but the home page says "2000+ equity stocks" and search covers more than the scanner. 56 of 751 have no index bucket (not in Large/Mid/Small/Micro) so an index filter drops them.
- 21–22 recent listings have no 52w/RS (TMCV, ICICIAMC, GROWW, LENSKART, MEESHO …). Correctly blank, but they silently disappear from RS and %52w filters.
- "Free float" = 100 − promoter holding. NSE free float is different (it excludes other locked-in holders).
- "Multiple EMA/DMA periods" = OR (any one), not AND; the popup does not say so.
- `% from 52w low 0–10 %` returns 311 stocks (41 %). Correct for a falling market but worth a market-breadth banner.
- Pattern detectors are loose: Double Bottom fires on 133 of 751 stocks right now and 4,008 historical occurrences (≈5.5 per stock), Cup & Handle 395. Real traders expect a handful.
- Backtest: overlapping signals counted as independent trades, no costs/slippage, survivorship (today's universe only), only ~5–6 years of history, entry = signal-day close. Statistics (win rate 52 %, PF 1.5) are optimistic and should carry a disclaimer.
- Demerged stocks keep unadjusted/odd history: TMPV all-time-high ₹1,179 (old Tata Motors), ATH/returns for corporate actions unreliable.
- Stock page "Financial Result (Amount in ₹ Lakhs)" – axis in lakhs (-50L … 200L) is unreadable for large caps; Indian investors read in crore.
- Peer names show raw HTML: `M &amp; M` / `M&AMP;M`; names truncated ("Hyundai Motor I").

## 4. Performance
- `/api/v1/stock-overview/<sym>` took 14–38 s (10 in parallel), ~17 s alone for RELIANCE (live scrape of Screener). `/stock-eps` ~6 s. First paint of Key Metrics is slow; Groww/Screener show it in < 1 s.
- Global search takes ~3 s to return the first result ("Searching…").
- Every page load issues duplicate requests (stock-overview, profile, eps, quote ×2).
- Fix: precompute into the scan/DB nightly, serve stale-while-revalidate.

## 5. UX / UI review (as a trader / broker-app user)
Good: dark theme, TradingView chart with ranges + style toggle + volume, recents, honest note in Fundamentals ("Known for 143 stocks"), scanner cards with neckline/invalidation, mobile layout has no horizontal scroll.

Needs work:
1. **No market status** – no "Market open / closed, last updated 15:30", no "as of" on prices. The red dot on the `LIVE` pill looks like "recording / live" even when the toggle is off and the market is closed.
2. **Above the fold on the stock page**: ticker + header + back link + title + price push the chart below the fold (laptop 800 px high). Put price, day change, 52w bar and chart in the first screen; make header compact.
3. **No actions** a broker/trader expects: Watchlist star, Buy/Sell/Alert, compare, share, notes. (ChartsMaze phase 2 items.)
4. **Create Screener popup**: no live "N stocks match" counter, no summary of active filters inside the popup, filters hidden after long scroll (Market cap appears below DMA). Add sticky count, collapsible groups, preset screens (e.g. "52-week breakout", "Momentum RS > 80").
5. **Fundamentals missing for traders**: ROE, ROCE, sales growth, profit growth, P/B, PEG, EV/EBITDA, interest coverage, promoter pledge, FII/DII change, 52-week high proximity, volume spike, delivery %, circuit/ASM lists.
6. **Results table** (scanner list): add column chooser, saved sort, row hover mini-chart, bulk add to watchlist, export current columns, shareable URL of filters.
7. **Mobile**: Market cap wraps to two lines ("₹15,74,584.00 Cr" – drop decimals, use compact "₹15.7 L Cr"); popup should be a full-screen sheet; chart height should adapt.
8. **Numbers**: use Indian grouping consistently; show `—` with a tooltip reason when a value is not available (the app does this in places, not everywhere); always say which basis (TTM / annual / consolidated / standalone).
9. **Loading states**: "…" placeholders for P/E / EPS never time out; show skeleton → value or "Not available yet".
10. **Accessibility**: pill buttons rely on colour for active state; keyboard focus ring on chart toolbar; contrast of grey helper text on dark background is low.
11. **Trust**: add data source + timestamp footers per block; backtest disclaimer; "not investment advice".

## 6. Suggested fix order
1. NaN → null in `/api/live-chart` (one-line, unblocks 45 % of charts).
2. Rebuild fundamentals for all 751 (retry failures, mark failed ≠ done) and recompute P/E/EPS from one definition (Screener TTM, consolidated-first); handle demergers; D/E "NM" for financials/negative equity.
3. One source of truth for every metric used on both scanner and stock page.
4. Nightly refresh of scanner data; show "as of".
5. Horizontal-resistance backtest route; N-matches counter in popup.
6. Speed: precompute stock overview; cache search.
7. UX items above.
