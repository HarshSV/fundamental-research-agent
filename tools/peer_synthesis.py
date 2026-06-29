import os
import sys
import statistics


# Sector groupings across the tracked NSE universe. A stock's peers are the other
# members of its sector group (so peer comparison works for the whole registry,
# not just a handful of hand-mapped tickers).
SECTOR_GROUPS = {
    "IT Services": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM"],
    "Private Banks": ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "INDUSINDBK", "IDFCFIRSTB", "YESBANK"],
    "PSU Banks": ["SBIN", "PNB", "BANKBARODA", "CANBK", "UNIONBANK", "IOB", "BANKINDIA", "CENTRALBK", "UCOBANK", "IDBI"],
    "Financials / NBFC": ["BAJFINANCE", "BAJAJFINSV", "SHRIRAMFIN", "JIOFIN", "RECLTD", "PFC", "IRFC", "CHOLAFIN"],
    "Insurance": ["SBILIFE", "HDFCLIFE", "LICI", "ICICIGI"],
    "Automobiles": ["MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO", "TVSMOTOR", "ASHOKLEY"],
    "FMCG": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "TATACONSUM", "DABUR", "MARICO", "GODREJCP", "COLPAL", "VBL"],
    "Pharma & Healthcare": ["SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "APOLLOHOSP"],
    "Energy & Oil": ["RELIANCE", "ONGC", "IOC", "BPCL", "GAIL"],
    "Metals & Mining": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "SAIL", "NMDC", "COALINDIA"],
    "Cement": ["ULTRACEMCO", "GRASIM", "SHREECEM", "AMBUJACEM", "ACC"],
    "Power & Utilities": ["NTPC", "POWERGRID", "TATAPOWER", "ADANIPOWER", "ADANIGREEN", "NHPC"],
    "Infra & Realty": ["LT", "DLF", "LODHA", "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "PHOENIXLTD", "SOBHA", "BRIGADE", "GMRINFRA", "ADANIPORTS"],
    "Telecom": ["BHARTIARTL", "INDUSTOWER"],
    "Consumer & Retail": ["TITAN", "TRENT", "DMART", "ZOMATO", "JUBLFOOD"],
    "Capital Goods & Defence": ["SIEMENS", "BEL", "HAL", "ADANIENT"],
}

# Per-metric direction: True => a higher value is better for the company.
METRIC_DIRECTION = {
    "pe": False,
    "operatingMargin": True,
    "roe": True,
    "revenueGrowth": True,
    "debtToEquity": False,
}


