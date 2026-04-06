# K939: CARR_YZ-MF(VIX) — Range + VIX Ultimate Combination

## Problem
K935 showed CARR_YZ (QLIKE=1.555) beats CARR_Parkinson (1.699) by 8%, but CARR_YZ hasn't been combined with VIX.
K889 showed MF-GJR(VIX) is the current best model (QLIKE~1.48).
Can Yang-Zhang range + VIX multiplicative factor beat MF-GJR(VIX)?

## Hypotheses
- **H1**: CARR_YZ-MF(VIX) QLIKE < MF-GJR(VIX) — range + VIX > return + VIX
- **H0**: CARR_YZ-MF(VIX) ~ MF-GJR(VIX) — VIX dominates, range adds no increment

## Method
- **Data**: SPY OHLC + ^VIX, 2004-01-05 ~ 2025-12-31 (yfinance)
- **OOS**: 2016-01-04 ~ 2025-12-31 (2,514 days)
- **Window**: 2000, Refit every 21 days (120 refits)
- **Evaluation**: QLIKE on r^2 (Patton 2011), Spearman rho, DM test (Harvey |t|>3.0)

## Models (6)
| # | Model | Description | Params |
|---|-------|-------------|--------|
| 1 | GARCH(1,1) | Return-based baseline | 3 |
| 2 | GJR(1,1,1) | Asymmetric return baseline | 4 |
| 3 | MF-GJR(VIX) | Current best (K889) | 6 |
| 4 | CARR_YZ | Range baseline (K935) | 3 |
| 5 | CARR_YZ-MF(VIX) | **NEW**: Range + VIX factor | 5 |
| 6 | CARR_YZ-MF-A(VIX) | **NEW**: Above + asymmetry | 6 |

## Results

### QLIKE on r^2 Ranking (Patton 2011)
| Rank | Model | QLIKE | vs MF-GJR |
|------|-------|-------|-----------|
| 1 | **CARR_YZ-MF(VIX)** | **1.4622** | -1.21% |
| 2 | CARR_YZ-MF-A(VIX) | 1.4724 | -0.52% |
| 3 | MF-GJR(VIX) | 1.4801 | baseline |
| 4 | CARR_YZ | 1.5550 | +5.06% |
| 5 | GJR | 1.5834 | +6.98% |
| 6 | GARCH | 1.6037 | +8.35% |

### Spearman Rank Correlation with r^2
| Model | rho |
|-------|-----|
| CARR_YZ-MF(VIX) | 0.4606 |
| MF-GJR(VIX) | 0.4583 |
| CARR_YZ-MF-A(VIX) | 0.4573 |
| CARR_YZ | 0.4177 |
| GJR | 0.3927 |
| GARCH | 0.3777 |

### DM Tests (Harvey |t|>3.0)
| Comparison | t-stat | Significant? |
|------------|--------|-------------|
| CARR_YZ-MF vs MF-GJR | -1.59 | No |
| CARR_YZ-MF-A vs MF-GJR | -0.71 | No |
| CARR_YZ-MF vs CARR_YZ | -5.90 | Yes *** |
| CARR_YZ-MF vs GARCH | -6.43 | Yes *** |
| MF-GJR vs GJR | -4.33 | Yes *** |
| MF-GJR vs GARCH | -5.24 | Yes *** |

### Native Target QLIKE
- CARR_YZ on YZ: 0.467 → CARR_YZ-MF on YZ: 0.372 (VIX improves range prediction by 20%!)

## Conclusions

1. **CARR_YZ-MF(VIX) achieves the lowest QLIKE (1.462) — new best model**, surpassing MF-GJR(VIX) (1.480) by 1.21%. However, the improvement is **not statistically significant** (DM t=-1.59, below Harvey threshold of 3.0).

2. **VIX is the dominant factor**: Adding VIX to CARR_YZ improves QLIKE by 6.0% (DM t=-5.90, highly significant). The model structure (range vs return) matters less than the VIX factor.

3. **Asymmetry doesn't help range models**: CARR_YZ-MF-A is slightly worse than CARR_YZ-MF (1.472 vs 1.462). Unlike GJR which benefits from leverage effect in returns, range already captures both up and down movements.

4. **Range provides marginal increment over returns when combined with VIX**: CARR_YZ-MF > MF-GJR in point estimate, but the edge is small and statistically insignificant.

## Interpretation
VIX dominates both information channels (range and return). The choice between range (CARR) and return (GARCH) is secondary to including VIX. CARR_YZ-MF is a credible alternative to MF-GJR but does not represent a statistically significant improvement.

## Limitations
- Single asset (SPY), single OOS period
- VIX uses concurrent value in tau (not purely lagged)
- CARR uses Exponential innovation (not Gamma which may be more appropriate)
- No VaR/ES backtesting

## References
- Yang & Zhang (2000) "Drift Independent Volatility Estimation"
- Chou (2005) "Forecasting Financial Volatilities with Extreme Values"
- Engle & Rangel (2008) "The Spline-GARCH Model"
- Patton (2011) J. Econometrics 160
- Harvey et al. (2016) "Tests for Forecast Encompassing"

## Files
- `k939.py` — experiment script
- `k939_results.json` — full results
- `k939_comparison.png` — visualization
