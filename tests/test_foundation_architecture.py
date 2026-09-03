"""
Architecture-level tests for the universal quantitative foundation
(tools.statement_selector, tools.fundamental_fact_store, tools.db_ratio_reader).

Deliberately company-agnostic: every case uses a synthetic symbol
("SYNTHCO"/"SYNTHCO2") and mocked extraction, never a real company or a
real network/PDF call. These test the ARCHITECTURE's decision rules (basis
selection, no-mixed-basis, fact reuse, cache isolation, missing-data
status), not any specific stock's numbers - per the explicit instruction
not to turn foundation hardening into stock-by-stock verification.

Run: python -m pytest tests/test_foundation_architecture.py -v
 or: python -m unittest tests.test_foundation_architecture -v
"""

import unittest
from unittest.mock import patch

from tools import statement_selector
from tools import fundamental_fact_store as ffs
from tools import db_ratio_reader


def _consolidated_parsed(source_url="http://example.test/AR.pdf"):
    return {
        "revenue": (1000.0, 900.0), "pat": (120.0, 100.0), "pbt": (150.0, 130.0),
        "equity": (600.0, 520.0), "equity_full": (650.0, 560.0),
        "total_assets": (2000.0, 1800.0), "total_current_assets": (500.0, 450.0),
        "total_current_liabilities": (300.0, 280.0), "cash": (200.0, 180.0),
        "inventory": (150.0, 140.0), "receivables": (180.0, 170.0), "payables": (120.0, 110.0),
        "net_fixed_assets": (900.0, 850.0), "shares_outstanding": (10_000_000, 10_000_000),
        "eps": (12.0, 10.0), "dividend_per_share": (3.0, 2.5),
        "tax_expense": (30.0, 25.0), "finance_costs": (40.0, 35.0), "depreciation": (60.0, 55.0),
        "total_expenses": (850.0, 770.0), "employee_benefit_expense": (200.0, 180.0),
        "other_expenses": (150.0, 140.0),
        "bs_page": 42, "pl_page": 40, "source_url": source_url, "basis_used": "consolidated",
    }


def _standalone_parsed(source_url="http://example.test/AR.pdf"):
    out = _consolidated_parsed(source_url)
    out["basis_used"] = "standalone"
    out["equity_full"] = out["equity"]  # no NCI in a standalone-only filer
    return out


class TestStatementSelection(unittest.TestCase):

    def setUp(self):
        ffs.clear_run_cache()

    def test_case_a_consolidated_exists(self):
        """Case A: consolidated exists and extracts successfully -> CONSOLIDATED."""
        with patch("tools.annual_report_financials._get_extracted_financials",
                   return_value=_consolidated_parsed()):
            sel = statement_selector._resolve("SYNTHCO", "Synth Co", 2025)
        self.assertEqual(sel.selected_basis, "CONSOLIDATED")
        self.assertIn("Consolidated", sel.selection_reason)

    def test_case_b_consolidated_absent_standalone_exists(self):
        """Case B: consolidated genuinely absent (the underlying extractor's
        own fallback already returned basis_used='standalone') -> STANDALONE,
        with an honest reason, not a silent relabel."""
        with patch("tools.annual_report_financials._get_extracted_financials",
                   return_value=_standalone_parsed()):
            sel = statement_selector._resolve("SYNTHCO", "Synth Co", 2025)
        self.assertEqual(sel.selected_basis, "STANDALONE")
        self.assertIn("No consolidated", sel.selection_reason)

    def test_case_c_partial_field_missing_does_not_trigger_fallback(self):
        """Case C: consolidated exists, ONE fact (e.g. dividend_per_share)
        is simply missing (None) - must NOT be interpreted as "consolidated
        absent". basis_used stays 'consolidated'; only that field's
        canonical fact should carry NOT_DISCLOSED."""
        parsed = _consolidated_parsed()
        parsed["dividend_per_share"] = None
        with patch("tools.annual_report_financials._get_extracted_financials", return_value=parsed):
            sel = statement_selector._resolve("SYNTHCO", "Synth Co", 2025)
        self.assertEqual(sel.selected_basis, "CONSOLIDATED")

        with patch("tools.annual_report_financials._get_extracted_financials", return_value=parsed), \
             patch("tools.annual_report_financials._compute_total_debt",
                   return_value={"applicable": True, "total_debt_cur": 300.0}):
            fs = ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2025)
        self.assertEqual(fs.get("dividend_per_share").status, "NOT_DISCLOSED")
        self.assertEqual(fs.get("revenue").status, "VERIFIED")
        self.assertEqual(fs.selection.selected_basis, "CONSOLIDATED")

    def test_case_d_both_exist_consolidated_wins(self):
        """Case D: both consolidated and standalone are present (the mocked
        extractor simply returns the consolidated result for a
        consolidated=True request, as the real one does when both exist) ->
        CONSOLIDATED selected globally, not per-ratio."""
        with patch("tools.annual_report_financials._get_extracted_financials",
                   return_value=_consolidated_parsed()):
            sel = statement_selector._resolve("SYNTHCO", "Synth Co", 2025)
        self.assertEqual(sel.selected_basis, "CONSOLIDATED")

    def test_case_h_missing_facts_never_become_zero(self):
        """Case H: an Annual Report that couldn't be read at all -> every
        canonical fact is INSUFFICIENT_DATA with value=None, never 0."""
        with patch("tools.annual_report_financials._get_extracted_financials",
                   return_value={"error": "Annual Report not found."}):
            fs = ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2025)
        for key, fact in fs.facts.items():
            if key == "_error":
                continue
            self.assertIsNone(fact.value)
            self.assertEqual(fact.status, "INSUFFICIENT_DATA")


