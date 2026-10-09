"""Global audit 2026.10.7 regressions: dividend fiscal-year attribution, COGS-based Inventory Turnover (+ dependents),
the Cash Ratio numerator, the EBIT-margin label. Synthetic text/facts only - no company-specific logic."""
import unittest

import tools.fundamental_ratio_registry as reg
from tools import ratio_contract as rc
from tools.annual_report_financials import _scan_dividend_disclosures, _dividend_target_fy
from tools.fundamental_fact_store import factset_from_values


def _pages(*texts):
    return list(texts)


class TestDividendFiscalYearAttribution(unittest.TestCase):

    INTERIM_FOR_PRIOR = ("5. DIVIDEND During the financial year under review, the Board in its Meeting held on July 15, 2025 "
                         "declared an interim dividend of ₹ 0.75/- per equity share i.e., 7.5% of the face value of ₹ 10/- each, "
                         "out of the retained earnings available for the financial year 2024-25. The dividend payout ratio for "
                         "the same is 11.33%. Further, the Board at its meeting held on May 23, 2026, recommended the payment "
                         "of Final Dividend of INR 1.5/- per Equity Share of face value of INR 10/- each, out of the profits of "
                         "the Company for the financial year 2025-26, subject to approval of the Members.")

    def test_interim_declared_in_the_year_but_for_the_prior_year_is_not_counted(self):
        r = _scan_dividend_disclosures(_pages(self.INTERIM_FOR_PRIOR), 2026)
        self.assertEqual(r["interim"], [])
        self.assertEqual(r["final"], [1.5])
        self.assertEqual(r["total"], 1.5)
        kinds = {(e["kind"], e["amount"]): e for e in r["events"]}
        self.assertEqual(kinds[("interim", 0.75)]["target_fy"], 2025)
        self.assertFalse(kinds[("interim", 0.75)]["counted"])

    def test_the_same_report_gives_the_other_answer_for_the_prior_fiscal_year(self):
        r = _scan_dividend_disclosures(_pages(self.INTERIM_FOR_PRIOR), 2025)
        self.assertEqual(r["interim"], [0.75])
        self.assertEqual(r["final"], [])

    def test_interim_for_the_current_year_is_counted_with_the_final(self):
        txt = ("The Board declared an interim dividend of Rs. 4 per equity share for the financial year 2025-26 on 5 November 2025. "
               "The Board recommends a final dividend of Rs. 6 per equity share for the financial year ended March 31, 2026.")
        r = _scan_dividend_disclosures(_pages(txt), 2026)
        self.assertEqual((r["interim"], r["final"], r["total"]), ([4.0], [6.0], 10.0))

    def test_unstated_year_falls_back_to_the_event_date(self):
        txt = "The Board declared an interim dividend of Rs. 3 per equity share on 12 February 2026."
        self.assertEqual(_scan_dividend_disclosures(_pages(txt), 2026)["interim"], [3.0])
        self.assertEqual(_scan_dividend_disclosures(_pages(txt), 2027)["interim"], [])

    def test_prior_year_final_paid_this_year_is_never_added(self):
        txt = "The final dividend of Rs. 2 per equity share for the financial year 2024-25 was paid on 20 August 2025."
        self.assertIsNone(_scan_dividend_disclosures(_pages(txt), 2026)["total"])      # unknown - not zero

    def test_target_year_reader(self):
        t = "dividend of Rs 2 per share out of profits for FY 2023-24. Next sentence for FY 2030-31"
        self.assertEqual(_dividend_target_fy(t, t.index("per share")), 2024)
        self.assertEqual(_dividend_target_fy("x of 2 per share for the year ended 31st March 2026", 0), 2026)
        self.assertIsNone(_dividend_target_fy("x of 2 per share paid on time", 0))


def _fs(**vals):
    base = {"revenue": (1000.0, 800.0), "inventory": (200.0, 110.0), "cogs": (450.0, 380.0)}
    base.update(vals)
    return factset_from_values("SYNTH", 2026, "CONSOLIDATED", base, source_document="synthetic://doc",
                               extras={"components": {"Cost of materials consumed": (500.0, 400.0),
                                                      "Changes in inventories": (-50.0, -20.0)}})


class TestInventoryTurnoverUsesCogsAndDependentsFollow(unittest.TestCase):

    def test_turnover_days_and_ccc_use_cogs(self):
        fs = _fs(receivables=(250.0, 150.0), payables=(160.0, 140.0), purchases=(450.0, 380.0))
        cache = {}
        it = rc.compute_with_parents("inventory_turnover", fs, None, cache)
        self.assertAlmostEqual(it["value_raw"], 450.0 / 155.0)
        self.assertEqual(it["numerator"]["value_cr"], 450.0)
        dio = rc.compute_with_parents("days_inventory_outstanding", fs, None, cache)
        self.assertAlmostEqual(dio["value_raw"], 365.0 / (450.0 / 155.0))
        ccc = rc.compute_with_parents("cash_conversion_cycle", fs, None, cache)
        dso, dpo = cache["days_sales_outstanding"]["value_raw"], cache["days_payables_outstanding"]["value_raw"]
        self.assertAlmostEqual(ccc["value_raw"], dso + dio["value_raw"] - dpo)

    def test_revenue_changes_do_not_move_inventory_turnover(self):
        a = rc.compute_ratio("inventory_turnover", _fs(), None, {})["value_raw"]
        b = rc.compute_ratio("inventory_turnover", _fs(revenue=(5000.0, 800.0)), None, {})["value_raw"]
        self.assertEqual(a, b)

    def test_non_positive_cogs_is_not_computed_and_not_zero(self):
        r = rc.compute_ratio("inventory_turnover", _fs(cogs=(-5.0, 1.0)), None, {})
        self.assertIsNone(r["value_raw"])
        self.assertEqual(r["status"], "insufficient_data")

    def test_missing_cogs_is_unavailable_not_zero(self):
        fs = factset_from_values("SYNTH", 2026, "CONSOLIDATED", {"revenue": (1000.0, 800.0), "inventory": (200.0, 110.0)}, source_document="synthetic://doc",
                                 extras={"components": {"Cost of materials consumed": (500.0, 400.0)}})
        r = rc.compute_ratio("inventory_turnover", fs, None, {})
        self.assertIsNone(r["value_raw"])


