"""Corporate-action adjustment of daily price history (demergers and anything else the provider leaves unadjusted).

The price provider adjusts for splits and bonuses but not always for a demerger: on the ex-date the share simply "drops"
and every earlier price stays at the old level, which inflates 52-week / all-time highs and every return that spans the date.

Rule (the same for every company): Screener.in publishes the company's own corporate-action ADJUSTED price history. Where the
provider's closes sit at a different level from Screener's on the same dates, the earlier part of the history is scaled to
Screener's level. Each segment of constant ratio becomes one factor (median of its samples); a factor within 1.5% of 1 is
noise and ignored; the most recent segment must agree with Screener (else the two sources use different bases and nothing is
changed). A real crash is never adjusted away because Screener's history contains it too."""
from __future__ import annotations

import bisect
import datetime as _dt
import statistics

NOISE = 0.015       # |factor - 1| below this is rounding, not a corporate action
JUMP = 0.03         # a change of the ratio between consecutive samples bigger than this starts a new segment
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))


def _date(t: int) -> str:
    return _dt.datetime.fromtimestamp(t, IST).strftime("%Y-%m-%d")


def adjust_for_demergers(candles: list[dict] | None, symbol: str, name: str | None = None, ref=None) -> list[dict] | None:
    """`ref` is a callable (symbol, name) -> [(date, price)] (default: Screener); injected by tests."""
    if not candles or len(candles) < 30:
        return candles
    try:
        if ref is None:
            from tools.screener_scraper import fetch_screener_price_history as ref
        hist = ref(symbol, name)
    except Exception:
        return candles
    if not hist or len(hist) < 8:
        return candles
    days = [_date(c["time"]) for c in candles]
    # ratio screener / provider on every sample date that is a provider trading day
    samples = []                                       # (candle index, ratio)
    for d, p in hist:
        i = bisect.bisect_right(days, d) - 1
        if i < 0 or days[i] != d or not candles[i]["close"] or p <= 0:
            continue
        samples.append((i, p / candles[i]["close"]))
    if len(samples) < 8:
        return candles
    # segments of (nearly) constant ratio
    segs, cur = [], [samples[0]]
    for prev, nxt in zip(samples, samples[1:]):
        if abs(nxt[1] / prev[1] - 1) > JUMP:
            segs.append(cur)
            cur = []
        cur.append(nxt)
    segs.append(cur)
    # the newest segment must agree with Screener, or the sources are not comparable
    newest = statistics.median(r for _, r in segs[-1])
    if abs(newest - 1) > NOISE or len(segs) == 1 and abs(newest - 1) <= NOISE:
        return candles
    factors = [(statistics.median(r for _, r in s), s) for s in segs]
    if all(abs(f - 1) <= NOISE for f, _ in factors):
        return candles
    # boundary of each segment: the biggest one-day fall between its last sample and the next segment's first sample
    out = [dict(c) for c in candles]
    bounds = []
    for k in range(len(segs) - 1):
        lo, hi = segs[k][-1][0], segs[k + 1][0][0]
        cand = range(lo + 1, hi + 1)
        b = min(cand, key=lambda j: candles[j]["close"] / candles[j - 1]["close"] if candles[j - 1]["close"] else 9)
        bounds.append(b)
    start = 0
    for k, (f, _) in enumerate(factors[:-1]):
        end = bounds[k]
        if abs(f - 1) > NOISE:
            for j in range(start, end):
                for key in ("open", "high", "low", "close"):
                    out[j][key] = candles[j][key] * f
        start = end
    return out
