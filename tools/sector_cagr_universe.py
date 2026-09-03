"""
Sector-median 3yr revenue CAGR universe for A.4's sector benchmark leg.

Same precompute+cache+lookup pattern as tools/peer_universe.py (that module's
docstring explains WHY a fixed, auditable universe is required rather than an
ad hoc web search): walk the same fixed NSE sector map
(tools/nse_sector_map.py, 751 Nifty Total Market constituents), compute each
symbol's own 3yr revenue CAGR, and cache it. A.4 (tools/qualitative_engine.py's
compute_a4_product_lifecycle_stage) then compares a company's SEGMENT revenue
CAGR against its own single NSE sector's peer-MEDIAN company-level revenue
CAGR - a documented scoping simplification (no per-segment sector
reclassification exists in this codebase), not a per-segment benchmark.

Revenue CAGR is computed via the EXACT SAME formula tools/metrics_engine.py's
FundamentalMetricsEngine already uses for F-05 (cagr_3y_revenue, requires 4
consecutive annual income-statement columns: (rev[-1]/rev[-4])**(1/3) - 1) -
reusing get_row_series so a future fix to that row-matching logic (e.g. new
label aliases) automatically applies here too, rather than drifting from a
second hand-rolled copy.

This is fast/live per-symbol (yfinance .income_stmt call), NOT an Annual
Report PDF fetch - comparable in cost to peer_universe.py's per-symbol market
cap fetch, just one extra yfinance call. Still slow in aggregate across 751
symbols, so it is precomputed the same way peer_universe.build_universe() is
today: a standalone script entry point (`python -m tools.sector_cagr_universe
build`), not triggered per-request or by a scheduler - this codebase has no
scheduled job for peer_universe.build_universe() either (checked: it's only
invoked from its own __main__ block), so sector_cagr_universe follows the
same manual-trigger convention rather than inventing new wiring.
"""

import os
import json
import time
import statistics

try:
    from tools import ssl_bootstrap  # noqa: F401  (Windows TLS fix; no-op on cloud)
except Exception:
    pass

CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "sector_cagr_universe.json"
)
STALE_AFTER = 7 * 24 * 3600  # same weekly-refresh convention as peer_universe.STALE_AFTER
MIN_PEERS = 5  # mirrors peer_universe.MIN_PEERS - a median of <5 companies is not a defensible benchmark


def _fetch_revenue_cagr_3y(symbol):
    """3yr revenue CAGR via yfinance's annual income statement - same source
    and same formula as tools/metrics_engine.py's F-05 cagr_3y_revenue.
    Returns float or None (never a guess: None whenever <4 annual columns or
    a non-positive start/end revenue, exactly like metrics_engine's own
    guard)."""
    try:
        import yfinance as yf
        from tools.metrics_engine import get_row_series

        ticker = yf.Ticker(f"{symbol}.NS")
        inc_df = ticker.income_stmt
        if inc_df is None or inc_df.empty:
            return None
        rev_series, rev_dates = get_row_series(inc_df, ['Total Revenue', 'Revenue'])
        if not rev_series or len(rev_series) < 4:
            return None
        # yfinance annual columns are newest-first; get_row_series doesn't
        # reorder, so sort ascending here the same way metrics_engine.py does
        # before indexing [-4]/[-1] (that code re-sorts growth_trends inline;
        # mirrored here rather than importing a private local variable).
        if len(rev_dates) > 1 and str(rev_dates[0]) > str(rev_dates[-1]):
            rev_series = rev_series[::-1]
        start_rev, end_rev = rev_series[-4], rev_series[-1]
        if start_rev and end_rev and start_rev > 0 and end_rev > 0:
            return (end_rev / start_rev) ** (1 / 3) - 1
        return None
    except Exception as e:
        print(f"[sector_cagr_universe] revenue CAGR fetch failed for {symbol}: {e}")
        return None


