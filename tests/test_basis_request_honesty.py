"""A request for one statement basis is never silently answered with the other: when the filing lacks the requested basis the FactSet says so
(selection reason, extras, and the `reporting` block every ratio carries), and the facts keep their real label."""
import unittest
from unittest.mock import patch

import tools.annual_report_financials as ar
import tools.fundamental_fact_store as ffs
import tools.ratio_contract as rc
from tests.test_ratio_remediation import parsed


def get(requested_consolidated, **over):
    ffs.clear_run_cache()
    with patch.object(ar, "_get_extracted_financials", return_value=parsed(**over)):
        return ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2026, consolidated=requested_consolidated)


class TestBasisRequestHonesty(unittest.TestCase):

    def test_standalone_request_answered_with_consolidated_is_flagged_and_labelled(self):
        fs = get(False, basis_used="consolidated")
        self.assertEqual(fs.selection.selected_basis, "CONSOLIDATED")
        self.assertIn("no readable standalone", fs.selection.selection_reason)
        self.assertEqual(fs.extras["basis_requested"], "standalone")
        rep = rc.compute_with_parents("current_ratio", fs, None, {})["reporting"]
        self.assertEqual(rep["statement_basis"], "consolidated")
        self.assertEqual(rep["basis_requested"], "standalone")
        self.assertIn("standalone statements were requested", rep["basis_note"].lower())

    def test_consolidated_request_answered_with_standalone_is_flagged(self):
        fs = get(True, basis_used="standalone")
        self.assertEqual(fs.selection.selected_basis, "STANDALONE")
        self.assertIn("no readable consolidated", fs.selection.selection_reason)

    def test_matching_basis_carries_no_fallback_note(self):
        fs = get(True, basis_used="consolidated")
        self.assertIsNone(fs.extras["basis_fallback"])
        self.assertNotIn("basis_note", rc.compute_with_parents("current_ratio", fs, None, {})["reporting"])


if __name__ == "__main__":
    unittest.main()
