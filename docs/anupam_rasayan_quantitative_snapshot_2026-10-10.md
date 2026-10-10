# Anupam Rasayan India Ltd - Quantitative section snapshot (2026-10-10)

Snapshot id **cf96428d9e46** (SHA-1 of the captured response). Read-only capture of what the running Navrist application serves to the **Quantitative Analysis** tab; the CSV `docs/anupam_rasayan_quantitative_snapshot_2026-10-10.csv` is rendered from the same response and carries the same id.

## 1. Company, reporting period and timestamps

* **Company (as in the filing):** Anupam Rasayan India Limited (CIN L24231GJ2003PLC042988, read from the annual-report text)
* **Navrist symbol:** ANURAS - the only registry entry containing 'Anupam' (cache/nse_company_names.json)
* **Reporting period shown:** FY2025-26 (year ended 31-Mar-2026), annual (non-TTM); the FY2024-25 column is the opening balance
* **Reporting basis:** CONSOLIDATED statements; statement-based rows carry `statement_basis = consolidated`; bank-only, shareholding and beta rows are not statement-based
* **Source document:** Uploaded Annual Report `ANURAS_2026.pdf` (Integrated Report 2025-26): consolidated balance sheet p.264, P&L p.265, cash flow p.299 as recorded by the application
* **Endpoint:** GET /api/v1/document-analysis/ANURAS (FastAPI `document_analysis_get_endpoint` in app.py -> `ensure_current_fundamental_results`) - the only request the Quantitative tab makes
* **Backend / data source:** FastAPI app.py on 127.0.0.1:8000; rows stored in `fundamental_analysis_results` (Supabase); inputs from the uploaded annual report PDF, the uploaded shareholding filing, the Angel One live quote and Yahoo Finance weekly prices (beta)
* **Formula version(s) in the response:** 2026.10.18
* **Calculation times (UTC):** first 2026-10-10T09:40:08, last 2026-10-10T09:40:14 (spread 6 s - every row was produced by one analysis run)
* **Quote time(s) on market-dependent rows (UTC):** 2026-10-10 09:40 UTC (a single quote shared by every market-dependent row)
* **Source retrieval:** the annual report and shareholding filing are uploaded documents (not re-fetched at calculation time); the quote is fetched once at the start of the run and its time is shown above; weekly prices for beta come from Yahoo Finance at run time

## 2. Complete list of displayed quantitative values

68 metrics. Display strings mirror `fmtRatioValue` (`%` and `x` 2 dp, `₹ Cr` 0 dp Indian grouping, others up to 2 dp); the unrounded API value is in the CSV.

### Priority cards (top of tab) - visible by default (13)

| Sr | Displayed name | Displayed value | Unit | FY | Basis | Availability | API status |
|---|---|---|---|---|---|---|---|
| 2 | Inventory Days | 444.96 | days | FY2025-26 | consolidated | available (needs review) | needs_review |
| 4 | Debtor Days | 130.63 | days | FY2025-26 | consolidated | available (needs review) | needs_review |
| 6 | Days Payable | 187.91 | days | FY2025-26 | consolidated | available (needs review) | needs_review |
| 9 | Cash Conversion Cycle | 387.68 | days | FY2025-26 | consolidated | available (needs review) | needs_review |
| 15 | EBIT Margin % | 17.04% | % | FY2025-26 | consolidated | available | verified |
| 18 | ROE % | 5.53% | % | FY2025-26 | consolidated | available | verified |
| 19 | ROCE % | 9.10% | % | FY2025-26 | consolidated | available (needs review) | needs_review |
| 24 | Stock P/E | 75.04x | x | FY2025-26 | consolidated | available | verified |
| 27 | Dividend Yield % | 0.13% | % | FY2025-26 | consolidated | available | verified |
| 31 | Working Capital Days | 144.8 | days | FY2025-26 | consolidated | available (needs review) | needs_review |
| 36 | Free Cash Flow | ₹-221 Cr | ₹ Cr | FY2025-26 | consolidated | available | verified |
| 43 | Tax % | 12.66% | % | FY2025-26 | consolidated | available | verified |
| 47 | Dividend Payout % | 5.02% | % | FY2025-26 | consolidated | available | verified |

### Balance Sheet - visible by default (9)

| Sr | Displayed name | Displayed value | Unit | FY | Basis | Availability | API status |
|---|---|---|---|---|---|---|---|
| 10 | Current Ratio | 1.43x | x | FY2025-26 | consolidated | available | verified |
| 11 | Quick Ratio | 0.75x | x | FY2025-26 | consolidated | available | verified |
| 12 | Cash Ratio | 0.15x | x | FY2025-26 | consolidated | available (needs review) | needs_review |
| 13 | Working Capital | ₹1,112 Cr | ₹ Cr | FY2025-26 | consolidated | available | verified |
| 20 | Debt-to-Equity Ratio | 0.40x | x | FY2025-26 | consolidated | available | verified |
| 21 | Debt Ratio | 0.23x | x | FY2025-26 | consolidated | available | verified |
| 23 | Financial Leverage Ratio | 1.72x | x | FY2025-26 | consolidated | available (needs review) | needs_review |
| 32 | Receivables-to-Payables Ratio | 1.01x | x | FY2025-26 | consolidated | available | verified |
| 46 | Book Value per Share (BVPS) | 290.02 | ₹ | FY2025-26 | consolidated | available | verified |

### P&L - visible by default (5)

| Sr | Displayed name | Displayed value | Unit | FY | Basis | Availability | API status |
|---|---|---|---|---|---|---|---|
| 14 | Gross Profit Margin | 44.06% | % | FY2025-26 | consolidated | available | verified |
| 16 | Net Profit Margin | 7.19% | % | FY2025-26 | consolidated | available | verified |
| 22 | Interest Coverage Ratio | 2.71x | x | FY2025-26 | consolidated | available | verified |
| 44 | Contribution Margin | 38.06% | % | FY2025-26 | consolidated | available (needs review) | needs_review |
| 45 | EPS Growth Rate | 77.53% | % | FY2025-26 | consolidated | available | verified |

### P&L + Balance Sheet - behind 'Show More Ratios' (9)

| Sr | Displayed name | Displayed value | Unit | FY | Basis | Availability | API status |
|---|---|---|---|---|---|---|---|
| 1 | Inventory Turnover | 0.82x | x | FY2025-26 | consolidated | available (needs review) | needs_review |
| 3 | Receivables Turnover | 2.79x | x | FY2025-26 | consolidated | available (needs review) | needs_review |
| 5 | Payables Turnover | 1.94x | x | FY2025-26 | consolidated | available (needs review) | needs_review |
| 7 | Asset Turnover | 0.36x | x | FY2025-26 | consolidated | available (needs review) | needs_review |
| 8 | Working Capital Turnover | 2.52x | x | FY2025-26 | consolidated | available (needs review) | needs_review |
| 17 | Return on Assets (ROA) | 2.56% | % | FY2025-26 | consolidated | available (needs review) | needs_review |
| 30 | Fixed Asset Turnover | 0.87x | x | FY2025-26 | consolidated | available (needs review) | needs_review |
| 33 | Net Debt/EBITDA | 2.74x | x | FY2025-26 | consolidated | available (needs review) | needs_review |
| 42 | Return on Invested Capital (ROIC) | 5.75% | % | FY2025-26 | consolidated | available (needs review) | needs_review |

### Cash Flow - behind 'Show More Ratios' (6)

| Sr | Displayed name | Displayed value | Unit | FY | Basis | Availability | API status |
|---|---|---|---|---|---|---|---|
| 34 | Debt Service Coverage Ratio (DSCR) | - | - | FY2025-26 | consolidated | unavailable (insufficient data) | insufficient_data |
| 35 | Cash Flow Coverage Ratio | 0.18x | x | FY2025-26 | consolidated | available | verified |
| 38 | FCF Margin | -9.34% | % | FY2025-26 | consolidated | available | verified |
| 39 | Operating Cash Flow Ratio | 0.13x | x | FY2025-26 | consolidated | available (needs review) | needs_review |
| 40 | Capex Intensity | 23.47% | % | FY2025-26 | consolidated | available | verified |
| 41 | OCF/Net Profit | 1.50x | x | FY2025-26 | consolidated | available | verified |

### Multi-source / Derived - behind 'Show More Ratios' (5)

| Sr | Displayed name | Displayed value | Unit | FY | Basis | Availability | API status |
|---|---|---|---|---|---|---|---|
| 48 | Retention Ratio | 94.98% | % | FY2025-26 | consolidated | available | verified |
| 49 | Sustainable Growth Rate | 5.25% | % | FY2025-26 | consolidated | available | verified |
| 55 | Altman Z-Score | 3.09 | score | FY2025-26 | consolidated | available | verified |
| 56 | Piotroski F-Score | 6 | - | FY2025-26 | consolidated | available | verified |
| 57 | Beneish M-Score | -1.83 | - | FY2025-26 | consolidated | available (needs review) | needs_review |

### Market / Valuation - behind 'Show More Ratios' (10)

| Sr | Displayed name | Displayed value | Unit | FY | Basis | Availability | API status |
|---|---|---|---|---|---|---|---|
| 25 | Price-to-Book (P/B) | 3.90x | x | FY2025-26 | consolidated | available | verified |
| 26 | Price-to-Sales (P/S) | 5.45x | x | FY2025-26 | consolidated | available | verified |
| 28 | Earnings Yield | 1.33% | % | FY2025-26 | consolidated | available | verified |
| 29 | Enterprise Value/EBITDA | 26.48x | x | FY2025-26 | consolidated | available | verified |
| 37 | FCF Yield | -1.71% | % | FY2025-26 | consolidated | available | verified |
| 50 | PEG Ratio | 0.97x | x | FY2025-26 | consolidated | available | verified |
| 51 | EV/Sales | 6.08x | x | FY2025-26 | consolidated | available | verified |
| 52 | EV/FCF | -65.13x | x | FY2025-26 | consolidated | value displayed but flagged NOT MEANINGFUL by the engine | not_meaningful |
| 53 | Price/Cash Flow | 38.56x | x | FY2025-26 | consolidated | available | verified |
| 54 | Graham Number | 313.8 | ₹ | FY2025-26 | consolidated | available | verified |

### Banking-specific - behind 'Show More Ratios' (8)

| Sr | Displayed name | Displayed value | Unit | FY | Basis | Availability | API status |
|---|---|---|---|---|---|---|---|
| 58 | Net Interest Margin (NIM) | - | - | - | - | not applicable | not_applicable |
| 59 | CASA Ratio | - | - | - | - | not applicable | not_applicable |
| 60 | Gross NPA % | - | - | - | - | not applicable | not_applicable |
| 61 | Net NPA % | - | - | - | - | not applicable | not_applicable |
| 62 | Provision Coverage Ratio (PCR) | - | - | - | - | not applicable | not_applicable |
| 63 | Capital Adequacy Ratio (CRAR) | - | - | - | - | not applicable | not_applicable |
| 64 | Credit-to-Deposit Ratio | - | - | - | - | not applicable | not_applicable |
| 65 | Cost-to-Income Ratio | - | - | - | - | not applicable | not_applicable |

