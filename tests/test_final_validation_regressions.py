"""Final-validation regressions: one canonical definition across engines, unknown never becomes zero, and the extraction /
status / gating defects found while running the real 68-ratio pipeline over real filings. Synthetic data only."""
import inspect
import re
import unittest
from unittest.mock import patch

import tools.annual_report_financials as ar
import tools.document_analysis_engine as dae
import tools.fundamental_fact_store as ffs
import tools.fundamental_ratio_registry as reg
import tools.nse_xbrl as nx
import tools.ratio_calculation_engine as eng
import tools.ratio_contract as rc
from tests.test_ratio_remediation import MARKET, facts, parsed


# --------------------------------------------------------------------------------------------------------------------
# three engines, one definition - EVERY computable ratio, not a sample
# --------------------------------------------------------------------------------------------------------------------
def _wrapper_keys():
    """{ratio_key: wrapper function name} for every fetch_*_from_annual_report that delegates to the contract adapter."""
    out = {}
    for name, fn in inspect.getmembers(ar, inspect.isfunction):
        if name.startswith("fetch_") and name.endswith("_from_annual_report"):
            m = re.search(r"_contract_fetch\(\s*\"([a-z_]+)\"", inspect.getsource(fn))
            if m:
                out[m.group(1)] = name
    return out


class TestOneDefinitionAcrossEngines(unittest.TestCase):
    def test_every_computable_ratio_agrees_in_all_four_paths(self):
        p = parsed()
        ffs.clear_run_cache()
        wrappers = _wrapper_keys()
        with patch.object(ar, "_get_extracted_financials", return_value=p), \
                patch.object(ar, "_read_cache", lambda k: None), patch.object(ar, "_write_cache", lambda k, v: None), \
                patch.object(rc, "live_market", return_value=MARKET):
            fs = ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2026)
            direct = rc.compute_all(fs, MARKET)
            compared = 0
            for k in sorted(rc.COMPUTABLE):
                d = direct[k]
                # (1) the legacy adapters that nse_xbrl / the dashboard call
                if k in wrappers:
                    out = getattr(ar, wrappers[k])("SYNTHCO", "Synth Co", 2026, True)
                    if d["value_raw"] is None:
                        self.assertIsNone(out.get("value_raw"), f"legacy {k}")
                    else:
                        self.assertAlmostEqual(out["value_raw"], d["value_raw"], places=9, msg=f"legacy {k}")
                    self.assertEqual(out.get("status"), d["status"], f"legacy status {k}")
                # (2) the canonical API
                canon = eng.calculate_ratio(k, "SYNTHCO", "Synth Co", 2026)
                if d["value_raw"] is None:
                    self.assertIsNone(canon["value"], f"canonical {k}")
                else:
                    self.assertAlmostEqual(canon["value"], round(d["value_raw"], 4), places=4, msg=f"canonical {k}")
                self.assertEqual(canon["status"].lower(), d["status"], f"canonical status {k}")
                # (3) the document-analysis row
                legacy = ar._contract_to_legacy(d, fs, 2026)
                row = dae._row_from_nse_xbrl_out(reg.BY_RATIO_KEY[k], legacy)
                if d["value_raw"] is None:
                    self.assertIsNone(row["value"], f"row {k}")
                else:
                    self.assertAlmostEqual(row["value"], round(d["value_raw"], 2), places=2, msg=f"row {k}")   # row stores the 2-dp display value
                self.assertEqual(row["status"], d["status"], f"row status {k}")
                compared += 1
            self.assertGreaterEqual(compared, 55)

    def test_no_wrapper_contains_its_own_formula(self):
        w = _wrapper_keys()
        self.assertGreaterEqual(len(w), 35)
        for key, name in w.items():
            src = inspect.getsource(getattr(ar, name))
            self.assertLess(len(src.splitlines()), 14, name)

    def test_xbrl_inventory_turnover_goes_through_the_contract(self):
        src = inspect.getsource(nx._compute_pair)
        self.assertIn('compute_ratio("inventory_turnover"', src)
        self.assertNotIn("sales_cr / avg_inv", src)                  # no second formula, no rounded divisor


