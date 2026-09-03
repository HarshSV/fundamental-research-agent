"""
Bulk-refresh A.2 (competitive advantage / moats) across the full company
registry, for use whenever a fix to tools/qualitative_engine.py's
compute_a2_competitive_moat / tools/moat_peer_scoring.py needs to reach
companies whose A.2 was already computed (and cached in Supabase's
qualitative_values table, 30-day TTL) under the OLD logic.

Same rationale as tools/refresh_ratios.py: `compute_a2_competitive_moat`'s
own cache check (`read_qualitative`) would otherwise keep serving the
stale pre-fix payload for up to 30 days per company. `force=True` bypasses
that read and always recomputes + upserts a fresh row.

Usage:
    python -m tools.refresh_a2_moat --all --workers 4
    python -m tools.refresh_a2_moat --symbols ITC,RELIANCE,HINDUNILVR

Long-running by design (one CRISIL fetch + up to 8 peer Screener fetches +
one LLM call per company) - meant to run in the background. Safe to
re-run/resume: just re-invoke with --all, already-fresh rows just get
overwritten with the same (or updated) data, no harm.
"""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, ".")

from tools.supabase_client import get_client

PAGE_SIZE = 1000


def _load_all_companies(sb):
    """Paginated fetch of every (symbol, name) in the `companies` table - 
    same pattern as tools/refresh_ratios.py's _load_all_companies."""
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


def refresh_one(symbol, name, skip_llm=True):
    from tools.qualitative_engine import compute_a2_competitive_moat
    try:
        market_cap_cr = None
        try:
            from tools.peer_universe import load_universe
            row = load_universe().get((symbol or "").strip().upper())
            market_cap_cr = (row or {}).get("market_cap_cr")
        except Exception:
            pass
        payload = compute_a2_competitive_moat(symbol, name, market_cap_cr=market_cap_cr,
                                               force=True, skip_llm=skip_llm)
        return symbol, True, payload.get("confidence_tag")
    except Exception as e:
        return symbol, False, str(e)


def refresh(symbols=None, workers=1, skip_llm=True):
    sb = get_client()
    if symbols:
        companies = [{"symbol": s.strip().upper(), "name": None} for s in symbols]
    else:
        print("[refresh_a2_moat] loading full company registry...")
        companies = _load_all_companies(sb)
    total = len(companies)
    print(f"[refresh_a2_moat] refreshing A.2 for {total} companies (workers={workers})...")

    done = ok = failed = 0
    start_t = time.time()

    def _run(c):
        return refresh_one(c["symbol"], c.get("name"), skip_llm=skip_llm)

    if workers <= 1:
        results_iter = (_run(c) for c in companies)
        for sym, success, info in results_iter:
            done += 1
            ok += int(success)
            failed += int(not success)
            if done % 25 == 0 or not success:
                elapsed = time.time() - start_t
                print(f"[refresh_a2_moat] {done}/{total} (ok={ok} failed={failed}, {elapsed:.0f}s) "
                      f"last={sym}: {'OK ' + str(info) if success else 'FAILED ' + info}")
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(refresh_one, c["symbol"], c.get("name"), skip_llm): c["symbol"] for c in companies}
            for fut in as_completed(futures):
                sym, success, info = fut.result()
                done += 1
                ok += int(success)
                failed += int(not success)
                if done % 25 == 0 or not success:
                    elapsed = time.time() - start_t
                    print(f"[refresh_a2_moat] {done}/{total} (ok={ok} failed={failed}, {elapsed:.0f}s) "
                          f"last={sym}: {'OK ' + str(info) if success else 'FAILED ' + info}")

    print(f"[refresh_a2_moat] DONE. {ok}/{total} succeeded, {failed} failed, {time.time() - start_t:.0f}s total.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", help="comma-separated list, e.g. ITC,RELIANCE")
    parser.add_argument("--all", action="store_true", help="refresh every company in the registry")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--with-llm", action="store_true",
                         help="also run the qualitative-evidence LLM scoring pass (touches the shared "
                              "Groq/OpenRouter quota) - default is quant-pillars-only, no LLM calls at all.")
    args = parser.parse_args()

    if not args.symbols and not args.all:
        parser.error("must pass --symbols or --all")

    refresh(symbols=args.symbols.split(",") if args.symbols else None, workers=args.workers,
            skip_llm=not args.with_llm)
