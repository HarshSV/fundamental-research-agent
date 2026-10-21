"""Consolidation / base patterns (bullish): VCP, Flat Base, Ascending Base, IPO Base,
High Tight Flag, Three Weeks Tight.

Common rules
- Breakout = a COMPLETED bar closes above the base's highest prior high (never the current bar's own high).
- Invalidation = a close decisively below the base's defining support, or the structure going stale.
- Volume rules only apply when volume is known; unknown volume never counts as "dry" or "heavy".
"""
from __future__ import annotations

import datetime as _dt

import numpy as np

from ..core import (
    AWAITING, BULLISH, CONFIRMED, FORMING, INVALIDATED, Candidate, Detector, View, sma, vol_known,
)

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))


def _first_close_above(c: np.ndarray, level: float, after: int) -> int | None:
    w = np.flatnonzero(c[after + 1 :] > level)
    return int(w[0]) + after + 1 if len(w) else None


def _pullbacks(v: View, lo: int, thr: float):
    """[(high_i, high_p, low_i, low_p, depth)] built from SIGNIFICANT swings (each leg >= `thr`, see
    View.zigzag), so a pullback is a real pullback and not a one-day wobble. The last entry is the
    developing pullback (low_i None) when no swing low has confirmed after the latest high yet."""
    zz = v.zigzag(lo=lo, thr_pct=thr, thr_atr=1.0)
    out = []
    for k, (hi, hp, kind) in enumerate(zz):
        if kind != "H":
            continue
        if k + 1 < len(zz) and zz[k + 1][2] == "L":
            li, lp, _ = zz[k + 1]
            out.append((hi, hp, li, lp, (hp - lp) / hp))
        elif k == len(zz) - 1:
            seg = v.l[hi + 1 : v.t + 1]
            if seg.size:
                m = hi + 1 + int(np.argmin(seg))
                out.append((hi, hp, None, float(v.l[m]), (hp - float(v.l[m])) / hp))
    return out


class VCP(Detector):
    name = "vcp"
    display = "VCP (Volatility Contraction Pattern)"
    category = "base"
    min_bars = 150
    defaults = dict(window=120, first_min=0.08, first_max=0.40, last_max=0.12, near_pivot=0.08, min_span=15,
                    max_span=120, min_contractions=2, dev_min=0.03, inval_pct=0.01)
    definition = ("Stage-2 uptrend (close > 50-day SMA > 150-day SMA) with >=2 successive pullbacks that each get "
                  "shallower (first 8-40%, last <=12%) and, where volume is known, quieter volume. Forming while "
                  "a contraction is still developing; awaiting breakout once the last contraction is <=12% and "
                  "price is within 8% of the pivot (latest swing high); confirmed on a close above the pivot; "
                  "invalidated by a close under the last contraction's low or after 120 bars.")

    def detect(self, v: View, p) -> list[Candidate]:
        t = v.t
        c = v.c
        s50, s150 = sma(c, 50), sma(c, 150)
        if s50 is None or s150 is None or not (c[t] > s50 > s150):
            return []
        pbs = _pullbacks(v, t - p["window"], p["dev_min"])[-6:]
        seq: list = []
        for pb in reversed(pbs):  # trailing run of strictly shrinking pullbacks
            if not seq or pb[4] < seq[0][4]:
                seq.insert(0, pb)
            else:
                break
        done = [x for x in seq if x[2] is not None]
        developing = seq[-1] if seq and seq[-1][2] is None and seq[-1][4] >= p["dev_min"] else None
        if len(seq) < p["min_contractions"] or not done:
            return []
        first = seq[0]
        last_done = done[-1]
        if not (p["first_min"] <= first[4] <= p["first_max"]):
            return []
        pivot = max(x[1] for x in seq)
        anchor = first[0]
        span = t - anchor
        if span < p["min_span"] or span > p["max_span"]:
            return [] if span < p["min_span"] else [self._c(anchor, INVALIDATED, t, pivot, last_done, seq, "expired")]
        inval = last_done[3] * (1 - p["inval_pct"])
        if c[t] < inval:
            return [self._c(anchor, INVALIDATED, t, pivot, last_done, seq, "broke_last_contraction_low")]
        bo = _first_close_above(c, pivot, last_done[2])
        if bo is not None and bo < t:
            return []
        if bo == t:
            return [self._c(anchor, CONFIRMED, t, pivot, last_done, seq, None)]
        dry = True
        if vol_known(v.v):
            v1 = float(np.mean(v.v[first[0] : first[2] + 1])) if first[2] is not None else None
            v2 = float(np.mean(v.v[last_done[0] : last_done[2] + 1]))
            dry = v1 is None or v2 < v1
        tight = last_done[4] <= p["last_max"] and c[t] >= pivot * (1 - p["near_pivot"])
        st = AWAITING if (tight and dry and developing is None and len(done) >= p["min_contractions"]) else FORMING
        return [self._c(anchor, st, t, pivot, last_done, seq, None)]

    def _c(self, anchor, st, t, pivot, last_done, seq, why):
        piv = []
        for hi, hp, li, lp, _ in seq:
            piv.append((hi, hp, "pullback high"))
            if li is not None:
                piv.append((li, lp, "pullback low"))
        return Candidate(self.name, BULLISH, anchor, st, anchor, t, pivot, last_done[3], piv,
                         [{"label": "pivot", "x0": anchor, "y0": pivot, "x1": t, "y1": pivot}], why,
                         dict(contractions=[round(x[4], 4) for x in seq]))


