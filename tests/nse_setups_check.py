"""Compares the Setups scanners with NSE's own daily prices (the exchange's bhavcopy files), for every stock, not a sample.

NSE publishes one file per trading day (sec_bhavdata_full_DDMMYYYY.csv: open, high, low, close, volume per symbol and series). This script reads them
into memory and saved under out/nse_check/ as plain CSV, rebuilds each stock's recent daily bars from NSE alone, recomputes the setups with the
plain rules, and lists where our scanner and NSE-based answer differ. NSE prices are not adjusted for splits or bonuses; a stock with one in the window
will differ for that reason alone (reported separately).
Run: python tests/nse_setups_check.py [YYYY-MM-DD for "today"]"""
import csv
import io
import os
import sys
import warnings
from datetime import date, datetime, timedelta

import requests

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from patterns import market_lists as ml, scan  # noqa: E402

OUT = os.path.join("out", "nse_check")
HEAD = {"User-Agent": "Mozilla/5.0", "Accept": "*/*"}
SERIES_OK = ("EQ", "BE", "BZ", "SM", "ST")


def fetch_day(d: date) -> list[dict] | None:
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{d:%Y%m%d}.csv")
    if os.path.exists(path):
        text = open(path, encoding="utf-8").read()
    else:
        r = requests.get(f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv", headers=HEAD, timeout=40)
        if r.status_code != 200:
            return None                                   # a weekend, a holiday, or a day not published yet
        text = r.text
        open(path, "w", encoding="utf-8").write(text)
    rows = []
    for x in csv.DictReader(io.StringIO(text)):
        x = {k.strip(): (v or "").strip() for k, v in x.items()}
        if x.get("SERIES") in SERIES_OK:
            try:
                rows.append({"sym": x["SYMBOL"], "series": x["SERIES"], "o": float(x["OPEN_PRICE"]), "h": float(x["HIGH_PRICE"]), "l": float(x["LOW_PRICE"]),
                             "c": float(x["CLOSE_PRICE"]), "v": float(x["TTL_TRD_QNTY"])})
            except ValueError:
                continue
    return rows


def main():
    today = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    bars: dict[str, list] = {}
    days = []
    d = today - timedelta(days=34)
    while d <= today:
        if d.weekday() < 5:
            rows = fetch_day(d)
            if rows:
                days.append(d)
                best = {}
                for r in rows:                         # one row per symbol and day: EQ before the others
                    if r["sym"] not in best or r["series"] == "EQ":
                        best[r["sym"]] = r
                for s, r in best.items():
                    bars.setdefault(s, []).append((d, r["o"], r["h"], r["l"], r["c"], r["v"]))
        d += timedelta(days=1)
    print("NSE trading days read:", len(days), days[0], "to", days[-1])

    def weeks(b):
        out, key = [], None
        for x in b:
            k = x[0].isocalendar()[:2]
            if k != key:
                out.append({"h": x[2], "l": x[3], "c": x[4], "last": x[0], "v": x[5]})
                key = k
            else:
                w = out[-1]
                w["h"], w["l"], w["c"], w["last"], w["v"] = max(w["h"], x[2]), min(w["l"], x[3]), x[4], x[0], w["v"] + x[5]
        return out

    def finished(w):
        if w and w[-1]["last"].isocalendar()[:2] == today.isocalendar()[:2] and today.weekday() < 5 and w[-1]["last"].weekday() != 4:
            return w[:-1]
        return w

    rows = scan._load_all()
    kinds = {"inside-bar": "daily inside", "inside-bar-weekly": "weekly inside", "tight-setup": "daily tight", "tight-setup-weekly": "weekly tight",
             "inside-bar-filtered": "daily filtered inside", "inside-bar-weekly-filtered": "weekly filtered inside"}
    common = [s for s in bars if s in rows]
    print("stocks in both NSE files and our scan:", len(common), "(NSE:", len(bars), "ours:", len(rows), ")")
    for kind, label in kinds.items():
        ours = {s for s in common if ml._EVAL[kind](rows[s], None)}
        theirs, why = set(), {}
        for s in common:
            b = bars[s]
            r = rows[s]
            sma50, price = (r.get("sma") or {}).get("50"), r.get("price")
            up = isinstance(sma50, (int, float)) and isinstance(price, (int, float)) and price > sma50
            ok = False
            if kind.startswith("inside-bar") and "weekly" not in kind:
                if len(b) >= 2:
                    (_, _, ph, pl, _, _), (_, _, h, l, _, v) = b[-2], b[-1]
                    ok = h <= ph and l >= pl and ph > pl and h > l and v > 0
                    if ok and "filtered" in kind:
                        ok = (h - l) / (ph - pl) <= 0.6 and up
            elif kind.startswith("inside-bar"):
                w = finished(weeks(b))
                if len(w) >= 2:
                    ph, pl, h, l = w[-2]["h"], w[-2]["l"], w[-1]["h"], w[-1]["l"]
                    ok = h <= ph and l >= pl and ph > pl and h > l and w[-1]["v"] > 0
                    if ok and "filtered" in kind:
                        ok = (h - l) / (ph - pl) <= 0.6 and up
            elif "weekly" in kind:
                w = finished(weeks(b))[-3:]
                cl = [x["c"] for x in w]
                ok = len(cl) == 3 and all(abs(y / x - 1) <= 0.015 for x, y in zip(cl, cl[1:])) and up
            else:
                cl = [x[4] for x in b[-5:]]
                ok = len(cl) == 5 and (max(cl) - min(cl)) / (sum(cl) / 5) <= 0.025 and up
            if ok:
                theirs.add(s)
        both, only_ours, only_nse = ours & theirs, ours - theirs, theirs - ours
        print(f"\n{label:24s} ours={len(ours):4d}  NSE-based={len(theirs):4d}  same={len(both):4d}  only ours={len(only_ours):3d}  only NSE={len(only_nse):3d}  "
              f"agreement={len(both) / max(1, len(ours | theirs)):.1%}")
        for tag, group in (("only ours", only_ours), ("only NSE ", only_nse)):
            if group:
                print("   ", tag, sorted(group)[:12])


if __name__ == "__main__":
    main()
