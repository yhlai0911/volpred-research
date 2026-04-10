# K1015: VIX9D+VIX3M Dual-Factor A4f Model

## Research Question
VIX9D captures short-term (9-day) implied volatility and VIX3M captures medium-term (3-month). Does combining them in a dual-factor A4f model improve volatility prediction over single-factor A4f-VIX9D? Does the term structure slope (VIX9D/VIX3M - 1) carry incremental information?

## Motivation
- K1004 showed A4f-VIX9D-t significantly beats A4f-VIX-t (SPY DM t=-4.588)
- K1003 showed VIX9D DM t=+5.15 but VIX3M only DM t=+2.59 (not robust)
- K879 found VIX/VIX3M reversion speed NULL (half-life partial r=0.014)
- Natural extension: test if VIX3M adds incremental value beyond VIX9D

## Models Tested (6 models, all Student-t)

| Model | Specification | QLIKE | Rank |
|-------|--------------|-------|------|
| M1: A4f-VIX9D | tau = theta0 + theta1*VIX9D^2 | **-8.382674** | **1** |
| M3: A4f-Dual | tau = theta0 + theta1*VIX9D^2 + theta2*VIX3M^2 | -8.381938 | 2 |
| M4: A4f-Slope | tau = theta0 + theta1*VIX9D^2 + theta2*(VIX9D/VIX3M-1)^2 | -8.379730 | 3 |
| M5: A4f-VIX | tau = theta0 + theta1*VIX^2 | -8.350955 | 4 |
| M2: A4f-VIX3M | tau = theta0 + theta1*VIX3M^2 | -8.329025 | 5 |
| M6: GJR-t | Standard GJR-GARCH(1,1) | -8.265577 | 6 |

## Key DM Test Results

| Comparison | DM t-stat | Harvey Significant (|t|>3.0) |
|-----------|-----------|------------------------------|
| M1 vs M3 (VIX9D vs Dual) | -0.298 | No |
| M1 vs M4 (VIX9D vs Slope) | -1.333 | No |
| M1 vs M2 (VIX9D vs VIX3M) | **-5.953** | **Yes** |
| M1 vs M5 (VIX9D vs VIX) | **-4.808** | **Yes** |
| M1 vs M6 (VIX9D vs GJR) | **-6.127** | **Yes** |
| M3 vs M6 (Dual vs GJR) | **-6.298** | **Yes** |

## Parameter Degeneracy

Both dual-factor models collapsed to single-factor:
- **M3 (Dual)**: theta2(VIX3M) = 0.0000 (degenerate -- VIX3M adds nothing)
- **M4 (Slope)**: theta2(slope) = 0.0000 (degenerate -- term structure slope adds nothing)

This means the optimizer found no incremental value in VIX3M or the slope beyond what VIX9D already captures.

## VaR/ES 2.5% Backtest

| Model | Violations | Rate | Kupiec p | CC p | DQ p | Basel | ES Z1 p | ES Z2 p | Score |
|-------|-----------|------|----------|------|------|-------|---------|---------|-------|
| M1: A4f-VIX9D | 47 | 2.56% | 0.879 | 0.846 | 0.995 | GREEN | 0.523 | 0.542 | **6/6** |
| M2: A4f-VIX3M | 50 | 2.72% | 0.553 | 0.740 | 0.603 | GREEN | 0.515 | 0.533 | 6/6 |
| M3: A4f-Dual | 49 | 2.66% | 0.655 | 0.774 | 0.753 | GREEN | 0.513 | 0.541 | 6/6 |
| M4: A4f-Slope | 49 | 2.66% | 0.655 | 0.774 | 0.798 | GREEN | 0.513 | 0.540 | 6/6 |
| M5: A4f-VIX | 52 | 2.83% | 0.378 | 0.672 | 0.681 | GREEN | 0.516 | 0.538 | 6/6 |
| M6: GJR-t | 62 | 3.37% | 0.023 | 0.947 | 0.024 | GREEN | 0.503 | 0.539 | **4/6** |

## Data
- **Asset**: SPY
- **Source**: yfinance
- **Full period**: 2011-01-03 to 2026-04-09 (N=3839)
- **OOS period**: 2018-12-13 to 2026-04-09 (N=1839)
- **Window**: 2000, refit every 63 days
- **Seed**: 42

## Conclusions

1. **A4f-VIX9D remains the best single model** -- QLIKE rank 1, VaR/ES score 6/6, DM t=-6.127 vs GJR
2. **VIX3M adds NO incremental value** -- theta2 collapses to 0 in both M3 and M4, DM t=-0.298 (not significant)
3. **Term structure slope adds NO value** -- theta2(slope) = 0, DM t=-1.333 (not significant)
4. **VIX9D >> VIX3M as a single factor** -- DM t=-5.953, highly significant under Harvey threshold
5. **Implication**: short-term fear (VIX9D) is sufficient for the long-run component. Medium-term (VIX3M) is redundant given VIX9D, consistent with K879's finding that VIX/VIX3M reversion speed is NULL

## Limitations
- SPY only (no cross-asset validation)
- OOS period 2018-2026 includes COVID and 2022 rate hike cycle but no 2008 crisis
- Degeneracy of theta2 may be sample-specific; different market regimes could activate VIX3M
- Slope measured as (VIX9D/VIX3M - 1)^2 loses sign information; alternative: separate contango/backwardation dummies

## Files
- `k1015.py` -- experiment script
- `k1015_results.json` -- complete results
- `k1015_qlike_comparison.png` -- QLIKE bar chart
- `k1015_var_timeline.png` -- VaR 2.5% violation timeline

## References
- Engle & Rangel (2008) - Spline-GARCH
- Patton (2011) - QLIKE loss proxy-robust ranking
- Kupiec (1995) - VaR unconditional coverage
- Christoffersen (1998) - VaR conditional coverage
- Engle & Manganelli (2004) - DQ test
- Acerbi & Szekely (2014) - ES backtesting
- Harvey (2016) - Multiple testing threshold t>3.0
