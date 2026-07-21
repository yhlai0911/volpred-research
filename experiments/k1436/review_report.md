# K1436 — independent review record

**Verdict: PASS** (CONDITIONAL_PASS -> fix -> PASS, then re-attested after an additive change)
**Reviewed commit**: `0b3ab65ee`
**Reviewer**: `feature-dev:code-reviewer` subagent, fresh context, read-only.
**Reviewer source**: fallback path. Codex CLI (primary) was unavailable —
`codex exec` returned `You've hit your usage limit ... try again at Jul 25th, 2026`.
Per `.claude/rules/experiments.md`, a fresh-context `code-reviewer` subagent is the
sanctioned fallback, and the knowledge entry must record that this was **not** a
primary-path Codex review. **If Codex quota returns before this is cited in any
outward-facing claim, re-verify on the primary path** (per the K1259 lesson that a
subagent PASS is not equivalent to a Codex PASS).

## Round 1 — CONDITIONAL_PASS

Passed: lookahead (both layers), nested-model inference (Clark-West formula, one-sided
direction, HAC bandwidth), QLIKE direction, log-space smearing symmetry, baseline
parity, RV construction, fetch pagination.

Verified explicitly that the verdict expression consumes only Clark-West-derived
quantities and never the `dm_*` dicts — i.e. the diagnostic-only demotion is real, not
just a comment.

**Blocking defect found**: README §7.4 and §8 quoted a baseline HAR-only R² of 0.5305
and an incremental R² of +0.0037. Those numbers were computed in an ad-hoc session
command, **not** by `k1436.py`, and were absent from `k1436_results.json` — so re-running
the committed script would not reproduce them. Violates "數字必對齊實驗檔".

## Fix

- Added `ols_baseline = hac_ols(panel, [])`; persisted to `har_ols_full.baseline` and to a
  new `incremental_r2` block (baseline / with_funding / with_abs_funding + both deltas).
- README §7.4 re-quoted at 5 dp with a pointer to `k1436_results.json.incremental_r2`.
- Non-blocking items also addressed: `rv > 0` attrition now counted explicitly
  (`n_days_dropped_nonpositive_rv`, empirically 0); the row-position-vs-calendar-date
  `.shift(1)` nuance documented as README §9 limitation 8.

## Round 2 — PASS

Re-review confirmed the defect is resolved and every README §7.4/§8 number traces to the
artifact (0.53046 → 0.53419, deltas 0.00372 / 0.00463, n = 2371). Diffed all
claim-critical logic — verdict expression, `clark_west`, `dm_with_sensitivity`,
`evaluate`, `rolling_forecast` training slice, `hac_ols`, both feature builders,
`assert_no_lookahead` — and found them byte-identical to round 1, i.e. no scope creep
while fixing. No new defects.

Reviewer also confirmed the |funding| CW p = 0.041 framing is handled honestly: labelled
as failing the Bonferroni bar and explicitly *not* presented as a finding.

## Note on the nested-DM correction

Worth recording because it changed a number, not just a label. The first draft of this
experiment used raw Diebold-Mariano as primary inference. The repo's `nested-dm-misuse`
gate rejected it (HAR-RV is nested in HAR-RV+funding). Switching to Clark-West moved the
same forecasts from p ≈ 0.36–0.41 to p ≈ 0.04–0.08. The conclusion stayed NULL, but the
raw-DM version would have reported a comfortable, far-from-significant null that was
partly an artifact of the wrong test.

## Round 3 — PASS (re-attestation after an additive change)

After round 2 I noticed the dispatch brief required a `limitations[]` field in
`k1436_results.json`, which was missing (the caveats existed only in the README). Added it
in `k1436.py` as a 9-item mirror of README §9 — purely additive, no computation touched.
That drifted the claim-surface sha and correctly invalidated the round-2 verdict, so it was
re-reviewed rather than hand-patched.

Reviewer confirmed: the diff contains only the `limitations` list; `clark_west`,
`dm_with_sensitivity`, `evaluate`, `rolling_forecast` (including the causal training
slice), `hac_ols`, both feature builders, `assert_no_lookahead`, and the verdict expression
are byte-identical to round 2; all 9 JSON items map 1:1 to README §9 with no caveat
weakened in either direction; and every numeric field is unchanged apart from the
`run_at_utc` stamp that `reproduce_spec.json` declares ignorable.

Final frozen commit: `0b3ab65ee`.