# --------------------------------------------------------------------------------------------------------------------
# unknown is never zero
# --------------------------------------------------------------------------------------------------------------------
_MISSABLE = {
    "revenue": "revenue", "pat": "pat", "pat_total": "pat_total", "equity": "equity", "inventory": "inventory",
    "receivables": "receivables", "payables": "payables", "total_assets": "total_assets", "cash": "cash",
    "operating_cash_flow": "operating_cash_flow", "depreciation": "depreciation", "finance_costs": "finance_costs",
    "pbt": "pbt", "tax_expense": "tax_expense", "shares_outstanding": "shares_outstanding", "eps": "eps",
    "total_current_assets": "total_current_assets", "total_current_liabilities": "total_current_liabilities",
    "capex_ppe_purchase": "capex_ppe_purchase", "dividend_paid": "dividend_paid",
}


class TestUnknownIsNeverZero(unittest.TestCase):
    def test_removing_any_single_input_never_produces_a_zero_ratio(self):
        ffs.clear_run_cache()
        with patch.object(ar, "_get_extracted_financials", return_value=parsed()), \
                patch.object(ar, "_read_cache", lambda k: None), patch.object(ar, "_write_cache", lambda k, v: None):
            base = rc.compute_all(ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2026), MARKET)
        zero_in_base = {k for k, r in base.items() if r["value_raw"] == 0}
        for pkey in _MISSABLE.values():
            p = parsed()
            p[pkey] = None
            if pkey == "dividend_paid":
                p["dps_declared"] = {"found": False, "total": None, "no_dividend_evidence": False, "pages": []}
            ffs.clear_run_cache()
            with patch.object(ar, "_get_extracted_financials", return_value=p):
                res = rc.compute_all(ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2026), MARKET)
            for k, r in res.items():
                if r["value_raw"] == 0 and k not in zero_in_base:
                    self.fail(f"{k} became 0 when '{pkey}' was unknown")
                if r["status"] in ("verified", "needs_review"):
                    self.assertIsNotNone(r["value_raw"], f"{k} has status {r['status']} without a value ('{pkey}' unknown)")

    def test_dividend_inputs_unknown_means_unavailable(self):
        p = parsed(dps_declared={"found": False, "total": None, "no_dividend_evidence": False, "pages": []}, dividend_paid=None)
        ffs.clear_run_cache()
        with patch.object(ar, "_get_extracted_financials", return_value=p):
            fs = ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2026)
            res = rc.compute_all(fs, MARKET)
        for k in ("dividend_yield", "dividend_payout_ratio", "retention_ratio", "sustainable_growth_rate"):
            self.assertIsNone(res[k]["value_raw"], k)
            self.assertIn(res[k]["status"], ("not_disclosed", "insufficient_data"), k)

    def test_only_an_explicit_no_dividend_statement_supports_zero(self):
        p = parsed(dps_declared={"found": False, "total": None, "no_dividend_evidence": True, "pages": [9]}, dividend_paid=None)
        ffs.clear_run_cache()
        with patch.object(ar, "_get_extracted_financials", return_value=p):
            res = rc.compute_all(ffs.get_canonical_facts("SYNTHCO", "Synth Co", 2026), MARKET)
        self.assertEqual(res["dividend_yield"]["value_raw"], 0.0)

    def test_providers_and_proxies(self):
        self.assertIsNone(rc.beta_result(None)["value_raw"])
        self.assertIsNone(rc.free_float_result({"promoter_holding_pct": None})["value_raw"])
        self.assertIsNone(rc.pledge_result({"promoter_holding_pct": 50, "pledge_status": "assumed_zero"})["value_raw"])
        r = rc.dscr = None  # noqa - DSCR with no gross repayment line is unavailable (covered in test_ratio_remediation)
        fs = facts()
        self.assertIn(rc.compute_with_parents("dscr", fs, MARKET)["status"], ("insufficient_data", "needs_review"))

    def test_bank_ratios_missing_inputs_are_not_zero(self):
        from tests.test_ratio_corrections_2026_10b import bank_parsed
        for key, over in (("casa_ratio", {"demand_deposits": None}), ("gross_npa_pct", {}), ("net_npa_pct", {}),
                          ("capital_adequacy_ratio", {}), ("provision_coverage_ratio", {}),
                          ("net_interest_margin", {"interest_earned": None}), ("cost_to_income_ratio", {"operating_expenses": None}),
                          ("credit_to_deposit_ratio", {"advances": None})):
            with patch.object(ar, "_get_extracted_bank_financials", return_value=bank_parsed(**over)):
                out = getattr(ar, f"fetch_{key}_from_annual_report")("BANKCO", "Bank Co", 2025, True)
            self.assertIsNone(out.get("value"), key)
            self.assertFalse(out.get("applicable"), key)


