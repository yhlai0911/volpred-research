---
name: schedule-operations
description: Inspect, change, reconcile, or verify VolPred schedules. Use for Operations Core jobs, cadence changes, owner conflicts, missed fires, schedule rollback, or liveness audits.
---

# Operate schedules

`config/runtime_schedules.json` is the schedule specification. Resolve its active fields at
invocation time. Operations Core is the only business clock while
`schedule_materialization.mode=active`.

## Workflow

1. Read the target job, schedule generation, active mode, retry/catch-up policy, and current owner.
2. Read `storage/ops/schedule_receipts.json` and the job's downstream receipt before diagnosing
   a missed or duplicate fire.
3. Use `scripts/reconcile_schedule_owners.py` in preview mode to census all possible owners.
4. Change the canonical config or owning wrapper first. Do not recreate an alternative clock.
5. Reconcile owners as one transaction.
6. Verify:
   - exactly one active clock owner;
   - an immutable fire identity and terminal schedule receipt;
   - the expected downstream acknowledgement;
   - no stale clock surface reappeared.

## Rollback

Rollback is also an owner transaction: change generation, mode, or active ownership in the
canonical spec, reconcile, then verify the next owner-specific receipt. Do not restore a single
clock surface by hand.

If the documented command or owner does not exist in the current code, stop and create an
implementation task rather than inventing a schedule path.
