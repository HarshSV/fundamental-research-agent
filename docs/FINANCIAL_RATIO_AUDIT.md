# Financial Ratio Audit Reference (68 ratios)

> Part of the Navrist documentation set: [`PROJECT_DOCUMENTATION.md`](../PROJECT_DOCUMENTATION.md) (main guide, sections G and J),
> [`PROJECT_CHANGELOG.md`](PROJECT_CHANGELOG.md) (history), [`ratio_contract.md`](ratio_contract.md) (generated formula contract),
> [`ratio_audit_matrix_2026-10.md`](ratio_audit_matrix_2026-10.md) (the raw ANURAS audit this file is built on).

**Formula version audited:** `2026.10.13` (read from `tools/ratio_contract.py`). Ratio numbering and names follow `tools/fundamental_ratio_registry.py`
(the in-repo copy of the approved 68-ratio specification).

## How to read this file - scope and honesty rules

1. **What the evidence actually is.** The detailed audit (`tests/ratio_audit_matrix.py`) ran on **one real filing: ANURAS FY2026 consolidated**
   (manual-upload pipeline, fixed price INR 1,165). For every ratio it (a) re-computed the value with a separate hand-written implementation of the
   approved formula (relative tolerance 1e-6), (b) searched each base fact in the Annual Report's own printed figures, (c) blanked each input on a synthetic
   filing to prove the ratio is withheld or falls back *flagged*, and (d) counted the tests that name the ratio. The other filings
   (17 in `tests/final_validation.py`, 133 in `tests/universe_scan.py`) were only checked for status/invariant consistency and accounting identities -
   **their values were not re-verified against an external source.**
2. **Two status columns.** "ANURAS matrix verdict" is what the audit produced (56 PASS / 12 NEEDS REVIEW / 0 FAIL).
   "Status (this document)" is stricter: a ratio that passed on ANURAS but reads an input with a known, still-open cross-company extraction defect is shown
   as NEEDS REVIEW with the reason spelled out. Nothing was upgraded.
3. **PASS never means "externally verified for every company".** It means: the formula implementation reproduces the approved formula, the ANURAS
   inputs trace to the printed Annual Report, missing inputs are not turned into numbers, and tests exist.
4. **NOT YET AUDITED** is used where no evidence has been collected. None of the 68 rows is in that state in the ANURAS matrix, but note
   that *no ratio has been source-audited across every company*.
5. **Approved formula caveat.** The registry says it was transcribed from `Ratio_Sheet_V8_patched 2.xls`. That workbook is **not in this repository**
   (newer `Ratio Sheet V*.xlsx` files exist in the user's Downloads folder, outside the repo, and were not compared). The registry text itself has been
   edited by the owner's later decisions (uncommitted working-tree changes versus `HEAD`: Sr 1 Net Sales -> COGS, Sr 8 closing -> average working
   capital, Sr 15 label OPM % -> EBIT Margin %, Sr 20/23 total equity incl. NCI, Sr 24/29/33 EPS/EBITDA wording, Sr 47 owners' perimeter, Sr 51/52 EV wording).
   "Approved formula" below means the *current working-tree registry text*; an independent comparison against the original workbook has not been done.
6. Every row's **Known discrepancy** cell is copied from the audit verdict notes plus any downgrade reason added here. Discrepancies stay open until fixed *and* tested.

## Result summary

| Status (this document) | Count |
|---|---|
| PASS | 44 |
| NEEDS REVIEW | 24 |
| FAIL | 0 |
| NOT YET AUDITED | 0 |
| **Total** | **68** |

## Summary matrix (one row per ratio)

| Sr | Ratio | ANURAS matrix verdict | Status (this document) | ANURAS engine status | ANURAS FY2026 value |
|---|---|---|---|---|---|
| 1 | Inventory Turnover | PASS | **PASS** | needs_review | 0.820305 |
| 2 | Inventory Days | PASS | **PASS** | needs_review | 444.956 |
| 3 | Receivables Turnover | NEEDS REVIEW | **NEEDS REVIEW** | needs_review | 2.79416 |
| 4 | Debtor Days | NEEDS REVIEW | **NEEDS REVIEW** | needs_review | 130.63 |
| 5 | Payables Turnover | PASS | **PASS** | needs_review | 1.94246 |
| 6 | Days Payable | PASS | **PASS** | needs_review | 187.906 |
| 7 | Asset Turnover | PASS | **PASS** | needs_review | 0.356203 |
| 8 | Working Capital Turnover | PASS | **NEEDS REVIEW** | needs_review | 2.52071 |
| 9 | Cash Conversion Cycle | NEEDS REVIEW | **NEEDS REVIEW** | needs_review | 387.68 |
| 10 | Current Ratio | PASS | **NEEDS REVIEW** | verified | 1.42519 |
| 11 | Quick Ratio | PASS | **NEEDS REVIEW** | verified | 0.746627 |
| 12 | Cash Ratio | NEEDS REVIEW | **NEEDS REVIEW** | needs_review | 0.147711 |
| 13 | Working Capital | PASS | **NEEDS REVIEW** | verified | 1,112.07 |
| 14 | Gross Profit Margin | PASS | **PASS** | verified | 44.0591 |
| 15 | EBIT Margin % | PASS | **PASS** | verified | 17.0418 |
| 16 | Net Profit Margin | PASS | **PASS** | verified | 7.19189 |
| 17 | Return on Assets (ROA) | PASS | **PASS** | needs_review | 2.56178 |
| 18 | ROE % | PASS | **PASS** | verified | 5.53046 |
| 19 | ROCE % | PASS | **NEEDS REVIEW** | needs_review | 9.1019 |
| 20 | Debt-to-Equity Ratio | PASS | **PASS** | verified | 0.403348 |
| 21 | Debt Ratio | PASS | **PASS** | verified | 0.233069 |
| 22 | Interest Coverage Ratio | PASS | **PASS** | verified | 2.71072 |
| 23 | Financial Leverage Ratio | PASS | **PASS** | needs_review | 1.72227 |
| 24 | Stock P/E | PASS | **PASS** | verified | 77.2034 |
| 25 | Price-to-Book (P/B) | PASS | **PASS** | verified | 4.01695 |
| 26 | Price-to-Sales (P/S) | PASS | **PASS** | verified | 5.60709 |
| 27 | Dividend Yield % | PASS | **NEEDS REVIEW** | verified | 0.128755 |
| 28 | Earnings Yield | PASS | **PASS** | verified | 1.29528 |
| 29 | Enterprise Value/EBITDA | PASS | **PASS** | verified | 27.1682 |
| 30 | Fixed Asset Turnover | PASS | **PASS** | needs_review | 0.869452 |
| 31 | Working Capital Days | PASS | **NEEDS REVIEW** | needs_review | 144.8 |
| 32 | Receivables-to-Payables Ratio | PASS | **PASS** | verified | 1.01465 |
| 33 | Net Debt/EBITDA | PASS | **PASS** | needs_review | 2.74286 |
| 34 | Debt Service Coverage Ratio (DSCR) | NEEDS REVIEW | **NEEDS REVIEW** | insufficient_data | - |
| 35 | Cash Flow Coverage Ratio | PASS | **PASS** | verified | 0.179025 |
| 36 | Free Cash Flow | PASS | **PASS** | verified | -220.83 |
| 37 | FCF Yield | PASS | **PASS** | verified | -1.66497 |
| 38 | FCF Margin | PASS | **PASS** | verified | -9.33562 |
| 39 | Operating Cash Flow Ratio | PASS | **NEEDS REVIEW** | needs_review | 0.127828 |
| 40 | Capex Intensity | PASS | **PASS** | verified | 23.4693 |
| 41 | OCF/Net Profit | PASS | **PASS** | verified | 1.50462 |
| 42 | Return on Invested Capital (ROIC) | PASS | **PASS** | needs_review | 5.75375 |
| 43 | Tax % | PASS | **PASS** | verified | 12.657 |
| 44 | Contribution Margin | NEEDS REVIEW | **NEEDS REVIEW** | needs_review | 38.0599 |
| 45 | EPS Growth Rate | PASS | **PASS** | verified | 77.5294 |
| 46 | Book Value per Share (BVPS) | PASS | **PASS** | verified | 290.021 |
| 47 | Dividend Payout % | PASS | **NEEDS REVIEW** | verified | 5.01878 |
| 48 | Retention Ratio | PASS | **NEEDS REVIEW** | verified | 94.9812 |
| 49 | Sustainable Growth Rate | PASS | **NEEDS REVIEW** | verified | 5.25289 |
| 50 | PEG Ratio | PASS | **PASS** | verified | 0.995796 |
| 51 | EV/Sales | PASS | **PASS** | verified | 6.23675 |
| 52 | EV/FCF | PASS | **PASS** | not_meaningful | -66.8059 |
| 53 | Price/Cash Flow | PASS | **PASS** | verified | 39.6718 |
| 54 | Graham Number | PASS | **PASS** | verified | 313.798 |
| 55 | Altman Z-Score | NEEDS REVIEW | **NEEDS REVIEW** | needs_review | 3.53741 |
| 56 | Piotroski F-Score | PASS | **NEEDS REVIEW** | verified | 7 |
| 57 | Beneish M-Score | NEEDS REVIEW | **NEEDS REVIEW** | needs_review | -1.82659 |
| 58 | Net Interest Margin (NIM) | NEEDS REVIEW | **NEEDS REVIEW** | not_applicable | - |
| 59 | CASA Ratio | NEEDS REVIEW | **NEEDS REVIEW** | not_applicable | - |
| 60 | Gross NPA % | PASS | **PASS** | not_applicable | - |
| 61 | Net NPA % | PASS | **PASS** | not_applicable | - |
| 62 | Provision Coverage Ratio (PCR) | PASS | **PASS** | not_applicable | - |
| 63 | Capital Adequacy Ratio (CRAR) | PASS | **PASS** | not_applicable | - |
| 64 | Credit-to-Deposit Ratio | NEEDS REVIEW | **NEEDS REVIEW** | not_applicable | - |
| 65 | Cost-to-Income Ratio | PASS | **PASS** | not_applicable | - |
| 66 | Beta | NEEDS REVIEW | **NEEDS REVIEW** | insufficient_data | - |
| 67 | Promoter Pledge % | PASS | **PASS** | verified | 21.79 |
| 68 | Free Float % | PASS | **PASS** | verified | 40.93 |

## Detailed matrix (one block per ratio)

### Sr 1 - Inventory Turnover (internal id `inventory_turnover`)

| Field | Detail |
|---|---|
| Category | P&L + Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Cost of Goods Sold ÷ Average Inventory |
| Actual implementation (`ratio_contract.SPEC`) | Cost of Goods Sold ÷ Average Inventory (opening + closing) ÷ 2. COGS = Cost of materials consumed + Purchases of stock-in-trade + Changes in inventories of finished goods, WIP and stock-in-trade (the P&L's own cost lines). Formal correction 2026.10.7: the earlier Net-Sales numerator (Annual Report's own definition) was retired. |
| Formula as printed in the calculation breakdown | Cost of Goods Sold ÷ Average Inventory |
| ANURAS FY2026 worked expression | ₹1,323.26 Cr ÷ ₹1,613.13 Cr |
| Required facts (read by the engine) | `cogs`, `inventory` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: average inventory; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: cogs, inventory |
| Relevant tests | 19 specific / 20 generic; e.g. `test_ar_definition_alignment.py::test_doh_dso_dpo_ccc_use_raw_turnover`, `test_ar_definition_alignment.py::test_inventory_turnover_engine_uses_cogs`, `test_ar_definition_alignment.py::test_missing_parent_stays_unavailable` |
| Cross-company run | 17 real filings run: needs_review=3, not_applicable=6, not_disclosed=2, verified=6 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | Screener has no turnover; its Inventory Days 490 = closing inventory / COGS x 365 -> same-basis Navrist 489.6 (inputs agree); Navrist averages opening |
| Warnings the engine printed on ANURAS FY2026 | Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). |
| Known discrepancy | status needs_review is the intended acquisition-year guard (balances consolidate a part-year acquisition) Corrected 2026.10.7 from Net Sales to COGS per the authoritative spec. |
| ANURAS FY2026 matrix verdict | PASS (value 0.820305, engine status `needs_review`) |
| **Status (this document)** | **PASS** |

### Sr 2 - Inventory Days (internal id `days_inventory_outstanding`)

| Field | Detail |
|---|---|
| Category | P&L + Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | 365 ÷ Inventory Turnover |
| Actual implementation (`ratio_contract.SPEC`) | 365 ÷ Inventory Turnover (unrounded). |
| Formula as printed in the calculation breakdown | 365 ÷ Inventory Turnover |
| ANURAS FY2026 worked expression | 365 ÷ 0.8203 |
| Required facts (read by the engine) | `cogs`, `inventory` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: derived; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output in days. |
| Dependencies (parent ratios) | `inventory_turnover` |
| Missing-data behaviour | withheld when missing: cogs, inventory |
| Relevant tests | 9 specific / 20 generic; e.g. `test_ar_definition_alignment.py::test_doh_dso_dpo_ccc_use_raw_turnover`, `test_ar_definition_alignment.py::test_missing_parent_stays_unavailable`, `test_full_quant_coverage.py::test_l_cogs_dependent_ratios_wired` |
| Cross-company run | 17 real filings run: needs_review=3, not_applicable=6, not_disclosed=2, verified=6 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | Screener Inventory Days 490 (closing basis) vs same-basis Navrist 489.6; native (average) 445.0 - averaging difference only. |
| Warnings the engine printed on ANURAS FY2026 | Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). / Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). |
| Known discrepancy | status needs_review is the intended acquisition-year guard (balances consolidate a part-year acquisition) |
| ANURAS FY2026 matrix verdict | PASS (value 444.956, engine status `needs_review`) |
| **Status (this document)** | **PASS** |

### Sr 3 - Receivables Turnover (internal id `receivables_turnover`)

