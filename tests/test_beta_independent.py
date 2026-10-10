"""Beta (Sr 66) estimator checked against an independent method: the least-squares SLOPE of stock weekly returns on market weekly returns
(numpy.polyfit) equals cov/var (ddof=1) exactly; a stock built as 1.5 x the market has beta 1.5; fewer than 52 aligned returns -> no value.
When Yahoo history is reachable the same identity is also confirmed on a real stock's actual series (skipped offline)."""
import unittest

import numpy as np
import pandas as pd

from tools import market_history as mh


def _closes(n, k, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n + 1, freq="W")
    mret = rng.normal(0.002, 0.02, n)
    sret = k * mret + rng.normal(0, 0.005, n)
    m = pd.Series(100 * np.cumprod(np.r_[1, 1 + mret]), index=idx)
    s = pd.Series(50 * np.cumprod(np.r_[1, 1 + sret]), index=idx)
    return s, m


class TestBetaIndependent(unittest.TestCase):

    def test_equals_least_squares_slope(self):
        s, m = _closes(104, 1.3)
        got = mh.beta_from_close_series(s, m)
        slope = np.polyfit(m.pct_change().dropna().to_numpy(), s.pct_change().dropna().to_numpy(), 1)[0]
        self.assertAlmostEqual(got["beta"], slope, places=10)
        self.assertAlmostEqual(got["beta"], 1.3, delta=0.1)
        self.assertEqual(got["n"], 104)

    def test_exact_multiple_has_that_beta(self):
        idx = pd.date_range("2024-01-01", periods=105, freq="W")
        mret = np.tile([0.01, -0.02, 0.015, -0.005], 27)[:104]
        m = pd.Series(100 * np.cumprod(np.r_[1, 1 + mret]), index=idx)
        s = pd.Series(80 * np.cumprod(np.r_[1, 1 + 1.5 * mret]), index=idx)
        self.assertAlmostEqual(mh.beta_from_close_series(s, m)["beta"], 1.5, delta=0.02)

    def test_too_short_history_gives_no_value(self):
        s, m = _closes(40, 1.0)
        got = mh.beta_from_close_series(s, m)
        self.assertNotIn("beta", got)
        self.assertEqual(got["n"], 40)

    def test_real_series_matches_slope_when_reachable(self):
        try:
            from tools.yf_cache import cached_history
            st = cached_history("TCS.NS", period=mh.PERIOD, interval=mh.INTERVAL)
            ix = cached_history(mh.BENCHMARK, period=mh.PERIOD, interval=mh.INTERVAL)
            if st is None or st.empty or ix is None or ix.empty:
                raise RuntimeError("no data")
        except Exception as e:
            raise unittest.SkipTest(f"price history unreachable: {e}")
        got = mh.beta_from_close_series(st["Close"], ix["Close"])
        j = pd.concat([st["Close"].tz_localize(None), ix["Close"].tz_localize(None)], axis=1, join="inner").pct_change().dropna()
        self.assertAlmostEqual(got["beta"], np.polyfit(j.iloc[:, 1].to_numpy(), j.iloc[:, 0].to_numpy(), 1)[0], places=8)


if __name__ == "__main__":
    unittest.main()
