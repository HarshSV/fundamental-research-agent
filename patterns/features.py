"""Per-stock features for the scanner: technical measures, horizontal resistance and historical pattern trades.

Pure functions over a list of daily candles ({time, open, high, low, close, volume}, oldest first). Every measure that
cannot be computed (too little history, no volume) is None - never 0 - so a filter on it simply does not match."""
from __future__ import annotations

import bisect

DAY = 86400
MA_PERIODS = (10, 20, 50, 100, 200)
HORIZONS = (5, 10, 20, 40, 60)       # bars after a confirmation at which a pattern trade is measured
UPTREND_PERIODS = (20, 50, 100, 200)
ADR_DAYS = (5, 10, 20, 30)
RES_TOL = 0.020                     # highs within 2% of each other belong to one resistance zone
RES_MIN_TOUCHES = 3
RES_PIVOT_SIDE = 3                  # a pivot high is the highest high of 3 bars either side
RES_NEAR = 0.05                     # "near": close is up to 5% under the level
RES_BREAKOUT = 0.03                 # "breakout": close is up to 3% above the level, breakout made in the last 3 bars


def _sma(vals, n):
    return sum(vals[-n:]) / n if len(vals) >= n else None


def _ema(vals, n):
    if len(vals) < n:
        return None
    k = 2.0 / (n + 1)
    e = sum(vals[:n]) / n
    for v in vals[n:]:
        e = v * k + e * (1 - k)
    return e


def _rising_days(closes, n):
    """How many most-recent sessions in a row the n-day simple average has risen."""
    if len(closes) < n + 1:
        return None
    cum = [0.0]
    for c in closes:
        cum.append(cum[-1] + c)
    sma = lambda i: (cum[i + 1] - cum[i + 1 - n]) / n          # average ending at bar i (i >= n-1)
    days, i = 0, len(closes) - 1
    while i - 1 >= n - 1 and sma(i) > sma(i - 1):
        days += 1
        i -= 1
    return days


def _ret(closes, bars):
    return (closes[-1] / closes[-1 - bars] - 1.0) * 100.0 if len(closes) > bars and closes[-1 - bars] else None


def metrics(candles: list[dict]) -> dict:
    """Technical measures of one stock from its full daily history."""
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    n = len(candles)
    last = candles[-1]
    price = last["close"]
    year_ago = last["time"] - 365 * DAY
    has_year = candles[0]["time"] <= year_ago + 7 * DAY
    win = [c for c in candles if c["time"] >= year_ago]
    hi52 = max(c["high"] for c in win) if win and has_year else None
    lo52 = min(c["low"] for c in win) if win and has_year else None
    ath = max(highs)

    new_high_days = None            # sessions since the latest new 52-week high (0 = today)
    if n >= 253:
        for i in range(n - 1, n - 1 - 253, -1):
            if i >= 252 and highs[i] >= max(highs[i - 252:i]):
                new_high_days = n - 1 - i
                break

    def adr(days):
        w = candles[-days:]
        return sum((c["high"] / c["low"] - 1.0) * 100.0 for c in w if c["low"]) / len(w) if len(w) == days else None

    vol30 = [c.get("volume") or 0 for c in candles[-30:]]
    turnover = ([c["close"] * (c.get("volume") or 0) for c in candles[-30:]] if len(candles) >= 30 else None)

    rs_raw = None                   # O'Neil-style relative strength: 40% 3m, 20% each 6m / 9m / 12m performance
    if n >= 253:
        p = lambda k: closes[-1] / closes[-1 - k] - 1.0
        rs_raw = 0.4 * p(63) + 0.2 * p(126) + 0.2 * p(189) + 0.2 * p(252)

    def ret_cal(days):
        target = last["time"] - days * DAY
        if candles[0]["time"] > target + 5 * DAY:
            return None
        base = next((c for c in reversed(candles) if c["time"] <= target), None)
        return (price / base["close"] - 1.0) * 100.0 if base and base["close"] else None

    return {
        "price": price,
        "ema": {str(p): _ema(closes, p) for p in MA_PERIODS},
        "sma": {str(p): _sma(closes, p) for p in MA_PERIODS},
        "ma_up_days": {str(p): _rising_days(closes, p) for p in UPTREND_PERIODS},
        "pct_from_52w_high": ((hi52 - price) / hi52 * 100.0) if hi52 else None,
        "pct_from_52w_low": ((price - lo52) / lo52 * 100.0) if lo52 else None,
        "pct_from_ath": (ath - price) / ath * 100.0 if ath else None,
        "new_high_days": new_high_days,
        "adr": {str(d): adr(d) for d in ADR_DAYS},
        "turnover_30d_cr": (sum(turnover) / len(turnover) / 1e7) if turnover and all(v > 0 for v in vol30) else None,
        "avg_volume_30d": (sum(vol30) / len(vol30)) if len(candles) >= 30 and all(v > 0 for v in vol30) else None,
        "rs_raw": rs_raw,
        "ret_1m": ret_cal(30), "ret_3m": ret_cal(91), "ret_6m": ret_cal(182), "ret_1y": ret_cal(365),
        "ret_3y": ret_cal(1096), "ret_5y": ret_cal(1826),
    }


