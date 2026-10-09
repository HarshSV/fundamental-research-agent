"""Hand-derived expected values for every computable ratio.

The synthetic filing is `tests.test_ratio_remediation.parsed()` (INR crore, price 100, 10 Cr shares). Every expectation below is written
as the textbook arithmetic on THOSE printed inputs - not produced by the engine and not by the independent oracle - so a formula that
drifts from the specification fails here even if the engine and the oracle were edited together. Inputs (cur / prior):

  revenue 1000/800 | materials 500/400, change in inventories -50/-20 -> COGS 450/380 | purchases (note) 480 | inventory 200/100
  receivables 250/150 | payables 160/140 | TCA 700/600 | TCL 400/380 | total assets 2000/1800 | owners' equity 900/800 | NCI 100/80
  PAT owners 100/80, whole entity 125/100 | PBT 130 | finance cost 30/25 | D&A 60/50 | tax 30 | cash 50 | borrowings 300+150+50, leases 60 -> debt 560
  OCF 140/120 | capex 150+10 | dividends paid 30 | DPS declared 3.0 | EPS owners 10/8 | shares 10 Cr | retained earnings 400
  net fixed assets = PPE+ROU+CWIP+intangibles = 970 (prior 865)

This is a check of the ARITHMETIC against the approved definitions. Whether the approved definitions are right is a separate question
(docs/ratio_contract.md); whether the extracted inputs are right is checked against real filings (test_anuras_fy2026_source_audit.py,
docs/ratio_audit_matrix_2026-10.md)."""
import math
import unittest

import tools.ratio_contract as rc
from tests.test_ratio_remediation import facts, MARKET

# key: (expected value, relative tolerance, the textbook arithmetic)
TEXTBOOK = {
    "inventory_turnover":          (450 / ((200 + 100) / 2), 1e-9, "COGS 450 / avg inventory 150"),
    "days_inventory_outstanding":  (365 / 3.0, 1e-9, "365 / 3.0"),
    "receivables_turnover":        (1000 / ((250 + 150) / 2), 1e-9, "revenue 1000 / avg receivables 200 (credit-sales proxy)"),
    "days_sales_outstanding":      (365 / 5.0, 1e-9, "365 / 5.0 = 73"),
    "payables_turnover":           (480 / ((160 + 140) / 2), 1e-9, "disclosed purchases 480 / avg payables 150"),
    "days_payables_outstanding":   (365 / 3.2, 1e-9, "365 / 3.2"),
    "asset_turnover":              (1000 / ((2000 + 1800) / 2), 1e-9, "1000 / avg assets 1900"),
    "working_capital_turnover":    (1000 / (((700 - 400) + (600 - 380)) / 2), 1e-9, "1000 / avg WC 260"),
    "cash_conversion_cycle":       (73 + 365 / 3.0 - 365 / 3.2, 1e-9, "73 + 121.667 - 114.0625"),
    "current_ratio":               (700 / 400, 1e-9, "700 / 400"),
    "quick_ratio":                 ((700 - 200) / 400, 1e-9, "(700 - 200) / 400"),
    "cash_ratio":                  (50 / 400, 1e-9, "cash 50 / 400 (no other bank balances in this filing)"),
    "working_capital":             (700 - 400, 1e-9, "700 - 400"),
    "gross_profit_margin":         ((1000 - 450) / 1000 * 100, 1e-9, "(1000 - 450) / 1000"),
    "operating_profit_margin":     ((130 + 30) / 1000 * 100, 1e-9, "EBIT 160 / 1000"),
    "net_profit_margin":           (100 / 1000 * 100, 1e-9, "owners' PAT 100 / 1000"),
    "roa":                         (100 / 1900 * 100, 1e-9, "owners' PAT 100 / avg assets 1900"),
    "roe":                         (100 / ((900 + 800) / 2) * 100, 1e-9, "100 / avg owners' equity 850"),
    "roce":                        (160 / (((2000 - 400) + (1800 - 380)) / 2) * 100, 1e-9, "EBIT 160 / avg(1600, 1420)"),
    "debt_to_equity":              (560 / 1000, 1e-9, "debt 560 / equity incl. NCI 1000"),
    "debt_ratio":                  (560 / 2000, 1e-9, "560 / 2000"),
    "interest_coverage_ratio":     (160 / 30, 1e-9, "EBIT 160 / finance cost 30"),
    "financial_leverage_ratio":    (1900 / ((1000 + 880) / 2), 1e-9, "avg assets 1900 / avg equity incl. NCI 940"),
    "pe_ratio":                    (100 / 10, 1e-9, "price 100 / EPS 10"),
    "pb_ratio":                    (100 / 90, 1e-9, "price 100 / BVPS 90"),
    "ps_ratio":                    (1000 / 1000, 1e-9, "market cap 1000 / revenue 1000"),
    "dividend_yield":              (3.0 / 100 * 100, 1e-9, "DPS 3 / price 100"),
    "earnings_yield":              (10 / 100 * 100, 1e-9, "EPS 10 / price 100"),
    "ev_to_ebitda":                ((1000 + 560 - 50) / (160 + 60), 1e-9, "EV 1510 / EBITDA 220"),
    "fixed_asset_turnover":        (1000 / ((970 + 865) / 2), 1e-9, "1000 / avg net fixed assets 917.5"),
    "days_working_capital":        (((300 + 220) / 2) / 1000 * 365, 1e-9, "avg WC 260 / revenue x 365"),
    "receivables_to_payables":     (250 / 160, 1e-9, "250 / 160"),
    "net_debt_to_ebitda":          ((560 - 50) / 220, 1e-9, "net debt 510 / EBITDA 220"),
    "cash_flow_coverage_ratio":    (140 / 560, 1e-9, "OCF 140 / debt 560"),
    "free_cash_flow":              (140 - 160, 1e-9, "OCF 140 - capex 160"),
    "fcf_yield":                   (-20 / 1000 * 100, 1e-9, "FCF -20 / market cap 1000"),
    "fcf_margin":                  (-20 / 1000 * 100, 1e-9, "FCF -20 / revenue 1000"),
    "ocf_ratio":                   (140 / 400, 1e-9, "OCF 140 / current liabilities 400"),
    "capex_intensity":             (160 / 1000 * 100, 1e-9, "capex 160 / revenue 1000"),
    "ocf_to_net_profit":           (140 / 125, 1e-9, "OCF 140 / whole-entity PAT 125"),
    "roic":                        (160 * (1 - 30 / 130) / (560 + 1000 - 50) * 100, 1e-9, "NOPAT 160 x (1 - 30/130) / IC 1510"),
    "effective_tax_rate":          (30 / 130 * 100, 1e-9, "tax 30 / PBT 130"),
    "eps_growth_rate":             ((10 / 8 - 1) * 100, 1e-9, "10 / 8 - 1"),
    "bvps":                        (900 * 1e7 / 1e8, 1e-9, "900 Cr / 10 Cr shares"),
    "dividend_payout_ratio":       (30 / 100 * 100, 1e-9, "dividends paid 30 / owners' PAT 100 (whole-entity paid: flagged)"),
    "retention_ratio":             (100 - 30, 1e-9, "100 - 30"),
    "sustainable_growth_rate":     (100 / 850 * 100 * 0.70, 1e-9, "ROE 11.7647 x retention 0.70"),
    "peg_ratio":                   (10 / 25, 1e-9, "P/E 10 / EPS growth 25"),
    "ev_to_sales":                 (1510 / 1000, 1e-9, "EV 1510 / revenue 1000"),
    "ev_to_fcf":                   (1510 / -20, 1e-9, "EV 1510 / FCF -20 (not meaningful)"),
    "price_to_cash_flow":          (1000 / 140, 1e-9, "market cap 1000 / OCF 140"),
    "graham_number":               (math.sqrt(22.5 * 10 * 90), 1e-9, "sqrt(22.5 x 10 x 90)"),
    # 1.2(300/2000) + 1.4(400/2000) + 3.3(160/2000) + 0.6(1000/1000) + 1.0(1000/2000)
    "altman_z_score":              (1.2 * 0.15 + 1.4 * 0.2 + 3.3 * 0.08 + 0.6 * 1.0 + 1.0 * 0.5, 1e-9, "1.8240"),
    # all nine tests pass on this improving, un-diluted company
    "piotroski_f_score":           (9.0, 0, "9 of 9"),
    # DSRI 1.33333, GMI 0.954545, AQI 0.9, SGI 1.25, DEPI 0.955556, SGAI 0.857143, TATA -0.0075, LVGI 0.965363 (hand-evaluated)
    "beneish_m_score":             (-2.01904, 2e-5, "hand-evaluated 8-variable model"),
}


