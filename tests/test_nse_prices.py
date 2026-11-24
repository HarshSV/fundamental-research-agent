"""NSE's official bars replace the scan's newest bars; they never invent data."""
from datetime import datetime, timedelta, timezone

from patterns import nse_prices

IST = timezone(timedelta(hours=5, minutes=30))
HEAD = "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER\n"


def ts(day):
    return datetime(2026, 11, day, tzinfo=IST).timestamp()


def row(sym, bars, exchange="NSE"):
    return {"symbol": sym, "exchange": exchange, "price": bars[-1][4], "candles": bars}


def setup(monkeypatch, files):
    monkeypatch.setattr(nse_prices, "_days", {iso: nse_prices.parse(HEAD + body) for iso, body in files.items()})
    monkeypatch.setattr(nse_prices, "_load_from_disk", lambda: None)
    monkeypatch.setattr(nse_prices, "_refresh_async", lambda *a, **k: None)


def test_parse_prefers_the_eq_row_and_skips_other_series():
    d = nse_prices.parse(HEAD + "AAA, BE, 23-Nov-2026, 10, 10, 11, 9, 10, 10, 10, 500, 1, 1, 1, 1\nAAA, EQ, 23-Nov-2026, 10, 10.5, 12, 9.5, 11, 11, 10, 900, 1, 1, 1, 1\n"
                           "BBB, N1, 23-Nov-2026, 10, 10, 11, 9, 10, 10, 10, 500, 1, 1, 1, 1\n")
    assert d == {"AAA": (10.5, 12.0, 9.5, 11.0, 900.0, 10.0)}


def test_the_newest_bar_takes_nses_figures(monkeypatch):
    setup(monkeypatch, {"2026-11-23": "AAA, EQ, 23-Nov-2026, 100, 101, 112, 98, 105, 105, 104, 12345, 1, 1, 1, 1\n"})
    r = row("AAA", [[ts(20), 100, 104, 99, 100, 1000], [ts(23), 101, 108, 100, 105, 5000]])        # the stored 23 Nov bar has a short high and volume
    assert nse_prices.patch_rows({"AAA": r}) == 1
    assert r["candles"][-1] == [ts(23), 101.0, 112.0, 98.0, 105.0, 12345]
    assert r["candles"][0][2] == 104                       # an earlier bar with no NSE file is left alone
    assert nse_prices.patch_rows({"AAA": r}) == 0          # idempotent


def test_a_split_or_bonus_is_left_alone(monkeypatch):
    setup(monkeypatch, {"2026-11-23": "AAA, EQ, 23-Nov-2026, 100, 100, 110, 95, 100, 100, 100, 100, 1, 1, 1, 1\n"})
    adjusted = [[ts(20), 50, 52, 49, 50, 1000], [ts(23), 50, 55, 47, 50, 2000]]               # 2:1 split: the stored prices are adjusted, NSE's are not
    r = row("AAA", [list(b) for b in adjusted])
    assert nse_prices.patch_rows({"AAA": r}) == 0 and r["candles"] == adjusted


def test_bse_only_stocks_and_unknown_symbols_are_untouched(monkeypatch):
    setup(monkeypatch, {"2026-11-23": "AAA, EQ, 23-Nov-2026, 100, 101, 112, 98, 105, 105, 104, 12345, 1, 1, 1, 1\n"})
    bse = row("AAA", [[ts(23), 101, 108, 100, 105, 5000]], exchange="BSE")
    other = row("ZZZ", [[ts(23), 101, 108, 100, 105, 5000]])
    assert nse_prices.patch_rows({"AAA": bse, "ZZZ": other}) == 0
    assert bse["candles"][-1][2] == 108 and other["candles"][-1][2] == 108


def test_a_patched_bar_changes_what_the_scanners_see(monkeypatch):
    from patterns import market_lists as ml
    setup(monkeypatch, {"2026-11-23": "AAA, EQ, 23-Nov-2026, 100, 101, 112, 98, 105, 105, 104, 12345, 1, 1, 1, 1\n"})
    prev = [ts(20), 100, 110, 96, 100, 1000]
    r = row("AAA", [prev, [ts(23), 101, 108, 100, 105, 5000]])
    assert ml._inside_bar(r) is not None                   # the stored bar looks inside the day before
    nse_prices.patch_rows({"AAA": r})
    assert ml._inside_bar(r) is None                       # NSE's high (112) and low (98) show it was not


