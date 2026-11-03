"""Build the screening universe (Screener fundamentals + daily prices for every company) outside the web server:
    python -m screens.build_cli          # only companies not refreshed in the last STALE_SECONDS
    python -m screens.build_cli --force  # everything
Progress is printed; results land in data/screens/universe.json exactly as the web-triggered build writes them."""
from __future__ import annotations

import sys
import time

from screens import universe
from tools.live_chart_yf import get_candles


def main() -> None:
    force = "--force" in sys.argv
    if not universe.build(lambda s, i, p: get_candles(s, interval=i, period=p), force=force):
        print("a build is already running")
        return
    last = -1
    while universe._state.get("building"):
        done = universe._state.get("done", 0)
        if done != last:
            print(f"[screens] {done}/{universe._state.get('total')} errors={universe._state.get('errors')}", flush=True)
            last = done
        time.sleep(15)
    print("[screens] done", universe.status(), flush=True)


if __name__ == "__main__":
    main()
