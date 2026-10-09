"""Calculation-breakdown payload (tools/ratio_breakdown.py): every number shown must be the number the engine used.
Synthetic SYNTHCO fixture only."""
import unittest

import tools.annual_report_financials as ar
import tools.fundamental_ratio_registry as reg
import tools.ratio_contract as rc
from tests.test_ratio_remediation import facts, MARKET

FIRST_18 = [r["ratio_key"] for r in reg.RATIOS[:18]]


def all_results(**over):
    fs = facts(**over)
    return fs, rc.compute_all(fs, MARKET)


class TestEveryNumericRatioReconciles(unittest.TestCase):
    def test_all_numeric_ratios_have_a_reconciling_breakdown(self):
        fs, res = all_results()
        checked = 0
        for k, r in res.items():
            if r.get("value_raw") is None:
                continue
            checked += 1
            b = r.get("breakdown")
            self.assertIsNotNone(b, k)
            self.assertTrue(b["reconciles"], f"{k}: {b['notes']}")
            self.assertIsNotNone(b["calculation"], k)
            self.assertEqual(b["calculation"]["result_raw"], r["value_raw"], k)
        self.assertGreater(checked, 45)

    def test_first_18_present_and_formula_is_the_implemented_one(self):
        _, res = all_results()
        for k in FIRST_18:
            self.assertTrue(res[k]["breakdown"]["formula"], k)
        # Sr 1 divides COGS (formal correction 2026.10.7), never Net Sales; Sr 3 divides Revenue (proxy), not net credit sales
        self.assertIn("Cost of Goods Sold", res["inventory_turnover"]["breakdown"]["formula"])
        self.assertNotIn("Net Sales", res["inventory_turnover"]["breakdown"]["formula"])
        self.assertNotIn("Credit", res["receivables_turnover"]["breakdown"]["formula"])
        self.assertNotIn("closing", res["working_capital_turnover"]["breakdown"]["formula"].lower())
        self.assertIn("Average", res["working_capital_turnover"]["breakdown"]["formula"])


class TestExactInputs(unittest.TestCase):
    def test_current_ratio_inputs_are_the_used_numbers(self):
        fs, res = all_results()
        b = res["current_ratio"]["breakdown"]
        vals = {i["fact"]: i["value_raw"] for i in b["inputs"]}
        self.assertEqual(vals["total_current_assets"], 700.0)
        self.assertEqual(vals["total_current_liabilities"], 400.0)
        self.assertEqual(b["calculation"]["expression"], "₹700.00 Cr ÷ ₹400.00 Cr")
        self.assertEqual(b["result"]["value_raw"], 700.0 / 400.0)

    def test_average_leg_shows_both_years_and_the_average(self):
        _, res = all_results()
        b = res["inventory_turnover"]["breakdown"]
        names = {i["name"]: i["value_raw"] for i in b["inputs"]}
        self.assertEqual(names["FY2025 Inventory"], 100.0)
        self.assertEqual(names["FY2026 Inventory"], 200.0)
        self.assertEqual(b["steps"][0]["result_raw"], 150.0)
        self.assertIn("(₹100.00 Cr + ₹200.00 Cr) ÷ 2", b["steps"][0]["expression"])

    def test_derived_ratio_uses_unrounded_parent_and_nests_parent_breakdown(self):
        _, res = all_results()
        b = res["days_inventory_outstanding"]["breakdown"]
        parent = b["parents"][0]
        self.assertEqual(parent["value_raw"], res["inventory_turnover"]["value_raw"])
        self.assertIsNotNone(parent["breakdown"])
        self.assertIn(f"{res['inventory_turnover']['value_raw']:.4f}", b["calculation"]["expression"])
        self.assertEqual(b["calculation"]["result_raw"], 365.0 / res["inventory_turnover"]["value_raw"])

    def test_ccc_shows_all_three_unrounded_parents(self):
        _, res = all_results()
        b = res["cash_conversion_cycle"]["breakdown"]
        self.assertEqual({p["ratio_key"] for p in b["parents"]},
                         {"days_sales_outstanding", "days_inventory_outstanding", "days_payables_outstanding"})
        self.assertTrue(b["reconciles"])

    def test_composite_numerators_are_decomposed(self):
        _, res = all_results()
        self.assertEqual(res["quick_ratio"]["breakdown"]["steps"][0]["result_raw"], 500.0)          # 700 - 200
        self.assertEqual(res["operating_profit_margin"]["breakdown"]["steps"][0]["result_raw"], 160.0)  # PBT 130 + FC 30
        self.assertEqual(res["gross_profit_margin"]["breakdown"]["steps"][0]["result_raw"], 550.0)   # 1000 - (500 - 50)

    def test_total_debt_is_decomposed_into_borrowings_and_leases(self):
        _, res = all_results()
        names = [i["name"] for i in res["debt_to_equity"]["breakdown"]["inputs"]]
        self.assertTrue(any(n.startswith("Borrowings") for n in names))
        self.assertTrue(any(n.startswith("Lease liabilities") for n in names))

    def test_market_derived_ratio_marks_the_price_as_live_quote(self):
        _, res = all_results()
        price = next(i for i in res["pe_ratio"]["breakdown"]["inputs"] if i["name"] == "Market price")
        self.assertEqual(price["period"], "Live quote")
        self.assertEqual(price["value_raw"], MARKET["price"])


