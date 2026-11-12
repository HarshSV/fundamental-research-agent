"""The pieces of the pattern study that can be checked without market data."""
from __future__ import annotations

import numpy as np
import pandas as pd

from research import pattern_study as ps


def test_benjamini_hochberg_is_monotone_and_capped():
    q = ps.bh([0.001, 0.008, 0.039, 0.041, 0.9])
    assert q == sorted(q)                                    # corrected values never decrease down the sorted list
    assert q[0] == 0.005 and q[-1] == 0.9 and max(q) <= 1.0
    assert ps.bh([0.04]) == [0.04]                           # one test: no correction


def test_forward_table_enters_at_the_open_and_exits_at_the_close_of_the_hth_session():
    idx = [f"2026-01-{d:02d}" for d in range(1, 9)]
    df = pd.DataFrame({"open": [10, 11, 12, 13, 14, 15, 16, 17], "close": [11, 12, 13, 14, 15, 16, 17, 18]}, index=idx)
    wide, mkt = ps.forward_table({"A": df})
    assert np.isclose(wide[1]["A"]["2026-01-01"], 11 / 10 - 1)       # one session held: that day's close over that day's open
    assert np.isclose(wide[5]["A"]["2026-01-01"], 15 / 10 - 1)       # five sessions held: the fifth close over the first open
    assert np.isnan(wide[5]["A"]["2026-01-06"])                      # not enough sessions left to exit
    assert mkt[5]["2026-01-01"] == wide[5]["A"]["2026-01-01"]        # one stock: the median of the day is itself


def test_the_baseline_is_the_median_stock_not_the_mean():
    idx = ["2026-01-01", "2026-01-02"]
    mk = lambda c: pd.DataFrame({"open": [10, 10], "close": [c, c]}, index=idx)
    wide, mkt = ps.forward_table({"A": mk(10), "B": mk(10), "C": mk(40)})      # one stock quadruples: the mean is far above the typical stock
    assert np.isclose(mkt[1]["2026-01-01"], 0.0)
