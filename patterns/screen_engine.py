"""Filtering, sorting, sector rotation and backtests over the per-stock files written by patterns/scan.py.

A stock matches a list filter (index, sector, pattern status, moving-average periods) when it satisfies at least one ticked
option; nothing ticked means no restriction. A range filter ({min, max}) with either bound set never matches a stock whose
value is unknown - an unknown value is not treated as zero."""
from __future__ import annotations

import time
import math
import statistics
from collections import Counter
from datetime import datetime, timezone

from . import market_lists, scan
from .features import HORIZONS, MA_PERIODS, ADR_DAYS, UPTREND_PERIODS

IST = 19800
DAY = 86400
_STATUS_RANK = {"awaiting_breakout": 0, "forming": 1, "confirmed": 2}
RRG_QUADRANTS = ("leading", "improving", "weakening", "lagging")
RRG_WINDOW = 10
NEAR_HIGH_SESSIONS = (1, 5, 10, 21, 63, 126)
UPTREND_MONTHS = (1, 2, 3, 6)
SPECIAL = {"all", "horizontal-resistance", "multi"} | set(market_lists.SCANNERS)   # scanners that are not one chart pattern

# range filters: filter key -> how to read the value from a stock row
RANGE_FIELDS = {
    "mcap": lambda r: r.get("market_cap_cr"),
    "price": lambda r: r.get("price"),
    "rs": lambda r: r.get("rs"),
    "pct_52w_low": lambda r: r.get("pct_from_52w_low"),
    "pct_52w_high": lambda r: r.get("pct_from_52w_high"),
    "pct_ath": lambda r: r.get("pct_from_ath"),
    "free_float": lambda r: r.get("free_float"),
    "turnover": lambda r: r.get("turnover_30d_cr"),
    "avg_volume": lambda r: r.get("avg_volume_30d"),
    "pe": lambda r: r.get("pe"),
    "eps_growth": lambda r: r.get("eps_growth"),
    "debt_equity": lambda r: r.get("debt_equity"),
    "promoter": lambda r: r.get("promoter"),
    "div_yield": lambda r: r.get("div_yield"),
    "net_profit": lambda r: r.get("net_profit_cr"),
    "volatility": lambda r: r.get("volatility"),
    "ret_1m": lambda r: r.get("ret_1m"),
    "ret_3m": lambda r: r.get("ret_3m"),
    "ret_6m": lambda r: r.get("ret_6m"),
    "ret_1y": lambda r: r.get("ret_1y"),
    "ret_3y": lambda r: r.get("ret_3y"),
    "ret_5y": lambda r: r.get("ret_5y"),
    # derived by market_lists.annotate() on every search
    "rvol": lambda r: r.get("rvol"),
    "gap_pct": lambda r: r.get("gap_pct"),
    "range_20d": lambda r: r.get("range_20d"),
    "vs_ema10": lambda r: r.get("vs_ema10"),
    "rs_1m": lambda r: r.get("rs_1m"),
    "rs_3m": lambda r: r.get("rs_3m"),
    # quarterly results (Screener) and exchange data
    **{k: (lambda k: (lambda r: r.get(k)))(k) for k in (
        "eps_qoq", "eps_yoy", "np_qoq", "np_yoy", "sales_qoq", "sales_yoy", "opm_qoq_pp", "opm_yoy_pp", "opm_ttm", "roe", "roce",
        "sales_cagr_5y", "peg", "np_pos_streak", "eps_incr_streak", "np_incr_streak", "sales_incr_streak", "opm_incr_streak",
        "fii_qoq_pp", "float_cr", "ind_rank_1w", "ind_rank_1m", "ind_rank_3m", "turnover_20d_cr")},
}

