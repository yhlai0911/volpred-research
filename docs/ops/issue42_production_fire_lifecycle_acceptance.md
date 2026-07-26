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

Before Issue #42 the baseline was persisted only as one transitional singleton
under that checkout's `<git-dir>`.  It was not bound to an exact job, cohort, or
generation.  When self-reload landed between worker completion and closeout, the
successor process could not prove that the singleton belonged to the pending
fire.  The observed production result was therefore fail-closed but incomplete:
PHASE-Z reported `no fire-start baseline`, declined the commit, preserved the
dirty files, and treated that closeout token as terminal; the file author then
had to confirm and commit the work manually.  Reusing a current or stale singleton
to avoid that refusal would have reintroduced the cross-session mis-attribution
class recorded in `docs/error_log.md` (2026-07-10), so guessing was not an
acceptable repair.

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

## Terminal read-back

- The worker committed this document as `e08db4da3f042cf35fb7a928e25c54cee46d19d9`.
- The workspace finalizer wrote `terminal_intent`, then a `finalized` receipt
  with `disposition=merged`, `gated_head_sha=e08db4da3…`, and
  `main_sha=74735c9f2a45a054b1f4216a2b3affbe3adb7e5e`.
- Git read-back confirms `e08db4da3…` is an ancestor of that main SHA.
- While the canary was still running, jobs `35badc1d…` and `ea14dc76…` joined
  cohort `b978d748…`; live state showed all three jobs carrying the exact same
  generation `78987568…` and the same 16-path baseline.
- PHASE-Z correctly deferred after the canary merged because two cohort siblings
  were still running.  No baseline-missing fallback was used for this fire.
