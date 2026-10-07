"""The 8-category / 68-ratio Fundamental Ratios classification: registry is the
single source of truth; read-time regrouping is presentation-only; the
frontend's category order must equal the registry's."""
import re
import unittest
from pathlib import Path

from tools.fundamental_ratio_registry import RATIOS, CATEGORY_ORDER, DEFAULT_VISIBLE_CATEGORIES
from tools.document_analysis_engine import regroup_fundamental_rows

SPEC = {
    "Balance Sheet": [10, 11, 12, 13, 20, 21, 23, 32, 46],
    "P&L": [14, 15, 16, 22, 43, 44, 45],
    "P&L + Balance Sheet": [1, 2, 3, 4, 5, 6, 7, 8, 9, 17, 18, 19, 30, 31, 33, 42],
    "Cash Flow": [34, 35, 36, 38, 39, 40, 41],
    "Multi-source / Derived": [47, 48, 49, 55, 56, 57],
    "Market / Valuation": [24, 25, 26, 27, 28, 29, 37, 50, 51, 52, 53, 54],
    "Banking-specific": [58, 59, 60, 61, 62, 63, 64, 65],
    "Market / Shareholding": [66, 67, 68],
}


class TestRatioCategories(unittest.TestCase):
    def test_registry_matches_authoritative_spec_exactly(self):
        got = {c: [r["sr_no"] for r in RATIOS if r["category"] == c] for c in CATEGORY_ORDER}
        self.assertEqual(got, SPEC)
        self.assertEqual(list(SPEC), CATEGORY_ORDER)
        self.assertEqual(sum(len(v) for v in got.values()), 68)
        self.assertEqual(len({r["sr_no"] for r in RATIOS}), 68)        # each ratio exactly once

    def test_first_view_is_16_and_rest_is_52(self):
        first = [r for r in RATIOS if r["category"] in DEFAULT_VISIBLE_CATEGORIES]
        self.assertEqual((DEFAULT_VISIBLE_CATEGORIES, len(first), 68 - len(first)),
                         (["Balance Sheet", "P&L"], 16, 52))

    def test_regroup_relabels_stale_rows_without_touching_values(self):
        stale = [{"ratio_key": r["ratio_key"], "category": "Liquidity", "value": i, "status": "verified"}
                 for i, r in enumerate(reversed(RATIOS))]
        out = regroup_fundamental_rows(stale)
        self.assertEqual([r["sr_no"] for r in out],
                         [n for c in CATEGORY_ORDER for n in SPEC[c]])           # category order, then Sr No
        by_key = {r["ratio_key"]: r for r in out}
        for s in stale:
            self.assertEqual((by_key[s["ratio_key"]]["value"], by_key[s["ratio_key"]]["status"]),
                             (s["value"], s["status"]))

    def test_frontend_order_equals_registry_order(self):
        js = (Path(__file__).resolve().parents[1] / "frontend/src/lib/ratioCategories.js").read_text(encoding="utf-8")
        block = re.search(r"CATEGORY_ORDER = \[(.*?)\];", js, re.S).group(1)
        self.assertEqual(re.findall(r"'([^']+)'", block), CATEGORY_ORDER)


if __name__ == "__main__":
    unittest.main()
