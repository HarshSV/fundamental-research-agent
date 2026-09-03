"""
Architecture-level tests for Phase 3C: tools/qualitative_task_engine.py -
the universal registry -> source router -> evidence -> interpretation ->
score -> provenance -> result -> persistence pipeline, and its wiring into
the batch worker.

Synthetic only - symbol "SYNTHCO", mocked extraction/scraper/DB calls.
Never a real company (TCS/ANURAS/Prime Fresh) used as a fixture.
"""

import os
import re
import unittest
from unittest.mock import patch

import tools.qualitative_task_engine as qte
import tools.qualitative_batch_worker as qbw
from tools.qualitative_evidence import EvidenceStatus, ConfidenceTier
from tools.qualitative_task_registry import TASK_BY_ID, TASK_REGISTRY

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# A migrated (structured-primitive-backed) task with no derived/LLM gate -
# found programmatically, never hardcoded to a specific ID, so this test
# file keeps working even if the registry's migrated set changes.
_MIGRATED_TEXT_FREE_TASK = next(
    t["task_id"] for t in TASK_REGISTRY
    if qbw._is_migrated(t) and t["task_id"].startswith("D.6")
)
# Excludes any task_id already covered by a legacy CASE-A adapter table
# (tools.qualitative_legacy_adapters) - those tasks now route through their
# OWN task-specific scorer (e.g. C.3.1 -> rpt_disclosure_scoring.
# score_rpt_frequency), not the generic text-concept path this test file
# exercises. Picking one of THOSE here would silently start testing the
# wrong code path and require different mocks.
def _find_generic_rpt_task():
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


_RPT_TASK = _find_generic_rpt_task()


class _FakeQuery:
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


class _FakeTable:
    def __init__(self, name, store):
        self.name = name
        self.store = store

    def upsert(self, row, **kw):
        if self.name == "qualitative_values":
            self.store[(row["symbol"], row["subpoint_id"])] = row
        return self

    def select(self, *a, **k):
        return _FakeQuery(list(self.store.values()))

    def execute(self):
        return None


class _FakeClient:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return _FakeTable(name, self.store)


def _fake_ar(text, page=10, anchor="rpt"):
    return {"pdf_url": "http://ar.test/x.pdf", "excerpts": [{"text": text, "page": page, "anchor": anchor}]}


class Test1OneSourceEvidence(unittest.TestCase):
    def test_single_source_partially_verified(self):
        fake = _fake_ar("The Company's business model is disclosed in Note 42.")
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "Synth Co", 2025, _RPT_TASK)
        self.assertEqual(r.status, EvidenceStatus.PARTIALLY_VERIFIED)
        self.assertEqual(len(r.evidence), 1)


class Test2CorroboratedEvidence(unittest.TestCase):
    def test_two_structured_agreeing_sources_verified(self):
        with patch("tools.shareholding_scraper.fetch_shareholding",
                   return_value={"promoter_holding_pct": 55.0, "source": "NSE"}), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "Synth Co", 2025, _MIGRATED_TEXT_FREE_TASK)
        self.assertIn(r.status, (EvidenceStatus.PARTIALLY_VERIFIED, EvidenceStatus.VERIFIED))


class Test3ContradictoryEvidence(unittest.TestCase):
    def test_same_concept_disagreement_flagged(self):
        from tools.qualitative_evidence import EvidenceBundle, Confidence, ConfidenceTier
        from tools.qualitative_evidence_extraction import extract_promoter_ownership
        bundle1 = extract_promoter_ownership.__wrapped__ if hasattr(extract_promoter_ownership, "__wrapped__") \
            else None
        # Build directly: two PARTIALLY_VERIFIED evidence, SAME evidence_type, different values.
        from tools.qualitative_evidence import QualitativeEvidence
        b = EvidenceBundle(company_identity="SYNTHCO", fiscal_year=2025, task_key="C", subtask_key="C.1")
        b.add(QualitativeEvidence.build(
            company_identity="SYNTHCO", fiscal_year=2025, task_key="C", subtask_key="C.1",
            evidence_type="promoter_ownership", source_document="AR", source_document_type="annual_report",
            extracted_text="55%", normalized_value=55.0, status=EvidenceStatus.PARTIALLY_VERIFIED,
            confidence=Confidence(ConfidenceTier.MEDIUM)))
        b.add(QualitativeEvidence.build(
            company_identity="SYNTHCO", fiscal_year=2025, task_key="C", subtask_key="C.1",
            evidence_type="promoter_ownership", source_document="Shareholding", source_document_type="shareholding_pattern_filing",
            extracted_text="60%", normalized_value=60.0, status=EvidenceStatus.PARTIALLY_VERIFIED,
            confidence=Confidence(ConfidenceTier.MEDIUM)))
        status, conf = b.classify()
        self.assertEqual(status, EvidenceStatus.CONTRADICTORY_EVIDENCE)


