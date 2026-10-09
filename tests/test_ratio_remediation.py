"""
Regression tests for the 2026-10 global ratio remediation (one test class per audited defect).

Synthetic only (symbol "SYNTHCO", round numbers, mocked extraction/market/shareholding data, cache I/O
disabled) - the checks are about the definitions, extraction rules and status logic, never one company.
"""

import datetime as dt
import math
import os
import tempfile
import unittest
from unittest.mock import patch

import tools.annual_report_financials as ar
import tools.fundamental_fact_store as ffs
import tools.ratio_calculation_engine as eng
import tools.ratio_contract as rc
import tools.document_analysis_engine as dae

MARKET = {"price": 100.0, "source": "test"}


def parsed(**over):
    """A complete, internally consistent consolidated filing (Rs crore)."""
    base = {
        "revenue": (1000.0, 800.0),
        "components": {"Cost of materials consumed": (500.0, 400.0), "Changes in inventories": (-50.0, -20.0)},
        "purchases_disclosed": {"cur": 480.0, "prior": 380.0, "page": 50},
        "inventory": (200.0, 100.0), "receivables": (250.0, 150.0), "payables": (160.0, 140.0),
        "total_current_assets": (700.0, 600.0), "total_current_liabilities": (400.0, 380.0),
        "total_assets": (2000.0, 1800.0),
        "equity": (900.0, 800.0), "equity_basis": "owners", "non_controlling_interest": (100.0, 80.0),
        "nci_evaluated": True, "equity_full": (1000.0, 880.0),
        "pat": (100.0, 80.0), "pat_total": (125.0, 100.0), "pat_basis": "owners",
        "pbt": (130.0, 100.0), "finance_costs": (30.0, 25.0), "depreciation": (60.0, 50.0), "tax_expense": (30.0, 20.0),
        "cash": (50.0, 40.0),
        "lt_borrowings": (300.0, 280.0), "st_borrowings": (150.0, 140.0), "current_maturities": (50.0, 40.0),
        "lease_liabilities_total": (60.0, 55.0), "lease_evidence": "found",
        "other_fin_liab_nc": {"qualifying_cur": 0.0}, "other_fin_liab_cur": {"qualifying_cur": 0.0},
        "total_liabilities": (1000.0, 920.0),
        "ppe": (800.0, 700.0), "rou_assets": (100.0, 90.0), "cwip": (50.0, 60.0), "intangibles": (20.0, 15.0),
        "goodwill": (30.0, 30.0), "net_fixed_assets": (800.0, 700.0),
        "operating_cash_flow": (140.0, 120.0), "capex_ppe_purchase": (150.0, 120.0), "capex_intangible_purchase": (10.0, 5.0),
        "dividend_paid": (-30.0, -25.0), "borrowings_repayment": (80.0, 60.0), "lease_repayment": (10.0, 9.0),
        "shares_outstanding": (100_000_000.0, 100_000_000.0),   # EPS 10 x 10 Cr shares = 100 Cr owners PAT (consistent)
        "eps": (12.5, 10.0), "eps_owners": (10.0, 8.0),
        "dividend_per_share": None, "dividend_per_share_found": False,
        "dps_declared": {"found": True, "total": 3.0, "interim": [1.0], "final": [2.0], "special": [],
                         "no_dividend_evidence": False, "pages": [10], "policy": "interim + final"},
        "other_expenses": (150.0, 140.0), "employee_benefit_expense": (200.0, 180.0), "total_expenses": (870.0, 700.0),
        "retained_earnings": (400.0, 350.0), "retained_earnings_basis": "exact",
        "acquisition_signals": {"hits": 0, "pages": []},
        "bs_page": 42, "pl_page": 40, "source_url": "http://example.test/AR.pdf", "basis_used": "consolidated",
    }
    base.update(over)
    return base


def facts(**over):
    ffs.clear_run_cache()
    with patch.object(ar, "_get_extracted_financials", return_value=parsed(**over)):
        return ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2026)


def calc(key, market=None, **over):
    fs = facts(**over)
    return rc.compute_with_parents(key, fs, market if key in rc.MARKET_KEYS or market else None, {})


def calc_m(key, **over):
    return calc(key, market=MARKET, **over)


# =================================================================================================
class TestNoteReferenceShareCapital(unittest.TestCase):                                   # test 1
    def test_note_ref_column_is_not_the_value(self):
        page = ("Equity Share Capital 16 1,138.48 1,099.31 Other Equity 16 31,879.90 27,403.82 "
                "Total Equity 33,018.39 28,503.13")
        hit = dae._extract_from_anchor_page(page, ["equity share capital"], 0.1, permissive=True)
        self.assertAlmostEqual(hit["value"], 113.848, places=3)
        self.assertAlmostEqual(hit["prior_value"], 109.931, places=3)

    def test_genuine_small_bare_values_still_read(self):
        page = "Equity Share Capital 8(m) 362 362 Other equity 1,06,878 94,394"
        hit = dae._extract_from_anchor_page(page, ["equity share capital"], 1.0, permissive=True)
        self.assertEqual((hit["value"], hit["prior_value"]), (362.0, 362.0))

    def test_price_to_book_uses_the_single_bvps(self):
        fs = facts()
        bv = rc.compute_with_parents("bvps", fs, None, {})
        pb = rc.compute_with_parents("pb_ratio", fs, MARKET, {})
        self.assertAlmostEqual(bv["value_raw"], 900.0 * 1e7 / 100_000_000)           # owners' equity / shares
        self.assertAlmostEqual(pb["value_raw"], MARKET["price"] / bv["value_raw"])   # P/B derives from THAT bvps


class TestOwnersEps(unittest.TestCase):                                                     # test 2
    def test_alias_reads_the_excluding_nci_line(self):
        page = ("Basic Earnings per Equity Share 19.71 14.56 Diluted Earnings per Equity Share 19.71 14.56 "
                "Basic Earnings per Equity Share - Excluding Non controlling interest 15.09 8.50 "
                "Diluted Earnings per Equity Share - Excluding Non controlling interest 15.09 8.50")
        hit = dae._extract_from_anchor_page(page, dae._LINE_ITEM_ALIASES["eps_owners"], 1.0)
        self.assertEqual((hit["value"], hit["prior_value"]), (15.09, 8.5))
        self.assertEqual(ar._find_eps_owners_row(page), (15.09, 8.5))
        self.assertIsNone(ar._find_eps_owners_row("Basic 19.71 14.56 Diluted 19.71 14.56"))

    def test_valuation_ratios_use_owners_eps(self):
        fs = facts()
        eps = fs.get("eps")
        self.assertEqual((eps.value, eps.prior_value), (10.0, 8.0))                    # NOT the 12.5 whole-entity line
        self.assertEqual(rc.compute_with_parents("pe_ratio", fs, MARKET, {})["value_raw"], 100.0 / 10.0)
        self.assertAlmostEqual(rc.compute_with_parents("earnings_yield", fs, MARKET, {})["value_raw"], 10.0)
        self.assertAlmostEqual(rc.compute_with_parents("eps_growth_rate", fs, None, {})["value_raw"], 25.0)
        self.assertAlmostEqual(rc.compute_with_parents("graham_number", fs, None, {})["value_raw"],
                               math.sqrt(22.5 * 10.0 * 90.0))
        peg = rc.compute_with_parents("peg_ratio", fs, MARKET, {})
        self.assertAlmostEqual(peg["value_raw"], (100.0 / 10.0) / 25.0)

    def test_single_printed_eps_is_the_owners_default(self):
        fs = facts(eps_owners=None, non_controlling_interest=None, nci_evaluated=True, pat_total=None)
        eps = fs.get("eps")
        self.assertEqual(eps.value, 12.5)
        self.assertIn("ind_as_33_default", eps.source_tag)

    def test_missing_eps_is_unavailable_not_zero(self):
        r = calc_m("pe_ratio", eps=None, eps_owners=None)
        self.assertIsNone(r["value_raw"])
        self.assertIn(r["status"], rc.UNAVAILABLE)


