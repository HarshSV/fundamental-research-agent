"""Liquidity / volume / institutional-style patterns: Order Blocks, Pocket Pivot, Undercut & Rally,
Shakeout, Wyckoff Spring (+ Upthrust mirror).

Undercut & Rally, Shakeout and Wyckoff Spring all involve a move below support and a reclaim. They
differ in CONTEXT and are ranked so one event is only counted once (registry GROUPS, keyed on the
undercut bar):

  Wyckoff Spring     support belongs to an established trading range (>=2 touches of support AND of
                     resistance, range >=6% tall); small penetration; reclaim within 3 bars; confirmed
                     only with follow-through above the spring bar's high.
  Shakeout           support = the low of a tight 20-bar consolidation; a >=1.5% undercut on >=1.5x average
                     volume; recovered within 2 bars.
  Undercut & Rally   the general case: any confirmed swing low is undercut by >=0.2% and reclaimed within 5
                     bars; confirmed when price also closes above the undercut bar's high (the rally).
"""
from __future__ import annotations

import numpy as np

from ..core import (
    AWAITING, BEARISH, BULLISH, CONFIRMED, FORMING, INVALIDATED, Bidirectional, Candidate, Detector,
    MirrorDetector, View, best_per_anchor, vol_known,
)


# -- order blocks ---------------------------------------------------------------------------
class OrderBlock(Detector):
    name = "order-block"
    display = "Order Blocks"
    category = "structure"
    maturity = "experimental"
    min_bars = 40
    defaults = dict(lookback=100, leg_max=5, disp_atr=2.0, forming_bars=3, inval_buffer=0.0)
    definition = ("Demand zone (bullish) = the last down-close candle before a displacement leg (>=2 ATR within 5 "
                  "bars) that CLOSES above the latest confirmed swing high. Forming on the displacement bar before "
                  "the structure break; confirmed on the break; retests (a bar trading into the zone and holding) "
                  "are counted; invalidated by a CLOSE below the zone low (a wick does not count). It is a "
                  "price-structure zone only - nothing here shows institutional participation.")

    def detect(self, v: View, p) -> list[Candidate]:
        t = v.t
        o, h, l, c = v.o, v.h, v.l, v.c
        out: list[Candidate] = []
        highs = v.swing_highs(lo=t - p["lookback"] - 40)
        seen_k: set[int] = set()
        for j in range(max(p["leg_max"] + 1, t - p["lookback"]), t + 1):
            atrp = v.atrp(j)
            if atrp != atrp:
                continue
            # the last down-close candle before the leg
            k = next((i for i in range(j - 1, max(j - p["leg_max"] - 1, 0), -1) if c[i] < o[i]), None)
            if k is None or k in seen_k:
                continue
            if (c[j] - l[k]) < p["disp_atr"] * v.atr[j] or c[j] <= o[j]:
                continue
            prior = [(i, q) for i, q in highs if i < k and i <= j - v.s.wing]
            if not prior:
                continue
            hi_i, hi_p = prior[-1]
            first_break = next((i for i in range(k + 1, j + 1) if c[i] > hi_p), None)
            zlo, zhi = float(l[k]), float(h[k])
            piv = [(hi_i, hi_p, "swing high"), (k, zhi, "zone candle")]
            lines = [{"label": "zone high", "x0": k, "y0": zhi, "x1": t, "y1": zhi},
                     {"label": "zone low", "x0": k, "y0": zlo, "x1": t, "y1": zlo}]
            if first_break is None:
                if t - j <= p["forming_bars"] and c[t] <= hi_p:
                    seen_k.add(k)
                    out.append(Candidate(self.name, BULLISH, k, FORMING, k, t, hi_p, zlo, piv, lines, None,
                                         dict(zone=(zlo, zhi), group_key=None)))
                continue
            seen_k.add(k)
            if (c[first_break : t + 1] < zlo * (1 - p["inval_buffer"])).any() and first_break <= t:
                bad = next(i for i in range(first_break, t + 1) if c[i] < zlo * (1 - p["inval_buffer"]))
                if bad == t:
                    out.append(Candidate(self.name, BULLISH, k, INVALIDATED, k, t, hi_p, zlo, piv, lines,
                                         "closed_below_zone", dict(zone=(zlo, zhi), track=True)))
                continue
            retests = [i for i in range(first_break + 1, t + 1) if l[i] <= zhi and c[i] >= zlo]
            if first_break == t or t - first_break <= p["lookback"]:
                out.append(Candidate(self.name, BULLISH, k, CONFIRMED, k, t, hi_p, zlo, piv, lines, None,
                                     dict(zone=(zlo, zhi), broke_at=int(first_break), retests=len(retests),
                                          last_retest=int(retests[-1]) if retests else None, track=True)))
        return best_per_anchor(out)


