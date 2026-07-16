# Codex → Claude Code handoff — K1704

Generated: 2026-07-16 13:40 Asia/Taipei

## Why control returns now

- Direct readiness probe succeeded at 13:39: `claude -p --model claude-opus-4-8 ...` returned rc=0 and `CLAUDE_READY`.
- Per user instruction, Codex stopped taking new work once Claude quota/runtime recovered.
- K1719 remains owned by `codex-failover-slot-1-a56566ffb1624435bfc9191fc165edbc`; do not touch it.

## Current K1704 checkpoint

- Canonical task: `K1704`; owner before handoff: `codex-desktop-recovery-k1704`.
- Worktree: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704`
- Branch: `dispatch-slot-1-f217aefb-k1704`
- Current HEAD: `b1dd7fb4c9ec6b7206d1b9fecffb3a4c6f58b96a`
- Frozen post-run claim surface: `89644f548adac795ed28e4d336bc74ad6bc13585`
- Post-run review prompt: `experiments/k1704/post_run_review_prompt.md`
- Verdict template: `experiments/k1704/review_verdict.json` (still contains FILL values; do not certify yet)
- Worktree should be clean. No merge has occurred.

## Review / repair history

1. Initial primary pre-run review: FAIL. It caught mismatched OOS ledgers, stale raw-byte cache verification, silent forecast gaps, premature README results, no tests, consensus self-inclusion, and mislabeled HLN/DM.
2. Fixes added one common ledger, raw source byte re-verification, leave-one-proxy-out reliability centres, correct Newey-West HAC naming, tests, correct K1057 prior and Liu et al. DOI.
3. Delta pre-run review: PASS.
4. Fresh raw rebuild then correctly failed closed: 24 target-eligible origins lacked HAR forecasts.
5. First origin-ledger delta review: FAIL because eligibility incorrectly depended on forecast outputs and could hide estimator failure.
6. Final fix added independent `t-1` input-availability masks; input-available but invalid raw forecasts now raise; audit stores indices/count/hash; calibration happens after eligibility freeze.
7. Input-ledger delta review: PASS.
8. Formal rerun from the freshly raw-built cache, with 3,548 raw files re-read and size/SHA-256 verified: completed successfully.

## Verified formal results (not yet certified / not yet in knowledge)

- Data: 3,548 TX day-session days, 2012-01-02 to 2026-07-14.
- Common OOS ledger: 2,016 days, 2018-02-01 to 2026-07-14.
- Ledger SHA-256: `8d778f2407d606cbee63a903412dcc4527e50baeb83a141762eeb12266df75d6`.
- All six targets use identical `n_oos=2016` and QLIKE order `HAR_RV5 < EWMA_R2 < GJR_GARCH`.
- Every 10% stationary-bootstrap MCS is singleton `{HAR_RV5}`; both early/late consensus splits are also singleton HAR.
- Consensus QLIKE: HAR `0.1839`, EWMA `0.2405`, GJR `0.2593`; HAR is lower by about 23.5% / 29.1%.
- Full-OOS HAC DM: HAR-vs-EWMA `t=-4.63`; HAR-vs-GJR `t=-4.24`.
- Honest limitation: early-OOS MCS elimination p-values are `0.093`, near the 10% threshold; correlated 1/5/10-minute RV errors and latent-IV identification remain unresolved.
- Source audit: `raw_bytes_reverified=true`; expected byte inventory equals current byte inventory. `Daily_2026_07_15TX.csv` is listed only as an extra file outside the frozen canonical ledger.
- Tests: `6 passed`; `experiment_gates.py run --path experiments/k1704` PASS.
- Visual QA completed for `K1704_qlike_by_proxy.png` (2070×1152); labels and values match results.

Do not write `storage/memory/knowledge.json` or state a final scientific conclusion until independent post-run PASS and certification.

## Exact continuation

1. Start by reading this file and `experiments/k1704/post_run_review_prompt.md`.
2. Queue the independent read-only post-run review (heavy/long work stays in compute queue):

   ```bash
   uv run python scripts/compute_queue.py enqueue \
     --id k1704-post-run-review-20260716 \
     --title 'K1704 independent post-run review' \
     --script /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/scripts/codex_review_job.sh \
     --interpreter bash \
     --script-args \
       /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/k1704/post_run_review_prompt.md \
       /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/k1704/post_run_review.md \
       1800 \
     --result-artifact /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/k1704/post_run_review.md \
     --output-path /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/k1704/post_run_review.md \
     --timeout 2100
   ```

3. Collect the review. If FAIL, fix only in the worktree, rerun tests/results when claim-surface code changes, freeze a new template, and re-review. If PASS, copy the review's exact `VERDICT_JSON` into `review_verdict.json` and verify every reviewed hash still matches.
4. Commit review + verdict in the worktree, then run:

   ```bash
   uv run pytest -q experiments/k1704/test_K1704.py
   uv run python scripts/experiment_gates.py run --path experiments/k1704
   uv run python scripts/experiment_gates.py certify --path experiments/k1704
   ```

5. From main, merge only through `bash scripts/merge_worktree.sh dispatch-slot-1-f217aefb-k1704`; never force-remove a worktree. Verify merged files and rerun the same gates/tests on main.
6. Claude main thread then uses the canonical K1259-gated knowledge writer for the narrow claim, updates `research_program.md` / `storage/work_log.json` as required, derives publication work if appropriate, and completes canonical task `K1704`.

## Timeout rule added during this takeover

- Main commits `4b215dab4` and `c8e44a98b` enforce: first execution timeout → `split_required`; identical retry is rejected; child stages require parent id, stage name and shorter budget. Auth/quota before work starts is the only unchanged-retry exception.
- The stale K1711 whole-task redispatch row was closed after confirming its salvage → evaluation → review recovery and canonical knowledge entry already existed.

## Shared-main cautions

- Shared main was dirty from concurrent workers; preserve unrelated changes.
- Main commits must use `scripts/git_writer_lock.py commit -- <exact paths>`; never raw `git add` / `git commit` on shared main and never push.
- Codex did not edit `storage/memory/knowledge.json` for K1704.
