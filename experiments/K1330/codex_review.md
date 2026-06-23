# K1330 Codex Review

- **Task**: `K1330_codex_review_followup`
- **Review date**: 2026-06-23
- **Reviewer**: Codex
- **Verdict**: **CONDITIONAL_PASS**

## Scope

K1330 is a governance / dedup closure artifact, not a new empirical experiment. The review question is whether `experiments/K1330/` can legitimately close the original USD-regime task as superseded by canonical K1439, and whether it is safe to keep K1330 out of knowledge promotion as a standalone empirical finding.

## Findings

1. **No lookahead issue in the referenced canonical experiment.** K1439 builds both USD level and trend regime buckets with explicit `bucket.shift(1)`, so the regime label used for day `t` is known at `t-1`. See `experiments/k1439/k1439.py:98-118`.
2. **The closure audit correctly verifies topic coverage.** K1330 checks that K1439 covers EEM, GLD, DBC, DBB, USO, uses UUP as the USD proxy, requires `shift(1)`, requires HAC/Newey-West inference, and requires overlap-risk disclosure. See `experiments/K1330/K1330.py:28-65`.
3. **The closure script is reproducible and deterministic.** It reads the existing K1439 results JSON, uses no random sampling, fixes `SEED = 42`, and rewrites `K1330_results.json`. Re-run on 2026-06-23 returned `SUPERSEDED_BY_K1439 | overlap_pass=True | robust_assets=USO`.
4. **The statistical conclusion is correctly downscoped.** K1439 uses HAC/Newey-West with maxlags 21 for overlapping 21d RV and Bonferroni alpha 0.01; only USO is significant in both level and trend regime definitions. See `experiments/k1439/k1439.py:172-198,256-283,336-355` and `experiments/k1439/k1439_results.json`.

## Caveats

- K1330 should not be promoted as a new empirical result. It is a duplicate-closure receipt that points to K1439.
- K1439's current conclusion is `CONDITIONAL_PASS`, not broad cross-asset confirmation: the robust effect is isolated to USO.

## Decision

`CONDITIONAL_PASS`. Keep K1330 closed as `SUPERSEDED_BY_K1439`; do not open a K1330 v2 methodology task. No `knowledge.json` write is needed for K1330 beyond the existing canonical K1439 entries.
