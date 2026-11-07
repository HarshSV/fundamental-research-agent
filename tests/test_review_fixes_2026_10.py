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


def test_promoter_pledge_uses_the_promoters_own_encumbered_shares(monkeypatch):
    """NSE's percSharesPledged is an all-holder figure; the promoter pledge is percPromoterShares / totPromoterShares."""
    from tools import shareholding_scraper as sh
    row = {"shp": "30-Sep-2026", "percSharesPledged": "4.16", "numSharesPledged": "3070312", "percPromoterShares": "     0.00",
           "totPromoterShares": "0", "percPromoterHolding": "    57.18", "totPromoterHolding": "42205601", "totIssuedShares": "73808451"}
    p = sh.NSEShareholdingProvider.__new__(sh.NSEShareholdingProvider)
    monkeypatch.setattr(sh, "_read_cache", lambda *a, **k: None)
    monkeypatch.setattr(sh, "_write_cache", lambda *a, **k: None)
    monkeypatch.setattr(p, "_session_get", lambda *a, **k: {"data": [row]}, raising=False)
    r = p.fetch_pledge("X")
    assert r["promoter_pledge_pct"] == 0.0 and r["num_shares_pledged"] == 0.0
    assert p.fetch_pledge_trend("X") == [{"quarter": "30-Sep-2026", "pledge_pct": 0.0}]
    rows = p.fetch_pledge_rows("X")
    assert rows["status"] == "ok" and rows["rows"][0]["pledge_pct"] == 0.0
    monkeypatch.setattr(p, "_session_get", lambda *a, **k: {"data": []}, raising=False)
    assert p.fetch_pledge_rows("X")["status"] == "none"
    monkeypatch.setattr(p, "_session_get", lambda *a, **k: None, raising=False)
    assert p.fetch_pledge_rows("X")["status"] == "unavailable"


def _stmt(rev, ni, ebit, intr):
    return {"Total Revenue": rev, "Net Income": ni, "EBIT": ebit, "Interest Expense": intr}


def test_key_ratios_on_both_bases_and_never_zero_filled():
    from screens import key_ratios as kr
    q = {f"20{y}-{m}-28": _stmt(100.0 + i, 5.0, 10.0, 1.0) for i, (y, m) in enumerate([(24, "09"), (24, "12"), (25, "03"), (25, "06"), (25, "09"), (25, "12"), (26, "03"), (26, "06")])}
    payload = {
        "financial_arrays": {
            "income_stmt": {"2025-03-31": _stmt(1000.0, 80.0, 150.0, 25.0), "2026-03-31": _stmt(1100.0, 99.0, 170.0, 20.0), "TTM": _stmt(1200.0, 120.0, 180.0, 0.0)},
            "balance_sheet": {"2026-03-31": {"Stockholders Equity": 600.0}, "2026-09-30": {"Stockholders Equity": 800.0}},
            "quarterly_income_stmt": q,
        },
        "info": {"bookValue": 50.0, "dividendYield": 0.0},
        "shareholding": {"latest": {"promoter": 61.5}},
    }
    r = kr.compute(payload)
    assert r["annual_label"] == "FY26"
    assert r["roe"] == {"ttm": 15.0, "annual": 16.5}                 # TTM profit / latest equity, FY profit / FY equity
    assert r["net_margin"] == {"ttm": 10.0, "annual": 9.0}
    assert r["revenue_growth"]["annual"] == 10.0
    assert r["revenue_growth"]["ttm"] == round((sum(100 + i for i in range(4, 8)) / sum(100 + i for i in range(0, 4)) - 1) * 100, 2)
    assert r["interest_coverage"]["annual"] == 8.5
    assert r["interest_coverage"]["ttm"] is None                      # no interest cost: not a meaningful number, not infinity or 0
    assert r["dividend_yield"] == 0.0 and r["promoter"] == 61.5 and r["book_value"] == 50.0
    assert kr.compute(payload, financial=True)["interest_coverage"] is None
    assert kr.compute(None) is None
    empty = kr.compute({"financial_arrays": {}, "info": {}})
    assert empty["roe"] == {"ttm": None, "annual": None} and empty["promoter"] is None and empty["dividend_yield"] is None


