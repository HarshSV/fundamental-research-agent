"""Glue: completed candles -> replay -> store -> API payload, cached per (symbol, timeframe, last bar)."""
from __future__ import annotations

import datetime as dt
import threading
import time
from collections import Counter
from typing import Callable

from . import store
from .core import DETECTOR_VERSION, Series
from .engine import replay
from .registry import ALL, GROUPS

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# timeframe -> (provider interval, provider period, bar seconds)
TIMEFRAMES = {
    "1d": ("1d", "5y", 86400),
    "1wk": ("1wk", "10y", 7 * 86400),
    # Intraday history is capped to what the patterns need (a few hundred bars of warm-up plus the
    # visible window): replaying the full provider limit takes ~25-30s per timeframe for no gain.
    "60m": ("60m", "6mo", 3600),
    "15m": ("15m", "60d", 900),
    "5m": ("5m", "30d", 300),
}

_locks: dict[tuple, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: tuple) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def drop_incomplete(candles: list[dict], timeframe: str, now: float | None = None) -> list[dict]:
    """Detectors run on COMPLETED bars only. Returns the candles minus a bar that is still forming."""
    if not candles:
        return candles
    now = time.time() if now is None else now
    last = candles[-1]
    secs = TIMEFRAMES[timeframe][2]
    if timeframe == "1d":
        d = dt.datetime.fromtimestamp(last["time"], IST).date()
        n = dt.datetime.fromtimestamp(now, IST)
        closed = n.date() > d or (n.date() == d and (n.hour, n.minute) >= (15, 35))
        return candles if closed else candles[:-1]
    if timeframe == "1wk":
        d = dt.datetime.fromtimestamp(last["time"], IST).date()
        n = dt.datetime.fromtimestamp(now, IST)
        friday = d + dt.timedelta(days=(4 - d.weekday()) % 7)  # that week's Friday
        closed = n.date() > friday or (n.date() == friday and (n.hour, n.minute) >= (15, 35))
        return candles if closed else candles[:-1]
    return candles if last["time"] + secs <= now else candles[:-1]


def build_series(candles: list[dict], timeframe: str, now: float | None = None) -> Series | None:
    cs = drop_incomplete(candles, timeframe, now)
    cs = [x for x in cs if all(x.get(k) is not None for k in ("open", "high", "low", "close"))]
    if len(cs) < 30:
        return None
    vol = [x.get("volume") if x.get("volume") is not None else float("nan") for x in cs]
    first = dt.datetime.fromtimestamp(cs[0]["time"], IST).date()
    years = {"1d": 5, "1wk": 10}.get(timeframe)
    # The listing date is only "known" when the provider's history starts well after the window it was
    # asked for, i.e. the stock listed inside that window. Otherwise we never guess it.
    listing_known = bool(years) and first > (dt.datetime.fromtimestamp(cs[-1]["time"], IST).date()
                                              - dt.timedelta(days=int(365.25 * years) - 45))
    return Series(
        [x["time"] for x in cs], [x["open"] for x in cs], [x["high"] for x in cs], [x["low"] for x in cs],
        [x["close"] for x in cs], vol, timeframe=timeframe, meta={"listing_known": listing_known},
    )


def get_patterns(symbol: str, timeframe: str, fetch: Callable[[str, str, str], list[dict] | None],
                 status: str | None = None, pattern: str | None = None, refresh: bool = False) -> dict:
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"unsupported timeframe {timeframe!r}; use one of {sorted(TIMEFRAMES)}")
    interval, period, _ = TIMEFRAMES[timeframe]
    candles = fetch(symbol, interval, period)
    series = build_series(candles or [], timeframe)
    if series is None:
        return {"symbol": symbol, "timeframe": timeframe, "version": DETECTOR_VERSION, "source": "unavailable",
                "n_bars": 0, "occurrences": [], "counts": {}, "errors": {},
                "note": "Not enough completed candles to run the pattern agent."}
    key = (symbol, timeframe)
    with _lock_for(key):
        run = store.get_run(symbol, timeframe, DETECTOR_VERSION)
        errors: dict = {}
        if refresh or run is None or run["last_bar_ts"] != int(series.t[-1]):
            res = replay(series, ALL, groups=GROUPS)
            store.save(symbol, timeframe, DETECTOR_VERSION, series, res.occurrences, res.errors)
            errors = res.errors
        else:
            import json
            errors = json.loads(run["errors_json"] or "{}")
        everything = store.load(symbol, timeframe, DETECTOR_VERSION, series)
    shown = [o for o in everything
             if (status is None or o["status"] == status) and (pattern is None or o["pattern"] == pattern)]
    return {
        "symbol": symbol, "timeframe": timeframe, "version": DETECTOR_VERSION, "source": "yfinance",
        "n_bars": series.n, "last_bar_ts": int(series.t[-1]),
        "listing_known": bool(series.meta.get("listing_known")),
        "counts": {
            "by_status": dict(Counter(o["status"] for o in everything)),
            "by_pattern": dict(Counter(o["pattern"] for o in everything)),
        },
        "errors": errors,
        "note": "Completed bars only. Status describes pattern FORMATION, not whether a trade will make money; "
                "realised outcomes are measured separately from the confirming bar.",
        "occurrences": shown,
    }
