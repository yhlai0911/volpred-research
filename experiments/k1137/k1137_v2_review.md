---
# K1137-v2 Code Review (post regime window fix)

**Reviewer**: code-reviewer subagent (Codex CLI fallback; K1259 protocol)
**Date**: 2026-05-13
**Verdict**: PASS

---

## Fix 1: Regime Window Off-by-One (Blocking Issue from v1)

**Status: CORRECTLY FIXED.**

`build_rolling_vix_regimes()` at lines 518-540:

```python
vix_lag1 = vix_series.shift(1)    # lag-1 for regime label
v_lag1 = vix_lag1.values          # VIX[t-1] for comparison
v_orig = vix_series.values        # unshifted for quantile window
...
past = v_orig[i - window:i]       # gives VIX[t-252..t-1] ✓
...
if v_lag1[i] <= q33:              # compares VIX[t-1] vs percentiles ✓
```

The fix correctly separates the two uses:
- `v_orig[i-window:i]`: unshifted, so window covers VIX[t-252..t-1] as designed
- Regime label uses `v_lag1[i]` = VIX[t-1]

v1 bug (both drawn from `vix_lag1.values`, double-shifting window to VIX[t-253..t-2]) is eliminated. Docstring at lines 511-516 accurately documents the correction.

---

## Fix 2: 10% Coverage Guard (Non-blocking → now hard abort)

**Status: CORRECTLY FIXED.**

Lines 701-713: `if not coverage_ok: ... continue` — hard `continue`, not warning-only. Asset is recorded in `all_results` with error key for auditability, then skipped. Consistent with spec and K1128/K1130/K1131 enforcement.

---

## Standard Methodology Checks

| Check | Lines | Result |
|---|---|---|
| HAR regressors all .shift(1) | 398-406 | PASS |
| HAR forecast uses strictly pre-t_abs data | 657-658 | PASS |
| DM-HLN Bartlett HAC + HLN correction | 460-486 | PASS |
| BH-FDR across full 54-cell pool | 857-870 | PASS |
| benjamini_hochberg() step-down correct | 489-499 | PASS |
| Training data strictly pre-t_abs | 601-605 | PASS |
| Underpowered cells (n<30) sentinel-skipped | 780-790 | PASS |
| np.random.seed(42) | 80 | PASS |
| M3 monthly VIX lag uses prior-month only | 305, 647 | PASS |
| QLIKE = ratio - log(ratio) - 1 (Patton 2011) | 446-453 | PASS |

---

## Non-blocking Issues

- **M4 vs M1 Parkinson target asymmetry**: M1 trained on r² (close²), M4 on Parkinson. Documented in code (lines 732-748) and README Limitations. +20-52% QLIKE margin large enough to not reverse verdict.
- **yfinance data dependency**: Unchanged from v1. Acceptable for this experiment scope.
- **M3 state update uses current-bar return (line 654)**: Correct GARCH recursion — forecast for period t already stored before state update. Not lookahead.

---

## Verdict Justification

Both v1 blocking issues resolved:
1. Regime window: `v_orig[i-window:i]` now correctly gives VIX[t-252..t-1]
2. Coverage guard: hard `continue` abort, not warning-only

All methodology checks pass. No new blocking issues. K1137 v2 corrected results (17/54 PASS, verdict C_HAR_REGIME_INVARIANT) faithfully implement the rolling ex-ante VIX tertile design.

**Cleared for knowledge.json propagation.**
