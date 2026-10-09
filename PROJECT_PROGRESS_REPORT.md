# Navrist Project Progress Report

**Reporting period:** 21 June 2026 (first commit) to 9 October 2026 (preparation date)
**Prepared from:** the repository (214 commits on `main`, plus the uncommitted working tree), the test suites, the audit records in `docs/`, and the owner's dated project notes.
**Supporting technical references (kept unchanged):** [`PROJECT_DOCUMENTATION.md`](PROJECT_DOCUMENTATION.md) (technical manual), [`docs/FINANCIAL_RATIO_AUDIT.md`](docs/FINANCIAL_RATIO_AUDIT.md) (68-ratio audit matrix), [`docs/PROJECT_CHANGELOG.md`](docs/PROJECT_CHANGELOG.md) (dated change log).

---

## 1. Executive Summary

**What Navrist is.** Navrist is an internal equity-research terminal for Indian listed companies. A researcher searches a company and sees live prices and charts, 68 standard financial ratios, the evidence behind every ratio, a large qualitative-analysis framework, and an experimental price-range forecast.

**How it evolved.** The project began on 21 June 2026 as a research agent that gathered data from several websites and asked AI language models to write the analysis. It took about 8–9 minutes per company, and some of its content was not reproducible. Over the following months it became a different kind of system: numbers are now taken from the company's own audited Annual Report (or uploaded filings), turned into structured "financial facts", and calculated by fixed formulas. The AI models were switched off completely on 19 August 2026.

**Most important capabilities delivered.**
- A web application with login, company search, a redesigned interface, live charts and a manual document-upload workflow.
- A database-backed pre-computation system so results can be read quickly instead of re-reading 300-page PDFs.
- A 68-ratio fundamental-analysis engine in which every ratio has one written definition, a status that says how far it can be trusted, and a "calculation breakdown" showing each input, its page and its source.
- A banking module, market-dependent metrics, and a qualitative framework (topics A–G built).

**Most significant quality improvements.** A single shared calculation path replaced three diverging ones; unknown values are no longer turned into zero (with two exceptions found and recorded below); numbers are checked against accounting identities; cached results now refresh when the logic changes; and a 68-ratio audit of one company (ANURAS FY2026) re-computed every ratio independently. The audit changed several headline values — for example ANURAS Inventory Turnover moved from 1.47 to 0.82 times once the agreed definition was applied.

**Evidence of progress.** 68 ratios defined; 542 backend and 73 frontend automated tests passing (run 9 October 2026); cross-company runs over 17 companies in detail and 133 filings for accounting-identity checks (recorded 8 October).

