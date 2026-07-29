"""
Move detection — layer 1 of the event-grounded reasoning pipeline (see memory
"event-grounded-reasoning-scope"). Flags windows where a stock moved sharply,
using only price history we already fetch (yfinance via yf_cache) — no new
dependency, no news source needed.

Two kinds of window:
  - single-day move beyond SINGLE_DAY_THRESHOLD
  - sustained move over SUSTAINED_WINDOW_DAYS trading days beyond
    SUSTAINED_THRESHOLD

Each window is also compared against the Nifty 50 (^NSEI) over the same dates
so the caller can tell stock-specific moves from market-wide ones. Never
raises — returns [] on any failure so this can't break the chat.
"""

from tools.yf_cache import cached_history

SINGLE_DAY_THRESHOLD = 5.0      # % single-session move to flag
SUSTAINED_WINDOW_DAYS = 15      # trading days for the sustained-move check
SUSTAINED_THRESHOLD = 15.0      # % move over that window to flag
LOOKBACK_PERIOD = "6mo"
MAX_WINDOWS = 6                 # cap returned windows (most recent first)


def _pct(a, b):
    if not a or not b:
        return None
    try:
        return round((b - a) / a * 100, 2)
    except Exception:
        return None


def _nifty_pct(date_from, date_to):
    """Nifty 50 % change over [date_from, date_to] (inclusive), or None."""
    try:
        hist = cached_history("^NSEI", period=LOOKBACK_PERIOD, interval="1d")
        if hist is None or hist.empty:
            return None
        window = hist.loc[(hist.index.date >= date_from) & (hist.index.date <= date_to)]
        if window.empty:
            return None
        return _pct(float(window["Close"].iloc[0]), float(window["Close"].iloc[-1]))
    except Exception:
        return None


def detect_significant_moves(symbol: str) -> list:
    """
    Returns a list of flagged move windows for `symbol` (bare NSE ticker, no
    .NS suffix needed), most recent first, each:
      {date_from, date_to, pct_change, direction, kind, nifty_pct_change,
       stock_specific}
    `kind` is "single_day" or "sustained". `stock_specific` is True when the
    move meaningfully diverges from Nifty 50 over the same window (heuristic:
    |stock_pct - nifty_pct| >= 8pp), None if Nifty data unavailable.
    """
    sym = (symbol or "").strip().upper().replace(".NS", "")
    if not sym:
        return []
    try:
        hist = cached_history(f"{sym}.NS", period=LOOKBACK_PERIOD, interval="1d")
        if hist is None or hist.empty or "Close" not in hist.columns or len(hist) < 2:
            return []
    except Exception:
        return []

    closes = hist["Close"]
    dates = [d.date() for d in hist.index]
    windows = []

    # Single-day moves.
    for i in range(1, len(closes)):
        pct = _pct(float(closes.iloc[i - 1]), float(closes.iloc[i]))
        if pct is not None and abs(pct) >= SINGLE_DAY_THRESHOLD:
            windows.append({
                "date_from": dates[i - 1], "date_to": dates[i],
                "pct_change": pct, "kind": "single_day",
            })

    # Sustained moves over a rolling N-trading-day window (non-overlapping scan).
    step = max(1, SUSTAINED_WINDOW_DAYS // 3)
    i = 0
    while i + SUSTAINED_WINDOW_DAYS < len(closes):
        j = i + SUSTAINED_WINDOW_DAYS
        pct = _pct(float(closes.iloc[i]), float(closes.iloc[j]))
        if pct is not None and abs(pct) >= SUSTAINED_THRESHOLD:
            windows.append({
                "date_from": dates[i], "date_to": dates[j],
                "pct_change": pct, "kind": "sustained",
            })
            i = j  # skip past this window instead of re-flagging overlapping sub-windows
        else:
            i += step

    if not windows:
        return []

    # Most recent first, cap.
    windows.sort(key=lambda w: w["date_to"], reverse=True)
    windows = windows[:MAX_WINDOWS]

    out = []
    for w in windows:
        nifty_pct = _nifty_pct(w["date_from"], w["date_to"])
        stock_specific = None
        if nifty_pct is not None:
            stock_specific = abs(w["pct_change"] - nifty_pct) >= 8.0
        out.append({
            "date_from": w["date_from"].isoformat(),
            "date_to": w["date_to"].isoformat(),
            "pct_change": w["pct_change"],
            "direction": "up" if w["pct_change"] > 0 else "down",
            "kind": w["kind"],
            "nifty_pct_change": nifty_pct,
            "stock_specific": stock_specific,
        })
    return out


if __name__ == "__main__":
    import sys
    import json
    sym = sys.argv[1] if len(sys.argv) > 1 else "TATASTEEL"
    print(json.dumps(detect_significant_moves(sym), indent=2))
