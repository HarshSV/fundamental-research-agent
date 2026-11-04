# NAVRIST AI: the full story, in plain words

**What this is:** one place that explains what we built, in what order, where every piece of data comes from, what we tried, what failed, and what we decided because of it. Read it once and you will not repeat our mistakes.

**Written:** 2026-10-31. **Based on:** project notes, git history, `PROJECT_DOCUMENTATION.md`, `docs/PROJECT_CHANGELOG.md`, `docs/DATA_SOURCES.md`, `docs/SITE_REVIEW_2026-10-31.md`, and the validation reports in `docs/`.

**Honesty note:** where a number or claim comes from an older record that I did not re-run today, it says "recorded". Nothing here is invented. If something was never tested, it says so.

---

## Contents

1. [What Navrist is (30 seconds)](#1-what-navrist-is)
2. [The timeline at a glance](#2-the-timeline-at-a-glance)
3. [Where all data comes from](#3-where-all-data-comes-from)
4. [Stage by stage: what we built, tried and what failed](#4-stage-by-stage)
5. [Master list of failures](#5-master-list-of-failures)
6. [Things we rejected on purpose, and why](#6-things-we-rejected-on-purpose)
7. [Rules we learned (do not break these)](#7-rules-we-learned)
8. [Open problems today](#8-open-problems-today)
9. [Quick "before you start" checklist](#9-before-you-start-checklist)

---

## 1. What Navrist is

An internal stock research terminal for Navrist (a trading and investment firm). It started as "fundamental research" and is meant to be phase 1 of a bigger AI-agent suite.

It now has these parts:

| Part | In one line |
|---|---|
| **Fundamental ratios** | 68 financial ratios per company, calculated from the company's audited Annual Report |
| **Qualitative analysis** | Business model, moat, governance and similar topics (sections A to U, only A to G built) |
| **Live chart and patterns** | TradingView-style chart with 32 chart-pattern detectors |
| **Pattern scanner / Create Screener** | Filter ~751 stocks by technicals, fundamentals and patterns (modelled on chartsmaze.com) |
| **Forecast system** | 5-minute and daily probabilistic forecasts (a pilot, 8 stocks) |
| **Ask Navrist chatbot** | Built, then switched off on purpose |

---

## 2. The timeline at a glance

| When | What happened | Result |
|---|---|---|
| 2026-06-21 | First commit: NSE scraper, earnings-surprise engine, orchestrator | Still in repo, not used for ratios |
| 2026-06-24 to 07-03 | First research agent: LangGraph + Angel One + Groq AI + FastAPI + one big HTML page + login | Worked but **slow (8 to 9 minutes per report)** |
| 2026-07-03 | Groq daily limit hit, all AI features broke at once. Another IDE's uncommitted work saved to branch `antigravity-backup` | Led to the fallback chain, later to disabling AI |
| 2026-07-08 | **Rework decisions**: speed first, Screener as main source, no vector DB, keep Groq | Speed fixed; Screener-main and keep-Groq were **later reversed** |
| July 2026 | Real statements: first NSE XBRL, then Annual Report PDFs | PDFs became the main source |
| 2026-07-15 to 07-20 | Supabase database, company registry, Vite frontend | Precompute instead of live parsing |
| 2026-07-21 | Ratios 41 to 68, first bank ratios | Bank part later rewritten |
| 2026-07-24 to 07-31 | QA review found many ratio bugs, fixed one by one | Many fixes, root cause was 3 engines with 3 definitions |
| 2026-08-08 to 08-20 | Qualitative A to G built, rule-based | H to U not built |
| 2026-08-19 | **All AI (Groq/OpenRouter) switched off** | Report time fell to about 65 seconds |
| 2026-09-03 | Manual document upload, evidence engine | Later unified with automatic path |
| 2026-09-28 to 10-05 | Live chart, patterns, forecast pilot | Ranges work, direction does not |
| 2026-10-07 to 10-09 | **Ratio contract**: one formula for each ratio, breakdowns, global audit | Verdict **NOT READY** (see section 8) |
| 2026-10-21 | Pattern agent: 32 patterns with forming-to-confirmed lifecycle | Thresholds not tuned |
| 2026-10-30 | Pattern scanner and Create Screener (chartsmaze-style) | Phase 1 built |
| 2026-10-31 | Full site review | Found 7 critical issues (section 8) |

---

## 3. Where all data comes from

### 3.1 Price and market data

| What you see | Source | Notes |
|---|---|---|
| Live price, Open/High/Low, Volume, VWAP | **Angel One** | Yahoo if Angel has no answer |
| Price chart history, 52-week range, returns, all-time high/low | **Yahoo Finance** | Also used for patterns and the scanner |
| Index ticker (NIFTY 50 etc.) | Yahoo Finance | |
| Beta (Sr 66) | Yahoo weekly prices, 2-year window | QA agreed to keep 2 years |
| 5-minute and daily bars for forecasts | Angel One `getCandleData` | Has quirks, see section 4.10 |
| Index membership (Large/Mid/Small/Micro) | NSE index lists (Nifty 100, Midcap 150, Smallcap 250, Microcap 250) | 56 of 751 stocks fall in none |

### 3.2 Company financial data

| What | Source | Notes |
|---|---|---|
| **All 68 ratios (main path)** | **Audited Annual Report PDF** from BSE, NSE as backup, or uploaded by hand | Consolidated first, standalone only if no consolidated exists. Banks use standalone |
| Structured audited results | **NSE XBRL** | Backup/cross-check. NSE's list was about 1.5 years out of date in July 2026 |
| Market cap, Face Value, Debt/Equity, financial result bars, shareholding, peers | **Screener.in** | **Not** used for the 68 ratios on purpose |
| EPS and P/E | Annual Report EPS, checked against Screener; P/E = live price / EPS | |
| About, HQ, CEO, website | NSE Market Lens, Yahoo as backup | |
| Promoter pledge (Sr 67), free float (Sr 68) | Shareholding Pattern filing / NSE endpoint | Marked "needs review" when from the secondary source |
| Scanner fundamentals (P/E, EPS growth, D/E, promoter, yield) | Screener.in via `python -m screens.build_cli` | Slow, rate limited, only 143 of 751 stocks have it |

### 3.3 Calculated by us

Moving averages, RS rating, sector rotation, horizontal resistance, ADR, all 32 patterns, backtest. All computed from Yahoo daily prices. Stored one file per stock in `data/pattern_scan/`.

### 3.4 Sources that exist in the code but are **not** part of the ratios

| Source | Status |
|---|---|
| Groq / OpenRouter AI | Code present, **disabled** |
| Dhan | **Not integrated** anywhere. Do not claim it is |
| Axis RAPID, Upstox, Zerodha Kite | Scaffolding only (Axis used for live chart in test mode) |
| Apify Screener actor | Used early on, later dropped from the hot path |
| BSE segment results PDF | Used for segment revenue only |

---

## 4. Stage by stage

Each stage says: **what we did**, **what failed**, **what we learned**.

### 4.1 Stage 1: the first research agent (June to early July 2026)

**Built:** LangGraph agent, Angel One + yfinance data, Groq AI for qualitative text, FastAPI backend, one 8,416-line React page loaded from a CDN, shared-password login.

**Failed / went wrong**

| Problem | Cause |
|---|---|
| A report took **8 to 9 minutes** | Everything ran one after another: 6+ yfinance calls in a row, 3 uncached history downloads, up to 3 concall PDFs at 30 s each, Apify cold starts, Angel re-login every request, and the whole agent ran on the web server's main loop. **Groq was not the slow part** |
| Groq daily quota (100k tokens) ran out on 2026-07-03 | Every AI feature broke at once: empty canvas, "Summary generation failed" |
| Page crashed with "[object Object]" | The small fallback AI model returned list items as objects or bare strings. One bad value crashed React and wiped the page |
| Early "moat" score was an AI guess with canned "8/8" fallbacks | Replaced by a data-driven moat score |
| Fabricated filler values in qualitative text | Removed. Rule now in `CLAUDE.md` |
| Auth was first planned as email + password per user, then changed to **one shared password** | No per-user audit trail. The password text also leaked into git history (open issue) |

**Fix for Groq:** a two-model chain (70b, then 8b when rate-limited), loose JSON repair, trimmed inputs, and normalising every AI list before showing it.
**Learned:** never render AI output fields directly; always clean them first.

### 4.2 Stage 2: the 2026-07-08 rework decisions

| Decision | What happened later |
|---|---|
| Speed first (8 to 9 min down to under 75 s cold) | Done, mainly by caching, precompute, and switching AI off |
| Screener.in as the main financial source | **Reversed.** Audited filings became the source, because Screener re-labels and re-derives numbers |
| Grounded retrieval, no vector DB | Never needed (AI disabled) |
| Keep Groq | **Reversed** on 2026-08-19 |

### 4.3 Stage 3: getting real financial statements

This was the longest struggle in the project. Three attempts:

| Attempt | Result | Why |
|---|---|---|
| **yfinance / Screener / Angel statements** | Not enough | They lack line items like Inventory and Cost of Materials |
| **NSE XBRL** (machine-readable audited results) | Worked for a few ratios, then hit a wall | NSE list ~1.5 years stale (newest annual was FY24 in July 2026). Quirk: NSE mislabels the annual start date, so you must pick the year by the longest duration. Taxonomy changed at FY23: older filings have no balance-sheet inventory, so only Tata Steel FY24 was computable. NSE also blocks datacenter IPs |
| **BSE PDFs** | First rejected, then adopted | BSE has current filings but only as PDFs. Text and numbers are spatially separated and tables have no borders, so simple extraction guessed wrong numbers. The July note said "don't revisit BSE". The code later **did** rely on PDFs, with no record of that reversal |

**Final answer:** parse Annual Report PDFs, with identity checks (does assets = liabilities + equity?) to catch misreads. XBRL stays as backup.

### 4.4 Stage 4: database and registry (July 2026)

- **Why a database:** every search re-downloaded and re-parsed the PDF, taking 3 to 4 minutes per company.
- **Choice:** Supabase (compared AWS RDS, Aurora+Timestream, Neon, self-hosted TimescaleDB). Free tier (500 MB) will be tight, Pro ($25 a month) expected.
- **Built:** tables `companies`, `ratio_values`, `price_eod`, `price_intraday`, `refresh_jobs`; a precompute worker; a registry of about 2,409 companies.
- **Not done:** intraday data needs a paid vendor (Kite historical, Global Datafeeds, TrueData). Angel and yfinance do not give long intraday history. No vendor chosen, so `price_intraday` stays empty.
- **Mistake to avoid:** the Supabase keys were pasted into chat in plain text. They are stored only in `.env`, but rotating the service_role key was recommended and never confirmed.
- **Gotcha:** the table's status field has a CHECK rule that does not allow `not_meaningful`; the real status lives in metadata.

### 4.5 Stage 5: frontend rebuild

| Step | Result |
|---|---|
| Move from CDN/Babel page to a Vite build | Done, verified |
| Real light and dark theme tokens | Done |
| Sidebar and mobile nav "reskin" | **User rejected it**: "same as old UI" |
| Ground-up redesign (landing page, header, overview) | Built, but **could not be viewed logged in** because everything sits behind the login and the browser extension was not connected |
| Vercel deploy | **Never tested** |
| Later: a separate Next.js app (NSE Market Lens-style) for the new site | Current main UI |

**Learned:** a UI behind a password cannot be verified by the assistant. The user must log in and look.

### 4.6 Stage 6: the 68 ratios and the QA loop (July 2026)

QA reviewed ratios and flagged bugs. Examples (all real):

| Ratio | Bug | Cause |
|---|---|---|
| Payables Turnover / DPO / CCC | Wrong payables on HUL | A second row also labelled "Trade payables" sits under a sub-heading after the MSME row |
| ROE | Equity 40% too high | "Total equity" is a substring of "Total equity **and liabilities**" |
| ROCE, Interest Coverage | EBIT inflated | PBT includes Other Income |
| Operating margin | QA saw stale number | Old cached value, code was already right |
| Inventory Turnover | Failed on Dabur, Gopal Snacks | Page detector matched Directors' Report text; some filings put balance sheet and P&L on one page with labels and numbers ~1,200 characters apart |
| Tata Steel OCF / capex | Wrong | Missing label wording, substring false match |
| Dividend per share (HUL) | Missed | It sits in a table note |
| Bharti Airtel and any "millions" filer | **10x wrong** | Code missed the plural word "millions" |
| L&T / Asian Paints current assets | **30x to 1000x wrong** | Subtotal split over lines misread |
| Profit before tax | Wrong subtotal | Label "before exceptional items and tax" was tried before plain "before tax" |
| Standalone BVPS | Showed consolidated | Hard-coded flag |
| DOH (days) | Did not follow the year picker | Fetched "latest" separately |
| Many ratios | Stale | A fast-path reader returned old database rows |

**The ID trap:** the database ratio number does not equal QA's Sr number (ROE is internal 18, D/E is 20). An early fix deleted the wrong row. Always check the code before deleting.

**Root cause behind most of this:** the same ratio was written in **three places** with three definitions.

### 4.7 Stage 7: qualitative analysis (July to September 2026)

- Built sections A to G (B.1 to B.6, C.1 to C.8, D.1 to D.6, E.1 to E.7, F.1 to F.6, G.1) using rules, not AI. H to U are catalogued, not built.
- In late July the team changed the sourcing logic (confidence tags: VERIFIED, SINGLE_SOURCE, CONFLICT_UNRESOLVED, NOT_FOUND etc.; both primary and secondary source must be tried; every value carries a retrieval date; a human must sign off on adverse findings). Work restarted at A.1 under the new rules, one sub-point at a time.
- **Failure:** keyword and regex extraction tuned on 1 to 3 companies did **not** generalise across about 2,409 companies with different wording and layouts. The user said clearly: stop fixing one stock at a time. Options raised: real table-structure parsing, or AI extraction (ruled out, no key).
- **Failure:** government registers (NCLT, eCourts) have CAPTCHAs, so they are "vendor API" tier, not automatic.
- MCA needs a free account with OTP; a wilful-defaulter search is Experian first, not CIBIL (an early spec error, corrected 2026-07-30).

### 4.8 Stage 8: Ask Navrist chatbot (2026-07-22) and why it was switched off

**Built:** floating chat, text + SVG graphs + browser voice. Live prices through a tool call.

**Failed:** stock questions took about 2 minutes. Cause: Angel's 30 MB instrument file times out behind the user's firewall, and the code retried the timeout on every call. **Fix:** disk cache for 24 hours, remember the failure, 18 s hard timeout, warm up at start. Result: about 8 to 11 s using yfinance fast data.

**Not built:** "why did this stock fall" with real evidence. Plan was 5 layers (detect move, retrieve evidence, filter by date, answer only from evidence, route the question). **Blocked on choosing a news source** (paid API vs scraping). The user said do not pick one without asking.

**Image generation:** skipped on purpose (needs a paid key).

**2026-08-19:** the user decided **no AI anywhere**. Every AI call now fails instantly and every qualitative point falls back to rules. Do not re-enable without asking.

### 4.9 Stage 9: the ratio contract and final validation (October 2026)

**Done:** `ratio_contract.py` holds every formula once; others are adapters. Per-ratio calculation breakdown (inputs, formula, source) shown in the UI. Bank extractor rewritten by word position. Facts versioned so stale caches cannot hide fixes.

**Problems found by the audit**

| Problem | Fix |
|---|---|
| Three engines with different formulas | One contract |
| **Unknown turned into 0** | Status model: unavailable, not disclosed, not meaningful. Never 0 |
| Rounded display values reused as inputs | Keep unrounded `value_raw` |
| Derived ratios marked "verified" over unverified inputs | Worst status passes down |
| Row reader read "693" as "5,150", single-digit decimals, note numbers as amounts | Reader hardened |
| Owners' profit mixed with whole-entity profit (Reliance, L&T, TCS PAT showed 1.0) | Perimeter stored per fact |
| Lender detection by name | Now by sector |
| Automatic and manual paths gave different facts | Unified (8 of 20 company-years differed, now 0) |
| Fixes hidden by stale caches | Version numbers in every cache key |
| Alignment to Annual Report definitions (ratios 1 to 18) | Partly **reversed** by the owner later (Sr 1 and Sr 8) |

**Remember:** a gap against the Annual Report table is usually a **basis** difference (AR table is standalone, Navrist is consolidated first), not a bug.

**Final verdict (2026-10-08): NOT READY.**
- 133 real filings scanned: **20 unreadable automatically**, **39 (29%) fail an accounting identity** (all now flagged "needs review", none root-fixed).
- Tests recorded: 542 backend, 73 frontend passing. They prove code does what we expect, not that every company is right.

### 4.10 Stage 10: forecast system (2026-10-05)

**Built:** LightGBM + a hand-written numpy neural net, conformal ranges, a confidence engine that can say NO RELIABLE FORECAST, a promotion gate.

**Results (pilot: 8 stocks + Nifty, ~207k out-of-sample rows)**

| Question | Answer |
|---|---|
| Does it forecast the **range** well? | **Yes**, at +1 to +5 bars |
| Does it forecast **direction**? | Barely (about 52% at +1, +2), nothing at +3 to +5. **No "high confidence" was ever issued** |
| Daily forecasts over 26 years | Ranges valid but coverage swings by year (0.66 to 0.88) and fails in market stress. **Direction: no edge at any daily horizon** |
| Regime-aware model | No better than the plain one |

**Failures and facts**

| Issue | Detail |
|---|---|
| PyTorch, `shap`, some sklearn parts **blocked** by Windows Application Control | Wrote the network in pure numpy. Do not try to bypass the policy; ask for whitelisting |
| Angel history | 5-minute data back to 2017, but max about 100 days per call and **the oldest part is silently dropped** with no error. Daily data silently truncates beyond about 1,375 rows. Chunk it and verify the first and last bar |
| Angel rate limit | Erratic, about 7 good requests a minute at best |
| Since 2026-08-03 the 15:15, 15:20, 15:25 bars are missing or flat | Cause unknown, so only the first 72 slots are used |
| Live screen showed "all dashes / Updating..." | Not a model problem. Data was 35 to 70 seconds late because of lazy refresh. Fixed with a scheduler. Live output is usually range only because P(up) is about 50%. **Do not weaken the confidence gate** |
| Long-horizon results | Only about 2 to 2.5 effective independent stocks; today's large caps cause survivorship bias |
| Scale-up | 2,592 NSE symbols would take about 9 hours at about 4.6 per minute. Not run |

**Rule:** never claim accuracy without walk-forward output.

### 4.11 Stage 11: pattern agent (2026-10-21)

**Built:** 32 rule-based detectors (reversal, base, continuation, liquidity), lifecycle Forming, Awaiting breakout, Confirmed or Invalidated (only a **close** counts, not a wick), overlap rules, SQLite history, no-look-ahead test.

**Known weak:**
- Thresholds are **not tuned** against history.
- Too loose: Double Bottom fires on 133 of 751 stocks and 4,008 historical times; Cup and Handle 395; pocket-pivot about 83 times in 5 years on one stock; order blocks and three-weeks-tight noisy.
- UI only calls daily; the backend supports weekly, 60m, 15m, 5m.
- First request per stock takes 8 to 10 s.
- Ports 8000 and 8001 can keep ghost listeners after a Windows process kill; the backend ran on port 8002.
- Order-block research tooling sits in `orderblock-research/` (outputs not summarised here).

### 4.12 Stage 12: chartsmaze-style scanner (2026-10-30)

**Built (phase 1):** Create Screener with 3 filter tabs, Save/Load/Share, List and Charts views, 1 or 2 charts per row, CSV, horizontal resistance, backtest tab, RRG sector rotation, 751-stock universe.

**Limits**
- ChartsMaze's Fundamentals and Miscellaneous tabs are behind a login, so those filters are **our own choice**.
- Universe is 751, not 2000+.
- Fundamentals available for only 143 stocks.
- Phase 2 not built: Tight Setup, Shakeout, Inside Bar, Momentum, Volume, Earnings, Gap, IPO, Market Analytics, Watchlist, Trade Journal, ASM/circuit/bulk/block/insider lists.

### 4.13 Stage 13: the full site review (2026-10-31)

**Passed:** 17 range filters match an independent count; EMA/DMA, price, market cap (within 0.1 to 0.5% of Screener), 52-week position and dividend yield agree.

**Failed:** see section 8, items 1 to 7.

---

## 5. Master list of failures

Grouped by cause so you can see the patterns.

### A. Speed
1. 8 to 9 minute reports (serial I/O).
2. 3 to 4 minutes per ratio load (re-parsing PDFs). Fixed with a database.
3. Chatbot 2 minutes (Angel file timeout retried). Fixed with caching.
4. Stock overview 14 to 38 s today; search about 3 s; duplicate requests on every page.

### B. Wrong numbers from PDF reading
5. Plural "millions" gave 10x error.
6. Subtotal misreads gave 30x to 1000x errors (L&T, Asian Paints, Titan depreciation).
7. Labels matched as substrings (Total equity, Trade payables, PBT).
8. Note numbers read as amounts (TCS PAT = 1.0; Finance Costs).
9. Number far from its label on combined pages (Gopal Snacks).
10. Currency symbol read as the letter "H" (Bharti Airtel DPS shown as 0).
11. Wrong page picked (Directors' Report text matched a heading).
12. Rupee symbol, page ranges, units and contents pages all caused misreads.

### C. Logic and definition errors
13. Three engines, three definitions.
14. Unknown became 0.
15. Rounded values reused in calculations.
16. Perimeter mix (owners vs whole entity).
17. Price at calculation time used for old years.
18. Lender gating by name.

### D. Caching and process
19. Stale cache hid fixes (made version keys mandatory).
20. Wrong database row deleted because internal ratio number differs from Sr number.
21. Fast-path database reader returned stale rows.
22. Almost all October work uncommitted (risk).
23. Test harness `final_validation.py` crashes.
24. Patching regex code through shell heredocs corrupted files; use script files.

### E. Data sources
25. NSE XBRL list ~1.5 years stale; blocks datacenter IPs.
26. NSE live company API returned 403 on the dev machine.
27. BSE PDFs hard to parse.
28. Angel: silent truncation, flaky rate limit, missing last bars, scrip-master timeout.
29. No intraday vendor chosen.
30. Screener fetch failures counted as "done" (751 done, 0 errors, but only 143 have data).
31. NaN candle from Yahoo breaks the chart API for about 45% of stocks.
32. Demerged stocks (TMPV) keep old history and wrong EPS.
33. ChartsMaze fundamentals tabs not visible (login wall).
34. News source for event reasoning not chosen.

### F. AI
35. Groq daily limit broke everything.
36. Fallback model returned objects instead of strings, crashing the page.
37. AI retries cost 15 to 90 s per call. Solved by disabling.
38. Keyword extraction does not generalise (qualitative).

### G. Environment
39. Windows policy blocks PyTorch, shap, parts of sklearn.
40. Ghost listeners on ports.
41. Pasted secrets in chat and a password inside a git docstring.
42. Logged-in UI cannot be checked by the assistant.

### H. Product and honesty
43. Forecast direction has no edge.
44. Patterns too loose, backtest too optimistic.
45. Same metric different on two screens (P/E for Reliance had three values).
46. Statuses no longer drawn on ratio cards, so "needs review" looks normal.

---

## 6. Things we rejected on purpose, and why

| Rejected | Why |
|---|---|
| Screener or Dhan values overriding audited filings | Aggregators re-derive and re-label; differences are usually definitions, not errors |
| BSE PDF + AI checksum (July) | User chose XBRL-only then. Later PDFs adopted with identity checks |
| Vector database | Not needed for the amount of text; AI is off anyway |
| Re-enabling Groq / OpenRouter | Explicit, repeated user decision |
| Image generation in chatbot | Needs a paid key |
| Copying AR numbers to close a gap | Check basis first |
| Making per-stock fixes | Rule: fix across the whole registry |
| Bypassing the Windows policy for PyTorch | Ask for whitelisting instead |
| Long-horizon forecast UI | Not until the user approves |
| Weakening the forecast confidence gate | It is correctly withholding weak calls |
| Silently choosing a news source | User wants to be asked |

---

## 7. Rules we learned

1. **Unknown is not zero.** Unavailable, not disclosed, not quantifiable and search-inconclusive stay as they are unless zero itself is proven.
2. **Fix the cause for every company**, not the one you tested. Test on at least several sectors and layouts.
3. **Nothing ticker-specific** in analysis logic. The selected stock is only a test case.
4. **One definition per ratio**, in `ratio_contract.py`. Never add a formula elsewhere.
5. **Bump versions** (`FORMULA_VERSION`, `_EXTRACTION_LOGIC_VERSION`, fact-store `EXTRACTION_VERSION`, `BREAKDOWN_VERSION`) whenever a rule changes, or caches will hide your fix.
6. **Check the basis first** (consolidated vs standalone, owners vs whole entity, FY vs TTM) before calling a gap a bug.
7. **Unrounded values** for calculations; rounded only for display.
8. **Derived values never look more certain than their inputs.**
9. **Primary source wins** over aggregator on conflict; aggregator fallback must be flagged.
10. **Show the source, the date and the basis** for every number.
11. **Never claim accuracy** for forecasts or patterns without out-of-sample proof.
12. **Failed fetch is not "done".** Record failures with reasons.
13. **Do not render raw AI or scraped fields**; normalise first.
14. **Never put secrets in chat, code or docs.** Names only.
15. **Ask before** choosing a paid vendor, a news source, or re-enabling AI.
16. After any extraction change, re-run `tests/final_validation.py`, `tests/universe_scan.py`, `tests/breakdown_probe.py` and `tests/ratio_regression_probe.py`.
17. Do not edit regex-heavy code through shell heredocs.
18. The user must visually verify login-protected screens.

---

## 8. Open problems today

### From the final validation (ratios)
| ID | Problem |
|---|---|
| M-1 | Cash Ratio not cross-checked with XBRL |
| M-2 | L&T current assets/liabilities misread (flagged, not fixed) |
| M-3 | Poonawalla asset-quality ratios not disclosed; Kotak conflicting |
| M-4 | Asian Paints subtotal misread |
| M-6 | Contribution Margin and DSO are proxies |
| M-12 | Only ANURAS is audited line by line |
| M-13 | Bharti Airtel DPS shown as 0 but "verified" (rupee glyph read as H). **Breaks the zero rule** |
| M-14 | Cash Ratio treats a missing "other bank balances" line as 0 and stays verified |
| M-15 | `tests/final_validation.py` crashes |
| M-16 | 20 of 133 filings unreadable; 29% fail an identity |
| M-17 | Most October work uncommitted |
| M-18 | Site password in git history (rotate it) |
| M-19 | Price ratios for old years use today's price |

### From the 2026-10-31 site review (in suggested fix order)
1. **Chart API returns 500 for about 45% of stocks** (NaN in newest candle). One-line fix to turn NaN into null.
2. **Fundamentals exist for only 143 of 751 stocks**; failures counted as done.
3. **Wrong scanner P/E** for demerged or restructured companies (TMPV 1.19 vs Screener 98.1; JSWDULUX 6.14 vs 31.4; ASHOKA 1.10 vs 4.00; ABB 45.4 vs 88.2).
4. **Same metric, different value** between scanner and stock page.
5. **Debt/Equity shown for banks and negative-equity companies** where it is meaningless.
6. **Horizontal-resistance backtest returns 404.**
7. **Stock-page P/E and EPS stay "..." forever** when no annual report is parsed.
8. Scanner prices a day old; no refresh job; no "as of" or market status.
9. Home says "2000+ stocks" but the scanner has 751.
10. Backtest is optimistic (overlapping trades, no costs, survivorship, about 5 years only).
11. Peer names show raw HTML (`M &amp; M`).
12. Financial results axis in lakhs instead of crore.
13. Missing trader basics: watchlist, alerts, ROE, ROCE, P/B and others.

---

## 9. Before-you-start checklist

Before touching any ratio, extraction or data feature:

- [ ] Do I know which **source** and **basis** this number should come from?
- [ ] Will it work for **banks, NBFCs, demergers, new listings, "millions" filers, combined-page layouts**?
- [ ] If the value is missing, does it show **unavailable**, not 0?
- [ ] Did I bump the **version constants**?
- [ ] Did I run it on **several companies across sectors**, not one?
- [ ] Is there a **regression test** with a real page?
- [ ] Does the scanner and the stock page show the **same value**?
- [ ] Does the number carry **source, basis and date**?
- [ ] Am I claiming accuracy I have not measured?
- [ ] Do I need to **ask the user** (paid vendor, news source, AI, secrets)?

---

*Companion documents:* `PROJECT_DOCUMENTATION.md` (deep technical detail), `docs/PROJECT_CHANGELOG.md` (dated change log), `docs/DATA_SOURCES.md` (UI data map), `docs/PATTERNS.md` (32 patterns), `docs/ratio_contract.md` (formulas), `docs/SITE_REVIEW_2026-10-31.md` (latest review).