def build_sector_cagr_universe(force=False, symbols=None):
    """
    Precompute step. Walks every symbol in the fixed NSE sector map
    (or `symbols`, an explicit subset - used for scoped test runs), computes
    3yr revenue CAGR, and writes {symbol: {sector, revenue_cagr_3y, as_of_ts}}
    to cache/sector_cagr_universe.json. Checkpoints every 25 symbols like
    peer_universe.build_universe. Resumable: skips symbols already present
    with a fresh value unless force=True.
    """
    from tools.nse_sector_map import all_symbols_by_sector, get_nse_sector

    existing = {}
    if not force and os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
        except Exception:
            existing = {}

    if symbols is not None:
        by_sector = {}
        for sym in symbols:
            sec = get_nse_sector(sym)
            if sec:
                by_sector.setdefault(sec, []).append(sym)
    else:
        by_sector = all_symbols_by_sector()

    universe = dict(existing)
    total = sum(len(v) for v in by_sector.values())
    done = 0
    for sector, syms in by_sector.items():
        for sym in syms:
            done += 1
            row = existing.get(sym)
            if (row and row.get("revenue_cagr_3y") is not None
                    and (time.time() - row.get("as_of_ts", 0)) < STALE_AFTER):
                continue
            cagr = _fetch_revenue_cagr_3y(sym)
            universe[sym] = {
                "sector": sector,
                "revenue_cagr_3y": cagr,
                "as_of_ts": time.time(),
                "as_of": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            if done % 25 == 0:
                print(f"[sector_cagr_universe] {done}/{total} ({sym}: {cagr}) - checkpointing")
                _write(universe)
    _write(universe)
    n_priced = sum(1 for r in universe.values() if r.get("revenue_cagr_3y") is not None)
    print(f"[sector_cagr_universe] DONE. {n_priced}/{len(universe)} symbols have a computed 3yr revenue CAGR.")
    return universe


def _write(universe):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump(universe, fh, indent=None)


def load_sector_cagr_universe():
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def get_sector_median_cagr(sector, universe=None):
    """
    Median 3yr revenue CAGR across every priced company in `sector` within
    the fixed universe. Never mean (per spec - a single outlier CAGR
    shouldn't swing the benchmark). Requires >=MIN_PEERS priced companies,
    mirroring peer_universe.select_peer_set's INSUFFICIENT_PEER_SET floor.

    Returns:
      {"status": "OK", "median_cagr": float, "n": int,
       "audit": [{"symbol", "revenue_cagr_3y"}, ...]}
      or {"status": "INSUFFICIENT_PEER_SET"/"NOT_IN_UNIVERSE", "reason": ...}
    Never raises, never fabricates a median from fewer than MIN_PEERS points.
    """
    if not sector:
        return {"status": "NOT_IN_UNIVERSE", "reason": "No sector provided."}

    universe = universe if universe is not None else load_sector_cagr_universe()
    rows = [
        (s, r.get("revenue_cagr_3y")) for s, r in universe.items()
        if r.get("sector") == sector and r.get("revenue_cagr_3y") is not None
    ]
    if not rows:
        return {
            "status": "NOT_IN_UNIVERSE" if not any(r.get("sector") == sector for r in universe.values())
            else "INSUFFICIENT_PEER_SET",
            "sector": sector,
            "reason": f"No priced companies with a computed 3yr revenue CAGR found in sector '{sector}'.",
        }
    if len(rows) < MIN_PEERS:
        return {
            "status": "INSUFFICIENT_PEER_SET",
            "sector": sector,
            "reason": f"Only {len(rows)} priced companies with a computed CAGR in sector '{sector}' (need >={MIN_PEERS}).",
        }

    cagrs = [c for _, c in rows]
    median = statistics.median(cagrs)
    return {
        "status": "OK",
        "sector": sector,
        "median_cagr": median,
        "n": len(rows),
        "audit": [{"symbol": s, "revenue_cagr_3y": c} for s, c in rows],
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        syms = None
        if "--symbols" in sys.argv:
            idx = sys.argv.index("--symbols")
            syms = sys.argv[idx + 1].split(",")
        build_sector_cagr_universe(force="--force" in sys.argv, symbols=syms)
    else:
        sector = sys.argv[1] if len(sys.argv) > 1 else "IT - Software"
        print(json.dumps(get_sector_median_cagr(sector), indent=2))
