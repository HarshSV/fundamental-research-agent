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


# ------------------------------------------------------------------ outlook
def test_tilt_thresholds():
    from patterns import sector_outlook as so
    assert so._tilt(4) == {"direction": "none", "size": "none"}
    assert so._tilt(7) == {"direction": "up", "size": "slight"}
    assert so._tilt(-12) == {"direction": "down", "size": "clear"}


def test_odds_report_tilt_against_usual(monkeypatch):
    import numpy as np
    from patterns import sector_outlook as so
    usual = [(0.05, 0.01)] * 50 + [(-0.05, -0.01)] * 50                      # half the months rise clearly, half fall clearly
    now = [(0.05, 0.01)] * 40 + [(-0.05, -0.01)] * 10                        # in this situation 80% rise
    o = so._odds(now, 0.01, usual)
    assert o["up"] == 80 and o["usual_up"] == 50 and o["tilt_up_points"] == 30 and o["tilt"] == {"direction": "up", "size": "clear"}
    assert o["samples"] == 50 and o["flat"] == 0


def test_estimate_falls_back_when_the_situation_is_rare():
    from patterns import sector_outlook as so
    month = [(0.02, 0.0)] * 40
    own_all = month
    few = [(0.02, 0.0)] * 5
    assert so._estimate(1, (True, True, False), few, month, own_all)["basis"] == "all sectors, same situation"
    assert so._estimate(1, (True, True, False), few, few, own_all)["basis"] == "all of this sector's months"
    assert so._estimate(1, (True, True, False), few, few, few)["call"] is None


def test_outlook_and_validation_on_made_up_sectors(monkeypatch):
    _fake(monkeypatch)
    from patterns import sector_outlook as so
    so._cache.clear(); so._val_cache.clear()
    monkeypatch.setattr(so, "_results_progress", lambda syms: {"available": False})
    monkeypatch.setattr(so.market_analytics, "sectors", lambda: {"sectors": []})
    monkeypatch.setattr(so.ex, "load", lambda name: [])
    monkeypatch.setattr(so.sector_events, "recent", lambda sec: {"orders_count": 0, "deals_buy_cr": 0, "deals_sell_cr": 0, "deals_count": 0})
    o = so.outlook()
    assert o["ready"] and {s["sector"] for s in o["sectors"]} == {"Alpha", "Beta"}          # Tiny has too few stocks
    v = o["validation"]
    assert v["ready"] and v["horizons"]["3m"]["months_tested"] > 0
    for s in o["sectors"]:
        assert [h["id"] for h in s["horizons"]] == ["1m", "3m"] and s["situation"]
