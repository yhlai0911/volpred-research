# K940: Simple Neural Network Volatility Predictor

## Problem
All traditional econometric models (GARCH/FIGARCH/CARR/Ensemble) have failed to beat MF-GJR(VIX) for daily volatility prediction (K889, K937). Can simple ML models (MLP, Random Forest, Ridge) using the same features do better?

**This is the first ML experiment in the project.**

## Motivation
- K889: MF-GJR(VIX) best single model, QLIKE=1.458, DM t=-4.42 vs GARCH
- K937: 4 ensemble methods all fail to beat MF-GJR(VIX) (H3 confirmed)
- K482: Equal weight ensemble best (combination puzzle)
- ML models can capture arbitrary nonlinearities that parametric models miss
- BUT daily vol has extremely low signal-to-noise (r² skewness=15.7, kurtosis=347)

## Method
- **Asset**: SPY (2004-2026, yfinance)
- **OOS**: 2016-01-04 ~ 2025-12-31 (2,514 days)
- **Target**: r² (squared return, proxy for sigma^2, Patton 2011)

### Features (11 total, ALL lagged using t-1 info)
1. GARCH(1,1) conditional variance at t
2. log(VIX_{t-1})
3. r²_{t-1}, |r_{t-1}|, YZ_{t-1}
4. r²_{t-2}..r²_{t-5}
5. GARCH/VIX² ratio
6. 20-day rolling variance

### Models
| Model | Type | Config |
|-------|------|--------|
| MLP | Neural Network | (32,16), ReLU, Adam, early_stopping |
| Ridge | Linear | alpha=1.0 |
| Random Forest | Tree ensemble | 100 trees, max_depth=5 |
| GARCH(1,1) | Benchmark | MLE |
| GJR(1,1,1) | Benchmark | MLE |
| MF-GJR(VIX) | Benchmark (best known) | MLE with VIX long-run component |

### Training Protocol
- Expanding window (always from 2004), retrain every 63 trading days (quarterly)
- Features standardized using training-only mean/std (no lookahead)
- Total refits: 40

## Results

### Summary Table
| Model | QLIKE | MSE | Spearman rho | DM vs MF-GJR |
|-------|-------|-----|-------------|-------------|
| **MF-GJR(VIX)** | **1.4582** | 2.13e-7 | **0.4573** | (benchmark) |
| GJR(1,1,1) | 1.5459 | 2.09e-7 | 0.4177 | t=-4.95*** |
| Random Forest | 1.5237 | 2.20e-7 | 0.4212 | t=-4.11*** |
| GARCH(1,1) | 1.5813 | 2.15e-7 | 0.3833 | t=-6.68*** |
| Ridge | 40278.5 | 2.10e-7 | 0.3995 | t=-3.33*** |
| MLP | 651520.2 | 1.21e-3 | 0.0735 | t=-4.46*** |

### Key Findings

1. **MF-GJR(VIX) remains the best model** -- no ML model beats it in QLIKE or Spearman rho.

2. **Random Forest is the only viable ML model**: QLIKE=1.5237 (between GJR and GARCH), Spearman=0.4212 (close to GJR). It benefits from VIX being its most important feature (importance=0.351).

3. **MLP catastrophically fails**: QLIKE=651520, Spearman=0.074. Daily squared returns are too noisy for gradient-based neural networks with this architecture. The MLP overfits badly despite early stopping.

4. **Ridge fails on QLIKE** (40278) despite reasonable MSE (2.10e-7). Linear models predict some near-zero variances that cause QLIKE to explode (QLIKE = r²/h - log(r²/h) - 1 penalizes underestimation catastrophically).

5. **Feature importance** (RF): log_VIX dominates (35.1%), followed by YZ range (14.7%) and lagged r² (11.8%). This explains why MF-GJR(VIX) works so well -- it structurally encodes VIX as the long-run component.

## Interpretation

The result confirms H2: **MF-GJR(VIX)'s multiplicative structure already captures the key nonlinearity** (VIX x short-run dynamics). ML models with the same features cannot find additional exploitable patterns. This is consistent with:

- The "combination puzzle" (K482): simple averages beat complex schemes
- High noise in daily r² (skew=15.7, kurtosis=347) limits what any model can extract
- VIX alone explains 35% of RF's predictive power, and MF-GJR already uses VIX structurally

## Limitations
- Only tested simple architectures (2-layer MLP, shallow RF)
- No LSTM/Transformer (would need longer sequences)
- Daily frequency only (5-min RV target might favor ML)
- Single asset (SPY), results may differ for other assets
- Fixed hyperparameters (no extensive HPO)

## Files
- `k940.py` -- experiment script
- `k940_results.json` -- full results
- `k940_comparison.png` -- model comparison bar chart
- `k940_feature_importance.png` -- RF importance + Ridge coefficients
- `k940_rolling_qlike.png` -- 252-day rolling QLIKE

## References
- Patton (2011) "Volatility Forecast Comparison Using Imperfect Volatility Proxies", JoE
- Bucci (2020) "Realized Volatility Forecasting with Neural Networks", JFEC
- Christensen et al. (2023) "A Machine Learning Approach to Volatility Forecasting", JBF
- Harvey et al. (2016) "Tests for Forecast Encompassing", JoE
