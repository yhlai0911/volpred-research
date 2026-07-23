# Refactor plan: dispatch work admission and deadline semantics

**Trigger:** `dreaming_persistent_alert_800782d7aa16a35c`  
**Opened:** 2026-07-23 (Three-Strike)  
**Status:** contained; admission redesign remains open

## Finding

The alert key `supervisor hang_killed` reached 12 sends between 2026-07-11 and
2026-07-22, but it did not represent one failure class. The transport key was
grouping three distinct events under one title:

| Sends | Evidence | Root-cause class | Disposition |
|---:|---|---|---|
| 1-3 | Three workers ended at 3001.3s while waiting for unbounded agentic children | Long child work placed inside a bounded fire | Fixed by `5aa8cd180`: agent work goes through the detached compute queue and the fire-scoped class gate blocks unbounded agentic CLIs |
| 4-5 | `b55db3be` and `fb33cf37` ended at 3001.1s/3002.6s; their platform work was later completed by successor fires | Ordinary task scope exceeded the 3000s fire container | Still an admission problem |
| 6-11 | Workers exited 143 at 131-961s, including two whole cohorts killed nearly simultaneously; sidecars showed healthy work | External SIGTERM was classified as hang | Fixed by `23b8063de`: raw external signals now produce `external_signal`, release claims, and never emit hang CRITICAL |
| 12 | `15911366` ended at 3001.4s after 64 active turns; its sidecar was still dispatching a Bash tool at the deadline, and the task later succeeded under Codex failover | Ordinary task scope exceeded the 3000s fire container | Still an admission problem |

The original detector was re-run against live `alert_dedup.json` before this
audit: 12 sends, last at `2026-07-22T02:47:16.606179+00:00`. The subsequent
completion ring contains 41 successful fires and no further timeout, but that
quiet window is not a root-cause fix.

## Containment landed with this plan

The supervisor now labels a confirmed configured-deadline kill as
`supervisor work_timeout` at WARN, with its own dedup identity. It keeps the
existing `killed_timeout` receipt and immediate claim release. A kill that
leaves survivors, an unverified target, or a non-deadline watchdog finding
continues to use `supervisor hang_killed` at CRITICAL.

This is a semantics correction, not the admission fix: reaching the configured
cap proves that work did not fit its container; it does not prove that the
worker was wedged. The split prevents dreaming from aggregating deadline,
external-signal, and orphan failures into one false persistent root cause.

## Root-cause redesign

### 1. Make execution budget part of the task contract

Every dispatchable task needs a machine-readable execution decision, not a
prose guess made after claim:

- `execution_mode`: `inline` or `detached`
- `budget_seconds`: an upper bound for the selected mode
- `split_contract`: required when a previous inline execution hit its cap
- `compute_job_id`: required while detached work is live

Tasks without this metadata may still run inline only when their task type and
requested actions are in an allowlisted short-work class. Experiment runs,
multistart estimation, full backtests, agentic reviews, and descriptions that
explicitly require multi-hour observation are detached by construction.

### 2. Put the gate before claim/start

The single owner should be task selection, before the task becomes
`in_progress`. The selector must return exactly one of:

- `inline_admitted`
- `detached_enqueue_required`
- `split_required`
- `blocked_missing_execution_contract`

Prompt wording remains useful guidance but is not enforcement. A task rejected
for inline execution must be enqueued through the canonical compute queue in
the same transaction or left pending with a precise reason; it must not be
started and then rely on the watchdog to discover its size.

### 3. A work timeout cannot be retried unchanged

When an inline task reaches its cap, annotate the task with the completion
receipt and require either a smaller split or detached execution before it is
eligible again. This mirrors the compute queue's existing
`identical_retry_prohibited` contract. Re-pending the same scope unchanged only
turns a deterministic deadline into an hourly retry loop.

### 4. Keep incident identities granular

The incident layer should fingerprint `work_timeout`, `external_signal`, and
`hang_killed` separately. A title-level hash is sufficient only after the
producer uses truthful, mutually exclusive titles. Deadline events may
escalate on repeated unchanged task scope; orphan/hang incidents escalate on
survivors or failed liveness verification.

## Acceptance gates

1. A synthetic over-budget task is routed to detached execution before claim;
   the inline worker is never spawned.
2. A task with a prior work-timeout receipt cannot be admitted unchanged;
   adding a valid split contract or detached job makes it eligible.
3. An own-deadline kill emits `supervisor work_timeout` WARN and preserves
   claim re-pend; no `supervisor hang_killed` notification is sent.
4. A failed kill with live survivors still emits `supervisor hang_killed`
   CRITICAL and quarantines the slot.
5. Replaying the 12-event evidence set yields three incident classes rather
   than one persistent signature.
6. Production observation remains clean for at least 48 hours after admission
   enforcement before this plan can be marked `root_cause_fixed_and_verified`.

