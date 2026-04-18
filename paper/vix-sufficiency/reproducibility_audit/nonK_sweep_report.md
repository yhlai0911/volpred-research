# Paper 7 (vix-sufficiency) — Non-K Forensic Sweep Report

**Date**: 2026-04-17
**Agent**: Non-K Forensic Sweep (worktree agent-a30d366f)
**Task**: Map non-K experiment folders to Paper 7 untraced/no-source items

---

## Paper 7 STILL_NO_SOURCE Summary

From `diff_report.md`, Paper 7 (vix-sufficiency) has:
- 3 untraced/no-source items: DIV-6 (Table 10 MDD reduction 8.2 pp), DIV-7 (36 null results count), DIV-8 (K1138 mixed result not in body)
- DIV-1 (Abstract 41.8% QLIKE improvement — direction error)
- DIV-2 (CV=0.33 vs actual 0.37)
- DIV-3 (BH 50/50 Sharpe=0.947 vs K731 0.827 — period mismatch)
- DIV-4 (Table 6 era-specific incremental R² — 5 cells 10–186× off)

Note: The task brief assigns vix-sufficiency to Paper 4 (per task numbering Paper 4 = vix-sufficiency). The diff_report confirms Paper 7 in README (titled "Paper 4 (Paper 7)").

---

## Non-K Folders Inspected (Paper 7 Assigned)

| Folder | Has Real Data? | Content Summary |
|--------|---------------|-----------------|
| `vix_sufficiency_boundary` | NO — planning stub | Status=planning, metrics={}, data_sources=[]. Created 2026-04-16. |
| `vix_term_structure_vol_pred` | YES — real data | VIX term structure vol prediction (OOS 2021–2025, n_windows_oos=56). Models: GARCH-only, VIX-only, VIX+Term Structure. Conclusion: "VIX term structure does NOT add predictive power beyond VIX alone." DM: VIX vs VIX+TS t=-2.208, p=0.027. |
| `vix_term_structure_vol_pred_v2` | YES — real data | v2 robustness. VIX-only OOS R²=0.236. VIX+ratio R²=0.352 (raw product) but OLS: VIX+ratio R²=0.139 (overcorrects). Conclusion: Classic overfitting pattern. |
| `vix_term_structure_trading` | NO — planning stub | Status=planning, metrics={}, data_sources=[]. Created 2026-04-16. |
| `vix_zone_cross_period_validation` | YES — real data | Rule 16 (VIX-zone enhancement) cross-period validation. 3 periods (2014–2018, 2019–2022, 2023–2026). Enhanced Hybrid VT wins all 3 periods (verdict: "PASS — GENUINE improvement"). Avg delta_sharpe=0.195. |
| `vix_death_zone_enhanced` | YES — real data | VIX death zone (15–18) enhancement test. Standard Hybrid VT Sharpe=1.082 vs Enhanced=0.877 (NEGATIVE: death zone reduction HURTS). Best config: Std-10% (Sharpe=1.017). |
| `vrp_regime_decomposition` | NO — planning stub | Status=planning, metrics={}, data_sources=[]. Created 2026-04-16. |
| `rate_hike_vt_experiment` | NO — planning stub | Status=planning, metrics={}, data_sources=[]. Created 2026-04-16. |

---

## Cross-Match: Non-K Folders vs No-Source Numbers

### DIV-6: Table 10 MDD reduction 12/VIX = -8.2 pp

Table 10 is about insurance/MDD metrics for the 12/VIX strategy. The VIX-zone and VIX term structure non-K folders do not compute MDD reduction in the format required for Table 10. K738 (in paper's experiment set) covers cross-asset MDD reduction with average 12.3 pp. The `vix_sufficiency_boundary` stub would be the natural place but is empty.

**Verdict: UNRELATED** for all active non-K folders; `vix_sufficiency_boundary` is a stub.

### DIV-7: "36 null results" count

This is a narrative claim in the paper's conclusion. No non-K experiment would resolve a counting claim. `vrp_regime_decomposition` is a stub.

**Verdict: UNRELATED** to all non-K folders.

### VIX Term Structure Content

`vix_term_structure_vol_pred` provides strong null results: term structure does NOT add predictive power (DM t=-2.208 for VIX vs VIX+TS at p=0.027, FAVORING VIX alone). `vix_term_structure_vol_pred_v2` confirms (0/7 OLS configurations beat VIX-only in OOS R²).

**Potential match**: Paper 7 (vix-sufficiency) could cite these as additional confirmation of VIX sufficiency — specifically that even term structure slope fails as an incremental predictor. These experiments directly support the paper's core thesis but are **not currently in Paper 7's registered experiment list**.

**Verdict: MATCH — NONK_UNDOCUMENTED**: `vix_term_structure_vol_pred` and `vix_term_structure_vol_pred_v2` provide VIX-sufficiency-relevant null results not reflected in Paper 7's experiments.md. DM confirms VIX term structure fails OOS.

### VIX Zone Analysis Content

`vix_zone_cross_period_validation` and `vix_death_zone_enhanced` test VIX-zone-based enhancements to VT. These are trading strategy experiments, not volatility forecasting null results. They are tangentially related to Paper 7 (which is about vol forecasting sufficiency), but the specific numbers (Table 3 BH Sharpe 0.947, DIV items) are not addressed by these experiments.

**Verdict: UNRELATED** to specific STILL_NO_SOURCE items. Could be cited in Paper 7's Section 7 (practical implications) as evidence that VIX-regime switching adds value.

---

## K-Uppercase Relevant Folders

`K1129` (GAS-t Commodity) and `K1053` (VIX Term Structure Slope as Vol Predictor) are Paper 7-adjacent:

**K1053** (experiments/K1053/): VIX Term Structure Slope predictor experiment.
- K1053_results.json exists
- Could provide additional evidence for/against Paper 7's VIX sufficiency thesis

**K1129** (GAS-t Commodity): Confirmed in `diff_report.md` as Paper 7 experiment (K1129 in body integration list but NOT in main_v2.tex yet — stale body).

---

## Summary

| Category | Count |
|----------|-------|
| Non-K folders inspected (Paper 7 assigned) | 8 directly |
| Folders with real data | 4 |
| Folders as planning stubs | 4 |
| **Matches: NONK_UNDOCUMENTED** (support paper but not registered) | **2** |
| No-source items resolved | **0** (DIV-6/7 remain) |
| STILL_NO_SOURCE after sweep | **3** (DIV-6, DIV-7, DIV-8) |

**Key finding**: `vix_term_structure_vol_pred` and `vix_term_structure_vol_pred_v2` contain null results directly supporting Paper 7's VIX-sufficiency thesis, but are NOT registered in Paper 7's experiments.md. These are NONK_UNDOCUMENTED experiments with paper-relevant content.

---

## Action Recommendations

1. **Add `vix_term_structure_vol_pred` and `vix_term_structure_vol_pred_v2` to Paper 7's experiments.md** — they support the "VIX term structure fails" null result narrative (Family 12 or new family).
2. **DIV-6 (Table 10 MDD reduction 8.2 pp)**: Identify if K786 (SPY/GLD 2007–2026) or an unreported experiment is the source. `vix_sufficiency_boundary` stub was created for this purpose but not executed.
3. **DIV-4 (Table 6 incremental R² — 5 cells wrong)**: These are sourced from K752 at different values — fix Table 6 from K752 rather than seeking new non-K source.
4. `rate_hike_vt_experiment` stub may be intended to address Paper 7's rate-hike era analysis (Era 4 in K752) — execute it.
