# K1141 — Paper 4 §4 Channel-Specific Table + Cover Figure

**Status**: COMPLETE  
**Date**: 2026-04-17  
**Author**: Claude (worktree agent, read-only on shared state)  
**Purpose**: Preparation assets for Paper 4 (`paper/vix-sufficiency/main_v2.tex`) body rewrite — channel-specific §4 claims

---

## Overview

Paper 4 narrative has pivoted to "channel-specific universal claims" supported by 9 experiments integrated on 2026-04-17. This experiment produces:

1. `tables/channel_x_asset_3x4.tex` — LaTeX booktabs table (`\input{}`-ready)
2. `tables/channel_x_asset_3x4.csv` — raw data for reproducibility
3. `tables/table_source_data.json` — per-cell K mapping + DM t + evidence path
4. `figures/paper4_cover_fig.png` (300 dpi) + `figures/paper4_cover_fig.pdf` (vector)
5. `figures/paper4_cover_fig.py` — reproducible figure generator (reads JSONs, no hardcodes)

**main_v2.tex is completely untouched.** These are snippet/asset files only.

---

## 3×4 Table Summary

| Channel | Equity | Commodity | Bond | FX |
|---|---|---|---|---|
| **Ch. 1** HAR+VIX vs GJR | **PASS** ($\bar{t}=+3.49$) | **PASS\*** ($\bar{t}=+8.13$) | **PASS** ($t_\max=+11.01$) | — |
| **Ch. 2** MIDAS-X vs GJR | **NULL** ($t_\max=+1.36$) | **NULL** ($t_\max=+1.23$) | **NULL** ($t_\max=+0.51$) | — |
| **Ch. 3** GAS-t vs GJR | **HARM** ($t_\min=-3.27$) | **NULL/PASS†** ($t_\max=+1.03$) | **PASS** ($t_\max=+3.18$) | — |

\* PASS\*: HAR structure beats GJR (PASS); VIX marginal value is NULL in K1136 Fair Test 2  
† NULL/PASS†: Symmetric GAS-t NULL (K1129); skew-t GAS VaR/ES PASS but QLIKE NULL (K1135 Verdict B)

---

## Per-Cell K Mapping and DM t Source

### Channel 1: HAR-RV-X vs GJR-GARCH (HAR+VIX regime-invariant)

| Cell | DM t (repr.) | Source K | JSON path |
|---|---|---|---|
| Equity (SPY) | +4.185 | K1138 | `k1138_results.json → nine_cell_analysis.cell_results.SPY_HAR-RV-X.DM_HLN_t` |
| Equity (QQQ) | +4.219 | K1138 | `k1138_results.json → nine_cell_analysis.cell_results.QQQ_HAR-RV-X.DM_HLN_t` |
| Equity (IWM) | +2.064 | K1138 | `k1138_results.json → nine_cell_analysis.cell_results.IWM_HAR-RV-X.DM_HLN_t` |
| Equity mean | +3.489 | K1138 | mean(SPY, QQQ, IWM) |
| Equity regime | QQQ/IWM all-3-PASS | K1137 | `k1137_results.json → channel_analysis.channel_1_HAR_equity` |
| Commodity (USO) | +10.610 (low regime) | K1137 | `k1137_results.json → pass_cells_BH[ticker=USO, model=M4_HAR_RV_X, regime=low].DM_HLN_t` |
| Commodity (GLD) | +5.647 (low regime) | K1137 | `k1137_results.json → pass_cells_BH[ticker=GLD, model=M4_HAR_RV_X, regime=low].DM_HLN_t` |
| Commodity mean | +8.128 | K1137 | mean(USO_low, GLD_low) |
| Commodity VIX marginal | NULL | K1136 | `k1136_results.json → summary.fair_test_2_vix_in_har_sig_count = 0` |
| Bond (TLT) low | +11.013 | K1137 | `k1137_results.json → pass_cells_BH[ticker=TLT, model=M4_HAR_RV_X, regime=low].DM_HLN_t` |
| Bond (TLT) mid | +8.619 | K1137 | `k1137_results.json → pass_cells_BH[ticker=TLT, model=M4_HAR_RV_X, regime=mid].DM_HLN_t` |
| Bond (TLT) high | +7.345 | K1137 | `k1137_results.json → pass_cells_BH[ticker=TLT, model=M4_HAR_RV_X, regime=high].DM_HLN_t` |

### Channel 2: GARCH-MIDAS-X vs GJR-GARCH (universal null)

| Cell | DM t (repr.) | Source K | JSON path |
|---|---|---|---|
| Equity (SPY) | +1.356 | K1138 | `k1138_results.json → nine_cell_analysis.cell_results.SPY_GARCH-MIDAS-X.DM_HLN_t` |
| Equity (QQQ) | −0.197 | K1138 | `k1138_results.json → nine_cell_analysis.cell_results.QQQ_GARCH-MIDAS-X.DM_HLN_t` |
| Equity (IWM) | +1.010 | K1138 | `k1138_results.json → nine_cell_analysis.cell_results.IWM_GARCH-MIDAS-X.DM_HLN_t` |
| Commodity (USO) | +1.234 | K1136 | `k1136_results.json → per_asset_results.USO.per_target.r2_close.dm_tests.M3_GARCH_MIDAS_X_vs_M1.DM_HLN_t` |
| Commodity (GLD) | +0.944 | K1136 | `k1136_results.json → per_asset_results.GLD.per_target.r2_close.dm_tests.M3_GARCH_MIDAS_X_vs_M1.DM_HLN_t` |
| Commodity (UNG) | +0.620 | K1136 | `k1136_results.json → per_asset_results.UNG.per_target.r2_close.dm_tests.M3_GARCH_MIDAS_X_vs_M1.DM_HLN_t` |
| Bond (TLT) best | +0.514 | K1137 | `k1137_results.json → channel_analysis.channel_2_MIDAS_conditional.TLT.max_DM_t` |
| Regime-conditional | 0/6 PASS | K1137 | `k1137_results.json → summary.n_midas_conditional_pass = 0` |

