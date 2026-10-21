"""The Popular Screens: 23 named screens in five groups, each a conjunction of simple, published criteria.

These thresholds are Navrist's OWN definitions (NSE does not publish the ones behind its screens), kept in
one place so they are easy to review and change. "Absolute" thresholds are plain numbers; "relative"
ones are percentiles of the screened universe (volume, volatility) so they adapt to the market.

A stock matches a screen only if EVERY metric the screen needs is known. An unknown value (no data, or
not computable) is never treated as 0 and never matches.
"""
from __future__ import annotations

THRESHOLDS = {
    "low_price": 150.0,        # Rs
    "high_eps": 15.0,          # Rs, trailing-12-month EPS
    "high_promoter": 60.0,     # % of shares
    "low_debt": 0.5,           # debt / equity
    "low_pe": 15.0,            # and P/E must be positive
    "high_yield": 2.0,         # dividend yield %
    "high_payout": 40.0,       # dividend payout % of EPS
    "high_cover": 3.0,         # EPS / dividend per share
    "ret_1m": 10.0,            # %
    "ret_1y": 20.0,
    "ret_3y": 50.0,
    "ret_5y": 100.0,
    "low_ret_5y": 25.0,
    "high_eps_growth": 15.0,   # % a year, annual EPS CAGR (>= 3 years of data)
    "high_profit_cr": 50.0,    # Rs crore, latest annual net profit
    "volume_pct": 75.0,        # "high volume" = at/above this percentile of average volume
    "vol_pct": 25.0,           # "low volatility" = at/below this percentile of annualised volatility
}

T = THRESHOLDS

# criterion id -> (human text, metric, operator, threshold key)
CRITERIA: dict[str, tuple[str, str, str, str]] = {
    "low_price": ("Price <= Rs %g" % T["low_price"], "price", "<=", "low_price"),
    "high_eps": ("EPS (TTM) >= Rs %g" % T["high_eps"], "eps", ">=", "high_eps"),
    "high_promoter": ("Promoter holding >= %g%%" % T["high_promoter"], "promoter", ">=", "high_promoter"),
    "low_debt": ("Debt/Equity <= %g" % T["low_debt"], "debt_equity", "<=", "low_debt"),
    "low_pe": ("P/E between 0 and %g" % T["low_pe"], "pe", "pos<=", "low_pe"),
    "high_yield": ("Dividend yield >= %g%%" % T["high_yield"], "div_yield", ">=", "high_yield"),
    "high_payout": ("Dividend payout >= %g%% of EPS" % T["high_payout"], "payout", ">=", "high_payout"),
    "high_cover": ("Dividend cover >= %gx (EPS / dividend)" % T["high_cover"], "cover", ">=", "high_cover"),
    "ret_1m": ("1-month return >= %g%%" % T["ret_1m"], "ret_1m", ">=", "ret_1m"),
    "ret_1y": ("1-year return >= %g%%" % T["ret_1y"], "ret_1y", ">=", "ret_1y"),
    "ret_3y": ("3-year return >= %g%%" % T["ret_3y"], "ret_3y", ">=", "ret_3y"),
    "ret_5y": ("5-year return >= %g%%" % T["ret_5y"], "ret_5y", ">=", "ret_5y"),
    "low_ret_5y": ("5-year return <= %g%%" % T["low_ret_5y"], "ret_5y", "<=", "low_ret_5y"),
    "eps_growth": ("EPS growth >= %g%% a year" % T["high_eps_growth"], "eps_growth", ">=", "high_eps_growth"),
    "profit": ("Net profit >= Rs %g Cr" % T["high_profit_cr"], "net_profit_cr", ">=", "high_profit_cr"),
    "high_volume": ("Average volume in the top %g%% of the universe" % (100 - T["volume_pct"]), "avg_volume", "pct>=", "volume_pct"),
    "low_vol": ("Volatility in the lowest %g%% of the universe" % T["vol_pct"], "volatility", "pct<=", "vol_pct"),
}

GROUPS = ["Growth at a Discount", "Income + Safety", "Momentum + Breakout", "Quality & Safety", "Value Growth"]

