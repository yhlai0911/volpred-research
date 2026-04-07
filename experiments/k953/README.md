# K953: HAR-RV Pilot with 56 Days 5-Min SPY Data (PRELIMINARY)

## Status: PRELIMINARY (56 days < 252 day formal OOS threshold)

## Problem
SPY 5-min data has accumulated 56 trading days (2026-01-14 to 2026-04-06). Although insufficient for formal evaluation, we can do a preliminary assessment of:
1. 5-min Realized Variance (RV) descriptive statistics
2. HAR-RV (Corsi 2009) in-sample fit quality
3. Short-window OOS (train 30 / test 4 days)
4. Cross-model comparison with GJR, EWMA, MF-GJR(VIX) on both RV and r² targets

## Motivation
- HAR-RV is the standard model for predicting realized variance from high-frequency data
- Previous experiments (K849) showed HAR-RV beats GJR on RV target (DM t=-11.14), but that is a MECHANICAL result
- This pilot establishes baseline statistics for ongoing 5-min data collection

## Method
- **Data**: yfinance 5-min SPY, 56 trading days, avg 74.8 obs/day
- **RV**: Sum of squared 5-min log returns within each trading day
- **HAR-RV**: RV_t = β₀ + β_d × RV_{t-1} + β_w × RV_{t-5:t-1} + β_m × RV_{t-22:t-1} + ε_t
- **Benchmarks**: GJR(1,1,1) on 3+ years daily returns, EWMA(λ=0.94), MF-GJR(VIX)
- **Evaluation**: QLIKE and MSE on both RV target (native for HAR) and r² target (Patton 2011 proxy-robust)

## Key Results (PRELIMINARY)

### RV Statistics
- Mean annualized vol: 11.30%
- RV ACF(1) = 0.290, ACF(5) = 0.096 — moderate persistence
- RV vs r² Pearson correlation = 0.280, Spearman = 0.229
- Mean(r² - RV) = 0.000034 — reflects overnight component

### HAR-RV In-Sample (34 obs after lag construction)
- **R² = 0.033, Adj R² = -0.064** — very poor fit
- No coefficient is significant (all p > 0.20)
- 34 observations is far too few for a model with 4 parameters (including constant)

### Cross-Model QLIKE (33 common days)

| Model | QLIKE(RV) | QLIKE(r²) |
|-------|-----------|-----------|
| HAR-RV | 0.109 | 1.296 |
| GJR | 0.194 | **1.139** |
| EWMA | 0.126 | 1.260 |
| MF-GJR(VIX) | 0.501 | 1.275 |

- On RV target: HAR-RV best (MECHANICAL — expected by design)
- On r² target (Patton 2011 fair comparison): GJR best (expected — GARCH predicts σ²)

## Limitations
- **56 days is far below 252-day minimum** for formal conclusions
- HAR-RV only has 34 usable obs (22 lost to monthly lag construction) — too few for reliable estimation
- OOS split = 30 train / 4 test — essentially meaningless
- No DM test (sample too small)
- All cross-model rankings are unreliable at this sample size

## Conclusion
This is a data quality checkpoint, not a research finding. The 5-min data collection pipeline is working (56 days, avg 74.8 obs/day). HAR-RV cannot be meaningfully evaluated with only 34 observations. Continue collecting and revisit at 120+ days (HAR becomes feasible) and 252+ days (formal evaluation).

## Files
- `k953.py` — Experiment script
- `k953_results.json` — Full results
- `k953_rv_analysis.png` — Visualization (RV time series, ACF, RV vs r², model comparison)

## References
- Corsi, F. (2009). A Simple Approximate Long-Memory Model of Realized Volatility. JFEC.
- Patton, A. (2011). Volatility forecast comparison using imperfect volatility proxies. JoE.
- Hansen, P. & Lunde, A. (2005). A forecast comparison of volatility models. JoE.

## Data Source
- yfinance 5-min SPY (free tier, ~60 day rolling window)
- Period: 2026-01-14 to 2026-04-06 (56 trading days)
