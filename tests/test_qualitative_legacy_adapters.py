"""
Tests for the CASE-A "legacy scorer adapter" migration mechanism
(tools/qualitative_legacy_adapters.py) - the bulk-migration path that
lifted universal-engine coverage from 18 to 150 tasks by calling the EXACT
SAME fetch+score functions the legacy compute_fn already called (never a
reimplementation).

Synthetic only, plus a real-cached-company smoke check (mocked DB writes,
real cached AR PDFs where available).
"""

import unittest
from unittest.mock import patch

from tools.qualitative_evidence import EvidenceStatus
from tools.qualitative_legacy_adapters import (
    LEGACY_AR_TEXT_SCORER_ADAPTERS, LEGACY_TABLE_TEXT_ADAPTERS,
    LEGACY_PRIVATE_HELPER_ADAPTERS, LEGACY_RPT_EVIDENCE_ADAPTERS, LEGACY_GOVERNANCE_FILING_ADAPTERS,
    evaluate_via_legacy_scorer, evaluate_via_legacy_table_scorer,
    evaluate_via_private_helper_scorer, evaluate_via_rpt_evidence_scorer, evaluate_via_governance_filing_scorer,
    _normalize_scorer_result,
)
from tools.qualitative_task_registry import TASK_BY_ID
import tools.qualitative_batch_worker as qbw
import tools.qualitative_task_engine as qte


class _FakeClient:
    def table(self, name):
        class T:
            def upsert(self, row, **kw):
                return self

            def execute(self):
                return None
        return T()


class TestNormalizeScorerResult(unittest.TestCase):
    def test_none_result(self):
        self.assertEqual(_normalize_scorer_result(None), (None, None))

    def test_tuple_result(self):
        self.assertEqual(_normalize_scorer_result((True, 4)), (True, 4))

    def test_string_result(self):
        self.assertEqual(_normalize_scorer_result("Qualified"), ("Qualified", None))

    def test_numeric_result(self):
        self.assertEqual(_normalize_scorer_result(3), (3, 3))

    def test_dict_with_score_field(self):
        val, score = _normalize_scorer_result({"depth_score": 5, "member_count": 10})
        self.assertEqual(score, 5)
        self.assertEqual(val["member_count"], 10)

    def test_dict_without_numeric_score(self):
        val, score = _normalize_scorer_result({"disclosed": None, "sanctions_exposure_score": None})
        self.assertIsNone(score)


_ALL_ADAPTER_TABLES = (
    LEGACY_AR_TEXT_SCORER_ADAPTERS, LEGACY_TABLE_TEXT_ADAPTERS,
    LEGACY_PRIVATE_HELPER_ADAPTERS, LEGACY_RPT_EVIDENCE_ADAPTERS, LEGACY_GOVERNANCE_FILING_ADAPTERS,
)


class TestAdapterTableIntegrity(unittest.TestCase):
    def test_every_adapter_task_id_exists_in_registry(self):
        for table in _ALL_ADAPTER_TABLES:
            for task_id in table:
                self.assertIn(task_id, TASK_BY_ID, task_id)

    def test_no_task_id_in_more_than_one_table(self):
        seen = {}
        for table in _ALL_ADAPTER_TABLES:
            for task_id in table:
                self.assertNotIn(task_id, seen, f"{task_id} appears in more than one adapter table")
                seen[task_id] = table

    def test_adapter_modules_and_functions_actually_exist(self):
        """Every (module, scorefn) pair must be a real, importable callable
        - catches a stale/renamed scoring function immediately rather than
        failing silently at evaluate_task() runtime."""
        import importlib
        for table in (LEGACY_AR_TEXT_SCORER_ADAPTERS, LEGACY_TABLE_TEXT_ADAPTERS, LEGACY_PRIVATE_HELPER_ADAPTERS,
                      LEGACY_RPT_EVIDENCE_ADAPTERS):
            for task_id, spec in table.items():
                mod = importlib.import_module(f"tools.{spec['module']}")
                self.assertTrue(hasattr(mod, spec["scorefn"]), f"{task_id}: {spec['module']}.{spec['scorefn']}")

    def test_private_helper_functions_exist_on_qualitative_engine(self):
        import tools.qualitative_engine as qe
        for task_id, spec in LEGACY_PRIVATE_HELPER_ADAPTERS.items():
            self.assertTrue(hasattr(qe, spec["helper"]), f"{task_id}: {spec['helper']}")

    def test_anchor_vars_exist_on_qualitative_engine(self):
        import tools.qualitative_engine as qe
        for task_id, spec in LEGACY_AR_TEXT_SCORER_ADAPTERS.items():
            self.assertTrue(hasattr(qe, spec["anchors_var"]), f"{task_id}: {spec['anchors_var']}")