### Market / Shareholding - behind 'Show More Ratios' (3)

| Sr | Displayed name | Displayed value | Unit | FY | Basis | Availability | API status |
|---|---|---|---|---|---|---|---|
| 66 | Beta | 0.8 | - | - | - | available | verified |
| 67 | Promoter Pledge % | 21.79% | % | - | - | available | verified |
| 68 | Free Float % | 40.93% | % | - | - | available | verified |

## 3. Underlying formulas and input evidence

Every input shows period, basis, source, page, statement and origin (`reported` = read from the annual report, `derived` = built from other facts, market = live quote). Fields the API does not expose are shown as *not recorded*.

### 1. Inventory Turnover - 0.82x

* Formula: `Cost of Goods Sold ÷ Average Inventory`
* Expression: `₹1,323.26 Cr ÷ ₹1,613.13 Cr`
  * Numerator: ₹1,323.26 Cr  
  * Denominator: ₹1,613.13 Cr
* Step: Average Inventory: (₹1,451.50 Cr + ₹1,774.75 Cr) ÷ 2 = ₹1,613.13 Cr
* Inputs:
  * Cost of Goods Sold | [Cost of Goods Sold (sum of the P&L cost lines below)] | ₹1,323.26 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=derived | derivation=sum(components)
  * FY2025 Inventory | ₹1,451.50 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * FY2026 Inventory | ₹1,774.75 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
* Reason: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).
* Warning: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).

### 2. Inventory Days - 444.96

* Formula: `365 ÷ Inventory Turnover`
* Expression: `365 ÷ 0.8203`
  * Numerator: 365  
  * Denominator: 0.8203
* Inputs:
  * PARENT RATIO Inventory Turnover | 0.82x | period=FY2026 | basis=consolidated | source=calculated parent ratio | page=not recorded | origin=needs_review
  * Cost of Goods Sold | [Cost of Goods Sold (sum of the P&L cost lines below)] | ₹1,323.26 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=derived | derivation=sum(components)
  * FY2025 Inventory | ₹1,451.50 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * FY2026 Inventory | ₹1,774.75 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
* Warning: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).

### 3. Receivables Turnover - 2.79x

* Formula: `Revenue from Operations ÷ Average Trade Receivables`
* Expression: `₹2,365.45 Cr ÷ ₹846.57 Cr`
  * Numerator: ₹2,365.45 Cr  
  * Denominator: ₹846.57 Cr
* Step: Average Trade Receivables: (₹733.76 Cr + ₹959.38 Cr) ÷ 2 = ₹846.57 Cr
* Inputs:
  * Revenue from Operations | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf
  * FY2025 Trade Receivables | ₹733.76 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * FY2026 Trade Receivables | ₹959.38 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
* Reason: Net credit sales are not disclosed; Revenue from Operations is used as the proxy.; Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).
* Warning: Net credit sales are not disclosed; Revenue from Operations is used as the proxy.
* Warning: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).

### 4. Debtor Days - 130.63

* Formula: `365 ÷ Receivables Turnover`
* Expression: `365 ÷ 2.7942`
  * Numerator: 365  
  * Denominator: 2.7942
* Inputs:
  * PARENT RATIO Receivables Turnover | 2.79x | period=FY2026 | basis=consolidated | source=calculated parent ratio | page=not recorded | origin=needs_review
  * Revenue from Operations | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf
  * FY2025 Trade Receivables | ₹733.76 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * FY2026 Trade Receivables | ₹959.38 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
* Warning: Net credit sales are not disclosed; Revenue from Operations is used as the proxy.
* Warning: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).

### 5. Payables Turnover - 1.94x

* Formula: `Purchases ÷ Average Trade Payables`
* Expression: `₹1,478.12 Cr ÷ ₹760.95 Cr`
  * Numerator: ₹1,478.12 Cr  
  * Denominator: ₹760.95 Cr
* Step: Average Trade Payables: (₹576.38 Cr + ₹945.53 Cr) ÷ 2 = ₹760.95 Cr
* Inputs:
  * Purchases | [Purchases (a: Purchases during the year (Cost of Materials Consumed note); no Purchases of stock-in-trade disclosed)] | ₹1,478.12 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Notes to the financial statements (cost of materials consumed) | page=not recorded | origin=derived | derivation=purchases_during_the_year
  * FY2025 Trade Payables | ₹576.38 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * FY2026 Trade Payables | ₹945.53 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
* Reason: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).
* Warning: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).

### 6. Days Payable - 187.91

* Formula: `365 ÷ Payables Turnover`
* Expression: `365 ÷ 1.9425`
  * Numerator: 365  
  * Denominator: 1.9425
* Inputs:
  * PARENT RATIO Payables Turnover | 1.94x | period=FY2026 | basis=consolidated | source=calculated parent ratio | page=not recorded | origin=needs_review
  * Purchases | [Purchases (a: Purchases during the year (Cost of Materials Consumed note); no Purchases of stock-in-trade disclosed)] | ₹1,478.12 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Notes to the financial statements (cost of materials consumed) | page=not recorded | origin=derived | derivation=purchases_during_the_year
  * FY2025 Trade Payables | ₹576.38 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * FY2026 Trade Payables | ₹945.53 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
* Warning: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).

### 7. Asset Turnover - 0.36x

* Formula: `Revenue from Operations ÷ Average Total Assets`
* Expression: `₹2,365.45 Cr ÷ ₹6,640.74 Cr`
  * Numerator: ₹2,365.45 Cr  
  * Denominator: ₹6,640.74 Cr
* Step: Average Total Assets: (₹5,268.88 Cr + ₹8,012.60 Cr) ÷ 2 = ₹6,640.74 Cr
* Inputs:
  * Revenue from Operations | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf
  * FY2025 Total Assets | ₹5,268.88 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * FY2026 Total Assets | ₹8,012.60 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
* Reason: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).
* Warning: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).

### 8. Working Capital Turnover - 2.52x

* Formula: `Revenue from Operations ÷ Average Working Capital`
* Expression: `₹2,365.45 Cr ÷ ₹938.41 Cr`
  * Numerator: ₹2,365.45 Cr  
  * Denominator: ₹938.41 Cr
* Step: FY2025 Working Capital: ₹2,572.95 Cr − ₹1,808.20 Cr = ₹764.74 Cr
* Step: FY2026 Working Capital: ₹3,727.51 Cr − ₹2,615.44 Cr = ₹1,112.07 Cr
* Step: Average Working Capital: (₹764.74 Cr + ₹1,112.07 Cr) ÷ 2 = ₹938.41 Cr
* Inputs:
  * Revenue from Operations | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf
  * Total Current Assets | ₹2,572.95 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Current Liabilities | ₹1,808.20 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Current Assets | ₹3,727.51 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Current Liabilities | ₹2,615.44 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
* Reason: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).
* Warning: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).

### 9. Cash Conversion Cycle - 387.68

* Formula: `Debtor Days + Inventory Days − Days Payable`
* Expression: `130.6296 + 444.9565 − 187.9067`
* Inputs:
  * PARENT RATIO Debtor Days | 130.63 days | period=FY2026 | basis=consolidated | source=calculated parent ratio | page=not recorded | origin=needs_review
  * PARENT RATIO Receivables Turnover | 2.79x | period=FY2026 | basis=consolidated | source=calculated parent ratio | page=not recorded | origin=needs_review
  * Revenue from Operations | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf
  * FY2025 Trade Receivables | ₹733.76 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * FY2026 Trade Receivables | ₹959.38 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * PARENT RATIO Inventory Days | 444.96 days | period=FY2026 | basis=consolidated | source=calculated parent ratio | page=not recorded | origin=needs_review
  * PARENT RATIO Inventory Turnover | 0.82x | period=FY2026 | basis=consolidated | source=calculated parent ratio | page=not recorded | origin=needs_review
  * Cost of Goods Sold | [Cost of Goods Sold (sum of the P&L cost lines below)] | ₹1,323.26 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=derived | derivation=sum(components)
  * FY2025 Inventory | ₹1,451.50 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * FY2026 Inventory | ₹1,774.75 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * PARENT RATIO Days Payable | 187.91 days | period=FY2026 | basis=consolidated | source=calculated parent ratio | page=not recorded | origin=needs_review
  * PARENT RATIO Payables Turnover | 1.94x | period=FY2026 | basis=consolidated | source=calculated parent ratio | page=not recorded | origin=needs_review
  * Purchases | [Purchases (a: Purchases during the year (Cost of Materials Consumed note); no Purchases of stock-in-trade disclosed)] | ₹1,478.12 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Notes to the financial statements (cost of materials consumed) | page=not recorded | origin=derived | derivation=purchases_during_the_year
  * FY2025 Trade Payables | ₹576.38 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * FY2026 Trade Payables | ₹945.53 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
* Warning: Net credit sales are not disclosed; Revenue from Operations is used as the proxy.
* Warning: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).

### 10. Current Ratio - 1.43x

* Formula: `Total Current Assets ÷ Total Current Liabilities`
* Expression: `₹3,727.51 Cr ÷ ₹2,615.44 Cr`
  * Numerator: ₹3,727.51 Cr  
  * Denominator: ₹2,615.44 Cr
* Inputs:
  * Total Current Assets (closing) | ₹3,727.51 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Current Liabilities (closing) | ₹2,615.44 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf

### 11. Quick Ratio - 0.75x

* Formula: `(Total Current Assets − Inventories) ÷ Total Current Liabilities`
* Expression: `₹1,952.76 Cr ÷ ₹2,615.44 Cr`
  * Numerator: ₹1,952.76 Cr  
  * Denominator: ₹2,615.44 Cr
* Step: Total Current Assets − Inventories: ₹3,727.51 Cr − ₹1,774.75 Cr = ₹1,952.76 Cr
* Inputs:
  * Total Current Assets | ₹3,727.51 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Inventories | ₹1,774.75 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Current Liabilities (closing) | ₹2,615.44 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf

### 12. Cash Ratio - 0.15x

* Formula: `(Cash and Cash Equivalents + Unrestricted Other Bank Balances) ÷ Total Current Liabilities`
* Expression: `₹386.33 Cr ÷ ₹2,615.44 Cr`
  * Numerator: ₹386.33 Cr  
  * Denominator: ₹2,615.44 Cr
