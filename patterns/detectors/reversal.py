"""Reversal structures: Double / Triple Bottom (+ Top mirrors), Inverse Head & Shoulders
(+ Head & Shoulders mirror). Written for the BULLISH case; the bearish twin runs the same rules on
the multiplicatively price-inverted series (core.MirrorDetector), so both sides share one definition.

Pivots come from the significant-swing zig-zag (core.View.zigzag): only meaningful, alternating
swings count, so "two lows" means two consecutive meaningful lows with exactly one rally between.

Status model (bullish; the bearish twin is the mirror image):
  forming            the first leg(s) exist and the last low is developing (not yet a confirmed swing)
  awaiting_breakout  the structure is complete (last low is a confirmed swing); price is still below the
                     breakout level (neckline / resistance)
  confirmed          a COMPLETED bar closes above the breakout level
  invalidated        a completed bar closes decisively below the pattern's lowest low, or the breakout did
                     not arrive within `max_wait` bars
"""
from __future__ import annotations

import numpy as np

from ..core import (
    AWAITING, BULLISH, CONFIRMED, FORMING, INVALIDATED, Candidate, Detector, MirrorDetector, View,
    best_per_anchor, fit_line,
)


def _status_after(v: View, low_idx: int, low_level: float, level_at, inval: float, max_wait: int):
    """Shared tail for 'complete structure' states. `level_at(i)` = breakout level at bar i.
    Returns (status, reason) or None when the formation was already broken out earlier."""
    t = v.t
    c = v.c
    if t > low_idx and (c[low_idx + 1 : t + 1] < inval).any():
        return INVALIDATED, "broke_support"
    levels = np.array([level_at(i) for i in range(low_idx + 1, t + 1)]) if t > low_idx else np.array([])
    above = c[low_idx + 1 : t + 1] > levels if len(levels) else np.array([], dtype=bool)
    if above.any():
        first = int(np.flatnonzero(above)[0]) + low_idx + 1
        if first == t:
            return CONFIRMED, None
        return None  # broke out earlier: that occurrence already exists (or is too old to open now)
    if t - low_idx > max_wait:
        return INVALIDATED, "expired_without_breakout"
    return AWAITING, None


_SWING = dict(swing_pct=0.04, swing_atr=2.0)


class DoubleBottom(Detector):
    name = "double-bottom"
    display = "Double Bottom"
    category = "reversal"
    min_bars = 40
    defaults = dict(_SWING, tol_pct=0.03, tol_atr=1.0, min_gap=8, max_gap=80, max_wait=40, inval_pct=0.015)
    definition = ("Two CONSECUTIVE significant swing lows (a rally of >=4% / 2 ATR between them) within a "
                  "volatility-scaled tolerance, 8-80 bars apart. Forming while the second low develops; awaiting "
                  "breakout once it is a confirmed swing low; confirmed on a close above the intervening swing "
                  "high (the neckline); invalidated by a close more than 1.5% under the lows or 40 bars without "
                  "a breakout. Three lows are a Triple Bottom instead and rank above this.")

    def detect(self, v: View, p) -> list[Candidate]:
        t = v.t
        zz = v.zigzag(lo=t - (p["max_gap"] + p["max_wait"] + 60), thr_pct=p["swing_pct"], thr_atr=p["swing_atr"])
        h, l, c = v.h, v.l, v.c
        out: list[Candidate] = []
        for k in range(len(zz) - 1):
            if zz[k][2] != "L" or zz[k + 1][2] != "H":
                continue
            i1, p1, _ = zz[k]
            pk_i, pk, _ = zz[k + 1]
            tol = v.tol(p["tol_pct"], p["tol_atr"], i1)
            # complete: the next pivot is the second low
            if k + 2 < len(zz) and zz[k + 2][2] == "L":
                i2, p2, _ = zz[k + 2]
                if p["min_gap"] <= i2 - i1 <= p["max_gap"] and abs(p2 - p1) / min(p1, p2) <= tol:
                    low = min(p1, p2)
                    inval = low * (1 - p["inval_pct"])
                    res = _status_after(v, i2, low, lambda i: pk, inval, p["max_wait"])
                    if res is not None:
                        st, why = res
                        out.append(Candidate(
                            self.name, BULLISH, i1, st, i1, t if st != INVALIDATED else i2, pk, inval,
                            [(i1, p1, "low 1"), (pk_i, pk, "neckline peak"), (i2, p2, "low 2")],
                            [{"label": "neckline", "x0": pk_i, "y0": pk, "x1": t, "y1": pk}], why,
                            dict(group_key=("lows", i2), swing=pk / low - 1)))
                continue
            # forming: the rally exists (last pivot is the peak) and price is back near the first low
            if k + 1 != len(zz) - 1:
                continue
            seg = l[pk_i + 1 : t + 1]
            if not seg.size or t - i1 > p["max_gap"] + 20:
                continue
            m_i = pk_i + 1 + int(np.argmin(seg))
            m = float(l[m_i])
            if m_i - i1 < p["min_gap"] or abs(m - p1) / p1 > tol or m < p1 * (1 - p["inval_pct"]) or c[t] < m:
                continue
            out.append(Candidate(
                self.name, BULLISH, i1, FORMING, i1, t, pk, p1 * (1 - p["inval_pct"]),
                [(i1, p1, "low 1"), (pk_i, pk, "neckline peak"), (m_i, m, "low 2 (developing)")],
                [{"label": "neckline", "x0": pk_i, "y0": pk, "x1": t, "y1": pk}], None,
                dict(group_key=("lows", m_i), swing=pk / p1 - 1)))
        return best_per_anchor(out)


