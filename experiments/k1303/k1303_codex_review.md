# K1303 Codex Primary-Path Code Review

**Reviewer**: Codex CLI (gpt-5.4, primary path)
**Date**: 2026-05-13
**Task ID**: task-k1303-codex-review-primary
**Experiment**: K1303 — HAR-CJ (BPV Jump Decomposition) vs HAR-RV on TAIFEX TX1

---

## Overall Verdict: FAIL

Codex FAIL — three blocking issues identified. NULL result on TX1 (DM_HLN=-0.91) cannot be signed off as "CJ genuinely adds no value" under this implementation.

---

## Issues Found

### Issue 1: DM-HLN HAC Insufficient (HIGH)
- **Finding**: `dm_hln()` at h=1 uses plain sample variance `((d-mu)^2).mean()` with no Newey-West/HAC autocorrelation correction. Volatility forecast loss differentials typically exhibit serial correlation; this miscalibrates t-stat and p-value.
- **Severity**: HIGH
- **Evidence**: `k1303.py:337`; repo's `src/volpred/stats/model_evaluation.py:83` has a proper HAC version.
- **Fix**: Replace inline DM with HAC-correct `dm_test()` from `src/volpred/stats/model_evaluation.py`, then apply HLN small-sample correction on top.

### Issue 2: No Formal Jump Threshold / BNS Significance Filter (HIGH)
- **Finding**: Jump identification uses only `J_t = max(RV_t - BPV_t, 0)` with no formal z-test. This treats all BPV sampling noise and microstructure noise as jumps, turning jump regressors into sparse noise. The resulting HAR-CJ jump betas (j_d=2224, j_w=4203, j_m=-8416) confirm the J features are very noisy.
- **Severity**: HIGH
- **Evidence**: `k1303.py:90`; `k851_jump_dynamics.py:325` uses a formal BNS z-test + TQ approach.
- **Fix**: Add a formal ABD/BNS significance test version (`HAR-CJ-ABD`): use truncated quarticity (TQ) to compute z-stat; set J>0 only for significantly identified jump days.

### Issue 3: Extra Lag in Feature Alignment — Not Standard HAR-CJ (MEDIUM)
- **Finding**: Features use `rv_lag1 = d["rv"].shift(1)` (X_{t-1}) while target is `Y = log(RV.shift(-1))` = log(RV_{t+1}). This means the model predicts two steps ahead from t-1 features — one extra lag beyond standard HAR-CJ (which uses X_t → Y_{t+1}). The extra lag is particularly damaging to jump signals which decay faster than continuous components.
- **Severity**: MEDIUM
- **Evidence**: `k1303.py:288`, `k1303.py:308`
- **Fix**: If goal is standard next-day HAR-CJ, change to X_t → Y_{t+1} (no .shift(1) on features, target still .shift(-1) on rv). If two-step-ahead is intentional, rename as "two-step-ahead HAR-CJ" and do not compare directly against standard HAR-CJ literature results.

### Issue 4: OOS Boundary Not Target-Date Clean (MEDIUM)
- **Finding**: Train/test split uses feature row index after shift, not target calendar date. The last training label includes the realized RV of the first holdout calendar day. Not major leakage, but boundary definition is not clean.
- **Severity**: MEDIUM
- **Evidence**: `k1303.py:387`
- **Fix**: Build explicit `(feature_end_date, target_date)` index pairs; split on `target_date` to ensure complete train/test separation in calendar time.

### Issue 5: IID Bootstrap for Time-Series CI (LOW)
- **Finding**: `bootstrap_mse_ci()` uses iid resampling (not block/stationary bootstrap). For time-series loss CI this is overly optimistic. Seed=42 is correctly fixed.
- **Severity**: LOW
- **Evidence**: `k1303.py:362`
- **Fix**: Switch to stationary or moving-block bootstrap, or at minimum note "iid bootstrap only" in results.

### Issue 6: BPV Formula Correct (PASS)
- **Finding**: BPV formula `abs_r[1:] * abs_r[:-1]` with `M/(M-1)` bias correction is correct per BNS (2004). No off-by-one errors.
- **Severity**: N/A
- **Evidence**: `k1303.py:74`

---

## Summary

| # | Issue | Severity | Blocks Closure? |
|---|-------|----------|-----------------|
| 1 | DM-HLN missing HAC correction | HIGH | YES |
| 2 | No formal jump threshold (BNS z-test) | HIGH | YES |
| 3 | Extra lag beyond standard HAR-CJ | MEDIUM | YES (reinterpretation needed) |
| 4 | OOS boundary not target-date clean | MEDIUM | Conditional |
| 5 | IID bootstrap for time-series | LOW | No (cosmetic) |
| 6 | BPV formula | PASS | N/A |

---

## NULL Verdict Reinterpretation

The TX1 DM_HLN=-0.91 NULL **cannot** be signed as "CJ adds no incremental value." The more accurate characterization is:

> "Under raw unthresholded jump identification + one-extra-lag feature alignment + HAC-insufficient DM inference, TX1 shows no significant advantage for HAR-CJ. A proper HAR-CJ-ABD version with formal BNS z-test, standard feature alignment, and HAC-DM is required before concluding on the jump channel."

---

## Required Next Steps (for K1303 revision)

1. Implement `HAR-CJ-ABD` with BNS/TQ formal jump test
2. Fix feature alignment to standard X_t → Y_{t+1}
3. Replace DM variance estimator with Newey-West HAC
4. Clean OOS boundary on target calendar date
5. Re-run and re-evaluate NULL vs PASS

---

## Closure Status

`requires_revision` — knowledge.json entry K1303 marked accordingly. Re-run required before closure.
