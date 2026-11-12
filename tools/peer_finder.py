"""Peers chosen from several independent sources, so that no single one can leave a company without any.

Screener rate-limits this machine and a BSE-only company has no NSE sector, so a Peer Comparison that depended on one source was often empty.
Each source below votes for candidates; a candidate's score is the number of sources that group it with the company, and the candidates
are ranked by that score, then by how close their market cap is. A source with nothing for the company simply does not vote.

  screener_industry   same Screener industry (screens/quarterly.py classification; finest level, else the industry group)
  yahoo_industry      same Yahoo Finance industry (tools/yahoo_industry.py)
  yahoo_similar       Yahoo's own "similar stocks" list, in either direction (this company lists it, or it lists this company)
  nse_sector          same NSE sector, for a company that has one

Candidates are the scanned companies (they have a price and market cap). Nothing is guessed: no vote and no market cap means no peer."""
from __future__ import annotations

import math

LABELS = {
    "screener_industry": "Screener industry",
    "yahoo_industry": "Yahoo industry",
    "yahoo_similar": "Yahoo similar stocks",
    "nse_sector": "NSE sector",
}


def _screener_label(q: dict, sym: str):
    c = (q.get(sym) or {}).get("cls") or []
    return (c[3] if len(c) > 3 else None) or (c[2] if len(c) > 2 else None)


def find(sym: str, rows: dict, limit: int = 7, target_cap: float | None = None):
    """(picked, used): `picked` = scanned-company rows (best first, at most `limit`), `used` = the sources that gave at least one of them
    (labels). Empty when no source knows the company."""
    from screens import quarterly
    from tools import yahoo_industry
    from tools.nse_sector_map import get_nse_sector

    q = quarterly.load()
    yd = yahoo_industry.load()
    me_cap = target_cap
    if me_cap is None:
        me_cap = (rows.get(sym) or {}).get("market_cap_cr")
    my = {
        "screener_industry": _screener_label(q, sym),
        "yahoo_industry": (yd.get(sym) or {}).get("industry"),
        "nse_sector": get_nse_sector(sym),
    }
    my_similar = set((yd.get(sym) or {}).get("similar") or [])
    votes: dict[str, dict] = {}
    for s, r in rows.items():
        cap = r.get("market_cap_cr")
        if s == sym or not isinstance(cap, (int, float)) or cap <= 0:
            continue
        v = set()
        if my["screener_industry"] and _screener_label(q, s) == my["screener_industry"]:
            v.add("screener_industry")
        if my["yahoo_industry"] and (yd.get(s) or {}).get("industry") == my["yahoo_industry"]:
            v.add("yahoo_industry")
        if s in my_similar or sym in set((yd.get(s) or {}).get("similar") or []):
            v.add("yahoo_similar")
        if my["nse_sector"] and r.get("sector") == my["nse_sector"]:
            v.add("nse_sector")
        if v:
            votes[s] = {"row": r, "v": v}

    def dist(r):
        cap = r["market_cap_cr"]
        return abs(math.log(cap / me_cap)) if isinstance(me_cap, (int, float)) and me_cap > 0 else -cap     # unknown own cap: bigger first

    ranked = sorted(votes.values(), key=lambda x: (-len(x["v"]), dist(x["row"])))[:limit]
    used = [LABELS[k] for k in LABELS if any(k in x["v"] for x in ranked)]
    return [x["row"] for x in ranked], used