# -- pocket pivot ---------------------------------------------------------------------------
class PocketPivot(Detector):
    name = "pocket-pivot"
    display = "Pocket Pivot"
    category = "specialized"
    min_bars = 60
    defaults = dict(vol_window=10, trend_sma=50, upper_half=0.5, inval_bars=5)
    definition = ("An up-close bar (close > prior close) in an uptrend (close above its 10- and 50-bar averages) "
                  "closing in the upper half of its range, whose volume exceeds the HIGHEST down-day volume of the "
                  "previous 10 bars (at least one down day is required; unknown volume = no signal). It is a "
                  "single-bar signal, confirmed on that bar; invalidated by a close below the pivot bar's low "
                  "within 5 bars.")

    def detect(self, v: View, p) -> list[Candidate]:
        t = v.t
        c, l, h, vol = v.c, v.l, v.h, v.v
        out: list[Candidate] = []
        for j in range(max(p["vol_window"] + 1, t - p["inval_bars"]), t + 1):
            if not (c[j] > c[j - 1]):
                continue
            win = range(j - p["vol_window"], j)
            vols = vol[list(win)]
            if np.isnan(vols).any() or np.isnan(vol[j]):
                continue
            down = [vol[i] for i in win if c[i] < c[i - 1]]
            if not down or vol[j] <= max(down):
                continue
            sma10 = c[j - 9 : j + 1].mean()
            sma50 = c[j - p["trend_sma"] + 1 : j + 1].mean() if j + 1 >= p["trend_sma"] else None
            if c[j] < sma10 or (sma50 is not None and c[j] < sma50):
                continue
            if h[j] == l[j] or (c[j] - l[j]) / (h[j] - l[j]) < p["upper_half"]:
                continue
            piv = [(j, float(c[j]), "pivot bar")]
            lines = [{"label": "pivot low", "x0": j, "y0": float(l[j]), "x1": t, "y1": float(l[j])}]
            bad = next((i for i in range(j + 1, t + 1) if c[i] < l[j]), None)
            if bad is not None:
                if bad == t:
                    out.append(Candidate(self.name, BULLISH, j, INVALIDATED, j, t, None, float(l[j]), piv, lines,
                                         "closed_below_pivot_low", dict(track=True)))
                continue
            out.append(Candidate(self.name, BULLISH, j, CONFIRMED, j, t, None, float(l[j]), piv, lines, None,
                                 dict(track=True, vol_ratio=float(vol[j] / max(down)))))
        return out


# -- undercut family ------------------------------------------------------------------------
def _first_under(l: np.ndarray, level: float, after: int, upto: int) -> int | None:
    w = np.flatnonzero(l[after + 1 : upto + 1] < level)
    return int(w[0]) + after + 1 if len(w) else None


