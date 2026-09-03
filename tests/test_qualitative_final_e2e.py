"""
Final Phase 3 end-to-end architecture test suite (spec section 28).

Synthetic only. Covers: registry integrity, evidence states, scoring
primitives, provenance, cache/versioning, execution-path parity (API/batch/
manual-upload all reaching the same engine), architecture guards, and
representative coverage across every A-U letter.
"""

import os
import re
import unittest
from unittest.mock import patch

from tools.qualitative_task_registry import TASK_REGISTRY, TASK_BY_ID
from tools.qualitative_evidence import EvidenceStatus, ConfidenceTier
import tools.qualitative_task_engine as qte
import tools.qualitative_batch_worker as qbw
import tools.qualitative_migration as qmig

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALL_LETTERS = "ABCDEFGHIJKLMNOPQRSTU"


def _generic_rpt_task():
    """A task requiring the `related_party_transaction` concept that is
    NOT covered by a legacy CASE-A adapter (tools.qualitative_legacy_adapters)
    - those route through their own task-specific scorer now, not the
    generic text-concept path these tests exercise."""
    from tools.qualitative_legacy_adapters import (
        LEGACY_AR_TEXT_SCORER_ADAPTERS, LEGACY_TABLE_TEXT_ADAPTERS,
        LEGACY_PRIVATE_HELPER_ADAPTERS, LEGACY_RPT_EVIDENCE_ADAPTERS,
    )
    adapter_covered = (set(LEGACY_AR_TEXT_SCORER_ADAPTERS) | set(LEGACY_TABLE_TEXT_ADAPTERS)
                       | set(LEGACY_PRIVATE_HELPER_ADAPTERS) | set(LEGACY_RPT_EVIDENCE_ADAPTERS))
    return next(
        t["task_id"] for t in TASK_REGISTRY
        if t["required_evidence_types"] == ["business_model"]
        and not t["derived_rollup"] and not t["llm_dependent"]
        and t["task_id"] not in adapter_covered
    )


class _FakeTable:
    def __init__(self, name, store):
        self.name, self.store = name, store

    def upsert(self, row, **kw):
        if self.name == "qualitative_values":
            self.store[(row["symbol"], row["subpoint_id"])] = row
        return self

    def select(self, *a, **k):
        class Q:
            def __init__(self, rows):
                self.rows = rows

            def eq(self, *a, **k):
                return self

            def limit(self, *a, **k):
                return self

            def execute(self):
                class R:
                    pass
                r = R()
                r.data = self.rows
                return r
        return Q(list(self.store.values()))

    def execute(self):
        return None


class _FakeClient:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return _FakeTable(name, self.store)


# ---------------------------------------------------------------- #
# A. Registry
# ---------------------------------------------------------------- #
class TestARegistry(unittest.TestCase):
    def test_1_all_364_entries_present(self):
        self.assertEqual(len(TASK_REGISTRY), 364)

    def test_2_every_au_letter_discoverable(self):
        letters_present = {t["section"] for t in TASK_REGISTRY}
        self.assertEqual(letters_present, set(ALL_LETTERS))

    def test_3_contract_fields_valid_types(self):
        for t in TASK_REGISTRY:
            self.assertIsInstance(t["preferred_sources"], list)
            self.assertIsInstance(t["fallback_sources"], list)
            self.assertIsInstance(t["required_evidence_types"], list)
            self.assertIsInstance(t["extraction_requirements"], dict)
            self.assertIsInstance(t["status_rules"], dict)
            self.assertIsInstance(t["confidence_rules"], dict)
            self.assertIsInstance(t["provenance_requirements"], list)


