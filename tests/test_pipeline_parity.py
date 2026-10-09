"""ONE financial-fact path: the manual document pipeline and the automatic pipeline must hand the ratio engine the SAME facts for the
same company and fiscal period (PAT, equity, ...). The extraction improvements that used to be fenced to the manual pipeline now apply
to every pipeline; `is_manual_mode()` survives only for SOURCE selection (never reach live BSE/NSE from an upload) and cache separation.

Fast structural tests run always; the real-Annual-Report parity runs (a subprocess driving tests/pipeline_parity_probe.py over the cached
PDFs) are skipped when the PDFs are absent or NAVRIST_SKIP_SLOW_TESTS is set."""
import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# the only functions of annual_report_financials.py allowed to look at the pipeline mode: cache keys and live-source resolution
MODE_AWARE_FUNCTIONS = {"_contract_cache_key", "_fetch_ar_evidence_excerpts", "list_annual_report_years", "_find_annual_report_pdf",
                        "_get_extracted_financials", "_get_extracted_financials_impl"}


class TestNoExtractionLogicIsFencedToOnePipeline(unittest.TestCase):

    def test_is_manual_mode_is_only_used_for_source_selection_and_cache_keys(self):
        src = open(os.path.join(ROOT, "tools", "annual_report_financials.py"), encoding="utf-8").read()
        tree = ast.parse(src)
        users = set()
        for fn in tree.body:
            if isinstance(fn, ast.FunctionDef):
                for n in ast.walk(fn):
                    if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "is_manual_mode":
                        users.add(fn.name)
        self.assertEqual(users - MODE_AWARE_FUNCTIONS, set(),
                         "extraction/parsing logic must not branch on the pipeline mode - the same document must give the same facts")

    def test_extract_line_items_reads_the_requested_year_and_ignores_uploaded_xbrl_outside_manual_mode(self):
        import tools.document_analysis_engine as dae
        seen = {}

        def fake_pages(sym, name, fiscal_year=None):
            seen["fy"] = fiscal_year
            return {"pages": []}
        with patch("tools.ar_document_cache.get_ar_pages", fake_pages):
            dae.extract_line_items("SYNTH", 2024)
        self.assertEqual(seen["fy"], 2024)
        self.assertFalse(dae._manual_xbrl_allowed())
        from tools.manual_mode import manual_mode
        with manual_mode():
            self.assertTrue(dae._manual_xbrl_allowed())

    def test_the_broad_extractor_fallback_is_taken_in_the_automatic_pipeline_too(self):
        import tools.annual_report_financials as ar
        called = {}

        def fake_broad(sym, fy, consolidated, content=None):
            called["args"] = (sym, fy, consolidated, content is not None)
            return {"revenue": (100.0, 90.0), "pat": (10.0, 9.0)}
        with patch.object(ar, "_read_cache", lambda k: None), patch.object(ar, "_write_cache", lambda k, v: None), \
                patch.object(ar, "_find_annual_report_pdf", lambda s, n, y: "https://example.test/ar.pdf"), \
                patch.object(ar, "_sess", lambda: type("S", (), {"get": staticmethod(lambda *a, **k: type("R", (), {"content": b"x" * 60000})())})()), \
                patch.object(ar, "_extract_from_pdf", lambda c, consolidated=True: {"error": "Consolidated Statement of Profit and Loss not found."}), \
                patch.object(ar, "_bank_core_parsed", lambda c, fy: None), \
                patch.object(ar, "_broad_extraction_to_parsed_shape", fake_broad), \
                patch.object(ar, "_attach_text_disclosures", lambda p, c, fy: p):
            out = ar._get_extracted_financials_impl("SYNTH", "Synth", 2026, True)
        self.assertEqual(called["args"], ("SYNTH", 2026, True, True))          # same fallback, same year, same PDF bytes
        self.assertEqual(out["pat"], (10.0, 9.0))
        self.assertIn("narrow_parser_error", out)

    def test_a_label_followed_by_a_colon_still_matches(self):
        from tools.annual_report_financials import _find_row_values
        text = "Profit for the year attributable to: Shareholders of the Company 48,553 45,908 Non-controlling interests 244 191"
        self.assertEqual(_find_row_values(text, ["attributable to shareholders of the company"]), (48553.0, 45908.0))


@unittest.skipIf(os.environ.get("NAVRIST_SKIP_SLOW_TESTS"), "slow real-document parity disabled")
class TestRealAnnualReportParity(unittest.TestCase):
    """Real cached Annual Reports, both pipelines, every base fact (revenue, PAT, equity, NCI, debt, ...) within 0.5%."""

    COMPANIES = ["ANURAS:2026", "TCS:2025", "MARUTI:2025", "ZEEL:2025", "BATAINDIA:2025"]

    def test_manual_and_automatic_pipelines_produce_the_same_facts(self):
        have = [c for c in self.COMPANIES if os.path.exists(os.path.join(ROOT, "cache", "ar_pdfs", c.replace(":", "_") + ".pdf"))]
        if len(have) < 2:
            self.skipTest("cached Annual Report PDFs are not available")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "parity.json")
            r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "pipeline_parity_probe.py"), "--out", out, *have],
                               capture_output=True, text=True, timeout=1500, cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            self.assertTrue(os.path.exists(out), r.stdout[-800:] + r.stderr[-800:])
            res = json.load(open(out, encoding="utf-8"))
        for c in have:
            with self.subTest(company=c):
                self.assertNotIn("error", res[c], res[c].get("error"))
                self.assertEqual(res[c]["diffs"], [], f"{c}: pipelines disagree")
                self.assertIsNotNone(res[c]["automatic"]["pat"], f"{c}: the automatic pipeline produced no PAT")

    def test_tcs_fy25_owners_pat_is_the_reported_figure_in_both_pipelines(self):
        if not os.path.exists(os.path.join(ROOT, "cache", "ar_pdfs", "TCS_2025.pdf")):
            self.skipTest("TCS_2025.pdf not cached")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "p.json")
            subprocess.run([sys.executable, os.path.join(ROOT, "tests", "pipeline_parity_probe.py"), "--out", out, "TCS:2025"],
                           capture_output=True, text=True, timeout=900, cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            res = json.load(open(out, encoding="utf-8"))["TCS:2025"]
        for mode in ("manual", "automatic"):
            self.assertAlmostEqual(res[mode]["pat"], 48553.0, places=1)        # was 1.0 (a note number next to a year)
            self.assertAlmostEqual(res[mode]["pat_total"], 48797.0, places=1)


if __name__ == "__main__":
    unittest.main()
