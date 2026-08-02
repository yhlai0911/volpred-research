# K1730 randomization-test upgrade: no-dispatch adjudication

**Task**: `k1730_randomization_test_upgrade_null`  
**Date**: 2026-08-02  
**Disposition**: `NO_DISPATCH — artifact contract mismatch and invalid randomization group`

## Decision

Do not enqueue the requested B=199 full macro-tensor permutation. This is not a
scientific NULL result and does not overturn K1730's descriptive NULL. The work
order cannot currently produce a valid test because its canonical producer
artifact is absent and its proposed transformation repeats a lookahead and
exchangeability defect already documented by the experiment's own remediation.

The task must be split into two bounded prerequisites: first restore and certify
the K1730 claim surface in canonical main; then preregister a time-series
randomization group that preserves point-in-time availability and has an
explicit invariance/exchangeability argument. Heavy computation may be queued
only after both prerequisites pass.

## Evidence read-back

### 1. The declared prerequisite did not land in canonical main

- At inspected HEAD `ca668e82b0d554dfe075dc1b1dbd46c9072c7058`,
  `git ls-tree -r --name-only HEAD experiments/k1730` returns zero paths.
- The prerequisite task `k1730_salvage_ref_integrate_v2_closeout` is archived as
  `succeeded`, but its result says the bytes were reconstructed in the canonical
  working tree and handed to PHASE-Z; it gives no landing commit.
- The files remain reachable only through preservation/quarantine refs:
  - salvage: `edcb5b0d07e76b3d6380b88c66363abb491da3bb`
  - mixed-path quarantine: `6349aec586065b854849a0f59ff77efa05bd0979`
- The quarantine commit contains 56 unrelated paths as well as the K1730 suite.
  It is not a certified task-scoped merge and must not be treated as canonical
  input merely because the bytes are recoverable.

Therefore a compute job launched from canonical main would have no tracked
K1730 producer script, no pinned results artifact, and no reproducible cache to
reuse. Falling back to a quick-mode or quarantine copy would violate the task's
own prerequisite.

### 2. The requested shuffle repeats a withdrawn design

The preserved `experiments/k1730/REMEDIATION_v2.md` records the v1 full-sample
macro-tensor permutation as invalid for two independent reasons:

1. it destroys the macro block's serial dependence; and
2. it moves later releases ahead of earlier forecast origins, producing
   54,950 future-release cells out of 118,080 under the withdrawn design.

The preserved producer code consequently states that whole-sample permutation
can support neither a placebo nor a leakage interpretation. It replaced that
design with five non-circular positive lag shifts, re-ran the point-in-time
stamp check for every arm, and honestly labelled the resulting p-value floor
of 1/6 as a coarse placebo rather than a permutation test.

The current task proposes shuffling the same time-indexed macro block B=199
times. Reusing HAR/GEV-HAR fits lowers runtime, but caching does not repair the
transformation's causal or exchangeability defect. Holding the expanding-window
schedule fixed also does not help: the shuffled covariate values themselves can
still come from releases unavailable at the forecast origin.

### 3. The canonical helper is intentionally narrower

`src/volpred/stats/inference.py::exact_label_permutation` exhaustively permutes a
fixed count of Boolean group labels for a difference in means. Its contract is
appropriate only when those labels are exchangeable under the null. It does not
license arbitrary permutations of a serially dependent, release-vintaged macro
tensor. `monte_carlo_p_value` supplies the correct `(r+1)/(B+1)` finite-draw
calculation once a valid draw mechanism exists; it does not define that
mechanism.

### 4. The queued-cost premise is also stale

The preserved remediated production artifact reports approximately 13,448.6
seconds (3.74 hours) for one full arm, not 21 minutes for the full pipeline.
B=199 is therefore on the order of 743 CPU-hours before orchestration overhead
if the focal model is refit for every draw. Reusing the no-macro forecasts is a
sound cache invariant, but it removes only the restricted-model work; it does
not remove the focal GEV/SSVS refits. A future runner must shard the workload and
publish resumable draw receipts rather than enqueue one opaque monolith.

## Required successor contracts

### A. Canonical artifact recovery

Recover only the K1730 producer/claim-surface paths from the preservation refs
into a clean registered worktree. Re-run artifact, reproduce, lookahead,
README-alignment, and pinned-review gates. Integrate only through
`scripts/merge_worktree.sh` and prove the paths exist at canonical HEAD after
merge. A FAIL review may land as an honest record, but must not be relabelled
PASS. Do not merge the 56-path quarantine snapshot wholesale.

### B. Time-series randomization preregistration

Before writing a B=199 runner, specify:

- the exact transformation group or conditional draw law;
- why it is invariant/exchangeable under the stated null;
- how every generated macro cell remains available at its forecast origin;
- how serial and cross-variable dependence are preserved or intentionally
  conditioned upon;
- one fixed common scoring window and byte-identical no-macro cache contract;
- seed 42, unique-draw accounting, the `(r+1)/(B+1)` p-value, and a falsifiable
  synthetic-null/known-signal validation.

Non-circular positive lag shifts are a possible starting point because they can
remain causal after matched-window cropping, but increasing their count alone
does not make them an exact test. The successor must justify the randomization
null and transformation group rather than rename a denser placebo grid.

## Terminal statement

No compute job was enqueued, no result artifact was generated, and no research
verdict was changed. The current task is terminalized as a failed specification
with two durable successors. This prevents a roughly multi-hour detached run
from producing a precise-looking p-value for a known-invalid null distribution.
