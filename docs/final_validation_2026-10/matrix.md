# Final 68-ratio validation matrix (2026-10)

Source: `tests/final_validation.py` over 17 real filings (`final_validation.json`) and `tests/universe_scan.py` over 133 real filings.
Status counts per ratio across the 17 companies: V verified, R needs_review, M not_meaningful, NA not_applicable, ND not_disclosed, ID insufficient_data.
`Y*` = correct on every validated company; platform-wide extraction caveat applies (see universe scan below).

| # | Ratio | Formula correct | Extraction correct | Basis correct | Status correct | External validation | Global status | Status counts (17 cos) |
|---|---|---|---|---|---|---|---|---|
| 1 | Inventory Turnover | Y | Y* | Y | Y | M/D | **COMPLETE** | V=8 R=1 NA=6 ND=2 |
| 2 | Days Inventory Outstanding (DOH) | Y | Y* | Y | Y | M/D | **COMPLETE** | V=8 R=1 NA=6 ND=2 |
| 3 | Receivables Turnover | Y (revenue proxy) | Y* | Y | Y | D | **NEEDS_REVIEW** | R=11 NA=6 |
| 4 | Days Sales Outstanding (DSO) | Y (revenue proxy) | Y* | Y | Y | D | **NEEDS_REVIEW** | R=11 NA=6 |
| 5 | Payables Turnover | Y (purchases proxy flagged) | Y* | Y | Y | D | **COMPLETE** | V=3 R=5 NA=6 ND=3 |
| 6 | Days Payables Outstanding (DPO) | Y (purchases proxy flagged) | Y* | Y | Y | D | **COMPLETE** | V=3 R=5 NA=6 ND=3 |
| 7 | Asset Turnover | Y | Y* | Y | Y | M/D | **COMPLETE** | V=10 R=1 NA=6 |
| 8 | Working Capital Turnover | Y | Y* | Y | Y | M/D | **COMPLETE** | V=7 R=1 M=3 NA=6 |
| 9 | Cash Conversion Cycle | Y | Y* | Y | Y | D | **NEEDS_REVIEW** | R=8 NA=6 ND=3 |
| 10 | Current Ratio | Y | Y* | Y | Y | M | **COMPLETE** | V=11 NA=6 |
| 11 | Quick Ratio | Y | Y* | Y | Y | M | **COMPLETE** | V=11 NA=6 |
| 12 | Cash Ratio | Y | Y* | Y | Y | M | **COMPLETE** | V=8 R=3 NA=6 |
| 13 | Working Capital | Y | Y* | Y | Y | M | **COMPLETE** | V=11 NA=6 |
| 14 | Gross Profit Margin | Y | Y* | Y | Y | M | **COMPLETE** | V=9 NA=6 ND=2 |
| 15 | Operating Profit Margin (EBIT Basis) | Y | Y* | Y | Y | M | **COMPLETE** | V=10 R=1 NA=6 |
| 16 | Net Profit Margin | Y (owners' policy) | Y* | Y | Y | M/D | **COMPLETE** | V=7 R=4 NA=6 |
| 17 | Return on Assets (ROA) | Y (owners' policy) | Y* | Y | Y | M/D | **COMPLETE** | V=12 R=5 |
| 18 | Return on Equity (ROE) | Y | Y* | Y | Y (banks: N/A policy) | M | **NEEDS_REVIEW** | V=7 R=3 M=1 NA=6 |
| 19 | Return on Capital Employed (ROCE) | Y | Y* | Y | Y | M/D | **COMPLETE** | V=9 R=2 NA=6 |
| 20 | Debt-to-Equity Ratio | Y | Y* | Y | Y | M/D | **COMPLETE** | V=7 R=3 M=1 NA=6 |
| 21 | Debt Ratio | Y | Y* | Y | Y | M/D | **COMPLETE** | V=8 R=3 NA=6 |
| 22 | Interest Coverage Ratio | Y | Y* | Y | Y | M/D | **COMPLETE** | V=10 R=1 NA=6 |
| 23 | Financial Leverage Ratio | Y | Y* | Y | Y | M/D | **COMPLETE** | V=9 R=1 M=1 NA=6 |
| 24 | Price-to-Earnings (P/E) | Y | Y* | Y | Y | M/D | **COMPLETE** | V=13 R=3 M=1 |
| 25 | Price-to-Book (P/B) | Y | Y* | Y | Y | M/D | **COMPLETE** | V=14 R=1 M=1 ND=1 |
| 26 | Price-to-Sales (P/S) | Y | Y* | Y | Y | M/D | **COMPLETE** | V=7 R=3 NA=6 ND=1 |
| 27 | Dividend Yield | Y | Y* (DPS text scan: 4 of 17 not found) | Y | Y | M | **NEEDS_REVIEW** | V=14 ND=3 |
| 28 | Earnings Yield | Y | Y* | Y | Y | M/D | **COMPLETE** | V=14 R=3 |
| 29 | Enterprise Value/EBITDA | Y (EV policy H, changed) | Y* | Y | Y | - | **COMPLETE** | V=4 R=6 NA=6 ND=1 |
| 30 | Fixed Asset Turnover | Y | Y* | Y | Y | M/D | **COMPLETE** | V=10 R=1 NA=6 |
| 31 | Days Working Capital | Y | Y* | Y | Y | M/D | **COMPLETE** | V=10 R=1 NA=6 |
| 32 | Receivables-to-Payables Ratio | Y | Y* | Y | Y | M/D | **COMPLETE** | V=10 NA=6 ND=1 |
| 33 | Net Debt/EBITDA | Y | Y* | Y | Y | M/D | **COMPLETE** | V=5 R=2 NA=10 |
| 34 | Debt Service Coverage Ratio (DSCR) | Y | N (gross repayment rarely disclosed) | Y | Y | - | **INSUFFICIENT_DATA** | R=8 NA=6 ID=3 |
| 35 | Cash Flow Coverage Ratio | Y | Y* | Y | Y | M/D | **COMPLETE** | V=8 R=3 NA=6 |
| 36 | Free Cash Flow (FCF) | Y | Y* | Y | Y | M/D | **COMPLETE** | V=11 NA=6 |
| 37 | FCF Yield | Y | Y* | Y | Y | M/D | **COMPLETE** | V=7 R=3 NA=6 ND=1 |
| 38 | FCF Margin | Y | Y* | Y | Y | M/D | **COMPLETE** | V=11 NA=6 |
| 39 | Operating Cash Flow Ratio | Y | Y* | Y | Y | M/D | **COMPLETE** | V=10 R=1 NA=6 |
| 40 | Capex Intensity | Y | Y* | Y | Y | M/D | **COMPLETE** | V=11 NA=6 |
| 41 | OCF/Net Profit | Y | Y* | Y | Y | M/D | **COMPLETE** | V=8 R=2 NA=6 ND=1 |
| 42 | Return on Invested Capital (ROIC) | Y | Y* | Y | Y | M/D | **COMPLETE** | V=6 R=4 NA=6 ND=1 |
| 43 | Effective Tax Rate | Y | Y* | Y | Y | M/D | **COMPLETE** | V=10 NA=6 ND=1 |
| 44 | Contribution Margin | Y (proxy) | partial | Y | Y (never verified) | - | **NEEDS_REVIEW** | R=4 NA=6 ND=7 |
| 45 | EPS Growth Rate | Y | Y* | Y | Y | M/D | **COMPLETE** | V=14 R=3 |
| 46 | Book Value per Share (BVPS) | Y | Y* | Y | Y | M/D | **COMPLETE** | V=13 R=3 ND=1 |
| 47 | Dividend Payout Ratio | Y (paid / NCI caveat) | Y* | Y | Y | D | **NEEDS_REVIEW** | V=3 R=11 ND=3 |
| 48 | Retention Ratio | Y (paid / NCI caveat) | Y* | Y | Y | D | **NEEDS_REVIEW** | V=3 R=11 ND=3 |
| 49 | Sustainable Growth Rate | Y (paid / NCI caveat) | Y* | Y | Y | D | **NEEDS_REVIEW** | V=3 R=7 NA=6 ID=1 |
| 50 | PEG Ratio | Y | Y* | Y | Y | M/D | **COMPLETE** | V=10 R=3 M=4 |
| 51 | EV/Sales | Y (EV policy H, changed) | Y* | Y | Y | - | **COMPLETE** | V=4 R=6 NA=6 ND=1 |
| 52 | EV/FCF | Y (EV policy H, changed) | Y* | Y | Y | - | **COMPLETE** | V=4 R=5 M=1 NA=6 ND=1 |
| 53 | Price/Cash Flow | Y | Y* | Y | Y | M/D | **COMPLETE** | V=7 R=3 NA=6 ND=1 |
| 54 | Graham Number | Y | Y* | Y | Y | M/D | **COMPLETE** | V=12 R=2 M=2 ND=1 |
| 55 | Altman Z-Score | Y (RE proxy) | Y* | Y | Y | - | **NEEDS_REVIEW** | R=9 NA=6 ND=2 |
| 56 | Piotroski F-Score | Y | partial (needs 2 yrs of every input) | Y | Y | - | **NEEDS_REVIEW** | V=2 R=2 NA=6 ND=7 |
| 57 | Beneish M-Score | Y | partial (needs 2 yrs of every input) | Y | Y | - | **NEEDS_REVIEW** | R=8 NA=6 ND=3 |
| 58 | Net Interest Margin (NIM) | Y | Y (4 banks, identities proven) | Y (standalone) | Y | M (HDFC/ICICI/Kotak/SBI disclosed values) | **COMPLETE** | V=6 NA=11 |
| 59 | CASA Ratio | Y | Y (4 banks, identities proven) | Y (standalone) | Y | M (HDFC/ICICI/Kotak/SBI disclosed values) | **COMPLETE** | V=4 NA=13 |
| 60 | Gross NPA % | Y (disclosed figure) | Y banks; NBFC partial | Y | Y | M (banks) | **NEEDS_REVIEW** | V=4 NA=11 ND=2 |
| 61 | Net NPA % | Y (disclosed figure) | Y banks; NBFC partial | Y | Y | M (banks) | **NEEDS_REVIEW** | V=5 NA=11 ND=1 |
| 62 | Provision Coverage Ratio (PCR) | Y (disclosed figure) | Y banks; NBFC partial | Y | Y | M (banks) | **NEEDS_REVIEW** | V=4 NA=11 ND=2 |
| 63 | Capital Adequacy Ratio (CRAR) | Y (disclosed figure) | Y banks; NBFC partial | Y | Y | M (banks) | **NEEDS_REVIEW** | V=5 NA=11 ND=1 |
| 64 | Credit-to-Deposit Ratio | Y | Y (4 banks, identities proven) | Y (standalone) | Y | M (HDFC/ICICI/Kotak/SBI disclosed values) | **COMPLETE** | V=4 NA=13 |
| 65 | Cost-to-Income Ratio | Y | Y (4 banks, identities proven) | Y (standalone) | Y | M (HDFC/ICICI/Kotak/SBI disclosed values) | **COMPLETE** | V=6 NA=11 |
| 66 | Beta | Y | Y (auto mode); manual mode has no price history | Y | Y | - (Screener shows none) | **NEEDS_REVIEW** | V=3 ID=14 |
| 67 | Promoter Pledge % | Y | unverifiable at primary source | Y | Y (needs_review) | - (cannot verify) | **NEEDS_REVIEW** | R=1 ND=16 |
| 68 | Free Float % | Y (proxy) | Y | Y | Y (needs_review) | M (promoter %) | **NEEDS_REVIEW** | R=1 ND=16 |

## Universe scan (133 real filings, latest year each)

- filings: 133; unreadable by the automatic extractor: 20; failing at least one accounting identity: 39 (29%)
- violation kinds: {'nci_bounds': 5, 'bs_identity': 14, 'eps_pat': 19, 'pat_vs_total': 4, 'debt_bounds': 5}
- violations NOT flagged by the status layer: 0

### Filings failing an identity (extraction-defect candidates; every one is flagged needs_review, none is 'verified')

- AARTIIND:2026 - nci_bounds: NCI -2 vs total equity 5,953
- AEGISLOG:2026 - bs_identity: TL 5,706 + equity 9,530 != TA 14,491
- AFSL:2025 - eps_pat: owners PAT 0 vs EPS x shares 108
- AZAD:2025 - nci_bounds: NCI -1 vs total equity 1,509
- BALKRISIND:2026 - eps_pat: owners PAT 778 vs EPS x shares 1,243
- CAMLINFINE:2026 - eps_pat: owners PAT 24 vs EPS x shares -31; bs_identity: TL 1,323 + equity 2,943 != TA 2,324
- DIAMINESQ:2026 - bs_identity: TL 17 + equity 1,153 != TA 174
- DLINKINDIA:2026 - bs_identity: TL 306 + equity 1,209 != TA 811
- ELECTHERM:2025 - eps_pat: owners PAT 442 vs EPS x shares 322; nci_bounds: NCI 0 vs total equity -159
- ETERNAL:2026 - nci_bounds: NCI -7 vs total equity 30,973
- GANGESSECU:2026 - eps_pat: owners PAT 3 vs EPS x shares 8; bs_identity: TL 41 + equity 1,530 != TA 581
- GCSL:2026 - eps_pat: owners PAT 23 vs EPS x shares 12
- GOKUL:2025 - bs_identity: TL 423 + equity 2,305 != TA 768
- GREENPLY:2026 - bs_identity: TL 1,066 + equity 2,131 != TA 1,962; pat_vs_total: owners 91 > whole-entity 90
- GRMOVER:2025 - debt_bounds: debt 36,259 vs assets 911
- GTL:2025 - debt_bounds: debt 5,639 vs assets 105
- HFCL:2025 - eps_pat: owners PAT 173 vs EPS x shares 0
- HINDUNILVR:2026 - eps_pat: owners PAT 15,040 vs EPS x shares 10,632; pat_vs_total: owners 15,040 > whole-entity 10,652
- INA:2025 - eps_pat: owners PAT 12,619 vs EPS x shares 2,778,488; debt_bounds: debt 10,809 vs assets 4
- JKTYRE:2026 - eps_pat: owners PAT 606 vs EPS x shares 785
- JUBLFOOD:2026 - eps_pat: owners PAT 428 vs EPS x shares 375
- KREBSBIO:2025 - debt_bounds: debt 21,221 vs assets 16,904
- KRONOX:2025 - eps_pat: owners PAT 2,547 vs EPS x shares 26
- KSL:2026 - bs_identity: TL 891 + equity 2,306 != TA 2,996
- LOTUSDEV:2025 - bs_identity: TL 285 + equity 1,089 != TA 1,219
- MWL:2026 - bs_identity: TL 623 + equity 3,240 != TA 929
- NAZARA:2025 - eps_pat: owners PAT 63 vs EPS x shares 72; pat_vs_total: owners 63 > whole-entity 51
- NITINSPIN:2025 - eps_pat: owners PAT 17,543 vs EPS x shares 175
- NLCINDIA:2025 - eps_pat: owners PAT 2,621 vs EPS x shares 4,128
- PRABHA:2026 - eps_pat: owners PAT 0 vs EPS x shares 1
- PRAJIND:2026 - bs_identity: TL 1,747 + equity 1,640 != TA 3,056
- RAJRATAN:2026 - bs_identity: TL 509 + equity 1,655 != TA 1,159
- SANOFICONR:2025 - eps_pat: owners PAT 240 vs EPS x shares 21
- SHYAMMETL:2026 - nci_bounds: NCI -4 vs total equity 11,519; pat_vs_total: owners 1,070 > whole-entity 1,060
- TPINDIA:2025 - debt_bounds: debt 16 vs assets 9
- TRITURBINE:2026 - bs_identity: TL 1,051 + equity 1,732 != TA 2,497
- TVTODAY:2026 - eps_pat: owners PAT 14 vs EPS x shares 20
- XELPMOC:2025 - eps_pat: owners PAT -9 vs EPS x shares -0
- ZEEL:2025 - bs_identity: TL 2,201 + equity 12,398 != TA 13,734

### Unreadable in automatic mode

- AADHARHFC:2026 - Consolidated Balance Sheet not found in the Annual Report.
- ANURAS:2026 - Consolidated Statement of Profit and Loss not found in the Annual Report.
- APEX:2025 - Consolidated Statement of Profit and Loss not found in the Annual Report.
- DALMIASUG:2025 - Consolidated Statement of Profit and Loss not found in the Annual Report.
- DIVGIITTS:2025 - Consolidated Statement of Profit and Loss not found in the Annual Report.
- GANESHCP:2025 - Consolidated Statement of Profit and Loss not found in the Annual Report.
- IDFCFIRSTB:2026 - Consolidated Statement of Profit and Loss not found in the Annual Report.
- IRMENERGY:2025 - Consolidated Statement of Profit and Loss not found in the Annual Report.
- OFSS:2026 - Consolidated Balance Sheet not found in the Annual Report.
- ORCHASP:2025 - Consolidated Statement of Profit and Loss not found in the Annual Report.
- PNGSREVA:2026 - Consolidated Statement of Profit and Loss not found in the Annual Report.
- REFEX:2026 - Consolidated Statement of Profit and Loss not found in the Annual Report.
- RELCHEMQ:2025 - Consolidated Statement of Profit and Loss not found in the Annual Report.
- RMDRIP:2025 - Consolidated Statement of Profit and Loss not found in the Annual Report.
- SATIA:2025 - Consolidated Statement of Profit and Loss not found in the Annual Report.
- SGL:2025 - Consolidated Statement of Profit and Loss not found in the Annual Report.
- SMARTWORKS:2025 - Consolidated Balance Sheet not found in the Annual Report.
- SUPREME:2025 - Consolidated Statement of Profit and Loss not found in the Annual Report.
- SUZLON:2026 - Consolidated Statement of Profit and Loss not found in the Annual Report.
- ZENITHSTL:2025 - Consolidated Statement of Profit and Loss not found in the Annual Report.