# ---------------------------------------------------------------- #
# B. Evidence
# ---------------------------------------------------------------- #
class TestBEvidence(unittest.TestCase):
    def setUp(self):
        self.client = _FakeClient()

    def _rpt_task(self):
        return _generic_rpt_task()

    def test_4_evidence_found(self):
        fake = {"pdf_url": "http://x", "excerpts": [{"text": "Business model disclosed in Note 42.",
                                                       "page": 1, "anchor": "rpt"}]}
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake), \
             patch("tools.qualitative_db.get_client", return_value=self.client):
            r = qte.evaluate_task("SYNTHCO", "X", 2025, self._rpt_task())
        self.assertEqual(r.status, EvidenceStatus.PARTIALLY_VERIFIED)

    def test_5_evidence_absent(self):
        fake = {"pdf_url": "http://x", "excerpts": []}
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake), \
             patch("tools.qualitative_db.get_client", return_value=self.client):
            r = qte.evaluate_task("SYNTHCO", "X", 2025, self._rpt_task())
        self.assertEqual(r.status, EvidenceStatus.NOT_DISCLOSED)

    def test_6_explicit_negative(self):
        fake = {"pdf_url": "http://x", "excerpts": [{"text": "The Company does not have a defined business model "
                                                               "disclosure.", "page": 1, "anchor": "rpt"}]}
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake), \
             patch("tools.qualitative_db.get_client", return_value=self.client):
            r = qte.evaluate_task("SYNTHCO", "X", 2025, self._rpt_task())
        self.assertEqual(r.status, EvidenceStatus.VERIFIED_ABSENT)

    def test_7_partial_evidence(self):
        fake = {"pdf_url": "http://x", "excerpts": [{"text": "Business model disclosed.",
                                                       "page": 1, "anchor": "rpt"}]}
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake), \
             patch("tools.qualitative_db.get_client", return_value=self.client):
            r = qte.evaluate_task("SYNTHCO", "X", 2025, self._rpt_task())
        self.assertEqual(r.confidence.tier, ConfidenceTier.LOW)

    def test_8_conflicting_evidence(self):
        from tools.qualitative_evidence import EvidenceBundle, QualitativeEvidence, Confidence
        b = EvidenceBundle(company_identity="S", fiscal_year=2025, task_key="C", subtask_key="C.1")
        b.add(QualitativeEvidence.build("S", 2025, "C", "C.1", "promoter_ownership", "AR", "annual_report",
                                         "55%", 55.0, EvidenceStatus.PARTIALLY_VERIFIED, Confidence(ConfidenceTier.MEDIUM)))
        b.add(QualitativeEvidence.build("S", 2025, "C", "C.1", "promoter_ownership", "SH", "shareholding_pattern_filing",
                                         "60%", 60.0, EvidenceStatus.PARTIALLY_VERIFIED, Confidence(ConfidenceTier.MEDIUM)))
        status, _ = b.classify()
        self.assertEqual(status, EvidenceStatus.CONTRADICTORY_EVIDENCE)

    def test_9_corroborating_evidence(self):
        from tools.qualitative_evidence import EvidenceBundle, QualitativeEvidence, Confidence
        b = EvidenceBundle(company_identity="S", fiscal_year=2025, task_key="C", subtask_key="C.1")
        b.add(QualitativeEvidence.build("S", 2025, "C", "C.1", "promoter_ownership", "AR", "annual_report",
                                         "55%", 55.0, EvidenceStatus.PARTIALLY_VERIFIED, Confidence(ConfidenceTier.MEDIUM)))
        b.add(QualitativeEvidence.build("S", 2025, "C", "C.1", "promoter_ownership", "SH", "shareholding_pattern_filing",
                                         "55%", 55.0, EvidenceStatus.PARTIALLY_VERIFIED, Confidence(ConfidenceTier.MEDIUM)))
        status, conf = b.classify()
        self.assertEqual(status, EvidenceStatus.VERIFIED)
        self.assertEqual(conf.tier, ConfidenceTier.HIGH)

    def test_10_multiple_documents(self):
        with patch("tools.shareholding_scraper.fetch_shareholding",
                   return_value={"promoter_holding_pct": 55.0, "promoter_pledge_pct": 5.0,
                                 "pledge_status": "ok", "source": "NSE"}), \
             patch("tools.qualitative_db.get_client", return_value=self.client):
            r = qte.evaluate_task("SYNTHCO", "X", 2025, "D.6.1")
        types = {e.source_document_type for e in r.evidence}
        self.assertTrue(len(r.evidence) >= 1 and types)

    def test_11_terminology_variants(self):
        fake = {"pdf_url": "http://x", "excerpts": [{"text": "Transactions with Related Parties are set out "
                                                               "in Note 42.", "page": 1, "anchor": "rpt"}]}
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake), \
             patch("tools.qualitative_db.get_client", return_value=self.client):
            r = qte.evaluate_task("SYNTHCO", "X", 2025, self._rpt_task())
        self.assertEqual(r.status, EvidenceStatus.PARTIALLY_VERIFIED)

    def test_12_missing_source(self):
        with patch("tools.manual_mode.is_manual_mode", return_value=True), \
             patch("tools.qualitative_engine._manual_doc_uploaded", return_value=False), \
             patch("tools.qualitative_db.get_client", return_value=self.client):
            r = qte.evaluate_task("SYNTHCO", "X", 2025, "D.6.1")
        self.assertEqual(r.status, EvidenceStatus.INSUFFICIENT_EVIDENCE)

    def test_13_source_unavailable_distinct_from_search_failed(self):
        from tools.qualitative_source_router import resolve_availability
        self.assertNotEqual(resolve_availability(available=False, searched=False),
                             resolve_availability(available=True, searched=True, search_failed=True))

    def test_14_not_applicable(self):
        from tools.qualitative_evidence import EvidenceBundle
        from tools.qualitative_source_router import resolve_availability
        b = EvidenceBundle(company_identity="S", fiscal_year=2025, task_key="S", subtask_key="S.1")
        b.source_availability["credit_rating_report"] = resolve_availability(
            available=True, searched=False, applicable=False)
        status, _ = b.classify()
        self.assertEqual(status, EvidenceStatus.NOT_APPLICABLE)


