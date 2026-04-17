# K1184 vs Paper 2 Skew-t Parameters Diff Report

**Source**: `paper/taiwan-vt/body.tex` line 459  
**Experiment**: K1184  
**Date**: 2026-04-17

---

## Paper Claim

> "We also evaluate the skewed Student-t distribution, which simultaneously estimates degrees of freedom (η) and skewness (λ) via maximum likelihood, adapting to each asset's specific tail behavior. For 0050.TW, the estimated parameters are η = 5.2 and λ = −0.05 (near-symmetric with moderate fat tails)."

---

## Comparison Table

| Parameter | Paper Value | K1184 Full-Sample | K1184 OOS (2020-2026) |
|---|---|---|---|
| η (degrees of freedom) | **5.2** | 4.968 (−4.5%) | 6.034 (+16%) |
| λ (skewness) | **−0.05** | −0.0590 (−18% rtol) | −0.0430 (+14% rtol) |
| abs(λ) diff | — | 0.009 | 0.007 |
| η diff | — | 0.232 | 0.834 |

---

## Verdict

**(a) MATCHED** — Full-sample η=4.97 vs paper 5.2 (diff 0.23, rtol 4.5%). λ near-zero in both directions, difference 0.009 is economically negligible. The paper's characterization "near-symmetric with moderate fat tails" is confirmed: |λ| < 0.06 in all estimates and η ≈ 5 in full sample.

**Symmetric Student-t MLE**: df=4.97, consistent with paper's fixed df=5 assumption.

---

## Root Cause of Small Discrepancy

The paper values η=5.2, λ=−0.05 are likely from a slightly different estimation window or data source:

1. **Data source**: Paper may use TEJ/Bloomberg adjusted data vs yfinance (post-split prices may differ slightly)
2. **GJR-GARCH specification**: Paper uses rolling window w=2000 with specific start; K1184 uses full sample from 2009
3. **Estimation period**: Paper's "2020–2026 VaR period" vs K1184's full-sample estimation
4. **Rounding**: Paper reports η=5.2 (1 decimal), λ=−0.05 (2 decimal) — standard rounding to readable precision

The η=4.97 is consistent with rounding to η≈5.0 (not 5.2). The discrepancy 5.0 vs 5.2 may reflect different data or rolling window end date.

---

## VaR Violation Divergence (Separate Issue)

K1184 finds 20 violations (1.32%) using Student-t(df=5) over 2020–2026, vs paper's claim of 8 violations (0.5%).

This is a separate issue documented as DIV-2 in the reproducibility audit:
- The paper's 8-violation claim likely corresponds to **Cornish-Fisher (CF) VaR**, not Student-t(df=5)
- K896 confirms GJR+CF → 9 violations (0.51%), GJR+Student-t → 18 violations (1.03%)
- The paper likely mislabels the distribution type for the 8-violation result

**This does NOT affect the skew-t parameter estimates (η, λ), which are confirmed.**

---

## Recommendation

The skew-t parameter estimates η=5.2, λ=−0.05 in the paper are **within acceptable tolerance** of the K1184 MLE results. No paper correction is required for these specific parameters.

However, consider updating the paper to note:
- Full-sample MLE gives η≈5.0 (rounded to 5.2 is slightly high)
- The symmetric Student-t df≈5 is consistent with the skew-t η≈5

The VaR violation count (8 vs 20) remains a separate issue requiring resolution (see DIV-2 in reproducibility audit).

---

## K1100c Connection

K1100c implemented the same Hansen (1994) skew-t PDF as a bivariate copula marginal. K1184 applies the same formula as a univariate marginal for GJR-GARCH standardized residuals. Both share:
- Hansen (1994) PDF formula: `bc[1 + (bz+a)²/((η-2)(1∓λ)²)]^{-(η+1)/2}`
- Constants: `c = Γ((η+1)/2)/(√(π(η-2))·Γ(η/2))`, `a=4λc(η-2)/(η-1)`, `b=√(1+3λ²-a²)`
- The K1100c copula parameter nu (for equity pairs) ≈ 5–8, consistent with K1184's η≈5.
