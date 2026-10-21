"""Per-company screening metrics from sources the backend already uses: the Screener page parse
(fundamentals, shareholding) and daily price history (returns, volume, volatility).

Every metric is None when it cannot be computed from real data - never 0."""
from __future__ import annotations

import math

DAY = 86400


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x)) else None


def _return(candles: list[dict], days: int) -> float | None:
    """% price return over `days`, only when the history actually reaches back that far."""
    if not candles or len(candles) < 2:
        return None
    last = candles[-1]
    target = last["time"] - days * DAY
    if candles[0]["time"] > target + 5 * DAY:
        return None
    base = next((c for c in reversed(candles) if c["time"] <= target), None)
    return (last["close"] / base["close"] - 1.0) * 100.0 if base and base["close"] else None


def _eps_cagr(income: dict) -> float | None:
    """Annual diluted-EPS CAGR in % between the first and last positive EPS (needs >= 3 years)."""
    pts = [(k, v.get("Diluted EPS")) for k, v in sorted(income.items())]
    pts = [(k, e) for k, e in pts if isinstance(e, (int, float)) and e > 0]
    if len(pts) < 3:
        return None
    years = len(pts) - 1
    return ((pts[-1][1] / pts[0][1]) ** (1.0 / years) - 1.0) * 100.0


def compute(fin: dict | None, candles: list[dict] | None) -> dict:
    info = (fin or {}).get("info") or {}
    arrays = (fin or {}).get("financial_arrays") or {}
    price = None
    if candles:
        price = _num(candles[-1].get("close"))
    if price is None:
        price = _num(info.get("currentPrice"))

    # trailing-12-month EPS: the last four reported quarters, only if all four are known
    q = [v.get("Diluted EPS") for _, v in sorted((arrays.get("quarterly_income_stmt") or {}).items())][-4:]
    eps = sum(q) if len(q) == 4 and all(isinstance(x, (int, float)) for x in q) else None

    y = _num(info.get("dividendYield"))
    div_yield = y * 100.0 if y is not None else None
    dps = div_yield / 100.0 * price if (div_yield is not None and price) else None
    payout = (dps / eps * 100.0) if (dps and eps and eps > 0) else None
    cover = (eps / dps) if (dps and eps and eps > 0) else None

    de = None
    bs = arrays.get("balance_sheet") or {}
    for period in sorted(bs, reverse=True):
        debt, eq = bs[period].get("Total Debt"), bs[period].get("Stockholders Equity")
        if isinstance(debt, (int, float)) and isinstance(eq, (int, float)) and eq > 0:
            de = debt / eq
            break

    inc = arrays.get("income_stmt") or {}
    latest = inc[max(inc)] if inc else {}
    np_inr = _num(latest.get("Net Income"))

    promoter = ((fin or {}).get("shareholding") or {}).get("latest", {}).get("promoter")

    vol = avg_vol = None
    if candles and len(candles) > 30:
        vols = [c.get("volume") for c in candles[-20:]]
        if all(isinstance(v, (int, float)) and v > 0 for v in vols):
            avg_vol = sum(vols) / len(vols)
        closes = [c["close"] for c in candles[-251:]]
        if len(closes) >= 200:
            rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
            if len(rets) >= 150:
                m = sum(rets) / len(rets)
                vol = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1)) * math.sqrt(250) * 100.0

    return {
        "price": price,
        "eps": eps,
        "pe": _num(info.get("trailingPE")),
        "market_cap_cr": round(info["marketCap"] / 1e7, 2) if _num(info.get("marketCap")) else None,
        "promoter": _num(promoter),
        "div_yield": div_yield,
        "payout": payout,
        "cover": cover,
        "debt_equity": de,
        "net_profit_cr": np_inr / 1e7 if np_inr is not None else None,
        "eps_growth": _eps_cagr(inc),
        "ret_1m": _return(candles or [], 30),
        "ret_1y": _return(candles or [], 365),
        "ret_3y": _return(candles or [], 1096),
        "ret_5y": _return(candles or [], 1826),
        "avg_volume": avg_vol,
        "volatility": vol,
    }
