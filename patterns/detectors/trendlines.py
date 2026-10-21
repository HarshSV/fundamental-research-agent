"""Trendline structures: Ascending / Descending / Symmetrical Triangle, Rising / Falling Wedge,
Rectangle, and the pole-based Flag and Pennant.

Triangles, wedges and rectangles share ONE analysis: fit an upper line through the swing highs and
a lower line through the swing lows over the longest valid lookback, then classify by the two
slopes. A formation needs >=2 touches on each boundary; with exactly 4 touches it is Forming, with
>=5 touches (and >=15 bars) it is Awaiting breakout.

Flag and Pennant need a preceding directional move (the pole). A small channel or triangle with no
pole is NOT reported.
"""
from __future__ import annotations

import numpy as np

from ..core import (
    AWAITING, BEARISH, BULLISH, CONFIRMED, FORMING, INVALIDATED, Bidirectional, Candidate, Detector, View,
    fit_line,
)

_CHAN_DEFAULTS = dict(
    lookbacks=(120, 90, 60, 45, 30, 20), dev_pct=0.015, dev_atr=1.0, flat=0.0005, min_len=15, max_len=120,
    min_width=0.03, converge=0.15, min_touches_awaiting=5,
)


def _analyse(v: View, p) -> list[dict]:
    """All valid (longest-first) boundary fits as of bar t, memoised per bar."""
    key = ("chan", v.t, tuple(sorted((k, str(x)) for k, x in p.items() if k in _CHAN_DEFAULTS)))
    hit = v.s.cache.get(key)
    if hit is not None:
        return hit
    t = v.t
    h, l, c = v.h, v.l, v.c
    out: list[dict] = []
    for W in p["lookbacks"]:
        lo = t - W
        if lo < 0:
            continue
        hs = v.swing_highs(lo=lo)
        ls = v.swing_lows(lo=lo)
        if len(hs) < 2 or len(ls) < 2:
            continue
        first = min(hs[0][0], ls[0][0])
        if t - first < p["min_len"] - 5:
            continue
        mu, bu = fit_line([i for i, _ in hs], [q for _, q in hs])
        ml, bl = fit_line([i for i, _ in ls], [q for _, q in ls])
        ref = float(c[t])
        tol = max(p["dev_pct"], p["dev_atr"] * (v.atrp(t) if v.atrp(t) == v.atrp(t) else 0.0))
        if any(abs(q - (mu * i + bu)) / ref > tol for i, q in hs):
            continue
        if any(abs(q - (ml * i + bl)) / ref > tol for i, q in ls):
            continue
        # price must have stayed inside the boundaries until the current bar
        idx = np.arange(first, t)
        up_line, lo_line = mu * idx + bu, ml * idx + bl
        if (c[first:t] > up_line * (1 + tol)).any() or (c[first:t] < lo_line * (1 - tol)).any():
            continue
        w_first = (mu * first + bu) - (ml * first + bl)
        w_now = (mu * t + bu) - (ml * t + bl)
        if w_first <= 0:
            continue
        out.append(dict(
            W=W, first=first, hs=hs, ls=ls, mu=mu, bu=bu, ml=ml, bl=bl, su=mu / ref, sl=ml / ref,
            w_first=w_first, w_now=w_now, tol=tol, touches=len(hs) + len(ls),
            up_now=mu * t + bu, lo_now=ml * t + bl,
        ))
    v.s.cache[key] = out
    return out


