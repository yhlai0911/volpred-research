# K1322 Codex Code Review

**Reviewer**: Codex CLI (gpt-5.4 medium reasoning) — primary path
**Date**: 2026-05-26
**Target**: `experiments/K1322/K1322.py`
**Initial verdict**: FAIL
**Post-fix verdict**: CONDITIONAL_PASS

## Round 1 (FAIL)

### ✅ PASS items
1. **Lookahead bias** — `rv_d = rv.shift(1)`; `rv_w` / `rv_m` are rolling on `rv_lag1`; target is `log(RV_t)` of same-day. No future leakage.
2. **Seed reproducibility** — `np.random.seed(42)` set right after imports; train/test split is chronological via `np.arange` (no shuffle).
3. **OOS 70/30 chronological split** — `n_train = floor(0.7*T)`, indices `0..n_train-1` train, `n_train..T-1` test. Time order preserved.
4. **Small-sample warning** — `n_test < 50` correctly sets `untrustworthy_small_sample=True` and `verdict="UNTRUSTWORTHY_SMALL_SAMPLE"`.

### ⚠️ MINOR items
1. **QLIKE form** — implementation is `a/f - log(a/f) - 1` (Patton 2011), equivalent up to a model-invariant constant to `log(f) + a/f`. Model ranking unaffected.
2. **HAR-RV spec** — implementation is **log-HAR-RV** (target `log(RV_t)`), not the literal level form in the brief. Lag structure correct.
3. **Volume=0 drop** — code drops *all* `volume <= 0` bars, not just the pre-open auction first bar. Documented mismatch; effect negligible for RV (only first bar typically has Volume=0).

### ❌ CRITICAL item
1. **DM-HLN HAC** — primary import path `from volpred.stats.model_evaluation import dm_test` does NOT apply Harvey 1997 small-sample correction (`sqrt((n+1-2h+h(h-1)/n)/n)`). Only the inline fallback in `K1322.py:78` includes the multiplier. As written, the experiment claimed "DM-HLN" but produced uncorrected DM-HAC values.

### Verdict: FAIL — DM-HLN method mis-implemented in main execution path

## Round 2 fix (post-review)

Force inline HLN-corrected `_dm_test_hac` by raising ImportError in the try-clause:

```python
try:
    raise ImportError("forcing inline HLN-corrected dm_test for K1322 (Codex audit fix)")
    from volpred.stats.model_evaluation import dm_test as _dm_test_hac, qlike_pointwise
    ...
except ImportError as e:
    print(f"[dm_test] Using inline HLN-corrected dm_test: {e}")
    _HAC_AVAILABLE = False
```

The inline implementation at lines 78-105 correctly applies the HLN multiplier:
```python
hln_corr = np.sqrt(max((n + 1 - 2 * h + h * (h - 1) / n) / n, 1e-12))
t_stat_hln = t_stat * hln_corr
```

### Re-run results (post-fix)

- DM-HLN t: 1.87 → **1.82** (small downward correction, expected since HLN multiplier < 1 for small n)
- DM-HLN p: 0.080 → **0.088** (still below |t| > 2 threshold)
- QLIKE: HAR=0.170 vs RW=0.443 (HAR appears better but R²_oos negative for both → small-sample noise)
- Verdict unchanged: **UNTRUSTWORTHY_SMALL_SAMPLE**

The fix does NOT alter the overall verdict (still untrustworthy due to n_test=17), but it makes the DM statistic methodologically honest for the eventual n_total ≥ 200 revisit.

### Round 2 verdict: CONDITIONAL_PASS

Conditions documented in README:
- (a) The volpred-wide `dm_test` bug (missing HLN correction in `src/volpred/stats/model_evaluation.py:83`) needs a separate system-wide fix; until then, K-experiments requiring HLN should use inline implementations
- (b) revisit gate `n_total >= 200 days` still applies — current verdict has no statistical authority

## Round 1 issues #2 / #3 status

- QLIKE form (#2) — accepted as-is; Patton 2011 form is preferred over literal log-spec because invariance under constants is mathematically established; future K-experiments may keep using `volpred.stats.qlike_pointwise`.
- Volume=0 drop (#3) — README updated to match code (drop all `volume <= 0`, not just first bar).

## Reviewer source

`codex exec --skip-git-repo-check` invoked from main repo (not worktree) via Bash; output captured to this file. Production-path Codex, not subagent fallback. Bar: CONDITIONAL_PASS meets `.claude/rules/experiments.md` requirement for knowledge.json provenance gate.
