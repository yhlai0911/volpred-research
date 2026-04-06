# K935: Gap-Adjusted CARR -- Fixing Parkinson Overnight Bias

## Problem
K934 found that CARR(1,1) with Parkinson range had the best Spearman ranking (rho=0.4418) but worst QLIKE on r^2 (1.815) among all models. Root cause: Parkinson estimator assumes continuous price paths, so overnight gaps violate this assumption and introduce systematic bias in the variance-to-sigma^2 conversion.

## Hypotheses
- **H1**: Yang-Zhang/Garman-Klass/Rogers-Satchell CARR have lower QLIKE on r^2 than Parkinson CARR
- **H2**: Gap-adjusted CARR may approach or exceed GARCH calibration ability

## Method
- **Asset**: SPY (2004-2026, yfinance OHLC data)
- **Window**: 2000, Refit every 21 days, OOS: 2016-01-01 ~ 2025-12-31 (2514 days)
- **4 Range Estimators**:
  1. **Parkinson (1980)**: sigma^2 = (H-L)^2 / (4*ln2). Ignores overnight gap.
  2. **Garman-Klass (1980)**: sigma^2 = 0.5*(H-L)^2 - (2*ln2-1)*(C-O)^2. Includes Open-Close.
  3. **Rogers-Satchell (1991)**: sigma^2 = (H-C)(H-O) + (L-C)(L-O). Allows non-zero drift.
  4. **Yang-Zhang (2000)**: sigma^2 = overnight^2 + k*open_var + (1-k)*RS. Full decomposition.
- **Models**: CARR(1,1) for each estimator, GARCH(1,1), MF-GJR(VIX) as benchmarks
- **Evaluation**: QLIKE on r^2 (Patton 2011), Spearman rho, DM test (Harvey |t|>3.0)

## Key Results

### QLIKE on r^2 Ranking (lower = better)
| Rank | Model | QLIKE | vs Parkinson CARR |
|------|-------|-------|-------------------|
| 1 | MF-GJR(VIX) | 1.4798 | -- |
| 2 | **CARR_YZ** | **1.5560** | **-8.04%** |
| 3 | GARCH(1,1) | 1.6033 | -- |
| 4 | CARR_RS | 1.6701 | -1.30% |
| 5 | CARR_GK | 1.6888 | -0.19% |
| 6 | CARR_Parkinson | 1.6921 | baseline |

### Spearman Rank Correlation (higher = better)
| Model | rho |
|-------|-----|
| MF-GJR | 0.4582 |
| CARR_GK | 0.4283 |
| CARR_Parkinson | 0.4271 |
| CARR_RS | 0.4206 |
| CARR_YZ | 0.4147 |
| GARCH | 0.3780 |

### DM Test Significance (Harvey |t| > 3.0)
- MF-GJR significantly beats all models (|t| = 3.6-4.8)
- CARR_YZ significantly beats CARR_Parkinson (t=-3.28) and CARR_GK (t=-3.26)
- CARR_YZ vs GARCH: t=-2.68, NOT significant at Harvey threshold
- GK, RS, Parkinson are NOT significantly different from each other

## Conclusions

### H1: CONFIRMED
Yang-Zhang CARR improves QLIKE on r^2 by 8.04% over Parkinson CARR (DM t=-3.28, significant). GK and RS improve marginally (0.2-1.3%) but not significantly.

### H2: EXCEEDED
CARR_YZ (QLIKE=1.556) actually beats GARCH(1,1) (QLIKE=1.603) by 2.95%, though the DM test (t=-2.68) does not reach Harvey threshold. This is a notable result: by incorporating overnight gap information, a range-based model achieves comparable or better calibration than standard GARCH.

### Key Insight
The overnight gap is the dominant source of bias in Parkinson CARR. Yang-Zhang's overnight component captures this effectively. However, MF-GJR(VIX) remains best overall -- it benefits from both VIX forward-looking information and GJR asymmetry.

### Trade-off: Calibration vs Ranking
Interesting observation: CARR_YZ has best calibration among CARR variants but lowest Spearman rho (0.4147). CARR_GK has highest Spearman (0.4283) among CARR variants. This suggests a calibration-ranking trade-off when including overnight information -- the overnight component adds calibration but introduces noise in ranking.

## Limitations
- SPY only (single asset)
- Daily OHLC from yfinance (no intraday data)
- Yang-Zhang k parameter uses asymptotic value (n -> infinity)
- No VaR/ES backtest performed (pure forecasting comparison)
- The floor treatment for negative GK/RS values (2 observations) is minimal

## Files
- `k935.py` -- Experiment script
- `k935_results.json` -- Full results
- `k935_comparison.png` -- Comparison chart

## References
- Parkinson (1980) "The Extreme Value Method for Estimating the Variance of the Rate of Return"
- Garman & Klass (1980) "On the Estimation of Security Price Volatilities from Historical Data"
- Rogers & Satchell (1991) "Estimating Variance from High, Low and Closing Prices"
- Yang & Zhang (2000) "Drift Independent Volatility Estimation"
- Chou (2005) "Forecasting Financial Volatilities with Extreme Values"
- Patton (2011) "Volatility Forecast Comparison Using Imperfect Volatility Proxies" J. Econometrics 160