class PeerSectorEvaluator:
    """
    F-04 (peer comparison) and F-17 (sector benchmark) engine.

    Builds a peer matrix from a stock's sector group, fetches valuation, margin,
    return, growth and leverage metrics via yfinance, ranks the target against
    its peers (best/worst markers), and computes sector medians plus the target's
    percentile standing on each metric.
    """

    def __init__(self, peer_map: dict = None):
        self.sector_groups = peer_map if peer_map is not None else SECTOR_GROUPS
        # Build a reverse index: symbol -> (sector_name, [peers])
        self._symbol_index = {}
        for sector, members in self.sector_groups.items():
            for sym in members:
                self._symbol_index[sym.upper()] = (sector, [m for m in members if m != sym])

    def _resolve_peers(self, symbol: str):
        sector, peers = self._symbol_index.get(symbol.upper(), (None, []))
        return sector, peers[:4]  # cap peer set for speed

    def _fetch_stock_metrics(self, symbol: str) -> dict:
        """Fetch valuation/return/growth/leverage metrics for a single symbol via
        yfinance `info` (fast). The slow Apify per-peer call was removed — it made
        peer synthesis take minutes."""
        clean_symbol = symbol.strip().upper()
        if clean_symbol.endswith('.NS'):
            clean_symbol = clean_symbol[:-3]

        try:
            import yfinance as yf
            symbol_ns = f"{clean_symbol}.NS"
            ticker = yf.Ticker(symbol_ns)
            info = ticker.info

            return {
                'symbol': clean_symbol,
                'lastPrice': info.get('currentPrice', info.get('lastPrice', info.get('regularMarketPrice'))),
                'pe': info.get('trailingPE'),
                'operatingMargin': info.get('operatingMargins'),
                'roe': info.get('returnOnEquity'),
                'revenueGrowth': info.get('revenueGrowth'),
                'debtToEquity': (info.get('debtToEquity') / 100.0) if info.get('debtToEquity') else None,
            }
        except Exception as e:
            print(f"[PeerSectorEvaluator] Warning: All sources failed for {clean_symbol}: {e}")
            return {
                'symbol': clean_symbol, 'lastPrice': None, 'pe': None,
                'operatingMargin': None, 'roe': None, 'revenueGrowth': None,
                'debtToEquity': None, 'error': str(e)
            }

    @staticmethod
    def _percentile(population, target, higher_is_better):
        """Target's percentile standing (0-100); higher = better positioned."""
        vals = [v for v in population if v is not None]
        if target is None or not vals:
            return None
        if higher_is_better:
            beaten = sum(1 for v in vals if v <= target)
        else:
            beaten = sum(1 for v in vals if v >= target)
        return round(beaten / len(vals) * 100)

    @staticmethod
    def _median(values):
        vals = [v for v in values if v is not None]
        return statistics.median(vals) if vals else None

    def fetch_peer_comparison_matrix(self, symbol: str) -> dict:
        clean_symbol = symbol.strip().upper()
        if clean_symbol.endswith('.NS'):
            clean_symbol = clean_symbol[:-3]

        sector, peers = self._resolve_peers(clean_symbol)
        print(f"[PeerSectorEvaluator] {clean_symbol} -> sector '{sector}', peers: {peers}")

        target_metrics = self._fetch_stock_metrics(clean_symbol)
        peer_matrix = [self._fetch_stock_metrics(p) for p in peers]

        all_rows = [target_metrics] + peer_matrix

        # --- F-04: best/worst rank markers per metric across target + peers ---
        for metric, higher_is_better in METRIC_DIRECTION.items():
            present = [(r['symbol'], r.get(metric)) for r in all_rows if r.get(metric) is not None]
            if not present:
                continue
            best = (max if higher_is_better else min)(present, key=lambda x: x[1])[0]
            worst = (min if higher_is_better else max)(present, key=lambda x: x[1])[0]
            for r in all_rows:
                r.setdefault('rank', {})
                if r.get(metric) is None:
                    r['rank'][metric] = None
                elif r['symbol'] == best:
                    r['rank'][metric] = 'best'
                elif r['symbol'] == worst:
                    r['rank'][metric] = 'worst'
                else:
                    r['rank'][metric] = None

        # --- F-17: sector medians + target percentile standing ---
        sector_medians = {}
        sector_percentiles = {}
        for metric, higher_is_better in METRIC_DIRECTION.items():
            population = [r.get(metric) for r in all_rows]
            sector_medians[metric] = self._median(population)
            sector_percentiles[metric] = self._percentile(
                population, target_metrics.get(metric), higher_is_better
            )

        valid_pcts = [p for p in sector_percentiles.values() if p is not None]
        overall_pct = round(sum(valid_pcts) / len(valid_pcts)) if valid_pcts else None

        # Backwards-compatible arithmetic averages (legacy UI field)
        def _avg(metric):
            vals = [p.get(metric) for p in peer_matrix if p.get(metric) is not None]
            return sum(vals) / len(vals) if vals else None

        sector_averages = {
            'lastPrice': _avg('lastPrice'), 'pe': _avg('pe'),
            'operatingMargin': _avg('operatingMargin'), 'roe': _avg('roe'),
        }

        # --- Comparative tags ---
        comparative_tags = []
        if sector_percentiles.get('roe') is not None and sector_percentiles['roe'] >= 60:
            comparative_tags.append("TOP-QUARTILE ROE" if sector_percentiles['roe'] >= 75 else "ABOVE-MEDIAN ROE")
        if sector_percentiles.get('pe') is not None and sector_percentiles['pe'] >= 50:
            comparative_tags.append("ATTRACTIVELY VALUED")
        if sector_percentiles.get('operatingMargin') is not None and sector_percentiles['operatingMargin'] >= 60:
            comparative_tags.append("SUPERIOR MARGINS")
        if sector_percentiles.get('revenueGrowth') is not None and sector_percentiles['revenueGrowth'] >= 60:
            comparative_tags.append("FASTER GROWTH")
        if sector_percentiles.get('debtToEquity') is not None and sector_percentiles['debtToEquity'] >= 60:
            comparative_tags.append("STRONGER BALANCE SHEET")
        if not comparative_tags:
            comparative_tags.append("IN-LINE WITH SECTOR")

        return {
            'sector': sector,
            'target_metrics': target_metrics,
            'peer_matrix': peer_matrix,
            'sector_averages': sector_averages,
            'comparative_tags': comparative_tags,
            # F-17 payload
            'sector_benchmark': {
                'sector': sector,
                'medians': sector_medians,
                'percentiles': sector_percentiles,
                'overall_percentile': overall_pct,
            },
        }


if __name__ == '__main__':
    import json
    evaluator = PeerSectorEvaluator()
    print("Testing PeerSectorEvaluator with INFY...")
    result = evaluator.fetch_peer_comparison_matrix('INFY')
    print(json.dumps(result, indent=4))