# yes/no filters: flag id -> test on the row; every ticked flag must hold. "exclude" flags remove only stocks KNOWN to be on the list.
FLAGS = {
    "code33": lambda r: r.get("f_code33") is True,
    "np_turnaround": lambda r: r.get("f_np_turnaround") is True,
    "eps_last_gt_prev": lambda r: r.get("f_eps_last_gt_prev") is True,
    "latest_quarter": lambda r: r.get("f_latest_quarter") is True,
    "fii_up": lambda r: r.get("f_fii_up") is True,
    "fno": lambda r: r.get("fno") is True,
    "exclude_asm": lambda r: not r.get("asm"),
    "exclude_circuit5": lambda r: r.get("band") != "5",
    "exclude_circuit2": lambda r: r.get("band") != "2",
    "block_deal": lambda r: r.get("block_recent") is True,
    "results_soon": lambda r: r.get("results_soon") is True,
    "fvg_daily": lambda r: r.get("fvg_d") is True,
    "fvg_weekly": lambda r: r.get("fvg_w") is True,
}

SORTS = {
    "market_cap": ("market_cap_cr", -1), "rs": ("rs", -1), "ret_1m": ("ret_1m", -1), "ret_3m": ("ret_3m", -1),
    "pct_52w_high": ("pct_from_52w_high", 1), "turnover": ("turnover_30d_cr", -1), "pe": ("pe", 1),
}


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _in_range(val, spec) -> bool:
    lo, hi = (spec or {}).get("min"), (spec or {}).get("max")
    if lo is None and hi is None:
        return True
    if not _num(val):
        return False
    return (lo is None or val >= lo) and (hi is None or val <= hi)


def _any_of(values: list, have: list) -> bool:
    """A stock matches when it has at least one ticked option; nothing ticked means no restriction."""
    return not values or any(v in set(have) for v in values)


def _ma_ok(row: dict, kind: str, spec: dict) -> bool:
    periods = [str(p) for p in (spec or {}).get("periods") or []]
    if not periods:
        return True
    price = row.get("price")
    side = (spec or {}).get("side", "above")
    for p in periods:
        v = (row.get(kind) or {}).get(p)
        if _num(v) and _num(price) and (price > v if side == "above" else price < v):
            return True
    return False


# ------------------------------------------------------------------ sector rotation (RRG)
def _day(t: int) -> int:
    return (t + IST) // DAY


def _zscore(series: list[float], w: int) -> list[float]:
    out = []
    for i in range(w - 1, len(series)):
        win = series[i - w + 1:i + 1]
        m = math.fsum(win) / w
        sd = math.sqrt(math.fsum((x - m) * (x - m) for x in win) / w)     # population standard deviation (statistics.pstdev used exact fractions: 100x slower)
        out.append(100.0 + (series[i] - m) / sd if sd else 100.0)
    return out


_rrg_cache: dict = {}


