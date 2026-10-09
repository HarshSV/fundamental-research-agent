"""IST/session helpers. Canonical time = unix seconds (UTC); IST only for session logic."""
import datetime as dt
from . import config

_IST = dt.timezone(dt.timedelta(seconds=config.IST_OFFSET_SEC))


def session_date(ts):
    """IST calendar date string 'YYYY-MM-DD' of a unix timestamp."""
    return dt.datetime.fromtimestamp(ts, _IST).strftime("%Y-%m-%d")


def minute_of_day(ts):
    d = dt.datetime.fromtimestamp(ts, _IST)
    return d.hour * 60 + d.minute


def slot_of(ts):
    """5m slot index within the regular session (0 = 09:15). May be <0 or >=75 for off-session bars."""
    return (minute_of_day(ts) - config.SESSION_OPEN_MIN) // (config.BAR_SECONDS // 60)


def in_regular_session(ts):
    return 0 <= slot_of(ts) < config.BARS_PER_SESSION


def parse_angel_ts(s):
    """'2026-09-10T15:25:00+05:30' -> unix seconds. Offset must be present (no naive guessing)."""
    d = dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        raise ValueError(f"naive timestamp from provider: {s!r}")
    return int(d.timestamp())


def slot_ts(session, slot):
    d = dt.datetime.fromisoformat(session).replace(tzinfo=_IST)
    return int(d.timestamp()) + config.SESSION_OPEN_MIN * 60 + slot * config.BAR_SECONDS