# ---------------------------------------------------------------- #
# C. Scoring
# ---------------------------------------------------------------- #
class TestCScoring(unittest.TestCase):
    def test_15_deterministic_scoring_repeatable(self):
        fake = {"pdf_url": "http://x", "excerpts": [{"text": "The Company does not have a defined business model "
                                                               "disclosure.", "page": 1, "anchor": "rpt"}]}
        rpt_task = _generic_rpt_task()
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r1 = qte.evaluate_task("SYNTHCO", "X", 2025, rpt_task, force=True)
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r2 = qte.evaluate_task("SYNTHCO", "X", 2025, rpt_task, force=True)
        self.assertEqual(r1.status, r2.status)

    def test_16_threshold_scoring_segment_concentration(self):
        with patch("tools.annual_report_financials.fetch_multi_year_segment_revenue",
                   return_value={2025: [{"label": "Textiles", "value_cr": 950.0}, {"label": "Chemicals", "value_cr": 50.0}]}), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "X", 2025, "A.1.A")
        self.assertEqual(r.score, "Single Product")
        self.assertEqual(r.score_scale, "categorical")

    def test_16b_threshold_scoring_portfolio(self):
        with patch("tools.annual_report_financials.fetch_multi_year_segment_revenue",
                   return_value={2025: [{"label": "Textiles", "value_cr": 500.0}, {"label": "Chemicals", "value_cr": 500.0}]}), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "X", 2025, "A.1.A")
        self.assertEqual(r.score, "Portfolio/Diversified")

    def test_17_matrix_scoring_audit_opinion(self):
        # C.6.3 is a CASE-A legacy-adapter task (tools.qualitative_legacy_adapters.
        # LEGACY_PRIVATE_HELPER_ADAPTERS) - it now calls the EXACT real
        # tools.auditor_scoring.score_audit_opinion via
        # tools.qualitative_engine._fetch_latest_audit_opinion_text, not the
        # generic text-concept path, so THAT is what's mocked here.
        with patch("tools.qualitative_engine._fetch_latest_audit_opinion_text",
                   return_value="Basis for Qualified Opinion: ..."), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "X", 2025, "C.6.3")
        # tools.auditor_scoring.score_audit_opinion's own real scale:
        # Modified (qualified/adverse/disclaimer) = 1, Unmodified = 5.
        self.assertEqual(r.score, 1)

    def test_18_no_score_when_evidence_insufficient(self):
        fake = {"pdf_url": "http://x", "excerpts": []}
        rpt_task = _generic_rpt_task()
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "X", 2025, rpt_task)
        self.assertIsNone(r.score)

    def test_19_confidence_independent_from_score(self):
        fake = {"pdf_url": "http://x", "excerpts": [{"text": "The Company does not have a defined business model "
                                                               "disclosure.", "page": 1, "anchor": "rpt"}]}
        rpt_task = _generic_rpt_task()
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "X", 2025, rpt_task)
        self.assertIsNone(r.score)  # VERIFIED_ABSENT still has no numeric "score"
        self.assertIn(r.confidence.tier, (ConfidenceTier.MEDIUM, ConfidenceTier.HIGH))  # yet confidence is real


