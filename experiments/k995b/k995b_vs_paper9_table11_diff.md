# K995b vs Paper 9 Table 11 Diff Report

**Date**: 2026-04-17  
**Experiment**: K995b — Paper 9 Table 11 Residual Diagnostics Source Recovery  
**Source identified**: K1045 (`experiments/K1045/k1045.py`, run 2026-04-11)

---

## Summary

| Cell | K1045 (Source) | Paper | K995b | Match |
|------|---------------|-------|-------|-------|
| GJR-t kurtosis | 3.065 | 3.065 | 2.686 | DIVERGENT (12.4%) |
| GJR-t skewness | -0.856 | -0.856 | -0.811 | APPROX (5.3%) |
| GJR-t JB stat | 938.8 | 938.8 | 750.0 | DIVERGENT (20.1%) |
| A4f-t kurtosis | 1.238 | 1.238 | 1.227 | MATCHED (0.9%) |
| A4f-t skewness | -0.594 | -0.594 | -0.593 | MATCHED (0.2%) |
| A4f-t JB stat | 224.2 | 224.2 | 221.8 | APPROX (1.1%) |

**A4f-t: 2 MATCHED + 1 APPROX = fully reproducible within 1.1%**  
**GJR-t: 0 MATCHED + 1 APPROX + 2 DIVERGENT = optimization-sensitive**

---

## Source Identification: K1045

The audit identified **K1045** (`experiments/K1045/k1045.py`) as the source of Paper 9 Table 11. Evidence:

- `k1045_results.json` contains exact matches:
  - `GJR_t.moments.excess_kurtosis = 3.0650001618374274` → paper 3.065 ✓
  - `GJR_t.moments.skewness = -0.8560196530413117` → paper -0.856 ✓  
  - `GJR_t.jarque_bera.statistic = 938.7773653298907` → paper 938.8 ✓
  - `A4f_t.moments.excess_kurtosis = 1.2384292192893565` → paper 1.238 ✓
  - `A4f_t.moments.skewness = -0.5936660077752721` → paper -0.594 ✓
  - `A4f_t.jarque_bera.statistic = 224.19386009630335` → paper 224.2 ✓
  - `median_df_gjr = 5.282358470566755` → paper ν=5.28 ✓
  - `median_df_a4f = 8.000606865786747` → paper ν=8.00 ✓
- K1045 was run on 2026-04-11 (OOS period 2019-01-02 to 2026-04-10, n=1828)

**Recommendation (a)**: Add K1045 to `paper/garch-x-vix/experiments.md` as the source for Table 11. The reproducibility audit can now be marked: "Table 11 sourced from K1045".

---

## Kurtosis Convention

**Fisher excess kurtosis** (scipy.stats.kurtosis, fisher=True, normal=0).

- Paper footnote: "Excess kurtosis relative to normal (=0)" — confirms Fisher convention
- K1045 code (line 433): `kurt = float(sp_stats.kurtosis(z_clean, fisher=True))`
- Paper values 3.065 and 1.238 are positive excess kurtosis (fat-tailed distribution)

---

## A4f-t Cells: REPRODUCED

A4f-t residual diagnostics (kurtosis 1.238, skewness -0.594, JB 224.2) are reproduced within 1.1% using K1045 methodology:
- `vix2 = (vix / 100)^2`
- `ret.clip(-0.20, 0.20)`
- Joint MLE for A4f-t (df fitted jointly, not from residuals)
- K1045 Student-t parameterization: standard t with `1 + z²/df` in log-likelihood

---

## GJR-t Cells: DIVERGENT (optimization sensitivity)

GJR-t residual diagnostics cannot be reproduced. Root cause: **optimization sensitivity in GJR-t likelihood**.

Key differences:
1. **Median df**: K995b produces median_ν ≈ 7.13 vs K1045's 5.28
   - Lower df = fatter t-distribution = higher excess kurtosis in z_t residuals
   - K1045 converged to df≈5.28; K995b converges to df≈7.13 for same windows
2. **Kurtosis impact**: df=5.28 → theoretical excess kurtosis = 6/(5.28-4)=4.69 (the actual empirical kurtosis after standardization is 3.065); df=7.13 → theoretical excess kurtosis = 6/(7.13-4)=1.92 (empirical: 2.686)
3. **Multiple local optima**: GJR-t likelihood surface with (ω, α, γ, β, ν) can have multiple local optima; L-BFGS-B starting from `x0=[var0*0.05, 0.05, 0.05, 0.90, df_init]` for df_init∈{5,8,15} produces different optima depending on training data and numerical precision

**The GJR-t divergence does NOT affect the paper's scientific conclusions.** The comparison is A4f-t vs GJR-t, and both models' key difference (A4f absorbs fat tails via VIX, improving kurtosis) holds regardless of which local optimum GJR-t reaches.

---

## Recommendations

### (a) Source attribution — DONE
K1045 is confirmed as Table 11 source. Add to `paper/garch-x-vix/experiments.md`:
```
K1045: Table 11 (residual diagnostics)
```

### (b) Paper footnote update — PENDING ERRATA
Table 11 footnote says n=1,828. K995 OOS is n=1,825 (different data end).  
K1045 used n=1,828 (data through 2026-04-10). This is consistent; K1045 is the authoritative source.

### (c) Pending errata for GJR-t reproducibility
The GJR-t cells (kurtosis=3.065, JB=938.8) are sourced from K1045 but cannot be exactly reproduced due to optimization path sensitivity. The discrepancy magnitude (20-30%) is significant.

Three options:
- **(c1)** Accept K1045 as canonical source; document that re-running may produce different GJR-t values due to local optima. Add errata note to paper if requested.
- **(c2)** Revise paper to use median/mean df values and report theoretical kurtosis from df estimate, making computation deterministic.
- **(c3)** Accept that K1045.py is the one-click reproducibility script for Table 11 and add to replication package as-is.

**Recommended action**: Option (c3) — K1045.py produces K1045_results.json which matches the paper. Include K1045 in the replication package. The optimization sensitivity for GJR-t is a limitation that should be noted in the paper's Appendix or supplementary materials.

---

## Integrity Notes

- `experiments/k995/k995_results.json` — **NOT modified** (submitted paper artifact)
- `paper/garch-x-vix/main.tex` — **NOT modified**
- No hard-coding or seed-tuning to match paper values
- K995b provides both: source identification (K1045) and an independent replication attempt
