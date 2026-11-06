"""HTTP surface for the market scanner (see patterns/scan.py and patterns/screen_engine.py). Mounted from app.py next to the
pattern agent router."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from . import market_analytics, market_lists, scan
from .registry import BY_NAME
from .screen_engine import SPECIAL


def make_router(require_session):
    r = APIRouter()

    def _check(pattern: str) -> None:
        if pattern not in BY_NAME and pattern not in SPECIAL:  # SPECIAL includes "multi" and every market-list scanner
            raise HTTPException(status_code=404, detail=f"Unknown pattern {pattern!r}.")

    @r.get("/api/v1/pattern-scan/options")
    def scan_options(_: dict = Depends(require_session)):
        """What the filter popup offers: indices, sectors, moving-average periods, statuses, bounds and rotation options."""
        return scan.options()

    @r.get("/api/v1/market/scanners")
    def market_scanners(_: dict = Depends(require_session)):
        """The market-list scanners (top gainers, volume, gaps, setups, momentum ...) with their definitions."""
        return {"scanners": market_lists.catalogue()}

    @r.get("/api/v1/market/breadth")
    def market_breadth(_: dict = Depends(require_session)):
        """Advance/decline, share of stocks above their 20/50/200-day averages, new highs and lows, and a history."""
        return market_analytics.breadth()

    @r.get("/api/v1/market/sectors")
    def market_sectors(_: dict = Depends(require_session)):
        """Sector strength table: returns over several periods against the Nifty 500, breadth inside the sector, RS and quadrant."""
        return market_analytics.sectors()

    @r.get("/api/v1/market/rrg")
    def market_rrg(timeframe: str = "weekly", benchmark: str = "nifty50", trail: int = 8, _: dict = Depends(require_session)):
        """Sector rotation graph: quadrant, RS-Ratio, RS-Momentum and the recent path of every sector."""
        if timeframe not in ("daily", "weekly") or benchmark not in ("nifty50", "nifty500"):
            raise HTTPException(status_code=400, detail="timeframe is daily or weekly; benchmark is nifty50 or nifty500.")
        return market_analytics.rrg(timeframe, benchmark, max(2, min(20, trail)))

    @r.get("/api/v1/pattern-scan/status")
    def scan_status(_: dict = Depends(require_session)):
        return scan.status()

    @r.post("/api/v1/pattern-scan/build")
    def scan_build(force: bool = False, _: dict = Depends(require_session)):
        """Start (or report an already running) background scan of the whole universe."""
        started = scan.build(force=force)
        return {"started": started, **scan.status()}

    @r.post("/api/v1/pattern-scan/{pattern}/search")
    def scan_search(pattern: str, include_candles: bool = False, filters: dict = Body(default_factory=dict),
                    _: dict = Depends(require_session)):
        """Stocks currently showing `pattern` ("all" = no pattern requirement, "horizontal-resistance" = stocks at a horizontal
        resistance), narrowed by the filters. List filters: indices / sectors / status: {values: [...]}; ema / dma: {periods,
        side}. Range filters {min, max}: mcap (Rs crore), price, rs, pct_52w_low, pct_52w_high, pct_ath, free_float, turnover,
        avg_volume, pe, eps_growth, debt_equity, promoter, div_yield, net_profit, volatility, ret_1m..ret_5y. Others: near_high
        {sessions}, ma_order {kind, periods}, ma_uptrend {period, months}, adr {days, min}, rrg {quadrants, timeframe,
        benchmark}, resistance {require, states}; q (name or ticker), page, page_size, sort."""
        _check(pattern)
        return scan.search(pattern, filters, include_candles=include_candles)

    @r.post("/api/v1/pattern-scan/{pattern}/backtest")
    def scan_backtest(pattern: str, filters: dict = Body(default_factory=dict), _: dict = Depends(require_session)):
        """What happened after `pattern` confirmed in the past, over the stocks that pass the stock-level filters. Extra keys:
        horizon (5/10/20/40/60 bars), page, page_size (the trade list)."""
        _check(pattern)
        return scan.backtest(pattern, filters)

    return r
