# K941: Conditional Quantile Volatility Forecasting

## Problem
Current models predict E[sigma^2] (conditional mean). Risk management needs the full distribution of sigma^2 -- the "vol of vol". Quantile regression predicts different percentiles of r^2 (5th, 25th, 50th, 75th, 95th), providing a more complete risk picture than point forecasts alone.

## Motivation
- Point forecasts tell you the expected volatility, but not the uncertainty around that forecast
- During crises, the conditional distribution of volatility becomes highly skewed
- VaR and ES calculations benefit from direct quantile estimation rather than parametric assumptions
- CAViaR (Engle & Manganelli 2004) models VaR directly without distribution assumptions

## Models
1. **CAViaR-SAV** (Engle & Manganelli 2004): q_t(tau) = b0 + b1*q_{t-1}(tau) + b2*r^2_{t-1}
2. **QR-GARCH**: Linear quantile regression with GARCH features (sigma^2, log VIX, |r|, r^2, 5d rolling r^2)
3. **Quantile Random Forest**: RF with leaf-membership-based quantile estimation (Meinshausen 2006)
4. **GARCH(1,1) Parametric**: Student-t quantiles from GARCH conditional variance
5. **MF-GJR(VIX) Parametric**: Student-t quantiles from multiplicative factor GJR with VIX

## Data
- **Asset**: SPY (S&P 500 ETF)
- **Source**: yfinance
- **Period**: 2006-01-04 ~ 2025-12-30 (N=5029)
- **OOS**: 2016-01-04 ~ 2025-12-30 (N=2513)
- **Target**: r^2 (squared daily return)

## Key Results

### Pinball Loss Rankings (lower = better)
| Rank | Model | Mean Pinball |
|------|-------|-------------|
| 1 | **CAViaR-SAV** | **0.000040** |
| 2 | GARCH Param | 0.000041 |
| 3 | Quantile RF | 0.000043 |
| 4 | MF-GJR Param | 0.000044 |
| 5 | QR-GARCH | 0.000045 |

### 90% Prediction Interval Coverage (target: 0.90)
| Model | Coverage | Status |
|-------|----------|--------|
| CAViaR-SAV | 0.912 | OK |
| QR-GARCH | 0.846 | MISS |
| Quantile RF | 0.900 | OK |
| GARCH Param | 0.887 | OK |
| MF-GJR Param | 0.893 | OK |

### Calibration MAD (lower = better)
| Model | MAD |
|-------|-----|
| **CAViaR-SAV** | **0.006** |
| Quantile RF | 0.011 |
| GARCH Param | 0.017 |
| QR-GARCH | 0.019 |
| MF-GJR Param | 0.028 |

### Winkler Score (combines coverage + width, lower = better)
| Model | Winkler |
|-------|---------|
| **CAViaR-SAV** | **0.000902** |
| GARCH Param | 0.000902 |
| MF-GJR Param | 0.001073 |
| Quantile RF | 0.001077 |
| QR-GARCH | 0.001230 |

## Conclusions
1. **CAViaR-SAV dominates across all metrics**: best pinball loss, best calibration (MAD=0.006), best or tied-best Winkler score, and correct 90% coverage (0.912)
2. **GARCH Parametric is surprisingly competitive**: nearly tied with CAViaR on pinball loss and Winkler, suggesting the Student-t distributional assumption is adequate for SPY
3. **QR-GARCH underperforms**: 90% coverage misses target significantly (0.846), indicating linear quantile regression with GARCH features is too conservative at the 95th percentile
4. **Quantile RF provides good coverage (0.900)** but with higher pinball loss than CAViaR
5. **MF-GJR Param intervals are too wide**: despite good coverage, the average width (0.000809) is 1.7x larger than CAViaR (0.000471), leading to worse efficiency

## Limitations
- Target is r^2 (noisy proxy for sigma^2)
- Only SAV specification of CAViaR (no asymmetric slope)
- Single asset (SPY only)
- No formal DM tests between quantile models
- QRF quantile estimation via leaf membership may not be optimal

## References
- Engle & Manganelli (2004) JBES 22(4):367-381
- Koenker & Bassett (1978) Econometrica 46:33-50
- Meinshausen (2006) JMLR 7:983-999
- Patton (2011) J Econometrics 160:246-256

## Files
- `k941.py` - Experiment script
- `k941_results.json` - Full results
- `k941_quantile_comparison.png` - Pinball loss comparison
- `k941_calibration.png` - Calibration plot
- `k941_prediction_intervals.png` - 90% PI time series
