"""Compares the market-list scanners (top gainers / losers, gap up, volume gainers, high volume) with NSE's own daily files for NSE-listed stocks.
Uses the files saved by tests/nse_setups_check.py or patterns/nse_prices.py (data/exchange/bhavcopy). Run: python tests/nse_lists_check.py"""
import csv
import io
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from patterns import market_lists as ml, nse_prices, scan  # noqa: E402


def day(path):
    out = {}
    for x in csv.DictReader(io.StringIO(open(path, encoding="utf-8").read())):
        x = {k.strip(): (v or "").strip() for k, v in x.items()}
        if x["SERIES"] == "EQ":
            try:
                out[x["SYMBOL"]] = dict(o=float(x["OPEN_PRICE"]), h=float(x["HIGH_PRICE"]), l=float(x["LOW_PRICE"]), c=float(x["CLOSE_PRICE"]), p=float(x["PREV_CLOSE"]), v=float(x["TTL_TRD_QNTY"]))
            except ValueError:
                pass
    return out


def main():
    DIR = os.path.join("data", "exchange", "bhavcopy") if os.path.isdir(os.path.join("data", "exchange", "bhavcopy")) else os.path.join("out", "nse_check")      # the files patterns/nse_prices.py keeps (the newest sessions)
    files = sorted(f for f in os.listdir(DIR) if f.endswith(".csv") and f[:8].isdigit())[-22:]
    days = [day(os.path.join(DIR, f)) for f in files]
    last = days[-1]
    rows = {s: r for s, r in scan._load_all().items() if r.get("exchange") in (None, "NSE") and s in last}
    print("NSE trading days used:", len(days), files[-1], "| NSE-listed stocks compared:", len(rows))
    kinds = {
        "top-gainers": lambda s, d: d["c"] > d["p"],
        "top-losers": lambda s, d: d["c"] < d["p"],
        "gap-up": lambda s, d: d["o"] >= d["p"] * 1.02,
        "volume-gainers": lambda s, d: (lambda base: len(base) == 5 and sum(base) > 0 and d["v"] >= 2 * (sum(base) / 5))([x[s]["v"] for x in days[-6:-1] if s in x]),      # NSE: today against the average of the 5 sessions before it
    }
    for kind, rule in kinds.items():
        ours = {s for s, r in rows.items() if ml._EVAL[kind](r, None)}
        theirs = set()
        for s in rows:
            d = last[s]
            if d["p"] > 0 and abs(rows[s]["candles"][-1][4] / d["c"] - 1) < 0.01 and rule(s, d):      # same price basis (no split in the window)
                theirs.add(s)
        both = ours & theirs
        print(f"{kind:16s} ours={len(ours):4d} NSE={len(theirs):4d} same={len(both):4d} only ours={len(ours - theirs):3d} only NSE={len(theirs - ours):3d} agreement={len(both) / max(1, len(ours | theirs)):.1%}",
              sorted(ours - theirs)[:5], sorted(theirs - ours)[:5])


if __name__ == "__main__":
    main()
