"""Does the Create Screener reproduce each preset scanner? For every preset, the same stocks must come back from the preset itself and from
the Create Screener's controls set the way the preset's definition reads. Run: python tests/screener_presets_probe.py (uses the stored market scan)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from patterns import screen_engine as eng  # noqa: E402

DMA50 = {"periods": [50], "side": "above"}
RESIST = {"require": True, "states": ["near", "breakout"]}

# preset id -> the Create Screener filters that should give the same stocks
RECIPES = {
    "tight-setup": {"dma": DMA50, "tight": {"timeframe": "daily", "bars": 5, "max_spread": 2.5}},
    "tight-setup-weekly": {"dma": DMA50, "tight": {"timeframe": "weekly", "bars": 3, "step": 1.5}},
    "inside-bar": {"inside_bar": {"timeframe": "daily"}},
    "inside-bar-weekly": {"inside_bar": {"timeframe": "weekly"}},
    "inside-bar-filtered": {"dma": DMA50, "inside_bar": {"timeframe": "daily", "max_ratio": 60}},
    "inside-bar-weekly-filtered": {"dma": DMA50, "inside_bar": {"timeframe": "weekly", "max_ratio": 60}},
    "rs-high-before-price-high": {"pct_52w_high": {"min": 2}, "rs_near_high": {"benchmark": "nifty500", "lookback": 252, "tolerance": 0.1}},
    "high-volume": {"sort": "traded_value"},
    "gap-filling": {"gap_fill": {"min_gap": 2, "lookback": 14}},
    "earnings-gap-up": {"earnings": {"quarter": "latest", "gap": 3}},
    "earnings-gap-up-prev": {"earnings": {"quarter": "previous", "gap": 3}},
    "positive-earnings-reaction": {"earnings": {"quarter": "latest", "best_gain": 5, "sessions": 5, "holds": True}},
    "positive-earnings-reaction-prev": {"earnings": {"quarter": "previous", "best_gain": 5, "sessions": 5, "holds": True}},
    "ipo-setups": {"listed_after": {"date": "2022-12-31"}, "dma": DMA50, "resistance": RESIST, "tight": {"timeframe": "daily", "bars": 5, "max_spread": 2.5},
                   "any_of": {"on": True}},
}


def symbols(pattern, f):
    out, page = [], 1
    while True:
        res = eng.search(pattern, {**f, "page": page, "page_size": 100})
        out += [r["symbol"] for r in res["rows"]]
        if len(out) >= res["total"] or not res["rows"]:
            return out
        page += 1


def main() -> int:
    bad = 0
    for preset, recipe in RECIPES.items():
        want, got = symbols(preset, {}), symbols("all", recipe)
        ok = set(want) == set(got) and (preset != "high-volume" or want[:50] == got[:50])
        bad += not ok
        print(f"{'OK  ' if ok else 'DIFF'} {preset:34s} preset {len(want):5d}  screener {len(got):5d}" + ("" if ok else f"  only preset: {sorted(set(want) - set(got))[:5]}  only screener: {sorted(set(got) - set(want))[:5]}"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
