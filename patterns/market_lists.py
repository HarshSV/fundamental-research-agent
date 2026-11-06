"""Market-wide list scanners (top gainers, volume, gaps, inside bars, tight setups, momentum, RS high before price high ...).

Each scanner reads only what the market scan already stores per stock (patterns/scan.py: the last ~160 daily candles
[time, open, high, low, close, volume], ~520 closes, moving averages, RS rating, distance from highs), so a search is instant and
needs no new data. `evaluate(kind, row)` returns {"value": number, "text": str, "note": str} for a stock that matches, or None.

Nothing is guessed: a measure that cannot be computed (too few bars, no volume, no benchmark) gives None and the stock simply
does not match; it is never treated as zero. These are open, documented definitions (shown in the app), not any vendor's formula."""
from __future__ import annotations

IST = 19800
DAY = 86400

GAP_MIN = 0.02            # a gap is an open at least 2% away from the previous close
GAP_LOOKBACK = 15         # gap-filling looks for a gap in the last 15 sessions
VOLUME_SURGE = 2.0        # volume gainers: latest volume at least 2x the average of the 20 sessions before it
TIGHT_DAYS, TIGHT_RANGE = 5, 0.025          # tight setup (daily): last 5 closes within 2.5% of each other
TIGHT_WEEKS, TIGHT_WEEK_RANGE = 3, 0.04     # tight setup (weekly): last 3 weekly closes within 4%
RS_LINE_BARS = 252        # RS line at a 52-week high


def _num(v) -> bool:
    return isinstance(v, (int, float)) and v == v


def _bars(r: dict) -> list:
    return [c for c in (r.get("candles") or []) if len(c) >= 6 and all(_num(x) for x in c[:6])]


def _pct(a: float, b: float):
    return (a / b - 1.0) * 100.0 if b else None