**Current state and priorities.** The system is substantially built but **not yet certified as financially correct**. The last full validation (8 October) concluded "NOT READY". Since then many defects were fixed and tested, but three extraction problems remain open (L&T, Asian Paints, Bharti Airtel's dividend), only one company has been checked line-by-line against its source, the main validation script currently fails to run, and most of the October work is not yet saved in version control. Priorities are listed in section 11.

---

## 2. Progress at a Glance

| Measure | Figure | What it represents | Date / status |
|---|---|---|---|
| Financial ratios defined | **68** | Ratios in the ratio registry, each with one implementation | Current |
| Backend automated tests passing | **542** (63 sub-checks) | `pytest` over the whole test folder; 1 warning, 0 failures | Run 9 Oct 2026 during the documentation pass |
| Backend tests, earlier audit report | 489 | Figure reported by the latest audit | **Historical**; the 53 extra tests were added since, not individually traced |
| Frontend automated tests passing | **73** | Node test runner, 7 test files | Run 9 Oct 2026; same as the audit's historical figure |
| Companies in the detailed validation | **17** | Real cached filings run through the full 68-ratio engine | Recorded 8 Oct 2026 (**processed, not verified**) |
| Filings in the identity scan | **133** | Latest filing per company checked for accounting-identity breaks | Recorded 8 Oct 2026; 20 unreadable automatically, 39 (29%) broke an identity — all flagged, not all fixed |
| Company-years compared across the two pipelines | **20** | Manual vs automatic extraction; 8 differed before the fix, 0 after | Recorded 8 Oct; parity test passes in the 9 Oct run |
| Company-years re-run for this report | **15** (14 companies) | Real extraction on cached filings, to confirm current values | 9 Oct 2026 |
| Ratios with a completed formula audit | **68 of 68** — on **one** company | The ANURAS FY2026 matrix: independent recompute, input tracing, missing-input test. Result: 56 PASS / 12 NEEDS REVIEW (as scored in the matrix) | Audit of 8–9 Oct; **a stricter 44 / 24 split** applies once known open defects are counted |
| Ratios independently verified against source documents **for several companies** | **0** | No such multi-company source audit exists | Not done |
| Audit corrections listed | 18 items | Distinct changes listed in section J.1 of `PROJECT_DOCUMENTATION.md` | Counted from the audit list; not a count of "bugs" |
| Backend API routes | 90 | `@app.get/post` handlers | Current |
| Qualitative scoring modules | 54 | Deterministic scorers for topics A–G | Built; topics H–U catalogued but not built |

Not counted on purpose: a total number of "bugs fixed". The history records dozens of fixes, but no defensible single count exists.

---

## 3. The Development Journey

```
Jun 2026         Jul 2026                 Aug 2026            Sep 2026          Oct 2026
|-- Phase 1 ----|-- Phase 2 & 3 -------- |-- Phase 3/4 -------|-- Phase 4 ------|-- Phases 5-8 -----------|
 First agent     Rework decisions,        Visual analytics,    Manual upload,    Single calculation path,
 + dashboard     database, new UI,        qualitative A–G,     evidence          cross-company audit,
                 ratios 41–68, QA fixes   AI switched off      architecture      tests, documentation
```

### Phase 1 — Initial research agent (21 June – early July 2026)

**What existed.** The first commit (21 June, `f84bcab`) added data-ingestion helpers. On 29 June (`1914c2e`) the first complete application arrived: an automated research "agent" that fetched prices and statements from several sources, computed metrics, asked Groq-hosted AI models to write qualitative analysis, and showed the result in a single-file web dashboard behind a shared-password login.

**Limitations that forced a rework.** According to the owner's 8 July notes, a single report took 8–9 minutes because many slow downloads ran one after another; third-party websites supplied the financial numbers; and AI-written text could not be reproduced or traced to a source. The interface was one very large file.

**Result.** A working prototype and a clear list of what had to change. Status: superseded in parts; the original agent still exists in the code but no longer supplies the ratios.

### Phase 2 — The rework and the research terminal (July 2026)

**Decisions (8 July).** Speed first, then reliability, then deeper analysis. Two of the four decisions were later reversed in favour of a stricter approach: "use Screener as the main financial source" gave way to "use the audited filing", and "keep the AI models" gave way to "switch them off".

**What was built.**
- A modern web front end (July 16–20) with a light and dark theme, a landing page, an overview page and a sidebar.
- A database (Supabase) and a *pre-compute worker* that calculates ratios once per company and stores them, replacing the 3–4 minute wait for a live PDF read.
- A company registry covering the full National Stock Exchange (NSE) list, with exchange codes and the location of each Annual Report.
- Company search that finds a company by symbol, name, exchange code or ISIN ignoring spacing and punctuation, ranked by closeness.
- Login, session tokens, and about 90 API routes.

**What users could now do.** Search any listed company, open a dashboard, and see ratios loaded from stored results.

**Still open.** The Vercel hosting set-up was never recorded as tested. The shared password is a single credential (see section 11).

### Phase 3 — Fundamental analysis takes shape (July 2026)

On 21 July the ratio set was extended to all **68 ratios** (`f30e8a7`), including a first bank-specific block and market-based measures. From 24 to 31 July the owner's QA team reviewed ratios one by one and each defect was fixed individually. These fixes taught the team the central lesson of the project: the same ratio had been written in several places, and each copy had its own mistakes.

*Examples from this stage:* Return on Equity had divided by "Total Equity **and Liabilities**"; Return on Capital Employed and Interest Coverage had silently included other income; Interest Coverage had read a *note number* as the finance cost; Debt-to-Equity had missed minority interests on split-page balance sheets; Dividend Yield had missed dividends printed in tables; a Bharti Airtel report had its figures read ten times too small because the unit word was plural ("millions"); and a "standalone" Book Value per Share card had been silently fetching consolidated data.

### Phase 4 — Annual-report and filing workflows (July – September 2026)

- **July:** the team first tried NSE's machine-readable XBRL filings (structured, free) but found NSE's listing was about 18 months out of date, and then built an extractor that reads the **Annual Report PDF** directly — finding the balance sheet, profit and loss and cash-flow pages, detecting the units, and reading each line for this year and last year.
- **Early August:** income-statement flow charts and segment-revenue extraction were added.
- **3 September (`b6adff5`):** the **manual document-upload workflow**: a researcher uploads an Annual Report, optional XBRL and shareholding-pattern files and other filings, and the system analyses only those documents — never reaching for live websites except for the share price.
- Supporting filings (insider trading, governance, sustainability, credit ratings, transcripts) are stored and used by the qualitative analysis.

*Honest limit:* a shareholding pattern uploaded as a PDF is stored but not turned into structured data; promoter-pledge and free-float need the XML/XBRL version.

### Qualitative analysis and the end of AI generation (late July – September)

In parallel, a qualitative framework (business model, moats, management quality, governance, related-party dealings, promoter activity, red flags, competition, channels) was built, one sub-point at a time, as deterministic scoring over Annual-Report text and NSE filings (topics A–G; the catalogue lists A–U). On **19 August** all AI-model calls were disabled by explicit owner instruction; a full report that took 8–9 minutes dropped to about a minute. In September an evidence-based architecture was added so every qualitative score points to its source passage.

### Live chart and forecast pilot (late September – October)

A live chart view with technical-analysis tools and chart-pattern detection was added (28 Sept – 1 Oct). A probabilistic price-range forecast was built in early October as a pilot on 8 stocks plus the Nifty 50 index. Its own validation says the **range** forecasts work but **direction forecasts have no demonstrated edge**. These tools do not feed any financial ratio.

### Phase 5 — Standardising the calculation method (7–8 October 2026)

**Why it became necessary.** An audit found the document-analysis engine, the dashboard functions and the interface engine each had their *own* formula for the same ratio, so one company could show different values depending on how it was opened. Unknown figures sometimes became zero, display-rounded numbers were reused in later calculations, and a derived ratio could be labelled "verified" on top of an unreliable input.

**What was done.** All 68 definitions were moved into one place — the **ratio contract** — and the other entry points became thin adapters. In addition:
- Every figure is stored as a *financial fact* with its value, prior-year value, period, statement basis (consolidated or standalone), whether it belongs to the parent's shareholders or the whole group, page, extraction method and a status.
- Each ratio now returns a status: **verified**, **needs review** (a proxy or ambiguity is involved), **not meaningful**, **not disclosed / insufficient data**, or **not applicable**. A ratio inherits the weakest status of the ratios it depends on.
- Calculations use unrounded values; rounding is only for display.
- A **calculation breakdown** shows each input, the formula, the pages and a check that re-computes the value.
- Bank ratios received a rewritten reader that works from word positions and proves its numbers using the bank's own totals.

**Why it matters.** One definition means one answer. A fix to a source figure now improves every ratio that uses it (see section 6).

**Result.** On 7 October the team also aligned ratios 1–18 to the Annual Report's own definitions (`6d348dc`). The owner later reversed two of those choices (Inventory Turnover and Working Capital Turnover) in favour of the approved specification; the committed copy of the ratio list still shows the earlier text, while the working copy shows the current decisions.

### Phase 6 — Data-extraction and accuracy improvements (October 2026)

Running real filings through the engine exposed problems that are easy to miss in testing with invented data. Each is now covered by a test that reproduces it.

| Defect class | Example | Effect on calculations |
|---|---|---|
| Wrong page chosen | A table-of-contents page (dotted leaders, as in the Infosys report) treated as a statement | Wrong or missing statement figures |
| Misread subtotal | A bare, unlabelled total taken from the wrong figures; whole-crore depreciation of 693 read as 5,150 (Titan) | Wrong EBITDA, liabilities, ratios built on them |
| Unit scaling | A unit footnote far below the table ignored; the plural "millions" missed (Bharti Airtel) | Values off by 10x or more |
| Page numbers read as figures | A range like "431-432" read as a number (Maruti) | Revenue and cost lines corrupted |
| Misread note references | "23A, 23B" or "26, 15" read as amounts (ITC) | Revenue and dividends paid wrong |
| Wrong fiscal year | An interim dividend declared in FY2026 *for* FY2025 counted in FY2026 | Dividend Yield, Payout, Retention, Sustainable Growth |
| Caption variants | "Cost of materials **and components** consumed" not recognised | Cost of goods sold missing |
| Wrong profit perimeter | Profit that included minority holders or discontinued operations (Reliance, L&T, ITC) | ROE, EPS ratios, payout |
| Company resolution | New listings missing from search; wrong exchange-code matches | Wrong or no company opened |
| Stale cached results | Fixes hidden because results saved earlier were reused | Old wrong values kept appearing |
| Pipeline divergence | The automatic pipeline found no ANURAS figures; TCS profit read as 1.0 (now 48,553) | Different numbers in different modes |

New safeguards: balance-sheet and cash-flow **identity checks** (for example, current assets cannot be smaller than the inventory, receivables and cash inside them), which flag — but never silently change — a suspect figure and everything built from it.

### Phase 7 — The global 68-ratio audit (8–9 October 2026)

**Why.** The final validation of 8 October concluded the system was **not ready**: 20 of 133 filings could not be read automatically and 29% broke an accounting identity. The owner also wanted every ratio proved, not assumed.

**How it was done.**
1. **Formula review.** Each ratio's approved formula was compared with its implementation. Differences are listed rather than hidden (for example: net *credit* sales are never disclosed, so revenue is a flagged stand-in).
2. **Independent recompute.** A separately written implementation recalculated each ratio from the raw facts; all 68 matched.
3. **Input tracing.** Each base figure was searched for in the printed Annual Report (current and prior year).
4. **Missing-input test.** Each input was removed in turn to prove the ratio disappears (or falls back *flagged*) rather than turning into a number.
5. **Dependent recalculation.** Because ratios depend on each other, a corrected input flowed automatically to its dependants.
6. **Trusted-source comparison.** ANURAS results were compared with Screener figures on the *same basis* so that agreement proves the inputs and a gap points to a definition difference.
7. **Cross-company runs.** Fourteen companies (ANURAS, TCS, Maruti, ITC, Infosys, HUL, Asian Paints, Bata, Airtel, L&T, Reliance, Titan, Kotak, Poonawalla) were run to find generic extraction faults.

**Outcome for ANURAS FY2026** (the "after" column is the engine's value in the audit matrix; the "before" column is arithmetic on the same matrix inputs under the old rule, not figures copied from the audit report):

| Ratio | Before | After | Reason |
|---|---|---|---|
| Inventory Turnover | 1.47 x (Net Sales ÷ average inventory) | **0.82 x** (cost of goods sold 1,323 Cr ÷ average inventory 1,613 Cr) | Agreed definition |
| Inventory Days | 248.9 days | **445.0 days** | Follows turnover |
| Cash Conversion Cycle | 191.6 days | **387.7 days** | Follows inventory days |
| Cash Ratio | 0.145 (cash only) or 0.151 (all "other bank balances") | **0.148** (cash 378.1 + free bank deposits 8.3 ÷ current liabilities 2,615.4); needs review | 7.3 Cr of restricted balances excluded; 7.6 Cr of unexplained "deposit account" included but flagged |
| Working Capital Turnover | 2.13 | **2.52** | Average working capital, as specified |
| Dividend Yield | 0.193% (if the FY2025 interim of ₹0.75 were counted) | **0.129%** (₹1.50 final dividend for FY2026, at the fixed audit price of ₹1,165) | Dividend assigned to its own year |
| EBIT Margin | labelled "OPM %" | **17.04%**, relabelled | Screener's operating margin (22%) is a different measure |
| Dividend Payout | — | **5.02%** of the parent's profit; the dividend declared for the year (10.04%) is shown as reference | Paid-in-year, parent-only basis |

**Corrections beyond ANURAS** include the extraction fixes in Phase 6, a single definition of enterprise value (minority interests no longer added), a documented equity basis for each ratio, rounding removed from intermediate steps, and the version numbers now included in every cache key.

**What remains to be independently verified.** Only ANURAS was traced line by line. The other companies were checked for internal consistency, not against an outside source. The Cash Ratio has not been cross-checked against the exchange's XBRL data.

### Phase 8 — Testing and quality (throughout, concentrated in October)

Testing grew from basic checks to layered protection:
- **Formula tests**, including an independent re-implementation of every formula.
- **Extraction tests** that reproduce real layout faults with small synthetic text.
- **Regression tests** pinning each fixed defect.
- **Cache and version tests** proving that a changed version number changes the saved-result key.
- **Missing-data tests** proving that removing any single input never produces a zero ratio.
- **Accounting-identity checks**, both in tests and in the running system.
- **Pipeline-parity test** proving manual and automatic modes agree.
- **Front-end tests** (73) for ratio grouping, card cleanliness, forecast display and chart-pattern logic.
- **Cross-company probes** that run real filings.

*What this proves and does not prove.* Tests show the code does what was intended and that old faults have not returned. They do **not** show every displayed financial figure is right. Proof of that day: with 542 tests passing, the engine still shows a current ratio of 566 for L&T FY2026 (flagged "needs review") and a "verified" 0 dividend for Bharti Airtel (section 9).

### Phase 9 — State on 9 October 2026

See sections 8–11.

---

## 4. Capabilities Delivered

| Area | What was built | Problem addressed | What users/system can now do | Remaining |
|---|---|---|---|---|
| **Research application** | Redesigned React interface with landing, overview, document analysis, live chart, history and settings views; light/dark themes | One huge unstructured page | Navigate a full terminal; open a ratio's breakdown | No rendered-screen tests; status badges removed from ratio cards on 8 Oct (details still in the breakdown) |
| **Backend and APIs** | A web service with about 90 routes: login, search, quotes, ratios, document upload, qualitative, charts, forecasts | One-off scripts and slow serial calls | Programmatic access; background pre-compute | No general API-contract test suite |
| **Company identification** | Full NSE company list, ranked search by symbol/name/code/ISIN, document-based company detection for uploads | Missing or mismatched companies | Find newly listed or oddly named companies | Probe and 17 unit tests exist; real-universe edge cases untested at scale |
| **Data ingestion and extraction** | Annual Report reader (page selection, units, line reading, text scans), XBRL reader, bank reader | Statements are PDFs with inconsistent layouts | Pull ~50 line items per company-year with page evidence | Difficult layouts still fail (20 of 133 filings unreadable at the 8 Oct scan) |
| **Reports and filings** | Manual upload of reports, XBRL, shareholding and other filings; document store | Researcher has the files, not the website | Analyse uploaded documents with no web fallback | PDF shareholding patterns not structured |
| **Fact normalisation** | One structured "fact" record per number, with basis, owner-versus-group perimeter and status | Same number read differently in different places | Every ratio reads the same fact | Some facts still depend on proxies (flagged) |
| **Fundamental ratios** | 68 ratios, one definition each, dependency-aware | Three diverging implementations | Consistent values and propagated statuses | Source audit of more companies |
| **Evidence and transparency** | Calculation breakdown: inputs, pages, formula, check that it reconciles | Opaque numbers | Trace any ratio to its page | Bank ratios use a coarser breakdown |
| **Market-dependent metrics** | P/E, P/B, yields, EV multiples, Beta, from the live price (Angel One, falling back to Yahoo) | Price-based ratios need market data kept separate from filings | Live valuation ratios | Price is "today's", not the price at the report date |
| **Banking analysis** | Rewritten bank reader and eight bank ratios gated by sector | Misread bank rows and unit errors | Verified NIM, CASA, NPA, capital adequacy and cost ratios for four large banks (recorded) | NBFC asset-quality figures (e.g. Poonawalla) not found |
| **Data quality and missing data** | Status model, identity checks, "unknown is never zero" rule | Silent wrong or zero values | Unreliable numbers are labelled | Two known zero-handling gaps |
| **Caching and versions** | Saved results keyed to document, extraction logic, formula and fact-store versions | Old results hiding fixes | Fixes take effect when versions are bumped | Relies on developers bumping versions |
| **Testing and validation** | 542 + 73 tests; five manual probe tools | Regressions | Repeatable checks | Main validation script currently broken |
| **Qualitative analysis** | Deterministic scoring for topics A–G | AI-generated, untraceable text | Source-cited qualitative scores | H–U not built |
| **Live chart and forecast** | Charts, pattern detection, range forecast pilot | — | Technical views; calibrated ranges | Pilot only; no direction edge shown |

---

## 5. The 68-Ratio Framework

| Category | Examples | Built from |
|---|---|---|
| Efficiency and activity (12) | Inventory, receivables and payables turnover and days; Cash Conversion Cycle; Working Capital measures | Sales, cost of goods sold, purchases, average balances |
| Liquidity (4) | Current, Quick, Cash ratios; Working Capital | Current assets and liabilities |
| Profitability (9) | Gross, EBIT and Net margins; ROA, ROE, ROCE, ROIC; tax rate; Contribution Margin | Profit lines and averages of assets/equity/capital |
| Leverage and coverage (6) | Debt-to-Equity, Debt Ratio, Interest Coverage, Financial Leverage, Net Debt/EBITDA, debt-service cover | Debt, equity, earnings before interest |
| Valuation (11) | P/E, P/B, P/S, EV multiples, Earnings Yield, PEG, Graham Number, book value per share | Price plus per-share and total figures |
| Cash flow (7) | Free Cash Flow, FCF yield and margin, cash-flow coverage, Capex intensity, OCF ratios | Cash-flow statement |
| Growth and dividend (5) | EPS growth, Dividend Yield, Payout, Retention, Sustainable Growth | Per-share and dividend disclosures |
| Composite scores (3) | Altman Z, Piotroski F, Beneish M | Many ratios combined; contain flagged proxies |
| Banking (8) | NIM, CASA, gross/net NPA, coverage, capital adequacy, credit-deposit, cost-income | Bank schedules and disclosures |
| Market and shareholding (3) | Beta, promoter pledge, free float | Price history; shareholding filing |

### How one correction improves several ratios

- **Cost of goods sold → Inventory Turnover → Inventory Days → Cash Conversion Cycle.** Changing the turnover's numerator to cost of goods sold (and fixing the cost-of-materials caption so the cost is found) automatically moved ANURAS inventory days from about 249 to 445 and the cycle from about 192 to 388 days, because each is derived from the one before. Cost of goods sold also drives Gross Margin.
- **Equity → Debt-to-Equity, Financial Leverage, ROE, Book Value.** Three kinds of equity are kept apart: total group equity (used with consolidated debt and assets), parent-shareholders' equity (used with parent profit, per-share values and market value), and a single shareholders' equity figure for companies without minority holders. Reading the wrong row (as the early ROE bug did) corrupts all four; the ratio-by-ratio equity basis is now declared and tested.
- **Dividend attribution → Yield, Payout, Retention, Sustainable Growth.** A dividend belongs to the year the report says it is *for*. Fixing that changes ANURAS yield, and payout (dividends actually paid to the parent's shareholders ÷ the parent's profit) feeds Retention (100% − payout) and Sustainable Growth (ROE × retention).
- **Operating cash flow and capex → Free Cash Flow and its relatives.** Operating cash flow minus gross capital spending gives Free Cash Flow, which feeds FCF yield, FCF margin and EV/FCF; a misread cash-flow section (early Tata Steel and plural-heading fixes) therefore affected the whole family. ANURAS shows operating cash flow 334 Cr, capex 555 Cr, Free Cash Flow −221 Cr.

---

## 6. Major Problems Identified and Resolved

Status key: **Fixed** = fixed and covered by a regression test; **Partial** = improved but a known gap remains; **Open** = still under investigation.

| Problem | Why it mattered | Work completed | Result or improvement | Verification status |
|---|---|---|---|---|
| Data read from a contents page | Statement figures wrong or absent | Contents pages never treated as statements | Infosys-type reports read correctly | **Fixed** (test); not compared with an outside source |
| Figures scaled incorrectly (plural "millions"; footnote units; thousands) | Values 10x–1,000x off | Unit logic generalised | Bharti Airtel-type scaling errors removed | **Fixed** (tests); similar glyph issues may remain |
| Subtotals read incorrectly | Wrong liquidity and leverage | Row reader and subtotal logic fixed (Titan, HUL-type cases); identity checks flag the rest | Many misreads corrected, remainder flagged | **Partial** — L&T and Asian Paints still misread (flagged "needs review") |
| Dividends in the wrong fiscal year | Wrong yield, payout, retention | Year assigned from the report's "for the financial year" wording | ANURAS yield 0.193% → 0.129% | **Fixed** (test); one company shows a wrong zero (below) |
| Dividend shown as a "verified" zero (Bharti Airtel) | Violates the "unknown is never zero" rule | Found 9 Oct while preparing documentation | None yet | **Open** — a follow-up task was proposed |
| Inventory Turnover used Net Sales | Wrong turnover, days and cycle | Switched to cost of goods sold | ANURAS 1.47 → 0.82 | **Fixed** (test); matches the approved definition |
| Cash Ratio ignored bank balances | Understated liquidity | Notes classified into restricted and free balances | ANURAS 0.145 → 0.148, flagged | **Partial** — exchange XBRL cross-check not done; a missing "other bank balances" line currently counts as zero while "verified" (under investigation) |
| Cached results not refreshing | Old wrong values persisted | Formula, extraction and fact-store versions added to every key | Fixes now take effect | **Fixed** (test); depends on bumping versions |
| Several calculation paths disagreed | Different numbers per entry point | One ratio contract; manual/automatic extraction unified | 8 of 20 company-years diverged → 0 | **Fixed** (parity test) |
| Missing facts treated as zero | Fake precision | Status model and tests that remove each input | Unknown stays unknown | **Partial** — two exceptions known |
| Misleading labels ("OPM %" for EBIT margin) | Users compare with the wrong figure | Relabelled "EBIT Margin %" | Clear definition | **Fixed** (test) |
| Derived metrics lacked evidence | Numbers could not be audited | Calculation breakdowns with pages and reconciliation | Every numeric ratio traceable (13-filing probe recorded) | **Fixed** for ratios 1–57; bank ratios coarser |
| Wrong profit perimeter (parent vs group; ITC discontinued operations) | ROE/EPS ratios misstated | Perimeter stored per fact; repairs flagged | Consistent bases | **Fixed** (tests); ITC EPS policy still under review |
| Page-number ranges and note references read as figures | Revenue and dividends corrupted | Ranges and "23A, 23B" blanked | Maruti/ITC-type rows read correctly | **Fixed** (tests) |
| Search missing new listings / wrong code match | Wrong company | Full universe, ranked matching | Better resolution | **Fixed** for tested cases (17 tests) |
| Manual and automatic pipelines disagreed (TCS profit 1.0) | Same company, different numbers | One extraction path | TCS 48,553 confirmed 9 Oct | **Fixed** |
| Weak bank reading | Wrong bank ratios | Rewritten reader with identity proof | Kotak's recorded run verified | **Partial** — audit and recorded run conflict for Kotak; Poonawalla's asset-quality ratios not found |
| Enterprise value included minority interests | Inconsistent EV multiples | One approved EV definition | Same EV in three ratios | **Fixed** (test) |

---

## 7. Evolution of Quality and Reliability

| From | To | Why it matters | Status in code |
|---|---|---|---|
| Free text and AI-written numbers | Structured financial facts | Numbers can be traced and compared | Implemented; some facts proxy-based |
| AI arithmetic | Deterministic formulas | Same inputs always give the same answer | Implemented; AI disabled |
| Mixed periods and bases | Declared period, consolidated/standalone basis, parent/group perimeter | Avoids comparing unlike figures | Implemented; mixes are deliberate and documented |
| Bare numbers | Evidence-backed results | Reviewer can check the page | Implemented |
| Zero for unknown | Explicit missing/ambiguous statuses | Prevents false precision | Implemented with two known gaps |
| Independent ratios | Dependency-aware recalculation | A fix flows to every dependant | Implemented |
| Stale caches | Version-keyed caches | Fixes reach users | Implemented |
| Manual spot-checks | Regression and cross-company tests | Old faults do not return | Implemented; one script broken |
| Comparing with any website | Same-basis comparison with trusted sources | Separates definition differences from bugs | **Done for one company only** |

---

## 8. Current State (9 October 2026)

| Dimension | State |
|---|---|
| Implemented | Everything in section 4; 68 ratios; manual and automatic pipelines on one calculation path |
| Tested | 542 backend and 73 frontend tests pass; cross-company probes run on 14 companies today |
| Financially verified | **One company (ANURAS FY2026)** line by line; bank ratios corroborated against disclosures for four banks only in part |
| Incomplete | Section 9 |
| Saved in version control | Only through 8 October's UI commits. The contract, breakdown, bank reader, company search, forecast and most tests are **uncommitted** |

---

## 9. Current Limitations and Next Steps

### Immediate correctness and safety issues

| Issue | Why it matters | Next practical step |
|---|---|---|
| Bharti Airtel dividend read as a verified zero (rupee sign extracted as "H") | A wrong zero breaks the project's core rule | Make the dividend scanner generic for odd currency glyphs; add a test |
| L&T current assets/liabilities misread (FY2025 assets 157 Cr; FY2026 liabilities 45 Cr → current ratio 566) | Liquidity ratios nonsensical (flagged, not fixed) | Fix the subtotal reader for multi-segment balance sheets; add a real-layout test |
| Asian Paints current assets 786 Cr vs 11,478 Cr of components | Same | Same fix; also reject an empty or short text cache |
| Main validation script (`final_validation.py`) crashes | The 17-company check cannot be repeated | Correct its stub; re-run and refresh the records |
| Missing "other bank balances" line counted as zero in the Cash Ratio, still "verified" | Possible silent understatement | Distinguish "line absent" from "line not found" |
| Cash Ratio not cross-checked with exchange XBRL | Classification rests on notes alone | Compare for ANURAS and three or four others |
| Bank metrics: Kotak evidence conflicts; Poonawalla asset-quality not found | Incomplete bank coverage | Re-run bank ratios on both upload and automatic paths once the script works |
| Only one company audited line by line | Accuracy beyond ANURAS unproven | Repeat the method for a bank, an IT firm and a manufacturer |
| Work not committed; shared password visible in the code's history | Loss and security risk | Commit in logical pieces; rotate the password and tokens (owner decision) |

### Documented proxies and design choices awaiting owner decisions

- **Days Sales Outstanding / Receivables Turnover** use revenue in place of net credit sales (never disclosed) and are always "needs review"; the code never searches for a credit-sales figure.
- **Contribution Margin** is an estimate by necessity.
- **Historical-year price ratios** use today's live price, not the price at the year-end.
- **Equity and dividend perimeters** are now declared and tested, but the owner/minority dividend split is often not printed, leaving payout "needs review" on many companies.
- Some wording in the approved specification was edited by later owner decisions; the original workbook is not in the repository, so a fresh comparison is outstanding.

### Future enhancements

Trailing-twelve-month ratios, dated price history, scanned-PDF support, rendered-screen tests, per-user accounts, qualitative topics H–U, scaling the forecast beyond the pilot, and any return of AI interpretation (explicit owner approval required).

---

## 10. Overall Summary

In under four months Navrist moved from a slow prototype that asked AI models to write research into a structured research terminal with a 68-ratio engine whose every number can be traced to a page of a filing. The work covers an application, a database, document workflows, a banking module, a qualitative framework, a forecast pilot and an extensive test and validation toolkit. The strongest engineering gains are a single calculation path, honest handling of unknown data, version-aware caching, and a first complete line-by-line audit of one company.

The accuracy claim is deliberately modest: the system is well tested and well instrumented, but **financial correctness has been demonstrated for one company and consistency-checked for others**. Closing the open items above, saving the work to version control, and extending the source audit to more companies are what separate "built" from "certified".

---

## 11. Priorities

1. Commit and back up the work; rotate exposed credentials.
2. Remove wrong "verified zeros" (Bharti dividend; absent bank balances).
3. Fix subtotal misreads (L&T, Asian Paints) and repair the validation script.
4. Extend source audits to several more companies, including a bank.
5. Resolve the proxy and price-timing decisions with the owner.

---

## 12. Sources and Limits of this Report

**Evidence used:** git history (214 commits, 21 June – 8 October); the working tree (92 changed or new paths on 9 October); the three supporting documents; the ratio contract and audit-matrix files; the recorded validation outputs in `docs/final_validation_2026-10/`; the owner's dated project notes; and test runs and probe runs on 9 October.

**Limits:**
- Most of October's work is uncommitted, so its dates rest on the owner's notes and file records rather than commits.
- The latest audit report itself is not stored; per-company attributions (Maruti, ITC, Bata, Infosys, Titan, HUL) follow the audit summary and the descriptions in the regression tests.
- ANURAS "before" values are the author's arithmetic on matrix inputs.
- The 489 → 542 test increase was not itemised.
- Backend and frontend counts were measured on 9 October during the documentation pass and were not re-run again for this report.
- Phase dates marked "early/late" reflect ranges in commits or notes, not exact days.