class TestDividendExtraction(unittest.TestCase):                                            # tests 3, 4
    FY = 2026

    def test_interim_plus_recommended_final_for_the_year(self):
        txt = ("The Board on July 15, 2025 declared an interim dividend of Rs. 0.75/- per equity share. "
               "A final dividend of INR 1.5/- per equity share for the financial year 2025-26 is recommended.")
        r = ar._scan_dividend_disclosures([txt], self.FY)
        self.assertTrue(r["found"])
        self.assertEqual((r["interim"], r["final"], r["total"]), ([0.75], [1.5], 2.25))

    def test_last_years_final_paid_this_year_is_not_added(self):
        txt = ("Final dividend of Rs. 24 per share for the financial year 2024-25 was approved at the AGM held on "
               "August 10, 2025 and paid. Interim dividend of Rs. 19 per share was declared on 2 November 2025.")
        r = ar._scan_dividend_disclosures([txt], self.FY)
        self.assertEqual(r["final"], [])                    # a prior-year final never counts
        self.assertEqual(r["interim"], [19.0])

    def test_interim_declared_outside_the_year_is_ignored(self):
        r = ar._scan_dividend_disclosures(["An interim dividend of Rs. 3 per share was declared on 5 March 2024."], self.FY)
        self.assertFalse(r["found"])

    def test_a_subsidiarys_dividend_is_never_added_to_the_parents_dps(self):
        txt = ("The Board on July 15, 2025 declared an interim dividend of Rs. 0.75/- per equity share. "
               "B. Subsidiary Company (X Industries Limited) The Board of Directors have recommended dividend of "
               "Rs. 4.50 per share for the financial year 2025-26. A final dividend of INR 1.5/- per equity share "
               "for the financial year 2025-26 is recommended.")
        r = ar._scan_dividend_disclosures([txt], self.FY)
        self.assertEqual((r["interim"], r["final"], r["total"]), ([0.75], [1.5], 2.25))

    def test_unlabelled_dividend_sentence_is_classified_by_its_wording(self):
        txt = ("The Board has recommended a dividend of Rs. 12 per equity share for the financial year 2025-26, "
               "subject to approval of the members.")
        r = ar._scan_dividend_disclosures([txt], self.FY)
        self.assertEqual(r["final"], [12.0])

    def test_nothing_found_is_not_a_zero_dividend(self):
        r = ar._scan_dividend_disclosures(["The company is committed to rewarding shareholders."], self.FY)
        self.assertFalse(r["found"])
        self.assertIsNone(r["total"])
        self.assertFalse(r["no_dividend_evidence"])

    def test_explicit_no_dividend_statement_is_the_only_zero_evidence(self):
        r = ar._scan_dividend_disclosures(
            ["For the financial year 2025-26, no dividend has been recommended by the Board."], self.FY)
        self.assertTrue(r["no_dividend_evidence"])
        self.assertFalse(r["found"])

    def test_cash_flow_dividend_paid_is_extracted_and_dividend_income_is_not(self):
        cf = ("Interest and Dividend Income (4.50) (4.35) Dividend paid (152.00) (134.19) Impact of Share issued (925.00) -")
        hit = dae._extract_from_anchor_page(cf, dae._LINE_ITEM_ALIASES["dividends_paid"], 0.1)
        self.assertAlmostEqual(hit["value"], -15.2, places=2)
        self.assertAlmostEqual(hit["prior_value"], -13.419, places=3)
        only_income = dae._extract_from_anchor_page("Interest and Dividend Income (4.50) (4.35)",
                                                    dae._LINE_ITEM_ALIASES["dividends_paid"], 0.1)
        self.assertIsNone(only_income)

    def test_payout_uses_dividends_paid_not_dps_times_shares(self):
        r = calc("dividend_payout_ratio")
        self.assertAlmostEqual(r["value_raw"], 30.0 / 100.0 * 100.0)                   # 30 paid / 100 owners PAT
        self.assertEqual(r["dividend_basis"], "paid")
        self.assertEqual(r["status"], "needs_review")                                    # NCI present: cash dividends may include NCI


class TestUnknownIsNeverZero(unittest.TestCase):                                            # test 5
    NO_DIVIDEND_INFO = dict(dividend_paid=None, dps_declared={"found": False, "total": None, "no_dividend_evidence": False},
                            dividend_per_share=None)

    def test_dividend_yield_payout_retention_sgr_are_unavailable_not_0_or_100(self):
        fs = facts(**self.NO_DIVIDEND_INFO)
        cache = {}
        yld = rc.compute_with_parents("dividend_yield", fs, MARKET, cache)
        pay = rc.compute_with_parents("dividend_payout_ratio", fs, None, cache)
        ret = rc.compute_with_parents("retention_ratio", fs, None, cache)
        sgr = rc.compute_with_parents("sustainable_growth_rate", fs, None, cache)
        for r in (yld, pay, ret, sgr):
            self.assertIsNone(r["value_raw"], r["ratio_key"])
            self.assertIn(r["status"], rc.UNAVAILABLE, r["ratio_key"])
        self.assertNotEqual(ret.get("value_raw"), 100.0)

    def test_explicit_no_dividend_evidence_supports_a_real_zero(self):
        fs = facts(dividend_paid=None, dps_declared={"found": False, "total": None, "no_dividend_evidence": True},
                   dividend_per_share=None)
        self.assertEqual(fs.get("dps").value, 0.0)
        self.assertEqual(fs.get("dividends_paid").value, 0.0)
        pay = rc.compute_with_parents("dividend_payout_ratio", fs, None, {})
        self.assertEqual(pay["value_raw"], 0.0)

    def test_missing_inputs_never_become_computed_zeros_elsewhere(self):
        for key, over in (("current_ratio", dict(total_current_assets=None)),
                          ("interest_coverage_ratio", dict(finance_costs=None)),
                          ("free_cash_flow", dict(operating_cash_flow=None)),
                          ("capex_intensity", dict(capex_ppe_purchase=None)),
                          ("bvps", dict(shares_outstanding=None))):
            r = calc(key, **over)
            self.assertIsNone(r["value_raw"], key)
            self.assertIn(r["status"], rc.UNAVAILABLE, key)

    def test_shareholding_unknowns(self):
        self.assertIn(rc.pledge_result(None)["status"], rc.UNAVAILABLE)
        self.assertEqual(rc.pledge_result({"promoter_holding_pct": 50.0, "pledge_status": "assumed_zero",
                                           "promoter_pledge_pct": 0.0})["status"], "insufficient_data")
        self.assertEqual(rc.free_float_result({})["status"], "not_disclosed")


class TestLeaseLiabilitiesAndTotalDebt(unittest.TestCase):                                  # test 6
    def test_lease_liabilities_are_in_total_debt(self):
        d = ar._compute_total_debt(parsed(), "basis1")
        self.assertEqual(d["total_debt_cur"], 300.0 + 150.0 + 50.0 + 60.0)
        self.assertEqual(d["total_debt_prior"], 280.0 + 140.0 + 40.0 + 55.0)
        self.assertEqual(d["lease_status"], "found")

    def test_basis2_excludes_leases(self):
        self.assertEqual(ar._compute_total_debt(parsed(), "basis2")["total_debt_cur"], 500.0)

    def test_unextracted_lease_is_flagged_not_labelled_included(self):
        d = ar._compute_total_debt(parsed(lease_liabilities_total=None, lease_evidence="unparsed"), "basis1")
        self.assertEqual(d["lease_status"], "not_found")
        self.assertTrue(d["estimated"])
        self.assertIs(d["components"]["b) Lease Liabilities included in Total Debt"], False)
        self.assertIsNone(d["components"]["b) Lease Liabilities"])
        self.assertIn("NOT EXTRACTED", d["components"]["b) Lease Liabilities status"])

    def test_no_lease_line_at_all_is_a_supported_zero(self):
        d = ar._compute_total_debt(parsed(lease_liabilities_total=None, lease_evidence="none_on_balance_sheet"), "basis1")
        self.assertEqual(d["lease_status"], "none_on_balance_sheet")
        self.assertEqual(d["total_debt_cur"], 500.0)
        self.assertFalse(d["estimated"])

    def test_every_debt_ratio_consumes_the_one_total_debt_fact(self):
        fs = facts()
        debt = fs.get("total_debt").value
        self.assertEqual(debt, 560.0)
        cache = {}
        de = rc.compute_with_parents("debt_to_equity", fs, None, cache)
        dr = rc.compute_with_parents("debt_ratio", fs, None, cache)
        cfc = rc.compute_with_parents("cash_flow_coverage_ratio", fs, None, cache)
        nd = rc.compute_with_parents("net_debt_to_ebitda", fs, None, cache)
        ev = rc.compute_with_parents("ev_to_ebitda", fs, MARKET, cache)
        self.assertAlmostEqual(de["value_raw"], debt / 1000.0)
        self.assertAlmostEqual(dr["value_raw"], debt / 2000.0)
        self.assertAlmostEqual(cfc["value_raw"], 140.0 / debt)
        self.assertAlmostEqual(nd["value_raw"], (debt - 50.0) / fs.get("ebitda").value)
        # EV (authoritative spec): Market Cap + Total Debt - Cash;  mcap = 10 Cr sh x 100 = 1000 Cr
        self.assertAlmostEqual(ev["numerator"]["value_cr"], MARKET["price"] * 10.0 + debt - 50.0)
        roic = rc.compute_with_parents("roic", fs, None, cache)
        self.assertEqual(roic["denominator"]["components"]["Total Debt"], round(debt, 2))

    def test_other_financial_liabilities_not_evaluated_is_flagged(self):
        d = ar._compute_total_debt(parsed(other_fin_liab_nc=None, other_fin_liab_cur=None), "basis1")
        self.assertTrue(d["estimated"])
        self.assertLessEqual(d["confidence"], 0.9)


