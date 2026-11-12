"""BSE-only companies for the market scan.

Reads BSE's own "List of Securities" (Equity, Active; saved by hand/pane as data/bse/bse_equity_active.json) and NSE's ISIN list
(data/bse/nse_isin.json, from EQUITY_L.csv), and writes data/bse/bse_only_universe.json: every active BSE equity that is not on NSE
(matched by ISIN), with the Yahoo ticker the scan prices it by (`<BSE trading symbol>.BO`; the numeric code does not work there).

Left out, on purpose: mutual-fund / ETF units (not companies) and a company whose BSE trading symbol is also an NSE symbol of a
different company (its Yahoo ticker would be ambiguous). Nothing is guessed: a missing market cap stays None.
"""
from __future__ import annotations

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, "data", "bse")
OUT = os.path.join(DIR, "bse_only_universe.json")
_FUND = re.compile(r"mutual fund|asset management|\betf\b|exchange traded|index fund|\breit\b|\binvit\b|bees\b", re.I)
_RIGHTS = re.compile(r"-RE\d?$")        # a rights entitlement (a temporary right to buy new shares), not a company


def build() -> list[dict]:
    with open(os.path.join(DIR, "bse_equity_active.json"), encoding="utf-8") as fh:
        rows = json.load(fh)
    with open(os.path.join(DIR, "nse_isin.json"), encoding="utf-8") as fh:
        nse = json.load(fh)["nse_isin"]                       # isin -> NSE symbol
    nse_syms = set(nse.values())
    out = []
    for x in rows:
        if x.get("isin") in nse or _FUND.search(x.get("n") or ""):
            continue
        sym = (x.get("id") or "").strip().upper()
        if not sym or sym in nse_syms or _RIGHTS.search(sym):
            continue
        try:
            mc = float(x["mc"])
        except (KeyError, TypeError, ValueError):
            mc = None                                          # unknown stays unknown
        out.append({"symbol": sym, "name": (x.get("n") or sym).strip(), "code": x["c"], "isin": x.get("isin"),
                    "mktcap_cr": mc, "yahoo": f"{sym}.BO"})
    out.sort(key=lambda r: r["symbol"])
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    return out


def load() -> list[dict]:
    try:
        with open(OUT, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return []


_info_cache: dict = {}


def info() -> dict:
    """{symbol: {code, name, yahoo, mktcap_cr}} for the BSE-only companies (re-read when the file changes)."""
    try:
        mt = os.path.getmtime(OUT)
    except OSError:
        return {}
    if _info_cache.get("mt") != mt:
        _info_cache.update(mt=mt, data={b["symbol"]: b for b in load()})
    return _info_cache["data"]


def prime(sym: str) -> bool:
    """Teach this process how to reach a BSE-only company: Screener by its BSE code, Yahoo by its trading symbol. A worker process has
    no company master loaded, so without this the symbol would be tried as an NSE one. False for an NSE company."""
    b = info().get(sym)
    if not b:
        return False
    try:
        from tools import live_chart_yf, screener_scraper
        live_chart_yf._TICKER_CACHE[sym] = b["yahoo"]
        screener_scraper._SYMBOL_MAP.setdefault(sym, b["code"])
    except Exception:
        pass
    return True


if __name__ == "__main__":
    print("BSE-only scan universe:", len(build()))
