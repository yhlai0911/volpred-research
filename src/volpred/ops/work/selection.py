"""Pure acquisition policy for Work Coordinator adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, TypeAlias

from . import WorkItemView, WorkerOffer


RankKey: TypeAlias = tuple[int, bool, datetime, datetime, str]


@dataclass(frozen=True)
class AcquisitionCandidateDecision:
    """Immutable explanation of one candidate's acquisition eligibility."""

    work_id: str
    eligible: bool
    reason_codes: tuple[str, ...]
    policy_codes: tuple[str, ...]
    missing_capabilities: frozenset[str]
    missing_attestations: frozenset[str]
    parent_status: str | None
    rank_key: RankKey


@dataclass(frozen=True)
class AcquisitionSelection:
    """Immutable winner and the policy decision for every candidate."""

    selected_id: str | None
    decisions: tuple[AcquisitionCandidateDecision, ...]


def _instant(value: str | datetime) -> datetime:
    instant = datetime.fromisoformat(value) if isinstance(value, str) else value
    if instant.tzinfo is None:
        raise ValueError("work selection timestamps must include a timezone")
    return instant.astimezone(timezone.utc)


def _rank_key(item: WorkItemView) -> RankKey:
    deadline = (
        datetime.max.replace(tzinfo=timezone.utc)
        if item.deadline is None
        else _instant(item.deadline)
    )
    return (
        item.priority,
        item.deadline is None,
        deadline,
        _instant(item.created_at),
        item.id,
    )


def select_acquirable_work(
    items: Iterable[WorkItemView],
    *,
    offer: WorkerOffer,
    observed_at: str | datetime,
) -> AcquisitionSelection:
    """Select one item using the production acquisition policy.

    The function has no side effects so adapters and diagnostics can share the
    same eligibility and ranking rules without reimplementing them.
    """

    candidates = tuple(items)
    by_id = {item.id: item for item in candidates}
    observed = _instant(observed_at)
    evaluated: list[
        tuple[
            WorkItemView,
            bool,
            tuple[str, ...],
            frozenset[str],
            frozenset[str],
            str | None,
            RankKey,
            tuple[str, ...],
        ]
    ] = []

    for item in candidates:
        reasons: list[str] = []
        policy_codes = [
            "coordinator_priority_deadline_created_id_rank",
            "coordinator_capability_enforced",
            "coordinator_attestation_enforced",
        ]
        status_eligible = False
        if item.status == "pending":
            status_eligible = True
            reasons.append("ready_pending")
        elif item.status in {"claimed", "running"}:
            policy_codes.append("coordinator_lease_reclaim_enabled")
            if item.claim_expires_at is None:
                reasons.append("claim_expiry_missing")
            elif _instant(item.claim_expires_at) <= observed:
                status_eligible = True
                reasons.append("ready_expired_claim")
            else:
                reasons.append("live_claim")
        else:
            reasons.append("status_not_acquirable")

        missing_capabilities = item.required_capabilities - offer.capabilities
        if missing_capabilities:
            reasons.append("capability_mismatch")
        missing_attestations = item.required_attestations - offer.attestations
        if missing_attestations:
            reasons.append("attestation_mismatch")

        parent_status: str | None = None
        parent_eligible = True
        if item.parent_id is not None:
            policy_codes.append("coordinator_parent_readiness_enforced")
            parent = by_id.get(item.parent_id)
            if parent is None:
                parent_eligible = False
                reasons.append("parent_missing")
            else:
                parent_status = parent.status
                if parent.status != "succeeded":
                    parent_eligible = False
                    reasons.append("parent_not_succeeded")

        eligible = (
            status_eligible
            and not missing_capabilities
            and not missing_attestations
            and parent_eligible
        )
        if item.deadline is not None:
            policy_codes.append("coordinator_deadline_ranked")
        evaluated.append(
            (
                item,
                eligible,
                tuple(reasons),
                missing_capabilities,
                missing_attestations,
                parent_status,
                _rank_key(item),
                tuple(policy_codes),
            )
        )

    eligible_items = tuple(
        entry for entry in evaluated if entry[1]
    )
    selected_id = (
        min(eligible_items, key=lambda entry: entry[6])[0].id
        if eligible_items
        else None
    )
    decisions = tuple(
        AcquisitionCandidateDecision(
            work_id=item.id,
            eligible=eligible,
            reason_codes=(
                reasons
                + (
                    ("selected",)
                    if item.id == selected_id
                    else ("eligible_not_selected_by_rank",)
                )
                if eligible
                else reasons
            ),
            policy_codes=policy_codes,
            missing_capabilities=missing_capabilities,
            missing_attestations=missing_attestations,
            parent_status=parent_status,
            rank_key=rank_key,
        )
        for (
            item,
            eligible,
            reasons,
            missing_capabilities,
            missing_attestations,
            parent_status,
            rank_key,
            policy_codes,
        ) in sorted(evaluated, key=lambda entry: entry[6])
    )
    return AcquisitionSelection(selected_id=selected_id, decisions=decisions)
