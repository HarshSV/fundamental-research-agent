"""
Historical price series - the ONE Beta (Sr No 66) implementation every engine uses.

Deliberately separate from `tools.market_price` (live tick) and from every
Annual-Report-sourced canonical fact (spec §16) - this module only ever
returns price HISTORY, never a financial-statement figure.

BETA POLICY (single, deterministic - `tools.ratio_contract.BETA_POLICY` documents it):
    benchmark            Nifty 50 (^NSEI)
    return frequency     weekly closing-price returns
    lookback             trailing 2 years
    minimum observations 52 aligned weekly returns (below that: insufficient_data, never a guess)
    estimator            sample covariance(stock, market) / sample variance(market), ddof=1,
                         series inner-joined on date (never positional alignment)
    price source         Yahoo Finance via `tools.yf_cache` (NSE ticker `<SYM>.NS`)
    manual mode          Beta needs a multi-year price history that an uploaded document cannot
                         supply, so the manual workflow reports insufficient_data (callers check
                         `tools.manual_mode`) - the value is never fabricated.
Confidence: 1.0 for >= 100 weekly points, 0.8 for 52-99.
"""

BENCHMARK = "^NSEI"
INTERVAL = "1wk"
PERIOD = "2y"
MIN_OBSERVATIONS = 52
FULL_CONFIDENCE_OBSERVATIONS = 100


def beta_from_close_series(stock_close, index_close):
    """Pure computation from two pandas Series of closing prices (DatetimeIndex).
    Returns {"beta","cov","var","n","start","end"} or {"reason": ..., "n": ...}. Never raises."""
    try:
        import pandas as pd
        import numpy as np
        s = stock_close.copy()
        m = index_close.copy()
        try:
            s.index = s.index.tz_localize(None)
            m.index = m.index.tz_localize(None)
        except (TypeError, AttributeError):
            pass
        aligned = pd.concat([s, m], axis=1, join="inner")
        aligned.columns = ["stock", "index"]
        returns = aligned.pct_change().dropna()
        n = len(returns)
        if n < MIN_OBSERVATIONS:
            return {"reason": f"Only {n} weeks of aligned trading history found - fewer than the {MIN_OBSERVATIONS}-week "
                              "(~1 year) minimum needed for a reliable Beta (newly-listed or very illiquid stock).", "n": n}
        sr, mr = returns["stock"].to_numpy(), returns["index"].to_numpy()
        var = float(np.var(mr, ddof=1))
        if var == 0:
            return {"reason": "Benchmark index return variance is zero over this window - Beta is undefined.", "n": n}
        cov = float(np.cov(sr, mr, ddof=1)[0][1])
        return {"beta": cov / var, "cov": cov, "var": var, "n": n,
                "start": returns.index.min().strftime("%d-%b-%Y"), "end": returns.index.max().strftime("%d-%b-%Y")}
    except Exception as e:
        return {"reason": f"Beta could not be computed ({e}).", "n": 0}


def weekly_beta(symbol):
    """Fetches the two histories per the policy above and returns `beta_from_close_series`' dict
    (or {"reason": ...}). Never raises, never fabricates."""
    try:
        from tools.yf_cache import cached_history
        sym = str(symbol).strip().upper().replace(".NS", "")
        stock_hist = cached_history(f"{sym}.NS", period=PERIOD, interval=INTERVAL)
        index_hist = cached_history(BENCHMARK, period=PERIOD, interval=INTERVAL)
    except Exception as e:
        return {"reason": "Could not fetch historical price data right now - please try again in a moment.", "n": 0,
                "error": str(e)}
    if stock_hist is None or stock_hist.empty or index_hist is None or index_hist.empty:
        return {"reason": "No historical price data available - likely a newly-listed stock with insufficient trading history.",
                "n": 0}
    return beta_from_close_series(stock_hist["Close"], index_hist["Close"])
