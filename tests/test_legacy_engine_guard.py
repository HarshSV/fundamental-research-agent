"""The 68-ratio engine (tools/ratio_contract.py) is the ONLY audited ratio calculation. A legacy research-report engine
(tools/metrics_engine.py, tools/financial_analysis.py, tools/forward_valuation.py -> /api/research) still computes a few similarly named
metrics from third-party statement data. These tests (1) pin that set so a new parallel calculation cannot appear unreviewed,
(2) lock the two generic defects fixed in the legacy engine (unknown debt/cash treated as zero; Piotroski liquidity on total assets)."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# modules allowed to contain ratio arithmetic: the contract + its breakdown/bank providers, and the documented legacy engine
AUDITED = {"ratio_contract.py", "ratio_breakdown.py", "bank_ratios.py", "bank_extractor.py"}
LEGACY_DOCUMENTED = {"metrics_engine.py", "financial_analysis.py", "forward_valuation.py"}

_RATIO_ASSIGN = re.compile(
    r"^\s*(?:roe|roce|roa|net_margin|ebitda_margin|operating_margin|gross_margin|debt_to_equity|current_ratio|quick_ratio|interest_coverage|"
    r"pe_ratio|inventory_turnover|asset_turnover|net_debt_to_ebitda|ocf_ratio)\w*\s*=\s*[^=\n]*[\w\)\]]\s*/\s*[\w\(]", re.M)


class TestNoUnreviewedParallelRatioCalculation(unittest.TestCase):

    def test_ratio_arithmetic_exists_only_in_the_contract_and_the_documented_legacy_engine(self):
        found = set()
        for fn in os.listdir(os.path.join(ROOT, "tools")):
            if fn.endswith(".py") and _RATIO_ASSIGN.search(open(os.path.join(ROOT, "tools", fn), encoding="utf-8", errors="ignore").read()):
                found.add(fn)
        unexpected = found - AUDITED - LEGACY_DOCUMENTED
        self.assertEqual(unexpected, set(), f"new ratio calculation outside the contract: {sorted(unexpected)} - route it through "
                                            "tools.ratio_contract or document it as legacy")

    def test_every_dashboard_fetch_wrapper_delegates_to_the_contract(self):
        import ast
        for rel in ("tools/annual_report_financials.py", "tools/nse_xbrl.py"):
            src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
            lines = src.splitlines()
            for n in ast.parse(src).body:
                if isinstance(n, ast.FunctionDef) and re.fullmatch(r"fetch_\w+_from_annual_report", n.name):
                    body = "\n".join(lines[n.lineno - 1:n.end_lineno])
                    if n.name in ("fetch_revenue_characteristics_evidence", "fetch_multi_year_segment_revenue",
                                  "fetch_multi_year_cash_flow_items"):
                        continue                                    # evidence / multi-year data fetchers, not ratio formulas
                    self.assertRegex(body, r"_contract_fetch\(|_contract_fact_fetch\(|ratio_contract|fetch_\w+_from_annual_report\(",
                                     f"{n.name} must delegate to the ratio contract")

    def test_legacy_payload_declares_that_it_is_not_the_audited_engine(self):
        from tools.metrics_engine import FundamentalMetricsEngine
        out = FundamentalMetricsEngine.calculate_all_metrics({"symbol": "SYNTH", "info": {}, "financial_arrays": {}})
        self.assertEqual(out["_engine"]["name"], "legacy_research_report")
        self.assertIn("ratio_contract", out["_engine"]["audited_ratio_engine"])


def _raw(with_debt=True, with_cash=True):
    bs = {"Total Assets": 200.0, "Stockholders Equity": 80.0, "Current Liabilities": 50.0}
    if with_debt:
        bs["Total Debt"] = 40.0
    if with_cash:
        bs["Cash And Cash Equivalents"] = 10.0
    return {"symbol": "SYNTH", "info": {}, "financial_arrays": {
        "income_stmt": {"2025-03-31": {"Total Revenue": 100.0, "EBITDA": 30.0, "Net Income": 10.0, "EBIT": 25.0, "Interest Expense": 5.0}},
        "balance_sheet": {"2025-03-31": bs}, "cash_flow": {}}}


class TestLegacySolvencyNeverTreatsUnknownAsZero(unittest.TestCase):

    def solvency(self, **kw):
        from tools.metrics_engine import FundamentalMetricsEngine
        return FundamentalMetricsEngine.calculate_all_metrics(_raw(**kw))["F-08_Solvency_Metrics"]

    def test_known_debt_and_cash_compute(self):
        s = self.solvency()
        self.assertAlmostEqual(s["debt_to_equity"], 40.0 / 80.0)
        self.assertAlmostEqual(s["net_debt_to_ebitda"], (40.0 - 10.0) / 30.0)

    def test_missing_debt_withholds_both_ratios_instead_of_computing_on_zero(self):
        s = self.solvency(with_debt=False)
        self.assertIsNone(s["debt_to_equity"])                 # was 0.0 -> looked debt-free
        self.assertIsNone(s["net_debt_to_ebitda"])

    def test_missing_cash_withholds_net_debt_instead_of_assuming_no_cash(self):
        s = self.solvency(with_cash=False)
        self.assertIsNone(s["net_debt_to_ebitda"])
        self.assertAlmostEqual(s["debt_to_equity"], 0.5)       # D/E does not need cash


class TestLegacyPiotroskiLiquidityUsesCurrentAssets(unittest.TestCase):

    def _series(self, cur_ca, prev_ca):
        base = {"net_income": 10.0, "revenue": 100.0, "ebit": 20.0, "equity": 80.0, "debt": 30.0, "cfo": 15.0, "eps": 1.0, "shares": 10.0}
        return [dict(base, year="2024-03-31", assets=200.0, curr_liab=50.0, curr_assets=prev_ca),
                dict(base, year="2025-03-31", assets=400.0, curr_liab=50.0, curr_assets=cur_ca)]

    def _liquidity(self, series):
        from tools.financial_analysis import compute_piotroski
        return next(c for c in compute_piotroski(series)["checks"] if c["name"] == "Improving liquidity")

    def test_total_assets_growth_no_longer_masks_a_worse_current_ratio(self):
        # total assets doubled (200 -> 400) so the old 'assets / current liabilities' proxy 'improved'; the real current ratio fell 3.0 -> 2.0
        self.assertIs(self._liquidity(self._series(cur_ca=100.0, prev_ca=150.0))["pass"], False)

    def test_improving_current_ratio_passes(self):
        self.assertIs(self._liquidity(self._series(cur_ca=200.0, prev_ca=150.0))["pass"], True)

    def test_missing_current_assets_leaves_the_test_unscored_not_failed(self):
        self.assertIsNone(self._liquidity(self._series(cur_ca=None, prev_ca=None))["pass"])


if __name__ == "__main__":
    unittest.main()
