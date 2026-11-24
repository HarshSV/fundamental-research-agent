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


def test_young_stock_gets_facts_with_unmeasured_values_left_empty():
    from setups import outlook as o
    out = o.build("X", [], _bars(17), None, [])
    y = out["young"]
    assert y["sessions"] == 17 and y["starts_in"] == 53 and out["outlook"][1]["call"] is None
    assert y["typical_move_pct"] is not None and y["volume"] is None            # no volume in these bars: unknown, not 0
    one = o.young_facts(_bars(1))
    assert one["since_listing"] is None and one["typical_move_pct"] is None and one["support"] is None
    assert "young" not in o.build("X", [], _bars(120), None, [])


def test_young_facts_count_up_and_down_days():
    from setups import outlook as o
    bars = [{"time": i * 86400, "open": c, "high": c + 1, "low": c - 1, "close": c} for i, c in enumerate([10, 11, 11, 9, 12])]
    assert o.young_facts(bars)["days"] == {"up": 2, "down": 1, "flat": 1}
    assert o.young_facts(bars[:1])["days"] is None


def test_breadth_is_computed_once_until_the_scan_data_changes(monkeypatch):
    from patterns import market_analytics as ma, scan
    calls = []
    monkeypatch.setattr(ma, "_breadth_compute", lambda: calls.append(1) or {"stocks": 5})
    monkeypatch.setattr(scan, "_load_all", lambda: {})                          # the real rows (and a scan writing them) are not part of this test
    monkeypatch.setitem(scan._mem, "stamp", ("a", 1))
    monkeypatch.setitem(ma._BREADTH, "val", None)
    assert ma.breadth() == {"stocks": 5} and ma.breadth() == {"stocks": 5} and len(calls) == 1
    monkeypatch.setitem(scan._mem, "stamp", ("a", 2))                    # the scan wrote new files: recomputed
    ma.breadth()
    assert len(calls) == 2