def test_pattern_catalogue_carries_a_bias_matching_what_the_scanner_finds():
    from patterns.registry import catalogue
    b = {c["id"]: c["bias"] for c in catalogue()}
    assert set(b.values()) == {"bullish", "bearish", "both"}
    assert b["double-bottom"] == b["cup-and-handle"] == b["falling-wedge"] == "bullish"
    assert b["double-top"] == b["head-and-shoulders"] == b["rising-wedge"] == b["descending-triangle"] == "bearish"
    assert b["flag"] == b["order-block"] == b["symmetrical-triangle"] == b["rectangle"] == "both"


def test_company_leader_comes_from_the_officer_list_and_never_from_a_subsidiary_head():
    from tools.company_profile import _clean_name, _leader_from_officers as lead
    assert lead([{"name": "Mr. Tarun Sanjay Mehta", "title": "Co-Founder, Executive Director & CEO"}, {"name": "Mr. X", "title": "Chief Financial Officer"}]) == {"name": "Tarun Sanjay Mehta", "title": "MD / CEO"}
    # a title carrying both ranks wins; the head of a brand or subsidiary is not the company's own head
    out = lead([{"name": "Mr. C. S. Shekar", "title": "Chief Executive Officer of UNLIMITED"}, {"name": "Ms. Amisha Hemchand Jain", "title": "CEO & MD"}])
    assert out["name"] == "Amisha Hemchand Jain"
    assert lead([{"name": "Mr. S", "title": "Chief Executive Officer of Arrow"}]) is None
    # no CEO or MD among the officers: unknown, not a guess
    assert lead([{"name": "Mr. R", "title": "Whole-Time Executive Director"}, {"name": "Mr. A", "title": "Chief Financial Officer"}]) is None
    assert lead([]) is None and lead(None) is None
    assert _clean_name("Dr.  Rajan  Venkatesh") == "Rajan Venkatesh"
    assert _clean_name("Mr. Amit  Jain A.C.A.") == "Amit Jain"


def test_a_profile_saved_without_a_leader_is_looked_up_again_soon(monkeypatch):
    from tools import company_profile as cp
    saved = {"paragraphs": ["x"], "headquarters": "Y", "incorporation_year": None, "leader": None, "website": "z", "source": "nse"}
    ttls = []

    def fake_get(key, ttl):
        ttls.append(ttl)
        return saved if ttl == cp._PROFILE_TTL else None        # fresh for a week, but older than the short window

    monkeypatch.setattr(cp, "_cache_get", fake_get)
    monkeypatch.setattr(cp, "_cache_put", lambda *a, **k: None)
    monkeypatch.setattr(cp, "_from_nse", lambda s: {"paragraphs": ["x"], "headquarters": "Y", "leader": {"name": "A B", "title": "MD / CEO"}, "website": "z", "source": "nse"})
    monkeypatch.setattr(cp, "_from_yahoo", lambda s: None)
    monkeypatch.setattr(cp, "latest_annual_report", lambda *a, **k: None)
    assert cp.get_profile("ABC")["leader"] == {"name": "A B", "title": "MD / CEO"}
    assert cp._LEADERLESS_TTL in ttls


def test_incorporation_year_is_read_from_the_description_when_the_field_is_missing():
    from tools.company_profile import _year_from_text as yr
    assert yr(["ATHER ENERGY LIMITED, is a Public Listed Company incorporated in the year 2013 and engaged in Automobiles."]) == 2013
    assert yr(["The company was founded in 1946 by X."]) == 1946
    assert yr(["It was incorporated on 15th March 1985 as a private limited company."]) == 1985
    assert yr(["Revenue grew in 2025. No founding statement here."]) is None
    assert yr(["incorporated in 1750"]) is None and yr([]) is None and yr(None) is None


def test_deputy_md_is_not_the_md_and_a_titled_officer_beats_a_bare_name():
    from tools.company_profile import _leader_from_officers as lead
    assert lead([{"name": "Mr. Kaizad Bharucha", "title": "Deputy MD & Director"}, {"name": "Mr. Anup Bagchi B.Tech, PGDM", "title": "MD, CEO & Director"}]) == {"name": "Anup Bagchi", "title": "MD / CEO"}
    assert lead([{"name": "Mr. K", "title": "Deputy Managing Director"}]) is None


