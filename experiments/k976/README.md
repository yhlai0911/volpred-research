# K976: MF2-GARCH + VIX Slope Integration

## Motivation
K970 showed MF2-VIX (using VIX as long-run component) improved GJR QLIKE by 9.55% (DM t=2.94). K975 found VIX slope (VIX/VIX3M) adds +2.2% incremental R-squared for 5d RV prediction. This experiment tests whether combining VIX level and VIX slope in the MF2-GARCH framework provides further improvement.

## Method
- **Data**: SPY, VIX, VIX3M from yfinance (2010-01-05 to 2026-04-06, 4087 obs)
- **IS**: 2010-2018, **OOS**: 2019-2026 (1824 days)
- **Target**: r-squared (squared daily return)
- **All tau values use shift(1)** to avoid lookahead bias

### Models Tested
1. **GJR-GARCH** (baseline)
2. **MF2-VIX**: tau = (VIX/sqrt(252))^2
3. **MF2-VIX-Slope**: tau = (VIX/sqrt(252))^2 x slope_adj, where slope_adj amplifies tau in backwardation (VIX/VIX3M > 1). Parameter k calibrated on IS via QLIKE grid search.
4. **MF2-2Factor**: tau = alpha x VIX^2 + beta x VIX^2 x slope + gamma. Coefficients estimated via OLS on IS.
5. **MF2-VIX+EMA**: tau = w1 x VIX^2 + w2 x EMA(r^2). Weights calibrated on IS via QLIKE grid search.

### Evaluation
- QLIKE, MSE, Mincer-Zarnowitz regression
- Diebold-Mariano test (vs GJR and vs MF2-VIX)
- VaR backtesting (1%, 5%) with Kupiec test

## Key Results

### QLIKE Ranking (OOS)
| Model | QLIKE | MSE | MZ R-squared |
|-------|-------|-----|-------------|
| MF2-2Factor | -8.3754 | 2.51e-7 | 0.3353 |
| MF2-VIX | -8.3611 | 2.78e-7 | 0.2832 |
| MF2-VIX-Slope | -8.3611 | 2.78e-7 | 0.2832 |
| MF2-VIX+EMA | -8.2795 | 3.01e-7 | 0.3080 |
| GJR | -8.2741 | 2.68e-7 | 0.2977 |

### Calibrated Parameters
- **Slope adjustment k = 0.00** (slope provides no benefit in multiplicative form)
- **2-Factor OLS**: alpha=7.6e-5, beta=2.9e-4, gamma=1.6e-5
- **VIX+EMA weights**: w1(VIX)=0.00, w2(EMA)=1.00 (pure EMA dominates)

### DM Tests
| Comparison | t-stat | p-value | Significant? |
|-----------|--------|---------|-------------|
| MF2-VIX vs GJR | 2.720 | 0.0065 | Yes *** |
| MF2-2Factor vs GJR | 3.265 | 0.0011 | Yes *** |
| MF2-VIX+EMA vs GJR | 0.139 | 0.8894 | No |
| MF2-VIX-Slope vs MF2-VIX | 0.000 | 1.0000 | No (identical) |
| MF2-2Factor vs MF2-VIX | 1.420 | 0.1557 | No |
| MF2-VIX+EMA vs MF2-VIX | -4.805 | 0.0000 | Worse *** |

## Conclusions

1. **VIX slope does NOT add significant value** in the MF2-GARCH framework:
   - Multiplicative form (slope_adj): calibrated k=0, zero effect
   - 2-Factor form: marginally better QLIKE but DM t=1.42, p=0.156 (not significant)

2. **MF2-2Factor has best point QLIKE** but the improvement over MF2-VIX is not statistically significant. The OLS coefficients show beta (slope interaction) is 3.9x larger than alpha, suggesting slope captures something, but noise dominates.

3. **VIX+EMA is strictly worse than MF2-VIX** (DM t=-4.81, highly significant). The IS calibration chose pure EMA (w1=0), confirming that adding VIX to EMA in an additive framework provides no benefit -- the VIX information is better incorporated multiplicatively.

4. **MF2-VIX remains the recommended tau specification**: simple, significant improvement over GJR (DM t=2.72), and adding slope complexity is not justified by the data.

5. **Why slope fails in MF2 but works for 5d RV (K975)?** The VIX slope captures term structure dynamics relevant for multi-day horizons. At the daily frequency used by GARCH, VIX level already captures most of the relevant information. The slope's predictive power for 5d RV may come from mean-reversion in the term structure that unfolds over days, not within a single day.

## Limitations
- Single asset (SPY), single OOS period
- IS calibration of slope parameters may be unstable across different IS windows
- VIX3M data only available from 2010, limiting sample size
- Did not test nonlinear slope transformations or regime-dependent models

## Files
- `k976_mf2_slope.py` -- experiment script
- `k976_mf2_slope_results.json` -- full results
- `k976_tau_comparison.png` -- tau comparison across models
- `k976_oos_comparison.png` -- OOS forecast comparison
- `k976_slope_analysis.png` -- VIX slope distribution and relationship

## References
- Engle & Rangel (2008) Spline-GARCH
- Patton (2011) QLIKE loss function
- K970: MF2-VIX baseline (QLIKE improvement 9.55%)
- K975: VIX Slope analysis (+2.2% R-squared for 5d RV)
