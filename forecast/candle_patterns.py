"""Deterministic candlestick-pattern definitions (pure python, no symbol-specific logic).

A pattern is a statement about OHLC structure (plus a prior-trend context where the pattern is defined
by one). It is NOT a trading signal. Every threshold lives in DEFAULT_PARAMS. A pattern whose definition
needs a trend context is not reported when there are too few prior bars (insufficient history is never a
detection). Candles are dicts with open/high/low/close; a candle with zero range matches nothing.

`detect_at(candles, i)` only reads candles[0..i], so it is safe to use bar-by-bar without look-ahead.
"""

DEFAULT_PARAMS = {
    "doji_body_frac": 0.10,       # body <= 10% of the candle range
    "long_body_frac": 0.60,       # "long" body >= 60% of range
    "small_body_frac": 0.30,      # star middle candle: body <= 30% of the first candle's body
    "shadow_body_mult": 2.0,      # hammer / star: long shadow >= 2x body
    "small_shadow_frac": 0.15,    # the opposite shadow <= 15% of range
    "trend_lookback": 5,          # bars before the pattern used for the trend context
    "trend_min_move": 0.0,        # |close change| must exceed this fraction to count as a trend
    "soldier_shadow_frac": 0.30,  # three soldiers/crows: closing-side shadow <= 30% of body
}

PATTERNS = {
    "doji": ("neutral", 1), "hammer": ("bullish", 1), "hanging_man": ("bearish", 1),
    "inverted_hammer": ("bullish", 1), "shooting_star": ("bearish", 1),
    "bullish_engulfing": ("bullish", 2), "bearish_engulfing": ("bearish", 2),
    "piercing_pattern": ("bullish", 2), "dark_cloud_cover": ("bearish", 2),
    "morning_star": ("bullish", 3), "evening_star": ("bearish", 3),
    "three_white_soldiers": ("bullish", 3), "three_black_crows": ("bearish", 3),
}

DEFINITIONS = {
    "doji": "Body is at most doji_body_frac of the range.",
    "hammer": "After a downtrend: lower shadow >= 2x body, tiny upper shadow.",
    "hanging_man": "After an uptrend: hammer-shaped candle.",
    "inverted_hammer": "After a downtrend: upper shadow >= 2x body, tiny lower shadow.",
    "shooting_star": "After an uptrend: inverted-hammer-shaped candle.",
    "bullish_engulfing": "After a downtrend: bearish candle followed by a larger bullish body that engulfs its body.",
    "bearish_engulfing": "After an uptrend: bullish candle followed by a larger bearish body that engulfs its body.",
    "piercing_pattern": "After a downtrend: long bearish candle, then a bullish candle opening below its close and closing above its body midpoint but below its open.",
    "dark_cloud_cover": "After an uptrend: long bullish candle, then a bearish candle opening above its close and closing below its body midpoint but above its open.",
    "morning_star": "After a downtrend: long bearish, small body below it, then a bullish close above the first body midpoint.",
    "evening_star": "After an uptrend: long bullish, small body above it, then a bearish close below the first body midpoint.",
    "three_white_soldiers": "Three bullish candles, each opening inside the previous body and closing higher near its high.",
    "three_black_crows": "Three bearish candles, each opening inside the previous body and closing lower near its low.",
}


def _f(c):
    return c["open"], c["high"], c["low"], c["close"]


def _parts(c):
    o, h, l, cl = _f(c)
    rng = h - l
    body = abs(cl - o)
    return rng, body, h - max(o, cl), min(o, cl) - l


def _valid(c):
    try:
        o, h, l, cl = _f(c)
        return all(v is not None and v == v for v in (o, h, l, cl)) and h >= l and h >= max(o, cl) and l <= min(o, cl) and h > l
    except (KeyError, TypeError):
        return False


def _trend(candles, i, p):
    """'down' / 'up' / None from the closes of the p['trend_lookback'] bars BEFORE bar i's pattern start
    is handled by the caller (pass the index of the candle just before the pattern)."""
    k = p["trend_lookback"]
    if i - k < 0:
        return None
    a, b = candles[i - k]["close"], candles[i]["close"]
    if not a:
        return None
    move = (b - a) / a
    if move < -p["trend_min_move"] and b < a:
        return "down"
    if move > p["trend_min_move"] and b > a:
        return "up"
    return None


