"""Regression tests for the 2026-10-31 site review fixes."""
import math

from patterns.features import resistance_trades
from screens import metrics
from tools import live_chart_yf as lc
from tools.screener_scraper import _parse_peers_table


def test_finite_helper_rejects_nan_and_none():
    assert lc._finite(1, 2.5, 3)
    assert not lc._finite(1, float("nan"))
    assert not lc._finite(None, 1)
    assert lc._vol(float("nan")) == 0.0 and lc._vol(12) == 12.0


def test_pe_prefers_screener_and_ignores_non_positive():
    assert metrics.screener_pe({"trailingPE": 98.1}) == 98.1
    assert metrics.screener_pe({"trailingPE": -3}) is None
    assert metrics.screener_pe({"trailingPE": float("nan")}) is None
    assert metrics.screener_pe({}) is None


def test_debt_equity_not_meaningful_for_negative_book_value():
    bs = {"2026-03-31": {"Total Debt": 100.0, "Stockholders Equity": 50.0}}
    assert metrics.debt_equity({"info": {"bookValue": 10}, "financial_arrays": {"balance_sheet": bs}}) == 2.0
    assert metrics.debt_equity({"info": {"bookValue": -44.1}, "financial_arrays": {"balance_sheet": bs}}) is None
    assert metrics.debt_equity(None) is None


def test_financial_sectors():
    for s in ("Banks", "NBFC", "Insurance", "Capital Markets (Broking/AMC/Exchanges)"):
        assert metrics.is_financial(s)
    for s in ("Information Technology", "Construction", None):
        assert not metrics.is_financial(s)


def test_peer_names_are_unescaped():
    row = ('<tr><td>1.</td><td><a href="/company/M&amp;M/consolidated/">M &amp; M</a></td>' + "<td>1</td>" * 9 + "</tr>")
    peers = _parse_peers_table(f"<table>{row}</table>")
    assert peers and peers[0]["name"] == "M & M" and peers[0]["symbol"] == "M&M"


def _bars(closes_highs):
    return [{"time": 1_600_000_000 + i * 86400, "open": c, "high": h, "low": c * 0.99, "close": c, "volume": 1}
            for i, (c, h) in enumerate(closes_highs)]


def test_resistance_trades_finds_a_breakout_once():
    # flat ~100 range with repeated tops at 105, then a close above, then drift up
    seq = []
    for i in range(120):
        top = 105 if i % 12 == 6 else 101
        seq.append((100 + (i % 3) * 0.2, top))
    seq += [(106, 107), (107, 108), (108, 109), (109, 110), (110, 111)] + [(110 + k * 0.1, 111 + k * 0.1) for k in range(80)]
    out = resistance_trades(_bars(seq), years=10)
    assert out, "the breakout through the 105 zone should be recorded"
    assert all(t[0] == "horizontal-resistance" and t[1] == "bullish" for t in out)
    assert math.isfinite(out[0][3])


def test_demerger_adjustment_scales_the_history_before_the_event():
    import datetime as dt
    from tools.price_adjust import adjust_for_demergers
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    t0 = int(dt.datetime(2025, 1, 1, tzinfo=ist).timestamp())
    candles = []
    for i in range(120):
        px = 1000.0 if i < 60 else 400.0                  # a 60% fall on bar 60: unadjusted demerger
        candles.append({"time": t0 + i * 86400, "open": px, "high": px * 1.01, "low": px * 0.99, "close": px, "volume": 1})
    day = lambda i: dt.datetime.fromtimestamp(candles[i]["time"], ist).strftime("%Y-%m-%d")
    ref = lambda *_: [(day(i), (400.0 if i < 60 else 400.0)) for i in range(0, 120, 4)]     # Screener: already adjusted
    out = adjust_for_demergers(candles, "X", ref=ref)
    assert out[0]["close"] == 400.0 and out[59]["close"] == 400.0 and out[60]["close"] == 400.0
    # a real crash that Screener also shows is left alone
    same = lambda *_: [(day(i), candles[i]["close"]) for i in range(0, 120, 4)]
    assert adjust_for_demergers(candles, "X", ref=same)[0]["close"] == 1000.0
    # no Screener data: unchanged
    assert adjust_for_demergers(candles, "X", ref=lambda *_: None)[0]["close"] == 1000.0


def test_empty_newest_daily_row_is_rebuilt_from_intraday_bars(monkeypatch):
    import pandas as pd
    idx_d = pd.DatetimeIndex(["2026-10-29", "2026-10-30"], tz="Asia/Kolkata")
    daily = pd.DataFrame({"Open": [10.0, float("nan")], "High": [11.0, float("nan")], "Low": [9.0, float("nan")],
                          "Close": [10.5, float("nan")], "Volume": [100.0, float("nan")]}, index=idx_d)
    idx_m = pd.DatetimeIndex(["2026-10-30 09:15", "2026-10-30 09:20", "2026-10-30 15:25"], tz="Asia/Kolkata")
    intra = pd.DataFrame({"Open": [10.6, 10.7, 10.9], "High": [10.8, 10.9, 11.2], "Low": [10.5, 10.6, 10.8],
                          "Close": [10.7, 10.8, 11.0], "Volume": [5.0, 6.0, 7.0]}, index=idx_m)

    class FakeTicker:
        def __init__(self, *_):
            pass

        def history(self, period=None, interval=None, auto_adjust=False):
            return daily if interval == "1d" else intra

    monkeypatch.setattr(lc.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(lc, "_HAVE_YF", True)
    monkeypatch.setattr(lc, "_to_symbol", lambda s: s + ".NS")
    c = lc.get_candles("X", interval="1d", period="1mo")
    assert len(c) == 2
    last = c[-1]
    assert (last["open"], last["high"], last["low"], last["close"], last["volume"]) == (10.6, 11.2, 10.5, 11.0, 18.0)


def test_screener_financials_cache_is_short_lived_and_can_be_bypassed(tmp_path, monkeypatch):
    import os
    import time
    from tools import screener_scraper as ss
    monkeypatch.setattr(ss, "CACHE_DIR", str(tmp_path))
    ss._write_cache("k", {"a": 1})
    assert ss._read_cache("k") == {"a": 1}
    old = time.time() - 3 * 3600
    os.utime(ss._cache_path("k"), (old, old))
    assert ss._read_cache("k") == {"a": 1}                      # the general 12h cache still serves a 3h-old copy ...
    assert ss._read_cache("k", ss.FIN_TTL) is None              # ... the financials page (2h) does not
    assert ss.FIN_TTL < ss.TTL


def test_a_company_with_a_consolidated_page_is_never_read_from_its_standalone_page(monkeypatch):
    from tools import screener_scraper as ss
    calls = []
    standalone = '<html><div id="profit-loss"></div><a href="/company/ABC/consolidated/">Consolidated</a></html>'

    def fake_get(url):
        calls.append(url)
        return standalone if url.endswith("/company/ABC/") else None        # the consolidated request keeps failing (throttled)

    monkeypatch.setattr(ss, "_get", fake_get)
    monkeypatch.setattr(ss.time, "sleep", lambda s: None)
    monkeypatch.setattr(ss, "_read_cache", lambda *a, **k: None)
    assert ss.fetch_screener_financials("ABC", None, fresh=True) is None
    assert sum(1 for c in calls if c.endswith("/consolidated/")) == 4         # one first try and three retries
