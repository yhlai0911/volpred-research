---
name: host-migration
description: Guide a VolPred host capture, standby parity check, cold restore, failover rehearsal, or primary promotion. Use only when the user explicitly requests host migration or failover work.
---

# Migrate a host

This is a rare, high-risk operator workflow. Read `config/host_migration_manifest.json`,
`docs/host-migration.md`, and the current host-migration section of `docs/architecture.md`.
Use `scripts/guided_host_migration.py` only after verifying its current interface.

## Select one branch

- **Capture and compare:** create signed source/target snapshots, identity-bound parity, and a
  dry-run plan with no performed mutations.
- **Cold restore:** restore only allowlisted artifacts; do not copy source secrets, browser
  sessions, desktop subscriptions, schedules, or primary authority.
- **Promotion:** proceed only with fresh signed parity, permission receipts, RPO/RTO evidence,
  rollback rehearsal, and explicit user authority.

## Invariants

1. Capture from clean, stable Git identities.
2. Bind bytes, symlink kind, executable mode, runtime tools, permissions, and capability receipts.
3. Reauthorize secrets and subscriptions on the target; never transfer their values.
4. Keep the target shadow-only until every promotion gate passes.
5. Preserve lease fencing and fail closed on a missing ledger, stale signature, identity drift, or
   incomplete cross-host evidence.

## Completion

Capture completes with a persisted signed plan that authorizes no primary lease. Cold restore
completes with zero copied secrets, zero installed schedules, and fresh parity. Promotion completes
only after the target obtains the canonical lease and rollback/readback evidence proves the source
cannot continue as a second owner.
