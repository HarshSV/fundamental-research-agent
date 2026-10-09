"""Edge cases applied to EVERY computable ratio (generic, no company data):
zero / negative inputs never raise or produce inf/NaN; unavailable opening balances fall back FLAGGED (or are withheld), never silently;
a missing input is withheld or flagged, never turned into a different 'verified' number; negative earnings / equity are `not_meaningful`
where the ratio would otherwise be misleading."""
import dataclasses
import math
import unittest

import tools.ratio_breakdown as rb
import tools.ratio_contract as rc
from tests.test_ratio_remediation import facts, MARKET

ALL_KEYS = sorted(rc.COMPUTABLE)
# facts that may legitimately be absent with no effect on the value (optional components)
OPTIONAL = {"capex_intangible_purchase", "capex_disposal_proceeds", "lease_repayment", "retained_earnings", "nci", "equity_full",
            "borrowings_repayment", "interest_paid"}


def _reads(key):
    fs = facts()
    cls = type(fs)
    orig = cls.get
    seen = set()

    def spy(self, k, *a, **kw):
        seen.add(k)
        return orig(self, k, *a, **kw)
    ob = rb.build_breakdown
    cls.get, rb.build_breakdown = spy, (lambda *a, **k: None)
    try:
        rc.compute_with_parents(key, fs, MARKET, {})
    finally:
        cls.get, rb.build_breakdown = orig, ob
    return sorted(seen)


def _with(fs, fact_key, **changes):
    f = fs.facts.get(fact_key)
    if f is None or not hasattr(f, "value"):
        return None
    d = dict(fs.facts)
    d[fact_key] = dataclasses.replace(f, **changes)
    return dataclasses.replace(fs, facts=d)


def _finite_or_none(v):
    return v is None or (isinstance(v, (int, float)) and math.isfinite(v))


class TestZeroAndNegativeInputsNeverBreakARatio(unittest.TestCase):

    def test_zeroing_any_input_never_raises_or_yields_inf_nan(self):
        for key in ALL_KEYS:
            for k in _reads(key):
                fs0 = facts()
                fs = _with(fs0, k, value=0.0, prior_value=0.0)
                if fs is None:
                    continue
                with self.subTest(ratio=key, zeroed=k):
                    r = rc.compute_with_parents(key, fs, MARKET, {})
                    self.assertTrue(_finite_or_none(r.get("value_raw")), r.get("value_raw"))

    def test_negating_any_input_never_raises_or_yields_inf_nan(self):
        for key in ALL_KEYS:
            for k in _reads(key):
                fs0 = facts()
                f = fs0.facts.get(k)
                if f is None or not hasattr(f, "value") or not isinstance(f.value, (int, float)):
                    continue
                fs = _with(fs0, k, value=-abs(f.value), prior_value=(-abs(f.prior_value) if f.prior_value is not None else None))
                with self.subTest(ratio=key, negated=k):
                    r = rc.compute_with_parents(key, fs, MARKET, {})
                    self.assertTrue(_finite_or_none(r.get("value_raw")), r.get("value_raw"))


class TestMissingInputsAreWithheldOrFlagged(unittest.TestCase):

    def test_blanking_an_input_never_changes_a_verified_value(self):
        for key in ALL_KEYS:
            base = rc.compute_with_parents(key, facts(), MARKET, {}).get("value_raw")
            for k in _reads(key):
                if k in OPTIONAL:
                    continue
                fs = _with(facts(), k, value=None, prior_value=None, status="NOT_DISCLOSED")
                if fs is None:
                    continue
                with self.subTest(ratio=key, blank=k):
                    r = rc.compute_with_parents(key, fs, MARKET, {})
                    v = r.get("value_raw")
                    same = v is not None and base is not None and abs(v - base) <= 1e-9 * max(1.0, abs(base))
                    withheld = v is None
                    flagged = bool(r.get("estimated")) or r.get("status") != "verified"
                    self.assertTrue(withheld or same or flagged, f"value moved {base} -> {v} while still verified")

    def test_unavailable_opening_balance_falls_back_flagged_or_is_withheld(self):
        average_based = [k for k in ALL_KEYS if "average" in (rc.SPEC.get(k, {}).get("basis") or "")]
        self.assertGreaterEqual(len(average_based), 8)
        for key in average_based:
            for k in _reads(key):
                f = facts().facts.get(k)
                if f is None or not hasattr(f, "prior_value") or f.prior_value is None:
                    continue
                fs = _with(facts(), k, prior_value=None)
                with self.subTest(ratio=key, no_opening_for=k):
                    r = rc.compute_with_parents(key, fs, MARKET, {})
                    base = rc.compute_with_parents(key, facts(), MARKET, {}).get("value_raw")
                    v = r.get("value_raw")
                    if v is None or (base is not None and abs(v - base) <= 1e-9 * max(1.0, abs(base))):
                        continue
                    self.assertTrue(r.get("estimated") or r.get("status") != "verified",
                                    f"{key}: closing balance used in place of the average without a flag")


