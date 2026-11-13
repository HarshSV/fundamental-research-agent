# Navrist - Complete Project Documentation

*Written 2026-10-09 from the repository at `C:\Users\vanar\Downloads\Agent-Clone\fundamental-research-agent` (branch `main`, last commit `86cb38f` of 2026-10-08, plus a large amount of uncommitted work - see [B.0](#b0-how-this-history-was-reconstructed-and-its-limits)).*

> **Update 2026-11-12 (latest):** every BSE-listed company was added (2,642 BSE-only, about 4,830 in the company master) and wired into the scan, fundamentals and peers: [B.20](#b20-stage-19---every-bse-listed-company-2026-11-12) and M-36 to M-38.
>
> **Update 2026-11-12 (later):** brand colours and font, landing-page chips, the forecast strip, the Chart lines filter with moving averages, clearer pattern markers with evidence on forming patterns, and the pattern study are in [B.19](#b19-stage-18---brand-colours-chart-controls-and-clearer-patterns-2026-11-12) and [`docs/PATTERN_STUDY.md`](docs/PATTERN_STUDY.md).
>
> **Update 2026-11-12:** the forecast window toggle, Financial Result tabs, hosting findings and the **sector specialist agent** are in [B.18](#b18-stage-17---forecast-window-financial-result-tabs-hosting-and-the-sector-specialist-agent-2026-11-06---11-12), [`docs/SECTOR_AGENT.md`](docs/SECTOR_AGENT.md) and M-29 to M-34.
>
> **Update 2026-11-06:** a public deployment at `https://ai.navrist.com`, a phone-layout pass, login hardening and a secrets review were added after this document was first written. They are recorded in [B.17](#b17-stage-16---public-deployment-phone-layout-and-secrets-review-2026-11-05---11-06), [D.3](#d3-authentication-as-implemented), [M.1](#m1-summary) (M-20 to M-25), [O.10](#o10-public-deployment-at-ainavristcom) and [`docs/PROJECT_CHANGELOG.md`](docs/PROJECT_CHANGELOG.md). The Create Screener "Patterns" tab, the separate Horizontal Resistance scanner and a ChartsMaze feature comparison ([`docs/CHARTSMAZE_GAP_ANALYSIS.md`](docs/CHARTSMAZE_GAP_ANALYSIS.md)) were added the same day (B.17, D.2, M-26 to M-28, R.1). Sections that describe the October ratio work were not re-verified in this update.

**Companion documents:** [`docs/FEATURE_LIST.md`](docs/FEATURE_LIST.md) (every feature in plain language, how it is shown, and its source) - [`docs/SECTOR_AGENT.md`](docs/SECTOR_AGENT.md) (sector specialist agent: history, what moved it, outlook) - [`docs/PATTERN_STUDY.md`](docs/PATTERN_STUDY.md) (do the patterns lead to anything?) - [`docs/FINANCIAL_RATIO_AUDIT.md`](docs/FINANCIAL_RATIO_AUDIT.md) (68-row audit matrix) - [`docs/PROJECT_CHANGELOG.md`](docs/PROJECT_CHANGELOG.md) (chronological changes) - [`docs/ratio_contract.md`](docs/ratio_contract.md) (generated formula contract) - [`docs/ratio_audit_matrix_2026-10.md`](docs/ratio_audit_matrix_2026-10.md) (raw ANURAS audit) - [`docs/final_validation_2026-10/matrix.md`](docs/final_validation_2026-10/matrix.md) (earlier cross-company validation) - [`docs/forecast_system.md`](docs/forecast_system.md) - [`DEPLOY.md`](DEPLOY.md) (deployment guide, partly out of date - see [O.9](#o9-known-stale-documentation)) - [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) (permanent project rules).

> **Read this first - what this document is and is not.** It records what the code and records in this repository *show*. Where something was
> discussed or planned but I could not find evidence of it in the code, it is called "planned" or "not verified", never "done". Test results are
> labelled **historical** (reported by earlier work) or **observed 2026-10-09** (run while writing this document). Passing tests do **not** prove that
> every financial number is correct - see [L.5](#l5-what-passing-tests-do-and-do-not-prove).

## Contents

| | | | |
|---|---|---|---|
| [A. What is Navrist?](#a-what-is-navrist) | [B. Project history](#b-the-complete-project-history) | [C. How the system works](#c-how-the-complete-system-works) | [D. Architecture and files](#d-project-architecture-and-important-files) |
| [E. Data sources and source-of-truth policy](#e-data-sources-and-source-of-truth-policy) | [F. Manual upload workflow](#f-manual-document-upload-workflow) | [G. All 68 ratios](#g-all-68-financial-ratios) | [H. Calculation policies](#h-important-financial-calculation-policies) |
| [I. Rework and major bug fixes](#i-initial-rework-and-major-bug-fixes) | [J. Recent global audit](#j-recent-global-audit) | [K. Cross-company validation](#k-cross-company-validation) | [L. Testing and QA](#l-testing-and-quality-assurance) |
| [M. Known problems](#m-known-problems-and-incomplete-work) | [N. Cache, versions, freshness](#n-cache-versions-and-data-freshness) | [O. Run and maintain](#o-how-to-run-and-maintain-navrist) | [P. Debug a wrong ratio](#p-how-to-investigate-a-wrong-ratio) |
| [Q. Glossary](#q-glossary) | [R. Roadmap and status](#r-roadmap-and-completion-status) | | |

---

## A. What is Navrist?

### A.1 In one paragraph

Navrist is an internal **equity research terminal** for Navrist (a professional trading and investment firm). A researcher picks an Indian listed company
(NSE/BSE) and gets, on one screen: live price and charts, a set of **68 standard financial ratios** calculated from the company's audited Annual
Report, an evidence trail showing exactly which numbers produced each ratio, a large **qualitative analysis** framework (moat, management, governance,
related-party dealings, and so on), live-chart pattern tools, and an experimental probabilistic **price-range forecast**. The fundamental research was
"phase 1" of a larger suite of AI agents the owner plans to build (project record: *navrist-research-terminal*).

### A.2 The problem it solves

Analysts normally collect numbers by hand from PDFs and then trust third-party websites whose definitions differ from the filing (for example one
site's "Operating Profit Margin" is not the same quantity as another's). Errors are easy to make and hard to trace. Navrist tries to make every number
**traceable to a page of an audited document** and every ratio **reproducible from a written formula**.

### A.3 Who it is for

Researchers and portfolio staff at Navrist. It is a login-protected internal tool (one shared site password -> signed session token; see [D](#d-project-architecture-and-important-files)),
not a public product.

### A.4 What a user can get

| Area | What the user sees | Where it lives |
|---|---|---|
| Company search and overview | Name, sector, live price, metric cards, income-statement Sankey/icicle charts | `frontend/src/views/Landing.jsx`, `Overview.jsx` |
| Fundamental ratios | 68 ratios with value, status, formula and a **Calculation Breakdown** (inputs, pages, warnings) | `frontend/src/views/DocumentAnalysis.jsx`, `components/CalculationBreakdown.jsx` |
| Manual document research | Upload an Annual Report (+ XBRL, shareholding pattern, other filings) and analyse it | `components/ManualUpload.jsx`, `tools/manual_document_pipeline.py` |
| Qualitative analysis | Topic A-U sub-points scored from filings with evidence | `tools/qualitative_engine.py` and ~60 `*_scoring.py` modules |
| Live chart | Candles, technical analysis, chart-pattern detection, event replay | `frontend/src/views/LiveChart.jsx` |
| Forecast | Calibrated range forecast for the next 1-5 five-minute bars (pilot) | `forecast/`, `components/ForecastPanel.jsx` |
| Ask Navrist chatbot | Floating chat assistant - **currently disabled** (all LLM calls off) | `tools/ask_navrist.py` |

### A.5 What makes the approach different from "ask an AI to calculate ratios"

An AI model asked to "give me the ROE of company X" can invent a plausible number, mix perimeters, round early, or quietly treat a missing figure as zero.
Navrist is built on one principle:

> **Collect data from reliable sources -> calculate deterministically -> preserve the evidence -> let AI interpret, never invent the numbers.**

Concretely, in the code:

1. **One formula per ratio**, written once in `tools/ratio_contract.py`; every pipeline is an adapter over it (no second formula anywhere).
2. **Facts are extracted once** into a normalised `FactSet` (`tools/fundamental_fact_store.py`) with page number, method, basis, perimeter and a status.
3. **Unknown is never zero.** A missing input produces `insufficient_data` / `not_disclosed`; a zero is accepted only when the filing explicitly supports it
   (this is also a permanent rule in `CLAUDE.md`). *Exception found while writing this document: see open issue M-13.*
4. **Unrounded arithmetic.** Intermediate values keep full precision (`value_raw`); rounding is for display only.
5. **Every result carries a status and a breakdown** (`verified`, `needs_review`, ...), so a proxy can never masquerade as an exact figure.
6. **The language model is switched off.** Since 2026-08-19 every Groq/OpenRouter call is disabled on the owner's explicit instruction
   (`tools/groq_client.py::groq_chat` raises immediately; commit `15447ed`). All numbers and scores today are deterministic code.

---

## B. The complete project history

### B.0 How this history was reconstructed and its limits

Sources used: (1) `git log` (214 commits on `main`, 2026-06-21 -> 2026-10-08); (2) the working tree (`git status` lists 88 modified or untracked paths);
(3) the owner's project memory notes (dated decision records, e.g. *rework-decisions-2026-07*, *ratio-contract-remediation-2026-10*); (4) the generated
documents in `docs/`; (5) file timestamps; (6) the code and tests themselves.

**Important limits:**

* **Most of the October 2026 remediation is not in git.** `tools/ratio_contract.py`, `tools/ratio_breakdown.py`, `tools/bank_extractor.py`, `tools/bank_ratios.py`,
  `tools/company_search.py`, `forecast/`, and almost every `tests/test_*` file written since September are **untracked**; `tools/annual_report_financials.py`,
  `tools/fundamental_fact_store.py`, `tools/ratio_calculation_engine.py`, `tools/fundamental_ratio_registry.py` and others carry large uncommitted edits
  (`git diff --stat`: 30 files, +3,864 / -8,482 lines). The only commits that touch the Oct ratio work are `6d348dc`, `c2ed624`, `86cb38f`.
  Dates for the rest therefore come from memory notes and document headers, not commits. **Nothing here is backed up by version control - committing is the top maintenance action** (owner's decision; I did not commit).
* Branches: `main`; `antigravity-backup` (a snapshot of an earlier IDE's uncommitted work, taken 2026-07-03, never merged); four `claude/*` worktree branches (not examined).
* The Maruti/ITC/Bata/Infosys/Titan/HUL fixes of the "latest audit" are evidenced by tests and code, but the audit report itself is not stored in the repo. Per-company attributions below follow the audit summary given by the owner and the test docstrings.
* I could not verify any exact calendar date for a stage unless a commit, a dated document or a memory record states it. Such dates are marked "(record)".

### B.1 Timeline at a glance

| # | Stage | When | Status |
|---|---|---|---|
| 1 | Ingestion-layer start: NSE scraper, PEAD engine, orchestrator | 2026-06-21 (`f84bcab`) | Completed (historical) |
| 2 | First research agent: LangGraph pipeline, Angel One data, Groq analysis, FastAPI, single-file dashboard, login | 2026-06-24 -> 07-03 (`1914c2e`, `260b1ff`) | Replaced in parts; still in repo |
| 3 | **Initial rework**: performance-first redesign decisions | 2026-07-08 (record) | Partly completed (see B.4) |
| 4 | Real statements from NSE XBRL; Annual-Report PDF extraction becomes the fundamentals source | 2026-07 (record, `6ebb97a`, `a2b0615`) | Completed, evolved |
| 5 | Vite/React frontend, Supabase precompute, company registry | 2026-07-16 -> 07-20 (`a2b0615`) | Completed |
| 6 | Ratios 41-68, bank extractor v1, Beta/pledge/free float | 2026-07-21 (`f30e8a7`) | Completed, later rewritten |
| 7 | QA-driven per-ratio fixes (Sr 1-47...) | 2026-07-24 -> 07-31 (many commits) | Completed for the items fixed |
| 8 | Qualitative analysis A-G, deterministic scoring, LLM disabled | 2026-07-24 -> 08-20 | Built; separate from ratios |
| 9 | Manual-upload pipeline, evidence architecture, calculation engine | 2026-09-03 (`b6adff5`) | Completed, evolved |
| 10 | Live chart, patterns, forecast system | 2026-09-28 -> 10-05 | Built; forecast is a pilot |
| 11 | Annual-Report definition alignment (ratios 1-18) | 2026-10-07 (`6d348dc`) | Partly reversed later (Sr 1, Sr 8) |
| 12 | **Ratio contract remediation** (one formula source), calculation breakdown, bank rewrite, final validation | 2026-10-07 -> 10-08 (record; uncommitted) | Implemented; verdict then "NOT READY" |
| 13 | **Global audit** (2026.10.7 -> .13): COGS inventory turnover, cash ratio, dividends, extraction hygiene, version keys | 2026-10-08 -> 10-09 (record; uncommitted) | Implemented; open items remain |
| 14 | Pipeline unification (manual and automatic share one fact path) | 2026-10-08 (record) | Implemented and parity-tested |
| 15 | UI simplification of ratio cards | 2026-10-08 (`86cb38f`) | Completed |

### B.2 Stage 1 - Ingestion layer (2026-06-21)

* **Before:** nothing.
* **Changed:** `f84bcab` "Initial Commit: Ingestion Layer Migration Complete" added `tools/nse_scraper.py`, `tools/pead_engine.py` (post-earnings drift), `tools/pipeline_orchestrator.py`, `tools/initialize_kite.py` (Zerodha Kite login helper).
* **Result / status:** historical starting point; these files remain but are not part of the current ratio path. Completed.

### B.3 Stage 2 - The original Fundamental Research Agent (2026-06-24 -> 07-03)

* **What existed:** a **LangGraph agent** (`agent/stock_agent.py`, now ~5,800 lines) that, for a symbol, (1) fetched price/financial data (Angel One via `tools/angel_scraper.py`, yfinance and Screener.in for statements and peers), (2) computed metrics (`tools/metrics_engine.py`, `tools/peer_synthesis.py`), (3) asked **Groq LLMs** for qualitative analysis (business model, moat, risks) and (4) produced a verdict; exposed by FastAPI `app.py` (`POST /api/research`) and shown in a **single-file React dashboard** (`frontend-dashboard/index.html`, React + Babel loaded from CDNs, no build step). Login was added 2026-06-24 and settled on one shared site password + JWT (`auth.py`).
* **Problem discovered:** a full run took **8-9 minutes** (project record *rework-decisions-2026-07*): serial blocking I/O (6+ serial yfinance calls, 3 uncached history downloads, up to 3 concall PDF downloads, a TOTP re-login per request, the whole graph executing on the web server's event loop), and LLM output was non-deterministic.
* **Changes:** UI redesigns (`1914c2e`, `260b1ff` Business Model Canvas, moat from Screener fundamentals `6fc2e6d`, peer percentiles `1194ea4`); branch `antigravity-backup` preserved an IDE's unsaved work (2026-07-03).
* **Status:** the agent graph and its `/api/research` endpoint still exist and still call modules that use Screener/yfinance, but **the 68-ratio system no longer uses them** (see B.5). Partially superseded.

### B.4 Stage 3 - The "initial rework" (decisions of 2026-07-08)

The owner and assistant agreed four locked decisions (record *rework-decisions-2026-07*):

| Decision | What was agreed | What the repository shows today |
|---|---|---|
| Sequencing | Speed first (8-9 min -> 30-75 s cold, <5 s warm), then reliability, data intelligence, deep AI | Speed addressed by precompute + caching (B.6) and by disabling LLMs (a report that took ~8-9 min dropped to ~65 s, record *llm-disabled-2026-08*) |
| Data layer | Screener.in as the primary financials source, yfinance only for price history | **Reversed in practice.** Fundamentals now come from the audited Annual Report PDF / XBRL; Screener is used for shareholding, peers, concalls and as a *comparison* in audits, not as a source of ratio inputs (see E) |
| Retrieval | Grounded multi-document retrieval, no vector database | Keyword/section retrieval over cached Annual-Report text (`tools/ar_document_cache.py`, `qualitative_source_router.py`); no vector DB found |
| LLM | Keep Groq (70b -> 8b fallback) | **Reversed 2026-08-19**: all LLM calls disabled by explicit instruction (`15447ed`) |

The rework was therefore *partly* carried out as agreed; the most important change of direction was moving from "third-party aggregator numbers + LLM text" to "audited filing numbers + deterministic code".

### B.5 Stage 4 - Real statements: NSE XBRL, then Annual-Report PDFs (July 2026)

* **Before:** itemised numbers (inventory, cost of materials...) were not available from Screener/yfinance/Angel One.
* **Step 1 (record *nse-xbrl-fundamentals*, 2026-07):** `tools/nse_xbrl.py` reads NSE's machine-tagged XBRL results (free; `INDAS_` taxonomy for non-financials, `BANKING_` for lenders). First ratio: Inventory Turnover. Problem found: NSE's annual listing was ~1.5 years stale, and only newer filings tag balance-sheet inventory. The owner rejected a BSE-PDF-plus-LLM approach at that time.
* **Step 2 (evidence: `6ebb97a` 2026-07-14, `a2b0615` 2026-07-20, `tools/annual_report_financials.py` now 8,635 lines, `tools/nse_annual_reports.py`, `tools/bse_scraper.py`):** the pipeline moved to **extracting statements directly from the company's Annual Report PDF** (BSE first, NSE as fallback) with page selection, unit detection and a row reader. `nse_xbrl.py` (5,034 lines) kept the per-ratio wrapper functions and the XBRL path.
* **Status:** completed and still the primary route; XBRL is used for uploaded filings (manual mode) and as a fallback. **Contradiction to note:** the 2026-07 record says "don't re-investigate BSE" but the code later relies on BSE/NSE Annual-Report PDFs; no record of the owner reversing that decision was found - treat the code as the current truth.

### B.6 Stage 5 - Frontend rebuild, database and company registry (July 2026)

* **Before:** one 8,416-line HTML file; every company search re-downloaded and re-parsed PDFs (3-4 minutes per company).
* **Changed:** (a) **Vite + React + Tailwind** frontend in `frontend/` (record *vite-migration*: scaffold 2026-07-16; ground-up UI rebuild 2026-07-17; `a2b0615` 2026-07-20); the backend serves `frontend/dist` and falls back to the legacy HTML. (b) **Supabase (Postgres)** database (`db/001_schema.sql` ... `009_*.sql`, `tools/supabase_client.py`): tables `companies`, `ratio_values`, `price_eod`, `price_intraday`, `qualitative_values`, `refresh_jobs`, `chat_messages`, `qualitative_research_*`, `uploaded_documents`, `extracted_values`, `fundamental_analysis_results`. (c) A **precompute worker** (`tools/precompute_worker.py`, `run_full_precompute.py`) that calculates every ratio once per company and stores it, so reads become a SQL SELECT (`tools/db_ratio_reader.py`). (d) A **company registry** seeded from the NSE universe (`tools/seed_company_registry.py`) with each company's BSE scrip code and Annual-Report URL (`a2b0615` also fixed BSE scrip-code name matching and Supabase pagination).
* **Result:** warm reads become fast. **Not verified:** the actual speed numbers for the Supabase path (the plan recorded a 3-4 min wait before; I did not benchmark).
* **Status:** completed. Vercel deployment config (`vercel.json`) was "not yet tested" at the time of the record; I found no later test.

### B.7 Stage 6 - Ratios 41-68 and the first bank module (2026-07-21)

`f30e8a7` added Sr 41-57 (OCF/Net Profit ... Beneish M-Score), the bank/NBFC block Sr 58-65 with "a new RBI-format statement parser separate from the Ind AS extractor", and Sr 66-68 (Beta via yfinance vs Nifty 50, Promoter Pledge %, Free Float %). The 68-ratio list is transcribed in `tools/fundamental_ratio_registry.py` "from `Ratio_Sheet_V8_patched 2.xls`, sheet 'Ratios'" (that workbook is not in the repo). The sector gating for Sr 58-65 comes from the same workbook's "Sector Applicability Matrix" (`tools/sector_ratio_applicability.py`). Status: completed then; the bank reader was found unreliable and **rewritten in October** (B.12).

### B.8 Stage 7 - QA-driven per-ratio fixes (2026-07-24 -> 07-31)

The owner's QA reviewed ratios in a spreadsheet (record *qa-ratio-review-2026-07*); fixes were made **one ratio at a time**. Examples with commits: Sr 5 Payables Turnover MSME dues (`7dd9020`); Sr 21 ROE capturing "Total Equity AND Liabilities" (`5f6cf9a`); Sr 22 ROCE EBIT silently including Other Income (`003bfb8`); Sr 23 Debt-to-Equity NCI missed on split-page balance sheets (`33b0902`) and lease mis-extraction (`cfd7534`); Sr 25 Interest Coverage capturing a note number as finance costs (`c55197a`); Sr 30 Dividend Yield missed tabulated dividend notes (`198e13c`); Sr 42 ROIC (`2e3971c`, `5ac4965`, `a9665f3`); Sr 46 BVPS silently fetching consolidated data for "standalone" (`5d91337`); Sr 47 Dividend Payout wrong PAT basis (`c232ac1`); Sr 50 PEG near-zero-growth guard (`5eb880b`); Sr 54 Graham Number EPS/BVPS fiscal-year mismatch (`c003b3b`); Sr 67 Pledge % wrong denominator (`bb3e94d`). Details in [I](#i-initial-rework-and-major-bug-fixes). Status: each completed individually; **but the same ratio was later implemented in three places with diverging definitions**, which triggered stage 12.

### B.9 Stage 8 - Qualitative analysis A-U (2026-07-24 -> 2026-08-20, evolved to September)

Topic-by-topic builds (`a82b189` Topic A ... `4aa3d51`): business model and moats (A), management quality (B), governance and related-party items (C), promoter activity from NSE data (D), red flags (E), competition (F), channels (G). Each sub-point is scored by deterministic code over Annual-Report text/tables and NSE filings; the Groq-based classifiers were retired. `a075e25` removed fabricated fallback data. `b6adff5` (2026-09-03) added an **evidence-based architecture** (`qualitative_evidence*.py`, `qualitative_task_engine.py`, `qualitative_source_router.py`, `qualitative_legacy_adapters.py`) and migrations `db/004`-`009`. This stream is large (>60 scoring modules) but **separate from the 68 ratios**; it is only summarised here, and its own spec is `Navrist_Qualitative_Framework.md`. Status: the task registry catalogues topics A-U, but the commit history only shows builds for A-G (B-G sub-points); H-U are not evidenced as built (not verified further).

### B.10 Stage 9 - Manual document upload and the calculation engine (2026-09-03)

`b6adff5` introduced the **document-first workflow**: upload the Annual Report (+ XBRL + shareholding pattern + others), analyse it with no live fallback to BSE/NSE (`tools/manual_mode.py`), store extracted values (`tools/manual_document_pipeline.py`, `tools/document_analysis_engine.py` - 2,395 lines) and a canonical `ratio_calculation_engine.py` behind `POST /api/v1/ratio/{ratio_key}`. **Problem:** the uploaded-document engine had its own broader extractor and its own formulas, while the dashboard used the older narrow parser - so the same company could show different numbers (see Y in the contract, B.14).

### B.11 Stage 10 - Live chart and forecast (2026-09-28 -> 10-05)

`4dddb64` and `ee66501` added the Live Chart view (candles, technical analysis, chart patterns, pattern selector, cluster popover, event replay) and Axis Direct RAPID client scaffolding (`tools/axis_rapid_client.py`; the `.env.example` keeps Axis in "uat" until production access is confirmed). The **forecast system** (`forecast/`, record *forecast-system*, 2026-10-05) is a pilot: 8 equities + Nifty 50, 5-minute bars, LightGBM + a NumPy GRU ensemble, conformal intervals and a confidence gate. Its own validation (`docs/forecast_validation_2026-10.md`, `docs/daily_validation_2026-10.md`) says range forecasts are validated, **direction has no demonstrated edge**, and no HIGH confidence is ever issued. This stream does not feed any fundamental ratio. Status: pilot, uncommitted.

### B.12 Stage 11 - Annual-Report definition alignment (2026-10-07)

* **Before:** ANURAS FY26 ratios differed from the Annual Report's own "Analytical Ratios" table.
* **Discovery (record *ar-definition-alignment-2026-10*):** most gaps were **basis** (the AR table is *standalone*, Navrist is *consolidated-first*), not bugs. The owner kept consolidated-first and owners' PAT for ROA/NPM/ROE, but chose to align *formulas* for ratios 1-18 to the AR's definitions.
* **Changed (`6d348dc`):** Inventory Turnover numerator = Net Sales; Working Capital Turnover and Days Working Capital = closing WC; Payables Turnover uses the "Purchases during the year" note line; DOH/DSO/DPO/CCC derive from *unrounded* turnovers; ratios regrouped into 8 UI categories.
* **Later reversal:** the owner then instructed that Inventory Turnover use **COGS** and that WC Turnover follow the **authoritative average-WC specification** (2026.10.7 and .8; B.14). So Sr 1 and Sr 8 of `6d348dc` are *historical* - the committed `HEAD` registry still says Net Sales / closing WC, while the working tree says COGS / average WC.

### B.13 Stage 12 - Ratio contract remediation, breakdown and final validation (2026-10-07 -> 10-08)

* **Problem:** an audit found the *same ratio implemented three times* with diverging definitions (document engine, `nse_xbrl` dashboard wrappers, canonical engine), unknown values turned into 0, rounded values reused as inputs, and derived ratios "verified" over unverified parents.
* **Changed (record *ratio-contract-remediation-2026-10*):** `tools/ratio_contract.py` now holds **all 68 definitions once** (`SPEC` + one function per ratio + `FORMULA_VERSION`) over the normalised `FactSet`; the other entry points became thin adapters. Added `tools/ratio_breakdown.py` (per-ratio auditable inputs/formula/pages; `BREAKDOWN_VERSION = 2`) and `frontend/src/components/CalculationBreakdown.jsx`. Versioned storage: rows carry `formula_version`; stale rows recalculate on read.
* **Final validation (record *final-validation-2026-10*)** ran the real orchestrator over 17 cached filings and scanned 133 filings for accounting-identity violations. Fixed that round: a **bank extractor rewrite** (word-coordinate rows, unit-normalised, identity-proven), silent row-shift bugs in the shared row reader, NCI read as the equity subtotal, owners' profit read as whole-entity (Reliance, L&T), lender gating by *sector*, `not_meaningful` no longer collapsing into `not_disclosed`, and pledge sanity checks. **Verdict then: NOT READY** - 20 of 133 filings unreadable automatically, 39 (29%) failed an accounting identity (all then flagged `needs_review`, none unflagged, but not root-fixed). These are **historical** figures from `docs/final_validation_2026-10/`.
* **Status:** implemented; validation tooling exists; open items in [M](#m-known-problems-and-incomplete-work).

### B.14 Stage 13 - The global ratio audit (formula versions 2026.10.7 -> 2026.10.13)

See [J](#j-recent-global-audit) for the full audit. In short: COGS-based Inventory Turnover and its dependants, the Cash Ratio numerator and restricted-balance policy, dividend fiscal-year attribution, many generic extraction fixes found by running 14 companies, ledger-identity checks, version keys in cache keys, the EBIT Margin relabel, average-WC turnover, a single EV definition, an explicit equity-basis policy, and a 68-row ANURAS audit matrix (56 PASS / 12 NEEDS REVIEW). Status: implemented and unit-tested; **not committed**.

### B.15 Stage 14 - One fact path for every pipeline (2026-10-08)

* **Problem (contract decision Y):** `annual_report_financials._extract_from_pdf` had several `is_manual_mode()` branches (3-column balance sheet, share-capital note scan, share-count fallback, EPS weighted-average trigger, unit conversion of Equity Share Capital) and the **broad alias extractor fallback** ran only for uploaded documents. The automatic pipeline returned *no* facts for ANURAS ("Consolidated P&L not found") and different `equity` for Maruti, Bata, Zee, Nazara, Bharti Airtel and Polycab.
* **Changed:** those branches are now unconditional; the broad fallback is bound to the same PDF bytes and fiscal year in every pipeline; `is_manual_mode()` is confined to *source selection* and cache-key separation (enforced by an AST test). TCS FY25 owners' PAT printed 1.0 in both pipelines (a colon in "Profit for the year attributable to: Shareholders of the Company" and a note number read as an amount) - fixed; now 48,553.
* **Evidence:** `tests/test_pipeline_parity.py` + `tests/pipeline_parity_probe.py`: 20 cached company-years, 8 diverged before, 0 after (recorded in `docs/final_validation_2026-10/pipeline_parity_*.json`). I re-confirmed TCS owners' PAT = 48,553 and ANURAS FY26 extraction on 2026-10-09 using `tests/ratio_regression_probe.py`.

### B.16 Stage 15 - Latest UI work (2026-10-07 -> 10-08)

`c2ed624` "prioritize screener-aligned ratio names" (first 13 ratios shown use Screener-style labels such as "Inventory Days", "Debtor Days", via `tools/ratio_display.py`; internal ids unchanged) and `86cb38f` "simplify ratio calculation cards" (cards show name and value; statuses/warnings remain in the API payload but are not drawn). Completed.

### B.17 Stage 16 - Public deployment, phone layout and secrets review (2026-11-05 -> 11-06)

*Source: this session's work and the commits `8434d3a`, `f8e1eec`, `a740486` (observed in git); the Cloudflare and Hostinger steps were done in their dashboards and are not in git.*

* **Public site.** `navrist.com` stays a WordPress site on Hostinger shared hosting (it cannot run Python or Node). The app is published as `ai.navrist.com` through a Cloudflare Tunnel from the owner's PC (details and lessons in [O.10](#o10-public-deployment-at-ainavristcom)).
* **Dev-mode hydration block (mistake found and fixed).** The first public load rendered only the page shell ("Loading market indices...") because the web app runs `next dev`, which refuses to hydrate pages for non-localhost origins. Fixed with `allowedDevOrigins: ["ai.navrist.com"]` in `navrist-web/next.config.ts`.
* **Phone layout pass (320 / 375 / 768 px).** Fixed: header title overlapping the theme toggle; home search placeholder wrapping over three lines; stock page and Backtest page wider than the screen (grid items without `min-w-0`); chart range tabs and Shareholding quarter tabs wider than the screen; Financial Result chart date labels colliding; tap targets of 20-30 px raised to 36-44 px on phones only; EMA/DMA checkbox lists made a two-column grid; a "Swipe sideways for more columns" line above wide tables; the typing headline no longer shifts the search box (the longest phrase is laid out invisibly to reserve its size). Verified with a script that lists elements wider than the viewport, plus screenshots. Not verified on a real phone.
* **Create Screener patterns.** The screener had no way to filter by chart pattern (the pattern list only appeared when one pattern was opened from the chips). A **Patterns** tab was added (patterns grouped by category, search, Select all, plus pattern status). The backend accepts `patterns: {values: [...]}` with scanner id `all` in `patterns/screen_engine.py` (`search` and `backtest`); a stock matches when it currently shows any ticked pattern (and any ticked status); results show the pattern name, status and breakout, and the Backtest tab covers the chosen patterns. Tested directly on the 751-stock store: no pattern -> 751; Double Bottom -> 113 (equal to the single Double Bottom scan); Double Bottom + Cup & Handle -> 118; with status "awaiting breakout" -> 70; Double Bottom backtest 4,042 trades in both routes.
* **Horizontal Resistance is its own scanner.** Removed as a tab/filter from the Create Screener and from every pattern scan (applying from those scanners switches it off); it keeps its tab, with the near/breakout choice, only in its own scanner. *Mistake found:* the scanner existed in code but had no button anywhere on the page, so nobody could open it. It is now a compact trend-line button in the header beside Create Screener (label shown from 1024 px; icon-only below), wired through `OPEN_RESISTANCE_EVENT` in `searchEvents.ts`. A large "Scanners" row on Home was tried first and removed at the owner's request.
* **ChartsMaze comparison.** Its pages are all behind a sign-up (none was created), so only the menu was compared; findings and a build plan are in [`docs/CHARTSMAZE_GAP_ANALYSIS.md`](docs/CHARTSMAZE_GAP_ANALYSIS.md).
* **Production build for the public site (M-22 fixed).** The site was served by `next dev`, which caused two visible problems: (1) *Hydration / "script tag" console errors:* Cloudflare re-labelled the app's `no-cache` on script files as `max-age=14400`, so a browser kept an old script for up to 4 hours while the page was new (for example the old header without the Horizontal Resistance button), and React reported the mismatch. Fixed in the Cloudflare dashboard with **Caching -> Configuration -> Browser Cache TTL = Respect Existing Headers** (verified: script files then carry `no-cache, must-revalidate`). (2) *The round "N" badge* is Next.js's development indicator; `devIndicators: false` hid it on localhost only. Both are removed for good by a production build: `NEXT_DIST_DIR=.next-prod npm run build` (separate folder, so building never disturbs a running dev server) and `npm run start -- -p 3100`; assets get content-hashed names and `Cache-Control: public, max-age=31536000, immutable`. Verified on ai.navrist.com: no dev client scripts, no badge, API still 401 without a session. `scripts/keep_running.ps1` now serves `.next-prod` (falling back to the dev server when no build exists) and `scripts/build_web.ps1` rebuilds and restarts. *Side effect:* the build added `.next-prod` type paths to `navrist-web/tsconfig.json`. *Mistake:* stopping the old keeper with `taskkill /T` also killed the backend it had started (it came back within seconds when the new keeper started).
* **Top bar, market scanners and analytics (built, reviewed on a dev server, not yet in the public build).** *Top bar* (`Header.tsx`): logo, then the menus **Screeners** (Build: Create Screener, Multiple Scans, Horizontal Resistance, Chart Patterns; Setups; Volume and gaps; Strength and weakness) and **Market Analytics** (Sector Analytics, RRG, Market Breadth, Top Gainers/Losers) as dropdown panels beside the logo; search icon and theme toggle on the right. **Create Screener and Horizontal Resistance are no longer buttons in the bar** (owner request, 2026-11-06); both live in the Screeners menu and the mobile drawer (the `OPEN_SCREENER_EVENT` listener in `HomeScreen.tsx` is kept). Below 1024 px a hamburger on the left opens a slide-in drawer with the same menus; the Ticker is now a slim 30 px strip. The menu talks to the page through one window event (`navrist-nav`, `scanners.ts` `navigateTo`). *Backend:* `patterns/market_lists.py` (13 list scanners computed from stored candles/closes at query time, no re-scan), `patterns/market_analytics.py` (breadth, sectors, RRG), `patterns/screen_engine.py` (`multi` and list scanners in `search`; `rrg_quadrants(..., trail=n)`), routes under `/api/v1/market/*` in `scan_api.py`. *Frontend:* `MultiScanModal.tsx`, `MarketAnalytics.tsx` (SVG charts, no chart library), `scanners.ts` (names and definitions, duplicated from the backend: keep both in step). Tested: every scanner returns plausible counts on the 751-stock store (for example Top Gainers 632, Volume Gainers 57, Gap Up 351, Momentum 24, RS High Before Price High 5), Multiple Scans in the UI matched the backend (Momentum + Double Bottom = 10), no horizontal overflow at 320 px on any new page. *Deployment:* rebuilt with `scripts/build_web.ps1` and verified on ai.navrist.com (new menu, no dev scripts, no badge). *Mistake:* the first rebuild left the OLD server running, because `build_web.ps1` found the process by the port listener, whose owner id Windows did not report; the script now finds it by command line (`-p 3100`). If a rebuild shows the old UI, stop the `npm run start -- -p 3100` / `next start` node processes and the keeper starts the new build. *Mistake fixed during review:* the first RRG drew every sector's trail at once and was unreadable; trails are now optional (hover or a checkbox) and labels avoid each other. Details and definitions: [`docs/CHARTSMAZE_GAP_ANALYSIS.md`](docs/CHARTSMAZE_GAP_ANALYSIS.md) section 3b.
* **Light theme made readable.** The light theme was almost entirely white (page, sections and cards all `#fff`, borders about 8% opacity), so headers and panels did not stand out. In `navrist-web/src/app/globals.css` (`html.light .ml`): page `#e6e9f4`, section background `--surface-0 #eceff8`, cards stay white, borders `#d2d8ea` / `#b1bad3`, darker secondary text, stronger shadows and overlays; table header rows get a tinted band with dark text and a bottom rule (`.ml thead tr`); the Home hero uses `--surface-0`. Dark mode is unchanged. Deployed with `scripts/build_web.ps1`. *Gotcha:* after editing `globals.css` the dev server (port 3101) kept serving an old stylesheet from its cache; deleting `navrist-web/.next` and restarting it fixed that (the production build is always fresh).
* **Top bar and menu headings recoloured (owner feedback: "very white").** The bar and the hamburger/dropdown headings were white and pale grey. Now the bar is a coloured band in both themes (`--bar-bg`: brand indigo `#3a2e7d` in light, deep purple `#1c1741` in dark, with `--bar-border`); in light mode everything inside the bar switches to white text through variable overrides scoped to `header.sticky`, the logo sits on a white tile (`.ml-logo`), and the dropdown panels (`.menu-panel`) switch back to dark-on-white. Menu and drawer group headings (BUILD, SETUPS ...) use `.menu-heading`: bold, accent colour, underlined. The mobile drawer has a coloured top band and tinted section buttons. Files: `globals.css`, `Header.tsx`. Checked in a browser in both themes (drawer and desktop dropdown).
* **Quick wins from the ChartsMaze comparison (data we already store).** New screener filters, computed at query time by `market_lists.annotate()` and read through `RANGE_FIELDS` in `screen_engine.py`: **RVOL** (latest volume over the average of the 20 sessions before it), **gap up %** (open vs previous close), **20-day range** (highest high over lowest low, % of the low), **price vs 10-day EMA** (%), **1-month RS** and **3-month RS** (1-99 percentile of the 1 / 3-month return among the scanned stocks), and a **200-day average turn-around** toggle (the average fell over the 60 sessions before last week, has risen since, price above it; None when there are fewer than 270 closes). Two new scanners: **Filtered Inside Bar** (daily, weekly: inside bar with range at most 60% of the previous one and price above the 50-day average). **Market Breadth** gained four history charts: stocks up / down 4.5%, advances and declines, new 52-week highs and lows (closing basis, from the stored 520 closes), and stocks with volume above their 20-day average (from the stored candles, about 90 sessions). Tested on the 751-stock store (RVOL 2+ = 57 stocks, equal to Volume Gainers; gap 3%+ = 183; 20-day range up to 8% = 10; RS 1M 80+ = 150; turn-around = 22; Filtered Inside Bar 12 daily and 13 weekly against 66 basic) and in the browser (filters present in the modal, RVOL 2+ applied from the UI returned the same stocks, five breadth charts rendered, no horizontal overflow at 320 px). *Not done:* % from 3-year high (the store keeps about two years of closes), industry rank filters (no industry field), exclude ASM / circuit-limit stocks, F&O only, float shares, listing date, FVG and dense volume (need data we do not store).
* **Watchlist and Trade Journal (from the ChartsMaze comparison; kept in the browser, no accounts).** Both store data in `localStorage` of the browser that uses them, so they are per device and per browser; the Watchlist has Share / Import (a text code) and the Journal has a CSV download as the way to keep or move data. *Watchlist* (`watchlist.ts`, `WatchlistPage.tsx`, key `navrist_watchlists_v1`): several named lists, each stock with a high / medium / low priority and a note, a star on every stock page (`WatchStar` in `StockView.tsx`), list and chart views, market data for up to 100 stocks per list taken from the daily scan through a new `symbols` filter (`filters.symbols` in `screen_engine.search`, `symbols` in `patternScan.ts`), and a **Scan these** button that opens the Create Screener limited to the list. A stock outside the 751 scanned ones can be saved; it shows "Not in the scanned list". *Journal* (`journal.ts`, `JournalPage.tsx`, key `navrist_journal_v1`): trades with side, setup, entry, quantity, stop, target, exit, fees, notes, "what went well / to improve", mistake tags and a chart screenshot (shrunk to a small JPEG, stored in the same key; a full browser quota gives an error message instead of losing data); per-trade P&L (after fees), return %, R-multiple (only with a stop) and holding days; summary of win rate, total P&L, average win and loss, profit factor, expectancy, average R, results by setup and the mistakes that repeat. Unknown values stay unknown (an open trade has no P&L, a trade without a stop has no R). Both are top-level links in the top bar and the mobile drawer. Tested in the browser: a list of three stocks with priorities, chart view (21 chart canvases), Scan these (3 rows), persistence in `localStorage`; two journal trades gave 50% win rate, P&L +1,000 and -1,000, profit factor 1.00, the setup table and the mistake tags; no horizontal overflow at 320 px on the pages, the chart view or the trade form. *Limits:* data lives only in that browser (clearing site data deletes it); no sync between devices except Share and CSV.
* **Data-dependent ChartsMaze features (exchange data, quarterly results, industries).** *Exchange feeds* (`patterns/exchange_data.py`, files in `data/exchange/`, read on demand and re-read in the background when older than 6 hours): NSE `EQUITY_L.csv` (listing dates, company names), `fo_mktlots.csv` (F&O list), the daily `sec_list_<date>.csv` price-band files (today's band per security and revisions found by comparing 30 days of files), the ASM report, the bulk and block deal files (each day appended, kept 120 days), the event calendar (board meetings for results), results filing times, order announcements and all indices. *Quarterly data* (`screens/quarterly.py`, `data/screens/quarterly.json`): one Screener.in page per scanned stock, consolidated view first and the standalone page when the consolidated one has no readable quarterly table, giving 12 quarters of sales, operating profit, OPM, net profit and EPS, FII and DII holding, annual EPS, ROE, ROCE, 5-year sales growth and Screener's four-level classification; 749 of 751 stocks read (HEG and ICICIPRULI have no readable page). `market_lists.annotate()` turns these into per-stock measures read by the screener: growth (QoQ, YoY) of EPS, net profit and sales, OPM change in percentage points, OPM of the last four quarters, ROE, ROCE, PEG (P/E over annual EPS growth), streaks (net profit positive, EPS / net profit / sales / OPM rising for N quarters), FII holding change, float shares (market cap / price x free float), industry rank (1 week, 1 month, 3 months), price x 20-day volume, plus yes/no **flags** (`FLAGS` in `screen_engine.py`): Code 33, profit turnaround, EPS up on last year, latest quarter reported, FII holding up, F&O only, exclude ASM, exclude 5% / 2% price band, block deal in 30 days, results due in 7 days, unfilled bullish fair value gap (daily 2% / weekly 3%); an industry multi-select and a "listed after" date. *New scanners:* Earnings Gap Up and Positive Earnings Reaction (latest and previous quarter; filing time -> first reaction session -> gap, best close within 5 sessions), Recent IPOs, IPO Setups. *New pages* (`FeedPage.tsx`, routes `/api/v1/market/feed/{name}`): Results Calendar, Circuit Revision List, Order Wins, Bulk and Block Deals, ASM List, Sector Indices, Recent IPOs, Past Winners; *Industry Analytics* tab (`market_analytics.industries`, 143 industry groups, equal or market-cap weighted, ranks, rotation); stock lists show small markers (ASM, 2% / 5% band, block deal, results soon) and the industry. All reachable from a new **Tools** menu, the Screeners and Market Analytics menus and the mobile drawer. *Tested:* every feed returned data (listings 2,630; F&O 224; 246 band revisions; ASM 189; 93 bulk deals, 0 block deals that day; 478 calendar rows; results filings for 1,450 companies in the Sep 2026 quarter; 67 order wins; 139 indices); the scanners returned 75 / 60 / 178 / 119 earnings matches; the Results Calendar showed 992 companies; the filters were applied from the modal in the browser (Code 33 gave 14 stocks with a Results-soon marker); no horizontal overflow at 320 px on any new page or modal tab. *Mistakes found and fixed:* NSE's financial-results API no longer lists the current quarter (it returns December 2024 filings), so results dates are read from "Outcome of Board Meeting" announcements instead; the first Screener pass recorded 481 stocks as missing because the shared fetch helper blocks all calls for three minutes after one slow reply, so `quarterly.py` has its own retrying fetch; some Screener pages have an empty period heading row (standalone page used); the order-win filter first included regulatory "orders passed" announcements; deal prices were overwritten by the current price; and the first fair-value-gap flag matched 574 of 751 stocks, so a minimum gap width was added. *Limits:* Screener and NSE are the sources (their layouts or access can change); a stock without a value for a measure never matches a filter on it; results dates come from announcement text that names the period, so a few filings may be missed; bulk and block deal history only goes back to when Navrist first read the files; the Past Winners page covers only the years inside the stored closes (about two); AI summaries on Order Wins are not generated.
* **Login hardening.** Wrong-password attempts are rate-limited per client address ([D.3](#d3-authentication-as-implemented)).
* **Secrets review.** Found the real site password in an `auth.py` comment (M-18) and API keys, bearer tokens, public IP and MAC address in tracked `logs/` files (M-20). `.gitignore` extended and `logs/` untracked in commit `a740486`.

---

### B.18 Stage 17 - Forecast window, Financial Result tabs, hosting and the sector specialist agent (2026-11-06 -> 11-12)

*Source: this session's work and the commits on `main` after `91fbaa5` (observed in git); dashboards (Cloudflare, Oracle, Hostinger) are not in git.*

* **Top bar.** The Screeners dropdown (about 25 items in five columns) became a category list on the left (Build, Setups, Volume and gaps, Strength and weakness, Earnings and IPOs) with one list at a time on the right; the mobile drawer slides in and out (420 / 340 ms, items fade in one after another, reduced motion respected). The site opens in **light mode** by default; a visitor's dark choice is saved in their own browser only (`layout.tsx`, key `navrist_theme`).
* **Landing page.** The pattern chips show the top 10 (Cup & Handle, VCP, Head & Shoulders, Double Bottom, Symmetrical Triangle, Double Top, Ascending Triangle, Inverse Head & Shoulders, Descending Triangle, Rectangle) with a small **More** button for the other 22. In Create Screener each pattern row is tinted green / red / grey with a triangle for its direction (`PatternFilterModal.tsx`).
* **Forecast.** (1) The daily forecast now learns from each stock's **whole adjusted history** (about 1996 on) instead of 5 years, with a **Full history / Last 5 years** toggle (`GET /api/v1/outlook/{symbol}?window=max|5y`). `tests/history_window_probe.py` replayed both on 80 large stocks (about 15,000 past dates): hit rate 53.1% for full history against 52.4% for 5 years, and fewer calls when unclear. The same probe shows the daily forecast barely beats a coin flip, so it is worded as a lean. (2) The headline states the percentages ("Leans down over the next 5 sessions: 32% up, 37% down", "Too close to call...: 34% up, 34% down") and says what "flat" means (a move smaller than +-x%). (3) **News** is a button beside the Forecast title (it used to sit inside "See the reasoning" and vanished when no forecast could be made); headlines now need the company's first two name words, and unscanned stocks take their name from the NSE listings file (a search for Panorama Studios had returned the BBC programme).
* **Stock page fixes.** Shareholding was "unavailable" for companies with no promoter row (YES Bank): the parser dropped the whole table (`tools/screener_scraper.py`; cache key `fin2_` -> `fin3_`). The "Not meaningful for lenders" note was removed. Stocks under a year old show "Range since listing" and a "Since listing" return instead of blanks.
* **Financial Result.** New tabs **PAT** and **Free Cash Flow** (yearly, from Screener's cash-flow table via `tools/screener_fcf.py`, `GET /api/v1/stock-fcf/{symbol}`; a company with no FCF row is "unavailable", never zero); the Results tab gets a yearly FCF bar (on the March quarter) and an EPS bar on its own right-hand scale; each quarter is a tappable card that opens a detail panel (figures, change on last quarter and on a year earlier); one colour per measure everywhere (income mint, PBT amber, net profit / PAT blue, FCF purple, EPS pink). *Mistakes found:* Screener throttles quickly (retry and cache added); a throttled consolidated page must not fall back to standalone for a company that has consolidated accounts.
* **Hosting.** `ai.navrist.com` is still served from the owner's PC through the Cloudflare Tunnel, so it shows Cloudflare **Error 1033** whenever the PC is off or `cloudflared` is not running (it does not start by itself; creating a startup task was refused by the permission system). A move was started: an Oracle Cloud Always Free account (home region India West, Mumbai) and a `navrist-vcn` network exist, but creating the free ARM server fails with "Out of capacity" at 4, 2 and 1 OCPU; a Hostinger KVM 2 VPS (2 vCPU, 8 GB, Rs 779/month on a 24-month term, Rs 18,696 upfront) was priced. `deploy/server_setup.sh` and `docs/ORACLE_DEPLOY.md` are ready (the upload package must leave out `cache/ar_pdfs`, 6.6 GB).
* **History depth.** NSE daily files exist from 1 December 1994; BSE's stock price page lists monthly and yearly figures from 1991 (daily only for the last 10 years). Those early prices are raw and BSE's company-action records start around 2000, so they cannot be adjusted and are **not used**.
* **Sector specialist agent.** Sector History, "what moved it" and Sector Outlook under Market Analytics; full description in [`docs/SECTOR_AGENT.md`](docs/SECTOR_AGENT.md).

### B.19 Stage 18 - Brand colours, chart controls and clearer patterns (2026-11-12)

*Source: this session's work and the commits on `main` after `ce42e61` (observed in git). Verified in the browser pane on the local dev site where noted; the live site runs the same code.*

* **Brand.** The top bar is exactly **#04295D** (Navrist blue) in both themes (`--bar-bg`; computed colour checked as rgb(4, 41, 93)); the menu panels, hover tints and shadow that were purple now use the same blue. The logo sits on a white rounded tile in both themes (it vanished on the blue bar in dark mode). The wordmark "NAVRIST AI" (header and the landing heading) uses **Manrope** 800 (`--font-brand`); the rest of the site stays in Poppins. A second brand colour, gold, was requested as "D5V36B", which is not a valid hex code, so it is **not applied** (open: ask the owner for the correct code).
* **Landing page.** The pattern chips are an aligned grid (2 / 3 / 5 columns): nine chips plus a **More (23)** cell fill two rows; the first four (Pocket Pivot, Order Blocks, Falling Wedge, Undercut & Rally) are the only patterns with a measured effect in the evidence study ([`docs/PATTERN_STUDY.md`](docs/PATTERN_STUDY.md)), then Cup & Handle, VCP, Double Bottom, and two bearish ones (Head & Shoulders, Double Top) so the first rows show both directions. The rest rise in one after another on More and sink out on Less (`chip-in` / `chip-out` animations, skipped for reduced motion). The "not a forecast" note under the chips was removed at the owner's request. Em dashes were removed from interface text (and the colour dashes from the chart filter); the roughly 100 "—" placeholders for missing values were left (open question: "N/A" instead?).
* **Forecast strip and chart lines.** Above the price chart, `ForecastStrip.tsx` shows three cards (next session, 5 and 20 sessions: lean, up and down odds, likely range, number of similar days) from the same data as the Forecast section. The chart's forecast lines show their prices and **both targets** ("Target 1 (1x) ₹819", "Target 2 (2x) ₹828"), swing lines are prefixed "Swing". A **Chart lines** filter (`ChartLinesMenu.tsx`, top row of the chart next to the Patterns toggle, with the Forecast and Volume switches) turns lines on and off: today's plan (the default, entry, stop, two targets), swing plan, opening range, 52-week high and low, and 20 / 50 / 100 / 200-day moving averages (daily charts). Each average is computed from the full daily history (`history` prop) and continues to the right as a **dashed line inside the forecast fan, assuming the price follows the middle of the fan** (`StockChart.tsx` effect 6; a projection under that assumption, not a separate prediction). The popover uses a CSS animation (`menu-pop`) instead of script timers, which a throttled browser tab can stall.
* **Pattern markers.** Over five years the Patterns toggle drew 126 small identical arrows. Now: developing patterns (forming / awaiting breakout) get large labelled arrows ("head & shoulders (waiting)"), recent confirmations are medium, older ones small and faded; a legend under the toggle explains arrow direction and colour (green gained, red fell, blue too recent, grey flat, measured 5 sessions after confirmation). The two developing patterns nearest the price also draw their outline, breakout or breakdown level, "fails" level and a **measured-move target** (breakout plus the pattern's depth, a rule of thumb) without being picked. The **Active setups** cards show the target and the study's evidence for that pattern ("Small proven edge", "No proven edge", "Went the other way", with the 20-session average and win share), from `GET /api/v1/patterns/evidence`, which reads `data/research/pattern_study.json`. Not done on purpose: a per-pattern price forecast, because the study found little or no edge.
* **Sector Outlook.** The reliability note and the scheduled events are now two popover buttons ("How far can this be trusted?", "Scheduled events ahead") instead of tall boxes; a duplicate Fed date (the 2028 table parsed as 2027) was fixed.
* **Mistakes found and fixed this session.** The first pattern study kept only patterns still "confirmed" today and so dropped 41,000 failed ones (see PATTERN_STUDY.md); the dev server serves stale CSS and fonts until `.next` is cleared and restarted; a throttled browser pane stalls `setTimeout` and `requestAnimationFrame` (use CSS animations for open and close).

### B.20 Stage 19 - Every BSE-listed company (2026-11-12)

*Source: this session's work (observed in git and in the running app). The BSE list was read from BSE's "List of Securities" page; counts are from that read on 2026-11-12.*

* **Universe.** BSE lists 5,148 active equities (Equity T+1, Active). Matched by ISIN against NSE's `EQUITY_L.csv`, 2,506 are also on NSE and **2,642 are BSE-only**. Left out: 279 mutual-fund and ETF units (not companies), 7 **rights entitlements** (codes 75xxxx, symbols ending `-RE` / `-RE1`, deleted again after they were found to show up as if they were companies) and a company whose BSE trading symbol is also an NSE symbol of a different company (its Yahoo ticker would be ambiguous). The Supabase `companies` master went from 2,473 to 4,829 rows; 2,091 existing NSE rows also got their ISIN and 39 a missing BSE code. A backup of the old master is `data/bse/companies_master_backup_2026-11-12.json` (data folder, not in git).
* **How the list was obtained.** BSE's API refuses plain requests ("Access Denied"). The page itself calls `ListofScripData_new` (Equity, Active); that call was made from inside the page in the browser pane and the rows were sent to a throwaway local receiver, then saved as `data/bse/bse_equity_active.json`. NSE's ISINs are in `data/bse/nse_isin.json`. `tools/bse_universe.py` turns them into `data/bse/bse_only_universe.json` (symbol = BSE trading symbol, BSE code, ISIN, listed market cap, Yahoo ticker `<symbol>.BO`; `python -m tools.bse_universe` regenerates it).
* **Pricing and data.** Yahoo prices a BSE-only company by its trading symbol (`ANDHRAPET.BO` works; the numeric code, `500012.BO`, returns nothing). **Screener** knows these companies by BSE code, so `tools/screener_scraper.py` pre-fills `_SYMBOL_MAP` with the codes (before this the overview often showed "unavailable"). Angel One also serves BSE daily history (sample of 40 codes: 25 with 250+ days). The stock page works for them: live price, chart, key metrics, shareholding, results, about, peers, tagged BSE.
* **Scan, screeners, fundamentals.** `patterns/scan.py` `universe()` = 751 NSE stocks + the BSE-only list (3,105 after exclusions), each row carrying `exchange`, sector None and index None (never guessed), market cap from Yahoo or else BSE's listed figure. A stock with fewer than 60 daily bars is skipped as "not enough price history". `screens/universe.py` (P/E, EPS, debt, promoter, profit, dividend) and `screens/quarterly.py` (quarterly growth, ROE, ROCE and **Screener's industry classification**) include them too. The NSE-taxonomy **sector** stays empty for BSE-only stocks, so they are excluded from Sector Analytics and the sector filter but appear in Industry Analytics once classified. Peer Comparison: when Screener has no peer table, `_sector_peers` falls back to scanned stocks in the same Screener industry, closest by market cap (only once the stock is scanned and classified).
* **State when written.** The first full scan (about 2,300 BSE-only stocks) and the two Screener builds were still running in the background (hours; resumable). Until they finish, many BSE-only stocks have no pattern row, fundamentals, classification or peers; those fields show "-" / unavailable and never zero.
* **Screener rate limit and the Yahoo fallback (later the same day).** Screener answers HTTP 429 to this machine when it is asked at about one request every 3 seconds or faster (a stock page read is 3 or more requests); the first build pace (two workers) blocked it for everyone, including the stock pages, which then showed only the chart. Fixes: `tools/screener_scraper.py` pauses all Screener requests after a 429, for 2, 4, 8, 16, then 30 minutes while it repeats (`note_429` / `note_ok` / `wait_if_down`, shared by the stock pages and both builds); a failed live read returns the last saved copy (up to 30 days); BSE-only reads are kept 7 days (`BSE_FIN_TTL`); the builds run one worker, the fundamentals build about one company per 5 seconds, BSE-only companies first and the biggest first, and it waits out a rate-limit instead of recording a weaker Yahoo-only row. When no Screener read is available, `app.py` `_yahoo_overview` fills the page from **Yahoo Finance** (market cap, P/E, EPS TTM from the last four quarters, book value, debt/equity, margin, growth, promoter holding as Yahoo's "insiders", the business summary and up to 13 quarters of results; a zero from Yahoo is treated as unknown; cached 6 hours; `source: "yahoo"`). Shareholding pattern stays unavailable on that path, and the results note says the figures are Yahoo's with no stated basis. Peers for a BSE-only company come from Screener, else from scanned stocks in the same Screener industry, so they need the classification build to have reached it. A test of 10 random BSE-only stocks gave 9 filled pages (peers for 3).
* **Suspended companies and a coverage audit (2026-11-12, later).** BSE's other segments were read the same way: Equity T+0 (520 rows) are all companies already covered (same ISINs as the main list or NSE); **Suspended equities** are 1,221 rows, of which 500 are rights entitlements and 176 mutual-fund series (excluded), leaving **544 listed-but-suspended companies**, added to the master (`tools/bse_universe.py` `build_suspended`, `data/bse/bse_suspended_universe.json`, `data/bse/bse_other_lists.json`; master now about 5,349 rows). They are searchable and get a stock page (last chart and Screener figures) with a "Suspended" chip (`status` from `company_search.describe`), but are **not** scanned or read by the background builds (nothing trades; each Screener read costs rate-limit budget). Audit of the 2,354 trading BSE-only companies at that moment: 2,308 have a listed market cap, 2,353 an ISIN; 2,137 scanned and 147 skipped for under 60 bars (about 70 still running); 864 classified by Screener (73 pages missing, 1,417 not read yet); only 53 fundamentals rows and 57 saved Screener reads (Screener rate limit, M-39). New: `tools/yahoo_industry.py` also keeps Yahoo's headline figures (P/E, EPS, debt/equity, promoter, yield; a zero is unknown), and `patterns/scan.py` `_load_all` uses them, marked `fund_src: "yahoo"`, for a stock with no Screener fundamentals row, so the screener filters have data for BSE-only stocks before Screener catches up. A second rights-entitlement spelling ("SGLRES- RE3") was found and removed.
* **Several sources for peers, ROCE, and page speed (2026-11-12, latest).** `tools/peer_finder.py` chooses peers by sources voting: Screener industry, Yahoo industry, Yahoo's "similar stocks" list (`recommendationsbysymbol`, either direction) and NSE sector; a candidate's score is the number of sources that group it with the company, then closeness in market cap, and a source with nothing simply does not vote (`peers_source: "mixed"`, `peers_used` names the sources; Screener's own peer table is still used first, an NSE sector first for a company that has one). BSE's own list carries no industry (0 of 5,148). The peer table's ROCE is Screener's (`screens/quarterly.py`) where that company was read, else Yahoo's statements (`tools/yahoo_industry.py` `_roce`: EBIT over total assets less current liabilities, latest annual; None when either is missing). Speed, measured on a BSE-only stock page (slowest calls, cold): outlook 6.4 s -> 2.0 s, patterns 5.6 s -> 1.8 s, overview 5.4 s -> 1.6 s, EPS 6.2 s -> 1.6 s; causes fixed: NSE lookups for companies NSE does not have (profile, overview) are skipped for BSE-only companies; the stock-eps endpoint waited up to 6 s (now 1.5 s; the page polls); `scan._load_all` re-joined about 3,000 files on every Yahoo-file change and concurrently from every request (now one locked rebuild, a cheap Yahoo overlay, and a start-up warm-up); the outlook treated "no sector" as "every stock with no sector" as peers; identical Yahoo history requests from one page now share one read (`get_candles` memory: 20 to 120 s intraday, 5 min daily); the Yahoo overview is saved 24 hours (`cache/yahoo_overview/`) and read in parallel with Screener and the price history.
* **End-to-end check of 20 random BSE-only stocks (2026-11-13) and what it found.** Search, price, chart, overview, peers and the Suspended tag were checked per stock against other sources. All 20 are found; 17 have a price and chart (the 3 without are two suspended companies and one new listing, `WEBSL`, with no trading history); 18 have an About text and peers. Defects found and fixed: (1) **EPS (TTM) summed four reported columns whatever their frequency**, so a half-yearly reporter (many BSE SMEs, e.g. `NBL`, `SHLOKKA`) showed two years of earnings; `app.py` `_ttm_eps` now sums 4 quarterly, 2 half-yearly or 1 annual column by the spacing of the periods (None when a column is missing), the overview returns `period_months`, and the results note says "half-years" for them; (2) **a live quote whose last price lies outside the day's own range** (Angel gave `TECHCON` open, high and low 99.54 but last 12.54, a stale close) is no longer believed: `live_quote` falls back to the other provider (generic check, not per stock). Not fixed, stated: `ZR2` market cap differs by source (Screener 207 cr; Yahoo and the BSE list 46 cr) because their share counts differ, so the number can change with whichever source answers; `AAPLUSTRAD`'s P/E looks off only because its EPS (0.03) is rounded to two places. Coverage at that time (2,354 trading BSE-only): 1,705 classified by Screener, Yahoo industry known for 2,182, Yahoo ROCE for 1,972.
* **Services stopped when the previous session ended (2026-11-13).** The backend, web server, keeper and Cloudflare tunnel had been started from the assistant's session and ended with it: `ai.navrist.com` returned 530 from about 23:23 on 12 November until they were restarted by hand (`scripts/keep_running.ps1` and `cloudflared tunnel run navrist`). Restarting also exposed that Windows Application Control had begun blocking `uuid_utils`' compiled file (needed only by langchain for tracing ids), so `import app` failed; `tools/uuid_utils_fallback.py` (imported first in `app.py`) installs a small pure-Python `uuid7` when the real package cannot load. Nothing starts these services automatically after a reboot (M-40).
* **Mistakes found.** Yahoo's BSE feed returned nothing for numeric codes and a first sample test wrongly concluded Yahoo had no BSE data; the stock-overview call timed out under load and reported "unavailable" for a page Screener served fine alone; Screener rate-limited (HTTP 429) when test bursts ran on top of the builds. Do not test in bursts while the builds run.

---

## C. How the complete system works

### C.1 The data flow

```
Source documents and market data
   Annual Report PDF (BSE/NSE download or user upload)   Uploaded XBRL / Shareholding Pattern   Live price (Angel One -> yfinance)   Price history (Yahoo, Beta only)
        |
        v
1. DATA EXTRACTION            tools/annual_report_financials.py (statement-page selection, unit detection, row reader,
        |                     broad alias fallback, text-disclosure scans for dividends/EPS, note scans) ; tools/nse_xbrl.py ;
        |                     tools/bank_extractor.py (banks) ; tools/shareholding_scraper.py
        v
2. FINANCIAL FACT NORMALISATION   tools/fundamental_fact_store.py -> FactSet of CanonicalFact
        |                         (value, prior value, period, basis, perimeter, page, method, status, confidence, warnings)
        v
3. VALIDATION AND UNIT CONVERSION   everything converted to Rs Crore; ledger / balance-sheet identity checks;
        |                           EPS x shares vs profit; debt <= assets; failing facts become needs_review
        v
4. STORAGE AND CACHING        disk caches under cache/ (PDF bytes, page text, extraction results, per-ratio wrappers);
        |                     in-process FactSet memo; Supabase tables ratio_values / fundamental_analysis_results
        v
5. DETERMINISTIC RATIO CALCULATION   tools/ratio_contract.py (one function per ratio, unrounded value_raw, status inheritance)
        |
        v
6. EVIDENCE AND CALCULATION BREAKDOWNS   tools/ratio_breakdown.py (legs, expression, pages, parents, reconciles flag)
        |
        v
7. API                        app.py: POST /api/v1/ratio/{key}, /api/v1/document-analysis/*, per-ratio legacy endpoints
        |
        v
8. FRONTEND DISPLAY           frontend/src/views/DocumentAnalysis.jsx + CalculationBreakdown.jsx
```

### C.2 What happens at each step

| Step | What it does | If data is missing | If ambiguous | If wrongly formatted | If inconsistent |
|---|---|---|---|---|---|
| 1 Extraction | Finds the Balance Sheet, P&L, Cash Flow and note pages; reads each labelled row's current and prior-year figures; chooses consolidated first, standalone only if the filing has no consolidated statements | Fact marked missing -> ratio `insufficient_data` / `not_disclosed` with a reason; **never 0** | Narrow label match first, then broad alias fallback; the label, page and method are recorded; a proxy is marked `estimated` | Page-number ranges, lettered note references ("23A, 23B"), a second reference column, dot-leader contents pages and unit footnotes far below a table are handled generically (audit decision T) | Two EPS lines -> owners' ("excluding NCI") line chosen; shown in warnings |
| 2 Normalisation | Builds one `FactSet` per (company, year, basis) | A required fact stays absent | `perimeter` (owners vs whole entity) is stored on each fact | Values that fail type checks are dropped | A fact never mixes bases; prior-year values travel with current |
| 3 Validation | Converts units; checks identities | - | - | Unit declared per page (crore / lakh / million / thousand); "millions" plural bug fixed | **Flags, never changes**: current assets >= inventory+receivables+cash and <= total assets; current liabilities >= payables and <= total liabilities; revenue not under 5% of profit; TA = liabilities + equity; owners' <= whole-entity profit; 0 <= debt <= assets. A failing fact and everything built on it becomes `needs_review` |
| 4 Storage | Writes caches keyed by document identity + code versions | - | - | - | Version keys force recomputation after a code change ([N](#n-cache-versions-and-data-freshness)) |
| 5 Calculation | Applies the contract formula to unrounded values | Withholds the ratio (never fabricates) | Uses documented policy (perimeter, EV, cash...) | - | A derived ratio inherits the *worst* status of its parents |
| 6 Breakdown | Records every input leg, formula text, pages and a `reconciles` check (re-evaluates the expression) | Shows which input was missing | - | - | A non-reconciling breakdown is a test failure |
| 7-8 API / UI | Returns value, unit, status, confidence, warnings, breakdown; UI shows value and a plain reason line when no value | "Not available" text with reason | - | - | `stale` flag when the stored row's `formula_version` is old |

### C.3 Status vocabulary (also in the glossary)

`verified` - computed from disclosed inputs, no caveat. `needs_review` - computed, but an input is a proxy/estimate, a perimeter is ambiguous, an
acquisition distorts comparability or a parent is `needs_review`. `not_meaningful` - arithmetic exists but is economically meaningless (e.g. EV/FCF with negative FCF). `insufficient_data` / `not_disclosed` - an input is unknown. `not_applicable` - the ratio does not apply (bank ratios for a non-bank; Net Debt/EBITDA for a net-cash company).

### C.4 Manual upload versus the automatic data pipeline

| | Manual (document-first) | Automatic |
|---|---|---|
| Entry | `POST /api/v1/documents/analyse` (or `/manual/upload*`), then `/api/v1/document-analysis/run` | Search a company -> per-ratio endpoints (`/api/v1/<ratio>`), `POST /api/v1/ratio/{key}`, precompute worker |
| Source documents | Files the user uploaded (Annual Report required; XBRL, shareholding pattern, other filings optional) | Annual Report downloaded from BSE, then NSE (`cache/ar_pdfs`, 30-day TTL); NSE XBRL; NSE shareholding endpoint |
| Live fallbacks | **Forbidden** (`tools/manual_mode.py`); only the Angel One live price is allowed; Beta -> `insufficient_data` | Allowed (live BSE/NSE/yfinance) |
| Extraction code | **Same** as automatic since 2026-10-08 (`_extract_from_pdf`, broad fallback) | Same |
| Fact store and formulas | **Same** `get_canonical_facts` -> `ratio_contract` | Same |
| Where results are stored | `fundamental_analysis_results` (+ `uploaded_documents`, `extracted_values`) | `ratio_values` (precompute) and per-ratio disk caches |
| Cache separation | Memo/cache keys include `is_manual_mode()` and the document identity hash | Same keys with the other flag |
| Remaining differences | Uploaded XBRL facts are used only in manual mode; shareholding and Beta source; DB tables | Precompute writes `extraction_version`; DB fast path only for the *latest* year |

There is **no second calculation engine**. The remaining differences are in *where the documents come from* and *where results are stored*, not in how numbers are computed.


---

## D. Project architecture and important files

### D.1 Top-level layout (as found)

| Path | Responsibility |
|---|---|
| `app.py` (2,676 lines) | FastAPI application: auth, company search, ~90 routes, serves `frontend/dist`, startup loading of the NSE company universe |
| `auth.py` | Shared-password login -> JWT; `require_session` dependency guards data endpoints |
| `agent/stock_agent.py` | Original LangGraph research agent (`POST /api/research`); legacy, still wired |
| `tools/` | All data, extraction, calculation and scoring modules (~170 files; detail below) |
| `forecast/` | Probabilistic price-range forecasting package (pilot); `forecast/daily/` is the daily-bar research track |
| `frontend/` | Vite + React 18 + Tailwind single-page app (`src/views`, `src/components`, `src/lib`, `tests/*.test.mjs`, `scripts/`) |
| `frontend-dashboard/` | Legacy single-file React dashboard (served only if `frontend/dist` is missing) |
| `db/` | SQL migrations `001_schema.sql` ... `009_supporting_document_extraction.sql` for Supabase |
| `tests/` | Backend tests (`test_*.py`, run by pytest) and manual probes (`*_probe.py`, `universe_scan.py`, `final_validation.py`, `ratio_audit_matrix.py`) |
| `docs/` | Generated and written documentation (this set, ratio contract, validation reports) |
| `cache/` | Runtime caches (git-ignored): `ar_pdfs`, `ar_text`, `bse`, `nse_xbrl`, `xbrl_manual`, `manual_docs_text`, `shareholding*`, `statement_selection`, `screener*`, `reports`, ... |
| `data/forecast/` | SQLite market store for the forecast package (git-ignored) |
| `exports/`, `uploads/`, `logs/` | Generated PDFs/CSVs, user uploads, application logs |
| Root `*.md`, `*.xlsx` | `CLAUDE.md`/`AGENTS.md` (permanent rules), `DEPLOY.md`, `Navrist_Qualitative_Framework.md`, qualitative and feature trackers |
| Root `*.log`, `*_pages.txt`, `_dbg_*.txt`, `_audit_final_table.txt`... | Debug leftovers from past sessions (not part of the product) |

### D.2 The files that matter, by responsibility

| Responsibility | Actual files |
|---|---|
| Backend application and API routes | `app.py` (routes: `/api/search-symbols`, `/api/auth/*`, `/api/quote`, `/api/live-chart/*`, `/api/research`, `/api/v1/ratio/{ratio_key}`, ~65 legacy `POST /api/v1/<ratio>` endpoints, `/api/v1/documents/*`, `/api/v1/manual/*`, `/api/v1/document-analysis/*`, `/api/v1/qualitative/*`, `/api/v1/ask-navrist`, `/api/v1/ratio-audit/{symbol}`, `/api/health`) ; forecast routes are in `forecast/api.py` |
| Authentication | `auth.py` |
| Stock-page chart controls (added 2026-11-12) | `ForecastStrip.tsx` (forecast above the chart), `ChartLinesMenu.tsx` + `StockView.tsx` (filter, averages, levels), `StockChart.tsx` (overlays: markers, developing patterns, moving averages and their projection), `ActiveSetups.tsx`, `patterns.ts` (`measuredTarget`, `fetchEvidence`), `patterns/api.py` (`/api/v1/patterns/evidence`) |
| Research code (added 2026-11-12) | `research/pattern_study.py` (event study), `research/lookahead_check.py` (replay on a cut series), `tests/test_pattern_study.py`, results in `data/research/` (not in git); see [`docs/PATTERN_STUDY.md`](docs/PATTERN_STUDY.md) |
| Sector specialist agent (added 2026-11-12) | `patterns/sector_history.py` (monthly sector indices from stocks' adjusted history -> `data/sector_history/monthly.json`), `patterns/sector_events.py` + `sector_events.json` (biggest moves, events, reactions), `patterns/sector_outlook.py` (odds, tilt, replay), `patterns/upcoming.py` + `upcoming_events.json` (dated events ahead); `SectorHistory.tsx`, `SectorOutlook.tsx`; see [`docs/SECTOR_AGENT.md`](docs/SECTOR_AGENT.md) |
| Exchange data and quarterly fundamentals (added 2026-11-06) | `patterns/exchange_data.py` (NSE feeds -> `data/exchange/*.json`), `patterns/market_feeds.py` (row sets for the list pages), `screens/quarterly.py` (Screener quarterly pages -> `data/screens/quarterly.json`; also runnable as `python -m screens.quarterly [--force]`), `navrist-web/.../FeedPage.tsx` |
| Pattern scanner and screener (added Oct-Nov 2026; not covered in the October sections) | `patterns/` (`registry.py`, `engine.py`, `detectors/`, `features.py` per-stock measures and horizontal resistance, `scan.py` per-stock store in `data/pattern_scan/`, `screen_engine.py` filters/backtest/RRG/multi-scan, `market_lists.py` list scanners, `market_analytics.py` breadth/sectors/RRG, `scan_api.py` routes); web UI in `navrist-web/src/components/sites/marketlens/` (`PatternFilterModal.tsx`, `PatternScanPage.tsx`, `BacktestPanel.tsx`, `patternScan.ts`, `HomeScreen.tsx`, `Header.tsx`, `controls.tsx`). Local reference notes `docs/PATTERNS.md` and `docs/DATA_SOURCES.md` exist in the working folder and are deliberately kept uncommitted |
| Company identification and symbol resolution | `tools/company_search.py` (ranking: exact symbol > exact name > prefix > contains > fuzzy; matches symbol / BSE code / ISIN / name; returns the exchanges), `app.py::STOCK_REGISTRY`, `resolve_symbol_from_registry`, `load_scrip_master_async`; `tools/seed_company_registry.py`; `tools/nse_sector_map.py`; frontend `src/lib/companySearch.js`, `components/StockSearch.jsx`; `tools/audit_company_references.py`, `tools/remove_company_records.py` |
| Statement basis (consolidated vs standalone) | `tools/statement_selector.py` (thin wrapper), actual logic in `annual_report_financials._get_extracted_financials` |
| Annual-Report parsing | `tools/annual_report_financials.py` (page selection, row reader, unit detection, dividend/EPS scans; `_EXTRACTION_LOGIC_VERSION`), `tools/ar_table_extractor.py` (pdfplumber tables), `tools/ar_document_cache.py` (PDF bytes + page-text caches), `tools/nse_annual_reports.py`, `tools/bse_scraper.py` |
| XBRL parsing | `tools/nse_xbrl.py` (NSE XBRL fetch/parse and the per-ratio wrapper functions), manual XBRL override in `tools/manual_document_pipeline.py` |
| Bank/NBFC extraction | `tools/bank_extractor.py`, `tools/bank_ratios.py`, `tools/sector_ratio_applicability.py` |
| Financial fact storage | `tools/fundamental_fact_store.py` (`EXTRACTION_VERSION`, `FactSet`, integrity checks, `get_canonical_facts`) |
| Ratio definitions and contract | `tools/fundamental_ratio_registry.py` (68 ratios: number, label, formula text, category, strategy, dependencies), `tools/ratio_contract.py` (`SPEC`, `PARENTS`, `FORMULA_VERSION`, `PERIMETER_POLICY`, `EQUITY_BASIS`, `BANK_BOUNDS`, `BETA_POLICY`), `docs/ratio_contract.md` (generated) |
| Ratio calculation services | `tools/ratio_calculation_engine.py` (canonical API adapter), `tools/document_analysis_engine.py` (manual-upload orchestrator/adapter), `tools/precompute_worker.py` + `run_full_precompute.py` (batch), `tools/db_ratio_reader.py` (fast DB read), `tools/refresh_ratios.py` |
| Evidence and calculation breakdowns | `tools/ratio_breakdown.py` (`BREAKDOWN_VERSION`), `frontend/src/components/CalculationBreakdown.jsx`, `tools/ratio_display.py` (labels/order only) |
| Manual document workflow | `tools/manual_document_pipeline.py`, `tools/manual_mode.py`, `app.py` `/api/v1/documents/*`, `/api/v1/manual/*`, `frontend/src/components/ManualUpload.jsx`, `frontend/src/views/DocumentAnalysis.jsx` |
| Market data | `tools/market_price.py` (live quote), `tools/angel_scraper.py` (Angel One), `tools/market_history.py` (Beta history), `tools/yf_cache.py`, `tools/live_chart_yf.py`, `tools/axis_rapid_client.py` + `axis_feed_*.py`, `tools/shareholding_scraper.py`, `tools/screener_scraper.py` |
| Cache management | `_document_identity_tag`, `_contract_cache_key`, `_EXTRACTION_LOGIC_VERSION` in `annual_report_financials.py`; `clear_run_cache` in `fundamental_fact_store.py`; `tools/ar_document_cache.py`; `tools/db_ratio_reader.py` freshness guard |
| Qualitative analysis | `tools/qualitative_engine.py` (~8,000 lines), `qualitative_task_registry.py`, `qualitative_task_engine.py`, `qualitative_evidence*.py`, `qualitative_source_router.py`, `qualitative_db.py`, 54 `*_scoring.py` modules |
| Frontend | `frontend/src/main.jsx` (app shell, many legacy components), `views/{Landing,Overview,DocumentAnalysis,LiveChart,History,Settings}.jsx`, `components/*`, `lib/*` |
| Testing | `tests/test_*.py` (24 files), `frontend/tests/*.test.mjs` (7 files), probes listed in L |
| Documentation | `docs/`, `DEPLOY.md`, `CLAUDE.md`, `AGENTS.md`, project memory notes (outside the repo, in the user's Claude profile) |

### D.3 Authentication (as implemented)

Not an email/password system: `auth.py` verifies a **single shared `SITE_PASSWORD`** (constant-time comparison) and issues a short-lived JWT (`JWT_SECRET_KEY`, default 12 h). The token is stored in the browser's `localStorage` and sent as `Authorization: Bearer`; protected endpoints use `Depends(auth.require_session)`. An older memory note describing per-user email accounts is out of date. Hardening gaps recorded by the owner: token in `localStorage`, no per-user audit trail.

**Added 2026-11-06 (working tree, not yet committed):** `/api/auth/login` is rate-limited per client address (`auth.client_key`, `login_retry_after`, `record_login_failure`, `clear_login_failures`): 5 wrong passwords in 15 minutes return HTTP 429 with `Retry-After`; defaults are `LOGIN_MAX_FAILURES=5` and `LOGIN_WINDOW_SECONDS=900` (both overridable in `.env`). The client address is `CF-Connecting-IP`, else the first `X-Forwarded-For` entry, else the socket address. State is in memory and resets on restart. Audit result: 91 of 95 backend routes require `auth.require_session`; the four open routes are `POST /api/auth/login`, `GET /`, `GET /api/health` and `GET /api/v1/market-indices` (public market data shown in the ticker before sign-in). CORS allows any origin, which is acceptable only because the backend port is not exposed publicly and tokens travel in a header, not a cookie.

> **Security finding while documenting (partly fixed 2026-11-06):** the docstring line has been replaced by a placeholder in the working tree, but the password remains in git history and **must still be rotated** (M-18). Original finding: the module docstring of `auth.py` contains an example line `SITE_PASSWORD=...` with what appears to be the **real shared password in clear text**, and it has been in git history since commit `1914c2e` (the repository has an `origin` remote on GitHub). Treat that password as exposed: rotate it, change the docstring, and consider the history public. I have deliberately not repeated the value here.

---

## E. Data sources and source-of-truth policy

### E.1 Source-by-source

| Source | Is it integrated? | Role |
|---|---|---|
| Audited **Annual Report PDF** | Yes - primary | Primary source for every statement-based ratio (Balance Sheet, P&L, Cash Flow, notes). Downloaded from BSE then NSE, or uploaded |
| Consolidated statements | Yes | Default basis. Chosen first whenever the filing has them |
| Standalone statements | Yes | Used only when the filing has no consolidated statements, **and for banks** (policy I: RBI schedules exist only at the regulated-entity level) |
| **NSE XBRL** results | Yes (`tools/nse_xbrl.py`) | Machine-tagged audited results; fallback/cross-source in the automatic pipeline and the structured source for an *uploaded* XBRL in manual mode. NSE's annual listing was ~1.5 years stale in July 2026 |
| **BSE** filings | Yes, as a document locator (scrip code, Annual Report PDF, segment results PDF) | Locator and PDF source - not a structured numeric API |
| **Shareholding Pattern** filing | Yes | Source of Promoter Pledge % (Sr 67) and Free Float % (Sr 68): uploaded filing in manual mode, NSE endpoint otherwise (secondary -> `needs_review`) |
| Other company disclosures (insider trading, corporate actions, governance, BRSR, concalls, credit ratings, investor presentations) | Yes, for **qualitative** analysis only | Not used by the 68 ratios |
| **Screener.in** | Yes, but **outside the ratio path** | `tools/screener_scraper.py`: shareholding history, peers, concall links, "moat" fundamentals and the legacy research agent. `ratio_contract` / `fundamental_fact_store` do not read it. Audit documents quote Screener only as an *external comparison* |
| **Dhan** | **No** - no integration found anywhere in the code | Do not describe as integrated |
| **Angel One** SmartAPI | Yes | Live quote (`tools/market_price.py`) for every price-dependent ratio and the live chart; historical 5-minute/daily bars for the forecast package |
| **Yahoo Finance (yfinance)** | Yes | Fallback live quote; weekly price history for Beta (Sr 66); live-chart fallback; the legacy agent |
| Axis Direct RAPID, Upstox, Zerodha Kite | Scaffolding only (Axis client for live chart in UAT; Upstox "testing only - not wired into the app" per `.env.example`; Kite login helper) | Not part of ratio calculation |
| CRISIL, commodity-price, concall sources | Yes, qualitative modules | Not part of the 68 ratios |
| Groq / OpenRouter LLMs | Code present, **disabled** | No calculation ever depended on them |

**Primary extraction:** Annual Report (and uploaded XBRL in manual mode). **Validation:** identity checks inside the fact store; cross-checks such as the bank's own disclosed NIM (gap > 0.75 pp -> `needs_review`); manual comparison with Screener during audits. **Market-dependent metrics:** the live price from Angel One (yfinance fallback).

### E.2 Why Screener or Dhan must not automatically override audited statements

* The audited filing is the legally filed source; aggregators re-derive and re-label it (Screener's "OPM %" is operating profit **before depreciation and excluding other income**; Navrist's Sr 15 is EBIT margin after depreciation, other income included - a different quantity. Screener "Working Capital Days 108" uses an undisclosed definition that cannot be reproduced from the statements; Screener ROCE uses equity + borrowings as capital employed).
* Aggregators silently choose perimeter (whole-entity vs owners), period and basis. In the ANURAS audit Screener's net profit (222.199) is the *whole-entity* PAT; Navrist's NPM uses owners' PAT (170.121) by policy.
* A gap against Screener is therefore first treated as a **definition difference** (compare on the same basis), and only becomes an extraction bug if inputs disagree on the same basis (e.g. Screener Borrowings 1,867 = Navrist Total Debt 1,867.49 - inputs agree).
* If an aggregator is ever used as a fallback it must be flagged as secondary and `needs_review`; the DPS fallback from Screener (commit `1cf8562`) is not present in the current contract path.

### E.3 The rules, and where they are implemented

| Topic | Rule | Status in code |
|---|---|---|
| **Financial year vs TTM** | Fundamental ratios use **fiscal-year** annual-report figures (FY = year ending 31 March of that calendar year, e.g. FY2026). No trailing-twelve-month calculation exists in the contract path (I searched `ratio_contract.py`, the fact store and the extractor: no TTM logic) | Implemented (FY only). TTM = future enhancement |
| **Consolidated vs standalone** | Consolidated first; standalone only when no consolidated statements exist; banks use standalone; the basis is stamped on every fact and result; a result never mixes bases | Implemented and tested |
| **Parent shareholders vs NCI** | `perimeter` is stored per fact. Owners' basis: ROE, EPS ratios, BVPS, P/B, payout, NPM, ROA (by policy). Whole-entity basis: D/E, financial leverage, ROIC, OCF/Net Profit, Beneish TATA | Implemented (policies O, W); mixed perimeters are deliberate and documented |
| **Reporting units** | Converted to Rs Crore from the unit declared on the statement's own page (crore, lakh, million, thousand; the plural "millions" bug fixed in `5d9bf57`; a unit footnote far below a table is honoured; bank figures declared in Rs '000 are converted) | Implemented; one known weak spot: a share count printed in crore (TITAN) was recorded as rounded in the final-validation record - verify |
| **Missing data** | `insufficient_data` / `not_disclosed`; never 0 | Implemented and tested (`test_removing_any_single_input_never_produces_a_zero_ratio`); **one violation found: M-13** |
| **Conflicting source values** | Fact store keeps the primary extraction, records warnings; identity checks flag conflicts to `needs_review`; there is no automatic "vote" between sources | Partly - detection yes, reconciliation manual |
| **Stale data** | Stored rows carry `formula_version`/`breakdown_version`; older rows recalculate on read or return `stale`; the DB fast path has a 12-hour freshness guard; Annual-Report PDFs cache 30 days; extraction caches 90 days | Implemented for code staleness. **Time-based freshness of the source filing is not enforced** (a company's newer Annual Report must be fetched/uploaded) |
| **Restricted cash and bank balances** | Cash Ratio counts cash & equivalents + *unrestricted* other bank balances; lien/earmarked/unclaimed-dividend lines excluded; undisclosed nature flagged; valuation/leverage use cash & equivalents only (policy N) | Implemented and tested; NSE XBRL cross-check not done (M-1) |
| **Market-price timestamps** | The price is a **live quote at calculation time** (`market = {price, source, as_of: "live quote"}`); the source (Angel / yfinance) is recorded. No fiscal-year-end or announcement-date price is used, and a cached ratio row keeps whatever price existed when it was computed | **Gap**: a historical-year ratio (e.g. FY2024 P/E) is computed with today's price - flagged for the roadmap |

---

## F. Manual document-upload workflow

### F.1 From the user's side

1. Open the Document Analysis view and drop the files into the upload slots (`components/ManualUpload.jsx`). The frontend gates **Analyse** until the required files are present.
2. The browser calls `POST /api/v1/documents/analyse` with: `annual_report` (**required**), `xbrl`, `shareholding_pattern`, `additional_filings[]`, and optional qualitative documents (`insider_trading_filings[]`, `corporate_actions_filings[]`, `corporate_governance_report`, `brsr_esg_report`, `investor_presentation`, `earnings_call_transcript`, `credit_rating_report`, `other_supporting_documents[]`) and an optional `symbol`.
3. If no symbol is given the company is detected **from the Annual Report itself**; the resolved symbol is returned and the dashboard opens (`/api/v1/document-analysis/run`, `/api/v1/document-analysis/{symbol}`).
4. A single missing qualitative document can be added later from its card (`POST /api/v1/documents/{symbol}/add-supporting`), which re-runs the qualitative engine. The "search" tool (`POST /api/v1/manual/{symbol}/search`) looks up any term (e.g. "EBIT") in the uploaded document and returns value + page + evidence, or `not_found` - never zero.

### F.2 Supported categories and formats (from the code)

| Category | Format | Used for |
|---|---|---|
| Annual Report | PDF | All statement-based ratios (required) |
| Financial XBRL | `.xml` / `.xbrl` (NSE/BSE) | Structured facts in manual mode, ahead of PDF text where present |
| Shareholding Pattern | `.xml` / `.xbrl` for structured facts (a PDF or other accepted format is only saved: status `saved_not_structured`, so Sr 67/68 are not computed from it) | Sr 67 Pledge %, Sr 68 Free Float %; locked-in flags are read from the filing XML |
| Additional filings, insider trading, corporate actions | PDF | Stored and text-extracted; used by qualitative sub-points |
| Governance, BRSR/ESG, presentation, transcript, credit rating, others | PDF | Qualitative sub-points only |

### F.3 What happens to an uploaded file

1. **Stored** under `uploads/` with a `document_type` and a row in `uploaded_documents` (Supabase) - `save_upload` in `tools/manual_document_pipeline.py`.
2. **Parsed**: the Annual Report's page text is written to `cache/ar_text/{SYMBOL}_{FY}.json` and `cache/manual_docs_text`, the PDF bytes to `cache/ar_pdfs` - the *same* caches the automatic pipeline reads, so no per-ratio change was needed.
3. **Facts extracted** by `extract_line_items` (XBRL first when uploaded, then the Annual Report) through the same `_extract_from_pdf` + broad alias fallback the automatic pipeline uses (since 2026-10-08).
4. **Facts normalised** (`get_canonical_facts`) and **identity-checked**; **ratios computed** by `ratio_contract` through `document_analysis_engine.run_fundamental_analysis`; results stored in `fundamental_analysis_results` with `_metadata` (formula version, breakdown, status detail).
5. **Evidence retained**: every input records document, page, method and statement; the breakdown payload is stored with the row and shown in the UI.

### F.4 Missing or ambiguous values; absent requirements

* A value not in the filing is **reported as not found / not disclosed**, never estimated from the web (no live fallback in manual mode). Examples: DSCR when gross principal repayments are not printed -> `insufficient_data`; Beta -> `insufficient_data` (an upload has no price series); Promoter Pledge/Free Float -> need the uploaded shareholding filing.
* If the filing contains an ambiguous figure (e.g. an "Other bank balances" line of unstated nature), it is included **but flagged** `needs_review` with the reason.
* If the uploaded Annual Report cannot be parsed, the API returns 422 with the reason; no partial guess is produced.

### F.5 Interaction with cached data

A re-upload into the same symbol/year slot changes the file's modification time and size, which is folded into the **document identity tag**, so caches keyed on it miss and recompute; a code or formula change does the same through the version numbers ([N](#n-cache-versions-and-data-freshness)). Manual and automatic runs use separate cache keys (the manual flag is part of every key).

### F.6 Limitations (current)

* One company-year per analysis slot; the user must upload the right year.
* A shareholding pattern uploaded as a PDF is stored but not structured, so Promoter Pledge % / Free Float % need the XML/XBRL version.
* Scanned (image-only) PDFs without a text layer cannot be read (no OCR is used).
* A PDF whose currency glyph is mapped to a letter (e.g. rupee printed as "H") can defeat text scanners that look for "Rs/₹/INR" - this is the cause of M-13.
* Quality varies by filer layout: the 133-filing scan (historical) found 20 unreadable automatically and 29% failing an accounting identity; all are flagged, none root-fixed.
* Qualitative sub-points beyond those built (B.9) have no extractor.


---

## G. All 68 financial ratios

**How to read this section.** Numbering, names and "approved formula" come from `tools/fundamental_ratio_registry.py` (the in-repo transcription of the approved
specification; see the caveat in [`FINANCIAL_RATIO_AUDIT.md`](docs/FINANCIAL_RATIO_AUDIT.md) - the original workbook is not in the repository). The *actual* implementation text
for each ratio is in `tools/ratio_contract.py::SPEC` and is reproduced per ratio in the audit file, together with the missing-data behaviour, tests and the Screener comparison. The "Status"
column is the stricter status of the audit file: **no ratio has been source-audited across every company**; PASS means "ANURAS FY2026 audit passed *and* no known open extraction defect affects its inputs".

Differences between implementation and the approved text (all documented, none silently rewritten):

| Sr | Approved text | Implementation | State |
|---|---|---|---|
| 3 / 4 | Net **credit** sales | Revenue from operations (credit sales are never disclosed); always `needs_review` | Deliberate deviation, open by design |
| 5 | Net purchases | Purchases note line + stock-in-trade; flagged proxy (cost of materials) when absent | Deliberate, flagged |
| 12 | (Cash + Cash Equivalents) / Current Liabilities | Adds *unrestricted* other bank balances (policy N) | User-directed extension; unresolved against the original sheet |
| 17 / 16 | Net Income | Owners' profit (policy B) | Approved policy |
| 20 / 23 | Equity / Shareholders' Equity | Total equity **including NCI** (registry text edited, uncommitted) | Approved policy W |
| 24 / 28 | EPS | Basic EPS attributable to owners | Approved policy |
| 34 | Net Operating Income | EBITDA proxy; gross repayments required | Deliberate, flagged |
| 44 | Variable costs | Estimated proxy, never `verified` | Deliberate, open by design |
| 47 | Dividends Paid / Net Profit | Dividends paid **to the company's own shareholders** / owners' PAT | Approved policy A |
| 55 | Retained earnings | Other-Equity proxy | Deliberate, flagged |
| 57 | SG&A | Other expenses proxy | Deliberate, flagged |
| 1, 8, 15, 29, 31, 33, 51, 52 | (changed by later decisions) | Working-tree registry follows the decisions; `HEAD` registry still shows the 2026-10-07 text | See B.12 |


### G.1 Efficiency and activity ratios

| Sr | Ratio | Approved formula (registry) | In plain English | Required inputs and where they come from | Key calculation rules | Known limitations | Individually audited? | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | Inventory Turnover | Cost of Goods Sold ÷ Average Inventory | How many times a year the stock of goods is used up (sold) - higher means stock moves faster. | COGS (materials consumed + stock-in-trade purchases + inventory change), inventory (current and prior year) - P&L and Balance Sheet. | COGS numerator since formula version 2026.10.7 (earlier Net Sales basis retired). Zero/negative COGS -> insufficient_data. Limit: acquisition-year balance sheets are flagged needs_review. | Acquisition-year distortion; COGS for service companies is not defined (not_disclosed). | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 2 | Inventory Days | 365 ÷ Inventory Turnover | Average number of days stock sits before it is used/sold (365 / turnover). | Sr 1. | Uses unrounded turnover. Inherits Sr 1's status. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 3 | Receivables Turnover | Net Credit Sales ÷ Average Accounts Receivable | How many times a year customers' unpaid bills are collected. | Revenue from operations (proxy for net credit sales), trade receivables (current and prior) - P&L, Balance Sheet. | Net credit sales are never disclosed, so revenue is a proxy -> always needs_review. | Proxy numerator. | ANURAS FY2026 single-filing audit: NEEDS REVIEW. Not source-audited across companies. | **NEEDS REVIEW** |
| 4 | Debtor Days | 365 ÷ Receivables Turnover | Average days customers take to pay (365 / receivables turnover). | Sr 3. | Inherits Sr 3's proxy warning. | Proxy numerator. | ANURAS FY2026 single-filing audit: NEEDS REVIEW. Not source-audited across companies. | **NEEDS REVIEW** |
| 5 | Payables Turnover | Net Purchases ÷ Average Accounts Payable | How many times a year the company pays its suppliers. | Purchases (note 'Purchases during the year' + stock-in-trade purchases; flagged proxy: cost of materials), trade payables (current and prior) - P&L/notes, Balance Sheet. | Falls back to cost of materials consumed (flagged, confidence 0.8) when the note has no purchases line. | Purchases may be a proxy. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 6 | Days Payable | 365 ÷ Payables Turnover | Average days the company takes to pay suppliers (365 / payables turnover). | Sr 5. | Inherits Sr 5. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 7 | Asset Turnover | Net Sales ÷ Average Total Assets | Sales produced per rupee of total assets. | Revenue, total assets (current and prior). | Averages opening and closing assets. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 8 | Working Capital Turnover | Net Sales ÷ Average Working Capital (Current Assets − Current Liabilities) | Sales produced per rupee of working capital (short-term assets minus short-term liabilities). | Revenue, current assets, current liabilities (current and prior year). | Authoritative average working capital (corrected 2026.10.8); closing WC only if the prior year is missing (flagged); negative average WC withheld. | Same as Sr 10. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **NEEDS REVIEW** |
| 9 | Cash Conversion Cycle | DSO + DOH − DPO | Days between paying for stock and getting paid by customers: debtor days + inventory days - payable days. | Sr 4, Sr 2, Sr 6. | Inherits the receivables proxy; Inventory Days now COGS-based. | Inherits proxies. | ANURAS FY2026 single-filing audit: NEEDS REVIEW. Not source-audited across companies. | **NEEDS REVIEW** |
| 30 | Fixed Asset Turnover | Net Sales ÷ Average Net Fixed Assets (PPE + ROU + CWIP + Intangibles) | Sales produced per rupee of fixed assets. | Revenue, net fixed assets (PPE + ROU + CWIP + intangibles; current and prior). | Goodwill excluded. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 31 | Working Capital Days | (Average Working Capital ÷ Revenue) × 365 | How many days of sales are tied up in working capital. | Revenue, working capital (current and prior). | Average working capital. | Same as Sr 10. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **NEEDS REVIEW** |
| 32 | Receivables-to-Payables Ratio | Trade Receivables ÷ Trade Payables | Customer receivables compared with supplier payables. | Trade receivables, trade payables. | Closing balances. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |

### G.2 Liquidity ratios

| Sr | Ratio | Approved formula (registry) | In plain English | Required inputs and where they come from | Key calculation rules | Known limitations | Individually audited? | Status |
|---|---|---|---|---|---|---|---|---|
| 10 | Current Ratio | Current Assets ÷ Current Liabilities | Can short-term assets cover short-term liabilities? | Total current assets, total current liabilities. | Statement subtotals must pass ledger identity checks. | Open: current-assets/liabilities subtotal misread on some filings (L&T, Asian Paints, Bharti Airtel). | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **NEEDS REVIEW** |
| 11 | Quick Ratio | (Current Assets − Inventory) ÷ Current Liabilities | Same, but ignoring inventory (harder to turn into cash quickly). | Total current assets, inventory, total current liabilities. | Same. | Same as Sr 10. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **NEEDS REVIEW** |
| 12 | Cash Ratio | (Cash + Cash Equivalents) ÷ Current Liabilities | Can cash (and free bank deposits) alone cover short-term liabilities? | Cash & cash equivalents, unrestricted other bank balances (Notes), total current liabilities. | Deviation from the registry text: adds *unrestricted* other bank balances (policy N). Restricted (lien, unclaimed dividend, margin money) excluded; unstated nature included but flagged. | Open: NSE XBRL cross-check not done; unstated 'Deposit account' lines are included but flagged. | ANURAS FY2026 single-filing audit: NEEDS REVIEW. Not source-audited across companies. | **NEEDS REVIEW** |
| 13 | Working Capital | Current Assets − Current Liabilities | Short-term assets minus short-term liabilities, in Rs Crore. | Total current assets, total current liabilities. | Closing balance. | Same as Sr 10. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **NEEDS REVIEW** |

### G.3 Profitability ratios

| Sr | Ratio | Approved formula (registry) | In plain English | Required inputs and where they come from | Key calculation rules | Known limitations | Individually audited? | Status |
|---|---|---|---|---|---|---|---|---|
| 14 | Gross Profit Margin | Gross Profit ÷ Revenue | Share of revenue left after the direct cost of goods. | Revenue, COGS. | COGS is materials-based; labour/conversion costs are not in COGS. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 15 | EBIT Margin % | Operating Profit (EBIT) ÷ Revenue | Operating profit (after depreciation, before interest and tax) as a share of revenue. Not Screener's OPM %. | Profit before tax, finance costs, revenue. | EBIT = PBT + finance costs (other income included). Different from Screener OPM %. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 16 | Net Profit Margin | Net Income ÷ Revenue | Share of revenue that ends up as profit for the company's own shareholders. | Owners' profit after tax, revenue. | Owners' profit by policy (PERIMETER_POLICY). Whole-entity NPM is a different number. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 17 | Return on Assets (ROA) | Net Income ÷ Average Total Assets | Profit earned per rupee of average assets. | Owners' profit after tax, total assets (current and prior). | Owners' profit over 100% consolidated assets - deliberate perimeter mix, flagged when NCI is material. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 18 | ROE % | Net Income ÷ Average Shareholders' Equity | Profit earned per rupee of the owners' average equity. | Owners' profit after tax, owners' equity (current and prior). | Never calculated on negative equity. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 19 | ROCE % | EBIT ÷ Average Capital Employed | Operating profit earned per rupee of capital employed (total assets minus current liabilities). | EBIT, total assets, total current liabilities (current and prior). | Capital employed = total assets - total current liabilities (average). | Same as Sr 10. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **NEEDS REVIEW** |
| 42 | Return on Invested Capital (ROIC) | NOPAT ÷ Invested Capital | After-tax operating profit per rupee of capital invested in the business. | EBIT, tax rate, total debt, total equity incl. NCI, cash. | NOPAT = EBIT x (1 - effective tax rate); invested capital = debt + total equity - cash. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 43 | Tax % | Tax Expense ÷ Profit Before Tax | Share of pre-tax profit paid as tax. | Tax expense, profit before tax. | Continuing-operations PBT. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 44 | Contribution Margin | (Revenue − Variable Costs) ÷ Revenue | Share of revenue left after variable costs (an estimated proxy - see limits). | Revenue, estimated variable costs (goods cost + direct/volume-linked expenses). | Always an estimated proxy (needs_review, confidence 0.6); unavailable when only goods cost can be identified. Never 'verified'. | Proxy. | ANURAS FY2026 single-filing audit: NEEDS REVIEW. Not source-audited across companies. | **NEEDS REVIEW** |

### G.4 Leverage and coverage ratios

| Sr | Ratio | Approved formula (registry) | In plain English | Required inputs and where they come from | Key calculation rules | Known limitations | Individually audited? | Status |
|---|---|---|---|---|---|---|---|---|
| 20 | Debt-to-Equity Ratio | Total Debt ÷ Total Equity (incl. NCI) | Borrowings relative to total equity. | Total debt, total equity incl. NCI. | Total equity incl. NCI (debt is consolidated at 100%). Debt includes leases (basis 1). | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 21 | Debt Ratio | Total Debt ÷ Total Assets | Share of total assets that is financed by debt. | Total debt, total assets. | Same debt definition. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 22 | Interest Coverage Ratio | EBIT ÷ Interest Expense | How many times operating profit covers interest cost. | EBIT, finance costs. | Finance costs gross (not net of interest income). | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 23 | Financial Leverage Ratio | Average Total Assets ÷ Average Total Equity (incl. NCI) | How many rupees of assets each rupee of equity supports (average assets / average equity). | Total assets, total equity incl. NCI (current and prior). | Average total equity incl. NCI. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 33 | Net Debt/EBITDA | (Total Debt − Cash) ÷ EBITDA (EBIT + D&A) | Years of EBITDA needed to repay net debt. | Total debt, cash, EBITDA. | Cash = cash & equivalents only (bank deposits not netted). Net-cash companies -> not_applicable. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 34 | Debt Service Coverage Ratio (DSCR) | Net Operating Income (EBITDA proxy) ÷ (Gross Principal Repayment + Interest Due) | Can operating income cover principal repayments plus interest? | EBITDA, finance costs, gross principal repayments (borrowings + lease). | EBITDA is a flagged proxy for net operating income; unavailable if gross repayments are not disclosed. | Gross principal repayments are rarely disclosed -> usually insufficient_data. | ANURAS FY2026 single-filing audit: NEEDS REVIEW. Not source-audited across companies. | **NEEDS REVIEW** |

### G.5 Valuation ratios

| Sr | Ratio | Approved formula (registry) | In plain English | Required inputs and where they come from | Key calculation rules | Known limitations | Individually audited? | Status |
|---|---|---|---|---|---|---|---|---|
| 24 | Stock P/E | Market Price per Share ÷ Basic EPS (owners) | Price paid per rupee of annual earnings per share. | Live share price, basic EPS (owners). | Live price at calculation time, FY EPS. Not-meaningful when EPS <= 0. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 25 | Price-to-Book (P/B) | Market Price per Share ÷ Book Value per Share | Price relative to the accounting value of each share. | Share price, BVPS (Sr 46). | Owners' BVPS. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 26 | Price-to-Sales (P/S) | Market Cap ÷ Total Revenue | Market value relative to annual sales. | Share price x shares outstanding, revenue. | Revenue from operations. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 28 | Earnings Yield | EPS ÷ Market Price per Share | Earnings per share as a percentage of the share price (inverse of P/E). | Basic EPS, share price. | Unrounded EPS / price. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 29 | Enterprise Value/EBITDA | (Market Cap + Debt − Cash) ÷ EBITDA (EBIT + D&A) | Enterprise value (what the whole business is priced at) relative to EBITDA. | Market cap, total debt, cash & equivalents, EBITDA (EBIT + D&A). | One EV: market cap + total debt - cash & equivalents. NCI not added (policy H); a labelled reference 'EV incl. NCI' is carried separately. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 46 | Book Value per Share (BVPS) | Total Equity ÷ Number of Equity Shares Outstanding | Owners' equity per share outstanding. | Owners' equity, shares outstanding. | Owners' equity / closing shares. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 50 | PEG Ratio | Price-to-Earnings ÷ EPS Growth Rate | P/E relative to EPS growth - is growth being paid for? | Sr 24, Sr 45. | Not meaningful when growth <= 0. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 51 | EV/Sales | Enterprise Value (Mkt Cap + Debt − Cash) ÷ Revenue | Enterprise value relative to sales. | EV (as Sr 29), revenue. | Same EV as Sr 29. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 52 | EV/FCF | Enterprise Value (Mkt Cap + Debt − Cash) ÷ Free Cash Flow | Enterprise value relative to free cash flow. | EV, Sr 36. | Not meaningful when FCF <= 0. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 53 | Price/Cash Flow | Market Capitalisation ÷ Operating Cash Flow | Market capitalisation relative to operating cash flow. | Market cap, operating cash flow. | - | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 54 | Graham Number | √(22.5 × EPS × Book Value per Share) | Benjamin Graham's rule-of-thumb ceiling price: sqrt(22.5 x EPS x book value per share). | Basic EPS (owners), BVPS. | Owners' EPS and BVPS (same fiscal year). | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |

### G.6 Cash-flow ratios

| Sr | Ratio | Approved formula (registry) | In plain English | Required inputs and where they come from | Key calculation rules | Known limitations | Individually audited? | Status |
|---|---|---|---|---|---|---|---|---|
| 35 | Cash Flow Coverage Ratio | Operating Cash Flow ÷ Total Debt | Operating cash flow relative to total debt. | Operating cash flow, total debt. | Closing total debt. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 36 | Free Cash Flow | Operating Cash Flow − Capital Expenditure | Cash left after maintenance and growth spending: operating cash flow minus capex. | Operating cash flow, capex (PPE + intangibles purchases). | Gross capex, no disposal proceeds netted. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 37 | FCF Yield | Free Cash Flow ÷ Market Capitalisation | Free cash flow as a percentage of market capitalisation. | Sr 36, market cap. | Not meaningful as a normal multiple when FCF is negative. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 38 | FCF Margin | Free Cash Flow ÷ Revenue | Free cash flow as a percentage of revenue. | Sr 36, revenue. | - | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 39 | Operating Cash Flow Ratio | Operating Cash Flow ÷ Current Liabilities | Operating cash flow relative to short-term liabilities. | Operating cash flow, total current liabilities. | Closing current liabilities. | Same as Sr 10. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **NEEDS REVIEW** |
| 40 | Capex Intensity | Capital Expenditure ÷ Revenue | Share of revenue spent on capital expenditure. | Capex, revenue. | Gross capex. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 41 | OCF/Net Profit | Operating Cash Flow ÷ Net Profit (whole entity) | How much cash the business generated per rupee of reported profit. | Operating cash flow, total (whole-entity) profit after tax. | Both whole-entity. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |

### G.7 Growth and dividend ratios

| Sr | Ratio | Approved formula (registry) | In plain English | Required inputs and where they come from | Key calculation rules | Known limitations | Individually audited? | Status |
|---|---|---|---|---|---|---|---|---|
| 27 | Dividend Yield % | Dividend per Share ÷ Market Price per Share | Annual dividend per share as a percentage of the share price. | Dividend per share declared for the FY, share price. | DPS = interim/special + final declared FOR the fiscal year; unknown is never 0. Price is a live quote, not the FY-end price. | Open: dividends printed with a non-rupee glyph (Bharti Airtel) can become 0; price timing. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **NEEDS REVIEW** |
| 45 | EPS Growth Rate | (Current Year EPS ÷ Prior Year EPS) − 1 | Year-on-year growth in earnings per share. | Basic EPS (owners), current and prior year. | Owners' EPS; Ind AS 33 single printed line otherwise. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 47 | Dividend Payout % | Dividends Paid to the Company's shareholders ÷ Net Profit (owners) | Share of the owners' profit that was paid out as cash dividends. | Dividends paid (cash-flow statement, split owners vs minorities), owners' profit. | Paid in the year to the company's own shareholders / owners' PAT (policy A); declared-for-year payout carried as a reference only. Flagged when the owners/NCI split cannot be made. | Open: same dividend risk; owners/NCI split unavailable on many filings (needs_review). | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **NEEDS REVIEW** |
| 48 | Retention Ratio | 1 − Dividend Payout Ratio | Share of profit kept in the business (100% minus payout). | Sr 47. | 100 - payout; inherits status. | As Sr 47. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **NEEDS REVIEW** |
| 49 | Sustainable Growth Rate | Return on Equity × Retention Ratio | Growth the company could fund from retained profit alone (ROE x retention). | Sr 18 (ROE), Sr 48. | ROE x retention; inherits both statuses. | As Sr 47. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **NEEDS REVIEW** |

### G.8 Composite financial-strength and manipulation-risk indicators

| Sr | Ratio | Approved formula (registry) | In plain English | Required inputs and where they come from | Key calculation rules | Known limitations | Individually audited? | Status |
|---|---|---|---|---|---|---|---|---|
| 55 | Altman Z-Score | 1.2(WC/TA) + 1.4(RE/TA) + 3.3(EBIT/TA) + 0.6(MktCap/TL) + 1.0(Sales/TA) | Bankruptcy-risk score combining five ratios (higher is safer). | Working capital, retained earnings (Other-Equity proxy), EBIT, market cap, total liabilities, revenue, total assets. | Retained earnings is an Other-Equity proxy -> always needs_review. | Proxy for retained earnings. | ANURAS FY2026 single-filing audit: NEEDS REVIEW. Not source-audited across companies. | **NEEDS REVIEW** |
| 56 | Piotroski F-Score | Sum of 9 binary fundamental-strength tests (0-9 scale) | 0-9 score of nine yes/no fundamental-strength tests. | Two years of: profit, OCF, total assets, long-term borrowings, current ratio, shares, gross margin, asset turnover. | Reported only when all nine tests can be evaluated, else insufficient_data. | Same as Sr 10; needs two clean years. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **NEEDS REVIEW** |
| 57 | Beneish M-Score | -4.84 + 0.92·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI + 0.115·DEPI - 0.172·SGAI + 4.679·TATA - 0.327·LVGI | Earnings-manipulation risk score from eight indices (higher/less negative = more suspect). | Two years of: receivables, revenue, gross profit, depreciation, PPE, other expenses (SG&A proxy), total debt, OCF, profit. | SG&A proxied by Other expenses -> needs_review. | Proxy for SG&A. | ANURAS FY2026 single-filing audit: NEEDS REVIEW. Not source-audited across companies. | **NEEDS REVIEW** |

### G.9 Banking-specific ratios

| Sr | Ratio | Approved formula (registry) | In plain English | Required inputs and where they come from | Key calculation rules | Known limitations | Individually audited? | Status |
|---|---|---|---|---|---|---|---|---|
| 58 | Net Interest Margin (NIM) | (Interest Income − Interest Expense) ÷ Average Interest-Earning Assets | Bank's spread between interest earned and paid, relative to earning assets. | Bank statements: interest earned/expended, balance-sheet earning assets (current and prior). | Dedicated RBI-format extraction, identity-gated, plausibility-bounded; bank's disclosed NIM used as cross-check. | See audit reference. | ANURAS FY2026 single-filing audit: NEEDS REVIEW. Not source-audited across companies. | **NEEDS REVIEW** |
| 59 | CASA Ratio | (Current Account + Savings Account Deposits) ÷ Total Deposits | Share of a bank's deposits held in current and savings accounts (cheap funding). | Schedule 3 deposit split. | Bank only; NBFCs not applicable. | See audit reference. | ANURAS FY2026 single-filing audit: NEEDS REVIEW. Not source-audited across companies. | **NEEDS REVIEW** |
| 60 | Gross NPA % | Gross Non-Performing Assets ÷ Gross Advances | Share of a bank's loans that are non-performing (gross). | Bank's RBI asset-quality disclosure. | Disclosed figure used, never rebuilt. | NBFC asset-quality figures often not found (Poonawalla). | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 61 | Net NPA % | Net Non-Performing Assets ÷ Net Advances | Share of loans non-performing after provisions (net). | Same. | Same. | As Sr 60. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 62 | Provision Coverage Ratio (PCR) | Total Provisions Held ÷ Gross Non-Performing Assets | How much of the bad loans is covered by provisions. | Same. | Same. | As Sr 60. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 63 | Capital Adequacy Ratio (CRAR) | (Tier I Capital + Tier II Capital) ÷ Risk-Weighted Assets | Bank capital relative to risk-weighted assets (regulatory capital cushion). | Basel III capital table. | Disclosed or computed from the Basel III table. | As Sr 60. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 64 | Credit-to-Deposit Ratio | Total Advances ÷ Total Deposits | Loans relative to deposits. | Advances, deposits. | Banks only. | See audit reference. | ANURAS FY2026 single-filing audit: NEEDS REVIEW. Not source-audited across companies. | **NEEDS REVIEW** |
| 65 | Cost-to-Income Ratio | Operating Expenses ÷ (Net Interest Income + Other Income) | Operating costs relative to operating income for a bank. | Operating expenses, net interest income, other income. | Banks and NBFC variants. | See audit reference. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |

### G.10 Market and shareholding metrics

| Sr | Ratio | Approved formula (registry) | In plain English | Required inputs and where they come from | Key calculation rules | Known limitations | Individually audited? | Status |
|---|---|---|---|---|---|---|---|---|
| 66 | Beta | Covariance(Stock Returns, Market Returns) ÷ Variance(Market Returns) | How strongly the stock's weekly returns move with the Nifty 50 (market sensitivity). | Weekly closing prices of the stock and Nifty 50 for 2 years (not in any filing). | Manual-upload mode reports insufficient_data (no price series in a filing). Needs >= 52 observations. | Not computable in manual mode. | ANURAS FY2026 single-filing audit: NEEDS REVIEW. Not source-audited across companies. | **NEEDS REVIEW** |
| 67 | Promoter Pledge % | Pledged Promoter Shares ÷ Total Promoter Shareholding | Share of the promoters' holding that is pledged as loan collateral. | Shareholding Pattern: pledged and total promoter shares. | Filing-disclosed counts -> verified; inferred zero from NSE dataset -> needs_review. | Primary-source pledge data not always verifiable. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |
| 68 | Free Float % | (Total Shares − Promoter Holding − Locked-in Shares) ÷ Total Shares | Share of shares available to the public (not held by promoters or locked in). | Shareholding Pattern: promoter shares, locked-in shares, total shares. | Proxy (needs_review) unless the filing states locked-in shares. | Proxy when locked-in shares are undisclosed. | ANURAS FY2026 single-filing audit: PASS. Not source-audited across companies. | **PASS** |


### G.11 Key concepts in plain language

* **Average vs closing balance.** A profit or sales figure covers a whole year, but a balance (inventory, assets, equity) is a snapshot. Turnover and return ratios therefore divide by the **average of opening and closing** balances. Example: ANURAS FY2026 inventory 1,774.752 Cr (closing) and 1,451.502 Cr (opening) -> average 1,613.127 Cr; COGS 1,323.256 Cr / 1,613.127 = **0.82 times**.
* **Days ratios.** A "days" ratio is 365 divided by a turnover: 365 / 0.82 = 445 days of inventory. The turnover must be the *unrounded* number.
* **Cash conversion cycle.** Debtor days + inventory days - payable days: how many days cash is tied up between paying suppliers and collecting from customers.
* **Owners vs whole entity.** A group's consolidated profit includes the share belonging to outside (minority) shareholders (NCI). Ratios about what **owners** earn (ROE, EPS, P/E) use owners' profit; ratios about the **whole business** (debt vs total equity, cash flow vs total profit) use the whole-entity figures.
* **Enterprise value.** What the whole business costs to buy: market value of shares + debt - cash. It is compared with EBITDA, sales and free cash flow.
* **Composite scores (Altman, Piotroski, Beneish).** Fixed recipes combining many ratios; here they contain flagged proxies, so they are never "verified".

---

## H. Important financial calculation policies

Each policy below was checked against the code on 2026-10-09 (`ratio_contract.py` v`2026.10.13`) and its tests.

| # | Policy | Implemented? | Evidence / remaining question |
|---|---|---|---|
| 1 | Inventory Turnover = **COGS / average inventory** | **Implemented** | `_r_inventory_turnover`; `TestInventoryTurnoverUsesCogsAndDependentsFollow`; contract decision E. *History:* the 2026-10-07 commit `6d348dc` had Net Sales; the owner reversed it |
| 2 | Days Inventory Outstanding derived from Inventory Turnover (365 / unrounded turnover) | **Implemented** | `PARENTS["days_inventory_outstanding"]`; `test_doh_dso_dpo_ccc_use_raw_turnover` |
| 3 | DSO uses **net credit sales when available**; revenue proxy must be identified | **Partly.** The proxy is implemented and flagged (`needs_review`, confidence <= 0.8, warning text, inherited by CCC). The "when available" branch **does not exist** - the code never looks for a credit-sales figure | Open: decide whether to search for a credit-sales disclosure or accept the proxy permanently (M-6) |
| 4 | DPO = purchases / average trade payables | **Implemented** (365 / payables turnover). Purchases = note "Purchases during the year" + stock-in-trade purchases; cost of materials consumed is a flagged 0.8-confidence proxy | `_r_payables_turnover`; ANURAS audit: lineage OK |
| 5 | CCC depends on DSO, inventory days and DPO | **Implemented** | `_r_ccc`; inherits the worst parent status |
| 6 | EBIT Margin is not Screener's Operating Profit Margin | **Implemented** (label "EBIT Margin %"; internal id `operating_profit_margin` unchanged; legacy label map) | `test_sr15_is_labelled_as_what_it_computes` |
| 7 | ROE, NPM, ROA use a consistent, explicit perimeter | **Implemented as a documented policy** - ROE owners/owners; NPM and ROA owners' profit over 100% revenue/assets (`PERIMETER_POLICY`, flagged when NCI is material). The mix is deliberate, not a bug | `TestEquityBasisPolicy`, `TestOwnersVersusWholeEntityPerimeter` |
| 8 | ROCE follows the approved capital-employed method | **Implemented** as EBIT / average (total assets - total current liabilities). *No separate approval record was found beyond the registry text*; Screener's ROCE uses a different capital base | Confirm with owner |
| 9 | Dividend events attributed to the correct fiscal year | **Implemented** - by the year the sentence says the dividend is *for*; date/label only as fallback; a prior-year final merely paid this year is never added | `TestDividendFiscalYearAttribution`; policy P |
| 10 | Dividend Yield uses the correct period's DPS **and a time-appropriate price** | **Half implemented.** DPS is correct. The price is a **live quote at calculation time** (`as_of: "live quote"`) - not the price at the fiscal-year end or declaration | Open: historical-year yields use today's price; needs a dated price series (roadmap) |
| 11 | Payout, Retention, Sustainable Growth numerator/denominator policy | **Implemented** (policy A): dividends *paid* to the company's own shareholders / owners' PAT; Retention = 100 - payout; SGR = ROE x retention; estimates flagged; unknown -> unavailable | `TestDividendPayoutPerimeter`. Residual: when the owners/NCI split cannot be made the ratio is `needs_review` (11 of 17 companies in the recorded validation) |
| 12 | Cash Ratio and valuation cash follow different documented definitions | **Implemented** (policy N): Cash Ratio = cash + *unrestricted* other bank balances; Net debt, EV, EV/EBITDA, EV/Sales, EV/FCF use cash & equivalents only; no shared code path | `TestCashRatioRestrictedBalancePolicy.test_net_debt_and_ev_do_not_move_with_the_cash_ratio_policy`. Open: NSE XBRL cross-check (M-1); *new* concern M-14 |
| 13 | One approved EV definition for Sr 29/51/52 | **Implemented** (policy H, v2026.10.9): market cap + total debt - cash & equivalents; NCI never added; a separately labelled `reference_ev_incl_nci` is carried for consolidated entities with NCI and feeds nothing | `TestOneEnterpriseValueDefinition` |
| 14 | Working Capital Turnover = Net Sales / **average** working capital | **Implemented** (v2026.10.8); closing WC only when the prior year is missing (flagged); negative average withheld; Sr 31 also average | `TestWorkingCapitalTurnoverIsAverageBased` |
| 15 | Rounding only for display | **Implemented for contract ratios** (`value_raw`; Total Debt and Contribution-Margin intermediates un-rounded in the matrix audit). **Exception:** bank ratios 58-65 use `legacy_breakdown` with 2-dp legs (tolerance flagged) | `TestRoundedValuesNeverFeedCalculations`; ratio_breakdown memo |
| 16 | Missing values never silently become zero | **Implemented and tested generically** (`test_removing_any_single_input_never_produces_a_zero_ratio`) **with two exceptions found while documenting:** M-13 (Bharti Airtel DPS = 0) and M-14 (absent "other bank balances" line contributes 0 to the Cash Ratio as `verified`) | See M |
| 17 | A proxy is never presented as exact | **Implemented** by status (`needs_review`, `estimated`, confidence < 1) and warnings: Sr 3/4, 5, 9, 12, 34, 44, 55, 57, 68. DSCR's EBITDA proxy is flagged | Matrix verdict notes |

---

## I. Initial rework and major bug fixes

Every row is supported by a commit subject, a test, or a contract/validation record. Commit subjects state the root cause the engineer found; I have not re-diagnosed them. "Verification" is what proves the fix exists, **not** that all companies are now correct.

### I.1 Early platform problems (June-July 2026)

| Problem | Root cause | Fix | Affects | Verification |
|---|---|---|---|---|
| Research took 8-9 minutes | Serial blocking I/O, TOTP login per request, graph run on the event loop (record) | Precompute + disk/DB caches; LLM calls later disabled | Whole app | Record *rework-decisions*; ~65 s report after LLM disable (`15447ed`, record). Not re-measured |
| Cache stampede on Annual-Report extraction | Many parallel requests re-parsing the same PDF | Per-(symbol, year) lock (`38b96e6`); wider thread pool (`be0d66b`) | All AR ratios | Commit |
| Header price blank | Field-name mismatch with `/api/quote` (`7996b46`) | Fixed field names | UI | Commit |
| Search missed newly listed stocks (`2dccf49`); wrong BSE scrip-code match (`a2b0615`); company search by name/ISIN/spaces | Curated seed list; loose name matching | Full NSE universe + `companies` master; ranked search (`tools/company_search.py`); BSE name-matching fix | Company identification | `tests/test_company_search.py` (17 tests); `tests/company_search_probe.py` |
| Fabricated fallback data in qualitative analysis (`a075e25`) | Filler values when data missing | Removed; honest "data missing" | Qualitative | Commit; rule now in `CLAUDE.md` |

### I.2 Statement-extraction and attribution errors

| Problem | Root cause | Fix | Ratios / features | Verification |
|---|---|---|---|---|
| ~30x wrong Total Current Assets/Liabilities on split-subtotal filings (`33caf32`) | Subtotal split over lines misread | Subtotal logic fixed | Sr 10-13 and dependants | Commit; **similar misreads still occur (M-2, M-4)** |
| Bharti Airtel (and any "millions"-plural filer) 10x scale error (`5d9bf57`) | `_unit_factor` missed the plural "millions" | Fixed | All values on such filings | Commit; `TestUnitFactor` |
| ROE denominator captured Total Equity **and Liabilities** (`5f6cf9a`) | Wrong row label match | Equity row corrected | Sr 18 | Commit |
| ROCE EBIT silently included Other Income (`003bfb8`); Interest Coverage EBIT likewise and Finance Costs read as a *note number* (`c55197a`) | Row reader took the note column as a figure | EBIT = PBT + finance costs defined; note numbers skipped | Sr 19, 22 | Commits; later generalised in `TestExtractionNoiseRegressions` |
| NCI missed on split-page balance sheets (`33b0902`); lease mis-extraction (`cfd7534`) | Layout variants | Fixed; owners-only vs total equity separated | Sr 20 | Commits |
| Tata Steel OCF/capex wrong (`c4bba15`, `b4e92da`) | Missing label phrasing; substring false positive | Labels widened | Sr 35-41 | Commits |
| Cash-flow section boundary missed "from/(used in)" phrasing (`5ebe825`) | Regex | Fixed + targeted re-derivation | Cash-flow ratios | Commits `bd09e11`, `1320884` |
| Dividend per share missed tabulated notes, e.g. HUL (`198e13c`) | Narrow regex | Table-aware scan | Sr 27 | Commit |
| Standalone BVPS card silently fetched consolidated data (`5d91337`) | Hard-coded `consolidated=True` | Basis honoured | Sr 46 | Commit; later `statement_selector.py` |
| Graham Number mixed fiscal years (`c003b3b`); PEG with near-zero growth (`5eb880b`); Pledge % wrong denominator (`bb3e94d`) | Period mismatch / missing guard / wrong base | Fixed | Sr 54, 50, 67 | Commits |
| Net Debt/EBITDA year probe discarded a real "Net Cash" finding (`9c8e730`) | Probe logic | Fixed | Sr 33, 22 | Commit |
| FCF label claimed "net" capex when no disposal proceeds were found (`12ef9df`, `8121e3a`); Capex Intensity switched to gross capex (`0474e9e`) | Wording / QA methodology | Gross capex, honest wording | Sr 36, 40 | Commits |
| DSCR did not follow the QA specification | Interest basis (commit subject: "per QA spec") | Rewritten to cash-basis interest paid (`3cbc294`); later contract rule: unavailable when gross principal repayments are not disclosed, never rebuilt from net financing flows | Sr 34 | Commit; `TestDscr` |

### I.3 Formula, engine and consistency problems (October 2026)

| Problem | Root cause | Fix | Ratios | Verification |
|---|---|---|---|---|
| **Three engines, three definitions** | Document engine, `nse_xbrl` wrappers and canonical engine each had formulas | `ratio_contract.py` is the only place; others are adapters | All 68 | `test_every_computable_ratio_agrees_in_all_four_paths`, `test_no_wrapper_contains_its_own_formula` |
| Unknown became 0 | Defaults in formulas | Status model; unknown -> unavailable | Dividend, debt, etc. | `TestUnknownIsNeverZero` (two files) |
| Derived ratios "verified" over unverified parents; rounded values reused as inputs | Missing inheritance; display rounding in the data path | Worst-status inheritance; `value_raw` | CCC, DSO..., PEG, SGR, EV/* | `TestStatusPropagation`, `TestRoundedValuesNeverFeedCalculations` |
| Missing dependency between ratios (Retention/SGR on payout; EV ratios on EV) | Each recomputed its own | `PARENTS` graph + `compute_with_parents` | Sr 2, 4, 6, 9, 48-52 | `TestCrossEngineEquality` |
| Silent row-shift in the shared row reader (single-digit decimals, comma-less whole-crore integers such as Titan depreciation 693 read as 5,150, label parentheticals like "Total assets (1+2)") | Row reader heuristics | Reader hardened | Many | `TestRealFilingDefects` |
| NCI read as the equity subtotal; owners' profit read as whole-entity (Reliance, L&T) | Label ambiguity | Perimeter stored per fact | Sr 16-18, 20, 46... | `TestOwnersVersusWholeEntityPerimeter` |
| Bank ratios read from prose lines (Kotak "Advances"), no unit normalisation (ICICI/Kotak in Rs '000) | Text-window reader | `bank_extractor.py` word-coordinate reader + identities | Sr 58-65 | `TestBankExtractorRows`, `TestBankRatios` |
| Lender gating by company-name keywords (a lender without "bank" in its name was mis-gated) | Name heuristic | Gate by **sector** | Sr 58-65, 10-13 | `test_lender_gate_is_sector_based_not_name_based` |
| `not_meaningful` collapsed into `not_disclosed`; pledge 8,174% case; inferred zero pledge shown as verified | Status mapping; no sanity | Preserved; bounds; pledge `needs_review` unless filing-disclosed | Sr 67 etc. | `test_inferred_zero_pledge_is_not_verified` |
| Automatic pipeline returned *no* facts for ANURAS and different `equity` for Maruti, Bata, Zee, Nazara, Airtel, Polycab | `is_manual_mode()` branches in extraction (decision Y) | Branches removed; same path for both modes | Everything | `tests/test_pipeline_parity.py` (20 company-years, 8 diverged -> 0) |
| TCS owners' PAT = 1.0 | Colon in "attributable to: Shareholders of the Company"; note number read as an amount | Matcher and fallback fixed | Sr 16-18, 41, 47 | Parity tests; re-observed 48,553 on 2026-10-09 |
| Stale cached results hid fixes | Cache keys ignored fact-store/extraction changes | `FORMULA_VERSION` + `_EXTRACTION_LOGIC_VERSION` + `EXTRACTION_VERSION` folded into every key | All | `TestCacheKeysFoldEveryVersion`, `test_version_bumps_invalidate_every_cache_key` |
| Incorrect source evidence (cash-flow facts cited the P&L page) | Page attribution | Provenance page fixed | Sr 35-41 | `TestCashFlowProvenancePage` |
| Misleading labels: "OPM %" for EBIT margin; "Graham/EPS growth" breakdown naming the wrong inputs | Naming | "EBIT Margin %"; breakdown names real inputs | Sr 15, 45, 54 | `TestEbitMarginLabel`, `TestBreakdownDisplayAccuracy` |

### I.4 Fixes of the global audit

Listed in [J](#j-recent-global-audit).

---

## J. Recent global audit

The audit ran from formula version `2026.10.7` to `2026.10.13` (record dates 2026-10-08/09; **uncommitted**). Evidence: `tests/test_global_audit_2026_10c.py` (65 test functions), `tests/test_final_validation_regressions.py`, `tests/test_pipeline_parity.py`, the contract's decision tables N-Y, and `docs/ratio_audit_matrix_2026-10.*`.

### J.1 Changes

| Item | What was wrong | What changed | Test evidence |
|---|---|---|---|
| **COGS-based Inventory Turnover** | Used Net Sales (AR definition, `6d348dc`) | COGS = cost of materials + stock-in-trade purchases + changes in inventories; Zero/negative COGS -> insufficient_data; XBRL route also goes through the contract | `TestInventoryTurnoverUsesCogsAndDependentsFollow`; `test_xbrl_inventory_turnover_goes_through_the_contract` |
| **Inventory Days and CCC recomputed** | Followed the old turnover | DIO = 365 / unrounded turnover; CCC = DSO + DIO - DPO | `test_turnover_days_and_ccc_use_cogs` |
| **Cash Ratio / other bank balances** | Cash only, or whole "other bank balances" including restricted amounts | Notes classified line by line: restricted (unclaimed dividend, earmarked, margin money, escrow, bank guarantee, lien-marked deposits) excluded; unrestricted deposits included; unstated nature included but `needs_review`; accepted only if the note total equals the balance-sheet line | `TestCashRatioNumerator`, `TestCashRatioRestrictedBalancePolicy` |
| **Dividend fiscal-year attribution** | An interim dividend declared in FY26 *for FY25* was counted in FY26 | Attribute by the "for the financial year ..." text; date only as fallback | `TestDividendFiscalYearAttribution` |
| **Maruti unit scaling and page-number extraction** (per audit) | Page-number ranges ("431-432") read as figures; unit footnote far below a table ignored; two reference columns before the figures | Row reader and unit logic generalised | `test_page_number_ranges_are_not_figures`, `test_unit_footnote_far_below_the_table_is_honoured`, `test_two_reference_columns_before_the_figures` |
| **ITC note-reference extraction** (per audit) | Lettered/listed note references ("23A, 23B", "26, 15") read as figures; discontinued operations mixed PAT and EPS perimeters (ITC FY25: Rs 15,016 Cr) | References dropped; PAT repaired to continuing operations and flagged (policy M) | `test_lettered_and_listed_note_references_are_not_figures` |
| **Bata dividend extraction** (per audit) | Reported by the audit; the specific failure is not recorded in the repository | Event-level scanner with `target_fy` and `counted` per event | `_scan_dividend_disclosures` tests. *Observed 2026-10-09:* BATAINDIA FY25 DPS 19, yield `verified` |
| **Infosys contents-page extraction** (per audit) | A table-of-contents page (dot leaders) taken as a statement | Contents pages are never statements | `test_table_of_contents_page_is_not_a_statement` |
| **Titan and HUL subtotal extraction** (per audit) | Whole-crore depreciation 693 read as 5,150 (Titan); bare unlabelled subtotal taken from the wrong figures (HUL-style) | Reader and `_find_subtotal_before` fixed | `test_whole_crore_integers_under_1000_do_not_shift_to_the_next_row`, `test_bare_subtotal_comes_from_the_figures_after_the_last_label` |
| **Cost-of-materials caption** | "Cost of materials and components consumed" not matched | Alias added | `test_materials_and_components_caption_is_cost_of_materials` |
| **Balance-sheet identity checks** | Misread subtotals produced confident ratios | `_apply_ledger_integrity` flags (never changes) failing facts and dependants | `TestLedgerIdentitiesFlagMisreadSubtotals` |
| **Fact-store version in cache keys** | A change to fact derivation did not invalidate stored ratios | Key = formula + extraction logic + fact-store version | `TestCacheKeysFoldEveryVersion` |
| **EBIT Margin relabel** | "OPM %" suggested Screener's metric | Label "EBIT Margin %" | `TestEbitMarginLabel` |
| Working Capital Turnover contract | Closing WC "AR alignment" deviated from spec | Average WC (v2026.10.8) | `TestWorkingCapitalTurnoverIsAverageBased` |
| EV methodology | NCI added to EV | Single EV; NCI only as a labelled reference (v2026.10.9) | `TestOneEnterpriseValueDefinition` |
| Equity basis | Implicit mixing | Machine-checked `EQUITY_BASIS` | `TestEquityBasisPolicy` |
| Dividend payout perimeter | Cash-flow dividends include minorities' share | Split by recipient; flagged when not splittable | `TestDividendPayoutPerimeter` |
| 68-row matrix findings (v2026.10.13) | Contribution-margin rounding, Total Debt rounded to 2 dp, Three-Part-Test "not evaluated", pledge/free-float over-flagging, percentages from tagged fractions, capex note | See contract decision X | `TestAuditMatrixFindings`, `TestOtherFinancialLiabilitiesNoteEvaluation` |

*The "what was wrong" text for the per-company extraction items is taken from the regression tests' descriptions (`TestExtractionNoiseRegressions` names Maruti, ITC, Infosys, Titan and Bata as the source of the generic defects); the original audit report is not stored in the repository.*

### J.2 Reported results (HISTORICAL) and observed results

| | Backend | Frontend |
|---|---|---|
| **Historical report (the audit)** | 489 passing tests | 73 passing tests |
| **Observed 2026-10-09 (this document)** | `venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --ignore=tests/universe_scan.py` -> **542 passed, 1 warning, 63 subtests passed in 124.72 s** | `npm test` in `frontend/` -> **73 passed, 0 failed** (7 test files) |

The backend count has grown by 53 since the report; I did not determine which tests were added after it (the file `test_global_audit_2026_10c.py` contains tests for decisions made after the first audit pass, e.g. average WC, single EV, equity basis). Passing tests do **not** prove every financial number is correct ([L.5](#l5-what-passing-tests-do-and-do-not-prove)).

### J.3 ANURAS FY2026: before and after

The audit report itself is not stored in the repository. The "after" values below are the engine's values in `docs/ratio_audit_matrix_2026-10.json`. The "before" values are **my arithmetic from the same matrix inputs**, using the old rule; they are illustrative reconstructions, not figures copied from the audit report.

| Ratio | Before (old rule) | After (engine, v2026.10.13) | Why it moved |
|---|---|---|---|
| Sr 1 Inventory Turnover | 2,365.455 / 1,613.127 = **1.466 x** (Net Sales basis) | **0.8203 x** (COGS 1,323.256 Cr) | Policy E |
| Sr 2 Inventory Days | 365 / 1.466 = **248.9 days** | **444.96 days** | Follows Sr 1 |
| Sr 9 CCC | 130.63 + 248.9 - 187.91 = **191.6 days** | **387.68 days** | Follows Sr 2 |
| Sr 12 Cash Ratio | Cash only 378.069 / 2,615.438 = **0.1446**; or cash + whole other-bank 15.556 = 0.1505 | **0.1477** = (378.069 + 8.260 unrestricted) / 2,615.438; `needs_review` | Policy N: 7.30 Cr restricted/lien excluded; 7.605 Cr "Deposit account" unclassified |
| Sr 8 WC Turnover | Closing WC 2,365.455 / 1,112.07 = **2.127** | **2.5207** (average WC) | Policy F |
| Sr 27 Dividend Yield | If the FY25 interim 0.75 were counted: DPS 2.25 / 1,165 = **0.193 %** | **0.1288 %** (DPS 1.50 = final recommended for FY26) | Policy P |
| Sr 15 | labelled "OPM %" | **17.04 %**, labelled "EBIT Margin %" (Screener's OPM is 22 %, a different quantity) | Label only |
| Sr 47 Dividend Payout | - | **5.02 %** (dividends paid to owners incl. the FY25 interim, 8.54 Cr) ÷ owners' PAT; declared-for-year payout 10.04 % carried as a reference | Policy A |

*Price used by the matrix is a fixed audit price of INR 1,165, not a market price.*

### J.4 Cross-checks of the audit that I re-ran

On 2026-10-09 I re-ran the extraction (no network except what the harness itself opens) on the cached filings with `tests/ratio_regression_probe.py` for 15 company-years; all ran without error. TCS owners' PAT = 48,553 (no longer 1.0); ANURAS FY26 owners' PAT = 170.121 (verified). These are the "observed" values quoted in K and M.

---

## K. Cross-company validation

**Method of the recorded validation** (`tests/final_validation.py`, 17 filings; `tests/universe_scan.py`, 133 filings; `docs/final_validation_2026-10/`): run the real 68-ratio orchestrator on cached filings, then check cross-company *invariants* (68 rows, value <-> status consistency, current formula version, every numeric result has a reconciling breakdown, a derived ratio is never better than its parents) and *accounting identities*. **This verifies internal consistency, not agreement with an external source.** Only ANURAS was compared line-by-line with an independent source (the Annual Report's own printed numbers and Screener). **No claim is made that all 68 ratios were independently verified for every company, and the latest audit did not do so.**

**Why a legitimate formula difference must be separated from an extraction bug.** If Navrist says ROCE 9.1 % and Screener says 7 %, the first question is *definition*: Screener divides EBIT by (equity + borrowings); Navrist divides by (total assets - current liabilities). Recomputing Navrist's inputs on Screener's definition (the audit's "same-basis recompute") shows whether the **inputs** agree. Matching inputs + different outputs = definition difference (document it); different inputs on the same basis = extraction bug (fix at the fact, add a regression test, never patch the displayed ratio).

**Observed 2026-10-09 (contract ratios, automatic pipeline harness, no sector gating):** counts are over the 57 ratios the harness computes.

| Company (year) | Tested for | Errors found / corrected (per audit and tests) | Observed now | Still uncertain |
|---|---|---|---|---|
| **ANURAS** (FY26) | The only line-by-line audit: 68-row matrix, independent recompute, lineage in the AR, Screener same-basis comparison | Cash Ratio policy; dividend attribution (interim 0.75 belongs to FY25); inventory/CCC basis; Total Debt rounding; `Three-Part Test`; pledge/free float flags; no consolidated P&L found in the automatic pipeline | 34 verified, 21 needs_review, 1 insufficient, 1 not meaningful; PAT 170.121 verified | Acquisition-year comparability (goodwill +540 Cr; flagged); debt-like rows listed as "candidates, not included" (sale-and-lease-back liability 64.5 Cr, accrued interest 4.7 Cr) - policy decision pending |
| **TCS** (FY25) | Pipeline parity; ratio sanity | Owners' PAT 1.0 -> 48,553 | Cash ratio 0.157 verified; inventory/CCC `not_disclosed` (services); payout 92.2 % needs_review; PAT NEEDS_REVIEW (estimated flag) | Why PAT carries an estimated flag; no external comparison |
| **Maruti** (FY25) | Unit scaling, page-number ranges, two reference columns, equity (share-capital scaling) | Fixed generically (J.1) | Inventory turnover 17.58 verified; cash ratio 0.018 needs_review; CCC -28.9 days | Not compared with Screener/AR in this repository |
| **ITC** (FY25) | Note references; discontinued operations; payout perimeter | Note-reference fix; PAT repaired to continuing operations (Rs 15,016 Cr difference) | 28 of 57 ratios needs_review; owners' PAT 34,746.6 NEEDS_REVIEW | Continuing-vs-total EPS policy flagged in the final-validation record |
| **Infosys** (FY26) | Contents-page extraction | Contents page no longer read as a statement | Cash ratio 0.424 verified; current ratio 1.978 verified; owners' PAT NEEDS_REVIEW | Services company: no inventory/COGS |
| **HUL** (FY25) | NCI/dividend payer; bare subtotal; DPS in tables | Subtotal fix; DPS from tabulated note (`198e13c`) | 38 verified; payout 116.9 % verified; cash ratio 0.457 needs_review | A payout > 100 % is plausible (special dividend) but is not source-checked here |
| **Asian Paints** (FY25) | Manufacturing sample; text cache | Zero-page cache reported by the audit | Text cache now has 283 pages (file last written 2026-10-07). **TCA = 785.8 Cr** (inventory + receivables + cash = 11,478 Cr, total assets 30,371 Cr) -> current ratio **0.097**, `needs_review` | Subtotal misread is **still open** (M-4) |
| **Bata** (FY25) | Leases; dividend extraction | Dividend scanner fixed | 47 verified; DPS 19; payout 85.3 % | No external comparison here |
| **Bharti Airtel** (FY26) | "Millions" plural scale fix (`5d9bf57`); parity | Unit fix; share-capital scaling | TCL not found -> 15 ratios `not_disclosed`; **DPS 0.0 / yield 0 verified although the AR recommends INR 24/share** | M-13 (new, serious) |
| **L&T** (FY25, FY26) | Conglomerate; owners' vs whole-entity profit | Owners' profit fix (record) | FY25: TCA **157.4 Cr** -> current ratio 0.0008; FY26: TCL **45 Cr** -> current ratio 566, cash ratio 463 - both `needs_review` | M-2 open: nonsensical numbers are flagged, not fixed |
| **Reliance** (FY25) | Holding/consolidated+standalone | Owners' profit read as whole-entity (fixed); DPS not found (record) | 35 verified; payout 9.1 % verified; yield `not_disclosed` | DPS extraction (record) |
| **Titan** (FY25) | Whole-crore depreciation; share count | Row-shift fix (693 vs 5,150) | 37 verified; DPS 11 | Share count printed rounded in crore (record) - unverified |
| **Kotak** (FY25) | Bank module | Rewrite of the bank extractor | Recorded 2026-10-08 run: Sr 58-65 all `verified` (NIM 4.50 vs bank-disclosed 4.96; CASA 42.96; GNPA 1.42; NNPA 0.31; PCR 80.38; CRAR 22.25; C/D 85.54; C/I 43.36) | **Conflicts with the audit statement that Kotak metrics were "not disclosed" in the local-PDF workflow** - unresolved (M-3) |
| **Poonawalla** (FY25, NBFC) | NBFC variant | Sector gate (name has no lender keyword) | NIM 8.28 and C/I 47.16 verified; GNPA, NNPA, PCR, CRAR `not_disclosed` | M-3 open for NBFC asset-quality figures |

External comparisons available in the repository: Screener (ANURAS only; see the audit file), the Annual Report's own analytical-ratios table (ANURAS, standalone basis), and bank-disclosed NIM/CASA/NPA values for four banks (HDFC, ICICI, Kotak, SBI; NIM/CASA/C-D printed verbatim in the bank report for only 1-2 of them).


---

## L. Testing and quality assurance

### L.1 Structure

| Kind | Where | What it covers |
|---|---|---|
| **Formula tests** | `tests/test_ratio_remediation.py` (124 test functions), `tests/test_ratio_formula_oracle.py` (independent re-implementation of every formula vs the contract, plus a check of the audit artefact), `tests/test_calculation_engine.py`, `tests/test_full_quant_coverage.py` | Each ratio's arithmetic, status inheritance, negative/meaningless multiples, DSCR, WC definitions, Altman/Piotroski/Beneish, Beta method, free float |
| **Extraction tests** | `TestRealFilingDefects`, `TestExtractionNoiseRegressions`, `TestUnitFactor`, `TestExtractionRepairs`, `TestDividendExtraction`, `TestBankExtractorRows` | Row reader, note references, page-number ranges, units, contents pages, dividend scans, bank rows (synthetic text that reproduces a real defect) |
| **Regression tests** | `tests/test_final_validation_regressions.py`, `tests/test_global_audit_2026_10c.py`, `tests/test_ratio_corrections_2026_10b.py`, `tests/test_ar_definition_alignment.py` | Each fixed defect is pinned with a minimal example |
| **Pipeline parity** | `tests/test_pipeline_parity.py` (+ `pipeline_parity_probe.py`) | Manual and automatic modes give the same facts; an AST test confines `is_manual_mode()` to source selection/cache keys |
| **Cache and version tests** | `TestCacheAndVersioning`, `TestCacheKeysFoldEveryVersion`, `TestDbRatioReaderCacheCorrectness`, `test_version_bumps_invalidate_every_cache_key` | Each version constant changes the key; DB rows from older versions are cache misses |
| **Missing / insufficient data tests** | `TestUnknownIsNeverZero` (two files), `test_bank_ratios_missing_inputs_are_not_zero`, `test_dividend_inputs_unknown_means_unavailable`, `test_missing_parent_stays_unavailable` | Removing any single input never yields a 0 ratio |
| **Financial-statement identity checks** | `TestLedgerIdentitiesFlagMisreadSubtotals`, `TestBalanceSheetIntegrity`, runtime `_apply_ledger_integrity` and `universe_scan.py` | Flags misread subtotals |
| **Breakdown / evidence tests** | `tests/test_ratio_breakdown.py`, `TestProvenanceCompleteness` | Every numeric ratio has a reconciling breakdown with provenance |
| **Company search / identity** | `tests/test_company_search.py` (17), `tests/company_search_probe.py` (integration probe) | Ranking, ISIN/BSE/name matching |
| **API tests** | `tests/test_forecast_api_errors.py`, `tests/test_live_chart_ticker.py`; no general API-contract test suite for the ratio routes was found | Limited |
| **Frontend tests** | `frontend/tests/*.test.mjs` (7 files, 73 tests; run with Node's built-in runner): ratio categories, ratio-card cleanliness (source-level guard), forecast view/errors, higher-timeframe patterns, pipeline | Logic and source guards; **no rendered-component or browser tests** |
| **Qualitative tests** | `tests/test_qualitative_*.py` (4 files) | Evidence architecture and task engine |
| **Forecast tests** | `tests/test_forecast_*.py`, `tests/test_daily_core.py` | Forecast package |
| **Cross-company validation (manual probes, not pytest)** | `tests/final_validation.py`, `tests/universe_scan.py`, `tests/breakdown_probe.py`, `tests/ratio_regression_probe.py`, `tests/pipeline_parity_probe.py`, `tests/ratio_audit_matrix.py` + `ratio_audit_render.py` | Real cached filings |

### L.2 Commands (verified)

```bash
# backend (pytest is installed in the project's venv; it is NOT in requirements.txt)
venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --ignore=tests/universe_scan.py

# frontend
cd frontend && npm test            # = node --test tests/*.test.mjs   (frontend/package.json)

# manual probes (real cached filings; see section L.3 for their current state)
venv/Scripts/python.exe tests/ratio_regression_probe.py --root . --out out.json --symbols TCS:2025 ANURAS:2026   # space-separated
venv/Scripts/python.exe tests/pipeline_parity_probe.py --out parity.json TCS:2025
venv/Scripts/python.exe tests/universe_scan.py --out universe_scan.json
venv/Scripts/python.exe tests/company_search_probe.py "prime fresh" TCS
```

### L.3 Latest results actually observed (2026-10-09)

* Backend: **542 passed, 1 warning, 63 subtests passed in 124.72 s** (deprecation warning from Starlette's test client). The historical report said 489.
* Frontend: **73 passed, 0 failed**. Matches the historical 73.
* `tests/ratio_regression_probe.py` on 15 company-years: all ran, no error (values in K).
* **`tests/final_validation.py` currently crashes** for every company with `TypeError: run_company.<locals>.<lambda>() got an unexpected keyword argument 'fiscal_year'` - its stub `adc.get_ar_pages = lambda s, n, y=None: ...` (line ~114) does not accept the `fiscal_year` keyword the code now passes. This is a **test-harness defect, not necessarily a product defect**, but it means the 17-company validation cannot currently be reproduced (open issue M-15). I did not re-run `universe_scan.py`, `breakdown_probe.py` or `pipeline_parity_probe.py` standalone (the parity test inside pytest passed).

### L.4 What each test type proves - and cannot prove

| Type | Can prove | Cannot prove |
|---|---|---|
| Unit / formula | The code computes the written formula on given numbers | That the written formula is the *right* one, or that real inputs are right |
| Oracle (independent recompute) | Two independent implementations of the same formula agree | That both implement the intended definition |
| Extraction (synthetic text) | A specific known layout defect is fixed | That other layouts of other companies parse |
| Regression | An old bug does not come back | New bugs |
| Parity | Both pipelines produce the same facts for the tested company-years | Correctness of those facts |
| Cache / version | A version bump invalidates keys | That a developer remembered to bump |
| Missing-data | No input removal yields 0 | That *real* extraction failures are detected (M-13/M-14 slipped through) |
| Identity checks | Internally inconsistent subtotals are flagged | Errors that keep identities true |
| Cross-company runs | Invariants hold, no crashes | Agreement with an external source |
| ANURAS line-by-line audit | One filing's inputs trace to printed figures | Anything about another company |

### L.5 What passing tests do and do not prove

A green suite means the code does what its authors described. It does not mean every displayed financial number is right: on the same day 542 tests passed, the engine still produced a current ratio of 566 for L&T FY26 (flagged, not fixed), a verified 0 % dividend yield for a company that recommended INR 24/share, and a harness that no longer runs. Treat tests as a guard against regressions, and treat `needs_review` flags plus source checks as the guard against wrong numbers.

---

## M. Known problems and incomplete work

Status was re-verified on 2026-10-09. "Observed" = I ran or read it today; "Recorded" = from a dated record or report not re-run today.

### M.1 Summary

| ID | Issue | Current status |
|---|---|---|
| M-1 | NSE XBRL cross-check of the Cash Ratio not done | **Open** (no evidence of a cross-check) |
| M-2 | L&T current-liability / current-asset extraction unreliable | **Open** (flagged `needs_review`, not fixed) - observed |
| M-3 | Kotak / Poonawalla banking metrics | **Conflicting evidence**: Kotak resolved in the 2026-10-08 recorded run; Poonawalla asset-quality ratios still `not_disclosed` |
| M-4 | Asian Paints zero-page text cache | **Cache part not reproduced** (283 pages now); **subtotal misread still open** - observed |
| M-5 | Legacy regression harness reports TCS PAT 1.0 and fails on ANURAS | **Resolved** - observed (TCS 48,553; ANURAS runs) |
| M-6 | Contribution Margin and DSO are proxies | **Open by design**; owner review pending |
| M-7 | Working Capital Turnover average vs closing | **Resolved** in code (v2026.10.8) and tested |
| M-8 | EV methodology and NCI | **Resolved** in code (v2026.10.9) and tested |
| M-9 | Equity-basis consistency | **Resolved** by a machine-checked policy (W) |
| M-10 | Dividend payout: dividends paid vs NCI vs owners' PAT | **Mostly resolved** (policy A); residual `needs_review` when the split is not printed |
| M-11 | Restricted bank balances in Cash Ratio | **Implemented** (policy N); XBRL verification and M-14 remain |
| M-12 | 68 ratios not individually source-audited across companies | **Open** |
| M-13 | **NEW** DPS = 0 `verified` for Bharti Airtel FY26 although INR 24 is recommended | **Open - discovered while documenting** |
| M-14 | **NEW** Cash Ratio treats an unextracted "other bank balances" line as 0 and stays `verified` | **Pending investigation** |
| M-15 | **NEW** `tests/final_validation.py` crashes (`fiscal_year` TypeError) | **Open** (test harness) |
| M-16 | Latest universe scan: 20/133 filings unreadable; 29 % fail an identity | **Open** (recorded 2026-10-08, not re-run) |
| M-17 | Almost all October work is uncommitted | **Open - risk** (partly reduced: UI and `.gitignore` work is committed in `8434d3a`, `f8e1eec`, `a740486`; the ratio work is still uncommitted) |
| M-18 | Shared password appears in `auth.py` docstring in git history | **Partly fixed**: docstring is now a placeholder (working tree); password **not yet rotated**, history **not purged** - security |
| M-19 | Dividend Yield (and other price ratios) use today's live price for any historical year | **Open - design gap** |
| M-20 | Tracked `logs/` files contained the Angel API key (confirmed equal to the current `.env` value), about 16 bearer tokens, the public IP and the MAC address; pushed to GitHub | **Untracked in `a740486`**; the key is **not yet rotated** and remains in pushed history - security |
| M-21 | `.env.example` is out of date: lacks the OpenRouter and Supabase keys, lists AXIS/Telegram/HOST/PORT/RELOAD that `.env` lacks (Telegram alerts need `TELEGRAM_BOT_TOKEN`) | **Open** |
| M-22 | The public site ran `next dev` (slow, dev badge, stale-script hydration errors behind Cloudflare) | **Fixed 2026-11-06**: production build served from `.next-prod`; Cloudflare Browser Cache TTL set to Respect Existing Headers. **Rebuild with `scripts/build_web.ps1` after any web code change** |
| M-23 | Tunnel availability: `cloudflared service install` registered a service with no `tunnel run` arguments and crashed (exit 1067); a scheduled-task replacement was not created | **Open**: the tunnel stays up only while a manual process keeps it running |
| M-24 | No limit on wrong-password attempts once the site was public | **Fixed** (working tree, uncommitted) - observed: attempts 1-5 gave 401, 6-7 gave 429 |
| M-26 | Create Screener could not filter by chart pattern; Horizontal Resistance was a filter inside every scanner and its own scanner had no button | **Fixed 2026-11-06** (patterns tab; separate header button); tested on the 751-stock store and in the browser (desktop, 375 px) |
| M-27 | ChartsMaze features Navrist lacks | **Nearly all built 2026-11-06** (scanners, analytics, Watchlist, Journal, quarterly fundamentals, exchange lists, industries; see B.17). **Still not built:** Volume Footprint (needs intraday volume), "dense volume" (meaning unknown), % from 3-year high (only about two years of closes stored), Templates (shared presets), a rotation graph on the NSE sector indices (index price history is not available from the sources tried), Order Wins AI notes (LLM calls are disabled), Insider Trading list (the NSE feed returned nothing in testing), bulk/block history before Navrist started reading. *Earlier status:* **Mostly built 2026-11-06** (13 list scanners, Multiple Scans, Sector Analytics, RRG, Market Breadth). **Still open:** Industry Analytics (no finer industry field), earnings scanners and results calendar (no result dates), watchlist/journal (no user accounts), exchange-feed lists, Templates. Definitions are ours; ChartsMaze page contents could not be seen (sign-up wall) |
| M-29 | ai.navrist.com goes down whenever the owner's PC is off or the tunnel program is not running (Cloudflare Error 1033) | **Open.** Oracle free ARM capacity is exhausted in Mumbai; a Hostinger VPS is priced; nothing starts the tunnel automatically (see B.18, `docs/ORACLE_DEPLOY.md`) |
| M-30 | Sector History is flattered by survivorship and equal weighting | **Open, stated on the page.** Only today's listed stocks (about 750) are included; the share of rising months (about 60%) and yearly growth (for example 39% for Consumer Durables) are not what an investor earned; compare sectors, not levels |
| M-31 | The sector event list is editorial | **Open.** `patterns/sector_events.json` was written from general knowledge with month precision, not from a feed; correct it there. "Around then" is never shown as "because of" |
| M-32 | RBI policy dates cannot be listed | **Open.** No source we can read reliably publishes them; the Sector Outlook page links to headlines about the FY27 schedule. Add dates to `patterns/upcoming_events.json` from RBI's own calendar |
| M-33 | Sector Outlook has only a small edge | **Stated on the page.** Replay on 4,700 sector-months: calls of up or down were right about as often as the sector simply rose; a situation that made a rise 10+ points more likely was followed by a 3-month rise 66.6% of the time against 63.1% usually. The odds are not adjusted for scheduled events |
| M-34 | History before 1996 is not used | **Open.** NSE daily files start December 1994 and BSE monthly/yearly figures 1991, but the early prices are raw (no split or bonus adjustment, and BSE's company-action records start about 2000) |
| M-35 | Chart patterns have no proven trading edge | **Measured 2026-11-12** ([`docs/PATTERN_STUDY.md`](docs/PATTERN_STUDY.md)): of 23 bullish patterns only pocket-pivot, order-block, falling-wedge and undercut-and-rally show a small positive average after costs (about +0.8% to +1% over 20 sessions), and their median trade is negative; bearish patterns point the wrong way on average (biased by survivorship); the landing-page top 10 is not supported by the data. Detectors showed no look-ahead (`research/lookahead_check.py`) |
| M-36 | BSE-only stocks have no NSE sector | **Open, by design.** Screener's industry classification (a different taxonomy) is used for Industry Analytics and peers; the sector filter, Sector Analytics, Sector History and Outlook still cover the NSE list only. Choosing a mapping from Screener's classes to NSE's sectors is a decision for the owner |
| M-37 | BSE-only data is thinner and later | **Stated.** About 1,700 of the 2,354 BSE-only stocks are under Rs 100 crore; some have little or no price history (shown without a chart; under 60 bars are left out of the scan), a company with under four reported quarters has no TTM EPS or P/E, and Screener rate-limits (HTTP 429) so a page can briefly show "unavailable" while the background builds run. The numbers in B.20 are a snapshot of 2026-11-12 |
| M-39 | Screener rate-limits this machine | **Mitigated, not solved.** One shared pause with doubling back-off, saved reads kept up to 7 days (BSE-only) and a Yahoo fallback; the full Screener fill of about 2,350 BSE-only companies takes many hours and peers, classification and shareholding stay empty for a company until its read succeeds. Do not run test bursts against Screener while the builds run. A paid data feed or a licensed export would remove the limit |
| M-40 | The site stays up only while its processes live | **Open.** The keeper, backend, web server and tunnel are plain processes: they stop when the session that started them ends or the PC restarts, and then `ai.navrist.com` shows error 530. A Windows Startup entry or service for `scripts/start_navrist.ps1` plus the tunnel would fix this (needs the owner's go-ahead: it is persistent configuration). Related: Application Control now blocks `uuid_utils`' compiled file; a stand-in keeps the backend starting (`tools/uuid_utils_fallback.py`) |
| M-38 | The BSE list is a manual snapshot | **Open.** `data/bse/*.json` was captured once through the browser pane (BSE blocks scripts); new listings, delistings and suspensions after 2026-11-12 are not picked up automatically, and the code has no scheduled refresh |
| M-28 | Result rows in pattern scans still show a "Resistance" line for stocks that have one, although resistance is no longer a filter | **Open - display choice** (informational; owner may want it hidden outside the Horizontal Resistance scanner) |
| M-25 | Phone layout defects (overlaps, sideways overflow, tiny tap targets, headline jump) | **Fixed and verified at 320/375/768 px in an emulated browser**; real-device test and stock-page light mode still pending |

### M.2 Details

**M-1 NSE XBRL cross-check for the Cash Ratio.** *Description:* the original audit asked for the Cash Ratio's cash and other-bank-balance inputs to be compared with the NSE XBRL tags. *Impact:* the restricted/unrestricted classification of "other bank balances" rests on the Annual Report notes alone. *Root cause:* not performed. *Status:* open - I found no test, document or code path that does this comparison (the ANURAS matrix marks Screener "n/a" for Sr 12). *Evidence:* absence in `tests/`, `docs/`; matrix row Sr 12 = NEEDS REVIEW. *Next step:* compare `cash`, `other_bank_balances` and the note's total with the filing's XBRL for ANURAS and 3-4 other companies; record the result in the audit file.

**M-2 L&T.** *Description:* L&T's balance sheet is a large multi-segment layout (Financial Services + Development projects + Others); the extractor reads a wrong total. *Impact:* observed today: FY25 total current assets 157.4 Cr (while inventory + receivables + cash = 73,571 Cr, total assets 379,524 Cr) -> current ratio 0.0008; FY26 total current liabilities 45 Cr -> current ratio 566, cash ratio 463. *Root cause:* subtotal misread (identity layer proves it). *Status:* flagged `needs_review` (never `verified`), root cause open. *Evidence:* `docs/final_validation_2026-10/final_validation_2026-10-08.json` and my 2026-10-09 probe. *Next step:* fix the current-liabilities/current-assets subtotal reader for multi-segment balance sheets, add a regression test from the real page, then bump `_EXTRACTION_LOGIC_VERSION` and `EXTRACTION_VERSION`.

**M-3 Kotak / Poonawalla.** *Description:* the audit reported banking metrics "not disclosed" for both in the tested local-PDF workflow. *Evidence today:* the recorded 2026-10-08 validation shows Kotak Sr 58-65 all `verified` (identity-gated) while Poonawalla (NBFC) has NIM and Cost-to-Income verified but GNPA, NNPA, PCR and CRAR `not_disclosed` ("could not be found in its regulatory disclosures"). The generic probe I ran today (no sector gate) is not a bank-ratio run, so it neither confirms nor refutes. *Status:* conflicting; I could not reproduce the Kotak failure because the validation harness is broken (M-15). *Next step:* fix the harness, re-run the bank block for both through the manual upload path and the automatic path, record both; for NBFCs decide whether asset-quality ratios come from Ind AS disclosures (Stage 3 assets) or are `not_applicable`.

**M-4 Asian Paints.** *Description:* the audit reported a zero-page local text cache. *Observed:* `cache/ar_text/ASIANPAINT_2025.json` has 283 pages (last written 2026-10-07 16:07), so the zero-page state is not present now. *Separate defect, observed:* total current assets 785.8 Cr against 11,478 Cr of inventory + receivables + cash -> current ratio 0.0965, cash ratio from the same misread; both `needs_review`. *Root cause:* subtotal misread (same family as M-2). *Next step:* add a guard that rejects a zero-page/short text cache (so an empty cache is never "valid"), and fix the subtotal reader.

**M-5 Legacy harness.** *Observed 2026-10-09:* `tests/ratio_regression_probe.py` returns TCS owners' PAT 48,553 and runs ANURAS FY26 (PAT 170.121 `VERIFIED`) without error. Root cause was the "attributable to:" colon and a note number read as an amount (decision Y). *Status:* resolved; regression covered by `tests/test_pipeline_parity.py`. TCS PAT still carries `NEEDS_REVIEW` / `estimated` - reason not investigated.

**M-6 Contribution Margin and DSO proxies.** Contribution margin is an estimated proxy by necessity (Ind AS has no variable-cost line); DSO/Receivables turnover use revenue for net credit sales. Both are `needs_review` by design and propagate to CCC. *Next step:* the owner decides whether to (a) keep them permanently as proxies, (b) search for a credit-sales disclosure, (c) hide them behind a "proxy" label in the UI (the UI currently does not draw statuses - `86cb38f`).

**M-7 Working Capital Turnover.** Contract had closing WC ("Annual Report alignment", `6d348dc`); spec says average. Corrected to average in v2026.10.8; `TestWorkingCapitalTurnoverIsAverageBased` passes (observed). Residual: it inherits the current-asset/liability misread risk (M-2/M-4).

**M-8 EV and NCI.** Resolved: EV = market cap + total debt - cash; NCI only in a labelled reference. `TestOneEnterpriseValueDefinition` passes (observed). Residual: whether the owner wants a second "EV incl. NCI" ratio shown in the UI.

**M-9 Equity basis.** `ratio_contract.EQUITY_BASIS` + `TestEquityBasisPolicy` (spies on every fact read) pass (observed). Residual: ROA is a deliberate perimeter mix (owners' profit over 100% assets).

**M-10 Dividend payout.** Policy A splits cash-flow dividends by recipient; when the filing prints neither split on a consolidated entity with material NCI the result is `needs_review` with a perimeter warning. Recorded validation: payout `needs_review` for 11 of 17 companies.

**M-11 Restricted balances.** Implemented and tested; two limits: no XBRL cross-check (M-1), and lines of unstated nature are included but flagged.

**M-12 Not all ratios source-audited.** Only ANURAS has a line-by-line audit. *Next step:* choose 3-5 companies across sectors and repeat the ANURAS method (independent recompute + lineage + external comparison).

**M-13 Bharti Airtel FY26 DPS.** *Description:* the Annual Report text says (page 14) "dividend of H24 per share for FY 2025-26" (rupee glyph rendered as H) and (page 163) "H 24/- per fully paid-up equity share ... H 6/- per partly paid-up share" - i.e. the rupee symbol is extracted as the letter **H** from this PDF's text layer. The dividend patterns (`_DIVIDEND_RE`, `_DIVIDEND_GENERIC_RE` in `tools/annual_report_financials.py`) accept an optional `Rs`/`INR`/rupee-sign/backtick token between "of" and the number, so the unrecognised letter "H" breaks the match and no dividend is found; a "no dividend" phrase elsewhere in the report (with the financial year in its context) then satisfied `no_dividend_evidence` - the fact-store branch that wrote the zero only runs in that case - and the fact store wrote `dps = 0.0`, tag `no_dividend_statement`, status VERIFIED, confidence 0.9 (`tools/fundamental_fact_store.py` line ~419). Dividend Yield shows 0 %, `verified`. *Impact:* violates the rule that zero must be evidence-supported; affects Sr 27 directly (and Sr 47-49 wherever the declared-DPS fallback is used). Any filer with a mis-mapped currency glyph could be affected. *Status:* open, not fixed (documentation task). *Evidence:* my probe values (`dps` = 0.0, tag `no_dividend_statement`) and the page text. *Next step:* treat mis-mapped currency glyphs as currency in the dividend patterns (generic, not Airtel-specific), require that a "no dividend" statement is not contradicted by any "dividend of <something> per share" sentence, add a regression test, bump the versions.

**M-14 Cash Ratio and an unextracted "other bank balances" line.** *Description:* `_r_cash_ratio` sets the unrestricted other-bank-balances amount to 0.0 when the line was not extracted at all, and keeps status `verified`. The ANURAS matrix probe also found that blanking `other_bank_balances` left the Cash Ratio unchanged. *Impact:* a company with such a line whose extraction failed gets an understated, "verified" Cash Ratio. A balance sheet that has no such line legitimately contributes zero, so the rule needs to distinguish "absent" from "not found". *Status:* pending investigation - I have not demonstrated it on a real filing. *Next step:* have the fact store record `other_bank_balances` as "not present on the balance sheet" vs "not found", and set `needs_review` for the latter.

**M-15 Broken validation harness.** See L.3. *Next step:* make the stub accept `**kwargs`, re-run the 17-company validation, replace `final_validation_2026-10-08.json`.

**M-16 Universe scan.** Recorded: 133 real filings, 20 unreadable automatically, 39 (29 %) fail an identity - all flagged `needs_review`, none root-fixed. Not re-run today.

**M-17 Uncommitted work.** See B.0. *Next step:* commit in logical pieces (contract, fact store, extraction, tests, docs).

**M-18 Credentials in history.** See D.3. *Next step:* rotate the site password and JWT secret, remove the line from the docstring, consider purging history.

**M-19 Price timing.** See E.3 and H-10.

**M-20 Secrets in tracked logs.** The Angel client logs the full request headers on errors (`X-PrivateKey`, `Authorization: Bearer ...`, `X-ClientPublicIP`, `X-MACAddress`). `.gitignore` listed `logs/` patterns, but ignoring does not apply to files git already tracks, so six files stayed in the repository. *Done:* `git rm --cached -r logs`, `logs/` and `data/` ignored, committed as `a740486` (local files kept). *Next step:* regenerate the Angel API key (the old one is in pushed history); decide whether to purge history (destructive; copies and forks keep the old data). *Lesson:* after adding an ignore rule, check `git ls-files` for files it should have covered.

**M-21 `.env.example` drift.** Keep it as placeholders only. *Next step:* add the missing names and remove names no code reads.

**M-22 Dev server in public (fixed).** See B.17. Operating rule: web code changes are **not** visible on localhost:3100 or ai.navrist.com until `powershell -ExecutionPolicy Bypass -File scripts\build_web.ps1` has run (a few minutes; the site restarts within about a minute). For editing with live reload, run a dev server on another port (`cd navrist-web && npm run dev -- -p 3101`; `allowedDevOrigins` is already set); both can run at once because the production build uses its own folder. Backend (Python) changes still need the `python app.py` processes restarted (the keeper restarts them).

**M-23 Tunnel persistence.** See O.10. *Next step (owner, Administrator shell):* `sc.exe delete cloudflared`, then create a startup task that runs `cloudflared tunnel run navrist`.

### M.3 Other limitations worth knowing

* `DEPLOY.md` still lists yfinance as the financials source and Groq for AI sections (stale; O.9).
* `requirements.txt` omits packages the tests need (pytest, scikit-learn, lightgbm).
* `tools/ratio_audit.py` documents a ratio numbering conflict between `precompute_worker.RATIO_FETCHERS` and the UI (2026-08-07). Today `RATIO_FETCHERS` is built from the registry, so the conflict appears resolved, but that docstring is stale.
* Hard-coded shorthand aliases (SBI, ICICI, HDFC...) exist in `app.py::resolve_symbol_from_registry`; these are search aliases, not analysis logic.
* The Ask Navrist chatbot and all LLM-based features are intentionally disabled.
* Qualitative topics H-U are catalogued but not built.
* The forecast package covers 8 pilot equities; direction forecasts are not validated.
* Frontend has no rendered-UI tests.

---

## N. Cache, versions and data freshness

### N.1 What is cached, and why

Parsing a 300-700 page PDF takes tens of seconds (observed 24-91 s per company-year with 4 parallel workers). Caching avoids repeating it.

| Cache | Location | TTL / key |
|---|---|---|
| Annual Report PDF bytes | `cache/ar_pdfs/{SYM}_{FY}.pdf` | 30 days |
| Annual Report page text | `cache/ar_text/{SYM}_{FY}.json` (also written on manual upload) | until overwritten; file mtime+size feed the document identity |
| Extraction result and per-ratio wrappers | `cache/bse/ar_*_{SYM}_{FY}_{C or S}_{docid}.json` | 90 days; key contains the document identity tag and `_EXTRACTION_LOGIC_VERSION` |
| NSE XBRL / manual XBRL | `cache/nse_xbrl`, `cache/xbrl_manual` | per file |
| Statement-basis selection | `cache/statement_selection` | 12 h |
| In-process FactSet memo | `fundamental_fact_store._run_cache` | process lifetime; key includes document identity, extraction version, fact version and the manual flag; `clear_run_cache()` |
| Stored ratio rows | Supabase `ratio_values` (automatic) / `fundamental_analysis_results` (manual) | row carries `formula_version`, `breakdown_version`, `extraction_version`, `calculated_at` |
| Shareholding / Screener / others | `cache/shareholding*`, `cache/screener*` | hours (see module docstrings) |

### N.2 How stale data causes wrong numbers

* A code fix does not change the PDF's mtime, so a cache keyed only on the document would keep serving the pre-fix result. This happened repeatedly (record *final-validation-2026-10*; ANURAS and Prime Fresh examples in `annual_report_financials.py` comments).
* The precompute worker skips pairs already `done` in `refresh_jobs`, and each `nse_xbrl` wrapper first reads Supabase (`try_db_ratio`) for the latest year - so re-running the precompute silently re-serves an old wrong row (documented in `tools/refresh_ratios.py`, confirmed on ITC, 2026-08-07). Use `tools/refresh_ratios.py` for fixes.
* A price-dependent ratio row keeps the price at its computation time.

### N.3 Version constants (read from the code on 2026-10-09)

| Constant | File | Value | Bump when |
|---|---|---|---|
| `FORMULA_VERSION` | `tools/ratio_contract.py` | `"2026.10.13"` | Any formula or policy definition changes |
| `_EXTRACTION_LOGIC_VERSION` | `tools/annual_report_financials.py` | `"86"` | Any label list, row reader, fallback or bank/XBRL path changes |
| `EXTRACTION_VERSION` | `tools/fundamental_fact_store.py` | `20` | Fact derivation or integrity checks change |
| `BREAKDOWN_VERSION` | `tools/ratio_breakdown.py` | `2` | The breakdown payload changes |
| `_QUALITATIVE_LOGIC_VERSION` | `tools/qualitative_db.py` | `"40"` | Qualitative logic changes |
| `QUALITATIVE_EXTRACTION_VERSION` / `QUALITATIVE_ENGINE_VERSION` | `tools/qualitative_evidence.py` / `tools/qualitative_task_engine.py` | `1` / `1` | Qualitative evidence/engine changes |
| Qualitative schema versions (`_A1_SCHEMA_VERSION` ... `_A3_SCHEMA_VERSION`, `_BIZ_COMP_SCHEMA_VERSION`, etc.) | `tools/qualitative_engine.py` | various (e.g. `_A2D` 7, `_A3` 8, `_BIZ_COMP` 12) | Per sub-point |

Rule (contract "Cache / version rule"): any extraction change bumps `_EXTRACTION_LOGIC_VERSION` and `EXTRACTION_VERSION` in the same change; a formula/policy change also bumps `FORMULA_VERSION`. The ratio cache key folds all of `FORMULA_VERSION`, `_EXTRACTION_LOGIC_VERSION` and `EXTRACTION_VERSION` (`_contract_cache_key`; tested).

### N.4 When to invalidate

1. After any change to extraction code, labels, units, a formula, a policy -> bump versions (do **not** hand-delete files).
2. When a user re-uploads a document -> automatic (identity tag changes).
3. When a stored row must reach already-precomputed companies -> `tools/refresh_ratios.py`.
4. A zero- or short-page `cache/ar_text` file should be deleted and rebuilt (no guard exists yet; M-4).

### N.5 Cold versus warm runs

* **Cold:** PDF downloaded/read, text cached, statements extracted, facts built, ratios computed, row stored. Must be slow but correct.
* **Warm:** the same answer must come from caches in seconds. A warm run returning a *different number* than a cold run means a cache key is missing a version or the document identity - treat as a bug. `tests/test_pipeline_parity.py` and the cache tests check part of this; there is no automated cold-vs-warm comparison on a real filing.

### N.6 Manual versus automatic

Manual runs never write the shared `ratio_values` table (so uploads cannot pollute it), never reach live BSE/NSE, and use separate keys (flag in the key). Automatic runs read the DB fast path only for the latest year.

---

## O. How to run and maintain Navrist

### O.1 Prerequisites

Python 3.14.x in the existing `venv/` (observed `Python 3.14.6`), Node (observed v24.18.0) for the frontend, internet access for NSE/BSE/Angel/Yahoo, and (optionally) a Supabase project. NSE blocks many non-Indian datacentre IPs; `DEPLOY.md` recommends an Indian region.

### O.2 Environment setup

```bash
python -m venv venv
venv/Scripts/activate            # Windows; on Linux: source venv/bin/activate
pip install -r requirements.txt
pip install pytest               # needed by the tests, missing from requirements.txt
cp .env.example .env             # then fill in real values; never commit .env
```

### O.3 Configuration (names only - never put values in documentation or commits)

| Variable | Purpose |
|---|---|
| `SITE_PASSWORD`, `JWT_SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_HOURS` | Login and session tokens (`auth.py`) |
| `ANGEL_API_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_PASSWORD`, `ANGEL_TOTP_SECRET` | Angel One live price; blank -> yfinance fallback |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | Database (read in `tools/supabase_client.py`; **not listed in `.env.example`**) |
| `HOST`, `PORT`, `RELOAD` | Server binding (defaults 127.0.0.1 / 8000 / reload on) |
| `NSE_PROXY_URL`, `NSE_INSECURE` | NSE access from restricted networks (insecure flag: dev only) |
| `AXIS_*`, `UPSTOX_*` | Live-chart broker scaffolding (optional) |
| `GROQ_API_KEY` | Present in the template but unused while LLMs are disabled |
| `FORECAST_DATA_DIR` | Forecast data location |

### O.4 Starting the backend and frontend

```bash
venv/Scripts/python.exe app.py            # FastAPI on http://127.0.0.1:8000 (reload on; cache/ is excluded from the watcher)
cd frontend && npm install && npm run dev  # Vite on http://localhost:5173 (proxies /api and /exports to :8000)
cd frontend && npm run build               # produces frontend/dist, which app.py serves at /
```
`.claude/launch.json` defines the same servers (`backend`, `frontend`, `test-instance` on :8010 via `frontend/scripts/serveTestInstance.py`). Health check: `GET /api/health`. Changing `.env` needs a backend restart (the reloader does not watch it).

**Production build (2026-11-06).** The keeper now serves the production build from `navrist-web/.next-prod` (see M-22); the description below of the keeper starting `npm run dev` applies only when no build exists.

**Current web UI (added 2026-11-06).** The interface in use is the Next.js app in `navrist-web/` (Next 16, App Router), not the Vite app in `frontend/`. `start_navrist.bat` runs `scripts/start_navrist.ps1`, which starts `scripts/keep_running.ps1` (a hidden loop that restarts the backend `python app.py` on :8000 and `npm run dev -- -p 3100` in `navrist-web/` when a port stops answering, checking every ~60 s) and opens `http://localhost:3100`. `navrist-web/next.config.ts` rewrites `/api/*` to `NAVRIST_BACKEND_URL` (default `http://127.0.0.1:8000`), so a single public origin is enough. To make backend code changes take effect, stop the `python app.py` processes; the keeper restarts them. **Gotchas:** the backend did not pick up a change to `auth.py`/`app.py` until it was restarted, and `netstat` may show the owner of the :8000 listener as PID 0, so find the process by command line (`Win32_Process`).

### O.5 Uploading / processing documents

Use the Document Analysis view, or call `POST /api/v1/documents/analyse` (multipart; Bearer token from `POST /api/auth/login`). Then `POST /api/v1/document-analysis/run` and `GET /api/v1/document-analysis/{symbol}`. Details in [F](#f-manual-document-upload-workflow). Batch precompute (automatic mode, writes Supabase):

```bash
venv/Scripts/python.exe tools/run_full_precompute.py --workers 2     # long-running; resumable
venv/Scripts/python.exe tools/refresh_ratios.py --ratios 10,11,12 --symbols ITC   # force recompute after a fix
```

### O.6 Diagnosing a failed company search

1. Call `GET /api/search-symbols?q=<text>` (needs the session token). It waits up to 15 s for the universe to load - an early query right after startup can be incomplete.
2. Run the integration probe: `venv/Scripts/python.exe tests/company_search_probe.py "<name>" <SYMBOL>`; it uses the real universe.
3. Check whether the company is in the NSE universe / `companies` table and whether its symbol, BSE code or ISIN differs from the name searched (`tools/company_search.py` matches all four; ranking exact symbol > exact name > prefix > contains > fuzzy).
4. Newly listed or renamed companies: check `cache/nse_company_names.json` and re-seed with `tools/seed_company_registry.py`.

### O.7 Investigating an incorrect ratio, reading evidence, statuses

See [P](#p-how-to-investigate-a-wrong-ratio). To read evidence: open the ratio's **Calculation Breakdown** (or `GET /api/v1/document-analysis/{symbol}`; the row's `_metadata.breakdown`). It lists each input leg with its unrounded value, fact name, period, basis, page, statement, extraction method, the parents of derived ratios, warnings, and a `reconciles` flag. Statuses are defined in C.3.

### O.8 Clearing or invalidating stale caches

Preferred: bump `_EXTRACTION_LOGIC_VERSION` / `EXTRACTION_VERSION` / `FORMULA_VERSION` (N.3) so keys change. Deleting `cache/` files is safe (they are rebuilt) but slow; delete `cache/ar_text/{SYM}_{FY}.json` only if it is empty/short. For stored rows use `tools/refresh_ratios.py`. Never patch extraction code containing regular expressions through shell heredocs (escape corruption, record *final-validation-2026-10*); edit with a proper editor or script file.

### O.10 Public deployment at ai.navrist.com

*Set up 2026-11-05. Names only; no credentials belong here.*

| Item | Value |
|---|---|
| Registrar | Hostinger (domain `navrist.com`) |
| DNS | **Cloudflare** (Free plan); the Hostinger nameservers were replaced by the two Cloudflare ones |
| `navrist.com` / `www` | WordPress on Hostinger shared hosting (A/AAAA/CNAME, proxied) - unchanged |
| `ai.navrist.com` | CNAME created by `cloudflared tunnel route dns navrist ai.navrist.com`, pointing at tunnel `navrist`, which forwards to `http://localhost:3100` |
| Config | `C:\Users\<user>\.cloudflared\config.yml` (tunnel `navrist`; ingress `ai.navrist.com` -> `http://localhost:3100`, fallback 404); `cert.pem` and the tunnel's `<id>.json` credentials sit beside it and must never be committed |
| Run | `cloudflared tunnel run navrist` (needs `C:\Program Files (x86)\cloudflared` on PATH) |

**Steps in order:** (1) add `navrist.com` to Cloudflare and compare the imported records with Hostinger's; (2) set the mail-related records to *DNS only* (`autoconfig`, `autodiscover`, the three `hostingermail-*._domainkey` CNAMEs, `ftp`) because proxying breaks them, and delete the old `ai` A record; (3) change the nameservers at Hostinger and wait for "Active"; (4) set SSL/TLS to **Full**; (5) `cloudflared tunnel login`, choosing the zone `navrist.com` by **clicking its row**; (6) `tunnel create`, `tunnel route dns`, write the config, run.

**Mistakes made and what they taught:** `cloudflared tunnel login` cannot finish until the domain is a zone in the account; a new PowerShell window is needed after `winget install` to refresh PATH; the Windows service created by `cloudflared service install` had no `tunnel run` arguments and exited (1067), and a service reads its config from the *system profile*, not the user's folder; a stopped service can hang in STOP_PENDING and needs `taskkill /F /PID`; Cloudflare error 530 means "no tunnel connected"; and the first public page load hung until `allowedDevOrigins` was set.

**Serving mode:** since 2026-11-06 the public site serves a production build, not the dev server (see M-22); remember to run `scripts\build_web.ps1` after changing web code. The Cloudflare setting *Caching -> Browser Cache TTL = Respect Existing Headers* is required, or old scripts can be held for 4 hours.

**Security posture while public:** the site is behind the shared password; 91 of 95 API routes require a session; login is rate limited (D.3). The tunnel exposes only port 3100. The machine must stay awake and online. This is a demo-grade setup; a small VPS plus a production build is the recommended next step.

### O.9 Known stale documentation

`DEPLOY.md` section 6 (data sources: "yfinance ... as filed", Groq for AI sections) describes the 2026-06 architecture; the first lines of section 2 still say `GROQ_API_KEY` is required. `docs/ratio_contract.md` is generated and current (formula `2026.10.13`). Project memory notes outside the repo describe email/password auth and "Screener primary" - both superseded (D.3, B.4). `.env.example` is stale (M-21). Section O.4 originally described only the Vite app in `frontend/`; the Next.js app in `navrist-web/` is the interface in use (see the 2026-11-06 note under O.4).

---

## P. How to investigate a wrong ratio

**Rule: never patch the displayed ratio. If the underlying fact is wrong, fix the extraction (generically), not the output.** (`CLAUDE.md`: no ticker-specific logic.)

1. **Confirm the company and symbol.** Check the resolved symbol / BSE code / ISIN (`company_search_probe.py`); beware namesakes and renamed companies. Confirm the document belongs to that company (`document_id` / `source_url` in the breakdown).
2. **Confirm the financial year.** FY2026 = year ending 31 March 2026. Check the Annual Report's cover year and the `period` on each input (current vs prior).
3. **Confirm the basis.** Consolidated or standalone? (`basis` on the fact; banks are standalone by policy.) Never compare a consolidated Navrist number with a standalone AR table or Screener standalone figure.
4. **Find the original source figure.** Open the PDF at the page the breakdown cites (`page`, `statement`). Note the printed unit and whether the figure is owners' or whole-entity.
5. **Verify the extracted value.** Compare the fact's `value`/`prior_value` with the page; look for note-reference columns, page-number ranges, parentheses for negatives, and the wrong row.
6. **Check units.** Rs crore / lakh / million / thousand; a footnote far from the table; a plural "millions".
7. **Check the normalised fact.** Run `tools.fundamental_fact_store.get_canonical_facts(symbol, name, fy)` and read `fs.facts[...]`: `status`, `estimated`, `warnings`, `raw_label`, `perimeter`, `method`.
8. **Check the formula and inputs.** Compare the breakdown's expression with `ratio_contract.SPEC[key]["definition"]` and the approved formula in `fundamental_ratio_registry.py`; recompute by hand with `value_raw` legs.
9. **Trace dependent ratios.** `ratio_contract.PARENTS` (e.g. CCC <- DSO, DIO, DPO; DIO <- Inventory Turnover). A wrong parent makes every child wrong, and a child inherits the worst parent status.
10. **Check status and evidence.** Is it `needs_review`/`not_meaningful`? Read the warning text; is a proxy involved (Sr 3, 4, 5, 34, 44, 55, 57, 68)? Run the ledger identities (current assets >= parts; TA = L + E).
11. **Check the cache and version keys.** Was the stored row produced under the current `FORMULA_VERSION`, `_EXTRACTION_LOGIC_VERSION`, `EXTRACTION_VERSION`? Is `stale` true? Did the precompute DB fast path return an old row? (N.2)
12. **Compare with a semantically equivalent trusted-source value.** Convert to the same basis first (e.g. Screener ROCE uses a different capital base; OPM excludes depreciation). Agreement of inputs with a gap in outputs = definition difference; disagreement of inputs = extraction bug.
13. **Add a regression test.** Minimal synthetic text reproducing the layout defect (see `TestExtractionNoiseRegressions`), plus an assertion that unknown stays unknown.
14. **Re-run the relevant and full suites.** `pytest` (L.2), `npm test`, then the real-filing probes (`ratio_regression_probe.py`, `pipeline_parity_probe.py`, `universe_scan.py`) and compare before/after against a `git worktree` of the previous commit. Bump the versions first, or the old cache will hide your fix.

---

## Q. Glossary

| Term | Plain-English meaning |
|---|---|
| Annual report | The yearly document a listed company publishes, containing audited financial statements, notes and management commentary |
| XBRL | A machine-readable tagging format for financial filings; NSE/BSE publish results in it |
| Financial fact | One extracted number (e.g. "Revenue FY2026 = 2,365.455 Cr") with its period, basis, perimeter, page, method and status |
| Consolidated statements | Figures for the parent plus all its subsidiaries combined |
| Standalone statements | Figures for the parent company alone |
| Parent-company shareholders | The company's own shareholders ("owners"); profit and equity attributable to them exclude outside holders |
| Non-controlling interest (NCI) | The part of a subsidiary owned by outside (minority) shareholders |
| Revenue | Money earned from selling goods/services (here "Revenue from operations") |
| COGS | Cost of goods sold: cost of materials consumed + purchases of stock-in-trade + changes in inventories |
| EBIT | Earnings before interest and tax: profit before tax + finance costs (Navrist includes other income) |
| EBITDA | EBIT + depreciation, amortisation and impairment |
| PAT | Profit after tax (owners' or whole-entity - always state which) |
| EPS | Earnings per share |
| DPS | Dividend per share |
| Working capital | Current assets minus current liabilities |
| Capital employed | Total assets minus current liabilities |
| OCF | Operating cash flow (from the cash-flow statement) |
| Capex | Capital expenditure: money spent on fixed assets (gross, in Navrist) |
| Free cash flow | OCF minus capex |
| Market capitalisation | Share price x shares outstanding |
| Enterprise value (EV) | Market cap + total debt - cash & cash equivalents (Navrist definition, NCI excluded) |
| Book value | Owners' equity (per share = BVPS) |
| Data provenance | Where a number came from: document, page, statement, method |
| Cache invalidation | Throwing away a saved result because it may be out of date |
| Regression test | A test that pins a fixed bug so it cannot silently return |
| `needs_review` | Computed, but an input is a proxy/estimate, a perimeter is ambiguous, or a parent needs review - do not rely on it without checking |
| `not_disclosed` | The filing does not contain the needed input (or it could not be found); no number is shown |
| `not_applicable` | The ratio does not apply to this company (e.g. bank ratios for a manufacturer) |
| `insufficient_data` | Not enough inputs (e.g. no prior-year balance, nine tests not all evaluable) |
| `verified` | Computed from disclosed inputs with no caveat (still only as good as the extraction) |
| `not_meaningful` | The arithmetic exists but the result is economically meaningless (e.g. EV/FCF with negative FCF) |
| Perimeter | Whether a figure covers the owners only or the whole consolidated entity |
| Proxy | A stand-in for a figure that is not disclosed (e.g. revenue for credit sales); always flagged |

---

## R. Roadmap and completion status

### R.1 Status table

| Category | Items |
|---|---|
| **Completed and verified** (code + tests + an observed run today) | Single ratio contract and adapters (B.13); statuses and unknown-never-zero model (with M-13/M-14 exceptions); calculation breakdown payload; COGS Inventory Turnover and dependants; average-WC turnover; single EV definition; equity-basis policy; dividend fiscal-year attribution; version folding into cache keys; pipeline parity; EBIT Margin relabel; frontend logic tests (73 pass); backend suite (542 pass) |
| **Implemented but not fully verified** | Cash Ratio restricted-balance policy (no XBRL cross-check); dividend payout perimeter split (many `needs_review`); bank extractor for Kotak/HDFC/ICICI/SBI (identities proven, disclosed values corroborated for only 1-2 per ratio); Total Debt Three-Part Test; pledge/free-float against the filing; qualitative A-G scoring; live chart patterns; income-statement charts |
| **Partially implemented** | Net-credit-sales DSO (proxy only); NBFC asset-quality ratios (Poonawalla not found); Beta in manual mode (insufficient by policy); XBRL path for uploaded filings; Supabase fast path (latest year only); qualitative H-U (catalogued, not built); forecast beyond 8 pilot symbols |
| **Known bug** | M-2 L&T current items; M-4 Asian Paints subtotal; M-13 Bharti DPS zero; M-15 broken validation harness; `DEPLOY.md` / `requirements.txt` stale; credentials in git history (M-18, M-20) |
| **Pending investigation** | M-1 XBRL Cash Ratio cross-check; M-3 Kotak/Poonawalla discrepancy; M-14 absent-vs-unextracted bank balances; TCS owners' PAT `NEEDS_REVIEW` reason; ITC continuing-vs-total EPS policy; 20/133 unreadable filings and 29% identity failures (M-16); Titan share-count rounding; payout > 100 % cases |
| **Future enhancement** | ChartsMaze-parity scanners and lists in three groups (candle-based scanners and Market Breadth first; result dates and exchange feeds next; watchlist/journal with user accounts) - see `docs/CHARTSMAZE_GAP_ANALYSIS.md`; dated (fiscal-year-end) price series for historical yields; TTM ratios; OCR for scanned PDFs; second EV view with NCI in UI; cold-vs-warm automated comparison on real filings; rendered-UI tests; per-user accounts; re-enabling LLM interpretation (owner's explicit decision required); daily-forecast production model |

### R.2 Priorities (financial correctness first, then user impact)

1. **Rotate the exposed secrets (site password, `JWT_SECRET_KEY`, Angel API key; M-18, M-20) and commit the remaining October work** (M-17) - one bad disk or force-push loses the audit trail. Then: a production build and a persistent tunnel or a VPS (M-22, M-23), a real-phone test (M-25) and a refreshed `.env.example` (M-21).
2. **M-13** dividend glyph zero (a wrong "verified 0") and **M-14** (possible silent zero) - both break the project's central rule.
3. **M-2 / M-4** subtotal misreads (L&T, Asian Paints, Bharti): they are already flagged, but every liquidity ratio depends on them.
4. **Repair the validation harness (M-15)** and re-run `final_validation.py` / `universe_scan.py`; update the matrix.
5. **Source-audit 3-5 more companies** with the ANURAS method (M-12), starting with a bank, an IT company and a manufacturer.
6. Bank/NBFC completeness (M-3).
7. Price-timing (M-19) and the credit-sales/contribution-margin decisions (M-6).
8. Documentation hygiene (`DEPLOY.md`, `requirements.txt`).

### R.3 Original scope versus later enhancements

*Original scope (phase 1, June 2026):* a fundamental research terminal - data ingestion, ratio/financial analysis, AI-assisted qualitative analysis, a dashboard behind a login. *Later enhancements:* Vite/React rebuild and design system; Supabase precompute; the 68-ratio programme and its audits; manual document upload; calculation breakdowns; the qualitative framework A-U; live chart/pattern tools; the forecast pilot; the Ask Navrist chatbot (now disabled).

> **Overall:** the system is **not** complete. The final-validation verdict of 2026-10-08 was **NOT READY**; since then many defects were fixed and tested, but the validation harness is currently broken, three extraction defects are open, one "verified zero" violation was found today, and only one company has been audited line by line.
