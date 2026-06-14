# Codex Review: K1333

**Reviewer**: Codex CLI (gpt-5.4, ChatGPT auth) — primary path
**Date**: 2026-06-14
**Verdict**: CONDITIONAL_PASS

## Reasons

1. **Lookahead bias: PASS** — All predictors carry an explicit `.shift(1)`
   (`rv_short_lag1`, `rv_long_lag1`, `VIX_lag1`, `r_lag1`); `jump_proxy` is
   built from `r.shift(1)` and `rv_long.shift(1)` and is not double-shifted.
   No same-day signal × same-day target observed.

2. **OOS split boundary: PASS** — `TRAIN_END=2020-01-01`,
   `VAL_END=2024-01-01` with `np.searchsorted`; effective test first date
   `2024-01-02`. Expanding fit at row `i` uses `[:i]`, excluding the current
   target.

3. **AR(1) baseline lag: PASS** — Level baseline regresses `delta_vix_t` on
   `delta_vix.shift(1)` then adds `VIX_{t-1}`; abs baseline regresses
   `|dVIX|_t` on `|dVIX|_{t-1}`. Same `t-1 -> t` convention as the model.

4. **Seed / bootstrap: PASS** — `SEED=42`,
   `np.random.default_rng(seed)`; paired stationary bootstrap resamples the
   loss differential `se_model - se_ar1` with `B=2000`, `block_len=10`,
   preserving the matched-pair structure.

5. **DM test: CONDITIONAL** — `dm_test` provides HAC (Newey-West) variance
   with student-t df=n-1. This is **HAC-DM**, NOT
   Harvey-Leybourne-Newbold finite-sample adjusted. The original code
   comment was corrected to drop the "HLN-adjusted" claim.

6. **Verdict aggregation: CONDITIONAL → FIXED** — Initial script flagged
   `PASS` whenever any of 4 (target, spec) cells beat AR(1) at p<0.05. This
   is data-snooping across 4 tests. Logic was updated to a three-tier rule:
   `PASS` requires Bonferroni-survival (p < 0.0125); `CONDITIONAL_PASS`
   covers unadjusted p<0.05; otherwise `NULL`. Final reported verdict is
   `CONDITIONAL_PASS` — modest positive OOS evidence that does not survive
   multiple-testing correction.

7. **Artifact completeness: FIXED** — `README.md` added per experiment
   triplet rule.

## Final conclusion

CONDITIONAL_PASS. Core lag handling, OOS split, AR(1) baseline, seed, and
bootstrap implementations are clean. Reported as weak positive evidence
(two cells at unadjusted p≈0.041; none survive Bonferroni) — NOT a strong
PASS. Safe to write knowledge.json with `verdict=CONDITIONAL_PASS` and
`reviewer=Codex review (primary path)`.
