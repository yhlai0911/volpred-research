# K1731 arm B rev9 — bounded canonical claim-surface remediation

**Model**: claude-opus-4-8 / xhigh (per model_router)
**Source task**: `assign_k1731_rev9`
**Worktree / cwd**: `.claude/worktrees/dispatch-slot-1-bd00f90a-k1731`
**Blocking verdict**: canonical
`storage/ops/codex_reviews/k1731_armB_rev8_verdict.md`

This is a narrow remediation of the round-8 FAIL. Read the repository
`AGENTS.md`, the full round-8 verdict, and the current K1731 files before
editing. The worktree already contains commits after frozen target
`bb57bda984475a4732051b8f96a09697bb9f7236`; preserve all of them. Do not
reset, revert, or overwrite later work.

## Scope

1. In
   `experiments/k1731/k1731_finalize_report.py`, fix
   `ARM_A_ENGINE_ISSUES[0].why_it_matters`. It must not call low PIP
   "evidence of no effect", say that an arm-B null rests on it, or imply an OOS
   null. The strongest supported interpretation is weak in-sample selection
   under the stated prior; explicitly say this does not establish an OOS null.
2. Regenerate all three canonical result JSON files with the finalizer. Never
   hand-edit generated JSON.
3. Extend `experiments/k1731/k1731_armB_verification.py` so the artifact claim
   scan covers every `armA_engine_issues` entry in all three artifacts. Add a
   real negative control proving a residual null phrase on that surface makes
   the verifier exit nonzero.
4. Strengthen `experiments/k1731/k1731_rev8_drift_check.py` so numeric
   additions and removals fail the gate, not only changed values. Add regression
   tests or executable negative controls for both an added and a removed numeric
   leaf.
5. Run the complete current lightweight ratchet and drift suite, including the
   nested-DM checks, arm-B verification, canonical regeneration comparison, and
   the 3,834-leaf regression/drift gates. Do not rerun estimation, GARCH MLE,
   bootstrap, or any full backtest.
6. Build a fresh round-9 freeze manifest over the complete current claim
   surface. Pin the committed worktree bytes, not a dirty intermediate state.

## Hard invariants

- Estimated numeric leaf changes/additions/removals must all remain zero after
  canonical regeneration. Renamed numeric values must remain exact.
- The three artifacts' provenance invariants (`is_primary`, `do_not_cite`, and
  supersession fields) must remain intact.
- Do not merge the worktree, write `knowledge.json`, change the task pool,
  publish anything, or modify unrelated experiments.
- Do not invoke a long Codex review from inside this agent. A later PHASE A
  collector will submit the frozen commit through
  `scripts/codex_review_job.sh`.
- Commit only the scoped worktree changes. The commit message must contain
  `assign_k1731_rev9` so the task/worktree collision guard can identify it.

## Required result artifact

Write
`experiments/k1731/k1731_armB_rev9_remediation.json` with at least:

- `source_task_id`
- `base_commit`, `result_commit`, and freeze-manifest path
- exact changed-file list
- canonical regeneration command and exit status
- numeric changed/added/removed counts
- renamed-value exactness result
- verification commands and exit statuses
- negative-control evidence for the residual-null phrase
- negative-control evidence for numeric addition and removal
- `ready_for_codex_round9` (true only if every required gate passes)
- `blocking_issues`

If any invariant or gate fails, record the exact evidence, set
`ready_for_codex_round9` to false, commit the bounded diagnostic artifact if
safe, and stop. Research honesty takes priority over making the round pass.