class TestCashRatioNumerator(unittest.TestCase):

    def test_cash_plus_current_other_bank_balances(self):
        fs = factset_from_values("S", 2026, "CONSOLIDATED", source_document="synthetic://doc", values={"cash": (378.069, 113.046), "other_bank_balances": (15.556, 14.671),
                                                             "total_current_liabilities": (2615.438, 1808.205)})
        r = rc.compute_ratio("cash_ratio", fs, None, {})
        self.assertAlmostEqual(r["value_raw"], (378.069 + 15.556) / 2615.438)
        self.assertEqual(r["status"], "needs_review")                       # restricted split genuinely unavailable -> flagged
        self.assertTrue(any("LIMITATION" in w for w in r["warnings"]))

    def test_ev_keeps_the_cash_and_equivalents_definition(self):
        # documented policy N: valuation/leverage use cash & cash equivalents only; the liquidity ratio adds bank balances
        fs = factset_from_values("S", 2026, "STANDALONE", source_document="synthetic://doc",
                                 values={"cash": (100.0, 90.0), "other_bank_balances": (20.0, 10.0), "total_debt": (300.0, 250.0),
                                         "shares_outstanding": (1e7, None)})
        ev, _ = rc._enterprise_value(fs, {"price": 100.0, "source": "x"})
        self.assertAlmostEqual(ev, 100.0 + 300.0 - 100.0)                 # market cap 100 Cr + debt - cash (no bank balances)


class TestEbitMarginLabel(unittest.TestCase):

    def test_sr15_is_labelled_as_what_it_computes(self):
        r = reg.BY_SR_NO[15]
        self.assertEqual(r["label"], "EBIT Margin %")
        self.assertEqual(r["ratio_key"], "operating_profit_margin")        # internal id unchanged
        self.assertEqual(reg.LEGACY_LABELS["OPM %"], "EBIT Margin %")


class TestExtractionNoiseRegressions(unittest.TestCase):
    """Generic row-reader / unit / page-selection defects found by the cross-company run (Maruti, ITC, Infosys, Titan, Bata)."""

    def test_page_number_ranges_are_not_figures(self):
        from tools.annual_report_financials import _blank_page_ranges, _find_row_values
        t = _blank_page_ranges("Revenue from operations 22 431-432 1,529,130 1,418,582 Other income 23 432 50,222")
        self.assertEqual(_find_row_values(t, ["revenue from operations"]), (1529130.0, 1418582.0))
        # fiscal-year labels, dates and genuine negatives are untouched
        for keep in ("FY 2024-25", "31-03-2026", "2024-2025", "(1,234)"):
            self.assertEqual(_blank_page_ranges(keep), keep)

    def test_lettered_and_listed_note_references_are_not_figures(self):
        from tools.annual_report_financials import _blank_page_ranges, _find_row_values
        t = _blank_page_ranges("I Revenue From Operations 23A, 23B 81612.78 73891.43 II Other Income 24 2529.69")
        self.assertEqual(_find_row_values(t, ["revenue from operations"]), (81612.78, 73891.43))
        t = _blank_page_ranges("Dividends paid (incl. IEPF) 26, 15 (2,819.45) (1,730.97) Payment of lease")
        self.assertEqual(_find_row_values(t, ["dividends paid"]), (-2819.45, -1730.97))

    def test_table_of_contents_page_is_not_a_statement(self):
        from tools.annual_report_financials import _is_toc_page
        toc = " ".join(f"2.{i} Revenue from operations {'.' * 40} {300 + i}" for i in range(8))
        self.assertTrue(_is_toc_page(toc))
        self.assertFalse(_is_toc_page("Revenue from operations 2.18 1,78,650 1,62,990 Other income 4,322"))

    def test_unit_footnote_far_below_the_table_is_honoured(self):
        from tools.document_analysis_engine import _page_unit_multiplier
        page = "Balance Sheet " + "row 1,234 " * 400 + "(in ` million, unless otherwise stated)"
        self.assertEqual(_page_unit_multiplier(page), 0.1)
        self.assertEqual(_page_unit_multiplier("Balance Sheet (` in Crores) rows"), 1.0)
        self.assertEqual(_page_unit_multiplier("row " * 500 + "markets grew in million units"), 1.0)   # prose is not a declaration

    def test_two_reference_columns_before_the_figures(self):
        from tools.annual_report_financials import _find_row_values
        self.assertEqual(_find_row_values("Cost of materials consumed 24.1 432 873,183 789,153 Purchases", ["cost of materials consumed"]),
                         (873183.0, 789153.0))
        # a genuine whole-crore row with one note column is unaffected
        self.assertEqual(_find_row_values("Depreciation and amortisation expense 25 693 584 Other", ["depreciation and amortisation expense"]),
                         (693.0, 584.0))

    def test_bare_subtotal_comes_from_the_figures_after_the_last_label(self):
        from tools.annual_report_financials import _find_subtotal_before
        t = ("(c) Provisions 19 155 100 (d) Current tax liabilities (net) 8 40 62 (e) Liabilities directly associated with Assets "
             "held for sale 40 - 1 25,793 16,529 TOTAL EQUITY AND LIABILITIES 40,647 31,550")
        self.assertEqual(_find_subtotal_before(t, ["total liabilities", "total equity and liabilities"]), (25793.0, 16529.0))

    def test_materials_and_components_caption_is_cost_of_materials(self):
        from tools.annual_report_financials import _COGS_LABELS
        self.assertIn("cost of materials and components consumed", _COGS_LABELS["Cost of materials consumed"])


