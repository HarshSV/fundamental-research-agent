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


# ---------------------------------------------------------------------------
# Market-cap classification (SEBI/AMFI-aligned, approximate ₹-crore cutoffs).
# SEBI defines large/mid/small by rank (top 100 / 101-250 / 251+); these absolute
# thresholds approximate those rank cutoffs as of FY25 and are easy to tune.
# ---------------------------------------------------------------------------
LARGE_CAP_MIN_CR = 80000   # ~ rank 100 by market cap
MID_CAP_MIN_CR = 25000     # ~ rank 250 by market cap


def classify_market_cap(market_cap_cr):
    """Return 'Large Cap' / 'Mid Cap' / 'Small Cap' for a market cap in ₹ crore."""
    if market_cap_cr is None:
        return None
    try:
        mc = float(market_cap_cr)
    except (TypeError, ValueError):
        return None
    if mc >= LARGE_CAP_MIN_CR:
        return "Large Cap"
    if mc >= MID_CAP_MIN_CR:
        return "Mid Cap"
    return "Small Cap"


# Comparison columns rendered for the Screener-sourced peer table. `pct_raw` means
# the value is already a percentage number (e.g. 12.5 == 12.5%), not a fraction.
SCREENER_PEER_COLUMNS = [
    {"key": "marketCapCr", "label": "Market Cap", "fmt": "cr", "higher_is_better": None},
    {"key": "price", "label": "Price", "fmt": "inr", "higher_is_better": None},
    {"key": "pe", "label": "P/E", "fmt": "num", "higher_is_better": False},
    {"key": "roce", "label": "ROCE", "fmt": "pct_raw", "higher_is_better": True},
    {"key": "qtrProfitGrowth", "label": "Qtr Profit Growth (YoY)", "fmt": "pct_raw", "higher_is_better": True},
    {"key": "qtrSalesGrowth", "label": "Qtr Sales Growth (YoY)", "fmt": "pct_raw", "higher_is_better": True},
    {"key": "divYield", "label": "Div Yield", "fmt": "pct_raw", "higher_is_better": None},
]


def _peer_val(metrics: dict, key: str):
    """Pull a numeric value out of a Screener {raw, value, label} metric cell."""
    cell = (metrics or {}).get(key)
    if isinstance(cell, dict):
        return cell.get("value")
    return cell


def _extract_screener_peer(p: dict) -> dict:
    """Flatten one Screener peer record into a compact comparison row."""
    m = p.get("metrics", {}) or {}
    mcap = _peer_val(m, "marketCapitalization")
    return {
        "name": p.get("name"),
        "symbol": (p.get("symbol") or "").upper(),
        "screenerRank": p.get("rank"),
        "marketCapCr": mcap,
        "capTier": classify_market_cap(mcap),
        "price": _peer_val(m, "currentPrice"),
        "pe": _peer_val(m, "priceToEarning"),
        "roce": _peer_val(m, "returnOnCapitalEmployed"),
        "qtrProfitGrowth": _peer_val(m, "yoyQuarterlyProfitGrowth"),
        "qtrSalesGrowth": _peer_val(m, "yoyQuarterlySalesGrowth"),
        "divYield": _peer_val(m, "dividendYield"),
        "netProfitQtrCr": _peer_val(m, "netProfitLatestQuarter"),
        "salesQtrCr": _peer_val(m, "salesLatestQuarter"),
    }


