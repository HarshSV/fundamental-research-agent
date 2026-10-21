"""Shared building blocks for the Navrist pattern agent.

Conventions
- A `Series` holds OHLCV arrays for ONE symbol/timeframe, oldest first, COMPLETED bars only.
- A `View(series, t)` is the series as it was known right after bar `t` closed. Detectors only
  ever receive a View, so they cannot read future bars. Swing points are exposed only once
  `wing` further bars have closed (their confirmation lag) - no look-ahead.
- Unknown volume is NaN (never 0). A detector that needs volume treats NaN as "cannot evaluate"
  and emits nothing for that rule.
- Detectors return `Candidate`s; the engine tracks them across bars as occurrences.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

FORMING = "forming"
AWAITING = "awaiting_breakout"
CONFIRMED = "confirmed"
INVALIDATED = "invalidated"
STATUSES = (FORMING, AWAITING, CONFIRMED, INVALIDATED)
ACTIVE = (FORMING, AWAITING)
TERMINAL = (CONFIRMED, INVALIDATED)

BULLISH = "bullish"
BEARISH = "bearish"

DETECTOR_VERSION = "1.0.0"


def slug(name: str) -> str:
    return (
        name.lower().replace("&", "and").replace("(", "").replace(")", "")
        .replace("-like", "").replace(" ", "-")
    )


def _atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14) -> np.ndarray:
    """Wilder ATR; NaN until `n` true ranges exist."""
    m = len(c)
    out = np.full(m, np.nan)
    if m <= n:
        return out
    tr = np.empty(m)
    tr[0] = h[0] - l[0]
    prev = c[:-1]
    tr[1:] = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - prev), np.abs(l[1:] - prev)))
    out[n] = tr[1 : n + 1].mean()
    for i in range(n + 1, m):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


class Series:
    def __init__(self, t, o, h, l, c, v, timeframe: str = "1d", wing: int = 3, meta: dict | None = None):
        self.t = np.asarray(t, dtype=np.int64)
        self.o, self.h, self.l, self.c = (np.asarray(x, dtype=float) for x in (o, h, l, c))
        self.v = np.asarray(v, dtype=float)
        self.n = len(self.t)
        self.timeframe = timeframe
        self.wing = wing
        self.meta = meta or {}
        self.atr = _atr(self.h, self.l, self.c)
        self._piv: dict[int, tuple[list[int], list[int]]] = {}
        self._mirror: "Series | None" = None
        self.cache: dict = {}  # per-bar memo shared by detectors (e.g. trendline analysis)

    # -- swing pivots (precomputed once; exposed through View only after their lag) ----------
    def pivots(self, wing: int) -> tuple[list[int], list[int]]:
        if wing not in self._piv:
            hi, lo = [], []
            for i in range(wing, self.n - wing):
                if self.h[i] >= self.h[i - wing : i].max() and self.h[i] > self.h[i + 1 : i + wing + 1].max():
                    hi.append(i)
                if self.l[i] <= self.l[i - wing : i].min() and self.l[i] < self.l[i + 1 : i + wing + 1].min():
                    lo.append(i)
            self._piv[wing] = (hi, lo)
        return self._piv[wing]

    def mirrored(self) -> "Series":
        """Multiplicative price-inverted twin (p -> K/p): bullish detectors run on it find the bearish
        mirror pattern. K/p keeps every price positive and makes percentage moves symmetric (an x% rise
        becomes about an x% fall), which negation would not - all the detectors' % rules assume positive
        prices. Highs and lows swap roles. `K` converts levels back: p = K / p'."""
        if self._mirror is None:
            K = float(np.mean(self.c)) ** 2
            m = Series(self.t, K / self.o, K / self.l, K / self.h, K / self.c, self.v, self.timeframe, self.wing,
                       self.meta)
            m.K = K
            m._mirror = self
            self._mirror = m
        return self._mirror