| Field | Detail |
|---|---|
| Category | P&L + Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Net Credit Sales ÷ Average Accounts Receivable |
| Actual implementation (`ratio_contract.SPEC`) | Revenue from Operations ÷ Average Trade Receivables (net credit sales are not disclosed - revenue is a proxy, so the result is always needs_review). |
| Formula as printed in the calculation breakdown | Revenue from Operations ÷ Average Trade Receivables |
| ANURAS FY2026 worked expression | ₹2,365.45 Cr ÷ ₹846.57 Cr |
| Required facts (read by the engine) | `receivables`, `revenue` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Contains a documented proxy input (see Known discrepancy). |
| Financial period / perimeter | period basis: average receivables; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: receivables, revenue |
| Relevant tests | 5 specific / 20 generic; e.g. `test_ar_definition_alignment.py::test_doh_dso_dpo_ccc_use_raw_turnover`, `test_calculation_engine.py::test_case_j_registry_dependency_behaviour`, `test_ratio_breakdown.py::test_first_18_present_and_formula_is_the_implemented_one` |
| Cross-company run | 17 real filings run: needs_review=11, not_applicable=6 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Warnings the engine printed on ANURAS FY2026 | Net credit sales are not disclosed; Revenue from Operations is used as the proxy. / Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). |
| Known discrepancy | DEVIATION (documented, forced by disclosure): authoritative numerator is Net CREDIT Sales; credit sales are never disclosed, Revenue from operations is the proxy -> needs_review by design (policy S). |
| ANURAS FY2026 matrix verdict | NEEDS REVIEW (value 2.79416, engine status `needs_review`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 4 - Debtor Days (internal id `days_sales_outstanding`)

| Field | Detail |
|---|---|
| Category | P&L + Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | 365 ÷ Receivables Turnover |
| Actual implementation (`ratio_contract.SPEC`) | 365 ÷ Receivables Turnover (unrounded). |
| Formula as printed in the calculation breakdown | 365 ÷ Receivables Turnover |
| ANURAS FY2026 worked expression | 365 ÷ 2.7942 |
| Required facts (read by the engine) | `receivables`, `revenue` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Contains a documented proxy input (see Known discrepancy). |
| Financial period / perimeter | period basis: derived; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output in days. |
| Dependencies (parent ratios) | `receivables_turnover` |
| Missing-data behaviour | withheld when missing: receivables, revenue |
| Relevant tests | 8 specific / 20 generic; e.g. `test_ar_definition_alignment.py::test_doh_dso_dpo_ccc_use_raw_turnover`, `test_calculation_engine.py::test_case_j_registry_dependency_behaviour`, `test_global_audit_2026_10c.py::test_turnover_days_and_ccc_use_cogs` |
| Cross-company run | 17 real filings run: needs_review=11, not_applicable=6 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | Screener Debtor Days 148 (closing basis) vs same-basis Navrist 148.0; native (average) 130.6. |
| Warnings the engine printed on ANURAS FY2026 | Net credit sales are not disclosed; Revenue from Operations is used as the proxy. / Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). / Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). |
| Known discrepancy | Inherits the revenue proxy of Sr 3 (needs_review by design). |
| ANURAS FY2026 matrix verdict | NEEDS REVIEW (value 130.63, engine status `needs_review`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 5 - Payables Turnover (internal id `payables_turnover`)

| Field | Detail |
|---|---|
| Category | P&L + Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Net Purchases ÷ Average Accounts Payable |
| Actual implementation (`ratio_contract.SPEC`) | Net Purchases ÷ Average Trade Payables. Purchases = the Cost of Materials Consumed note's 'Purchases during the year' (+ Purchases of stock-in-trade); when the note line is absent Cost of Materials Consumed is a flagged proxy. |
| Formula as printed in the calculation breakdown | Purchases ÷ Average Trade Payables |
| ANURAS FY2026 worked expression | ₹1,478.12 Cr ÷ ₹760.95 Cr |
| Required facts (read by the engine) | `payables`, `purchases` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Contains a documented proxy input (see Known discrepancy). |
| Financial period / perimeter | period basis: average payables; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: payables, purchases |
| Relevant tests | 5 specific / 20 generic; e.g. `test_ar_definition_alignment.py::test_doh_dso_dpo_ccc_use_raw_turnover`, `test_ar_definition_alignment.py::test_engine_purchases_prefer_disclosed_line`, `test_full_quant_coverage.py::test_m_purchases_dependent_ratios_wired` |
| Cross-company run | 17 real filings run: needs_review=8, not_applicable=6, not_disclosed=3 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Warnings the engine printed on ANURAS FY2026 | Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). |
| Known discrepancy | status needs_review is the intended acquisition-year guard (balances consolidate a part-year acquisition) |
| ANURAS FY2026 matrix verdict | PASS (value 1.94246, engine status `needs_review`) |
| **Status (this document)** | **PASS** |

### Sr 6 - Days Payable (internal id `days_payables_outstanding`)

| Field | Detail |
|---|---|
| Category | P&L + Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | 365 ÷ Payables Turnover |
| Actual implementation (`ratio_contract.SPEC`) | 365 ÷ Payables Turnover (unrounded). |
| Formula as printed in the calculation breakdown | 365 ÷ Payables Turnover |
| ANURAS FY2026 worked expression | 365 ÷ 1.9425 |
| Required facts (read by the engine) | `payables`, `purchases` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Contains a documented proxy input (see Known discrepancy). |
| Financial period / perimeter | period basis: derived; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output in days. |
| Dependencies (parent ratios) | `payables_turnover` |
| Missing-data behaviour | withheld when missing: payables, purchases |
| Relevant tests | 6 specific / 20 generic; e.g. `test_ar_definition_alignment.py::test_doh_dso_dpo_ccc_use_raw_turnover`, `test_full_quant_coverage.py::test_m_purchases_dependent_ratios_wired`, `test_full_quant_coverage.py::test_m_purchases_proxy_is_never_verified` |
| Cross-company run | 17 real filings run: needs_review=8, not_applicable=6, not_disclosed=3 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | Screener Days Payable 261 = closing payables / COGS x 365 -> same-basis 260.8; Navrist uses purchases / average payables (187.9). |
| Warnings the engine printed on ANURAS FY2026 | Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). / Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). |
| Known discrepancy | status needs_review is the intended acquisition-year guard (balances consolidate a part-year acquisition) |
| ANURAS FY2026 matrix verdict | PASS (value 187.906, engine status `needs_review`) |
| **Status (this document)** | **PASS** |

### Sr 7 - Asset Turnover (internal id `asset_turnover`)