class TestTotalLiabilitiesWithNci(unittest.TestCase):                                       # test 7
    def test_reported_total_liabilities_is_used(self):
        self.assertEqual(facts().get("total_liabilities").value, 1000.0)

    def test_derived_total_liabilities_never_books_nci_as_a_liability(self):
        fs = facts(total_liabilities=None)
        tl = fs.get("total_liabilities")
        self.assertEqual(tl.value, 2000.0 - (900.0 + 100.0))     # not 2000 - 900
        self.assertIn("nci", tl.source_tag)

    def test_unread_nci_makes_derived_liabilities_needs_review(self):
        fs = facts(total_liabilities=None, non_controlling_interest=None, nci_evaluated=False, equity_basis="generic",
                   pat_basis="generic")
        self.assertTrue(fs.get("total_liabilities").estimated)

    def test_altman_uses_total_liabilities(self):
        r = calc_m("altman_z_score")
        self.assertEqual(r["components"]["total_liabilities_cr"], 1000.0)
        mc = 100.0 * 100_000_000 / 1e7
        expected = (1.2 * 300 / 2000 + 1.4 * 400 / 2000 + 3.3 * 160 / 2000 + 0.6 * mc / 1000 + 1.0 * 1000 / 2000)
        self.assertAlmostEqual(r["value_raw"], expected)


class TestPiotroskiNineTests(unittest.TestCase):                                            # test 8
    def test_prior_year_share_count_from_the_four_column_layout(self):
        page = ("Issued, subscribed and fully paid up equity shares outstanding at the end of the year "
                "11,38,48,310 1,138.48 10,99,31,337 1,099.31 Reconciliation")
        self.assertEqual(dae._shares_prior_from_page(
            page, ["issued, subscribed and fully paid up equity shares outstanding at the end of the year"]), 109931337.0)
        self.assertIsNone(dae._shares_prior_from_page("shares outstanding at the end of the year 100 200", ["shares outstanding at the end of the year"]))

    def test_all_nine_tests_evaluated_when_inputs_exist(self):
        r = calc("piotroski_f_score")
        self.assertEqual(r["max_score"], 9)
        self.assertEqual(r["tests_evaluated"], 9)
        self.assertEqual(r["value_raw"], float(sum(1 for t in r["tests"] if t["passed"])))
        self.assertTrue(0 <= r["value_raw"] <= 9)

    def test_missing_prior_shares_is_insufficient_not_a_seven_point_score(self):
        r = calc("piotroski_f_score", shares_outstanding=(10_000_000.0, None))
        self.assertIsNone(r["value_raw"])
        self.assertEqual(r["status"], "insufficient_data")
        self.assertEqual(r["tests_evaluated"], 8)
        self.assertIn("dilution", r["reason"].lower())
        self.assertEqual(r["max_score"], 9)

    def test_dilution_test_fails_when_shares_increase(self):
        r = calc("piotroski_f_score", shares_outstanding=(11_000_000.0, 10_000_000.0))
        t = [x for x in r["tests"] if "dilution" in x["name"].lower()][0]
        self.assertIs(t["passed"], False)

    def test_leverage_test_falls_back_to_total_debt_when_lt_borrowings_absent(self):
        r = calc("piotroski_f_score", lt_borrowings=None)
        self.assertEqual(r["tests_evaluated"], 9)
        self.assertTrue(any("Total Debt/TA" in t["name"] for t in r["tests"]))


class TestEbitdaConsistency(unittest.TestCase):                                             # test 9
    def test_one_ebit_one_ebitda_other_income_in_both(self):
        fs = facts()
        ebit, ebitda = fs.get("ebit"), fs.get("ebitda")
        self.assertEqual(ebit.value, 130.0 + 30.0)
        self.assertEqual(ebitda.value, ebit.value + 60.0)

    def test_every_ebitda_ratio_uses_that_fact_and_evidence_matches(self):
        fs = facts()
        ebitda = fs.get("ebitda").value
        cache = {}
        nd = rc.compute_with_parents("net_debt_to_ebitda", fs, None, cache)
        ev = rc.compute_with_parents("ev_to_ebitda", fs, MARKET, cache)
        dscr = rc.compute_with_parents("dscr", fs, None, cache)
        for r in (nd, ev):
            self.assertEqual(r["denominator"]["value_cr"], round(ebitda, 2))    # displayed evidence == calculation input
        self.assertEqual(dscr["numerator"]["value_cr"], round(ebitda, 2))
        self.assertAlmostEqual(nd["value_raw"], nd["numerator"]["value_cr"] / ebitda, places=2)

    def test_opm_roce_interest_coverage_share_the_same_ebit(self):
        fs = facts()
        ebit = fs.get("ebit").value
        cache = {}
        self.assertAlmostEqual(rc.compute_with_parents("operating_profit_margin", fs, None, cache)["value_raw"], ebit / 10.0)
        self.assertAlmostEqual(rc.compute_with_parents("interest_coverage_ratio", fs, None, cache)["value_raw"], ebit / 30.0)
        roce = rc.compute_with_parents("roce", fs, None, cache)
        self.assertAlmostEqual(roce["value_raw"], ebit / (((2000 - 400) + (1800 - 380)) / 2.0) * 100)


class TestRoundedValuesNeverFeedCalculations(unittest.TestCase):                           # test 10
    def test_days_ratios_divide_the_raw_turnover(self):
        fs = facts(inventory=(200.0, 110.0))
        cache = {}
        it = rc.compute_with_parents("inventory_turnover", fs, None, cache)
        doh = rc.compute_with_parents("days_inventory_outstanding", fs, None, cache)
        self.assertAlmostEqual(doh["value_raw"], 365.0 / it["value_raw"], places=9)
        self.assertNotAlmostEqual(doh["value_raw"], 365.0 / it["value"], places=3)   # not the rounded display value

    def test_earnings_yield_is_eps_over_price_not_100_over_rounded_pe(self):
        fs = facts(eps_owners=(7.0, 6.0))
        ey = rc.compute_with_parents("earnings_yield", fs, MARKET, {})
        pe = rc.compute_with_parents("pe_ratio", fs, MARKET, {})
        self.assertAlmostEqual(ey["value_raw"], 7.0 / 100.0 * 100.0, places=12)
        self.assertNotAlmostEqual(ey["value_raw"], 100.0 / pe["value"], places=6)

    def test_sgr_uses_unrounded_roe_and_retention(self):
        fs = facts()
        cache = {}
        roe = rc.compute_with_parents("roe", fs, None, cache)
        pay = rc.compute_with_parents("dividend_payout_ratio", fs, None, cache)
        sgr = rc.compute_with_parents("sustainable_growth_rate", fs, None, cache)
        self.assertAlmostEqual(sgr["value_raw"], roe["value_raw"] * (100.0 - pay["value_raw"]) / 100.0, places=12)

    def test_value_display_is_rounded_only_for_display(self):
        r = calc("inventory_turnover", inventory=(200.0, 110.0))
        self.assertEqual(r["value"], round(r["value_raw"], 2))
        self.assertNotEqual(r["value"], r["value_raw"])


