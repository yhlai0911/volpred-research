"""Pure selection policy for the legacy ``next_tasks`` claim path.

The file-backed CLI owns locking and mutation.  This module owns the claim
admission and ranking decision so read-only replay can execute the same policy
without touching the live queue.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import re
from typing import Any, Iterable, Mapping

from .next_tasks import (
    is_main_thread_reserved,
    normalize_dispatch_lane,
    priority_sort_key,
)
from .dreaming_revalidate import requires_live_revalidation
from .task_urgency import (
    LANE_DEFERRED,
    LANE_SCHEDULED,
    LANE_TIME_CRITICAL,
    LANE_URGENT,
    classify as classify_urgency,
)
from .timestamps import parse_iso_warn


CODEX_ELIGIBLE_TASK_TYPES = frozenset(
    {
        "platform_ops",
        "experiment",
        "governance",
        "code_review",
        "paper_review",
        "daily_article",
        "daily_digest",
    }
)
# Capability is a task-type contract, not metadata preference.  Every type in
# this set requires a Claude-owned lifecycle; malformed `preferred_agent=codex`
# must never turn that into a Codex claim.
CLAUDE_ONLY_TASK_TYPES = frozenset(
    {
        "email_reply",
        "event_article",
        "member_qa",
        "paper_body",
        "paper_decision",
        "strategy_lifecycle",
        "telegram_reply",
        "trending_repost",
    }
)
CODEX_HARD_DENY_TASK_TYPES = CLAUDE_ONLY_TASK_TYPES

# Two Claude-only types are intentionally executed by an Operations Core
# Claude worker.  The rest require an interactive/responder lifecycle and are
# excluded from the generic background candidate pool as well.
GENERIC_BACKGROUND_HARD_DENY_TASK_TYPES = CLAUDE_ONLY_TASK_TYPES - {
    "event_article",
    "member_qa",
}
DISPATCH_MUTATING_TASK_TYPES = frozenset({"platform_ops", "governance"})
SINGLE_FLIGHT_TASK_TYPES = frozenset({"event_article"})
_ACTIVE_STATUSES = frozenset({"claimed", "in_progress"})
_CLAIMABLE_STATUSES = frozenset(
    {"pending", "pending_main_thread", "claimed", "blocked", ""}
)


@dataclass(frozen=True)
class LegacyClaimDecision:
    task_id: str
    owner: str
    eligible: bool
    primary_reason: str
    reason_codes: tuple[str, ...]
    policy_codes: tuple[str, ...]
    rank_key: tuple[int, str] | None
    status: str
    dispatch_lane: str
    preferred_agent: str
    claimed_by: str | None
    deadline_at: str | None


@dataclass(frozen=True)
class LegacyClaimSelection:
    selected_task_id: str | None
    eligible_task_ids: tuple[str, ...]
    decisions: tuple[LegacyClaimDecision, ...]
    selected_index: int | None
    eligible_indexes: tuple[int, ...]

    def decision_for(self, task_id: str) -> LegacyClaimDecision:
        matches = tuple(
            decision
            for decision in self.decisions
            if decision.task_id == task_id
        )
        if not matches:
            raise LookupError(f"decision identity not found: {task_id}")
        if len(matches) > 1:
            raise ValueError(f"ambiguous decision identity: {task_id}")
        return matches[0]


@dataclass(frozen=True)
class TaskIdentityResolution:
    task_id: str
    matching_indexes: tuple[int, ...]
    reason_code: str


def task_identity(task: Mapping[str, Any]) -> str:
    """Return the exact identity used by the file-backed production CLI."""

    return str(task.get("id") or task.get("task_id") or "")


def resolve_task_identity(
    tasks: Iterable[Mapping[str, Any]],
    task_id: str,
) -> TaskIdentityResolution:
    """Resolve the production direct-claim uniqueness gate without mutation."""

    candidates = tuple(tasks)
    normalized = str(task_id or "")
    matching_indexes = tuple(
        index
        for index, task in enumerate(candidates)
        if task_identity(task) == normalized
    )
    if not normalized:
        reason_code = "missing_task_id"
    elif not matching_indexes:
        reason_code = "task_not_found"
    elif len(matching_indexes) > 1:
        reason_code = "duplicate_task_id"
    else:
        reason_code = "unique_task_id"
    return TaskIdentityResolution(
        task_id=normalized,
        matching_indexes=matching_indexes,
        reason_code=reason_code,
    )


def normalize_task_type_value(value: object) -> str:
    """Canonical spelling shared by claim, dispatch, routing, and reporting."""
    return re.sub(r"[-_\s]+", "_", str(value or "").strip().lower()).strip("_")


def normalized_task_type(task: Mapping[str, Any]) -> str:
    return normalize_task_type_value(task.get("task_type"))


def requires_supervisor_preassignment(task: Mapping[str, Any]) -> bool:
    """Whether an hourly/failover worker needs supervisor-bound execution.

    This predicate is shared by the dispatcher menu and the claim mutation
    gate.  Keeping the two decisions together prevents a starvation lockout
    from offering a generic worker only tasks that its claim CLI must reject.
    Main-thread lanes are excluded because they have a different owner rather
    than a missing supervisor preassignment.
    """

    return (
        normalized_task_type(task) in DISPATCH_MUTATING_TASK_TYPES
        and not is_main_thread_reserved(dict(task))
    )


def is_codex_owner(owner: str) -> bool:
    normalized = str(owner or "").strip().lower()
    return (
        normalized == "codex"
        or normalized.startswith("codex-")
        or normalized.startswith("codex_")
    )


def is_codex_eligible_task(task: Mapping[str, Any]) -> bool:
    status = str(task.get("status") or "").strip().lower()
    if status == "pending_main_thread":
        return False
    lane = normalize_dispatch_lane(dict(task))
    if lane in {"main_thread", "blocked"}:
        return False
    task_type = normalized_task_type(task)
    if task_type in CODEX_HARD_DENY_TASK_TYPES:
        return False
    if task_type in CODEX_ELIGIBLE_TASK_TYPES:
        return True
    preferred_agent = (
        str(task.get("preferred_agent") or task.get("target_agent") or "")
        .strip()
        .lower()
    )
    return preferred_agent == "codex"


def single_flight_blocker_task_id(
    tasks: Iterable[Mapping[str, Any]],
    target: Mapping[str, Any],
) -> str | None:
    """Return the active sibling that owns a serialized task-type lease.

    The caller must invoke this while holding the canonical queue's exclusive
    lock.  That makes the read-and-claim transition atomic across worker
    processes instead of relying on the current production slot count.
    """

    task_type = normalized_task_type(target)
    if task_type not in SINGLE_FLIGHT_TASK_TYPES:
        return None
    target_id = task_identity(target)
    for candidate in tasks:
        if task_identity(candidate) == target_id:
            continue
        if normalized_task_type(candidate) != task_type:
            continue
        if str(candidate.get("status") or "").strip().lower() in _ACTIVE_STATUSES:
            return task_identity(candidate)
    return None


def task_rank_key(task: Mapping[str, Any]) -> tuple[int, str]:
    """Return the production ``next_tasks list`` priority/id ordering key."""

    task_id = task_identity(task)
    return (
        priority_sort_key(task.get("priority"), default=999),
        task_id,
    )


def dispatch_admission_rank_key(
    task: Mapping[str, Any],
) -> tuple[int, int, str, str]:
    """Put canonical immediate lanes ahead of mutating preassignment.

    ``continue_task_dispatch`` uses :mod:`task_urgency` as the single lane
    owner.  The supervisor consults this key before deciding whether to bind a
    mutating workspace or leave the fire generic, so an urgent/time-critical
    task cannot be displaced by the mutating subset.  This is deliberately not
    the scheduled-menu selector: starvation, rotation and collision policy
    stay owned by ``continue_task_dispatch``.
    """

    lane = classify_urgency(dict(task))
    lane_rank = {
        LANE_URGENT: 0,
        LANE_TIME_CRITICAL: 1,
        LANE_SCHEDULED: 2,
        LANE_DEFERRED: 3,
    }.get(lane, 2)
    task_id = task_identity(task)
    if lane in {LANE_URGENT, LANE_TIME_CRITICAL}:
        return (
            lane_rank,
            0,
            str(task.get("created_at") or ""),
            task_id,
        )
    return (
        lane_rank,
        priority_sort_key(task.get("priority"), default=999),
        "",
        task_id,
    )


def is_immediate_dispatch_task(task: Mapping[str, Any]) -> bool:
    """Whether the canonical worker menu places this task before scheduling."""

    return classify_urgency(dict(task)) in {LANE_URGENT, LANE_TIME_CRITICAL}


def is_pending_list_candidate(
    task: Mapping[str, Any],
    *,
    codex_eligible: bool,
) -> bool:
    """Match production ``list --status pending`` worker filtering."""

    if str(task.get("status") or "").strip().lower() != "pending":
        return False
    return not codex_eligible or is_codex_eligible_task(task)


def _is_managed_event(task: Mapping[str, Any]) -> bool:
    return normalized_task_type(task) == "event_article" and (
        str(task.get("source") or "").strip().lower() == "event_expander"
        or bool(task.get("ref_event_job_id"))
    )


def _parse_deadline(raw: Any) -> datetime | None:
    parsed = parse_iso_warn(
        raw,
        tag="task_pool_selection",
        field_name="deadline_at",
        fallback=None,
    )
    if parsed is None:
        return None
    return parsed.astimezone(timezone.utc)


def evaluate_task_claim(
    task: Mapping[str, Any],
    *,
    owner: str,
    main_thread: bool,
    observed_at: datetime,
    revalidation_checked: bool = False,
) -> LegacyClaimDecision:
    """Evaluate the deterministic part of ``task_pool_claim.cmd_claim``."""

    if observed_at.tzinfo is None:
        raise ValueError("observed_at must include a timezone")
    observed_at = observed_at.astimezone(timezone.utc)
    task_id = task_identity(task)
    status = str(task.get("status") or "").strip().lower()
    claimed_by_value = task.get("claimed_by")
    claimed_by = (
        str(claimed_by_value).strip()
        if claimed_by_value is not None and str(claimed_by_value).strip()
        else None
    )
    lane = normalize_dispatch_lane(dict(task))
    preferred_agent = (
        str(task.get("preferred_agent") or task.get("target_agent") or "")
        .strip()
        .lower()
    )
    managed_event = _is_managed_event(task)
    live_revalidation_required = requires_live_revalidation(dict(task))
    raw_deadline = task.get("deadline")
    deadline = _parse_deadline(raw_deadline)
    policy_reasons: list[str] = []
    policy_reasons.append("legacy_priority_then_id_rank")
    if lane:
        policy_reasons.append("legacy_dispatch_lane_enforced")
    if preferred_agent:
        policy_reasons.append("legacy_preferred_agent_routing")
    if task.get("parent_task_id") is not None or task.get("parent_id") is not None:
        policy_reasons.append("legacy_parent_not_enforced")
    if task.get("deadline") is not None:
        policy_reasons.append("legacy_deadline_not_ranked")
    if managed_event:
        policy_reasons.append("legacy_managed_event_deadline_gate")
    if live_revalidation_required and status != "claimed":
        policy_reasons.append("legacy_dreaming_revalidation_gate")
    if task.get("required_capabilities"):
        policy_reasons.append("legacy_capability_not_enforced")
    if task.get("required_attestations"):
        policy_reasons.append("legacy_attestation_not_enforced")
    if status in _ACTIVE_STATUSES:
        policy_reasons.append("legacy_cleanup_only_reclaim")

    primary_reason = "eligible"
    eligible = True
    if (
        claimed_by is not None
        and claimed_by != owner
        and status in _ACTIVE_STATUSES
    ):
        primary_reason = "already_claimed"
        eligible = False
    elif status not in _CLAIMABLE_STATUSES:
        primary_reason = "wrong_status"
        eligible = False
    elif managed_event and status != "claimed" and not raw_deadline:
        primary_reason = "missing_deadline"
        eligible = False
    elif managed_event and status != "claimed" and deadline is None:
        primary_reason = "invalid_deadline"
        eligible = False
    elif (
        managed_event
        and status != "claimed"
        and deadline is not None
        and observed_at > deadline
    ):
        primary_reason = "deadline_expired"
        eligible = False
    elif (
        status != "claimed"
        and live_revalidation_required
        and not revalidation_checked
    ):
        primary_reason = "live_revalidation_required"
        eligible = False
    elif is_main_thread_reserved(dict(task)) and not main_thread:
        primary_reason = "main_thread_lane"
        eligible = False
    elif is_codex_owner(owner) and not is_codex_eligible_task(task):
        primary_reason = "not_codex_eligible"
        eligible = False
    elif (
        normalized_task_type(task) in GENERIC_BACKGROUND_HARD_DENY_TASK_TYPES
        and not main_thread
    ):
        primary_reason = "main_thread_capability"
        eligible = False

    return LegacyClaimDecision(
        task_id=task_id,
        owner=owner,
        eligible=eligible,
        primary_reason=primary_reason,
        reason_codes=(primary_reason,),
        policy_codes=tuple(policy_reasons),
        rank_key=(
            task_rank_key(task)
            if eligible
            else None
        ),
        status=status,
        dispatch_lane=lane,
        preferred_agent=preferred_agent,
        claimed_by=claimed_by,
        deadline_at=(
            deadline.isoformat()
            if deadline is not None
            else None
        ),
    )


def select_task_for_claim(
    tasks: Iterable[Mapping[str, Any]],
    *,
    owner: str,
    main_thread: bool,
    observed_at: datetime,
) -> LegacyClaimSelection:
    candidates = tuple(tasks)
    identity_counts = Counter(task_identity(task) for task in candidates)
    base_decisions = tuple(
        evaluate_task_claim(
            task,
            owner=owner,
            main_thread=main_thread,
            observed_at=observed_at,
        )
        for task in candidates
    )
    decisions = tuple(
        (
            replace(
                decision,
                eligible=False,
                primary_reason=(
                    "missing_task_id"
                    if not decision.task_id
                    else "duplicate_task_id"
                ),
                reason_codes=(
                    (
                        "missing_task_id"
                        if not decision.task_id
                        else "duplicate_task_id"
                    ),
                ),
                policy_codes=tuple(
                    dict.fromkeys(
                        (
                            *decision.policy_codes,
                            "legacy_unique_identity_required",
                        )
                    )
                ),
                rank_key=None,
            )
            if (
                not decision.task_id
                or identity_counts[decision.task_id] > 1
            )
            else decision
        )
        for decision in base_decisions
    )
    eligible = tuple(
        sorted(
            (
                (index, decision)
                for index, (task, decision) in enumerate(
                    zip(
                        candidates,
                        decisions,
                        strict=True,
                    )
                )
                if decision.eligible
                and is_pending_list_candidate(
                    task,
                    codex_eligible=is_codex_owner(owner),
                )
            ),
            key=lambda item: (
                item[1].rank_key or (999, item[1].task_id),
                item[0],
            ),
        )
    )
    return LegacyClaimSelection(
        selected_task_id=eligible[0][1].task_id if eligible else None,
        eligible_task_ids=tuple(
            decision.task_id for _, decision in eligible
        ),
        decisions=decisions,
        selected_index=eligible[0][0] if eligible else None,
        eligible_indexes=tuple(index for index, _ in eligible),
    )


__all__ = [
    "CLAUDE_ONLY_TASK_TYPES",
    "CODEX_HARD_DENY_TASK_TYPES",
    "CODEX_ELIGIBLE_TASK_TYPES",
    "DISPATCH_MUTATING_TASK_TYPES",
    "GENERIC_BACKGROUND_HARD_DENY_TASK_TYPES",
    "SINGLE_FLIGHT_TASK_TYPES",
    "LegacyClaimDecision",
    "LegacyClaimSelection",
    "TaskIdentityResolution",
    "evaluate_task_claim",
    "is_codex_eligible_task",
    "is_codex_owner",
    "is_pending_list_candidate",
    "normalize_task_type_value",
    "normalized_task_type",
    "dispatch_admission_rank_key",
    "is_immediate_dispatch_task",
    "requires_supervisor_preassignment",
    "resolve_task_identity",
    "select_task_for_claim",
    "single_flight_blocker_task_id",
    "task_identity",
    "task_rank_key",
]
