"""Final consistency audit (2026.10.18): one EV definition everywhere, Piotroski on one profit perimeter, Altman Z from reconciled inputs with an
exact Retained Earnings line, quote/valuation invalidation, the Altman adapter without a second formula or a cache.  Synthetic round numbers; every
expected value is written out by hand from the fixture in tests/test_ratio_remediation.py (never read back from the code under test)."""
import ast
import os
import unittest
from unittest.mock import patch

import tools.annual_report_financials as ar
import tools.ratio_contract as rc
from tests.test_ratio_remediation import MARKET, facts, parsed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def val(key, fs, market=None):
    return rc.compute_with_parents(key, fs, market, {})


class TestEnterpriseValueConsistency(unittest.TestCase):

    def test_specification_text_matches_the_calculation_for_every_ev_ratio(self):
        for key in ("ev_to_sales", "ev_to_fcf"):
            d = rc.SPEC[key]["definition"]
            self.assertIn("NCI is not added", d)
            self.assertNotIn("+ NCI", d)
        import tools.fundamental_ratio_registry as reg
        for r in reg.RATIOS:
            if r["ratio_key"] in ("ev_to_sales", "ev_to_fcf"):
                self.assertNotIn("NCI", r["formula"])

    def test_all_ev_multiples_use_the_same_enterprise_value(self):
        fs = facts()
        mcap = 100.0 * 100_000_000.0 / 1e7                 # 1,000 Cr
        ev = mcap + 600.0 - 50.0                           # debt: 300 + 150 + 50 + leases 60 + ... read back below
        debt = fs.get("total_debt").value
        ev = mcap + debt - fs.get("cash").value
        ebitda, sales, fcf = fs.get("ebitda").value, fs.get("net_sales").value, fs.get("fcf").value
        self.assertAlmostEqual(val("ev_to_ebitda", fs, MARKET)["value_raw"], ev / ebitda, places=9)
        self.assertAlmostEqual(val("ev_to_sales", fs, MARKET)["value_raw"], ev / sales, places=9)
        r = val("ev_to_fcf", fs, MARKET)
        self.assertAlmostEqual(r["value_raw"], ev / fcf, places=9) if fcf > 0 else self.assertNotEqual(r["status"], "verified")

    def test_negative_fcf_is_not_presented_as_a_meaningful_multiple(self):
        fs = facts(operating_cash_flow=(100.0, 120.0), capex_ppe_purchase=(150.0, 120.0), capex_intangible_purchase=(10.0, 5.0))
        r = val("ev_to_fcf", fs, MARKET)
        self.assertEqual(r["status"], "not_meaningful")


class TestPiotroskiReproducible(unittest.TestCase):
    P = parsed()

    def test_every_signal_is_reproducible_from_the_fixture_with_one_profit_perimeter(self):
        fs = facts()
        r = val("piotroski_f_score", fs, None)
        p = self.P
        pat_t, ta = p["pat_total"], p["total_assets"]                         # whole-entity profit (125/100) over closing assets
        cogs = (500.0 - 50.0, 400.0 - 20.0)
        rev = p["revenue"]
        expected = {
            "ROA > 0": pat_t[0] / ta[0] > 0,
            "ROA improved YoY": pat_t[0] / ta[0] > pat_t[1] / ta[1],
            "Operating Cash Flow > 0": p["operating_cash_flow"][0] > 0,
            "OCF > Net Profit (accrual quality)": p["operating_cash_flow"][0] > pat_t[0],
            "Leverage decreased (LT Debt/TA)": p["lt_borrowings"][0] / ta[0] < p["lt_borrowings"][1] / ta[1],
            "Current Ratio improved YoY": p["total_current_assets"][0] / p["total_current_liabilities"][0]
            > p["total_current_assets"][1] / p["total_current_liabilities"][1],
            "No dilution (shares not increased)": p["shares_outstanding"][0] <= p["shares_outstanding"][1] * 1.001,
            "Gross Margin improved YoY": (rev[0] - cogs[0]) / rev[0] > (rev[1] - cogs[1]) / rev[1],
            "Asset Turnover improved YoY": rev[0] / ta[0] > rev[1] / ta[1],
        }
        got = {t["name"]: t["passed"] for t in r["tests"]}
        self.assertEqual(got, expected)
        self.assertEqual(r["value_raw"], float(sum(expected.values())))

    def test_roa_signal_uses_whole_entity_profit_not_the_owners_figure(self):
        fs = facts(pat=(10.0, 80.0), pat_total=(125.0, 100.0))                # owners' PAT collapsed: the score must not read it
        roa = next(t for t in val("piotroski_f_score", fs, None)["tests"] if t["name"] == "ROA improved YoY")
        self.assertTrue(roa["passed"])                                       # 6.25% vs 5.56% on whole-entity profit
        self.assertIn("whole-entity", roa["spec"]["label"])

    def test_displayed_roa_is_a_different_declared_metric(self):
        fs = facts()
        self.assertAlmostEqual(val("roa", fs)["value_raw"], 100.0 / ((2000.0 + 1800.0) / 2) * 100, places=9)   # owners PAT / average assets
        self.assertNotAlmostEqual(val("roa", fs)["value_raw"], 125.0 / 2000.0 * 100, places=3)