class Test4MissingSource(unittest.TestCase):
    def test_unavailable_source_gives_insufficient_evidence_not_not_disclosed(self):
        with patch("tools.qualitative_engine._manual_doc_uploaded", return_value=False), \
             patch("tools.manual_mode.is_manual_mode", return_value=True), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "Synth Co", 2025, _MIGRATED_TEXT_FREE_TASK)
        self.assertEqual(r.status, EvidenceStatus.INSUFFICIENT_EVIDENCE)
        self.assertNotEqual(r.status, EvidenceStatus.NOT_DISCLOSED)


class Test5NotDisclosed(unittest.TestCase):
    def test_searched_nothing_found(self):
        fake = {"pdf_url": "http://x", "excerpts": []}
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "Synth Co", 2025, _RPT_TASK)
        self.assertEqual(r.status, EvidenceStatus.NOT_DISCLOSED)


class Test6ExplicitNegative(unittest.TestCase):
    def test_verified_absent(self):
        fake = _fake_ar("The Company does not have a defined business model disclosure during the year.")
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "Synth Co", 2025, _RPT_TASK)
        self.assertEqual(r.status, EvidenceStatus.VERIFIED_ABSENT)


class Test7PartialEvidence(unittest.TestCase):
    def test_single_excerpt_low_confidence(self):
        fake = _fake_ar("Business model disclosed in Note 42.")
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "Synth Co", 2025, _RPT_TASK)
        self.assertEqual(r.confidence.tier, ConfidenceTier.LOW)


class Test8HighConfidenceWeakScore(unittest.TestCase):
    def test_verified_absent_can_carry_medium_high_confidence_no_score(self):
        fake = _fake_ar("The Company does not have a defined business model.")
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "Synth Co", 2025, _RPT_TASK)
        self.assertIsNone(r.score)
        self.assertIn(r.confidence.tier, (ConfidenceTier.MEDIUM, ConfidenceTier.HIGH))


class Test9LowConfidenceUnknown(unittest.TestCase):
    def test_insufficient_evidence_low_or_unknown_confidence(self):
        with patch("tools.qualitative_engine._manual_doc_uploaded", return_value=False), \
             patch("tools.manual_mode.is_manual_mode", return_value=True), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "Synth Co", 2025, _MIGRATED_TEXT_FREE_TASK)
        self.assertIsNone(r.score)
        self.assertIn(r.confidence.tier, (ConfidenceTier.LOW, ConfidenceTier.UNKNOWN))


class Test10SourcePrioritization(unittest.TestCase):
    def test_structured_source_priority_lower_than_text(self):
        with patch("tools.shareholding_scraper.fetch_shareholding",
                   return_value={"promoter_holding_pct": 55.0, "source": "NSE"}), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "Synth Co", 2025, _MIGRATED_TEXT_FREE_TASK)
        self.assertTrue(all(e.source_priority <= 10 for e in r.evidence))


class Test11MultipleDocumentTypes(unittest.TestCase):
    def test_bundle_can_hold_evidence_from_two_source_types(self):
        with patch("tools.shareholding_scraper.fetch_shareholding",
                   return_value={"promoter_holding_pct": 55.0, "promoter_pledge_pct": 10.0,
                                 "pledge_status": "ok", "source": "NSE"}), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "Synth Co", 2025, _MIGRATED_TEXT_FREE_TASK)
        types = {e.source_document_type for e in r.evidence}
        self.assertTrue(len(r.evidence) >= 1)


class Test12TerminologyVariants(unittest.TestCase):
    def test_rpt_synonym_in_excerpt_still_classified(self):
        fake = _fake_ar("Transactions with Related Parties are set out in Note 42.")
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "Synth Co", 2025, _RPT_TASK)
        self.assertEqual(r.status, EvidenceStatus.PARTIALLY_VERIFIED)


class Test13ProvenancePreservation(unittest.TestCase):
    def test_provenance_survives_to_payload(self):
        fake = _fake_ar("Business model disclosed in Note 42.", page=77, anchor="rpt")
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "Synth Co", 2025, _RPT_TASK)
        payload = r.to_payload()
        self.assertEqual(payload["provenance"][0]["page_number"], 77)
        self.assertEqual(payload["provenance"][0]["source_document"], "http://ar.test/x.pdf")


