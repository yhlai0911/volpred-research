# Issue #42 — Production Acceptance: Durable Fire Lifecycle

Production acceptance canary for GitHub Issue #42, executed post-reload against a
running supervisor daemon that carries commit `de63029c0` (`[codex] persist fire
lifecycle across self-reload #42`).

## Identity

| Field | Value |
| --- | --- |
| Acceptance task id | `issue42_production_fire_lifecycle_acceptance_20260727` |
| Job id | `06c75e969f6c4a1abea609e27ab54524` |
| Cohort id | `b978d7486de94d7baecfe7e3f6e7a36a` |
| Slot | 1 |
| Generation id | `78987568ef6747e28fcb1a977c33b6ff` |
| Lifecycle captured_at | `2026-07-26T19:39:01.541648+00:00` (UTC) |
| pre_fire_dirty entries | 16 |
| Managed workspace | `.claude/worktrees/dispatch-slot-1-06c75e96` (branch `worktree-dispatch-slot-1-06c75e96`) |

## Live-in-daemon evidence

The earlier attempt was correctly BLOCKED (not fabricated): the daemon running at
that time (pid 47886, started 2026-07-27T02:50:28+08:00) predated the feature
commit, so every in-flight job carried `fire_lifecycle=None`.

This acceptance runs against a reloaded daemon that postdates the commit:

- Feature commit `de63029c0` committed at `2026-07-27T03:21:22+08:00`
  (`2026-07-26T19:21:22+00:00` UTC).
- Running supervisor `pid 88234` started at `2026-07-26T19:37:32+00:00` UTC —
  16 minutes AFTER the commit, i.e. the self-reload has taken effect.
- `storage/ops/dispatch_state.json` records this exact job
  (`06c75e969f6c4a1abea609e27ab54524`, slot 1, phase running) with a non-empty
  `fire_lifecycle` containing `generation_id`, `captured_at`, and a 16-entry
  `pre_fire_dirty` snapshot.

Precondition ("this exact job has a non-empty fire_lifecycle") therefore holds
truthfully in production, so this doc is emitted rather than deferred.

## Why matching durable generation prevents post-reload PHASE-Z baseline loss

PHASE-Z commits **only the files this fire produced**. It does that by diffing the
working tree against a baseline snapshot captured at fire start (`pre_fire_dirty`
= the files already dirty before the fire touched anything). Any file dirty at
PHASE-Z that is NOT in that baseline is attributed to this fire.

Before Issue #42 the baseline lived only in the supervisor's in-memory process
state. When the supervisor self-reloaded mid-fire (scheduler/state/phase_z code
changes, or a scheduled restart), the new process started with an empty baseline.
At PHASE-Z it would then either:

- treat pre-existing dirty files (belonging to other slots / interactive
  sessions) as this fire's output and sweep them into the commit, or
- lose the true baseline entirely and mis-attribute the diff —

exactly the class of mis-attribution recorded in `docs/error_log.md` (2026-07-10).

Issue #42 persists the baseline as a **durable fire lifecycle** keyed by
`generation_id`, written to `storage/ops/dispatch_state.json` at fire start. After
a reload the successor process re-reads the lifecycle for the **same job id** and,
because the `generation_id` matches the generation that captured the baseline,
recovers the original `pre_fire_dirty` snapshot instead of starting blank. The
generation match is the guard: it proves the recovered baseline belongs to *this*
fire generation, so PHASE-Z's "new vs pre-existing" diff stays correct across the
reload boundary and cannot silently absorb another actor's uncommitted work.

This canary confirms the durable lifecycle is written and readable in a live,
post-reload daemon for job `06c75e969f6c4a1abea609e27ab54524`, generation
`78987568ef6747e28fcb1a977c33b6ff`.
