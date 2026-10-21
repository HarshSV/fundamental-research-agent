"""Bar-by-bar replay: runs every detector as of each completed bar and tracks each formation
(an *occurrence*) through Forming -> Awaiting breakout -> Confirmed / Invalidated.

Look-ahead safety: a detector at bar t only receives View(series, t). Because replay is
sequential and deterministic, re-running over a longer series reproduces the same history for
the earlier bars - which is what makes it safe to persist and to compare against live use.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np

from .core import (
    ACTIVE, CONFIRMED, INVALIDATED, TERMINAL, Candidate, Detector, Series, View,
)

log = logging.getLogger("patterns.engine")

LAPSE_BARS = 3  # an active formation whose structure stops matching for this many bars is invalidated
HORIZONS = (5, 15, 30)
FLAT_K = 0.5  # flat band = K * sigma * sqrt(horizon), sigma from the 60 bars before confirmation


@dataclass
class Occurrence:
    pattern: str
    direction: str | None
    anchor: int
    start: int
    end: int
    status: str
    first_seen: int
    updated: int
    detector: str
    maturity: str = "standard"
    category: str = ""
    confirmed_idx: int | None = None
    breakout_level: float | None = None
    invalidation_level: float | None = None
    pivots: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    reason: str | None = None
    meta: dict = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    absent: int = 0

    @property
    def key(self) -> tuple:
        return (self.pattern, self.direction, self.anchor)


@dataclass
class ReplayResult:
    occurrences: list[Occurrence]
    errors: dict[str, str]
    evaluated: dict[str, int]


def _snap(occ: Occurrence, t: int, price: float, reason: str | None = None) -> dict:
    return {
        "idx": t,
        "status": occ.status,
        "price": price,
        "breakout_level": occ.breakout_level,
        "invalidation_level": occ.invalidation_level,
        "reason": reason if reason is not None else occ.reason,
    }


OVERLAP_SUPPRESS = 0.5  # a new candidate covering >=50% of an existing same-pattern span is the SAME formation


def _overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> float:
    inter = min(a_end, b_end) - max(a_start, b_start)
    return max(0.0, inter) / max(1, min(a_end - a_start, b_end - b_start))


def _apply_groups(per_det: dict[str, list[Candidate]], groups: Iterable[tuple[str, ...]]):
    """Within an exclusive group (ordered by priority) a lower-priority candidate that describes
    the same formation (same `group_key`) as a higher-priority one is dropped. Returns the
    superseded (lower_name, group_key, winner_name) triples so existing occurrences can be closed."""
    superseded = []
    for group in groups:
        taken: dict[Any, str] = {}
        for name in group:
            for c in list(per_det.get(name, [])):
                gk = c.meta.get("group_key")
                if gk is None or c.status == INVALIDATED:
                    continue
                if gk in taken and taken[gk] != name:
                    per_det[name].remove(c)
                    superseded.append((name, gk, taken[gk]))
                else:
                    taken.setdefault(gk, name)
    return superseded


def replay(series: Series, detectors: list[Detector], cfg: dict | None = None,
           groups: Iterable[tuple[str, ...]] = ()) -> ReplayResult:
    occs: dict[tuple, Occurrence] = {}
    order: list[Occurrence] = []
    suppressed: set[tuple] = set()
    errors: dict[str, str] = {}
    evaluated: dict[str, int] = {d.name: 0 for d in detectors}
    close = series.c

    for t in range(series.n):
        v = View(series, t)
        per_det: dict[str, list[Candidate]] = {}
        ran: set[str] = set()
        for det in detectors:
            if t + 1 < det.min_bars or not det.supports(series.timeframe):
                continue
            ran.add(det.name)
            evaluated[det.name] += 1
            try:
                per_det[det.name] = det.detect(v, det.params(cfg)) or []
            except Exception as e:  # one broken detector must never stop the others
                errors.setdefault(det.name, f"{type(e).__name__}: {e}")
                per_det[det.name] = []

        superseded = _apply_groups(per_det, groups)
        by_name = {d.name: d for d in detectors}
        seen: set[tuple] = set()

        for name, cands in per_det.items():
            det = by_name[name]
            for c in cands:
                key = (c.pattern, c.direction, c.anchor)
                if key in suppressed:
                    continue
                seen.add(key)
                occ = occs.get(key)
                if occ is None:
                    if c.status == INVALIDATED:
                        continue  # never record a formation that we only ever saw as already dead
                    # one formation, one record: skip near-duplicates of an existing same-pattern occurrence
                    if any(o.pattern == c.pattern and o.direction == c.direction
                           and _overlap(o.start, o.end, c.start, c.end) >= OVERLAP_SUPPRESS for o in order):
                        suppressed.add(key)
                        continue
                    occ = Occurrence(
                        pattern=c.pattern, direction=c.direction, anchor=c.anchor, start=c.start, end=c.end,
                        status=c.status, first_seen=t, updated=t, detector=name, maturity=det.maturity,
                        category=det.category, breakout_level=c.breakout_level,
                        invalidation_level=c.invalidation_level, pivots=c.pivots, lines=c.lines,
                        reason=c.reason, meta=c.meta,
                    )
                    occs[key] = occ
                    order.append(occ)
                    if c.status == CONFIRMED:
                        occ.confirmed_idx = t
                    occ.history.append(_snap(occ, t, float(close[t])))
                    continue
                if occ.status in TERMINAL:
                    # A confirmed zone/signal can keep being tracked (retests, later invalidation) when the
                    # detector asks for it with meta['track']; confirmation itself is never rewritten.
                    if occ.status == CONFIRMED and c.meta.get("track"):
                        occ.meta = c.meta
                        occ.updated = t
                        if c.status == INVALIDATED:
                            occ.status, occ.reason = INVALIDATED, c.reason
                            occ.history.append(_snap(occ, t, float(close[t])))
                    continue
                occ.absent = 0
                occ.updated = t
                occ.start, occ.end = c.start, c.end
                occ.breakout_level, occ.invalidation_level = c.breakout_level, c.invalidation_level
                occ.pivots, occ.lines, occ.meta = c.pivots, c.lines, c.meta
                if c.status != occ.status:
                    occ.status = c.status
                    occ.reason = c.reason
                    if c.status == CONFIRMED:
                        occ.confirmed_idx = t
                    occ.history.append(_snap(occ, t, float(close[t])))

        for lower, gk, winner in superseded:
            for occ in order:
                if occ.pattern == lower and occ.status in ACTIVE and occ.meta.get("group_key") == gk:
                    occ.status, occ.updated, occ.reason = INVALIDATED, t, f"superseded_by:{winner}"
                    occ.history.append(_snap(occ, t, float(close[t])))

        for occ in order:
            if occ.status in ACTIVE and occ.key not in seen and occ.detector in ran:
                occ.absent += 1
                if occ.absent >= LAPSE_BARS:
                    occ.status, occ.updated, occ.reason = INVALIDATED, t, "structure_lost"
                    occ.history.append(_snap(occ, t, float(close[t])))

    return ReplayResult(order, errors, evaluated)


# -- realised outcomes (kept strictly separate from the pattern's status / expected direction) ---
def outcomes(series: Series, occ: Occurrence, horizons=HORIZONS, k: float = FLAT_K) -> dict[str, dict] | None:
    """Forward move after the CONFIRMING bar's close, per horizon in bars. None until confirmed.
    state: positive/negative/flat (vs a volatility band), pending (future bars not yet printed),
    not_evaluable (too little history to size the band). Never zero-filled."""
    i = occ.confirmed_idx
    if i is None:
        return None
    c = series.c
    lo = max(1, i - 60)
    rets = np.diff(np.log(c[lo - 1 : i + 1])) if i - lo >= 19 else None
    sigma = float(rets.std(ddof=1)) if rets is not None and len(rets) >= 20 else None
    out: dict[str, dict] = {}
    for h in horizons:
        j = i + h
        if j > series.n - 1:
            out[str(h)] = {"state": "pending", "ret": None, "band": None}
            continue
        ret = float(c[j] / c[i] - 1.0)
        if sigma is None:
            out[str(h)] = {"state": "not_evaluable", "ret": ret, "band": None}
            continue
        band = k * sigma * math.sqrt(h)
        state = "positive" if ret > band else "negative" if ret < -band else "flat"
        out[str(h)] = {"state": state, "ret": ret, "band": band}
    return out


def to_dict(series: Series, occ: Occurrence, with_history: bool = True) -> dict:
    ts = lambda i: int(series.t[min(max(i, 0), series.n - 1)])
    d = {
        "pattern": occ.pattern,
        "direction": occ.direction,
        "category": occ.category,
        "maturity": occ.maturity,
        "timeframe": series.timeframe,
        "status": occ.status,
        "reason": occ.reason,
        "anchor_ts": ts(occ.anchor),
        "start_ts": ts(occ.start),
        "end_ts": ts(occ.end),
        "first_seen_ts": ts(occ.first_seen),
        "updated_ts": ts(occ.updated),
        "confirmed_ts": ts(occ.confirmed_idx) if occ.confirmed_idx is not None else None,
        "confirmed_price": float(series.c[occ.confirmed_idx]) if occ.confirmed_idx is not None else None,
        "breakout_level": occ.breakout_level,
        "invalidation_level": occ.invalidation_level,
        "pivots": [{"ts": ts(i), "price": p, "label": lab} for i, p, lab in occ.pivots],
        "lines": [
            {"label": ln.get("label"), "ts0": ts(ln["x0"]), "y0": ln["y0"], "ts1": ts(ln["x1"]), "y1": ln["y1"]}
            for ln in occ.lines
        ],
        "meta": {k: v for k, v in occ.meta.items() if k != "group_key"},
        "outcomes": outcomes(series, occ),
    }
    if with_history:
        d["history"] = [
            {"ts": ts(h["idx"]), "status": h["status"], "price": h["price"],
             "breakout_level": h["breakout_level"], "invalidation_level": h["invalidation_level"],
             "reason": h["reason"]}
            for h in occ.history
        ]
    return d
