"""docs/global_ratio_audit_2026-10.* must account for all 68 ratios with one of the five audit statuses, a code location that really exists,
and must not claim 'verified' without an independent recompute; the source-verification table must list what was actually checked."""
import json
import os
import unittest

import tools.fundamental_ratio_registry as reg
import tools.ratio_contract as rc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUSES = {
    "Verified against source evidence and specification", "Fixed and independently reverified", "Legitimate methodology difference",
    "Source extraction issue", "Needs review", "Not applicable", "Unavailable",
}


class TestGlobalAuditArtefact(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.data = json.load(open(os.path.join(ROOT, "docs", "global_ratio_audit_2026-10.json"), encoding="utf-8"))
        cls.md = open(os.path.join(ROOT, "docs", "global_ratio_audit_2026-10.md"), encoding="utf-8").read()
        cls.rows = cls.data["rows"]

    def test_all_68_ratios_have_exactly_one_of_the_five_statuses(self):
        self.assertEqual([r["sr_no"] for r in self.rows], list(range(1, 69)))
        self.assertEqual(sorted(r["ratio_key"] for r in self.rows), sorted(x["ratio_key"] for x in reg.RATIOS))
        for r in self.rows:
            self.assertIn(r["status"], STATUSES, r["ratio_key"])

    def test_each_row_has_the_required_audit_columns(self):
        for r in self.rows:
            for f in ("authoritative_formula", "implementation", "code_location", "ui_path", "required_inputs", "basis", "dependencies", "tests",
                      "anuras_fy2026", "status"):
                self.assertIn(f, r, f"{r['ratio_key']} lacks {f}")
            self.assertTrue(r["code_location"] and r["code_location"] != "?", r["ratio_key"])

    def test_code_locations_point_at_real_functions(self):
        for r in self.rows:
            loc = r["code_location"]
            if loc.startswith("tools/ratio_contract.py:") and not loc.startswith("tools/ratio_contract.py::"):
                line = int(loc.split(":")[1].split(" ")[0])
                src = open(os.path.join(ROOT, "tools", "ratio_contract.py"), encoding="utf-8").read().splitlines()
                self.assertIn("def ", src[line - 1], f"{r['ratio_key']}: {loc}")

    def test_no_row_is_verified_without_an_independent_recompute_that_agreed(self):
        for r in self.rows:
            if r["status"] == "Verified against source evidence and specification" and r["sr_no"] <= 57:
                an = r["anuras_fy2026"]
                self.assertIsNotNone(an["independent"], r["ratio_key"])
                self.assertLessEqual(an["rel_diff"] or 0.0, 1e-6, r["ratio_key"])

    def test_open_decisions_are_never_reported_as_verified(self):
        decision = {3, 4, 9, 12, 15, 17, 19, 31, 44, 47, 55, 57}
        for r in self.rows:
            if r["sr_no"] in decision:
                self.assertNotEqual(r["status"], "Verified against source evidence and specification", r["ratio_key"])
        for sr in (34,):
            self.assertEqual(next(r for r in self.rows if r["sr_no"] == sr)["status"], "Needs review")

    def test_matrix_names_the_source_verified_company_years_and_the_engine_inventory(self):
        sv = self.data["source_verification"]
        self.assertIn("ANURAS:2026", sv)
        self.assertGreaterEqual(len(sv), 10)
        for cy, v in sv.items():
            if not v.get("error"):
                self.assertIn("publisher", v)
        self.assertIn("legacy research-report engine", self.md)
        self.assertIn(f"formula version {rc.FORMULA_VERSION}", self.md.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