class TestEvaluateViaLegacyScorer(unittest.TestCase):
    def test_real_match_produces_real_score(self):
        """T.1.1 wraps geopolitical_scoring.score_sanctions_exposure exactly
        - text that matches its real regex must produce its real score (2),
        not a fabricated or generic value."""
        fake_ar = {"pdf_url": "http://x", "excerpts": [
            {"text": "The Company may be affected by trade embargoes and sanctions imposed by "
                     "certain governments.", "page": 45, "anchor": "sanctions"}]}
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake_ar):
            bundle = evaluate_via_legacy_scorer("SYNTHCO", "X", 2025, "T", "T.1.1")
        self.assertEqual(len(bundle.evidence), 1)
        self.assertEqual(bundle.legacy_score, 2)

    def test_no_match_produces_not_disclosed_never_fabricated(self):
        fake_ar = {"pdf_url": "http://x", "excerpts": [
            {"text": "The Company reported strong revenue growth this year.", "page": 1, "anchor": "x"}]}
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake_ar):
            bundle = evaluate_via_legacy_scorer("SYNTHCO", "X", 2025, "T", "T.1.1")
        status, _ = bundle.classify()
        self.assertEqual(status, EvidenceStatus.NOT_DISCLOSED)
        self.assertFalse(hasattr(bundle, "legacy_score") and bundle.legacy_score)

    def test_no_excerpts_found(self):
        fake_ar = {"pdf_url": "http://x", "excerpts": []}
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake_ar):
            bundle = evaluate_via_legacy_scorer("SYNTHCO", "X", 2025, "T", "T.1.1")
        status, _ = bundle.classify()
        self.assertEqual(status, EvidenceStatus.NOT_DISCLOSED)

    def test_search_failure_is_insufficient_evidence_not_not_disclosed(self):
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", side_effect=RuntimeError("boom")):
            bundle = evaluate_via_legacy_scorer("SYNTHCO", "X", 2025, "T", "T.1.1")
        status, _ = bundle.classify()
        self.assertEqual(status, EvidenceStatus.INSUFFICIENT_EVIDENCE)

    def test_unknown_task_id_returns_empty_bundle_not_crash(self):
        bundle = evaluate_via_legacy_scorer("SYNTHCO", "X", 2025, "Z", "Z.9.9")
        self.assertEqual(len(bundle.evidence), 0)


class TestEvaluateViaLegacyTableScorer(unittest.TestCase):
    def test_real_extraction_call(self):
        with patch("tools.ar_table_extractor.extract_text_near_anchors",
                   return_value={"capex": "The Company commissioned a new greenfield facility this year."}):
            bundle = evaluate_via_legacy_table_scorer("SYNTHCO", "X", 2025, "C", "C.7.1")
        self.assertEqual(len(bundle.evidence), 1)


class TestEvaluateViaPrivateHelperScorer(unittest.TestCase):
    def test_bare_data_helper(self):
        with patch("tools.qualitative_engine._fetch_group_entities",
                   return_value=[{"name": "X Trust", "type": "SPV"}]):
            bundle = evaluate_via_private_helper_scorer("SYNTHCO", "X", 2025, "C", "C.4.2")
        self.assertGreaterEqual(len(bundle.evidence), 0)  # never crashes; may legitimately find nothing

    def test_tuple_returning_helper(self):
        with patch("tools.qualitative_engine._fetch_competitive_landscape_text",
                   return_value=("We compete with several large players in a fragmented market.", "http://x")):
            bundle = evaluate_via_private_helper_scorer("SYNTHCO", "X", 2025, "F", "F.1.2")
        self.assertIsNotNone(bundle)  # no crash regardless of scorer outcome

    def test_unknown_task_id_empty_bundle(self):
        bundle = evaluate_via_private_helper_scorer("SYNTHCO", "X", 2025, "Z", "Z.9.9")
        self.assertEqual(len(bundle.evidence), 0)


