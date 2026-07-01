# K1600 Codex Code Review

**Reviewer**: Codex CLI (`codex exec`, gpt-5.4), 2026-07-01
**Verdict**: **PASS** — no correctness issue that would make results untrustworthy.

## Review scope
Correctness-only review of `experiments/k1600/k1600.py`:
lookahead / forward-label timing, per-horizon DM + HLN correction, QLIKE
orientation, insanity filter OOS-cleanliness, sqrt(RQ) standardization leak.

## Findings

- **Forward-label / lookahead — CORRECT.** `make_target()` builds `t+1..t+h`;
  `rolling_oos()` uses `train_end = i - h` (exclusive slice), so the last
  training row `j = i-h-1` satisfies `j + h = i-1 < i`. No off-by-one.
- **`beta1Q_significance` — CORRECT.** Drops the last `h` valid rows;
  conservative, not leaky.
- **DM-HLN — CORRECT** per requested formula: HAC lag `h-1`, HLN correction
  `sqrt((n+1-2h+h(h-1)/n)/n)`, `t(n-1)` reference.
- **QLIKE — CORRECT** canonical orientation `actual/predicted` via
  `volpred.stats.model_evaluation.qlike_pointwise`. No inverse-QLIKE.
- **Insanity filter — OOS-CLEAN.** Uses only `y_tr.min/max/mean` from the
  allowed training window; applied identically to HAR/HARQ/HARQ-F → fair.
- **Full-sample `sqrt(RQ)` standardization — NOT a target leak.** Only an
  affine reparameterization of a regressor (base HAR terms also present);
  does not create predictive information leakage or alter forecast rankings.

## Minor caveat (documentation only, not result-validity)
Avoid describing the full-sample `sqrt(RQ)` scaling as "training-only"; it is a
feature-only global affine scaling. The script comment already states it "does
not touch y" and "does not change OOS forecast rank" — consistent with Codex's
assessment. README wording updated accordingly.

## Bug fixed before this review (documented for provenance)
First run produced absurd QLIKE values (up to 1.7e13) driven by a single
level-RV OLS OOS forecast extrapolating negative (floored to 1e-16 → QLIKE
`actual/1e-16` explosion). Fixed with the BPQ (2016) **insanity filter**
(reset out-of-support forecasts to the training-window mean), applied
identically to all models. Post-fix QLIKE values are all in a sane range
(0.28–2.58); Codex reviewed the fixed version.