### Channel 3: GAS-t vs GJR-GARCH (asset-class-specific)

| Cell | DM t (repr.) | Source K | JSON path |
|---|---|---|---|
| Equity (SPY sym-GAS) | −3.267 (HARM) | K1138 | `k1138_results.json → nine_cell_analysis.cell_results.SPY_GAS-t.DM_HLN_t` |
| Equity (QQQ sym-GAS) | −2.806 (HARM) | K1138 | `k1138_results.json → nine_cell_analysis.cell_results.QQQ_GAS-t.DM_HLN_t` |
| Equity (SPY skew-t) | −3.267 (HARM) | K1143 | `k1143_results.json → per_asset_results.SPY.dm_vs_BASE_GJR_N.M1_GAS_t_sym.DM_HLN_t` |
| Equity skew-t variants | all HARM | K1143 | `k1143_results.json → scenario_analysis.scenario = "D: All variants still HARM"` |
| Commodity (USO sym) | +1.033 (NULL) | K1129 | `k1129_results.json → results.USO.dm_tests.M3_GAS_t_vs_M1.DM_HLN_t` |
| Commodity (GLD sym) | −0.761 (NULL) | K1129 | `k1129_results.json → results.GLD.dm_tests.M3_GAS_t_vs_M1.DM_HLN_t` |
| Commodity (UNG sym) | +0.186 (NULL) | K1129 | `k1129_results.json → results.UNG.dm_tests.M3_GAS_t_vs_M1.DM_HLN_t` |
| Commodity skew-t | VaR/ES PASS, QLIKE NULL | K1135 | `k1135_results.json → verdict.scenario = "B"` |
| Bond (TLT) low | +2.527 (PASS) | K1137 | `k1137_results.json → channel_analysis.channel_3_GAS_rescue.TLT.low.DM_HLN_t` |
| Bond (TLT) high | +3.178 (PASS) | K1137 | `k1137_results.json → channel_analysis.channel_3_GAS_rescue.TLT.high.DM_HLN_t` |

---

## Cover Figure

**Layout chosen: A (Heatmap 3×4)**  
Rationale: clearest way to show the asymmetric pattern — Channel 1 all green (PASS), Channel 2 all near-zero, Channel 3 red-for-equity/green-for-bond.

- Color: RdYlGn diverging, TwoSlopeNorm (center=0, vmin=-4, vmax=+12)
- DM t displayed in each cell; verdict label + K-reference
- 300 dpi PNG + vector PDF

---

## Divergence Report: K1141 vs main_v2.tex

The current `main_v2.tex` (953 lines) does **not yet contain** channel-specific §4 content. The paper's abstract and conclusion describe the 11-family horse race on SPY data (1993–2026). The channel-specific framework (Channel 1/2/3 × Equity/Commodity/Bond) is the **new narrative** prepared in this experiment for the forthcoming body rewrite.

**No numerical divergences detected** because the specific DM t values produced here (for cross-asset HAR/MIDAS/GAS experiments) are not yet written into main_v2.tex. The only relevant number in main_v2.tex is:

> "Our preliminary HAR-RV results show a 41.8% QLIKE improvement" (§7.1 frontier)

This refers to a preliminary HAR-RV on 5-minute intraday data, distinct from the daily HAR-RV-X cross-asset results here. **No conflict.**

**Decision: (b) — main_v2.tex will be updated during the body rewrite** to incorporate these channel-specific results. This is expected, not an error.

---

## Files

```
experiments/k1141/
├── README.md                         (this file)
├── tables/
│   ├── channel_x_asset_3x4.tex       (LaTeX booktabs table, \input{}-ready)
│   ├── channel_x_asset_3x4.csv       (raw data, CSV)
│   └── table_source_data.json        (per-cell K mapping + DM t + source paths)
└── figures/
    ├── paper4_cover_fig.py           (generator script — reads JSONs, no hardcodes)
    ├── paper4_cover_fig.png          (300 dpi, heatmap)
    └── paper4_cover_fig.pdf          (vector, submission-ready)
```

No experiment script (k1141.py) — this task is purely assembly/visualization of existing results, not a new statistical experiment.

---

## Success Criteria Checklist

- [x] 3×4 table .tex with booktabs, threeparttable footnotes, symbol legend
- [x] 3×4 table .csv for raw data reproducibility
- [x] table_source_data.json with per-cell K mapping and DM t source paths
- [x] Cover figure PNG (300 dpi) + PDF (vector)
- [x] Generator script reads JSONs directly; no hardcoded DM t values
- [x] README documents per-cell K mapping
- [x] README reports divergence status vs main_v2.tex (none — new narrative)
- [x] main_v2.tex completely untouched
- [x] No shared state modified