class TestStatusPropagation(unittest.TestCase):                                             # test 11
    def test_children_inherit_needs_review_from_the_parent(self):
        fs = facts()                                                  # payout is needs_review (NCI cash dividends)
        cache = {}
        pay = rc.compute_with_parents("dividend_payout_ratio", fs, None, cache)
        self.assertEqual(pay["status"], "needs_review")
        self.assertEqual(rc.compute_with_parents("retention_ratio", fs, None, cache)["status"], "needs_review")
        self.assertEqual(rc.compute_with_parents("sustainable_growth_rate", fs, None, cache)["status"], "needs_review")

    def test_dso_is_not_verified_when_receivables_turnover_is_a_proxy(self):
        fs = facts()
        cache = {}
        rt = rc.compute_with_parents("receivables_turnover", fs, None, cache)
        dso = rc.compute_with_parents("days_sales_outstanding", fs, None, cache)
        ccc = rc.compute_with_parents("cash_conversion_cycle", fs, None, cache)
        self.assertEqual(rt["status"], "needs_review")
        self.assertEqual(dso["status"], "needs_review")
        self.assertEqual(ccc["status"], "needs_review")

    def test_unavailable_parent_makes_the_child_unavailable(self):
        fs = facts(receivables=None)
        cache = {}
        dso = rc.compute_with_parents("days_sales_outstanding", fs, None, cache)
        ccc = rc.compute_with_parents("cash_conversion_cycle", fs, None, cache)
        self.assertIsNone(dso["value_raw"])
        self.assertIn(dso["status"], rc.UNAVAILABLE)
        self.assertIsNone(ccc["value_raw"])
        self.assertIn(ccc["status"], rc.UNAVAILABLE)

    def test_status_ranking_never_improves_through_a_derivation(self):
        fs = facts()
        res = rc.compute_all(fs, MARKET)
        for key, parents in rc.PARENTS.items():
            for p in parents:
                if res[p]["status"] in rc.UNAVAILABLE:
                    self.assertIn(res[key]["status"], rc.UNAVAILABLE, f"{key} <- {p}")
                if res[p]["status"] == "needs_review" and res[key]["value_raw"] is not None:
                    self.assertNotEqual(res[key]["status"], "verified", f"{key} <- {p}")


class TestNegativeAndMeaninglessMultiples(unittest.TestCase):                              # test 12
    def test_ev_to_fcf_with_negative_fcf_is_not_meaningful_but_keeps_the_number(self):
        fs = facts(operating_cash_flow=(100.0, 90.0), capex_ppe_purchase=(150.0, 120.0), capex_intangible_purchase=(10.0, 5.0))
        r = rc.compute_with_parents("ev_to_fcf", fs, MARKET, {})
        self.assertLess(fs.get("fcf").value, 0)
        self.assertEqual(r["status"], "not_meaningful")
        self.assertLess(r["value_raw"], 0)                                          # mathematical value preserved
        legacy = ar._contract_to_legacy(r, fs, 2026)
        self.assertFalse(legacy["applicable"])                                      # but never displayed as a normal multiple
        self.assertEqual(legacy["mathematical_value"], r["value_raw"])

    def test_zero_or_negative_denominators_are_not_meaningful(self):
        self.assertEqual(calc_m("price_to_cash_flow", operating_cash_flow=(-5.0, 1.0))["status"], "not_meaningful")
        self.assertEqual(calc_m("pe_ratio", eps_owners=(-2.0, 1.0))["status"], "not_meaningful")
        self.assertEqual(calc_m("ev_to_ebitda", pbt=(-100.0, 10.0), finance_costs=(10.0, 5.0), depreciation=(10.0, 5.0))["status"],
                         "not_meaningful")
        self.assertEqual(calc("effective_tax_rate", pbt=(-10.0, 5.0))["status"], "not_meaningful")
        self.assertEqual(calc("eps_growth_rate", eps_owners=(5.0, -1.0))["status"], "not_meaningful")

    def test_peg_is_not_meaningful_when_growth_is_not_positive(self):
        self.assertEqual(calc_m("peg_ratio", eps_owners=(8.0, 10.0))["status"], "not_meaningful")

    def test_net_cash_is_not_a_leverage_ratio(self):
        r = calc("net_debt_to_ebitda", cash=(900.0, 800.0))
        self.assertEqual(r["status"], "not_applicable")
        self.assertTrue(r["net_cash"])

    def test_stored_status_survives_the_db_check_constraint(self):
        self.assertEqual(dae._db_status("not_meaningful"), "needs_review")
        self.assertEqual(dae._db_status("verified"), "verified")
        row = {"ratio_key": "ev_to_fcf", "status": "needs_review", "inputs": [{"name": "_metadata", "status_detail": "not_meaningful"}]}
        self.assertEqual(dae.regroup_fundamental_rows([row])[0]["status"], "not_meaningful")


class TestDscr(unittest.TestCase):                                                          # test 13
    def test_unavailable_when_gross_repayment_missing(self):
        r = calc("dscr", borrowings_repayment=None)
        self.assertIsNone(r["value_raw"])
        self.assertEqual(r["status"], "insufficient_data")
        self.assertIn("gross principal", r["reason"].lower())

    def test_net_financing_flow_is_never_substituted(self):
        r = calc("dscr", borrowings_repayment=None, interest_paid=(38.0, 33.0), lease_repayment=(5.0, 4.0))
        self.assertIsNone(r["value_raw"])

    def test_formula_when_disclosed(self):
        fs = facts()
        r = rc.compute_with_parents("dscr", fs, None, {})
        denom = 80.0 + 10.0 + 30.0            # gross principal + lease principal (leases are in debt) + interest due
        self.assertAlmostEqual(r["value_raw"], fs.get("ebitda").value / denom)
        self.assertEqual(r["status"], "needs_review")               # NOI is a flagged proxy (EBITDA)

    def test_canonical_and_contract_agree_on_unavailable(self):
        ffs.clear_run_cache()
        with patch.object(ar, "_get_extracted_financials", return_value=parsed(borrowings_repayment=None)):
            out = eng.calculate_ratio("dscr", "SYNTHCO", "Synth Co", 2026)
        self.assertEqual(out["status"], "INSUFFICIENT_DATA")
        self.assertIsNone(out["value"])


class TestWorkingCapitalDefinitions(unittest.TestCase):                                     # tests 14, 15, 16
    def test_days_working_capital_is_average_wc_over_revenue_times_365(self):
        r = calc("days_working_capital")
        wc_cur, wc_prior = 700.0 - 400.0, 600.0 - 380.0
        self.assertAlmostEqual(r["value_raw"], ((wc_cur + wc_prior) / 2.0) / 1000.0 * 365.0)
        self.assertNotAlmostEqual(r["value_raw"], wc_cur / 1000.0 * 365.0, places=2)   # not the closing figure

    def test_days_working_capital_falls_back_to_closing_only_flagged(self):
        r = calc("days_working_capital", total_current_assets=(700.0, None), total_current_liabilities=(400.0, None))
        self.assertAlmostEqual(r["value_raw"], 300.0 / 1000.0 * 365.0)
        self.assertTrue(r["estimated"])

    def test_wc_turnover_uses_the_authoritative_average_working_capital(self):
        r = calc("working_capital_turnover")
        self.assertAlmostEqual(r["value_raw"], 1000.0 / ((300.0 + 220.0) / 2.0))          # average WC (authoritative spec, Sr 8)
        it = calc("inventory_turnover")
        self.assertAlmostEqual(it["value_raw"], 450.0 / 150.0)                            # COGS / avg inventory (Sr 1, corrected 2026.10.7)

    def test_roce_is_ebit_over_average_capital_employed(self):
        r = calc("roce")
        ce_cur, ce_prior = 2000.0 - 400.0, 1800.0 - 380.0
        self.assertAlmostEqual(r["value_raw"], 160.0 / ((ce_cur + ce_prior) / 2.0) * 100.0)
        self.assertEqual(r["denominator"]["capital_employed_by_year"], {"FY2026": 1600.0, "FY2025": 1420.0})

    def test_roic_is_nopat_over_closing_invested_capital(self):
        fs = facts()
        r = rc.compute_with_parents("roic", fs, None, {})
        etr = 30.0 / 130.0
        nopat = 160.0 * (1 - etr)
        ic = 560.0 + 1000.0 - 50.0                       # total debt + total equity incl NCI - cash (closing)
        self.assertAlmostEqual(fs.get("nopat").value, nopat)
        self.assertAlmostEqual(r["value_raw"], nopat / ic * 100.0)
        self.assertEqual(r["averaging"], "closing-only")

    def test_capital_employed_and_invested_capital_defined_once(self):
        fs = facts()
        self.assertEqual(fs.get("capital_employed").value, 1600.0)
        self.assertEqual(fs.get("invested_capital").value, 560.0 + 1000.0 - 50.0)


