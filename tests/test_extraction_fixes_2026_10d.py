"""Generic extraction defects found by the cross-company source verification (docs/source_verification_2026-10.json):
 * borrowings / lease liabilities read from the printed balance-sheet ROWS (note references printed as decimals, list dashes, a thousands
   comma the PDF dropped - resolved by the balance-sheet identity);
 * the tax block 'on exceptional items' no longer shadows the real tax expense; PBT caption variant;
 * unit-converted figures keep full precision.
Synthetic one-page PDFs for the row reader; real cached reports (skipped if absent / NAVRIST_SKIP_SLOW_TESTS) for the end-to-end figures,
each checked against the figure printed in that report and, where it exists, Screener's published borrowings."""
import os
import unittest

import fitz

import tools.annual_report_financials as ar

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _doc(header, rows):
    """One PDF page: a header line then one row per line (words laid out left to right)."""
    d = fitz.open()
    p = d.new_page(width=600, height=60 + 14 * (len(rows) + 3))
    p.insert_text((20, 20), header, fontsize=8)
    for i, r in enumerate(rows):
        x = 20
        for tok in r.split(" "):
            p.insert_text((x, 40 + 14 * i), tok, fontsize=8)
            x += 8 + 5.2 * len(tok)
    return d


class TestBalanceSheetRowReader(unittest.TestCase):

    def test_decimal_note_reference_is_not_an_amount(self):
        d = _doc("(In ` crore) Particulars Note As at March 31, 2026 2025",
                 ["Non-current liabilities", "Lease liabilities 2.21 6,016 5,772", "Other non-current liabilities 2.15 561 215",
                  "Total non-current liabilities 10,348 9,850", "Current liabilities", "Lease liabilities 2.21 3,160 2,455",
                  "Trade payables 2.14 4,744 4,164", "Total current liabilities 52,322 42,850"])
        r = ar._bs_row_debt_items(d, 0)
        self.assertEqual(r[("lease", "nc")], (6016.0, 5772.0))
        self.assertEqual(r[("lease", "cur")], (3160.0, 2455.0))

    def test_a_dropped_thousands_comma_is_resolved_by_the_section_total(self):
        # "9 453" is 9,453: the rows only add up to the printed subtotal 12,980 with that reading
        d = _doc("(H crore) Note As at 31 March 2026 2025",
                 ["Non-current liabilities", "Class B preference shares 8(n) 126 -", "Lease liabilities 9 453 7,838",
                  "Other financial liabilities 8(h) 588 680", "Employee benefit obligations 13 961 841",
                  "Deferred tax liabilities (net) 17 1,205 980", "Unearned and deferred revenue 647 518",
                  "Total non-current liabilities 12,980 10,857"])
        self.assertEqual(ar._bs_row_debt_items(d, 0)[("lease", "nc")], (9453.0, 7838.0))

    def test_a_small_amount_stays_small_when_the_section_adds_up_without_merging(self):
        d = _doc("(H crore) Note As at 31 March 2026 2025",
                 ["Non-current liabilities", "Lease liabilities 9 453 7,838", "Other liabilities 1,000 900", "Total non-current liabilities 1,453 8,738"])
        self.assertEqual(ar._bs_row_debt_items(d, 0)[("lease", "nc")], (453.0, 7838.0))      # the printed total proves 453

    def test_list_dash_label_and_million_unit(self):
        d = _doc("(All amounts are in millions of Indian Rupee) Notes March 31, 2025 2024",
                 ["Non-current liabilities", "- Borrowings 18 1,048,638 1,309,626", "- Lease liabilities 36 556,701 539,271",
                  "Current liabilities", "- Borrowings 18 434,485 209,539", "- Lease liabilities 36 96,597 97,487", "Total liabilities 3,608,927 3,389,671"])
        r = ar._bs_row_debt_items(d, 0)
        self.assertAlmostEqual(r[("borrow", "nc")][0], 104863.8, places=1)
        self.assertAlmostEqual(r[("lease", "nc")][0], 55670.1, places=1)
        self.assertAlmostEqual(r[("borrow", "cur")][0], 43448.5, places=1)
        self.assertAlmostEqual(r[("lease", "cur")][0], 9659.7, places=1)

    def test_rows_outside_the_liability_sections_are_ignored(self):
        d = _doc("(In crore)", ["Assets", "Lease liabilities 5 100 90", "Non-current liabilities", "Borrowings 7 200 180"])
        r = ar._bs_row_debt_items(d, 0)
        self.assertNotIn(("lease", "nc"), r)
        self.assertEqual(r[("borrow", "nc")], (200.0, 180.0))

    def test_row_figure_replaces_a_missing_or_disagreeing_text_figure_only(self):
        self.assertEqual(ar._prefer_row_read(None, (10.0, 9.0)), (10.0, 9.0))
        self.assertEqual(ar._prefer_row_read((4.42, None), (9176.0, 7627.0)), (9176.0, 7627.0))           # Infosys 4.42 -> 9,176
        self.assertEqual(ar._prefer_row_read((100.0, 90.0), (101.0, 91.0)), (100.0, 90.0))                 # within 2%: text kept
        self.assertEqual(ar._prefer_row_read((100.0, 90.0), None), (100.0, 90.0))
        self.assertEqual(ar._prefer_row_read((100.0, 90.0), (1e9, 1.0), ceiling=5000.0), (100.0, 90.0))   # impossible row figure ignored