class TestRawNotRounded(unittest.TestCase):
    def test_result_carries_unrounded_value_and_display_separately(self):
        _, res = all_results(inventory=(200.0, 110.0))
        r = res["inventory_turnover"]
        b = r["breakdown"]
        self.assertEqual(b["result"]["value_raw"], r["value_raw"])
        self.assertNotEqual(r["value_raw"], round(r["value_raw"], 2))
        self.assertEqual(b["result"]["value_display"], f"{r['value_raw']:.2f}x")
        self.assertEqual(b["result"]["value_calc"], f"{r['value_raw']:.4f}x")


class TestMissingData(unittest.TestCase):
    def test_missing_input_is_not_disclosed_never_zero_and_no_fake_calculation(self):
        fs, res = all_results(total_current_liabilities=None)
        r = res["current_ratio"]
        b = r["breakdown"]
        self.assertIsNone(r["value_raw"])
        self.assertIsNone(b["calculation"])
        miss = [i for i in b["inputs"] if i["value_raw"] is None]
        self.assertTrue(miss)
        for i in miss:
            self.assertEqual(i["value_display"], "Not disclosed")
        self.assertTrue(b["missing"])

    def test_derived_ratio_without_parent_has_no_calculation(self):
        fs, res = all_results(inventory=None)
        self.assertIsNone(res["days_inventory_outstanding"]["value_raw"])
        self.assertIsNone(res["days_inventory_outstanding"]["breakdown"]["calculation"])


class TestProvenance(unittest.TestCase):
    def test_statement_inputs_carry_period_basis_statement_page(self):
        _, res = all_results()
        b = res["current_ratio"]["breakdown"]
        i = next(x for x in b["inputs"] if x["fact"] == "total_current_assets")
        self.assertEqual((i["period"], i["basis"], i["statement"], i["page"]), ("FY2026", "consolidated", "Balance Sheet", 42))
        self.assertIn("FY2026 Consolidated", b["source"])


class TestFormatting(unittest.TestCase):
    def test_indian_grouping_and_negative_sign(self):
        from tools.ratio_breakdown import fmt
        self.assertEqual(fmt(1234567.891, "₹ Cr"), "₹12,34,567.89 Cr")
        self.assertEqual(fmt(-118.75, "₹ Cr"), "−₹118.75 Cr")
        self.assertEqual(fmt(None, "₹ Cr"), "Not disclosed")


class TestRowPlumbing(unittest.TestCase):
    def test_breakdown_survives_the_legacy_adapter_and_row_metadata(self):
        import tools.document_analysis_engine as dae
        from tools.ratio_breakdown import BREAKDOWN_VERSION
        fs, res = all_results()
        legacy = ar._contract_to_legacy(res["current_ratio"], fs, 2026)
        self.assertIn("breakdown", legacy)
        row = dae._row_from_nse_xbrl_out(reg.BY_RATIO_KEY["current_ratio"], legacy)
        md = next(i for i in row["inputs"] if i["name"] == "_metadata")
        self.assertEqual(md["breakdown"]["ratio_key"], "current_ratio")
        self.assertEqual(md["breakdown_version"], BREAKDOWN_VERSION)

    def test_rows_without_breakdown_are_flagged_for_refresh(self):
        import tools.document_analysis_engine as dae
        old = {"ratio_key": "current_ratio", "inputs": [{"name": "_metadata", "formula_version": rc.FORMULA_VERSION}]}
        self.assertTrue(dae.mark_stale_rows([old])[0]["breakdown_outdated"])


class TestProviders(unittest.TestCase):
    def test_pledge_beta_free_float_breakdowns_reconcile(self):
        p = rc.pledge_result({"promoter_holding_pct": 50, "num_shares_pledged": 1000, "total_promoter_holding": 5000,
                              "pledge_status": "ok"})
        self.assertTrue(p["breakdown"]["reconciles"])
        b = rc.beta_result({"beta": 1.1, "cov": 0.0011, "var": 0.001, "n": 104, "start": "a", "end": "b"})
        self.assertTrue(b["breakdown"]["reconciles"])
        f = rc.free_float_result({"promoter_holding_pct": 53.7, "locked_in_pct": None})
        self.assertTrue(f["breakdown"]["reconciles"])
        u = rc.pledge_result({"promoter_holding_pct": 50, "pledge_status": "assumed_zero"})
        self.assertIsNone(u["breakdown"]["calculation"])


if __name__ == "__main__":
    unittest.main()