class TestNegativeEarningsAndEquity(unittest.TestCase):

    def _neg(self, **parsed_over):
        """parsed-level overrides: the fact store re-derives EPS, BVPS, EBITDA, working capital ... consistently."""
        return rc.compute_all(facts(**parsed_over), MARKET)

    def test_negative_eps_makes_price_multiples_not_meaningful(self):
        r = self._neg(eps_owners=(-5.0, 8.0))
        for key in ("pe_ratio", "graham_number"):
            self.assertIsNone(r[key]["value_raw"], key)
            self.assertEqual(r[key]["status"], "not_meaningful", key)
        self.assertIsNone(r["peg_ratio"]["value_raw"])

    def test_negative_prior_eps_makes_growth_not_meaningful(self):
        r = self._neg(eps_owners=(5.0, -3.0))
        self.assertEqual(r["eps_growth_rate"]["status"], "not_meaningful")
        self.assertIsNone(r["eps_growth_rate"]["value_raw"])

    def test_negative_pat_gives_a_negative_return_but_no_payout(self):
        r = self._neg(pat=(-20.0, 80.0))
        self.assertLess(r["roe"]["value_raw"], 0)                         # a loss is a real negative return
        self.assertEqual(r["dividend_payout_ratio"]["status"], "not_meaningful")
        self.assertIsNone(r["dividend_payout_ratio"]["value_raw"])

    def test_negative_equity_makes_equity_based_ratios_not_meaningful(self):
        r = self._neg(equity=(-100.0, -50.0), non_controlling_interest=(0.0, 0.0), equity_full=(-100.0, -50.0), total_liabilities=(2100.0, 1850.0))
        for key in ("roe", "debt_to_equity", "financial_leverage_ratio", "graham_number", "pb_ratio"):
            self.assertIsNone(r[key]["value_raw"], key)
            self.assertEqual(r[key]["status"], "not_meaningful", key)

    def test_negative_ebitda_makes_ev_and_leverage_multiples_not_meaningful(self):
        r = self._neg(pbt=(-300.0, 100.0))                                # EBIT = -270, EBITDA = -210
        for key in ("ev_to_ebitda", "net_debt_to_ebitda"):
            self.assertIsNone(r[key]["value_raw"], key)
            self.assertEqual(r[key]["status"], "not_meaningful", key)

    def test_negative_working_capital_withholds_the_turnover(self):
        r = self._neg(total_current_assets=(300.0, 300.0))                # WC = 300 - 400 = -100 (prior -80)
        self.assertIsNone(r["working_capital_turnover"]["value_raw"])
        self.assertEqual(r["working_capital_turnover"]["status"], "not_meaningful")

    def test_zero_denominators_are_unavailable_not_zero(self):
        for key, fact in (("current_ratio", "total_current_liabilities"), ("asset_turnover", "total_assets"),
                          ("net_profit_margin", "revenue"), ("interest_coverage_ratio", "finance_costs"),
                          ("debt_to_equity", "equity_full")):
            r = rc.compute_with_parents(key, _with(facts(), fact, value=0.0, prior_value=0.0), MARKET, {})
            self.assertIsNone(r["value_raw"], f"{key} with {fact}=0")
            self.assertNotEqual(r["status"], "verified", key)


class TestRestatedAndAcquisitionYears(unittest.TestCase):

    def test_prior_year_comes_from_the_current_filing_comparative_column(self):
        # averages use the comparative printed in THIS filing (restated figures), never a separately filed older number
        fs = facts()
        r = rc.compute_with_parents("inventory_turnover", _with(fs, "inventory", value=200.0, prior_value=140.0), MARKET, {})
        self.assertAlmostEqual(r["value_raw"], 450.0 / ((200 + 140) / 2))
        d = r["denominator"]
        self.assertIn("FY2025", str(d.get("inventory_by_year") or d))

    def test_acquisition_year_flags_every_balance_vs_flow_ratio_without_changing_numbers(self):
        fs = facts()
        fs2 = dataclasses.replace(fs, extras={**(fs.extras or {}), "acquisition": {"flag": True, "reasons": ["part-year consolidation"]}})
        base, flagged = rc.compute_all(fs, MARKET), rc.compute_all(fs2, MARKET)
        n = 0
        for key in ("inventory_turnover", "asset_turnover", "roce", "fixed_asset_turnover", "days_working_capital", "financial_leverage_ratio"):
            self.assertAlmostEqual(base[key]["value_raw"], flagged[key]["value_raw"], places=12)      # numbers untouched
            if flagged[key]["status"] == "needs_review" and base[key]["status"] == "verified":
                n += 1
        self.assertGreaterEqual(n, 4)


if __name__ == "__main__":
    unittest.main()
