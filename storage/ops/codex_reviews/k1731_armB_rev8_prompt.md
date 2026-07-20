# K1731 arm B — Codex review round 8

You are reviewing a **bounded claim-layer remediation**. Round 7 returned FAIL.
Your job is to decide whether the three blocking issues in that verdict are
actually closed, and whether closing them introduced anything new.

## Working directory

`/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731`

Branch `wt/dispatch-slot-1-bd00f90a-k1731`, HEAD `65f3d4461`. This experiment is
NOT merged into main and must not be.

## Frozen bytes

`storage/ops/codex_reviews/k1731_armB_rev8_freeze.txt` pins every file in the
claim surface. **Verify the hashes first.** If any file has changed, say so and
stop — a verdict against moved bytes is worthless.

## What round 7 blocked on

Read `storage/ops/codex_reviews/k1731_armB_rev7_verdict.md` in full. Its three
blocking issues were:

1. `k1731_gevreg_midas_ssvs_returns.py:404-427` applied one formal CI/bound
   interpretation to ALL primary comparisons including the nested GEV-HAR rows.
   Required: branch by comparison type; retain CI semantics only for non-nested
   rows; stamp nested rows diagnostic-only with no coverage or bound claim;
   regenerate all three artifacts from source; do not hand-edit JSON.
2. The primary artifact's two GEV-HAR `interpretation` fields carried the same
   false statement. Required: the regenerated primary artifact must contain the
   diagnostic-only wording, and the regression allow-list must restrict the
   change to narrative leaves.
3. `README.md:3-4` and `:557-565` stated that macro does not improve OOS
   forecasts while naming in-sample PIPs as load-bearing evidence. Required:
   downgrade to weak in-sample selection plus an uncorrected directional OOS
   diagnostic; make the opening verdict, §3.3b, §6, primary JSON and module-level
   description agree.

## What this round claims to have done

`experiments/k1731/k1731_armB_rev8_remediation.json` is the round's own account,
including its `honest_limitations`. Treat it as a claim to be checked, not as
evidence.

## What to check, and where you should be hardest

- **Does the branch actually reach every surface?** The failure mode of rounds
  5, 6 and 7 was that a retraction was applied where it was noticed and survived
  everywhere else. Look for the claim in: the README headline, §3.2, §3.3b, §6,
  §7, §10; the three result artifacts (field NAMES as well as prose); the
  estimation source; the finalizer; the module docstring. If it survives
  anywhere as a live claim, that is a FAIL.
- **Is `no coverage or bound` genuinely satisfied for the nested rows?** They
  retain a ±1.96·HAC-SE range under `hac_pm1p96se_*_no_coverage`. The remediation
  argues renaming is enough and records the counter-argument in
  `honest_limitations`. Decide whether you accept it. If you think the numbers
  must be deleted rather than renamed, say so as a blocking issue.
- **Was any number moved?** `k1731_rev8_drift_check.py` claims 0 numeric leaves
  moved against the rev7 bytes and 64 interval leaves reproduced exactly by the
  refactored estimation path. Re-derive this independently — do not take the
  gate's own output as proof of the gate.
- **Is the refactor of `score_all`'s inline block genuinely value-preserving?**
  The old code computed `base` from `np.mean(pinball[b])`; the new function reads
  `by_model[b]["mean_pinball"]`. Satisfy yourself these are the same float, and
  that the arithmetic and its evaluation order are unchanged.
- **Did the regression gate get weakened?** It gained a rename-following pass and
  a narrative-path allow-list. Check that the allow-list covers only prose, that
  the rename pass fails when a renamed value moves, and that no numeric leaf on a
  primary DM row can now change without being reported.
- **The `derive_intervals=False` design.** The finalize stage claims to do no
  arithmetic so that re-finalizing cannot deposit a derived statistic into the
  pre-rev2 artifact. Verify that is true of the code, not just of the docstring.
- **The baseline addition.** The ratchet initially failed on
  `k1731_finalize_report.py` as a new nested-DM site. It was added to
  `storage/ops/nested_dm_misuse_baseline.json` under `exposed` rather than
  silenced with the `nested-dm: diagnostic-only` marker. Judge whether that was
  the right call and whether the bucket is right.
- **Anything the round-8 changes broke.** B5, the detector, the provenance
  invariant and the earlier-round fixes all passed in round 7. Confirm they still
  do.

## Reproduce the gates

```
cd /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731
uv run --extra dev python -m pytest scripts/tests/test_nested_dm_misuse_ratchet.py -q
cd experiments/k1731
uv run --active python k1731_armB_verification.py        # expect 107/107, 0 problems
uv run --active python k1731_rev8_drift_check.py         # expect 0 numeric moved
uv run --active python k1731_regression_check.py \
  --baseline regression_baseline/k1731_gevreg_midas_ssvs_returns_results_corrected.json \
  --candidate k1731_gevreg_midas_ssvs_returns_results_corrected_rev5.json
```

Note that running the verification/drift/regression scripts rewrites their own
`*_results.json`, which will change those two hashes in the manifest. That is
expected; check the hashes BEFORE you run anything.

## Output

Write a verdict in the same shape as the round-7 verdict:

- `VERDICT: PASS` or `VERDICT: FAIL` on the first line.
- A section per blocking issue (B1a, B1b, B3) with PASS/FAIL and your reasoning.
- Sections for the drift proof, the regression gate, the baseline addition, and
  earlier-round fixes.
- A `## Blocking issues` section listing anything that must be fixed before this
  can be certified, with file:line references. Empty if none.

Be adversarial. Four rounds have now been spent removing one false claim, each
time behind green gates. Assume there is a surface nobody has looked at yet, and
go looking for it.
