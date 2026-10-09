"""Daily-track universe: EXPLICIT and CONFIGURABLE (no architecture change to expand).

Default = the 8 validated pilot symbols + 40 additional liquid, sector-representative NSE equities.
Override without touching code: write data/forecast/daily_universe.json
    {"symbols": ["RELIANCE", ...], "sector_map": {"RELIANCE": "NIFTY ENERGY"}, "indices": ["NIFTY 50", ...]}
"""
import json
import os

from .. import config

PILOT = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "ITC", "LT"]

EXTRA = [
    "HINDUNILVR", "BHARTIARTL", "KOTAKBANK", "AXISBANK", "BAJFINANCE", "BAJAJFINSV", "MARUTI", "SUNPHARMA",
    "TITAN", "ULTRACEMCO", "NESTLEIND", "ASIANPAINT", "HCLTECH", "WIPRO", "TECHM", "NTPC", "POWERGRID", "ONGC",
    "COALINDIA", "TATASTEEL", "JSWSTEEL", "HINDALCO", "ADANIENT", "ADANIPORTS", "M&M", "DRREDDY", "CIPLA",
    "BRITANNIA", "GRASIM", "EICHERMOT", "HEROMOTOCO", "BPCL", "IOC", "DIVISLAB", "APOLLOHOSP", "INDUSINDBK",
    "SBILIFE", "HDFCLIFE", "TATACONSUM", "BAJAJ-AUTO",
]

# Market + sector context indices (resolved from the Angel scrip master by name; anything that does not resolve is
# simply absent -> its features are NaN, never guessed).
MARKET_INDEX = "NIFTY 50"
INDICES = ["NIFTY 50", "NIFTY BANK", "NIFTY IT", "NIFTY PHARMA", "NIFTY AUTO", "NIFTY FMCG", "NIFTY METAL", "NIFTY ENERGY"]

SECTOR_MAP = {
    **{s: "NIFTY BANK" for s in ("HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "INDUSINDBK")},
    **{s: "NIFTY IT" for s in ("TCS", "INFY", "HCLTECH", "WIPRO", "TECHM")},
    **{s: "NIFTY PHARMA" for s in ("SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB")},
    **{s: "NIFTY AUTO" for s in ("MARUTI", "M&M", "EICHERMOT", "HEROMOTOCO", "BAJAJ-AUTO")},
    **{s: "NIFTY FMCG" for s in ("ITC", "HINDUNILVR", "NESTLEIND", "BRITANNIA", "TATACONSUM")},
    **{s: "NIFTY METAL" for s in ("TATASTEEL", "JSWSTEEL", "HINDALCO")},
    **{s: "NIFTY ENERGY" for s in ("RELIANCE", "ONGC", "BPCL", "IOC", "NTPC", "POWERGRID", "COALINDIA")},
}

HISTORY_START = "2000-01-01"          # daily history is requested from here (provider depth verified to 1995)
OVERRIDE_PATH = os.path.join(config.DATA_DIR, "daily_universe.json")


def load():
    cfg = {"symbols": PILOT + EXTRA, "sector_map": dict(SECTOR_MAP), "indices": list(INDICES), "start": HISTORY_START}
    if os.path.exists(OVERRIDE_PATH):
        cfg.update(json.load(open(OVERRIDE_PATH, encoding="utf-8")))
    cfg["symbols"] = list(dict.fromkeys(cfg["symbols"]))
    return cfg
