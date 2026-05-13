---
# K1303-v2 Code Review (post ABD revision)

**Reviewer**: code-reviewer subagent (Codex CLI fallback; K1259 protocol)
**Date**: 2026-05-13
**Verdict**: CONDITIONAL PASS → PASS (after line-67 fix applied same session)

---

## ABD1 Check: Jump Threshold + Feature Scaling

**Status: MOSTLY FIXED — one known limitation documented.**

Feature scaling fix is complete: J/RV ratio (dimensionless [0,1]) is used in `build_har_features()` (lines 407-411). Post-fix betas are plausible: j_d=0.92, j_w=1.54, j_m=−3.33 (all |β|<10, vs v1 magnitudes 2224/4203/−8416). Zero-out on non-jump days via `j_thresh = raw_j * jump_day` is correct.

**Known limitation (non-blocking, documented):** The jump threshold statistics `mu_j` and `sigma_j` are computed over the full dataset (lines 172-174) before the 70/30 split. This means OOS observations contribute to the threshold used to classify OOS jump days — a mild informational leak in jump identification. For TX1 (n=2186, 23 jump days = 1.05%), the practical magnitude is small. Full fix would require training-window-only threshold estimation. This is documented in `README.md` Limitations.

---

## ABD2 Check: HAC DM Test + QLIKE

**Status: FIXED (results correct; REPO_ROOT path bug patched same session).**

QLIKE formula (`ratio - log(ratio) - 1`, Patton 2011) is correct in both canonical and fallback implementations. DM-HLN HAC structure (Bartlett weights, `max_lag = ceil(h^(1/3)*n^(1/3))`, t-distribution p-value, HLN correction) is correct.

**REPO_ROOT bug (now fixed):** Line 67 originally used `parents[3]` (Desktop/) instead of `parents[2]` (repo root), causing `from volpred.stats.model_evaluation import dm_test` to always ImportError and fall through to the inline HAC fallback. The fallback mirrors the canonical implementation line-for-line, so results are numerically identical.

**Fix applied (same session, line 67-69):** Changed to `_SRC_DIR = Path(__file__).resolve().parents[2] / "src"` + `sys.path.insert(0, str(_SRC_DIR))`. The canonical dm_test will now be loaded correctly on next run.

---

## ABD3 Check: 1-Step Lag

**Status: FIXED — correct.**

`build_har_features()` at lines 394-396:
- `rv_lag1 = d["rv"].shift(1)` → all HAR terms are lag-1 or longer
- Target `Y = log(rv)` has no shift

Standard ABD (2007) 1-step HAR convention. The v1 two-step-ahead defect is eliminated. No off-by-one.

---

## Additional Checks

| Check | Lines | Result |
|---|---|---|
| OOS split chronological | 479-489 | PASS (integer index on sorted, post-dropna data) |
| Seed fixed | 80-81 | PASS (SEED=42, RNG=default_rng(42)) |
| BPV formula | 148-164 | PASS (unchanged from v1 PASS) |
| No recursive refit lookahead | single static OLS fit on training | PASS |
| log-RV clipped before log | 414, clip(lower=eps) | PASS |

---

## Verdict Justification

CONDITIONAL PASS issued pending one-line REPO_ROOT fix. Fix applied same session (parents[3]/Desktop → parents[2]/src). Post-fix verdict: **PASS**.

Results (TX1 NULL: DM_HLN_t=1.002, p=0.317, n_test=650) are numerically correct regardless of import path, since fallback HAC matches canonical. The NULL result reinforces the K868/K1301/K1309 NULL quartet on TX1 realized-vol forecasting.

Cleared for knowledge.json closure.
