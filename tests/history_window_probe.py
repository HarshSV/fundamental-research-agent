"""Does a longer daily history make the 5-session outlook better or worse?

For stocks with a long history, at many past dates the outlook is computed twice from what was known then: once from the last
5 years only (what the stock page used so far) and once from the whole history. Each call (up / down) is then compared with what the
price actually did over the next 5 sessions. Nothing here is synthetic: real closes, past dates only, no look-ahead (the model sees
only bars up to the cut).

Run:  python -m tests.history_window_probe [--stocks 40] [--step 10] [--span 750]
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time

sys.path.insert(0, ".")

from patterns import scan  # noqa: E402
from setups import outlook  # noqa: E402
from tools.live_chart_yf import get_candles  # noqa: E402

H = 5
WINDOW_5Y = 1250


def run(n_stocks: int, step: int, span: int) -> None:
    rows = scan._load_all()
    syms = sorted(rows, key=lambda s: -(rows[s].get("market_cap_cr") or 0))
    stats = {"5y": {"calls": 0, "hits": 0, "ret_up": [], "ret_down": [], "even": 0},
             "full": {"calls": 0, "hits": 0, "ret_up": [], "ret_down": [], "even": 0}}
    used, t0 = 0, time.time()
    for sym in syms:
        if used >= n_stocks:
            break
        daily = get_candles(sym, interval="1d", period="max")
        if not daily or len(daily) < WINDOW_5Y + span + 300:
            continue
        used += 1
        n = len(daily)
        for i in range(n - span - H, n - H, step):
            known = daily[: i + 1]
            fwd = daily[i + H]["close"] / daily[i]["close"] - 1.0
            for name, bars in (("5y", known[-WINDOW_5Y:]), ("full", known)):
                o = outlook.horizon_outlook(bars, H)
                s = stats[name]
                if o.get("call") in ("up", "down"):
                    s["calls"] += 1
                    s["hits"] += (fwd > 0) == (o["call"] == "up")
                    (s["ret_up"] if o["call"] == "up" else s["ret_down"]).append(fwd)
                elif o.get("call") == "even":
                    s["even"] += 1
        print(f"{used}/{n_stocks} {sym} ({n} sessions) {time.time() - t0:.0f}s", flush=True)
    print("\nstocks", used, "| step", step, "| span", span, "sessions | horizon", H)
    for name, s in stats.items():
        m = lambda a: f"{statistics.mean(a) * 100:+.2f}%" if a else "n/a"
        print(f"{name:>5}: calls {s['calls']:5d}  hit-rate {100 * s['hits'] / max(s['calls'], 1):5.1f}%  even {s['even']:5d}  "
              f"mean 5-session return after 'up' {m(s['ret_up'])}  after 'down' {m(s['ret_down'])}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stocks", type=int, default=40)
    ap.add_argument("--step", type=int, default=10)
    ap.add_argument("--span", type=int, default=750)
    a = ap.parse_args()
    run(a.stocks, a.step, a.span)
