"""
Temporary live-chart candle provider using yfinance, filling in for the
Axis Direct RAPID API (tools/axis_feed_ws.py) until Axis (or ICICI Breeze,
if that path is chosen instead) actually provisions API access. yfinance
has no push/streaming feed, so "live" here means polling: the frontend
re-fetches on an interval and the chart's last candle updates.

Company-agnostic: takes any NSE symbol + interval/period, no per-ticker
branching, matching tools/market_history.py's convention. This module
owns ONLY chart candle data - never a financial-statement figure.

Swap-out point: once Axis/ICICI credentials exist, the live-chart
endpoint in app.py should switch its provider call from
`get_candles`/`get_latest` here to the equivalent AxisLiveFeed-backed
function, without changing the frontend's response shape (a list of
{time, open, high, low, close, volume} dicts, ascending by time).
"""

import datetime

try:
    import yfinance as yf
    _HAVE_YF = True
except Exception:  # pragma: no cover
    _HAVE_YF = False

# yfinance's intraday history is capped per-interval (see
# _INTRADAY_MAX_PERIOD below) - a single day's request further back than
# that has no data to return at all, so get_candles_for_date reports it
# honestly as unavailable rather than silently falling back to a nearby day.
_INTRADAY_MAX_DAYS = {"1m": 7, "2m": 60, "5m": 60, "15m": 60, "30m": 60, "60m": 730}

# NSE trading window in IST - a day's candles are trimmed to this even
# though yfinance already only returns bars inside market hours, so a
# provider quirk (e.g. a stray pre/post-market print) can't leak into the
# "9:15 to 3:30" history view.
_MARKET_OPEN = datetime.time(9, 15)
_MARKET_CLOSE = datetime.time(15, 30)

# yfinance intraday intervals and the max history period each supports.
_INTRADAY_MAX_PERIOD = {
    "1m": "7d",
    "2m": "60d",
    "5m": "60d",
    "15m": "60d",
    "30m": "60d",
    "60m": "730d",
}


# Chart-provider ticker resolution. app.py registers a provider that returns the
# candidate Yahoo tickers for a company by the app's exchange rules (NSE first;
# a BSE-only company is tried under its BSE trading symbol(s) as `<sym>.BO`).
# Several candidates are probed once and the first with real data is cached.
_CANDIDATES_PROVIDER = None
_TICKER_CACHE: dict = {}


def set_ticker_candidates_provider(fn):
    """fn(symbol) -> (candidate_tickers: list[str], company_name: str | None)"""
    global _CANDIDATES_PROVIDER
    _CANDIDATES_PROVIDER = fn


def _has_data(ticker: str) -> bool:
    try:
        h = yf.Ticker(ticker).history(period="5d", interval="1d")
        return h is not None and not h.empty
    except Exception:
        return False


def _search_by_name(name: str):
    """Last resort for a BSE-only company with no known trading symbol: Yahoo's own
    search, accepting only a .BO hit whose name equals the company name after
    normalisation (no fuzzy guessing)."""
    try:
        from tools.company_search import normalize, strip_legal
        want = strip_legal(normalize(name))
        for q in yf.Search(name, max_results=8).quotes:
            sym = q.get("symbol", "")
            got = strip_legal(normalize(q.get("longname") or q.get("shortname") or ""))
            if sym.endswith(".BO") and got and got == want:
                return sym
    except Exception:
        pass
    return None


def _to_symbol(symbol: str) -> str:
    base = str(symbol).strip().upper().replace(".NS", "")
    if _CANDIDATES_PROVIDER is None:
        return _TICKER_CACHE.get(base) or base + ".NS"
    try:
        cands, name = _CANDIDATES_PROVIDER(base)
    except Exception:
        return base + ".NS"
    if len(cands) == 1:
        # NSE-listed, or not a known company at all: the company master is authoritative,
        # so any cached BSE mapping for a company that has since been removed is dropped.
        _TICKER_CACHE.pop(base, None)
        return cands[0]
    if base in _TICKER_CACHE:
        return _TICKER_CACHE[base]
    for c in cands:
        if _have_yf() and _has_data(c):
            _TICKER_CACHE[base] = c
            return c
    found = _search_by_name(name) if (name and _have_yf()) else None
    if found:
        _TICKER_CACHE[base] = found
        return found
    return cands[0]  # nothing verified: the first candidate, so the failure is an honest "unavailable"


def _have_yf() -> bool:
    return bool(_HAVE_YF)


