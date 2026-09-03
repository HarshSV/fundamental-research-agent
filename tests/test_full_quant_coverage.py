"""
Architecture-level tests for the Phase-2 completion pass: COGS/Purchases/
Retained-Earnings canonical facts, Altman/Piotroski/Beneish, bank
applicability, shareholding pledge/free-float, Beta, and precompute-worker
migration to the universal engine.

Synthetic only (symbol "SYNTHCO", mocked extraction/market/shareholding/
price-history data) - never a real company.
"""

import random
import unittest
from unittest.mock import patch

import tools.fundamental_fact_store as ffs
import tools.ratio_calculation_engine as eng
import tools.precompute_worker as pw


_COMPONENTS = {
    "Cost of materials consumed": (400.0, 360.0),
    "Purchases of stock-in-trade": (50.0, 45.0),
    "Changes in inventories": (10.0, 8.0),
}


def _parsed(**overrides):
    base = {
        "revenue": (1000.0, 900.0), "pat": (120.0, 100.0), "pbt": (150.0, 130.0),
        "equity": (600.0, 520.0), "equity_full": (650.0, 560.0),
        "retained_earnings": (400.0, 350.0), "retained_earnings_basis": "exact",
        "total_assets": (2000.0, 1800.0), "total_current_assets": (500.0, 450.0),
        "total_current_liabilities": (300.0, 280.0), "cash": (200.0, 180.0),
        "inventory": (150.0, 140.0), "receivables": (180.0, 170.0), "payables": (120.0, 110.0),
        "net_fixed_assets": (900.0, 850.0), "shares_outstanding": (10_000_000, 10_000_000),
        "eps": (12.0, 10.0), "dividend_per_share": (3.0, 2.5),
        "tax_expense": (30.0, 25.0), "finance_costs": (40.0, 35.0), "depreciation": (60.0, 55.0),
        "total_expenses": (850.0, 770.0), "employee_benefit_expense": (200.0, 180.0),
        "other_expenses": (150.0, 140.0), "operating_cash_flow": (140.0, 120.0),
        "capex_ppe_purchase": (50.0, 45.0), "capex_intangible_purchase": (5.0, 4.0),
        "capex_disposal_proceeds": (0.0, 0.0), "lt_borrowings": (200.0, 220.0),
        "borrowings_repayment": (20.0, 15.0), "lease_repayment": (5.0, 4.0),
        "interest_paid": (38.0, 33.0), "dividend_paid": (-30.0, -25.0),
        "components": dict(_COMPONENTS),
        "bs_page": 42, "pl_page": 40, "source_url": "http://example.test/AR.pdf", "basis_used": "consolidated",
    }
    base.update(overrides)
    return base


_DEBT = {"applicable": True, "total_debt_cur": 300.0}


def _patched(parsed=None, **kw):
    return patch.multiple(
        "tools.annual_report_financials",
        _get_extracted_financials=lambda *a, **k: (parsed if parsed is not None else _parsed()),
        _compute_total_debt=lambda *a, **k: _DEBT,
    )


class TestCOGSPurchasesRatios(unittest.TestCase):
    """L, M: COGS-dependent and Purchases-dependent ratios."""

    def setUp(self):
        ffs.clear_run_cache()

    def test_l_cogs_dependent_ratios_wired(self):
        with _patched():
            for key in ("inventory_turnover", "gross_profit_margin", "days_inventory_outstanding"):
                r = eng.calculate_ratio(key, "SYNTHCO", "Synth Co", 2025)
                self.assertEqual(r["status"], "VERIFIED", key)
                self.assertIsNotNone(r["value"], key)

    def test_m_purchases_dependent_ratios_wired(self):
        with _patched():
            for key in ("payables_turnover", "days_payables_outstanding", "cash_conversion_cycle"):
                r = eng.calculate_ratio(key, "SYNTHCO", "Synth Co", 2025)
                self.assertEqual(r["status"], "VERIFIED", key)
                self.assertIsNotNone(r["value"], key)

    def test_cogs_absent_never_fabricated(self):
        """No `components` disclosed -> NOT_DISCLOSED/INSUFFICIENT_DATA,
        never a fabricated COGS or a substituted operating-expense line."""
        parsed = _parsed(components={})
        with _patched(parsed):
            r = eng.calculate_ratio("gross_profit_margin", "SYNTHCO", "Synth Co", 2025)
        self.assertIn(r["status"], ("NOT_DISCLOSED", "INSUFFICIENT_DATA"))
        self.assertIsNone(r["value"])


