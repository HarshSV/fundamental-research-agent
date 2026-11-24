"""A young index fund borrows the index's history: the name-to-index rule and the forecast it produces."""
import pytest

from setups import etf_index, outlook


@pytest.mark.parametrize("name,expect", [
    ("Nippon India ETF Nifty 50 BeES", "Nifty 50"),
    ("Mirae Asset Nifty Next 50 ETF", "Nifty Next 50"),
    ("Nippon India Nifty 500 ETF", "Nifty 500"),
    ("SBI Nifty IT ETF", "Nifty IT"),
    ("Kotak Nifty PSU Bank ETF", "Nifty PSU Bank"),
    ("Nippon India ETF Nifty Bank BeES", "Nifty Bank"),
])
def test_plain_index_funds_map_to_their_index(name, expect):
    assert etf_index.underlying_index(name)[0] == expect


@pytest.mark.parametrize("name", [
    "HDFC Nifty 50 Equal Weight ETF",          # a variant tracks a different series
    "Nifty 500 Momentum 50 ETF",
    "UTI Nifty 100 Quality 30 ETF",
    "ICICI Prudential BSE Power ETF",          # an index the provider has no history for
    "Reliance Industries Limited",             # not a fund
    "Nippon India ETF Gold BeES",
    "", None,
])
def test_unknown_or_variant_stays_unmapped(name):
    assert etf_index.underlying_index(name) is None


def _bars(n):
    import math
    return [{"time": 86400 * i, "open": 100 + 10 * math.sin(i / 7), "high": 101 + 10 * math.sin(i / 7), "low": 99 + 10 * math.sin(i / 7), "close": 100 + 10 * math.sin(i / 7) + i * 0.02} for i in range(n)]


def test_borrowed_forecast_is_labelled_and_priced_from_the_fund():
    base = {"outlook": [{"id": "session", "label": "Next session"}, {"id": "week", "label": "Next 5 sessions", "sessions": 5}, {"id": "month", "label": "Next 20 sessions", "sessions": 20}]}
    out = etf_index.with_index_forecast(base, _bars(600), "Nifty 50", "^NSEI", 250.0)
    assert out["forecast_basis"] == {"kind": "index", "index": "Nifty 50", "symbol": "^NSEI", "sessions": 600}
    for h in out["outlook"]:
        assert h["up"] is not None
        assert h["price_low"] <= h["price_mid"] <= h["price_high"]
        assert h["price_mid"] == round(250.0 * (1 + h["median"] / 100), 2)      # priced from the fund's own last price, not the index level


def test_index_with_too_little_history_gives_no_odds():
    base = {"outlook": [{"id": "session", "label": "Next session"}]}
    out = etf_index.with_index_forecast(base, _bars(outlook.MIN_HISTORY - 1), "Nifty 50", "^NSEI", 250.0)
    assert out["outlook"][0]["call"] is None and "price_low" not in out["outlook"][0]


def test_short_history_gives_flagged_odds_but_no_trade_plan():
    from setups import outlook as o
    daily = _bars(120)
    out = o.build("X", [], daily, None, [])
    week = next(h for h in out["outlook"] if h["id"] == "week")
    assert week["up"] is not None and week["short_history"] == 120
    assert next(h for h in out["outlook"] if h["id"] == "month")["up"] is not None      # 120 >= 90
    assert o.build("X", [], _bars(80), None, [])["outlook"][2]["call"] is None            # 80 < 90: the 20-session view waits
    assert o.build("X", [], _bars(40), None, [])["outlook"][1]["call"] is None            # 40 is too few for any horizon
    assert out["swing"].get("plan") is None
