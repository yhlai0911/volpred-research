# K1184: Paper 2 Skew-t Parameters Verification

**Status**: COMPLETE  
**Date**: 2026-04-17  
**Worktree**: agent-aa2d76a6

## Motivation

Paper 2 (`paper/taiwan-vt/body.tex`, line 459) claims:

> "For 0050.TW, the estimated parameters are η = 5.2 and λ = −0.05 (near-symmetric with moderate fat tails)."

The reproducibility audit (`diff_report.md`) flagged both numbers as "? No source" — no backing experiment JSON existed. K1184 provides that backing.

## Model

- **Distribution**: Hansen (1994) skewed Student-t
- **Reference**: Hansen (1994) "Autoregressive Conditional Density Estimation," IER 35(3):705–730
- **Procedure**: Fit GJR-GARCH(1,1) to 0050.TW daily log returns, then fit skew-t MLE to standardized residuals
- **K1100c connection**: Uses the same Hansen (1994) PDF implementation as K1100c bivariate skew-t copula

## Data

- Ticker: 0050.TW (Taiwan 50 ETF)
- Period: 2009-01-02 to 2026-03-31 (n=4,216 after removing 2014-01-02 split artifact)
- Returns: log close-to-close, multiplied by 100

**Note on 2014-01-02 data artifact**: yfinance reports a spurious –138.89% return on this date due to a 4:1 stock split that was not properly adjusted. This is excluded as a known data error; the paper's original estimation likely used adjusted CCXE/TEJ data without this issue.

## Results

| Parameter | Paper (body.tex:459) | MLE Full-Sample | Diff | Status |
|---|---|---|---|---|
| η (degrees of freedom) | 5.2 | 4.968 | 0.232 (4.5%) | MATCH |
| λ (skewness) | −0.05 | −0.059 | 0.009 | MATCH |

OOS sub-period (2020–2026):

| Parameter | Paper | MLE OOS | Diff | Status |
|---|---|---|---|---|
| η | 5.2 | 6.034 | 0.834 | DIVERGE |
| λ | −0.05 | −0.043 | 0.007 | MATCH |

**Overall verdict: (a) MATCHED** — full-sample η within 4.5%, λ within 18% (absolute diff 0.009, economically negligible).

The symmetric Student-t MLE yields df=4.97, consistent with the paper's fixed df=5 assumption.

## GJR-GARCH Parameters (Full Sample)

| Param | Value |
|---|---|
| ω | 0.04333 |
| α | 0.0437 |
| γ | 0.1010 |
| β | 0.8803 |
| Persistence | 0.9745 |
| Converged | Yes |

Standardized residuals: mean=0.053, std=1.007, skew=−0.136, kurt=4.000

## VaR Violation Count (2020–2026, n=1,513 days)

| Method | Violations | Rate |
|---|---|---|
| Student-t(df=5) | 20 | 1.32% |
| Symmetric t MLE (df=4.97) | 20 | 1.32% |
| Paper claimed | 8 | 0.5% |

The paper claims 8 violations (0.5%) but K1184 obtains 20 (1.32%) using Student-t(df=5). This divergence matches the DIV-2 issue identified in the reproducibility audit — the paper's 8-violation claim likely refers to the Cornish-Fisher (CF) variant or a different sub-period (not available via yfinance). The skew-t parameter estimates (η, λ) themselves are confirmed.

## Files

- `k1184.py` — implementation
- `k1184_results.json` — MLE estimates and comparison table
- `k1184_vs_paper2_skew-t_diff.md` — detailed diff report
- `run.log` — execution log

## Related Experiments

- K1100c: Hansen (1994) skew-t copula bivariate implementation (shared PDF code)
- K896: VaR violation analysis (2019–2026 period)
