# K937: CARR-GARCH Rank-Calibration Ensemble

## Problem
K934 showed CARR(1,1) has the best Spearman ranking (rho=0.474) but worst calibration (QLIKE=1.815). K935 showed Yang-Zhang CARR improves to QLIKE=1.556, closer to GARCH (1.603). Can ensemble methods combine CARR's ranking advantage with GARCH's calibration advantage to beat MF-GJR(VIX), the best known single model (QLIKE~1.47)?

## Motivation
The "forecast combination puzzle" (Timmermann 2006) shows equal-weight ensembles often beat sophisticated combinations. K482 confirmed this for MCS-weighted ensembles. This experiment tests whether the distinct strengths of CARR (ranking) and GARCH (calibration) can be exploited via novel ensemble designs.

## Method
- **Data**: SPY + VIX, yfinance, 2004-01-01 ~ 2025-12-31
- **OOS**: 2017-01-03 ~ 2025-12-31 (2262 days, after 252-day warm-up)
- **Window**: 2000, Refit every 21 days (120 refits)
- **Seed**: 42

### Base Models
1. GARCH(1,1) -- standard benchmark
2. GJR(1,1,1) -- asymmetric effects
3. MF-GJR(VIX) -- best known single model (K889)
4. CARR_YZ(1,1) -- Yang-Zhang CARR (K935)

### Ensemble Methods
1. **Equal Weight**: simple average of 4 models
2. **Inverse QLIKE Weight**: weight proportional to 1/QLIKE over rolling 252-day window
3. **Rank-Level Hybrid**: use CARR ranking + GARCH percentile mapping
4. **OLS Stacking**: NNLS regression of r^2 on 4 model forecasts (rolling 252-day)

## Results

### QLIKE on r^2 (lower = better)
| Model | QLIKE | Spearman rho |
|-------|-------|-------------|
| MF-GJR(VIX) | **1.4624** | **0.4619** |
| Inv QLIKE Ensemble | 1.4924 | 0.4471 |
| EQ Weight Ensemble | 1.4937 | 0.4464 |
| OLS Stack Ensemble | 1.4969 | 0.4519 |
| CARR_YZ | 1.5337 | 0.4305 |
| GJR | 1.5381 | 0.4221 |
| Rank-Level Hybrid | 1.5583 | 0.4226 |
| GARCH | 1.5856 | 0.3898 |

### DM Tests vs MF-GJR(VIX)
| Ensemble | DM t-stat | Significant? | Direction |
|----------|-----------|-------------|-----------|
| OLS Stack | -1.728 | No | MF-GJR better |
| Inv QLIKE | -2.123 | No (t<3.0) | MF-GJR better |
| EQ Weight | -2.178 | No (t<3.0) | MF-GJR better |
| Rank Hybrid | -3.717 | Yes | MF-GJR better |

### OLS Stacking Weights (Mean)
- MF-GJR: 41.7% (dominant)
- GJR: 31.5%
- CARR_YZ: 15.4%
- GARCH: 11.4%

## Conclusions
1. **No ensemble beats MF-GJR(VIX)**: All four ensemble methods produce higher QLIKE than MF-GJR(VIX) alone. MF-GJR(VIX) remains the best single model.
2. **VIX information is sufficient**: The VIX already captures the long-run volatility component that CARR provides via range. Adding CARR to an ensemble with MF-GJR(VIX) adds noise, not signal.
3. **Rank-Level Hybrid fails**: CARR's ranking advantage does not transfer well to GARCH's calibration scale. The method produces worse QLIKE (1.558) than simple averaging (1.494).
4. **OLS Stacking reveals information hierarchy**: MF-GJR gets 41.7% weight, confirming it carries the most predictive content. CARR_YZ gets only 15.4%.
5. **Combination puzzle partially confirmed**: Among ensembles, Inv QLIKE (1.4924) marginally beats Equal Weight (1.4937), but the gap is economically negligible.

## Limitations
- Single asset (SPY), single OOS period
- CARR_YZ-to-sigma^2 conversion assumes YZ is unbiased for daily variance
- Rolling 252-day weight estimation adds estimation noise
- No Model Confidence Set (MCS) test for multiple comparison control

## Files
- `k937.py` -- experiment script
- `k937_results.json` -- complete results
- `k937_ensemble_comparison.png` -- visualization (4 panels)
