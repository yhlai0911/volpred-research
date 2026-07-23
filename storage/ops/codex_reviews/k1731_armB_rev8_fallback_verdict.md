# K1731 arm B round 8 — independent fallback review

**Reviewer**: `feature-dev:code-reviewer` subagent, fresh context, opus.
**Why not Codex**: Codex usage limit exhausted, resets 2026-07-25 13:30. See
`k1731_armB_rev8_verdict.md`.
**Status of this document**: a fallback review, NOT a substitute for a
primary-path Codex verdict (`.claude/rules/experiments.md`). It also predates the
fixes it prompted, so it does not certify the current bytes.

**Reviewed against**: commit `65f3d4461` (round-8 first pass).

---

VERDICT: FAIL

## B1a — FAIL

Three live assertions of the OOS null survived in README prose, on surfaces the
round-7 verdict had not named and the round-8 self-check did not search:

- `README.md:309-310` — "This is independent evidence from the DM tests, which is
  why the null rests on more than a failure to reject." The round-7 defect
  verbatim, in a Results section, 535 lines before §10 announced its retraction,
  and in direct contradiction of §6's "two pieces of evidence that each fail to
  support a conclusion do not support it jointly."
- `README.md:568-573` — "would make a low PIP weaker evidence of no effect ... the
  arm B null rests most solidly on CPI, UNRATE, VIX and TERM."
- `README.md:663-664` — "a properly vintage-consistent IP and NFP would let the
  null be stated on all six." Presupposes the null is currently stated on four,
  and contradicts the bullet six lines later naming the nested-forecast
  correction as the binding constraint.

Root cause: the round's self-check was a grep over `does not improve`,
`the null is`, `macro null`, `bounded null`, `95% HAC`, `95% CI`. None of those
patterns match "the null rests on", "the arm B null rests", or "let the null be
stated". This is the same pattern-limited search that produced the round-5, -6
and -7 failures, applied one more time.

## B1b — PASS

Verified directly against the artifacts rather than through the round's own gate:

- `NESTED_BENCHMARKS` and `annotate_primary_dm_inference` branch correctly; the
  inline block is gone; estimation and finalize share one implementation.
- `ci95_` key counts: 12 in `_corrected_rev5.json`, 12 in `_corrected.json`,
  0 in `_results.json`, against 16 in the frozen `regression_baseline/` copy —
  exactly the 4 nested keys / 8 leaves moved, and no more.
- `"bounds the effect"` occurs exactly 6 times in each production artifact (the 6
  non-nested primary rows, where the semantics are valid) and 0 times on any
  nested row, `headline_verdict`, or `cross_arm_comparison`. Whole-file grep, not
  the scoped subset the verification script checks.

## B3 — FAIL

Four of five surfaces agree (primary JSON, module docstring, §3.3b, §6). The
README does not: §3.3, §5.1 and §7b still state the null. Fails as a consequence
of B1a, on the surface it was written about.

## Drift proof — PASS, re-derived independently

The refactor is value-preserving. `score_all` stores
`"mean_pinball": float(np.mean(pinball[m]))`, so the new
`oos["by_model"][b]["mean_pinball"]` **is** the old `float(np.mean(pinball[b]))` —
the same expression, cached rather than recomputed. Identical by construction.

Intervals re-derived by hand from stored inputs on three rows (nested mean,
nested tail, non-nested mean): `se = |md/t|`, `md ± 1.96·se`, and the percentage
against the benchmark's own loss all reproduce the stored values to full
precision. Evaluation order unchanged. The 86 additions reconcile exactly
(26 + 26 + 34).

## Regression gate — not weakened

`ALLOWED_PREFIXES` adds only the three prose fields. No numeric field is
allow-listed; a change to `t_stat`, `p_value`, `hac_se_of_loss_differential` or
any interval leaf classifies as UNEXPECTED. The rename pass routes to UNEXPECTED
when the value moved. I could not construct a reachable scenario in which a real
numeric drift on a primary DM row goes unreported.

One latent hole, unreachable today: a candidate-only leaf whose reverse-rename
source exists in the baseline is skipped without a value check, which is sound
only because the stale name cannot survive into the candidate. A gate depending on
an invariant it does not assert.

## `derive_intervals=False` — PASS, verified from code

The branch contains no arithmetic on any estimate — only `d[live] = d.pop(stale)`
under an explicit guard. A field absent from the artifact is never invented;
confirmed against `_results.json`, whose nested rows carry the three label fields
and terminate with no interval keys.

## Baseline addition — PASS

Filing `k1731_finalize_report.py` under `exposed` rather than silencing it with
the `nested-dm: diagnostic-only` marker is the right call, and the bucket is
right: understating debt is the worse error direction, consistent with the k1730
precedent.

## Is renaming enough for "no coverage or bound"? — Yes

A coverage claim is an assertion, not a number. `±1.96·HAC-SE` remains a
well-defined descriptive statistic of the realised sample; what nesting destroys
is the null distribution, not the arithmetic of the dispersion. Three surfaces now
deny coverage (field name, `inference_validity`, interpretation text), and §3.2's
extended argument about why that specific range is not a bound would be left
explaining a number the reader can no longer see if it were deleted.

## Newly introduced defects

- **`k1731_armB_verification.py:376` — the script always exits 0.** It computes
  `bad`, prints `problems = N`, and returns success for any N. Every round-8
  invariant is enforced by a script with no failure mode. Given that round 8's
  stated thesis is "add the gates that make that checkable rather than asserted",
  a gate that cannot fail does not discharge the thesis.
- **`k1731_rev8_drift_check.py:134`** — `zip(before[f], after.get(f, []))` checks
  zero leaves and records no mismatch when the recomputed field is absent, which
  is exactly the shape `computable` going false would produce.
- `k1731_rev8_drift_check.py:99-101` — a value-moved rename is double-counted into
  `added`.
- The pre-rev2 artifact's nested `interpretation` references a
  `hac_pm1p96se_*` field that file does not contain.
- The positive control for the text scan is real and would fail if the
  interpretation text vanished — but it inherits the parent script's inability to
  fail the process.

## Blocking issues

1. `README.md:309-310` — live assertion of the OOS null with PIPs as joint
   load-bearing evidence.
2. `README.md:568-573` — "the arm B null rests most solidly on...".
3. `README.md:663-664` — "would let the null be stated on all six".
4. `k1731_armB_verification.py:376` — always exits 0; wrap in a `main()` returning
   1 when `bad` is non-empty.
5. `k1731_rev8_drift_check.py:134` — compare lengths explicitly; assert `checked`
   against an expected count.

## Process observation for round 9

Rounds 5-8 have each verified the retraction with a fixed list of grep patterns
and each missed a paraphrase. Round 8 built real machine gates — and pointed all
of them at the JSON artifacts, while every one of this round's three failures is
README prose. The gate that would close this is a README-side scan keyed on the
*concept*, with an explicit allow-list of retraction and review-trail lines, wired
to a non-zero exit. Without it, round 9 will find a fourth paraphrase.
