"""Checks the Setups scanners against price data fetched separately from the provider (not the scan's stored candles).
For a sample of the stocks each setup returns, recompute the setup from fresh daily bars with the plain textbook rule and report disagreements.
Run: python tests/setups_probe.py   (reads the price provider; not a pytest)"""
import random
import sys
import warnings
from datetime import datetime, timezone, timedelta

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from patterns import market_lists as ml, scan  # noqa: E402
from tools.live_chart_yf import get_candles  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
KINDS = ["inside-bar", "inside-bar-weekly", "inside-bar-filtered", "inside-bar-weekly-filtered", "tight-setup", "tight-setup-weekly"]


def weeks(bars):
    out, key = [], None
    for b in bars:
        d = datetime.fromtimestamp(b["time"], IST).date()
        k = d.isocalendar()[:2]
        if k != key:
            out.append({"o": b["open"], "h": b["high"], "l": b["low"], "c": b["close"], "last": d})
            key = k
        else:
            w = out[-1]
            w["h"], w["l"], w["c"], w["last"] = max(w["h"], b["high"]), min(w["l"], b["low"]), b["close"], d
    return out


def finished(w):
    """Drop an unfinished trailing week: the last bar is not a Friday, it is still the current week, and it is not the weekend."""
    today = datetime.now(IST).date()
    if w and w[-1]["last"].isocalendar()[:2] == today.isocalendar()[:2] and today.weekday() < 5 and w[-1]["last"].weekday() != 4:
        return w[:-1]
    return w


def main():
    rows = scan._load_all()
    random.seed(7)
    print("data as of", max(r.get("candles", [[0]])[-1][0] for r in list(rows.values())[:200] if r.get("candles")))
    for kind in KINDS:
        hits = [s for s, r in rows.items() if ml._EVAL[kind](r, None)]
        sample = random.sample(hits, min(25, len(hits)))
        bad = []
        for s in sample:
            d = get_candles(s, interval="1d", period="1y") or []
            if len(d) < 60:
                continue
            if kind.startswith("inside-bar") and "weekly" not in kind:
                a, b = d[-2], d[-1]
                ok = b["high"] <= a["high"] and b["low"] >= a["low"]
            elif kind.startswith("inside-bar"):
                w = finished(weeks(d))
                a, b = w[-2], w[-1]
                ok = b["h"] <= a["h"] and b["l"] >= a["l"]
                if ok and b["last"].weekday() != 4:
                    ok = "PARTIAL WEEK ended " + str(b["last"])
            elif "weekly" in kind:
                w = finished(weeks(d))[-3:]
                cl = [x["c"] for x in w]
                ok = all(abs(b / a - 1) <= 0.015 for a, b in zip(cl, cl[1:]))
                if ok and w[-1]["last"].weekday() != 4:
                    ok = "PARTIAL WEEK ended " + str(w[-1]["last"])
            else:
                cl = [x["close"] for x in d[-5:]]
                ok = (max(cl) - min(cl)) / (sum(cl) / 5) <= 0.025
            if ok is not True:
                bad.append((s, ok))
        print(f"{kind:28s} matches={len(hits):4d} sampled={len(sample):2d} disagree={len(bad)} {bad[:6]}")


if __name__ == "__main__":
    main()