class FlatBase(Detector):
    name = "flat-base"
    display = "Flat Base"
    category = "base"
    min_bars = 80
    defaults = dict(min_len=25, forming_len=15, max_len=65, max_depth=0.15, prior_advance=0.20, near_high=0.05)
    definition = ("After an advance of >=20% in the 50 bars before the base, price moves sideways from its high for "
                  ">=25 bars within a <=15% high-to-low range. Forming from 15 bars; awaiting breakout at >=25 "
                  "bars with price in the top 5% of the range; confirmed on a close above the base high; "
                  "invalidated when the range exceeds 15% or the base runs past 65 bars.")

    def detect(self, v: View, p) -> list[Candidate]:
        t = v.t
        h, l, c = v.h, v.l, v.c
        lo = max(0, t - p["max_len"] - 1)
        if t - lo < 2:
            return []
        s = lo + int(np.argmax(h[lo:t]))  # base high = highest high before the current bar
        L = t - s
        if s < 50 or L < p["forming_len"]:
            return []
        prior = c[s] / c[s - 50] - 1
        if prior < p["prior_advance"]:
            return []
        hi = float(h[s])
        base_low = float(l[s : t + 1].min())
        depth = (hi - base_low) / hi
        out = lambda st, why=None: [Candidate(
            self.name, BULLISH, s, st, s, t, hi, base_low,
            [(s, hi, "base high"), (s + int(np.argmin(l[s : t + 1])), base_low, "base low")],
            [{"label": "breakout", "x0": s, "y0": hi, "x1": t, "y1": hi}], why,
            dict(depth=depth, length=L, prior_advance=prior))]
        if depth > p["max_depth"]:
            return out(INVALIDATED, "too_deep")
        if L > p["max_len"]:
            return out(INVALIDATED, "too_long")
        if c[t] > hi:
            return out(CONFIRMED) if L >= p["min_len"] else []
        if L >= p["min_len"] and c[t] >= hi * (1 - p["near_high"]):
            return out(AWAITING)
        return out(FORMING)


class AscendingBase(Detector):
    name = "ascending-base"
    display = "Ascending Base"
    category = "base"
    min_bars = 100
    defaults = dict(window=150, depth_min=0.08, depth_max=0.25, min_span=45, near_high=0.10, max_wait=30,
                    inval_pct=0.01)
    definition = ("Three CONSECUTIVE pullbacks of 8-25% over >=45 bars, each with a higher high and a higher low "
                  "than the one before. Forming with two complete pullbacks and a third developing; awaiting "
                  "breakout once the third is complete and price is within 10% of its high; confirmed on a close "
                  "above the latest high; invalidated by a close under the latest higher low.")

    def detect(self, v: View, p) -> list[Candidate]:
        t = v.t
        c = v.c
        pbs = _pullbacks(v, t - p["window"], p["depth_min"])
        ok = lambda x: p["depth_min"] <= x[4] <= p["depth_max"]
        rising = lambda a, b: b[3] > a[3] and b[1] > a[1]
        # most recent run of consecutive pullbacks that are in range and rising
        run: list = []
        for pb in reversed(pbs):
            if ok(pb) and (not run or rising(pb, run[0])):
                run.insert(0, pb)
            else:
                break
        if len(run) < 2:
            return []
        run = run[-3:]
        anchor = run[0][0]
        complete = len(run) == 3 and all(x[2] is not None for x in run)
        last = run[-1]
        pivot = last[1]
        piv = []
        for hi, hp, li, lp, _ in run:
            piv.append((hi, hp, "higher high"))
            if li is not None:
                piv.append((li, lp, "higher low"))
        mk = lambda st, why=None: [Candidate(
            self.name, BULLISH, anchor, st, anchor, t, pivot, last[3] * (1 - p["inval_pct"]), piv,
            [{"label": "resistance", "x0": anchor, "y0": pivot, "x1": t, "y1": pivot}], why,
            dict(pullbacks=[round(x[4], 4) for x in run]))]
        if c[t] < last[3] * (1 - p["inval_pct"]) and last[2] is not None:
            return mk(INVALIDATED, "broke_higher_low")
        if complete and last[2] - run[0][0] >= p["min_span"]:
            bo = _first_close_above(c, pivot, last[2])
            if bo is not None and bo < t:
                return []
            if bo == t:
                return mk(CONFIRMED)
            if t - last[2] > p["max_wait"]:
                return mk(INVALIDATED, "expired_without_breakout")
            if c[t] >= pivot * (1 - p["near_high"]):
                return mk(AWAITING)
        return mk(FORMING)