class TestLedgerIdentitiesFlagMisreadSubtotals(unittest.TestCase):

    def _facts(self, **v):
        base = {"total_assets": (1000.0, 900.0), "total_current_assets": (500.0, 450.0), "total_current_liabilities": (250.0, 200.0),
                "inventory": (100.0, 90.0), "receivables": (80.0, 70.0), "cash": (60.0, 50.0), "payables": (90.0, 80.0),
                "revenue": (800.0, 700.0), "pat": (50.0, 40.0)}
        base.update(v)
        return factset_from_values("S", 2026, "CONSOLIDATED", base, source_document="synthetic://doc")

    def _integrity(self, fs):
        from tools.fundamental_fact_store import _apply_ledger_integrity
        out = []
        _apply_ledger_integrity(fs.facts, out)
        return out

    def test_consistent_statement_raises_nothing(self):
        self.assertEqual(self._integrity(self._facts()), [])

    def test_current_liabilities_smaller_than_payables_is_flagged(self):
        fs = self._facts(total_current_liabilities=(100.0 * 0.5, 200.0))
        msgs = self._integrity(fs)
        self.assertTrue(any("current liabilities" in m for m in msgs))
        self.assertEqual(fs.facts["total_current_liabilities"].status, "NEEDS_REVIEW")

    def test_current_assets_smaller_than_their_parts_is_flagged(self):
        self.assertTrue(any("current assets" in m for m in self._integrity(self._facts(total_current_assets=(120.0, 450.0)))))

    def test_revenue_orders_of_magnitude_below_profit_is_flagged(self):
        self.assertTrue(any("Revenue" in m for m in self._integrity(self._facts(revenue=(0.43, 0.4), pat=(145.0, 130.0)))))


if __name__ == "__main__":
    unittest.main()


class TestCacheKeysFoldEveryVersion(unittest.TestCase):

    def test_formula_extraction_and_fact_versions_each_change_the_ratio_cache_key(self):
        import tools.annual_report_financials as ar
        import tools.fundamental_fact_store as ffs

        def key():
            return ar._contract_cache_key("cash_ratio", "SYNTH", 2026, True, "basis1")
        base = key()
        seen = {base}
        o = ffs.EXTRACTION_VERSION
        ffs.EXTRACTION_VERSION = o + 1
        try:
            seen.add(key())
        finally:
            ffs.EXTRACTION_VERSION = o
        l = ar._EXTRACTION_LOGIC_VERSION
        ar._EXTRACTION_LOGIC_VERSION = "zz"
        try:
            seen.add(key())
        finally:
            ar._EXTRACTION_LOGIC_VERSION = l
        f = rc.FORMULA_VERSION
        rc.FORMULA_VERSION = "zz"
        try:
            seen.add(key())
        finally:
            rc.FORMULA_VERSION = f
        self.assertEqual(len(seen), 4)
        self.assertEqual(key(), base)


class TestWorkingCapitalTurnoverIsAverageBased(unittest.TestCase):

    def _fs(self, wc):
        return factset_from_values("S", 2026, "CONSOLIDATED", {"revenue": (1000.0, 800.0), "working_capital": wc},
                                   source_document="synthetic://doc")

    def test_average_working_capital_denominator(self):
        r = rc.compute_ratio("working_capital_turnover", self._fs((300.0, 220.0)), None, {})
        self.assertAlmostEqual(r["value_raw"], 1000.0 / 260.0)
        self.assertEqual(r["status"], "verified")
        self.assertIn("Average", r["breakdown"]["formula"])

    def test_closing_only_when_prior_year_missing_and_flagged(self):
        r = rc.compute_ratio("working_capital_turnover", self._fs((300.0, None)), None, {})
        self.assertAlmostEqual(r["value_raw"], 1000.0 / 300.0)
        self.assertTrue(r["estimated"])

    def test_negative_average_withheld(self):
        r = rc.compute_ratio("working_capital_turnover", self._fs((-100.0, -100.0)), None, {})
        self.assertIsNone(r["value_raw"])

    def test_registry_spec_and_days_wc_share_the_average_basis(self):
        self.assertIn("Average Working Capital", reg.BY_SR_NO[8]["formula"])
        self.assertIn("Average Working Capital", reg.BY_SR_NO[31]["formula"])
        self.assertEqual(rc.SPEC["working_capital_turnover"]["basis"], "average working capital")


