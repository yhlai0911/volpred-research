# Temporary Copilot repair request — MUST NOT MERGE

Tracking: Issue #9, architecture contract #62.

This file exists only to create an isolated Draft PR for the coding agent. The implementer MUST delete this file before the PR can become Ready.

Required permanent diff:

- `scripts/compute_queue.py`
- `tests/test_repend_claim_ownership.py`

Repair:

1. Import and use canonical `volpred.ops.next_tasks.clear_claim_ownership`.
2. In `_release_collected_source_task` and `_release_cancelled_source_task`, clear claim ownership immediately before transitioning the source task to `pending`.
3. Remove both functions from `KNOWN_UNCONVERTED_REPEND_SITES`.
4. Add behavioral tests carrying stale claim fields through both real release functions and verify the real Work Coordinator legacy reconciler emits no `invalid_lifecycle` issue.
5. Preserve source-task settlement, lock ordering, status history, WorkItem identity and multi-agent isolation semantics.
6. Run focused re-pend/compute queue tests, canonical-writer audit, py_compile and `git diff --check`.
7. Do not alter soak timestamps, cutover criteria, workflows, storage, config, paper, research data or model behavior.
8. Delete this temporary request file before marking Ready.

Trigger note: semantic no-op update to launch the already-registered one-shot repair workflow. This note must disappear with the sentinel before merge.
