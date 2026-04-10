# K1028: DCC-A4f Multivariate Extension for Portfolio Risk

## Motivation
Paper 9 future work proposes "extending the multiplicative framework to multivariate settings for portfolio risk management." This experiment is the initial proof-of-concept: applying A4f (tau x g, tau=VIX^2) as univariate marginals inside DCC-GARCH (Engle 2002) for bivariate portfolio variance forecasting.

## Method
- **Two-step DCC** (Engle 2002):
  1. Fit univariate A4f (or GJR baseline) to SPY and QQQ separately
  2. Compute standardised residuals, fit scalar DCC(1,1) parameters (a, b)
- **Four model variants**: DCC-A4f, DCC-GJR, CCC-A4f, CCC-GJR
- **Portfolio**: 50/50 SPY/QQQ
- **Evaluation**: QLIKE on portfolio r^2, DM tests, Kupiec VaR backtest (5%)
- **Data**: yfinance SPY+QQQ+VIX, 2004-2026 (5601 obs), OOS 2019-2026 (1827 days)
- **Window**: 2000, refit every 63 days, seed=42

## Key Results

### Portfolio QLIKE (lower is better)
| Model | QLIKE |
|-------|-------|
| CCC-A4f | **-8.0736** |
| DCC-A4f | -8.0733 |
| CCC-GJR | -7.9986 |
| DCC-GJR | -7.9916 |

### DM Tests
| Comparison | t-stat | p-value | Interpretation |
|-----------|--------|---------|----------------|
| DCC-GJR vs DCC-A4f | 2.579 | 0.010 | A4f significantly better |
| CCC-GJR vs CCC-A4f | 2.652 | 0.008 | A4f significantly better |
| DCC-A4f vs CCC-A4f | 0.289 | 0.773 | DCC unnecessary for A4f |
| DCC-GJR vs CCC-GJR | 1.528 | 0.127 | DCC not significant for GJR either |

### VaR Backtest (5% level)
| Model | Violations | Rate | Kupiec p | Pass? |
|-------|-----------|------|----------|-------|
| DCC-A4f | 95/1827 | 5.2% | 0.697 | YES |
| CCC-A4f | 97/1827 | 5.3% | 0.548 | YES |
| DCC-GJR | 117/1827 | 6.4% | 0.008 | NO |
| CCC-GJR | 119/1827 | 6.5% | 0.005 | NO |

### DCC Parameters (full sample)
- DCC-A4f: a=0.056, b=0.926, persistence=0.982
- DCC-GJR: a=0.057, b=0.923, persistence=0.981

### Dynamic Correlation (OOS)
- DCC-A4f rho: mean=0.912, std=0.039, range=[0.740, 0.980]
- DCC-GJR rho: mean=0.913, std=0.041, range=[0.658, 0.981]

## Conclusions

1. **A4f significantly improves over GJR in bivariate setting** (DM t=2.58, p=0.01). The VIX-driven tau component helps both marginals, leading to better portfolio variance forecasts. This is an empirical finding: the VIX exogenous variable captures common market-wide volatility information that benefits both assets.

2. **DCC does NOT add value over CCC when A4f marginals are used** (DM t=0.29, p=0.77). This suggests that A4f's tau already captures the time-varying correlation structure through the shared VIX factor. When both marginals use the same VIX-driven component, the correlation between standardised residuals is relatively stable.

3. **VaR calibration strongly favours A4f**: Both A4f variants pass Kupiec at 5%, while both GJR variants fail. GJR underestimates tail risk (6.4-6.5% violation rate vs 5% target), while A4f is well-calibrated (5.2-5.3%).

4. **The DCC dynamic correlation is highly persistent** (a+b ~ 0.98) for both models, confirming SPY-QQQ correlation is stable with occasional dips (COVID: rho drops to ~0.66 for GJR, ~0.74 for A4f).

## Implications for Paper 9
- A4f extends naturally to multivariate settings via standard DCC machinery
- The shared VIX factor in tau acts as a "common volatility factor" that implicitly captures much of the time-varying correlation
- For highly correlated equity pairs (rho > 0.9), CCC-A4f may be sufficient (simpler than DCC-A4f)
- For diverse portfolios (equities + bonds + commodities), DCC may become necessary

## Limitations
- Only tested on SPY/QQQ (high unconditional correlation 0.918)
- Normal distribution assumed (no Student-t)
- No ES backtest (only VaR 5%)
- 2-asset case; scalability to N assets untested

## Files
- `k1028.py` - Experiment script
- `k1028_results.json` - Complete results
- `k1028_dcc_correlation.png` - Dynamic correlation plot

## References
- Engle, R. (2002). Dynamic Conditional Correlation. JBES 20(3), 339-350.
- Patton, A. (2011). Volatility forecast comparison using imperfect proxies. JoE 160(1), 246-256.
- A4f multiplicative framework from Paper 9 (Lai, 2026)