class TripleBottom(Detector):
    name = "triple-bottom"
    display = "Triple Bottom"
    category = "reversal"
    min_bars = 50
    defaults = dict(_SWING, tol_pct=0.03, tol_atr=1.0, min_gap=5, max_span=120, max_wait=40, inval_pct=0.015)
    definition = ("Three consecutive significant swing lows within tolerance, >=5 bars apart over <=120 bars, "
                  "each separated by a rally of >=4% / 2 ATR. Resistance = the higher of the two rally peaks. "
                  "Forming while the third low develops; awaiting breakout once it is a confirmed swing low; "
                  "confirmed on a close above resistance; invalidated by a close >1.5% under the lows.")

    def detect(self, v: View, p) -> list[Candidate]:
        t = v.t
        zz = v.zigzag(lo=t - (p["max_span"] + p["max_wait"] + 30), thr_pct=p["swing_pct"], thr_atr=p["swing_atr"])
        l, c = v.l, v.c
        out: list[Candidate] = []
        for k in range(len(zz) - 3):
            if [x[2] for x in zz[k : k + 4]] != ["L", "H", "L", "H"]:
                continue
            (i1, p1, _), (k1, h1, _), (i2, p2, _), (k2, h2, _) = zz[k : k + 4]
            tol = v.tol(p["tol_pct"], p["tol_atr"], i1)
            if i2 - i1 < p["min_gap"] or abs(p2 - p1) / min(p1, p2) > tol:
                continue
            res_lvl = max(h1, h2)
            base = [(i1, p1, "low 1"), (k1, h1, "rebound 1"), (i2, p2, "low 2"), (k2, h2, "rebound 2")]
            lines = [{"label": "resistance", "x0": k1, "y0": res_lvl, "x1": t, "y1": res_lvl}]
            if k + 4 < len(zz) and zz[k + 4][2] == "L":  # complete: third low is a confirmed swing
                i3, p3, _ = zz[k + 4]
                if i3 - i2 < p["min_gap"] or i3 - i1 > p["max_span"] or max(p1, p2, p3) / min(p1, p2, p3) - 1 > tol:
                    continue
                low = min(p1, p2, p3)
                inval = low * (1 - p["inval_pct"])
                r = _status_after(v, i3, low, lambda i: res_lvl, inval, p["max_wait"])
                if r is None:
                    continue
                st, why = r
                out.append(Candidate(
                    self.name, BULLISH, i1, st, i1, t if st != INVALIDATED else i3, res_lvl, inval,
                    base + [(i3, p3, "low 3")], lines, why, dict(group_key=("lows", i3))))
                continue
            if k + 3 != len(zz) - 1 or t - i1 > p["max_span"]:
                continue
            seg = l[k2 + 1 : t + 1]
            if not seg.size:
                continue
            m_i = k2 + 1 + int(np.argmin(seg))
            m = float(l[m_i])
            if m_i - i2 < p["min_gap"] or max(p1, p2, m) / min(p1, p2, m) - 1 > tol or c[t] < m:
                continue
            out.append(Candidate(
                self.name, BULLISH, i1, FORMING, i1, t, res_lvl, min(p1, p2, m) * (1 - p["inval_pct"]),
                base + [(m_i, m, "low 3 (developing)")], lines, None, dict(group_key=("lows", m_i))))
        return best_per_anchor(out)