def suggest_comparison_parameters(target_name: str, peer_names: list, cap_tier: str) -> dict:
    """
    Ask the LLM which comparison parameters matter most for this company type, and
    to name the sector it belongs to. Falls back to a keyword heuristic when Groq
    is unavailable so the feature degrades gracefully (never raises).

    Returns: {"sector_guess": str, "recommended": [column keys], "note": str}
    """
    valid_keys = [c["key"] for c in SCREENER_PEER_COLUMNS]

    def _heuristic():
        names = " ".join([str(target_name or "")] + [str(n) for n in (peer_names or [])]).lower()
        is_financial = any(w in names for w in [
            "bank", "finance", "financ", "nbfc", "insurance", "capital", "fin ", "fin.", "housing"
        ])
        if is_financial:
            return {
                "sector_guess": "Banking / Financials",
                # ROCE/operating-margin style metrics are not meaningful for lenders;
                # lead with valuation, growth and size instead.
                "recommended": ["pe", "qtrProfitGrowth", "marketCapCr", "divYield"],
                "note": "For lenders & financials, ROCE/operating margin are not comparable — "
                        "focus on P/E, quarterly profit growth, size and dividend yield.",
            }
        return {
            "sector_guess": "General",
            "recommended": ["roce", "pe", "qtrProfitGrowth", "qtrSalesGrowth"],
            "note": "Capital efficiency (ROCE), valuation (P/E) and growth momentum are the "
                    "primary cross-peer quality signals for this company.",
        }

    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key or api_key.strip() in ("", "your_api_key_here"):
        return _heuristic()

    try:
        import json as _json
        from groq import Groq
        client = Groq(api_key=api_key.strip())
        cols_desc = ", ".join([f'{c["key"]} ({c["label"]})' for c in SCREENER_PEER_COLUMNS])
        prompt = (
            f"A peer-comparison table is being shown for the Indian listed company "
            f"\"{target_name}\" ({cap_tier or 'unknown cap'}). Its peers are: "
            f"{', '.join([str(n) for n in (peer_names or [])][:10])}.\n\n"
            f"Available comparison columns (use these exact keys): {cols_desc}.\n\n"
            "Decide which sector this company belongs to, and which 3-5 of the available "
            "columns are the MOST meaningful for comparing it against these peers "
            "(e.g. ROCE is meaningless for banks; growth & valuation matter more for small-caps).\n"
            "Respond ONLY with compact JSON: "
            '{"sector_guess": "...", "recommended": ["key1","key2",...], "note": "one short sentence why"}'
        )
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are an equity research analyst. Reply with strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=300,
            temperature=0.2,
        )
        text = (completion.choices[0].message.content or "").strip()
        if text.startswith("```"):
            import re as _re
            text = _re.sub(r"^```(?:json)?\n", "", text)
            text = _re.sub(r"\n```$", "", text).strip()
        parsed = _json.loads(text)
        rec = [k for k in (parsed.get("recommended") or []) if k in valid_keys]
        if not rec:
            return _heuristic()
        return {
            "sector_guess": parsed.get("sector_guess") or "—",
            "recommended": rec,
            "note": parsed.get("note") or "",
        }
    except Exception as e:
        print(f"[peer_synthesis] AI parameter suggestion failed ({e}); using heuristic.")
        return _heuristic()


