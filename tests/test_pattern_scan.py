"""Pattern scanner filters. Synthetic stocks only - never a real company."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from patterns import scan  # noqa: E402


def stock(sym, index="large", sector="Banks", cap=50000.0, price=100.0, ema=None, sma=None, occ=None, name=None):
    return {
        "symbol": sym, "name": name or f"{sym} Limited", "sector": sector, "index": index, "price": price,
        "market_cap_cr": cap, "ret_1m": 1.0, "ret_3m": 2.0, "pct_from_52w_high": 5.0, "as_of": 1,
        "ema": ema or {"20": 90.0, "50": 95.0}, "sma": sma or {"20": 90.0, "50": 95.0},
        "occurrences": occ if occ is not None else [{"pattern": "vcp", "status": "forming", "end_ts": 5}],
        "candles": [[1, 1, 2, 1, 2, 10]],
    }


def run(monkeypatch, rows, pattern="vcp", **f):
    monkeypatch.setattr(scan, "_load_all", lambda: {r["symbol"]: r for r in rows})
    monkeypatch.setattr(scan, "status", lambda: {"building": False, "done": 0, "total": 0, "errors": 0, "have": len(rows), "universe": len(rows)})
    return [r["symbol"] for r in scan.search(pattern, f)["rows"]]


def test_only_stocks_showing_the_pattern_are_listed(monkeypatch):
    rows = [stock("AAA"), stock("BBB", occ=[{"pattern": "flag", "status": "forming", "end_ts": 1}]), stock("CCC", occ=[])]
    assert run(monkeypatch, rows) == ["AAA"]


def test_index_filter_matches_any_ticked_index(monkeypatch):
    rows = [stock("L", index="large"), stock("M", index="mid"), stock("N", index=None)]
    assert sorted(run(monkeypatch, rows, indices={"values": ["large", "mid"]})) == ["L", "M"]
    assert run(monkeypatch, rows, indices={"values": ["large"]}) == ["L"]
    assert sorted(run(monkeypatch, rows, indices={"values": []})) == ["L", "M", "N"]   # nothing ticked = no restriction
    # every option ticked ("Select all") still leaves out a stock that is in no index: unknown never matches


def test_unknown_market_cap_never_passes_a_cap_filter_and_is_not_treated_as_zero(monkeypatch):
    rows = [stock("K", cap=None), stock("S", cap=500.0), stock("B", cap=90000.0)]
    assert sorted(run(monkeypatch, rows)) == ["B", "K", "S"]                       # no cap filter: unknown is still listed
    assert run(monkeypatch, rows, mcap={"min": None, "max": 1000}) == ["S"]        # not "0 <= 1000"
    assert run(monkeypatch, rows, mcap={"min": 1000, "max": None}) == ["B"]


def test_ema_and_dma_are_separate_filters(monkeypatch):
    rows = [
        stock("UP", price=100, ema={"20": 90, "50": 95}, sma={"20": 120, "50": 130}),
        stock("MIX", price=100, ema={"20": 90, "50": 110}, sma={"20": 90, "50": 95}),
        stock("NA", price=100, ema={"20": 90, "50": None}),  # too little history for the 50: unknown
    ]
    above = {"periods": [20, 50], "side": "above"}
    assert sorted(run(monkeypatch, rows, ema=above)) == ["MIX", "NA", "UP"]            # above at least one ticked EMA
    assert run(monkeypatch, rows, ema={"periods": [50], "side": "above"}) == ["UP"]    # an unknown EMA never satisfies
    assert run(monkeypatch, rows, dma={"periods": [20], "side": "below"}) == ["UP"]    # price 100 < sma20 120
    assert run(monkeypatch, rows, ema={"periods": [], "side": "above"}) != []          # no periods ticked = no filter


def test_sector_status_and_text_search(monkeypatch):
    rows = [
        stock("A", sector="Banks", name="Alpha Bank"),
        stock("B", sector="Power", occ=[{"pattern": "vcp", "status": "awaiting_breakout", "end_ts": 2},
                                        {"pattern": "vcp", "status": "confirmed", "end_ts": 3}]),
    ]
    assert run(monkeypatch, rows, sectors={"values": ["Power"]}) == ["B"]
    assert run(monkeypatch, rows, status={"values": ["confirmed"]}) == ["B"]
    assert sorted(run(monkeypatch, rows, status={"values": ["awaiting_breakout", "forming"]})) == ["A", "B"]
    assert run(monkeypatch, rows, q="ALPHA") == ["A"]


def test_closest_to_breakout_sorts_first_and_pages(monkeypatch):
    rows = [stock("F", occ=[{"pattern": "vcp", "status": "forming", "end_ts": 1}], cap=1.0),
            stock("W", occ=[{"pattern": "vcp", "status": "awaiting_breakout", "end_ts": 1}], cap=1.0),
            stock("C", occ=[{"pattern": "vcp", "status": "confirmed", "end_ts": 1}], cap=1.0)]
    assert run(monkeypatch, rows) == ["W", "F", "C"]
    monkeypatch.setattr(scan, "_load_all", lambda: {r["symbol"]: r for r in rows})
    monkeypatch.setattr(scan, "status", lambda: {})
    res = scan.search("vcp", {"page": 2, "page_size": 2})
    assert res["total"] == 3 and [r["symbol"] for r in res["rows"]] == ["C"]


def test_current_keeps_only_live_and_recently_confirmed_occurrences():
    times = list(range(100, 130))
    occs = [
        {"pattern": "p", "status": "forming", "confirmed_ts": None},
        {"pattern": "p", "status": "awaiting_breakout", "confirmed_ts": None},
        {"pattern": "p", "status": "confirmed", "confirmed_ts": 128},   # inside the last 10 bars
        {"pattern": "p", "status": "confirmed", "confirmed_ts": 105},   # long ago
        {"pattern": "p", "status": "invalidated", "confirmed_ts": None},
    ]
    assert [o["status"] for o in scan._current(occs, times)] == ["forming", "awaiting_breakout", "confirmed"]


def test_moving_averages():
    assert scan._sma([1, 2, 3, 4], 2) == 3.5 and scan._sma([1], 2) is None
    assert scan._ema([5, 5, 5, 5], 3) == 5 and scan._ema([1, 2], 3) is None
