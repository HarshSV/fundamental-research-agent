"""Pattern agent tests. Synthetic data only - never a real company."""
import os
import sys
import tempfile

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from patterns import service, store  # noqa: E402
from patterns.core import ACTIVE, Series  # noqa: E402
from patterns.engine import outcomes, replay  # noqa: E402
from patterns.registry import ALL, BY_NAME, GROUPS  # noqa: E402
from patterns_synth import DAY, T0, path, series_from_closes, timeline  # noqa: E402


def _statuses(res, pattern):
    return [s for _, s, *_ in timeline(res, pattern)]


def _run(closes, names, **kw):
    s = series_from_closes(closes, **kw)
    return s, replay(s, [BY_NAME[n] for n in names], groups=GROUPS)


# -- registry ------------------------------------------------------------------------------------
def test_registry_has_32_unique_patterns():
    assert len(ALL) == 32 and len(BY_NAME) == 32
    assert all(d.definition for d in ALL), "every pattern needs a written definition"


# -- lifecycle ------------------------------------------------------------------------------------
DB_PTS = [(0, 120), (40, 100), (55, 112), (70, 100.5), (80, 111), (88, 114), (100, 120)]


def test_double_bottom_goes_forming_awaiting_confirmed_in_order():
    s, res = _run(path(DB_PTS), ["double-bottom"])
    tl = timeline(res, "double-bottom")
    assert [x[1] for x in tl] == ["forming", "awaiting_breakout", "confirmed"]
    bars = [x[0] for x in tl]
    assert bars == sorted(bars) and bars[0] < bars[1] < bars[2]
    assert all(b != 41 for b in bars[:0])  # anchor is the first low
    assert {x[2] for x in tl} == {41}
    # confirmation is a COMPLETED bar closing above the neckline
    occ = res.occurrences[0]
    assert s.c[occ.confirmed_idx] > occ.breakout_level


def test_double_top_is_the_bearish_mirror():
    pts = [(i, 240 - p) for i, p in DB_PTS]  # invert the double bottom
    _, res = _run(path(pts), ["double-top"])
    occ = res.occurrences[0]
    assert occ.direction == "bearish"
    assert _statuses(res, "double-top") == ["forming", "awaiting_breakout", "confirmed"]
    # levels are converted back to real prices: the peaks sit ABOVE the neckline (support) that must break
    assert occ.pivots[0][1] > occ.breakout_level
    assert occ.invalidation_level > occ.pivots[0][1]


def test_double_bottom_invalidated_when_support_breaks():
    pts = [(0, 120), (40, 100), (55, 112), (70, 100.5), (78, 105), (90, 92), (110, 90)]
    _, res = _run(path(pts), ["double-bottom"])
    sts = _statuses(res, "double-bottom")
    assert sts[-1] == "invalidated" and "confirmed" not in sts


def test_double_bottom_is_not_declared_before_a_second_low_exists():
    s, res = _run(path([(0, 120), (40, 100), (55, 112), (60, 108)]), ["double-bottom"])
    assert res.occurrences == []


# -- exclusivity ------------------------------------------------------------------------------------
def _base(depth_pct: float):
    adv = np.linspace(80, 120, 61)
    x = np.linspace(0, 1, 121)[1:]
    base = 120 * (1 - depth_pct) + 120 * depth_pct * (2 * x - 1) ** 2
    return np.concatenate([adv, base, np.linspace(120, 130, 15)[1:]])


def test_deep_curved_base_is_a_cup_base_and_counted_once():
    _, res = _run(_base(0.167), ["cup-base", "saucer-base", "rounding-bottom", "cup-and-handle"])
    live = {o.pattern for o in res.occurrences if o.status != "invalidated"}
    assert live == {"cup-base"}
    assert _statuses(res, "cup-base") == ["forming", "awaiting_breakout", "confirmed"]


def test_shallow_broad_curved_base_is_a_saucer_not_a_cup():
    _, res = _run(_base(0.10), ["cup-base", "saucer-base", "rounding-bottom", "cup-and-handle"])
    live = {o.pattern for o in res.occurrences if o.status != "invalidated"}
    assert "saucer-base" in live and "cup-base" not in live and "cup-and-handle" not in live


# -- no look-ahead ----------------------------------------------------------------------------------
def _random_walk(n=520, seed=11):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.014, n)))
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.01, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.01, n))
    v = rng.uniform(5e5, 2e6, n)
    return Series(T0 + np.arange(n) * DAY, o, h, l, c, v, timeframe="1d")


