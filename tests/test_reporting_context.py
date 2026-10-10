"""Phase-2 non-TTM policy: every contract ratio declares it is built from the selected fiscal year's ANNUAL statements, names the
fiscal year and statement basis, and market-priced ratios say they use the latest quote (not the fiscal-year-end price)."""
import unittest

import tools.ratio_contract as rc
from tests.test_ratio_remediation import facts, MARKET


class TestReportingContext(unittest.TestCase):

    def test_every_computable_ratio_declares_annual_non_ttm_with_fy_and_basis(self):
        fs = facts()
        for key in sorted(rc.COMPUTABLE):
            rep = rc.compute_with_parents(key, fs, MARKET, {})["reporting"]
            self.assertEqual(rep["period_type"], "annual", key)
            self.assertIs(rep["ttm"], False, key)
            self.assertEqual(rep["fiscal_year_label"], rc.fiscal_year_label(fs.fiscal_year), key)
            self.assertEqual(rep["statement_basis"], fs.selection.selected_basis.lower(), key)

    def test_only_market_ratios_carry_price_provenance(self):
        fs = facts()
        for key in sorted(rc.COMPUTABLE):
            rep = rc.compute_with_parents(key, fs, MARKET, {})["reporting"]
            self.assertEqual("price" in rep, key in rc.MARKET_KEYS, key)
            if "price" in rep:
                self.assertIn("not the fiscal-year-end price", rep["price"]["note"])

    def test_fiscal_year_label(self):
        self.assertEqual(rc.fiscal_year_label(2026), "FY2025-26")
        self.assertEqual(rc.fiscal_year_label(2000), "FY1999-00")
        self.assertIsNone(rc.fiscal_year_label(None))


if __name__ == "__main__":
    unittest.main()