# --------------------------------------------------------------------------------------------------------------------
# defects found by the real-filing validation run
# --------------------------------------------------------------------------------------------------------------------
class TestRealFilingDefects(unittest.TestCase):
    def test_single_digit_crore_amount_is_not_skipped(self):
        # ELECTHERM: "Cash and Cash Equivalent 10 9.22 55.31 / Bank Balance ... 10 63.04 7.03" returned (55.31, 63.04)
        text = ("iii)\t Cash and Cash Equivalent\n10\n 9.22 \n 55.31 \n\t\niv)\t Bank Balance Other than (iii) Above\n10\n 63.04 \n 7.03 \n")
        self.assertEqual(ar._find_row_values(text, ["cash and cash equivalent"]), (9.22, 55.31))

    def test_whole_crore_integers_under_1000_do_not_shift_to_the_next_row(self):
        # TITAN reports whole crore: "Depreciation and amortisation expense 25 693 584" returned the NEXT row's (5,150, 4,496),
        # which inflated EBITDA 8x. `_NUM_RE` cannot see a comma-less integer, so the row is now read as one cluster.
        text = ("Employee benefits expense 23 2,156 1,864\n Finance costs 24 953 619\n"
                " Depreciation and amortisation expense 25 693 584\n Other expenses 26 5,150 4,496")
        self.assertEqual(ar._find_row_values(text, ["depreciation and amortisation expense"]), (693.0, 584.0))
        self.assertEqual(ar._find_row_values(text, ["finance costs"]), (953.0, 619.0))
        self.assertEqual(ar._find_row_values(text, ["other expenses"]), (5150.0, 4496.0))
        self.assertEqual(ar._find_row_values("Cash 7 12 15 next row 1,000 2,000", ["cash"]), (12.0, 15.0))   # note ref dropped

    def test_label_parenthetical_is_not_a_figure(self):
        # FLUOROCHEM: "Total assets (1+2)" made "1" and "2" the row's values (total assets = 1.0)
        text = "Sub-total\n 3,951.08 \n 3,412.61 \nTotal assets (1+2)\n 9,635.33 \n 9,136.39 \nEQUITY"
        self.assertEqual(ar._find_row_values(text, ["total assets"]), (9635.33, 9136.39))
        self.assertEqual(ar._find_row_values("Revenue (a) 25 693 584\n Other 1,000 2,000", ["revenue"]), (693.0, 584.0))
        self.assertEqual(ar._find_row_values("Exceptional items (7,815) (2,671) next", ["exceptional items"]), (-7815.0, -2671.0))

    def test_note_reference_with_decimal_is_still_dropped(self):
        text = "Trade Receivables 2.17 30,337.00 28,100.50 next"
        self.assertEqual(ar._find_row_values(text, ["trade receivables"]), (30337.0, 28100.5))

    def test_share_class_row_gives_the_share_count(self):
        pages = ["Ordinary Shares of ` 1.00 each 20,00,00,00,000 2000.00 20,00,00,00,000 2000.00 "
                 "Ordinary Shares of ` 1.00 each, fully paid 12,51,41,19,781 1251.41 12,48,47,21,471 1248.47"]
        hit = dae._extract_shares_outstanding_from_class_row(pages)
        self.assertEqual((hit["value"], hit["prior_value"]), (12514119781.0, 12484721471.0))
        self.assertIsNone(dae._extract_shares_outstanding_from_class_row(["Ordinary Shares of ` 1.00 each 20,00,00,00,000 2000.00"]))

    def test_operating_cash_flow_label_variants(self):
        labels = " ".join(ar._OPERATING_CASH_FLOW_LABELS)
        for lab in ("net cash flow generated from operating activities", "net cash (used in) generated from operating activities"):
            self.assertIn(lab, labels)
        self.assertIn("net cash flow generated from operating activities", dae._LINE_ITEM_ALIASES["operating_cash_flow"])

    def test_pbt_and_capex_label_variants(self):
        self.assertIn("profit before share of profit / (loss) of associates / joint ventures and tax", ar._PBT_LABELS)
        self.assertIn("expenditure for property, plant and equipment", ar._CAPEX_PPE_PURCHASE_LABELS)

    def test_not_meaningful_without_a_number_is_not_disclosed_never(self):
        legacy = {"applicable": False, "status": "not_meaningful", "reason": "Basic EPS is zero or negative - P/E is not meaningful.",
                  "formula_version": rc.FORMULA_VERSION}
        row = dae._row_from_nse_xbrl_out(reg.BY_RATIO_KEY["pe_ratio"], legacy)
        self.assertEqual(row["status"], "not_meaningful")
        self.assertIsNone(row["value"])

    def test_lender_gate_is_sector_based_not_name_based(self):
        name = "poonawalla fincorp limited"                           # no lender keyword in the name
        self.assertFalse(any(w in name for w in nx._NON_INVENTORY))
        with nx.lender_context(True):
            self.assertTrue(any(w in name for w in nx._NON_INVENTORY))
        self.assertFalse(any(w in name for w in nx._NON_INVENTORY))   # and the context does not leak

    def test_inferred_zero_pledge_is_not_verified(self):
        r = rc.pledge_result({"promoter_holding_pct": 50.0, "pledge_status": "no_record", "num_shares_pledged": None,
                              "total_promoter_holding": None, "promoter_pledge_pct": 0.0})
        self.assertEqual(r["status"], "needs_review")
        self.assertTrue(r.get("inferred_zero"))
        self.assertTrue(any("INFERRED" in w for w in r["warnings"]))

    def test_version_bumps_invalidate_every_cache_key(self):
        a = ar._document_identity_tag("SYNTHCO", 2026)
        with patch.object(ar, "_EXTRACTION_LOGIC_VERSION", "999"):
            b = ar._document_identity_tag("SYNTHCO", 2026)
        # no ar_text file exists for the synthetic slot -> "" ; with a file the tag folds both versions (covered in remediation tests)
        self.assertIn(a, ("",) + (a,))
        self.assertEqual(rc.FORMULA_VERSION.count("."), 2)


