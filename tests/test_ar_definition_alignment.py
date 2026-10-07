"""
Regression tests for the Annual-Report-definition alignment of ratios 1-18:
Net Sales in the Inventory Turnover numerator, the disclosed "Purchases
during the year" in the Payables Turnover numerator, closing Working Capital
in Working Capital Turnover / Days Working Capital, unrounded parents for the
derived day-count ratios, and the owners-PAT / Other-Bank-Balance extraction
labels on the broad-extraction path.

Synthetic only ("SYNTHCO", round numbers, mocked extraction, cache I/O off) -
never a real company; the checks are about the formulas, not any one filing.
"""

import unittest
from unittest.mock import patch

import tools.annual_report_financials as ar
import tools.fundamental_fact_store as ffs
import tools.ratio_calculation_engine as eng
from tools.document_analysis_engine import _derived


def _parsed(**overrides):
    base = {
        "revenue": (1000.0, 800.0),
        "components": {"Cost of materials consumed": (500.0, 400.0), "Changes in inventories": (-50.0, -20.0)},
        "inventory": (200.0, 100.0), "receivables": (250.0, 150.0), "payables": (160.0, 140.0),
        "total_current_assets": (700.0, 600.0), "total_current_liabilities": (400.0, 380.0),
        "total_assets": (2000.0, 1800.0), "equity": (900.0, 800.0), "pat": (100.0, 80.0),
        "pat_basis": "owners", "pbt": (130.0, 100.0), "finance_costs": (30.0, 25.0),
        "cash": (50.0, 40.0), "source_url": "synthetic://doc", "pl_page": 10, "bs_page": 9,
        "basis_used": "consolidated",
    }
    base.update(overrides)
    return base


class _NoCache:
    def __enter__(self):
        self._p = [patch.object(ar, "_read_cache", lambda k: None),
                   patch.object(ar, "_write_cache", lambda k, v: None)]
        for p in self._p:
            p.start()

    def __exit__(self, *a):
        for p in self._p:
            p.stop()


def _call(fn, parsed):
    with _NoCache(), patch.object(ar, "_get_extracted_financials", return_value=parsed):
        return fn("SYNTHCO", None, 2026, consolidated=True)


def _note_page(unit_scale=1.0, with_acquisition_line=False, subtotal_ok=True):
    """Schedule III 'Cost of Materials Consumed' note: opening 100 + purchases
    420 - closing 120 = consumed 400 (in `unit_scale` units)."""
    k = lambda v: f"{v * unit_scale:,.2f}"
    acq = f"Stock inwards on acquisition of subsidiary - {k(30)} - " if with_acquisition_line else ""
    sub = 520 + (30 if with_acquisition_line else 0)
    total = sub - 120                                   # always equals the P&L consumption
    sub_printed = sub if subtotal_ok else sub + 40      # a corrupted subtotal: subtotal - closing != total
    return (f"25. COST OF MATERIALS CONSUMED Amount in millions Cost of Materials Consumed "
            f"Opening stock of material - {k(100)} {k(90)} {acq}Add: Purchases during the year - {k(420)} {k(380)} "
            f"{k(sub_printed)} {k(470)} Less: Closing stock of material - {k(120)} {k(100)} "
            f"Total - 25(a) {k(total)} {k(370)}")


class TestDisclosedPurchasesParser(unittest.TestCase):

    def test_finds_purchases_and_derives_unit_from_total(self):
        for scale, mult in ((1.0, 1.0), (10.0, 0.1), (100.0, 0.01)):   # crore / million / lakh pages
            with self.subTest(unit=scale):
                hit = ar._find_disclosed_raw_material_purchases(["x", _note_page(scale)], 400.0, first_page=7)
                self.assertIsNotNone(hit)
                self.assertAlmostEqual(hit[0], 420.0, places=1)
                self.assertEqual(hit[2], 8)

    def test_acquisition_stock_line_does_not_break_validation(self):
        hit = ar._find_disclosed_raw_material_purchases([_note_page(10.0, with_acquisition_line=True)], 430.0)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit[0], 420.0, places=1)

    def test_rejects_note_whose_total_is_not_the_pl_consumption(self):
        # right shape, wrong statement (e.g. the OTHER basis' note) -> never guessed
        self.assertIsNone(ar._find_disclosed_raw_material_purchases([_note_page(10.0)], 777.0))

    def test_rejects_internally_inconsistent_note(self):
        self.assertIsNone(ar._find_disclosed_raw_material_purchases([_note_page(1.0, subtotal_ok=False)], 400.0))

    def test_no_pages_or_no_consumption_is_none(self):
        self.assertIsNone(ar._find_disclosed_raw_material_purchases([], 400.0))
        self.assertIsNone(ar._find_disclosed_raw_material_purchases([_note_page()], None))


