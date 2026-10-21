"""Rounded structures: Rounding Bottom / Top, Saucer Base, Cup Base, Cup & Handle.

How the overlapping ones differ (one formation is only ever counted once - see GROUPS in
registry.py, highest priority first, keyed on the LEFT RIM bar):

  Cup & Handle   cup (rims within 10%, 12-35% deep, U-shaped, after an advance) AND a 5-25 bar handle
  Cup Base       the same cup, right rim reached, NO handle yet (a handle turns it into Cup & Handle)
  Saucer Base    broad, shallow (<=20%) curved base, >=60 bars, after an advance - gradual, no distinct rim
  Rounding Bottom any smooth curved decline-and-recovery (>=8% deep, >=40 bars), the general case

Rim = the left swing high. Breakout level = the rim (for cups: the higher of the two rims).
"""
from __future__ import annotations

import numpy as np

from ..core import (
    AWAITING, BULLISH, CONFIRMED, FORMING, INVALIDATED, Candidate, Detector, MirrorDetector, View,
)


def _parabola(y: np.ndarray):
    m = len(y)
    x = np.linspace(0.0, 1.0, m)
    x2 = x * x
    # normal equations for y = a x^2 + b x + c (3x3 solve; far cheaper than np.polyfit's lstsq)
    A = np.array([[(x2 * x2).sum(), (x2 * x).sum(), x2.sum()],
                  [(x2 * x).sum(), x2.sum(), x.sum()],
                  [x2.sum(), x.sum(), float(m)]])
    rhs = np.array([(x2 * y).sum(), (x * y).sum(), y.sum()])
    try:
        a, b, c0 = np.linalg.solve(A, rhs)
    except np.linalg.LinAlgError:
        return 0.0, 0.0, float("nan")
    fit = a * x2 + b * x + c0
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float(((y - fit) ** 2).sum()) / ss_tot if ss_tot else 0.0
    vertex = -b / (2 * a) if a else float("nan")
    return a, r2, vertex


def _first_break(c: np.ndarray, level: float, after: int) -> int | None:
    w = np.flatnonzero(c[after + 1 :] > level)
    return int(w[0]) + after + 1 if len(w) else None


class RoundingBottom(Detector):
    name = "rounding-bottom"
    display = "Rounding Bottom"
    category = "reversal"
    min_bars = 60
    defaults = dict(min_len=40, max_len=250, r2_min=0.70, vertex_lo=0.2, vertex_hi=0.75, depth_min=0.08,
                    rim_tol=0.03, forming_recovery=0.5, awaiting_recovery=0.8, max_wait=25)
    definition = ("A gradual curved decline, a broad base and a gradual recovery: a parabola fitted to the closes "
                  "from the left swing-high rim (>=40 bars, R2>=0.70, vertex in the middle of the span, >=8% "
                  "deep). Forming once 50% of the depth is recovered; awaiting breakout from 80%; confirmed on "
                  "the first close above the rim; invalidated if no breakout within 25 bars of reaching 80%.")
    saucer = False

    def _geometry(self, v: View, p):
        t = v.t
        h, c = v.h, v.c
        rims = v.swing_highs(lo=t - p["max_len"])
        for a, ra in rims:  # earliest (longest) formation first -> stable choice as t advances
            m = t - a + 1
            if m < p["min_len"]:
                continue
            seg = c[a : t + 1]
            low = float(seg.min())
            low_i = a + int(np.argmin(seg))
            depth = (ra - low) / ra
            if depth < p["depth_min"] or low_i - a < 8:
                continue
            if h[a + 1 : t].size and h[a + 1 : t].max() > ra * (1 + p["rim_tol"]):
                continue  # something already overshot the rim: not this formation
            coef, r2, vertex = _parabola(seg)
            if coef <= 0 or r2 < p["r2_min"] or not (p["vertex_lo"] <= vertex <= p["vertex_hi"]):
                continue
            yield dict(a=a, ra=ra, low=low, low_i=low_i, depth=depth, r2=r2, m=m)

    def _candidate(self, v: View, p, g, name, **extra) -> Candidate | None:
        t = v.t
        c = v.c
        a, ra, low, low_i = g["a"], g["ra"], g["low"], g["low_i"]
        rec = (c[t] - low) / (ra - low)
        bo = _first_break(c, ra, low_i)
        if bo is not None and bo < t:
            return None  # broke out earlier; that occurrence exists already
        if bo == t:
            st = CONFIRMED
        else:
            near = np.flatnonzero((c[low_i:] - low) / (ra - low) >= p["awaiting_recovery"])
            if len(near) and t - (low_i + int(near[0])) > p["max_wait"]:
                st = INVALIDATED
            elif rec >= p["awaiting_recovery"]:
                st = AWAITING
            elif rec >= p["forming_recovery"]:
                st = FORMING
            else:
                return None
        meta = dict(depth=g["depth"], r2=g["r2"], length=g["m"], group_key=a, **extra)
        return Candidate(
            name, BULLISH, a, st, a, t, ra, low,
            [(a, ra, "left rim"), (low_i, low, "base low")],
            [{"label": "rim / breakout", "x0": a, "y0": ra, "x1": t, "y1": ra}],
            "no_breakout_in_time" if st == INVALIDATED else None, meta,
        )

    def detect(self, v: View, p) -> list[Candidate]:
        for g in self._geometry(v, p):
            if self.saucer:
                a = g["a"]
                if g["m"] < p["saucer_min_len"] or g["depth"] > p["saucer_max_depth"] or a < 60:
                    continue
                if v.c[a] / v.c[a - 60] - 1 < p["saucer_prior_advance"]:
                    continue
            cand = self._candidate(v, p, g, self.name)
            if cand is not None:
                return [cand]
        return []