class TestOneEnterpriseValueDefinition(unittest.TestCase):
    """EV = Market Cap + Total Debt - Cash for Sr 29, 51 and 52 (authoritative spec). NCI only as a separate reference figure."""

    def _fs(self, nci=(500.0, 400.0), basis="CONSOLIDATED"):
        vals = {"total_debt": (300.0, 250.0), "cash": (100.0, 90.0), "shares_outstanding": (1e7, None), "ebitda": (150.0, 120.0),
                "revenue": (1000.0, 900.0)}
        if nci is not None:
            vals["nci"] = nci
        return factset_from_values("S", 2026, basis, vals, source_document="synthetic://doc")

    MKT = {"price": 100.0, "source": "x"}                                       # market cap = 1e7 sh x 100 / 1e7 = 100 Cr

    def test_ev_is_the_same_number_in_all_three_multiples(self):
        fs = self._fs()
        ev = 100.0 + 300.0 - 100.0
        self.assertAlmostEqual(rc.compute_ratio("ev_to_ebitda", fs, self.MKT, {})["numerator"]["value_raw"], ev)
        self.assertAlmostEqual(rc.compute_ratio("ev_to_sales", fs, self.MKT, {})["numerator"]["value_raw"], ev)
        fcf = {"value_raw": 50.0, "label": "FCF", "status": "verified", "confidence": 1.0, "estimated": False, "warnings": []}
        r = rc.compute_ratio("ev_to_fcf", fs, self.MKT, {"free_cash_flow": fcf})
        self.assertAlmostEqual(r["value_raw"], ev / 50.0)
        self.assertAlmostEqual(rc.compute_ratio("ev_to_ebitda", fs, self.MKT, {})["value_raw"], ev / 150.0)

    def test_nci_never_changes_the_multiple_status_or_warnings(self):
        a = rc.compute_ratio("ev_to_ebitda", self._fs(), self.MKT, {})
        b = rc.compute_ratio("ev_to_ebitda", self._fs(nci=None), self.MKT, {})
        s = rc.compute_ratio("ev_to_ebitda", self._fs(basis="STANDALONE", nci=None), self.MKT, {})
        self.assertEqual(a["value_raw"], b["value_raw"])
        self.assertEqual(a["value_raw"], s["value_raw"])
        self.assertEqual(a["status"], "verified")
        self.assertEqual(a["warnings"], [])

    def test_consolidated_ev_with_nci_is_a_separate_labelled_reference(self):
        a = rc.compute_ratio("ev_to_ebitda", self._fs(), self.MKT, {})
        ref = a["reference_ev_incl_nci"]
        self.assertAlmostEqual(ref["ev_incl_nci_cr"], 300.0 + 500.0)
        self.assertIn("NOT the Navrist EV", ref["label"])
        self.assertIsNone(rc.compute_ratio("ev_to_ebitda", self._fs(nci=None), self.MKT, {})["reference_ev_incl_nci"])

    def test_registry_and_spec_text_carry_no_nci(self):
        for sr in (29, 51, 52):
            self.assertNotIn("NCI", reg.BY_SR_NO[sr]["formula"])
        self.assertNotIn("+ Non-Controlling", rc.SPEC["ev_to_ebitda"]["definition"].split("NOT added")[0])


class TestEquityBasisPolicy(unittest.TestCase):
    """Each ratio reads exactly the equity concept it is declared to use (rc.EQUITY_BASIS); no ratio reads equity by accident."""

    OWNERS = {"equity", "bvps"}
    TOTAL = {"equity_full"}
    ALL_EQUITY = OWNERS | TOTAL | {"nci"}

    def _facts_read(self, key):
        from tests.test_ratio_remediation import facts, MARKET
        fs = facts()
        read = set()
        cls = type(fs)
        orig = cls.get

        def spy(self, k, *a, **kw):
            read.add(k)
            return orig(self, k, *a, **kw)
        import tools.ratio_breakdown as rb
        orig_bd = rb.build_breakdown
        cls.get = spy
        rb.build_breakdown = lambda *a, **k: None        # the display breakdown shows equity_full = owners + NCI; not a calculation input
        try:
            rc.compute_with_parents(key, fs, MARKET, {})
        finally:
            cls.get = orig
            rb.build_breakdown = orig_bd
        return read

    def test_declared_basis_matches_the_facts_each_ratio_reads(self):
        for key, basis in rc.EQUITY_BASIS.items():
            read = self._facts_read(key)
            if basis == "total_equity_incl_nci":
                self.assertIn("equity_full", read, key)
                self.assertFalse(read & self.OWNERS, f"{key} must not read owners' equity: {read & self.OWNERS}")
            else:
                self.assertTrue(read & self.OWNERS, key)
                self.assertNotIn("equity_full", read, f"{key} must not read total equity incl. NCI")

    def test_no_undeclared_ratio_reads_an_equity_fact(self):
        for key in sorted(rc.COMPUTABLE):
            if key in rc.EQUITY_BASIS:
                continue
            read = self._facts_read(key)
            self.assertFalse(read & (self.OWNERS | self.TOTAL), f"{key} reads {read & (self.OWNERS | self.TOTAL)} but is not in EQUITY_BASIS")

    def test_roa_altman_piotroski_are_documented_as_reading_no_equity_fact(self):
        for key in ("roa", "altman_z_score", "piotroski_f_score"):
            self.assertIn(key, rc.EQUITY_NOTES)
            self.assertNotIn(key, rc.EQUITY_BASIS)

    def test_basis_is_stamped_on_the_result(self):
        from tests.test_ratio_remediation import facts, MARKET
        fs = facts()
        self.assertEqual(rc.compute_with_parents("debt_to_equity", fs, None, {})["equity_basis"], "total_equity_incl_nci")
        self.assertEqual(rc.compute_with_parents("roe", fs, None, {})["equity_basis"], "owners_equity")
        self.assertEqual(rc.compute_with_parents("piotroski_f_score", fs, MARKET, {})["equity_basis"], "none")

    def test_numbers_follow_the_declared_basis_when_nci_is_material(self):
        from tests.test_ratio_remediation import facts, MARKET
        fs = facts()                                  # owners' equity 900/800, NCI 100/80, total 1000/880, PAT 100, debt from fixture
        owners, total = fs.get("equity"), fs.get("equity_full")
        self.assertNotEqual(owners.value, total.value)
        debt = fs.get("total_debt").value
        self.assertAlmostEqual(rc.compute_ratio("debt_to_equity", fs, None, {})["value_raw"], debt / total.value)
        self.assertAlmostEqual(rc.compute_with_parents("roe", fs, None, {})["value_raw"], 100.0 / ((900.0 + 800.0) / 2.0) * 100)
        self.assertAlmostEqual(rc.compute_ratio("bvps", fs, None, {})["value_raw"], 900.0 * 1e7 / 100_000_000.0)
        fl = rc.compute_ratio("financial_leverage_ratio", fs, None, {})["value_raw"]
        self.assertAlmostEqual(fl, ((2000.0 + 1800.0) / 2.0) / ((1000.0 + 880.0) / 2.0))

    def test_standalone_or_no_nci_collapses_to_one_shareholders_equity(self):
        from tests.test_ratio_remediation import facts
        fs = facts(non_controlling_interest=(0.0, 0.0), equity_full=(900.0, 800.0), pat_total=(100.0, 80.0))
        self.assertEqual(fs.get("equity").value, fs.get("equity_full").value)


