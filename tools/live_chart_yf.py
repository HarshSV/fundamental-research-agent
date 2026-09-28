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


def _to_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace(".NS", "") + ".NS"


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


def get_candles_for_date(symbol: str, date_str: str, interval: str = "5m"):
    """Returns the full trading day's (9:15-3:30 IST) candles for one
    calendar date - the "History" view's data source, distinct from the
    rolling-window get_candles used by the live chart. `date_str` is
    'YYYY-MM-DD'. Returns None if the date is outside what yfinance's
    intraday retention actually has for this interval, or if there's no
    trading data for that date (weekend/holiday) - never a fabricated or
    nearest-available substitute.
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
        start = datetime.datetime.combine(day, datetime.time.min)
        end = start + datetime.timedelta(days=1)
        hist = yf.Ticker(sym).history(start=start, end=end, interval=interval)
        if hist is None or hist.empty:
            return None
        candles = []
        for ts, row in hist.iterrows():
            local_ts = ts.tz_convert("Asia/Kolkata") if ts.tzinfo is not None else ts
            if not (_MARKET_OPEN <= local_ts.time() <= _MARKET_CLOSE):
                continue
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
