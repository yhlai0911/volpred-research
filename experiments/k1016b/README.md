# K1016b: HAR+vix_gap Corrected (Fixed M4/M5 Bug + vix_gap Variants)

## Problem Description
K1016 had two bugs:
1. **M4 (A4f-VIX9D) and M5 (GJR-t) produced identical results** (QLIKE=1.537, Spearman=0.386). The `arch` library's `x=` parameter silently fell back to plain GJR when VIX9D had NaN values.
2. **HAR+vix_gap improved on |r| (DM=-2.87) but degraded on QLIKE(r²)** (1.616 to 1.831). Needed investigation.

## Fixes Applied
- M4 (A4f): Reimplemented using K988's multiplicative GARCH-X (tau = theta0 + theta1*VIX^2, free omega, GJR g_t) via custom MLE
- M5 (GJR-t): Reimplemented with custom Student-t MLE, independent from arch library
- Added vix_gap variants: vix_gap^2 (M2b) and |vix_gap| (M2c)
- Changed vix_gap definition: VIX/(100*sqrt(252)) - |r|_5d (using abs return average, not sqrt(rv_22))

## Key Results

### Model Comparison (QLIKE on r^2, lower = better)
| Model | QLIKE | Spearman(r^2) |
|-------|-------|--------------|
| **M4: A4f (VIX^2)** | **1.467** | **0.422** |
| M2c: HAR+\|vix_gap\| | 1.533 | 0.384 |
| M2b: HAR+vix_gap^2 | 1.546 | 0.367 |
| M5: GJR-t | 1.586 | 0.355 |
| M1: HAR(1,5,22) | 1.616 | 0.323 |
| M2: HAR+vix_gap | 1.623 | 0.393 |
| M3: HAR+VIX_level | 1.623 | 0.393 |

### DM Tests (Harvey |t| > 3.0)
| Comparison | t-stat | Significant? |
|-----------|--------|-------------|
| M4 vs M5 | -5.05 | Yes, A4f wins |
| M2b vs M1 | -5.57 | Yes, vix_gap^2 improves |
| M2c vs M1 | -4.20 | Yes, \|vix_gap\| improves |
| M1 vs M4 | 6.92 | Yes, A4f much better |
| M2 vs M1 | 0.16 | No |
| M3 vs M1 | 0.16 | No |

## Key Findings

### 1. M4/M5 Bug Confirmed and Fixed
- M4-M5 correlation now = 0.835 (was 1.000 in K1016)
- A4f (M4) clearly outperforms GJR (M5): DM t=-5.05

### 2. vix_gap = VIX_level in linear HAR
- M2 (HAR+vix_gap) and M3 (HAR+VIX_level) produce **identical** results
- Reason: vix_gap = VIX/(100*sqrt(252)) - |r|_5d, and |r|_5d is already a HAR regressor
- In a linear model with |r|_5d included, adding vix_gap or VIX_level is algebraically equivalent
- The vix_gap construct offers no advantage over raw VIX in a linear HAR specification

### 3. Non-linear vix_gap transforms work
- vix_gap^2 (M2b): QLIKE=1.546, DM t=-5.57 vs M1 (significant)
- |vix_gap| (M2c): QLIKE=1.533, DM t=-4.20 vs M1 (significant)
- These break the linear equivalence with VIX_level
- |vix_gap| is the best HAR extension tested

### 4. A4f dominates all HAR variants on QLIKE
- A4f QLIKE=1.467 vs best HAR(|vix_gap|)=1.533
- DM t=3.71 (M2 vs M4), confirming GARCH-type models' superiority on r^2 target
- This is consistent with K782 finding: GARCH beats HAR on r^2 (its native target)

### 5. MSE(|r|) tells a different story
- On |r| target, HAR+vix_gap (M2) beats HAR baseline: DM t=-2.48
- vix_gap^2 (M2b) does NOT improve on |r|: DM t=0.69 (NS)
- This confirms the dual-target evaluation is essential (Patton 2011)

## Conclusion
- The K1016 M4/M5 bug was caused by arch library fallback, now fixed with custom MLE
- Linear vix_gap offers no advantage over VIX_level in HAR (algebraic equivalence)
- Non-linear transforms (vix_gap^2, |vix_gap|) break this equivalence and significantly improve QLIKE
- A4f (multiplicative GARCH-X) remains the best model on r^2 target

## References
- Corsi (2009) JAE: HAR-RV
- Patton (2011) JoE: QLIKE proxy-robustness
- Harvey et al. (2016) RFS: t > 3.0 threshold
- K988: A4f implementation
- K1016: Original (buggy) version
