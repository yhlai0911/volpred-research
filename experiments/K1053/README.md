# K1053: VIX Term Structure Slope as Volatility Predictor

**[提出: Claude, 執行: Claude]**

## Motivation

K975 found the VIX term structure slope is a "significant vol predictor" but details were unclear. K976 found VIX slope is NULL at daily frequency (horizon mismatch). K1015 found VIX9D+VIX3M dual-factor NULL (collinear with VIX). Paper 9 Table 8 shows VIX/VIX3M ratio has DM t=3.53 in sensitivity analysis. K1052 found asymmetric VIX NULL. This experiment tests whether the VIX term structure slope (VIX/VIX3M ratio or VIX-VIX3M spread) adds **incremental** predictive power beyond VIX level alone in the A4f framework.

## Method

5 models compared on SPY (OOS 2019-2026, window=2000, refit/63d, seed=42):

| Model | Tau Specification | Description |
|-------|------------------|-------------|
| M1 (baseline) | theta0 + theta1 * VIX^2 | A4f-VIX |
| M2 | theta0 + theta1 * VIX^2 + theta2 * (VIX/VIX3M) | A4f + slope ratio |
| M3 | theta0 + theta1 * VIX^2 + theta3 * (VIX-VIX3M)^2 | A4f + spread squared |
| M4 | theta0 + theta1 * VIX9D^2 | A4f-VIX9D (best single variant) |
| M5 | GJR-GARCH(1,1) | Benchmark |

Evaluation: QLIKE on r^2 (Patton 2011), DM test (Harvey |t| > 3.0), Spearman rho.

## Key Results

### QLIKE Ranking (lower = better)

| Rank | Model | QLIKE | Spearman rho |
|------|-------|-------|--------------|
| 1 | M4 A4f-VIX9D | 1.3890 | 0.4358 |
| 2 | M3 A4f-VIX+Spread^2 | 1.3989 | 0.4310 |
| 3 | M1 A4f-VIX (baseline) | 1.4115 | 0.4202 |
| 4 | M2 A4f-VIX+Slope | 1.4129 | 0.4194 |
| 5 | M5 GJR | 1.4948 | 0.3681 |

### DM Test Results

| Comparison | DM t | Sig | Winner |
|-----------|------|-----|--------|
| M2 vs M1 (slope adds info?) | +0.584 | NS | M1 (slope adds nothing) |
| M3 vs M1 (spread adds info?) | -2.168 | ** | M3 (weak, fails Harvey) |
| M1 vs M5 (A4f beats GJR?) | -3.559 | *** | M1 (Harvey PASS) |
| M4 vs M1 (VIX9D beats VIX?) | -2.663 | ** | M4 (weak, fails Harvey) |
| M2 vs M4 (slope vs VIX9D?) | +2.940 | ** | M4 (VIX9D > VIX+slope) |
| M4 vs M5 (VIX9D beats GJR?) | -4.725 | *** | M4 (Harvey PASS) |

## Conclusion: NULL

**The VIX term structure slope does NOT add statistically significant incremental information beyond VIX level alone in the A4f framework** (Harvey threshold |t| > 3.0):

1. **M2 (VIX + slope ratio) vs M1 (VIX only)**: DM t = +0.584 (NS). The slope ratio adds zero incremental value. The slope contribution is only ~10% of VIX level's contribution.

2. **M3 (VIX + spread^2) vs M1 (VIX only)**: DM t = -2.168. Suggestive improvement but fails Harvey (2016) threshold of |t| > 3.0. The spread squared contributes ~28% of VIX level's magnitude, but not enough to be statistically significant.

3. **VIX9D remains the best single VIX variant** (QLIKE 1.389 vs 1.411 for VIX), consistent with K1004/K1015 findings. DM t = -2.663 vs M1, suggestive but still fails Harvey threshold.

4. **All A4f variants beat GJR** at Harvey threshold (M1 t=-3.56, M3 t=-4.34, M4 t=-4.73).

### Descriptive Statistics
- VIX term structure is in contango 89% of the time (VIX < VIX3M)
- Backwardation only 11% of days
- Pearson corr(spread_lag, r^2) = 0.473 > corr(VIX_lag, r^2) = 0.458, but the spread information is already captured by VIX level in the multiplicative GARCH-X framework

### Regime Analysis
- In backwardation (131 OOS days): M2 vs M1 DM t = -0.357 (NS)
- In contango (1697 OOS days): M2 vs M1 DM t = +0.634 (NS)
- No regime-specific advantage for the slope

## Implications

- VIX level (squared) is sufficient for the A4f tau component; the term structure slope is redundant
- The spread has some raw predictive correlation with r^2, but this is already absorbed by VIX^2 in A4f
- VIX9D remains the strongest VIX variant, likely because it better captures near-term fear
- Confirms K1015 (VIX+VIX3M dual factor = NULL) and extends it to slope/spread specifications

## Data

- SPY: 2006-07-17 to 2026-04-10, n=4,965 (limited by VIX3M availability from 2006-07)
- OOS: 2019-01-01 to 2026-04-10, n=1,828
- Source: yfinance (SPY, ^VIX, ^VIX3M, ^VIX9D)

## Files

- `K1053.py` — Experiment script
- `K1053_results.json` — Full results with parameters and DM tests
- `K1053_term_structure.png` — 4-panel chart (QLIKE, term structure, DM tests, Spearman)

## References

- Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
- Harvey et al. (2016). Multiple testing threshold t > 3.0.
- Mixon (2007). The implied volatility term structure. J Deriv 15(2):29-46.
- Campa & Chang (1995). Expectations hypothesis on vol term structure. J Finance 50(2):529-547.
- Lu & Zhu (2010). Volatility components. J Financial Econometrics 8(4):431-456.
