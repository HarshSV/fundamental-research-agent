"""Does any pattern detector use the future? (A look-ahead check, the idea behind freqtrade's "lookahead-analysis".)

The agent replays a stock bar by bar, each detector seeing only the bars up to that one. If that holds, replaying the same stock on a series
CUT SHORT at bar k must give exactly the same confirmations up to bar k as replaying the whole series. Anything that differs used a bar
after the cut (or a quantity computed from the whole series, such as the series mean the bearish mirror is built from).

For each sampled stock: replay the full 5-year daily series and a copy cut at 70% of its length, on the same fetched candles, then compare
the confirmations (pattern, direction, anchor bar, first-confirmed bar) that happened up to the cut. Reported per pattern: how many
confirmations were seen in the full run up to the cut, how many of those the cut run also gave, and how many the cut run gave that the full
run did not. 100% agreement and no extras = no look-ahead.

Run:  python -m research.lookahead_check [--stocks 12]"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, ".")

from patterns import scan  # noqa: E402
from patterns.engine import replay  # noqa: E402
from patterns.registry import ALL, GROUPS  # noqa: E402
from patterns.service import build_series  # noqa: E402
from tools.live_chart_yf import get_candles  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "research", "lookahead_check.json")


def _confirmed(res, series, limit_idx: int) -> set:
    """{(pattern, direction, anchor bar time, first confirmed bar time)} for confirmations at or before bar limit_idx."""
    out = set()
    for o in res.occurrences:
        first = next((h["idx"] for h in o.history if h["status"] == "confirmed"), None)
        if first is not None and first <= limit_idx:
            out.add((o.pattern, o.direction, int(series.t[o.anchor]), int(series.t[first])))
    return out


def run(n_stocks: int = 12, cut_share: float = 0.7) -> dict:
    rows = scan._load_all()
    syms = sorted(rows, key=lambda s: -(rows[s].get("market_cap_cr") or 0))
    syms = syms[:: max(1, len(syms) // n_stocks)][:n_stocks]            # spread across large and small stocks
    agg = defaultdict(lambda: {"full": 0, "same": 0, "extra": 0})
    per_stock, t0 = [], time.time()
    for sym in syms:
        cs = get_candles(sym, interval="1d", period="5y")
        series = build_series(cs or [], "1d")
        if series is None or series.n < 400:
            continue
        cut = int(series.n * cut_share)
        short = build_series(cs[: len(cs) - (series.n - cut)], "1d")
        if short is None:
            continue
        full = _confirmed(replay(series, ALL, groups=GROUPS), series, cut - 1)
        part = _confirmed(replay(short, ALL, groups=GROUPS), short, short.n - 1)
        part = {e for e in part if e[3] <= int(series.t[cut - 1])}
        for e in full:
            agg[e[0]]["full"] += 1
            agg[e[0]]["same"] += e in part
        for e in part - full:
            agg[e[0]]["extra"] += 1
        per_stock.append({"symbol": sym, "bars": series.n, "full": len(full), "same": len(full & part), "extra": len(part - full)})
        print(f"{sym}: {len(full)} confirmations up to the cut, {len(full & part)} reproduced, {len(part - full)} extra  ({time.time() - t0:.0f}s)", flush=True)
    out = {"stocks": per_stock, "by_pattern": {k: v for k, v in sorted(agg.items())},
           "total": {k: sum(v[k] for v in agg.values()) for k in ("full", "same", "extra")}}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stocks", type=int, default=12)
    a = ap.parse_args()
    r = run(a.stocks)
    print("\npattern                      full  same  extra")
    for k, v in r["by_pattern"].items():
        flag = "" if v["same"] == v["full"] and v["extra"] == 0 else "   <-- differs"
        print(f"{k:27} {v['full']:5d} {v['same']:5d} {v['extra']:5d}{flag}")
    t = r["total"]
    print(f"\ntotal: {t['full']} confirmations, {t['same']} reproduced, {t['extra']} extra")
