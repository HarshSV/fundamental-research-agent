# Pattern evidence study (2026-11-12)

**Question:** do the chart patterns the agent confirms lead to anything a trader could use? Code: `research/pattern_study.py` (event study), `research/lookahead_check.py`
(look-ahead test), tests `tests/test_pattern_study.py`. Results: `data/research/pattern_study*.json` (not in git). Nothing on the live site was changed by this study.

## Method
* **Events:** every daily pattern ever confirmed in `data/patterns/patterns.db` (100,541 events after de-duplication; 751 stocks; 17 Dec 2021 to 5 Nov 2026), whatever happened to it afterwards.
  *A first version kept only patterns still "confirmed" today. That silently dropped the 41,000 that were confirmed and later invalidated, and made order blocks and pocket pivots look
  far too good (about +5% over 20 sessions with a 70-79% win rate, in both directions). It was caught because bullish and bearish both "worked"; the corrected study has no such effect.*
* **Trade:** enter at the open of the first session after the confirmation bar (the signal is known only at that bar's close); exit at the close of the h-th session held (h = 1, 5, 10, 20).
* **Excess return:** minus the return of the **median stock** entering the same day (so a rising market is not credited to the pattern; the median, not the mean, because returns are skewed
  and the mean sits above the typical stock). Bearish patterns count with the sign flipped. A cost of **0.25%** per trade is deducted (an assumption: brokerage, taxes, slippage).
* **De-duplication:** one event per stock, pattern and direction in any 10 sessions.
* **Significance:** events are grouped by the month they were confirmed (they share the market's mood), t-test across months, Benjamini-Hochberg correction over all 144 tests. A pattern is called a
  real effect only if the corrected q < 0.05, the average is positive, and it is positive in **both** halves of the period (before and from 1 July 2024).
* **Robustness:** entry delayed by 1 and 2 extra sessions gives the same picture.
* **Look-ahead test:** replaying 11 stocks on a series cut at 70% of its length reproduced all 1,542 confirmations up to the cut for every detector, with no extra ones (ipo-base differs only
  because its "listing date known" flag depends on where the series ends, not on the future). So detection does not use future bars.

## Findings (20 sessions held, after costs)
| | Result |
|---|---|
| Patterns with a real positive effect | **4 of 23 bullish**: pocket-pivot (+0.97%), order-block (+0.97%), falling-wedge (+0.84%), undercut-and-rally (+0.76%), positive in both halves and with delayed entry |
| ...but | The **median** trade of those four is **negative** (-0.2% to -0.5%) and they win 47-48% of the time: the average comes from a few large winners. Not a reliable edge for one trade |
| Other bullish patterns (Cup & Handle, VCP, Double Bottom, Flat Base, Ascending Triangle...) | Average +0.5% to +1.1%, **not statistically distinguishable from zero** |
| High Tight Flag | +7.0% but only 59 events, q = 0.08: not proven |
| Bearish patterns (13 of them) | **Wrong way on average**: stocks beat the median by 0.7% to 2.3% after them. 39 of 144 tests flag this as a reverse effect (rising wedge, head and shoulders, double top, triple top, wyckoff upthrust, symmetrical triangle, order-block bearish...) |

**Read with care**
* Only stocks listed today are included. Stocks that fell hard and were delisted are missing, which biases results **against bearish** patterns, so "bearish patterns are inverted" is not proven. What is proven: in this sample, they gave no shorting edge.
* 2021-2026 was mostly a rising market for Indian stocks. Results can differ in another regime.
* Overlapping 20-session windows and events in the same month are not independent; the monthly grouping handles most of this, not all.
* The detectors are untuned; this is a baseline, not a verdict on the ideas.

## What it means for Navrist
*Applied 2026-11-12: the landing-page chips (`Hero.tsx`, `TOP_PATTERNS`) now lead with pocket-pivot, order-block, falling-wedge and undercut-and-rally, then Cup & Handle, VCP, Double Bottom, High Tight Flag, Triple Bottom and Flat Base; the bearish patterns sit behind "More"; a note under the chips says a confirmed pattern is not a forecast.*
* The previous landing-page **top 10 patterns** (Cup & Handle, VCP, Head & Shoulders, Double Bottom, Symmetrical Triangle, Double Top, Ascending Triangle, Inverse H&S, Descending Triangle, Rectangle) came from general reputation, not measurement. By this study, only pocket-pivot, order-block, falling-wedge and undercut-and-rally have a measurable effect, and it is small.
* The pattern pages should say that confirmation is **not** a forecast, and bearish patterns should not be presented as sell signals without a caveat.
* Next steps: tune detector thresholds on the first half and test them on the second half; add trade-plan (stop and target) simulation; repeat when more history is stored.

## vectorbt
Installing vectorbt in a fresh environment failed here: Windows Application Control blocked a pandas library file in the new folder. No attempt was made to bypass the policy, and the environment was removed. The event study needs only numpy, pandas and scipy, which the project already has. A stop-and-target simulator can be written with numpy, or vectorbt installed once the policy allows it.