class TestAltmanPiotroskiBeneish(unittest.TestCase):
    """N, O, P."""

    def setUp(self):
        ffs.clear_run_cache()

    def test_n_altman_z_uses_market_cap_not_book_equity(self):
        with _patched(), patch("tools.market_price.get_live_price", return_value={"ltp": 50.0, "source": "test"}):
            r = eng.calculate_ratio("altman_z_score", "SYNTHCO", "Synth Co", 2025)
        self.assertEqual(r["status"], "VERIFIED")
        self.assertIn("live_market_price", r["input_facts"])
        self.assertIn("retained_earnings", r["input_facts"])

    def test_n_altman_needs_review_on_retained_earnings_proxy(self):
        parsed = _parsed(retained_earnings_basis="other_equity_proxy")
        with _patched(parsed), patch("tools.market_price.get_live_price", return_value={"ltp": 50.0, "source": "test"}):
            r = eng.calculate_ratio("altman_z_score", "SYNTHCO", "Synth Co", 2025)
        self.assertEqual(r["status"], "NEEDS_REVIEW")

    def test_o_piotroski_computes_real_score_when_all_facts_present(self):
        with _patched():
            r = eng.calculate_ratio("piotroski_f_score", "SYNTHCO", "Synth Co", 2025)
        self.assertEqual(r["status"], "VERIFIED")
        self.assertIsInstance(r["value"], int)
        self.assertTrue(0 <= r["value"] <= 9)

    def test_o_piotroski_insufficient_when_leverage_fact_missing(self):
        parsed = _parsed(lt_borrowings=None)
        with _patched(parsed):
            r = eng.calculate_ratio("piotroski_f_score", "SYNTHCO", "Synth Co", 2025)
        # NOT_DISCLOSED (fact genuinely absent from the filing) or
        # INSUFFICIENT_DATA (couldn't be resolved) are both correct per
        # spec's status vocabulary - the only wrong outcome is a fabricated
        # partial score.
        self.assertIn(r["status"], ("NOT_DISCLOSED", "INSUFFICIENT_DATA"))
        self.assertIsNone(r["value"])

    def test_p_beneish_insufficient_never_fabricated(self):
        """SGAI has no canonical SG&A fact - whole score stays
        INSUFFICIENT_DATA (never a partial/wrong M-Score)."""
        with _patched():
            r = eng.calculate_ratio("beneish_m_score", "SYNTHCO", "Synth Co", 2025)
        self.assertEqual(r["status"], "INSUFFICIENT_DATA")
        self.assertIsNone(r["value"])


class TestBankApplicability(unittest.TestCase):
    """Q, R."""

    def test_q_not_applicable_for_non_bank_sector(self):
        with patch("tools.sector_ratio_applicability.is_bank_ratio_applicable", return_value=False), \
             patch("tools.nse_sector_map.get_nse_sector", return_value="FMCG"):
            r = eng.calculate_ratio("net_interest_margin", "SYNTHCO", "Synth Co", 2025)
        self.assertEqual(r["status"], "NOT_APPLICABLE")
        self.assertIsNone(r.get("value"))

    def test_r_bank_ratio_not_fabricated_when_applicable_but_unwired(self):
        """Sector says applicable, but the canonical banking FactSet
        doesn't exist yet - must return INSUFFICIENT_DATA with a named
        missing_dependency, never a fabricated bank ratio."""
        with patch("tools.sector_ratio_applicability.is_bank_ratio_applicable", return_value=True), \
             patch("tools.nse_sector_map.get_nse_sector", return_value="Banks"), \
             _patched():
            r = eng.calculate_ratio("net_interest_margin", "SYNTHCO", "Synth Co", 2025)
        self.assertEqual(r["status"], "INSUFFICIENT_DATA")
        self.assertIn("missing_dependency", r)
        self.assertIsNone(r["value"])