class UndercutRally(Detector):
    name = "undercut-and-rally"
    display = "Undercut & Rally"
    category = "specialized"
    min_bars = 40
    defaults = dict(min_age=5, max_age=60, undercut=0.002, undercut_atr=0.1, reclaim_bars=5)
    definition = ("A confirmed swing low (5-60 bars old) is undercut by >=0.2% (or 0.1 ATR) and reclaimed. Forming "
                  "while price is back below the level; awaiting breakout once a close is back above the level; "
                  "confirmed when a close is above the undercut bar's high (the rally); invalidated if no "
                  "reclaim within 5 bars. Ranks below Shakeout and Wyckoff Spring.")

    def detect(self, v: View, p) -> list[Candidate]:
        t = v.t
        l, h, c = v.l, v.h, v.c
        out: list[Candidate] = []
        for si, sp in v.swing_lows(lo=t - p["max_age"] - p["reclaim_bars"] - 5):
            if t - si < p["min_age"]:
                continue
            thr = sp * (1 - v.tol(p["undercut"], p["undercut_atr"], si))
            u = _first_under(l, thr, si, t)
            if u is None or t - u > p["reclaim_bars"] + 5:
                continue
            seg = slice(u, t + 1)
            reclaim = next((i for i in range(u, t + 1) if c[i] >= sp), None)
            hi_u = float(h[u : (reclaim if reclaim is not None else t) + 1].max())
            low_u = float(l[u : t + 1].min())
            piv = [(si, sp, "support"), (u, float(l[u]), "undercut")]
            lines = [{"label": "support", "x0": si, "y0": sp, "x1": t, "y1": sp}]
            mk = lambda st, why=None: Candidate(
                self.name, BULLISH, u, st, si, t, hi_u, low_u, piv, lines, why, dict(group_key=("undercut", u)))
            if reclaim is None:
                out.append(mk(INVALIDATED, "no_reclaim") if t - u >= p["reclaim_bars"] else mk(FORMING))
            elif reclaim - u > p["reclaim_bars"]:
                continue
            else:
                rally = next((i for i in range(reclaim, t + 1) if c[i] > hi_u), None)
                if rally is None:
                    out.append(mk(AWAITING))
                elif rally == t:
                    out.append(mk(CONFIRMED))
        return best_per_anchor(out)


class Shakeout(Detector):
    name = "shakeout"
    display = "Shakeout"
    category = "specialized"
    min_bars = 40
    defaults = dict(base_len=20, base_max_depth=0.15, undercut=0.015, vol_mult=1.5, recover_bars=2)
    definition = ("Support = the low of a tight 20-bar consolidation (<=15% range). A rapid undercut of >=1.5% on "
                  ">=1.5x its average volume (volume must be known), then recovery back above the level within 2 "
                  "bars. Forming while still below; confirmed on the recovery close; invalidated if not recovered "
                  "in 2 bars. Differs from Undercut & Rally by needing the tight base, the deeper undercut and "
                  "the volume spike.")

    def detect(self, v: View, p) -> list[Candidate]:
        t = v.t
        h, l, c, vol = v.h, v.l, v.c, v.v
        out: list[Candidate] = []
        if not vol_known(vol):
            return []
        for u in range(max(p["base_len"] + 1, t - p["recover_bars"]), t + 1):
            b0 = u - p["base_len"]
            base_hi, base_lo = float(h[b0:u].max()), float(l[b0:u].min())
            if (base_hi - base_lo) / base_hi > p["base_max_depth"]:
                continue
            if l[u] > base_lo * (1 - p["undercut"]):
                continue
            avg = float(vol[b0:u].mean())
            if avg <= 0 or vol[u] < p["vol_mult"] * avg:
                continue
            rec = next((i for i in range(u, t + 1) if c[i] >= base_lo), None)
            piv = [(int(b0 + np.argmin(l[b0:u])), base_lo, "base low"), (u, float(l[u]), "undercut")]
            lines = [{"label": "base low", "x0": b0, "y0": base_lo, "x1": t, "y1": base_lo}]
            mk = lambda st, why=None: Candidate(
                self.name, BULLISH, u, st, b0, t, base_hi, float(l[u]), piv, lines, why,
                dict(group_key=("undercut", u), vol_ratio=float(vol[u] / avg)))
            if rec is None:
                out.append(mk(INVALIDATED, "not_recovered_in_time") if t - u >= p["recover_bars"] else mk(FORMING))
            elif rec - u <= p["recover_bars"] and rec == t:
                out.append(mk(CONFIRMED))
            elif rec - u <= p["recover_bars"] and rec < t:
                continue  # confirmed on an earlier bar
        return best_per_anchor(out)


