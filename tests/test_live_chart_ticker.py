"""
Live-chart ticker resolution (tools/live_chart_yf._to_symbol): a removed company must not
keep resolving through the in-process ticker cache. Synthetic symbols, no network.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools import live_chart_yf as lc  # noqa: E402


def _reset():
    lc._TICKER_CACHE.clear()
    lc._CANDIDATES_PROVIDER = None
    lc._HAVE_YF = True


def test_bse_only_company_resolves_and_is_cached():
    _reset()
    lc._has_data = lambda t: t == "ZZTRADE.BO"
    lc.set_ticker_candidates_provider(lambda s: (["ZZTRADE.BO", "ZZMASTER.BO"], "Zz Trade Limited"))
    assert lc._to_symbol("ZZMASTER") == "ZZTRADE.BO"
    assert lc._TICKER_CACHE["ZZMASTER"] == "ZZTRADE.BO"


def test_removed_company_no_longer_resolves_via_cache():
    _reset()
    lc._has_data = lambda t: t == "ZZTRADE.BO"
    lc.set_ticker_candidates_provider(lambda s: (["ZZTRADE.BO", "ZZMASTER.BO"], "Zz Trade Limited"))
    assert lc._to_symbol("ZZMASTER") == "ZZTRADE.BO"
    # the company is deleted from the master: the provider now treats the symbol as unknown (NSE-style)
    lc.set_ticker_candidates_provider(lambda s: ([f"{s}.NS"], None))
    assert lc._to_symbol("ZZMASTER") == "ZZMASTER.NS"      # not the cached BSE ticker
    assert "ZZMASTER" not in lc._TICKER_CACHE               # and the stale entry is gone


def test_nse_company_unaffected():
    _reset()
    lc.set_ticker_candidates_provider(lambda s: ([f"{s}.NS"], None))
    assert lc._to_symbol("ABCNSE") == "ABCNSE.NS"
    assert lc._to_symbol("abcnse.ns") == "ABCNSE.NS"


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if failed else 0)
