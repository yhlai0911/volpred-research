# K1731 arm B — Codex review round 10

You are reviewing a **bounded claim-layer remediation**. Round 9 returned FAIL on
ONE blocking finding: the round-9 rewrite overcorrected. Your job is to decide
whether that single overclaim is now closed on **every** surface it appeared on,
and whether closing it introduced anything new. This is a narrow claim-surface
review, NOT a re-estimation review.

## Working directory

`/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731`

Branch `wt/dispatch-slot-1-bd00f90a-k1731`, HEAD `76b55a73d`.
This experiment is NOT merged into main and must not be.

## Frozen bytes — verify FIRST

`storage/ops/codex_reviews/k1731_armB_rev10_freeze.txt` pins the SHA-256 of every
file in the claim surface (32 worktree files + 3 repo-level nested-DM files).
**Verify the hashes before anything else.** If any file has changed, say so and
STOP — a verdict against moved bytes is worthless. The three repo-level hashes are
byte-identical to rev9 / `f5338d54d`; nothing out-of-directory changed this round.

## What round 9 blocked on (single blocking finding)

Read `storage/ops/codex_reviews/k1731_armB_rev9_verdict.md` in full. Round 9's one
blocking issue: `k1731_finalize_report.py` asserted a posterior inclusion
probability (PIP) **"carries no information about out-of-sample predictive value"**.
That is stronger than the evidence licenses — a PIP is neither an OOS measure nor
sufficient evidence, but it does not follow that it carries *no* information about
OOS predictive value. Round 9 flagged it at `ARM_A_ENGINE_ISSUES[0].why_it_matters`
(and its three JSON positions + the collection blockquote). The verdict also
recorded that the round-9 freeze itself verified clean (35/35, verification
111/111, regression UNEXPECTED=0, drift 0/0/0).

## What round 10 changed (full detail in `experiments/k1731/K1731_ARMB_REV9_COLLECTION.md` §5)

1. Softened the overclaim to Codex round-9's own suggested wording — **"does not
   directly measure or by itself establish out-of-sample predictive value"** — on
   **BOTH** surfaces the identical phrase stood on:
   - `k1731_finalize_report.py` `HEADLINE_VERDICT.why_not[0]` (lines 78–80), and
   - `k1731_finalize_report.py` `ARM_A_ENGINE_ISSUES[0].why_it_matters` (lines 291–293).
   Round 9 flagged only the second; the first carried the same phrase. Fixing only
   the flagged one would repeat the documented failure mode (fix where the claim is
   looked for, leave it standing elsewhere), so both were fixed. The load-bearing
   conclusion — a low PIP cannot establish an OOS null — is preserved on both.
2. Regenerated all three result JSONs via `k1731_finalize_report.py` (no hand edit).
   Numeric changed/added/removed = 0/0/0; the only changed leaves are the two
   softened strings.
3. Synced the collection §1 blockquote to the new artifact wording and added a
   round-10 §5 addendum documenting the fix, fresh SHA-256, and gate reruns.
4. Rebuilt the freeze as `k1731_armB_rev10_freeze.txt` (self-verified 35/35).

No gate logic changed this round. No re-estimation.

## Your job — decide PASS or FAIL

Confirm, against the frozen bytes:

1. The round-9 overclaim is genuinely closed **everywhere**: grep the exact phrase
   `carries no information about out-of-sample predictive value` across the claim
   surface (source + all three result JSONs). It must survive **only** as quoted
   meta-text inside the collection §5 (documenting the fix), and NOWHERE as an
   assertion. Confirm both softened strings reach all three result JSONs.
2. The softened wording did not overcorrect the other way or become internally
   inconsistent with `HEADLINE_VERDICT.what_is_supported` / `why_not` and
   `cross_arm_comparison.inference_caveats`.
3. Numeric drift 0/0/0 and nothing outside the bounded claim-layer scope changed.
   Reproduce the gates if in doubt:

```
uv run --active python k1731_armB_verification.py               # expect PASS, exit 0
uv run --active python k1731_armB_verification.py --self-test   # negative control, exit 0
uv run --active python k1731_regression_check.py \
    --baseline regression_baseline/k1731_gevreg_midas_ssvs_returns_results_corrected.json \
    --candidate k1731_gevreg_midas_ssvs_returns_results_corrected_rev5.json
uv run --active python k1731_rev8_drift_check.py --rev f5338d54d # expect PASS, exit 0
uv run --active python k1731_rev8_drift_check.py --self-test     # negative control, exit 0
uv run --extra dev pytest scripts/tests/test_nested_dm_misuse_ratchet.py   # run from the worktree; expect 108 passed
```

NOTE: `k1731_finalize_report.py` rewrites `finalized_utc` on every run, so running
it dirties the three result JSONs vs the frozen bytes. If you run it,
`git checkout -- experiments/k1731/k1731_gevreg_midas_ssvs_returns_results*.json`
afterward before judging hashes. Prefer judging the committed bytes directly.

## Known non-blocking residuals (disclosed in collection §5.6 — do NOT treat as blocking)

- The arm-B verification gate bans only the round-8 phrases; it does not yet ratchet
  the round-9 phrase `carries no information about out-of-sample`. Adding that
  ratchet was deliberately kept out of this round to honour the minimal-fix
  instruction (rebuild JSONs, sync collection, rebuild freeze — no new gate logic).
- `k1731_rev8_drift_check.py` top-level docstring (line 19) still describes only
  `numeric_moved` as failing — the stale comment you flagged non-blocking in round 9.

These are honest standing items, not evidence problems. Do not fail the round on
them, and do not propose scope expansion (the deferred general-loss
recursive-bootstrap / nested-forecast pinball correction is out of scope).

## Verdict format

End with a line `VERDICT: PASS` or `VERDICT: FAIL`. If FAIL, list each blocking
finding with the exact file:line and the minimal change required to close it.