def _weeks(bars: list) -> list:
    """Daily bars folded into IST weeks: [open, high, low, close] per week, oldest first (the last week may be incomplete)."""
    out, key = [], None
    for t, o, h, l, c, _v in (b[:6] for b in bars):
        k = ((t + IST) // DAY + 3) // 7
        if k != key:
            out.append([o, h, l, c])
            key = k
        else:
            w = out[-1]
            w[1], w[2], w[3] = max(w[1], h), min(w[2], l), c
    return out


def _change_1d(r):
    b = _bars(r)
    return _pct(b[-1][4], b[-2][4]) if len(b) >= 2 else None


def _gainers(r, sign):
    ch = _change_1d(r)
    if ch is None or ch * sign <= 0:
        return None
    return {"value": ch, "text": f"{ch:+.2f}%", "note": "change in the latest session"}


def _volume_ratio(r):
    b = _bars(r)
    if len(b) < 22:
        return None
    base = [x[5] for x in b[-21:-1]]
    avg = sum(base) / len(base)
    return (b[-1][5] / avg, avg) if avg > 0 and b[-1][5] >= 0 else None


def _volume_gainers(r):
    vr = _volume_ratio(r)
    if not vr or vr[0] < VOLUME_SURGE:
        return None
    ch = _change_1d(r)
    return {"value": vr[0], "text": f"{vr[0]:.1f}x volume", "note": f"latest volume vs the average of the 20 sessions before"
            + (f"; price {ch:+.2f}%" if ch is not None else "")}


def _high_volume(r):
    b = _bars(r)
    if not b or b[-1][5] <= 0:
        return None
    val = b[-1][4] * b[-1][5] / 1e7
    return {"value": val, "text": f"₹{val:,.1f} Cr traded", "note": "latest session's traded value (price x volume)"}


def _gap_up(r):
    b = _bars(r)
    if len(b) < 2:
        return None
    g = _pct(b[-1][1], b[-2][4])
    if g is None or g < GAP_MIN * 100:
        return None
    filled = b[-1][3] <= b[-2][4]
    return {"value": g, "text": f"Gap {g:+.2f}%", "note": "opened above the previous close" + ("; gap already filled in the session" if filled else "")}


def _gap_filling(r):
    """A gap up of at least 2% in the last 15 sessions (not today) that price has since come back into, without closing it completely."""
    b = _bars(r)
    n = len(b)
    if n < GAP_LOOKBACK + 2:
        return None
    last = b[-1]
    for i in range(n - 2, n - 1 - GAP_LOOKBACK, -1):
        g = _pct(b[i][1], b[i - 1][4])
        if g is None or g < GAP_MIN * 100:
            continue
        floor, top = b[i - 1][4], b[i][1]            # the gap zone: previous close .. gap-day open
        low_since = min(x[3] for x in b[i + 1:])
        if low_since <= floor:
            return None                              # fully closed: not "filling" any more
        if low_since < top and last[4] > floor:
            filled = (top - max(low_since, floor)) / (top - floor) * 100.0
            return {"value": filled, "text": f"{filled:.0f}% of gap filled", "note": f"gap of {g:+.1f}% on session {n - i} sessions ago"}
        return None
    return None


def _inside_bar(r, weekly=False, filtered=False):
    if weekly:
        w = _weeks(_bars(r))
        if len(w) < 2:
            return None
        (_, ph, pl, _), (_, h, l, _) = w[-2], w[-1]
    else:
        b = _bars(r)
        if len(b) < 2:
            return None
        ph, pl, h, l = b[-2][2], b[-2][3], b[-1][2], b[-1][3]
    if not (h <= ph and l >= pl) or ph <= pl:
        return None
    ratio = (h - l) / (ph - pl) * 100.0
    if filtered:                     # the "filtered" variant: only a clearly narrower bar, in an uptrend
        sma50, price = (r.get("sma") or {}).get("50"), r.get("price")
        if ratio > 60 or not _num(sma50) or not _num(price) or price <= sma50:
            return None
    return {"value": ratio, "text": f"Range {ratio:.0f}% of prior", "note": ("this week" if weekly else "latest session") + " traded inside the prior " + ("week" if weekly else "session") + "'s high and low"}


def _tight_setup(r, weekly=False):
    sma50 = (r.get("sma") or {}).get("50")
    price = r.get("price")
    if not _num(sma50) or not _num(price) or price <= sma50:
        return None                                   # only consolidations above the 50-day average
    if weekly:
        w = _weeks(_bars(r))
        closes = [x[3] for x in w[-TIGHT_WEEKS:]]
        limit, label = TIGHT_WEEK_RANGE, f"last {TIGHT_WEEKS} weekly closes"
        if len(w) < TIGHT_WEEKS:
            return None
    else:
        closes = [x[4] for x in _bars(r)[-TIGHT_DAYS:]]
        limit, label = TIGHT_RANGE, f"last {TIGHT_DAYS} closes"
        if len(closes) < TIGHT_DAYS:
            return None
    rng = (max(closes) - min(closes)) / (sum(closes) / len(closes))
    if rng > limit:
        return None
    return {"value": rng * 100.0, "text": f"{rng * 100:.1f}% range", "note": f"{label} within {limit * 100:.1f}%, price above the 50-day average"}


def _momentum(r):
    sma, rs = r.get("sma") or {}, r.get("rs")
    price, r3, off = r.get("price"), r.get("ret_3m"), r.get("pct_from_52w_high")
    if not all(_num(x) for x in (sma.get("50"), sma.get("200"), rs, price, r3, off)):
        return None
    if not (price > sma["50"] > sma["200"] and rs >= 80 and off <= 15 and r3 >= 20):
        return None
    return {"value": rs, "text": f"RS {rs}", "note": f"above 50 and 200-day averages, within {off:.0f}% of the 52-week high, 3-month return {r3:+.0f}%"}


def _shorting(r):
    sma, rs = r.get("sma") or {}, r.get("rs")
    price, low = r.get("price"), r.get("pct_from_52w_low")
    if not all(_num(x) for x in (sma.get("50"), sma.get("200"), rs, price, low)):
        return None
    if not (price < sma["50"] < sma["200"] and rs <= 30 and low <= 15):
        return None
    return {"value": rs, "text": f"RS {rs}", "note": f"below 50 and 200-day averages, only {low:.0f}% above the 52-week low"}


_bench_days: dict = {}


def _benchmark_by_day(bench):
    key = (len(bench), bench[-1][0]) if bench else None
    if key not in _bench_days:
        _bench_days.clear()
        _bench_days[key] = {(t + IST) // DAY: c for t, c in bench}
    return _bench_days[key]


def rs_high_before_price_high(r, bench):
    """The stock's relative-strength line (close / Nifty 500) is at a 52-week high while the price is still short of its own."""
    cl = r.get("closes") or []
    if not bench or len(cl) < RS_LINE_BARS + 5:
        return None
    bd = _benchmark_by_day(bench)
    line = [c / bd[(t + IST) // DAY] for t, c in cl if c and bd.get((t + IST) // DAY)]
    if len(line) < RS_LINE_BARS:
        return None
    window = line[-RS_LINE_BARS:]
    off = r.get("pct_from_52w_high")
    if not _num(off) or off < 2 or line[-1] < max(window) * 0.999:
        return None
    return {"value": off, "text": f"{off:.1f}% below high", "note": "relative strength line at a 52-week high while the price is below its 52-week high"}


# ------------------------------------------------------------------ derived per-stock measures used as screener filters
RANGE_DAYS = 20


def _sma_series(closes: list, n: int):
    """Simple moving average of `closes` ending at every index >= n-1 (list aligned to the END of closes)."""
    if len(closes) < n:
        return []
    out, run = [], sum(closes[:n])
    out.append(run / n)
    for i in range(n, len(closes)):
        run += closes[i] - closes[i - n]
        out.append(run / n)
    return out


def ma200_turnaround(r: dict):
    """True when the 200-day average was falling over the 60 sessions before last week and has been rising since, with the price above it.
    None when there are too few closes to say (never False for 'unknown')."""
    cl = [c for _, c in (r.get("closes") or []) if _num(c)]
    if len(cl) < 200 + 70:
        return None
    s = _sma_series(cl, 200)
    if len(s) < 66:
        return None
    return bool(s[-1] > s[-6] and s[-6] < s[-66] and cl[-1] > s[-1])


def annotate(rows: dict) -> None:
    """Adds the measures the screener's extra filters read to every stock row (idempotent, cheap): rvol (latest volume over the
    average of the 20 sessions before it), gap_pct (open vs previous close), range_20d (high-low range of the last 20 sessions,
    % of the low), vs_ema10 (% the price is above its 10-day EMA), rs_1m / rs_3m (1-99 percentile of the 1 / 3-month return among
    the scanned stocks) and ma200_turn. A measure that cannot be computed is None and never matches a filter."""
    import bisect
    for key, src in (("rs_1m", "ret_1m"), ("rs_3m", "ret_3m")):
        vals = sorted(r[src] for r in rows.values() if _num(r.get(src)))
        n = len(vals)
        for r in rows.values():
            v = r.get(src)
            r[key] = None if not _num(v) or n < 2 else int(round(1 + 98 * bisect.bisect_left(vals, v) / (n - 1)))
    for r in rows.values():
        b = _bars(r)
        vr = _volume_ratio(r)
        r["rvol"] = round(vr[0], 2) if vr else None
        r["gap_pct"] = _pct(b[-1][1], b[-2][4]) if len(b) >= 2 else None
        w = b[-RANGE_DAYS:]
        low = min((x[3] for x in w), default=None)
        r["range_20d"] = ((max(x[2] for x in w) / low - 1.0) * 100.0 if len(w) >= RANGE_DAYS and low else None)
        e10 = (r.get("ema") or {}).get("10")
        r["vs_ema10"] = _pct(r["price"], e10) if _num(r.get("price")) and _num(e10) else None
        r["ma200_turn"] = ma200_turnaround(r)


# id -> (name, group, definition, sort direction: -1 largest first, 1 smallest first)
SCANNERS = {
    "top-gainers": ("Top Gainers", "Market lists", "Stocks that rose in the latest session, biggest gain first.", -1),
    "top-losers": ("Top Losers", "Market lists", "Stocks that fell in the latest session, biggest fall first.", 1),
    "volume-gainers": ("Volume Gainers", "Volume", "Latest session's volume at least 2x the average of the 20 sessions before it.", -1),
    "high-volume": ("High Volume Stocks", "Volume", "Stocks ranked by the value traded in the latest session (price x volume).", -1),
    "gap-up": ("Gap Up", "Gaps", "Opened at least 2% above the previous close in the latest session.", -1),
    "gap-filling": ("Gap Filling", "Gaps", "Gapped up at least 2% in the last 15 sessions and has since come back into the gap without closing it completely.", -1),
    "inside-bar": ("Inside Bar (daily)", "Setups", "The latest session traded inside the previous session's high and low.", 1),
    "inside-bar-weekly": ("Inside Bar (weekly)", "Setups", "This week has traded inside last week's high and low.", 1),
    "inside-bar-filtered": ("Filtered Inside Bar (daily)", "Setups", "An inside bar whose range is at most 60% of the previous session's, with the price above its 50-day average.", 1),
    "inside-bar-weekly-filtered": ("Filtered Inside Bar (weekly)", "Setups", "A weekly inside bar at most 60% of last week's range, with the price above its 50-day average.", 1),
    "tight-setup": ("Tight Setup (daily)", "Setups", "The last 5 closes are within 2.5% of each other and the price is above its 50-day average.", 1),
    "tight-setup-weekly": ("Tight Setup (weekly)", "Setups", "The last 3 weekly closes are within 4% of each other and the price is above its 50-day average.", 1),
    "momentum": ("Momentum", "Strength", "Above the 50 and 200-day averages (50 over 200), RS rating 80+, within 15% of the 52-week high and up 20%+ in 3 months.", -1),
    "rs-high-before-price-high": ("RS High Before Price High", "Strength", "The relative-strength line (against the Nifty 500) is at a 52-week high while the price is still at least 2% under its own 52-week high.", -1),
    "shorting": ("Shorting Scanner", "Weakness", "Below the 50 and 200-day averages (50 under 200), RS rating 30 or less and within 15% of the 52-week low.", 1),
}

_EVAL = {
    "top-gainers": lambda r, b: _gainers(r, 1),
    "top-losers": lambda r, b: _gainers(r, -1),
    "volume-gainers": lambda r, b: _volume_gainers(r),
    "high-volume": lambda r, b: _high_volume(r),
    "gap-up": lambda r, b: _gap_up(r),
    "gap-filling": lambda r, b: _gap_filling(r),
    "inside-bar": lambda r, b: _inside_bar(r),
    "inside-bar-weekly": lambda r, b: _inside_bar(r, True),
    "inside-bar-filtered": lambda r, b: _inside_bar(r, False, True),
    "inside-bar-weekly-filtered": lambda r, b: _inside_bar(r, True, True),
    "tight-setup": lambda r, b: _tight_setup(r),
    "tight-setup-weekly": lambda r, b: _tight_setup(r, True),
    "momentum": lambda r, b: _momentum(r),
    "rs-high-before-price-high": lambda r, b: rs_high_before_price_high(r, b),
    "shorting": lambda r, b: _shorting(r),
}


def evaluate(kind: str, r: dict, bench=None):
    """The scanner's reading for this stock, or None when it does not match or cannot be computed."""
    fn = _EVAL.get(kind)
    if fn is None:
        return None
    try:
        return fn(r, bench)
    except (TypeError, ValueError, ZeroDivisionError, KeyError, IndexError):
        return None


def catalogue() -> list:
    return [{"id": k, "name": v[0], "group": v[1], "definition": v[2]} for k, v in SCANNERS.items()]