class InverseHeadShoulders(Detector):
    name = "inverse-head-and-shoulders"
    display = "Inverse Head & Shoulders"
    category = "reversal"
    min_bars = 60
    defaults = dict(_SWING, shoulder_tol=0.12, shoulder_atr=3.0, head_pct=0.03, head_atr=1.5, min_leg=4,
                    max_span=160, max_wait=40)
    definition = ("Five consecutive significant swings: left trough, peak, a deeper head, peak, and a higher right "
                  "trough of similar depth to the left (within a volatility-scaled tolerance). Neckline = line "
                  "through the two peaks. Forming while the right shoulder develops; awaiting breakout once it is "
                  "a confirmed swing low; confirmed on a close above the neckline; invalidated by a close below "
                  "the head.")

    def detect(self, v: View, p) -> list[Candidate]:
        t = v.t
        zz = v.zigzag(lo=t - (p["max_span"] + p["max_wait"]), thr_pct=p["swing_pct"], thr_atr=p["swing_atr"])
        l, c = v.l, v.c
        out: list[Candidate] = []
        for k in range(len(zz) - 3):
            if [x[2] for x in zz[k : k + 4]] != ["L", "H", "L", "H"]:
                continue
            (ia, pa, _), (k1, h1, _), (ib, pb, _), (k2, h2, _) = zz[k : k + 4]
            if ib - ia < p["min_leg"] or k2 - ib < p["min_leg"]:
                continue
            head_gap = v.tol(p["head_pct"], p["head_atr"], ib)
            if pb > pa * (1 - head_gap):
                continue  # the head must be clearly deeper than the left shoulder
            sh_tol = v.tol(p["shoulder_tol"], p["shoulder_atr"], ia)
            m, bb = fit_line([k1, k2], [h1, h2])
            nl = lambda i, m=m, bb=bb: m * i + bb
            base = [(ia, pa, "left shoulder"), (k1, h1, "peak 1"), (ib, pb, "head"), (k2, h2, "peak 2")]
            if k + 4 < len(zz) and zz[k + 4][2] == "L":
                ic, pc, _ = zz[k + 4]
                if ic - k2 < p["min_leg"] or ic - ia > p["max_span"]:
                    continue
                if pc <= pb * (1 + head_gap) or abs(pc - pa) / pa > sh_tol:
                    continue
                r = _status_after(v, ic, pb, nl, pb, p["max_wait"])
                if r is None:
                    continue
                st, why = r
                out.append(Candidate(
                    self.name, BULLISH, ia, st, ia, t if st != INVALIDATED else ic, nl(t), pb,
                    base + [(ic, pc, "right shoulder")],
                    [{"label": "neckline", "x0": k1, "y0": nl(k1), "x1": t, "y1": nl(t)}], why))
                continue
            if k + 3 != len(zz) - 1 or t - ia > p["max_span"]:
                continue
            seg = l[k2 + 1 : t + 1]
            if not seg.size:
                continue
            m_i = k2 + 1 + int(np.argmin(seg))
            mv = float(l[m_i])
            if mv <= pb * (1 + head_gap) or abs(mv - pa) / pa > sh_tol or c[t] < mv:
                continue
            out.append(Candidate(
                self.name, BULLISH, ia, FORMING, ia, t, nl(t), pb, base + [(m_i, mv, "right shoulder (developing)")],
                [{"label": "neckline", "x0": k1, "y0": nl(k1), "x1": t, "y1": nl(t)}], None))
        return best_per_anchor(out)


DOUBLE_BOTTOM = DoubleBottom()
TRIPLE_BOTTOM = TripleBottom()
INV_HS = InverseHeadShoulders()
DETECTORS = [
    DOUBLE_BOTTOM,
    MirrorDetector(DOUBLE_BOTTOM, "double-top", "Double Top",
                   "Two consecutive significant swing highs near the same resistance with a pullback between; "
                   "confirmed on a close below the intervening swing low; invalidated by a decisive close above "
                   "the highs."),
    TRIPLE_BOTTOM,
    MirrorDetector(TRIPLE_BOTTOM, "triple-top", "Triple Top",
                   "Three consecutive swing highs around a common resistance zone; confirmed on a close below the "
                   "support formed by the intervening lows."),
    INV_HS,
    MirrorDetector(INV_HS, "head-and-shoulders", "Head & Shoulders",
                   "Left shoulder, higher head, right shoulder of similar height; neckline through the two "
                   "troughs; confirmed on a close below the neckline."),
]
