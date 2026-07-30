# Snapshot — event_article routing before Operations Core cutover

- Captured at: 2026-07-30 14:18 Asia/Taipei
- Repository HEAD: `6688f6e6d4773783a749faaa5e186b5792a5d400`
- Canonical file: `.claude/rules/task-routing.md`
- Canonical file SHA-256:
  `fe812940d513a3b7efde9e71be03c7c6e65b79c6612e616d323b505b92a5a40f`
- Trigger: owner-directed full Operations Core replacement and autonomous
  operation; the FOMC T+0 live regression proved that `main_thread-only`
  leaves a correctly materialized P1 event task without a legal executor when
  no interactive desktop session is open.

## Pre-change contract

The routing matrix says `event_article` is Claude-only, Codex-ineligible,
one-at-a-time, and requires main-thread judgement. The decision tree groups it
with other Claude main-thread workflows.

## Intended bounded change

Preserve Claude-only, Codex hard-deny, one-at-a-time, `feed-publisher`, direct
published, and Facebook dual-publish requirements. Change only the execution
owner from an interactive Claude session to an Operations Core Claude
subscription worker. `scripts/model_router.py` remains the sole topology owner;
the governance rule must not duplicate its `inline` value.

Rollback is the exact canonical file blob identified by the SHA-256 above.
