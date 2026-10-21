"""Harmonic pattern (Gartley-like), bullish written; bearish via the price-inverted twin.

Swing points X, A, B, C, D come from CONFIRMED swing pivots (alternating low/high). Ratios (all
configurable, each within a tolerance band):
  B retraces XA by 0.618            C retraces AB by 0.382-0.886
  CD extends BC by 1.272-1.618      D completes at 0.786 retracement of XA (and stays above X)

Status: forming while X-A-B-C exist with valid ratios and price is above the projected completion zone;
awaiting breakout (= awaiting completion) once price trades inside the zone; confirmed when D is a
confirmed swing low inside the zone and every ratio holds (the STRUCTURE is complete - it is not a
forecast); invalidated by a close below X or beyond the 0.886 retracement. Low-reliability: experimental.
"""
from __future__ import annotations

from ..core import (
    AWAITING, BULLISH, CONFIRMED, FORMING, INVALIDATED, Bidirectional, Candidate, Detector, View,
)


def _alternating(v: View, lo: int) -> list[tuple[int, float, str]]:
    pts = [(i, q, "H") for i, q in v.swing_highs(lo=lo)] + [(i, q, "L") for i, q in v.swing_lows(lo=lo)]
    pts.sort()
    out: list[tuple[int, float, str]] = []
    for pt in pts:
        if out and out[-1][2] == pt[2]:
            keep_new = pt[1] > out[-1][1] if pt[2] == "H" else pt[1] < out[-1][1]
            if keep_new:
                out[-1] = pt
        else:
            out.append(pt)
    return out


class _Gartley(Detector):
    name = "harmonic-gartley"
    display = "Harmonic Pattern (Gartley-like)"
    category = "harmonic"
    maturity = "experimental"
    min_bars = 60
    defaults = dict(lookback=200, b_ratio=0.618, b_tol=0.06, c_lo=0.382, c_hi=0.886, d_ratio=0.786, d_tol=0.05,
                    ext_lo=1.272, ext_hi=1.618, ext_slack=0.08, beyond=0.886)
    definition = ("Five ordered swing points X, A, B, C, D with Fibonacci ratios inside configurable bands: "
                  "B=0.618 of XA, C=0.382-0.886 of AB, CD=1.272-1.618 of BC, D=0.786 of XA. Forming while D is "
                  "still ahead; awaiting while price is inside the completion zone; confirmed when D is a "
                  "confirmed swing and all ratios hold (structure complete, not a forecast); invalidated by a "
                  "close below X or past the 0.886 retracement. Bearish direction is the mirror.")

    def detect(self, v: View, p) -> list[Candidate]:
        t = v.t
        l, c = v.l, v.c
        seq = _alternating(v, t - p["lookback"])
        out: list[Candidate] = []
        # bullish: X is a low, A a high, B a low, C a high, (D a low)
        for start in range(len(seq)):
            if seq[start][2] != "L":
                continue
            pts = seq[start : start + 5]
            if len(pts) < 4:
                continue
            (xi, x, _), (ai, a, _), (bi, b, _), (ci, cc, _) = pts[:4]
            xa = a - x
            if xa <= 0 or not (b > x and cc < a and cc > b):
                continue
            if abs((a - b) / xa - p["b_ratio"]) > p["b_tol"]:
                continue
            ab = a - b
            if not (p["c_lo"] - 0.02 <= (cc - b) / ab <= p["c_hi"] + 0.02):
                continue
            d_t = a - p["d_ratio"] * xa
            tol = p["d_tol"] * xa
            zone = (d_t - tol, d_t + tol)
            piv = [(xi, x, "X"), (ai, a, "A"), (bi, b, "B"), (ci, cc, "C")]
            lines = [{"label": "XA", "x0": xi, "y0": x, "x1": ai, "y1": a},
                     {"label": "AB", "x0": ai, "y0": a, "x1": bi, "y1": b},
                     {"label": "BC", "x0": bi, "y0": b, "x1": ci, "y1": cc},
                     {"label": "D zone", "x0": ci, "y0": d_t, "x1": t, "y1": d_t}]
            meta = dict(prz=zone)
            mk = lambda st, why=None, pv=piv, ln=lines, di=None: Candidate(
                self.name, BULLISH, xi, st, xi, t, None, x, pv, ln, why, {**meta, "d_idx": di})
            if (c[ci + 1 : t + 1] < x).any():
                out.append(mk(INVALIDATED, "closed_below_X"))
                continue
            if (c[ci + 1 : t + 1] < a - p["beyond"] * xa).any():
                out.append(mk(INVALIDATED, "beyond_0.886_retracement"))
                continue
            # complete: D is a confirmed swing low
            if len(pts) == 5 and pts[4][2] == "L":
                di, d, _ = pts[4]
                bc = cc - b
                cd = cc - d
                ext = cd / bc if bc else 0
                if (abs(d - d_t) <= tol and d > x and p["ext_lo"] - p["ext_slack"] <= ext <= p["ext_hi"] + p["ext_slack"]):
                    ln = lines[:3] + [{"label": "CD", "x0": ci, "y0": cc, "x1": di, "y1": d}]
                    out.append(mk(CONFIRMED, None, piv + [(di, d, "D")], ln, di))
                    continue
            # still developing: price relative to the completion zone
            if t - ci < 3:
                continue
            if float(l[ci + 1 : t + 1].min()) <= zone[1]:
                out.append(mk(AWAITING))
            elif c[t] > zone[1]:
                out.append(mk(FORMING))
        # latest geometry per X
        best: dict[int, Candidate] = {}
        rank = {INVALIDATED: 0, FORMING: 1, AWAITING: 2, CONFIRMED: 3}
        for cnd in out:
            cur = best.get(cnd.anchor)
            if cur is None or rank[cnd.status] >= rank[cur.status]:
                best[cnd.anchor] = cnd
        # only the most recent few formations are interesting
        return sorted(best.values(), key=lambda x: -x.anchor)[:2]


HARMONIC = Bidirectional(_Gartley(), "harmonic-gartley", "Harmonic Pattern (Gartley-like)")
DETECTORS = [HARMONIC]
