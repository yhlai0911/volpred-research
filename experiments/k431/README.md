# K431: Smooth Transition GARCH vs GJR on SPY

- Experiment ID: `k431`
- Status: completed; v2 rerun completed 2026-06-16
- Source article: `mile_764012ef`
- Scripts:
  - `k431_stgarch.py`: original run used by the first article version.
  - `k431_stgarch_v2.py`: lookahead/state-propagation fix rerun.
- Results:
  - `k431_stgarch_results.json`: original results.
  - `k431_stgarch_v2_results.json`: canonical reviewed results.

## Question

Does adding a logistic smooth-transition mechanism to daily SPY GARCH improve out-of-sample volatility forecasts relative to GJR-GARCH?

## Data

- Asset: SPY daily returns from yfinance, with VIX as an external transition variable for one STGARCH variant.
- Sample: 2005-01-04 to 2026-03-24, `N=5338`.
- OOS evaluation: 2023-01-01 to 2024-12-31, `N=502`.
- Loss proxy: squared daily return.
- QLIKE formula: `mean(log(forecast_variance) + realized_squared_return / forecast_variance)`.

## Models

- GARCH(1,1)
- GJR-GARCH(1,1)
- STGARCH-VIX
- STGARCH-|ret|
- STGARCH-lagvol

## v2 Fixes

The original article/code review found that headline direction was likely robust, but exact STGARCH margins were not reliable. `k431_stgarch_v2.py` applies four fixes:

1. STGARCH-lagvol transition variable uses walk-forward in-sample-only GJR conditional volatility instead of a full-sample GJR fit.
2. GARCH/GJR rolling baselines use `iloc[idx-lookback:idx]` and `forecast(horizon=1)`, so the OOS forecast excludes the return being evaluated.
3. STGARCH OOS recursion carries forward `h_forecast` as the current variance state instead of double-advancing the state.
4. STGARCH log-likelihood/AIC/BIC add the Gaussian normalizing constant for comparability with `arch_model`.

## v2 OOS Results

| Model | QLIKE | Difference vs GJR | Two-sided DM p |
|---|---:|---:|---:|
| GJR-GARCH(1,1) | 0.5588 | baseline | -- |
| STGARCH-lagvol | 0.5870 | +5.05% | 0.0142 |
| STGARCH-VIX | 0.5882 | +5.26% | 0.0133 |
| GARCH(1,1) | 0.5890 | +5.40% | 0.0082 |
| STGARCH-|ret| | 0.5955 | +6.56% | 0.0014 |

## Interpretation

GJR remains the best OOS model under the v2 reviewed implementation. The STGARCH variants still do not beat GJR, but the original article overstated the STGARCH gap: after v2 fixes, the STGARCH disadvantage is about 5.05-6.56%, not 9-12%.

The DM tests in this experiment are conventional two-sided tests on OOS-only QLIKE loss differentials. They do not include HAC/Newey-West serial-correlation adjustment or Harvey-Leybourne-Newbold small-sample correction, so publication language should not claim Harvey-level significance.

## Article Update

`mile_764012ef` was updated on 2026-06-16 to use the v2 numbers and a more conservative interpretation. The headline conclusion did not reverse, but the exact gaps, parameter-count statement, and DM-strength language were corrected.
