"""Sector history and event study maths, on small made-up price series (the maths is what is tested; no market data is used)."""
from __future__ import annotations

import math

from patterns import sector_events, sector_history


def _months(start_year: int, n: int, growth):
    """[[yyyymm, close]] for n consecutive months; growth(i) is the monthly return at step i."""
    out, price, y, m = [], 100.0, start_year, 1
    for i in range(n):
        out.append([y * 100 + m, price])
        price *= 1.0 + growth(i)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _fake(monkeypatch):
    store, rows = {}, {}
    for k in range(6):                                    # six stocks in sector "Alpha": +1% a month, a 20% fall in month 30
        sym = f"A{k}"
        store[sym] = {"at": 0, "m": _months(2000, 120, lambda i: -0.20 if i == 30 else 0.01)}
        rows[sym] = {"sector": "Alpha"}
    for k in range(6):                                    # six stocks in sector "Beta": flat
        sym = f"B{k}"
        store[sym] = {"at": 0, "m": _months(2000, 120, lambda i: 0.0)}
        rows[sym] = {"sector": "Beta"}
    for k in range(2):                                    # too few stocks to count
        sym = f"C{k}"
        store[sym] = {"at": 0, "m": _months(2000, 120, lambda i: 0.0)}
        rows[sym] = {"sector": "Tiny"}
    monkeypatch.setattr(sector_history, "_load", lambda: store)
    monkeypatch.setattr(sector_history.scan, "_load_all", lambda: rows)
    monkeypatch.setattr(sector_history.os.path, "getmtime", lambda p: 1.0 + len(sector_history._levels_cache) * 0)
    sector_history._cache.clear()
    sector_history._levels_cache.clear()


def test_sector_index_compounds_equal_weighted_returns(monkeypatch):
    _fake(monkeypatch)
    r = sector_history.build("full")
    alpha = next(s for s in r["sectors"] if s["sector"] == "Alpha")
    assert alpha["available"] and alpha["from"] == "2000-01"
    expected = (1.01 ** 118 * 0.8 / 1.01) ** (12 / 118) - 1                      # 119 months of returns, one of them -20%
    assert math.isclose(alpha["cagr"] / 100, expected, rel_tol=0.05)
    assert alpha["max_drawdown"]["depth"] == -20.0
    assert alpha["max_drawdown"]["months_to_recover"] is not None
    beta = next(s for s in r["sectors"] if s["sector"] == "Beta")
    assert beta["cagr"] == 0.0 and beta["max_drawdown"]["depth"] == 0.0


def test_sector_with_too_few_stocks_is_not_invented(monkeypatch):
    _fake(monkeypatch)
    r = sector_history.build("full")
    tiny = next(s for s in r["sectors"] if s["sector"] == "Tiny")
    assert tiny["available"] is False and "at least" in tiny["reason"]


def test_five_year_window_starts_later(monkeypatch):
    _fake(monkeypatch)
    full, five = sector_history.build("full"), sector_history.build("5y")
    a_full = next(s for s in full["sectors"] if s["sector"] == "Alpha")
    a_five = next(s for s in five["sectors"] if s["sector"] == "Alpha")
    assert a_five["from"] > a_full["from"] and a_five["years"] <= 5.1


def test_event_study_splits_sector_and_market(monkeypatch):
    _fake(monkeypatch)
    monkeypatch.setattr(sector_events, "_catalogue", lambda: [
        {"month": "2002-07", "title": "Made-up shock", "scope": "market"},
        {"month": "2003-01", "title": "Only for Beta", "scope": "sectors", "sectors": ["Beta"]},
    ])
    a = sector_events.analyse("Alpha")
    assert a["available"] and a["events_known"] == 1                                # the Beta-only event does not apply to Alpha
    shock = next(r for r in a["reactions"] if r["title"] == "Made-up shock")
    assert shock["sector_month"] is not None and shock["market_month"] is not None
    worst = min(a["moves"]["underperformed"], key=lambda m: m["sector_return"])
    assert worst["month"] == "2002-08" and worst["sector_return"] < -15              # the -20% fall lands in August 2002
    assert worst["events"][0]["title"] == "Made-up shock"                            # and the July 2002 event is within a month of it
    assert worst["kind"] == "specific to this sector"


def test_unknown_sector_and_unbuilt_history(monkeypatch):
    _fake(monkeypatch)
    assert sector_events.analyse("Nowhere")["available"] is False
    monkeypatch.setattr(sector_history, "_load", lambda: {})
    sector_history._levels_cache.clear()
    assert sector_events.analyse("Alpha")["ready"] is False
