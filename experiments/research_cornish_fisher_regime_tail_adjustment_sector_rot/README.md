# research_cornish_fisher_regime_tail_adjustment_sector_rot

## Question

Can a 2-state HMM market-regime signal plus Cornish-Fisher tail-risk estimates improve sector ETF rotation versus simple sector equal weight and a volatility-targeted equal-weight baseline?

The motivating idea is that a turbulent SPY regime should make downside asymmetry more relevant, so sector weights should tilt toward sectors with lower regime-conditional Cornish-Fisher tail risk, with an explicit defensive boost for XLP and XLU in turbulent regimes.

## Literature And Source Check

- Practitioner motivation: "Options Volatility Analysis: What Cornish-Fisher Tail Risk Reveals About the February 2026 Sector Rotation", February 2026. This is treated as a practitioner prompt, not a peer-reviewed result.
- Maillard, "A User's Guide to the Cornish Fisher Expansion", SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1997178.
- Wang, Lin, and Mikhelson (2020), "Regime-Switching Factor Investing with Hidden Markov Models", JRFM: https://www.mdpi.com/1911-8074/13/12/311.
- PerformanceAnalytics `VaR.CornishFisher` reference page, including modified VaR references: https://www.rdocumentation.org/packages/PerformanceAnalytics/versions/0.9.6/topics/VaR.CornishFisher.

## Data

- Source: `yfinance` adjusted close.
- Assets: 11 U.S. sector ETFs (`XLB`, `XLC`, `XLE`, `XLF`, `XLI`, `XLK`, `XLP`, `XLRE`, `XLU`, `XLV`, `XLY`) plus `SPY`.
- Price sample: 2018-06-19 to 2026-06-23.
- OOS strategy sample: 2021-07-01 to 2026-06-23, 1,249 trading days.
- Rebalance count: 61 monthly rebalances.

The sample starts in 2018 because the full 11-sector ETF set requires XLC and XLRE history.

## Design

At each month-end rebalance:

1. Fit a 2-state Gaussian HMM on trailing 756 SPY daily returns.
2. Label the higher-variance state as turbulent.
3. Use the current inferred state to select the matching training-window observations for each sector.
4. Estimate a Cornish-Fisher 5% left-tail quantile using sector returns in that state.
5. Define tail score as `0.65 * CF VaR loss + 0.35 * empirical ES loss below the CF quantile`.
6. Allocate by inverse tail score, with a 1.75x XLP/XLU defensive multiplier in turbulent states and a 25% single-sector cap.
7. Apply weights only from the next trading day onward.
8. Charge 10 bps per one-way turnover.

Baselines:

- `sector_ew`: monthly equal weight across the 11 sector ETFs.
- `sector_ew_vt`: equal weight scaled monthly to 12% annualized volatility using the trailing 63 daily returns, capped between 0.25x and 1.50x.

Tests:

- Net Sharpe, max drawdown, cumulative return.
- `strategy_dm_test` on daily net returns using `negative_return` and `downside` losses.
- Harvey-style hurdle: `abs(t) > 3.0`.
- 1,000 circular block bootstrap samples for Sharpe differences, block length 21 trading days.

## Results

Verdict: `NULL_CF_HMM_ROTATION_NO_EDGE`.

Performance:

| strategy | ann return | ann vol | Sharpe | max DD | cumulative return |
| --- | ---: | ---: | ---: | ---: | ---: |
| CF-HMM rotation | 10.12% | 14.09% | 0.718 | -19.00% | 61.26% |
| Sector EW | 10.84% | 14.82% | 0.731 | -19.19% | 66.51% |
| Sector EW VT | 10.35% | 13.23% | 0.782 | -16.17% | 62.94% |

DM tests:

| model | baseline | loss | t | Harvey pass | model better |
| --- | --- | --- | ---: | --- | --- |
| CF-HMM | Sector EW | negative return | 1.043 | no | no |
| CF-HMM | Sector EW | downside | -3.519 | yes | yes |
| CF-HMM | Sector EW VT | negative return | 0.048 | no | no |
| CF-HMM | Sector EW VT | downside | 1.189 | no | no |

Bootstrap Sharpe differences:

| comparison | mean | 95% CI | P(diff > 0) |
| --- | ---: | --- | ---: |
| CF-HMM minus Sector EW | -0.013 | [-0.117, 0.095] | 0.402 |
| CF-HMM minus Sector EW VT | -0.061 | [-0.359, 0.238] | 0.361 |

Regime diagnostics:

- Turbulent monthly rebalance share: 29.5%.
- XLP is the lowest-tail sector in 54 of 61 rebalances.
- XLE is the highest-tail sector in 53 of 61 rebalances.

## Interpretation

The strategy slightly reduces downside loss versus raw sector equal weight, but it does not improve return, Sharpe, cumulative performance, or drawdown versus the volatility-targeted equal-weight baseline. Once a simple VT baseline is included, the apparent risk-management benefit disappears.

The CF-HMM signal mostly becomes a persistent XLP/XLU defensive tilt, not a strong dynamic sector-rotation edge. This is useful as a diagnostic: Cornish-Fisher tail asymmetry can identify defensive sectors, but in this free ETF implementation it does not beat a simpler risk-scaled baseline.

## Limitations

- XLC and XLRE shorten the full-sector sample to post-2018.
- HMM state labels are estimated from SPY returns only, not from a multi-asset covariance model.
- Cornish-Fisher quantiles are clipped to avoid non-monotone/extreme sample-moment artifacts; this is a stability guard, not an exact CF implementation.
- The VT baseline allows capped leverage without explicit financing cost.
- Monthly sector ETF rotation is a coarse proxy for any option-implied sector tail-risk framework.

## Files

- `research_cornish_fisher_regime_tail_adjustment_sector_rot.py` - full experiment script.
- `research_cornish_fisher_regime_tail_adjustment_sector_rot_results.json` - machine-readable result summary.
- `data/prices.csv` and `data/daily_returns.csv` - source price and return data.
- `data/cf_hmm_rotation_rebalance_weights.csv` - monthly strategy weights.
- `data/rebalance_diagnostics.csv` - HMM state and CF tail diagnostics.
- `data/strategy_net_returns.csv` - aligned net returns for strategy and baselines.
- `data/performance_summary.csv` - performance table.
- `data/dm_tests.csv` - DM test table.
- `figures/cumulative_returns.png` - net cumulative return chart.
- `figures/regime_weights.png` - turbulent-regime signal and selected weights.