| Field | Detail |
|---|---|
| Category | P&L + Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Net Sales ÷ Average Total Assets |
| Actual implementation (`ratio_contract.SPEC`) | Net Sales ÷ Average Total Assets. |
| Formula as printed in the calculation breakdown | Revenue from Operations ÷ Average Total Assets |
| ANURAS FY2026 worked expression | ₹2,365.45 Cr ÷ ₹6,640.74 Cr |
| Required facts (read by the engine) | `revenue`, `total_assets` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: average assets; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: revenue, total_assets |
| Relevant tests | 3 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[asset_turnover]`, `test_ratio_remediation.py::test_no_acquisition_no_flag`, `test_ratio_remediation.py::test_part_year_consolidation_flags_balance_sensitive_ratios_without_changing_numbers` |
| Cross-company run | 17 real filings run: needs_review=1, not_applicable=6, verified=10 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Warnings the engine printed on ANURAS FY2026 | Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). |
| Known discrepancy | status needs_review is the intended acquisition-year guard (balances consolidate a part-year acquisition) |
| ANURAS FY2026 matrix verdict | PASS (value 0.356203, engine status `needs_review`) |
| **Status (this document)** | **PASS** |

### Sr 8 - Working Capital Turnover (internal id `working_capital_turnover`)

| Field | Detail |
|---|---|
| Category | P&L + Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Net Sales ÷ Average Working Capital (Current Assets − Current Liabilities) |
| Actual implementation (`ratio_contract.SPEC`) | Net Sales ÷ Average Working Capital, Working Capital = Current Assets − Current Liabilities, average = (opening + closing) ÷ 2 (authoritative 68-ratio specification; same average basis as Sr 31). Closing WC is used only when the prior year is unavailable, and the result is then flagged. Corrected in 2026.10.8 - the earlier closing-WC alignment is retired. |
| Formula as printed in the calculation breakdown | Revenue from Operations ÷ Average Working Capital |
| ANURAS FY2026 worked expression | ₹2,365.45 Cr ÷ ₹938.41 Cr |
| Required facts (read by the engine) | `revenue`, `total_current_assets`, `total_current_liabilities`, `working_capital` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: average working capital; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: revenue, working_capital |
| Relevant tests | 9 specific / 20 generic; e.g. `test_ar_definition_alignment.py::test_registry_formulas_describe_ar_definitions`, `test_ar_definition_alignment.py::test_working_capital_turnover_engine_uses_average_wc`, `test_global_audit_2026_10c.py::test_average_working_capital_denominator` |
| Cross-company run | 17 real filings run: needs_review=1, not_applicable=6, not_meaningful=2, verified=8 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Warnings the engine printed on ANURAS FY2026 | Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). |
| Known discrepancy | status needs_review is the intended acquisition-year guard (balances consolidate a part-year acquisition) Downgraded in this document: ANURAS passes, but the current-assets / current-liabilities subtotal it reads is misread on other filings (L&T FY25 TCA = 157 Cr, FY26 TCL = 45 Cr; Asian Paints FY25 TCA = 786 Cr; Bharti Airtel FY26 TCL not found). The identity layer flags these `needs_review`, but the extraction defect is open (see PROJECT_DOCUMENTATION.md section M). |
| ANURAS FY2026 matrix verdict | PASS (value 2.52071, engine status `needs_review`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 9 - Cash Conversion Cycle (internal id `cash_conversion_cycle`)

| Field | Detail |
|---|---|
| Category | P&L + Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | DSO + DOH − DPO |
| Actual implementation (`ratio_contract.SPEC`) | DSO + DOH - DPO (unrounded parents). |
| Formula as printed in the calculation breakdown | Debtor Days + Inventory Days − Days Payable |
| ANURAS FY2026 worked expression | 130.6296 + 444.9565 − 187.9060 |
| Required facts (read by the engine) | `cogs`, `inventory`, `payables`, `purchases`, `receivables`, `revenue` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: derived; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output in days. |
| Dependencies (parent ratios) | `days_sales_outstanding`, `days_inventory_outstanding`, `days_payables_outstanding` |
| Missing-data behaviour | withheld when missing: cogs, inventory, payables, purchases, receivables, revenue |
| Relevant tests | 7 specific / 20 generic; e.g. `test_full_quant_coverage.py::test_m_purchases_proxy_is_never_verified`, `test_global_audit_2026_10c.py::test_turnover_days_and_ccc_use_cogs`, `test_ratio_breakdown.py::test_ccc_shows_all_three_unrounded_parents` |
| Cross-company run | 17 real filings run: needs_review=8, not_applicable=6, not_disclosed=3 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | Screener CCC 377 = 148 + 490 - 261 -> same-basis 377.0; native 387.7. |
| Warnings the engine printed on ANURAS FY2026 | Net credit sales are not disclosed; Revenue from Operations is used as the proxy. / Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). / Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). |
| Known discrepancy | Inherits the receivables proxy (needs_review by design); Inventory Days now COGS-based. |
| ANURAS FY2026 matrix verdict | NEEDS REVIEW (value 387.68, engine status `needs_review`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 10 - Current Ratio (internal id `current_ratio`)

| Field | Detail |
|---|---|
| Category | Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Current Assets ÷ Current Liabilities |
| Actual implementation (`ratio_contract.SPEC`) | Total Current Assets ÷ Total Current Liabilities. |
| Formula as printed in the calculation breakdown | Total Current Assets ÷ Total Current Liabilities |
| ANURAS FY2026 worked expression | ₹3,727.51 Cr ÷ ₹2,615.44 Cr |
| Required facts (read by the engine) | `total_current_assets`, `total_current_liabilities` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: closing; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: total_current_assets, total_current_liabilities |
| Relevant tests | 16 specific / 20 generic; e.g. `test_calculation_engine.py::test_case_a_shared_factset_no_re_extraction`, `test_calculation_engine.py::test_case_b_consolidated_propagates_to_all_ratios`, `test_calculation_engine.py::test_case_c_standalone_propagates_consistently` |
| Cross-company run | 17 real filings run: needs_review=2, not_applicable=6, verified=9 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | Downgraded in this document: ANURAS passes, but the current-assets / current-liabilities subtotal it reads is misread on other filings (L&T FY25 TCA = 157 Cr, FY26 TCL = 45 Cr; Asian Paints FY25 TCA = 786 Cr; Bharti Airtel FY26 TCL not found). The identity layer flags these `needs_review`, but the extraction defect is open (see PROJECT_DOCUMENTATION.md section M). |
| ANURAS FY2026 matrix verdict | PASS (value 1.42519, engine status `verified`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 11 - Quick Ratio (internal id `quick_ratio`)

| Field | Detail |
|---|---|
| Category | Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | (Current Assets − Inventory) ÷ Current Liabilities |
| Actual implementation (`ratio_contract.SPEC`) | (Total Current Assets - Inventories) ÷ Total Current Liabilities. |
| Formula as printed in the calculation breakdown | (Total Current Assets − Inventories) ÷ Total Current Liabilities |
| ANURAS FY2026 worked expression | ₹1,952.76 Cr ÷ ₹2,615.44 Cr |
| Required facts (read by the engine) | `inventory`, `total_current_assets`, `total_current_liabilities` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: closing; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: inventory, total_current_assets, total_current_liabilities |
| Relevant tests | 2 specific / 20 generic; e.g. `test_ratio_breakdown.py::test_composite_numerators_are_decomposed`, `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[quick_ratio]` |
| Cross-company run | 17 real filings run: needs_review=2, not_applicable=6, verified=9 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | Downgraded in this document: ANURAS passes, but the current-assets / current-liabilities subtotal it reads is misread on other filings (L&T FY25 TCA = 157 Cr, FY26 TCL = 45 Cr; Asian Paints FY25 TCA = 786 Cr; Bharti Airtel FY26 TCL not found). The identity layer flags these `needs_review`, but the extraction defect is open (see PROJECT_DOCUMENTATION.md section M). |
| ANURAS FY2026 matrix verdict | PASS (value 0.746627, engine status `verified`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 12 - Cash Ratio (internal id `cash_ratio`)

| Field | Detail |
|---|---|
| Category | Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | (Cash + Cash Equivalents) ÷ Current Liabilities |
| Actual implementation (`ratio_contract.SPEC`) | (Cash & Cash Equivalents + unrestricted Other Bank Balances) ÷ Total Current Liabilities. Other Bank Balances count when the note shows they are unrestricted: restricted lines (unclaimed dividend, earmarked, margin money, lien-marked deposits) are excluded; a line of unstated nature is included but needs_review; an undisclosed split keeps the line, needs_review, with an explicit limitation. Separate from the Cash (cash & equivalents only) used by Net debt / EV / EV multiples. |
| Formula as printed in the calculation breakdown | (Cash and Cash Equivalents + Unrestricted Other Bank Balances) ÷ Total Current Liabilities |
| ANURAS FY2026 worked expression | ₹386.33 Cr ÷ ₹2,615.44 Cr |
| Required facts (read by the engine) | `cash`, `other_bank_balances`, `total_current_liabilities` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: closing; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: cash, total_current_liabilities; blanking these on the synthetic filing left the value unchanged (not material to that synthetic case): other_bank_balances |
| Relevant tests | 8 specific / 20 generic; e.g. `test_full_quant_coverage.py::test_w_missing_never_zero`, `test_global_audit_2026_10c.py::test_cash_plus_current_other_bank_balances`, `test_global_audit_2026_10c.py::test_formula_extraction_and_fact_versions_each_change_the_ratio_cache_key` |
| Cross-company run | 17 real filings run: needs_review=4, not_applicable=6, verified=7 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Warnings the engine printed on ANURAS FY2026 | Restricted / lien-marked balances of 7.30 Cr were excluded from the numerator. / 7.61 Cr of other bank balances sits on a line whose nature the note does not state (e.g. 'Deposit account'); no restriction is disclosed so it is included, but it is not confirmed as free cash. |
| Known discrepancy | DEVIATION (user-directed extension, policy N): authoritative (Cash + Cash Equivalents); implementation adds UNRESTRICTED current other bank balances. 'Deposit account' (INR 7.61 Cr) has no stated nature -> needs_review. |
| ANURAS FY2026 matrix verdict | NEEDS REVIEW (value 0.147711, engine status `needs_review`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 13 - Working Capital (internal id `working_capital`)

| Field | Detail |
|---|---|
| Category | Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Current Assets − Current Liabilities |
| Actual implementation (`ratio_contract.SPEC`) | Total Current Assets - Total Current Liabilities. |
| Formula as printed in the calculation breakdown | Total Current Assets − Total Current Liabilities |
| ANURAS FY2026 worked expression | ₹3,727.51 Cr − ₹2,615.44 Cr |
| Required facts (read by the engine) | `total_current_assets`, `total_current_liabilities` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: closing; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) |
| Relevant tests | 2 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[working_capital]`, `test_ratio_remediation.py::test_every_computable_key_has_exactly_one_registry_entry_and_spec` |
| Cross-company run | 17 real filings run: needs_review=2, not_applicable=6, verified=9 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | Downgraded in this document: ANURAS passes, but the current-assets / current-liabilities subtotal it reads is misread on other filings (L&T FY25 TCA = 157 Cr, FY26 TCL = 45 Cr; Asian Paints FY25 TCA = 786 Cr; Bharti Airtel FY26 TCL not found). The identity layer flags these `needs_review`, but the extraction defect is open (see PROJECT_DOCUMENTATION.md section M). |
| ANURAS FY2026 matrix verdict | PASS (value 1,112.07, engine status `verified`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 14 - Gross Profit Margin (internal id `gross_profit_margin`)

| Field | Detail |
|---|---|
| Category | P&L |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Gross Profit ÷ Revenue |
| Actual implementation (`ratio_contract.SPEC`) | (Revenue - COGS) ÷ Revenue; COGS = Cost of materials consumed + Purchases of stock-in-trade + Changes in inventories. |
| Formula as printed in the calculation breakdown | (Gross Profit ÷ Revenue from Operations) × 100 |
| ANURAS FY2026 worked expression | (₹1,042.20 Cr ÷ ₹2,365.45 Cr) × 100 |
| Required facts (read by the engine) | `cogs`, `revenue` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: flow; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: cogs, revenue |
| Relevant tests | 4 specific / 20 generic; e.g. `test_full_quant_coverage.py::test_cogs_absent_never_fabricated`, `test_full_quant_coverage.py::test_l_cogs_dependent_ratios_wired`, `test_ratio_breakdown.py::test_composite_numerators_are_decomposed` |
| Cross-company run | 17 real filings run: not_applicable=6, not_disclosed=2, verified=9 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | Not provided by Screener (COGS = materials + purchases + change in inventories ties to the AR P&L: 14,420.07 - 1,187.51 million). |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 44.0591, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 15 - EBIT Margin % (internal id `operating_profit_margin`)

| Field | Detail |
|---|---|
| Category | P&L |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Operating Profit (EBIT) ÷ Revenue |
| Actual implementation (`ratio_contract.SPEC`) | EBIT ÷ Revenue; EBIT = Profit Before Tax + Finance Costs (Other Income included - same EBIT everywhere). |
| Formula as printed in the calculation breakdown | (Operating Profit ÷ Revenue from Operations) × 100 |
| ANURAS FY2026 worked expression | (₹403.12 Cr ÷ ₹2,365.45 Cr) × 100 |
| Required facts (read by the engine) | `ebit`, `finance_costs`, `pbt`, `revenue` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: flow; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: ebit, revenue; blanking these on the synthetic filing left the value unchanged (not material to that synthetic case): finance_costs, pbt |
| Relevant tests | 5 specific / 20 generic; e.g. `test_calculation_engine.py::test_case_g_derived_facts_computed_once_and_reused`, `test_global_audit_2026_10c.py::test_sr15_is_labelled_as_what_it_computes`, `test_ratio_breakdown.py::test_composite_numerators_are_decomposed` |
| Cross-company run | 17 real filings run: needs_review=1, not_applicable=6, verified=10 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | Screener OPM 22% is operating profit before D&A excl. other income (a different metric: (EBITDA - other income)/sales = 22.2%); Navrist EBIT margin 17 |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 17.0418, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 16 - Net Profit Margin (internal id `net_profit_margin`)

| Field | Detail |
|---|---|
| Category | P&L |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Net Income ÷ Revenue |
| Actual implementation (`ratio_contract.SPEC`) | Owners'-attributable Profit After Tax ÷ Revenue from Operations (PERIMETER_POLICY['npm']). |
| Formula as printed in the calculation breakdown | (Profit for the Year Attributable to Owners of the Company ÷ Revenue from Operations) × 100 |
| ANURAS FY2026 worked expression | (₹170.12 Cr ÷ ₹2,365.45 Cr) × 100 |
| Required facts (read by the engine) | `pat`, `revenue` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: flow; perimeter: owners (policy) |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: pat, revenue |
| Relevant tests | 7 specific / 20 generic; e.g. `test_calculation_engine.py::test_case_b_consolidated_propagates_to_all_ratios`, `test_calculation_engine.py::test_case_c_standalone_propagates_consistently`, `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[net_profit_margin]` |
| Cross-company run | 17 real filings run: needs_review=4, not_applicable=6, verified=7 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | Screener Net Profit 222 = whole-entity PAT (222.199) -> whole-entity NPM 9.39%; Navrist NPM uses owners' PAT 170.121 (7.19%) by policy. |
| Warnings the engine printed on ANURAS FY2026 | Perimeter: owners' profit over 100%-consolidated revenue (NCI share of profit excluded). |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 7.19189, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 17 - Return on Assets (ROA) (internal id `roa`)

| Field | Detail |
|---|---|
| Category | P&L + Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Net Income ÷ Average Total Assets |
| Actual implementation (`ratio_contract.SPEC`) | Owners'-attributable Profit After Tax ÷ Average Total Assets (PERIMETER_POLICY['roa']). |
| Formula as printed in the calculation breakdown | (Profit After Tax ÷ Average Total Assets) × 100 |
| ANURAS FY2026 worked expression | (₹170.12 Cr ÷ ₹6,640.74 Cr) × 100 |
| Required facts (read by the engine) | `pat`, `total_assets` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: average assets; perimeter: owners (policy); equity basis: none |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: pat, total_assets |
| Relevant tests | 8 specific / 20 generic; e.g. `test_calculation_engine.py::test_case_a_shared_factset_no_re_extraction`, `test_calculation_engine.py::test_case_b_consolidated_propagates_to_all_ratios`, `test_calculation_engine.py::test_case_c_standalone_propagates_consistently` |
| Cross-company run | 17 real filings run: needs_review=5, verified=12 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | Not provided by Screener. |
| Warnings the engine printed on ANURAS FY2026 | Perimeter: owners' profit over whole-entity assets (assets include NCI-funded assets). / Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). |
| Known discrepancy | status needs_review is the intended acquisition-year guard (balances consolidate a part-year acquisition) |
| ANURAS FY2026 matrix verdict | PASS (value 2.56178, engine status `needs_review`) |
| **Status (this document)** | **PASS** |

### Sr 18 - ROE % (internal id `roe`)

| Field | Detail |
|---|---|
| Category | P&L + Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Net Income ÷ Average Shareholders' Equity |
| Actual implementation (`ratio_contract.SPEC`) | Owners'-attributable PAT ÷ Average Owners' Equity (EQUITY_BASIS = owners_equity; never calculated on negative equity). |
| Formula as printed in the calculation breakdown | (Profit After Tax ÷ Average Total Equity) × 100 |
| ANURAS FY2026 worked expression | (₹170.12 Cr ÷ ₹3,076.08 Cr) × 100 |
| Required facts (read by the engine) | `equity`, `pat` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: average equity; perimeter: owners; equity basis: owners_equity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: equity, pat |
| Relevant tests | 13 specific / 20 generic; e.g. `test_global_audit_2026_10c.py::test_basis_is_stamped_on_the_result`, `test_global_audit_2026_10c.py::test_numbers_follow_the_declared_basis_when_nci_is_material`, `test_global_audit_2026_10c.py::test_retention_and_sustainable_growth_follow_the_owners_payout` |
| Cross-company run | 17 real filings run: needs_review=3, not_applicable=6, not_meaningful=1, verified=7 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | Screener ROE 5.55% vs Navrist 5.53% (-0.4%). |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 5.53046, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 19 - ROCE % (internal id `roce`)

| Field | Detail |
|---|---|
| Category | P&L + Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | EBIT ÷ Average Capital Employed |
| Actual implementation (`ratio_contract.SPEC`) | EBIT ÷ Average Capital Employed; Capital Employed = Total Assets - Total Current Liabilities. |
| Formula as printed in the calculation breakdown | (EBIT ÷ Average Capital Employed) × 100 |
| ANURAS FY2026 worked expression | (₹403.12 Cr ÷ ₹4,428.92 Cr) × 100 |
| Required facts (read by the engine) | `capital_employed`, `ebit`, `finance_costs`, `pbt`, `total_assets`, `total_current_liabilities` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: average capital employed; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: capital_employed, ebit; blanking these on the synthetic filing left the value unchanged (not material to that synthetic case): finance_costs, pbt |
| Relevant tests | 4 specific / 20 generic; e.g. `test_calculation_engine.py::test_case_g_derived_facts_computed_once_and_reused`, `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[roce]`, `test_ratio_remediation.py::test_opm_roce_interest_coverage_share_the_same_ebit` |
| Cross-company run | 17 real filings run: needs_review=2, not_applicable=6, verified=9 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | Screener ROCE 7% uses equity+borrowings capital employed; Navrist = EBIT / avg(Total assets - current liabilities) = 9.10% (definition difference). |
| Warnings the engine printed on ANURAS FY2026 | Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). |
| Known discrepancy | status needs_review is the intended acquisition-year guard (balances consolidate a part-year acquisition) Downgraded in this document: ANURAS passes, but the current-assets / current-liabilities subtotal it reads is misread on other filings (L&T FY25 TCA = 157 Cr, FY26 TCL = 45 Cr; Asian Paints FY25 TCA = 786 Cr; Bharti Airtel FY26 TCL not found). The identity layer flags these `needs_review`, but the extraction defect is open (see PROJECT_DOCUMENTATION.md section M). |
| ANURAS FY2026 matrix verdict | PASS (value 9.1019, engine status `needs_review`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 20 - Debt-to-Equity Ratio (internal id `debt_to_equity`)

| Field | Detail |
|---|---|
| Category | Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Total Debt ÷ Total Equity (incl. NCI) |
| Actual implementation (`ratio_contract.SPEC`) | Total Debt ÷ Total Equity incl. NCI (whole-entity debt over whole-entity equity; EQUITY_BASIS = total_equity_incl_nci). |
| Formula as printed in the calculation breakdown | Total Debt ÷ Total Equity incl. Non-Controlling Interests |
| ANURAS FY2026 worked expression | ₹1,867.49 Cr ÷ ₹4,629.96 Cr |
| Required facts (read by the engine) | `equity`, `equity_full`, `nci`, `total_debt` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: closing; perimeter: whole_entity; equity basis: total_equity_incl_nci |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: equity_full, total_debt |
| Relevant tests | 10 specific / 20 generic; e.g. `test_calculation_engine.py::test_case_b_consolidated_propagates_to_all_ratios`, `test_calculation_engine.py::test_case_c_standalone_propagates_consistently`, `test_calculation_engine.py::test_case_f_different_basis_no_contamination` |
| Cross-company run | 17 real filings run: needs_review=3, not_applicable=6, not_meaningful=1, verified=7 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | Screener Borrowings 1,867 = Navrist Total Debt 1,867.49 (inputs agree); Screener equity 3,302 (owners) -> 0.57 vs Navrist 0.40 on total equity incl. N |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 0.403348, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 21 - Debt Ratio (internal id `debt_ratio`)

| Field | Detail |
|---|---|
| Category | Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Total Debt ÷ Total Assets |
| Actual implementation (`ratio_contract.SPEC`) | Total Debt ÷ Total Assets. |
| Formula as printed in the calculation breakdown | Total Debt ÷ Total Assets |
| ANURAS FY2026 worked expression | ₹1,867.49 Cr ÷ ₹8,012.60 Cr |
| Required facts (read by the engine) | `total_assets`, `total_debt` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: closing; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: total_assets, total_debt |
| Relevant tests | 3 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[debt_ratio]`, `test_ratio_remediation.py::test_debt_above_total_assets_is_flagged_not_verified`, `test_ratio_remediation.py::test_every_debt_ratio_consumes_the_one_total_debt_fact` |
| Cross-company run | 17 real filings run: needs_review=3, not_applicable=6, verified=8 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 0.233069, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 22 - Interest Coverage Ratio (internal id `interest_coverage_ratio`)

| Field | Detail |
|---|---|
| Category | P&L |
| Approved formula (`tools/fundamental_ratio_registry.py`) | EBIT ÷ Interest Expense |
| Actual implementation (`ratio_contract.SPEC`) | EBIT ÷ Finance Costs (gross). |
| Formula as printed in the calculation breakdown | EBIT ÷ Interest Expense |
| ANURAS FY2026 worked expression | ₹403.12 Cr ÷ ₹148.71 Cr |
| Required facts (read by the engine) | `ebit`, `finance_costs`, `pbt` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: flow; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: ebit, finance_costs; blanking these on the synthetic filing left the value unchanged (not material to that synthetic case): pbt |
| Relevant tests | 3 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[interest_coverage_ratio]`, `test_ratio_remediation.py::test_missing_inputs_never_become_computed_zeros_elsewhere`, `test_ratio_remediation.py::test_opm_roce_interest_coverage_share_the_same_ebit` |
| Cross-company run | 17 real filings run: needs_review=1, not_applicable=6, verified=10 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 2.71072, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 23 - Financial Leverage Ratio (internal id `financial_leverage_ratio`)

| Field | Detail |
|---|---|
| Category | Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Average Total Assets ÷ Average Total Equity (incl. NCI) |
| Actual implementation (`ratio_contract.SPEC`) | Average Total Assets ÷ Average Total Equity incl. NCI. |
| Formula as printed in the calculation breakdown | Average Total Assets ÷ Average Total Equity incl. Non-Controlling Interests |
| ANURAS FY2026 worked expression | ₹6,640.74 Cr ÷ ₹3,855.81 Cr |
| Required facts (read by the engine) | `equity`, `equity_full`, `nci`, `total_assets` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: average; perimeter: whole_entity; equity basis: total_equity_incl_nci |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: equity_full, total_assets |
| Relevant tests | 3 specific / 20 generic; e.g. `test_global_audit_2026_10c.py::test_numbers_follow_the_declared_basis_when_nci_is_material`, `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[financial_leverage_ratio]`, `test_ratio_remediation.py::test_debt_to_equity_and_leverage_use_total_equity_including_nci` |
| Cross-company run | 17 real filings run: needs_review=1, not_applicable=6, not_meaningful=1, verified=9 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Warnings the engine printed on ANURAS FY2026 | Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). |
| Known discrepancy | status needs_review is the intended acquisition-year guard (balances consolidate a part-year acquisition) |
| ANURAS FY2026 matrix verdict | PASS (value 1.72227, engine status `needs_review`) |
| **Status (this document)** | **PASS** |