class TestFixedAssetDefinition(unittest.TestCase):                                         # test 17
    def test_net_fixed_assets_is_ppe_rou_cwip_intangibles_excluding_goodwill(self):
        fs = facts()
        nfa = fs.get("net_fixed_assets")
        self.assertEqual(nfa.value, 800.0 + 100.0 + 50.0 + 20.0)
        self.assertEqual(nfa.prior_value, 700.0 + 90.0 + 60.0 + 15.0)
        r = rc.compute_with_parents("fixed_asset_turnover", fs, None, {})
        self.assertAlmostEqual(r["value_raw"], 1000.0 / ((970.0 + 865.0) / 2.0))

    def test_ppe_only_legacy_parse_is_flagged_not_silently_used(self):
        fs = facts(ppe=None, rou_assets=None, cwip=None, intangibles=None)
        nfa = fs.get("net_fixed_assets")
        self.assertEqual(nfa.value, 800.0)
        self.assertTrue(nfa.estimated)
        self.assertIn("PPE-only", nfa.warnings[0])

    def test_missing_components_are_named_in_the_evidence(self):
        nfa = facts(cwip=None).get("net_fixed_assets")
        self.assertIn("cwip", nfa.warnings[0])


class TestContributionMargin(unittest.TestCase):                                            # test 18
    def test_unavailable_when_only_goods_cost_is_known(self):
        r = calc("contribution_margin")
        self.assertIsNone(r["value_raw"])
        self.assertEqual(r["status"], "insufficient_data")
        self.assertIn("goods cost alone", r["reason"].lower())

    def test_proxy_with_note_items_is_needs_review_never_verified(self):
        note = {"items": {"Freight and forwarding": (40.0, 35.0), "Power and fuel": (30.0, 25.0)}}
        r = calc("contribution_margin", variable_opex_note=note)
        var = 500.0 - 50.0 + 40.0 + 30.0
        self.assertAlmostEqual(r["value_raw"], (1000.0 - var) / 1000.0 * 100.0)
        self.assertEqual(r["status"], "needs_review")
        self.assertTrue(r["approximation"])
        self.assertLessEqual(r["confidence"], 0.6)

    def test_direct_expenses_line_counts_as_variable_cost_proxy(self):
        r = calc("contribution_margin", direct_expenses=(120.0, 100.0))
        self.assertAlmostEqual(r["value_raw"], (1000.0 - (500.0 - 50.0 + 120.0)) / 1000.0 * 100.0)
        self.assertEqual(r["status"], "needs_review")


class TestFreeFloat(unittest.TestCase):                                                     # test 19
    def test_proxy_is_labelled_and_needs_review(self):
        r = rc.free_float_result({"promoter_holding_pct": 55.0})
        self.assertAlmostEqual(r["value_raw"], 45.0)
        self.assertEqual(r["status"], "needs_review")
        self.assertIn("PROXY", r["warnings"][0])

    def test_locked_in_shares_are_subtracted_and_then_it_is_verified(self):
        r = rc.free_float_result({"promoter_holding_pct": 55.0, "locked_in_pct": 5.0})
        self.assertAlmostEqual(r["value_raw"], 40.0)
        self.assertEqual(r["status"], "verified")

    def test_unknown_promoter_holding_is_not_assumed_100_percent_free_float(self):
        r = rc.free_float_result({"institutional_holding_pct": 10.0})
        self.assertIsNone(r["value_raw"])
        self.assertEqual(r["status"], "not_disclosed")

    def test_genuine_zero_promoter_holding_is_a_real_100(self):
        r = rc.free_float_result({"promoter_holding_pct": 0.0})
        self.assertAlmostEqual(r["value_raw"], 100.0)

    def test_pledge_zero_promoter_is_not_applicable(self):
        self.assertEqual(rc.pledge_result({"promoter_holding_pct": 0.0})["status"], "not_applicable")


class TestBetaMethodology(unittest.TestCase):                                               # test 20
    def _series(self, n, beta=0.8, seed=1):
        import pandas as pd
        import random
        random.seed(seed)
        idx = pd.date_range("2022-01-07", periods=n + 1, freq="W-FRI")
        m, s = [100.0], [50.0]
        for _ in range(n):
            r = random.gauss(0.001, 0.02)
            m.append(m[-1] * (1 + r))
            s.append(s[-1] * (1 + beta * r))
        return pd.Series(s, index=idx), pd.Series(m, index=idx)

    def test_policy_constants_are_one_definition(self):
        from tools import market_history as mh
        self.assertEqual((mh.BENCHMARK, mh.INTERVAL, mh.PERIOD, mh.MIN_OBSERVATIONS),
                         (rc.BETA_POLICY["benchmark"], rc.BETA_POLICY["interval"], rc.BETA_POLICY["period"],
                          rc.BETA_POLICY["min_observations"]))

    def test_beta_is_sample_cov_over_sample_var_of_weekly_returns(self):
        from tools import market_history as mh
        import numpy as np
        s, m = self._series(104, beta=0.8)
        info = mh.beta_from_close_series(s, m)
        sr, mr = s.pct_change().dropna().to_numpy(), m.pct_change().dropna().to_numpy()
        self.assertAlmostEqual(info["beta"], np.cov(sr, mr, ddof=1)[0][1] / np.var(mr, ddof=1), places=10)
        self.assertAlmostEqual(info["beta"], 0.8, places=6)

    def test_below_minimum_observations_is_insufficient_never_a_guess(self):
        from tools import market_history as mh
        s, m = self._series(40)
        info = mh.beta_from_close_series(s, m)
        self.assertNotIn("beta", info)
        res = rc.beta_result(info)
        self.assertEqual(res["status"], "insufficient_data")
        self.assertIsNone(res["value_raw"])

    def test_confidence_tiers(self):
        from tools import market_history as mh
        self.assertEqual(rc.beta_result(mh.beta_from_close_series(*self._series(104)))["status"], "verified")
        self.assertEqual(rc.beta_result(mh.beta_from_close_series(*self._series(60)))["status"], "needs_review")

    def test_manual_mode_never_fabricates_a_beta_and_engines_agree(self):
        from tools import nse_xbrl
        from tools.manual_mode import manual_mode
        with manual_mode():
            legacy = nse_xbrl.fetch_beta("SYNTHCO")
        self.assertEqual(legacy["status"], "insufficient_data")
        self.assertIsNone(legacy["value"])
        info = {"reason": "none", "n": 0}
        with patch("tools.market_history.weekly_beta", return_value=info):
            canon = eng.calculate_ratio("beta", "SYNTHCO", "Synth Co", 2026)
        self.assertEqual(canon["status"], "INSUFFICIENT_DATA")


