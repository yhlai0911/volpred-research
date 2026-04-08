# K934: CARR Conditional Autoregressive Range Model

## Problem
Chou (2005) proposed the CARR model using daily high-low range to predict volatility. Range is a theoretically more efficient volatility estimator than squared returns (Parkinson 1980: efficiency ratio ~5x). Can CARR beat GARCH/GJR on SPY?

## Motivation
- K464 showed HAR log-range works well for Asian markets (6/6 wins)
- K468 explored Yang-Zhang estimator as realized kernel proxy
- Neither used CARR as a dynamic model -- this fills the gap

## Method
- **Asset**: SPY (2004-01-01 ~ 2025-12-31, yfinance OHLC)
- **Window**: 2000, **Refit**: every 21 days, **OOS**: 2016-01-01 ~ 2025-12-31 (2,514 days)
- **Fixed seed**: `np.random.seed(42)`

### Models
| Model | Equation | Native Target |
|-------|----------|---------------|
| **CARR(1,1)** | lambda_t = omega + alpha * Range_{t-1} + beta * lambda_{t-1} | Range |
| **CARR-MF(VIX)** | lambda_t = tau_t * g_t, tau_t = exp(theta0 + theta1 * log_VIX_{t-1}) | Range |
| **GARCH(1,1)** | h_t = omega + alpha * r²_{t-1} + beta * h_{t-1} | sigma² |
| **GJR(1,1,1)** | h_t = omega + alpha * r²_{t-1} + gamma * I * r²_{t-1} + beta * h_{t-1} | sigma² |
| **MF-GJR(VIX)** | h_t = tau_t * g_t, with asymmetry | sigma² |

### Evaluation Framework (Patton 2011 compliant)
1. **Layer 1**: Native target QLIKE (each model on its own target)
2. **Layer 2**: QLIKE on r² (Patton 2011 proxy-robust -- **primary ranking**)
3. **Layer 3**: Spearman rank correlation (distribution-free)
4. **Layer 4**: DM tests with Harvey (2016) |t| > 3.0

CARR forecasts converted to variance via Parkinson: sigma² = lambda² / (4 * ln(2))

## Results

### Layer 2: QLIKE on r² (Fair Comparison -- Primary Ranking)
| Rank | Model | QLIKE |
|------|-------|-------|
| 1 | MF-GJR(VIX) | 1.4749 |
| 2 | GJR | 1.5618 |
| 3 | GARCH | 1.6024 |
| 4 | CARR-MF(VIX) | 1.6994 |
| 5 | CARR | 1.8154 |

**Return-based models dominate on r² target.** GARCH/GJR significantly beat CARR (DM |t| > 3.0).

### Layer 3: Spearman Rank Correlation with r²
| Model | rho | p-value |
|-------|-----|---------|
| **CARR-MF** | **0.4743** | < 1e-100 |
| **MF-GJR** | **0.4573** | < 1e-100 |
| **CARR** | **0.4418** | < 1e-100 |
| GJR | 0.4074 | < 1e-100 |
| GARCH | 0.3825 | < 1e-100 |

**CARR models rank HIGHER on Spearman** -- they capture the ordering of volatility well, even though QLIKE penalizes their level calibration.

### Supplementary: QLIKE on Parkinson Variance
| Model | QLIKE |
|-------|-------|
| **CARR-MF** | **0.3963** |
| CARR | 0.4470 |
| **MF-GJR** | 0.4531 |
| GJR | 0.5301 |
| GARCH | 0.5680 |

**When evaluated against Parkinson variance, CARR-MF is the best model.** This shows range-based models capture intraday price dynamics better than return-based models.

### Layer 4: DM Tests (Harvey |t| > 3.0)
| Pair | t-stat | Significant | Winner |
|------|--------|-------------|--------|
| CARR vs GARCH | 4.44 | YES | GARCH |
| CARR vs GJR | 5.36 | YES | GJR |
| CARR-MF vs GARCH | 2.45 | NO | n.s. |
| CARR-MF vs GJR | 3.68 | YES | GJR |
| CARR-MF vs MF-GJR | 6.89 | YES | MF-GJR |
| GARCH vs GJR | 3.26 | YES | GJR |
| GJR vs MF-GJR | 4.06 | YES | MF-GJR |

### Model Parameters (First Fit)
| Model | Persistence | Key Parameters |
|-------|-------------|----------------|
| CARR | 0.970 | alpha=0.251, beta=0.720 |
| CARR-MF | 0.981 | theta1=1.589 (VIX elasticity), alpha=0.080, beta=0.902 |
| GARCH | 0.983 | alpha=0.083, beta=0.900 |
| GJR | 0.983 | gamma=0.233 (strong asymmetry), beta=0.866 |
| MF-GJR | 0.937 | theta1=2.560, gamma=0.149 |

## Conclusions

### Key Findings
1. **On the primary fair comparison (QLIKE on r²), return-based models beat range-based models.** MF-GJR > GJR > GARCH > CARR-MF > CARR. This is an **empirical finding** (not mechanical) because CARR forecasts are converted to variance via Parkinson before evaluation.

2. **CARR models rank higher on Spearman correlation** (CARR-MF rho=0.474 vs GARCH rho=0.383), indicating they capture volatility *ordering* well but have poor *level calibration* when converted to variance.

3. **On Parkinson variance target, CARR-MF is the best model** (QLIKE=0.396 vs MF-GJR=0.453). This is a **mechanical result** -- CARR is designed to predict range, so it naturally excels when evaluated against range-derived measures.

4. **VIX as external regressor improves all models**: CARR-MF beats CARR (DM t=3.15), MF-GJR beats GJR (DM t=4.06). This is consistent with prior findings.

5. **CARR-MF vs GARCH is NOT statistically significant** (DM t=2.45 < 3.0), meaning range + VIX information is approximately equivalent to simple return-based GARCH.

### Interpretation
The Parkinson conversion (sigma² = lambda²/(4*ln(2))) assumes continuous sample paths, which is violated by overnight gaps. This creates a systematic bias when converting range forecasts to variance, explaining why CARR loses on QLIKE/r² despite having better rank correlation.

### Limitations
- Single asset (SPY) -- results may differ for other assets
- No intraday data to compute true RV for gold-standard comparison
- Exponential distribution for CARR innovations (Weibull or Gamma could improve fit)
- No VaR/ES evaluation (this is a pure forecasting comparison)

## Files
- `k934.py` -- experiment script
- `k934_results.json` -- full results
- `k934_comparison.png` -- 4-panel comparison chart

## References
- Chou, R.Y. (2005). "Forecasting Financial Volatilities with Extreme Values: The CARR Model." *Journal of Money, Credit and Banking*, 37(3), 561-582.
- Parkinson, M. (1980). "The Extreme Value Method for Estimating the Variance of the Rate of Return." *Journal of Business*, 53(1), 61-65.
- Patton, A.J. (2011). "Volatility Forecast Comparison Using Imperfect Volatility Proxies." *Journal of Econometrics*, 160(1), 246-256.
- Harvey, C.R. et al. (2016). "...and the Cross-Section of Expected Returns." *Review of Financial Studies*, 29(1), 5-68.
