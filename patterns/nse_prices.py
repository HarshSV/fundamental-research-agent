"""NSE's official daily prices for the newest sessions, laid over the scan's stored bars.

The scan takes each stock's daily history from Yahoo. Every day up to the last settled one matches the exchange exactly, but the newest session
is a mid-session snapshot for part of the market (checked against NSE's own files: on 23 Nov the high or low differed for 14% of NSE stocks, the open
for 20%, the volume for 39%). A bar that is too narrow looks "inside" the one before it, so setups that read the last bar were wrong.

NSE publishes one file per trading day after the close (sec_bhavdata_full_DDMMYYYY.csv: open, high, low, close, traded quantity per symbol and
series). This module keeps the recent ones on disk, and `patch_rows` replaces the open / high / low / close / volume of a stock's bar for that date
with the exchange's figures. Nothing is invented: a stock or day that NSE has no row for keeps the scan's bar; a stock whose close differs from NSE's by
more than 1% (a split or bonus: NSE prices are not adjusted) is left alone; BSE-only companies are untouched (they are not in the NSE files)."""
from __future__ import annotations

import csv
import io
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "exchange", "bhavcopy")
URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"
KEEP_DAYS = 10                         # trading days kept and laid over
SERIES = ("EQ", "BE", "BZ", "SM", "ST")
MAX_CLOSE_GAP = 0.01                   # a bigger gap between the scan's close and NSE's close: leave the bar alone (corporate action)

ALIAS_URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"
_aliases: dict[str, str] = {}          # old NSE symbol -> its current one (NSE's symbol-change list)
_alias_loaded = 0.0
_days: dict[str, dict] = {}            # ISO date -> {symbol: (o, h, l, c, v)}, parsed once per file
_lock = threading.Lock()
_last_fetch = 0.0
_fetching = False


def _path(d: date) -> str:
    return os.path.join(DIR, f"{d:%Y%m%d}.csv")


def parse(text: str) -> dict:
    """{symbol: (open, high, low, close, volume)} from one bhavcopy file; the EQ row wins when a symbol trades in more than one series."""
    best: dict[str, tuple] = {}
    rank = {s: i for i, s in enumerate(SERIES)}
    for x in csv.DictReader(io.StringIO(text)):
        x = {(k or "").strip(): (v or "").strip() for k, v in x.items()}
        ser = x.get("SERIES")
        if ser not in rank:
            continue
        try:
            row = (float(x["OPEN_PRICE"]), float(x["HIGH_PRICE"]), float(x["LOW_PRICE"]), float(x["CLOSE_PRICE"]), float(x["TTL_TRD_QNTY"]))
        except (KeyError, ValueError):
            continue
        sym = x["SYMBOL"]
        if sym not in best or rank[ser] < best[sym][0]:
            best[sym] = (rank[ser], row)
    return {s: r for s, (_, r) in best.items()}


def dated_files() -> list[str]:
    """The saved daily price files (YYYYMMDD.csv), oldest first; the symbol-change list sits in the same folder."""
    import re
    return sorted(f for f in os.listdir(DIR) if re.fullmatch(r"\d{8}\.csv", f)) if os.path.isdir(DIR) else []


def _load_from_disk() -> None:
    if not os.path.isdir(DIR):
        return
    files = dated_files()[-KEEP_DAYS:]
    for f in files:
        iso = f"{f[:4]}-{f[4:6]}-{f[6:8]}"
        if iso in _days:
            continue
        try:
            with open(os.path.join(DIR, f), encoding="utf-8") as fh:
                _days[iso] = parse(fh.read())
        except Exception:
            continue


