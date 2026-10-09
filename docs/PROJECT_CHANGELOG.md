# Navrist Project Changelog

Chronological record of significant milestones, fixes and architectural changes. Full explanations live in
[`PROJECT_DOCUMENTATION.md`](../PROJECT_DOCUMENTATION.md) (section letters below link there); per-ratio evidence is in
[`FINANCIAL_RATIO_AUDIT.md`](FINANCIAL_RATIO_AUDIT.md); the generated formula contract is [`ratio_contract.md`](ratio_contract.md).

**How to read:** each entry gives *Historical* (what existed), *Change* (what was done), *Current* (behaviour today, checked 2026-10-09) and
*Unresolved*. **Source key:** `abc1234` = git commit on `main`; **(record)** = dated owner/assistant project note (not in git); **(uncommitted)** = present in the working tree
but in no commit; **(derived)** = reconstructed from file timestamps/documents. Exact days are given only where a commit, a dated document or a record states them.

> The repository has 214 commits (2026-06-21 -> 2026-10-08). Almost all October 2026 ratio work is **uncommitted** - see
> [PROJECT_DOCUMENTATION.md B.0](../PROJECT_DOCUMENTATION.md#b0-how-this-history-was-reconstructed-and-its-limits) and open issue M-17.

---

## June 2026 - Ingestion and the first agent

### 2026-06-21 - `f84bcab` Initial commit: ingestion layer
* *Historical:* nothing. *Change:* `tools/nse_scraper.py`, `pead_engine.py`, `pipeline_orchestrator.py`, `initialize_kite.py`. *Current:* files remain, not on the ratio path. *Unresolved:* none. [B.2](../PROJECT_DOCUMENTATION.md#b-the-complete-project-history)

### 2026-06-24 - Login added (record) -> 2026-06-29 `1914c2e` "Major update"
* *Historical:* no UI, no auth. *Change:* LangGraph research agent (`agent/stock_agent.py`), Angel One scraper, FastAPI `app.py`, shared-password JWT `auth.py`, single-file React dashboard `frontend-dashboard/index.html`, `DEPLOY.md`, `.env.example`.
* *Current:* all present; auth is one shared `SITE_PASSWORD` + JWT (not per-user email accounts). *Unresolved:* the real password appears in `auth.py`'s docstring in this commit and later history (M-18). [B.3](../PROJECT_DOCUMENTATION.md#b-the-complete-project-history), [D.3](../PROJECT_DOCUMENTATION.md#d3-authentication-as-implemented)

### 2026-06-29 / 06-30 - UI polish, moat from Screener, peer percentiles
* `963d297` remove Windows-only dependency; `6bbdf10` favicon/title; `6fc2e6d` data-driven moat score from Screener fundamentals; `1194ea4` peer-set percentiles. *Current:* legacy agent features remain; Screener is **not** used by the ratio contract (E).

## July 2026 - Rework, real statements, database, QA

### 2026-07-03 - `260b1ff` AI Insights redesign; `339149a` Vercel config fix and two commits with placeholder messages (`9b1dc0c`, `7d5c98e`)
* *Change:* Business Model Canvas, dynamic moat, peer table, resilient LLM. Branch `antigravity-backup` created (record) to preserve an IDE's uncommitted work. *Unresolved:* branch never merged or reviewed.

### 2026-07-08 - Architecture rework decisions (record)
* *Historical:* a report took 8-9 minutes. *Change (decisions):* performance first; Screener as primary financials source; grounded retrieval without a vector DB; keep Groq.
* *Current:* speed work done via precompute/caching and LLM disable; **Screener-primary and keep-Groq were reversed** (audited filings are the source; LLMs disabled 2026-08-19). [B.4](../PROJECT_DOCUMENTATION.md#b-the-complete-project-history)

### July 2026 - NSE XBRL fundamentals (record) and `6ebb97a` (2026-07-14) "Major updates"
* *Change:* `tools/nse_xbrl.py` (first ratio: Inventory Turnover, standalone XBRL), then Annual-Report-PDF extraction (`annual_report_financials.py`, BSE/NSE PDFs). Text dumps `*_pages.txt` of sample filings were committed during extraction debugging.
* *Current:* AR-PDF extraction is the primary route; XBRL used in manual mode/fallback. *Unresolved:* a July record says "don't revisit BSE PDFs"; the code later relies on them - no reversal record. [B.5](../PROJECT_DOCUMENTATION.md#b-the-complete-project-history)

### 2026-07-15 - Supabase chosen (record) -> 2026-07-20 `a2b0615`
* *Change:* Vite/React frontend, Supabase tables (`db/001`, `002`), precompute worker, company-registry seeding (BSE scrip codes + AR URLs), coverage tooling, BSE name-matching and Supabase pagination fixes. Vite phases 1-3 (2026-07-16/17, record). *Current:* in use. *Unresolved:* Vercel deploy untested (record).

### 2026-07-21 - `f30e8a7` Ratios 41-68
* *Change:* Sr 41-57, bank block Sr 58-65 (first RBI-format parser), Beta/Pledge/Free Float, header search bar. *Current:* bank extraction rewritten Oct 2026; 68 ratios defined once in `ratio_contract.py`. [B.7](../PROJECT_DOCUMENTATION.md#b-the-complete-project-history)

### 2026-07-24 -> 07-31 - QA-driven per-ratio fixes
`a82b189` Topic A qualitative + data-fetch reliability; `8b58a1c` plural CFS headings; `7dd9020` Sr 5 MSME dues; `5f6cf9a` Sr 21 ROE equity row; `003bfb8` Sr 22 ROCE Other Income; `b94a102` Sr 67 source link; `5ac4965`, `2e3971c`, `a9665f3` Sr 42 ROIC; `38b96e6` cache stampede lock; `be0d66b` thread pool; `c55197a` Interest Coverage; `198e13c` Dividend Yield tabulated notes; `1cf8562` Screener DPS fallback (not in current contract path); `33b0902`, `cfd7534` Debt-to-Equity NCI/leases; `4f596e4` live-quote polling; `7996b46` header price field; `12ef9df`, `c4bba15`, `b4e92da` FCF/OCF/capex Tata Steel; `3413f47` DSCR; `5d9bf57` "millions" plural 10x bug; `0969b67` Ask Navrist checkpoint; `5d91337` BVPS standalone; `9c8e730` Net Debt/EBITDA; `8353d9a` Cash Ratio spec audit; `71c5e42` tax-rate scoping; `2dccf49` search newly listed; `a075e25` remove fabricated qualitative data; `95ac893` Ask Navrist event reasoning; `cda0f3a`, `5ebe825`, `bd09e11`, `1320884`, `03bfdb5`, `0474e9e`, `3cbc294`, `8121e3a`, `c098e27` Sr 1-30 and cash-flow fixes, regression repair, gross-capex switch, DSCR rewrite; `a9665f3`, `c232ac1`, `5eb880b`, `c003b3b`, `bb3e94d` Sr 42/47/50/54/67.
* *Historical:* each ratio re-implemented in several places. *Current:* all fixes folded into the single contract in October. *Unresolved:* any fix not reproduced as a generic test is only protected by the October regression suites. [B.8](../PROJECT_DOCUMENTATION.md#b-the-complete-project-history), [I.1-I.2](../PROJECT_DOCUMENTATION.md#i-initial-rework-and-major-bug-fixes)

## August 2026 - Visuals, qualitative framework, LLM off

### 2026-08-03 -> 08-07 - Income-statement charts and bulk audit tooling
Sankey -> icicle diagrams, multi-year comparison, segment-revenue extraction and classification (`be0eb23` ... `fd1762b`, `cab103b`, `68a2d27`, `4e28345`); `33caf32` ~30x-wrong Total Current Assets/Liabilities on split-subtotal filings; `80cc7c6` bulk ratio-audit endpoints; `8b07ea2` precomputed-ratio refresh tool (`tools/refresh_ratios.py`). *Unresolved:* similar subtotal misreads still occur (M-2, M-4).

### 2026-08-08 -> 08-20 - Qualitative A-G (deterministic)
`3ed4efc` A.2 moats ... `4aa3d51` F.4.1; builds for B.1-B.6, C.1-C.8, D.1-D.6, E.1-E.7, F.1-F.6, G.1. *Current:* built; spec in `Navrist_Qualitative_Framework.md`; the registry catalogues A-U, H-U not built. [B.9](../PROJECT_DOCUMENTATION.md#b-the-complete-project-history)

### 2026-08-19 - `15447ed` All LLM (Groq/OpenRouter) dependencies disabled
* *Historical:* Groq 70b->8b chain, 15-90 s retry per call. *Change:* `groq_chat()` raises immediately; Ask Navrist short-circuited. *Current:* still disabled; re-enable only on explicit owner instruction.

## September 2026

### 2026-09-03 - `b6adff5` Qualitative evidence architecture, manual upload pipeline, calculation engine, Upstox scaffolding
* *Change:* `qualitative_evidence*.py`, `qualitative_task_engine.py`, `manual_document_pipeline.py`, `document_analysis_engine.py`, `ratio_calculation_engine.py`, `db/004`-`009`, `manual_mode.py`. *Unresolved at that time:* the manual engine had its own extraction/formulas (fixed Oct 8). [B.10](../PROJECT_DOCUMENTATION.md#b-the-complete-project-history), [F](../PROJECT_DOCUMENTATION.md#f-manual-document-upload-workflow)

### 2026-09-28 -> 10-01 - `4dddb64`, `ee66501` Live chart
* Live chart with technical analysis, chart patterns, pattern selector, cluster popover, zoom, full-session day replay; Axis RAPID client (UAT). [B.11](../PROJECT_DOCUMENTATION.md#b-the-complete-project-history)

## October 2026

### 2026-10-05 - Forecast system (record; uncommitted)
* `forecast/` package; pilot of 8 equities + Nifty; range forecasts validated, direction not. `docs/forecast_system.md`, `docs/forecast_validation_2026-10.md`, `docs/daily_validation_2026-10.md`. *Unresolved:* no production daily model; no scale-up beyond the pilot.

### 2026-10-07 - `6d348dc` Align ratios 1-18 to Annual Report definitions; 8 UI categories
* *Historical:* ANURAS FY26 ratios differed from the AR table (mostly basis: AR standalone vs Navrist consolidated). *Change:* Sr 1 Net Sales numerator; Sr 5 purchases note; Sr 8/31 closing WC; DOH/DSO/DPO from unrounded turnovers; `_EXTRACTION_LOGIC_VERSION` 61, extract cache v28, fact store v5. *Current:* **Sr 1 and Sr 8 reversed** by the owner in the global audit (below); the committed registry still holds the `6d348dc` text. [B.12](../PROJECT_DOCUMENTATION.md#b-the-complete-project-history)

### 2026-10-07 -> 10-08 - Ratio contract remediation, breakdowns, final validation (record; uncommitted)
* *Historical:* three engines, three definitions; unknown -> 0; rounded values reused. *Change:* `tools/ratio_contract.py` (one definition per ratio, `FORMULA_VERSION`), `tools/ratio_breakdown.py` + `CalculationBreakdown.jsx`, `tools/bank_extractor.py` / `bank_ratios.py`, `tools/company_search.py`, fact-store integrity checks, row-reader hardening, sector-based lender gating, `not_meaningful` preserved, pledge sanity; validation tools `final_validation.py`, `universe_scan.py`, `breakdown_probe.py`, `ratio_regression_probe.py`.
* *Current:* in use. Verdict recorded 2026-10-08: **NOT READY** (20/133 filings unreadable, 39 identity failures, flagged not fixed). *Unresolved:* M-16. [B.13](../PROJECT_DOCUMENTATION.md#b-the-complete-project-history)

### 2026-10-07 -> 10-09 - Global audit, formula versions 2026.10.7 -> 2026.10.13 (record; uncommitted)
| Version | Change |
|---|---|
| 2026.10.7 | COGS-based Inventory Turnover (+ Days, CCC); Cash Ratio numerator and restricted-balance classification; dividend fiscal-year attribution; extraction hygiene (page ranges, note references, units, contents pages, subtotals, cost-of-materials caption); ledger identities; version folding into cache keys; "EBIT Margin %" label |
| 2026.10.8 | Working Capital Turnover and Days WC back to **average** WC |
| 2026.10.9 | One EV definition; NCI only as a labelled reference |
| (2026.10.9 -> .12) | Equity-basis policy W (`EQUITY_BASIS`), dividend payout perimeter (policy A), banks' basis (I), discontinued operations (M), lender gating (J) - exact version of each step not recorded |
| 2026.10.13 | 68-row ANURAS audit findings (rounding removal, Total Debt Three-Part Test via Notes, pledge/free-float evidence, capex note) |
* *Reported results (HISTORICAL):* backend 489 passing, frontend 73 passing. *Observed 2026-10-09:* backend **542 passed** (63 subtests), frontend **73 passed**.
* *Current:* ANURAS audit 56 PASS / 12 NEEDS REVIEW (see audit file for a stricter 44 / 24). *Unresolved:* M-1, M-2, M-3, M-4, M-12, M-13, M-14. [J](../PROJECT_DOCUMENTATION.md#j-recent-global-audit), [K](../PROJECT_DOCUMENTATION.md#k-cross-company-validation), [M](../PROJECT_DOCUMENTATION.md#m-known-problems-and-incomplete-work)

### 2026-10-08 - One fact path for every pipeline (record; uncommitted)
* *Historical:* `is_manual_mode()` branches inside extraction; broad alias fallback only for uploads; the automatic pipeline found no ANURAS facts and differed on 6 other companies. *Change:* branches removed; `extract_line_items(symbol, fiscal_year)`; AST test; TCS owners' PAT 1.0 -> 48,553. *Current:* `tests/test_pipeline_parity.py` passes (observed). 8 of 20 company-years diverged before, 0 after (recorded). [B.15](../PROJECT_DOCUMENTATION.md#b-the-complete-project-history)

### 2026-10-08 - `c2ed624`, `86cb38f` UI
* Screener-style display labels for the first 13 ratios (internal ids unchanged); simplified ratio cards (no status badges drawn; payload unchanged). *Current:* shipped. *Unresolved:* statuses are no longer visible on the card, so a `needs_review` ratio looks like any other value unless the breakdown is opened.

### 2026-10-09 - Documentation pass (this change set)
* Added `PROJECT_DOCUMENTATION.md`, `docs/FINANCIAL_RATIO_AUDIT.md`, `docs/PROJECT_CHANGELOG.md`; no application code changed. Findings recorded as new open issues: **M-13** Bharti Airtel DPS 0 `verified`, **M-14** unextracted bank balances as 0, **M-15** broken `tests/final_validation.py`, **M-18** password in history, **M-19** live price for historical years.

---

## Release/versions snapshot (2026-10-09)

| Constant | Value |
|---|---|
| `ratio_contract.FORMULA_VERSION` | `2026.10.13` |
| `annual_report_financials._EXTRACTION_LOGIC_VERSION` | `86` |
| `fundamental_fact_store.EXTRACTION_VERSION` | `20` |
| `ratio_breakdown.BREAKDOWN_VERSION` | `2` |
| `qualitative_db._QUALITATIVE_LOGIC_VERSION` | `40` |
