"""Synthetic OHLCV builders for the pattern-agent tests. Synthetic only - never a real company."""
from __future__ import annotations

import numpy as np

from patterns.core import Series

DAY = 86400
T0 = 1_600_000_000  # arbitrary fixed epoch; spacing is what matters


def path(points, n=None):
    """Piecewise-linear closes through [(index, price), ...]."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    n = n if n is not None else xs[-1] + 1
    return np.interp(np.arange(n), xs, ys)


def series_from_closes(closes, volume=1000.0, spread=0.004, timeframe="1d", vol_overrides=None) -> Series:
    c = np.asarray(closes, dtype=float)
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.maximum(o, c) * (1 + spread)
    l = np.minimum(o, c) * (1 - spread)
    v = np.full(len(c), float(volume))
    for i, x in (vol_overrides or {}).items():
        v[i] = x
    t = T0 + np.arange(len(c)) * DAY
    return Series(t, o, h, l, c, v, timeframe=timeframe)


def timeline(res, pattern):
    """[(bar, status)] status changes for one pattern, across all its occurrences."""
    out = []
    for occ in res.occurrences:
        if occ.pattern != pattern:
            continue
        for h in occ.history:
            out.append((h["idx"], h["status"], occ.anchor, h.get("reason")))
    return sorted(out)
