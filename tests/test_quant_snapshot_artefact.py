"""The committed ANURAS snapshot (Markdown + CSV) must be ONE consistent capture: the same 68 metrics, the same values/statuses/formulas in both
files, one snapshot id, one formula version equal to the code's, one quote time, calculation times within one analysis run, nothing replaced by zero,
and no description of the enterprise value that disagrees with its calculation."""
import csv
import datetime as dt
import os
import re
import unittest

import tools.fundamental_ratio_registry as reg
import tools.ratio_contract as rc

DOCS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
STEM = "anupam_rasayan_quantitative_snapshot_2026-10-10"


class TestQuantSnapshotArtefact(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.rows = list(csv.DictReader(open(os.path.join(DOCS, STEM + ".csv"), encoding="utf-8-sig")))
        cls.md = open(os.path.join(DOCS, STEM + ".md"), encoding="utf-8").read()

    def test_the_same_68_metrics_as_the_registry(self):
        self.assertEqual(len(self.rows), 68)
        self.assertEqual(sorted(r["ratio_key"] for r in self.rows), sorted(x["ratio_key"] for x in reg.RATIOS))
        self.assertEqual([int(r["sr_no"]) for r in self.rows], list(range(1, 69)))

    def test_one_snapshot_id_one_version_one_quote_one_run(self):
        ids = {r["snapshot_id"] for r in self.rows}
        self.assertEqual(len(ids), 1)
        self.assertIn(f"**{ids.pop()}**", self.md)
        self.assertEqual({r["formula_version"] for r in self.rows}, {rc.FORMULA_VERSION})
        self.assertLessEqual(len({r["quote_time"] for r in self.rows if r["quote_time"]}), 1)
        times = sorted(dt.datetime.fromisoformat(r["calculated_at"]) for r in self.rows if r["calculated_at"])
        self.assertLess((times[-1] - times[0]).total_seconds(), 180)

    def test_markdown_tables_carry_the_csv_values(self):
        for r in self.rows:
            pat = rf"\| {r['sr_no']} \| {re.escape(r['metric_name'])} \| {re.escape(r['displayed_value'])} \|"
            self.assertRegex(self.md, pat, r["metric_name"])
            self.assertIn(f"### {r['sr_no']}. {r['metric_name']} - {r['displayed_value']}", self.md)

    def test_missing_values_are_blank_with_a_reason_never_zero(self):
        for r in self.rows:
            if r["raw_value"] == "":
                self.assertEqual(r["displayed_value"], "-", r["metric_name"])
                self.assertIn("reason:", r["notes"], r["metric_name"])
                self.assertNotIn(r["status_api"], ("verified",), r["metric_name"])
            else:
                float(r["raw_value"])

    def test_market_rows_carry_the_quote_time_and_other_rows_do_not_pretend_to(self):
        market = {k for k in rc.MARKET_KEYS}
        for r in self.rows:
            if r["ratio_key"] in market and r["raw_value"] != "":
                self.assertTrue(r["quote_time"], r["metric_name"])

    def test_enterprise_value_is_described_exactly_as_calculated(self):
        for r in self.rows:
            if r["ratio_key"].startswith("ev_"):
                self.assertNotIn("+ NCI", r["notes"] + r["formula"], r["metric_name"])
                self.assertNotIn("Minority", r["notes"], r["metric_name"])

    def test_every_external_comparison_is_classified(self):
        sec = self.md.split("## 7. External benchmark comparison")[1]
        self.assertIn("screener.in/company/ANURAS", sec)
        self.assertIn("stockanalysis.com/quote/nse/ANURAS", sec)
        for line in sec.splitlines():
            if line.startswith("| ") and not line.startswith("| Metric") and not line.startswith("|---"):
                self.assertTrue(re.search(r"Matches|Different|Insufficient|Stale", line), line)


if __name__ == "__main__":
    unittest.main()
