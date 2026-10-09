"""Anupam Rasayan (ANURAS) FY2025-26 - ratios checked against the figures PRINTED in its Integrated Report 2025-26 (INR million on the page,
converted x0.1 to INR crore) and against Screener's published annual figures.

Two layers:
  1. the contract's arithmetic on the verified printed figures (always runs; no PDF needed) - including the proof that Screener's own
     numbers are reproduced from the SAME inputs when its (closing-balance, COGS-based) definitions are applied;
  2. extraction: the facts the pipeline reads from the real PDF equal the printed figures (skipped when the PDF is not cached).

Sources: consolidated Balance Sheet p.301 / P&L p.302 / Cash Flow p.303, Notes 11-12 (cash, other bank balances), 27 (cost of materials,
'Add: Purchases during the year' 14,781.15), standalone Balance Sheet p.227 / P&L p.228 / Cash Flow p.229 (PDF pages 264-266, 190-192).
"""
import os
import unittest

import tools.ratio_contract as rc
from tools.fundamental_fact_store import factset_from_values

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICE = 1132.4                       # latest quote used by the UI run being audited (Angel; previous close 1,097.70)

# ---- consolidated, INR crore (printed INR million x 0.1) -------------------------------------------------------------------------
C = {
    "revenue": (2365.455, 1436.974), "cogs": (1442.007 - 118.751, 936.922 - 332.434), "purchases": (1478.115, None),
    "inventory": (1774.752, 1451.502), "receivables": (959.385, 733.757), "payables": (511.26 / 10 + 8944.03 / 10, 89.70 / 10 + 5674.06 / 10),
    "total_current_assets": (3727.508, 2572.950), "total_current_liabilities": (2615.438, 1808.205),
    "pbt": (254.404, 197.851), "finance_costs": (148.712, 112.220), "depreciation": (139.900, 102.276),
    "tax_expense": (52.063 - 18.957 - 0.901, 43.809 - 5.930), "pat": (170.121, 93.349), "pat_total": (222.199, 159.972),
    "equity": (3301.839, 2850.313), "nci": (1328.122, 231.342), "total_assets": (8012.604, 5268.884),
    "operating_cash_flow": (334.326, -30.125), "capex": (555.156, None), "eps": (15.09, 8.50),
    "shares_outstanding": (113_848_310.0, 109_931_337.0),
}
# ---- standalone, INR crore -------------------------------------------------------------------------------------------------------
S = {
    "revenue": 1675.567, "cogs": 1024.329 - 84.237, "inventory": 1398.020, "receivables": 919.959,
    "payables": 11.14 / 10 + 862.107, "tca": 2815.795, "tcl": 2177.889, "ocf": 274.173, "capex": 443.806,
}


def fs_consolidated(**over):
    vals = {k: v for k, v in C.items()}
    vals["working_capital"] = (C["total_current_assets"][0] - C["total_current_liabilities"][0],
                               C["total_current_assets"][1] - C["total_current_liabilities"][1])
    vals["equity_full"] = (C["equity"][0] + C["nci"][0], C["equity"][1] + C["nci"][1])
    ebit = tuple(C["pbt"][i] + C["finance_costs"][i] for i in (0, 1))
    vals["ebit"] = ebit
    vals["ebitda"] = tuple(ebit[i] + C["depreciation"][i] for i in (0, 1))
    vals["fcf"] = (C["operating_cash_flow"][0] - C["capex"][0], None)
    vals["capital_employed"] = tuple(C["total_assets"][i] - C["total_current_liabilities"][i] for i in (0, 1))
    vals["bvps"] = (C["equity"][0] * 1e7 / C["shares_outstanding"][0], C["equity"][1] * 1e7 / C["shares_outstanding"][1])
    vals.update(over)
    return factset_from_values("ANURAS", 2026, "CONSOLIDATED", vals, source_document="synthetic://anuras-printed-figures",
                               extras={"components": {"Cost of materials consumed": (1442.007, 936.922),
                                                      "Changes in inventories": (-118.751, -332.434)}})


def avg(p):
    return (p[0] + p[1]) / 2.0