def test_a_row_built_from_a_headline_only_page_is_partial_and_retried_with_backoff():
    from screens import universe as u
    full = {"fund_ok": True, "fund_full": True, "eps": 5.0, "promoter": 50.0}
    headline = {"fund_ok": True, "fund_full": False, "pe": 30.0, "fund_at": 1000, "fund_tries": 0}
    legacy = {"fund_ok": True, "pe": 30.0, "eps": None, "promoter": None, "net_profit_cr": None, "fund_at": 1000}   # saved before fund_full existed
    legacy_ok = {"fund_ok": True, "pe": 30.0, "eps": 2.0, "promoter": None, "net_profit_cr": None}
    assert not u.is_partial(full) and u.is_partial(headline) and u.is_partial(legacy) and not u.is_partial(legacy_ok)
    assert not u.is_partial({"fund_ok": False}) and not u.is_partial(None)
    assert not u.partial_due(headline, now=1000 + 60) and u.partial_due(headline, now=1000 + u.PARTIAL_RETRY_SECONDS + 1)
    again = dict(headline, fund_tries=2)                                  # 30 min, 1h, 2h ...: a page that never parses is not hammered
    assert not u.partial_due(again, now=1000 + 3 * u.PARTIAL_RETRY_SECONDS) and u.partial_due(again, now=1000 + 4 * u.PARTIAL_RETRY_SECONDS + 1)
    assert not u.partial_due(full, now=10 ** 12)


def test_nse_fill_takes_only_positive_figures_and_never_overwrites(monkeypatch):
    import types
    from screens import universe as u
    payload = {"data": {"peRatio": 0, "promoterHolding": 61.2, "divYield": 0, "netProfit": 1205.0, "debtToEquity": 0.4}}

    class R:
        status_code = 200
        def json(self):
            return payload

    monkeypatch.setitem(__import__("sys").modules, "requests", types.SimpleNamespace(get=lambda *a, **k: R()))
    m = {"pe": None, "promoter": None, "div_yield": None, "net_profit_cr": 99.0, "debt_equity": None}
    filled = u._nse_fill("ZZTEST", m)
    assert m["promoter"] == 61.2 and m["debt_equity"] == 0.4 and "promoter" in filled
    assert m["pe"] is None and m["div_yield"] is None            # NSE's 0 means "not available": stays unknown, not zero
    assert m["net_profit_cr"] == 99.0                            # an existing value is never replaced


def test_empty_consolidated_skeleton_is_told_apart_from_a_real_page():
    from tools import screener_scraper as ss
    skeleton = '<section id="profit-loss"><table><thead><tr><th class="text"></th></tr></thead><tbody><tr><td>Sales</td></tr></tbody></table></section>'
    real = '<section id="profit-loss"><table><thead><tr><th data-date-key="2026-03-31">Mar 2026</th></tr></thead></table></section>'
    assert not ss._has_columns(skeleton) and ss._has_columns(real) and not ss._has_columns("<html></html>")


def test_a_standalone_only_company_is_read_from_its_standalone_page_but_a_dual_one_never_is(monkeypatch):
    from tools import screener_scraper as ss
    skeleton = '<section id="profit-loss"><table><thead><tr><th class="text"></th></tr></thead></table></section>'
    dated = '<section id="profit-loss"><table><thead><tr><th data-date-key="2026-03-31">Mar 2026</th></tr></thead></table></section>'
    monkeypatch.setattr(ss, "_read_cache", lambda *a, **k: None)
    monkeypatch.setattr(ss, "_write_cache", lambda *a, **k: None)
    monkeypatch.setattr(ss.time, "sleep", lambda s: None)
    seen = {}

    def run(standalone_html):
        pages = {"/company/ZZ/consolidated/": skeleton, "/company/ZZ/": standalone_html}
        monkeypatch.setattr(ss, "_get", lambda url: next((v for k, v in pages.items() if url.endswith(k)), None))
        monkeypatch.setattr(ss, "_build_income_grid", lambda t: seen.setdefault("grid", {}) or {})
        return ss.fetch_screener_financials("ZZ", None, fresh=True)

    # standalone page without a link to consolidated accounts: it is the company's only page, so it is read (the parse step
    # then decides; here it is stubbed to give nothing, which returns None, but the standalone page must have been chosen)
    chosen = []
    monkeypatch.setattr(ss, "_parse_data_table", lambda html, sec: chosen.append(html) or {})
    run(dated)
    assert chosen and chosen[0] is dated
    # a standalone page that links to consolidated accounts must never stand in for them
    chosen.clear()
    assert run(dated + '<a href="/company/ZZ/consolidated/">View Consolidated</a>') is None
    assert not chosen