class TestAltmanZ(unittest.TestCase):

    def test_components_and_final_score_by_hand(self):
        fs = facts()
        wc, ta, re_, ebit, tl, sales, mcap = 700 - 400, 2000.0, 400.0, 130.0 + 30.0, 1000.0, 1000.0, 1000.0
        z = 1.2 * wc / ta + 1.4 * re_ / ta + 3.3 * ebit / ta + 0.6 * mcap / tl + 1.0 * sales / ta
        self.assertAlmostEqual(z, 1.824, places=9)
        r = val("altman_z_score", fs, MARKET)
        self.assertAlmostEqual(r["value_raw"], z, places=9)

    def test_market_input_states_source_and_quote_time(self):
        mk = {"price": 100.0, "source": "angel", "quoted_at": "2026-10-10 08:42 UTC"}
        src = val("altman_z_score", facts(), mk)["market_price"]["source"]
        self.assertIn("fetched 2026-10-10 08:42 UTC", src)
        self.assertIn("NOT the fiscal-year-end price", src)

    def test_total_liabilities_derived_with_nci_never_assets_minus_owners_equity(self):
        fs = facts(total_liabilities=None)
        self.assertAlmostEqual(fs.get("total_liabilities").value, 2000.0 - (900.0 + 100.0), places=9)    # TA - (owners' equity + NCI)

    def test_exact_retained_earnings_note_replaces_the_other_equity_proxy(self):
        note = ("B. OTHER EQUITY Amount in millions Retained Earnings As per Last Balance Sheet 8,344.64 7,480.59 Add: Profit for the year 1,701.21 933.49 "
                "Add: Hedge reclassified 1.75 5.18 Less: Dividend paid (85.38) (82.38) Less: Remeasurement (5.30) 7.74 9,956.92 8,344.64 "
                "Other Comprehensive Income As per Last Balance Sheet 1.75 5.18 Add: Movement 76.76 1.50 Less: reclassified (1.75) (5.18) "
                "Less: translation - 0.25 76.76 1.75 Total 31,879.90 27,403.82")
        hit = ar._find_retained_earnings_note(["x", note], (3187.99, 2740.382), 0)
        self.assertAlmostEqual(hit[0], 995.692, places=3)
        self.assertAlmostEqual(hit[1], 834.464, places=3)
        self.assertEqual(hit[2], 2)

    def test_note_of_a_different_basis_or_unit_is_rejected(self):
        note = ("Retained Earnings As per Last Balance Sheet 7,894.13 7,237.54 Add: Profit for the year 1,613.96 726.74 Less: Dividend (85.38) (82.38) "
                "9,422.71 7,881.90 Total 31,000.00 26,000.00")
        self.assertIsNone(ar._find_retained_earnings_note([note], (3187.99, 2740.382), 0))        # total does not tie to this balance sheet
        broken = ("Retained Earnings As per Last Balance Sheet 100.00 90.00 Add: Profit 10.00 9.00 Closing 999.00 98.00 Total 31,879.90 27,403.82")
        self.assertIsNone(ar._find_retained_earnings_note([broken], (3187.99, 2740.382), 0))      # closing does not reconcile

    def test_proxy_stays_flagged_when_the_note_is_absent(self):
        fs = facts(retained_earnings_basis="other_equity_proxy")
        re_ = fs.get("retained_earnings")
        self.assertEqual(re_.status, "NEEDS_REVIEW")
        self.assertTrue(re_.estimated)
        self.assertEqual(val("altman_z_score", fs, MARKET)["status"], "needs_review")

    def test_note_makes_it_exact_and_verified(self):
        fs = facts(retained_earnings_basis="other_equity_proxy", retained_earnings_note=(300.0, 250.0, 77))
        re_ = fs.get("retained_earnings")
        self.assertEqual((re_.value, re_.prior_value, re_.status, re_.source_tag), (300.0, 250.0, "VERIFIED", "retained_earnings(note)"))
        self.assertEqual(fs.extras["retained_earnings_proxy_total_cr"], 400.0)