class View:
    """The series as known at the close of bar `t`."""

    def __init__(self, s: Series, t: int):
        self.s = s
        self.t = t
        self.n = t + 1
        self.timeframe = s.timeframe
        self.meta = s.meta

    @property
    def tm(self): return self.s.t[: self.n]
    @property
    def o(self): return self.s.o[: self.n]
    @property
    def h(self): return self.s.h[: self.n]
    @property
    def l(self): return self.s.l[: self.n]
    @property
    def c(self): return self.s.c[: self.n]
    @property
    def v(self): return self.s.v[: self.n]
    @property
    def atr(self): return self.s.atr[: self.n]

    @property
    def last(self) -> float:
        return float(self.s.c[self.t])

    def atrp(self, i: int | None = None) -> float:
        """ATR as a fraction of price at bar i (default: now); NaN when unknown."""
        i = self.t if i is None else i
        a = self.s.atr[i]
        return float(a / self.s.c[i]) if a == a and self.s.c[i] else float("nan")

    def tol(self, base: float, atr_mult: float, i: int | None = None) -> float:
        """Volatility-aware tolerance: never below `base`, widened by ATR when ATR is known."""
        a = self.atrp(i)
        return max(base, atr_mult * a) if a == a else base

    def swing_highs(self, wing: int | None = None, lo: int = 0) -> list[tuple[int, float]]:
        return self._swings(0, wing, lo)

    def swing_lows(self, wing: int | None = None, lo: int = 0) -> list[tuple[int, float]]:
        return self._swings(1, wing, lo)

    def _swings(self, which: int, wing: int | None, lo: int) -> list[tuple[int, float]]:
        wing = wing or self.s.wing
        idxs = self.s.pivots(wing)[which]
        a = bisect.bisect_left(idxs, max(lo, 0))
        b = bisect.bisect_right(idxs, self.t - wing)  # confirmed only after `wing` later bars closed
        arr = self.s.h if which == 0 else self.s.l
        return [(i, float(arr[i])) for i in idxs[a:b]]

    def zigzag(self, lo: int = 0, thr_pct: float = 0.04, thr_atr: float = 2.0,
               wing: int | None = None) -> list[tuple[int, float, str]]:
        """Significant, alternating swing pivots [(idx, price, 'H'|'L')], oldest first.

        Built only from CONFIRMED raw swings (so no look-ahead). A leg between consecutive pivots
        must be at least max(thr_pct, thr_atr x ATR%) of price, otherwise the small counter-swing is
        ignored; two same-kind pivots in a row keep the more extreme one. This removes day-to-day
        micro-swings so 'consecutive lows' means consecutive MEANINGFUL lows."""
        wing = wing or self.s.wing
        key = ("zz", self.t, lo, thr_pct, thr_atr, wing)
        hit = self.s.cache.get(key)
        if hit is not None:
            return hit
        pts = sorted([(i, q, "H") for i, q in self.swing_highs(wing, lo)] +
                     [(i, q, "L") for i, q in self.swing_lows(wing, lo)])
        out: list[tuple[int, float, str]] = []
        for pt in pts:
            if not out:
                out.append(pt)
                continue
            last = out[-1]
            if pt[2] == last[2]:
                if (pt[2] == "H" and pt[1] > last[1]) or (pt[2] == "L" and pt[1] < last[1]):
                    out[-1] = pt
                continue
            thr = max(thr_pct, thr_atr * (self.atrp(pt[0]) if self.atrp(pt[0]) == self.atrp(pt[0]) else 0.0))
            if abs(pt[1] - last[1]) / last[1] >= thr:
                out.append(pt)
        self.s.cache[key] = out
        return out

    def mirrored(self) -> "View":
        return View(self.s.mirrored(), self.t)


@dataclass
class Candidate:
    pattern: str
    direction: str | None
    anchor: int  # bar index that identifies this formation across bars (e.g. its first pivot)
    status: str
    start: int
    end: int
    breakout_level: float | None = None
    invalidation_level: float | None = None
    pivots: list[tuple[int, float, str]] = field(default_factory=list)
    lines: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def unmirror(self, pattern: str, K: float) -> "Candidate":
        """Convert a candidate found on the mirrored series back to real prices (p = K / p')."""
        inv = lambda x: None if x is None else K / x
        flip = {BULLISH: BEARISH, BEARISH: BULLISH}
        meta = dict(self.meta)
        for key in ("zone", "prz"):  # (low, high) price bands swap order under inversion
            if isinstance(meta.get(key), tuple):
                a, b = (K / x for x in meta[key])
                meta[key] = (min(a, b), max(a, b))
        return Candidate(
            pattern=pattern,
            direction=flip.get(self.direction, self.direction),
            anchor=self.anchor,
            status=self.status,
            start=self.start,
            end=self.end,
            breakout_level=inv(self.breakout_level),
            invalidation_level=inv(self.invalidation_level),
            pivots=[(i, K / p, lab) for i, p, lab in self.pivots],
            lines=[{**ln, "y0": K / ln["y0"], "y1": K / ln["y1"]} for ln in self.lines],
            reason=self.reason,
            meta=meta,
        )