class IPOBase(Detector):
    name = "ipo-base"
    display = "IPO Base"
    category = "base"
    min_bars = 25
    timeframes = ("1d",)
    defaults = dict(min_age=25, max_age=250, skip_early=10, forming_len=8, min_len=15, max_len=25, max_depth=0.35,
                    near_high=0.10, inval_pct=0.01)
    definition = ("Only evaluated when the loaded history starts at the real listing (series meta "
                  "`listing_known`). A young issue (25-250 sessions old) forms a 15-25 bar consolidation after the "
                  "first 10 sessions of listing volatility, <=35% deep. Forming from 8 bars; awaiting breakout at "
                  ">=15 bars with price in the top 10%; confirmed on a close above the base high; invalidated by "
                  "a close under the base low.")

    def detect(self, v: View, p) -> list[Candidate]:
        t = v.t
        if not v.meta.get("listing_known"):
            return []  # never guess a listing date
        age = t + 1
        if not (p["min_age"] <= age <= p["max_age"]):
            return []
        h, l, c = v.h, v.l, v.c
        start = p["skip_early"]
        for L in range(min(p["max_len"], t - start), p["forming_len"] - 1, -1):
            s = t - L
            hi = float(h[s:t].max())
            lo_ = float(l[s : t + 1].min())
            depth = (hi - lo_) / hi
            if depth > p["max_depth"]:
                continue
            mk = lambda st, why=None: [Candidate(
                self.name, BULLISH, s, st, s, t, hi, lo_ * (1 - p["inval_pct"]),
                [(s + int(np.argmax(h[s:t])), hi, "base high"), (s + int(np.argmin(l[s : t + 1])), lo_, "base low")],
                [{"label": "breakout", "x0": s, "y0": hi, "x1": t, "y1": hi}], why, dict(depth=depth, age=age))]
            if c[t] < lo_ * (1 - p["inval_pct"]) and L >= p["forming_len"]:
                return mk(INVALIDATED, "broke_base_low")
            if c[t] > hi:
                return mk(CONFIRMED) if L >= p["min_len"] else []
            if L >= p["min_len"] and c[t] >= hi * (1 - p["near_high"]):
                return mk(AWAITING)
            return mk(FORMING)
        return []