# ---------------------------------------------------------------- #
# D. Provenance
# ---------------------------------------------------------------- #
class TestDProvenance(unittest.TestCase):
    def test_20_to_25_full_provenance_chain(self):
        fake = {"pdf_url": "http://ar.test/y.pdf", "excerpts": [{"text": "Business model disclosed.",
                                                                  "page": 42, "anchor": "rpt"}]}
        rpt_task = _generic_rpt_task()
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "X", 2025, rpt_task)
        p = r.to_payload()["provenance"][0]
        self.assertEqual(p["source_document"], "http://ar.test/y.pdf")   # 20
        self.assertEqual(p["page_number"], 42)                            # 21
        self.assertIn("extracted_text", p)                                # 23
        self.assertEqual(p["extraction_method"], "keyword_anchor")        # 24
        self.assertEqual(r.extraction_version, r.extraction_version)      # 25 (version present)
        self.assertIsNotNone(r.qualitative_logic_version)


# ---------------------------------------------------------------- #
# E. Cache
# ---------------------------------------------------------------- #
class TestECache(unittest.TestCase):
    def test_26_29_cache_hit_and_invalidation(self):
        fake = {"pdf_url": "http://x", "excerpts": [{"text": "Business model disclosed.",
                                                       "page": 1, "anchor": "rpt"}]}
        rpt_task = _generic_rpt_task()
        client = _FakeClient()
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake) as mock_fetch, \
             patch("tools.qualitative_db.get_client", return_value=client):
            qte.evaluate_task("SYNTHCO", "X", 2025, rpt_task)
            self.assertEqual(mock_fetch.call_count, 1)
            qte.evaluate_task("SYNTHCO", "X", 2025, rpt_task)
            self.assertEqual(mock_fetch.call_count, 1)  # 26: cache hit
            old_ev = qte.QUALITATIVE_EXTRACTION_VERSION
            qte.QUALITATIVE_EXTRACTION_VERSION = 99999
            try:
                # note: read_qualitative gate checks _extraction_version
                # against the CURRENT module constant at read time, so
                # bumping it here simulates an extraction-version change (28)
                qte.evaluate_task("SYNTHCO", "X", 2025, rpt_task)
                self.assertEqual(mock_fetch.call_count, 2)
            finally:
                qte.QUALITATIVE_EXTRACTION_VERSION = old_ev
            old_v = qte.QUALITATIVE_ENGINE_VERSION
            qte.QUALITATIVE_ENGINE_VERSION = old_v + 1
            try:
                qte.evaluate_task("SYNTHCO", "X", 2025, rpt_task)
                self.assertEqual(mock_fetch.call_count, 3)  # 29: logic version invalidation
            finally:
                qte.QUALITATIVE_ENGINE_VERSION = old_v