class TestTextbookValues(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.results = rc.compute_all(facts(), MARKET)

    def test_every_computable_ratio_has_a_hand_derived_expectation(self):
        needs = set(rc.COMPUTABLE) - {"contribution_margin", "dscr"}
        self.assertEqual(needs - set(TEXTBOOK), set(), "ratio without a hand-derived expected value")

    def test_each_ratio_equals_its_textbook_arithmetic(self):
        for key, (want, tol, how) in TEXTBOOK.items():
            with self.subTest(ratio=key, textbook=how):
                got = self.results[key].get("value_raw")
                self.assertIsNotNone(got, f"{key}: {self.results[key].get('reason')}")
                self.assertAlmostEqual(got, want, delta=max(tol * abs(want), 1e-12), msg=f"{key} ({how})")

    def test_dscr_is_ebitda_over_principal_plus_interest(self):
        r = self.results["dscr"]
        want_with_leases = 220 / (80 + 10 + 30)
        want_without = 220 / (80 + 30)
        self.assertIn(round(r["value_raw"], 6), (round(want_with_leases, 6), round(want_without, 6)))

    def test_statuses_reflect_proxies_and_meaningfulness(self):
        self.assertEqual(self.results["ev_to_fcf"]["status"], "not_meaningful")          # negative FCF
        self.assertEqual(self.results["receivables_turnover"]["status"], "needs_review")  # revenue stands in for credit sales
        self.assertEqual(self.results["beneish_m_score"]["status"], "needs_review")       # SG&A proxy
        self.assertEqual(self.results["dividend_payout_ratio"]["status"], "needs_review") # consolidated cash dividends incl. minorities
        self.assertEqual(self.results["inventory_turnover"]["status"], "verified")


if __name__ == "__main__":
    unittest.main()
