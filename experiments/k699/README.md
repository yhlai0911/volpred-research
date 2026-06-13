# K699: Contrarian Tilt Cross-OOS Validation

- Experiment ID: `K699`
- Status: completed
- Created At: 2026-04-16T09:40:33.613170+00:00
- Script: `experiments/k699/k699_contrarian_cross_oos.py`
- Results: `experiments/k699/k699_results.json`
- Data source: yfinance adjusted close for SPY and GLD
- Effective return sample: 2006-01-04 to 2026-03-27, 5,089 aligned observations
- Transaction cost assumption: 5 bps per unit turnover

## Question

K698 found a small full-period improvement from a simple contrarian tilt on a 50/50 SPY/GLD portfolio. K699 tests whether that apparent edge survives across non-overlapping market regimes.

## Method

Two lagged contrarian rules are compared against a 50/50 SPY/GLD baseline:

- Default: after an absolute SPY daily move above 1%, set the next-day SPY weight to 70% after a down day or 30% after an up day.
- Optimized: after an absolute SPY daily move above 2%, set the next-day SPY weight to 80% after a down day or 20% after an up day.

The signal is explicitly lagged with `ret_spy_full.shift(1)`, so the strategy uses the prior trading day's SPY return for the current day's allocation. The validation uses five non-overlapping OOS windows: 2008-2009, 2011-2013, 2015-2017, 2020-2021, and 2023-2024. Robustness requires at least 4 wins out of 5 on net Sharpe versus the baseline, with an additional Harvey-style t > 3 screen on period-level Sharpe deltas.

## Key Results

- Default 1% / 20% rule: wins 3 of 5 windows, mean net Sharpe delta +0.0128, period-delta t-stat 0.121, Harvey screen fails.
- Optimized 2% / 30% rule: wins 4 of 5 windows, mean net Sharpe delta +0.1762, period-delta t-stat 1.573, Harvey screen fails.
- Full-period confirmation from 2007 onward: default net Sharpe 0.8780 vs baseline 0.8433; optimized net Sharpe 0.9405 vs baseline 0.8433.
- The optimized rule's stronger result is concentrated in volatile reversal-heavy windows; the low-volatility 2015-2017 window remains negative.

## Conclusion

The 2% / 30% contrarian tilt is a marginal result: it passes the 4-of-5 cross-OOS win count but fails the stricter period-level statistical screen. The default 1% / 20% rule is rejected. The evidence supports a cautious reader-facing conclusion that contrarian dip-buying can help in some regimes, but is not stable enough to treat as a reliable standalone allocation rule.

## Artifacts

- `experiments/k699/k699_results.json`
- `experiments/k699/k699_cross_oos_deltas.png`
- `experiments/k699/k699_robustness_scorecard.png`
- `storage/drafts/k699_general_draft.md`
