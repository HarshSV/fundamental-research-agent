"""Popular-screens logic. Synthetic companies only - never a real company."""
import os
import pytest
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from screens import metrics, universe  # noqa: E402
from screens.definitions import BY_ID, SCREENS  # noqa: E402

DAY = 86400


def co(**kw):
    base = dict(price=100.0, eps=20.0, pe=10.0, promoter=70.0, div_yield=3.0, payout=50.0, cover=2.0,
                debt_equity=0.2, net_profit_cr=100.0, eps_growth=20.0, ret_1m=12.0, ret_1y=30.0,
                ret_3y=80.0, ret_5y=30.0, avg_volume=1000.0, volatility=20.0, market_cap_cr=1000.0, name="X")
    base.update(kw)
    return base


def test_there_are_23_screens_in_5_groups_with_unique_ids():
    assert len(SCREENS) == 23
    assert len({s[0] for s in SCREENS}) == 23
    assert len({s[1] for s in SCREENS}) == 5


def test_a_company_matching_every_criterion_is_listed():
    data = {"AAA": co()}
    assert [r["symbol"] for r in universe.evaluate("low-price-high-eps", data)] == ["AAA"]


def test_unknown_values_never_match_and_are_never_treated_as_zero():
    # unknown EPS must not satisfy "EPS >= 15" nor, as 0, satisfy any "low" rule
    data = {"AAA": co(eps=None), "BBB": co(promoter=None), "CCC": co(pe=None)}
    syms = lambda sid: {r["symbol"] for r in universe.evaluate(sid, data)}
    assert "AAA" not in syms("low-price-high-eps")          # unknown EPS never satisfies "EPS >= 15"
    assert "BBB" not in syms("high-promoter-high-eps")      # unknown promoter holding never satisfies it
    assert "CCC" not in syms("high-eps-low-pe")             # unknown P/E never counts as "low"
    # ...while a company is not penalised for a metric the screen does not use
    assert "BBB" in syms("low-price-high-eps") and "CCC" in syms("low-price-high-eps")


def test_low_pe_requires_a_positive_pe():
    data = {"NEG": co(pe=-5.0), "OK": co(pe=8.0)}
    assert [r["symbol"] for r in universe.evaluate("high-eps-low-pe", data)] == ["OK"]


def test_relative_screens_use_universe_percentiles():
    data = {f"S{i}": co(avg_volume=float(i * 100), ret_1y=30.0) for i in range(1, 11)}
    got = {r["symbol"] for r in universe.evaluate("high-volume-high-ret1y", data)}
    assert got and got <= {"S8", "S9", "S10"}  # only the top quartile of volume


def test_counts_match_evaluate(monkeypatch):
    data = {"AAA": co(), "BBB": co(price=500.0)}
    monkeypatch.setattr(universe, "load", lambda: data)
    c = universe.counts()
    assert c["low-price-high-eps"] == 1
    assert all(c[s[0]] == len(universe.evaluate(s[0], data)) for s in SCREENS)


# -- metrics -----------------------------------------------------------------------------------------
def _candles(n, start=100.0, step=0.1, vol=1000.0, start_ts=1_600_000_000):
    return [{"time": start_ts + i * DAY, "open": start + i * step, "high": start + i * step + 1,
             "low": start + i * step - 1, "close": start + i * step, "volume": vol} for i in range(n)]


def test_returns_are_none_when_history_does_not_reach_back_far_enough():
    m = metrics.compute(None, _candles(120))
    assert m["ret_1m"] is not None
    assert m["ret_1y"] is None and m["ret_5y"] is None  # never extrapolated


def test_missing_fundamentals_stay_none():
    m = metrics.compute(None, _candles(300))
    assert m["eps"] is None and m["pe"] is None and m["promoter"] is None and m["debt_equity"] is None
    assert m["payout"] is None and m["cover"] is None


def test_eps_is_only_computed_from_four_known_quarters():
    q = {f"2025-0{i}-30": {"Diluted EPS": 2.0} for i in range(1, 4)}  # only three quarters
    fin = {"info": {}, "financial_arrays": {"quarterly_income_stmt": q}}
    assert metrics.compute(fin, _candles(50))["eps"] is None
    q["2025-04-30"] = {"Diluted EPS": 3.0}
    assert metrics.compute(fin, _candles(50))["eps"] == 9.0


def test_debt_equity_needs_both_figures_and_positive_equity():
    fin = {"info": {}, "financial_arrays": {"balance_sheet": {
        "2025-03-31": {"Total Debt": 50.0, "Stockholders Equity": 100.0}}}}
    assert metrics.compute(fin, _candles(50))["debt_equity"] == 0.5
    fin["financial_arrays"]["balance_sheet"]["2025-03-31"]["Stockholders Equity"] = -10.0
    assert metrics.compute(fin, _candles(50))["debt_equity"] is None


def test_pe_is_price_over_trailing_eps_and_none_when_earnings_are_not_positive():
    def fin(eps_each):
        q = {f"2025-0{i}-30": {"Diluted EPS": eps_each} for i in range(1, 5)}
        return {"info": {"trailingPE": 56.9}, "financial_arrays": {"quarterly_income_stmt": q}}

    c = _candles(60)  # last close is the price
    price = c[-1]["close"]
    assert metrics.compute(fin(2.5), c)["pe"] == pytest.approx(price / 10.0)
    # negative trailing earnings: not meaningful. The provider's own P/E (56.9) must NOT be used instead.
    assert metrics.compute(fin(-1.0), c)["pe"] is None


def test_eps_row_ignores_a_leading_note_reference_column():
    from tools.annual_report_financials import _find_eps_row
    txt = ("Earnings per equity share Equity shares of par value 5/- each Basic (`) 2.23 71.58 64.50 "
           "Diluted (`) 2.23 71.46 64.34 Weighted average equity shares")
    assert _find_eps_row(txt) == (71.58, 64.5)
    plain = "Earnings per equity share Basic (`) 71.58 64.50 Diluted (`) 71.46 64.34"
    assert _find_eps_row(plain) == (71.58, 64.5)