class TestNavristFormulasOnTheVerifiedPrintedFigures(unittest.TestCase):

    def setUp(self):
        self.r = rc.compute_all(fs_consolidated(), {"price": PRICE, "source": "audit"})

    def v(self, key):
        return self.r[key]["value_raw"]

    # --- working capital: COGS / average inventory etc. (approved definitions) ---
    def test_inventory_days_are_365_over_cogs_turnover_on_average_inventory(self):
        cogs = C["cogs"][0]
        self.assertAlmostEqual(cogs, 1323.256, places=3)                          # = 14,420.07 - 1,187.51 million
        self.assertAlmostEqual(self.v("inventory_turnover"), cogs / avg(C["inventory"]), places=9)
        self.assertAlmostEqual(self.v("days_inventory_outstanding"), 365 * avg(C["inventory"]) / cogs, places=6)
        self.assertAlmostEqual(self.v("days_inventory_outstanding"), 444.96, places=2)

    def test_debtor_days_use_revenue_proxy_on_average_receivables(self):
        self.assertAlmostEqual(self.v("days_sales_outstanding"), 365 * avg(C["receivables"]) / C["revenue"][0], places=6)
        self.assertAlmostEqual(self.v("days_sales_outstanding"), 130.63, places=2)
        self.assertEqual(self.r["days_sales_outstanding"]["status"], "needs_review")          # revenue is a proxy for credit sales

    def test_days_payable_use_disclosed_purchases_on_average_payables(self):
        self.assertAlmostEqual(self.v("days_payables_outstanding"), 365 * avg(C["payables"]) / 1478.115, places=4)
        self.assertAlmostEqual(self.v("days_payables_outstanding"), 187.91, places=2)

    def test_cash_conversion_cycle_is_the_identity(self):
        self.assertAlmostEqual(self.v("cash_conversion_cycle"),
                               self.v("days_sales_outstanding") + self.v("days_inventory_outstanding") - self.v("days_payables_outstanding"),
                               places=9)
        self.assertAlmostEqual(self.v("cash_conversion_cycle"), 387.68, places=2)

    def test_working_capital_days_use_average_working_capital(self):
        wc = [C["total_current_assets"][i] - C["total_current_liabilities"][i] for i in (0, 1)]
        self.assertAlmostEqual(self.v("days_working_capital"), (wc[0] + wc[1]) / 2 / C["revenue"][0] * 365, places=6)
        self.assertAlmostEqual(self.v("days_working_capital"), 144.80, places=2)

    # --- Screener's numbers are reproduced from the SAME inputs with ITS definitions (closing balance / COGS) ---
    def test_screener_working_capital_rows_reproduce_from_the_same_inputs(self):
        cogs, rev = C["cogs"][0], C["revenue"][0]
        dio, dso, dpo = (C["inventory"][0] / cogs * 365, C["receivables"][0] / rev * 365, C["payables"][0] / cogs * 365)
        self.assertEqual((round(dio), round(dso), round(dpo)), (490, 148, 261))                 # Screener: 490 / 148 / 261
        self.assertEqual(round(dso + dio - dpo), 377)                                           # Screener CCC 377

    def test_screener_standalone_rows_reproduce_from_the_standalone_statements(self):
        cogs, rev = S["cogs"], S["revenue"]
        dio, dso, dpo = S["inventory"] / cogs * 365, S["receivables"] / rev * 365, S["payables"] / cogs * 365
        self.assertEqual((round(dio), round(dso), round(dpo)), (543, 200, 335))                 # Screener standalone 543 / 200 / 335
        self.assertEqual(round(dso + dio - dpo), 408)                                           # Screener standalone CCC 408
        self.assertEqual(round(S["ocf"] - S["capex"]), -170)                                    # Screener standalone FCF ~ -169 (-169.6)

    def test_consolidated_free_cash_flow_matches_screener(self):
        self.assertAlmostEqual(self.v("free_cash_flow"), 334.326 - 555.156, places=6)
        self.assertAlmostEqual(self.v("free_cash_flow"), -220.83, places=2)                     # Screener ~ -220

    # --- the other displayed ratios ---
    def test_profitability_ratios(self):
        self.assertAlmostEqual(self.v("operating_profit_margin"), (254.404 + 148.712) / 2365.455 * 100, places=6)   # EBIT margin 17.04
        self.assertAlmostEqual(self.v("operating_profit_margin"), 17.04, places=2)
        self.assertAlmostEqual(self.v("roe"), 170.121 / avg(C["equity"]) * 100, places=6)
        self.assertAlmostEqual(self.v("roe"), 5.53, places=2)
        self.assertAlmostEqual(self.v("net_profit_margin"), 170.121 / 2365.455 * 100, places=6)
        self.assertAlmostEqual(self.v("effective_tax_rate"), 32.205 / 254.404 * 100, places=2)                 # 12.66 (Screener 13)
        self.assertAlmostEqual(self.v("interest_coverage_ratio"), 403.116 / 148.712, places=6)
        ce = lambda i: C["total_assets"][i] - C["total_current_liabilities"][i]          # noqa: E731
        self.assertAlmostEqual(self.v("roce"), 403.116 / ((ce(0) + ce(1)) / 2) * 100, places=6)               # 9.10 (Screener 7)

    def test_liquidity_and_leverage_ratios(self):
        self.assertAlmostEqual(self.v("current_ratio"), 3727.508 / 2615.438, places=6)
        self.assertAlmostEqual(self.v("quick_ratio"), (3727.508 - 1774.752) / 2615.438, places=6)
        self.assertAlmostEqual(self.v("receivables_to_payables"), 959.385 / 945.529, places=6)
        self.assertAlmostEqual(self.v("working_capital"), 1112.07, places=2)
        self.assertAlmostEqual(self.v("bvps"), 3301.839 * 1e7 / 113_848_310, places=4)                        # 290.02

    def test_market_ratios_use_the_latest_quote_with_fiscal_year_per_share_figures(self):
        self.assertAlmostEqual(self.v("pe_ratio"), PRICE / 15.09, places=6)                                 # 75.04 at 1,132.40
        self.assertAlmostEqual(self.v("pe_ratio"), 75.04, places=2)
        self.assertAlmostEqual(self.v("eps_growth_rate"), (15.09 / 8.50 - 1) * 100, places=6)               # 77.53 (printed EPS)
        src = self.r["pe_ratio"]["numerator"]["source"]
        self.assertIn("NOT the fiscal-year-end price", src)                                                 # provenance is explicit
        self.assertIn("Latest quote", src)

    def test_fiscal_year_end_price_would_give_a_different_pe_so_the_basis_must_be_stated(self):
        self.assertNotAlmostEqual(PRICE / 15.09, 1097.7 / 15.09, places=1)