class SaucerBase(RoundingBottom):
    name = "saucer-base"
    display = "Saucer Base"
    category = "base"
    saucer = True
    min_bars = 100
    defaults = {**RoundingBottom.defaults, "saucer_min_len": 60, "saucer_max_depth": 0.12,
                "saucer_prior_advance": 0.10}
    definition = ("The Rounding Bottom geometry, but broad (>=60 bars) and shallower than any cup (<12% deep) and "
                  "forming after an advance (>=10% over the 60 bars before the rim): a base, not a reversal. "
                  "Cups start at 12% depth, so a formation is never both. Same status rules; ranks above "
                  "Rounding Bottom so the same formation is not counted twice.")


# -- cups ------------------------------------------------------------------------------------------
def _cup(v: View, p, a: int, ra: float, r: int, rr: float):
    """Geometry check for a cup from left rim a to right rim r. Returns dict or None."""
    h, l, c = v.h, v.l, v.c
    if not (p["min_len"] <= r - a <= p["max_len"]):
        return None
    if abs(ra - rr) / ra > p["rim_match"] and rr < ra:  # right rim may exceed left; may not be far below
        return None
    seg_h = h[a + 1 : r]
    if seg_h.size and seg_h.max() > ra * (1 + p["rim_tol"]):
        return None
    low = float(l[a : r + 1].min())
    low_i = a + int(np.argmin(l[a : r + 1]))
    depth = (ra - low) / ra
    if not (p["depth_min"] <= depth <= p["depth_max"]):
        return None
    frac = (low_i - a) / (r - a)
    if not (0.25 <= frac <= 0.75):
        return None
    floor = low + (ra - low) / 3
    if (c[a : r + 1] <= floor).mean() < p["u_share"]:
        return None  # a V, not a rounded cup
    if a < 60 or c[a] / c[a - 60] - 1 < p["prior_advance"]:
        return None
    return dict(a=a, ra=ra, r=r, rr=rr, low=low, low_i=low_i, depth=depth)


_CUP_DEFAULTS = dict(min_len=30, max_len=250, rim_match=0.10, rim_tol=0.03, depth_min=0.12, depth_max=0.35,
                     u_share=0.40, prior_advance=0.10, handle_min_len=5, handle_max_len=25, handle_min_depth=0.01,
                     handle_max_depth=0.15, handle_start=0.03, max_wait=10)


class CupAndHandle(Detector):
    name = "cup-and-handle"
    display = "Cup & Handle"
    category = "base"
    min_bars = 100
    defaults = _CUP_DEFAULTS
    definition = ("A rounded cup (rims within 10%, 12-35% deep, U-shaped, after an advance) followed by a 5-25 bar "
                  "handle that pulls back 1% to min(15%, half the cup depth). Forming while the handle develops "
                  "(started, shorter than 5 bars); awaiting breakout once the handle is valid; confirmed on the "
                  "first close above the higher rim; invalidated if the handle is too deep/long or price loses "
                  "the cup's midpoint.")

    def detect(self, v: View, p) -> list[Candidate]:
        t = v.t
        h, l, c = v.h, v.l, v.c
        out: list[Candidate] = []
        highs = v.swing_highs(lo=t - p["max_len"] - p["handle_max_len"] - 20)
        for a, ra in highs:
            for r, rr in highs:
                if r - a < p["min_len"]:
                    continue
                hl = t - r  # handle length so far
                if hl < 1 or hl > p["handle_max_len"] + p["max_wait"]:
                    continue
                g = _cup(v, p, a, ra, r, rr)
                if not g:
                    continue
                hl_low = float(l[r : t + 1].min())
                depth_h = (rr - hl_low) / rr
                lvl = max(ra, rr)
                mid = g["low"] + (ra - g["low"]) / 2
                max_depth = min(p["handle_max_depth"], g["depth"] / 2)
                bo = _first_break(c, lvl, r)
                if bo is not None and bo < t:
                    continue
                if bo == t:
                    if hl < p["handle_min_len"] or depth_h < p["handle_min_depth"]:
                        continue  # no real handle: this is a Cup Base breakout, not a C&H
                    st, why = CONFIRMED, None
                elif depth_h < p["handle_start"] * 0.33:
                    continue  # no pullback yet -> Cup Base territory
                elif depth_h > max_depth or c[t] < mid:
                    st, why = INVALIDATED, "handle_too_deep"
                elif hl > p["handle_max_len"]:
                    st, why = INVALIDATED, "handle_too_long"
                elif hl >= p["handle_min_len"] and depth_h >= p["handle_min_depth"]:
                    st, why = AWAITING, None
                else:
                    st, why = FORMING, None
                out.append(Candidate(
                    self.name, BULLISH, a, st, a, t, lvl, hl_low if st != INVALIDATED else mid,
                    [(a, ra, "left rim"), (g["low_i"], g["low"], "cup low"), (r, rr, "right rim")],
                    [{"label": "rim / breakout", "x0": a, "y0": lvl, "x1": t, "y1": lvl}], why,
                    dict(depth=g["depth"], handle_depth=depth_h, handle_len=hl, group_key=a),
                ))
        # keep the most advanced single candidate per left rim
        best: dict[int, Candidate] = {}
        rank = {INVALIDATED: 0, FORMING: 1, AWAITING: 2, CONFIRMED: 3}
        for cnd in out:
            cur = best.get(cnd.anchor)
            if cur is None or (rank[cnd.status], cnd.pivots[-1][0]) > (rank[cur.status], cur.pivots[-1][0]):
                best[cnd.anchor] = cnd
        return list(best.values())