class TestCrossEngineEquality(unittest.TestCase):                                           # test 21
    """The contract, the nse_xbrl-facing legacy adapters and the canonical API must give the same number."""
    KEYS = ["inventory_turnover", "receivables_turnover", "payables_turnover", "asset_turnover",
            "working_capital_turnover", "current_ratio", "quick_ratio", "cash_ratio", "working_capital",
            "gross_profit_margin", "operating_profit_margin", "net_profit_margin", "roe", "roce", "debt_to_equity",
            "debt_ratio", "interest_coverage_ratio", "financial_leverage_ratio", "fixed_asset_turnover",
            "days_working_capital", "receivables_to_payables", "net_debt_to_ebitda", "dscr", "cash_flow_coverage_ratio",
            "free_cash_flow", "fcf_margin", "ocf_ratio", "capex_intensity", "ocf_to_net_profit", "roic",
            "effective_tax_rate", "eps_growth_rate", "bvps", "dividend_payout_ratio", "piotroski_f_score"]

    def test_three_paths_agree_for_every_statement_ratio(self):
        p = parsed()
        ffs.clear_run_cache()
        with patch.object(ar, "_get_extracted_financials", return_value=p), \
             patch.object(ar, "_read_cache", lambda k: None), patch.object(ar, "_write_cache", lambda k, v: None):
            fs = ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2026)
            direct = {k: rc.compute_with_parents(k, fs, None, {}) for k in self.KEYS}
            legacy_fn = {
                "inventory_turnover": ar.fetch_inventory_turnover_from_annual_report,
                "debt_to_equity": ar.fetch_debt_to_equity_from_annual_report,
                "roic": ar.fetch_roic_from_annual_report,
                "dividend_payout_ratio": ar.fetch_dividend_payout_ratio_from_annual_report,
                "days_working_capital": ar.fetch_days_working_capital_from_annual_report,
                "net_profit_margin": ar.fetch_net_profit_margin_from_annual_report,
                "free_cash_flow": ar.fetch_free_cash_flow_from_annual_report,
            }
            for k, fn in legacy_fn.items():
                out = fn("SYNTHCO", "Synth Co", 2026, True)
                self.assertAlmostEqual(out["value_raw"], direct[k]["value_raw"], places=9, msg=f"legacy {k}")
                self.assertEqual(out["status"], direct[k]["status"], k)
            for k in self.KEYS:
                canon = eng.calculate_ratio(k, "SYNTHCO", "Synth Co", 2026)
                if direct[k]["value_raw"] is None:
                    self.assertIsNone(canon["value"], k)
                else:
                    self.assertAlmostEqual(canon["value"], round(direct[k]["value_raw"], 4), places=4, msg=f"canonical {k}")
                self.assertEqual(canon["status"].lower(), direct[k]["status"], k)

    def test_document_row_matches_the_contract(self):
        fs = facts()
        res = rc.compute_with_parents("net_profit_margin", fs, None, {})
        legacy = ar._contract_to_legacy(res, fs, 2026)
        ratio_def = {"ratio_key": "net_profit_margin", "label": "Net Profit Margin", "category": "P&L",
                     "formula": "x", "strategy": "A"}
        row = dae._row_from_nse_xbrl_out(ratio_def, legacy)
        self.assertAlmostEqual(row["value"], round(res["value_raw"], 4))
        self.assertEqual(row["status"], res["status"])

    def test_every_computable_key_has_exactly_one_registry_entry_and_spec(self):
        from tools.fundamental_ratio_registry import BY_RATIO_KEY
        for k in rc.COMPUTABLE:
            self.assertIn(k, BY_RATIO_KEY, k)
            self.assertIn(k, rc.SPEC if k not in ("working_capital",) else rc.SPEC, k)

    def test_legacy_wrappers_contain_no_formula_code(self):
        import inspect
        for name in ("fetch_inventory_turnover_from_annual_report", "fetch_debt_to_equity_from_annual_report",
                     "fetch_roic_from_annual_report", "fetch_altman_z_score_components_from_annual_report",
                     "fetch_piotroski_f_score_from_annual_report"):
            src = inspect.getsource(getattr(ar, name))
            self.assertIn("_contract_fetch", src, name)
            self.assertLess(len(src.splitlines()), 12, name)


class TestCacheAndVersioning(unittest.TestCase):                                            # tests 22, 23
    def test_document_tag_changes_with_the_formula_version(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "SYNTHCO_2026.json")
            open(path, "w").write("{}")
            with patch("tools.ar_document_cache._text_cache_path", return_value=path):
                t1 = ar._document_identity_tag("SYNTHCO", 2026)
                with patch.object(rc, "FORMULA_VERSION", "9999.99.9"):
                    t2 = ar._document_identity_tag("SYNTHCO", 2026)
            self.assertTrue(t1 and t2)
            self.assertNotEqual(t1, t2)

    def test_contract_cache_key_carries_the_formula_version(self):
        k1 = ar._contract_cache_key("roe", "SYNTHCO", 2026, True, "basis1")
        with patch.object(rc, "FORMULA_VERSION", "9999.99.9"):
            k2 = ar._contract_cache_key("roe", "SYNTHCO", 2026, True, "basis1")
        self.assertNotEqual(k1, k2)

    def test_logic_version_is_bumped_with_the_formula_version(self):
        self.assertGreaterEqual(int(ar._EXTRACTION_LOGIC_VERSION), 62)
        self.assertGreaterEqual(ffs.EXTRACTION_VERSION, 6)

    def test_fact_memo_is_keyed_by_document_and_logic_version(self):
        ffs.clear_run_cache()
        with patch.object(ar, "_get_extracted_financials", return_value=parsed()) as m:
            ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2026)
            ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2026)
            self.assertEqual(m.call_count, 1)                                # memoised within one document identity
            with patch.object(ar, "_document_identity_tag", return_value="newdoc"):
                ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2026)         # a re-uploaded document
            self.assertEqual(m.call_count, 2)

    def test_rows_without_or_with_an_old_formula_version_are_flagged_stale(self):
        cur = {"ratio_key": "roe", "status": "verified", "inputs": [{"name": "_metadata", "formula_version": rc.FORMULA_VERSION}]}
        old = {"ratio_key": "roa", "status": "verified", "inputs": [{"name": "_metadata", "formula_version": "2026.07"}]}
        none = {"ratio_key": "bvps", "status": "verified", "inputs": [{"name": "_metadata"}]}
        out = {r["ratio_key"]: r["stale"] for r in dae.mark_stale_rows([cur, old, none])}
        self.assertEqual(out, {"roe": False, "roa": True, "bvps": True})

    def test_every_row_shell_is_versioned_and_timestamped(self):
        row = dae._row_shell({"ratio_key": "x", "label": "X", "category": "P&L", "formula": "f", "strategy": "A"},
                             1.0, "x", "verified", [])
        md = [i for i in row["inputs"] if i["name"] == "_metadata"][0]
        self.assertEqual(md["formula_version"], rc.FORMULA_VERSION)
        self.assertEqual(md["status_detail"], "verified")
        dt.datetime.fromisoformat(md["calculated_at"])

    def test_stale_rows_are_recalculated_on_read_not_served_as_current(self):
        stale = [{"ratio_key": "roe", "status": "verified", "category": "Returns",
                  "inputs": [{"name": "_metadata", "formula_version": "old"}]}]
        fresh = [{"ratio_key": "roe", "status": "verified", "category": "Returns",
                  "inputs": [{"name": "_metadata", "formula_version": rc.FORMULA_VERSION}]}]
        calls = {"n": 0}

        def fake_get(sym):
            return dae.mark_stale_rows(stale if calls["n"] == 0 else fresh)

        def fake_run(sym, name=None):
            calls["n"] += 1

        with patch.object(dae, "get_fundamental_results", side_effect=fake_get), \
             patch.object(dae, "run_fundamental_analysis", side_effect=fake_run):
            rows = dae.ensure_current_fundamental_results("SYNTHCO")
        self.assertEqual(calls["n"], 1)
        self.assertFalse(rows[0]["stale"])

    def test_failed_recalculation_still_returns_flagged_stale_rows(self):
        stale = [{"ratio_key": "roe", "status": "verified", "inputs": [{"name": "_metadata", "formula_version": "old"}]}]
        with patch.object(dae, "get_fundamental_results", return_value=dae.mark_stale_rows(stale)), \
             patch.object(dae, "run_fundamental_analysis", side_effect=RuntimeError("documents gone")):
            rows = dae.ensure_current_fundamental_results("SYNTHCO")
        self.assertTrue(rows[0]["stale"])