def _history(res, upto):
    out = {}
    for o in res.occurrences:
        h = [(x["idx"], x["status"]) for x in o.history if x["idx"] <= upto]
        if h:
            out[(o.pattern, o.direction, o.anchor)] = h
    return out


def test_replay_over_a_prefix_equals_the_same_bars_of_the_full_replay():
    """The agent's knowledge at bar t must not depend on bars after t (swing-point confirmation lag,
    breakout checks, etc.). Compare statuses over the shared prefix."""
    full = _random_walk()
    cut = 380
    pre = Series(full.t[:cut], full.o[:cut], full.h[:cut], full.l[:cut], full.c[:cut], full.v[:cut], timeframe="1d")
    a = _history(replay(pre, ALL, groups=GROUPS), cut - 1)
    b = _history(replay(full, ALL, groups=GROUPS), cut - 1)
    assert a == b


# -- engine behaviour --------------------------------------------------------------------------------
def test_unknown_volume_never_counts_as_a_volume_signal():
    n = 120
    c = np.linspace(100, 130, n)
    s = series_from_closes(c)
    s.v[:] = np.nan
    res = replay(s, [BY_NAME["pocket-pivot"], BY_NAME["shakeout"]], groups=GROUPS)
    assert res.occurrences == []


def test_outcomes_pending_until_future_bars_exist_and_never_zero_filled():
    s, res = _run(path(DB_PTS), ["double-bottom"])
    occ = res.occurrences[0]
    o = outcomes(s, occ)
    assert set(o) == {"5", "15", "30"}
    assert o["30"]["state"] in {"pending", "positive", "negative", "flat", "not_evaluable"}
    if o["30"]["state"] == "pending":
        assert o["30"]["ret"] is None


def test_every_occurrence_records_its_status_transitions():
    _, res = _run(path(DB_PTS), ["double-bottom"])
    occ = res.occurrences[0]
    assert [h["status"] for h in occ.history] == ["forming", "awaiting_breakout", "confirmed"]
    assert all(h["price"] is not None for h in occ.history)


# -- storage ------------------------------------------------------------------------------------------
def test_store_roundtrip_and_history_is_append_only(monkeypatch):
    d = tempfile.mkdtemp()
    monkeypatch.setattr(store, "DATA_DIR", d)
    monkeypatch.setattr(store, "DB_PATH", os.path.join(d, "p.db"))
    s, res = _run(path(DB_PTS), ["double-bottom"])
    store.save("SYNTH", "1d", "t1", s, res.occurrences, {})
    store.save("SYNTH", "1d", "t1", s, res.occurrences, {})  # idempotent
    rows = store.load("SYNTH", "1d", "t1", s)
    assert len(rows) == 1 and [h["status"] for h in rows[0]["history"]] == ["forming", "awaiting_breakout", "confirmed"]
    store.save("SYNTH", "1d", "t2", s, res.occurrences, {})  # a new detector version adds rows, keeps old ones
    assert len(store.load("SYNTH", "1d", "t1", s)) == 1 and len(store.load("SYNTH", "1d", "t2", s)) == 1


# -- service ------------------------------------------------------------------------------------------
def test_incomplete_bar_is_dropped_so_detectors_only_see_completed_candles():
    import datetime as dt
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    day = dt.datetime(2026, 10, 21, 0, 0, tzinfo=ist)
    cs = [{"time": int((day - dt.timedelta(days=1)).timestamp()), "open": 1, "high": 1, "low": 1, "close": 1},
          {"time": int(day.timestamp()), "open": 1, "high": 1, "low": 1, "close": 1}]
    mid_session = dt.datetime(2026, 10, 21, 11, 0, tzinfo=ist).timestamp()
    after_close = dt.datetime(2026, 10, 21, 16, 0, tzinfo=ist).timestamp()
    assert len(service.drop_incomplete(cs, "1d", now=mid_session)) == 1
    assert len(service.drop_incomplete(cs, "1d", now=after_close)) == 2


def test_listing_is_only_known_when_history_starts_inside_the_requested_window():
    c = [{"time": T0 + i * DAY, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100} for i in range(300)]
    s = service.build_series(c, "1d", now=T0 + 400 * DAY)
    assert s is not None and s.meta["listing_known"] is True  # 300 bars << 5 years requested
    assert BY_NAME["ipo-base"].detect.__self__ is BY_NAME["ipo-base"]


def test_ipo_base_never_guesses_a_listing_date():
    s = series_from_closes(path([(0, 50), (60, 80), (80, 75), (100, 78)]))
    s.meta["listing_known"] = False
    assert replay(s, [BY_NAME["ipo-base"]]).occurrences == []
