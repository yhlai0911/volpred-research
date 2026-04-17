# Paper 6 — Undocumented K Additions for experiments.md

**Date**: 2026-04-17
**Source**: nosource_rescan_report.md (2 UNDOCUMENTED_K identified)

These entries should be added to `paper/prg-periodic-garch/experiments.md` to complete the Table → Experiment mapping.

---

## 1. K874c — Table 2 PRG vs Separate DM Column Source

**Resolves**: DIV-6 (TAIFEX DM PRG vs Separate = -4.07)

**Add to Core Experiments table**:
Already listed as K874c (Periodic Realized GARCH base). **Update contribution description** to include:
> "Original PRG estimation; also source for Table 2 PRG-vs-Separate DM column (PRG_Extended_vs_Separate = -4.07)"

**Add to Table → Experiment Mapping**:
Update Table 2 row to:
| Table 2 | Out-of-sample QLIKE and DM tests across six markets | K874d (TAIFEX QLIKE, Spearman, PRG vs GJR, PRG vs HAR), **K874c (TAIFEX PRG vs Separate DM=-4.07)**, K880 (SPY), K881 (QQQ/GLD/EEM), K886 (0050.TW) |

**Evidence**:
- K874c `dm_tests.PRG_Extended_vs_Separate_GARCH.t_stat = -4.0657` → paper reports -4.07 (rtol=0.001)
- K874c `dm_tests.PRG_Basic_vs_Separate_GARCH.t_stat = -4.1482` (alternative if paper uses PRG_Basic comparison)
- K874c path: `experiments/k874c/k874c_results.json`

---

## 2. K874e — Table 2 MCS Column Source

**Resolves**: NOTE-1 (TAIFEX MCS "PRG only" at 10% level)

**Add to Core Experiments table**:
Already listed as K874e (Full Model Comparison). **Update contribution description** to include:
> "Comprehensive 5-model horse race (PRG vs HAR/RV-GARCH/EGARCH/GJR); MCS source for Table 2 (surviving: PRG_Basic + PRG_Extended only, GJR p=0.0, HAR p=0.0 eliminated at α=0.1)"

**Add to Table → Experiment Mapping**:
Update Table 2 row to include K874e as MCS source:
| Table 2 | Out-of-sample QLIKE and DM tests across six markets | K874d (TAIFEX QLIKE/DM/Spearman), K874c (PRG vs Separate DM), **K874e (MCS)**, K880 (SPY), K881 (QQQ/GLD/EEM), K886 (0050.TW) |

**Evidence**:
- K874e `layer2_mcs.superior_set = ['PRG Basic', 'PRG Extended']`
- K874e `layer2_mcs.eliminated_pvalues = {'GJR-GARCH': 0.0, 'HAR(RV_total)': 0.0, 'PRG Basic': 0.201}`
- K874e `layer2_mcs.alpha = 0.1, B = 1000, block_size = 22, loss_function = 'QLIKE'`
- K874e path: `experiments/k874e/k874e_results.json`

---

## 3. DIV-7 Correction Note

**DIV-7 is NOT a no-source issue** — it was an audit field-name error in the original diff_report.

The original audit found K874d `GJR spearman = 0.537` and concluded 0.726 was unsourced.
The correct field is `K874d model_results["PRG Extended"]["spearman_fullday"] = 0.72650` which matches 0.726.

**No action needed** for experiments.md — K874d is already documented. Recommend noting in the diff_report errata that DIV-7 is RESOLVED.

---

## 4. K880 vs K880v2 experiments.md Note

**For future experiments.md maintenance**, add the following note under K880v2:

> **K880v2 methodology note**: K880v2 uses `h_overnight_t` (the forecast) as input to `h_intraday_t`, instead of K880's `r2_overnight[t]` (realized same-day). The sequential-timing interpretation matters: if the forecast horizon is "at t-1 close for full day t", K880v2 is correct (lookahead-free). If the interpretation is "at market open for the intraday period only", K880 may be valid. Paper must clarify in Eq. 3-4 and the methodology section. The QLIKE performance gap (0.748 → 0.864, +15.5%) strongly favors the K880v2 correction being needed.

---

## Summary of Additions Required

| Action | File | Priority |
|--------|------|---------|
| Add K874c as Table 2 PRG vs Sep DM source | experiments.md | HIGH |
| Add K874e as Table 2 MCS source | experiments.md | HIGH |
| Note DIV-7 resolved in diff_report | diff_report.md (or errata note) | MEDIUM |
| Add K880/K880v2 methodology clarification note | experiments.md | HIGH (BLOCKER) |
