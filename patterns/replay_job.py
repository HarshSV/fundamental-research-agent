"""Runs one pattern replay in its own process: `python -m patterns.replay_job` reads {symbol, timeframe, candles} as JSON on stdin and
writes the result to the pattern store (patterns/store.py), exactly as patterns.service does in-process.

Why: a full replay takes 10 to 30 seconds of pure Python. Run inside the web server it holds the interpreter lock, so every other request
in that process slows down while it works. In its own process it costs the same time but the server stays responsive."""
from __future__ import annotations

import json
import sys


def main() -> int:
    payload = json.load(sys.stdin)
    from . import service, store
    from .core import DETECTOR_VERSION
    from .engine import replay
    from .registry import ALL, GROUPS

    series = service.build_series(payload["candles"], payload["timeframe"])
    if series is None:
        return 3
    res = replay(series, ALL, groups=GROUPS)
    store.save(payload["symbol"], payload["timeframe"], DETECTOR_VERSION, series, res.occurrences, res.errors)
    return 0


if __name__ == "__main__":
    sys.exit(main())
