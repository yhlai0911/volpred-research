# K995b: Paper 9 Table 11 Residual Diagnostics Source Recovery

**[提出: 賴奕豪, 執行: Claude]**

## 動機

Paper 9 (garch-x-vix, submitted J. Empirical Finance) reproducibility audit (commit 4e84d37f) found Table 11 residual diagnostics had no script source:
- GJR-t: kurtosis=3.065, skewness=-0.856, JB=938.8
- A4f-t: kurtosis=1.238, skewness=-0.594, JB=224.2

K995b identifies K1045 as the source and replicates its methodology.

## Key Finding: K1045 is the Source

**`experiments/K1045/k1045.py`** (run 2026-04-11) produced all Table 11 values:

| Value | K1045 | Paper | Match |
|-------|-------|-------|-------|
| GJR-t kurtosis | 3.0650 | 3.065 | ✓ exact |
| GJR-t skewness | -0.8560 | -0.856 | ✓ exact |
| GJR-t JB | 938.78 | 938.8 | ✓ rounded |
| A4f-t kurtosis | 1.2384 | 1.238 | ✓ exact |
| A4f-t skewness | -0.5937 | -0.594 | ✓ exact |
| A4f-t JB | 224.19 | 224.2 | ✓ rounded |
| GJR-t median ν | 5.28 | 5.28 | ✓ exact |
| A4f-t median ν | 8.00 | 8.00 | ✓ exact |

## Kurtosis Convention

**Fisher excess kurtosis** (scipy.stats.kurtosis, fisher=True, normal=0).

Paper footnote: "Excess kurtosis relative to normal (=0)" confirms this.

## K1045 Methodology (differs from K995)

| Parameter | K1045 | K995 |
|-----------|-------|------|
| VIX transform | `(vix/100)^2` | raw VIX |
| Return clipping | `clip(-0.20, 0.20)` | none |
| GJR-t df | joint MLE | joint MLE |
| A4f-t df | joint MLE | residual-based |
| Student-t | `1 + z²/df` (standard t) | `1 + z²/(df-2)` (standardized) |
| Data end | 2026-04-10 (n_oos=1828) | 2026-04-07 (n_oos=1825) |

## K995b Reproduction Results

| Cell | K995b | Paper | Status |
|------|-------|-------|--------|
| GJR-t kurtosis | 2.686 | 3.065 | DIVERGENT (12.4%) |
| GJR-t skewness | -0.811 | -0.856 | APPROX (5.3%) |
| GJR-t JB | 750.0 | 938.8 | DIVERGENT (20.1%) |
| A4f-t kurtosis | 1.227 | 1.238 | MATCHED (0.9%) |
| A4f-t skewness | -0.593 | -0.594 | MATCHED (0.2%) |
| A4f-t JB | 221.8 | 224.2 | APPROX (1.1%) |

**A4f-t: fully reproduced within 1.1% (MATCHED/APPROX)**  
**GJR-t: divergent — optimization sensitivity (different local optimum for df)**

Root cause of GJR-t divergence: L-BFGS-B converges to median_ν≈7.13 in K995b vs 5.28 in K1045. The GJR-t likelihood surface with 5 parameters has multiple local optima; lower df (fatter tails) produces higher excess kurtosis in standardized residuals.

## Recommendations

1. **(a)** Add K1045 to `paper/garch-x-vix/experiments.md` as source for Table 11
2. **(b)** Include `experiments/K1045/k1045.py` in the replication package as the one-click script for Table 11
3. **(c)** Note optimization sensitivity for GJR-t in supplementary materials

## Data

- SPY + VIX from yfinance
- K1045 data: 2004-01-05 to 2026-04-10, OOS 2019-01-02 to 2026-04-10, n=1828
- K995b data: 2004-01-05 to 2026-04-10 (same period)

## Files

- `k995b.py`: Replication script (K1045 methodology)
- `k995b_results.json`: Results with reproduction status
- `k995b_vs_paper9_table11_diff.md`: Per-cell diff table and recommendations
- `run.log`: Full execution log

## References

- K1045: A4f vs GJR Residual Diagnostic Suite (2026-04-11)
- K995: VaR/ES Backtesting for MF-GJR-X(A4f) vs GJR-GARCH
- Paper 9 (garch-x-vix): Submitted J. Empirical Finance
- Jarque & Bera (1987). A test for normality. ISR 55(2):163-172.
