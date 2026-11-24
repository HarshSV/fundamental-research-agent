"""Weekly setups are judged on finished weeks only (a Monday-only "week" must never count)."""
import datetime as dt
import time

from patterns import market_lists as ml

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def ts(day: int, hour: int = 10) -> float:
    return dt.datetime(2026, 11, day, hour, 0, tzinfo=IST).timestamp()


def bar(day, o, h, l, c):
    return [ts(day), o, h, l, c, 1000]


# week of 9-13 Nov wide, week of 16-20 Nov inside it, then a partial week (23, 24 Nov) that breaks above
BARS = [bar(9, 100, 110, 90, 100), bar(10, 100, 108, 92, 100), bar(11, 100, 106, 94, 100), bar(12, 100, 106, 94, 100), bar(13, 100, 108, 92, 100),
        bar(16, 100, 104, 96, 100), bar(17, 100, 104, 97, 100), bar(18, 100, 103, 97, 100), bar(19, 100, 103, 98, 100), bar(20, 100, 104, 98, 100),
        bar(23, 100, 112, 99, 111), bar(24, 111, 113, 108, 112)]


def row(bars):
    return {"candles": bars, "sma": {"50": 50.0}, "price": bars[-1][4]}


def at(monkeypatch, day, hour=16):
    monkeypatch.setattr(time, "time", lambda: ts(day, hour))


def test_a_partial_trailing_week_is_dropped_midweek(monkeypatch):
    at(monkeypatch, 24)                                     # Tuesday: the 23 to 24 Nov "week" is unfinished
    kept = ml._finished_weeks(BARS)
    assert kept[-1][0] == ts(20)
    assert ml._inside_bar(row(BARS), weekly=True) is not None        # 16-20 Nov sits inside 9-13 Nov


def test_the_week_counts_once_it_is_over(monkeypatch):
    at(monkeypatch, 28)                                     # Saturday: 23 to 24 Nov is all there will be
    assert ml._finished_weeks(BARS) == BARS
    assert ml._inside_bar(row(BARS), weekly=True) is None            # that week broke out above the one before it


def test_a_friday_bar_finishes_the_week_even_on_the_same_day(monkeypatch):
    at(monkeypatch, 20)
    assert ml._finished_weeks(BARS[:10]) == BARS[:10]


def test_weekly_tight_needs_each_close_within_a_point_and_a_half_of_the_week_before(monkeypatch):
    at(monkeypatch, 24)
    flat = [bar(6, 100, 101, 99, 100), bar(13, 100, 101, 99, 100.5), bar(20, 100, 101, 99, 100.8), bar(23, 100, 140, 99, 140)]   # 3 finished weeks, then a partial one
    assert ml._tight_setup(row(flat), weekly=True) is not None       # 100, 100.5, 100.8: steps of 0.5% and 0.3%; the partial week is ignored
    loose = [bar(6, 100, 101, 99, 100), bar(13, 100, 104, 99, 103), bar(20, 100, 106, 99, 105)]
    assert ml._tight_setup(row(loose), weekly=True) is None          # a 3% step is not "tight"


def test_create_screener_tight_control_can_use_the_step_form(monkeypatch):
    at(monkeypatch, 28)
    flat = [bar(6, 100, 101, 99, 100), bar(13, 100, 101, 99, 100.5), bar(20, 100, 101, 99, 100.8)]
    assert ml.check_tight(row(flat), {"timeframe": "weekly", "bars": 3, "step": 1.5}) is True
    assert ml.check_tight(row(flat), {"timeframe": "weekly", "bars": 3, "step": 0.2}) is False


def test_inside_bar_and_tight_setup_return_real_levels(monkeypatch):
    at(monkeypatch, 24)
    sig = ml._inside_bar(row(BARS), weekly=True)
    lv = {x["label"]: x["price"] for x in sig["levels"]}
    assert lv == {"Mother high": 110, "Mother low": 90}                         # the 9-13 Nov week's high and low
    flat = [bar(6, 100, 101, 99, 100), bar(13, 100, 101, 99, 100.5), bar(20, 100, 101, 99, 100.8)]
    t = ml._tight_setup(row(flat), weekly=True)
    assert {x["label"]: x["price"] for x in t["levels"]} == {"Tight high": 100.8, "Tight low": 100}


def test_chart_lines_are_averages_over_all_the_history_cut_to_the_bars_shown():
    wk = [[i * 7 * 86400, 100 + i, 101 + i, 99 + i, 100 + i, 1000 + i] for i in range(60)]
    shown = wk[-20:]
    lines = ml.chart_lines({"wcandles": wk}, shown, weekly=True)
    assert lines["fast"]["label"] == "10-week" and len(lines["fast"]["pts"]) == 20
    assert lines["slow"]["label"] == "40-week" and len(lines["slow"]["pts"]) == 20          # 40 weeks of history exist before the first shown bar
    assert lines["fast"]["pts"][-1][1] == round(sum(100 + i for i in range(50, 60)) / 10, 2)
    short = ml.chart_lines({"wcandles": wk[:30]}, wk[10:30], weekly=True)
    assert "slow" not in short                                                              # 30 weeks cannot support a 40-week average: left out, not drawn from fewer bars
    daily = ml.chart_lines({"closes": [[i * 86400, 100.0 + i] for i in range(260)]}, [[i * 86400, 1, 1, 1, 1, 10] for i in range(100, 260)], weekly=False)
    assert daily["fast"]["label"] == "50-day" and daily["slow"]["label"] == "200-day" and len(daily["slow"]["pts"]) == 61