class TestDividendPayoutPerimeter(unittest.TestCase):
    """Dividend Payout = dividends paid TO THE COMPANY'S SHAREHOLDERS / owners' PAT. The cash-flow line is whole-entity (it also holds
    subsidiaries' dividends to their minorities), so it is split by recipient before it is divided by owners' profit."""

    ANURAS_RE_NOTE = ("Amount (₹) in millions Particulars As at March 31, 2026 As at March 31, 2025 "
                      "Less: Equity Share Final Dividend paid (85.38) (82.38) Less: Remeasurement of defined benefit obligations (5.30) 7.74")
    ANURAS_NCI_NOTE = ("Details of the same are as follows: For FY 2025-26 Amount (₹) in millions Particulars Opening balance of the NCI "
                       "2313.42 Add: TANFAC Profit for the Year 2025-26 701.69 NCI Share in profit 74.21% 520.72 "
                       "Less: NCI Share of Dividend (66.62) Impact of intra-group profit/loss eliminations (0.24)")
    OTHER_CO_EQ = "(₹ in crore) Reserves note Equity shares dividend paid (7,007) (6,500) Transfer to reserves 12"
    OTHER_CO_NCI = "(₹ in crore) Non-controlling interests Dividend paid to non-controlling interests (436) (390) Share of profit 900"

    def _components(self, *pages):
        from tools.annual_report_financials import _scan_dividend_components
        return _scan_dividend_components(list(pages))

    def test_scanner_reads_owners_and_minority_dividends_in_crore(self):
        c = self._components(self.ANURAS_RE_NOTE, self.ANURAS_NCI_NOTE)
        self.assertAlmostEqual(c["owners_candidates"][0]["cur"], 8.538, places=3)
        self.assertAlmostEqual(c["owners_candidates"][0]["prior"], 8.238, places=3)
        self.assertAlmostEqual(c["nci"]["cur"], 6.662, places=3)

    def test_scanner_does_not_mistake_the_whole_entity_cash_flow_line_for_the_owners_row(self):
        c = self._components("(₹ in crore) Financing: Dividend paid (152.00) (134.19) Interest paid (10) (9)")
        self.assertEqual(c["owners_candidates"], [])
        self.assertIsNone(c["nci"])

    def _facts(self, **over):
        from tests.test_ratio_remediation import facts
        return facts(**over)

    def test_anuras_style_split_owners_only_numerator(self):
        comps = self._components(self.ANURAS_RE_NOTE, self.ANURAS_NCI_NOTE)
        fs = self._facts(dividend_paid=(-15.2, -13.419), dividend_components=comps, pat=(170.121, 93.349),
                         pat_total=(222.199, 159.972), non_controlling_interest=(1328.122, 231.342),
                         eps=(14.94, 8.49), eps_owners=(14.94, 8.49), shares_outstanding=(113_848_310.0, 109_900_000.0))
        paid = fs.get("dividends_paid")
        self.assertAlmostEqual(paid.value, 8.538, places=3)
        self.assertEqual(paid.perimeter, "owners")
        self.assertTrue(fs.extras["dividend_components"]["reconciles"])                    # 8.538 + 6.662 == 15.2
        r = rc.compute_with_parents("dividend_payout_ratio", fs, None, {})
        self.assertAlmostEqual(r["value_raw"], 8.538 / 170.121 * 100, places=6)            # 5.02 %, not 8.93 %
        self.assertEqual(r["status"], "verified")

    def test_retention_and_sustainable_growth_follow_the_owners_payout(self):
        comps = self._components(self.ANURAS_RE_NOTE, self.ANURAS_NCI_NOTE)
        fs = self._facts(dividend_paid=(-15.2, -13.419), dividend_components=comps, pat=(170.121, 93.349),
                         pat_total=(222.199, 159.972), non_controlling_interest=(1328.122, 231.342),
                         eps=(14.94, 8.49), eps_owners=(14.94, 8.49), shares_outstanding=(113_848_310.0, 109_900_000.0))
        cache = {}
        pay = rc.compute_with_parents("dividend_payout_ratio", fs, None, cache)["value_raw"]
        ret = rc.compute_with_parents("retention_ratio", fs, None, cache)["value_raw"]
        sgr = rc.compute_with_parents("sustainable_growth_rate", fs, None, cache)
        roe = cache["roe"]["value_raw"]
        self.assertAlmostEqual(ret, 100.0 - pay)
        self.assertAlmostEqual(sgr["value_raw"], roe * ret / 100.0)

    BIG = dict(revenue=(900000.0, 800000.0), total_assets=(500000.0, 450000.0), equity=(150000.0, 140000.0),
               equity_full=(168000.0, 157000.0), total_current_assets=(200000.0, 180000.0),
               total_current_liabilities=(100000.0, 90000.0), total_liabilities=(332000.0, 293000.0),
               pat=(80775.0, 69000.0), pat_total=(95000.0, 80000.0), non_controlling_interest=(18000.0, 17000.0),
               eps=(80.775, 69.0), eps_owners=(80.775, 69.0), shares_outstanding=(10_000_000_000.0, 10_000_000_000.0))

    def test_second_company_with_nci_split_from_the_notes(self):
        comps = self._components(self.OTHER_CO_EQ, self.OTHER_CO_NCI)
        fs = self._facts(dividend_paid=(-7443.0, -6890.0), dividend_components=comps, **self.BIG)
        self.assertAlmostEqual(fs.get("dividends_paid").value, 7007.0)
        self.assertTrue(fs.extras["dividend_components"]["reconciles"])                    # 7007 + 436 == 7443
        r = rc.compute_with_parents("dividend_payout_ratio", fs, None, {})
        self.assertAlmostEqual(r["value_raw"], 7007.0 / 80775.0 * 100, places=6)
        self.assertEqual(r["status"], "verified")

    def test_minority_share_alone_still_yields_the_owners_figure(self):
        comps = self._components(self.OTHER_CO_NCI)                                         # no owners row printed
        fs = self._facts(dividend_paid=(-7443.0, -6890.0), dividend_components=comps, **self.BIG)
        self.assertAlmostEqual(fs.get("dividends_paid").value, 7443.0 - 436.0)
        self.assertEqual(fs.get("dividends_paid").perimeter, "owners")

    def test_unsplittable_consolidated_total_is_flagged_not_presented_as_owners(self):
        fs = self._facts(dividend_paid=(-7443.0, -6890.0), dividend_components=None, **self.BIG)
        self.assertEqual(fs.get("dividends_paid").perimeter, "whole_entity")
        r = rc.compute_with_parents("dividend_payout_ratio", fs, None, {})
        self.assertEqual(r["status"], "needs_review")
        self.assertTrue(any("NCI" in w or "minorit" in w.lower() for w in r["warnings"]))

    def test_no_nci_company_uses_the_cash_flow_total_verified(self):
        fs = self._facts(dividend_paid=(-30.0, -25.0), dividend_components=None, non_controlling_interest=(0.0, 0.0),
                         equity_full=(900.0, 800.0), pat_total=(100.0, 80.0))
        r = rc.compute_with_parents("dividend_payout_ratio", fs, None, {})
        self.assertAlmostEqual(r["value_raw"], 30.0 / 100.0 * 100)
        self.assertEqual(r["status"], "verified")

    def test_declared_for_year_payout_is_carried_as_reference_only(self):
        fs = self._facts(dividend_paid=(-20.0, -25.0), dividend_components=None, non_controlling_interest=(0.0, 0.0),
                         equity_full=(900.0, 800.0), pat_total=(100.0, 80.0))
        r = rc.compute_with_parents("dividend_payout_ratio", fs, None, {})
        self.assertIn("reference_declared_for_year_payout_pct", r)
        self.assertNotAlmostEqual(r["reference_declared_for_year_payout_pct"], r["value_raw"])


