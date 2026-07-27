# K1731 arm B — Codex review round 9

You are reviewing a **bounded claim-layer remediation**. Round 8 returned FAIL on
ONE blocking finding. Your job is to decide whether that finding is actually
closed, and whether closing it (plus the two gate-hole fixes) introduced anything
new. This is a narrow claim-surface + gate review, NOT a re-estimation review.

## Working directory

`/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731`

Branch `wt/dispatch-slot-1-bd00f90a-k1731`, HEAD `a6a7d0cea635944d394c16b638136c25f97d21a6`.
This experiment is NOT merged into main and must not be.

## Frozen bytes — verify FIRST

`storage/ops/codex_reviews/k1731_armB_rev9_freeze.txt` pins the SHA-256 of every
file in the claim surface. **Verify the hashes before anything else.** If any file
has changed, say so and STOP — a verdict against moved bytes is worthless.

## What round 8 blocked on (single blocking finding)

Read `storage/ops/codex_reviews/k1731_armB_rev8_verdict.md` in full. Round 8's one
blocking issue: the canonical finalizer's
`k1731_finalize_report.py:ARM_A_ENGINE_ISSUES[0].why_it_matters` still

1. called a low posterior inclusion probability (PIP) **"evidence of no effect"**, and
2. asserted **"the arm B null rests most solidly on CPI, UNRATE, VIX and TERM"**,

i.e. it stated an out-of-sample null as an established result, on the exact surface
a downstream machine reader hits first (the finalizer writes this string into all
three result JSONs, including the primary artifact).

Two gate holes let it pass silently:
- **arm-B verification gate** never scanned `armA_engine_issues` (only nested DM
  rows, `headline_verdict`, `cross_arm_comparison`, and the README).
- **rev8 drift check** turned its verdict solely on `numeric_moved`; a regeneration
  that invented or dropped a numeric leaf would have passed.

## What round 9 changed (full detail in `experiments/k1731/K1731_ARMB_REV9_COLLECTION.md`)

1. **F-rev9-1** — rewrote `ARM_A_ENGINE_ISSUES[0].why_it_matters` to support ONLY an
   in-sample-selection reading and to state explicitly that a low PIP does NOT
   establish an out-of-sample null. Numeric anchors kept factual (CPI 0.131,
   UNRATE 0.192, VIX 0.178, TERM 0.086, all < 0.20).
2. **F-rev9-2** — regenerated all three result JSONs via
   `k1731_finalize_report.py` (no hand edit). Independent leaf diff vs frozen
   `f5338d54d`: numeric changed/added/removed = 0/0/0; the only changed leaf is
   `armA_engine_issues[0].why_it_matters` (a string).
3. **F-rev9-3** — extended `k1731_armB_verification.py` with `scan_engine_issues`
   over `armA_engine_issues` for the retracted phrases, three MISMATCH-on-presence
   rows (one per artifact), a positive control, and a `--self-test` negative control.
4. **F-rev9-4** — `k1731_rev8_drift_check.py` now fails on `numeric_added` /
   `numeric_removed` too, with a `--self-test` negative control.
5. **F-rev9-5** — rebuilt freeze manifest `k1731_armB_rev9_freeze.txt`.

## Your job — decide PASS or FAIL

Confirm, against the frozen bytes:

1. The round-8 blocking finding is genuinely closed: read the current
   `ARM_A_ENGINE_ISSUES[0].why_it_matters` and confirm neither retracted claim
   ("evidence of no effect" as a null; "arm B null rests most solidly …") survives,
   in the source AND as it lands in all three result JSONs.
2. The rewrite did not overcorrect into a new false claim, and stays consistent
   with `HEADLINE_VERDICT.what_is_supported` / `why_not` and
   `cross_arm_comparison.inference_caveats`.
3. The two gate-hole fixes are real (not cosmetic): the new verification scan
   would actually fire on the round-8 wording, and the drift check would actually
   fail on a numeric add/remove. Reproduce the gates if in doubt:

```
uv run --active python k1731_finalize_report.py                 # regenerate (idempotent)
uv run --active python k1731_armB_verification.py               # expect PASS, exit 0
uv run --active python k1731_armB_verification.py --self-test   # negative control, exit 0
uv run --active python k1731_regression_check.py \
    --baseline regression_baseline/k1731_gevreg_midas_ssvs_returns_results_corrected.json \
    --candidate k1731_gevreg_midas_ssvs_returns_results_corrected_rev5.json
uv run --active python k1731_rev8_drift_check.py --rev f5338d54d # expect PASS, exit 0
uv run --active python k1731_rev8_drift_check.py --self-test     # negative control, exit 0
uv run --extra dev pytest scripts/tests/test_nested_dm_misuse_ratchet.py
```

NOTE: `k1731_finalize_report.py` rewrites `finalized_utc` on every run, so running
it will dirty the three result JSONs relative to the frozen bytes. If you run it,
`git checkout -- experiments/k1731/k1731_gevreg_midas_ssvs_returns_results*.json`
afterward to restore the frozen bytes before judging hashes. Prefer judging the
committed bytes directly; only regenerate if you need to confirm idempotence.

4. Nothing outside the stated bounded scope changed (no re-estimation, no
   out-of-directory drift; the nested-DM baseline is byte-identical to `f5338d54d`).

## Verdict format

End with a line `VERDICT: PASS` or `VERDICT: FAIL`. If FAIL, list each blocking
finding with the exact file:line and the minimal change required to close it. Do
not propose scope expansion (the deferred general-loss recursive-bootstrap /
nested-forecast pinball correction is explicitly out of scope for this round).
