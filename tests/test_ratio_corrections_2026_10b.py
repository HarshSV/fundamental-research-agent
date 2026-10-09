"""Regression tests for defects found while auditing the breakdown output against real filings (ANURAS FY26 PDF, ICICI /
Kotak / HDFC bank filings). Synthetic data only."""
import math
import unittest
from unittest.mock import patch

import tools.annual_report_financials as ar
import tools.ratio_contract as rc
from tests.test_ratio_remediation import facts, MARKET


class TestCashFlowProvenancePage(unittest.TestCase):
    def test_cash_flow_facts_cite_the_cash_flow_page_not_the_pnl_page(self):
        fs = facts(cf_page=44)
        for k in ("operating_cash_flow", "capex_ppe_purchase", "capex", "fcf", "dividends_paid"):
            self.assertEqual(fs.get(k).source_page, 44, k)
        self.assertEqual(fs.get("revenue").source_page, 40)          # P&L page untouched
        self.assertEqual(fs.get("total_assets").source_page, 42)     # balance-sheet page untouched

    def test_falls_back_to_pl_page_when_cash_flow_page_unknown(self):
        self.assertEqual(facts().get("operating_cash_flow").source_page, 40)


class TestUnitFactor(unittest.TestCase):
    def test_thousands_header_scales_to_crore(self):
        self.assertEqual(ar._unit_factor("SCHEDULE 3 - DEPOSITS\n` in ‘000s\nAt 31.03.2025"), 1e-4)
        self.assertEqual(ar._unit_factor("BALANCE SHEET (₹ in thousands)"), 1e-4)

    def test_existing_units_unchanged_and_prose_does_not_rescale(self):
        self.assertEqual(ar._unit_factor("(in ` million, unless otherwise stated)"), 0.1)
        self.assertEqual(ar._unit_factor("(₹ in Lakh)"), 0.01)
        self.assertEqual(ar._unit_factor("(₹ in Crore) employees: 2 thousand"), 1.0)


def _d(v, p=None, page=5):
    return {"cur": v, "prior": p if p is not None else v * 0.9, "page": page, "unit_factor": 1.0, "method": "row"}


def bank_parsed(**over):
    parsed = {"basis": "standalone", "problems": [], "source_url": "http://x",
              "identities": {"balance_sheet_total": True, "schedule3_components_sum_to_total": True,
                             "schedule3_total_equals_balance_sheet": True},
              "deposits": _d(1000.0), "advances": _d(800.0), "investments": _d(300.0), "borrowings": _d(100.0),
              "cash_rbi": _d(60.0), "balances_banks": _d(40.0),
              "interest_earned": _d(100.0), "interest_expended": _d(60.0), "other_income": _d(20.0), "operating_expenses": _d(30.0),
              "demand_deposits": _d(100.0), "savings_deposits": _d(300.0), "term_deposits": _d(600.0), "schedule3_total": _d(1000.0),
              "disclosed": {}, "capital_amounts": None}
    parsed.update(over)
    return parsed


