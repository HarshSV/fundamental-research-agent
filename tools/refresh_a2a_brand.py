"""
Bulk-compute A.2.A (brand moat, deterministic no-LLM scorer) across the full
company registry. Same pattern as tools/refresh_a2_moat.py, but for the new
2A sub-point - this one never touches any LLM API at all (see
tools/moat_brand_scoring.py), so it's safe to run at full 2,409-company
scale immediately, unlike the qualitative-evidence pass in A.2 itself.

Usage:
    python -m tools.refresh_a2a_brand --all --workers 6
    python -m tools.refresh_a2a_brand --symbols ITC,RELIANCE,HINDUNILVR
"""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, ".")

from tools.supabase_client import get_client

PAGE_SIZE = 1000


def _load_all_companies(sb):
    rows = []
    start = 0
    while True:
        resp = sb.table("companies").select("symbol,name").range(start, start + PAGE_SIZE - 1).execute()
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    return rows


def refresh_one(symbol, name):
    from tools.qualitative_engine import compute_a2a_brand_moat
    try:
        payload = compute_a2a_brand_moat(symbol, name, description="", force=True)
        return symbol, True, payload.get("score")
    except Exception as e:
        return symbol, False, str(e)


def refresh(symbols=None, workers=1):
    sb = get_client()
    if symbols:
        companies = [{"symbol": s.strip().upper(), "name": None} for s in symbols]
    else:
        print("[refresh_a2a_brand] loading full company registry...")
        companies = _load_all_companies(sb)
    total = len(companies)
    print(f"[refresh_a2a_brand] refreshing A.2.A for {total} companies (workers={workers})...")

    done = ok = failed = 0
    start_t = time.time()

    if workers <= 1:
        for c in companies:
            sym, success, info = refresh_one(c["symbol"], c.get("name"))
            done += 1
            ok += int(success)
            failed += int(not success)
            if done % 50 == 0 or not success:
                elapsed = time.time() - start_t
                print(f"[refresh_a2a_brand] {done}/{total} (ok={ok} failed={failed}, {elapsed:.0f}s) "
                      f"last={sym}: {'score=' + str(info) if success else 'FAILED ' + info}")
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(refresh_one, c["symbol"], c.get("name")): c["symbol"] for c in companies}
            for fut in as_completed(futures):
                sym, success, info = fut.result()
                done += 1
                ok += int(success)
                failed += int(not success)
                if done % 50 == 0 or not success:
                    elapsed = time.time() - start_t
                    print(f"[refresh_a2a_brand] {done}/{total} (ok={ok} failed={failed}, {elapsed:.0f}s) "
                          f"last={sym}: {'score=' + str(info) if success else 'FAILED ' + info}")

    print(f"[refresh_a2a_brand] DONE. {ok}/{total} succeeded, {failed} failed, {time.time() - start_t:.0f}s total.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", help="comma-separated list, e.g. ITC,RELIANCE")
    parser.add_argument("--all", action="store_true", help="refresh every company in the registry")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    if not args.symbols and not args.all:
        parser.error("must pass --symbols or --all")

    refresh(symbols=args.symbols.split(",") if args.symbols else None, workers=args.workers)