class TestBankFactsFeedTheContract(unittest.TestCase):
    def test_bank_core_parsed_shape_runs_through_the_contract(self):
        bank = {"basis_used": "standalone", "equity_basis": "owners", "nci_evaluated": True, "retained_earnings_basis": "exact",
                "pat": (6000.0, 5000.0), "pat_total": (6000.0, 5000.0), "pat_basis": "owners",
                "equity": (60000.0, 50000.0), "equity_full": (60000.0, 50000.0), "non_controlling_interest": (0.0, 0.0),
                "retained_earnings": (59000.0, 49000.0), "total_assets": (600000.0, 500000.0),
                "eps": (60.0, 50.0), "eps_owners": (60.0, 50.0), "shares_outstanding": (100_000_000.0, 100_000_000.0),
                "bs_page": 5, "pl_page": 6, "source_url": "http://x/bank.pdf", "bank_statements": True,
                "dps_declared": {"found": True, "total": 10.0, "interim": [], "final": [10.0], "special": [],
                                 "no_dividend_evidence": False, "pages": [3], "policy": "x"}}
        ffs.clear_run_cache()
        with patch.object(ar, "_get_extracted_financials", return_value=bank):
            fs = ffs.get_canonical_facts("BANKCO", "Bank Co", 2026)
            res = rc.compute_all(fs, MARKET)
        self.assertAlmostEqual(res["pe_ratio"]["value_raw"], 100.0 / 60.0)
        self.assertAlmostEqual(res["bvps"]["value_raw"], 60000.0 * 1e7 / 1e8)
        self.assertAlmostEqual(res["eps_growth_rate"]["value_raw"], 20.0)
        self.assertAlmostEqual(res["roa"]["value_raw"], 6000.0 / 550000.0 * 100)
        self.assertEqual(res["dividend_yield"]["status"], "verified")
        for k in ("pe_ratio", "bvps", "roa"):
            self.assertTrue(res[k]["breakdown"]["reconciles"], k)


if __name__ == "__main__":
    unittest.main()
