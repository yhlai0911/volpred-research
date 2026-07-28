# K1731 arm B — Codex round 11 review (rev12, read-only)

**This is the first round that actually reaches the arm-B rev10 claim surface.** Round 10 never got
there: 3 of 35 freeze-manifest entries did not match their bytes, so certification stopped before any
claim was read. rev11 re-froze the claim surface atomically (43/43). rev12 fixed a crash in the gate
runner itself — **not one line of statistical content**. So treat this as a substantive first review,
not a re-review.

## Scope — READ ONLY

Review root: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/`
Branch `wt/dispatch-slot-1-bd00f90a-k1731` @ `223f85081172481d7f4a1b7b6bac60b877b43a84`.

- `k1731_armB_rev12_gatefix_report.json` — the authors' account of the rev12 gate repair
- `k1731_armB_rev11_freeze.txt` (43 entries) and `k1731_armB_rev11_freeze_selfcheck.json`
- the frozen claim surface itself: results JSONs, `README.md`, `reproduce_spec.json`, the analysis
  and production scripts named in the manifest
- prior verdicts under `storage/ops/codex_reviews/`

**Do not modify anything, do not re-run the experiment, do not merge.** Output is the verdict file only.

## Context you need to judge scope honestly

This worktree's base is **1,143 commits behind main** (merge-base `a2bcd7e14`, 2026-07-18). The rev12
crash (`experiment_gates.py:157 TypeError: scan_file() takes 1 positional argument but 2 were given`)
came from that staleness: the gate module was written against current-main auditor signatures while
the branch carried older ones. The authors repaired it by path-scoped extraction from main
(`git show main:<path>`), and report that **two** files were inconsistent, not the one their brief
predicted — they corrected their own brief rather than matching it.

## Already verified by the main thread (do not re-spend effort, but challenge if you disagree)

- **Freeze integrity, independently recomputed**: the manifest parses to 43 entries; 5 sampled at
  random were re-hashed from disk and every one matched. The authors' own independent recheck
  (a standalone script sharing no code with `experiment_gates.py`, run twice — before and after all
  fixes) reports 43/43 matched, 0 mismatched, 0 missing, 0 unreadable, and agrees with
  `..._selfcheck.json` on every field.
- **Gates re-run from scratch by the main thread**: `experiment_gates.py run --path experiments/k1731`
  → exit 0, 14 files, 4 methodology gates, **0 violations**, nothing relaxed/skipped/re-thresholded.
- **The 3 pytest failures are a stale-base artifact, confirmed not asserted**: all three assert
  against `scripts/compute_queue.py`, which this branch never touched. The main thread ran those same
  three tests on canonical main — **all 3 pass there**. Round 11's own suite is green in the worktree
  (12 passed / 0 failed, including all five freeze-integrity tests).
- **Spec/disk consistency**: `reproduce_spec.entrypoint.path = run_corrected_rev5_production.py`,
  on-disk sha256 `35f74d4c2a39d50c…`, identical to freeze-manifest line 55.
- **Artifact gate**: PASS (strict). Note the authors materialised `check_experiment_artifacts.py`
  from main's blob to run it and did **not** commit it to the branch — verify that claim.

## Your job

### 1. The arm-B claim surface — the actual review
Round 10 never reached this. Review the substantive content: the estimator and specification, the
lookahead discipline, the inference (including any bootstrap / multiplicity handling), whether the
stated verdict follows from the numbers in the frozen results, and whether `README.md` reconciles
with those results digit by digit. **Assume nothing has been reviewed before.**

### 2. Did the rev12 repair stay inside its bounds?
The authors claim both diffs are purely the root-threading change (a `root` parameter added;
`path.relative_to(REPO_ROOT)` → `path.relative_to(root)`), with no detection logic, verdict set or
threshold altered, and that call sites were deliberately **not** degraded to single-argument form
because that would reintroduce worktree-prefixed keys. Verify this by reading the diffs. A weakened
gate hidden inside a "crash fix" is the failure mode to hunt for.

### 3. Is the freeze the right freeze, over the right surface?
43 entries — confirm the manifest actually covers the full claim surface (no result, script or README
that a claim depends on is left unfrozen), and that the newest freeze is the one enforced.

### 4. Residual divergence
The report declares one item under `gate_fix.class_sweep.residual_divergence_reported_not_changed`.
Judge whether leaving it unchanged is defensible or whether it contaminates any claim.

## Output contract

Write the verdict to `storage/ops/codex_reviews/k1731_r11_verdict.md`.

**First non-empty line must be exactly `VERDICT: PASS` or `VERDICT: FAIL`.** Then, per area
(claim surface, rev12 scope, freeze coverage, residual divergence): `PASS` / `BLOCKING` /
`NON_BLOCKING`, with file and line for anything you fault. If you FAIL, state each blocking defect so
it can be fixed without another round of clarification.