class _Channel(Detector):
    """Base for the six boundary-pair patterns. Subclasses provide `kind_ok`, expected breakout
    direction (`expect`: 'up' | 'down' | None) and a width rule."""

    category = "continuation"
    min_bars = 40
    defaults = _CHAN_DEFAULTS
    expect: str | None = None
    converging = True

    def kind_ok(self, f: dict, p) -> bool:  # pragma: no cover
        raise NotImplementedError

    def detect(self, v: View, p) -> list[Candidate]:
        t = v.t
        c = v.c
        for f in _analyse(v, p):
            if not self.kind_ok(f, p):
                continue
            if self.converging and f["w_now"] > f["w_first"] * (1 - p["converge"]):
                continue
            if not self.converging and (f["w_now"] / float(c[t]) < p["min_width"]):
                continue
            length = t - f["first"]
            if length > p["max_len"]:
                continue
            up, lo = f["up_now"], f["lo_now"]
            tol = f["tol"]
            broke_up = c[t] > up
            broke_dn = c[t] < lo
            direction = BULLISH if self.expect == "up" else BEARISH if self.expect == "down" else None
            # breakout bookkeeping: only the FIRST breaking close counts
            first_up = self._first_break(v, f, True)
            first_dn = self._first_break(v, f, False)
            # Breakout/invalidation levels follow the expected direction. Neutral shapes (symmetrical
            # triangle, rectangle) report the upper boundary as `breakout_level` and the lower as
            # `invalidation_level`; either boundary can be the break.
            brk, inv = (lo, up) if self.expect == "down" else (up, lo)
            mk = lambda st, why=None, d=direction: [Candidate(
                self.name, d, f["first"], st, f["first"], t, brk, inv,
                [(i, q, "swing high") for i, q in f["hs"]] + [(i, q, "swing low") for i, q in f["ls"]],
                [{"label": "upper boundary", "x0": f["first"], "y0": f["mu"] * f["first"] + f["bu"], "x1": t, "y1": up},
                 {"label": "lower boundary", "x0": f["first"], "y0": f["ml"] * f["first"] + f["bl"], "x1": t, "y1": lo}],
                why, dict(touches=f["touches"], length=length))]
            if self.converging:
                # apex: x where the boundaries meet
                dm = f["mu"] - f["ml"]
                if dm < 0:
                    apex = (f["bl"] - f["bu"]) / dm
                    if t >= apex:
                        return mk(INVALIDATED, "apex_passed")
            if first_up is not None and first_up < t or first_dn is not None and first_dn < t:
                continue  # already broke out earlier; that occurrence exists (or is stale)
            if broke_up or broke_dn:
                up_dir = bool(broke_up)
                if self.expect is None:
                    d = BULLISH if up_dir else BEARISH
                    return [self._confirmed_neutral(f, t, up, lo, up_dir, length)]
                good = (self.expect == "up") == up_dir
                return mk(CONFIRMED if good else INVALIDATED, None if good else "broke_against_bias")
            st = AWAITING if (f["touches"] >= p["min_touches_awaiting"] and length >= p["min_len"]) else FORMING
            return mk(st)
        return []

    @staticmethod
    def _first_break(v: View, f: dict, up: bool) -> int | None:
        idx = np.arange(f["first"], v.t + 1)
        line = (f["mu"] if up else f["ml"]) * idx + (f["bu"] if up else f["bl"])
        c = v.c[f["first"] : v.t + 1]
        hit = np.flatnonzero(c > line) if up else np.flatnonzero(c < line)
        return int(hit[0]) + f["first"] if len(hit) else None

    def _confirmed_neutral(self, f, t, up, lo, up_dir, length):
        d = BULLISH if up_dir else BEARISH
        lvl = up if up_dir else lo
        return Candidate(
            self.name, d, f["first"], CONFIRMED, f["first"], t, lvl, lo if up_dir else up,
            [(i, q, "swing high") for i, q in f["hs"]] + [(i, q, "swing low") for i, q in f["ls"]],
            [{"label": "upper boundary", "x0": f["first"], "y0": f["mu"] * f["first"] + f["bu"], "x1": t, "y1": up},
             {"label": "lower boundary", "x0": f["first"], "y0": f["ml"] * f["first"] + f["bl"], "x1": t, "y1": lo}],
            None, dict(touches=f["touches"], length=length),
        )


class AscendingTriangle(_Channel):
    name = "ascending-triangle"
    display = "Ascending Triangle"
    expect = "up"
    definition = ("Roughly horizontal resistance with rising swing lows (>=2 touches each; both boundaries must hold). "
                  "Forming at 4 touches, awaiting breakout at >=5 touches over >=15 bars; confirmed on a close "
                  "above resistance; invalidated by a close below the rising support or once the apex passes.")

    def kind_ok(self, f, p):
        return abs(f["su"]) <= p["flat"] and f["sl"] > 1.5 * p["flat"]


class DescendingTriangle(_Channel):
    name = "descending-triangle"
    display = "Descending Triangle"
    expect = "down"
    definition = ("Roughly horizontal support with falling swing highs; confirmed on a close below support, "
                  "invalidated by a close above the falling resistance or once the apex passes.")

    def kind_ok(self, f, p):
        return abs(f["sl"]) <= p["flat"] and f["su"] < -1.5 * p["flat"]


class SymmetricalTriangle(_Channel):
    name = "symmetrical-triangle"
    display = "Symmetrical Triangle"
    expect = None
    definition = ("A falling resistance line and a rising support line that converge. No direction is assumed: the "
                  "direction is set by the first close outside the boundaries.")

    def kind_ok(self, f, p):
        if not (f["su"] < -p["flat"] and f["sl"] > p["flat"]):
            return False
        return 0.4 <= abs(f["su"]) / abs(f["sl"]) <= 2.5


class RisingWedge(_Channel):
    name = "rising-wedge"
    display = "Rising Wedge"
    expect = "down"
    category = "reversal"
    definition = ("Both boundaries rising and converging, the lower rising faster than the upper. A close below "
                  "the lower boundary confirms (bearish); a close above the upper invalidates.")

    def kind_ok(self, f, p):
        return f["su"] > p["flat"] and f["sl"] > p["flat"] and f["sl"] > f["su"]


class FallingWedge(_Channel):
    name = "falling-wedge"
    display = "Falling Wedge"
    expect = "up"
    category = "reversal"
    definition = ("Both boundaries falling and converging, the upper falling faster than the lower. A close above "
                  "the upper boundary confirms (bullish); a close below the lower invalidates.")

    def kind_ok(self, f, p):
        return f["su"] < -p["flat"] and f["sl"] < -p["flat"] and abs(f["su"]) > abs(f["sl"])