def aliases() -> dict[str, str]:
    """{old symbol: new symbol} from NSE's symbol-change list (cached on disk, read again at most daily). A company renamed on NSE (ICICIPRULI to
    ICICILIFE) is still stored under its old symbol by the scan; NSE's price files use the new one."""
    global _aliases, _alias_loaded
    path = os.path.join(DIR, "symbolchange.csv")
    if _aliases and time.monotonic() - _alias_loaded < 3600:
        return _aliases
    try:
        stale = (not os.path.exists(path)) or time.time() - os.path.getmtime(path) > 86400
    except OSError:
        stale = True
    if stale:
        try:
            import requests
            r = requests.get(ALIAS_URL, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"}, timeout=40)
            if r.status_code == 200 and "OLD SYMBOL" in r.text.upper():
                os.makedirs(DIR, exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(r.text)
        except Exception:
            pass
    out: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for x in csv.reader(io.StringIO(fh.read())):
                if len(x) >= 3 and x[1].strip() and x[2].strip() and x[1].strip().upper() != "OLD SYMBOL":
                    out[x[1].strip()] = x[2].strip()
    except Exception:
        pass
    _aliases, _alias_loaded = out, time.monotonic()
    return _aliases


def fetch_recent() -> int:
    """Download the NSE files for the last two weeks that are not on disk yet (a weekend, a holiday or a day not published yet gives no file).
    Returns how many were saved. Network only; call from a background thread."""
    import requests
    os.makedirs(DIR, exist_ok=True)
    saved = 0
    today = datetime.now(IST).date()
    for back in range(0, 15):
        d = today - timedelta(days=back)
        if d.weekday() >= 5 or os.path.exists(_path(d)):
            continue
        try:
            r = requests.get(URL.format(d=f"{d:%d%m%Y}"), headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"}, timeout=40)
        except Exception:
            continue
        if r.status_code == 200 and r.text.startswith("SYMBOL"):
            tmp = _path(d) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(r.text)
            os.replace(tmp, _path(d))
            saved += 1
    return saved


def _refresh_async(every: float = 1800.0) -> None:
    """At most every half hour, read any newly published file in the background."""
    global _last_fetch, _fetching
    if _fetching or time.monotonic() - _last_fetch < every:
        return
    _fetching = True
    _last_fetch = time.monotonic()

    def run():
        global _fetching
        try:
            fetch_recent()
        except Exception as e:
            print(f"[nse_prices] fetch failed: {e}", flush=True)
        finally:
            _fetching = False
    threading.Thread(target=run, daemon=True, name="nse-prices").start()


def patch_rows(rows: dict) -> int:
    """Lay NSE's official bars over the stored bars of NSE-listed stocks, for every date NSE has a file for. Idempotent and cheap (it only
    compares the newest few bars). Returns how many bars changed."""
    with _lock:
        _refresh_async()
        before = len(_days)
        _load_from_disk()
        if not _days:
            return 0
        dates = sorted(_days)[-KEEP_DAYS:]
        alias = aliases()
        changed = 0
        for r in rows.values():
            if r.get("exchange") not in (None, "NSE"):
                continue
            cs = r.get("candles")
            if not cs:
                continue
            tail = range(max(0, len(cs) - KEEP_DAYS - 2), len(cs))
            by_date = {datetime.fromtimestamp(cs[i][0], IST).date().isoformat(): i for i in tail}
            sym = r["symbol"]
            new_sym = alias.get(sym)
            for iso in dates:
                i = by_date.get(iso)
                o = _days[iso].get(sym) or (_days[iso].get(new_sym) if new_sym else None)
                if i is None or o is None:
                    continue
                c = cs[i]
                if not (o[3] > 0 and abs(c[4] / o[3] - 1.0) <= MAX_CLOSE_GAP):
                    continue
                new = [c[0], round(o[0], 2), round(o[1], 2), round(o[2], 2), round(o[3], 2), round(o[4])]
                if c[:6] != new:
                    cs[i] = new
                    changed += 1
                    if i == len(cs) - 1 and isinstance(r.get("price"), (int, float)):
                        r["price"] = new[4]
                    r.pop("_bars", None)             # the scanners' cached copy of the valid bars is rebuilt from the patched candles
        return changed
