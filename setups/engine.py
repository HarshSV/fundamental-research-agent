"""Setup layer: what is this stock setting up for right now?

Pure functions over candles ({time (unix s), open, high, low, close, volume}, oldest first); no network. A setup that
cannot be judged (too few bars, no volume) says so - it is never reported as "no setup" or as zero.

Setups
  orb         15-minute opening-range breakout (intraday, 5-minute bars)
  oversold    oversold bounce (daily, Wilder RSI-14)
  resistance  horizontal resistance: sitting just under it, or just through it (daily)

States: forming (not decidable yet), waiting (set up, no trigger yet), triggered, failed, no_breakout, inactive."""
from __future__ import annotations

import datetime as _dt
from collections import defaultdict

from patterns.features import resistance

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
OPEN_MIN = 9 * 60 + 15            # 09:15 IST
OR_BARS = 3                       # opening range = first 15 minutes = three 5-minute bars
CLOSE_MIN = 15 * 60 + 30


def _ist(t: int) -> _dt.datetime:
    return _dt.datetime.fromtimestamp(t, IST)


def _mins(t: int) -> int:
    d = _ist(t)
    return d.hour * 60 + d.minute


def session_bars(bars: list[dict], day: str | None = None) -> tuple[str | None, list[dict]]:
    """The regular-session bars of one IST date (default: the newest date present)."""
    by_day: dict[str, list[dict]] = defaultdict(list)
    for b in bars:
        m = _mins(b["time"])
        if OPEN_MIN <= m < CLOSE_MIN:
            by_day[_ist(b["time"]).strftime("%Y-%m-%d")].append(b)
    if not by_day:
        return None, []
    d = day if day in by_day else max(by_day)
    return d, sorted(by_day[d], key=lambda b: b["time"])


