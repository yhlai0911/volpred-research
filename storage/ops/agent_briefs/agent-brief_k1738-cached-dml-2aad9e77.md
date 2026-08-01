# K1738 cached DML continuation (split stage 2/2)

Work only in the registered worktree `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-9783132d-k1738` and only under `experiments/k1738/`. This is a bounded continuation of timed-out job `agent-brief_k1738-b377db`, not permission to rerun the original whole brief.

Read and obey `AGENTS.md`, `.claude/rules/experiments.md`, `.claude/rules/worktree.md`, `docs/error_log.md` relevant methodology incidents, the existing `experiments/k1738/README.md`, `experiments/k1738/checkpoint_manifest.json`, and the parent followup contract recorded in `/Users/yhlai0911/volpred-research/storage/ops/compute_queue/agent-brief_k1738-b377db.json`.

The checkpoint commit is `f258ae7a448d006d3f7d9ed89ddda16d0338232c`. First verify every identity in `checkpoint_manifest.json`; fail closed on any mismatch. Preserve the checkpoint and use only the frozen cache/panel. Do not download data and do not alter the preregistered success criteria.

Execute only the missing stages with the existing entrypoint and `--no-download`: primary cross-fitted DML, within-month-demeaned robustness, subperiod family, inclusive-window robustness, level-RV robustness, and Lasso-nuisance robustness. Keep seed 42. Every outcome window must start after the actual earnings announcement date; preserve explicit lag. DML must genuinely cross-fit. Apply the declared FDR families to all three horizons and all subperiod cells.

The IV exclusion restriction is a hard honesty gate. The interim JSON is internally suspicious because it says no credible instrument while `instrument_analysis.instrument_valid` appears true. Resolve this from the declared exclusion/relevance tests and code, not by choosing the favorable label. If no credible instrument survives, explicitly mark it invalid and cap every conclusion at conditional association; never claim causal ATE.

Produce a fresh, final `experiments/k1738/K1738_results.json` with `run_complete=true`, complete `stages_completed`, empty `stages_missing`, and no interim `insurance-artifact-no-DML` verdict. Generate sibling `experiments/k1738/reproduce_spec.json` at runtime with `finalize_experiment(...)`; verify its `canonical_result_identity` against the actual result bytes and pin the executed entrypoint identity. Regenerate README numbers only from the final JSON and label the seasonal-random-walk SUE proxy honestly (not analyst-consensus SUE).

Run `uv run pytest -q experiments/k1738/test_k1738.py`, `uv run python scripts/experiment_gates.py run --path experiments/k1738`, and `uv run python scripts/check_experiment_artifacts.py check --path experiments/k1738`. The artifact check may lack main-thread knowledge only; report that separately. Do not write shared memory, task-pool state, feed, paper, or files outside `experiments/k1738/`. Do not merge or remove the worktree. Leave the frozen final claim surface for a later independent fresh-context Codex review; do not manufacture a PASS verdict. Do not run bare Git mutations; the PHASE A collector will use the formal merge workflow after review.

Return exact hashes, run commands, data/sample dates and counts, DML/OLS/IV comparisons, multiplicity decisions, limitations, test/gate exits, and the exact final result path. NULL or invalid-IV conditional association is a valid result.