class TestStatementBasis(unittest.TestCase):                                                # test 24
    def test_all_facts_share_one_basis_and_legacy_output_says_so(self):
        fs = facts()
        bases = {f.statement_basis for f in fs.facts.values() if isinstance(f, ffs.CanonicalFact)}
        self.assertEqual(bases, {"CONSOLIDATED"})
        out = ar._contract_to_legacy(rc.compute_with_parents("current_ratio", fs, None, {}), fs, 2026)
        self.assertEqual(out["statement_basis"], "consolidated")
        self.assertIn("consolidated", out["period"])

    def test_standalone_fallback_is_reported_as_standalone_everywhere(self):
        fs = facts(basis_used="standalone", non_controlling_interest=None, nci_evaluated=False, equity_basis="generic",
                   pat_basis="generic", equity_full=None, pat_total=None)
        bases = {f.statement_basis for f in fs.facts.values() if isinstance(f, ffs.CanonicalFact)}
        self.assertEqual(bases, {"STANDALONE"})
        out = ar._contract_to_legacy(rc.compute_with_parents("current_ratio", fs, None, {}), fs, 2026)
        self.assertIn("standalone", out["period"])
        # a standalone filing has no NCI to split: nothing is flagged as a perimeter ambiguity
        self.assertEqual(fs.get("equity_full").value, fs.get("equity").value)
        self.assertEqual(fs.get("pat_total").value, fs.get("pat").value)

    def test_every_result_carries_its_period_and_basis_provenance(self):
        fs = facts()
        res = rc.compute_with_parents("roe", fs, None, {})
        for inp in res["inputs"]:
            self.assertEqual(inp["period"], "FY2026")
            self.assertEqual(inp["statement_basis"], "CONSOLIDATED")
        self.assertEqual(res["formula_version"], rc.FORMULA_VERSION)


class TestOwnersVersusWholeEntityPerimeter(unittest.TestCase):                              # test 25
    def test_roe_is_owners_profit_over_owners_equity(self):
        r = calc("roe")
        self.assertAlmostEqual(r["value_raw"], 100.0 / ((900.0 + 800.0) / 2.0) * 100.0)

    def test_npm_and_roa_follow_the_approved_owners_policy_and_flip_with_it(self):
        self.assertAlmostEqual(calc("net_profit_margin")["value_raw"], 100.0 / 1000.0 * 100.0)
        self.assertAlmostEqual(calc("roa")["value_raw"], 100.0 / ((2000.0 + 1800.0) / 2.0) * 100.0)
        with patch.dict(rc.PERIMETER_POLICY, {"npm": "whole_entity", "roa": "whole_entity"}):
            self.assertAlmostEqual(calc("net_profit_margin")["value_raw"], 125.0 / 1000.0 * 100.0)
            self.assertAlmostEqual(calc("roa")["value_raw"], 125.0 / ((2000.0 + 1800.0) / 2.0) * 100.0)

    def test_whole_entity_flows_are_not_divided_by_owners_only_profit(self):
        r = calc("ocf_to_net_profit")
        self.assertAlmostEqual(r["value_raw"], 140.0 / 125.0)                                  # whole-entity OCF / total PAT
        self.assertEqual(r["denominator"]["label"], "Profit for the Year (whole entity, incl. NCI)")

    def test_debt_to_equity_and_leverage_use_total_equity_including_nci(self):
        self.assertAlmostEqual(calc("debt_to_equity")["value_raw"], 560.0 / 1000.0)
        self.assertAlmostEqual(calc("financial_leverage_ratio")["value_raw"], ((2000.0 + 1800.0) / 2.0) / ((1000.0 + 880.0) / 2.0))

    def test_beneish_tata_uses_whole_entity_profit(self):
        fs = facts()
        r = rc.compute_with_parents("beneish_m_score", fs, None, {})
        # (total PAT 125 - OCF 140) / total assets 2000
        self.assertAlmostEqual(r["variables"]["TATA"], round((125.0 - 140.0) / 2000.0, 3))
        self.assertEqual(r["status"], "needs_review")      # SG&A proxy

    def test_perimeter_is_declared_for_every_ratio_with_a_formula(self):
        for k in rc.COMPUTABLE:
            if k in rc.SPEC:
                self.assertTrue(rc.SPEC[k].get("perimeter"), k)

    def test_ev_is_market_cap_plus_debt_minus_cash_one_global_definition(self):
        fs = facts()
        mc, debt, cash = 1000.0, fs.get("total_debt").value, fs.get("cash").value
        for k in ("ev_to_ebitda", "ev_to_sales"):
            r = rc.compute_with_parents(k, fs, MARKET, {})
            self.assertAlmostEqual(r["numerator"]["value_raw"], mc + debt - cash, msg=k)
            self.assertTrue(r["breakdown"]["reconciles"], k)
        names = [i["name"] for i in rc.compute_with_parents("ev_to_ebitda", fs, MARKET, {})["breakdown"]["inputs"]]
        self.assertFalse(any("Non-Controlling" in n for n in names))

    def test_unreadable_nci_does_not_change_ev_or_its_status(self):
        with_nci = calc_m("ev_to_ebitda")
        without = calc_m("ev_to_ebitda", non_controlling_interest=None, nci_evaluated=False)
        self.assertAlmostEqual(with_nci["value_raw"], without["value_raw"])
        self.assertFalse(any("non-controlling" in w.lower() for w in without["warnings"]))

    def test_owners_pat_ambiguity_is_flagged_when_nci_exists_but_no_owners_line(self):
        fs = facts(pat_basis="generic")
        self.assertEqual(fs.get("pat").perimeter, "ambiguous")
        self.assertEqual(fs.get("pat").status, "NEEDS_REVIEW")


class TestAcquisitionDistortion(unittest.TestCase):                                         # phase 6
    def test_part_year_consolidation_flags_balance_sensitive_ratios_without_changing_numbers(self):
        clean = calc("asset_turnover")
        flagged = calc("asset_turnover", goodwill=(300.0, 30.0), acquisition_signals={"hits": 5, "pages": [1]})
        self.assertAlmostEqual(clean["value_raw"], flagged["value_raw"])            # never adjusted
        self.assertEqual(flagged["status"], "needs_review")
        self.assertTrue(flagged.get("acquisition_flag"))
        self.assertIn("Acquisition-affected", " ".join(flagged["warnings"]))

    def test_insensitive_ratios_are_not_flagged(self):
        r = calc("current_ratio", goodwill=(300.0, 30.0), acquisition_signals={"hits": 5, "pages": [1]})
        self.assertEqual(r["status"], "verified")

    def test_no_acquisition_no_flag(self):
        self.assertEqual(calc("asset_turnover")["status"], "verified")


class TestPersistence(unittest.TestCase):                                                   # test 23
    def test_a_recalculation_refreshes_computed_at(self):
        """`computed_at`'s column default only fires on INSERT, so every upsert must set it explicitly."""
        captured = []

        class Q:
            def upsert(self, rows, **k):
                captured.append(rows)
                return self

            def execute(self):
                return self

        class C:
            def table(self, _):
                return Q()

        rows = [{"ratio_key": "roe", "status": "verified", "inputs": []}]
        dae._persist_fundamental_rows(C(), "SYNTHCO", rows)
        first = dt.datetime.fromisoformat(captured[0][0]["computed_at"])
        import time
        time.sleep(0.01)
        dae._persist_fundamental_rows(C(), "SYNTHCO", rows)
        second = dt.datetime.fromisoformat(captured[1][0]["computed_at"])
        self.assertGreater(second, first)
        self.assertEqual(captured[0][0]["symbol"], "SYNTHCO")

    def test_not_meaningful_is_stored_in_a_constraint_safe_way(self):
        captured = []

        class Q:
            def upsert(self, rows, **k):
                captured.extend(rows)
                return self

            def execute(self):
                return self

        class C:
            def table(self, _):
                return Q()

        dae._persist_fundamental_rows(C(), "SYNTHCO", [{"ratio_key": "ev_to_fcf", "status": "not_meaningful", "inputs": []}])
        self.assertEqual(captured[0]["status"], "needs_review")