def resistance(candles: list[dict], lookback: int = 260, fresh_only: bool = False) -> dict | None:
    """The strongest horizontal resistance the stock is at right now, or None.

    Resistance = a price zone that at least three separate pivot highs (each the highest high of 3 bars either side)
    touched within 2% of each other, with the first and last touch at least 15 bars apart. Its level is the top of the
    zone (the highest of those touches), and no close may have cleared it since the first touch (a wick above is fine).
    The stock is then
      near      - its close is up to 5% under the level, or
      breakout  - it closed up to 3% above the level and the first close above came in the last 3 bars."""
    bars = candles[-lookback:]
    n = len(bars)
    if n < 40:
        return None
    side = RES_PIVOT_SIDE
    highs = [b["high"] for b in bars]
    closes = [b["close"] for b in bars]
    piv = [i for i in range(side, n - side) if highs[i] == max(highs[i - side:i + side + 1])]
    best = None
    for seed in piv:
        h0 = highs[seed]
        idx = [i for i in piv if abs(highs[i] - h0) / h0 <= RES_TOL]
        if len(idx) < RES_MIN_TOUCHES or idx[-1] - idx[0] < 15:
            continue
        level = max(highs[i] for i in idx)
        after = closes[idx[0]:]
        first_above = next((k for k, c in enumerate(after) if c > level), None)
        price = closes[-1]
        dist = (price - level) / level
        if first_above is None:
            state = "near" if -RES_NEAR <= dist < 0 else None
        else:
            age = len(after) - 1 - first_above              # bars since the first close above the level
            state = "breakout" if (age <= (0 if fresh_only else 2) and 0 <= dist <= RES_BREAKOUT) else None
        if state is None:
            continue
        cand = {"level": level, "touches": len(idx), "state": state, "dist_pct": dist * 100.0,
                "first_ts": bars[idx[0]]["time"], "last_touch_ts": bars[idx[-1]]["time"],
                "touch_ts": [bars[i]["time"] for i in idx]}
        if best is None or (cand["touches"], cand["last_touch_ts"]) > (best["touches"], best["last_touch_ts"]):
            best = cand
    return best


def resistance_trades(candles: list[dict], years: float = 5.0, min_gap: int = 20) -> list[list]:
    """Every past breakout through a horizontal resistance as a long trade: entered at the close of the first bar that
    closed above the zone, measured HORIZONS bars later. Same row layout as `trades`."""
    if len(candles) < 80:
        return []
    closes = [c["close"] for c in candles]
    start = max(60, bisect.bisect_left([c["time"] for c in candles], candles[-1]["time"] - int(years * 365.25 * 86400)))
    out, last_i = [], -10**9
    for i in range(start, len(candles)):
        if i - last_i < min_gap:
            continue
        r = resistance(candles[: i + 1], fresh_only=True)
        if not r or r["state"] != "breakout" or not closes[i]:
            continue
        last_i = i
        rets = [round((closes[i + h] / closes[i] - 1.0) * 100.0, 2) if i + h < len(closes) else None for h in HORIZONS]
        out.append(["horizontal-resistance", "bullish", candles[i]["time"], round(closes[i], 2), *rets])
    return out


def trades(occurrences: list[dict], candles: list[dict]) -> list[list]:
    """Every confirmed pattern in the stock's history as a trade: entered at the close of the confirming bar, in the
    pattern's direction (a bearish pattern is a short), measured HORIZONS bars later. A horizon the history does not yet
    reach is None. Row: [pattern, direction, confirmed_ts, entry, ret@5, @10, @20, @40, @60] (returns in %)."""
    times = [c["time"] for c in candles]
    closes = [c["close"] for c in candles]
    out = []
    for o in occurrences:
        if o.get("status") != "confirmed" or not o.get("confirmed_ts") or o.get("direction") not in ("bullish", "bearish"):
            continue
        i = bisect.bisect_left(times, o["confirmed_ts"])
        if i >= len(times) or times[i] != o["confirmed_ts"] or not closes[i]:
            continue
        sign = 1.0 if o["direction"] == "bullish" else -1.0
        rets = [round(sign * (closes[i + h] / closes[i] - 1.0) * 100.0, 2) if i + h < len(closes) else None for h in HORIZONS]
        out.append([o["pattern"], o["direction"], o["confirmed_ts"], round(closes[i], 2), *rets])
    return out
