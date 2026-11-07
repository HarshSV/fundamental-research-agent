"""The 32 supported patterns, their detectors, and the rules for counting each formation once."""
from __future__ import annotations

from .core import DETECTOR_VERSION, Bidirectional, Detector, MirrorDetector
from .detectors import bases, harmonic, liquidity, reversal, rounding, trendlines

ALL: list[Detector] = [
    *reversal.DETECTORS,      # double/triple top+bottom, (inverse) head & shoulders          6
    *rounding.DETECTORS,      # rounding bottom/top, saucer, cup base, cup & handle           5
    *bases.DETECTORS,         # vcp, flat, ascending, ipo, high tight flag, three weeks tight 6
    *trendlines.DETECTORS,    # 3 triangles, 2 wedges, rectangle, flag, pennant                8
    *liquidity.DETECTORS,     # order blocks, pocket pivot, undercut, shakeout, spring, upthrust 6
    *harmonic.DETECTORS,      # gartley-like                                                  1
]

# Within a group (highest priority first) one formation is reported once: a lower-priority detector
# that describes the same formation (same `group_key`) is dropped / superseded.
GROUPS = [
    ("cup-and-handle", "cup-base", "saucer-base", "rounding-bottom"),
    ("wyckoff-spring", "shakeout", "undercut-and-rally"),
    ("triple-bottom", "double-bottom"),  # keyed on the last low: three lows are one Triple, not also a Double
    ("triple-top", "double-top"),
]

BY_NAME = {d.name: d for d in ALL}
assert len(BY_NAME) == len(ALL) == 32, "pattern names must be unique and total 32"


# Patterns whose single detector reports both directions (taken from the actual structure) although they are not
# wrapped in `Bidirectional`.
_EITHER_WAY = {"symmetrical-triangle", "rectangle"}
# Bearish by definition but written as their own detector rather than as a MirrorDetector.
_BEARISH = {"descending-triangle", "rising-wedge"}


def bias(d: Detector) -> str:
    """What a confirmed formation of this pattern implies: "bullish", "bearish", or "both" when its direction comes
    from the structure found. Derived from how the detector is built: detectors are written bullish, a Mirror is
    their bearish twin, a Bidirectional runs both."""
    if isinstance(d, Bidirectional) or d.name in _EITHER_WAY:
        return "both"
    return "bearish" if isinstance(d, MirrorDetector) or d.name in _BEARISH else "bullish"


def catalogue() -> list[dict]:
    return [
        {"id": d.name, "name": d.display, "category": d.category, "bias": bias(d), "maturity": d.maturity,
         "min_bars": d.min_bars, "timeframes": list(d.timeframes) if d.timeframes else "any",
         "definition": d.definition, "parameters": {k: v for k, v in d.defaults.items()}}
        for d in ALL
    ]


__all__ = ["ALL", "GROUPS", "BY_NAME", "catalogue", "DETECTOR_VERSION"]