class TestProfitAttribution(unittest.TestCase):

    def test_net_margin_owners_vs_whole_entity_are_distinct_and_labelled(self):
        fs = facts()
        npm = val("net_profit_margin", fs)
        self.assertAlmostEqual(npm["value_raw"], 100.0 / 1000.0 * 100, places=9)
        self.assertIn("Attributable to Owners", npm["numerator"]["label"])
        self.assertTrue(any("NCI" in w for w in npm["warnings"]))
        self.assertAlmostEqual(125.0 / 1000.0 * 100, 12.5)                 # the whole-entity reference differs (and is not what the card shows)

    def test_roe_uses_owners_profit_over_owners_equity_and_roic_total_equity(self):
        fs = facts()
        self.assertAlmostEqual(val("roe", fs)["value_raw"], 100.0 / ((900.0 + 800.0) / 2) * 100, places=9)
        self.assertEqual(val("roe", fs)["equity_basis"], "owners_equity")

    def test_eps_and_payout_follow_the_owners_perimeter(self):
        fs = facts()
        self.assertAlmostEqual(val("eps_growth_rate", fs)["value_raw"], (10.0 / 8.0 - 1) * 100, places=9)


class TestQuoteRefresh(unittest.TestCase):

    def setUp(self):
        rc.clear_quote_memo()

    def tearDown(self):
        rc.clear_quote_memo()

    def test_one_quote_and_one_timestamp_inside_a_run(self):
        calls = []

        def provider(symbol, bse_code=None):
            calls.append(symbol)
            return {"ltp": 100.0 + len(calls), "close": 99.0, "source": "angel"}
        with patch("tools.market_price.get_live_price", provider):
            a, b = rc.live_market("SYNTH"), rc.live_market("SYNTH")
        self.assertEqual(len(calls), 1)
        self.assertEqual((a["price"], a["quoted_at"]), (b["price"], b["quoted_at"]))

    def test_expired_memo_fetches_a_new_quote_and_every_valuation_follows_it(self):
        fs = facts()
        prices = iter([100.0, 125.0])
        with patch("tools.market_price.get_live_price", lambda s, bse_code=None: {"ltp": next(prices), "close": 1.0, "source": "angel"}):
            m1 = rc.live_market("SYNTH")
            with patch.object(rc, "QUOTE_MEMO_SECONDS", -1):
                m2 = rc.live_market("SYNTH")
        self.assertEqual((m1["price"], m2["price"]), (100.0, 125.0))
        for key in ("pe_ratio", "pb_ratio", "ps_ratio", "ev_to_ebitda", "ev_to_sales", "earnings_yield", "price_to_cash_flow", "altman_z_score"):
            self.assertNotAlmostEqual(val(key, fs, m1)["value_raw"], val(key, fs, m2)["value_raw"], places=6, msg=key)
        self.assertAlmostEqual(val("pe_ratio", fs, m2)["value_raw"], 125.0 / 10.0, places=9)

    def test_failed_quote_is_not_memoised_and_no_value_is_invented(self):
        with patch("tools.market_price.get_live_price", lambda s, bse_code=None: None):
            self.assertIsNone(rc.live_market("SYNTH"))
        with patch("tools.market_price.get_live_price", lambda s, bse_code=None: {"ltp": 50.0, "close": None, "source": "angel"}):
            self.assertEqual(rc.live_market("SYNTH")["price"], 50.0)


class TestAltmanAdapterHasNoSecondFormulaOrCache(unittest.TestCase):

    def test_wrapper_neither_caches_nor_reads_stored_rows_nor_recombines(self):
        src = open(os.path.join(ROOT, "tools", "nse_xbrl.py"), encoding="utf-8").read()
        fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "fetch_altman_z_score_components")
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
        self.assertTrue({"_write_cache", "_read_cache", "try_db_ratio", "_combine_altman_z_score"}.isdisjoint(names), names)


if __name__ == "__main__":
    unittest.main()