class TestUnitConversionKeepsPrecision(unittest.TestCase):

    def test_million_to_crore_keeps_the_third_decimal(self):
        self.assertEqual(ar._scale((34880.26, 34784.13), 0.1), (3488.026, 3478.413))      # was rounded to (3488.03, 3478.41)
        self.assertEqual(ar._scale(None, 0.1), None)
        self.assertEqual(ar._scale((5.0, None), 0.1), (0.5, None))


def _skip_real():
    return os.environ.get("NAVRIST_SKIP_SLOW_TESTS")


@unittest.skipIf(_skip_real(), "slow real-document checks disabled")
class TestRealReportFigures(unittest.TestCase):
    """End-to-end on the cached reports: Total Debt equals what the filing prints (borrowings + lease liabilities) and Screener's borrowings."""

    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        import ratio_regression_probe as P
        orig = ar._get_extracted_financials_impl
        P._setup(ROOT)
        ar._get_extracted_financials_impl = orig
        cls.P = P

    def _facts(self, sym, fy):
        if not os.path.exists(os.path.join(ROOT, "cache", "ar_pdfs", f"{sym}_{fy}.pdf")):
            self.skipTest(f"{sym}_{fy}.pdf not cached")
        from tools.fundamental_fact_store import get_canonical_facts, clear_run_cache
        clear_run_cache()
        return get_canonical_facts(sym, sym, fy)

    def test_infosys_fy26_debt_is_its_lease_liabilities(self):
        fs = self._facts("INFY", 2026)
        self.assertAlmostEqual(fs.get("total_debt").value, 6016 + 3160, delta=1.0)           # printed 6,016 + 3,160; Screener 9,176 (was 4.42)

    def test_tcs_fy26_non_current_leases_include_the_dropped_comma_figure(self):
        fs = self._facts("TCS", 2026)
        self.assertAlmostEqual(fs.get("total_debt").value, 9453 + 1830, delta=1.0)           # Screener 11,283 (was 2,283)

    def test_bharti_airtel_borrowings_and_leases_on_a_side_by_side_page(self):
        fs = self._facts("BHARTIARTL", 2025)
        self.assertAlmostEqual(fs.get("total_debt").value, (1048638 + 556701 + 434485 + 96597) / 10, delta=1.0)   # printed, INR million; Screener 213,642

    def test_lt_tax_expense_is_the_main_block_not_the_exceptional_items_block(self):
        fs = self._facts("LT", 2025)
        self.assertAlmostEqual(fs.get("tax_expense").value, 5891.40, delta=0.05)              # was 20.83 (tax on exceptional items)

    def test_reliance_pbt_caption_variant_is_read(self):
        fs = self._facts("RELIANCE", 2025)
        self.assertAlmostEqual(fs.get("pbt").value, 106017.0, delta=1.0)
        self.assertIsNotNone(fs.get("tax_expense").value)


if __name__ == "__main__":
    unittest.main()
