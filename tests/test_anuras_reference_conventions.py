"""ANURAS FY2025-26: every external reference value quoted in the 2026-10 discrepancy list is REPRODUCED from the same printed inputs with that
reference's own convention (independent arithmetic below, not the contract), and each Navrist value is shown to follow the approved definition.
The two sets of numbers differ by definition (average vs closing balances, COGS vs purchases vs revenue, owners vs whole-entity profit); none
is a data error.  Inputs = the printed consolidated figures in tests/test_anuras_fy2026_source_audit.py (INR crore)."""
import unittest

import tools.ratio_contract as rc
from tests.test_anuras_fy2026_source_audit import C, fs_consolidated

REV, COGS, PUR = C["revenue"][0], 1442.007 - 118.751, 1478.115
INV, REC, PAY = C["inventory"], C["receivables"], C["payables"]
avg = lambda p: (p[0] + p[1]) / 2.0                                                    # noqa: E731


def navrist(key, market=None):
    return rc.compute_with_parents(key, fs_consolidated(), market, {})["value_raw"]


class TestWorkingCapitalDays(unittest.TestCase):

    def test_navrist_days_follow_the_approved_average_balance_definitions(self):
        self.assertAlmostEqual(navrist("days_inventory_outstanding"), 365 * avg(INV) / COGS, places=6)       # COGS / average inventory
        self.assertAlmostEqual(navrist("days_sales_outstanding"), 365 * avg(REC) / REV, places=6)            # revenue is the credit-sales PROXY
        self.assertAlmostEqual(navrist("days_payables_outstanding"), 365 * avg(PAY) / PUR, places=6)         # disclosed purchases
        self.assertAlmostEqual(navrist("cash_conversion_cycle"),
                               365 * avg(REC) / REV + 365 * avg(INV) / COGS - 365 * avg(PAY) / PUR, places=6)
        self.assertEqual([round(navrist(k), 2) for k in ("days_inventory_outstanding", "days_sales_outstanding",
                                                           "days_payables_outstanding", "cash_conversion_cycle")],
                         [444.96, 130.63, 187.91, 387.68])

    def test_screener_values_are_reproduced_with_closing_balances_and_cogs(self):
        di, dr, dp = 365 * INV[0] / COGS, 365 * REC[0] / REV, 365 * PAY[0] / COGS
        self.assertEqual((round(di), round(dr), round(dp), round(di + dr - dp)), (490, 148, 261, 377))

    def test_value_research_values_are_reproduced_with_average_balances_and_sales_for_inventory(self):
        self.assertEqual(round(365 * avg(INV) / REV, 2), 248.91)
        self.assertEqual(round(365 * avg(REC) / REV, 2), 130.63)
        self.assertEqual(round(365 * avg(PAY) / COGS, 2), 209.90)
        self.assertAlmostEqual(365 * avg(INV) / REV + 365 * avg(REC) / REV - 365 * avg(PAY) / COGS, 169.65, delta=0.011)   # published to 2 dp from rounded parts

    def test_working_capital_days_is_its_own_formula_average_working_capital_over_revenue(self):
        wc = [C["total_current_assets"][i] - C["total_current_liabilities"][i] for i in (0, 1)]
        self.assertAlmostEqual(navrist("days_working_capital"), 365 * avg(wc) / REV, places=6)
        self.assertEqual(round(navrist("days_working_capital"), 1), 144.8)


class TestReturnsAndLeverageReferences(unittest.TestCase):
    EQ_OWNERS, EQ_TOTAL = C["equity"], (C["equity"][0] + C["nci"][0], C["equity"][1] + C["nci"][1])

    def test_roe_owners_profit_over_average_owners_equity_and_the_whole_entity_reference(self):
        self.assertAlmostEqual(navrist("roe"), C["pat"][0] / avg(self.EQ_OWNERS) * 100, places=6)
        self.assertEqual(round(navrist("roe"), 2), 5.53)
        # the ~5.76% reference = whole-entity profit / average equity incl. NCI (a different perimeter, same arithmetic)
        self.assertEqual(round(C["pat_total"][0] / avg(self.EQ_TOTAL) * 100, 2), 5.76)

    def test_roa_and_roce_follow_their_documented_definitions(self):
        self.assertAlmostEqual(navrist("roa"), C["pat"][0] / avg(C["total_assets"]) * 100, places=6)
        ebit = C["pbt"][0] + C["finance_costs"][0]
        ce = [C["total_assets"][i] - C["total_current_liabilities"][i] for i in (0, 1)]
        self.assertAlmostEqual(navrist("roce"), ebit / avg(ce) * 100, places=6)
        self.assertEqual((round(navrist("roa"), 2), round(navrist("roce"), 2)), (2.56, 9.10))

    DEBT, CASH = (1867.487, 1373.384), (378.069, 113.046)

    def test_roic_uses_closing_invested_capital_per_the_specification(self):
        ebit, t = C["pbt"][0] + C["finance_costs"][0], C["tax_expense"][0] / C["pbt"][0]
        ic = self.DEBT[0] + self.EQ_TOTAL[0] - self.CASH[0]                      # Total Debt + Total Equity incl. NCI - Cash, closing
        fs = fs_consolidated(total_debt=self.DEBT, cash=self.CASH, nopat=(ebit * (1 - t), None), tax_rate=(t, None),
                             invested_capital=(ic, None))
        self.assertAlmostEqual(rc.compute_with_parents("roic", fs, None, {})["value_raw"], ebit * (1 - t) / ic * 100, places=6)
        # reference with AVERAGE invested capital (6.7%), not adopted: the contract fixes closing capital
        ic0 = self.DEBT[1] + self.EQ_TOTAL[1] - self.CASH[1]
        self.assertEqual(round(ebit * (1 - t) / ((ic + ic0) / 2) * 100, 2), 6.73)

    def test_debt_to_equity_basis_and_the_borrowings_over_owners_equity_reference(self):
        fs = fs_consolidated(total_debt=self.DEBT, cash=self.CASH)
        d = rc.compute_with_parents("debt_to_equity", fs, None, {})["value_raw"]
        self.assertAlmostEqual(d, self.DEBT[0] / self.EQ_TOTAL[0], places=9)       # whole-entity debt over equity incl. NCI
        self.assertEqual(round(d, 2), 0.40)
        self.assertEqual(round(1814.655 / self.EQ_OWNERS[0], 2), 0.55)             # reference: balance-sheet borrowings / owners' equity


if __name__ == "__main__":
    unittest.main()