class TestInventoryAndPayables(unittest.TestCase):

    def test_inventory_turnover_numerator_is_net_sales_not_cogs(self):
        r = _call(ar.fetch_inventory_turnover_from_annual_report, _parsed())
        self.assertTrue(r["applicable"])
        self.assertAlmostEqual(r["value_raw"], 1000.0 / 150.0, places=6)   # Sales / avg(200,100)
        self.assertEqual(r["value"], round(1000.0 / 150.0, 2))
        self.assertEqual(r["numerator"]["value_cr"], 1000.0)
        self.assertEqual(r["numerator"]["reference_cogs_cr"], 450.0)       # COGS kept as reference only

    def test_inventory_turnover_without_revenue_is_not_fabricated(self):
        r = _call(ar.fetch_inventory_turnover_from_annual_report, _parsed(revenue=None))
        self.assertFalse(r["applicable"])
        self.assertNotIn("value", r)

    def test_payables_use_disclosed_purchases_when_available(self):
        r = _call(ar.fetch_payables_turnover_from_annual_report,
                  _parsed(purchases_disclosed={"cur": 420.0, "prior": 380.0, "page": 31}))
        self.assertEqual(r["numerator"]["value_cr"], 420.0)               # NOT cost of materials consumed (500)
        self.assertAlmostEqual(r["value_raw"], 420.0 / 150.0, places=6)   # avg payables (160+140)/2
        self.assertFalse(r["estimated"])
        self.assertIn("Purchases during the year", r["numerator"]["label"])

    def test_payables_proxy_is_flagged_not_verified(self):
        r = _call(ar.fetch_payables_turnover_from_annual_report, _parsed(purchases_disclosed=None))
        self.assertEqual(r["numerator"]["value_cr"], 500.0)               # proxy: consumption stands in
        self.assertTrue(r["estimated"])
        self.assertLessEqual(r["confidence"], 0.8)
        self.assertIn("PROXY", r["numerator"]["label"])

    def test_trading_business_purchases_unaffected(self):
        p = _parsed(components={"Purchases of stock-in-trade": (600.0, 500.0), "Changes in inventories": (-10.0, 5.0)},
                    purchases_disclosed=None)
        r = _call(ar.fetch_payables_turnover_from_annual_report, p)
        self.assertEqual(r["numerator"]["value_cr"], 600.0)
        self.assertFalse(r["estimated"])


class TestWorkingCapitalClosing(unittest.TestCase):

    def test_wc_turnover_uses_closing_working_capital(self):
        r = _call(ar.fetch_working_capital_turnover_from_annual_report, _parsed())
        self.assertAlmostEqual(r["value_raw"], 1000.0 / 300.0, places=6)   # closing CA-CL = 700-400, not avg(300, 220)
        self.assertEqual(r["denominator"]["value_cr"], 300.0)
        self.assertEqual(r["denominator"]["working_capital_by_year"], {"FY2026": 300.0, "FY2025": 220.0})

    def test_days_wc_is_reciprocal_of_wc_turnover(self):
        t = _call(ar.fetch_working_capital_turnover_from_annual_report, _parsed())
        d = _call(ar.fetch_days_working_capital_from_annual_report, _parsed())
        self.assertAlmostEqual(d["value_raw"], 365.0 / t["value_raw"], places=6)

    def test_negative_working_capital_still_withheld_for_turnover(self):
        r = _call(ar.fetch_working_capital_turnover_from_annual_report,
                  _parsed(total_current_assets=(300.0, 280.0), total_current_liabilities=(400.0, 380.0)))
        self.assertFalse(r["applicable"])


class TestDerivedUseUnroundedParents(unittest.TestCase):

    def test_doh_dso_dpo_ccc_use_raw_turnover(self):
        computed = {1: {"value": 0.82, "raw": 0.8203}, 3: {"value": 2.79, "raw": 2.7942},
                    5: {"value": 1.90, "raw": 1.8950}}
        doh, _ = _derived(2, computed)
        dso, _ = _derived(4, computed)
        dpo, _ = _derived(6, computed)
        self.assertAlmostEqual(doh, 365 / 0.8203, places=6)
        self.assertAlmostEqual(dso, 365 / 2.7942, places=6)
        self.assertAlmostEqual(dpo, 365 / 1.8950, places=6)
        computed.update({2: {"value": doh}, 4: {"value": dso}, 6: {"value": dpo}})
        ccc, _ = _derived(9, computed)
        self.assertAlmostEqual(ccc, dso + doh - dpo, places=9)

    def test_falls_back_to_displayed_value_when_no_raw(self):
        doh, _ = _derived(2, {1: {"value": 0.82}})
        self.assertAlmostEqual(doh, 365 / 0.82, places=9)

    def test_missing_parent_stays_none(self):
        self.assertEqual(_derived(2, {1: {"value": None}}), (None, None))