### Sr 24 - Stock P/E (internal id `pe_ratio`)

| Field | Detail |
|---|---|
| Category | Market / Valuation |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Market Price per Share ÷ Basic EPS (owners) |
| Actual implementation (`ratio_contract.SPEC`) | Market Price ÷ Basic EPS attributable to owners. |
| Formula as printed in the calculation breakdown | Market price ÷ Basic EPS attributable to owners |
| ANURAS FY2026 worked expression | ₹1,165.00 ÷ ₹15.09 |
| Required facts (read by the engine) | `eps` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Market price: `tools/market_price.get_live_price` (Angel One live quote, yfinance fallback) - a live quote taken at calculation time (`as_of = "live quote"`), not the price on the fiscal-year end. |
| Financial period / perimeter | period basis: price / FY EPS; perimeter: owners |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Share counts and per-share values kept in absolute shares / Rs per share; market cap = price x shares / 1e7 -> Crore. Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: eps |
| Relevant tests | 10 specific / 20 generic; e.g. `test_calculation_engine.py::test_case_h_market_data_only_when_required`, `test_final_validation_regressions.py::test_bank_core_parsed_shape_runs_through_the_contract`, `test_final_validation_regressions.py::test_not_meaningful_without_a_number_is_not_disclosed_never` |
| Cross-company run | 17 real filings run: needs_review=3, not_meaningful=1, verified=13 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | Screener P/E 72.1 at its price; Navrist 77.2 at the fixed audit price 1,165 and AR EPS 15.09 (Screener EPS 14.94). |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 77.2034, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 25 - Price-to-Book (P/B) (internal id `pb_ratio`)

| Field | Detail |
|---|---|
| Category | Market / Valuation |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Market Price per Share ÷ Book Value per Share |
| Actual implementation (`ratio_contract.SPEC`) | Market Price ÷ BVPS (the single BVPS of Sr 46). |
| Formula as printed in the calculation breakdown | Market price ÷ Book Value per Share |
| ANURAS FY2026 worked expression | ₹1,165.00 ÷ ₹290.02 |
| Required facts (read by the engine) | `bvps`, `equity`, `shares_outstanding` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Market price: `tools/market_price.get_live_price` (Angel One live quote, yfinance fallback) - a live quote taken at calculation time (`as_of = "live quote"`), not the price on the fiscal-year end. |
| Financial period / perimeter | period basis: price / closing BVPS; perimeter: owners; equity basis: owners_equity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Share counts and per-share values kept in absolute shares / Rs per share; market cap = price x shares / 1e7 -> Crore. Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: bvps |
| Relevant tests | 4 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[pb_ratio]`, `test_ratio_remediation.py::test_market_dependent_ratios_without_a_price_are_unavailable_not_stale`, `test_ratio_remediation.py::test_price_to_book_uses_the_single_bvps` |
| Cross-company run | 17 real filings run: needs_review=1, not_disclosed=1, not_meaningful=1, verified=14 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 4.01695, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 26 - Price-to-Sales (P/S) (internal id `ps_ratio`)

| Field | Detail |
|---|---|
| Category | Market / Valuation |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Market Cap ÷ Total Revenue |
| Actual implementation (`ratio_contract.SPEC`) | Market Cap ÷ Revenue from Operations. |
| Formula as printed in the calculation breakdown | Market Capitalisation ÷ Revenue from Operations |
| ANURAS FY2026 worked expression | ₹13,263.33 Cr ÷ ₹2,365.45 Cr |
| Required facts (read by the engine) | `revenue`, `shares_outstanding` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Market price: `tools/market_price.get_live_price` (Angel One live quote, yfinance fallback) - a live quote taken at calculation time (`as_of = "live quote"`), not the price on the fiscal-year end. |
| Financial period / perimeter | period basis: mcap / FY revenue; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Share counts and per-share values kept in absolute shares / Rs per share; market cap = price x shares / 1e7 -> Crore. Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: revenue, shares_outstanding |
| Relevant tests | 2 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[ps_ratio]`, `test_ratio_remediation.py::test_market_dependent_ratios_without_a_price_are_unavailable_not_stale` |
| Cross-company run | 17 real filings run: needs_review=3, not_applicable=6, not_disclosed=1, verified=7 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 5.60709, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 27 - Dividend Yield % (internal id `dividend_yield`)

| Field | Detail |
|---|---|
| Category | Market / Valuation |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Dividend per Share ÷ Market Price per Share |
| Actual implementation (`ratio_contract.SPEC`) | DPS ÷ Market Price; DPS = interim/special dividend declared during the FY + final dividend recommended for the FY. |
| Formula as printed in the calculation breakdown | (Dividend per Share ÷ Market price) × 100 |
| ANURAS FY2026 worked expression | (₹1.50 ÷ ₹1,165.00) × 100 |
| Required facts (read by the engine) | `dps` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Market price: `tools/market_price.get_live_price` (Angel One live quote, yfinance fallback) - a live quote taken at calculation time (`as_of = "live quote"`), not the price on the fiscal-year end. |
| Financial period / perimeter | period basis: price / FY DPS; perimeter: owners |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Share counts and per-share values kept in absolute shares / Rs per share; market cap = price x shares / 1e7 -> Crore. Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: dps |
| Relevant tests | 8 specific / 20 generic; e.g. `test_calculation_engine.py::test_case_d_missing_fact_correct_status_never_zero`, `test_final_validation_regressions.py::test_bank_core_parsed_shape_runs_through_the_contract`, `test_final_validation_regressions.py::test_dividend_inputs_unknown_means_unavailable` |
| Cross-company run | 17 real filings run: not_disclosed=3, verified=14 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | Not on Screener's annual table; DPS 1.50 = final dividend recommended for FY26 (interim 0.75 belongs to FY25 per the AR). |
| Warnings the engine printed on ANURAS FY2026 | interim=[], special=[], final(recommended)=[1.5] |
| Known discrepancy | Downgraded in this document: on Bharti Airtel FY2026 the DPS fact came out 0.0 / `verified` (tag `no_dividend_statement`) although the Annual Report recommends INR 24 per share (the rupee glyph is printed as 'H' in that PDF). Unknown/other-glyph dividends must not become zero - open issue M-13. |
| ANURAS FY2026 matrix verdict | PASS (value 0.128755, engine status `verified`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 28 - Earnings Yield (internal id `earnings_yield`)

| Field | Detail |
|---|---|
| Category | Market / Valuation |
| Approved formula (`tools/fundamental_ratio_registry.py`) | EPS ÷ Market Price per Share |
| Actual implementation (`ratio_contract.SPEC`) | Basic EPS (owners) ÷ Market Price (unrounded). |
| Formula as printed in the calculation breakdown | (Basic EPS attributable to owners ÷ Market price) × 100 |
| ANURAS FY2026 worked expression | (₹15.09 ÷ ₹1,165.00) × 100 |
| Required facts (read by the engine) | `eps` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Market price: `tools/market_price.get_live_price` (Angel One live quote, yfinance fallback) - a live quote taken at calculation time (`as_of = "live quote"`), not the price on the fiscal-year end. |
| Financial period / perimeter | period basis: derived; perimeter: owners |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Share counts and per-share values kept in absolute shares / Rs per share; market cap = price x shares / 1e7 -> Crore. Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: eps |
| Relevant tests | 4 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[earnings_yield]`, `test_ratio_remediation.py::test_earnings_yield_is_eps_over_price_not_100_over_rounded_pe`, `test_ratio_remediation.py::test_market_dependent_ratios_without_a_price_are_unavailable_not_stale` |
| Cross-company run | 17 real filings run: needs_review=3, verified=14 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 1.29528, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 29 - Enterprise Value/EBITDA (internal id `ev_to_ebitda`)

| Field | Detail |
|---|---|
| Category | Market / Valuation |
| Approved formula (`tools/fundamental_ratio_registry.py`) | (Market Cap + Debt − Cash) ÷ EBITDA (EBIT + D&A) |
| Actual implementation (`ratio_contract.SPEC`) | (Market Cap + Total Debt - Cash & Cash Equivalents) ÷ EBITDA (EBIT + D&A) - the authoritative specification, and the ONE Enterprise Value definition used by Sr 29, 51 and 52. Non-controlling interest is NOT added (corrected 2026.10.8); a separately labelled 'EV incl. NCI' reference figure is carried alongside for consolidated entities with NCI but never feeds a ratio. |
| Formula as printed in the calculation breakdown | Enterprise Value ÷ EBITDA |
| ANURAS FY2026 worked expression | ₹14,752.75 Cr ÷ ₹543.02 Cr |
| Required facts (read by the engine) | `cash`, `depreciation`, `ebitda`, `finance_costs`, `nci`, `pbt`, `shares_outstanding`, `total_debt` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Market price: `tools/market_price.get_live_price` (Angel One live quote, yfinance fallback) - a live quote taken at calculation time (`as_of = "live quote"`), not the price on the fiscal-year end. |
| Financial period / perimeter | period basis: closing debt/cash; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Share counts and per-share values kept in absolute shares / Rs per share; market cap = price x shares / 1e7 -> Crore. Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: cash, ebitda, shares_outstanding, total_debt; blanking these on the synthetic filing left the value unchanged (not material to that synthetic case): nci |
| Relevant tests | 12 specific / 20 generic; e.g. `test_global_audit_2026_10c.py::test_consolidated_ev_with_nci_is_a_separate_labelled_reference`, `test_global_audit_2026_10c.py::test_ev_is_the_same_number_in_all_three_multiples`, `test_global_audit_2026_10c.py::test_nci_never_changes_the_multiple_status_or_warnings` |
| Cross-company run | 17 real filings run: needs_review=7, not_applicable=6, not_disclosed=1, verified=3 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 27.1682, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 30 - Fixed Asset Turnover (internal id `fixed_asset_turnover`)

| Field | Detail |
|---|---|
| Category | P&L + Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Net Sales ÷ Average Net Fixed Assets (PPE + ROU + CWIP + Intangibles) |
| Actual implementation (`ratio_contract.SPEC`) | Net Sales ÷ Average Net Fixed Assets; Net Fixed Assets = PPE + Right-of-use assets + Capital WIP + Intangibles (goodwill excluded). |
| Formula as printed in the calculation breakdown | Revenue from Operations ÷ Average Net Fixed Assets |
| ANURAS FY2026 worked expression | ₹2,365.45 Cr ÷ ₹2,720.63 Cr |
| Required facts (read by the engine) | `cwip`, `intangibles`, `net_fixed_assets`, `ppe`, `revenue`, `rou_assets` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: average net fixed assets; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: net_fixed_assets, revenue |
| Relevant tests | 2 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[fixed_asset_turnover]`, `test_ratio_remediation.py::test_net_fixed_assets_is_ppe_rou_cwip_intangibles_excluding_goodwill` |
| Cross-company run | 17 real filings run: needs_review=1, not_applicable=6, verified=10 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Warnings the engine printed on ANURAS FY2026 | Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). |
| Known discrepancy | status needs_review is the intended acquisition-year guard (balances consolidate a part-year acquisition) |
| ANURAS FY2026 matrix verdict | PASS (value 0.869452, engine status `needs_review`) |
| **Status (this document)** | **PASS** |

### Sr 31 - Working Capital Days (internal id `days_working_capital`)

| Field | Detail |
|---|---|
| Category | P&L + Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | (Average Working Capital ÷ Revenue) × 365 |
| Actual implementation (`ratio_contract.SPEC`) | (Average Working Capital ÷ Revenue) × 365 (authoritative spec; closing WC only when the prior year is missing). |
| Formula as printed in the calculation breakdown | (Average Working Capital ÷ Revenue from Operations) × 365 |
| ANURAS FY2026 worked expression | (₹938.41 Cr ÷ ₹2,365.45 Cr) × 365 |
| Required facts (read by the engine) | `revenue`, `total_current_assets`, `total_current_liabilities`, `working_capital` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: average working capital; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output in days. |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: revenue, working_capital |
| Relevant tests | 4 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[days_working_capital]`, `test_ratio_remediation.py::test_days_working_capital_falls_back_to_closing_only_flagged`, `test_ratio_remediation.py::test_days_working_capital_is_average_wc_over_revenue_times_365` |
| Cross-company run | 17 real filings run: needs_review=1, not_applicable=6, verified=10 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | Screener Working Capital Days 108 uses an undisclosed definition (not reproducible from the statements); Navrist (avg WC / revenue x 365) = 144.8. |
| Warnings the engine printed on ANURAS FY2026 | Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). |
| Known discrepancy | status needs_review is the intended acquisition-year guard (balances consolidate a part-year acquisition) Downgraded in this document: ANURAS passes, but the current-assets / current-liabilities subtotal it reads is misread on other filings (L&T FY25 TCA = 157 Cr, FY26 TCL = 45 Cr; Asian Paints FY25 TCA = 786 Cr; Bharti Airtel FY26 TCL not found). The identity layer flags these `needs_review`, but the extraction defect is open (see PROJECT_DOCUMENTATION.md section M). |
| ANURAS FY2026 matrix verdict | PASS (value 144.8, engine status `needs_review`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 32 - Receivables-to-Payables Ratio (internal id `receivables_to_payables`)

| Field | Detail |
|---|---|
| Category | Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Trade Receivables ÷ Trade Payables |
| Actual implementation (`ratio_contract.SPEC`) | Trade Receivables ÷ Trade Payables. |
| Formula as printed in the calculation breakdown | Trade Receivables ÷ Trade Payables |
| ANURAS FY2026 worked expression | ₹959.38 Cr ÷ ₹945.53 Cr |
| Required facts (read by the engine) | `payables`, `receivables` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: closing; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: payables, receivables |
| Relevant tests | 1 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[receivables_to_payables]` |
| Cross-company run | 17 real filings run: needs_review=2, not_applicable=6, not_disclosed=1, verified=8 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 1.01465, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 33 - Net Debt/EBITDA (internal id `net_debt_to_ebitda`)