class TestCanonicalFactStoreNoMixedBasisAndReuse(unittest.TestCase):

    def setUp(self):
        ffs.clear_run_cache()

    def test_no_mixed_basis_all_facts_share_one_extraction(self):
        """Requirement #5: every canonical fact for one (symbol, FY) call
        must report the SAME statement_basis, because they're read from one
        parsed object, not independently re-resolved per fact."""
        with patch("tools.annual_report_financials._get_extracted_financials",
                   return_value=_consolidated_parsed()), \
             patch("tools.annual_report_financials._compute_total_debt",
                   return_value={"applicable": True, "total_debt_cur": 300.0}):
            fs = ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2025)
        bases = {f.statement_basis for f in fs.facts.values() if isinstance(f, ffs.CanonicalFact)}
        self.assertEqual(bases, {"CONSOLIDATED"})
        self.assertEqual(fs.get("total_debt").statement_basis, "CONSOLIDATED")
        self.assertEqual(fs.get("ebit").statement_basis, "CONSOLIDATED")

    def test_case_e_same_symbol_reused_not_re_extracted(self):
        """Case E: requesting the same (symbol, FY) twice must hit the
        in-process run cache the second time - exactly ONE extraction call
        total, not one per canonical-fact request."""
        with patch("tools.annual_report_financials._get_extracted_financials",
                   return_value=_consolidated_parsed()) as mock_extract, \
             patch("tools.annual_report_financials._compute_total_debt",
                   return_value={"applicable": True, "total_debt_cur": 300.0}):
            ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2025)
            ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2025)
        self.assertEqual(mock_extract.call_count, 1)

    def test_case_f_different_company_no_cross_contamination(self):
        """Case F: two different symbols must never share a cached FactSet."""
        with patch("tools.annual_report_financials._get_extracted_financials",
                   side_effect=[_consolidated_parsed("http://a"), _consolidated_parsed("http://b")]), \
             patch("tools.annual_report_financials._compute_total_debt",
                   return_value={"applicable": True, "total_debt_cur": 300.0}):
            fs1 = ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2025)
            fs2 = ffs.get_canonical_facts("SYNTHCO2", "Synth Co 2", 2025)
        self.assertNotEqual(fs1.symbol, fs2.symbol)
        self.assertEqual(fs1.get("revenue").source_document, "http://a")
        self.assertEqual(fs2.get("revenue").source_document, "http://b")

    def test_case_g_same_company_different_basis_no_cache_collision(self):
        """Case G: if the underlying filing's resolved basis differs across
        two separate (cache-cleared) resolutions for the same (symbol, FY)
        - e.g. a re-run after the extractor logic changes - the second call
        must report the NEW basis, not silently keep serving the first."""
        with patch("tools.annual_report_financials._get_extracted_financials",
                   return_value=_consolidated_parsed()), \
             patch("tools.annual_report_financials._compute_total_debt",
                   return_value={"applicable": True, "total_debt_cur": 300.0}):
            fs_a = ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2025)
        self.assertEqual(fs_a.selection.selected_basis, "CONSOLIDATED")

        ffs.clear_run_cache()
        with patch("tools.annual_report_financials._get_extracted_financials",
                   return_value=_standalone_parsed()), \
             patch("tools.annual_report_financials._compute_total_debt",
                   return_value={"applicable": True, "total_debt_cur": 300.0}):
            fs_b = ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2025)
        self.assertEqual(fs_b.selection.selected_basis, "STANDALONE")


class TestDbRatioReaderCacheCorrectness(unittest.TestCase):

    def test_write_persists_actual_basis_not_hardcoded_true(self):
        """The historical bug: write_db_ratio always wrote consolidated=True
        regardless of what was actually computed. Verify the payload sent
        to Supabase now reflects the `consolidated` argument."""
        captured = {}

        class _FakeTable:
            def upsert(self, payload):
                captured.update(payload)
                return self

            def execute(self):
                return None

        class _FakeClient:
            def table(self, name):
                return _FakeTable()

        with patch("tools.db_ratio_reader.get_client", return_value=_FakeClient()), \
             patch("tools.manual_mode.is_manual_mode", return_value=False):
            db_ratio_reader.write_db_ratio(
                "SYNTHCO", 20, {"selected_period": "31-Mar-2025", "applicable": True, "value": 0.5},
                consolidated=False,
            )
        self.assertEqual(captured.get("consolidated"), False)

    def test_try_db_ratio_filters_by_requested_basis(self):
        """A basis-specific lookup must add an .eq('consolidated', ...)
        filter, so a STANDALONE-resolved request can never be served a row
        that was computed on a CONSOLIDATED basis."""
        calls = {"eq_args": []}

        class _FakeQuery:
            def eq(self, field, value):
                calls["eq_args"].append((field, value))
                return self

            def order(self, *a, **k):
                return self

            def limit(self, *a, **k):
                return self

            def execute(self):
                class R:
                    data = []
                return R()

        class _FakeTable:
            def select(self, *a, **k):
                return _FakeQuery()

        class _FakeClient:
            def table(self, name):
                return _FakeTable()

        with patch("tools.db_ratio_reader.get_client", return_value=_FakeClient()), \
             patch("tools.manual_mode.is_manual_mode", return_value=False):
            db_ratio_reader.try_db_ratio("SYNTHCO", 20, consolidated=False)
        self.assertIn(("consolidated", False), calls["eq_args"])


if __name__ == "__main__":
    unittest.main()
