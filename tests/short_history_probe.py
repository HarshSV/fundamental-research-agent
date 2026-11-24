"""How reliable is the forecast when only N sessions of history exist? Cut the long history of well-traded stocks to the last N sessions at many
past dates, make the call, and compare with what happened. Not a pytest: it reads the price provider (python tests/short_history_probe.py)."""
import statistics
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from setups import outlook  # noqa: E402
from tools.live_chart_yf import get_candles  # noqa: E402

SYMS = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ITC", "SBIN", "LT", "AXISBANK", "MARUTI", "SUNPHARMA", "TITAN", "ONGC", "NTPC", "COALINDIA", "HINDUNILVR", "BAJFINANCE", "ASIANPAINT", "TATASTEEL", "WIPRO", "CIPLA"]
NS = (70, 90)
H = (5, 20)
STEP = 7


def run():
    res = {(n, h): {"calls": 0, "hit": 0, "all": 0, "base_hit": 0, "n_even": 0} for n in NS for h in H}
    for s in SYMS:
        d = get_candles(s, interval="1d", period="max") or []
        if len(d) < 700:
            continue
        cl = [b["close"] for b in d]
        for h in H:
            for t in range(400, len(d) - h, STEP):
                actual = cl[t + h - 1 + 1 - 1] if False else cl[t - 1 + h] / cl[t - 1] - 1
                for n in NS:
                    w = d[t - n:t]
                    o = outlook.horizon_outlook(w, h, min_history=n if n < 250 else 250)
                    r = res[(n, h)]
                    r["all"] += 1
                    if o.get("call") is None:
                        continue
                    band = o["flat_band_pct"] / 100
                    real = "up" if actual > band else "down" if actual < -band else "flat"
                    if o["call"] == "even":
                        r["n_even"] += 1
                        continue
                    r["calls"] += 1
                    r["hit"] += real == o["call"]
                    r["base_hit"] += real == ("up")      # always saying "up", the naive bar to beat
    print("history | horizon | calls made | right when it leaned | always-up")
    for (n, h), r in sorted(res.items()):
        if r["calls"]:
            print(f"{n:7d} | {h:7d} | {r['calls']:10d} | {r['hit'] / r['calls']:.1%} | {r['base_hit'] / r['calls']:.1%}")


if __name__ == "__main__":
    run()
