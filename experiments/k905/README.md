# K905: Quantile Regression for Volatility

- Experiment ID: `K905`
- Status: `COMPLETE`
- Created At: 2026-04-16T09:41:26.985182+00:00
- Script: `experiments/k905/k905_quantile_vol_forecast.py`
- Results: `experiments/k905/k905_quantile_vol_forecast_results.json`
- Article figures: `experiments/k905/k905_article_figures.py`

## Problem

K905 tests whether direct quantile forecasting models improve SPY tail-risk
forecasts relative to GJR-GARCH distributional baselines.

The core comparison is:

- `M1_Normal`: GJR-GARCH(1,1) plus Normal quantile.
- `M2_StudentT`: GJR-GARCH(1,1) plus scaled Student-t quantile.
- `M3_FHS`: GJR-GARCH(1,1) plus filtered historical simulation.
- `M4_CAViaR`: CAViaR-SAV direct quantile recursion.
- `M5_QuantHAR`: HAR-style quantile regression.

## Data

- Source: `yfinance`, ticker `SPY`.
- Download window in script: `2005-01-01` through the data available at run time.
- Stored result data source: `yfinance (SPY, 2005-01-01 to 2026-04-02)`.
- Out-of-sample period: `2019-01-02` to `2026-04-02`.
- OOS sample size: `1,823` trading days.

## Method

The script uses an expanding-window OOS loop with refits every 63 trading days.
Forecasts are one-step-ahead and use data through `t-1` for the return evaluated
at `t`.

Evaluation metrics:

- 1% and 5% VaR violation rates.
- Kupiec unconditional coverage test.
- Christoffersen independence test.
- Basel-style 250-day traffic-light screen.
- Acerbi-Szekely ES backtest.
- Pinball loss for quantile forecast accuracy.
- DM tests on pinball loss versus `M3_FHS`, using the project convention
  `abs(t) > 3.0` for Harvey-style publication caution.

Random optimizer restarts use fixed deterministic seeds inside each model fit.

## Results

Main stored findings:

- `M3_FHS` has the lowest pinball loss at both 1% and 5% tails.
- At 1% VaR, only `M2_StudentT` and `M3_FHS` pass the full Trinity screen.
- At 5% VaR, all five models fail the script's full Trinity screen because the
  Basel-style 250-day traffic-light check is applied in addition to Kupiec and
  Christoffersen.
- If the 5% result is read only through Kupiec + Christoffersen coverage tests,
  `M1_Normal`, `M3_FHS`, `M4_CAViaR`, and `M5_QuantHAR` pass both coverage
  checks; `M2_StudentT` fails Kupiec at 5%.
- No model significantly outperforms `M3_FHS` on pinball loss under the
  `abs(t) > 3.0` publication threshold.

## Figures

`k905_article_figures.py` generates:

- `k905_pinball_ranking.png`
- `k905_violation_rates.png`

Both figures are derived directly from
`k905_quantile_vol_forecast_results.json`.

## Limitations

- The Basel traffic-light rule is designed around 1% regulatory VaR exceptions.
  Applying the same screen to 5% VaR is a conservative project screen, not a
  formal Basel 5% verdict.
- The DM tests use a HAC variance estimate and the project `abs(t) > 3.0`
  threshold; the artifact does not store HLN small-sample adjusted p-values.
- ES results are consistently poor across models and should not be treated as
  solved by the VaR ranking.
- This experiment is SPY-only; cross-asset generalization requires separate
  experiments.

## Post-Publish Review

- 2026-06-13 Codex 24h-rule review for `mile_40c66bef`: article numbers match
  the stored JSON and lookahead protection is present. The article was revised
  to clarify that the 5% "all fail" statement referred to the script's strict
  Trinity screen, not to Kupiec + Christoffersen coverage tests alone.
