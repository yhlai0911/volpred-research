"""Read-only legacy snapshot mapping for the shadow Work Coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping
from urllib.parse import quote

from . import WorkRequest
from ..next_tasks import normalize_dispatch_lane, normalize_priority
from ..task_pool_selection import task_identity


_NEXT_TASK_STATUS = {
    "pending": "pending",
    "pending_main_thread": "pending",
    "claimed": "claimed",
    "in_progress": "running",
    "blocked": "blocked",
    "blocked_on_user": "blocked",
    "succeeded": "succeeded",
    "succeeded_null_result": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
    "closed_no_action": "cancelled",
    "expired": "cancelled",
    "superseded": "cancelled",
    "decision_made_awaiting_body_rewrite": "blocked",
}

_CAPABILITY_BY_KIND = {
    "assignment": frozenset({"code"}),
    "daily_article": frozenset({"content"}),
    "daily_digest": frozenset({"content"}),
    "email_reply": frozenset({"content"}),
    "event_article": frozenset({"content"}),
    "experiment": frozenset({"research"}),
    "governance": frozenset({"code"}),
    "member_qa": frozenset({"content"}),
    "paper_body": frozenset({"paper"}),
    "paper_decision": frozenset({"paper"}),
    "paper_review": frozenset({"paper"}),
    "platform_ops": frozenset({"code"}),
    "telegram_reply": frozenset({"content"}),
    "trending_repost": frozenset({"content"}),
}

_NEXT_TASK_SOURCE = {
    # Direct human ingress. These exact legacy producer labels retain user
    # priority; lookalike prefixes are deliberately not accepted.
    "user": "user",
    "telegram": "user",
    "telegram-responder": "user",
    "telegram_remediation": "user",
    "gmail_inbox_poll": "user",
    "boss-telegram-msg302-series-decompose": "user",
    "telegram_directive_msg154_myth_busting": "user",
    # Schedule/materializer ingress.
    "schedule": "schedule",
    "scheduled": "schedule",
    "system": "schedule",
    "hourly-dispatch": "schedule",
    "hourly_dispatch": "schedule",
    "hourly_15_governance_seed": "schedule",
    "dispatch": "schedule",
    "dispatch_workspace_gate": "schedule",
    "continue_task_dispatch_pool_dry_breaker": "schedule",
    "task_generator_v2_daily_article": "schedule",
    "task_generator_v2_experiment": "schedule",
    "task_generator_v2_paper_body": "schedule",
    "task_generator_v2_paper_decision": "schedule",
    "task_generator_v2_event_article": "schedule",
    "event_expander": "schedule",
    "internal_alert_remediation_router": "schedule",
    "alert_remediation_bridge": "schedule",
    "release_pool_audit_skip_materializer": "schedule",
    "reap_orphan_deliverables_held_ttl": "schedule",
    "compute_queue_followup": "schedule",
    "question_ops_maintain": "schedule",
    # Agent/discovery ingress. Ambiguous producer labels are kept at the
    # lowest-priority canonical class; each value must still be reviewed and
    # registered explicitly.
    "agent": "agent",
    "agent-discovered": "agent",
    "agent_discovered": "agent",
    "auto_discovered": "agent",
    "auto_research_fallback": "agent",
    "auto_journal_discovery_fallback": "agent",
    "auto_remediation": "agent",
    "auto_publish_drought_emergency": "agent",
    "research_backlog_auto": "agent",
    "reader_facing_refill": "agent",
    "diverse_gen": "agent",
    "dreaming": "agent",
    "phase_z": "agent",
    "codex_review_followup": "agent",
    "codex_v5_independent_round1_split": "agent",
    "audience_correction_backfill": "agent",
    "platform_optimization_plan_20260704_C": "agent",
    "paper_audit_2026-06-10": "agent",
    "paper_review_followup": "agent",
    "fable_deep_review_20260711": "agent",
    "topology-fit-audit-20260710": "agent",
    "leverage_direction_reframing_decision_20260701": "agent",
    "BTC_GAS_negative_paper": "agent",
    "nosource_rescan_extension_top5": "agent",
    "main_thread_discovered_2026-06-30": "agent",
    "decompose:fable0711_abm_honesty_pass": "agent",
    "autonomous_backlog_gen": "agent",
    "paper9_a4f_alignment_audit": "agent",
    "orphan_closeout": "agent",
    "governance_error_log_review_200_followup": "agent",
    "refactor_plan_token_ops_waste": "agent",
}

_TASK_RECORD_STATUS = {
    "queued": "pending",
    "claimed": "claimed",
    "running": "running",
    "awaiting_approval": "awaiting_approval",
    "blocked": "blocked",
    "succeeded": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
}

_TASK_RECORD_CAPABILITY = {
    "code": frozenset({"code"}),
    "content": frozenset({"content"}),
    "member": frozenset({"content"}),
    "ops": frozenset({"code"}),
    "research": frozenset({"research"}),
    "review": frozenset({"code"}),
    "strategy": frozenset({"code"}),
}

_WORK_RISKS = frozenset({"safe", "sensitive", "destructive"})
_WORK_APPROVALS = frozenset({"auto", "required"})
_TASK_RECORD_SOURCES = frozenset({"user", "schedule", "agent"})
_TASK_RECORD_APPROVAL_MODES = frozenset({"auto", "needs_approval"})
_TASK_RECORD_RISKS = {
    "safe": "safe",
    "elevated": "sensitive",
    "destructive": "destructive",
}

_OPS_JOB_STATUS = {
    "queued": "pending",
    "running": "running",
    "succeeded": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
}

_OPS_JOB_SOURCE = {
    "human": "user",
    "agent": "agent",
    "system": "schedule",
}

_OPS_JOB_ACTIONS = frozenset(
    {
        "cleanup_test_post",
        "daily_update",
        "health_check",
        "paper_migrate_storage",
        "paper_upload_pdf",
        "paper_upsert",
        "platform_cycle_summary",
        "publish_milestone",
        "question_answer",
        "question_ranking_summary",
        "question_ranking_workflow",
        "question_rerank",
        "recalc_metrics",
        "release_article_pool",
        "release_article_pool_by_settings",
        "send_article_notification",
        "send_daily_digest",
        "strategy_set_active",
        "strategy_upsert",
        "sync_all",
        "unpublish_article",
    }
)


@dataclass(frozen=True)
class LegacySnapshots:
    next_tasks: tuple[Mapping[str, Any], ...] = ()
    task_records: tuple[Mapping[str, Any], ...] = ()
    ops_jobs: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class LegacyWorkCandidate:
    source_system: str
    legacy_id: str
    request: WorkRequest
    status: str
    legacy_status: str
    legacy_source: str
    source_classification: str
    created_at: str
    updated_at: str | None = None
    finished_at: str | None = None
    claimed_by: str | None = None
    claimed_at: str | None = None
    started_at: str | None = None
    result_summary: str | None = None
    blocked_reason: str | None = None
    dispatch_lane: str | None = None
    preferred_agent: str | None = None
    target_agent: str | None = None
    fallback_allowed: bool | None = None
    claim_expires_at: str | None = None
    ref_event_job_id: str | None = None
    dreaming: dict[str, Any] | None = None


@dataclass(frozen=True)
class ReconciliationIssue:
    code: str
    source_system: str
    record_id: str | None
    detail: str
    record_index: int | None = None
    affected_record_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReconciliationReport:
    candidates: tuple[LegacyWorkCandidate, ...]
    issues: tuple[ReconciliationIssue, ...]
    source_counts: dict[str, dict[str, int]]

    @property
    def ready(self) -> bool:
        return not self.issues

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "candidate_count": len(self.candidates),
            "issue_count": len(self.issues),
            "source_counts": {
                source: dict(counts)
                for source, counts in self.source_counts.items()
            },
            "candidates": [
                {
                    "source_system": candidate.source_system,
                    "legacy_id": candidate.legacy_id,
                    "status": candidate.status,
                    "legacy_status": candidate.legacy_status,
                    "source_provenance": {
                        "legacy": candidate.legacy_source,
                        "canonical": candidate.request.source,
                        "classification": candidate.source_classification,
                    },
                    "created_at": candidate.created_at,
                    "updated_at": candidate.updated_at,
                    "finished_at": candidate.finished_at,
                    "claimed_by": candidate.claimed_by,
                    "claimed_at": candidate.claimed_at,
                    "started_at": candidate.started_at,
                    "result_summary": candidate.result_summary,
                    "blocked_reason": candidate.blocked_reason,
                    "dispatch_lane": candidate.dispatch_lane,
                    "preferred_agent": candidate.preferred_agent,
                    "target_agent": candidate.target_agent,
                    "fallback_allowed": candidate.fallback_allowed,
                    "claim_expires_at": candidate.claim_expires_at,
                    "ref_event_job_id": candidate.ref_event_job_id,
                    "dreaming": candidate.dreaming,
                    "request": {
                        "idempotency_key": candidate.request.idempotency_key,
                        "source": candidate.request.source,
                        "kind": candidate.request.kind,
                        "title": candidate.request.title,
                        "priority": candidate.request.priority,
                        "required_capabilities": sorted(
                            candidate.request.required_capabilities
                        ),
                        "required_attestations": sorted(
                            candidate.request.required_attestations
                        ),
                        "risk": candidate.request.risk,
                        "approval": candidate.request.approval,
                        "payload_ref": candidate.request.payload_ref,
                        "parent_id": candidate.request.parent_id,
                        "deadline": candidate.request.deadline,
                        "requester_ref": candidate.request.requester_ref,
                    },
                }
                for candidate in self.candidates
            ],
            "issues": [
                {
                    "code": issue.code,
                    "source_system": issue.source_system,
                    "record_id": issue.record_id,
                    "detail": issue.detail,
                    **(
                        {"record_index": issue.record_index}
                        if issue.record_index is not None
                        else {}
                    ),
                    **(
                        {
                            "affected_record_ids": list(
                                issue.affected_record_ids
                            )
                        }
                        if issue.affected_record_ids
                        else {}
                    ),
                }
                for issue in self.issues
            ],
        }


class _LegacyMappingError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


class LegacySnapshotImporter:
    """Map supplied snapshots without reading or mutating their sources."""

    def import_snapshot(self, snapshots: LegacySnapshots) -> ReconciliationReport:
        candidates: list[LegacyWorkCandidate] = []
        issues: list[ReconciliationIssue] = []
        mapped_counts: dict[str, int] = {}
        identity_inventory = self._supplied_identity_inventory(snapshots)
        for source_system, records, mapper in (
            ("next_tasks", snapshots.next_tasks, self._map_next_task),
            ("task_records", snapshots.task_records, self._map_task_record),
            ("ops_jobs", snapshots.ops_jobs, self._map_ops_job),
        ):
            mapped = 0
            for record_index, record in enumerate(records):
                record_id = _optional_string(
                    (
                        task_identity(record)
                        if source_system == "next_tasks"
                        else record.get("id")
                    )
                )
                try:
                    candidates.append(mapper(record))
                    mapped += 1
                except _LegacyMappingError as error:
                    issues.append(
                        ReconciliationIssue(
                            code=error.code,
                            source_system=source_system,
                            record_id=record_id,
                            detail=str(error),
                            record_index=record_index,
                        )
                    )
                except (KeyError, TypeError, ValueError) as error:
                    issues.append(
                        ReconciliationIssue(
                            code="invalid_record",
                            source_system=source_system,
                            record_id=record_id,
                            detail=str(error),
                            record_index=record_index,
                        )
                    )
            mapped_counts[source_system] = mapped
        issues.extend(self._reconcile_supplied_identities(identity_inventory))
        issues.extend(
            self._reconcile(
                candidates,
                supplied_ids=self._supplied_record_ids(snapshots),
            )
        )
        deduplicated_issues = tuple(dict.fromkeys(issues))
        return ReconciliationReport(
            candidates=tuple(candidates),
            issues=deduplicated_issues,
            source_counts={
                "next_tasks": {
                    "seen": len(snapshots.next_tasks),
                    "mapped": mapped_counts["next_tasks"],
                },
                "task_records": {
                    "seen": len(snapshots.task_records),
                    "mapped": mapped_counts["task_records"],
                },
                "ops_jobs": {
                    "seen": len(snapshots.ops_jobs),
                    "mapped": mapped_counts["ops_jobs"],
                },
            },
        )

    @staticmethod
    def _supplied_identity_inventory(
        snapshots: LegacySnapshots,
    ) -> dict[str, tuple[str, ...]]:
        inventory: dict[str, list[str]] = {}
        for source_system, records, identity_reader in (
            ("next_tasks", snapshots.next_tasks, task_identity),
            (
                "task_records",
                snapshots.task_records,
                lambda record: record.get("id"),
            ),
            ("ops_jobs", snapshots.ops_jobs, lambda record: record.get("id")),
        ):
            for record in records:
                legacy_id = _valid_identity(identity_reader(record))
                if legacy_id is None:
                    # Mapping emits the structured invalid_record issue.
                    continue
                inventory.setdefault(legacy_id, []).append(source_system)
        return {
            legacy_id: tuple(source_systems)
            for legacy_id, source_systems in inventory.items()
        }

    @staticmethod
    def _reconcile_supplied_identities(
        inventory: Mapping[str, tuple[str, ...]],
    ) -> tuple[ReconciliationIssue, ...]:
        issues: list[ReconciliationIssue] = []
        for legacy_id, occurrences in sorted(inventory.items()):
            if len(occurrences) < 2:
                continue
            sources = sorted(set(occurrences))
            issues.append(
                ReconciliationIssue(
                    code="duplicate_id",
                    source_system=(
                        "cross_source" if len(sources) > 1 else sources[0]
                    ),
                    record_id=legacy_id,
                    detail=(
                        f"legacy id appears {len(occurrences)} times in "
                        f"{', '.join(sources)}"
                    ),
                )
            )
        return tuple(issues)

    @staticmethod
    def _supplied_record_ids(
        snapshots: LegacySnapshots,
    ) -> frozenset[str]:
        """Project raw record presence separately from valid identity census."""

        identities = {
            task_identity(record)
            for record in snapshots.next_tasks
            if task_identity(record)
        }
        for records in (snapshots.task_records, snapshots.ops_jobs):
            identities.update(
                record_id
                for record in records
                if (record_id := _optional_string(record.get("id")))
                is not None
            )
        return frozenset(identities)

    @staticmethod
    def _reconcile(
        candidates: list[LegacyWorkCandidate],
        *,
        supplied_ids: frozenset[str],
    ) -> tuple[ReconciliationIssue, ...]:
        by_id: dict[str, list[LegacyWorkCandidate]] = {}
        for candidate in candidates:
            by_id.setdefault(candidate.legacy_id, []).append(candidate)

        issues: list[ReconciliationIssue] = []
        for legacy_id in sorted(by_id):
            copies = by_id[legacy_id]
            if len(copies) < 2:
                continue
            sources = sorted({candidate.source_system for candidate in copies})
            active_claims = [
                candidate
                for candidate in copies
                if candidate.status in {"claimed", "running"}
                and candidate.claimed_by is not None
            ]
            if len(active_claims) > 1:
                owners = sorted(
                    {
                        f"{candidate.source_system}={candidate.claimed_by}"
                        for candidate in active_claims
                    }
                )
                issues.append(
                    ReconciliationIssue(
                        code="simultaneous_claim",
                        source_system=(
                            "cross_source" if len(sources) > 1 else sources[0]
                        ),
                        record_id=legacy_id,
                        detail=f"active claims disagree: {', '.join(owners)}",
                    )
                )
        by_idempotency_key: dict[str, list[LegacyWorkCandidate]] = {}
        for candidate in candidates:
            by_idempotency_key.setdefault(
                candidate.request.idempotency_key, []
            ).append(candidate)
        for idempotency_key in sorted(by_idempotency_key):
            copies = by_idempotency_key[idempotency_key]
            if len(copies) < 2:
                continue
            record_ids = tuple(
                sorted({candidate.legacy_id for candidate in copies})
            )
            sources = sorted({candidate.source_system for candidate in copies})
            issues.append(
                ReconciliationIssue(
                    code="duplicate_idempotency_key",
                    source_system=(
                        "cross_source" if len(sources) > 1 else sources[0]
                    ),
                    record_id=",".join(record_ids),
                    affected_record_ids=record_ids,
                    detail=(
                        "canonical idempotency key is shared by distinct "
                        f"legacy records: {idempotency_key}"
                    ),
                )
            )
        known_ids = set(by_id)
        for candidate in candidates:
            parent_id = candidate.request.parent_id
            if parent_id is None or parent_id in known_ids:
                continue
            parent_is_supplied = parent_id in supplied_ids
            issues.append(
                ReconciliationIssue(
                    code=(
                        "unrepresentable_parent"
                        if parent_is_supplied
                        else "missing_parent"
                    ),
                    source_system=candidate.source_system,
                    record_id=candidate.legacy_id,
                    detail=(
                        "parent id is present in supplied snapshots but "
                        f"could not be represented: {parent_id}"
                        if parent_is_supplied
                        else (
                            "parent id is absent from supplied snapshots: "
                            f"{parent_id}"
                        )
                    ),
                )
            )
        for candidate in candidates:
            problems: list[str] = []
            if candidate.status in {"claimed", "running"}:
                if candidate.claimed_by is None:
                    problems.append("active status has no claim owner")
                if candidate.claimed_at is None:
                    problems.append("active status has no claim timestamp")
                if candidate.status == "running" and candidate.started_at is None:
                    problems.append("running status has no start timestamp")
            elif candidate.status in {"pending", "awaiting_approval"} and any(
                value is not None
                for value in (
                    candidate.claimed_by,
                    candidate.claimed_at,
                    candidate.started_at,
                )
            ):
                problems.append("unclaimed status carries active claim trace")
            if (
                candidate.status in {"succeeded", "failed", "cancelled"}
                and candidate.finished_at is None
            ):
                problems.append("terminal status has no finish timestamp")
            if candidate.status == "blocked" and candidate.blocked_reason is None:
                problems.append("blocked status has no reason")
            timestamps = {
                "created_at": candidate.created_at,
                "claimed_at": candidate.claimed_at,
                "started_at": candidate.started_at,
                "finished_at": candidate.finished_at,
                "updated_at": candidate.updated_at,
            }
            parsed = {
                name: datetime.fromisoformat(value)
                for name, value in timestamps.items()
                if value is not None
            }
            created_at = parsed["created_at"]
            for name in ("claimed_at", "started_at", "finished_at", "updated_at"):
                value = parsed.get(name)
                if value is not None and value < created_at:
                    problems.append(f"created_at > {name}")
            for earlier, later in (
                ("claimed_at", "started_at"),
                ("claimed_at", "finished_at"),
                ("started_at", "finished_at"),
            ):
                if (
                    earlier in parsed
                    and later in parsed
                    and parsed[earlier] > parsed[later]
                ):
                    problems.append(f"{earlier} > {later}")
            updated_at = parsed.get("updated_at")
            if updated_at is not None:
                for name in ("claimed_at", "started_at", "finished_at"):
                    value = parsed.get(name)
                    if value is not None and value > updated_at:
                        problems.append(f"{name} > updated_at")
            if problems:
                issues.append(
                    ReconciliationIssue(
                        code="invalid_lifecycle",
                        source_system=candidate.source_system,
                        record_id=candidate.legacy_id,
                        detail="; ".join(problems),
                    )
                )
        return tuple(issues)

    @staticmethod
    def _map_next_task(record: Mapping[str, Any]) -> LegacyWorkCandidate:
        legacy_id = _next_task_id(record)
        legacy_status = str(record["status"])
        if legacy_status not in _NEXT_TASK_STATUS:
            raise _LegacyMappingError(
                "unknown_status",
                f"next_tasks status is not mapped: {legacy_status}",
            )
        kind = str(record["task_type"])
        if kind not in _CAPABILITY_BY_KIND:
            raise _LegacyMappingError(
                "unknown_kind",
                f"next_tasks task_type is not mapped: {kind}",
            )
        created_at = _timestamp(record["created_at"])
        legacy_source, source, source_classification = (
            _classify_next_task_source(record["source"])
        )
        requester_ref = _identity_or_default(
            record.get("created_by"),
            field="created_by",
            default=source,
        )
        identity_ref = f"legacy:next_tasks:{legacy_id}"
        payload_ref = _payload_reference("next_tasks", legacy_id, record)
        capabilities = record.get("required_capabilities")
        attestations = record.get("required_attestations")
        risk = str(record.get("risk") or "safe")
        approval = str(
            record.get("approval")
            or (
                "required"
                if risk != "safe"
                or record.get("approval_mode") == "needs_approval"
                else "auto"
            )
        )
        approval_mode = record.get("approval_mode")
        approval_mode_value = (
            None if approval_mode is None else str(approval_mode)
        )
        if (
            risk not in _WORK_RISKS
            or approval not in _WORK_APPROVALS
            or (
                approval_mode_value is not None
                and approval_mode_value not in _TASK_RECORD_APPROVAL_MODES
            )
            or (risk != "safe" and approval != "required")
            or (
                approval_mode_value == "needs_approval"
                and approval != "required"
            )
        ):
            raise _LegacyMappingError(
                "unknown_policy",
                "next_tasks risk/approval policy is not mapped: "
                f"risk={risk}, approval={approval}, "
                f"approval_mode={approval_mode}",
            )
        return LegacyWorkCandidate(
            source_system="next_tasks",
            legacy_id=legacy_id,
            request=WorkRequest(
                idempotency_key=identity_ref,
                source=source,
                kind=kind,
                title=str(record["title"]),
                priority=normalize_priority(record["priority"]),
                required_capabilities=(
                    _CAPABILITY_BY_KIND[kind]
                    | _string_set(
                        capabilities,
                        field="required_capabilities",
                        allow_empty=False,
                    )
                    if capabilities is not None
                    else _CAPABILITY_BY_KIND[kind]
                ),
                required_attestations=_string_set(
                    attestations,
                    field="required_attestations",
                    allow_empty=True,
                ),
                risk=risk,
                approval=approval,
                payload_ref=payload_ref,
                parent_id=_optional_record_identity(
                    record,
                    "parent_task_id",
                    "parent_id",
                ),
                deadline=_optional_timestamp(record.get("deadline")),
                requester_ref=requester_ref,
            ),
            status=_NEXT_TASK_STATUS[legacy_status],
            legacy_status=legacy_status,
            legacy_source=legacy_source,
            source_classification=source_classification,
            created_at=created_at,
            updated_at=_optional_timestamp(record.get("updated_at")),
            finished_at=_optional_timestamp(
                record.get("completed_at") or record.get("finished_at")
            ),
            claimed_by=_optional_identity(
                record.get("claimed_by"), field="claimed_by"
            ),
            claimed_at=_optional_timestamp(record.get("claimed_at")),
            started_at=_optional_timestamp(record.get("started_at")),
            result_summary=_optional_string(
                record.get("result_summary") or record.get("result")
            ),
            blocked_reason=_optional_string(
                record.get("blocked_reason") or record.get("blocked_note")
            ),
            dispatch_lane=normalize_dispatch_lane(dict(record)) or None,
            preferred_agent=_optional_string(record.get("preferred_agent")),
            target_agent=_optional_string(record.get("target_agent")),
            fallback_allowed=_optional_bool(record.get("fallback_allowed")),
            claim_expires_at=_optional_timestamp(
                record.get("claim_expires_at")
            ),
            ref_event_job_id=_optional_string(
                record.get("ref_event_job_id")
            ),
            dreaming=_optional_mapping(record.get("dreaming")),
        )

    @staticmethod
    def _map_task_record(record: Mapping[str, Any]) -> LegacyWorkCandidate:
        legacy_id = _legacy_id(record)
        legacy_status = str(record["status"])
        if legacy_status not in _TASK_RECORD_STATUS:
            raise _LegacyMappingError(
                "unknown_status",
                f"TaskRecord status is not mapped: {legacy_status}",
            )
        kind = str(record["task_family"])
        if kind not in _TASK_RECORD_CAPABILITY:
            raise _LegacyMappingError(
                "unknown_kind",
                f"TaskRecord task_family is not mapped: {kind}",
            )
        public_effect = str(record.get("public_effect") or "none")
        if public_effect not in {"none", "draft_only"}:
            raise _LegacyMappingError(
                "unrepresentable_public_effect",
                f"TaskRecord public_effect requires Effect Delivery: {public_effect}",
            )
        source = str(record["source"])
        approval_mode = str(record["approval_mode"])
        legacy_risk = str(record["risk_level"])
        if (
            source not in _TASK_RECORD_SOURCES
            or approval_mode not in _TASK_RECORD_APPROVAL_MODES
            or legacy_risk not in _TASK_RECORD_RISKS
        ):
            raise _LegacyMappingError(
                "unknown_policy",
                "TaskRecord source/risk/approval policy is not mapped: "
                f"source={source}, risk_level={legacy_risk}, "
                f"approval_mode={approval_mode}",
            )
        risk = _TASK_RECORD_RISKS[legacy_risk]
        approval = (
            "required"
            if risk != "safe"
            or approval_mode == "needs_approval"
            else "auto"
        )
        requester_ref = _identity_or_default(
            record.get("created_by"),
            field="created_by",
            default=source,
        )
        identity_ref = f"legacy:task_records:{legacy_id}"
        payload_ref = _payload_reference("task_records", legacy_id, record)
        return LegacyWorkCandidate(
            source_system="task_records",
            legacy_id=legacy_id,
            request=WorkRequest(
                idempotency_key=identity_ref,
                source=source,
                kind=kind,
                title=str(record["title"]),
                priority=int(record["priority"]),
                required_capabilities=_TASK_RECORD_CAPABILITY[kind],
                required_attestations=frozenset(),
                risk=risk,
                approval=approval,
                payload_ref=payload_ref,
                parent_id=_optional_record_identity(
                    record, "parent_task_id"
                ),
                requester_ref=requester_ref,
            ),
            status=_TASK_RECORD_STATUS[legacy_status],
            legacy_status=legacy_status,
            legacy_source=source,
            source_classification=f"exact:{source}",
            created_at=_timestamp(record["created_at"]),
            updated_at=_optional_timestamp(record.get("updated_at")),
            finished_at=_optional_timestamp(record.get("finished_at")),
            claimed_by=_optional_identity(
                record.get("claimed_by"), field="claimed_by"
            ),
            claimed_at=_optional_timestamp(record.get("claimed_at")),
            started_at=_optional_timestamp(record.get("started_at")),
            result_summary=_optional_string(record.get("result_summary")),
            blocked_reason=_optional_string(
                record.get("last_error") if legacy_status == "blocked" else None
            ),
            preferred_agent=_optional_string(record.get("preferred_agent")),
            fallback_allowed=_optional_bool(record.get("fallback_allowed")),
        )

    @staticmethod
    def _map_ops_job(record: Mapping[str, Any]) -> LegacyWorkCandidate:
        legacy_id = _legacy_id(record)
        legacy_status = str(record["status"])
        if legacy_status not in _OPS_JOB_STATUS:
            raise _LegacyMappingError(
                "unknown_status",
                f"ops_jobs status is not mapped: {legacy_status}",
            )
        action = str(record["action"])
        if action not in _OPS_JOB_ACTIONS:
            raise _LegacyMappingError(
                "unknown_kind",
                f"ops_jobs action is not mapped: {action}",
            )
        if record.get("dry_run") is not True:
            raise _LegacyMappingError(
                "unrepresentable_public_effect",
                f"ops_jobs action requires Effect Delivery: {action}",
            )
        legacy_source = str(record["source"])
        if legacy_source not in _OPS_JOB_SOURCE:
            raise _LegacyMappingError(
                "unknown_source",
                f"ops_jobs source is not mapped: {legacy_source}",
            )
        source = _OPS_JOB_SOURCE[legacy_source]
        dedupe_key = _identity_or_default(
            record.get("dedupe_key"),
            field="dedupe_key",
            default=legacy_id,
        )
        requester_ref = _identity_or_default(
            record.get("requested_by"),
            field="requested_by",
            default=source,
        )
        payload_ref = _payload_reference("ops_jobs", legacy_id, record)
        return LegacyWorkCandidate(
            source_system="ops_jobs",
            legacy_id=legacy_id,
            request=WorkRequest(
                idempotency_key=f"legacy:ops_jobs:{dedupe_key}",
                source=source,
                kind=f"ops_job.{action}",
                title=f"Legacy dry-run ops job: {action}",
                priority=int(record["priority"]),
                required_capabilities=frozenset({"code"}),
                required_attestations=frozenset(),
                risk="safe",
                approval="auto",
                payload_ref=payload_ref,
                requester_ref=requester_ref,
            ),
            status=_OPS_JOB_STATUS[legacy_status],
            legacy_status=legacy_status,
            legacy_source=legacy_source,
            source_classification=f"exact:{legacy_source}",
            created_at=_timestamp(record["created_at"]),
            updated_at=_optional_timestamp(record.get("updated_at")),
            finished_at=_optional_timestamp(record.get("finished_at")),
            claimed_by=_optional_identity(
                record.get("worker_id"), field="worker_id"
            ),
            claimed_at=_optional_timestamp(record.get("started_at")),
            started_at=_optional_timestamp(record.get("started_at")),
            result_summary=_optional_string(record.get("result")),
            blocked_reason=_optional_string(record.get("error")),
        )


def _timestamp(value: Any) -> str:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("legacy timestamp must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _classify_next_task_source(value: Any) -> tuple[str, str, str]:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _LegacyMappingError(
            "unknown_source",
            "next_tasks source must be a non-empty, trimmed string",
        )
    exact = _NEXT_TASK_SOURCE.get(value)
    if exact is not None:
        return value, exact, f"exact:{value}"
    raise _LegacyMappingError(
        "unknown_source",
        f"next_tasks source is not in the reviewed provenance registry: {value}",
    )


def _next_task_id(record: Mapping[str, Any]) -> str:
    value = _valid_identity(task_identity(record))
    if value is None:
        raise ValueError("legacy id must be a non-empty, trimmed string")
    return value


def _legacy_id(record: Mapping[str, Any]) -> str:
    value = _valid_identity(record.get("id"))
    if value is None:
        raise ValueError("legacy id must be a non-empty, trimmed string")
    return value


def _valid_identity(value: Any) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    return value


def _payload_reference(
    source_system: str,
    legacy_id: str,
    record: Mapping[str, Any],
) -> str:
    serialized = json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(serialized).hexdigest()
    return (
        f"legacy-snapshot://{source_system}/{quote(legacy_id, safe='')}"
        f"?sha256={digest}"
    )


def _optional_timestamp(value: Any) -> str | None:
    return None if value in (None, "") else _timestamp(value)


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError("optional boolean field must be a bool")
    return value


def _optional_mapping(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("optional mapping field must be an object")
    return dict(value)


def _optional_identity(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty, trimmed string")
    return value


def _identity_or_default(value: Any, *, field: str, default: str) -> str:
    if value is None:
        return default
    identity = _optional_identity(value, field=field)
    if identity is None:  # Defensive narrowing; value is known non-null.
        raise ValueError(f"{field} is required")
    return identity


def _optional_record_identity(
    record: Mapping[str, Any], *fields: str
) -> str | None:
    for field in fields:
        if field in record and record[field] is not None:
            return _optional_identity(record[field], field=field)
    return None


def _string_set(
    value: Any, *, field: str, allow_empty: bool
) -> frozenset[str]:
    if value is None:
        return frozenset()
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError(f"{field} must be an array")
    tokens: list[str] = []
    for item in value:
        if (
            not isinstance(item, str)
            or not item
            or item != item.strip()
        ):
            raise ValueError(
                f"{field} entries must be non-empty, trimmed strings"
            )
        tokens.append(item)
    if not tokens and not allow_empty:
        raise ValueError(f"{field} must not be empty when supplied")
    return frozenset(tokens)


__all__ = [
    "LegacySnapshotImporter",
    "LegacySnapshots",
    "LegacyWorkCandidate",
    "ReconciliationIssue",
    "ReconciliationReport",
]