class TestBalanceSheetIntegrity(unittest.TestCase):                                         # multi-company findings
    """Accounting identities that must hold for ANY company - impossible numbers are rejected/flagged, never
    presented as verified (found by the multi-company regression: wrong NCI picks, grand-total 'liabilities',
    debt above total assets, profit inconsistent with EPS x shares)."""

    def test_impossible_nci_is_rejected_so_liabilities_are_never_negative(self):
        # NCI of 5000 with owners' equity 900 cannot fit inside Total Assets 2000 - Current Liabilities 400
        fs = facts(non_controlling_interest=(5000.0, 4000.0), total_liabilities=None)
        self.assertTrue(fs.extras["integrity_failures"])
        self.assertIsNone(fs.get("nci").value)
        tl = fs.get("total_liabilities")
        self.assertTrue(tl.value is None or tl.value > 0)
        self.assertNotEqual(tl.status, "VERIFIED") if tl.value is None else self.assertTrue(tl.estimated)

    def test_a_grand_total_mistaken_for_total_liabilities_is_not_used(self):
        fs = facts(total_liabilities=(2000.0, 1800.0))            # == total assets: that is 'Total Equity and Liabilities'
        tl = fs.get("total_liabilities")
        self.assertEqual(tl.value, 2000.0 - 1000.0)                # falls back to TA - (owners equity + NCI)
        self.assertIn("identity", " ".join(fs.extras["integrity_failures"]))

    def test_total_liabilities_below_current_liabilities_is_impossible(self):
        fs = facts(total_liabilities=(300.0, 250.0))
        self.assertTrue(fs.extras["integrity_failures"])

    def test_debt_above_total_assets_is_flagged_not_verified(self):
        fs = facts(lt_borrowings=(2500.0, 2000.0))
        self.assertEqual(fs.get("total_debt").status, "NEEDS_REVIEW")
        r = rc.compute_with_parents("debt_ratio", fs, None, {})
        self.assertEqual(r["status"], "needs_review")
        self.assertTrue(any("exceeds Total Assets" in w for w in r["warnings"]))

    def test_profit_that_contradicts_eps_times_shares_is_flagged(self):
        fs = facts(pat=(0.0, 3667.0))                              # eps 10 x 10 Cr shares = 100 Cr, but 'profit' = 0
        self.assertEqual(fs.get("pat").status, "NEEDS_REVIEW")
        self.assertEqual(rc.compute_with_parents("net_profit_margin", fs, None, {})["status"], "needs_review")
        self.assertEqual(rc.compute_with_parents("roe", fs, None, {})["status"], "needs_review")

    def test_share_count_far_from_profit_over_eps_is_flagged(self):
        fs = facts(shares_outstanding=(150_000_000.0, 150_000_000.0))     # PAT/EPS implies 100,000,000
        sh = fs.get("shares_outstanding")
        self.assertEqual(sh.status, "NEEDS_REVIEW")
        self.assertEqual(rc.compute_with_parents("bvps", fs, None, {})["status"], "needs_review")
        self.assertEqual(rc.compute_with_parents("pb_ratio", fs, MARKET, {})["status"], "needs_review")

    def test_clean_filing_has_no_integrity_failures(self):
        self.assertEqual(facts().extras["integrity_failures"], [])


class TestBankingRatios(unittest.TestCase):                                                 # phase 11
    def test_implausible_extracted_bank_ratio_is_withheld(self):
        out = rc.guard_bank("net_interest_margin", {"applicable": True, "value": 94775.1, "unit": "%"})
        self.assertFalse(out["applicable"])
        self.assertEqual(out["status"], "insufficient_data")
        self.assertIsNone(out["value"])
        self.assertEqual(out["mathematical_value"], 94775.1)

    def test_plausible_values_and_unavailable_results_pass_through(self):
        ok = {"applicable": True, "value": 4.07, "unit": "%"}
        self.assertEqual(rc.guard_bank("net_interest_margin", ok), ok)
        na = {"applicable": False, "reason": "x"}
        self.assertEqual(rc.guard_bank("casa_ratio", na), na)

    def test_every_bank_ratio_has_bounds_and_the_fetchers_are_guarded(self):
        import tools.nse_xbrl as nx
        for k in ("net_interest_margin", "casa_ratio", "gross_npa_pct", "net_npa_pct", "capital_adequacy_ratio",
                  "cost_to_income_ratio", "provision_coverage_ratio", "credit_to_deposit_ratio"):
            self.assertIn(k, rc.BANK_BOUNDS)
        for fn in ("fetch_net_interest_margin", "fetch_casa_ratio", "fetch_gross_npa_pct", "fetch_net_npa_pct",
                   "fetch_capital_adequacy_ratio", "fetch_cost_to_income_ratio"):
            self.assertTrue(hasattr(getattr(nx, fn), "__wrapped__"), fn)
            self.assertTrue(hasattr(getattr(ar, fn + "_from_annual_report"), "__wrapped__"), fn)

    def test_bank_ratios_are_never_built_from_generic_statement_proxies(self):
        for k in ("net_interest_margin", "casa_ratio", "gross_npa_pct", "net_npa_pct", "capital_adequacy_ratio",
                  "cost_to_income_ratio", "provision_coverage_ratio", "credit_to_deposit_ratio"):
            self.assertNotIn(k, rc.COMPUTABLE, k)

    def test_non_bank_and_unclassified_sectors_are_not_applicable(self):
        from tools.sector_ratio_applicability import is_bank_ratio_applicable
        for sector in ("Insurance", "Information Technology", "Capital Markets (Broking/AMC/Exchanges)", None):
            self.assertFalse(is_bank_ratio_applicable(sector), sector)
        self.assertTrue(is_bank_ratio_applicable("Banks"))
        self.assertTrue(is_bank_ratio_applicable("NBFC"))
        with patch("tools.sector_ratio_applicability.is_bank_ratio_applicable", return_value=False),              patch("tools.nse_sector_map.get_nse_sector", return_value="Insurance"):
            self.assertEqual(eng.calculate_ratio("casa_ratio", "SYNTHCO", "Synth Co", 2026)["status"], "NOT_APPLICABLE")


class TestExtractionRepairs(unittest.TestCase):                                             # found by multi-company runs
    TCS_LIKE = ("TOTAL TAX EXPENSE | 16,534 | 15,898 | PROFIT FOR THE YEAR | 48,797 | 46,099 | OTHER COMPREHENSIVE INCOME | "
                "Profit for the year attributable to: | Shareholders of the Company | 48,553 | 45,908 | "
                "Non-controlling interests | 244 | 191 | 48,797 | 46,099 |")

    def test_owners_profit_is_repaired_when_the_label_reader_returned_a_wrong_row(self):
        pat, basis, repaired, total = ar._repair_owners_pat((16234.0, 70033.0), "owners", self.TCS_LIKE, 1.0,
                                                     (134.19, 125.88), (3_618_000_000.0, None))
        self.assertTrue(repaired)
        self.assertEqual((pat, basis), ((48553.0, 45908.0), "owners"))

    def test_a_consistent_owners_profit_is_left_alone(self):
        pat, basis, repaired, total = ar._repair_owners_pat((48553.0, 45908.0), "owners", self.TCS_LIKE, 1.0,
                                                     (134.19, 125.88), (3_618_000_000.0, None))
        self.assertFalse(repaired)
        self.assertEqual(pat, (48553.0, 45908.0))

    def test_no_repair_without_a_validating_total_or_eps(self):
        pat, _, repaired, total = ar._repair_owners_pat((1.0, 2.0), "generic", "Shareholders of the Company | 9 | 8 |", 1.0, None, None)
        self.assertFalse(repaired)
        self.assertEqual(pat, (1.0, 2.0))

    def test_candidate_must_agree_with_eps_times_shares(self):
        text = "PROFIT FOR THE YEAR | 100 | 90 | Owners of the Company | 100 | 90 |"
        _, _, repaired, total = ar._repair_owners_pat((5.0, 4.0), "generic", text, 1.0, (50.0, 40.0), (10_000_000.0, None))
        self.assertFalse(repaired)            # EPS x shares = 50 Cr: the 100 candidate is not within 35% -> not trusted

    def test_the_same_borrowings_row_read_twice_is_counted_once(self):
        d = ar._compute_total_debt(parsed(lt_borrowings=(1.0, 13.0), st_borrowings=(1.0, 13.0), current_maturities=None,
                                          lease_liabilities_total=(1647.0, 1471.0)), "basis1")
        self.assertEqual(d["total_debt_cur"], 1.0 + 1647.0)
        self.assertTrue(d["estimated"])


class TestSharedMarketPrice(unittest.TestCase):
    def test_market_dependent_ratios_without_a_price_are_unavailable_not_stale(self):
        fs = facts()
        for k in ("pe_ratio", "pb_ratio", "ps_ratio", "dividend_yield", "earnings_yield", "ev_to_ebitda", "fcf_yield",
                  "price_to_cash_flow", "altman_z_score"):
            r = rc.compute_with_parents(k, fs, None, {})
            self.assertIsNone(r["value_raw"], k)
            self.assertEqual(r["status"], "insufficient_data", k)


if __name__ == "__main__":
    unittest.main()