class Rectangle(_Channel):
    name = "rectangle"
    display = "Rectangle"
    expect = None
    converging = False
    definition = ("Repeated touches of roughly horizontal support and resistance (>=2 each) at least 3% apart. "
                  "Awaiting breakout until price closes outside either boundary; the direction is that of the "
                  "breakout.")

    def kind_ok(self, f, p):
        return abs(f["su"]) <= p["flat"] and abs(f["sl"]) <= p["flat"]


# -- flag / pennant ------------------------------------------------------------------------------
class _PoleBase(Detector):
    category = "continuation"
    min_bars = 40
    defaults = dict(pole_pct=0.10, pole_atr=4.0, pole_max_bars=15, min_flag=5, max_flag=20, max_retrace=0.5,
                    par_slope=0.0015, conv_slope=0.0005, size_vs_pole=0.5)
    pennant = False

    def detect(self, v: View, p) -> list[Candidate]:
        t = v.t
        h, l, c = v.h, v.l, v.c
        lo = max(p["pole_max_bars"], t - p["max_flag"] - 1)
        if t - lo < 3:
            return []
        pe = lo + int(np.argmax(h[lo:t]))  # pole top = highest high before the current bar
        flag_len = t - pe
        if flag_len < 4:
            return []
        ps = max(0, pe - p["pole_max_bars"]) + int(np.argmin(c[max(0, pe - p["pole_max_bars"]) : pe + 1]))
        pole = float(h[pe] / c[ps] - 1)
        if pole < v.tol(p["pole_pct"], p["pole_atr"], ps):  # >=10% or >=4 ATR, whichever is larger
            return []
        xs = np.arange(pe + 1, t + 1)
        if len(xs) < 3:
            return []
        mu, bu = fit_line(xs, h[pe + 1 : t + 1])
        ml, bl = fit_line(xs, l[pe + 1 : t + 1])
        ref = float(c[t])
        su, sl = mu / ref, ml / ref
        top = float(h[pe])
        flag_low = float(l[pe : t + 1].min())
        retrace = (top - flag_low) / (top - float(c[ps]))
        if self.pennant:
            shape_ok = su < -p["conv_slope"] and sl > p["conv_slope"]
        else:
            shape_ok = su < p["par_slope"] and sl < p["par_slope"] and abs(su - sl) <= p["par_slope"]
        up_now = mu * t + bu
        lo_now = ml * t + bl
        height = (float(h[pe + 1 : t + 1].max()) - float(l[pe + 1 : t + 1].min()))
        mk = lambda st, why=None: [Candidate(
            self.name, BULLISH, ps, st, ps, t, up_now, lo_now,
            [(ps, float(c[ps]), "pole start"), (pe, top, "pole top")],
            [{"label": "upper", "x0": pe + 1, "y0": mu * (pe + 1) + bu, "x1": t, "y1": up_now},
             {"label": "lower", "x0": pe + 1, "y0": ml * (pe + 1) + bl, "x1": t, "y1": lo_now}],
            why, dict(pole=pole, flag_len=flag_len, retrace=retrace))]
        if retrace > p["max_retrace"]:
            return mk(INVALIDATED, "retraced_more_than_half_the_pole")
        if flag_len > p["max_flag"]:
            return mk(INVALIDATED, "flag_too_long")
        if height > (top - float(c[ps])) * p["size_vs_pole"]:
            return []
        if not shape_ok:
            return []
        if c[t] < lo_now * 0.99 and flag_len >= p["min_flag"]:
            return mk(INVALIDATED, "broke_against_the_pole")
        prior_break = np.flatnonzero(c[pe + 1 : t] > (mu * np.arange(pe + 1, t) + bu))
        if c[t] > up_now:
            return mk(CONFIRMED) if (flag_len >= p["min_flag"] and not len(prior_break)) else []
        return mk(AWAITING if flag_len >= p["min_flag"] else FORMING)


class _Flag(_PoleBase):
    name = "flag"
    display = "Flag"
    pennant = False
    definition = ("A strong directional move (the pole, >=10% over <=15 bars) followed by a compact countertrend "
                  "channel of 5-20 bars, roughly parallel, retracing <=50% of the pole and no taller than half "
                  "of it. Forming from 4 bars, awaiting breakout from 5; confirmed on a close through the "
                  "channel in the pole's direction; invalidated by a deeper retrace or a break the other way. "
                  "Bearish flags are the mirror (a down-pole).")


class _Pennant(_PoleBase):
    name = "pennant"
    display = "Pennant"
    pennant = True
    defaults = {**_PoleBase.defaults, "max_flag": 15}
    definition = ("The same pole, followed by a CONVERGING consolidation (falling highs, rising lows) of 5-15 bars "
                  "no taller than half the pole; confirmed on a close through the upper line (bullish), "
                  "invalidated by a break the other way. Bearish pennants are the mirror.")


FLAG = Bidirectional(_Flag(), "flag", "Flag")
PENNANT = Bidirectional(_Pennant(), "pennant", "Pennant")
DETECTORS = [
    AscendingTriangle(), DescendingTriangle(), SymmetricalTriangle(), RisingWedge(), FallingWedge(), Rectangle(),
    FLAG, PENNANT,
]