# (id, group, title, description, [criteria ids])
SCREENS: list[tuple[str, str, str, str, list[str]]] = [
    ("low-price-high-eps", GROUPS[0], "Low Price + High EPS",
     "Low absolute price + high absolute earnings, suitable for low entry prices with solid fundamentals",
     ["low_price", "high_eps"]),
    ("high-promoter-high-eps", GROUPS[0], "High Promoter Holding + High EPS",
     "Strong management + Strong earnings, high conviction growth.", ["high_promoter", "high_eps"]),
    ("high-cover-low-price", GROUPS[0], "High Dividend Cover + Low price",
     "Safe and sustainable dividends + low entry cost", ["high_cover", "low_price"]),
    ("high-payout-low-pe", GROUPS[0], "High Dividend Payout + Low P/E",
     "High income + cheap valuation, ideal for income + value investors.", ["high_payout", "low_pe"]),

    ("high-yield-high-payout", GROUPS[1], "High Dividend Yield + High Dividend Payout",
     "Ideal for income-focused investors seeking sustainable payouts.", ["high_yield", "high_payout"]),
    ("high-cover-high-eps", GROUPS[1], "High Dividend Cover + High EPS",
     "Safe dividends backed by strong earnings, less risk of cuts.", ["high_cover", "high_eps"]),
    ("high-yield-low-pe", GROUPS[1], "High Dividend Yield + Low P/E",
     "Income + value, ideal for retirees or income-focused portfolios.", ["high_yield", "low_pe"]),
    ("high-payout-high-ret1y", GROUPS[1], "High Dividend Payout + High Return Over 1 Year",
     "Income + momentum, stocks that pay and perform.", ["high_payout", "ret_1y"]),
    ("high-yield-high-promoter", GROUPS[1], "High Dividend Yield + High Promoter Holding",
     "Income + strong ownership, stable, dividend-paying companies.", ["high_yield", "high_promoter"]),

    ("high-volume-high-ret1y", GROUPS[2], "High Volume + High Return Over 1 Year",
     "Trending momentum + strong liquidity, potential breakout stocks.", ["high_volume", "ret_1y"]),
    ("high-eps-high-ret3y", GROUPS[2], "High EPS + High Return Over 3 Years",
     "Strong earnings + sustained growth, high-quality growth stocks.", ["high_eps", "ret_3y"]),
    ("low-debt-high-ret1y", GROUPS[2], "Low Debt + High Return Over 1 Year",
     "Low risk + strong performance, quality with upside.", ["low_debt", "ret_1y"]),
    ("high-ret1m-high-volume", GROUPS[2], "High Return Over 1 Month + High Volume",
     "Short-term momentum + liquidity, potential breakout or trend stocks.", ["ret_1m", "high_volume"]),

    ("high-promoter-low-debt", GROUPS[3], "High Promoter Holding + Low Debt",
     "Quality management + low financial risk, strong ownership and balance sheet.", ["high_promoter", "low_debt"]),
    ("low-debt-high-profit", GROUPS[3], "Low Debt + High Net Profit",
     "Strong balance sheet + profitable, safe and scalable businesses.", ["low_debt", "profit"]),
    ("high-yield-high-ret1y", GROUPS[3], "High Dividend Yield + High Return Over 1 Year",
     "Income + momentum, stocks that deliver both.", ["high_yield", "ret_1y"]),
    ("high-eps-low-volatility", GROUPS[3], "High EPS + Low Volatility",
     "Strong earnings + low risk, stable, high-quality businesses.", ["high_eps", "low_vol"]),
    ("high-promoter-high-ret3y", GROUPS[3], "High Promoter Holding + High Return Over 3 Years",
     "Strong ownership + sustained performance, high conviction.", ["high_promoter", "ret_3y"]),

    ("high-eps-low-pe", GROUPS[4], "High EPS + Low P/E",
     "Premium earnings + cheap valuation, classic value growth combo.", ["high_eps", "low_pe"]),
    ("low-pe-high-eps-low-cost", GROUPS[4], "Low P/E + High EPS + Low Cost",
     "Low Entry cost, cheap valuation + low absolute earnings.", ["low_pe", "high_eps", "low_price"]),
    ("low-pe-high-ret1y", GROUPS[4], "Low P/E + High Return Over 1 Year",
     "Cheap valuation + strong momentum. value with upside.", ["low_pe", "ret_1y"]),
    ("high-eps-high-ret5y", GROUPS[4], "High EPS + High Return Over 5 Years",
     "Strong earnings + long-term performance, elite growth stocks.", ["high_eps", "ret_5y"]),
    ("high-eps-growth-low-ret5y", GROUPS[4], "High EPS Growth + Low Return Over 5 Years",
     "Value trap + long-term performance.", ["eps_growth", "low_ret_5y"]),
]

BY_ID = {s[0]: s for s in SCREENS}