* Step: Cash and Cash Equivalents + Unrestricted Other Bank Balances: ₹378.07 Cr + ₹8.26 Cr = ₹386.33 Cr
* Inputs:
  * Cash and Cash Equivalents | ₹378.07 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Unrestricted Other Bank Balances (Notes breakup) | ₹8.26 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | page=not recorded | origin=reported
  * Total Current Liabilities (closing) | ₹2,615.44 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
* Reason: Restricted / lien-marked balances of 7.30 Cr were excluded from the numerator.; 7.61 Cr of other bank balances sits on a line whose nature the note does not state (e.g. 'Deposit account'); no restriction is disclosed so it is included, but it is not confirmed as free cash.
* Warning: Restricted / lien-marked balances of 7.30 Cr were excluded from the numerator.
* Warning: 7.61 Cr of other bank balances sits on a line whose nature the note does not state (e.g. 'Deposit account'); no restriction is disclosed so it is included, but it is not confirmed as free cash.

### 13. Working Capital - ₹1,112 Cr

* Formula: `Total Current Assets − Total Current Liabilities`
* Expression: `₹3,727.51 Cr − ₹2,615.44 Cr`
* Inputs:
  * Total Current Assets (closing) | ₹3,727.51 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Current Liabilities (closing) | ₹2,615.44 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf

### 14. Gross Profit Margin - 44.06%

* Formula: `(Gross Profit ÷ Revenue from Operations) × 100`
* Expression: `(₹1,042.20 Cr ÷ ₹2,365.45 Cr) × 100`
  * Numerator: (₹1,042.20 Cr  
  * Denominator: ₹2,365.45 Cr) × 100
* Step: Gross Profit: ₹2,365.45 Cr − ₹1,442.01 Cr − (−₹118.75 Cr) = ₹1,042.20 Cr
* Inputs:
  * Revenue from Operations | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf
  * Cost of materials consumed | ₹1,442.01 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Statement of Profit and Loss (expense note) | page=not recorded | origin=reported
  * Changes in inventories | −₹118.75 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Statement of Profit and Loss (expense note) | page=not recorded | origin=reported

### 15. EBIT Margin % - 17.04%

* Formula: `(Operating Profit ÷ Revenue from Operations) × 100`
* Expression: `(₹403.12 Cr ÷ ₹2,365.45 Cr) × 100`
  * Numerator: (₹403.12 Cr  
  * Denominator: ₹2,365.45 Cr) × 100
* Step: Operating Profit: ₹254.40 Cr + ₹148.71 Cr = ₹403.12 Cr
* Inputs:
  * Profit Before Tax | ₹254.40 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Finance Costs (added back) | ₹148.71 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Revenue from Operations | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf

### 16. Net Profit Margin - 7.19%

* Formula: `(Profit for the Year Attributable to Owners of the Company ÷ Revenue from Operations) × 100`
* Expression: `(₹170.12 Cr ÷ ₹2,365.45 Cr) × 100`
  * Numerator: (₹170.12 Cr  
  * Denominator: ₹2,365.45 Cr) × 100
* Inputs:
  * Profit for the Year Attributable to Owners of the Company | ₹170.12 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Revenue from Operations | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf
* Reason: Perimeter: owners' profit over 100%-consolidated revenue (NCI share of profit excluded).
* Warning: Perimeter: owners' profit over 100%-consolidated revenue (NCI share of profit excluded).

### 17. Return on Assets (ROA) - 2.56%

* Formula: `(Profit After Tax ÷ Average Total Assets) × 100`
* Expression: `(₹170.12 Cr ÷ ₹6,640.74 Cr) × 100`
  * Numerator: (₹170.12 Cr  
  * Denominator: ₹6,640.74 Cr) × 100
* Step: Average Total Assets: (₹5,268.88 Cr + ₹8,012.60 Cr) ÷ 2 = ₹6,640.74 Cr
* Inputs:
  * Profit After Tax (owners-attributable) | ₹170.12 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * FY2025 Total Assets | ₹5,268.88 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * FY2026 Total Assets | ₹8,012.60 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
* Reason: Perimeter: owners' profit over whole-entity assets (assets include NCI-funded assets).; Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).
* Warning: Perimeter: owners' profit over whole-entity assets (assets include NCI-funded assets).
* Warning: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).

### 18. ROE % - 5.53%

* Formula: `(Profit After Tax ÷ Average Total Equity) × 100`
* Expression: `(₹170.12 Cr ÷ ₹3,076.08 Cr) × 100`
  * Numerator: (₹170.12 Cr  
  * Denominator: ₹3,076.08 Cr) × 100
* Step: Average Total Equity: (₹2,850.31 Cr + ₹3,301.84 Cr) ÷ 2 = ₹3,076.08 Cr
* Inputs:
  * Profit After Tax (owners-attributable) | ₹170.12 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * FY2025 Total Equity | ₹2,850.31 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * FY2026 Total Equity | ₹3,301.84 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf

### 19. ROCE % - 9.10%

* Formula: `(EBIT ÷ Average Capital Employed) × 100`
* Expression: `(₹403.12 Cr ÷ ₹4,428.92 Cr) × 100`
  * Numerator: (₹403.12 Cr  
  * Denominator: ₹4,428.92 Cr) × 100
* Step: EBIT: ₹254.40 Cr + ₹148.71 Cr = ₹403.12 Cr
* Step: FY2025 Capital Employed: ₹5,268.88 Cr − ₹1,808.20 Cr = ₹3,460.68 Cr
* Step: FY2026 Capital Employed: ₹8,012.60 Cr − ₹2,615.44 Cr = ₹5,397.17 Cr
* Step: Average Capital Employed: (₹3,460.68 Cr + ₹5,397.17 Cr) ÷ 2 = ₹4,428.92 Cr
* Inputs:
  * Profit Before Tax | ₹254.40 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Finance Costs (added back) | ₹148.71 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Total Assets | ₹5,268.88 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Current Liabilities | ₹1,808.20 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Assets | ₹8,012.60 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Current Liabilities | ₹2,615.44 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
* Reason: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).
* Warning: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).

### 20. Debt-to-Equity Ratio - 0.40x

* Formula: `Total Debt ÷ Total Equity incl. Non-Controlling Interests`
* Expression: `₹1,867.49 Cr ÷ ₹4,629.96 Cr`
  * Numerator: ₹1,867.49 Cr  
  * Denominator: ₹4,629.96 Cr
* Step: Total Debt: ₹1,814.65 Cr + ₹52.83 Cr = ₹1,867.49 Cr
* Step: Total Equity incl. Non-Controlling Interests: ₹3,301.84 Cr + ₹1,328.12 Cr = ₹4,629.96 Cr
* Inputs:
  * Borrowings | [Borrowings (long-term + short-term + current maturities)] | ₹1,814.65 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Balance Sheet | page=264 | origin=reported
  * Lease liabilities (non-current + current) | ₹52.83 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Balance Sheet | page=264 | origin=reported
  * Owners' Equity | ₹3,301.84 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Non-Controlling Interest | ₹1,328.12 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf

### 21. Debt Ratio - 0.23x

* Formula: `Total Debt ÷ Total Assets`
* Expression: `₹1,867.49 Cr ÷ ₹8,012.60 Cr`
  * Numerator: ₹1,867.49 Cr  
  * Denominator: ₹8,012.60 Cr
* Step: Total Debt: ₹1,814.65 Cr + ₹52.83 Cr = ₹1,867.49 Cr
* Inputs:
  * Borrowings | [Borrowings (long-term + short-term + current maturities)] | ₹1,814.65 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Balance Sheet | page=264 | origin=reported
  * Lease liabilities (non-current + current) | ₹52.83 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Balance Sheet | page=264 | origin=reported
  * Total Assets (closing balance, not averaged) | ₹8,012.60 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf

### 22. Interest Coverage Ratio - 2.71x

* Formula: `EBIT ÷ Interest Expense`
* Expression: `₹403.12 Cr ÷ ₹148.71 Cr`
  * Numerator: ₹403.12 Cr  
  * Denominator: ₹148.71 Cr
* Step: EBIT: ₹254.40 Cr + ₹148.71 Cr = ₹403.12 Cr
* Inputs:
  * Profit Before Tax | ₹254.40 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Finance Costs (added back) | ₹148.71 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf

### 23. Financial Leverage Ratio - 1.72x

* Formula: `Average Total Assets ÷ Average Total Equity incl. Non-Controlling Interests`
* Expression: `₹6,640.74 Cr ÷ ₹3,855.81 Cr`
  * Numerator: ₹6,640.74 Cr  
  * Denominator: ₹3,855.81 Cr
* Step: Average Total Assets: (₹5,268.88 Cr + ₹8,012.60 Cr) ÷ 2 = ₹6,640.74 Cr
* Step: FY2025 Total Equity incl. Non-Controlling Interests: ₹2,850.31 Cr + ₹231.34 Cr = ₹3,081.66 Cr
* Step: FY2026 Total Equity incl. Non-Controlling Interests: ₹3,301.84 Cr + ₹1,328.12 Cr = ₹4,629.96 Cr
* Step: Average Total Equity incl. Non-Controlling Interests: (₹3,081.66 Cr + ₹4,629.96 Cr) ÷ 2 = ₹3,855.81 Cr
* Inputs:
  * FY2025 Total Assets | ₹5,268.88 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * FY2026 Total Assets | ₹8,012.60 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Owners' Equity | ₹2,850.31 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Non-Controlling Interest | ₹231.34 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Owners' Equity | ₹3,301.84 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Non-Controlling Interest | ₹1,328.12 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
* Reason: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).
* Warning: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).

### 24. Stock P/E - 75.04x

* Formula: `Market price ÷ Basic EPS attributable to owners`
* Expression: `₹1,132.40 ÷ ₹15.09`
  * Numerator: ₹1,132.40  
  * Denominator: ₹15.09
* Inputs:
  * Market price | ₹1,132.40 | period=Live quote | source=Latest quote (angel) fetched 2026-10-10 09:40 UTC - NOT the fiscal-year-end price; EPS / DPS / book value are the fiscal-year figures | page=not recorded | origin=reported
  * Basic EPS attributable to owners (FY) | ₹15.09 | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf | label=Basic EPS attributable to owners (excluding NCI)

### 25. Price-to-Book (P/B) - 3.90x

* Formula: `Market price ÷ Book Value per Share`
* Expression: `₹1,132.40 ÷ ₹290.02`
  * Numerator: ₹1,132.40  
  * Denominator: ₹290.02
* Step: Book Value per Share: ₹3,301.84 Cr × 1,00,00,000 ÷ 11,38,48,310 = ₹290.02
* Inputs:
  * Market price | ₹1,132.40 | period=Live quote | source=Latest quote (angel) fetched 2026-10-10 09:40 UTC - NOT the fiscal-year-end price; EPS / DPS / book value are the fiscal-year figures | page=not recorded | origin=reported
  * Owners' Equity | ₹3,301.84 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Equity Shares Outstanding | 11,38,48,310 | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf

### 26. Price-to-Sales (P/S) - 5.45x

* Formula: `Market Capitalisation ÷ Revenue from Operations`
* Expression: `₹12,892.18 Cr ÷ ₹2,365.45 Cr`
  * Numerator: ₹12,892.18 Cr  
  * Denominator: ₹2,365.45 Cr
* Step: Market Capitalisation: ₹1,132.40 × 11,38,48,310 ÷ 1,00,00,000 (₹ → ₹ crore) = ₹12,892.18 Cr
* Inputs:
  * Market price | ₹1,132.40 | period=Live quote | source=Latest quote (angel) fetched 2026-10-10 09:40 UTC - NOT the fiscal-year-end price; EPS / DPS / book value are the fiscal-year figures | page=not recorded | origin=reported
  * Equity Shares Outstanding | 11,38,48,310 | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Revenue from Operations | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf

### 27. Dividend Yield % - 0.13%

* Formula: `(Dividend per Share ÷ Market price) × 100`
* Expression: `(₹1.50 ÷ ₹1,132.40) × 100`
  * Numerator: (₹1.50  
  * Denominator: ₹1,132.40) × 100
* Inputs:
  * Dividend per Share (declared for the FY) | ₹1.50 | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Directors' Report / dividend disclosure | page=not recorded | origin=derived/document_text | derivation=dps_declared(text) | label=interim/special + final dividends declared FOR the fiscal year (attributed by the year the sentence states, else by date/label)
  * Market price | ₹1,132.40 | period=Live quote | source=Latest quote (angel) fetched 2026-10-10 09:40 UTC - NOT the fiscal-year-end price; EPS / DPS / book value are the fiscal-year figures | page=not recorded | origin=reported
* Reason: interim=[], special=[], final(recommended)=[1.5]
* Warning: interim=[], special=[], final(recommended)=[1.5]

### 28. Earnings Yield - 1.33%

* Formula: `(Basic EPS attributable to owners ÷ Market price) × 100`
* Expression: `(₹15.09 ÷ ₹1,132.40) × 100`
  * Numerator: (₹15.09  
  * Denominator: ₹1,132.40) × 100
* Inputs:
  * Basic EPS attributable to owners (FY) | ₹15.09 | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf | label=Basic EPS attributable to owners (excluding NCI)
  * Market price | ₹1,132.40 | period=Live quote | source=Latest quote (angel) fetched 2026-10-10 09:40 UTC - NOT the fiscal-year-end price; EPS / DPS / book value are the fiscal-year figures | page=not recorded | origin=reported

### 29. Enterprise Value/EBITDA - 26.48x

* Formula: `Enterprise Value ÷ EBITDA`
* Expression: `₹14,381.60 Cr ÷ ₹543.02 Cr`
  * Numerator: ₹14,381.60 Cr  
  * Denominator: ₹543.02 Cr
* Step: Market Capitalisation: ₹1,132.40 × 11,38,48,310 ÷ 1,00,00,000 (₹ → ₹ crore) = ₹12,892.18 Cr
* Step: Enterprise Value: ₹12,892.18 Cr + ₹1,867.49 Cr − ₹378.07 Cr = ₹14,381.60 Cr
* Step: EBIT: ₹254.40 Cr + ₹148.71 Cr = ₹403.12 Cr
* Step: EBITDA: ₹403.12 Cr + ₹139.90 Cr = ₹543.02 Cr
* Inputs:
  * Market price | ₹1,132.40 | period=Live quote | source=Latest quote (angel) fetched 2026-10-10 09:40 UTC - NOT the fiscal-year-end price; EPS / DPS / book value are the fiscal-year figures | page=not recorded | origin=reported
  * Equity Shares Outstanding | 11,38,48,310 | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Debt | ₹1,867.49 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=derived | derivation=_compute_total_debt
  * Cash and Cash Equivalents | ₹378.07 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Profit Before Tax | ₹254.40 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Finance Costs | ₹148.71 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Depreciation & Amortisation | ₹139.90 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf

### 30. Fixed Asset Turnover - 0.87x

* Formula: `Revenue from Operations ÷ Average Net Fixed Assets`
* Expression: `₹2,365.45 Cr ÷ ₹2,720.63 Cr`
  * Numerator: ₹2,365.45 Cr  
  * Denominator: ₹2,720.63 Cr
* Step: FY2025 Net Fixed Assets: ₹1,930.06 Cr + ₹108.31 Cr + ₹216.16 Cr + ₹22.96 Cr = ₹2,277.49 Cr
* Step: FY2026 Net Fixed Assets: ₹2,873.69 Cr + ₹106.36 Cr + ₹114.43 Cr + ₹69.28 Cr = ₹3,163.77 Cr
* Step: Average Net Fixed Assets: (₹2,277.49 Cr + ₹3,163.77 Cr) ÷ 2 = ₹2,720.63 Cr
* Inputs:
  * Revenue from Operations | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf
  * Property, Plant & Equipment | ₹1,930.06 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Right-of-use Assets | ₹108.31 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Capital Work-in-Progress | ₹216.16 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Intangible Assets | ₹22.96 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Property, Plant & Equipment | ₹2,873.69 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Right-of-use Assets | ₹106.36 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Capital Work-in-Progress | ₹114.43 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Intangible Assets | ₹69.28 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
* Reason: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).
* Warning: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).

### 31. Working Capital Days - 144.8

* Formula: `(Average Working Capital ÷ Revenue from Operations) × 365`
* Expression: `(₹938.41 Cr ÷ ₹2,365.45 Cr) × 365`
  * Numerator: (₹938.41 Cr  
  * Denominator: ₹2,365.45 Cr) × 365
* Step: FY2025 Working Capital: ₹2,572.95 Cr − ₹1,808.20 Cr = ₹764.74 Cr
* Step: FY2026 Working Capital: ₹3,727.51 Cr − ₹2,615.44 Cr = ₹1,112.07 Cr
* Step: Average Working Capital: (₹764.74 Cr + ₹1,112.07 Cr) ÷ 2 = ₹938.41 Cr
* Inputs:
  * Total Current Assets | ₹2,572.95 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Current Liabilities | ₹1,808.20 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Current Assets | ₹3,727.51 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Current Liabilities | ₹2,615.44 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Revenue from Operations | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf
* Reason: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).
* Warning: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).

### 32. Receivables-to-Payables Ratio - 1.01x

* Formula: `Trade Receivables ÷ Trade Payables`
* Expression: `₹959.38 Cr ÷ ₹945.53 Cr`
  * Numerator: ₹959.38 Cr  
  * Denominator: ₹945.53 Cr
* Inputs:
  * Trade Receivables (closing) | ₹959.38 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Trade Payables (closing) | ₹945.53 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf

### 33. Net Debt/EBITDA - 2.74x

* Formula: `Net Debt ÷ EBITDA`
* Expression: `₹1,489.42 Cr ÷ ₹543.02 Cr`
  * Numerator: ₹1,489.42 Cr  
  * Denominator: ₹543.02 Cr
* Step: Total Debt: ₹1,814.65 Cr + ₹52.83 Cr = ₹1,867.49 Cr
* Step: Net Debt: ₹1,867.49 Cr − ₹378.07 Cr = ₹1,489.42 Cr
* Step: EBIT: ₹254.40 Cr + ₹148.71 Cr = ₹403.12 Cr
* Step: EBITDA: ₹403.12 Cr + ₹139.90 Cr = ₹543.02 Cr
* Inputs:
  * Borrowings | [Borrowings (long-term + short-term + current maturities)] | ₹1,814.65 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Balance Sheet | page=264 | origin=reported
  * Lease liabilities (non-current + current) | ₹52.83 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Balance Sheet | page=264 | origin=reported
  * Cash and Cash Equivalents | ₹378.07 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Profit Before Tax | ₹254.40 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Finance Costs | ₹148.71 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Depreciation & Amortisation | ₹139.90 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
* Reason: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).
* Warning: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).

### 34. Debt Service Coverage Ratio (DSCR) - -

* Formula: `Net Operating Income (EBITDA proxy) ÷ (Gross Principal Repayment + Interest Due)`
* Inputs:
  * EBITDA | ₹543.02 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=derived | derivation=ebit+depreciation | label=EBITDA = EBIT + Depreciation, Amortisation & Impairment (Other Income included)
  * Finance Costs | ₹148.71 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
* Reason: Gross principal repayments of borrowings are not disclosed as a separate line (only net financing flows are) - DSCR is not rebuilt from net flows.

### 35. Cash Flow Coverage Ratio - 0.18x

* Formula: `Net Cash Flow from Operating Activities ÷ Total Debt`
* Expression: `₹334.33 Cr ÷ ₹1,867.49 Cr`
  * Numerator: ₹334.33 Cr  
  * Denominator: ₹1,867.49 Cr
* Step: Total Debt: ₹1,814.65 Cr + ₹52.83 Cr = ₹1,867.49 Cr
* Inputs:
  * Net Cash Flow from Operating Activities | ₹334.33 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Cash Flow Statement | page=266 | origin=reported/annual_report_pdf
  * Borrowings | [Borrowings (long-term + short-term + current maturities)] | ₹1,814.65 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Balance Sheet | page=264 | origin=reported
  * Lease liabilities (non-current + current) | ₹52.83 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Balance Sheet | page=264 | origin=reported

### 36. Free Cash Flow - ₹-221 Cr

* Formula: `Operating Cash Flow − Capital Expenditure`
* Expression: `₹334.33 Cr − ₹555.16 Cr`
* Inputs:
  * Operating Cash Flow | ₹334.33 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Cash Flow Statement | page=266 | origin=reported/annual_report_pdf
  * Capital Expenditure | ₹555.16 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=266 | origin=derived | derivation=capex_ppe_purchase+capex_intangible_purchase | label=Gross capital expenditure (cash flow statement, no disposal proceeds netted)
* Reason: No separate 'purchase of intangible assets' line was found in the cash-flow statement; it is treated as nil (the statement lists every cash movement - a combined PPE+intangibles line is already in the PPE figure).
* Warning: No separate 'purchase of intangible assets' line was found in the cash-flow statement; it is treated as nil (the statement lists every cash movement - a combined PPE+intangibles line is already in the PPE figure).

### 37. FCF Yield - -1.71%

* Formula: `(Free Cash Flow ÷ Market Capitalisation) × 100`
* Expression: `(−₹220.83 Cr ÷ ₹12,892.18 Cr) × 100`
  * Numerator: (−₹220.83 Cr  
  * Denominator: ₹12,892.18 Cr) × 100
