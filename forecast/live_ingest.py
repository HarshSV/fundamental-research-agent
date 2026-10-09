"""Keep the store current for live inference.

Why this exists: a forecast is only legitimate when the store holds the LATEST completed 5-minute bar
(inference withholds otherwise). The provider serves a new bar ~0.1 s after it closes (measured), so any
delay is ours. Fetching lazily from the UI poll left every new bar 35-70 s late, during which the API
correctly answered NO_RELIABLE_FORECAST ("updating"). This module instead keeps every ACTIVE symbol
(requested in the last ACTIVE_TTL seconds) current: right after each 5-minute boundary it fetches until the
expected bar is stored, with bounded retries. It uses its own Angel session, throttled by the collector.
It never fabricates or back-fills a bar: a bar exists in the store only if the provider returned it.
"""
import datetime as dt
import threading
import time

from . import collector, config, store

ACTIVE_TTL = 900            # seconds a symbol stays "active" after its last request
TICK = 2.0                  # scheduler cadence
RETRY_GAP = 3.0             # min seconds between fetch attempts for one symbol
MAX_ATTEMPTS_PER_BAR = 25   # then wait for the next boundary (holiday / provider outage safety)
_IST = dt.timezone(dt.timedelta(seconds=config.IST_OFFSET_SEC))

_lock = threading.Lock()                  # one provider fetch at a time
_client = None
_active = {}                              # symbol -> last touch (epoch)
_attempts = {}                            # symbol -> (expected_bar_open, attempts, last_attempt_ts)
_inflight = set()
_state_lock = threading.Lock()
_sched = None


def _get_client():
    global _client
    if _client is None:
        c = collector.AngelHistory(min_delay=2.0, max_delay=6.0, cooldown=4.0)
        c.login()
        _client = c
    return _client


def expected_bar_open(now):
    """Open ts of the latest bar that should be complete at `now`."""
    return int(now // config.BAR_SECONDS) * config.BAR_SECONDS - config.BAR_SECONDS


def in_session(bar_open):
    """Is `bar_open` a regular-session slot on a weekday (IST)? Holidays are not known here - the retry cap
    bounds the cost of asking on one."""
    d = dt.datetime.fromtimestamp(bar_open, _IST)
    if d.weekday() >= 5:
        return False
    slot = ((d.hour * 60 + d.minute) - config.SESSION_OPEN_MIN) // (config.BAR_SECONDS // 60)
    return 0 <= slot < config.USABLE_SLOTS          # bars past the usable slots are never used, so never awaited


def bar_is_behind(latest_open, now):
    """True when the store lacks a bar that should exist now (and the session is open)."""
    exp = expected_bar_open(now)
    return in_session(exp) and (latest_open is None or latest_open < exp)


def _latest_open(symbol):
    con = store.connect()
    r = con.execute("SELECT max(ts) FROM candles WHERE symbol=? AND interval=?", (symbol, config.INTERVAL)).fetchone()
    con.close()
    return r[0]


INDEX_SYMBOL = "NIFTY 50"


def _behind(symbol, now):
    """Behind if the symbol OR its index context lacks the expected bar (the model uses NIFTY features)."""
    return bar_is_behind(_latest_open(symbol), now) or bar_is_behind(_latest_open(INDEX_SYMBOL), now)


def is_refreshing(symbol):
    """Truthful 'updating' signal: a fetch is running, or the store is behind and a fetch is still due."""
    with _state_lock:
        if symbol in _inflight:
            return True
    now = time.time()
    if not _behind(symbol, now):
        return False
    exp, n, _ = _attempts.get(symbol, (None, 0, 0))
    return not (exp == expected_bar_open(now) and n >= MAX_ATTEMPTS_PER_BAR)


def refresh_symbol(symbol, index_symbol="NIFTY 50", force=False):
    """Fetch the last ~10 days for `symbol` (+ index) into the store. Returns a short status dict."""
    with _lock:
        try:
            client = _get_client()
            con = store.connect()
            res = [collector.backfill_symbol(client, con, symbol, years=10 / 365.25)]
            if index_symbol and symbol != index_symbol:
                res.append(collector.backfill_symbol(client, con, index_symbol, years=10 / 365.25))
            con.close()
            return {"refreshed": True, "result": res}
        except Exception as e:                                   # provider failure must never break the API
            return {"refreshed": False, "reason": f"{type(e).__name__}: {str(e)[:120]}"}


def _tick():
    now = time.time()
    exp = expected_bar_open(now)
    for symbol, touched in list(_active.items()):
        if now - touched > ACTIVE_TTL:
            _active.pop(symbol, None)
            continue
        if not _behind(symbol, now):
            continue
        e, n, last = _attempts.get(symbol, (None, 0, 0))
        if e != exp:
            e, n, last = exp, 0, 0                                # new boundary: reset the retry budget
        if n >= MAX_ATTEMPTS_PER_BAR or now - last < RETRY_GAP:
            _attempts[symbol] = (e, n, last)
            continue
        _attempts[symbol] = (e, n + 1, now)
        with _state_lock:
            _inflight.add(symbol)
        try:
            refresh_symbol(symbol)
        finally:
            with _state_lock:
                _inflight.discard(symbol)


def _loop():
    while True:
        try:
            _tick()
        except Exception:
            pass
        time.sleep(TICK)


def refresh_async(symbol, index_symbol="NIFTY 50"):
    """Register `symbol` as active (the scheduler keeps it current) and return whether an update is pending.
    Never blocks on the provider."""
    global _sched
    _active[symbol] = time.time()
    with _state_lock:
        if _sched is None:
            _sched = threading.Thread(target=_loop, daemon=True, name="forecast-ingest")
            _sched.start()
    return is_refreshing(symbol)
