"""HTTP surface for the market scanner (see patterns/scan.py and patterns/screen_engine.py). Mounted from app.py next to the
pattern agent router."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from . import exchange_data, market_analytics, market_feeds, market_lists, scan, sector_history
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

    @r.get("/api/v1/market/feed/{name}")
    def market_feed(name: str, kind: str = "", year: int = 0, start: str = "", end: str = "", _: dict = Depends(require_session)):
        """List pages built from exchange data: results-calendar, circuit-revisions, order-wins, deals (kind=bulk|block), asm,
        sector-indices, recent-ipos, past-winners. Starts a background read of the exchange feeds when they are missing or old."""
        exchange_data.ensure_fresh()
        if name == "results-calendar":
            return market_feeds.results_calendar(start or None, end or None)
        if name == "circuit-revisions":
            return market_feeds.circuit_revisions()
        if name == "order-wins":
            return market_feeds.order_wins()
        if name == "deals":
            if kind not in ("bulk", "block"):
                raise HTTPException(status_code=400, detail="kind is bulk or block.")
            return market_feeds.deals(kind)
        if name == "asm":
            return market_feeds.asm_list()
        if name == "sector-indices":
            return market_feeds.sector_indices()
        if name == "recent-ipos":
            return market_feeds.recent_ipos()
        if name == "past-winners":
            return market_feeds.past_winners(year or None)
        raise HTTPException(status_code=404, detail=f"Unknown list {name!r}.")

    @r.get("/api/v1/market/sector-history")
    def market_sector_history(window: str = "full", _: dict = Depends(require_session)):
        """Each sector's history since about 1996 (equal-weighted from its stocks' adjusted prices): yearly returns, deepest fall,
        rolling returns, seasonality, strength against all stocks. window = full | 5y."""
        return sector_history.build("5y" if window == "5y" else "full")

    @r.post("/api/v1/market/sector-history/refresh")
    def market_sector_history_refresh(_: dict = Depends(require_session)):
        return sector_history.start_refresh_background()

    @r.get("/api/v1/market/industries")
    def market_industries(weighting: str = "equal", _: dict = Depends(require_session)):
        """Industry analytics: returns, ranks, stock count, group market cap and rotation quadrant per industry (Screener classification)."""
        return market_analytics.industries("cap" if weighting == "cap" else "equal")

    @r.get("/api/v1/market/data-status")
    def market_data_status(_: dict = Depends(require_session)):
        from screens import quarterly
        return {"exchange": exchange_data.status(), "quarterly": quarterly.status()}

    @r.post("/api/v1/market/data-refresh")
    def market_data_refresh(_: dict = Depends(require_session)):
        """Read the exchange feeds and the Screener quarterly pages again in the background."""
        import threading
        from screens import quarterly
        threading.Thread(target=exchange_data.refresh, kwargs={"force": True}, daemon=True).start()
        threading.Thread(target=quarterly.build, daemon=True).start()
        return {"started": True}

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
