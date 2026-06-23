# Codex Review: research_cornish_fisher_regime_tail_adjustment_sector_rot

## Scope

Reviewed the experiment script, generated CSVs, plots, and JSON result after running the full walk-forward strategy.

## Checks

- Data provenance: adjusted close prices are downloaded from `yfinance` and cached in `data/prices.csv`.
- Sample: the full 11-sector universe begins on 2018-06-19 because of XLC/XLRE history; OOS starts on 2021-07-01 after the 756-day HMM training window.
- Lookahead: weights are computed at month-end close and shifted one trading day before return application.
- Regime model: each rebalance refits a 2-state Gaussian HMM on trailing SPY returns only; the higher-variance state is labeled turbulent.
- Tail metric: Cornish-Fisher quantile uses lagged training-window moments; clipping of skew/kurtosis and CF z-score is disclosed as a stability guard.
- Costs: all strategy and baseline returns are net of 10 bps one-way turnover cost.
- Baselines: raw sector equal weight and a monthly volatility-targeted equal-weight baseline are both included.
- Inference: `strategy_dm_test` is used for return and downside comparisons; Harvey-style `abs(t) > 3` is recorded.
- Bootstrap: Sharpe differences use 1,000 fixed-seed circular block bootstrap samples.

## Findings

No implementation blocker found.

The only Harvey pass is the downside-loss comparison versus raw sector equal weight. The strategy fails to beat sector equal weight on return loss and fails both return and downside comparisons versus the volatility-targeted equal-weight baseline. The result should therefore remain a null for active sector rotation.

## Review Verdict

Accept as `NULL_CF_HMM_ROTATION_NO_EDGE`.