| Field | Detail |
|---|---|
| Category | P&L + Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | (Total Debt − Cash) ÷ EBITDA (EBIT + D&A) |
| Actual implementation (`ratio_contract.SPEC`) | (Total Debt - Cash & Cash Equivalents) ÷ EBITDA. |
| Formula as printed in the calculation breakdown | Net Debt ÷ EBITDA |
| ANURAS FY2026 worked expression | ₹1,489.42 Cr ÷ ₹543.02 Cr |
| Required facts (read by the engine) | `cash`, `depreciation`, `finance_costs`, `pbt` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: closing debt/cash; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) |
| Relevant tests | 5 specific / 20 generic; e.g. `test_global_audit_2026_10c.py::test_net_debt_and_ev_do_not_move_with_the_cash_ratio_policy`, `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[net_debt_to_ebitda]`, `test_ratio_remediation.py::test_every_debt_ratio_consumes_the_one_total_debt_fact` |
| Cross-company run | 17 real filings run: needs_review=3, not_applicable=10, verified=4 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Warnings the engine printed on ANURAS FY2026 | Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). |
| Known discrepancy | status needs_review is the intended acquisition-year guard (balances consolidate a part-year acquisition) |
| ANURAS FY2026 matrix verdict | PASS (value 2.74286, engine status `needs_review`) |
| **Status (this document)** | **PASS** |

### Sr 34 - Debt Service Coverage Ratio (DSCR) (internal id `dscr`)

| Field | Detail |
|---|---|
| Category | Cash Flow |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Net Operating Income (EBITDA proxy) ÷ (Gross Principal Repayment + Interest Due) |
| Actual implementation (`ratio_contract.SPEC`) | Net Operating Income (= EBITDA, flagged proxy) ÷ (gross principal repayments + interest due [Finance Costs]). Unavailable when gross principal repayments are not disclosed - never rebuilt from net financing flows. |
| Formula as printed in the calculation breakdown | Net Operating Income (EBITDA proxy) ÷ (Gross Principal Repayment + Interest Due) |
| Required facts (read by the engine) | `borrowings_repayment`, `ebitda`, `finance_costs`, `lease_repayment` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: flow; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: borrowings_repayment, ebitda, finance_costs; falls back, flagged: lease_repayment |
| Relevant tests | 6 specific / 20 generic; e.g. `test_final_validation_regressions.py::test_providers_and_proxies`, `test_ratio_remediation.py::test_canonical_and_contract_agree_on_unavailable`, `test_ratio_remediation.py::test_every_ebitda_ratio_uses_that_fact_and_evidence_matches` |
| Cross-company run | 17 real filings run: insufficient_data=3, needs_review=8, not_applicable=6 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | ANURAS discloses no gross principal repayment line, so DSCR is correctly WITHHELD (insufficient_data, never rebuilt from net flows); the numeric path is covered by synthetic tests only. |
| ANURAS FY2026 matrix verdict | NEEDS REVIEW (value -, engine status `insufficient_data`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 35 - Cash Flow Coverage Ratio (internal id `cash_flow_coverage_ratio`)

| Field | Detail |
|---|---|
| Category | Cash Flow |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Operating Cash Flow ÷ Total Debt |
| Actual implementation (`ratio_contract.SPEC`) | Operating Cash Flow ÷ Total Debt. |
| Formula as printed in the calculation breakdown | Net Cash Flow from Operating Activities ÷ Total Debt |
| ANURAS FY2026 worked expression | ₹334.33 Cr ÷ ₹1,867.49 Cr |
| Required facts (read by the engine) | `operating_cash_flow`, `total_debt` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: flow / closing debt; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: operating_cash_flow, total_debt |
| Relevant tests | 2 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[cash_flow_coverage_ratio]`, `test_ratio_remediation.py::test_every_debt_ratio_consumes_the_one_total_debt_fact` |
| Cross-company run | 17 real filings run: needs_review=3, not_applicable=6, verified=8 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 0.179025, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 36 - Free Cash Flow (internal id `free_cash_flow`)

| Field | Detail |
|---|---|
| Category | Cash Flow |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Operating Cash Flow − Capital Expenditure |
| Actual implementation (`ratio_contract.SPEC`) | Operating Cash Flow - gross Capex (no disposal proceeds netted). |
| Formula as printed in the calculation breakdown | Operating Cash Flow − Capital Expenditure |
| ANURAS FY2026 worked expression | ₹334.33 Cr − ₹555.16 Cr |
| Required facts (read by the engine) | `capex`, `operating_cash_flow` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: flow; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) |
| Relevant tests | 4 specific / 20 generic; e.g. `test_global_audit_2026_10c.py::test_ev_is_the_same_number_in_all_three_multiples`, `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[free_cash_flow]`, `test_ratio_remediation.py::test_missing_inputs_never_become_computed_zeros_elsewhere` |
| Cross-company run | 17 real filings run: not_applicable=6, verified=11 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Warnings the engine printed on ANURAS FY2026 | No separate 'purchase of intangible assets' line was found in the cash-flow statement; it is treated as nil (the statement lists every cash movement - a combined PPE+intangibles line is already in the PPE figure). |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value -220.83, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 37 - FCF Yield (internal id `fcf_yield`)

| Field | Detail |
|---|---|
| Category | Market / Valuation |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Free Cash Flow ÷ Market Capitalisation |
| Actual implementation (`ratio_contract.SPEC`) | Free Cash Flow ÷ Market Cap. |
| Formula as printed in the calculation breakdown | (Free Cash Flow ÷ Market Capitalisation) × 100 |
| ANURAS FY2026 worked expression | (−₹220.83 Cr ÷ ₹13,263.33 Cr) × 100 |
| Required facts (read by the engine) | `capex`, `operating_cash_flow`, `shares_outstanding` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Market price: `tools/market_price.get_live_price` (Angel One live quote, yfinance fallback) - a live quote taken at calculation time (`as_of = "live quote"`), not the price on the fiscal-year end. |
| Financial period / perimeter | period basis: flow / mcap; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Share counts and per-share values kept in absolute shares / Rs per share; market cap = price x shares / 1e7 -> Crore. Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) |
| Relevant tests | 2 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[fcf_yield]`, `test_ratio_remediation.py::test_market_dependent_ratios_without_a_price_are_unavailable_not_stale` |
| Cross-company run | 17 real filings run: needs_review=3, not_applicable=6, not_disclosed=1, verified=7 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Warnings the engine printed on ANURAS FY2026 | No separate 'purchase of intangible assets' line was found in the cash-flow statement; it is treated as nil (the statement lists every cash movement - a combined PPE+intangibles line is already in the PPE figure). |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value -1.66497, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 38 - FCF Margin (internal id `fcf_margin`)

| Field | Detail |
|---|---|
| Category | Cash Flow |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Free Cash Flow ÷ Revenue |
| Actual implementation (`ratio_contract.SPEC`) | Free Cash Flow ÷ Revenue. |
| Formula as printed in the calculation breakdown | (Free Cash Flow ÷ Revenue from Operations) × 100 |
| ANURAS FY2026 worked expression | (−₹220.83 Cr ÷ ₹2,365.45 Cr) × 100 |
| Required facts (read by the engine) | `capex`, `operating_cash_flow`, `revenue` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: flow; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) |
| Relevant tests | 1 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[fcf_margin]` |
| Cross-company run | 17 real filings run: not_applicable=6, verified=11 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Warnings the engine printed on ANURAS FY2026 | No separate 'purchase of intangible assets' line was found in the cash-flow statement; it is treated as nil (the statement lists every cash movement - a combined PPE+intangibles line is already in the PPE figure). |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value -9.33562, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 39 - Operating Cash Flow Ratio (internal id `ocf_ratio`)

| Field | Detail |
|---|---|
| Category | Cash Flow |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Operating Cash Flow ÷ Current Liabilities |
| Actual implementation (`ratio_contract.SPEC`) | Operating Cash Flow ÷ Total Current Liabilities. |
| Formula as printed in the calculation breakdown | Net Cash Flow from Operating Activities ÷ Total Current Liabilities |
| ANURAS FY2026 worked expression | ₹334.33 Cr ÷ ₹2,615.44 Cr |
| Required facts (read by the engine) | `operating_cash_flow`, `total_current_liabilities` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: flow / closing; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: operating_cash_flow, total_current_liabilities |
| Relevant tests | 1 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[ocf_ratio]` |
| Cross-company run | 17 real filings run: needs_review=1, not_applicable=6, verified=10 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Warnings the engine printed on ANURAS FY2026 | Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). |
| Known discrepancy | status needs_review is the intended acquisition-year guard (balances consolidate a part-year acquisition) Downgraded in this document: ANURAS passes, but the current-assets / current-liabilities subtotal it reads is misread on other filings (L&T FY25 TCA = 157 Cr, FY26 TCL = 45 Cr; Asian Paints FY25 TCA = 786 Cr; Bharti Airtel FY26 TCL not found). The identity layer flags these `needs_review`, but the extraction defect is open (see PROJECT_DOCUMENTATION.md section M). |
| ANURAS FY2026 matrix verdict | PASS (value 0.127828, engine status `needs_review`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 40 - Capex Intensity (internal id `capex_intensity`)

| Field | Detail |
|---|---|
| Category | Cash Flow |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Capital Expenditure ÷ Revenue |
| Actual implementation (`ratio_contract.SPEC`) | Gross Capex ÷ Revenue. |
| Formula as printed in the calculation breakdown | (Capital Expenditure ÷ Revenue from Operations) × 100 |
| ANURAS FY2026 worked expression | (₹555.16 Cr ÷ ₹2,365.45 Cr) × 100 |
| Required facts (read by the engine) | `capex`, `capex_intangible_purchase`, `capex_ppe_purchase`, `revenue` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: flow; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: capex, revenue; blanking these on the synthetic filing left the value unchanged (not material to that synthetic case): capex_intangible_purchase, capex_ppe_purchase |
| Relevant tests | 2 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[capex_intensity]`, `test_ratio_remediation.py::test_missing_inputs_never_become_computed_zeros_elsewhere` |
| Cross-company run | 17 real filings run: not_applicable=6, verified=11 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Warnings the engine printed on ANURAS FY2026 | No separate 'purchase of intangible assets' line was found in the cash-flow statement; it is treated as nil (the statement lists every cash movement - a combined PPE+intangibles line is already in the PPE figure). |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 23.4693, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 41 - OCF/Net Profit (internal id `ocf_to_net_profit`)

| Field | Detail |
|---|---|
| Category | Cash Flow |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Operating Cash Flow ÷ Net Profit (whole entity) |
| Actual implementation (`ratio_contract.SPEC`) | Operating Cash Flow ÷ Net Profit, both whole-entity (total PAT incl. NCI). |
| Formula as printed in the calculation breakdown | Net Cash Flow from Operating Activities ÷ Profit for the Year |
| ANURAS FY2026 worked expression | ₹334.33 Cr ÷ ₹222.20 Cr |
| Required facts (read by the engine) | `operating_cash_flow`, `pat_total` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: flow; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: operating_cash_flow, pat_total |
| Relevant tests | 2 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[ocf_to_net_profit]`, `test_ratio_remediation.py::test_whole_entity_flows_are_not_divided_by_owners_only_profit` |
| Cross-company run | 17 real filings run: needs_review=2, not_applicable=6, not_disclosed=1, verified=8 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 1.50462, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 42 - Return on Invested Capital (ROIC) (internal id `roic`)

| Field | Detail |
|---|---|
| Category | P&L + Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | NOPAT ÷ Invested Capital |
| Actual implementation (`ratio_contract.SPEC`) | NOPAT ÷ Invested Capital; NOPAT = EBIT × (1 - effective tax rate); Invested Capital = Total Debt + Total Equity (incl. NCI) - Cash & Cash Equivalents (closing, per spec). |
| Formula as printed in the calculation breakdown | (NOPAT ÷ Invested Capital (closing)) × 100 |
| ANURAS FY2026 worked expression | (₹352.09 Cr ÷ ₹6,119.38 Cr) × 100 |
| Required facts (read by the engine) | `cash`, `equity`, `finance_costs`, `nci`, `pbt`, `tax_expense` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: closing invested capital; perimeter: whole_entity; equity basis: total_equity_incl_nci |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) |
| Relevant tests | 4 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[roic]`, `test_ratio_remediation.py::test_every_debt_ratio_consumes_the_one_total_debt_fact`, `test_ratio_remediation.py::test_roic_is_nopat_over_closing_invested_capital` |
| Cross-company run | 17 real filings run: needs_review=4, not_applicable=6, not_disclosed=1, verified=6 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Warnings the engine printed on ANURAS FY2026 | Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)). |
| Known discrepancy | status needs_review is the intended acquisition-year guard (balances consolidate a part-year acquisition) |
| ANURAS FY2026 matrix verdict | PASS (value 5.75375, engine status `needs_review`) |
| **Status (this document)** | **PASS** |

### Sr 43 - Tax % (internal id `effective_tax_rate`)

| Field | Detail |
|---|---|
| Category | P&L |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Tax Expense ÷ Profit Before Tax |
| Actual implementation (`ratio_contract.SPEC`) | Total Tax Expense ÷ Profit Before Tax. |
| Formula as printed in the calculation breakdown | (Total Tax Expense ÷ Profit Before Tax) × 100 |
| ANURAS FY2026 worked expression | (₹32.20 Cr ÷ ₹254.40 Cr) × 100 |
| Required facts (read by the engine) | `pbt`, `tax_expense` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: flow; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: pbt, tax_expense |
| Relevant tests | 2 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[effective_tax_rate]`, `test_ratio_remediation.py::test_zero_or_negative_denominators_are_not_meaningful` |
| Cross-company run | 17 real filings run: not_applicable=6, not_disclosed=1, verified=10 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | Screener Tax % 13 vs Navrist 12.66. |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 12.657, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 44 - Contribution Margin (internal id `contribution_margin`)

