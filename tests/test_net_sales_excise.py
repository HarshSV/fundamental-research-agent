"""Excise duty / other-operating-revenue policy (2026.10.17): revenue from operations stays the source-reported fact; a SEPARATE net-sales fact
(revenue less an excise-duty EXPENSE line) feeds the revenue-denominated ratios. Other operating revenue is part of revenue from operations and is
never deducted. Synthetic round numbers; expected values are written out by hand."""
import unittest

import tools.annual_report_financials as ar
import tools.ratio_contract as rc
from tests.test_ratio_remediation import MARKET, facts


def val(key, fs, market=None):
    return rc.compute_with_parents(key, fs, market, {})


class TestNetSales(unittest.TestCase):

    def setUp(self):
        # revenue 1000 (800 prior) is gross of excise duty 100 (80 prior): net sales 900 (720)
        self.fs = facts(excise_duty=(100.0, 80.0))

    def test_reported_revenue_is_kept_and_net_sales_is_a_separate_fact(self):
        self.assertEqual(self.fs.get("revenue").value, 1000.0)
        ns = self.fs.get("net_sales")
        self.assertEqual((ns.value, ns.prior_value, ns.source_tag), (900.0, 720.0, "revenue-excise_duty"))

    def test_no_excise_line_means_net_sales_is_the_reported_revenue(self):
        fs = facts()                                       # HUL-style: other operating revenue sits INSIDE revenue, nothing is deducted
        self.assertEqual(fs.get("net_sales").value, fs.get("revenue").value)
        self.assertEqual(val("net_profit_margin", fs)["value_raw"], 100.0 / 1000.0 * 100)

    def test_revenue_denominated_ratios_use_net_sales(self):
        fs = self.fs
        self.assertAlmostEqual(val("net_profit_margin", fs)["value_raw"], 100.0 / 900.0 * 100, places=9)
        self.assertAlmostEqual(val("operating_profit_margin", fs)["value_raw"], 160.0 / 900.0 * 100, places=9)    # EBIT 130 + 30
        cogs = 500.0 - 50.0
        self.assertAlmostEqual(val("gross_profit_margin", fs)["value_raw"], (900.0 - cogs) / 900.0 * 100, places=9)
        self.assertAlmostEqual(val("asset_turnover", fs)["value_raw"], 900.0 / ((2000.0 + 1800.0) / 2), places=9)
        self.assertAlmostEqual(val("receivables_turnover", fs)["value_raw"], 900.0 / ((250.0 + 150.0) / 2), places=9)

    def test_price_to_sales_and_ev_to_sales_use_net_sales(self):
        fs = self.fs
        mcap = 100.0 * 100_000_000.0 / 1e7                 # price 100 x 10 Cr shares = 1,000 Cr
        self.assertAlmostEqual(val("ps_ratio", fs, MARKET)["value_raw"], mcap / 900.0, places=9)

    def test_breakdown_shows_revenue_and_the_excise_deduction_only_when_applied(self):
        names = [i["name"] for i in val("net_profit_margin", self.fs)["breakdown"]["inputs"]]
        self.assertIn("Revenue from Operations", names)
        self.assertIn("Excise Duty", names)
        plain = [i["name"] for i in val("net_profit_margin", facts())["breakdown"]["inputs"]]
        self.assertNotIn("Excise Duty", plain)

    def test_excise_deducted_only_when_printed_below_total_income(self):
        expense_layout = "Total Income 84142.47 Expenses Cost of materials consumed 23757.33 21288.44 Excise duty 6289.44 5959.49 Employee benefits 6169.78 5548.53"
        old_layout = "Revenue from operations (gross) 90000.00 85000.00 Less: Excise duty 6289.44 5959.49 Revenue from operations (net) 83710.56 79040.51 Total Income 84142.47"
        hit = ar._find_row_values(expense_layout, ["excise duty"], after=r"total\s+income")
        self.assertEqual(hit, (6289.44, 5959.49))
        self.assertIsNone(ar._find_row_values(old_layout, ["excise duty"], after=r"total\s+income"))


if __name__ == "__main__":
    unittest.main()