class CupBase(Detector):
    name = "cup-base"
    display = "Cup Base"
    category = "base"
    min_bars = 100
    defaults = _CUP_DEFAULTS
    definition = ("The same cup as Cup & Handle, but with NO handle: the right rim is the highest high of the last "
                  "8 bars and price has not pulled back more than 3% from it. Forming while the right side "
                  "recovers (>=50% of the depth); awaiting breakout from 85%; confirmed on the first close "
                  "above the higher rim. If a handle forms it becomes Cup & Handle and this is superseded.")

    def detect(self, v: View, p) -> list[Candidate]:
        t = v.t
        h, l, c = v.h, v.l, v.c
        out: list[Candidate] = []
        lo8 = max(0, t - 7)
        r = lo8 + int(np.argmax(h[lo8 : t + 1]))
        rr = float(h[r])
        for a, ra in v.swing_highs(lo=t - p["max_len"] - 10):
            if r - a < p["min_len"]:
                continue
            low = float(l[a : t + 1].min())
            low_i = a + int(np.argmin(l[a : t + 1]))
            if low_i <= a + 5 or low_i >= r:
                continue
            depth = (ra - low) / ra
            rec = (c[t] - low) / (ra - low) if ra > low else 0.0
            # Breakout level = the highest PRIOR high of the cup (never the current bar's own high).
            lvl = max(ra, float(h[a + 1 : t].max())) if t > a + 1 else ra
            pull = (rr - float(l[r : t + 1].min())) / rr
            g = _cup(v, p, a, ra, r, rr) if rec >= 0.85 else None
            if rec >= 0.85 and not g:
                continue
            if g is None:  # right side still recovering: check the cup shape up to now
                if not (p["depth_min"] <= depth <= p["depth_max"] and rec >= 0.5 and 0.25 <= (low_i - a) / (t - a) <= 0.85):
                    continue
                if a < 60 or c[a] / c[a - 60] - 1 < p["prior_advance"]:
                    continue
                if h[a + 1 : t + 1].size and h[a + 1 : t + 1].max() > ra * (1 + p["rim_tol"]):
                    continue
                if (c[a : t + 1] <= low + (ra - low) / 3).mean() < p["u_share"]:
                    continue
            if pull > p["handle_start"]:
                continue  # a handle is forming: Cup & Handle's job
            bo = _first_break(c, lvl, low_i)
            if bo is not None and bo < t:
                continue
            st = CONFIRMED if bo == t else AWAITING if rec >= 0.85 else FORMING
            out.append(Candidate(
                self.name, BULLISH, a, st, a, t, lvl, low,
                [(a, ra, "left rim"), (low_i, low, "cup low")],
                [{"label": "rim / breakout", "x0": a, "y0": lvl, "x1": t, "y1": lvl}], None,
                dict(depth=depth, group_key=a),
            ))
            break  # longest valid cup only
        return out


ROUNDING_BOTTOM = RoundingBottom()
DETECTORS = [
    ROUNDING_BOTTOM,
    MirrorDetector(ROUNDING_BOTTOM, "rounding-top", "Rounding Top",
                   "Mirror of Rounding Bottom: a gradual rise, broad rounded peak and gradual decline; confirmed "
                   "only on a close below the left trough."),
    SaucerBase(),
    CupBase(),
    CupAndHandle(),
]