| Field | Detail |
|---|---|
| Category | P&L |
| Approved formula (`tools/fundamental_ratio_registry.py`) | (Revenue − Variable Costs) ÷ Revenue |
| Actual implementation (`ratio_contract.SPEC`) | (Revenue - Variable Costs) ÷ Revenue. Variable costs are NOT disclosed: reconstructed from goods cost + Direct Expenses / volume-linked Other-Expenses note items. Always a flagged proxy (needs_review); unavailable when only goods cost could be identified. |
| Formula as printed in the calculation breakdown | (Contribution ÷ Revenue from Operations) × 100 |
| ANURAS FY2026 worked expression | (₹900.29 Cr ÷ ₹2,365.45 Cr) × 100 |
| Required facts (read by the engine) | `revenue` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Contains a documented proxy input (see Known discrepancy). |
| Financial period / perimeter | period basis: flow (PROXY); perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: revenue |
| Relevant tests | 4 specific / 20 generic; e.g. `test_global_audit_2026_10c.py::test_contribution_margin_does_not_round_intermediates`, `test_ratio_remediation.py::test_direct_expenses_line_counts_as_variable_cost_proxy`, `test_ratio_remediation.py::test_proxy_with_note_items_is_needs_review_never_verified` |
| Cross-company run | 17 real filings run: needs_review=4, not_applicable=6, not_disclosed=7 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Warnings the engine printed on ANURAS FY2026 | PROXY: Ind AS filings do not disclose variable costs; reconstructed from goods cost + Direct Expenses / volume-linked note items. Rent, professional fees, employee cost, depreciation and finance costs are never treated as variable. |
| Known discrepancy | PROXY by necessity (Ind AS discloses no variable-cost line) - needs_review by design (policy C/S). Rounding of intermediates found by this audit and removed (2026.10.13). |
| ANURAS FY2026 matrix verdict | NEEDS REVIEW (value 38.0599, engine status `needs_review`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 45 - EPS Growth Rate (internal id `eps_growth_rate`)

| Field | Detail |
|---|---|
| Category | P&L |
| Approved formula (`tools/fundamental_ratio_registry.py`) | (Current Year EPS ÷ Prior Year EPS) − 1 |
| Actual implementation (`ratio_contract.SPEC`) | (Current Basic EPS (owners) ÷ Prior Basic EPS (owners)) - 1. |
| Formula as printed in the calculation breakdown | (Basic EPS FY2026 ÷ Basic EPS FY2025 − 1) × 100 |
| ANURAS FY2026 worked expression | (₹15.09 ÷ ₹8.50 − 1) × 100 |
| Required facts (read by the engine) | `eps` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: YoY; perimeter: owners |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: eps |
| Relevant tests | 5 specific / 20 generic; e.g. `test_final_validation_regressions.py::test_bank_core_parsed_shape_runs_through_the_contract`, `test_ratio_corrections_2026_10b.py::test_eps_growth_formula_names_both_periods`, `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[eps_growth_rate]` |
| Cross-company run | 17 real filings run: needs_review=3, verified=14 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | Screener EPS 14.94 vs 8.49 = +76.0%; Navrist uses the AR's printed owners' EPS 15.09 vs 8.50 = +77.5%. |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 77.5294, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 46 - Book Value per Share (BVPS) (internal id `bvps`)

| Field | Detail |
|---|---|
| Category | Balance Sheet |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Total Equity ÷ Number of Equity Shares Outstanding |
| Actual implementation (`ratio_contract.SPEC`) | Owners' Equity ÷ Equity Shares Outstanding (closing). The ONE BVPS. |
| Formula as printed in the calculation breakdown | (Total Equity Attributable to Owners of the Company ÷ Equity Shares Outstanding) × 1,00,00,000 |
| ANURAS FY2026 worked expression | (₹3,301.84 Cr ÷ 11,38,48,310) × 1,00,00,000 |
| Required facts (read by the engine) | `equity`, `shares_outstanding` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: closing; perimeter: owners; equity basis: owners_equity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Share counts and per-share values kept in absolute shares / Rs per share; market cap = price x shares / 1e7 -> Crore. Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) |
| Relevant tests | 8 specific / 20 generic; e.g. `test_final_validation_regressions.py::test_bank_core_parsed_shape_runs_through_the_contract`, `test_global_audit_2026_10c.py::test_numbers_follow_the_declared_basis_when_nci_is_material`, `test_ratio_corrections_2026_10b.py::test_graham_breakdown_names_its_real_inputs` |
| Cross-company run | 17 real filings run: needs_review=3, not_disclosed=1, verified=13 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 290.021, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 47 - Dividend Payout % (internal id `dividend_payout_ratio`)

