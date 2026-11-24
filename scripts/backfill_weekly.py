"""Adds the weekly history (`wcandles`, about three years of weekly candles) to every scanned stock's file that does not have it yet.
New scans write it themselves; this fills in the stocks scanned before that existed, without re-running the pattern engine.
Run: python scripts/backfill_weekly.py [workers]"""
import json
import os
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from patterns import scan  # noqa: E402
from tools import live_chart_yf  # noqa: E402
from tools.live_chart_yf import get_candles  # noqa: E402


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    yahoo = {u["symbol"]: u["yahoo"] for u in scan.universe() if u.get("yahoo")}          # BSE-only companies are priced under their BSE symbol
    live_chart_yf._TICKER_CACHE.update(yahoo)
    files = [f for f in os.listdir(scan.SYMBOL_DIR) if f.endswith(".json")]

    def one(f):
        path = os.path.join(scan.SYMBOL_DIR, f)
        try:
            with open(path, encoding="utf-8") as fh:
                row = json.load(fh)
            if row.get("wcandles"):
                return "had"
            full = get_candles(row["symbol"], interval="1d", period="max")
            if not full or len(full) < 20:
                return "nodata"
            # re-read: a scan may have rewritten the file while the prices were being fetched; keep its newer fields
            with open(path, encoding="utf-8") as fh:
                row = json.load(fh)
            row["wcandles"] = scan.weekly_history(full)
            with open(path + ".bf.tmp", "w", encoding="utf-8") as fh:
                json.dump(row, fh)
            os.replace(path + ".bf.tmp", path)
            return "ok"
        except Exception as e:
            print(f"[backfill] {f}: {e}", flush=True)
            return "err"

    t0, tally = time.time(), {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, r in enumerate(ex.map(one, files), 1):
            tally[r] = tally.get(r, 0) + 1
            if i % 250 == 0:
                print(f"[backfill] {i}/{len(files)} {tally} {int(time.time() - t0)}s", flush=True)
    print("[backfill] done", tally, f"{int(time.time() - t0)}s")


if __name__ == "__main__":
    main()
