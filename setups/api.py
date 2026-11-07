"""HTTP surface for the forecast. Mounted from app.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from . import engine, outlook


def _quarters(sym: str) -> dict | None:
    """Screener's quarterly results for the stock, within a short wait (the page is cached for 12 hours); None if unavailable."""
    import concurrent.futures
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        from tools.screener_scraper import fetch_screener_financials
        fin = pool.submit(fetch_screener_financials, sym, None).result(timeout=6)
        return ((fin or {}).get("financial_arrays") or {}).get("quarterly_income_stmt")
    except Exception:
        return None
    finally:
        pool.shutdown(wait=False)


def make_router(require_session, resolve_symbol):
    r = APIRouter()

    @r.get("/api/v1/outlook/{symbol}")
    def stock_outlook(symbol: str, _: dict = Depends(require_session)):
        """The Forecast for one stock: outlook odds for the session / 5 / 20 sessions, one trade plan or "No trade", the
        Time Machine odds measured on that plan, and the evidence (trend, strength, quality, liquidity, segment)."""
        sym = resolve_symbol(symbol)
        if not sym:
            raise HTTPException(status_code=400, detail="Symbol required.")
        from tools.live_chart_yf import get_candles
        intraday = get_candles(sym, interval="5m", period="60d")
        daily = get_candles(sym, interval="1d", period="5y")
        if not daily:
            return {"symbol": sym, "source": "unavailable"}
        row, peers = None, []
        try:
            from patterns import scan
            rows = scan._load_all()
            row = rows.get(sym)
            if row:
                peers = [x for x in rows.values() if x.get("sector") == row.get("sector")]
        except Exception:
            pass
        out = outlook.build(sym, intraday, daily, row, peers, _quarters(sym))
        return {**out, "source": "yfinance"}

    @r.get("/api/v1/events/{symbol}")
    def stock_events(symbol: str, _: dict = Depends(require_session)):
        """Filings (NSE, BSE) and headlines (Google News) for the company; read only when the user opens the news panel."""
        sym = resolve_symbol(symbol)
        if not sym:
            raise HTTPException(status_code=400, detail="Symbol required.")
        from . import events
        row = None
        try:
            from patterns import scan
            row = scan._load_all().get(sym)
        except Exception:
            pass
        name = (row or {}).get("name")
        if not name:                                        # stocks outside the scanned set: the NSE listings file has every company name
            try:
                from patterns import exchange_data as ex
                name = ((ex.load("listings") or {}).get(sym) or {}).get("name")
            except Exception:
                name = None
        return events.collect(sym, name)

    @r.get("/api/v1/stock-fcf/{symbol}")
    def stock_fcf(symbol: str, _: dict = Depends(require_session)):
        """Free cash flow by financial year (Screener.in). 'available': false when the source has no FCF row for the company."""
        sym = resolve_symbol(symbol)
        if not sym:
            raise HTTPException(status_code=400, detail="Symbol required.")
        from tools.screener_fcf import free_cash_flow
        res = free_cash_flow(sym)
        return {"symbol": sym, "available": res is not None, **(res or {"rows": []})}

    @r.get("/api/v1/setups/{symbol}")
    def stock_setups(symbol: str, session: str | None = None, _: dict = Depends(require_session)):
        """The raw setup states (opening-range breakout, oversold bounce, horizontal resistance) the Forecast is built on."""
        sym = resolve_symbol(symbol)
        if not sym:
            raise HTTPException(status_code=400, detail="Symbol required.")
        from tools.live_chart_yf import get_candles
        return {**engine.analyse(sym, get_candles(sym, interval="5m", period="5d"), get_candles(sym, interval="1d", period="2y"), session), "source": "yfinance"}

    return r
