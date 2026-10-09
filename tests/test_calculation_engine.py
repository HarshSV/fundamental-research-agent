"""
Architecture-level tests for Phase 2: tools.ratio_calculation_engine wired
to tools.fundamental_fact_store as the sole data source for the 68-ratio
registry.

Synthetic only (symbols "SYNTHCO"/"SYNTHCO2", mocked extraction/market
data) - never a real company, per the explicit instruction that foundation
hardening must not become stock-by-stock verification.
"""

import unittest
from unittest.mock import patch

import tools.fundamental_fact_store as ffs
import tools.ratio_calculation_engine as eng
import tools.db_ratio_reader as db_ratio_reader


def _parsed(source_url="http://example.test/AR.pdf", basis_used="consolidated", **overrides):
    base = {
        "revenue": (1000.0, 900.0), "pat": (120.0, 100.0), "pbt": (150.0, 130.0),
        "equity": (600.0, 520.0), "equity_full": (650.0, 560.0),
        "total_assets": (2000.0, 1800.0), "total_current_assets": (560.0, 500.0),
        "total_current_liabilities": (300.0, 280.0), "cash": (200.0, 180.0),
        "inventory": (150.0, 140.0), "receivables": (180.0, 170.0), "payables": (120.0, 110.0),
        "net_fixed_assets": (900.0, 850.0), "shares_outstanding": (100_000_000, 100_000_000),
        "eps": (12.0, 10.0), "dividend_per_share": (3.0, 2.5),
        "tax_expense": (30.0, 25.0), "finance_costs": (40.0, 35.0), "depreciation": (60.0, 55.0),
        "total_expenses": (850.0, 770.0), "employee_benefit_expense": (200.0, 180.0),
        "other_expenses": (150.0, 140.0), "operating_cash_flow": (140.0, 120.0),
        "capex_ppe_purchase": (50.0, 45.0), "capex_intangible_purchase": (5.0, 4.0),
        "capex_disposal_proceeds": (0.0, 0.0), "borrowings_repayment": (20.0, 15.0),
        "lease_repayment": (5.0, 4.0), "interest_paid": (38.0, 33.0), "dividend_paid": (-30.0, -25.0),
        # NCI explicitly evaluated (equity_full = equity + 50), owners' profit line printed
        "non_controlling_interest": (50.0, 40.0), "pat_total": (130.0, 108.0), "nci_evaluated": True,
        "pat_basis": "owners", "equity_basis": "owners",
        "bs_page": 42, "pl_page": 40, "source_url": source_url, "basis_used": basis_used,
    }
    base.update(overrides)
    return base


_DEBT = {"applicable": True, "total_debt_cur": 300.0}


