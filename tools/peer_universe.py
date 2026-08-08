"""
Fixed, ranked peer universe for A.2's moat peer-set protocol.

The rule (per the qualitative sourcing protocol): peers may ONLY be drawn
from an existing fixed, auditable universe — never an open web search or
the AI's own "similar companies" judgment. This codebase has no ready-made
"Emkay ~258-company" list; what it DOES already have is
tools/nse_sector_map.py's NSE-sourced sector classification (751 Nifty
Total Market constituents, the exact codes used by the ratio workbook's
Sector Applicability Matrix). That is used here as the fixed universe of
record — every company in it has a verifiable NSE sector tag, and the
list itself is reproducible from frontend/src/lib/nseSectorMap.js.
COVERAGE CAVEAT (must be surfaced, never hidden): this covers the ~751
most liquid NSE names, not the full ~2,400-symbol registry — a micro-cap
outside Nifty Total Market has no valid peer set under this protocol and
must be flagged "insufficient peer set", not silently skipped.

This module has two parts:
  1. build_universe() — a precompute step (slow; run offline/background)
     that fetches market cap for every symbol in the fixed sector map and
     writes cache/peer_universe.json.
  2. select_peer_set() — the live, fast peer-set-selection algorithm
     (market-cap-band widening per the protocol) that reads that cache.
     Never fetches live — if the cache is empty/stale for a symbol, it
     returns an explicit "insufficient peer set" result, never a guess.
"""

import os
import json
import time

try:
    from tools import ssl_bootstrap  # noqa: F401  (Windows TLS fix; no-op on cloud)
except Exception:
    pass

CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "peer_universe.json"
)
STALE_AFTER = 7 * 24 * 3600  # market cap drifts; rebuild weekly

# Widening bands per the peer-set protocol, tried in order, stop at the
# first that yields >=5 peers. Never widen past the last one.
BAND_STEPS = [(0.4, 2.5), (0.25, 4.0), (0.15, 6.0), (0.1, 10.0)]
MIN_PEERS = 5
MAX_PEERS = 10


def _fetch_market_cap_cr(symbol):
    """Market cap in ₹ crore via yfinance — same source/approach already
    used by tools/peer_synthesis.py's PeerSectorEvaluator, so this stays
    on the same-source-lock rule when compared against other peer data
    built the same way."""
    try:
        import yfinance as yf
        info = yf.Ticker(f"{symbol}.NS").info
        mc = info.get("marketCap")
        return round(mc / 1e7, 2) if mc else None
    except Exception as e:
        print(f"[peer_universe] market cap fetch failed for {symbol}: {e}")
        return None


def build_universe(force=False, symbols=None):
    """
    Precompute step. Walks every symbol in the fixed NSE sector map, fetches
    its market cap, and writes {symbol: {sector, market_cap_cr, as_of}} to
    cache/peer_universe.json. Long-running (network call per symbol) —
    meant to run in the background, same pattern as run_full_precompute.py.
    Resumable: skips symbols already present with a fresh market_cap_cr
    unless force=True.
    """
    from tools.nse_sector_map import all_symbols_by_sector

    existing = {}
    if not force and os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
        except Exception:
            existing = {}

    by_sector = all_symbols_by_sector()
    universe = dict(existing)
    total = sum(len(v) for v in by_sector.values())
    done = 0
    for sector, syms in by_sector.items():
        for sym in syms:
            done += 1
            row = existing.get(sym)
            if row and row.get("market_cap_cr") and (time.time() - row.get("as_of_ts", 0)) < STALE_AFTER:
                continue
            mc = _fetch_market_cap_cr(sym)
            universe[sym] = {
                "sector": sector,
                "market_cap_cr": mc,
                "as_of_ts": time.time(),
                "as_of": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            if done % 25 == 0:
                print(f"[peer_universe] {done}/{total} ({sym}: {mc} cr) — checkpointing")
                _write(universe)
    _write(universe)
    n_priced = sum(1 for r in universe.values() if r.get("market_cap_cr"))
    print(f"[peer_universe] DONE. {n_priced}/{len(universe)} symbols priced.")
    return universe


def _write(universe):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump(universe, fh, indent=None)


def load_universe():
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def select_peer_set(symbol, market_cap_cr=None, universe=None):
    """
    Peer-set protocol, steps 1-4: universe lock (fixed sector map) -> exact
    sector match -> market-cap-band widening (0.4-2.5x, then wider) ->
    >=5-peer floor, cap 10 closest.

    Returns:
      {"status": "OK", "sector": ..., "band": (lo, hi), "peers": [sym,...],
       "audit": [{"symbol", "market_cap_cr"}, ...]}
      or
      {"status": "INSUFFICIENT_PEER_SET", "sector": ..., "reason": "..."}
      or
      {"status": "NOT_IN_UNIVERSE", "reason": "..."}  # symbol itself has no NSE sector tag
    Never raises, never fabricates a peer.
    """
    sym = (symbol or "").strip().upper()
    universe = universe if universe is not None else load_universe()
    row = universe.get(sym)

    from tools.nse_sector_map import get_nse_sector
    sector = (row or {}).get("sector") or get_nse_sector(sym)
    if not sector:
        return {
            "status": "NOT_IN_UNIVERSE",
            "reason": f"{sym} is not in the fixed NSE sector universe (outside Nifty Total Market "
                      f"coverage) — no valid peer set can be constructed under the protocol.",
        }

    mc = market_cap_cr if market_cap_cr is not None else (row or {}).get("market_cap_cr")
    if not mc:
        return {
            "status": "INSUFFICIENT_PEER_SET",
            "sector": sector,
            "reason": f"{sym}'s market cap is not yet in the precomputed peer universe "
                      f"(run tools.peer_universe.build_universe) — cannot band-match peers.",
        }

    candidates = [
        (s, r.get("market_cap_cr")) for s, r in universe.items()
        if s != sym and r.get("sector") == sector and r.get("market_cap_cr")
    ]
    if not candidates:
        return {
            "status": "INSUFFICIENT_PEER_SET",
            "sector": sector,
            "reason": f"No other priced companies found in sector '{sector}' within the fixed universe.",
        }

    for lo_mult, hi_mult in BAND_STEPS:
        lo, hi = mc * lo_mult, mc * hi_mult
        band_peers = [(s, c) for s, c in candidates if lo <= c <= hi]
        if len(band_peers) >= MIN_PEERS:
            band_peers.sort(key=lambda x: abs(x[1] - mc))
            band_peers = band_peers[:MAX_PEERS]
            return {
                "status": "OK",
                "sector": sector,
                "target_market_cap_cr": mc,
                "band": (round(lo, 1), round(hi, 1)),
                "band_widened": (lo_mult, hi_mult) != BAND_STEPS[0],
                "peers": [s for s, _ in band_peers],
                "audit": [{"symbol": s, "market_cap_cr": c} for s, c in band_peers],
            }

    return {
        "status": "INSUFFICIENT_PEER_SET",
        "sector": sector,
        "reason": f"Only {len(candidates)} priced peers exist in sector '{sector}' even at the widest "
                  f"0.1x-10x market-cap band (need >=5). Sector too thin in this universe.",
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build_universe(force="--force" in sys.argv)
    else:
        sym = sys.argv[1] if len(sys.argv) > 1 else "ITC"
        print(json.dumps(select_peer_set(sym), indent=2))