def rrg_quadrants(rows: dict, timeframe: str = "daily", benchmark: str = "nifty50", trail: int = 0, group: str = "sector") -> dict:
    """{sector: {quadrant, ratio, momentum}}: the sector (equal-weighted average of its stocks) against the benchmark index.
    RS = sector level / benchmark level; RS-Ratio and RS-Momentum are z-scores (around 100) of RS and of the ratio over 10
    periods; Leading = both >= 100, Weakening = ratio >= 100 only, Lagging = neither, Improving = momentum >= 100 only.
    An open approximation of the rotation graph, not the licensed JdK formula."""
    bench = scan.benchmarks().get(benchmark)
    if not bench:
        return {}
    key = (len(rows), timeframe, benchmark, bench[-1][0], trail, group)
    hit = _rrg_cache.get(key)
    if hit and time.time() - hit[0] < 300:        # the rows are re-read while a rescan runs: do not recompute the rotation for each one
        return hit[1]
    bdays = {_day(t): c for t, c in bench}
    sums: dict = {}
    for r in rows.values():
        cl = r.get("closes") or []
        for (_, c0), (t1, c1) in zip(cl, cl[1:]):
            if c0 and c1:
                if not r.get(group):
                    continue
                s = sums.setdefault(r[group], {}).setdefault(_day(t1), [0.0, 0])
                s[0] += c1 / c0 - 1.0
                s[1] += 1
    out = {}
    for sector, byday in sums.items():
        level, rs = 100.0, []
        for d in sorted(byday):
            if d not in bdays or byday[d][1] < 3:
                continue
            level *= 1.0 + byday[d][0] / byday[d][1]
            rs.append((d, level / bdays[d]))
        if timeframe == "weekly":                      # last reading of each week
            wk: dict = {}
            for d, v in rs:
                wk[(d + 3) // 7] = v
            series = [wk[k] for k in sorted(wk)]
        else:
            series = [v for _, v in rs]
        if len(series) < 2 * RRG_WINDOW:
            continue
        ratio = _zscore(series, RRG_WINDOW)
        mom = _zscore(ratio, RRG_WINDOW)
        a, m = ratio[-1], mom[-1]
        out[sector] = {"quadrant": ("leading" if m >= 100 else "weakening") if a >= 100 else ("improving" if m >= 100 else "lagging"),
                       "ratio": round(a, 2), "momentum": round(m, 2)}
        if trail:                                      # the last `trail` (ratio, momentum) points: the sector's path on the rotation graph
            out[sector]["trail"] = [[round(x, 2), round(y, 2)] for x, y in zip(ratio[-trail:], mom[-trail:])]
    _rrg_cache[key] = (time.time(), out)
    for k in [k for k, v in _rrg_cache.items() if time.time() - v[0] > 900]:
        del _rrg_cache[k]
    return out


# ------------------------------------------------------------------ options for the filter UI
def _median(vals):
    vals = sorted(vals)
    return vals[len(vals) // 2] if vals else None


def options() -> dict:
    rows = _rows()
    uni = scan.universe()

    def bounds(fn):
        vs = [fn(r) for r in rows.values() if _num(fn(r))]
        return {"min": min(vs) if vs else None, "max": max(vs) if vs else None}

    return {
        "indices": [{"id": k, "label": v} for k, v in scan.INDEX_LABEL.items()],
        "sectors": sorted({u["sector"] for u in uni if u.get("sector")}),
        "ma_periods": list(MA_PERIODS),
        "statuses": [{"id": "forming", "label": "Forming"}, {"id": "awaiting_breakout", "label": "Awaiting breakout"},
                     {"id": "confirmed", "label": "Confirmed (last %d sessions)" % scan.CONFIRMED_WINDOW_BARS}],
        "industries": [{"name": k, "stocks": v} for k, v in sorted(Counter(r.get("industry") for r in rows.values() if r.get("industry")).items())],
        "market_cap_cr": bounds(RANGE_FIELDS["mcap"]),
        "price": bounds(RANGE_FIELDS["price"]),
        "near_high_sessions": list(NEAR_HIGH_SESSIONS),
        "uptrend": {"periods": list(UPTREND_PERIODS), "months": list(UPTREND_MONTHS)},
        "adr_days": list(ADR_DAYS),
        "rrg": {"quadrants": list(RRG_QUADRANTS), "timeframes": ["daily", "weekly"],
                "benchmarks": [{"id": "nifty50", "label": "Nifty 50"}, {"id": "nifty500", "label": "Nifty 500"}],
                "available": bool(scan.benchmarks())},
        "resistance_states": [{"id": "near", "label": "Near (up to 5% below)"}, {"id": "breakout", "label": "Breakout (last 3 sessions)"}],
        "fundamentals_have": sum(1 for r in rows.values() if _num(r.get("pe"))),
        "fundamentals_yahoo": sum(1 for r in rows.values() if r.get("fund_src") == "yahoo"),
        "fundamentals_as_of": _median([r["fund_at"] for r in rows.values() if _num(r.get("fund_at"))]),
        "fundamentals_stale": sum(1 for r in rows.values() if not _num(r.get("fund_at")) or time.time() - r["fund_at"] > 48 * 3600),
    }


# ------------------------------------------------------------------ the screen
def _stock_passes(r: dict, f: dict, quad: dict | None, state: bool = True) -> bool:
    """Every filter that describes the stock itself (not the pattern it shows). `state=False` leaves out the horizontal
    resistance filter, which describes where the stock is right now (used by the backtest)."""
    ind, sec = f.get("indices") or {}, f.get("sectors") or {}
    if ind.get("values") and not _any_of(ind["values"], [r.get("index")] if r.get("index") else []):
        return False
    if sec.get("values") and not _any_of(sec["values"], [r.get("sector")]):
        return False
    for key, getter in RANGE_FIELDS.items():
        if key in f and not _in_range(getter(r), f[key]):
            return False
    if not _ma_ok(r, "ema", f.get("ema")) or not _ma_ok(r, "sma", f.get("dma")):
        return False
    if (f.get("ma200_turn") or {}).get("require") and r.get("ma200_turn") is not True:
        return False
    for fid in (f.get("flags") or {}).get("values") or []:
        test = FLAGS.get(fid)
        if test and not test(r):
            return False
    inds = (f.get("industries") or {}).get("values")
    if inds and r.get("industry") not in inds:
        return False
    la = (f.get("listed_after") or {}).get("date")
    if la and not (r.get("listed") and r["listed"] > la):
        return False
    nh = f.get("near_high")
    if nh and nh.get("sessions"):
        d = r.get("new_high_days")
        if not (_num(d) and d <= nh["sessions"]):
            return False
    mo = f.get("ma_order")
    if mo and len(mo.get("periods") or []) >= 2:
        vals = [(r.get(mo.get("kind", "sma")) or {}).get(str(p)) for p in mo["periods"]]
        if not all(_num(v) for v in vals) or any(vals[i] < vals[i + 1] for i in range(len(vals) - 1)):
            return False
    up = f.get("ma_uptrend")
    if up and up.get("period"):
        d = (r.get("ma_up_days") or {}).get(str(up["period"]))
        if not (_num(d) and d >= int(up.get("months") or 1) * 21):
            return False
    adr = f.get("adr")
    if adr and adr.get("min") is not None:
        v = (r.get("adr") or {}).get(str(adr.get("days") or 5))
        if not (_num(v) and v > adr["min"]):
            return False
    rr = f.get("rrg")
    if rr and rr.get("quadrants"):
        q = (quad or {}).get(r.get("sector"))
        if not q or q["quadrant"] not in rr["quadrants"]:
            return False
    if state:
        res = f.get("resistance")
        if res and res.get("require"):
            have = r.get("resistance")
            if not have or (res.get("states") and have["state"] not in res["states"]):
                return False
    return True


def _sort_key(sort: str):
    field, direction = SORTS[sort]
    return lambda x: (x.get(field) is None, direction * (x.get(field) or 0))


def _markers(r: dict) -> list:
    """Small flags shown beside a stock: ASM stage, a 2%/5% price band, a recent block deal, results due soon."""
    m = []
    if r.get("asm"):
        m.append({"k": "asm", "label": "ASM " + str(r["asm"])})
    if r.get("band") in ("2", "5"):
        m.append({"k": "band", "label": r["band"] + "% band"})
    if r.get("block_recent"):
        m.append({"k": "block", "label": "Block deal"})
    if r.get("results_soon"):
        m.append({"k": "results", "label": "Results soon"})
    return m


def _rows() -> dict:
    rows = scan._load_all()
    market_lists.annotate(rows)
    try:  # keep the exchange feeds and the Screener quarterly data fresh in the background (never blocks a search)
        from . import exchange_data
        from screens import quarterly
        exchange_data.ensure_fresh()
        quarterly.ensure_fresh()
    except Exception:
        pass
    return rows


def search(pattern, f: dict, include_candles: bool = False) -> dict:
    """See the module docstring; `pattern` may be a chart pattern id, "all", "horizontal-resistance", "multi" (f["scans"]["values"]) or a market-list scanner id."""
    rows = _rows()
    pat = None if pattern in (None, "") or pattern in SPECIAL else pattern
    f = dict(f or {})
    # The Create Screener can also be limited to stocks showing any of several chart patterns (f["patterns"]["values"]).
    multi = set((f.get("patterns") or {}).get("values") or []) if pattern == "all" else set()
    lst = pattern if pattern in market_lists.SCANNERS else None                     # a market-list scanner (gainers, gaps, ...)
    only = {str(x).upper() for x in ((f.get("symbols") or {}).get("values") or [])}      # Watchlist: restrict to these tickers
    scans = list((f.get("scans") or {}).get("values") or []) if pattern == "multi" else []   # Multiple Scans: stocks in ALL of these
    bench = (scan.benchmarks().get("nifty500") or None) if (lst == "rs-high-before-price-high" or scans) else None
    if pattern == "horizontal-resistance":
        f["resistance"] = {**(f.get("resistance") or {}), "require": True}
    quad = None
    if (f.get("rrg") or {}).get("quadrants"):
        quad = rrg_quadrants(rows, f["rrg"].get("timeframe", "daily"), f["rrg"].get("benchmark", "nifty50"))
    stat = f.get("status") or {}
    q = (f.get("q") or "").strip().lower()
    out = []
    for r in rows.values():
        if only and r["symbol"].upper() not in only:
            continue
        occ = []
        if pat or multi:
            occ = [o for o in r["occurrences"] if (o["pattern"] == pat if pat else o["pattern"] in multi)]
            if not occ:
                continue
            if stat.get("values") and not _any_of(stat["values"], [o["status"] for o in occ]):
                continue
            if stat.get("values"):
                occ = [o for o in occ if o["status"] in stat["values"]] or occ
        sig, matched = None, []
        if lst:
            sig = market_lists.evaluate(lst, r, bench)
            if sig is None:
                continue
        if pattern == "multi":
            if not scans:
                continue
            ok, occ = True, []
            for sid in scans:
                if sid in market_lists.SCANNERS:
                    hit = market_lists.evaluate(sid, r, bench) is not None
                elif sid == "horizontal-resistance":
                    res = r.get("resistance")
                    states = (f.get("resistance") or {}).get("states")
                    hit = bool(res) and (not states or res["state"] in states)
                else:
                    mine = [o for o in r["occurrences"] if o["pattern"] == sid]
                    if stat.get("values"):
                        mine = [o for o in mine if o["status"] in stat["values"]]
                    hit = bool(mine)
                    if hit and not occ:
                        occ = mine[:1]
                if not hit:
                    ok = False
                    break
                matched.append(sid)
            if not ok:
                continue
        if not _stock_passes(r, f, quad):
            continue
        if q and q not in r["symbol"].lower() and q not in (r.get("name") or "").lower():
            continue
        best = (sorted(occ, key=lambda o: (_STATUS_RANK.get(o["status"], 9), -(o.get("end_ts") or 0)))[0] if occ else None)
        row = {k: r.get(k) for k in ("symbol", "name", "sector", "index", "price", "market_cap_cr", "ret_1m", "ret_3m", "ret_1y",
                                      "pct_from_52w_high", "pct_from_52w_low", "pct_from_ath", "rs", "turnover_30d_cr", "pe",
                                      "eps_growth", "debt_equity", "promoter", "div_yield", "net_profit_cr", "free_float", "as_of")}
        row["adr5"] = (r.get("adr") or {}).get("5")
        row["resistance"] = r.get("resistance")
        row["occurrence"] = best
        row["occurrence_count"] = len(occ)
        row["signal"] = sig
        row["matched"] = matched or None
        row["industry"] = r.get("industry")
        row["listed"] = r.get("listed")
        row["markers"] = _markers(r)
        out.append(row)
    has_occ = bool(pat or multi)
    sort = f.get("sort") or ("status" if has_occ else ("signal" if lst else "market_cap"))
    if sort == "name":
        out.sort(key=lambda x: x["name"] or x["symbol"])
    elif sort == "signal" and lst:
        direction = market_lists.SCANNERS[lst][3]
        out.sort(key=lambda x: direction * x["signal"]["value"])
    elif sort == "status" and has_occ:
        out.sort(key=lambda x: (_STATUS_RANK.get(x["occurrence"]["status"], 9), -(x["market_cap_cr"] or -1)))
    else:
        out.sort(key=_sort_key(sort if sort in SORTS else "market_cap"))
    page = max(1, int(f.get("page") or 1))
    size = min(100, max(1, int(f.get("page_size") or 50)))
    page_rows = out[(page - 1) * size: page * size]
    if include_candles:
        for row in page_rows:
            row["candles"] = rows[row["symbol"]]["candles"]
    quad_default = rrg_quadrants(rows) if scan.benchmarks() else {}
    for row in page_rows:
        row["quadrant"] = (quad_default.get(row["sector"]) or {}).get("quadrant")
    return {"pattern": pattern, "total": len(out), "page": page, "page_size": size, "rows": page_rows, "scan": scan.status()}


# ------------------------------------------------------------------ backtest
def _stats(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0}
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v <= 0]
    return {
        "n": len(vals), "win_rate": round(len(wins) / len(vals) * 100.0, 1), "avg": round(statistics.fmean(vals), 2),
        "median": round(statistics.median(vals), 2), "best": round(max(vals), 2), "worst": round(min(vals), 2),
        "avg_win": round(statistics.fmean(wins), 2) if wins else None,
        "avg_loss": round(statistics.fmean(losses), 2) if losses else None,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) < 0 else None,
    }


