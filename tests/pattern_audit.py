"""How much does a pattern fire on real stocks, and what happens to that when its rule is set to the published one?
Runs the pattern detectors on ~120 NSE stocks' five-year daily history (fetched once, cached in out/pattern_audit/) with the stored settings (baseline)
and with settings taken from published definitions (variants), and counts the patterns showing right now (forming, awaiting breakout, or
confirmed within the last bars), the way the scanner does. Not a pytest: python tests/pattern_audit.py [number of stocks]"""
import json
import os
import random
import sys
import warnings
from collections import Counter

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from patterns import registry, scan  # noqa: E402
from patterns.engine import replay, to_dict  # noqa: E402
from patterns.service import build_series  # noqa: E402
from tools.live_chart_yf import get_candles  # noqa: E402

CACHE = os.path.join("out", "pattern_audit")
DAY = 86400


def history(sym: str):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{sym}.json")
    if os.path.exists(path):
        return json.load(open(path))
    full = get_candles(sym, interval="1d", period="max")
    if not full or len(full) < 400:
        return None
    window = [c for c in full if c["time"] >= full[-1]["time"] - int(5 * 365.25 * DAY)]
    json.dump(window, open(path, "w"))
    return window


def current(series, occs):
    return scan._current([to_dict(series, o, with_history=False) for o in occs], [int(t) for t in series.t])


def count(stocks, names, cfg=None, only_status=None):
    dets = [registry.BY_NAME[n] for n in names]
    out = Counter()
    for sym, window in stocks.items():
        series = build_series(window, "1d")
        if series is None:
            continue
        res = replay(series, dets, cfg=cfg)
        for o in current(series, res.occurrences):
            if only_status is None or o["status"] in only_status:
                out[o["pattern"]] += 1
    return out


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    rows = scan._load_all()
    pool = sorted(s for s, r in rows.items() if r.get("exchange") in (None, "NSE") and len(r.get("closes") or []) >= 400)
    random.seed(11)
    stocks = {}
    for s in random.sample(pool, min(len(pool), n + 40)):
        w = history(s)
        if w:
            stocks[s] = w
        if len(stocks) >= n:
            break
    print("stocks:", len(stocks))
    reversal = ["double-bottom", "double-top", "triple-bottom", "triple-top"]
    base = count(stocks, reversal)
    var = count(stocks, reversal, {k: {"swing_pct": 0.10} for k in reversal})
    print("\nreversal tops/bottoms: rise between the two points 4% (now) -> 10% (Bulkowski's minimum)")
    for k in reversal:
        print(f"  {k:16s} {base[k]:4d} -> {var[k]:4d}")
    base = count(stocks, ["ascending-base"])
    var = count(stocks, ["ascending-base"], {"ascending-base": {"depth_min": 0.10, "depth_max": 0.20}})
    print("\nascending base: pullbacks 8-25% (now) -> 10-20% (IBD)")
    print(f"  ascending-base   {base['ascending-base']:4d} -> {var['ascending-base']:4d}")
    base = count(stocks, ["high-tight-flag"])
    print(f"\nhigh-tight-flag now {base['high-tight-flag']}")
    base = count(stocks, ["harmonic-gartley"])
    print("\nharmonic-gartley now:", dict(Counter()), base["harmonic-gartley"])
    st = count(stocks, ["harmonic-gartley"], only_status={"awaiting_breakout", "confirmed"})
    print("  of which completed (awaiting / confirmed):", st["harmonic-gartley"])


if __name__ == "__main__":
    main()