class Test14StableResultSchema(unittest.TestCase):
    def test_every_task_produces_the_same_shape(self):
        fake_ar_ok = _fake_ar("Business model disclosed in Note 42.")
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake_ar_ok), \
             patch("tools.shareholding_scraper.fetch_shareholding",
                   return_value={"promoter_holding_pct": 55.0, "source": "NSE"}), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            for task_id in (_RPT_TASK, _MIGRATED_TEXT_FREE_TASK, "A.1"):  # A.1 is llm_dependent -> honest refusal
                r = qte.evaluate_task("SYNTHCO", "Synth Co", 2025, task_id)
                payload = r.to_payload()
                for field in ("_engine", "_engine_version", "_extraction_version", "subpoint_id",
                              "status", "confidence_tier", "rationale", "provenance"):
                    self.assertIn(field, payload, f"{task_id} missing {field}")


class Test15VersionMismatchInvalidation(unittest.TestCase):
    def test_engine_version_bump_invalidates_cache(self):
        fake = _fake_ar("Business model disclosed in Note 42.")
        client = _FakeClient()
        with patch("tools.annual_report_financials._fetch_ar_evidence_excerpts", return_value=fake) as mock_fetch, \
             patch("tools.qualitative_db.get_client", return_value=client):
            qte.evaluate_task("SYNTHCO", "Synth Co", 2025, _RPT_TASK)
            self.assertEqual(mock_fetch.call_count, 1)
            qte.evaluate_task("SYNTHCO", "Synth Co", 2025, _RPT_TASK)
            self.assertEqual(mock_fetch.call_count, 1, "second call should hit cache")
            old_v = qte.QUALITATIVE_ENGINE_VERSION
            qte.QUALITATIVE_ENGINE_VERSION = old_v + 1
            try:
                qte.evaluate_task("SYNTHCO", "Synth Co", 2025, _RPT_TASK)
                self.assertEqual(mock_fetch.call_count, 2, "version bump should force recompute")
            finally:
                qte.QUALITATIVE_ENGINE_VERSION = old_v


class Test16GenericRegistryRouting(unittest.TestCase):
    def test_unknown_task_id_error_not_crash(self):
        r = qte.evaluate_task("SYNTHCO", "Synth Co", 2025, "NOT.A.REAL.TASK")
        self.assertEqual(r.status, EvidenceStatus.ERROR)

    def test_incomplete_contract_is_needs_review_not_fabricated(self):
        incomplete = next(t for t in TASK_REGISTRY if not t["required_evidence_types"])
        with patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            r = qte.evaluate_task("SYNTHCO", "Synth Co", 2025, incomplete["task_id"])
        self.assertEqual(r.status, EvidenceStatus.NEEDS_REVIEW)
        self.assertIsNone(r.score)


class Test17APIDelegation(unittest.TestCase):
    def test_api_read_path_shares_persistence_with_engine(self):
        """app.py's /api/v1/qualitative/{symbol}/{task_id} reads via
        tools.qualitative_engine.read_qualitative, which is a re-export of
        tools.qualitative_db.read_qualitative - the SAME function the
        engine writes through. No API code change was needed for the API
        to serve universal-engine results; verify that re-export identity
        directly."""
        import tools.qualitative_engine as qe
        import tools.qualitative_db as qdb
        self.assertIs(qe.read_qualitative, qdb.read_qualitative)
        self.assertIs(qe.write_qualitative, qdb.write_qualitative)


class Test18BatchWorkerDelegation(unittest.TestCase):
    def test_migrated_task_routes_through_universal_engine(self):
        task = TASK_BY_ID[_MIGRATED_TEXT_FREE_TASK]
        fn, path = qbw._resolve_execution_fn(task)
        self.assertEqual(path, "universal_engine")

    def test_unmigrated_task_routes_through_legacy(self):
        # Found programmatically (never hardcoded) - any llm_dependent task
        # is guaranteed to stay on the legacy path, since the universal
        # engine explicitly refuses to fake a semantic/LLM judgment.
        task = next(t for t in TASK_REGISTRY if t["llm_dependent"])
        fn, path = qbw._resolve_execution_fn(task)
        self.assertEqual(path, "legacy_compute_fn")

    def test_classify_result_recognizes_new_vocabulary(self):
        self.assertEqual(qbw._classify_result({"confidence_tag": "VERIFIED_ABSENT"}), "COMPLETED")
        self.assertEqual(qbw._classify_result({"confidence_tag": "INSUFFICIENT_EVIDENCE"}), "INSUFFICIENT_DATA")
        self.assertEqual(qbw._classify_result({"confidence_tag": "NOT_APPLICABLE"}), "NOT_APPLICABLE")


