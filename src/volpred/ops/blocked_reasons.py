"""Canonical controlled vocabulary for `task.blocked_reason`.

Single source of truth for BLOCKED_REASONS — imported by:
- `scripts/mark_task_blocked.py` (CLI to set / clear block on a task)
- `scripts/continue_task_dispatch.py` (dispatcher filter)
- any future tooling that needs to validate / list reasons

Drift was observed 2026-05-27 (mark_task_blocked had 7 entries, dispatcher had 9,
and K1383 used `diversity_rule_post_null_quartet` which neither knew about).
Adding new reasons here is the only sanctioned way to extend the vocab.
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
    }
)


def is_valid(reason: str | None) -> bool:
    """Return True iff ``reason`` is a registered block reason."""
    if not reason:
        return False
    return reason.strip().lower() in BLOCKED_REASONS
