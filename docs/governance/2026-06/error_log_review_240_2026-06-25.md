# Error Log Governance Sweep 240 - 2026-06-25

## Trigger

`governance_error_log_review_240` was opened because `docs/error_log.md`
crossed the 240 top-level incident bucket. The task brief required reading
recent entries, identifying recurring root-cause patterns, and running
`scripts/audit_silent_fallbacks.py --json` when silent fallback appeared in the
cluster.

## Recent Cluster

Reviewed recent error-log entries from 2026-06-14 through 2026-06-25. The
dominant patterns are:

1. **Fail-open without observability**: mirror sync 401, digest test leakage,
   rolling-z invalid windows, gmail poll timeout, release-pool skip flags, and
   piggy-back schedule staleness all involved a path where the system preserved
   runtime continuity but hid the degraded source or wrong clock.
2. **Upstream/downstream gate mismatch**: refill/trending/task generation
   repeatedly produced work that publisher/release gates would later reject.
   This shows publisher gates need corresponding upstream pre-checks.
3. **Current artifact selection drift**: paper-update PDF selection, PRG
   submission-ready status, and K1416 uniqueness language all came from a
   downstream artifact retaining stale status after the source-of-truth changed.
4. **Metric/time-alignment bugs**: K445 origin-vs-target forecast alignment,
   K802 Basel/Student-t scaling, K783c inverse QLIKE, and MOVE/VIX NaN boolean
   handling show that source review must inspect local metric helpers, not just
   article/JSON consistency.
5. **Test/prod boundary weakness**: the digest drift incident came from test
   fixtures writing production-like rows; production write chokepoints need
   default test guards and read-back verification.

## Silent Fallback Audit

Command:

```bash
uv run python scripts/audit_silent_fallbacks.py --limit 12
uv run python scripts/audit_silent_fallbacks.py --strict --baseline storage/qa/silent_fallback_baseline.json --limit 20
```

Results after this sweep:

- Current findings: 99.
- Baseline findings: 126.
- New findings against baseline: 0.
- Resolved baseline findings: 27.
- By root: `scripts=61`, `src=38` after fixing new findings.
- Top remaining paths before future burn-down: `scripts/indicator_arena_daily.py`,
  `scripts/build_experiments_index.py`, `scripts/dispatch_supervisor/*`,
  `scripts/work_dashboard_server.py`, `src/volpred/ops/summaries.py`.

Four new baseline-exceeding findings were fixed during this sweep:

- `scripts/refill_task_pool.py`: legacy date-only `completed_at` skip now has
  `silent-ok` justification.
- `scripts/refill_task_pool.py`: dominant-cluster and cluster-classification
  fail-open paths now emit refill diagnostics.
- `src/volpred/ops/content.py`: malformed `release_dedup_skipped_at` now emits
  a release-pool warning before re-evaluation.
- `src/volpred/ops/content.py`: malformed `published_at` now emits a
  release-pool warning before treating the item as due.

The audit tool's human output now prints `by_action`, `by_root`, and `top_paths`
summaries before row-level findings. This keeps governance sweeps from
degrading into a long ungrouped JSON list.

## Rules Reinforced

- Fail-open is allowed for ops continuity; silent is not.
- Every publisher or release gate that can reject work needs an equivalent
  upstream pre-check in the refill/materialization layer.
- Any paper-local status artifact (`README.md`, `SUBMISSION_READY.md`,
  checklist) must be updated when `research_program.md` or a later experiment
  supersedes the paper's readiness state.
- Rolling-window indicators must separate invalid windows from false/zero
  signals and write valid sample counts into results.
- Tests that exercise publishing/sync paths must default to
  `VOLPRED_NO_REMOTE_WRITE=1` and stub the exact imported write function.

## Verification

```bash
uv run python scripts/audit_silent_fallbacks.py --strict --baseline storage/qa/silent_fallback_baseline.json --limit 20
uv run pytest tests/test_silent_fallback_audit.py
uv run python -m py_compile scripts/audit_silent_fallbacks.py scripts/refill_task_pool.py src/volpred/ops/content.py
```

All passed on 2026-06-25.
