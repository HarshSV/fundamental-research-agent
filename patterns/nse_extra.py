"""NSE-listed companies outside the sector-mapped universe (the Nifty Total Market, about 750 stocks), so the scan covers the whole NSE main board.

The list is NSE's own: every symbol in the newest daily price file (patterns/nse_prices.py) trading in the EQ or BE series, which also has a company name in
the NSE company master (EQUITY_L.csv, cache/nse_company_names.json). Funds and ETFs have no row in that master, so they drop out here. SME-board
companies (SM / ST series) are not included. Nothing is guessed: a company with no name or sector is still scanned, and its sector stays None."""
from __future__ import annotations

import csv
import io
import json
import os

from . import nse_prices

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAMES = os.path.join(ROOT, "cache", "nse_company_names.json")
BOARD = ("EQ", "BE")


def _latest_file() -> str | None:
    files = nse_prices.dated_files()
    if not files:
        return None
    return os.path.join(nse_prices.DIR, files[-1])


def symbols() -> set[str]:
    """Main-board symbols that traded in the newest NSE file."""
    path = _latest_file()
    if not path:
        return set()
    out = set()
    with open(path, encoding="utf-8") as fh:
        for x in csv.DictReader(io.StringIO(fh.read())):
            x = {(k or "").strip(): (v or "").strip() for k, v in x.items()}
            if x.get("SERIES") in BOARD and x.get("SYMBOL"):
                out.add(x["SYMBOL"])
    return out


def load(exclude: set[str]) -> list[dict]:
    """[{symbol, name, sector: None, exchange: 'NSE'}] for NSE main-board companies not in `exclude`."""
    try:
        with open(NAMES, encoding="utf-8") as fh:
            names = json.load(fh)
    except Exception:
        return []
    return [{"symbol": s, "name": names[s], "sector": None, "exchange": "NSE"} for s in sorted(symbols()) if s in names and s not in exclude]
