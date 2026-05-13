---
# K1138-v2 Code Review (post BH-FDR dual-gate fix)

**Reviewer**: code-reviewer subagent (Codex CLI fallback; K1259 protocol)
**Date**: 2026-05-13
**Verdict**: PASS

---

## Fix: BH-FDR Dual-Gate at Asset/Model Level (Blocking Issue from v1)

**Status: FULLY FIXED.**

v1 blocking defect used `max_t > 2.0` alone for asset/model summaries. v2 lines 843 and 853:

```python
# Line 843 (asset-level):
asset_pass = any(c['DM_HLN_t'] > 2.0 and c['DM_HLN_p_BH'] < 0.05 for c in asset_cells)

# Line 853 (model-level):
model_pass = any(c['DM_HLN_t'] > 2.0 and c['DM_HLN_p_BH'] < 0.05 for c in model_cells)
```

Both now enforce the dual criterion identically to the 9-cell gate at line 828. Comment block lines 836-838 documents the reasoning. Fix is complete and internally consistent.

---

## IWM Classification Verification

From k1138_results.json:
- `IWM_HAR-RV-X`: DM_HLN_t=2.0636, DM_HLN_p_BH=0.07065 → fails BH gate (p_BH > 0.05)
- `IWM_GARCH-MIDAS-X`: t=1.010, p_BH=0.402 → fails both
- `IWM_GAS-t`: t=−0.488, p_BH=0.704 → fails both

Result: `asset_null_map["IWM"] = "NULL"` ✓ (correctly reclassified from v1 PASS)

SPY and QQQ:
- `SPY_HAR-RV-X`: t=4.185, p_BH=0.000137 → PASS ✓
- `QQQ_HAR-RV-X`: t=4.219, p_BH=0.000137 → PASS ✓

---

## Standard Methodology Checks

| Check | Lines | Result |
|---|---|---|
| HAR regressors all .shift(1) | 397-403 | PASS |
| HAR forecast uses strictly pre-t_abs data | 426-432 | PASS |
| OOS split chronological | 527 | PASS |
| Refits use training data [:t_abs] only | 547-549 | PASS |
| DM-HLN Bartlett HAC + HLN correction | 457-477 | PASS |
| BH-FDR across full 9-cell pool before threshold | 804-806 | PASS |
| benjamini_hochberg() step-down correct | 482-493 | PASS |
| MIDAS monthly VIX lag uses prior-month only | 294-307 | PASS |
| np.random.seed(42) | 73 | PASS |
| Per-cell 9-cell gate unchanged from v1 | 828 | PASS |

---

## Non-blocking Issues

- **Timestamp in results JSON** (line 998): `"timestamp": "2026-04-17T05:18:16..."`. v2 correction date is recorded in `summary.v2_correction.correction_date = "2026-05-13"`. Minor provenance ambiguity; does not affect statistical results.
- **MIDAS state update uses current-bar return** (line 609): Correct GARCH recursion (innovation at t used to forecast t+1). Not lookahead.
- **HAR forecast VIX lag alignment**: `vix.iloc[:t_abs].iloc[-1]` = VIX[t-1], matching `.shift(1)` in fitting. Consistent. Confirmed correct.

---

## Verdict Justification

v1 blocking defect fully resolved. All three levels of the significance hierarchy (per-cell line 828, per-asset line 843, per-model line 853) now enforce identical dual criterion `DM_HLN_t > 2.0 AND DM_HLN_p_BH < 0.05`.

All standard methodology checks pass. IWM correctly NULL (p_BH=0.071 fails FDR gate). SPY and QQQ correctly PASS (p_BH=0.000137 via HAR-RV-X). Overall verdict MIXED, pass_count=2/9 consistent with per-cell data.

**Cleared for knowledge.json propagation.**