class TestPurchasesAreCarriedUnrounded(unittest.TestCase):

    NOTE = ("COST OF MATERIALS CONSUMED Amount (₹) in millions Particulars Notes As at March 31, 2026 As at March 31, 2025 "
            "Cost of Materials Consumed Opening stock of material - 2,731.75 2,074.04 Stock inwards on acquisition of the Subsidiary - - "
            "Opening stock of Material as at 27.02.2026 of Doriath S.a.r.l - 514.02 - Add: Purchases during the year - 14,781.15 10,026.93 "
            "18,026.92 12,100.97 Less: Closing stock of material - 3,606.85 2,731.75 Total - 27(a) 14,420.07 9,369.22")

    def test_disclosed_purchases_keep_full_precision(self):
        from tools.annual_report_financials import _find_disclosed_raw_material_purchases
        hit = _find_disclosed_raw_material_purchases([self.NOTE], 1442.007, first_page=308)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit[0], 1478.115, places=9)                      # was rounded to 1,478.12
        self.assertAlmostEqual(hit[1], 1002.693, places=9)


@unittest.skipUnless(os.path.exists(os.path.join(ROOT, "cache", "ar_pdfs", "ANURAS_2026.pdf")), "ANURAS_2026.pdf not cached")
class TestExtractedFactsEqualThePrintedFigures(unittest.TestCase):

    def test_pipeline_facts_equal_the_printed_statement_figures(self):
        from tools.manual_mode import manual_mode
        from tools.fundamental_fact_store import get_canonical_facts, clear_run_cache
        clear_run_cache()
        with manual_mode():
            fs = get_canonical_facts("ANURAS", "ANURAS", 2026)
        self.assertEqual(fs.selection.selected_basis, "CONSOLIDATED")
        for k, (cur, prior) in C.items():
            f = fs.get(k)
            self.assertIsNotNone(f, k)
            tol = 0.0051 if k not in ("eps", "shares_outstanding") else 0.0051
            if k == "tax_expense":
                tol = 0.011
            self.assertAlmostEqual(f.value, cur, delta=tol * max(1.0, abs(cur)) if k == "shares_outstanding" else tol, msg=f"{k} current")
            if prior is not None and f.prior_value is not None:
                self.assertAlmostEqual(f.prior_value, prior, delta=0.011 if k != "shares_outstanding" else 1.0, msg=f"{k} prior")


if __name__ == "__main__":
    unittest.main()
