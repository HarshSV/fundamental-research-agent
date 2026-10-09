# Anupam Rasayan India (ANURAS) FY2025-26 - ratio audit against the filing and external references

Basis: **consolidated**, year ended 31-Mar-2026, formula version 2026.10.14. Figures are INR crore (the report prints INR million; x0.1).
Source: Integrated Report 2025-26 (consolidated Balance Sheet p.301 / P&L p.302 / Cash Flow p.303; standalone p.227-229).
Regression coverage: `tests/test_anuras_fy2026_source_audit.py` (printed figures -> contract arithmetic; Screener reproduced from the same inputs;
extraction facts == printed figures).

## 1. The 27 displayed values were reproduced
All 27 ratios shown in the UI were reproduced exactly (the UI run used the live Angel quote **INR 1,132.40**; previous close 1,097.70) through the
real 68-ratio orchestrator. Inputs, page references and normalised facts are in `docs/ratio_audit_matrix_2026-10.md` (per-ratio breakdown) and were
independently re-derived there (0 mismatches, every base fact found printed in the report).

## 2. What the inputs are (checked against the filing)
| Fact | Value | Printed in the report |
|---|---|---|
| Revenue | 2,365.455 (FY25 1,436.974) | P&L: 23,654.55 / 14,369.74 million |
| COGS | 1,323.256 (FY25 604.488) | Cost of materials 14,420.07 + change in inventories (1,187.51) = 13,232.56 million (Note 27(c)) |
| Purchases | 1,478.115 | Note 27(a) "Add: Purchases during the year" 14,781.15 million (was stored rounded to 1,478.12 - fixed) |
| Inventory | 1,774.752 / 1,451.502 | BS 17,747.52 / 14,515.02 |
| Trade receivables | 959.385 / 733.757 | BS 9,593.85 / 7,337.57 |
| Trade payables | 945.529 / 576.376 | BS 511.26 + 8,944.03 / 89.70 + 5,674.06 |
| Current assets / liabilities | 3,727.508 / 2,615.438 | BS 37,275.08 / 26,154.38 |
| OCF / capex / FCF | 334.326 / 555.156 / -220.83 | CF statement |
| EPS (owners) | 15.09 (FY25 8.50) | P&L "Basic EPS - Excluding NCI" |

**The year-end balance sheet includes Doriath S.a.r.l, acquired 27-Feb-2026** (opening stock of material 514.02 and finished goods 1,160.25 million taken
over), while the P&L carries only ~1 month of it, and FY25 is the pre-acquisition balance sheet. Every average-balance ratio therefore mixes a
pre- and post-acquisition base - the engine flags these `needs_review` (acquisition guard); nothing is adjusted.

## 3. Working-capital ratios - formulas and why every source differs
| | Inventory Days | Debtor Days | Days Payable | CCC | WC Days |
|---|---|---|---|---|---|
| **Navrist (consolidated)** | 444.96 | 130.63 | 187.91 | 387.68 | 144.8 |
| Navrist formula | 365 / (COGS / **avg** inventory) | 365 / (revenue / **avg** receivables) | 365 / (**purchases** / **avg** payables) | DSO + DIO - DPO | avg(WC) / revenue x 365 |
| Same inputs, Screener's definition | 489.5 | 148.0 | 260.8 | 376.7 (rounds to 377) | not reproducible |
| **Screener consolidated** | 490 | 148 | 261 | 377 | 108 |
| Screener formula (reproduced) | closing inventory / COGS x 365 | closing receivables / sales x 365 | closing payables / COGS x 365 | 148 + 490 - 261 | undisclosed |
| Same standalone statements, Screener's definition | 542.8 | 200.4 | 335.1 | 408.1 | - |
| **Screener standalone** | 543 | 200 | 335 | 408 | 125 |

Conclusion: **the inputs agree** - Screener's consolidated *and* standalone rows are reproduced to the rupee from the filing's printed figures
with closing balances and COGS (consolidated 490 / 148 / 261 / 377; standalone 543 / 200 / 335 / 408 and FCF -169.6). The gaps are definition
differences, not extraction errors: (a) Navrist averages opening and closing balances (approved), (b) Navrist's payable days use disclosed
*purchases* (the authoritative spec's "Net Purchases"), Screener uses COGS, (c) Navrist's debtor days use revenue as a labelled proxy for credit
sales, (d) the acquisition distorts any average. Screener's Working Capital Days (108 / 125) is not derivable from the statements (its balance-sheet
"other assets / other liabilities" grouping is not published) - not a Navrist defect. No approved formula was changed.

