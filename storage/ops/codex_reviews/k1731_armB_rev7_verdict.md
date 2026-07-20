VERDICT: FAIL

All 15 files matched `k1731_armB_rev7_freeze.txt`. This verdict is against the
frozen rev7 bytes. The ratchet suite passed 108/108 tests, the traceability
checker passed 69/69 checks, and the regression gate compared 3,834 leaves with
zero unexpected drift.

## B1a — FAIL

The table-level repair is real: README §3.2 now calls the column a HAC diagnostic
interval, unbolds the nested row, and explicitly says it has no coverage
guarantee. The same README nevertheless opens with the OOS conclusion that macro
"does not improve" the forecasts (`README.md:3-4`) and repeats it as the first
"Honest conclusion" (`README.md:557-565`). It then calls in-sample PIPs the
load-bearing evidence even though the document itself correctly says that PIP is
about in-sample selection and does not establish OOS predictive value. The raw
nested DM is only directional. The table retraction therefore does not reach the
headline claim surface.

## B1b — FAIL

The specifically requested `cross_arm_comparison` repair passes: the canonical
finalizer generates the new four-part caveat, removes "demonstrably", labels arm
A's statistic directional, and moves no numeric leaf.

However, the PRIMARY artifact still asserts the retracted bound in both nested
DM cells:

- `oos.dm_tests.GEVReg-MIDAS-SSVS_vs_GEV-HAR__mean_pinball.interpretation`
- `oos.dm_tests.GEVReg-MIDAS-SSVS_vs_GEV-HAR__tail_pinball.interpretation`

Both say that the interval "bounds the effect". This is not superseded history:
it is live narrative in the only artifact stamped `is_primary=true` and
`do_not_cite=false`. The canonical estimation source generates the same sentence
for every primary comparison at
`k1731_gevreg_midas_ssvs_returns.py:404-427`, without branching on the nested
GEV-HAR case. A production rerun will therefore recreate the false formal-bound
claim. This is a new claim-evidence gap introduced or left outside the bounded
remediation's claimed whole-artifact consistency.

## B5 — PASS

The module docstring now accurately says that arm B reuses the implementation
while macro set, GARCH information set, and estimation mode differ. The hard
"six things" count is gone. Comparing ASTs with docstrings stripped confirms the
change is non-executable.

## Detector — PASS

The coefficient-mask channel sees the actual K1731 path: a zeroed slice of
`active` reaches `fit_gev_reg(..., active=active)`. Removing the mask makes the
positive fixture clean, while the `sample_weight` and never-estimated negatives
remain clean. The conjunction is narrow but principled: it requires both a
zeroed subscript and restriction-shaped flow into a fit-family call. The three
declared blind spots are genuine scope limits, not hidden exceptions to the
implemented claim. The 108-test ratchet passes.

## Baseline flip — PASS

The baseline records both K1730 and K1731 in the exposed bucket. Counts move
193 to 195 total and 103 to 105 exposed, with diagnostic-only unchanged at 90.
K1730's separate pending task `k1730_nested_dm_detector_exposure` owns its newly
revealed defect, so this review does not repair another experiment.

## Earlier-round fixes — PASS

The rev7 edits do not re-break the previously passed B2/B3/B4/B6/B7 checks. The
traceability checker reports 69 clean checks, the SHA-seeded ES proof remains in
place, and the review trail now records six prior rounds.

## Provenance invariant — PASS

Exactly one production artifact is primary and citeable. Both superseded
production artifacts have `is_primary=false`, `do_not_cite=true`,
`superseded_by`, and a non-empty `superseded_reason`; the quick-mode artifact is
not falsely presented as a provenance-stamped production artifact.

## Ready justification — FAIL

The remediation JSON honestly admits that nested-DM inference remains uncorrected
and arm A remains unrepaired. The README and primary artifact do not consistently
honour that admission: the former still states an OOS null as the verdict, and
the latter still labels the nested intervals as bounds.

## Blocking issues

- `experiments/k1731/k1731_gevreg_midas_ssvs_returns.py:404-427` applies one
  formal CI/bound interpretation to all primary comparisons, including nested
  GEV-HAR. Branch by comparison type: retain CI semantics only for non-nested
  rows; stamp the nested rows diagnostic-only with no coverage or bound claim.
  Regenerate all three result artifacts from the source; do not hand-edit JSON.
- `experiments/k1731/k1731_gevreg_midas_ssvs_returns_results_corrected_rev5.json`
  has the same false statement in the two GEV-HAR `interpretation` fields. The
  regenerated primary artifact must contain the diagnostic-only wording and the
  regression allow-list must restrict the change to narrative leaves.
- `experiments/k1731/README.md:3-4` and `:557-565` state that macro does not
  improve OOS forecasts while naming in-sample PIPs as load-bearing evidence.
  Downgrade this to the supported statement: macro is weakly selected in-sample,
  while the OOS comparison is an uncorrected directional diagnostic that cannot
  establish either improvement or a null. Make the opening verdict, §3.3b, §6,
  primary JSON, and module-level description agree.
