"""Screener-aligned display names + the first-13 order: presentation only. Internal ids, formulas, values, statuses, provenance and
calculation breakdowns must be untouched."""
import copy
import inspect
import unittest

import tools.fundamental_ratio_registry as reg
from tools.document_analysis_engine import regroup_fundamental_rows
from tools.ratio_display import apply_display_names

FIRST_13 = [  # (internal sr_no, ratio_key, display name) in the required display order
    (2, "days_inventory_outstanding", "Inventory Days"), (4, "days_sales_outstanding", "Debtor Days"),
    (6, "days_payables_outstanding", "Days Payable"), (9, "cash_conversion_cycle", "Cash Conversion Cycle"),
    (15, "operating_profit_margin", "OPM %"), (18, "roe", "ROE %"), (19, "roce", "ROCE %"), (24, "pe_ratio", "Stock P/E"),
    (27, "dividend_yield", "Dividend Yield %"), (31, "days_working_capital", "Working Capital Days"),
    (36, "free_cash_flow", "Free Cash Flow"), (43, "effective_tax_rate", "Tax %"), (47, "dividend_payout_ratio", "Dividend Payout %"),
]


def stored_rows():
    """68 rows as the DB would hand them back: OLD labels, OLD order, a saved breakdown that mentions old parent names."""
    old_label = {sr: old for sr, old in ((2, "Days Inventory Outstanding (DOH)"), (4, "Days Sales Outstanding (DSO)"),
                                         (6, "Days Payables Outstanding (DPO)"), (15, "Operating Profit Margin (EBIT Basis)"),
                                         (18, "Return on Equity (ROE)"), (19, "Return on Capital Employed (ROCE)"),
                                         (24, "Price-to-Earnings (P/E)"), (27, "Dividend Yield"), (31, "Days Working Capital"),
                                         (36, "Free Cash Flow (FCF)"), (43, "Effective Tax Rate"), (47, "Dividend Payout Ratio"))}
    rows = []
    for r in reg.RATIOS:
        md = {"name": "_metadata", "formula_version": "x", "status_detail": "verified"}
        if r["sr_no"] == 9:
            md["breakdown"] = {"formula": "Days Sales Outstanding (DSO) + Days Inventory Outstanding (DOH) \u2212 Days Payables Outstanding (DPO)",
                               "parents": [{"ratio_key": "days_sales_outstanding", "label": "Days Sales Outstanding (DSO)"}],
                               "inputs": [{"name": "Effective Tax Rate", "value_raw": 0.25}]}
            md["reason"] = "Days Inventory Outstanding (DOH) is not_disclosed: x"
        rows.append({"ratio_key": r["ratio_key"], "label": old_label.get(r["sr_no"], r["label"]), "category": "Liquidity",
                     "value": float(r["sr_no"]), "unit": "x", "status": "verified", "formula": r["formula"], "inputs": [md]})
    return list(reversed(rows))


class TestRegistryDefinition(unittest.TestCase):
    def test_the_13_names_priorities_and_internal_ids(self):
        got = [(r["sr_no"], r["ratio_key"], r["label"]) for r in reg.PRIORITY_RATIOS]
        self.assertEqual(got, FIRST_13)
        self.assertEqual([r["display_priority"] for r in reg.PRIORITY_RATIOS], list(range(1, 14)))

    def test_68_ratios_each_exactly_once_and_internal_ids_unchanged(self):
        self.assertEqual(len(reg.RATIOS), 68)
        self.assertEqual([r["sr_no"] for r in reg.RATIOS], list(range(1, 69)))
        self.assertEqual(len({r["ratio_key"] for r in reg.RATIOS}), 68)
        self.assertEqual(sum(1 for r in reg.RATIOS if r.get("display_priority")), 13)

    def test_other_55_labels_are_untouched(self):
        for r in reg.RATIOS:
            if not r.get("display_priority"):
                self.assertNotIn(r["label"], reg.LEGACY_LABELS)
                self.assertNotIn(r["label"], reg.LEGACY_LABELS.values())
        self.assertEqual(reg.BY_SR_NO[1]["label"], "Inventory Turnover")
        self.assertEqual(reg.BY_SR_NO[10]["label"], "Current Ratio")


class TestReadPath(unittest.TestCase):
    def test_first_13_in_order_then_the_rest_in_the_previous_order(self):
        out = regroup_fundamental_rows(stored_rows())
        self.assertEqual(len(out), 68)
        self.assertEqual([(r["sr_no"], r["ratio_key"], r["label"]) for r in out[:13]], FIRST_13)
        self.assertEqual([r["display_priority"] for r in out[:13]], list(range(1, 14)))
        rest = out[13:]
        self.assertEqual(len(rest), 55)
        self.assertTrue(all(r["display_priority"] is None for r in rest))
        first = {n for n, _, _ in FIRST_13}
        expected = [r["sr_no"] for c in reg.CATEGORY_ORDER for r in reg.RATIOS if r["category"] == c and r["sr_no"] not in first]
        self.assertEqual([r["sr_no"] for r in rest], expected)           # previous relative order preserved
        self.assertEqual(len({r["ratio_key"] for r in out}), 68)         # every ratio exactly once

    def test_values_status_ids_and_provenance_are_untouched(self):
        rows = stored_rows()
        before = {r["ratio_key"]: copy.deepcopy(r) for r in rows}
        for r in regroup_fundamental_rows(rows):
            b = before[r["ratio_key"]]
            for k in ("ratio_key", "value", "unit", "status", "formula"):
                self.assertEqual(r[k], b[k], (r["ratio_key"], k))
            self.assertEqual(r["sr_no"], reg.BY_RATIO_KEY[r["ratio_key"]]["sr_no"])

    def test_saved_text_never_shows_a_retired_name_but_input_names_are_kept(self):
        ccc = next(r for r in regroup_fundamental_rows(stored_rows()) if r["ratio_key"] == "cash_conversion_cycle")
        md = ccc["inputs"][0]
        bd = md["breakdown"]
        self.assertEqual(bd["formula"], "Debtor Days + Inventory Days \u2212 Days Payable")
        self.assertEqual(bd["parents"][0]["label"], "Debtor Days")
        self.assertEqual(bd["parents"][0]["ratio_key"], "days_sales_outstanding")       # identity of the parent unchanged
        self.assertTrue(md["reason"].startswith("Inventory Days is not_disclosed"))
        self.assertEqual(bd["inputs"][0]["name"], "Effective Tax Rate")                 # a statement component, not a ratio name

    def test_apply_is_idempotent_and_ignores_unknown_keys(self):
        r = stored_rows()[0]
        once = apply_display_names(r)
        self.assertEqual(apply_display_names(once), once)
        self.assertIsNone(apply_display_names({"ratio_key": "nope", "label": "x"})["display_priority"])

    def test_dividend_yield_is_not_double_suffixed(self):
        rows = [r for r in regroup_fundamental_rows(stored_rows()) if r["ratio_key"] == "dividend_yield"]
        self.assertEqual(rows[0]["label"], "Dividend Yield %")


class TestNoCalculationCodeChanged(unittest.TestCase):
    def test_display_module_has_no_arithmetic_on_ratio_values(self):
        import tools.ratio_display as rd
        src = inspect.getsource(rd)
        for forbidden in ("value_raw", "compute_ratio", "FORMULA_VERSION", "status_detail"):
            self.assertNotIn(forbidden, src, forbidden)


if __name__ == "__main__":
    unittest.main()