def test_a_renamed_symbol_takes_the_new_symbols_bar(monkeypatch):
    setup(monkeypatch, {"2026-11-23": "ICICILIFE, EQ, 23-Nov-2026, 100, 101, 112, 98, 105, 105, 104, 12345, 1, 1, 1, 1\n"})
    monkeypatch.setattr(nse_prices, "aliases", lambda: {"ICICIPRULI": "ICICILIFE"})
    r = row("ICICIPRULI", [[ts(20), 100, 104, 99, 100, 1000], [ts(23), 101, 108, 100, 105, 5000]])
    assert nse_prices.patch_rows({"ICICIPRULI": r}) == 1 and r["candles"][-1][2] == 112.0


def test_extra_nse_companies_are_main_board_named_and_not_already_covered(monkeypatch, tmp_path):
    import json
    from patterns import nse_extra
    names = tmp_path / "names.json"
    names.write_text(json.dumps({"AAA": "Alpha Ltd", "BBB": "Beta Ltd", "CCC": "Gamma Ltd"}), encoding="utf-8")
    monkeypatch.setattr(nse_extra, "NAMES", str(names))
    monkeypatch.setattr(nse_extra, "symbols", lambda: {"AAA", "BBB", "ZZZETF"})           # ZZZETF has no company name (a fund): dropped
    out = nse_extra.load({"BBB"})                                                           # BBB is already in the sector-mapped universe
    assert out == [{"symbol": "AAA", "name": "Alpha Ltd", "sector": None, "exchange": "NSE"}]


def nse(*lines):
    """An NSE file body from (symbol, open, high, low, close, volume, previous close) tuples."""
    return chr(10).join(f"{s}, EQ, 01-Nov-2026, {pc}, {o}, {h}, {low}, {c}, {c}, {c}, {v}, 1, 1, 1, 1" for s, o, h, low, c, v, pc in lines) + chr(10)


def test_a_session_the_provider_skipped_is_filled_from_nse(monkeypatch):
    setup(monkeypatch, {"2026-11-09": nse(("AAA", 99, 101, 98, 100, 1000, 98)), "2026-11-10": nse(("AAA", 100, 112, 98, 105, 7777, 100))})
    r = row("AAA", [[ts(9), 99, 101, 98, 100, 1000], [ts(11), 105, 108, 104, 107, 2000]])         # no bar for 10 Nov; the 9 Nov bar matches NSE: the anchor
    r["wcandles"] = [[ts(9), 99, 108, 98, 107, 3000]]
    assert nse_prices.patch_rows({"AAA": r}) == 1
    assert [c[0] for c in r["candles"]] == [ts(9), ts(10), ts(11)] and r["candles"][1][2:5] == [112.0, 98.0, 105.0]
    assert r["wcandles"][0][2] == 112.0 and r["wcandles"][0][5] == 1000 + 7777 + 2000              # the week now includes the filled day


def test_a_bar_stamped_with_the_wrong_date_is_corrected(monkeypatch):
    # the provider's "9 Nov" bar holds 10 Nov's prices (close 389.55) and 10 Nov is missing; NSE's 6 Nov bar matches ours, so it is the anchor
    setup(monkeypatch, {"2026-11-06": nse(("AAA", 388, 391, 387, 390.6, 900, 386)), "2026-11-09": nse(("AAA", 391, 398, 390, 395.65, 1100, 390.6)),
                        "2026-11-10": nse(("AAA", 395.7, 396.95, 386, 389.55, 2937929, 395.65))})
    r = row("AAA", [[ts(6), 388, 391, 387, 390.6, 900], [ts(9), 395.7, 396.95, 386, 389.55, 2937929], [ts(11), 389, 391, 388, 389.8, 1200]])
    assert nse_prices.patch_rows({"AAA": r}) == 2
    assert [(c[0], c[4]) for c in r["candles"]] == [(ts(6), 390.6), (ts(9), 395.65), (ts(10), 389.55), (ts(11), 389.8)]


def test_a_gap_is_not_filled_across_a_split(monkeypatch):
    setup(monkeypatch, {"2026-11-09": nse(("AAA", 199, 201, 198, 200, 1000, 196)), "2026-11-10": nse(("AAA", 200, 212, 198, 205, 7777, 200))})
    r = row("AAA", [[ts(9), 99, 101, 98, 100, 1000], [ts(11), 105, 108, 104, 107, 2000]])         # NSE's closes are double the stored ones: a split, nothing matches
    assert nse_prices.patch_rows({"AAA": r}) == 0 and len(r["candles"]) == 2