def build_screener_peer_comparison(symbol: str, screener_peers: list,
                                   target_name: str = None,
                                   target_market_cap_cr: float = None) -> dict | None:
    """
    Build the size/sector-aware peer comparison from Screener.in's company-specific
    peer list. Returns None when no usable peers are present (caller then falls back
    to the legacy sector-group matrix).
    """
    rows = [_extract_screener_peer(p) for p in (screener_peers or []) if p]
    rows = [r for r in rows if r.get("symbol") or r.get("name")]
    if not rows:
        return None

    target_sym = (symbol or "").upper()
    target_row = next((r for r in rows if r.get("symbol") == target_sym), None)
    if target_row is None:
        # Screener didn't include the target in its own peer list — synthesize a
        # minimal target row so the table still anchors on it.
        target_row = {
            "name": target_name or target_sym, "symbol": target_sym,
            "marketCapCr": target_market_cap_cr,
            "capTier": classify_market_cap(target_market_cap_cr),
            "price": None, "pe": None, "roce": None, "qtrProfitGrowth": None,
            "qtrSalesGrowth": None, "divYield": None, "isTarget": True,
        }
    else:
        target_row["isTarget"] = True
        if target_name:
            target_row["name"] = target_name

    peers = [r for r in rows if r is not target_row]
    # Sort peers by market cap (largest first) so the "top N" shown are the most
    # prominent comparables; None caps sink to the bottom.
    peers.sort(key=lambda r: (r.get("marketCapCr") is not None, r.get("marketCapCr") or 0), reverse=True)

    all_rows = [target_row] + peers

    # Best/worst markers + medians + target percentile per ranked column.
    medians, percentiles = {}, {}
    for col in SCREENER_PEER_COLUMNS:
        key, hib = col["key"], col["higher_is_better"]
        present = [(r["symbol"], r.get(key)) for r in all_rows if r.get(key) is not None]
        if present and hib is not None:
            best = (max if hib else min)(present, key=lambda x: x[1])[0]
            worst = (min if hib else max)(present, key=lambda x: x[1])[0]
            for r in all_rows:
                r.setdefault("rank", {})
                if r.get(key) is None:
                    r["rank"][key] = None
                elif r["symbol"] == best:
                    r["rank"][key] = "best"
                elif r["symbol"] == worst:
                    r["rank"][key] = "worst"
                else:
                    r["rank"][key] = None
        population = [r.get(key) for r in all_rows]
        medians[key] = PeerSectorEvaluator._median(population)
        if hib is not None:
            percentiles[key] = PeerSectorEvaluator._percentile(population, target_row.get(key), hib)

    valid_pcts = [p for p in percentiles.values() if p is not None]
    overall_pct = round(sum(valid_pcts) / len(valid_pcts)) if valid_pcts else None

    ai_guidance = suggest_comparison_parameters(
        target_row.get("name"), [p.get("name") for p in peers], target_row.get("capTier")
    )

    return {
        "available": True,
        "target": target_row,
        "peers": peers,                       # full list; UI shows top N + "see more"
        "columns": SCREENER_PEER_COLUMNS,
        "medians": medians,
        "percentiles": percentiles,
        "overall_percentile": overall_pct,
        "cap_tier": target_row.get("capTier"),
        "peer_count": len(peers),
        "ai_guidance": ai_guidance,
        "source": "screener.in",
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

    def _resolve_screener_peer_view(self, symbol: str, raw_payload: dict = None) -> dict | None:
        """
        Build the size/sector-aware peer view from Screener.in's per-company peer
        list. Prefers peers already present in the fetched payload (free); otherwise
        calls the cached Screener API. Best-effort — returns None on any failure so
        the legacy sector-group matrix remains the fallback.
        """
        try:
            screener_peers = None
            target_name = None
            target_market_cap_cr = None

            if raw_payload:
                screener_peers = raw_payload.get("screener_peers")
                info = raw_payload.get("info") or {}
                target_name = info.get("longName") or info.get("shortName")
                mc = info.get("marketCap") or raw_payload.get("marketCap")
                if mc:
                    target_market_cap_cr = mc / 1e7  # absolute INR -> ₹ crore

            # Not in the payload (yfinance was primary) -> use the cached Screener API.
            if not screener_peers:
                try:
                    from tools.screener_api import fetch_screener_fundamentals
                    sp = fetch_screener_fundamentals(symbol)
                    if sp:
                        screener_peers = sp.get("screener_peers")
                        if not target_name:
                            target_name = (sp.get("info") or {}).get("longName")
                        if target_market_cap_cr is None and sp.get("marketCap"):
                            target_market_cap_cr = sp["marketCap"] / 1e7
                except Exception as e:
                    print(f"[PeerSectorEvaluator] Screener peer fetch failed for {symbol}: {e}")

            if not screener_peers:
                return None
            return build_screener_peer_comparison(
                symbol, screener_peers, target_name, target_market_cap_cr
            )
        except Exception as e:
            print(f"[PeerSectorEvaluator] Screener peer view build failed for {symbol}: {e}")
            return None

    def fetch_peer_comparison_matrix(self, symbol: str, raw_payload: dict = None) -> dict:
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

        # --- Size/sector-aware peer comparison from Screener.in (company-specific
        # peers + market-cap tier + AI-suggested parameters). Works for the whole
        # universe, including small/mid-caps absent from the hardcoded sector groups.
        screener_view = self._resolve_screener_peer_view(clean_symbol, raw_payload)

        # Pick the market-cap tier for the target (Screener view preferred).
        cap_tier = screener_view.get('cap_tier') if screener_view else None
        if cap_tier is None and raw_payload:
            mc = (raw_payload.get('info') or {}).get('marketCap') or raw_payload.get('marketCap')
            if mc:
                cap_tier = classify_market_cap(mc / 1e7)

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
            # New: size/sector-aware Screener peer view + market-cap classification.
            'cap_tier': cap_tier,
            'screener_peer_view': screener_view,
        }


if __name__ == '__main__':
    import json
    evaluator = PeerSectorEvaluator()
    print("Testing PeerSectorEvaluator with INFY...")
    result = evaluator.fetch_peer_comparison_matrix('INFY')
    print(json.dumps(result, indent=4))