| Field | Detail |
|---|---|
| Category | Multi-source / Derived |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Dividends Paid to the Company's shareholders ÷ Net Profit (owners) |
| Actual implementation (`ratio_contract.SPEC`) | Dividends PAID (cash flow statement) ÷ owners' Net Profit. Declared DPS × shares only as a flagged estimate when no paid line exists; unavailable (never 0) when neither exists. |
| Formula as printed in the calculation breakdown | (Dividends paid to the Company's shareholders during the year ÷ Profit for the Year Attributable to Owners of the Company) × 100 |
| ANURAS FY2026 worked expression | (₹8.54 Cr ÷ ₹170.12 Cr) × 100 |
| Required facts (read by the engine) | `dividends_paid`, `dps`, `pat`, `shares_outstanding` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: flow; perimeter: owners (cash dividends: whole entity) |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: pat; blanking these on the synthetic filing left the value unchanged (not material to that synthetic case): dividends_paid, dps, shares_outstanding |
| Relevant tests | 15 specific / 20 generic; e.g. `test_calculation_engine.py::test_case_j_registry_dependency_behaviour`, `test_final_validation_regressions.py::test_dividend_inputs_unknown_means_unavailable`, `test_global_audit_2026_10c.py::test_anuras_style_split_owners_only_numerator` |
| Cross-company run | 17 real filings run: needs_review=8, not_disclosed=3, verified=6 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | Screener payout 10% = dividend declared for FY26 (1.50 x shares / owners' PAT = 10.04%, carried as reference_declared_for_year_payout_pct); the metric |
| Known discrepancy | Downgraded in this document: on Bharti Airtel FY2026 the DPS fact came out 0.0 / `verified` (tag `no_dividend_statement`) although the Annual Report recommends INR 24 per share (the rupee glyph is printed as 'H' in that PDF). Unknown/other-glyph dividends must not become zero - open issue M-13. |
| ANURAS FY2026 matrix verdict | PASS (value 5.01878, engine status `verified`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 48 - Retention Ratio (internal id `retention_ratio`)

| Field | Detail |
|---|---|
| Category | Multi-source / Derived |
| Approved formula (`tools/fundamental_ratio_registry.py`) | 1 − Dividend Payout Ratio |
| Actual implementation (`ratio_contract.SPEC`) | 100% - Dividend Payout (only when payout is available). |
| Formula as printed in the calculation breakdown | 100 − Dividend Payout % |
| ANURAS FY2026 worked expression | 100 − 5.0188 |
| Required facts (read by the engine) | `dividends_paid`, `dps`, `pat`, `shares_outstanding` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: derived; perimeter: owners |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | `dividend_payout_ratio` |
| Missing-data behaviour | withheld when missing: pat; blanking these on the synthetic filing left the value unchanged (not material to that synthetic case): dividends_paid, dps, shares_outstanding |
| Relevant tests | 6 specific / 20 generic; e.g. `test_calculation_engine.py::test_case_j_registry_dependency_behaviour`, `test_final_validation_regressions.py::test_dividend_inputs_unknown_means_unavailable`, `test_global_audit_2026_10c.py::test_retention_and_sustainable_growth_follow_the_owners_payout` |
| Cross-company run | 17 real filings run: needs_review=8, not_disclosed=3, verified=6 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | Downgraded in this document: on Bharti Airtel FY2026 the DPS fact came out 0.0 / `verified` (tag `no_dividend_statement`) although the Annual Report recommends INR 24 per share (the rupee glyph is printed as 'H' in that PDF). Unknown/other-glyph dividends must not become zero - open issue M-13. |
| ANURAS FY2026 matrix verdict | PASS (value 94.9812, engine status `verified`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 49 - Sustainable Growth Rate (internal id `sustainable_growth_rate`)

| Field | Detail |
|---|---|
| Category | Multi-source / Derived |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Return on Equity × Retention Ratio |
| Actual implementation (`ratio_contract.SPEC`) | ROE × Retention (both must be available). |
| Formula as printed in the calculation breakdown | ROE % × Retention Ratio ÷ 100 |
| ANURAS FY2026 worked expression | 5.5305 × 94.9812 ÷ 100 |
| Required facts (read by the engine) | `dividends_paid`, `dps`, `equity`, `pat`, `shares_outstanding` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: derived; perimeter: owners; equity basis: owners_equity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | `roe`, `retention_ratio` |
| Missing-data behaviour | withheld when missing: equity, pat; blanking these on the synthetic filing left the value unchanged (not material to that synthetic case): dividends_paid, dps, shares_outstanding |
| Relevant tests | 6 specific / 20 generic; e.g. `test_final_validation_regressions.py::test_dividend_inputs_unknown_means_unavailable`, `test_global_audit_2026_10c.py::test_retention_and_sustainable_growth_follow_the_owners_payout`, `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[sustainable_growth_rate]` |
| Cross-company run | 17 real filings run: insufficient_data=1, needs_review=4, not_applicable=6, verified=6 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | Downgraded in this document: on Bharti Airtel FY2026 the DPS fact came out 0.0 / `verified` (tag `no_dividend_statement`) although the Annual Report recommends INR 24 per share (the rupee glyph is printed as 'H' in that PDF). Unknown/other-glyph dividends must not become zero - open issue M-13. |
| ANURAS FY2026 matrix verdict | PASS (value 5.25289, engine status `verified`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 50 - PEG Ratio (internal id `peg_ratio`)

| Field | Detail |
|---|---|
| Category | Market / Valuation |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Price-to-Earnings ÷ EPS Growth Rate |
| Actual implementation (`ratio_contract.SPEC`) | P/E ÷ EPS growth (%) (not meaningful when growth ≤ 0). |
| Formula as printed in the calculation breakdown | P/E ÷ EPS Growth Rate |
| ANURAS FY2026 worked expression | 77.20x ÷ 77.5294% |
| Required facts (read by the engine) | `eps` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Market price: `tools/market_price.get_live_price` (Angel One live quote, yfinance fallback) - a live quote taken at calculation time (`as_of = "live quote"`), not the price on the fiscal-year end. |
| Financial period / perimeter | period basis: derived; perimeter: owners |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Share counts and per-share values kept in absolute shares / Rs per share; market cap = price x shares / 1e7 -> Crore. Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | `eps_growth_rate` |
| Missing-data behaviour | withheld when missing: eps |
| Relevant tests | 3 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[peg_ratio]`, `test_ratio_remediation.py::test_peg_is_not_meaningful_when_growth_is_not_positive`, `test_ratio_remediation.py::test_valuation_ratios_use_owners_eps` |
| Cross-company run | 17 real filings run: needs_review=3, not_meaningful=4, verified=10 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 0.995796, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 51 - EV/Sales (internal id `ev_to_sales`)

| Field | Detail |
|---|---|
| Category | Market / Valuation |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Enterprise Value (Mkt Cap + Debt − Cash) ÷ Revenue |
| Actual implementation (`ratio_contract.SPEC`) | Enterprise Value (Market Cap + Debt + NCI - Cash) ÷ Revenue. |
| Formula as printed in the calculation breakdown | Enterprise Value ÷ Revenue from Operations |
| ANURAS FY2026 worked expression | ₹14,752.75 Cr ÷ ₹2,365.45 Cr |
| Required facts (read by the engine) | `cash`, `revenue`, `shares_outstanding`, `total_debt` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Market price: `tools/market_price.get_live_price` (Angel One live quote, yfinance fallback) - a live quote taken at calculation time (`as_of = "live quote"`), not the price on the fiscal-year end. |
| Financial period / perimeter | period basis: derived; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Share counts and per-share values kept in absolute shares / Rs per share; market cap = price x shares / 1e7 -> Crore. Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: cash, revenue, shares_outstanding, total_debt |
| Relevant tests | 4 specific / 20 generic; e.g. `test_global_audit_2026_10c.py::test_ev_is_the_same_number_in_all_three_multiples`, `test_global_audit_2026_10c.py::test_net_debt_and_ev_do_not_move_with_the_cash_ratio_policy`, `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[ev_to_sales]` |
| Cross-company run | 17 real filings run: needs_review=7, not_applicable=6, not_disclosed=1, verified=3 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 6.23675, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 52 - EV/FCF (internal id `ev_to_fcf`)

| Field | Detail |
|---|---|
| Category | Market / Valuation |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Enterprise Value (Mkt Cap + Debt − Cash) ÷ Free Cash Flow |
| Actual implementation (`ratio_contract.SPEC`) | Enterprise Value (Market Cap + Debt + NCI - Cash) ÷ Free Cash Flow (not meaningful when FCF ≤ 0). |
| Formula as printed in the calculation breakdown | Enterprise Value ÷ Free Cash Flow |
| ANURAS FY2026 worked expression | ₹14,752.75 Cr ÷ −₹220.8300 Cr |
| Required facts (read by the engine) | `cash`, `shares_outstanding`, `total_debt` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Market price: `tools/market_price.get_live_price` (Angel One live quote, yfinance fallback) - a live quote taken at calculation time (`as_of = "live quote"`), not the price on the fiscal-year end. |
| Financial period / perimeter | period basis: derived; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Share counts and per-share values kept in absolute shares / Rs per share; market cap = price x shares / 1e7 -> Crore. Output is a multiple (x). |
| Dependencies (parent ratios) | `free_cash_flow` |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) - derived ratio inherits its parent's availability |
| Relevant tests | 5 specific / 20 generic; e.g. `test_global_audit_2026_10c.py::test_ev_is_the_same_number_in_all_three_multiples`, `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[ev_to_fcf]`, `test_ratio_remediation.py::test_ev_to_fcf_with_negative_fcf_is_not_meaningful_but_keeps_the_number` |
| Cross-company run | 17 real filings run: needs_review=6, not_applicable=6, not_disclosed=1, not_meaningful=1, verified=3 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Warnings the engine printed on ANURAS FY2026 | Free Cash Flow is negative: the multiple exists mathematically but is not economically meaningful. |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value -66.8059, engine status `not_meaningful`) |
| **Status (this document)** | **PASS** |

### Sr 53 - Price/Cash Flow (internal id `price_to_cash_flow`)

| Field | Detail |
|---|---|
| Category | Market / Valuation |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Market Capitalisation ÷ Operating Cash Flow |
| Actual implementation (`ratio_contract.SPEC`) | Market Cap ÷ Operating Cash Flow. |
| Formula as printed in the calculation breakdown | Market Capitalisation ÷ Net Cash Flow from Operating Activities |
| ANURAS FY2026 worked expression | ₹13,263.33 Cr ÷ ₹334.33 Cr |
| Required facts (read by the engine) | `operating_cash_flow`, `shares_outstanding` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Market price: `tools/market_price.get_live_price` (Angel One live quote, yfinance fallback) - a live quote taken at calculation time (`as_of = "live quote"`), not the price on the fiscal-year end. |
| Financial period / perimeter | period basis: mcap / flow; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Share counts and per-share values kept in absolute shares / Rs per share; market cap = price x shares / 1e7 -> Crore. Output is a multiple (x). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: operating_cash_flow, shares_outstanding |
| Relevant tests | 3 specific / 20 generic; e.g. `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[price_to_cash_flow]`, `test_ratio_remediation.py::test_market_dependent_ratios_without_a_price_are_unavailable_not_stale`, `test_ratio_remediation.py::test_zero_or_negative_denominators_are_not_meaningful` |
| Cross-company run | 17 real filings run: needs_review=3, not_applicable=6, not_disclosed=1, verified=7 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 39.6718, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 54 - Graham Number (internal id `graham_number`)

| Field | Detail |
|---|---|
| Category | Market / Valuation |
| Approved formula (`tools/fundamental_ratio_registry.py`) | √(22.5 × EPS × Book Value per Share) |
| Actual implementation (`ratio_contract.SPEC`) | √(22.5 × EPS (owners) × BVPS). |
| Formula as printed in the calculation breakdown | √(22.5 × Basic EPS × Book Value per Share) |
| ANURAS FY2026 worked expression | √(98,469.3481) |
| Required facts (read by the engine) | `bvps`, `eps`, `equity`, `shares_outstanding` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Market price: `tools/market_price.get_live_price` (Angel One live quote, yfinance fallback) - a live quote taken at calculation time (`as_of = "live quote"`), not the price on the fiscal-year end. |
| Financial period / perimeter | period basis: derived; perimeter: owners; equity basis: owners_equity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Share counts and per-share values kept in absolute shares / Rs per share; market cap = price x shares / 1e7 -> Crore. Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: bvps, eps |
| Relevant tests | 3 specific / 20 generic; e.g. `test_ratio_corrections_2026_10b.py::test_graham_breakdown_names_its_real_inputs`, `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[graham_number]`, `test_ratio_remediation.py::test_valuation_ratios_use_owners_eps` |
| Cross-company run | 17 real filings run: needs_review=2, not_disclosed=1, not_meaningful=2, verified=12 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | None recorded. |
| ANURAS FY2026 matrix verdict | PASS (value 313.798, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 55 - Altman Z-Score (internal id `altman_z_score`)

| Field | Detail |
|---|---|
| Category | Multi-source / Derived |
| Approved formula (`tools/fundamental_ratio_registry.py`) | 1.2(WC/TA) + 1.4(RE/TA) + 3.3(EBIT/TA) + 0.6(MktCap/TL) + 1.0(Sales/TA) |
| Actual implementation (`ratio_contract.SPEC`) | 1.2·WC/TA + 1.4·RE/TA + 3.3·EBIT/TA + 0.6·MktCap/Total Liabilities + 1.0·Sales/TA; Total Liabilities as reported (NCI is never booked as a liability); RE = Other Equity proxy (needs_review). |
| Formula as printed in the calculation breakdown | 1.2×(WC ÷ TA) + 1.4×(RE ÷ TA) + 3.3×(EBIT ÷ TA) + 0.6×(Market Cap ÷ TL) + 1.0×(Sales ÷ TA) |
| ANURAS FY2026 worked expression | 0.1665 + 0.5570 + 0.1660 + 2.3526 + 0.2952 |
| Required facts (read by the engine) | `ebit`, `finance_costs`, `pbt`, `retained_earnings`, `revenue`, `shares_outstanding`, `total_assets`, `total_current_assets`, `total_current_liabilities`, `total_liabilities`, `working_capital` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Market price: `tools/market_price.get_live_price` (Angel One live quote, yfinance fallback) - a live quote taken at calculation time (`as_of = "live quote"`), not the price on the fiscal-year end. Contains a documented proxy input (see Known discrepancy). |
| Financial period / perimeter | period basis: closing; perimeter: whole_entity; equity basis: none |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: ebit, retained_earnings, revenue, shares_outstanding, total_assets, total_liabilities, working_capital |
| Relevant tests | 6 specific / 20 generic; e.g. `test_full_quant_coverage.py::test_n_altman_needs_review_on_retained_earnings_proxy`, `test_full_quant_coverage.py::test_n_altman_z_uses_market_cap_not_book_equity`, `test_global_audit_2026_10c.py::test_roa_altman_piotroski_are_documented_as_reading_no_equity_fact` |
| Cross-company run | 17 real filings run: needs_review=9, not_applicable=6, not_disclosed=2 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Warnings the engine printed on ANURAS FY2026 | Retained Earnings is proxied by 'Other Equity' (reserves incl. securities premium). |
| Known discrepancy | Retained earnings is the Other-Equity proxy (always needs_review, policy D). |
| ANURAS FY2026 matrix verdict | NEEDS REVIEW (value 3.53741, engine status `needs_review`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 56 - Piotroski F-Score (internal id `piotroski_f_score`)

| Field | Detail |
|---|---|
| Category | Multi-source / Derived |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Sum of 9 binary fundamental-strength tests (0-9 scale) |
| Actual implementation (`ratio_contract.SPEC`) | Nine binary tests; a score is reported only when all nine can be evaluated, otherwise insufficient_data. |
| Formula as printed in the calculation breakdown | F-Score = number of the 9 tests passed (each 1 point) |
| ANURAS FY2026 worked expression | 1 + 1 + 1 + 1 + 1 + 1 + 0 + 0 + 1 |
| Required facts (read by the engine) | `cogs`, `gross_profit`, `lt_borrowings`, `operating_cash_flow`, `pat`, `pat_total`, `revenue`, `shares_outstanding`, `total_assets`, `total_current_assets`, `total_current_liabilities`, `total_debt` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. |
| Financial period / perimeter | period basis: two-year; perimeter: whole_entity; equity basis: none |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: gross_profit, operating_cash_flow, pat, pat_total, revenue, shares_outstanding, total_assets, total_current_assets, total_current_liabilities; blanking these on the synthetic filing left the value unchanged (not material to that synthetic case): lt_borrowings, total_debt |
| Relevant tests | 9 specific / 20 generic; e.g. `test_full_quant_coverage.py::test_o_piotroski_computes_real_score_when_all_facts_present`, `test_full_quant_coverage.py::test_o_piotroski_insufficient_when_leverage_fact_missing`, `test_global_audit_2026_10c.py::test_basis_is_stamped_on_the_result` |
| Cross-company run | 17 real filings run: needs_review=3, not_applicable=6, not_disclosed=7, verified=1 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | Conventions documented: ROA / asset turnover use closing total assets; leverage test uses total debt / total assets (long-term debt alone not separable). Downgraded in this document: ANURAS passes, but the current-assets / current-liabilities subtotal it reads is misread on other filings (L&T FY25 TCA = 157 Cr, FY26 TCL = 45 Cr; Asian Paints FY25 TCA = 786 Cr; Bharti Airtel FY26 TCL not found). The identity layer flags these `needs_review`, but the extraction defect is open (see PROJECT_DOCUMENTATION.md section M). |
| ANURAS FY2026 matrix verdict | PASS (value 7, engine status `verified`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 57 - Beneish M-Score (internal id `beneish_m_score`)

| Field | Detail |
|---|---|
| Category | Multi-source / Derived |
| Approved formula (`tools/fundamental_ratio_registry.py`) | -4.84 + 0.92·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI + 0.115·DEPI - 0.172·SGAI + 4.679·TATA - 0.327·LVGI |
| Actual implementation (`ratio_contract.SPEC`) | 8-variable M-Score; SGAI uses Other Expenses as the SG&A proxy (needs_review). |
| Formula as printed in the calculation breakdown | M = −4.84 + 0.92·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI + 0.115·DEPI − 0.172·SGAI + 4.679·TATA − 0.327·LVGI |
| ANURAS FY2026 worked expression | −4.84 + 0.92 × 0.7943 + 0.528 × 1.3149 + 0.404 × 1.2118 + 0.892 × 1.6461 + 0.115 × 1.0840 − 0.172 × 0.7310 + 4.679 × (−0.0140) − 0.327 × 0.9265 |
| Required facts (read by the engine) | `cogs`, `depreciation`, `gross_profit`, `lt_borrowings`, `operating_cash_flow`, `other_expenses`, `pat_total`, `ppe`, `receivables`, `revenue`, `total_assets`, `total_current_assets`, `total_current_liabilities`, `total_debt` |
| Source and extraction path | Annual Report PDF (statement pages, `tools/annual_report_financials.py`; uploaded XBRL only in manual mode) -> `tools/fundamental_fact_store.py` FactSet -> `tools/ratio_contract.py`. Contains a documented proxy input (see Known discrepancy). |
| Financial period / perimeter | period basis: two-year; perimeter: whole_entity |
| Unit handling | Statements normalised to Rs Crore using the unit declared on the statement page (`_page_unit_multiplier`). Output unit as in the registry row (percent / x / Rs). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | withheld when missing: depreciation, gross_profit, operating_cash_flow, other_expenses, pat_total, ppe, receivables, revenue, total_assets, total_current_assets, total_current_liabilities; falls back, flagged: total_debt; blanking these on the synthetic filing left the value unchanged (not material to that synthetic case): lt_borrowings |
| Relevant tests | 3 specific / 20 generic; e.g. `test_full_quant_coverage.py::test_p_beneish_insufficient_never_fabricated`, `test_ratio_formula_oracle.py::test_each_ratio_1_to_57_matches_its_authoritative_formula[beneish_m_score]`, `test_ratio_remediation.py::test_beneish_tata_uses_whole_entity_profit` |
| Cross-company run | 17 real filings run: needs_review=8, not_applicable=6, not_disclosed=3 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Warnings the engine printed on ANURAS FY2026 | SG&A is proxied by Other Expenses (Ind AS has no distinct SG&A line) - SGAI is an approximation. |
| Known discrepancy | SG&A is proxied by Other expenses (no SG&A line under Ind AS) -> needs_review by design. |
| ANURAS FY2026 matrix verdict | NEEDS REVIEW (value -1.82659, engine status `needs_review`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 58 - Net Interest Margin (NIM) (internal id `net_interest_margin`)

| Field | Detail |
|---|---|
| Category | Banking-specific |
| Approved formula (`tools/fundamental_ratio_registry.py`) | (Interest Income − Interest Expense) ÷ Average Interest-Earning Assets |
| Actual implementation (`ratio_contract.SPEC`) | Bank: (Interest Earned - Interest Expended) / average (Cash & RBI balances + Balances with banks + Investments + Advances) x 100; the bank's disclosed NIM is a cross-check (gap > 0.75 pp -> needs_review). NBFC/HFC (Ind AS): (Interest income - Finance costs) / average (Loans + Investments). [docs/ratio_contract.md, 'Banking ratios'] |
| Formula as printed in the calculation breakdown | not produced by the contract (bank / market-data / shareholding rows use their own provider) |
| Required facts (read by the engine) | - |
| Source and extraction path | Bank annual report (RBI-format schedules) -> `tools/bank_extractor.py` (word-coordinate row reader, unit-normalised, identity-gated) -> `tools/bank_ratios.py` -> `ratio_contract.guard_bank` plausibility bounds. Sector-gated (Banks / NBFC only; others `not_applicable`). |
| Financial period / perimeter | period basis: n/a; perimeter: n/a |
| Unit handling | Every figure converted to Rs Crore from the unit declared on its own page (Rs '000 / million / crore); ratio is a percentage. |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) |
| Relevant tests | 9 specific / 20 generic; e.g. `test_final_validation_regressions.py::test_bank_ratios_missing_inputs_are_not_zero`, `test_full_quant_coverage.py::test_q_not_applicable_for_non_bank_sector`, `test_full_quant_coverage.py::test_r_bank_ratio_not_fabricated_when_applicable_but_unwired` |
| Cross-company run | 17 real filings run: not_applicable=11, verified=6 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | ANURAS is a non-lender (correctly not_applicable). The value is computed from the bank's statements (identity-gated) and is verified on 4 bank filings, but it is printed verbatim in the bank's own report for only 1 of them (definition differences, e.g. the bank's own NIM/CASA basis) - not independently corroborated. Values: ['HDFCBANK=3.45', 'ICICIBANK=4.25', 'KOTAKBANK=4.5', 'SBIN=2.81'] |
| ANURAS FY2026 matrix verdict | NEEDS REVIEW (value -, engine status `not_applicable`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 59 - CASA Ratio (internal id `casa_ratio`)

| Field | Detail |
|---|---|
| Category | Banking-specific |
| Approved formula (`tools/fundamental_ratio_registry.py`) | (Current Account + Savings Account Deposits) ÷ Total Deposits |
| Actual implementation (`ratio_contract.SPEC`) | (Demand + Savings deposits) / Total deposits (Schedule 3); NBFCs: not applicable. [docs/ratio_contract.md] |
| Formula as printed in the calculation breakdown | not produced by the contract (bank / market-data / shareholding rows use their own provider) |
| Required facts (read by the engine) | - |
| Source and extraction path | Bank annual report (RBI-format schedules) -> `tools/bank_extractor.py` (word-coordinate row reader, unit-normalised, identity-gated) -> `tools/bank_ratios.py` -> `ratio_contract.guard_bank` plausibility bounds. Sector-gated (Banks / NBFC only; others `not_applicable`). |
| Financial period / perimeter | period basis: n/a; perimeter: n/a |
| Unit handling | Every figure converted to Rs Crore from the unit declared on its own page (Rs '000 / million / crore); ratio is a percentage. |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) |
| Relevant tests | 9 specific / 20 generic; e.g. `test_final_validation_regressions.py::test_bank_ratios_missing_inputs_are_not_zero`, `test_ratio_corrections_2026_10b.py::test_casa_from_proven_schedule_3`, `test_ratio_corrections_2026_10b.py::test_missing_demand_is_insufficient_not_zero` |
| Cross-company run | 17 real filings run: not_applicable=13, verified=4 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | ANURAS is a non-lender (correctly not_applicable). The value is computed from the bank's statements (identity-gated) and is verified on 4 bank filings, but it is printed verbatim in the bank's own report for only 2 of them (definition differences, e.g. the bank's own NIM/CASA basis) - not independently corroborated. Values: ['HDFCBANK=34.79', 'ICICIBANK=41.84', 'KOTAKBANK=42.96', 'SBIN=38.72'] |
| ANURAS FY2026 matrix verdict | NEEDS REVIEW (value -, engine status `not_applicable`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 60 - Gross NPA % (internal id `gross_npa_pct`)

| Field | Detail |
|---|---|
| Category | Banking-specific |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Gross Non-Performing Assets ÷ Gross Advances |
| Actual implementation (`ratio_contract.SPEC`) | The Gross NPA ratio the bank discloses (RBI asset-quality disclosure) - never rebuilt from a guessed denominator. [docs/ratio_contract.md] |
| Formula as printed in the calculation breakdown | not produced by the contract (bank / market-data / shareholding rows use their own provider) |
| Required facts (read by the engine) | - |
| Source and extraction path | Bank annual report (RBI-format schedules) -> `tools/bank_extractor.py` (word-coordinate row reader, unit-normalised, identity-gated) -> `tools/bank_ratios.py` -> `ratio_contract.guard_bank` plausibility bounds. Sector-gated (Banks / NBFC only; others `not_applicable`). |
| Financial period / perimeter | period basis: n/a; perimeter: n/a |
| Unit handling | Every figure converted to Rs Crore from the unit declared on its own page (Rs '000 / million / crore); ratio is a percentage. |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) |
| Relevant tests | 6 specific / 20 generic; e.g. `test_final_validation_regressions.py::test_bank_ratios_missing_inputs_are_not_zero`, `test_ratio_corrections_2026_10b.py::test_disclosed_ratio_is_used_as_printed`, `test_ratio_corrections_2026_10b.py::test_disclosed_ratios_missing_are_not_disclosed_never_zero` |
| Cross-company run | 17 real filings run: not_applicable=11, not_disclosed=2, verified=4 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | ANURAS is a non-lender (correctly not_applicable); validated on 4 bank filings, 4 with the value printed verbatim in the bank's own report |
| ANURAS FY2026 matrix verdict | PASS (value -, engine status `not_applicable`) |
| **Status (this document)** | **PASS** |

### Sr 61 - Net NPA % (internal id `net_npa_pct`)

| Field | Detail |
|---|---|
| Category | Banking-specific |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Net Non-Performing Assets ÷ Net Advances |
| Actual implementation (`ratio_contract.SPEC`) | The Net NPA ratio the bank discloses - never rebuilt. [docs/ratio_contract.md] |
| Formula as printed in the calculation breakdown | not produced by the contract (bank / market-data / shareholding rows use their own provider) |
| Required facts (read by the engine) | - |
| Source and extraction path | Bank annual report (RBI-format schedules) -> `tools/bank_extractor.py` (word-coordinate row reader, unit-normalised, identity-gated) -> `tools/bank_ratios.py` -> `ratio_contract.guard_bank` plausibility bounds. Sector-gated (Banks / NBFC only; others `not_applicable`). |
| Financial period / perimeter | period basis: n/a; perimeter: n/a |
| Unit handling | Every figure converted to Rs Crore from the unit declared on its own page (Rs '000 / million / crore); ratio is a percentage. |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) |
| Relevant tests | 5 specific / 20 generic; e.g. `test_final_validation_regressions.py::test_bank_ratios_missing_inputs_are_not_zero`, `test_ratio_corrections_2026_10b.py::test_disclosed_ratios_missing_are_not_disclosed_never_zero`, `test_ratio_formula_oracle.py::test_registry_has_exactly_68_ratios_each_with_a_contract_or_provider_path` |
| Cross-company run | 17 real filings run: not_applicable=11, not_disclosed=1, verified=5 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | ANURAS is a non-lender (correctly not_applicable); validated on 4 bank filings, 4 with the value printed verbatim in the bank's own report |
| ANURAS FY2026 matrix verdict | PASS (value -, engine status `not_applicable`) |
| **Status (this document)** | **PASS** |

### Sr 62 - Provision Coverage Ratio (PCR) (internal id `provision_coverage_ratio`)

| Field | Detail |
|---|---|
| Category | Banking-specific |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Total Provisions Held ÷ Gross Non-Performing Assets |
| Actual implementation (`ratio_contract.SPEC`) | The Provision Coverage Ratio the bank discloses (labelled when it excludes technical write-offs). [docs/ratio_contract.md] |
| Formula as printed in the calculation breakdown | not produced by the contract (bank / market-data / shareholding rows use their own provider) |
| Required facts (read by the engine) | - |
| Source and extraction path | Bank annual report (RBI-format schedules) -> `tools/bank_extractor.py` (word-coordinate row reader, unit-normalised, identity-gated) -> `tools/bank_ratios.py` -> `ratio_contract.guard_bank` plausibility bounds. Sector-gated (Banks / NBFC only; others `not_applicable`). |
| Financial period / perimeter | period basis: n/a; perimeter: n/a |
| Unit handling | Every figure converted to Rs Crore from the unit declared on its own page (Rs '000 / million / crore); ratio is a percentage. |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) |
| Relevant tests | 5 specific / 20 generic; e.g. `test_final_validation_regressions.py::test_bank_ratios_missing_inputs_are_not_zero`, `test_ratio_corrections_2026_10b.py::test_disclosed_ratios_missing_are_not_disclosed_never_zero`, `test_ratio_formula_oracle.py::test_registry_has_exactly_68_ratios_each_with_a_contract_or_provider_path` |
| Cross-company run | 17 real filings run: not_applicable=11, not_disclosed=2, verified=4 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | ANURAS is a non-lender (correctly not_applicable); validated on 4 bank filings, 4 with the value printed verbatim in the bank's own report |
| ANURAS FY2026 matrix verdict | PASS (value -, engine status `not_applicable`) |
| **Status (this document)** | **PASS** |

### Sr 63 - Capital Adequacy Ratio (CRAR) (internal id `capital_adequacy_ratio`)

| Field | Detail |
|---|---|
| Category | Banking-specific |
| Approved formula (`tools/fundamental_ratio_registry.py`) | (Tier I Capital + Tier II Capital) ÷ Risk-Weighted Assets |
| Actual implementation (`ratio_contract.SPEC`) | Total capital funds / Risk-weighted assets (Basel III table) when both are printed; else the disclosed total CRAR. [docs/ratio_contract.md] |
| Formula as printed in the calculation breakdown | not produced by the contract (bank / market-data / shareholding rows use their own provider) |
| Required facts (read by the engine) | - |
| Source and extraction path | Bank annual report (RBI-format schedules) -> `tools/bank_extractor.py` (word-coordinate row reader, unit-normalised, identity-gated) -> `tools/bank_ratios.py` -> `ratio_contract.guard_bank` plausibility bounds. Sector-gated (Banks / NBFC only; others `not_applicable`). |
| Financial period / perimeter | period basis: n/a; perimeter: n/a |
| Unit handling | Every figure converted to Rs Crore from the unit declared on its own page (Rs '000 / million / crore); ratio is a percentage. |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) |
| Relevant tests | 6 specific / 20 generic; e.g. `test_final_validation_regressions.py::test_bank_ratios_missing_inputs_are_not_zero`, `test_ratio_corrections_2026_10b.py::test_crar_computed_from_capital_and_rwa`, `test_ratio_corrections_2026_10b.py::test_disclosed_ratios_missing_are_not_disclosed_never_zero` |
| Cross-company run | 17 real filings run: not_applicable=11, not_disclosed=1, verified=5 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | ANURAS is a non-lender (correctly not_applicable); validated on 4 bank filings, 4 with the value printed verbatim in the bank's own report |
| ANURAS FY2026 matrix verdict | PASS (value -, engine status `not_applicable`) |
| **Status (this document)** | **PASS** |

### Sr 64 - Credit-to-Deposit Ratio (internal id `credit_to_deposit_ratio`)

| Field | Detail |
|---|---|
| Category | Banking-specific |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Total Advances ÷ Total Deposits |
| Actual implementation (`ratio_contract.SPEC`) | Advances / Deposits (balance-sheet face); NBFCs: not applicable. [docs/ratio_contract.md] |
| Formula as printed in the calculation breakdown | not produced by the contract (bank / market-data / shareholding rows use their own provider) |
| Required facts (read by the engine) | - |
| Source and extraction path | Bank annual report (RBI-format schedules) -> `tools/bank_extractor.py` (word-coordinate row reader, unit-normalised, identity-gated) -> `tools/bank_ratios.py` -> `ratio_contract.guard_bank` plausibility bounds. Sector-gated (Banks / NBFC only; others `not_applicable`). |
| Financial period / perimeter | period basis: n/a; perimeter: n/a |
| Unit handling | Every figure converted to Rs Crore from the unit declared on its own page (Rs '000 / million / crore); ratio is a percentage. |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) |
| Relevant tests | 5 specific / 20 generic; e.g. `test_final_validation_regressions.py::test_bank_ratios_missing_inputs_are_not_zero`, `test_ratio_corrections_2026_10b.py::test_credit_to_deposit_and_cost_to_income`, `test_ratio_formula_oracle.py::test_registry_has_exactly_68_ratios_each_with_a_contract_or_provider_path` |
| Cross-company run | 17 real filings run: not_applicable=13, verified=4 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | ANURAS is a non-lender (correctly not_applicable). The value is computed from the bank's statements (identity-gated) and is verified on 4 bank filings, but it is printed verbatim in the bank's own report for only 1 of them (definition differences, e.g. the bank's own NIM/CASA basis) - not independently corroborated. Values: ['HDFCBANK=96.5', 'ICICIBANK=83.32', 'KOTAKBANK=85.54', 'SBIN=77.35'] |
| ANURAS FY2026 matrix verdict | NEEDS REVIEW (value -, engine status `not_applicable`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 65 - Cost-to-Income Ratio (internal id `cost_to_income_ratio`)

| Field | Detail |
|---|---|
| Category | Banking-specific |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Operating Expenses ÷ (Net Interest Income + Other Income) |
| Actual implementation (`ratio_contract.SPEC`) | Operating expenses / (Net interest income + Other income); NBFC/HFC: (Employee + Depreciation + Other expenses) / (Total income - Finance costs). [docs/ratio_contract.md] |
| Formula as printed in the calculation breakdown | not produced by the contract (bank / market-data / shareholding rows use their own provider) |
| Required facts (read by the engine) | - |
| Source and extraction path | Bank annual report (RBI-format schedules) -> `tools/bank_extractor.py` (word-coordinate row reader, unit-normalised, identity-gated) -> `tools/bank_ratios.py` -> `ratio_contract.guard_bank` plausibility bounds. Sector-gated (Banks / NBFC only; others `not_applicable`). |
| Financial period / perimeter | period basis: n/a; perimeter: n/a |
| Unit handling | Every figure converted to Rs Crore from the unit declared on its own page (Rs '000 / million / crore); ratio is a percentage. |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) |
| Relevant tests | 5 specific / 20 generic; e.g. `test_final_validation_regressions.py::test_bank_ratios_missing_inputs_are_not_zero`, `test_ratio_corrections_2026_10b.py::test_credit_to_deposit_and_cost_to_income`, `test_ratio_formula_oracle.py::test_registry_has_exactly_68_ratios_each_with_a_contract_or_provider_path` |
| Cross-company run | 17 real filings run: not_applicable=11, verified=6 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | ANURAS is a non-lender (correctly not_applicable); validated on 4 bank filings, 3 with the value printed verbatim in the bank's own report |
| ANURAS FY2026 matrix verdict | PASS (value -, engine status `not_applicable`) |
| **Status (this document)** | **PASS** |

### Sr 66 - Beta (internal id `beta`)

| Field | Detail |
|---|---|
| Category | Market / Shareholding |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Covariance(Stock Returns, Market Returns) ÷ Variance(Market Returns) |
| Actual implementation (`ratio_contract.SPEC`) | Beta = sample covariance(stock weekly returns, Nifty 50 weekly returns) / sample variance(Nifty 50), 2 years, >= 52 aligned weekly observations (ddof=1); below that insufficient_data (`rc.BETA_POLICY`, `tools/market_history.py`). |
| Formula as printed in the calculation breakdown | not produced by the contract (bank / market-data / shareholding rows use their own provider) |
| Required facts (read by the engine) | - |
| Source and extraction path | Price history, not a filing: `tools/market_history.py` (Yahoo Finance weekly closes for `<SYM>.NS` vs `^NSEI`, 2y) -> `ratio_contract.beta_result`. Manual-upload mode reports `insufficient_data` by policy. |
| Financial period / perimeter | period basis: n/a; perimeter: n/a |
| Unit handling | Dimensionless (ratio of return series). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) |
| Relevant tests | 7 specific / 20 generic; e.g. `test_full_quant_coverage.py::test_s_beta_computed_from_real_series`, `test_full_quant_coverage.py::test_s_beta_insufficient_when_no_price_history`, `test_ratio_breakdown.py::test_pledge_beta_free_float_breakdowns_reconcile` |
| Cross-company run | 17 real filings run: insufficient_data=17 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | Insufficient_data by policy in the manual document mode (no price series in an uploaded filing); estimator covered by tests. |
| ANURAS FY2026 matrix verdict | NEEDS REVIEW (value -, engine status `insufficient_data`) |
| **Status (this document)** | **NEEDS REVIEW** |

### Sr 67 - Promoter Pledge % (internal id `promoter_pledge_pct`)

| Field | Detail |
|---|---|
| Category | Market / Shareholding |
| Approved formula (`tools/fundamental_ratio_registry.py`) | Pledged Promoter Shares ÷ Total Promoter Shareholding |
| Actual implementation (`ratio_contract.SPEC`) | Pledged promoter shares / total promoter shares from the Shareholding Pattern (`ratio_contract.pledge_result`); filing-disclosed count -> verified, value inferred from NSE pledge dataset -> needs_review. |
| Formula as printed in the calculation breakdown | not produced by the contract (bank / market-data / shareholding rows use their own provider) |
| Required facts (read by the engine) | - |
| Source and extraction path | Shareholding Pattern: the uploaded filing when present (manual mode), otherwise the NSE endpoint via `tools/shareholding_scraper.py` (secondary source -> `needs_review`) -> `ratio_contract.pledge_result` / `free_float_result`. |
| Financial period / perimeter | period basis: n/a; perimeter: n/a |
| Unit handling | Share counts -> percentage computed from counts (not the filing's 4-dp tagged fraction). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) |
| Relevant tests | 8 specific / 20 generic; e.g. `test_final_validation_regressions.py::test_inferred_zero_pledge_is_not_verified`, `test_full_quant_coverage.py::test_t_impossible_pledge_percentage_is_withheld`, `test_full_quant_coverage.py::test_t_promoter_pledge_assumed_zero_is_insufficient_not_a_zero` |
| Cross-company run | 17 real filings run: insufficient_data=17 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | Found by this audit: pledge came out needs_review ('NSE endpoint, secondary') although the uploaded filing itself carries the pledged count and percentage. Fixed 2026.10.13 -> verified, cross-checked against the filing's own percentage. |
| ANURAS FY2026 matrix verdict | PASS (value 21.79, engine status `verified`) |
| **Status (this document)** | **PASS** |

### Sr 68 - Free Float % (internal id `free_float_pct`)

| Field | Detail |
|---|---|
| Category | Market / Shareholding |
| Approved formula (`tools/fundamental_ratio_registry.py`) | (Total Shares − Promoter Holding − Locked-in Shares) ÷ Total Shares |
| Actual implementation (`ratio_contract.SPEC`) | (Total shares - promoter holding - locked-in shares) / total shares x 100 (`ratio_contract.free_float_result`); exact when the filing states locked-in shares (or none), otherwise a labelled proxy. |
| Formula as printed in the calculation breakdown | not produced by the contract (bank / market-data / shareholding rows use their own provider) |
| Required facts (read by the engine) | - |
| Source and extraction path | Shareholding Pattern: the uploaded filing when present (manual mode), otherwise the NSE endpoint via `tools/shareholding_scraper.py` (secondary source -> `needs_review`) -> `ratio_contract.pledge_result` / `free_float_result`. |
| Financial period / perimeter | period basis: n/a; perimeter: n/a |
| Unit handling | Share counts -> percentage computed from counts (not the filing's 4-dp tagged fraction). |
| Dependencies (parent ratios) | none (direct from facts) |
| Missing-data behaviour | no per-fact probe recorded in the matrix for this row; the generic rule applies (an unknown input yields `insufficient_data` / `not_disclosed`, never 0) |
| Relevant tests | 3 specific / 20 generic; e.g. `test_full_quant_coverage.py::test_u_free_float_not_disclosed_when_no_shareholding_data`, `test_full_quant_coverage.py::test_u_free_float_proxy_is_needs_review`, `test_ratio_formula_oracle.py::test_registry_has_exactly_68_ratios_each_with_a_contract_or_provider_path` |
| Cross-company run | 17 real filings run: insufficient_data=17 (status/invariant check only - values were not re-verified against an external source) |
| Trusted-source comparison | n/a (not a Screener metric) |
| Known discrepancy | Found by this audit: free float was a labelled proxy although the uploaded filing states there are NO locked-in shares in any category. Fixed 2026.10.13 -> exact (100 - promoter %). |
| ANURAS FY2026 matrix verdict | PASS (value 40.93, engine status `verified`) |
| **Status (this document)** | **PASS** |