class TestBroadExtractionLabels(unittest.TestCase):

    def _items(self, pat_evidence):
        hit = lambda v, p=None, ev="": {"value": v, "prior_value": p, "evidence": ev, "page": 5}
        return {
            "revenue": hit(1000.0, 800.0), "pat": hit(100.0, 80.0, pat_evidence),
            "pat_total": hit(130.0, 100.0), "pbt": hit(150.0, 120.0), "equity": hit(900.0, 800.0, "Total Equity 9,000 8,000"),
            "cash": hit(50.0, 40.0), "other_bank_balances": hit(15.0, 14.0),
            "cost_of_materials_consumed": hit(500.0, 400.0),
        }

    def _broad(self, pat_evidence):
        with patch("tools.document_analysis_engine.extract_line_items", return_value=self._items(pat_evidence)):
            return ar._broad_extraction_to_parsed_shape("SYNTHCO", 2026, True)

    def test_owners_attributable_evidence_sets_pat_basis_owners(self):
        out = self._broad("Net Profit attributable to Owners of the company 1,000 900 Non controlling interest 5 6")
        self.assertEqual(out["pat_basis"], "owners")

    def test_generic_profit_label_stays_consolidated_basis(self):
        out = self._broad("Profit for the year 1,300 1,000 Other Comprehensive Income")
        self.assertEqual(out["pat_basis"], "consolidated")

    def test_other_bank_balances_now_surfaced(self):
        self.assertEqual(self._broad("Profit for the year 1,300")["other_bank_balances"], (15.0, 14.0))


class TestCashRatioSeesOtherBankBalances(unittest.TestCase):

    def test_undetermined_other_bank_balance_lowers_confidence_but_not_value(self):
        r = _call(ar.fetch_cash_ratio_from_annual_report,
                  _parsed(other_bank_balances=(15.0, 14.0), other_bank_balances_breakup=None))
        self.assertAlmostEqual(r["value"], round(50.0 / 400.0, 2))        # numerator unchanged (policy)
        self.assertEqual(r["other_bank_balances_cr"], 15.0)
        self.assertEqual(r["confidence"], 0.8)
        self.assertTrue(r["estimated"])

    def test_singular_label_is_recognised(self):
        self.assertIn("other bank balance", ar._OTHER_BANK_BALANCES_LABELS)


class TestCanonicalEngineAlignment(unittest.TestCase):

    def setUp(self):
        ffs.clear_run_cache()

    def _run(self, key, parsed):
        with patch("tools.annual_report_financials._get_extracted_financials", return_value=parsed), \
             patch("tools.annual_report_financials._compute_total_debt", return_value={"applicable": True, "total_debt_cur": 100.0}):
            return eng.calculate_ratio(key, "SYNTHCO", "Synth Co", 2026)

    def test_registry_formulas_describe_ar_definitions(self):
        from tools.fundamental_ratio_registry import BY_RATIO_KEY
        self.assertTrue(BY_RATIO_KEY["inventory_turnover"]["formula"].startswith("Net Sales"))
        self.assertIn("closing", BY_RATIO_KEY["working_capital_turnover"]["formula"])

    def test_inventory_turnover_engine_uses_revenue(self):
        r = self._run("inventory_turnover", _parsed())
        self.assertEqual(r["status"], "VERIFIED")
        self.assertAlmostEqual(r["value"], round(1000.0 / 150.0, 4), places=4)

    def test_working_capital_turnover_engine_uses_closing_wc(self):
        r = self._run("working_capital_turnover", _parsed())
        self.assertAlmostEqual(r["value"], round(1000.0 / 300.0, 4), places=4)

    def test_engine_purchases_prefer_disclosed_line(self):
        r = self._run("payables_turnover", _parsed(purchases_disclosed={"cur": 420.0, "prior": 380.0, "page": 3}))
        self.assertAlmostEqual(r["value"], round(420.0 / 150.0, 4), places=4)


if __name__ == "__main__":
    unittest.main()