def adr_pct(daily: list[dict], n: int = 20) -> float | None:
    """Average daily range in % of low over the last n sessions: the stock's own yardstick for "a big move"."""
    w = [b for b in daily[-n:] if b.get("low") and b["low"] > 0 and b.get("high")]
    return sum((b["high"] / b["low"] - 1.0) * 100.0 for b in w) / len(w) if len(w) >= max(5, n // 2) else None


def _hhmm(t: int) -> str:
    return _ist(t).strftime("%H:%M")


# ---------------------------------------------------------------- opening-range breakout
def orb(intraday: list[dict], daily: list[dict] | None = None, session: str | None = None) -> dict:
    d, bars = session_bars(intraday, session)
    out = {"id": "orb", "label": "Opening-range breakout (15 min)", "timeframe": "5m", "session": d}
    if len(bars) < OR_BARS:
        return {**out, "state": "forming", "direction": None,
                "reason": "The first 15 minutes are not complete yet." if bars else "No intraday bars for this session."}
    rng = bars[:OR_BARS]
    hi, lo = max(b["high"] for b in rng), min(b["low"] for b in rng)
    rng_pct = (hi / lo - 1.0) * 100.0 if lo > 0 else None
    adr = adr_pct(daily or [])
    after = bars[OR_BARS:]
    trig = next((b for b in after if b["close"] > hi or b["close"] < lo), None)
    evidence = {"range_high": round(hi, 2), "range_low": round(lo, 2),
                "range_pct": round(rng_pct, 2) if rng_pct is not None else None,
                "adr20_pct": round(adr, 2) if adr is not None else None,
                "range_vs_adr": round(rng_pct / adr, 2) if (rng_pct is not None and adr) else None}
    if trig is None:
        ended = _mins(bars[-1]["time"]) >= CLOSE_MIN - 5
        return {**out, **evidence, "state": "no_breakout" if ended else "waiting", "direction": None,
                "last_price": round(bars[-1]["close"], 2), "last_time": _hhmm(bars[-1]["time"]),
                "reason": "Price stayed inside the opening range all session." if ended else "Price is still inside the opening range."}
    up = trig["close"] > hi
    level = hi if up else lo
    i = bars.index(trig)
    prior = [b["volume"] for b in bars[:i] if b.get("volume")]
    rvol = trig["volume"] / (sum(prior) / len(prior)) if (prior and trig.get("volume")) else None
    later = bars[i + 1:]
    failed = any((b["close"] < level) if up else (b["close"] > level) for b in later)
    return {**out, **evidence, "state": "failed" if failed else "triggered", "direction": "bullish" if up else "bearish",
            "trigger_price": round(trig["close"], 2), "trigger_time": _hhmm(trig["time"]),
            "level": round(level, 2), "breakout_pct": round(abs(trig["close"] / level - 1.0) * 100.0, 2),
            "trigger_volume_vs_avg": round(rvol, 2) if rvol is not None else None,
            "last_price": round(bars[-1]["close"], 2), "last_time": _hhmm(bars[-1]["time"]),
            "reason": ("Closed back through the range after the breakout." if failed else
                       f"First 5-minute close {'above' if up else 'below'} the opening range at {_hhmm(trig['time'])}.")}


# ---------------------------------------------------------------- oversold bounce
def rsi(closes: list[float], n: int = 14) -> list[float | None]:
    """Wilder RSI; None until n changes exist."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        ch = closes[i] - closes[i - 1]
        gains += max(ch, 0.0)
        losses += max(-ch, 0.0)
    ag, al = gains / n, losses / n
    out[n] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    for i in range(n + 1, len(closes)):
        ch = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(ch, 0.0)) / n
        al = (al * (n - 1) + max(-ch, 0.0)) / n
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def oversold(daily: list[dict]) -> dict:
    out = {"id": "oversold", "label": "Oversold bounce (RSI-14)", "timeframe": "1d"}
    if len(daily) < 30:
        return {**out, "state": "forming", "direction": None, "reason": "Not enough daily history."}
    closes = [b["close"] for b in daily]
    r = rsi(closes)
    now = r[-1]
    recent = [x for x in r[-4:-1] if x is not None]
    was_low = any(x < 30 for x in recent)
    prev_high = daily[-2]["high"]
    ev = {"rsi": round(now, 1) if now is not None else None, "rsi_min_3d": round(min(recent), 1) if recent else None,
          "last_close": round(closes[-1], 2), "prev_day_high": round(prev_high, 2)}
    if now is not None and now < 30:
        return {**out, **ev, "state": "waiting", "direction": "bullish",
                "trigger_price": round(prev_high, 2), "reason": "RSI is below 30; a close above the previous day's high would trigger the bounce."}
    if was_low and closes[-1] > prev_high:
        return {**out, **ev, "state": "triggered", "direction": "bullish", "trigger_price": round(closes[-1], 2),
                "reason": "RSI was below 30 in the last 3 sessions and the latest close is above the previous day's high."}
    return {**out, **ev, "state": "inactive", "direction": None, "reason": "RSI is not oversold."}


# ---------------------------------------------------------------- horizontal resistance
def resistance_setup(daily: list[dict]) -> dict:
    out = {"id": "resistance", "label": "Horizontal resistance", "timeframe": "1d"}
    if len(daily) < 60:
        return {**out, "state": "forming", "direction": None, "reason": "Not enough daily history."}
    r = resistance(daily[-520:])
    if not r:
        return {**out, "state": "inactive", "direction": None, "reason": "No horizontal resistance zone near the price."}
    near = r["state"] == "near"
    return {**out, "state": "waiting" if near else "triggered", "direction": "bullish", "level": round(r["level"], 2),
            "touches": r["touches"], "distance_pct": round(r["dist_pct"], 2), "trigger_price": round(r["level"], 2),
            "reason": (f"Price is {abs(r['dist_pct']):.1f}% under a level touched {r['touches']} times." if near else
                       f"Closed above a level touched {r['touches']} times, within the last 3 sessions.")}


def analyse(symbol: str, intraday: list[dict] | None, daily: list[dict] | None, session: str | None = None) -> dict:
    daily = daily or []
    a = adr_pct(daily)
    d, _ = session_bars(intraday or [], session)
    out = {"symbol": symbol, "price": round(daily[-1]["close"], 2) if daily else None,
           "adr20_pct": round(a, 2) if a is not None else None, "session": d,
           "setups": [orb(intraday or [], daily, session), oversold(daily), resistance_setup(daily)]}
    from setups.plan import plan_for
    for st in out["setups"]:
        st["plans"] = plan_for(st, daily, a)
    active = [s for s in out["setups"] if s["state"] in ("waiting", "triggered")]
    out["summary"] = {"active": len(active), "triggered": sum(1 for s in active if s["state"] == "triggered"),
                      "waiting": sum(1 for s in active if s["state"] == "waiting")}
    return out