def _histogram(vals: list[float]) -> list[dict]:
    edges = [x * 2.5 for x in range(-8, 9)]                    # -20% .. +20% in 2.5% steps, open-ended at both ends
    bins = [{"lo": None, "hi": edges[0], "n": 0}] + [{"lo": edges[i], "hi": edges[i + 1], "n": 0} for i in range(len(edges) - 1)] + \
           [{"lo": edges[-1], "hi": None, "n": 0}]
    for v in vals:
        for b in bins:
            if (b["lo"] is None or v >= b["lo"]) and (b["hi"] is None or v < b["hi"]):
                b["n"] += 1
                break
    return bins


def backtest(pattern: str, f: dict) -> dict:
    """What happened after this pattern confirmed, across the scanned stocks that pass the stock-level filters: each
    confirmation is a trade entered at the confirming close, in the pattern's direction, measured 5-60 bars later.
    It is a study of the past five years of the stocks that exist TODAY (no delisted names, no costs, trades from one stock
    can overlap) - not a promise about the future."""
    rows = _rows()
    f = dict(f or {})
    h = int(f.get("horizon") or 20)
    if h not in HORIZONS:
        h = 20
    col = 4 + HORIZONS.index(h)
    quad = None
    if (f.get("rrg") or {}).get("quadrants"):
        quad = rrg_quadrants(rows, f["rrg"].get("timeframe", "daily"), f["rrg"].get("benchmark", "nifty50"))
    stocks = [r for r in rows.values() if _stock_passes(r, f, quad, state=False)]
    pats = set((f.get("patterns") or {}).get("values") or []) if pattern == "all" else set()
    trades = [(r["symbol"], r["name"], t) for r in stocks for t in (r.get("trades") or [])
              if (t[0] in pats if pats else pattern == "all") or t[0] == pattern]
    stats = {str(hh): _stats([t[4 + i] for _, _, t in trades if t[4 + i] is not None]) for i, hh in enumerate(HORIZONS)}
    at_h = [t[col] for _, _, t in trades if t[col] is not None]
    years: dict = {}
    for _, _, t in trades:
        y = datetime.fromtimestamp(t[2] + IST, timezone.utc).year
        years.setdefault(y, []).append(t[col])
    by_year = [{"year": y, **{k: v for k, v in _stats([x for x in vs if x is not None]).items() if k in ("n", "win_rate", "avg")}}
               for y, vs in sorted(years.items())]
    ordered = sorted(trades, key=lambda x: -x[2][2])
    page = max(1, int(f.get("page") or 1))
    size = min(100, max(1, int(f.get("page_size") or 25)))
    return {
        "pattern": pattern, "horizon": h, "horizons": list(HORIZONS), "stocks": len(stocks),
        "stocks_with_trades": len({s for s, _, _ in trades}), "trades_total": len(trades),
        "directions": {d: sum(1 for _, _, t in trades if t[1] == d) for d in ("bullish", "bearish")},
        "stats": stats, "histogram": _histogram(at_h), "by_year": by_year,
        "page": page, "page_size": size,
        "trades": [{"symbol": s, "name": n, "direction": t[1], "confirmed_ts": t[2], "entry": t[3],
                    "returns": dict(zip([str(x) for x in HORIZONS], t[4:]))} for s, n, t in ordered[(page - 1) * size: page * size]],
        "scan": scan.status(),
    }