class HighTightFlag(Detector):
    name = "high-tight-flag"
    display = "High Tight Flag"
    category = "continuation"
    min_bars = 50
    defaults = dict(pole_gain=1.0, pole_window=40, min_flag=3, ok_flag=5, max_flag=25, max_depth=0.25)
    definition = ("A >=100% advance within <=40 bars, then a short, shallow flag: <=25% from its high, 5-25 bars. "
                  "Forming for the first 3-4 bars of the flag; awaiting breakout from 5 bars; confirmed on a close "
                  "above the flag's high; invalidated if the flag gets deeper than 25% or lasts past 25 bars.")

    def detect(self, v: View, p) -> list[Candidate]:
        t = v.t
        h, l, c = v.h, v.l, v.c
        lo = max(p["pole_window"], t - p["max_flag"] - 1)
        if t - lo < p["min_flag"]:
            return []
        pole_end = lo + int(np.argmax(h[lo : t - 1])) if t - 1 > lo else lo
        pe = pole_end
        pole_low_i = max(0, pe - p["pole_window"]) + int(np.argmin(c[max(0, pe - p["pole_window"]) : pe + 1]))
        gain = h[pe] / c[pole_low_i] - 1
        if gain < p["pole_gain"]:
            return []
        flag_len = t - pe
        if flag_len < p["min_flag"]:
            return []
        hi = float(h[pe])
        flag_low = float(l[pe : t + 1].min())
        depth = (hi - flag_low) / hi
        mk = lambda st, why=None: [Candidate(
            self.name, BULLISH, pole_low_i, st, pole_low_i, t, hi, flag_low,
            [(pole_low_i, float(c[pole_low_i]), "pole start"), (pe, hi, "pole top"),
             (pe + int(np.argmin(l[pe : t + 1])), flag_low, "flag low")],
            [{"label": "breakout", "x0": pe, "y0": hi, "x1": t, "y1": hi}], why,
            dict(pole_gain=gain, depth=depth, flag_len=flag_len))]
        if depth > p["max_depth"]:
            return mk(INVALIDATED, "flag_too_deep")
        if flag_len > p["max_flag"]:
            return mk(INVALIDATED, "flag_too_long")
        if c[t] > hi:
            return mk(CONFIRMED) if flag_len >= p["ok_flag"] else []
        return mk(AWAITING if flag_len >= p["ok_flag"] else FORMING)


def _weeks(v: View):
    """Completed weekly bars as of bar t: [(first_i, last_i, high, low, close)]. Daily bars are grouped
    by IST ISO week and the week still in progress is excluded; weekly series are used as-is."""
    s = v.s
    if v.timeframe == "1wk":
        return [(i, i, float(v.h[i]), float(v.l[i]), float(v.c[i])) for i in range(v.n)]
    if v.timeframe != "1d":
        return None
    # Group the WHOLE series into IST ISO weeks once (cached); as of bar t only the weeks before the
    # one containing t are complete, and a week's values use only its own bars, so nothing leaks.
    groups = s.cache.get("weeks")
    if groups is None:
        keys = [(_dt.datetime.fromtimestamp(int(x), IST).isocalendar()[:2]) for x in s.t]
        groups = []
        for i, k in enumerate(keys):
            if groups and keys[groups[-1][0]] == k:
                groups[-1].append(i)
            else:
                groups.append([i])
        s.cache["weeks"] = groups
        s.cache["week_first"] = [g[0] for g in groups]
    import bisect
    cur = bisect.bisect_right(s.cache["week_first"], v.t) - 1  # index of the week containing t
    return [(g[0], g[-1], float(s.h[g].max()), float(s.l[g].min()), float(s.c[g[-1]])) for g in groups[:cur]]


class ThreeWeeksTight(Detector):
    name = "three-weeks-tight"
    display = "Three Weeks Tight"
    category = "base"
    min_bars = 60
    timeframes = ("1d", "1wk")
    defaults = dict(tight=0.01, trend_weeks=10, inval_pct=0.0)
    definition = ("Weekly closes clustered within 1% of each other after an advance (latest close >= the close 10 "
                  "weeks earlier). Forming with two tight weeks; awaiting breakout with three; confirmed on a "
                  "close above the highest high of the three weeks; invalidated by a close below their lowest "
                  "low. Only completed weeks count.")

    def detect(self, v: View, p) -> list[Candidate]:
        wk = _weeks(v)
        if wk is None or len(wk) < p["trend_weeks"] + 3:
            return []
        t = v.t
        c = v.c
        out = []
        for k, need in ((3, AWAITING), (2, FORMING)):
            last = wk[-k:]
            closes = [w[4] for w in last]
            if (max(closes) - min(closes)) / closes[-1] > p["tight"]:
                continue
            if closes[-1] < wk[-1 - p["trend_weeks"]][4]:
                continue
            first_i = last[0][0]
            hi = max(w[2] for w in last)
            lo = min(w[3] for w in last)
            mk = lambda st, why=None: [Candidate(
                self.name, BULLISH, first_i, st, first_i, t, hi, lo,
                [(w[1], w[4], "weekly close") for w in last],
                [{"label": "breakout", "x0": first_i, "y0": hi, "x1": t, "y1": hi}], why, dict(weeks=k))]
            if c[t] < lo:
                return mk(INVALIDATED, "closed_below_range") if k == 3 else []
            if k == 3 and c[t] > hi:
                prior = _first_close_above(c, hi, last[-1][1])
                return mk(CONFIRMED) if prior == t else []
            return mk(need)
        return out


DETECTORS = [VCP(), FlatBase(), AscendingBase(), IPOBase(), HighTightFlag(), ThreeWeeksTight()]