## 4. Remaining ratios
| Ratio | Navrist | Reference | Class | Explanation |
|---|---|---|---|---|
| EBIT margin | 17.04% | Screener OPM 22% | methodology | OPM = operating profit before D&A excluding other income; EBIT = PBT + finance cost (other income in, D&A out). (EBITDA - other income)/sales = 22.2% |
| ROE | 5.53% | Screener 5.55% | correct | owners' PAT 170.121 / avg owners' equity |
| ROCE | 9.10% | Screener ~7% | methodology + acquisition | EBIT / avg(total assets - current liabilities); Screener uses equity + borrowings. Average mixes pre/post Doriath |
| Stock P/E | 75.04x | Screener 72.1 | **market-price basis** | UI price = latest Angel quote 1,132.40 (previous close 1,097.70) over FY26 owners' EPS 15.09 (Screener EPS 14.94). At the previous close the P/E would be 72.7. This is the documented product definition (latest price / fiscal-year EPS) but it was not stated on the ratio: **fixed** - the price input now says "Latest quote (source) fetched <time> - NOT the fiscal-year-end price" |
| Dividend yield | 0.13% | - | correct | DPS 1.50 (final recommended for FY26; the 0.75 interim belongs to FY25 per the report) / 1,132.40 |
| Dividend payout | 5.02% | Screener 10% | methodology | cash dividends paid to owners 8.538 (FY25 interim) / owners' PAT; declared-for-FY26 basis = 10.04% (carried as reference) |
| Tax | 12.66% | Screener 13% | correct | 32.205 = 520.63 - 189.57 - 9.01 million over PBT 254.404 |
| Current / quick / cash | 1.43 / 0.75 / 0.15 | - | correct | cash ratio = (378.069 + unrestricted other bank balances 8.26) / 2,615.438; restricted 7.30 Cr excluded; needs_review (unclassified "Deposit account") |
| Working capital | 1,112 | - | correct | |
| D/E, debt ratio, fin. leverage | 0.40 / 0.23 / 1.72 | Screener borrowings 1,867 | correct | debt 1,867.487 = borrowings 1,814.655 + leases 52.832; equity incl. NCI 4,629.961 |
| Receivables-to-payables | 1.01 | - | correct | 959.385 / 945.529 |
| BVPS | 290.02 | - | correct | 3,301.839 Cr / 113,848,310 shares |
| Gross margin / NPM | 44.06% / 7.19% | Screener net profit 222 | correct / perimeter | GM = (revenue - COGS)/revenue; NPM uses owners' PAT 170.121 (Screener's 222 is whole-entity 222.199) |
| Interest coverage | 2.71x | - | correct | EBIT 403.116 / finance costs 148.712 |
| Contribution margin | 38.06% | - | proxy | variable costs reconstructed (needs_review by design) |
| EPS growth | 77.53% | Screener 76% | correct | printed EPS 15.09 vs 8.50 (Screener 14.94 vs 8.49) |
| Free cash flow | -220.83 | Screener -220 | correct | OCF 334.326 - capex 555.156 |

## 5. Confirmed defects fixed in this pass
1. **Market price provenance** - market-dependent ratios used the latest quote with the fiscal-year per-share figures but did not say so. The price input now
   states the source, the fetch time, and that it is not the fiscal-year-end price (`tools/ratio_contract.py::live_market/_market_input`, orchestrator).
2. **Disclosed purchases rounded to 2 dp** (1,478.115 stored as 1,478.12) - now carried unrounded (`_find_disclosed_raw_material_purchases`).

## 6. Limitations that remain (not defects)
* The manual/broad extraction path reads the consolidated statements; a request for standalone facts still returns consolidated (honestly labelled).
  Standalone Screener figures were verified directly from the standalone statements in the report.
* Average-balance ratios in an acquisition year (ANURAS/Doriath) are distorted by construction and flagged `needs_review`.
* Revenue is a proxy for credit sales (never disclosed).