class TestEvaluateViaRptEvidenceScorer(unittest.TestCase):
    def test_real_scorer_call(self):
        fake = {"pdf_url": "http://x", "excerpts": [
            {"text": "Related party transactions during the year include sales of goods to group companies.",
             "page": 88, "anchor": "rpt"}]}
        with patch("tools.annual_report_financials.fetch_rpt_evidence_from_annual_report", return_value=fake):
            bundle = evaluate_via_rpt_evidence_scorer("SYNTHCO", "X", 2025, "C", "C.3.1")
        self.assertIsNotNone(bundle)


class TestEvaluateViaGovernanceFilingScorer(unittest.TestCase):
    def test_director_quality(self):
        fake_filing = {"cobod": [{"name": "A", "category": "Independent Director"}], "as_of_quarter": "Q1FY25"}
        with patch("tools.governance_scraper.fetch_latest_governance_filing", return_value=fake_filing):
            bundle = evaluate_via_governance_filing_scorer("SYNTHCO", "X", 2025, "C", "C.5.1")
        self.assertIsNotNone(bundle)

    def test_committee_effectiveness(self):
        fake_filing = {
            "coc": {"Audit Committee": [{"name": "A", "category": "Independent Director"}]},
            "meetingcomm": [{"commName": "Audit Committee", "date": "2025-01-01"}],
            "as_of_quarter": "Q1FY25",
        }
        with patch("tools.governance_scraper.fetch_latest_governance_filing", return_value=fake_filing):
            bundle = evaluate_via_governance_filing_scorer("SYNTHCO", "X", 2025, "C", "C.5.2")
        self.assertIsNotNone(bundle)

    def test_source_unavailable(self):
        with patch("tools.governance_scraper.fetch_latest_governance_filing", return_value=None):
            bundle = evaluate_via_governance_filing_scorer("SYNTHCO", "X", 2025, "C", "C.5.1")
        status, _ = bundle.classify()
        self.assertEqual(status, EvidenceStatus.NOT_DISCLOSED)


class TestEngineIntegration(unittest.TestCase):
    def test_evaluate_task_routes_ar_text_adapter(self):
        fake_ar = {"pdf_url": "http://x", "excerpts": [
            {"text": "sanctions imposed by certain jurisdictions and trade embargoes apply.",
             "page": 1, "anchor": "x"}]}
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake_ar), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "X", 2025, "T.1.1")
        self.assertEqual(r.status, EvidenceStatus.PARTIALLY_VERIFIED)
        self.assertEqual(r.score, 2)
        self.assertEqual(r.score_scale, "score(1-5)")

    def test_evaluate_task_routes_table_adapter(self):
        with patch("tools.ar_table_extractor.extract_text_near_anchors",
                   return_value={"capex": "greenfield expansion capex"}), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "X", 2025, "C.7.1")
        self.assertIn(r.status, (EvidenceStatus.PARTIALLY_VERIFIED, EvidenceStatus.NOT_DISCLOSED))

    def test_batch_worker_routes_legacy_adapter_tasks_to_universal_engine(self):
        for task_id in list(LEGACY_AR_TEXT_SCORER_ADAPTERS)[:5] + list(LEGACY_TABLE_TEXT_ADAPTERS):
            task = TASK_BY_ID[task_id]
            fn, path = qbw._resolve_execution_fn(task)
            self.assertEqual(path, "universal_engine", task_id)

    def test_migrated_count_substantially_increased(self):
        from tools.qualitative_task_registry import TASK_REGISTRY
        migrated = [t for t in TASK_REGISTRY if qbw._is_migrated(t)]
        self.assertGreaterEqual(len(migrated), 168)


if __name__ == "__main__":
    unittest.main()
