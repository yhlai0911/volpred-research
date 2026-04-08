# K944: KAN-Inspired Nonlinear Vol Prediction

## Problem
K940 showed MLP(32,16) catastrophically fails for daily vol prediction (QLIKE=651K) while RF is feasible (QLIKE=1.524) but does not beat MF-GJR(VIX) (1.458). KAN (Kolmogorov-Arnold Network, Liu et al. 2024) uses learnable B-spline activation functions instead of fixed ReLU, theoretically better suited for capturing log/exp nonlinearities inherent in GARCH-type models. Can KAN-style approaches do better?

## Motivation
- KAN replaces fixed activation with per-feature learnable B-spline functions: f(x) = sum_i phi_i(x_i)
- This additive structure with flexible basis matches vol prediction well (log VIX, r^2, sigma^2 all have different scales)
- Since pykan requires Python 3.9 (not available in our 3.12 environment), we implement the KAN concept via sklearn SplineTransformer + Ridge/GBR

## Method
### Models
1. **BSpline-Ridge (KAN proxy)**: B-spline basis expansion (degree 3, 5 knots) per feature, then Ridge regression. Trained on log(r^2) to ensure positive predictions.
2. **BSpline-GBR**: Same B-spline expansion + GradientBoosting. Tests if interactions beyond additive structure help.
3. **GBR**: Raw features + GradientBoosting.
4. **RF**: Random Forest (K940 baseline, reproduced).
5. **GARCH(1,1)**: Parametric baseline.
6. **MF-GJR(VIX)**: Best known model (K889).

### Features (all lagged t-1)
1. sigma^2_GARCH (GARCH fitted variance)
2. log(VIX)
3. r^2 (squared return)
4. |r| (absolute return)
5. YZ (Yang-Zhang variance)
6. 20-day rolling variance

### Protocol
- OOS: 2016-01-04 ~ 2025-12-31 (N=2514)
- Expanding window, refit every 63 days (40 refits)
- Rolling z-score standardization (training data only)
- Seed: 42

## Results

| Model | QLIKE | MSE | Spearman rho | DM t vs MF-GJR |
|-------|-------|-----|-------------|----------------|
| MF-GJR(VIX) | **1.3848** | **1.85e-7** | **0.4781** | -- |
| RF | 1.4977 | 2.01e-7 | 0.4362 | -6.91*** |
| GJR(1,1,1) | 1.5459 | 2.09e-7 | 0.4177 | -7.06*** |
| GARCH(1,1) | 1.5813 | 2.15e-7 | 0.3833 | -8.75*** |
| BSpline-GBR | 1.6686 | 2.12e-7 | 0.3921 | -3.70*** |
| GBR | 2.7063 | 1.99e-7 | 0.4193 | -1.16 |
| BSpline-Ridge | 3.4529 | 2.42e-7 | 0.4441 | -10.86*** |

### Feature Importance (all 3 ML models agree)
- **log(VIX) dominates**: 30-77% importance across all models
- Range-based vol (YZ) second most important
- GARCH variance and rolling variance contribute
- Lagged r^2 and |r| are relatively unimportant

## Conclusion
**H2 confirmed: MF-GJR(VIX) is still dominant.** No KAN-style nonlinear method beats the parametric MF-GJR(VIX) model for daily vol prediction on SPY.

Key insights:
1. **RF remains the best ML model** (QLIKE=1.498 vs MF-GJR 1.385) but the gap is statistically significant (DM t=-6.91).
2. **B-spline basis expansion (KAN proxy) does NOT help**: BSpline-Ridge (3.45) and BSpline-GBR (1.67) are worse than plain RF (1.50). The additive nonlinear structure that makes KAN theoretically attractive does not translate to practical improvement for noisy daily r^2.
3. **Log-transform training is critical for linear models** (Ridge) to avoid QLIKE explosion from negative predictions, but hurts calibration (Jensen's inequality bias).
4. **VIX is overwhelmingly the most important feature** (30-77%), confirming K889's finding that VIX as exogenous variable is the key ingredient.
5. **Parametric GARCH structure (recursive h[t] = f(h[t-1], r^2[t-1])) is irreplaceable** -- ML models predict r^2[t] from lagged features but lack the autoregressive variance dynamics that make GARCH effective.

### Why ML Fails at Daily Vol
The fundamental issue is that GARCH has a structural advantage: it models the *conditional variance process* recursively, while ML models treat each day as an independent prediction. The recursive h[t] = omega + alpha*r^2[t-1] + beta*h[t-1] captures vol clustering via the beta*h[t-1] persistence term. ML models approximate this with lagged r^2 and rolling variance, but these are crude substitutes for the full conditional variance path.

## Data
- Source: yfinance (SPY + ^VIX)
- Period: 2004-02-02 ~ 2025-12-31
- OOS: 2016-01-04 ~ 2025-12-31 (N=2514)

## References
- Liu et al. (2024) "KAN: Kolmogorov-Arnold Networks" arXiv:2404.19756
- Patton (2011) "Volatility Forecast Comparison Using Imperfect Volatility Proxies"
- Harvey et al. (2016) "Tests for Forecast Encompassing"
- Christensen et al. (2023) "A Machine Learning Approach to Volatility Forecasting"
- Bucci (2020) "Realized Volatility Forecasting with Neural Networks"
