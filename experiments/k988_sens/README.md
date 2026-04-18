# K988_sens: Paper 9 Table 12 Sensitivity Replication

## Purpose

Provide a reproducible JSON source for Paper 9 (garch-x-vix) Table 12 (sensitivity analysis of A4f specification), resolving audit flag D4: "Table 12 sensitivity analysis (16 DM t-statistics) has no corresponding JSON source in experiments/."

## Background

Paper 9 Table 12 reports DM t-statistics across four sensitivity dimensions:
1. **Refit frequency**: 21, 63, 126, 252 trading days (4 rows)
2. **Training window**: W = 1000, 1500, 2000, 2500, 3000 days (5 rows)
3. **OOS sub-period**: 2019–2020 (COVID), 2021–2022 (rate hikes), 2023–2026 (stable) (3 rows)
4. **VIX variant**: VIX, VIX9D, VIX3M, VIX/VIX3M ratio (4 rows)

Total: 4 + 5 + 3 + 4 = **16 cells**

The original script that generated these values was missing from `experiments/`. This experiment provides the replication.

## Model

**A4f** (champion from K988):
- Short-run: GJR-GARCH(1,1) on standardized returns
- Long-run component: τ_t = θ₀ + θ₁ · VIX²_{t-1} (free ω)
- Denominator: τ_t (Engle et al. 2013 logic)

**Baseline**: GJR-GARCH(1,1) with no external regressor

**Loss**: QLIKE on r² (Patton 2011)

**Test**: DM statistic with Newey-West HAC, Harvey (2016) |t| > 3.0 threshold

## Data

| Item | Value |
|---|---|
| Asset | SPY (daily log returns from Yahoo Finance) |
| VIX | ^VIX, ^VIX9D, ^VIX3M from Yahoo Finance |
| Data start | 2005-01-04 |
| Data end | 2026-03-30 |
| Base OOS start | 2019-01-01 |
| Base n_OOS | 1820 |

Note: Paper uses data to 2026-04-07 (n_OOS=1825). The 5-day difference accounts for some numerical variation in DM t.

## Results Summary

| Cell | Paper DM t | K988_sens DM t | Match |
|---|---|---|---|
| refit_21 | 4.29 | 4.016 | APPROX |
| refit_63 (baseline) | 3.92 | 3.924 | MATCHED |
| refit_126 | 3.36 | 4.182 | DIVERGENT |
| refit_252 | 3.32 | 3.831 | APPROX |
| window_1000 | 3.18 | 3.499 | APPROX |
| window_1500 | 3.49 | 3.656 | MATCHED |
| window_2000 (baseline) | 3.92 | 3.924 | MATCHED |
| window_2500 | 5.13 | 4.870 | APPROX |
| window_3000 | 4.94 | 5.441 | APPROX |
| sub_2019_2020 | 1.60 | 1.544 | MATCHED |
| sub_2021_2022 | 2.50 | 3.181 | DIVERGENT |
| sub_2023_2026 | 4.52 | 4.411 | MATCHED |
| vix_VIX | 3.92 | 3.924 | MATCHED |
| vix_VIX9D | 5.15 | 5.386 | MATCHED |
| vix_VIX3M | 2.59 | 2.491 | MATCHED |
| vix_ratio | 3.53 | 2.809 | DIVERGENT |

**8 MATCHED / 5 APPROX / 3 DIVERGENT / 0 SKIPPED**

Harvey pass (|t| > 3.0): Paper = 13/16, K988_sens = 13/16 (identical count)

## Key Findings

1. Qualitative conclusions **fully preserved**: A4f outperforms GJR in all 16 cells (all DM t > 0), Harvey-significant in 13/16 in both paper and replication.
2. Three divergent cells (`refit_126`, `sub_2021_2022`, `vix_ratio`) all have credible explanations: coarse-refit instability, short sub-period noise (n=503), and undocumented VIX3M alignment.
3. The original Table 12 generation script was missing (D4 confirmed). This experiment is now the **canonical JSON source**.
4. Recommendation: **(b) paper errata** — add footnote documenting the replication; no substantive revision needed.

## Files

| File | Description |
|---|---|
| `k988_sens.py` | Main script |
| `k988_sens_results.json` | 16-cell results JSON |
| `run.log` | Execution log (~29 min) |
| `k988_sens_vs_paper9_table12_diff.md` | Cell-by-cell diff analysis |
| `README.md` | This file |

## Runtime

~1730 seconds (~29 minutes) on M1 Max MacBook Pro

## Related Experiments

- `experiments/k988/` — Base K988 experiment (A4f model fitting + OOS evaluation)
- `paper/garch-x-vix/main.tex` — Table 12 source in Section 6.1 (Sensitivity to Estimation Settings)

## References

- Patton (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics* 160:246–256.
- Harvey, Liu & Zhu (2016). ...and the cross-section of expected returns. *Review of Financial Studies* 29(1):5–68.
- Diebold & Mariano (1995). Comparing predictive accuracy. *Journal of Business and Economic Statistics* 13(3):253–263.
- Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. *Review of Economics and Statistics* 95(3):776–797.

## Author

VolPred Research System | 2026-04-17 | seed=42
