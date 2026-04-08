# K973: Time-Varying Hurst Exponent for Volatility Forecasting

## Motivation
Rough Volatility literature (Gatheral et al. 2018) shows log-volatility has Hurst exponent H ~ 0.1, far below 0.5. K34 tested rough vol at daily frequency and found NULL (H ~0.01 too noisy). arXiv:2509.05820 (2025) proposes Time-Varying Hurst EWMA, where changes in H_t contain predictive information. This experiment tests whether time-varying H adds incremental value to volatility forecasting.

## Data
- **Source**: yfinance (SPY)
- **Period**: 2006-01-04 to 2026-04-06 (5,094 observations)
- **IS**: 2006-2018 (n=3,270), **OOS**: 2019-2026 (n=1,824)

## Methods
1. **R/S Hurst** (rolling 60-day window on returns)
2. **Variogram Hurst** (rolling 120-day window on log|returns|)
3. **EWMA smoothing** (halflife=22 days)
4. **HAR-type regression**: RV_t = a + b1*RV_{t-1} + b2*RV_{t-5} + b3*RV_{t-22} [+ b4*H_{t-1}]
5. **GJR-GARCH(1,1)** baseline (expanding window, refit every 22 days)
6. All H features lagged by 1 day (shift(1)) to avoid lookahead

## Key Results

### Hurst Exponent Characteristics
| Metric | H (R/S EWMA) | H (Variogram EWMA) |
|--------|-------------|-------------------|
| Mean | 0.502 | 0.009 |
| Std | 0.030 | 0.021 |
| Range | [0.417, 0.586] | [-0.042, 0.060] |

- R/S H is centered around 0.5 (random walk) -- rough vol NOT evident at daily frequency
- Variogram H ~ 0.01, consistent with K34's finding
- H slightly higher in crisis regimes (0.509 vs 0.498 in low vol) but difference is tiny

### OOS Forecasting (QLIKE, lower = better)
| Model | QLIKE | MZ R2 |
|-------|-------|-------|
| **HAR** | **1.5264** | **0.1971** |
| HAR + H_rs_ewma | 1.5275 | 0.1970 |
| HAR + H_vario_ewma | 1.5270 | 0.1969 |
| HAR + H_rs + H_vario | 1.5279 | 0.1968 |
| HAR + H_rs_raw | 1.5453 | 0.1974 |
| GJR-GARCH(1,1) | 2.4475 | 0.0355 |

### DM Tests (vs HAR baseline)
- HAR + H_rs_ewma: DM = -0.89, p = 0.372
- HAR + H_vario_ewma: DM = -0.11, p = 0.911
- None significant at any conventional level

### In-Sample H Coefficient
- H_rs_ewma_lag1: t = 0.39 (insignificant)
- H_vario_ewma_lag1: t = 0.62 (insignificant)

## Conclusion
**NULL RESULT.** Time-varying Hurst exponent has NO incremental predictive value for daily volatility forecasting of SPY. Key findings:

1. R/S Hurst at daily frequency is ~0.50, not rough (H << 0.5). The rough volatility phenomenon documented by Gatheral et al. (2018) operates at intraday frequencies and is not detectable with daily close-to-close returns.
2. Variogram H ~ 0.01 is consistent with K34 but too noisy to be useful.
3. Adding H to HAR actually slightly worsens QLIKE (overfitting with useless feature).
4. The weak correlation between H and forward volatility (r = 0.05-0.12) is not enough to improve forecasts.

**Implication**: Rough volatility is a real phenomenon, but it requires high-frequency data (5-min or tick) to estimate meaningful H values. Daily-frequency Hurst is not a useful volatility predictor.

## References
- Gatheral, Jaisson, Rosenbaum (2018) "Volatility is Rough", Quantitative Finance
- Corsi (2009) "A Simple Approximate Long-Memory Model of Realized Volatility", JFE
- Patton (2011) "Volatility Forecast Comparison Using Imperfect Proxies", JoE
- arXiv:2509.05820 (2025) Time-Varying Hurst EWMA

## Files
- `k973_hurst_vol.py` -- main experiment script
- `k973_hurst_vol_results.json` -- full results
- `k973_hurst_timeseries.png` -- H time series plot
- `k973_forecast_comparison.png` -- OOS comparison and regime analysis