* Step: Free Cash Flow: ₹334.33 Cr − ₹555.16 Cr = −₹220.83 Cr
* Step: Market Capitalisation: ₹1,132.40 × 11,38,48,310 ÷ 1,00,00,000 (₹ → ₹ crore) = ₹12,892.18 Cr
* Inputs:
  * Operating Cash Flow | ₹334.33 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Cash Flow Statement | page=266 | origin=reported/annual_report_pdf
  * Capital Expenditure | ₹555.16 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=266 | origin=derived | derivation=capex_ppe_purchase+capex_intangible_purchase | label=Gross capital expenditure (cash flow statement, no disposal proceeds netted)
  * Market price | ₹1,132.40 | period=Live quote | source=Latest quote (angel) fetched 2026-10-10 09:40 UTC - NOT the fiscal-year-end price; EPS / DPS / book value are the fiscal-year figures | page=not recorded | origin=reported
  * Equity Shares Outstanding | 11,38,48,310 | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
* Reason: No separate 'purchase of intangible assets' line was found in the cash-flow statement; it is treated as nil (the statement lists every cash movement - a combined PPE+intangibles line is already in the PPE figure).
* Warning: No separate 'purchase of intangible assets' line was found in the cash-flow statement; it is treated as nil (the statement lists every cash movement - a combined PPE+intangibles line is already in the PPE figure).

### 38. FCF Margin - -9.34%

* Formula: `(Free Cash Flow ÷ Revenue from Operations) × 100`
* Expression: `(−₹220.83 Cr ÷ ₹2,365.45 Cr) × 100`
  * Numerator: (−₹220.83 Cr  
  * Denominator: ₹2,365.45 Cr) × 100
* Step: Free Cash Flow: ₹334.33 Cr − ₹555.16 Cr = −₹220.83 Cr
* Inputs:
  * Operating Cash Flow | ₹334.33 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Cash Flow Statement | page=266 | origin=reported/annual_report_pdf
  * Capital Expenditure | ₹555.16 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=266 | origin=derived | derivation=capex_ppe_purchase+capex_intangible_purchase | label=Gross capital expenditure (cash flow statement, no disposal proceeds netted)
  * Revenue from Operations | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf
* Reason: No separate 'purchase of intangible assets' line was found in the cash-flow statement; it is treated as nil (the statement lists every cash movement - a combined PPE+intangibles line is already in the PPE figure).
* Warning: No separate 'purchase of intangible assets' line was found in the cash-flow statement; it is treated as nil (the statement lists every cash movement - a combined PPE+intangibles line is already in the PPE figure).

### 39. Operating Cash Flow Ratio - 0.13x

* Formula: `Net Cash Flow from Operating Activities ÷ Total Current Liabilities`
* Expression: `₹334.33 Cr ÷ ₹2,615.44 Cr`
  * Numerator: ₹334.33 Cr  
  * Denominator: ₹2,615.44 Cr
* Inputs:
  * Net Cash Flow from Operating Activities | ₹334.33 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Cash Flow Statement | page=266 | origin=reported/annual_report_pdf
  * Total Current Liabilities (closing) | ₹2,615.44 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
* Reason: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).
* Warning: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).

### 40. Capex Intensity - 23.47%

* Formula: `(Capital Expenditure ÷ Revenue from Operations) × 100`
* Expression: `(₹555.16 Cr ÷ ₹2,365.45 Cr) × 100`
  * Numerator: (₹555.16 Cr  
  * Denominator: ₹2,365.45 Cr) × 100
* Inputs:
  * Capital Expenditure (gross) | ₹555.16 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=266 | origin=derived | derivation=capex_ppe_purchase+capex_intangible_purchase | label=Gross capital expenditure (cash flow statement, no disposal proceeds netted)
  * Revenue from Operations | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf
* Reason: No separate 'purchase of intangible assets' line was found in the cash-flow statement; it is treated as nil (the statement lists every cash movement - a combined PPE+intangibles line is already in the PPE figure).
* Warning: No separate 'purchase of intangible assets' line was found in the cash-flow statement; it is treated as nil (the statement lists every cash movement - a combined PPE+intangibles line is already in the PPE figure).

### 41. OCF/Net Profit - 1.50x

* Formula: `Net Cash Flow from Operating Activities ÷ Profit for the Year`
* Expression: `₹334.33 Cr ÷ ₹222.20 Cr`
  * Numerator: ₹334.33 Cr  
  * Denominator: ₹222.20 Cr
* Inputs:
  * Net Cash Flow from Operating Activities | ₹334.33 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Cash Flow Statement | page=266 | origin=reported/annual_report_pdf
  * Profit for the Year (whole entity, incl. NCI) | ₹222.20 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf

### 42. Return on Invested Capital (ROIC) - 5.75%

* Formula: `(NOPAT ÷ Invested Capital (closing)) × 100`
* Expression: `(₹352.09 Cr ÷ ₹6,119.38 Cr) × 100`
  * Numerator: (₹352.09 Cr  
  * Denominator: ₹6,119.38 Cr) × 100
* Step: EBIT: ₹254.40 Cr + ₹148.71 Cr = ₹403.12 Cr
* Step: Effective Tax Rate: ₹32.20 Cr ÷ ₹254.40 Cr = 0.1266
* Step: (1 − Effective Tax Rate): 1 − 0.1266 = 0.8734
* Step: NOPAT: ₹403.12 Cr × 0.8734 = ₹352.09 Cr
* Step: Total Debt: ₹1,814.65 Cr + ₹52.83 Cr = ₹1,867.49 Cr
* Step: Total Equity incl. NCI: ₹3,301.84 Cr + ₹1,328.12 Cr = ₹4,629.96 Cr
* Step: Invested Capital (closing): ₹1,867.49 Cr + ₹4,629.96 Cr − ₹378.07 Cr = ₹6,119.38 Cr
* Inputs:
  * Profit Before Tax | ₹254.40 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Finance Costs | ₹148.71 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Total Tax Expense | ₹32.20 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Borrowings | [Borrowings (long-term + short-term + current maturities)] | ₹1,814.65 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Balance Sheet | page=264 | origin=reported
  * Lease liabilities (non-current + current) | ₹52.83 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Balance Sheet | page=264 | origin=reported
  * Owners' Equity | ₹3,301.84 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Non-Controlling Interest | ₹1,328.12 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Cash and Cash Equivalents | ₹378.07 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
* Reason: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).
* Warning: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so flows and balances are not on a comparable footing (Goodwill rose by 540 Cr (7% of total assets); Total assets grew 52% with business-combination disclosures present; Non-controlling interest rose sharply (part-year consolidation of a subsidiary)).

### 43. Tax % - 12.66%

* Formula: `(Total Tax Expense ÷ Profit Before Tax) × 100`
* Expression: `(₹32.20 Cr ÷ ₹254.40 Cr) × 100`
  * Numerator: (₹32.20 Cr  
  * Denominator: ₹254.40 Cr) × 100
* Inputs:
  * Total Tax Expense (Current + Deferred Tax) | ₹32.20 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Profit Before Tax | ₹254.40 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf

### 44. Contribution Margin - 38.06%

* Formula: `(Contribution ÷ Revenue from Operations) × 100`
* Expression: `(₹900.29 Cr ÷ ₹2,365.45 Cr) × 100`
  * Numerator: (₹900.29 Cr  
  * Denominator: ₹2,365.45 Cr) × 100
* Step: Contribution: ₹2,365.45 Cr − ₹1,442.01 Cr − (−₹118.75 Cr) − ₹141.91 Cr = ₹900.29 Cr
* Inputs:
  * Revenue from Operations | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf
  * Cost of materials consumed | ₹1,442.01 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Statement of Profit and Loss (expense note) | page=not recorded | origin=reported
  * Changes in inventories | −₹118.75 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Statement of Profit and Loss (expense note) | page=not recorded | origin=reported
  * Utility charges | ₹141.91 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Notes to the financial statements (other expenses) | page=not recorded | origin=reported
* Reason: PROXY: Ind AS filings do not disclose variable costs; reconstructed from goods cost + Direct Expenses / volume-linked note items. Rent, professional fees, employee cost, depreciation and finance costs are never treated as variable.
* Warning: PROXY: Ind AS filings do not disclose variable costs; reconstructed from goods cost + Direct Expenses / volume-linked note items. Rent, professional fees, employee cost, depreciation and finance costs are never treated as variable.

### 45. EPS Growth Rate - 77.53%

* Formula: `(Basic EPS FY2026 ÷ Basic EPS FY2025 − 1) × 100`
* Expression: `(₹15.09 ÷ ₹8.50 − 1) × 100`
  * Numerator: (₹15.09  
  * Denominator: ₹8.50 − 1) × 100
* Inputs:
  * Basic EPS (current year, owners) | ₹15.09 | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf | label=Basic EPS attributable to owners (excluding NCI)
  * Basic EPS (prior year, owners) | ₹8.50 | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf | label=Basic EPS attributable to owners (excluding NCI)

### 46. Book Value per Share (BVPS) - 290.02

* Formula: `(Total Equity Attributable to Owners of the Company ÷ Equity Shares Outstanding) × 1,00,00,000`
* Expression: `(₹3,301.84 Cr ÷ 11,38,48,310) × 1,00,00,000`
  * Numerator: (₹3,301.84 Cr  
  * Denominator: 11,38,48,310) × 1,00,00,000
* Inputs:
  * Total Equity Attributable to Owners of the Company | [Total Equity Attributable to Owners of the Company (closing)] | ₹3,301.84 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Equity Shares Outstanding (closing) | 11,38,48,310 | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf

### 47. Dividend Payout % - 5.02%

* Formula: `(Dividends paid to the Company's shareholders during the year ÷ Profit for the Year Attributable to Owners of the Company) × 100`
* Expression: `(₹8.54 Cr ÷ ₹170.12 Cr) × 100`
  * Numerator: (₹8.54 Cr  
  * Denominator: ₹170.12 Cr) × 100
* Inputs:
  * Dividends paid to the Company's shareholders during the year | ₹8.54 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Cash Flow Statement | page=299 | origin=reported/annual_report_pdf | label=Dividends paid to the company's own shareholders (reserves / equity-statement note); the cash-flow total (15.20 Cr) = owners 8.54 + minorities 6.66
  * Profit for the Year Attributable to Owners of the Company | ₹170.12 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf

### 48. Retention Ratio - 94.98%

* Formula: `100 − Dividend Payout %`
* Expression: `100 − 5.0188`
* Inputs:
  * PARENT RATIO Dividend Payout % | 5.02% | period=FY2026 | basis=consolidated | source=calculated parent ratio | page=not recorded | origin=verified
  * Dividends paid to the Company's shareholders during the year | ₹8.54 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Cash Flow Statement | page=299 | origin=reported/annual_report_pdf | label=Dividends paid to the company's own shareholders (reserves / equity-statement note); the cash-flow total (15.20 Cr) = owners 8.54 + minorities 6.66
  * Profit for the Year Attributable to Owners of the Company | ₹170.12 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf

### 49. Sustainable Growth Rate - 5.25%

* Formula: `ROE % × Retention Ratio ÷ 100`
* Expression: `5.5305 × 94.9812 ÷ 100`
  * Numerator: 5.5305 × 94.9812  
  * Denominator: 100
* Inputs:
  * PARENT RATIO ROE % | 5.53% | period=FY2026 | basis=consolidated | source=calculated parent ratio | page=not recorded | origin=verified
  * Profit After Tax (owners-attributable) | ₹170.12 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * FY2025 Total Equity | ₹2,850.31 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * FY2026 Total Equity | ₹3,301.84 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * PARENT RATIO Retention Ratio | 94.98% | period=FY2026 | basis=consolidated | source=calculated parent ratio | page=not recorded | origin=verified
  * PARENT RATIO Dividend Payout % | 5.02% | period=FY2026 | basis=consolidated | source=calculated parent ratio | page=not recorded | origin=verified
  * Dividends paid to the Company's shareholders during the year | ₹8.54 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Cash Flow Statement | page=299 | origin=reported/annual_report_pdf | label=Dividends paid to the company's own shareholders (reserves / equity-statement note); the cash-flow total (15.20 Cr) = owners 8.54 + minorities 6.66
  * Profit for the Year Attributable to Owners of the Company | ₹170.12 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf

### 50. PEG Ratio - 0.97x

* Formula: `P/E ÷ EPS Growth Rate`
* Expression: `75.04x ÷ 77.5294%`
  * Numerator: 75.04x  
  * Denominator: 77.5294%
* Step: P/E: ₹1,132.40 ÷ ₹15.09 = 75.04x
* Inputs:
  * Market price | ₹1,132.40 | period=Live quote | source=Latest quote (angel) fetched 2026-10-10 09:40 UTC - NOT the fiscal-year-end price; EPS / DPS / book value are the fiscal-year figures | page=not recorded | origin=reported
  * Basic EPS (owners) | ₹15.09 | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf | label=Basic EPS attributable to owners (excluding NCI)
  * PARENT RATIO EPS Growth Rate | 77.53% | period=FY2026 | basis=consolidated | source=calculated parent ratio | page=not recorded | origin=verified
  * Basic EPS (current year, owners) | ₹15.09 | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf | label=Basic EPS attributable to owners (excluding NCI)
  * Basic EPS (prior year, owners) | ₹8.50 | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf | label=Basic EPS attributable to owners (excluding NCI)

### 51. EV/Sales - 6.08x

* Formula: `Enterprise Value ÷ Revenue from Operations`
* Expression: `₹14,381.60 Cr ÷ ₹2,365.45 Cr`
  * Numerator: ₹14,381.60 Cr  
  * Denominator: ₹2,365.45 Cr
* Step: Market Capitalisation: ₹1,132.40 × 11,38,48,310 ÷ 1,00,00,000 (₹ → ₹ crore) = ₹12,892.18 Cr
* Step: Enterprise Value: ₹12,892.18 Cr + ₹1,867.49 Cr − ₹378.07 Cr = ₹14,381.60 Cr
* Inputs:
  * Market price | ₹1,132.40 | period=Live quote | source=Latest quote (angel) fetched 2026-10-10 09:40 UTC - NOT the fiscal-year-end price; EPS / DPS / book value are the fiscal-year figures | page=not recorded | origin=reported
  * Equity Shares Outstanding | 11,38,48,310 | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Debt | ₹1,867.49 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=derived | derivation=_compute_total_debt
  * Cash and Cash Equivalents | ₹378.07 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Revenue from Operations | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf

### 52. EV/FCF - -65.13x

* Formula: `Enterprise Value ÷ Free Cash Flow`
* Expression: `₹14,381.60 Cr ÷ −₹220.8300 Cr`
  * Numerator: ₹14,381.60 Cr  
  * Denominator: −₹220.8300 Cr
* Step: Market Capitalisation: ₹1,132.40 × 11,38,48,310 ÷ 1,00,00,000 (₹ → ₹ crore) = ₹12,892.18 Cr
* Step: Enterprise Value: ₹12,892.18 Cr + ₹1,867.49 Cr − ₹378.07 Cr = ₹14,381.60 Cr
* Inputs:
  * Market price | ₹1,132.40 | period=Live quote | source=Latest quote (angel) fetched 2026-10-10 09:40 UTC - NOT the fiscal-year-end price; EPS / DPS / book value are the fiscal-year figures | page=not recorded | origin=reported
  * Equity Shares Outstanding | 11,38,48,310 | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Debt | ₹1,867.49 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=derived | derivation=_compute_total_debt
  * Cash and Cash Equivalents | ₹378.07 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * PARENT RATIO Free Cash Flow | −₹220.83 Cr | period=FY2026 | basis=consolidated | source=calculated parent ratio | page=not recorded | origin=verified
  * Operating Cash Flow | ₹334.33 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Cash Flow Statement | page=266 | origin=reported/annual_report_pdf
  * Capital Expenditure | ₹555.16 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=266 | origin=derived | derivation=capex_ppe_purchase+capex_intangible_purchase | label=Gross capital expenditure (cash flow statement, no disposal proceeds netted)
* Reason: Negative Free Cash Flow - EV/FCF is not meaningful.
* Warning: Free Cash Flow is negative: the multiple exists mathematically but is not economically meaningful.

### 53. Price/Cash Flow - 38.56x

* Formula: `Market Capitalisation ÷ Net Cash Flow from Operating Activities`
* Expression: `₹12,892.18 Cr ÷ ₹334.33 Cr`
  * Numerator: ₹12,892.18 Cr  
  * Denominator: ₹334.33 Cr
* Step: Market Capitalisation: ₹1,132.40 × 11,38,48,310 ÷ 1,00,00,000 (₹ → ₹ crore) = ₹12,892.18 Cr
* Inputs:
  * Market price | ₹1,132.40 | period=Live quote | source=Latest quote (angel) fetched 2026-10-10 09:40 UTC - NOT the fiscal-year-end price; EPS / DPS / book value are the fiscal-year figures | page=not recorded | origin=reported
  * Equity Shares Outstanding | 11,38,48,310 | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Net Cash Flow from Operating Activities | ₹334.33 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Cash Flow Statement | page=266 | origin=reported/annual_report_pdf

### 54. Graham Number - 313.8

* Formula: `√(22.5 × Basic EPS × Book Value per Share)`
* Expression: `√(98,469.3481)`
* Step: Book Value per Share: ₹3,301.84 Cr × 1,00,00,000 ÷ 11,38,48,310 = ₹290.02
* Step: 22.5 × EPS: 22.5 × ₹15.09 × ₹290.02 = 98,469.35
* Inputs:
  * Basic EPS (owners) | ₹15.09 | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf | label=Basic EPS attributable to owners (excluding NCI)
  * Owners' Equity | ₹3,301.84 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Equity Shares Outstanding | 11,38,48,310 | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf

### 55. Altman Z-Score - 3.09

* Formula: `1.2×(WC ÷ TA) + 1.4×(RE ÷ TA) + 3.3×(EBIT ÷ TA) + 0.6×(Market Cap ÷ TL) + 1.0×(Sales ÷ TA)`
* Expression: `0.1665 + 0.1740 + 0.1660 + 2.2868 + 0.2952`
* Step: Working Capital: ₹3,727.51 Cr − ₹2,615.44 Cr = ₹1,112.07 Cr
* Step: EBIT: ₹254.40 Cr + ₹148.71 Cr = ₹403.12 Cr
* Step: Market Capitalisation: ₹1,132.40 × 11,38,48,310 ÷ 1,00,00,000 = ₹12,892.18 Cr
* Step: 1.2 × (Working Capital ÷ Total Assets): 1.2 × (₹1,112.07 Cr ÷ ₹8,012.60 Cr) = 0.1665
* Step: 1.4 × (Retained Earnings ÷ Total Assets): 1.4 × (₹995.69 Cr ÷ ₹8,012.60 Cr) = 0.1740
* Step: 3.3 × (EBIT ÷ Total Assets): 3.3 × (₹403.12 Cr ÷ ₹8,012.60 Cr) = 0.1660
* Step: 0.6 × (Market Capitalisation ÷ Total Liabilities): 0.6 × (₹12,892.18 Cr ÷ ₹3,382.64 Cr) = 2.2868
* Step: 1 × (Sales ÷ Total Assets): 1 × (₹2,365.45 Cr ÷ ₹8,012.60 Cr) = 0.2952
* Inputs:
  * Total Current Assets | ₹3,727.51 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Current Liabilities | ₹2,615.44 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Assets | ₹8,012.60 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Retained Earnings (Other-equity note) | ₹995.69 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=298 | origin=reported/annual_report_pdf | label=Retained Earnings (Other-equity note)
  * Profit Before Tax | ₹254.40 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Finance Costs | ₹148.71 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Total Liabilities | ₹3,382.64 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Sales (Net Sales) | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf
  * Market price | ₹1,132.40 | period=Live quote | source=Latest quote (angel) fetched 2026-10-10 09:40 UTC - NOT the fiscal-year-end price; EPS / DPS / book value are the fiscal-year figures | page=not recorded | origin=reported
  * Equity Shares Outstanding | 11,38,48,310 | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf

### 56. Piotroski F-Score - 6