def detect_at(candles, i, params=None):
    """Patterns whose LAST candle is candles[i]. Reads candles[0..i] only."""
    p = {**DEFAULT_PARAMS, **(params or {})}
    out = []
    if i < 0 or i >= len(candles) or not _valid(candles[i]):
        return out
    c = candles[i]
    rng, body, up, lo = _parts(c)
    o, h, l, cl = _f(c)
    bull, bear = cl > o, cl < o

    def add(name):
        out.append({"pattern": name, "direction": PATTERNS[name][0], "bars": PATTERNS[name][1], "index": i})

    if body <= p["doji_body_frac"] * rng:
        add("doji")
    tr1 = _trend(candles, i - 1, p) if i >= 1 else None
    if body > 0 and tr1:
        hammer_shape = lo >= p["shadow_body_mult"] * body and up <= p["small_shadow_frac"] * rng
        star_shape = up >= p["shadow_body_mult"] * body and lo <= p["small_shadow_frac"] * rng
        if tr1 == "down" and hammer_shape:
            add("hammer")
        if tr1 == "up" and hammer_shape:
            add("hanging_man")
        if tr1 == "down" and star_shape:
            add("inverted_hammer")
        if tr1 == "up" and star_shape:
            add("shooting_star")
    if i >= 1 and _valid(candles[i - 1]):
        pv = candles[i - 1]
        prng, pbody, _, _ = _parts(pv)
        po, _, _, pc = _f(pv)
        tr2 = _trend(candles, i - 2, p) if i >= 2 else None
        if tr2 and body > pbody > 0:
            if tr2 == "down" and pc < po and bull and o <= pc and cl >= po:
                add("bullish_engulfing")
            if tr2 == "up" and pc > po and bear and o >= pc and cl <= po:
                add("bearish_engulfing")
        if tr2 and pbody >= p["long_body_frac"] * prng:
            mid = (po + pc) / 2
            if tr2 == "down" and pc < po and bull and o < pc and mid < cl < po:
                add("piercing_pattern")
            if tr2 == "up" and pc > po and bear and o > pc and po < cl < mid:
                add("dark_cloud_cover")
    if i >= 2 and all(_valid(candles[i - k]) for k in (1, 2)):
        c1, c2 = candles[i - 2], candles[i - 1]
        r1, b1, _, _ = _parts(c1)
        r2, b2, _, _ = _parts(c2)
        o1, _, _, k1 = _f(c1)
        o2, _, _, k2 = _f(c2)
        tr3 = _trend(candles, i - 3, p) if i >= 3 else None
        mid1 = (o1 + k1) / 2
        if tr3 and b1 >= p["long_body_frac"] * r1 and b2 <= p["small_body_frac"] * b1:
            if tr3 == "down" and k1 < o1 and max(o2, k2) <= k1 and bull and cl > mid1:
                add("morning_star")
            if tr3 == "up" and k1 > o1 and min(o2, k2) >= k1 and bear and cl < mid1:
                add("evening_star")

        def soldiers(sign):
            seq = (c1, c2, c)
            for a, b_ in zip(seq, seq[1:]):
                if sign * (b_["close"] - b_["open"]) <= 0 or sign * (a["close"] - a["open"]) <= 0:
                    return False
                if not (min(a["open"], a["close"]) <= b_["open"] <= max(a["open"], a["close"])):
                    return False
                if sign * (b_["close"] - a["close"]) <= 0:
                    return False
            for k_ in seq:
                _, bd, upp, lw = _parts(k_)
                if bd == 0 or (upp if sign > 0 else lw) > p["soldier_shadow_frac"] * bd:
                    return False
            return True

        if soldiers(1):
            add("three_white_soldiers")
        if soldiers(-1):
            add("three_black_crows")
    return out


def detect_all(candles, params=None, start=0):
    res = []
    for i in range(max(start, 0), len(candles)):
        res.extend(detect_at(candles, i, params))
    return res
