"""Per-ratio formula oracle: every ratio's contract result must equal an INDEPENDENT hand-written implementation of the authoritative
registry formula (tests/ratio_audit_matrix.oracle) on a complete synthetic filing. This is the table-driven regression behind the
68-row audit matrix: one explicit entry per ratio, so a formula edit that drifts from the specification fails here by name."""
import unittest

import tools.fundamental_ratio_registry as reg
import tools.ratio_contract as rc
from tests.ratio_audit_matrix import oracle
from tests.test_ratio_remediation import facts, MARKET

# ratio_key -> why the oracle cannot compare it on the synthetic filing (everything else is compared numerically)
NOT_COMPARABLE_ON_SYNTHETIC = {
    "contribution_margin": "needs the Other-Expenses note / Direct Expenses line (variable-cost proxy) - covered by its own tests",
    "dscr": "needs gross principal repayments - covered by its own tests",
}

ORACLE_RATIO_KEYS = [r["ratio_key"] for r in reg.RATIOS if r["sr_no"] <= 57]


class TestEveryRatioMatchesTheIndependentFormula(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.fs = facts()
        cls.expected = oracle(cls.fs, MARKET)
        cls.results = rc.compute_all(cls.fs, MARKET)

    def test_each_ratio_1_to_57_matches_its_authoritative_formula(self):
        compared = []
        for key in ORACLE_RATIO_KEYS:
            if key in NOT_COMPARABLE_ON_SYNTHETIC:
                continue
            with self.subTest(ratio=key):
                self.assertIn(key, self.expected, f"{key}: no independent oracle formula")
                got = self.results[key].get("value_raw")
                self.assertIsNotNone(got, f"{key} was not computed on a complete filing: {self.results[key].get('reason')}")
                want = self.expected[key]
                self.assertAlmostEqual(got, want, delta=1e-9 * max(1.0, abs(want)), msg=key)
                compared.append(key)
        self.assertGreaterEqual(len(compared), 53)

    def test_registry_has_exactly_68_ratios_each_with_a_contract_or_provider_path(self):
        self.assertEqual(len(reg.RATIOS), 68)
        provider = {"net_interest_margin", "casa_ratio", "gross_npa_pct", "net_npa_pct", "provision_coverage_ratio",
                    "capital_adequacy_ratio", "credit_to_deposit_ratio", "cost_to_income_ratio", "beta", "promoter_pledge_pct",
                    "free_float_pct", "dscr_placeholder"}
        for r in reg.RATIOS:
            self.assertTrue(r["ratio_key"] in rc.COMPUTABLE or r["ratio_key"] in provider, r["ratio_key"])


class TestAuditMatrixArtefact(unittest.TestCase):
    """docs/ratio_audit_matrix_2026-10.* must account for all 68 ratios, contain no FAIL, and be regenerated for the current formula
    version (python tests/ratio_audit_matrix.py)."""

    def _load(self):
        import json
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return (json.load(open(os.path.join(root, "docs", "ratio_audit_verdicts_2026-10.json"), encoding="utf-8")),
                json.load(open(os.path.join(root, "docs", "ratio_audit_matrix_2026-10.json"), encoding="utf-8")),
                open(os.path.join(root, "docs", "ratio_audit_matrix_2026-10.md"), encoding="utf-8").read())

    def test_all_68_rows_present_with_a_verdict_and_no_fail(self):
        verdicts, matrix, md = self._load()
        keys = [r["ratio_key"] for r in reg.RATIOS]
        self.assertEqual(sorted(verdicts["verdicts"]), sorted(keys))
        self.assertEqual(len(matrix["rows"]), 68)
        self.assertEqual(sorted(r["sr_no"] for r in matrix["rows"]), list(range(1, 69)))
        for k, (v, reasons) in verdicts["verdicts"].items():
            self.assertIn(v, ("PASS", "NEEDS REVIEW"), f"{k}: {v} {reasons}")
        self.assertEqual(sum(verdicts["counts"].values()), 68)

    def test_every_row_records_the_twelve_audit_fields(self):
        _, matrix, md = self._load()
        for r in matrix["rows"]:
            for f in ("authoritative_formula", "implementation_formula", "perimeter", "period_basis", "tests_specific", "tests_generic",
                      "cross_company"):
                self.assertIn(f, r, f"{r['ratio_key']} lacks {f}")
            self.assertGreaterEqual(r["tests_specific"], 1, f"{r['ratio_key']} has no specific regression test")
        self.assertEqual(md.count("\n### "), 68)

    def test_matrix_was_generated_for_the_current_formula_version(self):
        _, _, md = self._load()
        self.assertIn(f"formula version {rc.FORMULA_VERSION}", md.splitlines()[0])

    def test_every_independent_recompute_that_exists_agreed(self):
        _, matrix, _ = self._load()
        for r in matrix["rows"]:
            if r.get("delta_rel") is not None:
                self.assertLessEqual(r["delta_rel"], 1e-6, r["ratio_key"])
