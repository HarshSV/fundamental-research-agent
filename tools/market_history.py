"""
Historical price series - the market-data interface Beta (Sr No 66) needs.
Deliberately separate from `tools.market_price` (live tick) and from every
Annual-Report-sourced canonical fact (spec §16) - this module only ever
returns price HISTORY, never a financial-statement figure.

Company-agnostic: `get_price_history`/`get_benchmark_history` take a symbol/
benchmark ticker and a period - no company-specific branching. Reuses the
yfinance dependency already used elsewhere in this codebase (e.g.
`tools.angel_scraper.compute_pe_band`) rather than adding a new provider.
"""

try:
    import yfinance as yf
    _HAVE_YF = True
except Exception:  # pragma: no cover
    _HAVE_YF = False

DEFAULT_BENCHMARK = "^NSEI"  # Nifty 50 - the canonical broad-market benchmark for NSE-listed equities
DEFAULT_PERIOD = "1y"
DEFAULT_INTERVAL = "1d"


def _daily_returns(closes):
    returns = []
    prev = None
    for c in closes:
        if c is None or c <= 0:
            prev = None
            continue
        if prev is not None:
            returns.append((c / prev) - 1.0)
        prev = c
    return returns


def get_price_history(symbol, period=DEFAULT_PERIOD, interval=DEFAULT_INTERVAL):
    """Returns a list of daily returns for `symbol` (NSE-listed), or None if
    unavailable. Never raises, never fabricates a series."""
    if not _HAVE_YF:
        return None
    try:
        sym = str(symbol).strip().upper().replace(".NS", "") + ".NS"
        hist = yf.Ticker(sym).history(period=period, interval=interval)
        if hist is None or hist.empty or "Close" not in hist.columns:
            return None
        return _daily_returns([float(c) for c in hist["Close"].tolist()])
    except Exception:
        return None


def get_benchmark_history(benchmark=DEFAULT_BENCHMARK, period=DEFAULT_PERIOD, interval=DEFAULT_INTERVAL):
    """Returns a list of daily returns for the benchmark index. Never raises."""
    if not _HAVE_YF:
        return None
    try:
        hist = yf.Ticker(benchmark).history(period=period, interval=interval)
        if hist is None or hist.empty or "Close" not in hist.columns:
            return None
        return _daily_returns([float(c) for c in hist["Close"].tolist()])
    except Exception:
        return None


def compute_beta(stock_returns, market_returns):
    """Beta = Cov(stock, market) / Var(market), over the OVERLAPPING trailing
    window (shorter series wins) - both series are daily returns aligned by
    position (most-recent-last), matching how `get_price_history`/
    `get_benchmark_history` build them. Returns None (never 1.0, never 0)
    if either series is missing or too short to be meaningful."""
    if not stock_returns or not market_returns:
        return None
    n = min(len(stock_returns), len(market_returns))
    if n < 20:  # a handful of days is not a defensible Beta - refuse rather than guess
        return None
    s = stock_returns[-n:]
    m = market_returns[-n:]
    mean_s = sum(s) / n
    mean_m = sum(m) / n
    cov = sum((s[i] - mean_s) * (m[i] - mean_m) for i in range(n)) / n
    var_m = sum((x - mean_m) ** 2 for x in m) / n
    if var_m == 0:
        return None
    return cov / var_m
