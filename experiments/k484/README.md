# K484: SSVS for Variance Equation Component Selection

- Experiment ID: `K484`
- Status: completed
- Script: `experiments/k484/k484_ssvs_variance_eq.py`
- Results: `experiments/k484/k484_ssvs_variance_eq_results.json`
- Data source: yfinance daily SPY OHLCV and `^VIX`
- Data period: 2015-01-02 to 2025-12-30
- OOS period: 2023-01-01 onward, 751 aligned trading observations
- Random seed: `np.random.seed(42)`

## 問題描述

K433 showed that SSVS on the mean equation did not find useful SPY return predictors. K484 asks the variance-equation version of the same model-selection question: among five common GARCH variance extensions, which components are worth keeping?

The candidate components are GJR asymmetry, VIX implied variance, Parkinson range, rolling negative semivariance, and absolute shock.

## 方法

The experiment estimates a GARCH variance equation with stochastic search variable selection over the five components. It uses 8,000 MCMC iterations with 3,000 burn-in observations and evaluates OOS volatility forecasts against squared daily returns using QLIKE and MSE. Baselines include base GARCH(1,1), GJR-GARCH, the SSVS median model, and a kitchen-sink model with all components.

All variance predictors are lagged relative to the forecasted close-to-close return. VIX and Parkinson range are used after the close of day `t` to forecast the return from `t` to `t+1`; return-based components use prior returns.

## 結果

Four components have posterior inclusion probability equal to 1.000: GJR asymmetry, VIX implied variance, Parkinson range, and absolute shock. Rolling negative semivariance is excluded with PIP 0.094.

OOS QLIKE versus base GARCH:

| Model | QLIKE | Relative QLIKE |
|---|---:|---:|
| Base GARCH(1,1) | 1.619642 | 0.00% |
| SSVS median model | 1.499313 | -7.43% |
| Kitchen sink | 1.506124 | -7.01% |
| GJR-GARCH | 1.572479 | -2.91% |

DM tests versus base GARCH are significant for the three alternatives in this single OOS window. The SSVS median model also has the best in-sample BIC among the compared specifications.

## 限制

This is a single-asset, single-OOS-window result for SPY in 2023-2024. Later K485 performs cross-OOS validation and should be used before making broader regime-robust claims. MCMC diagnostics also show low effective sample size for several continuous parameters, so the strongest claim here is component-screening evidence plus this OOS window's forecast comparison, not a universal model ranking.

## 結論

K484 supports a restrained model-selection conclusion: richer variance structure can help, but the useful set is selected rather than all-inclusive. The article based on this experiment should retain the single-window limitation and avoid presenting the result as a general theorem across assets or regimes.