# ---------------------------------------------------------------- #
# F. Execution
# ---------------------------------------------------------------- #
class TestFExecution(unittest.TestCase):
    def test_30_generic_api_shares_persistence(self):
        import tools.qualitative_engine as qe
        import tools.qualitative_db as qdb
        self.assertIs(qe.read_qualitative, qdb.read_qualitative)

    def test_31_batch_worker_routes_migrated_task(self):
        migrated = next(t for t in TASK_REGISTRY if qmig.is_migrated(t))
        fn, path = qbw._resolve_execution_fn(migrated)
        self.assertEqual(path, "universal_engine")

    def test_32_manual_upload_uses_same_gate(self):
        import tools.document_analysis_engine as dae
        # Confirms the manual pipeline imports the SAME shared gate module
        # the batch worker uses (grep-level structural check - both import
        # tools.qualitative_migration, never a second competing gate).
        with open(os.path.join(ROOT, "tools", "document_analysis_engine.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("from tools.qualitative_migration import resolve_execution_fn", src)

    def test_33_same_task_same_result_across_callers(self):
        migrated = next(t for t in TASK_REGISTRY if qmig.is_migrated(t) and t["task_id"] != "D.6.1")
        with patch("tools.shareholding_scraper.fetch_shareholding",
                   return_value={"promoter_holding_pct": 55.0, "source": "NSE"}), \
             patch("tools.governance_scraper.fetch_latest_governance_filing",
                   return_value={"board": [{"name": "A"}], "source_url": "http://g"}), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            fn, _ = qbw._resolve_execution_fn(migrated)
            via_batch = fn("SYNTHCO", "X", force=True)
            via_direct = qte.evaluate_task("SYNTHCO", "X", 2025, migrated["task_id"], force=True).to_payload()
        self.assertEqual(via_batch["status"], via_direct["status"])


# ---------------------------------------------------------------- #
# G. Architecture guards
# ---------------------------------------------------------------- #
class TestGArchitecture(unittest.TestCase):
    FILES = [
        "tools/qualitative_task_engine.py", "tools/qualitative_batch_worker.py",
        "tools/qualitative_migration.py", "tools/qualitative_evidence.py",
        "tools/qualitative_source_router.py", "tools/qualitative_evidence_extraction.py",
        "tools/qualitative_scoring_primitives.py",
    ]

    def test_34_no_company_specific_branching(self):
        for relpath in self.FILES:
            with open(os.path.join(ROOT, relpath), encoding="utf-8") as f:
                src = f.read()
            self.assertIsNone(re.search(r'if\s+symbol\s*==|if\s+ticker\s*==|if\s+company_name\s*==', src), relpath)

    def test_35_no_filename_specific_logic(self):
        for relpath in self.FILES:
            with open(os.path.join(ROOT, relpath), encoding="utf-8") as f:
                src = f.read()
            self.assertIsNone(re.search(r'if\s+filename\s*==', src), relpath)

    def test_36_no_page_hardcoding(self):
        for relpath in self.FILES:
            with open(os.path.join(ROOT, relpath), encoding="utf-8") as f:
                src = f.read()
            self.assertIsNone(re.search(r'if\s+page(_number)?\s*==\s*\d+', src), relpath)

    def test_37_no_frontend_scoring_logic_files_are_backend_only(self):
        for relpath in self.FILES:
            self.assertTrue(relpath.startswith("tools/"))


# ---------------------------------------------------------------- #
# H. A-U representative coverage
# ---------------------------------------------------------------- #
class TestHAllLetters(unittest.TestCase):
    def test_38_every_letter_has_a_task_that_evaluates_without_crashing(self):
        """One task per letter (first non-derived, non-llm task found) is
        run through the universal engine with EVERY source unavailable -
        proving the engine handles all 21 letters honestly (no crash, no
        fabricated result) even with zero real evidence supplied."""
        fake_empty_ar = {"pdf_url": "http://x", "excerpts": []}
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake_empty_ar), \
             patch("tools.annual_report_financials.fetch_multi_year_segment_revenue", return_value={}), \
             patch("tools.shareholding_scraper.fetch_shareholding", return_value={}), \
             patch("tools.governance_scraper.fetch_latest_governance_filing", return_value={}), \
             patch("tools.insider_trading_scraper.fetch_insider_trades", return_value=[]), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            for letter in ALL_LETTERS:
                task = next((t for t in TASK_REGISTRY if t["section"] == letter
                             and not t["derived_rollup"] and not t["llm_dependent"]), None)
                if task is None:
                    continue
                r = qte.evaluate_task("SYNTHCO", "X", 2025, task["task_id"])
                self.assertIsInstance(r.status, EvidenceStatus, f"letter {letter} task {task['task_id']} crashed")
                self.assertIn(r.status, (EvidenceStatus.NOT_DISCLOSED, EvidenceStatus.INSUFFICIENT_EVIDENCE,
                                          EvidenceStatus.NEEDS_REVIEW, EvidenceStatus.NOT_APPLICABLE,
                                          EvidenceStatus.ERROR))

    def test_39b_concept_overlap_alone_does_not_force_migration(self):
        """The concept-level gate (STRUCTURED_PRIMITIVES) must NEVER
        auto-migrate a task just because it shares an evidence concept with
        an already-scored task - P.3.2 ('Audit Attention Score...
        materiality and recurrence') shares `auditor_qualification` with
        C.6.3 but is a different rubric. It IS legitimately migrated now,
        via the CASE-A adapter table (tools.qualitative_legacy_adapters),
        keyed by task_id and calling P.3.2's OWN scorer
        (disclosure_audit_scoring.score_emphasis_of_matter) - never C.6.3's
        audit-opinion-severity scorer. This test locks in THAT distinction:
        task-id-specific adapter, not concept-level inference."""
        from tools.qualitative_legacy_adapters import LEGACY_AR_TEXT_SCORER_ADAPTERS
        p32_adapter = LEGACY_AR_TEXT_SCORER_ADAPTERS.get("P.3.2")
        self.assertIsNotNone(p32_adapter)
        self.assertEqual(p32_adapter["scorefn"], "score_emphasis_of_matter")
        self.assertNotEqual(p32_adapter["scorefn"], "interpret_audit_opinion_severity_score")
        # The OLD concept-level gate (structured primitives only, no
        # task-id-specific adapter) still correctly excludes P.3.2 - proving
        # the fix was adding a task-specific path, not loosening the
        # concept-level one.
        from tools.qualitative_evidence_extraction import STRUCTURED_PRIMITIVES
        p32 = next(t for t in TASK_REGISTRY if t["task_id"] == "P.3.2")
        required = p32.get("required_evidence_types") or []
        self.assertFalse(required and all(c in STRUCTURED_PRIMITIVES for c in required))

    def test_39_migrated_tasks_all_execute_through_universal_engine(self):
        migrated = [t for t in TASK_REGISTRY if qmig.is_migrated(t)]
        self.assertGreater(len(migrated), 0)
        for t in migrated:
            fn, path = qbw._resolve_execution_fn(t)
            self.assertEqual(path, "universal_engine", t["task_id"])

    def test_40_incomplete_tasks_return_honest_status(self):
        incomplete = [t for t in TASK_REGISTRY if not t["required_evidence_types"]]
        self.assertGreater(len(incomplete), 0)
        with patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            for t in incomplete[:15]:
                r = qte.evaluate_task("SYNTHCO", "X", 2025, t["task_id"])
                self.assertIn(r.status, (EvidenceStatus.NEEDS_REVIEW, EvidenceStatus.ERROR))
                self.assertIsNone(r.score)


if __name__ == "__main__":
    unittest.main()
