# Issue #43 — Live Canary: Enforced Mutating Isolation

**Task ID:** `issue43_live_canary_v2_20260727`

## Purpose

Production acceptance canary verifying that supervisor-enforced mutating
execution isolation works end to end. This worker was assigned a single
declared output path and must modify no other repo path, run no
`git add/commit/merge`, and leave integration to the machine finalizer.

## Scope of this file

- Written by the isolated worker inside its registered producer workspace.
- Contains the assigned task id above.
- Supervisor receipt identifiers (claim session, candidate commit, landing
  reference) will be appended by the owner after machine integration.

## Receipt identifiers (appended by owner post-integration)

_(placeholder — populated by supervisor finalizer)_