class WyckoffSpring(Detector):
    name = "wyckoff-spring"
    display = "Wyckoff Spring"
    category = "specialized"
    maturity = "experimental"
    min_bars = 50
    defaults = dict(windows=(80, 60, 40, 25), touch_tol=0.015, min_height=0.06, pen_min=0.002, pen_max=0.03,
                    reclaim_bars=3, stay_inside=0.01)
    definition = ("An established trading range (>=2 swing-low touches of support and >=2 swing-high touches of "
                  "resistance, >=6% tall, price staying inside it), a small downside penetration of support "
                  "(0.2%-3%) and a reclaim within 3 bars. Forming while below support; awaiting breakout once "
                  "reclaimed; confirmed only on FOLLOW-THROUGH (a close above the spring bar's high); invalidated "
                  "if not reclaimed in 3 bars. A bare support breach is never enough. Low-reliability, "
                  "experimental.")

    def detect(self, v: View, p) -> list[Candidate]:
        t = v.t
        h, l, c = v.h, v.l, v.c
        out: list[Candidate] = []
        for u in range(max(30, t - p["reclaim_bars"] - 1), t + 1):
            for W in p["windows"]:
                w0 = u - W
                if w0 < 0:
                    continue
                lows = [(i, q) for i, q in v.swing_lows(lo=w0) if i < u - v.s.wing]
                highs = [(i, q) for i, q in v.swing_highs(lo=w0) if i < u - v.s.wing]
                if len(lows) < 2 or len(highs) < 2:
                    continue
                sup = min(q for _, q in lows)
                res = max(q for _, q in highs)
                near_s = [i for i, q in lows if (q - sup) / sup <= p["touch_tol"]]
                near_r = [i for i, q in highs if (res - q) / res <= p["touch_tol"]]
                if len(near_s) < 2 or len(near_r) < 2 or (res - sup) / sup < p["min_height"]:
                    continue
                if (c[w0:u] < sup * (1 - p["stay_inside"])).any() or (c[w0:u] > res * (1 + p["stay_inside"])).any():
                    continue
                if not (sup * (1 - p["pen_max"]) <= l[u] < sup * (1 - p["pen_min"])):
                    continue
                if (l[w0:u] < sup * (1 - p["pen_min"])).any():
                    continue  # support already broken before this bar
                rec = next((i for i in range(u, t + 1) if c[i] >= sup), None)
                hi_u = float(h[u : (rec if rec is not None else t) + 1].max())
                piv = [(near_s[0], sup, "support"), (near_r[0], res, "resistance"), (u, float(l[u]), "spring")]
                lines = [{"label": "support", "x0": w0, "y0": sup, "x1": t, "y1": sup},
                         {"label": "resistance", "x0": w0, "y0": res, "x1": t, "y1": res}]
                mk = lambda st, why=None: Candidate(
                    self.name, BULLISH, u, st, near_s[0], t, hi_u, float(l[u:t + 1].min()), piv, lines, why,
                    dict(group_key=("undercut", u), range_height=(res - sup) / sup))
                if rec is None:
                    out.append(mk(INVALIDATED, "not_reclaimed_in_time") if t - u >= p["reclaim_bars"] else mk(FORMING))
                elif rec - u > p["reclaim_bars"]:
                    pass
                else:
                    follow = next((i for i in range(rec, t + 1) if c[i] > hi_u), None)
                    if follow is None:
                        out.append(mk(AWAITING))
                    elif follow == t:
                        out.append(mk(CONFIRMED))
                break  # longest valid range for this bar
        return best_per_anchor(out)


ORDER_BLOCK = Bidirectional(OrderBlock(), "order-block", "Order Blocks")
SPRING = WyckoffSpring()
DETECTORS = [
    ORDER_BLOCK,
    PocketPivot(),
    UndercutRally(),
    Shakeout(),
    SPRING,
    MirrorDetector(SPRING, "wyckoff-upthrust", "Wyckoff Upthrust",
                   "Mirror of Wyckoff Spring: in an established trading range, a small upside penetration of "
                   "resistance that closes back inside within 3 bars; confirmed only on follow-through (a close "
                   "below the upthrust bar's low); invalidated if price does not return in time."),
]