* Formula: `F-Score = number of the 9 tests passed (each 1 point)`
* Expression: `1 + 0 + 1 + 1 + 1 + 1 + 0 + 0 + 1`
* Step: ROA > 0: Piotroski ROA ₹222.20 Cr ÷ ₹8,012.60 Cr = 2.77% > 0 = Pass (1)
* Step: ROA improved YoY: FY2026: ₹222.20 Cr ÷ ₹8,012.60 Cr = 2.77%  >  FY2025: ₹159.97 Cr ÷ ₹5,268.88 Cr = 3.04% = Fail (0)
* Step: Operating Cash Flow > 0: Operating Cash Flow ₹334.33 Cr > 0 = Pass (1)
* Step: OCF > Net Profit (accrual quality): Operating Cash Flow ₹334.33 Cr > Profit After Tax (whole entity) ₹222.20 Cr = Pass (1)
* Step: Total Debt: ₹1,814.65 Cr + ₹52.83 Cr = ₹1,867.49 Cr
* Step: Leverage decreased (Total Debt/TA): FY2026: ₹1,867.49 Cr ÷ ₹8,012.60 Cr = 0.2331  <  FY2025: ₹1,373.38 Cr ÷ ₹5,268.88 Cr = 0.2607 = Pass (1)
* Step: Current Ratio improved YoY: FY2026: ₹3,727.51 Cr ÷ ₹2,615.44 Cr = 1.43x  >  FY2025: ₹2,572.95 Cr ÷ ₹1,808.20 Cr = 1.42x = Pass (1)
* Step: No dilution (shares not increased): FY2026: 11,38,48,310 shares ≤ FY2025: 10,99,31,337 × 1.001 = 11,00,41,268 = Fail (0)
* Step: Gross Profit: ₹2,365.45 Cr − ₹1,323.26 Cr = ₹1,042.20 Cr
* Step: Gross Profit: ₹1,436.97 Cr − ₹604.49 Cr = ₹832.49 Cr
* Step: Gross Margin improved YoY: FY2026: ₹1,042.20 Cr ÷ ₹2,365.45 Cr = 44.06%  >  FY2025: ₹832.49 Cr ÷ ₹1,436.97 Cr = 57.93% = Fail (0)
* Step: Asset Turnover improved YoY: FY2026: ₹2,365.45 Cr ÷ ₹8,012.60 Cr = 0.30x  >  FY2025: ₹1,436.97 Cr ÷ ₹5,268.88 Cr = 0.27x = Pass (1)
* Inputs:
  * Profit After Tax (whole entity) | ₹222.20 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Total Assets | ₹8,012.60 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Profit After Tax (whole entity) | ₹159.97 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Total Assets | ₹5,268.88 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Operating Cash Flow | ₹334.33 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Cash Flow Statement | page=266 | origin=reported/annual_report_pdf
  * Borrowings | [Borrowings (long-term + short-term + current maturities)] | ₹1,814.65 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Balance Sheet | page=264 | origin=reported
  * Lease liabilities (non-current + current) | ₹52.83 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Balance Sheet | page=264 | origin=reported
  * Total Debt | ₹1,373.38 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=derived | derivation=_compute_total_debt
  * Total Current Assets | ₹3,727.51 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Current Liabilities | ₹2,615.44 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Current Assets | ₹2,572.95 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Current Liabilities | ₹1,808.20 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Equity Shares Outstanding | 11,38,48,310 | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Equity Shares Outstanding | 10,99,31,337 | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Revenue from Operations | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Cogs | ₹1,323.26 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=derived | derivation=sum(components)
  * Net Sales | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf
  * Revenue from Operations | ₹1,436.97 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Cogs | ₹604.49 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=derived | derivation=sum(components)
  * Net Sales | ₹1,436.97 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf

### 57. Beneish M-Score - -1.83

* Formula: `M = −4.84 + 0.92·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI + 0.115·DEPI − 0.172·SGAI + 4.679·TATA − 0.327·LVGI`
* Expression: `−4.84 + 0.92 × 0.7943 + 0.528 × 1.3149 + 0.404 × 1.2118 + 0.892 × 1.6461 + 0.115 × 1.0840 − 0.172 × 0.7310 + 4.679 × (−0.0140) − 0.327 × 0.9265`
* Step: Gross Profit: ₹2,365.45 Cr − ₹1,323.26 Cr = ₹1,042.20 Cr
* Step: Gross Profit: ₹1,436.97 Cr − ₹604.49 Cr = ₹832.49 Cr
* Step: Total Debt: ₹1,814.65 Cr + ₹52.83 Cr = ₹1,867.49 Cr
* Step: DSRI: (₹959.38 Cr ÷ ₹2,365.45 Cr) ÷ (₹733.76 Cr ÷ ₹1,436.97 Cr) = 0.7943
* Step: GMI: (₹832.49 Cr ÷ ₹1,436.97 Cr) ÷ (₹1,042.20 Cr ÷ ₹2,365.45 Cr) = 1.3149
* Step: AQI: (1 − (₹3,727.51 Cr + ₹2,873.69 Cr) ÷ ₹8,012.60 Cr) ÷ (1 − (₹2,572.95 Cr + ₹1,930.06 Cr) ÷ ₹5,268.88 Cr) = 1.2118
* Step: SGI: ₹2,365.45 Cr ÷ ₹1,436.97 Cr = 1.6461
* Step: DEPI: (₹102.28 Cr ÷ (₹1,930.06 Cr + ₹102.28 Cr)) ÷ (₹139.90 Cr ÷ (₹2,873.69 Cr + ₹139.90 Cr)) = 1.0840
* Step: SGAI: (₹430.78 Cr ÷ ₹2,365.45 Cr) ÷ (₹358.00 Cr ÷ ₹1,436.97 Cr) = 0.7310
* Step: TATA: (₹222.20 Cr − ₹334.33 Cr) ÷ ₹8,012.60 Cr = −0.0140
* Step: LVGI: ((₹1,867.49 Cr + ₹2,615.44 Cr) ÷ ₹8,012.60 Cr) ÷ ((₹1,373.38 Cr + ₹1,808.20 Cr) ÷ ₹5,268.88 Cr) = 0.9265
* Inputs:
  * Trade Receivables | ₹959.38 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Trade Receivables | ₹733.76 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Net Sales | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf
  * Net Sales | ₹1,436.97 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=reported/annual_report_pdf
  * Revenue from Operations | ₹2,365.45 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Cogs | ₹1,323.26 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=derived | derivation=sum(components)
  * Revenue from Operations | ₹1,436.97 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Cogs | ₹604.49 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | page=265 | origin=derived | derivation=sum(components)
  * Total Current Assets | ₹3,727.51 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Current Assets | ₹2,572.95 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Property, Plant & Equipment | ₹2,873.69 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Property, Plant & Equipment | ₹1,930.06 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Assets | ₹8,012.60 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Assets | ₹5,268.88 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Depreciation & Amortisation | ₹139.90 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Depreciation & Amortisation | ₹102.28 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Other Expenses | ₹430.78 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Other Expenses | ₹358.00 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Total Current Liabilities | ₹2,615.44 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Total Current Liabilities | ₹1,808.20 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=reported/annual_report_pdf
  * Borrowings | [Borrowings (long-term + short-term + current maturities)] | ₹1,814.65 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Balance Sheet | page=264 | origin=reported
  * Lease liabilities (non-current + current) | ₹52.83 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report | statement=Balance Sheet | page=264 | origin=reported
  * Total Debt | ₹1,373.38 Cr | period=FY2025 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Balance Sheet | page=264 | origin=derived | derivation=_compute_total_debt
  * Profit After Tax (whole entity) | ₹222.20 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Statement of Profit and Loss | page=265 | origin=reported/annual_report_pdf
  * Operating Cash Flow | ₹334.33 Cr | period=FY2026 | basis=consolidated | source=Uploaded Annual Report (ANURAS_2026.pdf) | statement=Cash Flow Statement | page=266 | origin=reported/annual_report_pdf
* Reason: SG&A is proxied by Other Expenses (Ind AS has no distinct SG&A line) - SGAI is an approximation.
* Warning: SG&A is proxied by Other Expenses (Ind AS has no distinct SG&A line) - SGAI is an approximation.

### 58. Net Interest Margin (NIM) - -

* Formula: `(Interest Income − Interest Expense) ÷ Average Interest-Earning Assets`
* Reason: Net Interest Margin (NIM) is a banking/NBFC-specific ratio and is not applicable to Chemicals companies.

### 59. CASA Ratio - -

* Formula: `(Current Account + Savings Account Deposits) ÷ Total Deposits`
* Reason: CASA Ratio is a banking/NBFC-specific ratio and is not applicable to Chemicals companies.

### 60. Gross NPA % - -

* Formula: `Gross Non-Performing Assets ÷ Gross Advances`
* Reason: Gross NPA % is a banking/NBFC-specific ratio and is not applicable to Chemicals companies.

### 61. Net NPA % - -

* Formula: `Net Non-Performing Assets ÷ Net Advances`
* Reason: Net NPA % is a banking/NBFC-specific ratio and is not applicable to Chemicals companies.

### 62. Provision Coverage Ratio (PCR) - -

* Formula: `Total Provisions Held ÷ Gross Non-Performing Assets`
* Reason: Provision Coverage Ratio (PCR) is a banking/NBFC-specific ratio and is not applicable to Chemicals companies.

### 63. Capital Adequacy Ratio (CRAR) - -

* Formula: `(Tier I Capital + Tier II Capital) ÷ Risk-Weighted Assets`
* Reason: Capital Adequacy Ratio (CRAR) is a banking/NBFC-specific ratio and is not applicable to Chemicals companies.

### 64. Credit-to-Deposit Ratio - -

* Formula: `Total Advances ÷ Total Deposits`
* Reason: Credit-to-Deposit Ratio is a banking/NBFC-specific ratio and is not applicable to Chemicals companies.

### 65. Cost-to-Income Ratio - -

* Formula: `Operating Expenses ÷ (Net Interest Income + Other Income)`
* Reason: Cost-to-Income Ratio is a banking/NBFC-specific ratio and is not applicable to Chemicals companies.

### 66. Beta - 0.8

* Formula: `Covariance(Stock Returns, Nifty 50 Returns) ÷ Variance(Nifty 50 Returns)`
* Expression: `0.000262 ÷ 0.000328`
  * Numerator: 0.000262  
  * Denominator: 0.000328
* Inputs:
  * Covariance(Stock Returns, Nifty 50 Returns) | 0.000262 | period=None | source=Yahoo Finance weekly prices | page=not recorded | origin=reported
  * Variance(Nifty 50 Returns) | 0.000328 | period=None | source=Yahoo Finance weekly prices (^NSEI) | page=not recorded | origin=reported

### 67. Promoter Pledge % - 21.79%

* Formula: `(Pledged Promoter Shares ÷ Total Promoter Shareholding) × 100`
* Expression: `(1,46,55,780 ÷ 6,72,53,016) × 100`
  * Numerator: (1,46,55,780  
  * Denominator: 6,72,53,016) × 100
* Inputs:
  * Pledged Promoter Shares | 1,46,55,780 | period=None | source=Shareholding Pattern (uploaded filing) | page=not recorded | origin=reported
  * Total Promoter Shareholding (shares) | 6,72,53,016 | period=None | source=Shareholding Pattern (uploaded filing) | page=not recorded | origin=reported

### 68. Free Float % - 40.93%

* Formula: `Total shares − Promoter & promoter-group holding − Locked-in shares`
* Expression: `100.00% − 59.07% − 0.00%`
* Inputs:
  * Total shares (100%) | 100.00% | period=None | source=Shareholding Pattern | page=not recorded | origin=reported
  * Promoter & promoter-group holding | 59.07% | period=None | source=Shareholding Pattern | page=not recorded | origin=reported
  * Locked-in shares | 0.00% | period=None | source=Shareholding Pattern | page=not recorded | origin=reported

## 4. Missing, unavailable, not-applicable and withheld metrics