class TestBankRatios(unittest.TestCase):
    def _run(self, key, **over):
        with patch.object(ar, "_get_extracted_bank_financials", return_value=bank_parsed(**over)):
            return getattr(ar, f"fetch_{key}_from_annual_report")("BANKCO", "Bank Co", 2025, True)

    def test_casa_from_proven_schedule_3(self):
        out = self._run("casa_ratio")
        self.assertEqual(out["status"], "verified")
        self.assertAlmostEqual(out["value_raw"], 40.0)
        self.assertTrue(out["breakdown"]["reconciles"])

    def test_missing_demand_is_insufficient_not_zero(self):
        out = self._run("casa_ratio", demand_deposits=None)
        self.assertFalse(out["applicable"])
        self.assertEqual(out["status"], "insufficient_data")
        self.assertIsNone(out.get("value"))

    def test_schedule_that_does_not_add_up_is_rejected(self):
        out = self._run("casa_ratio", identities={"balance_sheet_total": True, "schedule3_components_sum_to_total": False,
                                                  "schedule3_total_equals_balance_sheet": True})
        self.assertEqual(out["status"], "insufficient_data")

    def test_credit_to_deposit_and_cost_to_income(self):
        self.assertAlmostEqual(self._run("credit_to_deposit_ratio")["value_raw"], 80.0)
        c = self._run("cost_to_income_ratio")             # 30 / ((100-60) + 20) = 50%
        self.assertAlmostEqual(c["value_raw"], 50.0)
        self.assertTrue(c["breakdown"]["reconciles"])

    def test_nim_uses_average_interest_earning_assets_and_cross_checks_disclosed(self):
        out = self._run("net_interest_margin")             # NII 40 / avg(1200, 1080)=1140 -> 3.5088%
        self.assertAlmostEqual(out["value_raw"], 40.0 / 1140.0 * 100)
        self.assertEqual(out["status"], "verified")
        far = self._run("net_interest_margin", disclosed={"nim_pct": {"cur": 6.0, "page": 9, "label": "NIM"}})
        self.assertEqual(far["status"], "needs_review")

    def test_disclosed_ratios_missing_are_not_disclosed_never_zero(self):
        for key in ("gross_npa_pct", "net_npa_pct", "provision_coverage_ratio", "capital_adequacy_ratio"):
            out = self._run(key)
            self.assertEqual(out["status"], "not_disclosed", key)
            self.assertIsNone(out.get("value"), key)

    def test_disclosed_ratio_is_used_as_printed(self):
        out = self._run("gross_npa_pct", disclosed={"gross_npa_pct": {"cur": 1.42, "page": 7, "label": "Gross NPA to Gross Advances (%)"}})
        self.assertEqual((out["status"], out["value_raw"]), ("verified", 1.42))

    def test_crar_computed_from_capital_and_rwa(self):
        out = self._run("capital_adequacy_ratio", capital_amounts={"page": 8, "capital": {"cur": 200.0, "prior": 180.0, "label": "Total capital"},
                                                                  "rwa": {"cur": 1000.0, "prior": 900.0, "label": "RWA"}})
        self.assertAlmostEqual(out["value_raw"], 20.0)


class TestBankExtractorRows(unittest.TestCase):
    def test_trailing_label_fragment_is_not_a_figure(self):
        from tools.bank_extractor import parse_row
        label, nums = parse_row("Total capital (Tier 1+Tier 2) 2,666,620.9 2,242,274.8".split())
        self.assertEqual(nums, [2666620.9, 2242274.8])
        self.assertTrue(label.endswith("2)"))

    def test_schedule_reference_column_is_dropped(self):
        from tools.bank_extractor import parse_row
        self.assertEqual(parse_row("Deposits 3 4,947,074,752 4,452,687,613".split())[1], [4947074752.0, 4452687613.0])

    def test_indian_style_digit_groups_and_units(self):
        from tools.bank_extractor import parse_row, _unit_factor_to_crore
        self.assertEqual(parse_row("(i) From Banks 4511,89,19 5960,27,24".split())[1], [45118919.0, 59602724.0])
        self.assertEqual(_unit_factor_to_crore("(000s omitted)"), 1e-4)
        self.assertEqual(_unit_factor_to_crore("(` in ‘000)"), 1e-4)
        self.assertEqual(_unit_factor_to_crore("` in million, except percentage"), 0.1)

    def test_label_prefixes_and_footnote_digits_are_normalised(self):
        from tools.bank_extractor import _norm
        self.assertEqual(_norm("A. I. Demand deposits"), "demand deposits")
        self.assertEqual(_norm("A I. Demand Deposits"), "demand deposits")
        self.assertEqual(_norm("Net non-performing assets2 to net advances3"), "net non-performing assets to net advances")


class TestBreakdownDisplayAccuracy(unittest.TestCase):
    def test_graham_breakdown_names_its_real_inputs(self):
        fs = facts()
        res = rc.compute_with_parents("graham_number", fs, MARKET)
        b = res["breakdown"]
        self.assertTrue(b["reconciles"])
        self.assertIn("Book Value per Share", b["formula"])
        self.assertNotIn("Cr", b["calculation"]["expression"])          # a per-share product is not a crore amount
        self.assertAlmostEqual(b["calculation"]["result_raw"], math.sqrt(22.5 * fs.get("eps").value * fs.get("bvps").value))

    def test_eps_growth_formula_names_both_periods(self):
        res = rc.compute_with_parents("eps_growth_rate", facts(), MARKET)
        self.assertIn("FY2026", res["breakdown"]["formula"])
        self.assertIn("FY2025", res["breakdown"]["formula"])


if __name__ == "__main__":
    unittest.main()
