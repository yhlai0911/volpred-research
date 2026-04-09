# K1010: Probabilistic Volatility Quantile Forecasting

## Motivation
Traditional volatility forecasts produce point estimates. Risk management needs prediction intervals (PIs) with quantified uncertainty. This experiment tests whether quantile regression (QR) on forecast errors can improve PI calibration beyond standard parametric assumptions (Normal, Student-t).

## Research Questions
1. Are A4f's prediction intervals properly calibrated under different distributional assumptions?
2. Does QR correction improve calibration vs parametric Normal/t PIs?
3. Can QR-based conditional quantiles improve VaR computation?

## Method
- **Models**: GJR-GARCH(1,1), A4f (MF-GJR-X with VIX-squared tau, free omega), A4f-t (joint Student-t)
- **Data**: SPY 2005-01-04 to 2026-04-07 (n=5,347), OOS 2019-01 to 2026-04 (n=1,825)
- **Config**: window=2000, refit/63d, QR window=500
- **PI methods** (6 total):
  1. GJR + Normal (chi2(1) quantiles)
  2. GJR + QR (quantile regression on forecast errors)
  3. A4f + Normal
  4. A4f + QR
  5. A4f + Student-t (F(1,df) quantiles)
  6. Direct QR on r^2 (using GJR+A4f+VIX as features)
- **Evaluation**: Coverage calibration (9 quantiles), sharpness (PI width), Winkler score, VaR/ES backtesting

## Key Results

### Point Forecasts (QLIKE)
| Model | QLIKE | DM vs GJR |
|-------|-------|-----------|
| GJR   | -8.291 | baseline |
| A4f   | -8.362 | t=3.687*** |
| A4f-t | -8.362 | same h sequence |

A4f significantly beats GJR (DM t=3.687 > Harvey 3.0 threshold).

### Calibration (MAD from target, lower=better)
| Method | MAD | Rank |
|--------|-----|------|
| A4f_t | 0.0064 | 1 (best) |
| GJR_Normal | 0.0157 | 2 |
| GJR_QR | 0.0164 | 3 |
| A4f_Normal | 0.0171 | 4 |
| Direct_QR | 0.0242 | 5 |
| A4f_QR | 0.0317 | 6 (worst) |

### Winkler Score (lower=better, combines calibration + sharpness)
| PI Level | Best Method | Score |
|----------|-------------|-------|
| 95% | A4f_Normal | 0.000913 |
| 90% | A4f_Normal | 0.000725 |
| 80% | A4f_t | 0.000545 |

### VaR Backtesting (pass/4 = UC + CC + DQ + Basel)
| Method | 1% VaR | 2.5% VaR | 5% VaR |
|--------|--------|----------|--------|
| GJR_Normal | 1/4 (RED) | 3/4 | 4/4 |
| A4f_Normal | 1/4 (YELLOW) | 4/4 | 4/4 |
| **A4f_t** | **4/4 (GREEN)** | **4/4** | **4/4** |
| A4f_QR_med | 0/4 (RED) | 0/4 | 1/4 |

## Conclusions

1. **A4f + Student-t is the clear winner** for probabilistic forecasting:
   - Best calibration (MAD=0.0064)
   - Only method passing ALL VaR backtests at ALL confidence levels (12/12)
   - Competitive Winkler scores

2. **QR does NOT improve calibration** -- it actually makes it worse:
   - QR overestimates lower quantiles (coverage ~7% at tau=0.025 vs target 2.5%)
   - This translates to terrible VaR performance (A4f_QR_med: 9-15% violation rates)
   - Likely cause: QR on squared-return errors amplifies noise in the tails

3. **Parametric Normal PIs are reasonably well-calibrated** for GJR and A4f at intermediate quantiles but fail at extreme tails (1% VaR). Student-t correction fixes this.

4. **Practical recommendation**: Use A4f + Student-t (joint MLE, df~8) for both point forecasts and risk management. The parametric t-distribution captures tail behavior that neither Normal assumption nor QR can match.

## Limitations
- QR on r^2 forecast errors may not be the optimal target; QR directly on returns could perform differently
- Student-t df estimated as median=8.0 across all refits; time-varying df could improve further
- Single asset (SPY); cross-asset validation needed
- QR_WINDOW=500 is somewhat arbitrary; sensitivity analysis not done

## Files
- `k1010.py` -- experiment script
- `k1010_results.json` -- full results

## References
- Koenker & Bassett (1978). Regression Quantiles. Econometrica 46:33-50.
- Christoffersen (1998). Evaluating Interval Forecasts. Int Econ Rev 39:841-862.
- Gneiting & Raftery (2007). JASA 102:359-378.
- Winkler (1972). JASA 67:187-191.
- Patton (2011). J Econometrics 160:246-256.
- Kupiec (1995). J Derivatives 3:73-84.
- Acerbi & Szekely (2014). Risk Magazine.