class TestShareholdingAndBeta(unittest.TestCase):
    """S, T, U."""

    def test_t_promoter_pledge_real_value(self):
        with patch("tools.shareholding_scraper.fetch_shareholding",
                   return_value={"promoter_pledge_pct": 12.5, "pledge_status": "ok",
                                 "promoter_holding_pct": 55.0, "source": "NSE"}):
            r = eng.calculate_ratio("promoter_pledge_pct", "SYNTHCO", "Synth Co", 2025)
        self.assertEqual(r["status"], "VERIFIED")
        self.assertEqual(r["value"], 12.5)

    def test_t_promoter_pledge_assumed_zero_is_needs_review_not_verified(self):
        with patch("tools.shareholding_scraper.fetch_shareholding",
                   return_value={"promoter_pledge_pct": 0.0, "pledge_status": "assumed_zero",
                                 "promoter_holding_pct": 55.0, "source": "fallback"}):
            r = eng.calculate_ratio("promoter_pledge_pct", "SYNTHCO", "Synth Co", 2025)
        self.assertEqual(r["status"], "NEEDS_REVIEW")

    def test_u_free_float_proxy_is_needs_review(self):
        with patch("tools.shareholding_scraper.fetch_shareholding",
                   return_value={"promoter_holding_pct": 55.0, "source": "Screener"}):
            r = eng.calculate_ratio("free_float_pct", "SYNTHCO", "Synth Co", 2025)
        self.assertEqual(r["status"], "NEEDS_REVIEW")
        self.assertAlmostEqual(r["value"], 45.0)

    def test_u_free_float_insufficient_when_no_shareholding_data(self):
        with patch("tools.shareholding_scraper.fetch_shareholding", return_value={}):
            r = eng.calculate_ratio("free_float_pct", "SYNTHCO", "Synth Co", 2025)
        self.assertEqual(r["status"], "INSUFFICIENT_DATA")
        self.assertIsNone(r["value"])

    def test_s_beta_computed_from_real_series(self):
        random.seed(7)
        stock = [random.gauss(0.001, 0.02) for _ in range(252)]
        mkt = [random.gauss(0.0005, 0.015) for _ in range(252)]
        with patch("tools.market_history.get_price_history", return_value=stock), \
             patch("tools.market_history.get_benchmark_history", return_value=mkt):
            r = eng.calculate_ratio("beta", "SYNTHCO", "Synth Co", 2025)
        self.assertEqual(r["status"], "VERIFIED")
        self.assertIsInstance(r["value"], float)
        self.assertEqual(r["benchmark"], "^NSEI")

    def test_s_beta_insufficient_when_no_price_history(self):
        with patch("tools.market_history.get_price_history", return_value=None), \
             patch("tools.market_history.get_benchmark_history", return_value=None):
            r = eng.calculate_ratio("beta", "SYNTHCO", "Synth Co", 2025)
        self.assertEqual(r["status"], "INSUFFICIENT_DATA")
        self.assertIsNone(r["value"])
        self.assertNotEqual(r.get("value"), 1.0)  # never a fabricated default of 1.0


class TestPrecomputeWorkerUsesEngine(unittest.TestCase):
    """V: the production precompute path calls the universal engine, not
    an independent per-ratio calculator."""

    def test_v_legacy_fetcher_shim_delegates_to_engine(self):
        with _patched(), patch("tools.annual_report_financials.list_annual_report_years", return_value=[2025]):
            fn = dict(pw.RATIO_FETCHERS)[10]  # current_ratio, sr_no 10
            out = fn("SYNTHCO", "Synth Co")
        self.assertTrue(out["applicable"])
        self.assertAlmostEqual(out["value"], 500.0 / 300.0, places=4)
        self.assertIn("consolidated", out)

    def test_v_compute_one_writes_via_engine_result(self):
        from tools.fundamental_ratio_registry import BY_SR_NO
        writes = {}

        class _FakeTable:
            def __init__(self, name):
                self._name = name

            def upsert(self, row):
                writes[self._name] = row
                return self

            def execute(self):
                return None

        class _FakeSb:
            def table(self, name):
                return _FakeTable(name)

        with _patched(), \
             patch("tools.db_ratio_reader.get_client", return_value=_FakeSb()), \
             patch("tools.manual_mode.is_manual_mode", return_value=False):
            ok = pw.compute_one(_FakeSb(), "SYNTHCO", "Synth Co", 2025, BY_SR_NO[10])
        self.assertTrue(ok)
        self.assertEqual(writes["ratio_values"]["ratio_no"], 10)
        self.assertTrue(writes["ratio_values"]["consolidated"])
        self.assertEqual(writes["ratio_values"]["extraction_version"], ffs.EXTRACTION_VERSION)


class TestProvenanceCompleteness(unittest.TestCase):
    """W, X: missing data never becomes zero; every result carries
    provenance."""

    def setUp(self):
        ffs.clear_run_cache()

    def test_w_missing_never_zero(self):
        parsed = _parsed(cash=None)
        with _patched(parsed):
            r = eng.calculate_ratio("cash_ratio", "SYNTHCO", "Synth Co", 2025)
        self.assertIn(r["status"], ("NOT_DISCLOSED", "INSUFFICIENT_DATA"))
        self.assertIsNone(r["value"])
        self.assertNotEqual(r["value"], 0)

    def test_x_every_result_has_provenance_fields(self):
        with _patched():
            r = eng.calculate_ratio("current_ratio", "SYNTHCO", "Synth Co", 2025)
        for field in ("ratio_key", "sr_no", "label", "formula", "financial_year",
                      "statement_basis", "source_documents", "status", "value", "calculation_trace"):
            self.assertIn(field, r, field)


if __name__ == "__main__":
    unittest.main()