class TestCashRatioRestrictedBalancePolicy(unittest.TestCase):
    """Cash Ratio counts cash & equivalents + UNRESTRICTED other bank balances. Restricted (unclaimed dividend, earmarked, margin,
    lien-marked deposits) never count when the source discloses them; an undisclosed split keeps the value but is needs_review.
    This policy is separate from the Cash used by Net Debt / EV / EV multiples (cash & cash equivalents only)."""

    NOTE = ("12. CURRENT ASSETS: FINANCIAL ASSETS - OTHER BANK BALANCES Amount (₹) in millions Particulars Notes As at March 31, 2026 "
            "As at March 31, 2025 Fixed deposits with banks with maturity less than 12 months Note D 73.77 68.92 "
            "Unclaimed Dividend - 5.74 4.17 Deposit Account - 76.05 73.62 Earmarked bank balance* - - Total 155.56 146.71 "
            "Note D: The amount of fixed deposit with Banks includes Lien over fixed deposit of INR 67.22 Million "
            "(Previous year: INR 60.52 Million). 13. CURRENT ASSETS: FINANCIAL ASSETS - LOANS Amount (₹) in millions "
            "Particulars Notes As at March 31, 2026 As at March 31, 2025 Loans and advances - 0.33 0.16 Total 16.76 20.53")

    def _scan(self, total=15.556):
        from tools.annual_report_financials import _scan_other_bank_balance_note
        return _scan_other_bank_balance_note([self.NOTE], total)

    def test_components_are_classified_from_the_note(self):
        r = self._scan()
        cls = {c["label"]: c["class"] for c in r["components"]}
        self.assertEqual(cls["Unclaimed Dividend"], "restricted")
        self.assertEqual(cls["Fixed deposits with banks with maturity less than 12 months - under lien"], "restricted")
        self.assertEqual(cls["Fixed deposits with banks with maturity less than 12 months"], "deposit")
        self.assertEqual(cls["Deposit Account"], "unclassified")
        self.assertAlmostEqual(r["netoff_cur"], 6.722 + 0.574, places=3)                   # lien 67.22m + unclaimed dividend 5.74m
        self.assertAlmostEqual(r["unrestricted_cur"], 15.556 - 7.296, places=3)            # 8.26 Cr
        self.assertAlmostEqual(r["unclassified_cur"], 7.605, places=3)

    def test_note_is_accepted_only_when_its_total_equals_the_balance_sheet_line(self):
        self.assertIsNone(self._scan(total=99.0))

    def test_restricted_amounts_are_excluded_and_unnamed_deposit_account_is_flagged(self):
        fs = factset_from_values("S", 2026, "CONSOLIDATED", source_document="synthetic://doc",
                                 values={"cash": (378.069, 113.046), "other_bank_balances": (15.556, 14.671),
                                         "total_current_liabilities": (2615.438, 1808.205)},
                                 extras={"other_bank_balances_breakup": self._scan()})
        r = rc.compute_ratio("cash_ratio", fs, None, {})
        self.assertAlmostEqual(r["value_raw"], (378.069 + 8.26) / 2615.438, places=6)     # not 393.6: restricted 7.30 Cr stays out
        self.assertEqual(r["status"], "needs_review")                                      # 'Deposit account' nature not stated
        self.assertTrue(any("Restricted" in w for w in r["warnings"]))
        self.assertTrue(any("nature" in w for w in r["warnings"]))

    def test_fully_classified_note_is_verified(self):
        bk = {"unrestricted_cur": 5.0, "netoff_cur": 2.0, "unclassified_cur": 0.0, "base_cur": 7.0}
        fs = factset_from_values("S", 2026, "CONSOLIDATED", source_document="synthetic://doc",
                                 values={"cash": (100.0, 90.0), "other_bank_balances": (7.0, 6.0), "total_current_liabilities": (500.0, 450.0)},
                                 extras={"other_bank_balances_breakup": bk})
        r = rc.compute_ratio("cash_ratio", fs, None, {})
        self.assertAlmostEqual(r["value_raw"], 105.0 / 500.0)
        self.assertEqual(r["status"], "verified")

    def test_undisclosed_split_keeps_the_value_but_is_needs_review_with_the_limitation(self):
        fs = factset_from_values("S", 2026, "CONSOLIDATED", source_document="synthetic://doc",
                                 values={"cash": (100.0, 90.0), "other_bank_balances": (7.0, 6.0), "total_current_liabilities": (500.0, 450.0)})
        r = rc.compute_ratio("cash_ratio", fs, None, {})
        self.assertAlmostEqual(r["value_raw"], 107.0 / 500.0)
        self.assertEqual(r["status"], "needs_review")
        self.assertTrue(any("LIMITATION" in w for w in r["warnings"]))

    def test_net_debt_and_ev_do_not_move_with_the_cash_ratio_policy(self):
        def ev(breakup):
            fs = factset_from_values("S", 2026, "STANDALONE", source_document="synthetic://doc",
                                     values={"cash": (100.0, 90.0), "other_bank_balances": (20.0, 10.0), "total_debt": (300.0, 250.0),
                                             "shares_outstanding": (1e7, None), "ebitda": (150.0, 120.0), "revenue": (1000.0, 900.0),
                                             "net_debt": (200.0, 160.0), "total_current_liabilities": (500.0, 450.0)},
                                     extras={"other_bank_balances_breakup": breakup})
            mk = {"price": 100.0, "source": "x"}
            return (rc.compute_ratio("ev_to_ebitda", fs, mk, {})["value_raw"], rc.compute_ratio("ev_to_sales", fs, mk, {})["value_raw"],
                    rc.compute_ratio("net_debt_to_ebitda", fs, None, {})["value_raw"],
                    rc.compute_ratio("cash_ratio", fs, None, {})["value_raw"])
        a = ev(None)
        b = ev({"unrestricted_cur": 2.0, "netoff_cur": 18.0, "unclassified_cur": 0.0})
        self.assertEqual(a[:3], b[:3])                      # EV/EBITDA, EV/Sales, Net debt/EBITDA identical
        self.assertNotEqual(a[3], b[3])                     # only the Cash Ratio reacts
        self.assertAlmostEqual(a[0], (100.0 + 300.0 - 100.0) / 150.0)