class TestCalculationEngineArchitecture(unittest.TestCase):

    def setUp(self):
        ffs.clear_run_cache()

    def test_case_a_shared_factset_no_re_extraction(self):
        """A: two different ratios for the same (symbol, FY) share one
        extraction call, not one per ratio."""
        with patch("tools.annual_report_financials._get_extracted_financials",
                   return_value=_parsed()) as mock_extract, \
             patch("tools.annual_report_financials._compute_total_debt", return_value=_DEBT):
            r1 = eng.calculate_ratio("current_ratio", "SYNTHCO", "Synth Co", 2025)
            r2 = eng.calculate_ratio("roa", "SYNTHCO", "Synth Co", 2025)
        self.assertEqual(mock_extract.call_count, 1)
        self.assertEqual(r1["status"], "VERIFIED")
        self.assertEqual(r2["status"], "VERIFIED")

    def test_case_b_consolidated_propagates_to_all_ratios(self):
        """B: every ratio computed for a consolidated filing reports
        statement_basis=CONSOLIDATED - never decided per-ratio."""
        with patch("tools.annual_report_financials._get_extracted_financials",
                   return_value=_parsed(basis_used="consolidated")), \
             patch("tools.annual_report_financials._compute_total_debt", return_value=_DEBT):
            for key in ("current_ratio", "roa", "debt_to_equity", "net_profit_margin"):
                r = eng.calculate_ratio(key, "SYNTHCO", "Synth Co", 2025)
                self.assertEqual(r["statement_basis"], "CONSOLIDATED", key)

    def test_case_c_standalone_propagates_consistently(self):
        """C: same, for a filing that only has standalone statements."""
        with patch("tools.annual_report_financials._get_extracted_financials",
                   return_value=_parsed(basis_used="standalone")), \
             patch("tools.annual_report_financials._compute_total_debt", return_value=_DEBT):
            for key in ("current_ratio", "roa", "debt_to_equity", "net_profit_margin"):
                r = eng.calculate_ratio(key, "SYNTHCO", "Synth Co", 2025)
                self.assertEqual(r["statement_basis"], "STANDALONE", key)

    def test_case_d_missing_fact_correct_status_never_zero(self):
        """D: a genuinely missing input fact yields NOT_DISCLOSED/
        INSUFFICIENT_DATA, and `value` is None - never 0."""
        parsed = _parsed()
        parsed["dividend_per_share"] = None
        with patch("tools.annual_report_financials._get_extracted_financials", return_value=parsed), \
             patch("tools.annual_report_financials._compute_total_debt", return_value=_DEBT), \
             patch("tools.market_price.get_live_price", return_value={"ltp": 50.0, "source": "test"}):
            r = eng.calculate_ratio("dividend_yield", "SYNTHCO", "Synth Co", 2025)
        self.assertIn(r["status"], ("NOT_DISCLOSED", "INSUFFICIENT_DATA"))
        self.assertIsNone(r["value"])

    def test_case_e_different_companies_no_contamination(self):
        """E: two different symbols never share source documents/facts."""
        with patch("tools.annual_report_financials._get_extracted_financials",
                   side_effect=[_parsed("http://a"), _parsed("http://b")]), \
             patch("tools.annual_report_financials._compute_total_debt", return_value=_DEBT):
            r1 = eng.calculate_ratio("current_ratio", "SYNTHCO", "Synth Co", 2025)
            r2 = eng.calculate_ratio("current_ratio", "SYNTHCO2", "Synth Co 2", 2025)
        self.assertEqual(r1["source_documents"], ["http://a"])
        self.assertEqual(r2["source_documents"], ["http://b"])

    def test_case_f_different_basis_no_contamination(self):
        """F: the same symbol resolved under two different bases (across a
        cleared run-cache) never mixes facts from one basis into the other."""
        with patch("tools.annual_report_financials._get_extracted_financials",
                   return_value=_parsed(basis_used="consolidated")), \
             patch("tools.annual_report_financials._compute_total_debt", return_value=_DEBT):
            r_cons = eng.calculate_ratio("debt_to_equity", "SYNTHCO", "Synth Co", 2025)
        ffs.clear_run_cache()
        with patch("tools.annual_report_financials._get_extracted_financials",
                   return_value=_parsed(basis_used="standalone")), \
             patch("tools.annual_report_financials._compute_total_debt", return_value=_DEBT):
            r_stand = eng.calculate_ratio("debt_to_equity", "SYNTHCO", "Synth Co", 2025)
        self.assertEqual(r_cons["statement_basis"], "CONSOLIDATED")
        self.assertEqual(r_stand["statement_basis"], "STANDALONE")

    def test_case_g_derived_facts_computed_once_and_reused(self):
        """G: EBIT (a derived fact) is computed once inside the FactSet and
        reused identically by two different ratios that both need it."""
        with patch("tools.annual_report_financials._get_extracted_financials",
                   return_value=_parsed()), \
             patch("tools.annual_report_financials._compute_total_debt", return_value=_DEBT):
            fs = ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2025)
            r_opm = eng.calculate_ratio("operating_profit_margin", "SYNTHCO", "Synth Co", 2025, _fs=fs)
            r_roce = eng.calculate_ratio("roce", "SYNTHCO", "Synth Co", 2025, _fs=fs)
        ebit = fs.get("ebit").value
        self.assertAlmostEqual(r_opm["value"], round(ebit / 1000.0 * 100, 4))
        self.assertIn("ebit", r_roce["input_facts"])
        self.assertIn("ebit", r_opm["input_facts"])

    def test_case_h_market_data_only_when_required(self):
        """H: a financial-statement-only ratio never calls get_live_price;
        a market-data ratio does."""
        with patch("tools.annual_report_financials._get_extracted_financials",
                   return_value=_parsed()), \
             patch("tools.annual_report_financials._compute_total_debt", return_value=_DEBT), \
             patch("tools.market_price.get_live_price", return_value={"ltp": 50.0, "source": "test"}) as mock_price:
            eng.calculate_ratio("current_ratio", "SYNTHCO", "Synth Co", 2025)
            self.assertEqual(mock_price.call_count, 0)
            eng.calculate_ratio("pe_ratio", "SYNTHCO", "Synth Co", 2025)
            self.assertEqual(mock_price.call_count, 1)

    def test_case_i_extraction_version_prevents_stale_reads(self):
        """I: a row written under an OLDER extraction_version must not be
        returned when the caller requests the CURRENT version."""
        class _FakeQuery:
            def __init__(self):
                self.filters = {}

            def eq(self, field, value):
                self.filters[field] = value
                return self

            def order(self, *a, **k):
                return self

            def limit(self, *a, **k):
                return self

            def execute(self):
                # Simulate a row stored under extraction_version=1; a query
                # that filtered on extraction_version=2 would never reach
                # this row in a real DB - here we assert the filter was
                # actually requested, proving the code enforces it.
                if self.filters.get("extraction_version") == 2:
                    class R:
                        data = []
                    return R()
                class R:
                    data = [{"applicable": True, "value": 1.0, "unit": "x", "confidence": None,
                             "estimated": False, "period_label": "FY24", "fiscal_year": 2024,
                             "numerator": None, "denominator": None, "sources": None,
                             "reason": None, "note": None}]
                return R()

        class _FakeTable:
            def select(self, *a, **k):
                return _FakeQuery()

        class _FakeClient:
            def table(self, name):
                return _FakeTable()

        with patch("tools.db_ratio_reader.get_client", return_value=_FakeClient()), \
             patch("tools.manual_mode.is_manual_mode", return_value=False):
            stale_ok = db_ratio_reader.try_db_ratio("SYNTHCO", 20, extraction_version=1)
            current_miss = db_ratio_reader.try_db_ratio("SYNTHCO", 20, extraction_version=2)
        self.assertIsNotNone(stale_ok)
        self.assertIsNone(current_miss)

    def test_case_j_registry_dependency_behaviour(self):
        """J: strategy-B ratios genuinely compose their dependencies'
        computed values (not re-derived independently) - DSO = 365 /
        receivables_turnover, retention_ratio = 100 - payout_ratio."""
        with patch("tools.annual_report_financials._get_extracted_financials",
                   return_value=_parsed()), \
             patch("tools.annual_report_financials._compute_total_debt", return_value=_DEBT):
            fs = ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2025)
            rt = eng.calculate_ratio("receivables_turnover", "SYNTHCO", "Synth Co", 2025, _fs=fs)
            dso = eng.calculate_ratio("days_sales_outstanding", "SYNTHCO", "Synth Co", 2025, _fs=fs)
            payout = eng.calculate_ratio("dividend_payout_ratio", "SYNTHCO", "Synth Co", 2025, _fs=fs)
            retention = eng.calculate_ratio("retention_ratio", "SYNTHCO", "Synth Co", 2025, _fs=fs)
        # derived ratios consume the parent's UNROUNDED value, never its rounded display value
        self.assertAlmostEqual(dso["value"], round(365 / rt["value_raw"], 4), places=4)
        self.assertAlmostEqual(retention["value"], round(100 - payout["value"], 4))


if __name__ == "__main__":
    unittest.main()