| Sr | Metric | Availability | API status | Reason exposed by the API |
|---|---|---|---|---|
| 34 | Debt Service Coverage Ratio (DSCR) | unavailable (insufficient data) | insufficient_data | Gross principal repayments of borrowings are not disclosed as a separate line (only net financing flows are) - DSCR is not rebuilt from net flows. |
| 58 | Net Interest Margin (NIM) | not applicable | not_applicable | Net Interest Margin (NIM) is a banking/NBFC-specific ratio and is not applicable to Chemicals companies. |
| 59 | CASA Ratio | not applicable | not_applicable | CASA Ratio is a banking/NBFC-specific ratio and is not applicable to Chemicals companies. |
| 60 | Gross NPA % | not applicable | not_applicable | Gross NPA % is a banking/NBFC-specific ratio and is not applicable to Chemicals companies. |
| 61 | Net NPA % | not applicable | not_applicable | Net NPA % is a banking/NBFC-specific ratio and is not applicable to Chemicals companies. |
| 62 | Provision Coverage Ratio (PCR) | not applicable | not_applicable | Provision Coverage Ratio (PCR) is a banking/NBFC-specific ratio and is not applicable to Chemicals companies. |
| 63 | Capital Adequacy Ratio (CRAR) | not applicable | not_applicable | Capital Adequacy Ratio (CRAR) is a banking/NBFC-specific ratio and is not applicable to Chemicals companies. |
| 64 | Credit-to-Deposit Ratio | not applicable | not_applicable | Credit-to-Deposit Ratio is a banking/NBFC-specific ratio and is not applicable to Chemicals companies. |
| 65 | Cost-to-Income Ratio | not applicable | not_applicable | Cost-to-Income Ratio is a banking/NBFC-specific ratio and is not applicable to Chemicals companies. |

## 5. Data-quality warnings and reporting-basis issues

* **Acquisition distortion:** the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution (goodwill +540 Cr, total assets +52%, NCI up sharply; acquisition 27-Feb-2026); flow-over-balance ratios are `needs_review`.
* **Revenue is a proxy for credit sales** in Receivables Turnover / Debtor Days / Receivables-to-Payables (net credit sales are not disclosed).
* **Perimeter by definition:** Net Profit Margin and ROA use owners' profit (170.12 Cr) - the whole-entity profit is 222.20 Cr (external 9.32% margin / 5.76% ROE use it); ROE uses owners' profit over owners' equity; Debt/Equity and ROIC use equity incl. NCI; the Piotroski score uses whole-entity profit throughout (its ROA is not the displayed ROA).
* **Altman Z-Score:** original (1968, public manufacturing) variant, suitable for a chemicals manufacturer; Retained Earnings is the exact Retained Earnings line of the Other-equity note (995.69 Cr) when the note reconciles - not total Other Equity (3,187.99 Cr); other filings fall back to the flagged Other-Equity proxy.
* **Market ratios are current-price valuations on annual results:** the quote is the latest price, not the fiscal-year-end price; EPS, DPS, book value, EBITDA and cash flow are FY2025-26.
* **Enterprise value** = market cap + total debt - cash & cash equivalents everywhere (EV/EBITDA, EV/Sales, EV/FCF); non-controlling interest is not added and the formula text says so.
* **Dividend payout** = dividends PAID to owners in the year / owners' profit; the declared-for-the-year basis (DPS 1.5 -> ~10%, Screener's 10%) is a different measure.
* **Cash ratio** includes unrestricted other bank balances; restricted / lien balances are excluded and balances of unstated nature are included but unconfirmed.
* **Free cash flow is negative:** FCF-based multiples are flagged not meaningful rather than shown as ordinary multiples (EV/FCF still prints its number; its status is `not_meaningful`).
* **Banking-specific metrics** are Not Applicable to a chemicals company and show '-'.
* **Shareholding rows and Beta** carry no fiscal-year label (filing / price-series based).

Metrics flagged `needs_review` (value shown, but the engine marks it as proxy / estimated / acquisition-affected / policy-dependent):

* 1 Inventory Turnover: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so f
* 2 Inventory Days: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so f
* 3 Receivables Turnover: Net credit sales are not disclosed; Revenue from Operations is used as the proxy.; Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so f
* 4 Debtor Days: Net credit sales are not disclosed; Revenue from Operations is used as the proxy.; Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so f
* 5 Payables Turnover: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so f
* 6 Days Payable: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so f
* 7 Asset Turnover: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so f
* 8 Working Capital Turnover: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so f
* 9 Cash Conversion Cycle: Net credit sales are not disclosed; Revenue from Operations is used as the proxy.; Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so f
* 12 Cash Ratio: Restricted / lien-marked balances of 7.30 Cr were excluded from the numerator.; 7.61 Cr of other bank balances sits on a line whose nature the note does not state (e.g. 'Deposit account'); no restriction is disclosed so it is incl
* 17 Return on Assets (ROA): Perimeter: owners' profit over whole-entity assets (assets include NCI-funded assets).; Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so f
* 19 ROCE %: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so f
* 23 Financial Leverage Ratio: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so f
* 30 Fixed Asset Turnover: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so f
* 31 Working Capital Days: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so f
* 33 Net Debt/EBITDA: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so f
* 39 Operating Cash Flow Ratio: Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so f
* 42 Return on Invested Capital (ROIC): Acquisition-affected: the year-end balance sheet consolidates an acquired business in full while the P&L carries only its part-year contribution, so f
* 44 Contribution Margin: PROXY: Ind AS filings do not disclose variable costs; reconstructed from goods cost + Direct Expenses / volume-linked note items. Rent, professional f
* 57 Beneish M-Score: SG&A is proxied by Other Expenses (Ind AS has no distinct SG&A line) - SGAI is an approximation.

## 6. Source / API used and verification method

* Authentication: the configured flow - POST /api/auth/login with the site password from the local `.env` (never printed or stored), then the bearer token on GET /api/v1/document-analysis/<symbol> over HTTP to localhost:8000. No auth bypass or dependency override was used for the captured data.
* **The values were NOT read from the logged-in browser UI.** The displayed strings re-implement the tab's `fmtRatioValue`, and the section grouping runs the repository's own `groupFundamentalRatios` (node) on the response.
* Freshness: before the capture the symbol's wrapper caches were cleared and the engine run once, so every row has the same formula version, one quote and calculation times within seconds. The application stores those rows in its own table (normal behaviour of an analysis run).
* Re-run: `python tests/quant_snapshot.py --symbol ANURAS --capture` then `--api-json <file>`.

## 7. External benchmark comparison

References were read on 2026-10-10 from the sites below; a difference is classified, never silently counted as a Navrist error. Only the metrics in this table were compared externally - the other metrics were verified against the annual report and by independent recomputation (docs/ratio_audit_matrix_2026-10.md).

Sources: https://www.screener.in/company/ANURAS/consolidated/ ; https://stockanalysis.com/quote/nse/ANURAS/financials/ratios/ ; Value Research figures were supplied earlier by the product owner (inventory 248.91 / debtor 130.63 / payable 209.90 / CCC 169.65, reproduced in tests/test_anuras_reference_conventions.py).

| Metric | Navrist (displayed) | Reference platform | Reference value | Reference definition | Classification |
|---|---|---|---|---|---|
| Debtor Days | 130.63 | Screener consolidated (annual Mar-2026 column) | 148 | closing receivables / sales x 365 | Different documented methodology (closing vs average balance) |
| Inventory Days | 444.96 | Screener consolidated | 490 | closing inventory / COGS x 365 | Different documented methodology (closing vs average balance) |
| Days Payable | 187.91 | Screener consolidated | 261 | closing payables / COGS x 365 | Different documented methodology (closing balance; COGS vs disclosed purchases) |
| Cash Conversion Cycle | 387.68 | Screener consolidated | 377 | debtor + inventory - payable days (closing) | Different documented methodology (follows its components) |
| Working Capital Days | 144.8 | Screener consolidated | 108 | Screener's own definition (not reproducible from the statements) | Insufficient evidence for the reference formula; Navrist = average working capital / revenue x 365 |
| Dividend Payout % | 5.02% | Screener consolidated | 10% | dividend declared for the year / profit | Different documented methodology (Navrist: dividends PAID to owners / owners' profit) |
| Tax % | 12.66% | Screener consolidated | 13% | Screener tax row (whole percent) | Matches (12.66% rounds to 13%) |
| ROE % | 5.53% | Screener key-metrics box | 5.55% | period not labelled by the site | Different reporting basis / unlabelled period |
| ROE % | 5.53% | Stock Analysis FY2026 | 5.76% | whole-entity profit 222.20 / average equity incl. NCI 3,855.81 (reproduced) | Different documented methodology (profit perimeter: owners' vs whole entity) |
| Return on Assets (ROA) | 2.56% | Stock Analysis FY2026 | 3.66% | formula not published; not reproducible from the statements | Insufficient evidence for the reference formula |
| Return on Invested Capital (ROIC) | 5.75% | Stock Analysis FY2026 | 6.45% | formula not published (average invested capital gives 6.73% on Navrist's NOPAT) | Different documented methodology / insufficient evidence |
| ROCE % | 9.10% | Screener (last value) / Stock Analysis FY2026 | 7% / 7.20% | formula not published; EBIT here includes other income and uses average (assets - current liabilities) | Insufficient evidence for the reference formula |
| Debt-to-Equity Ratio | 0.40x | Stock Analysis FY2026 | 0.42 | formula not published (borrowings / owners' equity = 0.55; Navrist debt incl. leases / equity incl. NCI = 0.40) | Different documented methodology |
| Current Ratio | 1.43x | Stock Analysis FY2026 | 1.43 | current assets / current liabilities | Matches |
| Stock P/E | 75.04x | Screener key metrics | 73.8 | Screener's own price at its own time | Stale or different market price (Navrist uses the quote shown in the snapshot over FY EPS 15.09) |
| Price-to-Book (P/B) | 3.90x | Screener text | 3.90x | price 1,132 / book value 290 | Matches |
| Stock P/E | 75.04x | Stock Analysis | 82.37 | page price dated 2026-10-09; earnings basis not stated | Stale or different market price / different earnings basis |
| Price-to-Book (P/B) | 3.90x | Stock Analysis | 3.03 | book-value basis not stated | Insufficient evidence for the reference formula |
| Enterprise Value/EBITDA | 26.48x | Stock Analysis | 28.92 | EV and EBITDA definitions not published | Insufficient evidence for the reference formula |
| Net Profit Margin | 7.19% | external 9.32% (whole-entity 222.20 / 2,365.45) | 9.32% | whole-entity profit | Different documented methodology (Navrist: owners' profit; reference reproduced with 222.199 / 2,365.455) |

## 8. Final checks

* Metrics captured: **68** (59 with a value, 9 without; none replaced by zero).
* Duplicates: 0 duplicate ratio keys, 0 duplicate labels.
* One snapshot: 1 formula version(s), 1 quote time(s), calculation spread 6 s, snapshot id cf96428d9e46 on every CSV row.