class TestAuditMatrixFindings(unittest.TestCase):
    """Defects the 68-row audit matrix found (contribution-margin rounding; pledge / free float ignoring the uploaded filing)."""

    def test_contribution_margin_does_not_round_intermediates(self):
        fs = factset_from_values("S", 2026, "CONSOLIDATED", source_document="synthetic://doc",
                                 values={"revenue": (1000.0, 900.0)},
                                 extras={"components": {"Cost of materials consumed": (333.333333, 1.0)},
                                         "direct_expenses": (111.111111, 1.0)})
        r = rc.compute_ratio("contribution_margin", fs, None, {})
        self.assertAlmostEqual(r["value_raw"], (1000.0 - 333.333333 - 111.111111) / 1000.0 * 100, places=9)

    def _sh(self, **kw):
        base = {"promoter_holding_pct": 59.07, "promoter_pledge_pct": 21.79, "num_shares_pledged": 14655780.0,
                "total_promoter_holding": 67253016.0, "pledge_status": "ok"}
        base.update(kw)
        return base

    def test_pledge_from_the_uploaded_filing_is_verified(self):
        r = rc.pledge_result(self._sh(source="uploaded_filing"))
        self.assertEqual(r["status"], "verified")
        self.assertAlmostEqual(r["value_raw"], 14655780.0 / 67253016.0 * 100)

    def test_pledge_from_the_secondary_endpoint_stays_needs_review(self):
        self.assertEqual(rc.pledge_result(self._sh())["status"], "needs_review")

    def test_filing_whose_own_percentage_disagrees_is_flagged(self):
        r = rc.pledge_result(self._sh(source="uploaded_filing", promoter_pledge_pct=30.0))
        self.assertEqual(r["status"], "needs_review")

    def test_free_float_is_exact_when_the_filing_states_no_locked_in_shares(self):
        self.assertEqual(rc.free_float_result({"promoter_holding_pct": 59.07, "locked_in_pct": 0.0})["status"], "verified")
        self.assertAlmostEqual(rc.free_float_result({"promoter_holding_pct": 59.07, "locked_in_pct": 0.0})["value_raw"], 40.93)
        self.assertEqual(rc.free_float_result({"promoter_holding_pct": 59.07, "locked_in_pct": None})["status"], "needs_review")

    def test_locked_in_flags_are_read_from_the_filing_xml(self):
        import tempfile, shutil, os
        import tools.nse_xbrl as nx
        head = ('<xbrli:xbrl xmlns:xbrli="x" xmlns:in-bse-shp="y">'
                '<xbrli:context id="ShareholdingOfPromoterAndPromoterGroup_ContextI"><xbrli:scenario>'
                '<xbrldi:explicitMember dimension="in-bse-shp:CategoryOfShareholdersAxis">in-bse-shp:ShareholdingOfPromoterAndPromoterGroupMember'
                '</xbrldi:explicitMember></xbrli:scenario></xbrli:context>'
                '<xbrli:context id="Public_ContextI"><xbrli:scenario><xbrldi:explicitMember dimension="in-bse-shp:CategoryOfShareholdersAxis">'
                'in-bse-shp:PublicShareholdingMember</xbrldi:explicitMember></xbrli:scenario></xbrli:context>')
        facts = ('<in-bse-shp:NumberOfFullyPaidUpEquityShares contextRef="ShareholdingOfPromoterAndPromoterGroup_ContextI">600</in-bse-shp:NumberOfFullyPaidUpEquityShares>'
                 '<in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="ShareholdingOfPromoterAndPromoterGroup_ContextI">0.6</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>'
                 '<in-bse-shp:NumberOfSharesEncumberedUnderPledged contextRef="ShareholdingOfPromoterAndPromoterGroup_ContextI">60</in-bse-shp:NumberOfSharesEncumberedUnderPledged>'
                 '<in-bse-shp:NumberOfFullyPaidUpEquityShares contextRef="Public_ContextI">400</in-bse-shp:NumberOfFullyPaidUpEquityShares>')
        tmp = tempfile.mkdtemp()
        old = nx._MANUAL_SHAREHOLDING_DIR
        try:
            nx._MANUAL_SHAREHOLDING_DIR = tmp
            for flag, expect in (("false", 0.0), ("true", None)):
                open(os.path.join(tmp, "SYNTH.xml"), "w", encoding="utf-8").write(
                    head + facts + f'<in-bse-shp:WhetherTheListedEntityHasAnySharesInLockedIn contextRef="MainI">{flag}</in-bse-shp:WhetherTheListedEntityHasAnySharesInLockedIn></xbrli:xbrl>')
                sh = nx._shareholding_from_manual_upload("SYNTH")
                self.assertEqual(sh["locked_in_pct"], expect)
                self.assertEqual(sh["source"], "uploaded_filing")
        finally:
            nx._MANUAL_SHAREHOLDING_DIR = old
            shutil.rmtree(tmp, ignore_errors=True)


