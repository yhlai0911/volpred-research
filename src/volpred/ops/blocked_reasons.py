"""Canonical controlled vocabulary for `task.blocked_reason`.

Single source of truth for BLOCKED_REASONS — imported by:
- `scripts/mark_task_blocked.py` (CLI to set / clear block on a task)
- `scripts/continue_task_dispatch.py` (dispatcher filter)
- any future tooling that needs to validate / list reasons

Drift was observed 2026-05-27 (mark_task_blocked had 7 entries, dispatcher had 9,
and K1383 used `diversity_rule_post_null_quartet` which neither knew about).
Adding new reasons here is the only sanctioned way to extend the vocab.

2026-07-20 (refactor_plan_ops_master WS-A3): the vocab gate now also covers the
`blocked_reason` FIELD on the canonical queue (audit in
``volpred.ops.next_tasks.write_tasks_to_handle`` + CI baseline in
``scripts/validate_next_tasks_status.py``). Two reasons were legitimized because
live sanctioned flows already wrote them (the vocab lagged the process):
``awaiting_codex_review`` (scripts/sync_next_tasks_status.py review-gate) and
``awaiting_owner_decision`` (pairs with status=blocked_on_user).
"""

from __future__ import annotations

BLOCKED_REASONS: frozenset[str] = frozenset(
    {
        "awaiting_external_data",           # auth / data not yet available (Dropbox, GCP)
        "awaiting_interactive_session",     # needs interactive Chrome / FB / UI-capable session
        "compute_runtime_incompatible",     # background agent timeout < experiment runtime
        "self_tagged_optional",             # task self-flags itself as optional / skippable
        "kid_collision",                    # K-id reuse — needs rename before dispatch
        "prior_attempts_failed",            # repeated failures; needs main-thread debug
        "deprecated",                       # superseded by another task / no longer relevant
        "codex_quota_reset_pending",        # ChatGPT-account daily quota exhausted — paired with blocked_until
        "paid_data_source_decision_pending",  # task gated on user/admin paid-API decision
        "diversity_rule_post_null_quartet", # paused per CLAUDE.md ML novel-method NULL-quartet diversity rule
        "awaiting_event_window",            # time-window wait (event_jobs not_before, observation windows) — paired with blocked_until
        "daily_cap_reached",                # task_type hit its per-day publish cap — paired with blocked_until=next local midnight
        "awaiting_codex_review",            # review gate: experiment done, Codex review artifact missing (sync_next_tasks_status.py)
        "awaiting_owner_decision",          # awaiting boss/owner sign-off — pairs with status=blocked_on_user
        "awaiting_main_thread_body_rewrite",  # narrative decision is final; paper body remains main-thread-only
        "external_compute_job_active",        # compute queue receipt owns execution until collection
        "external_compute_job_running",       # source task is fenced by a live compute child
        "external_compute_receipt_pending_collection",  # terminal job receipt awaits PHASE A
        "awaiting_prerequisite_fix",          # an identified prerequisite defect must land first
    }
)

WORK_SHADOW_CUTOVER_GATE = "work_shadow_cutover_ready_v1"
INCIDENT_SUSTAINED_CLEAN_GATE = "incident_sustained_clean_v1"
UNBLOCK_GATES: frozenset[str] = frozenset(
    {
        WORK_SHADOW_CUTOVER_GATE,
        INCIDENT_SUSTAINED_CLEAN_GATE,
    }
)


def is_valid(reason: str | None) -> bool:
    """Return True iff ``reason`` is a registered block reason."""
    if not reason:
        return False
    return reason.strip().lower() in BLOCKED_REASONS