def get_candles(symbol: str, interval: str = "5m", period: str | None = None):
    """Returns a list of {time (unix seconds), open, high, low, close,
    volume} dicts, oldest first, or None if unavailable. Never raises,
    never fabricates a bar - a gap in the source data is just a gap.
    """
    if not _HAVE_YF:
        return None
    period = period or _INTRADAY_MAX_PERIOD.get(interval, "1y")
    try:
        sym = _to_symbol(symbol)
        hist = yf.Ticker(sym).history(period=period, interval=interval)
        if hist is None or hist.empty:
            return None
        candles = []
        for ts, row in hist.iterrows():
            o, h, l, c = row.get("Open"), row.get("High"), row.get("Low"), row.get("Close")
            if o is None or h is None or l is None or c is None:
                continue
            candles.append({
                "time": int(ts.timestamp()),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(row.get("Volume") or 0),
            })
        return candles or None
    except Exception:
        return None


_IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
_WARMUP_LOOKBACK_DAYS = 10   # calendar days; enough for several prior sessions
_WARMUP_MAX_BARS = 300       # prior-session bars handed to the detectors


def _row_to_candle(ts, row):
    o, h, l, c = row.get("Open"), row.get("High"), row.get("Low"), row.get("Close")
    if o is None or h is None or l is None or c is None:
        return None
    return {
        "time": int(ts.timestamp()),
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(c),
        "volume": float(row.get("Volume") or 0),
    }


def get_session_with_warmup(symbol: str, date_str: str, interval: str = "5m"):
    """Returns (session, warmup) for one trading date, or None.

    session = that date's regular-session (9:15-3:30 IST) candles - the
    display window. warmup = up to _WARMUP_MAX_BARS regular-session candles
    from the sessions BEFORE it - the detector calculation window only, so
    indicators (RSI/BB/swings need ~30 bars) are already warm at 9:15 instead
    of the replay silently skipping the first ~2.5 hours. Warmup bars are
    never part of the displayed session. Dates are matched on the IST
    calendar date, not UTC. None if the date is outside yfinance's intraday
    retention or has no data (weekend/holiday) - never a substituted day.
    """
    if not _HAVE_YF:
        return None
    try:
        day = datetime.date.fromisoformat(date_str)
    except ValueError:
        return None
    max_days = _INTRADAY_MAX_DAYS.get(interval, 60)
    if (datetime.date.today() - day).days > max_days:
        return None
    try:
        sym = _to_symbol(symbol)
        start = datetime.datetime.combine(day - datetime.timedelta(days=_WARMUP_LOOKBACK_DAYS), datetime.time.min)
        end = datetime.datetime.combine(day, datetime.time.min) + datetime.timedelta(days=1)
        hist = yf.Ticker(sym).history(start=start, end=end, interval=interval)
        if hist is None or hist.empty:
            return None
        session, warmup = [], []
        for ts, row in hist.iterrows():
            local_ts = ts.tz_convert("Asia/Kolkata") if ts.tzinfo is not None else ts.replace(tzinfo=_IST)
            if not (_MARKET_OPEN <= local_ts.time() <= _MARKET_CLOSE):
                continue
            candle = _row_to_candle(ts, row)
            if candle is None:
                continue
            if local_ts.date() == day:
                session.append(candle)
            elif local_ts.date() < day:
                warmup.append(candle)
        if not session:
            return None
        return session, warmup[-_WARMUP_MAX_BARS:]
    except Exception:
        return None


def get_candles_for_date(symbol: str, date_str: str, interval: str = "5m"):
    """Session-only candles for one date (see get_session_with_warmup)."""
    res = get_session_with_warmup(symbol, date_str, interval)
    return res[0] if res else None


def get_latest(symbol: str):
    """Returns {ltp, prev_close, change, change_pct} for the polling
    ticker on top of the chart, or None if unavailable."""
    if not _HAVE_YF:
        return None
    try:
        sym = _to_symbol(symbol)
        t = yf.Ticker(sym)
        info = t.fast_info
        ltp = getattr(info, "last_price", None)
        prev_close = getattr(info, "previous_close", None)
        if ltp is None:
            return None
        change = change_pct = None
        if prev_close:
            change = round(float(ltp) - float(prev_close), 2)
            change_pct = round((float(ltp) - float(prev_close)) / float(prev_close) * 100, 2)
        return {
            "ltp": float(ltp),
            "prev_close": float(prev_close) if prev_close else None,
            "change": change,
            "change_pct": change_pct,
            "source": "yfinance",
        }
    except Exception:
        return None