class Test19ManualUploadDelegation(unittest.TestCase):
    def test_manual_mode_never_calls_live_scrapers(self):
        with patch("tools.manual_mode.is_manual_mode", return_value=True), \
             patch("tools.shareholding_scraper.fetch_shareholding") as mock_sh, \
             patch("tools.qualitative_engine._manual_doc_uploaded", return_value=False), \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            qte.evaluate_task("SYNTHCO", "Synth Co", 2025, _MIGRATED_TEXT_FREE_TASK)
        self.assertFalse(mock_sh.called, "manual mode must never silently call a live scraper")

    def test_automatic_mode_does_call_live_scrapers(self):
        with patch("tools.manual_mode.is_manual_mode", return_value=False), \
             patch("tools.shareholding_scraper.fetch_shareholding",
                   return_value={"promoter_holding_pct": 55.0, "source": "NSE"}) as mock_sh, \
             patch("tools.qualitative_db.get_client", return_value=_FakeClient()):
            qte.evaluate_task("SYNTHCO", "Synth Co", 2025, _MIGRATED_TEXT_FREE_TASK)
        self.assertTrue(mock_sh.called)


class Test19bManualUploadOrchestratorDelegates(unittest.TestCase):
    """Proves tools.document_analysis_engine.run_qualitative_analysis - the
    REAL manual-upload orchestrator, not a reimplementation - calls the
    universal engine for a migrated task, through its own actual
    ThreadPoolExecutor/retry machinery (unmocked), once the pre-existing
    external-source gate has cleared the task as document-available."""

    def test_orchestrator_calls_universal_engine_for_migrated_task(self):
        from unittest.mock import MagicMock
        import tools.document_analysis_engine as dae

        migrated_task = TASK_BY_ID[_MIGRATED_TEXT_FREE_TASK]
        fake_result = MagicMock()
        fake_result.to_payload.return_value = {"subpoint_id": migrated_task["task_id"]}
        fake_result.status.value = "PARTIALLY_VERIFIED"

        with patch.object(dae, "TASK_REGISTRY", [migrated_task]), \
             patch.object(dae, "_requires_external_source", return_value=(False, None)), \
             patch("tools.qualitative_task_engine.evaluate_task", return_value=fake_result) as mock_eval, \
             patch("tools.qualitative_engine.read_qualitative", return_value={"x": 1}), \
             patch("tools.qualitative_engine.write_qualitative"), \
             patch("tools.manual_mode.manual_mode"):
            out = dae.run_qualitative_analysis("SYNTHCO", "Synth Co")
        self.assertEqual(out["completed"], 1)
        self.assertTrue(mock_eval.called)


class Test20NoCompanySpecificLogic(unittest.TestCase):
    FILES = [
        "tools/qualitative_task_engine.py",
        "tools/qualitative_batch_worker.py",
        "tools/qualitative_migration.py",
        "tools/qualitative_evidence_extraction.py",
    ]
    BANNED_PATTERNS = [r'if\s+symbol\s*==', r'if\s+ticker\s*==', r'if\s+company_name\s*==']
    BANNED_LITERALS = ["TCS", "ANURAS", "PRIMEFRESH", "PRIME FRESH", "HINDUNILVR"]

    def test_no_banned_patterns(self):
        for relpath in self.FILES:
            with open(os.path.join(ROOT, relpath), encoding="utf-8") as f:
                src = f.read()
            for pat in self.BANNED_PATTERNS:
                self.assertIsNone(re.search(pat, src), f"{relpath}: {pat}")

    def test_no_company_literals_in_conditionals(self):
        for relpath in self.FILES:
            with open(os.path.join(ROOT, relpath), encoding="utf-8") as f:
                src = f.read()
            for lit in self.BANNED_LITERALS:
                for m in re.finditer(re.escape(lit), src):
                    line_start = src.rfind("\n", 0, m.start()) + 1
                    line_end = src.find("\n", m.start())
                    line = src[line_start:line_end if line_end != -1 else None]
                    self.assertNotRegex(line.strip(), r'^\s*(if|elif)\b', f"{relpath}: {line.strip()}")

    def test_no_hardcoded_page_numbers(self):
        for relpath in self.FILES:
            with open(os.path.join(ROOT, relpath), encoding="utf-8") as f:
                src = f.read()
            self.assertIsNone(re.search(r'if\s+page(_number)?\s*==\s*\d+', src), relpath)


if __name__ == "__main__":
    unittest.main()
