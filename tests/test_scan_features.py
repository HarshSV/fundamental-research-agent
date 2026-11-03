"""Scanner features, filters and backtest. Synthetic stocks only - never a real company."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from patterns import features, scan, screen_engine as eng  # noqa: E402

DAY = 86400
T0 = 1_600_000_000 - (1_600_000_000 % DAY)


def bars(closes, spread=0.01, volume=1000.0):
    """Daily candles from closes: high/low a fixed fraction either side."""
    return [{"time": T0 + i * DAY, "open": c, "high": c * (1 + spread), "low": c * (1 - spread), "close": c, "volume": volume}
            for i, c in enumerate(closes)]


# -- metrics --------------------------------------------------------------------------------------------------------
def test_metrics_on_a_steady_uptrend():
    c = bars([100 + i * 0.5 for i in range(400)])
    m = features.metrics(c)
    assert m["price"] == c[-1]["close"]
    assert m["new_high_days"] == 0                                   # today made the 52-week high
    assert m["pct_from_52w_high"] == pytest.approx((c[-1]["high"] - c[-1]["close"]) / c[-1]["high"] * 100)
    assert m["pct_from_52w_low"] > 0 and m["pct_from_ath"] == pytest.approx(m["pct_from_52w_high"])
    assert m["ma_up_days"]["200"] == 400 - 200                       # the 200-day average rose on every day it existed after the first
    assert m["rs_raw"] > 0 and m["adr"]["5"] == pytest.approx(((1.01 / 0.99) - 1) * 100)
    assert m["turnover_30d_cr"] == pytest.approx(sum(x["close"] * 1000 for x in c[-30:]) / 30 / 1e7)
    assert m["sma"]["20"] == pytest.approx(sum(x["close"] for x in c[-20:]) / 20)


def test_metrics_never_invent_values_for_short_history_or_missing_volume():
    c = bars([100.0 + (i % 5) for i in range(60)], volume=0.0)
    m = features.metrics(c)
    assert m["rs_raw"] is None and m["new_high_days"] is None        # fewer than a year of bars
    assert m["pct_from_52w_high"] is None and m["ret_1y"] is None
    assert m["turnover_30d_cr"] is None and m["avg_volume_30d"] is None   # no volume: unknown, not zero
    assert m["sma"]["200"] is None and m["ma_up_days"]["200"] is None


# -- horizontal resistance ------------------------------------------------------------------------------------------
def _resistance_series(last_close, extra=()):
    """~100 bars rising and falling back from three pivot highs of 100, ending at last_close."""
    c = []
    for _ in range(3):                                                # three humps, each peaking at ~100 (high = 100.99)
        c += [90, 92, 94, 96, 98, 99.0, 98, 96, 94, 92, 90, 90, 90, 90, 90]
    c += list(extra) + [last_close]
    return bars(c)


def test_resistance_near():
    r = features.resistance(_resistance_series(98.5))
    assert r and r["state"] == "near" and r["touches"] >= 3
    assert 98 < r["level"] < 101 and r["dist_pct"] < 0


def test_resistance_breakout_only_if_the_first_close_above_is_recent():
    r = features.resistance(_resistance_series(101.5))               # first close above the zone is the last bar
    assert r and r["state"] == "breakout" and r["dist_pct"] > 0
    assert features.resistance(_resistance_series(101.5, extra=[101.6, 101.7, 101.8, 101.9])) is None   # broke out long ago


def test_resistance_needs_three_touches_and_not_far_away():
    two = bars([90, 92, 94, 96, 98, 99.0, 98, 96, 94, 92, 90, 90, 90, 90, 90] * 2 + [97.0])
    assert features.resistance(two) is None
    assert features.resistance(_resistance_series(80.0)) is None     # 20% under the level: not "near"


# -- backtest trades ------------------------------------------------------------------------------------------------
def test_trades_follow_the_patterns_direction_and_never_invent_a_horizon():
    c = bars([100.0 + i for i in range(70)])
    i = 25
    occ = [
        {"pattern": "p", "status": "confirmed", "direction": "bullish", "confirmed_ts": c[i]["time"]},
        {"pattern": "q", "status": "confirmed", "direction": "bearish", "confirmed_ts": c[i]["time"]},
        {"pattern": "r", "status": "forming", "direction": "bullish", "confirmed_ts": None},
        {"pattern": "s", "status": "confirmed", "direction": None, "confirmed_ts": c[i]["time"]},
    ]
    got = {t[0]: t for t in features.trades(occ, c)}
    assert set(got) == {"p", "q"}                                     # only confirmed ones with a direction
    assert got["p"][4] == pytest.approx((c[i + 5]["close"] / c[i]["close"] - 1) * 100, abs=0.01)
    assert got["q"][4] == pytest.approx(-got["p"][4], abs=0.01)       # a bearish pattern is a short
    assert got["p"][8] is None and got["p"][7] is not None            # 60 bars ahead does not exist yet; 40 does
    assert features.trades(occ, c)[0][3] == round(c[i]["close"], 2)


# -- filter engine ---------------------------------------------------------------------------------------------------
def row(sym, **kw):
    base = {"symbol": sym, "name": sym, "sector": "Banks", "index": "large", "price": 100.0, "market_cap_cr": 5000.0,
            "ema": {"50": 90.0}, "sma": {"20": 95.0, "50": 90.0, "200": 80.0}, "rs": 80, "pct_from_52w_high": 5.0,
            "pct_from_52w_low": 40.0, "pct_from_ath": 10.0, "new_high_days": 3, "ma_up_days": {"200": 50},
            "adr": {"5": 3.0}, "turnover_30d_cr": 20.0, "avg_volume_30d": 1e6, "pe": 20.0, "promoter": 60.0, "free_float": 40.0,
            "resistance": None, "occurrences": [], "trades": [], "candles": [], "closes": []}
    base.update(kw)
    return base


def run(monkeypatch, rows, pattern="all", **f):
    monkeypatch.setattr(scan, "_load_all", lambda: {r["symbol"]: r for r in rows})
    monkeypatch.setattr(scan, "status", lambda: {})
    monkeypatch.setattr(scan, "benchmarks", lambda: {})
    return [r["symbol"] for r in eng.search(pattern, f)["rows"]]


def test_range_filters_never_match_an_unknown_value(monkeypatch):
    rows = [row("A", rs=90), row("B", rs=40), row("C", rs=None)]
    assert sorted(run(monkeypatch, rows, rs={"min": 50})) == ["A"]
    assert sorted(run(monkeypatch, rows, rs={"min": 30, "max": 95})) == ["A", "B"]      # C is unknown, not 0
    assert sorted(run(monkeypatch, rows)) == ["A", "B", "C"]                             # no filter: unknown is still listed
    assert run(monkeypatch, [row("P", pe=None), row("Q", pe=12.0)], pe={"max": 15}) == ["Q"]


def test_technical_filters(monkeypatch):
    rows = [row("OK"), row("LOWRS", rs=20), row("NOHIGH", new_high_days=100), row("DOWN", ma_up_days={"200": 5}),
            row("QUIET", adr={"5": 1.0}), row("DISORDER", sma={"20": 85.0, "50": 90.0, "200": 80.0}),
            row("THIN", turnover_30d_cr=2.0), row("NOMA", sma={"20": 95.0, "50": 90.0, "200": None})]
    f = dict(rs={"min": 50}, near_high={"sessions": 10}, ma_uptrend={"period": 200, "months": 1}, adr={"days": 5, "min": 2.0},
             ma_order={"kind": "sma", "periods": [20, 50, 200]}, turnover={"min": 5.0})
    assert run(monkeypatch, rows, **f) == ["OK"]


def test_resistance_filter_and_scanner(monkeypatch):
    near = {"level": 100.0, "touches": 3, "state": "near", "dist_pct": -2.0, "first_ts": 1, "last_touch_ts": 2, "touch_ts": []}
    brk = {**near, "state": "breakout", "dist_pct": 1.0}
    rows = [row("N", resistance=near), row("B", resistance=brk), row("X")]
    assert sorted(run(monkeypatch, rows, pattern="horizontal-resistance")) == ["B", "N"]       # the scanner always requires one
    assert run(monkeypatch, rows, pattern="horizontal-resistance", resistance={"states": ["breakout"]}) == ["B"]
    assert sorted(run(monkeypatch, rows, resistance={"require": True})) == ["B", "N"]          # the option on any search
    assert sorted(run(monkeypatch, rows)) == ["B", "N", "X"]


# -- backtest --------------------------------------------------------------------------------------------------------
def test_backtest_statistics(monkeypatch):
    def t(ts, r20):
        return ["vcp", "bullish", ts, 100.0, None, None, r20, None, None]

    rows = [row("A", trades=[t(T0 + 5 * DAY, 10.0), t(T0 + 400 * DAY, -5.0), ["flag", "bullish", T0, 1.0, 1, 1, 1, 1, 1]]),
            row("B", index="small", trades=[t(T0 + 9 * DAY, 20.0), t(T0 + 12 * DAY, None)])]
    monkeypatch.setattr(scan, "_load_all", lambda: {r["symbol"]: r for r in rows})
    monkeypatch.setattr(scan, "status", lambda: {})
    monkeypatch.setattr(scan, "benchmarks", lambda: {})
    res = eng.backtest("vcp", {"horizon": 20})
    s = res["stats"]["20"]
    assert res["trades_total"] == 4 and s["n"] == 3                  # the trade with no 20-bar result is not counted in the stats
    assert s["win_rate"] == pytest.approx(66.7, abs=0.1) and s["avg"] == pytest.approx(8.33, abs=0.01)
    assert s["best"] == 20.0 and s["worst"] == -5.0 and s["profit_factor"] == pytest.approx(30 / 5)
    assert res["stats"]["5"]["n"] == 0 and sum(b["n"] for b in res["histogram"]) == 3
    from datetime import datetime, timezone
    years = sorted({datetime.fromtimestamp(x + 19800, timezone.utc).year for x in (T0 + 5 * DAY, T0 + 9 * DAY, T0 + 12 * DAY, T0 + 400 * DAY)})
    assert [y["year"] for y in res["by_year"]] == years
    only_small = eng.backtest("vcp", {"horizon": 20, "indices": {"values": ["small"]}})
    assert only_small["stocks"] == 1 and only_small["trades_total"] == 2
    assert res["trades"][0]["confirmed_ts"] == T0 + 400 * DAY       # newest first


# -- sector rotation -------------------------------------------------------------------------------------------------
def test_rrg_puts_an_accelerating_sector_in_a_strong_quadrant(monkeypatch):
    n = 80
    ts = [T0 + i * DAY for i in range(n)]
    bench = [[t, 100.0 + i * 0.1] for i, t in enumerate(ts)]
    strong = [100.0 * (1.004 ** i) * (1.002 ** (max(0, i - 40) ** 1.0)) for i in range(n)]     # outruns the index, faster late
    weak = [100.0 * (0.998 ** i) for i in range(n)]

    def rows_for(prefix, series, sector):
        return {f"{prefix}{k}": {"symbol": f"{prefix}{k}", "sector": sector, "closes": [[t, c] for t, c in zip(ts, series)]} for k in range(4)}

    rows = {**rows_for("S", strong, "Strong"), **rows_for("W", weak, "Weak")}
    monkeypatch.setattr(scan, "benchmarks", lambda: {"nifty50": bench})
    q = eng.rrg_quadrants(rows)
    assert set(q) == {"Strong", "Weak"}
    assert q["Strong"]["ratio"] > q["Weak"]["ratio"]
    assert q["Weak"]["quadrant"] in ("lagging", "improving") and q["Strong"]["quadrant"] in ("leading", "weakening")
