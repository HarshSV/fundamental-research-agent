"""The committed Screener benchmark must equal what the generator renders from the committed source-verification record (fails when stale),
and every difference must be classified with a cause."""
import json
import os
import unittest

from tests import screener_benchmark as sb

DOCS = os.path.join(sb.ROOT, "docs")


class TestScreenerBenchmarkArtefact(unittest.TestCase):

    def test_committed_files_are_not_stale(self):
        rows = sb.build()
        self.assertEqual(json.load(open(os.path.join(DOCS, "screener_benchmark_2026-10.json"), encoding="utf-8"))["rows"], rows)
        self.assertEqual(open(os.path.join(DOCS, "screener_benchmark_2026-10.md"), encoding="utf-8").read(), sb.render(rows))

    def test_every_difference_has_a_classified_cause_and_nothing_is_ttm(self):
        for r in sb.build():
            self.assertEqual(r["period_class"], "annual (non-TTM)")
            if not r["classification"].startswith("Matches"):
                self.assertIn(r["classification"], (sb.VALID, sb.EXTRACT, sb.REVIEW))
                self.assertTrue(r["root_cause"] and r["root_cause"] != "-")

    def test_all_fifteen_company_years_times_four_metrics(self):
        self.assertEqual(len(sb.build()), 15 * 4)


if __name__ == "__main__":
    unittest.main()
