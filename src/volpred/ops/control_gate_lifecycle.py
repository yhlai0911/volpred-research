"""Operations Core owner for lock/gate lifecycle evidence and PDCA review.

The platform has several kinds of control points: exact idempotency gates,
dispatch admission constraints, observational pre-gates, and safety locks such
as PHASE-Z ownership proof. Historically each emitted a local log (or only an
incident), so the system could count triggers without seeing which downstream
edge was cut or whether the same gate later caused a missed deadline.

This module keeps one machine-readable registry, reads the existing evidence
surfaces, joins decisions to canonical task/feed/incident outcomes, and creates
at most one review task per gate/window through ``append_task_record``. It does
not own a runner, schedule, pending queue, alert transport, or incident state.
The existing hourly check-alerts path invokes it.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from volpred.canonical_write import guard_canonical_write
from volpred.publisher.arc_dedup import normalize_event_series_slot

from .common import project_path
from .shared_lock import shared_state_lock

SCHEMA_VERSION = 1
DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "control_gate_registry.json"
)
DEFAULT_STATE_RELATIVE_PATH = "ops/control_gate_lifecycle_latest.json"
CONTROL_DECISIONS_RELATIVE_PATH = "logs/control_gate_decisions.jsonl"
ACTIVE_TASK_STATUSES = {
    "pending",
    "pending_main_thread",
    "claimed",
    "in_progress",
    "awaiting_agent_job",
    "blocked",
}
REVIEW_ACTIONS = (
    "retain",
    "recalibrate",
    "downgrade_to_warn",
    "retire",
)
HARD_MODES = {"hard_block", "fail_closed", "mutex"}
EXACT_IDENTITY_STRENGTHS = {"canonical_exact", "cryptographic_exact"}
GATE_MODES = HARD_MODES | {
    "shadow",
    "warn",
    "selection_constraint",
}
IDENTITY_STRENGTHS = EXACT_IDENTITY_STRENGTHS | {"heuristic"}
OUTCOME_JOIN_STRATEGIES = {
    "candidate_or_event_stage",
    "candidate_task",
    "dispatch_signature",
    "incident_or_generation",
}


def _parse_time(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _try_parse_time(raw: Any) -> tuple[datetime | None, bool]:
    """Return parsed UTC time and whether a non-empty value was malformed."""

    if raw in (None, ""):
        return None, False
    try:
        return _parse_time(raw), False
    except (TypeError, ValueError, OverflowError):
        return None, True


def _load_json_with_health(
    path: Path,
    default: Any,
) -> tuple[Any, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return default, {
            "path": str(path),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return payload, {"path": str(path), "ok": True, "error": None}


def _read_jsonl(
    path: Path,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    malformed = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return rows, malformed, {
            "path": str(path),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "row_count": 0,
            "malformed_rows": 0,
        }
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:  # silent-ok: counted in source-health
            malformed += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            malformed += 1
    return rows, malformed, {
        "path": str(path),
        "ok": malformed == 0,
        "error": None if malformed == 0 else "malformed_jsonl_rows",
        "row_count": len(rows),
        "malformed_rows": malformed,
    }


def _validate_registry(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("control gate registry must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"control gate registry schema_version must be {SCHEMA_VERSION}"
        )
    owner = payload.get("owner")
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("control gate registry requires one owner")
    gates = payload.get("gates")
    if not isinstance(gates, list) or not gates:
        raise ValueError("control gate registry requires a non-empty gates list")

    seen: set[str] = set()
    for gate in gates:
        if not isinstance(gate, dict):
            raise ValueError("every gate registry row must be an object")
        gate_id = str(gate.get("gate_id") or "").strip()
        if not gate_id or gate_id in seen:
            raise ValueError(f"gate_id must be unique and non-empty: {gate_id!r}")
        seen.add(gate_id)
        for field in ("owner", "invariant"):
            value = gate.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"gate {gate_id!r} requires {field}")
        mode = str(gate.get("mode") or "")
        identity = str(gate.get("identity_strength") or "")
        if mode not in GATE_MODES:
            raise ValueError(
                f"gate {gate_id!r} mode must be one of {sorted(GATE_MODES)!r}"
            )
        if identity not in IDENTITY_STRENGTHS:
            raise ValueError(
                f"gate {gate_id!r} identity_strength must be one of "
                f"{sorted(IDENTITY_STRENGTHS)!r}"
            )
        if mode in HARD_MODES and identity not in EXACT_IDENTITY_STRENGTHS:
            raise ValueError(
                f"heuristic gate {gate_id!r} cannot use hard_block/fail_closed/mutex "
                f"mode (identity_strength={identity!r})"
            )
        graph = gate.get("protected_graph")
        if (
            not isinstance(graph, dict)
            or not graph.get("nodes")
            or not graph.get("edges")
        ):
            raise ValueError(
                f"gate {gate_id!r} requires protected_graph.nodes and edges"
            )
        blocked_edges = gate.get("blocked_downstream_edges")
        if not isinstance(blocked_edges, list) or not blocked_edges:
            raise ValueError(
                f"gate {gate_id!r} requires blocked_downstream_edges"
            )
        if not isinstance(gate.get("incident_refs"), list):
            raise ValueError(f"gate {gate_id!r} requires incident_refs")
        sources = gate.get("evidence_sources")
        if not isinstance(sources, list) or not sources:
            raise ValueError(f"gate {gate_id!r} requires evidence_sources")
        outcome_join = str(gate.get("outcome_join") or "")
        if outcome_join not in OUTCOME_JOIN_STRATEGIES:
            raise ValueError(
                f"gate {gate_id!r} outcome_join must be one of "
                f"{sorted(OUTCOME_JOIN_STRATEGIES)!r}"
            )
        if not isinstance(gate.get("deadline_required"), bool):
            raise ValueError(
                f"gate {gate_id!r} requires boolean deadline_required"
            )
        policy = gate.get("review_policy")
        if not isinstance(policy, dict) or not policy.get("window_hours"):
            raise ValueError(f"gate {gate_id!r} requires review_policy.window_hours")
        if "max_false_positive_signals" not in policy:
            raise ValueError(
                f"gate {gate_id!r} requires review_policy."
                "max_false_positive_signals"
            )
        lifecycle = gate.get("lifecycle")
        actions = (
            lifecycle.get("allowed_actions")
            if isinstance(lifecycle, dict)
            else None
        )
        if list(actions or []) != list(REVIEW_ACTIONS):
            raise ValueError(
                f"gate {gate_id!r} lifecycle actions must be "
                f"{list(REVIEW_ACTIONS)!r}"
            )
        reviewed_at = lifecycle.get("last_reviewed_at")
        if reviewed_at is not None:
            parsed, malformed = _try_parse_time(reviewed_at)
            if malformed or parsed is None:
                raise ValueError(
                    f"gate {gate_id!r} lifecycle.last_reviewed_at is invalid"
                )
            if lifecycle.get("last_action") not in REVIEW_ACTIONS:
                raise ValueError(
                    f"gate {gate_id!r} lifecycle.last_action is invalid"
                )
            if not lifecycle.get("review_task_id"):
                raise ValueError(
                    f"gate {gate_id!r} lifecycle.review_task_id is required"
                )
    return payload


def load_gate_registry(
    path: str | Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    registry_path = Path(path)
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"control gate registry unreadable: {registry_path}: {exc}"
        ) from exc
    return _validate_registry(payload)


def _matches(row: dict[str, Any], selector: dict[str, Any]) -> bool:
    for field, allowed in selector.items():
        values = allowed if isinstance(allowed, list) else [allowed]
        if row.get(field) not in values:
            return False
    return True


def _row_timestamp(row: dict[str, Any]) -> Any:
    for field in (
        "ts",
        "generated_at",
        "rejected_at",
        "created_at",
        "at",
    ):
        if row.get(field) not in (None, ""):
            return row[field]
    return None


def _candidate_id(row: dict[str, Any]) -> str | None:
    for field in (
        "candidate_id",
        "target_id",
        "task_id",
        "job_id",
        "rejection_id",
        "generation_id",
        "signature",
    ):
        value = row.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    reasons = row.get("reasons")
    if isinstance(reasons, dict):
        signature = reasons.get("signature")
        if isinstance(signature, str) and signature.strip():
            return signature.strip()
    return None


def _event_identity(item: dict[str, Any]) -> str | None:
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    event_key = str(
        item.get("event_key") or details.get("event_key") or ""
    ).strip()
    raw_slot = item.get("event_series_slot") or details.get("event_series_slot")
    if not event_key or raw_slot in (None, ""):
        return None
    try:
        slot = normalize_event_series_slot(str(raw_slot))
    except ValueError:  # silent-ok: invalid identity remains explicitly unjoined
        return None
    return f"{event_key.casefold()}:{slot}"


def _candidate_event_identity(raw: str) -> str | None:
    event_key, separator, slot_raw = str(raw or "").rpartition(":")
    if not separator or not event_key:
        return None
    try:
        slot = normalize_event_series_slot(slot_raw)
    except ValueError:  # silent-ok: invalid identity remains explicitly unjoined
        return None
    return f"{event_key.strip().casefold()}:{slot}"


def _load_incidents(
    storage_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload, health = _load_json_with_health(
        storage_root / "ops" / "incidents.json", {}
    )
    incidents = payload.get("incidents") if isinstance(payload, dict) else {}
    if not isinstance(incidents, dict):
        return [], {**health, "ok": False, "error": "invalid_incident_schema"}
    rows = [
        {"incident_id": incident_id, **row}
        for incident_id, row in incidents.items()
        if isinstance(row, dict)
    ]
    invalid_timestamps = sum(
        1
        for row in rows
        if _try_parse_time(row.get("last_seen_at"))[0] is None
    )
    if invalid_timestamps:
        health = {
            **health,
            "ok": False,
            "error": "missing_or_malformed_incident_timestamp",
            "invalid_timestamps": invalid_timestamps,
        }
    return rows, health


def _load_tasks(
    queue_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload, health = _load_json_with_health(queue_path, [])
    rows = (
        payload
        if isinstance(payload, list)
        else payload.get("tasks", [])
        if isinstance(payload, dict)
        else None
    )
    if not isinstance(rows, list):
        return [], {**health, "ok": False, "error": "invalid_task_schema"}
    return [row for row in rows if isinstance(row, dict)], health


def _load_feed(
    storage_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload, health = _load_json_with_health(
        storage_root / "reports" / "feed.json", []
    )
    if not isinstance(payload, list):
        return [], {**health, "ok": False, "error": "invalid_feed_schema"}
    return [row for row in payload if isinstance(row, dict)], health


def _load_dispatch_completions(
    storage_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload, health = _load_json_with_health(
        storage_root / "ops" / "dispatch_state.json", {}
    )
    completions = (
        payload.get("completions")
        if isinstance(payload, dict)
        else None
    )
    if not isinstance(completions, list):
        return [], {
            **health,
            "ok": False,
            "error": "invalid_dispatch_completion_schema",
        }
    rows = [row for row in completions if isinstance(row, dict)]
    invalid_timestamps = sum(
        1
        for row in rows
        if _try_parse_time(row.get("fire_at"))[0] is None
    )
    if invalid_timestamps:
        health = {
            **health,
            "ok": False,
            "error": "missing_or_malformed_dispatch_fire_timestamp",
            "invalid_timestamps": invalid_timestamps,
        }
    return rows, health


def _collect_evidence(
    gate: dict[str, Any],
    *,
    storage_root: Path,
    window_start: datetime,
    now: datetime,
    incidents: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    int,
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    evidence: list[dict[str, Any]] = []
    malformed = 0
    source_health: list[dict[str, Any]] = []
    for source in gate.get("evidence_sources") or []:
        if not isinstance(source, dict) or source.get("kind") != "jsonl":
            continue
        path = storage_root / str(source.get("path") or "")
        rows, bad, health = _read_jsonl(path)
        malformed += bad
        invalid_timestamps = 0
        selector = source.get("match") if isinstance(source.get("match"), dict) else {}
        for row in rows:
            raw_timestamp = _row_timestamp(row)
            ts, bad_timestamp = _try_parse_time(raw_timestamp)
            if bad_timestamp or ts is None:
                invalid_timestamps += 1
                malformed += 1
                continue
            # A completed review consumes evidence through its exact watermark.
            # The lower boundary is therefore exclusive.
            if ts <= window_start or ts > now:
                continue
            if selector and not _matches(row, selector):
                continue
            evidence.append({"source_path": str(path), **row})
        health["invalid_timestamps"] = invalid_timestamps
        health["malformed_rows"] = int(health["malformed_rows"]) + invalid_timestamps
        if invalid_timestamps:
            health["ok"] = False
            health["error"] = "malformed_timestamp_rows"
        source_health.append(health)

    kinds = {
        str(kind)
        for kind in (gate.get("incident_kinds") or [])
        if isinstance(kind, str)
    }
    incident_hits: list[dict[str, Any]] = []
    for row in incidents:
        if str(row.get("kind") or "") not in kinds:
            continue
        last_seen, malformed_ts = _try_parse_time(row.get("last_seen_at"))
        if malformed_ts:
            malformed += 1
            continue
        if (
            last_seen or datetime.min.replace(tzinfo=timezone.utc)
        ) > window_start:
            incident_hits.append(row)
    return evidence, malformed, incident_hits, source_health


def _join_outcomes(
    evidence: list[dict[str, Any]],
    *,
    tasks: list[dict[str, Any]],
    feed: list[dict[str, Any]],
    dispatch_completions: list[dict[str, Any]],
    now: datetime,
    strategy: str,
    deadline_required: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    task_by_id = {
        str(row.get("id")): row
        for row in tasks
        if isinstance(row.get("id"), str)
    }
    published_ids = {
        str(row.get("id"))
        for row in feed
        if row.get("status") in (None, "published") and row.get("id")
    }
    published_event_stages = {
        identity
        for row in feed
        if row.get("status") in (None, "published")
        for identity in [_event_identity(row)]
        if identity
    }

    by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in evidence:
        candidate = _candidate_id(row)
        if candidate:
            by_candidate[candidate].append(row)

    outcome_sets: dict[str, set[str]] = {
        name: set()
        for name in (
            "published",
            "succeeded",
            "failed",
            "missed_deadline",
            "sequence_coverage_gap",
            "retry",
            "waiver",
            "superseded",
            "observed",
            "dispatch_fire",
            "task_claim",
            "worker_failed",
            "queued",
            "in_flight",
            "blocked",
            "unjoined",
        )
    }
    malformed_task_deadlines: set[str] = set()
    details: list[dict[str, Any]] = []
    for candidate, rows in by_candidate.items():
        joined: set[str] = set()
        target_ids = {
            str(row.get("target_id") or row.get("task_id") or "")
            for row in rows
            if row.get("target_id") or row.get("task_id")
        }
        if strategy == "candidate_task":
            target_ids.add(candidate)
        tasks_for_candidate = [
            task_by_id[target_id]
            for target_id in target_ids
            if target_id in task_by_id
        ]
        candidate_event = (
            _candidate_event_identity(candidate)
            if strategy == "candidate_or_event_stage"
            else None
        )
        if (
            strategy == "candidate_or_event_stage"
            and (
                candidate in published_ids
                or candidate_event in published_event_stages
            )
        ):
            joined.add("published")
        explicit_decisions = {
            str(row.get(field) or "").strip().casefold()
            for row in rows
            for field in ("action", "decision", "outcome")
        }
        if explicit_decisions & {"retry", "retried"}:
            joined.add("retry")
        if explicit_decisions & {"waive", "waiver", "unlock", "bypass"}:
            joined.add("waiver")
        if strategy == "incident_or_generation":
            matching_jobs = [
                item
                for item in dispatch_completions
                if str(item.get("job_id") or "") == candidate
            ]
            if matching_jobs:
                joined.add("dispatch_fire")
                if any(
                    isinstance(item.get("workspace"), dict)
                    and item["workspace"].get("task_id")
                    for item in matching_jobs
                ):
                    joined.add("task_claim")
                if any(
                    int(item.get("exit_code") or 0) != 0
                    for item in matching_jobs
                ):
                    joined.add("worker_failed")
        if strategy == "dispatch_signature":
            for row in rows:
                decision_at, malformed = _try_parse_time(
                    _row_timestamp(row)
                )
                if malformed or decision_at is None:
                    continue
                matching_fires = []
                for completion in dispatch_completions:
                    fire_at, bad_fire_at = _try_parse_time(
                        completion.get("fire_at")
                    )
                    if (
                        bad_fire_at
                        or fire_at is None
                        or (fire_at - decision_at).total_seconds() < 0
                        or (fire_at - decision_at).total_seconds() > 600
                    ):
                        continue
                    matching_fires.append(completion)
                if not matching_fires:
                    continue
                joined.add("dispatch_fire")
                if any(
                    isinstance(item.get("workspace"), dict)
                    and item["workspace"].get("task_id")
                    and item["workspace"].get("claim_session_id")
                    for item in matching_fires
                ):
                    joined.add("task_claim")
                if any(
                    int(item.get("exit_code") or 0) != 0
                    or str(item.get("outcome") or "")
                    in {
                        "fatal_fastfail",
                        "kill_failed_orphan_drained",
                        "external_signal",
                    }
                    for item in matching_fires
                ):
                    joined.add("worker_failed")

        for task in tasks_for_candidate:
            status = str(task.get("status") or "").lower()
            if status in {"pending", "pending_main_thread"}:
                joined.add("queued")
            if status in {"claimed", "in_progress", "awaiting_agent_job"}:
                joined.add("in_flight")
            if status == "blocked":
                joined.add("blocked")
            if status == "succeeded":
                joined.add("succeeded")
            if status == "failed":
                joined.add("failed")
            if status == "superseded" or task.get("superseded_by"):
                joined.add("superseded")
            if task.get("gate_waiver") or (task.get("details") or {}).get(
                "gate_waiver"
            ):
                joined.add("waiver")
            deadline_raw = task.get("deadline")
            deadline, malformed_deadline = _try_parse_time(deadline_raw)
            if malformed_deadline or (
                deadline_required and deadline is None
            ):
                malformed_task_deadlines.add(
                    str(task.get("id") or "<unknown>")
                )
            if (
                deadline is not None
                and deadline < now
                and status in ACTIVE_TASK_STATUSES
            ):
                joined.add("missed_deadline")
            task_event = _event_identity(task)
            if (
                task_event
                and task_event not in published_event_stages
                and (
                    status in {
                        "failed",
                        "expired",
                        "superseded",
                        "succeeded",
                    }
                    or (
                        deadline is not None
                        and deadline < now
                        and status in ACTIVE_TASK_STATUSES
                    )
                )
            ):
                joined.add("sequence_coverage_gap")
            if task_event and task_event in published_event_stages:
                joined.add("published")

        if not joined:
            joined.add("unjoined")
        for outcome in joined:
            outcome_sets[outcome].add(candidate)
        details.append(
            {
                "candidate_id": candidate,
                "decision_count": len(rows),
                "task_ids": sorted(target_ids),
                "outcomes": sorted(joined),
            }
        )

    return {
        **{name: len(values) for name, values in outcome_sets.items()},
        "candidate_outcomes": sorted(details, key=lambda row: row["candidate_id"]),
    }, {
        "malformed_task_deadlines": sorted(malformed_task_deadlines),
    }


def _review_due(
    gate: dict[str, Any],
    *,
    trigger_count: int,
    distinct_candidates: int,
    incident_occurrences: int,
    outcomes: dict[str, Any],
) -> tuple[bool, list[str]]:
    policy = gate["review_policy"]
    reasons: list[str] = []
    max_raw = int(policy.get("max_raw_triggers") or 0)
    if max_raw and trigger_count >= max_raw:
        reasons.append(f"raw_triggers={trigger_count}>={max_raw}")
    minimum = int(policy.get("min_distinct_candidates") or 0)
    if minimum and distinct_candidates >= minimum:
        reasons.append(
            f"distinct_candidates={distinct_candidates}>={minimum}"
        )
    harm = sum(
        int(outcomes.get(name) or 0)
        for name in ("missed_deadline", "sequence_coverage_gap", "failed")
    )
    max_harm = int(policy.get("max_harm_outcomes") or 0)
    if max_harm and harm >= max_harm:
        reasons.append(f"harm_outcomes={harm}>={max_harm}")
    waivers = int(outcomes.get("waiver") or 0)
    max_waivers = int(
        policy.get("max_false_positive_signals")
        or policy.get("max_waivers")
        or 0
    )
    if max_waivers and waivers >= max_waivers:
        reasons.append(f"false_positive_signals={waivers}>={max_waivers}")
    min_occurrences = int(policy.get("min_incident_occurrences") or 0)
    if min_occurrences and incident_occurrences >= min_occurrences:
        reasons.append(
            f"incident_occurrences={incident_occurrences}>={min_occurrences}"
        )
    return bool(reasons), reasons


def _existing_open_review(
    tasks: list[dict[str, Any]], gate_id: str
) -> dict[str, Any] | None:
    return next(
        (
            row
            for row in tasks
            if row.get("gate_review_id") == gate_id
            and str(row.get("status") or "") in ACTIVE_TASK_STATUSES
        ),
        None,
    )


def _review_watermark(
    gate: dict[str, Any],
    tasks: list[dict[str, Any]],
) -> datetime | None:
    """Latest mechanically valid adjudication consumed by this audit."""

    gate_id = str(gate["gate_id"])
    lifecycle = gate.get("lifecycle") or {}
    registry_task_id = str(lifecycle.get("review_task_id") or "")
    registry_action = str(lifecycle.get("last_action") or "")
    registry_time, registry_bad = _try_parse_time(
        lifecycle.get("last_reviewed_at")
    )
    if (
        not registry_task_id
        or registry_action not in REVIEW_ACTIONS
        or registry_bad
        or registry_time is None
    ):
        return None
    candidates: list[datetime] = []
    for task in tasks:
        if (
            task.get("gate_review_id") != gate_id
            or task.get("id") != registry_task_id
            or str(task.get("status") or "") != "succeeded"
            or task.get("gate_decision") != registry_action
            or not str(task.get("gate_live_readback") or "").strip()
            or task.get("gate_registry_reviewed_at")
            != lifecycle.get("last_reviewed_at")
        ):
            continue
        completed_at, malformed_completed = _try_parse_time(
            task.get("completed_at")
        )
        watermark, malformed_watermark = _try_parse_time(
            task.get("gate_review_watermark") or task.get("created_at")
        )
        if (
            malformed_completed
            or completed_at is None
            or malformed_watermark
            or watermark is None
            or watermark > registry_time
            or registry_time > completed_at
        ):
            continue
        candidates.append(watermark)
    return max(candidates) if candidates else None


def _materialize_review_task(
    gate: dict[str, Any],
    verdict: dict[str, Any],
    *,
    registry: dict[str, Any],
    queue_path: Path,
    tasks: list[dict[str, Any]],
    window_start: datetime,
    now: datetime,
    review_cycle_at: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    from .next_tasks import append_task_record

    gate_id = str(gate["gate_id"])
    existing = _existing_open_review(tasks, gate_id)
    if existing is not None:
        return existing, False
    cycle_at = review_cycle_at or now
    cycle_hash = hashlib.sha256(
        f"{gate_id}:{cycle_at.isoformat()}".encode("utf-8")
    ).hexdigest()[:12]
    cycle = f"{cycle_at.strftime('%Y%m%dT%H%M%S')}_{cycle_hash}"
    task_id = f"control_gate_review_{gate_id}_{cycle}"
    defaults = registry.get("review_task") or {}
    record = {
        "id": task_id,
        "title": f"[Gate PDCA] {gate_id} lifecycle review",
        "description": "\n".join(
            [
                f"gate_id: {gate_id}",
                f"owner: {gate.get('owner')}",
                f"mode: {gate.get('mode')}",
                f"invariant: {gate.get('invariant')}",
                f"protected_edges: {gate.get('protected_graph', {}).get('edges')}",
                f"blocked_downstream_edges: {gate.get('blocked_downstream_edges')}",
                f"review_reasons: {verdict['review']['reasons']}",
                f"evidence: {verdict['evidence']}",
                f"outcomes: {verdict['outcomes']}",
                "",
                "Required adjudication: retain / recalibrate / "
                "downgrade_to_warn / retire.",
                "不得只標 observing；裁決後更新 registry lifecycle 的 "
                "last_action/last_reviewed_at/review_task_id + tests + "
                "live read-back。",
                "complete 時必傳 --gate-decision 與 --gate-live-readback；"
                "task_pool_claim 會回讀 registry Act receipt，不一致則拒絕結案。",
            ]
        ),
        "task_type": str(defaults.get("task_type") or "platform_ops"),
        "priority": int(defaults.get("priority") or 2),
        "status": "pending",
        "source": str(defaults.get("source") or "control_gate_lifecycle"),
        "dispatch_lane": "agent",
        "created_at": now.isoformat(),
        "gate_review_id": gate_id,
        "gate_review_window_start": window_start.isoformat(),
        "gate_review_watermark": (
            review_cycle_at.isoformat() if review_cycle_at is not None else None
        ),
        "acceptance": [
            "choose exactly one: retain/recalibrate/downgrade_to_warn/retire",
            "update registry lifecycle last_action/last_reviewed_at/review_task_id",
            "attach downstream outcome read-back",
            "complete with --gate-decision and --gate-live-readback",
        ],
    }
    stored, created = append_task_record(
        record,
        path=queue_path,
        if_exists="skip",
        # gate_id + evidence watermark are the exact identity. Generic title
        # similarity ("dispatch") would incorrectly collapse two distinct
        # protected graph edges into one review.
        semantic_dedupe=False,
        active_unique_fields=("gate_review_id",),
    )
    return stored, created


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    guard_canonical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    json.loads(tmp.read_text(encoding="utf-8"))
    tmp.replace(path)


def audit_control_gates(
    *,
    storage_dir: str = "storage",
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    queue_path: str | Path | None = None,
    state_path: str | Path | None = None,
    now: datetime | None = None,
    materialize_reviews: bool = False,
    write_state: bool = False,
) -> dict[str, Any]:
    """Join gate decisions to graph outcomes and optionally actuate PDCA review."""

    current = (
        now.astimezone(timezone.utc)
        if now is not None
        else datetime.now(timezone.utc)
    )
    storage_root = project_path(storage_dir)
    queue = (
        Path(queue_path)
        if queue_path is not None
        else storage_root / "next_tasks.json"
    )
    state = (
        Path(state_path)
        if state_path is not None
        else storage_root / DEFAULT_STATE_RELATIVE_PATH
    )
    registry = load_gate_registry(registry_path)
    tasks, tasks_health = _load_tasks(queue)
    feed, feed_health = _load_feed(storage_root)
    incidents, incidents_health = _load_incidents(storage_root)
    dispatch_completions, dispatch_health = _load_dispatch_completions(
        storage_root
    )

    gate_verdicts: list[dict[str, Any]] = []
    created_reviews: list[str] = []
    existing_reviews: list[str] = []
    for gate in registry["gates"]:
        window_hours = float(gate["review_policy"]["window_hours"])
        lookback_start = current - timedelta(hours=window_hours)
        reviewed_through = _review_watermark(gate, tasks)
        window_start = max(
            candidate
            for candidate in (lookback_start, reviewed_through)
            if candidate is not None
        )
        evidence, malformed, incident_hits, source_health = _collect_evidence(
            gate,
            storage_root=storage_root,
            window_start=window_start,
            now=current,
            incidents=incidents,
        )
        outcome_join = str(gate["outcome_join"])
        if outcome_join in {"candidate_task", "candidate_or_event_stage"}:
            source_health.append(tasks_health)
        if outcome_join == "candidate_or_event_stage":
            source_health.append(feed_health)
        if outcome_join == "incident_or_generation":
            source_health.append(incidents_health)
        if outcome_join in {"dispatch_signature", "incident_or_generation"}:
            source_health.append(dispatch_health)
        candidates = {
            candidate
            for row in evidence
            for candidate in [_candidate_id(row)]
            if candidate
        }
        incident_occurrences = sum(
            int(row.get("occurrence_count") or 1)
            for row in incident_hits
        )
        outcomes, outcome_diagnostics = _join_outcomes(
            evidence,
            tasks=tasks,
            feed=feed,
            dispatch_completions=dispatch_completions,
            now=current,
            strategy=outcome_join,
            deadline_required=bool(gate["deadline_required"]),
        )
        if outcome_diagnostics["malformed_task_deadlines"]:
            source_health.append(
                {
                    **tasks_health,
                    "ok": False,
                    "error": "missing_or_malformed_task_deadlines",
                    "task_ids": outcome_diagnostics[
                        "malformed_task_deadlines"
                    ],
                }
            )
        outcomes["incident_open"] = sum(
            1 for row in incident_hits if str(row.get("state") or "") != "resolved"
        )
        outcomes["incident_resolved"] = sum(
            1 for row in incident_hits if str(row.get("state") or "") == "resolved"
        )
        outcomes["incident_recurrence"] = sum(
            1
            for row in incident_hits
            if int(row.get("occurrence_count") or 1) > 1
            or int(row.get("episode_count") or 1) > 1
        )
        due, reasons = _review_due(
            gate,
            trigger_count=len(evidence),
            distinct_candidates=len(candidates),
            incident_occurrences=incident_occurrences,
            outcomes=outcomes,
        )
        evidence_times = [
            parsed
            for row in evidence
            for parsed, malformed_ts in [
                _try_parse_time(_row_timestamp(row))
            ]
            if not malformed_ts and parsed is not None
        ]
        incident_times = [
            parsed
            for row in incident_hits
            for parsed, malformed_ts in [_try_parse_time(row.get("last_seen_at"))]
            if not malformed_ts and parsed is not None
        ]
        newest_evidence_at = max(evidence_times + incident_times, default=None)
        verdict = {
            "gate_id": gate["gate_id"],
            "owner": gate["owner"],
            "mode": gate["mode"],
            "identity_strength": gate["identity_strength"],
            "invariant": gate["invariant"],
            "protected_graph": gate["protected_graph"],
            "blocked_downstream_edges": gate["blocked_downstream_edges"],
            "incident_refs": gate.get("incident_refs") or [],
            "window": {
                "hours": window_hours,
                "lookback_start": lookback_start.isoformat(),
                "start": window_start.isoformat(),
                "end": current.isoformat(),
                "last_reviewed_at": (
                    reviewed_through.isoformat()
                    if reviewed_through is not None
                    else None
                ),
                "newest_evidence_at": (
                    newest_evidence_at.isoformat()
                    if newest_evidence_at is not None
                    else None
                ),
            },
            "evidence": {
                "trigger_count": len(evidence),
                "distinct_candidates": len(candidates),
                "malformed_rows": malformed,
                "incident_count": len(incident_hits),
                "incident_occurrences": incident_occurrences,
                "incident_ids": sorted(
                    str(row.get("incident_id") or "") for row in incident_hits
                ),
                "source_health": source_health,
            },
            "outcomes": outcomes,
            "review": {"due": due, "reasons": reasons},
            "pdca_phase": (
                "act"
                if due
                else "check"
                if evidence or incident_hits
                else "plan"
            ),
            "allowed_actions": list(REVIEW_ACTIONS),
        }
        gate_verdicts.append(verdict)
        if materialize_reviews and due:
            stored, created = _materialize_review_task(
                gate,
                verdict,
                registry=registry,
                queue_path=queue,
                tasks=tasks,
                window_start=window_start,
                now=current,
                review_cycle_at=newest_evidence_at,
            )
            review_id = str(stored.get("id") or "")
            if created:
                created_reviews.append(review_id)
                tasks.append(stored)
            elif review_id:
                existing_reviews.append(review_id)

    result = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": current.isoformat(),
        "registry_path": str(Path(registry_path)),
        "registry_owner": registry["owner"],
        "gates": gate_verdicts,
        "summary": {
            "gate_count": len(gate_verdicts),
            "review_due_count": sum(
                1 for verdict in gate_verdicts if verdict["review"]["due"]
            ),
            "hard_gate_count": sum(
                1 for verdict in gate_verdicts if verdict["mode"] in HARD_MODES
            ),
            "unhealthy_source_count": sum(
                1
                for verdict in gate_verdicts
                for source in verdict["evidence"]["source_health"]
                if not source["ok"]
            ),
        },
        "review_tasks": {
            "created_count": len(created_reviews),
            "created_ids": created_reviews,
            "existing_ids": sorted(set(existing_reviews)),
        },
    }
    unhealthy_sources = [
        {
            "gate_id": verdict["gate_id"],
            **source,
        }
        for verdict in gate_verdicts
        for source in verdict["evidence"]["source_health"]
        if not source["ok"]
    ]
    result["audit_health"] = {
        "healthy": not unhealthy_sources,
        "unhealthy_sources": unhealthy_sources,
    }
    if write_state:
        _write_state(state, result)
    return result


def _append_control_decisions(
    rows: list[dict[str, Any]], *, storage_dir: str
) -> None:
    if not rows:
        return
    storage_root = project_path(storage_dir)
    path = storage_root / CONTROL_DECISIONS_RELATIVE_PATH
    guard_canonical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with shared_state_lock("control_gate_decisions", storage_dir=str(storage_root)):
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def record_dispatch_gate_decisions(
    report: dict[str, Any],
    *,
    storage_dir: str = "storage",
) -> dict[str, Any]:
    """Persist collision/starvation decisions from one canonical dispatch report."""

    starvation = (
        report.get("starvation")
        if isinstance(report.get("starvation"), dict)
        else {}
    )
    timestamp = str(
        report.get("generated_at") or datetime.now(timezone.utc).isoformat()
    )
    rows: list[dict[str, Any]] = []
    for item in starvation.get("collision_blocked_tasks") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        rows.append(
            {
                "ts": timestamp,
                "gate_id": "dispatch_collision",
                "decision": "block",
                "candidate_id": str(item["id"]),
                "reason": (
                    f"worktree={item.get('worktree')} commit={item.get('commit')}"
                ),
                "protected_edge": "pending_task -> agent_workspace",
            }
        )
    admitted_candidate_ids = {
        str(item["id"])
        for item in report.get("dispatch_candidates") or []
        if isinstance(item, dict) and item.get("id")
    }
    if starvation.get("locked"):
        for item in starvation.get("starved_tasks") or []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            candidate_id = str(item["id"])
            # A lockout observation is not itself a graph intervention.  Record
            # the gate only when this report actually admits the starved task
            # onto pending_task -> dispatch_candidate.  In particular, a
            # zero-capacity pass has no candidate edge to constrain and must not
            # inflate lifecycle trigger counts on every dry observation.
            if candidate_id not in admitted_candidate_ids:
                continue
            rows.append(
                {
                    "ts": timestamp,
                    "gate_id": "dispatch_starvation_lockout",
                    "decision": "constrain",
                    "candidate_id": candidate_id,
                    "reason": (
                        f"age_hours={item.get('age_hours')} "
                        f"threshold_hours={item.get('threshold_hours')}"
                    ),
                    "protected_edge": "pending_task -> dispatch_candidate",
                }
            )
    _append_control_decisions(rows, storage_dir=storage_dir)
    return {
        "recorded": len(rows),
        "gate_ids": sorted({str(row["gate_id"]) for row in rows}),
    }