class Detector:
    """Base class. Subclasses set `name`/`display`/`min_bars` and implement `detect`."""

    name = ""
    display = ""
    min_bars = 40
    category = "reversal"
    maturity = "standard"  # 'experimental' = low-reliability definition, shown as such
    defaults: dict[str, Any] = {}
    definition = ""
    timeframes: tuple[str, ...] | None = None  # None = any

    def params(self, cfg: dict | None) -> dict:
        return {**self.defaults, **((cfg or {}).get(self.name) or {})}

    def detect(self, v: View, p: dict) -> list[Candidate]:  # pragma: no cover - interface
        raise NotImplementedError

    def supports(self, timeframe: str) -> bool:
        return self.timeframes is None or timeframe in self.timeframes


class MirrorDetector(Detector):
    """Bearish twin of a bullish detector: runs the base on the price-inverted view."""

    def __init__(self, base: Detector, name: str, display: str, definition: str = ""):
        self.base = base
        self.name = name
        self.display = display
        self.min_bars = base.min_bars
        self.category = base.category
        self.maturity = base.maturity
        self.defaults = base.defaults
        self.timeframes = base.timeframes
        self.definition = definition or f"Mirror of {base.display}"

    def params(self, cfg):
        return {**self.defaults, **((cfg or {}).get(self.base.name) or {}), **((cfg or {}).get(self.name) or {})}

    def detect(self, v: View, p: dict) -> list[Candidate]:
        K = v.s.mirrored().K
        return [c.unmirror(self.name, K) for c in self.base.detect(v.mirrored(), p)]


class Bidirectional(Detector):
    """Runs a bullish-written detector on the series AND on its price-inverted twin, so a single
    pattern name (e.g. Flag) can appear in either direction, taken from the actual structure."""

    def __init__(self, base: Detector, name: str, display: str, definition: str = ""):
        self.base = base
        self.name = name
        self.display = display
        self.min_bars = base.min_bars
        self.category = base.category
        self.maturity = base.maturity
        self.defaults = base.defaults
        self.timeframes = base.timeframes
        self.definition = definition or base.definition

    def detect(self, v: View, p: dict) -> list[Candidate]:
        up = [c for c in self.base.detect(v, p)]
        for c in up:
            c.pattern = self.name
        K = v.s.mirrored().K
        down = [c.unmirror(self.name, K) for c in self.base.detect(v.mirrored(), p)]
        return up + down


_RANK = {INVALIDATED: 0, FORMING: 1, AWAITING: 2, CONFIRMED: 3}


def best_per_anchor(cands: list[Candidate]) -> list[Candidate]:
    """One candidate per (pattern, direction, anchor): the most advanced status wins, then the
    one that ends latest. Detectors that try several geometries use this to stay unambiguous."""
    best: dict[tuple, Candidate] = {}
    for c in cands:
        k = (c.pattern, c.direction, c.anchor)
        cur = best.get(k)
        if cur is None or (_RANK[c.status], c.end) > (_RANK[cur.status], cur.end):
            best[k] = c
    return list(best.values())


def first_idx_where(mask: np.ndarray, after: int) -> int | None:
    """First index > `after` where `mask` is True."""
    if after + 1 >= len(mask):
        return None
    w = np.flatnonzero(mask[after + 1 :])
    return int(w[0]) + after + 1 if len(w) else None


# -- small numeric helpers ---------------------------------------------------------------------
def fit_line(xs, ys) -> tuple[float, float]:
    """Least-squares line y = m*x + b."""
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    if len(xs) < 2 or xs.max() == xs.min():
        return 0.0, float(ys.mean()) if len(ys) else 0.0
    xm, ym = xs.mean(), ys.mean()
    dx = xs - xm
    m = float((dx * (ys - ym)).sum() / (dx * dx).sum())  # closed form: much cheaper than np.polyfit
    return m, float(ym - m * xm)


def line_y(m: float, b: float, x: float) -> float:
    return m * x + b


def pct(a: float, b: float) -> float:
    """(a-b)/b guarded against zero."""
    return (a - b) / b if b else float("nan")


def seg_max(arr: np.ndarray, a: int, b: int) -> float:
    return float(arr[a : b + 1].max())


def seg_min(arr: np.ndarray, a: int, b: int) -> float:
    return float(arr[a : b + 1].min())


def sma(c: np.ndarray, n: int, end: int | None = None) -> float | None:
    end = len(c) - 1 if end is None else end
    if end + 1 < n:
        return None
    return float(c[end - n + 1 : end + 1].mean())


def vol_known(v: np.ndarray) -> bool:
    return bool(len(v)) and not np.isnan(v).any()
