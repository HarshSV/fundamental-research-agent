"""Setup layer: opening-range breakout, oversold bounce, horizontal resistance."""
import datetime as dt

from setups import engine

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _t(day, hh, mm):
    return int(dt.datetime(*day, hh, mm, tzinfo=IST).timestamp())


def _intraday(closes, day=(2026, 10, 30), vol=100):
    """5-minute bars from 09:15; each bar's high/low is close +/- 0.2."""
    out = []
    for i, c in enumerate(closes):
        m = 9 * 60 + 15 + 5 * i
        out.append({"time": _t(day, m // 60, m % 60), "open": c, "high": c + 0.2, "low": c - 0.2, "close": c, "volume": vol})
    return out


def test_orb_forming_until_first_fifteen_minutes_done():
    r = engine.orb(_intraday([100, 100.1]))
    assert r["state"] == "forming" and r["direction"] is None


def test_orb_waiting_while_inside_the_range():
    r = engine.orb(_intraday([100, 100.1, 100.0, 100.05, 100.1]))
    assert r["state"] == "waiting"
    assert r["range_high"] == 100.3 and r["range_low"] == 99.8


def test_orb_triggers_on_first_close_above_the_range():
    r = engine.orb(_intraday([100, 100.1, 100.0, 100.1, 100.6, 100.8]))
    assert r["state"] == "triggered" and r["direction"] == "bullish"
    assert r["trigger_price"] == 100.6 and r["trigger_time"] == "09:35"


def test_orb_short_trigger_and_failure():
    short = engine.orb(_intraday([100, 100.1, 100.0, 99.4, 99.2]))
    assert short["state"] == "triggered" and short["direction"] == "bearish"
    failed = engine.orb(_intraday([100, 100.1, 100.0, 100.6, 100.0, 99.9]))
    assert failed["state"] == "failed"


def test_orb_no_breakout_after_the_session_ends():
    flat = [100 + (i % 2) * 0.1 for i in range(75)]
    assert engine.orb(_intraday(flat))["state"] == "no_breakout"


def test_orb_uses_only_the_requested_session():
    two = _intraday([100, 100.1, 100.0, 100.6], day=(2026, 10, 29)) + _intraday([200, 200.1, 200.0, 200.05], day=(2026, 10, 30))
    assert engine.orb(two)["range_high"] == 200.3
    assert engine.orb(two, session="2026-10-29")["state"] == "triggered"


def _daily(closes):
    return [{"time": 1_700_000_000 + i * 86400, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1000}
            for i, c in enumerate(closes)]


def test_rsi_bounds_and_oversold_waiting():
    falling = _daily([200 - i for i in range(60)])
    r = engine.rsi([b["close"] for b in falling])
    assert r[-1] is not None and r[-1] < 30
    assert engine.oversold(falling)["state"] == "waiting"


def test_oversold_triggers_when_price_clears_the_previous_high():
    closes = [200 - i for i in range(60)] + [150]            # sharp rebound bar after a long slide
    r = engine.oversold(_daily(closes))
    assert r["state"] == "triggered"


def test_oversold_inactive_in_an_uptrend_and_forming_when_short():
    assert engine.oversold(_daily([100 + i for i in range(60)]))["state"] == "inactive"
    assert engine.oversold(_daily([100, 101, 102]))["state"] == "forming"


def test_analyse_summary_counts_active_setups():
    out = engine.analyse("X", _intraday([100, 100.1, 100.0, 100.1, 100.6]), _daily([200 - i for i in range(60)]))
    assert out["session"] == "2026-10-30" and len(out["setups"]) == 3
    assert out["summary"]["active"] == out["summary"]["triggered"] + out["summary"]["waiting"]
    assert out["summary"]["triggered"] >= 1


def test_adr_is_none_without_enough_days():
    assert engine.adr_pct(_daily([100, 101])) is None
    assert engine.adr_pct(_daily([100] * 30)) == (1.01 / 0.99 - 1) * 100


# ---------------------------------------------------------------- plan layer
from setups.plan import plan_for


def test_orb_plan_when_triggered_uses_range_midpoint_and_one_r():
    setup = engine.orb(_intraday([100, 100.1, 100.0, 100.1, 100.6, 100.8]))
    (p,) = plan_for(setup, _daily([100] * 30), 1.0)
    assert p["side"] == "long" and p["entry"] == 100.6 and p["conditional"] is False
    assert p["stop"] == 100.05                      # (100.3 + 99.8) / 2
    assert p["risk_per_share"] == 0.55 and p["targets"][0]["r"] == 1.0 and p["targets"][0]["price"] == 101.15


def test_orb_plan_waiting_offers_both_sides_as_conditional():
    setup = engine.orb(_intraday([100, 100.1, 100.0, 100.05]))
    plans = plan_for(setup, _daily([100] * 30), 1.0)
    assert [p["side"] for p in plans] == ["long", "short"] and all(p["conditional"] for p in plans)
    assert plans[0]["entry"] == 100.3 and plans[1]["entry"] == 99.8
    assert plans[0]["stop"] == plans[1]["stop"] == 100.05


def test_plan_flags_a_stop_inside_normal_noise_and_one_that_is_too_wide():
    setup = engine.orb(_intraday([100, 100.1, 100.0, 100.1, 100.6]))
    tight = plan_for(setup, _daily([100] * 30), 5.0)[0]            # typical day 5%: a 0.55% stop is noise
    assert any("normal noise" in w for w in tight["warnings"])
    wide = plan_for(setup, _daily([100] * 30), 0.2)[0]             # typical day 0.2%: 0.55% is more than a day
    assert any("larger than" in w or "more than a typical day" in w for w in wide["warnings"])
    assert not plan_for(setup, _daily([100] * 30), 0.9)[0]["warnings"]


def test_no_plan_for_inactive_or_unjudged_setups():
    assert plan_for({"id": "orb", "state": "inactive"}, [], None) is None
    assert plan_for({"id": "orb", "state": "forming"}, [], None) is None
    assert plan_for({"id": "resistance", "state": "waiting", "level": 100}, [], None) is None   # no ADR: no guess


def test_resistance_and_oversold_plans():
    res = plan_for({"id": "resistance", "state": "waiting", "level": 100.0}, _daily([95] * 30), 3.0)[0]
    assert res["entry"] == 100.0 and res["stop"] == 99.25 and res["first_target_r"] == 2.0 and res["conditional"]
    falling = _daily([200 - i for i in range(60)])
    ov = engine.oversold(falling)
    p = plan_for(ov, falling, 2.0)[0]
    assert p["entry"] == ov["trigger_price"] and p["stop"] < p["entry"] and p["conditional"]


def test_analyse_attaches_plans():
    out = engine.analyse("X", _intraday([100, 100.1, 100.0, 100.1, 100.6]), _daily([100] * 30))
    orb = next(s for s in out["setups"] if s["id"] == "orb")
    assert orb["plans"] and orb["plans"][0]["entry"] == 100.6
    assert next(s for s in out["setups"] if s["id"] == "oversold")["plans"] is None


# ---------------------------------------------------------------- forecast (outlook, Time Machine, decisions)
import numpy as np

from setups import outlook


def _trend_daily(n=400, drift=0.001, seed=1):
    rng = np.random.default_rng(seed)
    px, out = 100.0, []
    for i in range(n):
        r = drift + rng.normal(0, 0.01)
        o, px = px, px * (1 + r)
        out.append({"time": 1_600_000_000 + i * 86400, "open": o, "high": max(o, px) * 1.003, "low": min(o, px) * 0.997, "close": px, "volume": 1000})
    return out


def test_horizon_outlook_needs_history_and_returns_probabilities_that_sum_to_100():
    short = outlook.horizon_outlook(_trend_daily(100), 5)
    assert short["call"] is None and "history" in short["reason"]
    r = outlook.horizon_outlook(_trend_daily(500, drift=0.0), 5)
    assert r["call"] in ("up", "down", "even") and r["conviction"] in (None, "slight", "moderate", "strong")
    assert abs(r["up"] + r["flat"] + r["down"] - 100) <= 1
    assert r["p10"] <= r["median"] <= r["p90"] and r["samples"] > 60


def test_horizon_outlook_calls_a_strong_persistent_trend_up():
    r = outlook.horizon_outlook(_trend_daily(600, drift=0.004, seed=3), 5)
    assert r["call"] == "up" and r["up"] > r["down"]


def test_simulation_is_repeatable_and_symmetric_steps_give_balanced_odds():
    steps = [np.array([[1.004, 0.996, 1.0], [1.003, 0.997, 1.001], [1.004, 0.996, 0.999]])] * 40
    a = outlook.simulate("long", 100.0, 99.0, 101.0, 100.0, steps)
    b = outlook.simulate("long", 100.0, 99.0, 101.0, 100.0, steps)
    assert a == b                                           # seeded: anyone can repeat it
    assert a["enters"] == 100 and abs(a["target"] - a["stop"]) <= 15
    assert a["target"] + a["stop"] + a["open"] in (99, 100, 101)


def test_simulation_entry_never_reached_gives_no_numbers():
    steps = [np.array([[1.001, 0.999, 1.0]])] * 10
    r = outlook.simulate("long", 120.0, 119.0, 121.0, 100.0, steps)
    assert r["enters"] == 0 and r["target"] is None


def test_a_bar_touching_stop_and_target_counts_as_the_stop():
    steps = [np.array([[1.02, 0.98, 1.0]])] * 3
    r = outlook.simulate("long", 100.0, 99.0, 101.0, 100.0, steps)
    assert r["stop"] == 100 and r["target"] == 0


def test_replay_orb_counts_each_past_session_once():
    def day(d, closes):
        return _intraday(closes, day=(2026, 10, d))
    flat = [100, 100.1, 100.0] + [100.6 + 0.05 * i for i in range(72)]          # breaks up, keeps rising
    s = {f"2026-10-{d:02d}": day(d, flat) for d in (26, 27, 28)}
    s["2026-10-29"] = day(29, flat)
    rep = outlook.replay_orb(s, "2026-10-29", "long")
    assert rep["trades"] == 3 and rep["target"] == 3 and rep["stop"] == 0


def test_build_with_market_closed_still_gives_a_plan_for_the_next_session():
    out = outlook.build("X", _intraday([100, 100.1, 100.0, 100.1]), _trend_daily(400), None, [])
    assert out["market_open"] is False                       # the bars are from 2026-10-30, not now
    assert out["today"]["plan"] is not None and "closed" in out["today"]["note"] and out["today"]["decision"]["action"].startswith(("Buy", "Sell"))
    assert out["swing"]["plan"] is not None and out["swing"]["edge"]["label"] in ("favourable", "against", "even")
    assert [h["id"] for h in out["outlook"]] == ["session", "week", "month"]
    assert out["outlook"][0]["label"] == "Next session"


def test_evidence_tones_use_only_good_bad_or_neutral():
    row = {"index": "small", "sector": "S", "rs": 85, "pe": 10, "eps_growth": 20, "debt_equity": 2.0, "promoter": 60, "turnover_30d_cr": 0.5}
    peers = [{"pe": 20}] * 6
    ev, liq = outlook.evidence(_trend_daily(300), row, peers)
    tones = {e["label"].split(" (")[0]: e["tone"] for e in ev}
    assert tones["Relative strength"] == "good" and tones["Debt / equity"] == "bad" and tones["Promoter holding"] == "good"
    assert tones["P/E"] == "good" and tones["Average daily turnover"] == "bad"
    assert liq["max_position_inr"] == round(0.5 * 1e7 * 0.02)
    assert {e["tone"] for e in ev} <= {"good", "bad", None}


def test_quarter_rows_compare_with_the_same_quarter_a_year_ago_and_skip_loss_bases():
    q = {f"2025-0{m}-30": {"Total Revenue": 100.0, "Net Income": 10.0} for m in (3, 6, 9)}
    q["2025-12-31"] = {"Total Revenue": 100.0, "Net Income": -5.0}
    q["2026-03-31"] = {"Total Revenue": 100.0, "Net Income": 10.0}
    q["2026-06-30"] = {"Total Revenue": 125.0, "Net Income": 20.0}
    rows = {r["label"]: r for r in outlook.quarter_rows(q)}
    assert rows["Latest quarter sales vs a year ago"]["value"] == "+25.0%" and rows["Latest quarter sales vs a year ago"]["tone"] == "good"
    assert rows["Latest quarter net profit vs a year ago"]["value"] == "+100.0%"
    q["2025-06-30"]["Net Income"] = -2.0                      # last year's quarter was a loss: no % change is shown
    assert "Latest quarter net profit vs a year ago" not in {r["label"] for r in outlook.quarter_rows(q)}
    assert outlook.quarter_rows({"2026-03-31": {}}) == [] and outlook.quarter_rows(None) == []


# ---------------------------------------------------------------- events (NSE / BSE / Google News parsing)
from setups import events


def test_nse_announcements_and_calendar_parse_and_calendar_keeps_only_upcoming():
    rows = [{"an_dt": "30-Oct-2026 19:40:11", "desc": "Outcome of Board Meeting", "attchmntText": "  The Board   approved results ", "attchmntFile": "https://x/y.pdf"},
            {"an_dt": "bad", "desc": "x"}]
    out = events.parse_nse_announcements(rows)
    assert len(out) == 1 and out[0]["title"] == "The Board approved results" and out[0]["source"] == "NSE" and out[0]["link"] == "https://x/y.pdf"
    import datetime as dt
    cal = [{"date": "05-Aug-2005", "purpose": "Demerger", "bm_desc": "old"}, {"date": "08-Nov-2026", "purpose": "Financial Results", "bm_desc": "meeting"}]
    up = events.parse_nse_calendar(cal, dt.date(2026, 11, 4))
    assert [u["date"] for u in up] == ["2026-11-08"]


def test_bse_rows_parse():
    out = events.parse_bse({"Table": [{"NEWS_DT": "2026-11-03T10:15:00", "CATEGORYNAME": "Board Meeting", "NEWSSUB": "Intimation of board meeting", "ATTACHMENTNAME": "a.pdf"}]})
    assert out[0]["source"] == "BSE" and out[0]["link"].endswith("/AttachLive/a.pdf") and out[0]["ts"].startswith("2026-11-03")
    assert events.parse_bse({}) == [] and events.parse_bse({"Table": [{"NEWS_DT": "nonsense"}]}) == []


def test_google_news_keeps_only_headlines_naming_the_company_and_recent_ones():
    import datetime as dt
    xml = """<rss><channel>
      <item><title>HFCL shares jump on order - Mint</title><link>http://a</link><pubDate>Tue, 03 Nov 2026 09:00:00 GMT</pubDate><source>Mint</source></item>
      <item><title>Some other company wins deal - ET</title><link>http://b</link><pubDate>Tue, 03 Nov 2026 09:00:00 GMT</pubDate><source>ET</source></item>
      <item><title>HFCL old story - Mint</title><link>http://c</link><pubDate>Tue, 01 Sep 2026 09:00:00 GMT</pubDate><source>Mint</source></item>
    </channel></rss>"""
    now = dt.datetime(2026, 11, 4, tzinfo=dt.timezone.utc)
    out = events.parse_google_news(xml, "hfcl", now=now, days=14)
    assert [o["title"] for o in out] == ["HFCL shares jump on order"] and out[0]["category"] == "Mint"
    assert events._name_key("Reliance Industries Limited", "RELIANCE") == "reliance"
    assert events._name_key(None, "HFCL") == "hfcl"


def test_collect_survives_a_failing_source_and_reports_which_one(monkeypatch):
    events._cache.clear()
    monkeypatch.setattr(events, "nse", lambda s, days=30: ([{"ts": "2026-11-01T10:00:00", "source": "NSE", "category": "c", "title": "Filing A", "link": None}], []))
    monkeypatch.setattr(events, "google_news", lambda s, n, days=14: (_ for _ in ()).throw(RuntimeError("down")))
    out = events.collect("ZZZ", "Zzz Limited", bse_listed=False)
    assert out["sources"] == {"NSE": "ok", "News": "unavailable"} and [i["title"] for i in out["items"]] == ["Filing A"]


def test_lean_always_names_a_side_unless_the_two_are_level():
    assert outlook.lean(0.34, 0.43) == {"call": "down", "conviction": "slight"}
    assert outlook.lean(0.52, 0.15) == {"call": "up", "conviction": "strong"}
    assert outlook.lean(0.40, 0.25) == {"call": "up", "conviction": "moderate"}
    assert outlook.lean(0.33, 0.32) == {"call": "even", "conviction": None}


def test_key_levels_show_resistance_red_support_green_and_session_range():
    d = _trend_daily(300, drift=0.0, seed=5)
    px = d[-1]["close"]
    rows = outlook.key_levels(d, px, {"label": "Next session", "price_low": px * 0.98, "price_high": px * 1.02})
    labels = {r["label"]: r for r in rows}
    assert "Next session, likely range" in labels and "52-week high / low" in labels
    res = labels.get("Nearest resistance (recent swing high)")
    sup = labels.get("Nearest support (recent swing low)")
    assert (res is None or res["tone"] == "bad") and (sup is None or sup["tone"] == "good")
    assert outlook.key_levels([], None, {}) == []


def test_edge_uses_the_worse_of_simulation_and_replay():
    good = {"target": 50, "stop": 20}
    assert outlook._edge_view(good, 1.0)["label"] == "favourable"
    bad_replay = {"trades": 30, "target": 4, "stop": 21}
    e = outlook._edge_view(good, 1.0, bad_replay)
    assert e["label"] == "against" and e["value"] < 0
    assert outlook._edge_view(good, 1.0, {"trades": 5, "target": 0, "stop": 5})["label"] == "favourable"   # too few past trades to count
    assert outlook._edge_view(None, 1.0) is None


def test_trend_plan_short_side_mirrors_the_long():
    d = _trend_daily(300, drift=-0.003, seed=9)
    adr = engine.adr_pct(d)
    s = outlook._trend_plan(d, len(d) - 1, adr, side="short")
    l = outlook._trend_plan(d, len(d) - 1, adr, side="long")
    assert s["stop"] > s["entry"] > s["targets"][0]["price"] and l["stop"] < l["entry"] < l["targets"][0]["price"]
    assert 0.5 * adr <= s["risk_pct"] + 0.01 and s["risk_pct"] <= 1.5 * adr + 0.01


def test_side_for_follows_the_first_lean_then_the_trend():
    assert outlook._side_for(["up", "down"], None, []) == "long"
    assert outlook._side_for(["even", "down"], "long", []) == "short"
    assert outlook._side_for(["even", "even"], "short", []) == "short"
    assert outlook._side_for([None], None, _trend_daily(250, drift=0.003)) == "long"


def test_a_session_with_under_45_minutes_left_plans_for_the_next_one():
    import datetime as dt
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    assert outlook.minutes_left(dt.datetime(2026, 11, 4, 14, 53, tzinfo=ist)) == 37 < outlook.LATE_MINUTES
    assert outlook.minutes_left(dt.datetime(2026, 11, 4, 11, 0, tzinfo=ist)) == 270 > outlook.LATE_MINUTES
    # the block's own wording when it is called with a closed session and the late flag
    out = outlook.build("X", _intraday([100, 100.1, 100.0, 100.1]), _trend_daily(400), None, [])
    assert out["session_late"] is False and out["today"]["plan"] is not None
    blk = outlook._today_block({"state": "waiting", "direction": None}, False, [], {}, None, _trend_daily(400), 2.0, None, "up", "up", True)
    assert "within 45 minutes" in blk["note"] and blk["plan"]["side"] == "long"
