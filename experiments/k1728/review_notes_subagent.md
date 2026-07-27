# K1728 — independent adversarial code review (subagent fallback)

- **Reviewer**: `general-purpose` code-review subagent (Claude Opus, high reasoning effort),
  fresh context, no access to the author's reasoning.
- **Why not Codex primary path**: Codex CLI (`gpt-5.6-sol`) returned
  `You've hit your usage limit … try again at Aug 2nd, 2026` on 2026-07-27, i.e. the ChatGPT
  account credits were exhausted. Per `.claude/rules/experiments.md`, the sanctioned fallback
  when Codex cannot be recovered is an independent fresh-context `code-reviewer` subagent.
  **Note (K1259 rule)**: *subagent-fallback PASS ≠ primary-path Codex PASS.* The receiving
  main thread should, if it wants full closure parity, re-verify with primary-path Codex once
  credits return (2026-08-02) before writing `knowledge.json`. Bar for this artifact: PASS.
- **Reviewed at**: 2026-07-27T23:01:01+08:00
- **Method**: read all three claim-surface files in full plus `fetch_data.py`,
  `data/provenance.json`, and canonical `src/volpred/stats/model_evaluation.py`; then
  **independently reproduced the pipeline** and ran targeted lookahead probes without
  modifying any file.

## Round 1 — findings

**Lookahead: CLEAN (explicitly probed).**
- HAR terms are `y.shift(1)`, `y.rolling(5).mean().shift(1)`, `y.rolling(22).mean().shift(1)`;
  exogenous predictors go through bounded-ffill then `.shift(1)`; day-t regressors are dated
  ≤ previous trading day.
- Training slice `slice(lo, i)` excludes origin `i`; manual recompute with rows `[0,i)`
  matched the pipeline exactly, and including row `i` changed the value — origin is excluded.
- **Shift is load-bearing**: removing it inflates VIX incremental R² from **+8.03% → +15.08%**,
  proving the lag is applied and material.
- **ffill cap honest**: capped news last-valid → sample ends **2023-12-04**; removing the cap
  fabricates a frozen-constant news column through 2026-07-27. `FFILL_LIMIT=5` works.
- Regime thresholds computed from pre-OOS block only; regime variable already lagged.

**Baseline lag parity: CORRECT** — `dropna` on the union of all spec columns ⇒ HAR baseline
evaluated on the identical intersection rows / OOS origins / target as every augmented spec.

**Nested-test correctness: CORRECT** — CW called small=HAR, large=aug, actual=log-RV_t;
Campbell-Thompson `1 − SSE_large/SSE_small`; verdict uses only `(r2>0) and (CW p<0.05)`; DM
never enters the verdict.

**QLIKE: mechanically correct** — canonical `qlike(actual, predicted)`; `var_pred =
exp(fc + 0.5·s2)`; `s2` from pre-OOS train residuals only.

**Number integrity** — README headline table, regime cells, robustness, descriptives and corr
matrix all match `k1728_results.json` exactly (~30 values spot-checked).

**Non-blocking observations raised:**
1. "robust across loss functions / MSE-QLIKE losses" overstated: variance-level QLIKE point
   estimates and the diagnostic `dm_qlike` mildly *favor* the free specs (HAR+EPU one-sided
   QLIKE-DM ≈ 0.045); plausibly a per-spec `s2` bias-correction level-shift artifact. Soften.
2. Regime bullet mixed the `fixed_VIX20` and `pre_oos_70pct` cuts in adjacent sentences.

Round-1 verdict: **CONDITIONAL_PASS** (no blocking defects).

## Round 2 — confirmation on final bytes

Author applied both fixes (README rescoped to the primary criterion; dedicated "QLIKE caveat"
bullet; `methodology_notes.qlike_direction_caveat` added to results.json; regime cuts now
labelled `VIX>20 n=737`, `pre-OOS 70th-pct EPU n=713`, `pre-OOS 70th-pct VIX 13.5%/6.0%`).
Reviewer re-read the final bytes, confirmed the edits are documentation-only, every load-bearing
number remains byte-consistent, nothing regressed, both observations resolved.

**FINAL VERDICT: PASS. Blocking defects: none. Remaining observations: none.**

The primary-criterion NULL for free attention/sentiment and the VIX-control PASS both stand;
the lookahead audit is clean.
