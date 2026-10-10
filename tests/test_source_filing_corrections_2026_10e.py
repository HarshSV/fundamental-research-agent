"""Real-filing regressions for the 2026-10e corrections (skipped when the annual-report PDF is not cached on this machine).
Expected values are the figures PRINTED in the filings (read by hand from the statements), not outputs of the pipeline:
  L&T FY2025 consolidated balance sheet: Borrowings 57,503.34 (non-current) + 35,861.30 (current) + 'Current maturities of long term
      borrowings' 36,194.70 + Lease liabilities 2,265.24 + 584.34 = 132,408.92 (the maturities row was dropped before: 96,214.22).
  Titan FY2025 consolidated: Total debt 20,777 incl. 'Gold on loan' 7,810 (interest-bearing, 1.5-5.5% p.a.).
  Bharti Airtel consolidated tax: FY2026 current 78,812 + deferred 34,687 = 113,499 mn (the header-only 'Tax expense / (credit)' line
      returned the current-tax row, 78,812); FY2025 current 41,121 + deferred (31,949) = 9,172 mn.
  ITC FY2025: revenue 81,612.78 is gross of the Excise duty expense line 6,289.44 -> net sales 75,323.34."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _facts(sym, fy):
    if not os.path.exists(os.path.join(ROOT, "cache", "ar_pdfs", f"{sym}_{fy}.pdf")):
        raise unittest.SkipTest(f"{sym}_{fy}.pdf not cached")
    from tools.fundamental_fact_store import get_canonical_facts
    return get_canonical_facts(sym, sym, fy)


class TestSourceFilingCorrections(unittest.TestCase):

    def test_lt_total_debt_includes_current_maturities_of_long_term_borrowings(self):
        fs = _facts("LT", 2025)
        self.assertAlmostEqual(fs.get("total_debt").value, 57503.34 + 35861.30 + 36194.70 + 2265.24 + 584.34, delta=0.05)

    def test_titan_total_debt_includes_gold_on_loan(self):
        fs = _facts("TITAN", 2025)
        self.assertAlmostEqual(fs.get("total_debt").value, 20777.0, delta=1.0)

    def test_bharti_tax_expense_is_current_plus_deferred_not_the_current_row(self):
        fs26, fs25 = _facts("BHARTIARTL", 2026), _facts("BHARTIARTL", 2025)
        self.assertAlmostEqual(fs26.get("tax_expense").value, (78812 + 34687) / 10.0, delta=0.05)
        self.assertAlmostEqual(fs26.get("tax_expense").value / fs26.get("pbt").value * 100, 113499 / 451727 * 100, places=2)
        self.assertAlmostEqual(fs25.get("tax_expense").value, 9172 / 10.0, delta=0.05)

    def test_itc_net_sales_deducts_the_excise_duty_expense_line_only(self):
        fs = _facts("ITC", 2025)
        self.assertAlmostEqual(fs.get("revenue").value, 81612.78, places=2)
        self.assertAlmostEqual(fs.get("net_sales").value, 81612.78 - 6289.44, places=2)

    def test_hul_other_operating_revenue_is_not_deducted(self):
        fs = _facts("HINDUNILVR", 2025)
        self.assertEqual(fs.get("net_sales").value, fs.get("revenue").value)


def _facts_basis(sym, fy, consolidated):
    if not os.path.exists(os.path.join(ROOT, "cache", "ar_pdfs", f"{sym}_{fy}.pdf")):
        raise unittest.SkipTest(f"{sym}_{fy}.pdf not cached")
    from tools.fundamental_fact_store import clear_run_cache, get_canonical_facts
    from tools.manual_mode import manual_mode
    clear_run_cache()
    with manual_mode():                                   # ANURAS is an uploaded report: the manual workflow is its real path
        return get_canonical_facts(sym, sym, fy, consolidated=consolidated)


class TestFinalAuditFilings(unittest.TestCase):
    """2026.10.18.  Printed figures: L&T consolidated balance sheet 'Sub-total - Current assets' 245,184.27 / 217,583.24 and 'Sub-total - Current
    liabilities' 201,970.90 / 177,109.46 (the caption is 'Sub-total', not 'Total'); ANURAS consolidated Other-equity note 'Retained Earnings'
    closing 9,956.92 mn (= 995.692 Cr; the balance sheet's total Other equity is 31,879.90 mn); ANURAS standalone statements (INR crore):
    revenue 1,675.567, inventory 1,398.020, total current assets 2,815.795, total current liabilities 2,177.889."""

    def test_lt_current_assets_and_liabilities_use_the_sub_total_captions(self):
        fs = _facts("LT", 2025)
        self.assertAlmostEqual(fs.get("total_current_assets").value, 245184.27, places=2)
        self.assertAlmostEqual(fs.get("total_current_assets").prior_value, 217583.24, places=2)
        self.assertAlmostEqual(fs.get("total_current_liabilities").value, 201970.90, places=2)
        self.assertEqual(fs.extras["integrity_failures"], [])

    def test_anuras_retained_earnings_is_the_note_line_not_total_other_equity(self):
        fs = _facts_basis("ANURAS", 2026, True)
        re_ = fs.get("retained_earnings")
        self.assertAlmostEqual(re_.value, 995.692, places=3)
        self.assertEqual((re_.status, re_.source_tag), ("VERIFIED", "retained_earnings(note)"))
        self.assertAlmostEqual(fs.extras["retained_earnings_proxy_total_cr"], 3187.99, places=2)

    def test_standalone_request_is_never_silently_answered_with_consolidated_facts(self):
        """ANURAS's integrated report words its standalone P&L 'Statement of Standalone Profit and Loss'; the statement locator does not read that
        layout, so a standalone request cannot be served. It must say so (basis label + note) and keep the figures labelled consolidated - it
        must not present consolidated numbers as standalone. (Printed standalone figures - revenue 1,675.567, inventory 1,398.020, current assets
        2,815.795, current liabilities 2,177.889 - are verified separately in tests/test_anuras_fy2026_source_audit.py.)"""
        fs = _facts_basis("ANURAS", 2026, False)
        self.assertEqual(fs.selection.selected_basis, "CONSOLIDATED")
        self.assertIn("no readable standalone", fs.extras["basis_fallback"])
        self.assertEqual(fs.extras["basis_requested"], "standalone")
        self.assertAlmostEqual(fs.get("revenue").value, 2365.455, places=2)                  # consolidated, labelled as such
        self.assertNotAlmostEqual(fs.get("revenue").value, 1675.567, places=1)
        cons = _facts_basis("ANURAS", 2026, True)
        self.assertIsNone(cons.extras["basis_fallback"])
        self.assertAlmostEqual(cons.get("revenue").value, 2365.455, places=2)

    def test_tcs_second_company_regression(self):
        fs = _facts("TCS", 2026)
        self.assertEqual(fs.selection.selected_basis, "CONSOLIDATED")
        self.assertAlmostEqual(fs.get("total_debt").value, 11283.0, delta=1.0)           # Screener borrowings 11,283 (earlier extraction fix)
        self.assertGreater(fs.get("net_sales").value, 250000)
        self.assertEqual(fs.get("net_sales").value, fs.get("revenue").value)           # no excise line: net sales IS reported revenue


if __name__ == "__main__":
    unittest.main()