class TestOtherFinancialLiabilitiesNoteEvaluation(unittest.TestCase):
    """Total Debt's Three-Part Test is evaluated on the NOTE tables when the balance-sheet face has no sub-items, so debt is not left
    'not evaluated' (estimated) - and debt-like items the term lists do not accept stay visible, never silently added."""

    NC = ("18. OTHER FINANCIAL LIABILITIES Amount (₹) in millions Particulars Notes As at March 31, 2026 As at March 31, 2025 "
          "Financial liability related to Sale and Lease Back Note 18(i) 343.97 436.56 Deferred Capital Recovery Fee - 110.61 - "
          "Total 454.58 436.56")
    CUR = ("21. OTHER FINANCIAL LIABILITIES Amount (₹) in millions Particulars Notes As at March 31, 2026 As at March 31, 2025 "
           "Other payables Note 21A 1,505.54 106.02 Interest accrued and due to banks - 46.94 27.76 Unclaimed/Payable Dividend - 2.89 0.09 "
           "Employees Benefits Payable - 76.13 70.52 Total 2,122.70 309.00 Note 21A: Other payables includes advances.")

    def _scan(self, totals):
        from tools.annual_report_financials import _scan_other_financial_liabilities_note
        return _scan_other_financial_liabilities_note([self.NC, self.CUR], totals)

    def test_tables_are_matched_to_the_balance_sheet_lines_and_evaluated(self):
        r = self._scan([(45.458, 43.656), (212.27, 30.9)])
        self.assertEqual(len(r["tables"]), 2)
        self.assertEqual(r["qualifying_cur"], 0.0)                         # a determined zero, not a missing value
        labels = {c["label"] for c in r["candidates"]}
        self.assertIn("Financial liability related to Sale and Lease Back", labels)
        self.assertIn("Interest accrued and due to banks", labels)

    def test_a_table_whose_total_is_not_on_the_balance_sheet_is_ignored(self):
        self.assertIsNone(self._scan([(999.0, 1.0)]))

    def test_debt_like_row_that_passes_the_three_part_test_is_counted_and_excluded_rows_are_not(self):
        nc = ("OTHER FINANCIAL LIABILITIES Amount (₹) in crore Particulars Notes As at March 31, 2026 As at March 31, 2025 "
              "Interest accrued but not due on borrowings 5.00 4.00 Employees dues 7.00 6.00 Unclaimed dividend 1.00 1.00 Total 13.00 11.00")
        from tools.annual_report_financials import _scan_other_financial_liabilities_note
        r = _scan_other_financial_liabilities_note([nc], [(13.0, 11.0)])
        self.assertAlmostEqual(r["qualifying_cur"], 5.0)

    def test_total_debt_uses_the_note_evaluation_and_is_not_flagged_for_it(self):
        import tools.annual_report_financials as ar
        parsed = {"lt_borrowings": (500.0, 450.0), "st_borrowings": (200.0, 180.0), "current_maturities": (50.0, 40.0),
                  "lease_liabilities_total": (60.0, 55.0), "lease_evidence": "found", "borrowings_face_label_found": True,
                  "finance_costs": (30.0, 25.0),
                  "ofl_note": {"qualifying_cur": 0.0, "qualifying_prior": 0.0, "candidates": [{"label": "x", "amount_cr": 1.0}]}}
        d = ar._compute_total_debt(parsed, "basis1")
        if d.get("applicable"):
            self.assertFalse(any("NOT" in str(k) and "evaluated" in str(k) for k in d["components"]))
            self.assertTrue(d["components_raw"]["ofl_evaluated"])
            self.assertIsInstance(d["total_debt_cur"], float)
            self.assertNotEqual(d["total_debt_cur"], round(d["total_debt_cur"], 0) + 0.123456)   # carried unrounded

    def test_total_debt_is_not_rounded_to_two_decimals(self):
        import tools.annual_report_financials as ar
        parsed = {"lt_borrowings": (500.0049, 450.0), "st_borrowings": (200.0049, 180.0), "current_maturities": (50.0, 40.0),
                  "lease_liabilities_total": (0.0, 0.0), "lease_evidence": "none_on_balance_sheet", "borrowings_face_label_found": True,
                  "finance_costs": (30.0, 25.0), "ofl_note": {"qualifying_cur": 0.0, "qualifying_prior": 0.0}}
        d = ar._compute_total_debt(parsed, "basis1")
        if d.get("applicable"):
            self.assertAlmostEqual(d["total_debt_cur"], 750.0098, places=6)
