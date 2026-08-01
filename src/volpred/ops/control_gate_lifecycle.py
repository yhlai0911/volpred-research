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
import math
import re
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
MAX_TIMEDELTA_WHOLE_SECONDS = (
    timedelta.max.days * 24 * 60 * 60 + timedelta.max.seconds
)
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
INCIDENT_METRICS = {"raw_observations", "instance_transitions"}
INSTANCE_TRANSITION_TYPES = {"opened", "reopened"}
OUTCOME_JOIN_STRATEGIES = {
    "candidate_or_event_stage",
    "candidate_or_feed",
    "candidate_task",
    "dispatch_signature",
    "incident_or_generation",
}
OUTCOME_NAMES = {
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
}


def control_gate_inventory_snapshot_payload(
    *,
    watermark: str,
    gaps: list[dict[str, Any]],
    unclassified: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return the complete, deterministic inventory snapshot identity."""

    def canonical_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = [
            json.loads(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            for row in rows
            if isinstance(row, dict)
        ]
        return sorted(
            normalized,
            key=lambda row: json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )

    return {
        "watermark": str(watermark),
        "inventory_gaps": canonical_rows(gaps),
        "inventory_unclassified_blocking": canonical_rows(unclassified),
    }


def control_gate_inventory_snapshot_hash(
    *,
    watermark: str,
    gaps: list[dict[str, Any]],
    unclassified: list[dict[str, Any]],
) -> str:
    """Hash the full canonical snapshot, not only gate IDs and row counts."""

    payload = control_gate_inventory_snapshot_payload(
        watermark=watermark,
        gaps=gaps,
        unclassified=unclassified,
    )
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:12]


def _review_task_id(gate_id: str, cycle_at: datetime) -> str:
    """Return the lossless gate + evidence-watermark task identity."""

    cycle_hash = hashlib.sha256(
        f"{gate_id}:{cycle_at.isoformat()}".encode("utf-8")
    ).hexdigest()[:12]
    cycle = f"{cycle_at.strftime('%Y%m%dT%H%M%S')}_{cycle_hash}"
    return f"control_gate_review_{gate_id}_{cycle}"


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


def _validate_discovery_policy(payload: dict[str, Any]) -> None:
    discovery = payload.get("discovery")
    if not isinstance(discovery, dict):
        raise ValueError("control gate registry requires discovery policy")
    if float(discovery.get("window_hours") or 0) <= 0:
        raise ValueError("discovery.window_hours must be positive")
    if int(discovery.get("high_frequency_threshold") or 0) <= 0:
        raise ValueError(
            "discovery.high_frequency_threshold must be positive"
        )
    if not isinstance(discovery.get("incidents_required"), bool):
        raise ValueError("discovery.incidents_required must be boolean")
    identity_required_after, malformed_identity_ratchet = _try_parse_time(
        discovery.get("candidate_identity_required_after")
    )
    if malformed_identity_ratchet or identity_required_after is None:
        raise ValueError(
            "discovery.candidate_identity_required_after is required"
        )
    sources = discovery.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("discovery.sources must be a non-empty list")
    for source in sources:
        if not isinstance(source, dict) or source.get("kind") != "jsonl":
            raise ValueError("every discovery source must be a jsonl object")
        if not str(source.get("path") or "").strip():
            raise ValueError("every discovery source requires path")
        for field in ("identity_fields", "decision_fields", "blocking_values"):
            values = source.get(field)
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value.strip()
                for value in values
            ):
                raise ValueError(
                    f"discovery source {source['path']!r} requires {field}"
                )
        aliases = source.get("action_gate_aliases", {})
        if not isinstance(aliases, dict) or not all(
            isinstance(key, str)
            and key.strip()
            and isinstance(value, str)
            and value.strip()
            for key, value in aliases.items()
        ):
            raise ValueError(
                f"discovery source {source['path']!r} has invalid "
                "action_gate_aliases"
            )


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
    _validate_discovery_policy(payload)
    gates = payload.get("gates")
    if not isinstance(gates, list) or not gates:
        raise ValueError("control gate registry requires a non-empty gates list")

    seen: set[str] = set()
    incident_kind_owners: dict[str, str] = {}
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
        incident_kinds = gate.get("incident_kinds")
        if not isinstance(incident_kinds, list) or not all(
            isinstance(kind, str) and kind.strip()
            for kind in incident_kinds
        ):
            raise ValueError(f"gate {gate_id!r} requires valid incident_kinds")
        for raw_kind in incident_kinds:
            kind = raw_kind.strip()
            prior_owner = incident_kind_owners.get(kind)
            if prior_owner is not None:
                raise ValueError(
                    f"incident kind {kind!r} is owned by both "
                    f"{prior_owner!r} and {gate_id!r}"
                )
            incident_kind_owners[kind] = gate_id
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
        if (
            str(policy.get("incident_metric") or "raw_observations")
            not in INCIDENT_METRICS
        ):
            raise ValueError(
                f"gate {gate_id!r} review_policy.incident_metric must be "
                f"one of {sorted(INCIDENT_METRICS)!r}"
            )
        reason_prefixes = policy.get("incident_transition_reason_prefixes")
        if reason_prefixes is not None and (
            str(policy.get("incident_metric") or "raw_observations")
            != "instance_transitions"
            or not isinstance(reason_prefixes, list)
            or not reason_prefixes
            or not all(
                isinstance(prefix, str) and prefix.strip()
                for prefix in reason_prefixes
            )
            or len({prefix.strip() for prefix in reason_prefixes})
            != len(reason_prefixes)
        ):
            raise ValueError(
                f"gate {gate_id!r} review_policy."
                "incident_transition_reason_prefixes requires unique "
                "non-empty strings with incident_metric=instance_transitions"
            )
        safe_reasons = policy.get("incident_transition_safe_reasons")
        if safe_reasons is not None and (
            str(policy.get("incident_metric") or "raw_observations")
            != "instance_transitions"
            or not isinstance(safe_reasons, list)
            or not safe_reasons
            or not all(
                isinstance(reason, str) and reason.strip()
                for reason in safe_reasons
            )
            or len({reason.strip() for reason in safe_reasons})
            != len(safe_reasons)
            or not reason_prefixes
        ):
            raise ValueError(
                f"gate {gate_id!r} review_policy."
                "incident_transition_safe_reasons requires unique "
                "non-empty strings, owned reason prefixes, and "
                "incident_metric=instance_transitions"
            )
        reason_receipt = policy.get("incident_transition_reason_receipt")
        if reason_receipt is not None:
            raw_receipt_path = (
                reason_receipt.get("path")
                if isinstance(reason_receipt, dict)
                else None
            )
            receipt_path = (
                raw_receipt_path.strip()
                if isinstance(raw_receipt_path, str)
                else ""
            )
            receipt_events = (
                reason_receipt.get("events")
                if isinstance(reason_receipt, dict)
                else None
            )
            receipt_fields = (
                [
                    reason_receipt.get(name).strip()
                    for name in (
                        "identity_field",
                        "reason_field",
                        "timestamp_field",
                    )
                    if isinstance(reason_receipt.get(name), str)
                ]
                if isinstance(reason_receipt, dict)
                else []
            )
            raw_max_age_seconds = (
                reason_receipt.get("max_age_seconds")
                if isinstance(reason_receipt, dict)
                else None
            )
            has_valid_max_age_seconds = (
                isinstance(raw_max_age_seconds, int)
                and not isinstance(raw_max_age_seconds, bool)
                and 0 < raw_max_age_seconds <= MAX_TIMEDELTA_WHOLE_SECONDS
            ) or (
                isinstance(raw_max_age_seconds, float)
                and math.isfinite(raw_max_age_seconds)
                and 0 < raw_max_age_seconds <= MAX_TIMEDELTA_WHOLE_SECONDS
            )
            if (
                str(policy.get("incident_metric") or "raw_observations")
                != "instance_transitions"
                or not isinstance(reason_receipt, dict)
                or not reason_prefixes
                or not receipt_path
                or Path(receipt_path).is_absolute()
                or ".." in Path(receipt_path).parts
                or not isinstance(receipt_events, list)
                or not receipt_events
                or not all(
                    isinstance(event, str) and event.strip()
                    for event in receipt_events
                )
                or len({event.strip() for event in receipt_events})
                != len(receipt_events)
                or len(receipt_fields) != 3
                or not all(receipt_fields)
                or len(set(receipt_fields)) != len(receipt_fields)
                or not has_valid_max_age_seconds
            ):
                raise ValueError(
                    f"gate {gate_id!r} review_policy."
                    "incident_transition_reason_receipt requires a relative "
                    "path, unique events/fields, positive max_age_seconds, "
                    "and incident_metric=instance_transitions"
                )
        harm_outcomes = policy.get("harm_outcomes")
        if (
            not isinstance(harm_outcomes, list)
            or not harm_outcomes
            or not all(
                isinstance(name, str) and name in OUTCOME_NAMES
                for name in harm_outcomes
            )
        ):
            raise ValueError(
                f"gate {gate_id!r} requires valid "
                "review_policy.harm_outcomes"
            )
        if float(policy.get("max_review_age_hours") or 0) <= 0:
            raise ValueError(
                f"gate {gate_id!r} requires positive "
                "review_policy.max_review_age_hours"
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
        review_anchor, malformed_anchor = _try_parse_time(
            lifecycle.get("review_anchor_at")
            if isinstance(lifecycle, dict)
            else None
        )
        if malformed_anchor or review_anchor is None:
            raise ValueError(
                f"gate {gate_id!r} lifecycle.review_anchor_at is required"
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
            review_task_id = str(lifecycle["review_task_id"])
            pattern = (
                rf"^control_gate_review_{re.escape(str(gate_id))}_"
                r"\d{8}T\d{6}_[0-9a-f]{12}$"
            )
            if re.fullmatch(pattern, review_task_id) is None:
                raise ValueError(
                    f"gate {gate_id!r} lifecycle.review_task_id has wrong "
                    "gate identity"
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


def _first_string(row: dict[str, Any], fields: list[str]) -> str:
    for field in fields:
        value = row.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _canonicalize_decision_row(
    row: dict[str, Any],
    source: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Resolve one decision identity once for inventory and per-gate PDCA.

    A producer-supplied gate identity is authoritative.  Action aliases exist
    only to recover historical action-only rows; the same action vocabulary can
    legitimately occur at a different graph layer (for example task-generation
    arc screening versus publisher arc screening).
    """

    decision = _first_string(row, list(source["decision_fields"]))
    explicit_values = [
        str(row[field]).strip()
        for field in source["identity_fields"]
        if isinstance(row.get(field), str) and str(row[field]).strip()
    ]
    explicit = explicit_values[0] if explicit_values else ""
    aliases = {
        str(key).casefold(): str(value)
        for key, value in source.get("action_gate_aliases", {}).items()
    }
    aliased = aliases.get(decision.casefold()) if decision else None
    conflict = len(set(explicit_values)) > 1
    gate_id = explicit or aliased
    if not gate_id and decision:
        gate_id = f"action:{decision.casefold()}"
    normalized = dict(row)
    if gate_id:
        normalized["gate_id"] = gate_id
        normalized["gate"] = gate_id
    return normalized, conflict


def _unclassified_signal_id(row: dict[str, Any]) -> str:
    """Return a stable identity for one blocking signal lacking gate identity."""

    payload = {
        key: row.get(key)
        for key in (
            "source_path",
            "timestamp",
            "decision",
            "candidate_id",
            "raw_gate_id",
            "raw_gate",
        )
    }
    return (
        "unclassified:"
        + hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
    )


def _discovery_source_for_path(
    registry: dict[str, Any],
    relative_path: str,
) -> dict[str, Any] | None:
    for source in registry["discovery"]["sources"]:
        if str(source.get("path") or "") == relative_path:
            return source
    return None


def _discover_gate_inventory(
    registry: dict[str, Any],
    *,
    storage_root: Path,
    now: datetime,
    incidents: list[dict[str, Any]],
    incidents_health: dict[str, Any],
) -> dict[str, Any]:
    """Find control decisions that escaped the registered graph inventory."""

    policy = registry["discovery"]
    window_hours = float(policy["window_hours"])
    window_start = now - timedelta(hours=window_hours)
    registered = {
        str(gate["gate_id"])
        for gate in registry["gates"]
    }
    observed: dict[str, dict[str, Any]] = {}
    source_health: list[dict[str, Any]] = []
    unclassified_blocking: list[dict[str, Any]] = []

    for source in policy["sources"]:
        path = storage_root / str(source["path"])
        rows, malformed, health = _read_jsonl(path)
        if (
            not source.get("required", True)
            and not health["ok"]
            and health.get("row_count") == 0
            and str(health.get("error") or "").startswith("FileNotFoundError")
        ):
            health = {
                **health,
                "ok": True,
                "error": None,
                "optional_missing": True,
            }
        decision_fields = list(source["decision_fields"])
        blocking_values = {
            str(value).casefold()
            for value in source["blocking_values"]
        }
        invalid_timestamps = 0
        identity_conflicts = 0
        for row in rows:
            timestamp, malformed_timestamp = _try_parse_time(
                _row_timestamp(row)
            )
            if malformed_timestamp or timestamp is None:
                invalid_timestamps += 1
                continue
            if timestamp <= window_start or timestamp > now:
                continue
            normalized_row, identity_conflict = (
                _canonicalize_decision_row(row, source)
            )
            identity_conflicts += int(identity_conflict)
            if identity_conflict:
                unclassified_blocking.append(
                    {
                        "source_path": str(path),
                        "timestamp": timestamp.isoformat(),
                        "decision": "identity_conflict",
                        "candidate_id": _candidate_id(row),
                        "raw_gate_id": row.get("gate_id"),
                        "raw_gate": row.get("gate"),
                    }
                )
                continue
            decision = _first_string(normalized_row, decision_fields)
            gate_id = _first_string(normalized_row, ["gate_id"])
            normalized_decision = decision.casefold()
            blocking = (
                normalized_row.get("blocked") is True
                or normalized_decision in blocking_values
                or normalized_decision.startswith(
                    ("block", "deny", "reject")
                )
            )
            candidate = _candidate_id(normalized_row)
            if not gate_id:
                if blocking:
                    unclassified_blocking.append(
                        {
                            "source_path": str(path),
                            "timestamp": timestamp.isoformat(),
                            "decision": decision,
                            "candidate_id": candidate,
                        }
                    )
                continue
            bucket = observed.setdefault(
                gate_id,
                {
                    "gate_id": gate_id,
                    "trigger_count": 0,
                    "blocking_count": 0,
                    "candidate_ids": set(),
                    "latest_at": timestamp,
                },
            )
            bucket["trigger_count"] += 1
            bucket["blocking_count"] += int(blocking)
            if candidate:
                bucket["candidate_ids"].add(candidate)
            bucket["latest_at"] = max(bucket["latest_at"], timestamp)
        health["invalid_timestamps"] = invalid_timestamps
        health["identity_conflicts"] = identity_conflicts
        health["malformed_rows"] = int(
            health.get("malformed_rows") or malformed
        ) + invalid_timestamps + identity_conflicts
        if invalid_timestamps or identity_conflicts:
            health["ok"] = False
            health["error"] = (
                "decision_identity_conflicts"
                if identity_conflicts
                else "malformed_timestamp_rows"
            )
        source_health.append(health)

    threshold = int(policy["high_frequency_threshold"])
    observed_rows: list[dict[str, Any]] = []
    unregistered: list[dict[str, Any]] = []
    for gate_id, bucket in observed.items():
        row = {
            "gate_id": gate_id,
            "registered": gate_id in registered,
            "trigger_count": bucket["trigger_count"],
            "blocking_count": bucket["blocking_count"],
            "distinct_candidates": len(bucket["candidate_ids"]),
            "latest_at": bucket["latest_at"].isoformat(),
        }
        observed_rows.append(row)
        reasons: list[str] = []
        if gate_id not in registered and row["blocking_count"]:
            reasons.append(
                f"blocking_signals={row['blocking_count']}"
            )
        if (
            gate_id not in registered
            and row["trigger_count"] >= threshold
        ):
            reasons.append(
                f"raw_triggers={row['trigger_count']}>={threshold}"
            )
        if reasons:
            unregistered.append({**row, "reasons": reasons})

    registered_incident_kinds = {
        str(kind): str(gate["gate_id"])
        for gate in registry["gates"]
        for kind in gate.get("incident_kinds") or []
        if isinstance(kind, str) and kind
    }
    incident_buckets: dict[str, dict[str, Any]] = {}
    for incident in incidents:
        kind = str(incident.get("kind") or "").strip()
        control_gate_id = str(
            incident.get("control_gate_id") or ""
        ).strip()
        is_control = (
            incident.get("is_control_intervention") is True
            or bool(control_gate_id)
        )
        last_seen, malformed_timestamp = _try_parse_time(
            incident.get("last_seen_at")
        )
        expected_gate_id = registered_incident_kinds.get(kind)
        explicit_gate_mismatch = bool(
            control_gate_id
            and expected_gate_id
            and control_gate_id != expected_gate_id
        )
        registered_identity = bool(
            expected_gate_id
            and (
                not control_gate_id
                or control_gate_id == expected_gate_id
            )
        )
        if (
            not kind
            or not is_control
            or malformed_timestamp
            or last_seen is None
            or last_seen <= window_start
            or last_seen > now
            or registered_identity
        ):
            continue
        inventory_gate_id = (
            control_gate_id
            if control_gate_id
            else f"incident:{kind}"
        )
        bucket = incident_buckets.setdefault(
            f"{kind}:{control_gate_id or '-'}",
            {
                "gate_id": inventory_gate_id,
                "incident_kind": kind,
                "incident_count": 0,
                "occurrence_count": 0,
                "latest_at": last_seen,
                "incident_ids": set(),
                "expected_gate_id": expected_gate_id,
                "explicit_gate_mismatch": explicit_gate_mismatch,
            },
        )
        bucket["incident_count"] += 1
        bucket["occurrence_count"] += int(
            incident.get("occurrence_count") or 1
        )
        bucket["latest_at"] = max(bucket["latest_at"], last_seen)
        if incident.get("incident_id"):
            bucket["incident_ids"].add(str(incident["incident_id"]))
    unregistered_incident_controls = [
        {
            **bucket,
            "latest_at": bucket["latest_at"].isoformat(),
            "incident_ids": sorted(bucket["incident_ids"]),
            "reasons": [
                f"incident_occurrences={bucket['occurrence_count']}",
                *(
                    [
                        "incident kind/gate mismatch: "
                        f"expected={bucket['expected_gate_id']} "
                        f"explicit={bucket['gate_id']}"
                    ]
                    if bucket["explicit_gate_mismatch"]
                    else []
                ),
            ],
        }
        for bucket in incident_buckets.values()
    ]
    for incident_gap in unregistered_incident_controls:
        unregistered.append(
            {
                "gate_id": incident_gap["gate_id"],
                "registered": False,
                "trigger_count": incident_gap["occurrence_count"],
                "blocking_count": incident_gap["occurrence_count"],
                "distinct_candidates": incident_gap["incident_count"],
                "latest_at": incident_gap["latest_at"],
                "reasons": incident_gap["reasons"],
                "incident_kind": incident_gap["incident_kind"],
                "incident_ids": incident_gap["incident_ids"],
            }
        )
    incident_inventory_health = {
        **incidents_health,
        "source_role": "incident_inventory",
    }
    if (
        policy.get("incidents_required", True) is False
        and not incident_inventory_health["ok"]
        and str(incident_inventory_health.get("error") or "").startswith(
            "FileNotFoundError"
        )
    ):
        incident_inventory_health.update(
            {"ok": True, "error": None, "optional_missing": True}
        )
    source_health.append(incident_inventory_health)

    for row in unclassified_blocking:
        row["inventory_signal_id"] = _unclassified_signal_id(row)

    newest_gap = max(
        [
            _parse_time(row["latest_at"])
            for row in unregistered
        ]
        + [
            _parse_time(row["timestamp"])
            for row in unclassified_blocking
        ],
        default=None,
    )
    return {
        "window": {
            "hours": window_hours,
            "start": window_start.isoformat(),
            "end": now.isoformat(),
        },
        "registered_gate_count": len(registered),
        "observed_gate_count": len(observed_rows),
        "observed_gates": sorted(
            observed_rows,
            key=lambda row: row["gate_id"],
        ),
        "unregistered_gates": sorted(
            unregistered,
            key=lambda row: row["gate_id"],
        ),
        "unregistered_incident_controls": sorted(
            unregistered_incident_controls,
            key=lambda row: row["gate_id"],
        ),
        "unclassified_blocking_count": len(unclassified_blocking),
        "unclassified_blocking": unclassified_blocking,
        "source_health": source_health,
        "newest_gap_at": (
            newest_gap.isoformat() if newest_gap is not None else None
        ),
    }


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
            candidate = value.strip()
            if field == "candidate_id":
                k_identity = _legacy_k_candidate_identity(candidate, row)
                if k_identity:
                    return k_identity
            return candidate
    reasons = row.get("reasons")
    if isinstance(reasons, dict):
        signature = reasons.get("signature")
        if isinstance(signature, str) and signature.strip():
            return signature.strip()
    title = row.get("new_title")
    if isinstance(title, str) and title.strip():
        return _title_identity(title)
    reason_text = str(row.get("reason") or "")
    k_match = re.search(r"\b[Kk](\d+[A-Za-z]?)\b", reason_text)
    if k_match:
        audience_match = re.search(
            r"\baudience=([^\s,)]+)",
            reason_text,
            flags=re.IGNORECASE,
        )
        return _k_audience_identity(
            f"K{k_match.group(1)}",
            (
                audience_match.group(1)
                if audience_match
                else row.get("audience_scope") or row.get("audience")
            ),
        )
    # Historical pre-write decisions sometimes had no title or task id.  Keep
    # their stable decision identity visible for PDCA (and explicitly marked
    # lower-quality) instead of dropping the receipt from graph accounting.
    action = row.get("action") or row.get("decision")
    reason = row.get("reason")
    matched_id = row.get("matched_id")
    if any(value not in (None, "") for value in (action, reason, matched_id)):
        material = json.dumps(
            {
                "action": action,
                "matched_id": matched_id,
                "reason": reason,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
        return f"decision:{digest}"
    return None


def _k_audience_identity(ref: Any, audience: Any) -> str | None:
    match = re.fullmatch(r"[Kk](\d+[A-Za-z]?)", str(ref or "").strip())
    scope = str(audience or "").strip().casefold()
    if not match or not scope or scope == "any":
        return None
    return f"k:K{match.group(1)}|audience:{scope}"


def _legacy_k_candidate_identity(
    candidate: str,
    row: dict[str, Any],
) -> str | None:
    if candidate.startswith("k:") and "|audience:" in candidate:
        return candidate
    reason = str(row.get("reason") or "")
    audience_match = re.search(
        r"\baudience=([^\s,)]+)",
        reason,
        flags=re.IGNORECASE,
    )
    return _k_audience_identity(
        candidate,
        (
            audience_match.group(1)
            if audience_match
            else row.get("audience_scope") or row.get("audience")
        ),
    )


def _title_identity(title: Any) -> str | None:
    normalized = " ".join(str(title or "").casefold().split())
    if not normalized:
        return None
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"title:{digest}"


def _feed_identities(item: dict[str, Any]) -> set[str]:
    """Typed identities by which a gate candidate can reach a feed row."""

    identities: set[str] = set()
    item_id = item.get("id")
    if isinstance(item_id, str) and item_id.strip():
        identities.add(item_id.strip())
    title_identity = _title_identity(item.get("title"))
    if title_identity:
        identities.add(title_identity)
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    refs = [
        *(item.get("experiment_refs") or []),
        *(details.get("experiment_refs") or []),
        *(item.get("tags") or []),
    ]
    for ref in refs:
        identity = _k_audience_identity(
            ref,
            item.get("audience") or details.get("audience"),
        )
        if identity:
            identities.add(identity)
    question_id = item.get("question_id") or details.get("question_id")
    if isinstance(question_id, str) and question_id.strip():
        identities.add(question_id.strip())
    return identities


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
    from .incident import CONTROL_GATE_BY_KIND

    payload, health = _load_json_with_health(
        storage_root / "ops" / "incidents.json", {}
    )
    incidents = (
        payload.get("incidents", {})
        if isinstance(payload, dict)
        else {}
    )
    if not isinstance(incidents, dict):
        return [], {**health, "ok": False, "error": "invalid_incident_schema"}
    rows = []
    for incident_id, raw_row in incidents.items():
        if not isinstance(raw_row, dict):
            continue
        row = {"incident_id": incident_id, **raw_row}
        kind = str(row.get("kind") or "").strip().lower()
        classified_gate = CONTROL_GATE_BY_KIND.get(kind)
        if row.get("control_gate_id") in (None, "") and classified_gate:
            row["control_gate_id"] = classified_gate
            row["is_control_intervention"] = True
            row["control_classification_source"] = "incident_kind_policy"
        rows.append(row)
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
    registry: dict[str, Any],
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
        discovery_source = _discovery_source_for_path(
            registry,
            str(source.get("path") or ""),
        )
        identity_conflicts = 0
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
            normalized_row = row
            if discovery_source is not None:
                normalized_row, conflict = _canonicalize_decision_row(
                    row,
                    discovery_source,
                )
                identity_conflicts += int(conflict)
                if conflict:
                    continue
            if selector and not _matches(normalized_row, selector):
                continue
            evidence.append({"source_path": str(path), **normalized_row})
        health["invalid_timestamps"] = invalid_timestamps
        health["identity_conflicts"] = identity_conflicts
        health["malformed_rows"] = (
            int(health["malformed_rows"])
            + invalid_timestamps
            + identity_conflicts
        )
        if invalid_timestamps or identity_conflicts:
            health["ok"] = False
            health["error"] = (
                "decision_identity_conflicts"
                if identity_conflicts
                else "malformed_timestamp_rows"
            )
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
    feed_by_identity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in feed:
        for identity in _feed_identities(item):
            feed_by_identity[identity].append(item)
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
        name: set() for name in OUTCOME_NAMES
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
        if strategy == "candidate_or_feed":
            for feed_item in feed_by_identity.get(candidate, []):
                status = str(
                    feed_item.get("status") or "published"
                ).casefold()
                if status == "published":
                    joined.add("published")
                elif status in {"draft", "scheduled"}:
                    joined.add("queued")
                elif status in {
                    "archived",
                    "retracted",
                    "unpublished",
                }:
                    joined.add("superseded")
                else:
                    joined.add("observed")
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
        if any(
            decision in {"block", "blocked", "hold", "constrain"}
            or decision.startswith(("block", "deny", "reject"))
            for decision in explicit_decisions
        ):
            joined.add("blocked")
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

        if not (joined - {"blocked"}):
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
    now: datetime,
    review_anchor_at: datetime,
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
        for name in policy["harm_outcomes"]
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
    max_review_age = float(policy["max_review_age_hours"])
    review_age = (now - review_anchor_at).total_seconds() / 3600.0
    if review_age >= max_review_age:
        reasons.append(
            f"review_age_hours={review_age:.1f}>={max_review_age:g}"
        )
    return bool(reasons), reasons


def _incident_occurrences_since(
    row: dict[str, Any],
    *,
    window_start: datetime,
    now: datetime,
) -> tuple[int, list[str]]:
    """Count failure-edge transitions, falling back for legacy incidents.

    Instance-aware detectors poll open edges repeatedly.  Their raw
    ``occurrence_count`` remains useful as an observation/noise metric, but
    PDCA review frequency must follow graph transitions within this review
    window or an unchanged incident will reopen a review forever.  Selecting
    this metric in the registry is the migration boundary: legacy poll counts
    are not replayed; :mod:`volpred.ops.incident` records one explicit baseline
    transition for each edge that is still open at migration time.
    """
    summary = _incident_transition_summary_since(
        row,
        window_start=window_start,
        now=now,
    )
    return int(summary["count"]), list(summary["diagnostics"])


def _index_transition_reason_receipts(
    rows: list[dict[str, Any]],
    *,
    policy: dict[str, Any],
) -> tuple[
    dict[str, list[tuple[datetime, str]]],
    list[str],
    int,
]:
    """Index immutable edge-opening receipts by their workspace identity."""

    accepted_events = {
        str(event).strip() for event in policy.get("events") or []
    }
    identity_field = str(policy["identity_field"])
    reason_field = str(policy["reason_field"])
    timestamp_field = str(policy["timestamp_field"])
    indexed: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    diagnostics: list[str] = []
    selected_count = 0
    for index, row in enumerate(rows):
        if str(row.get("event") or "").strip() not in accepted_events:
            continue
        selected_count += 1
        identity = str(row.get(identity_field) or "").strip()
        reason = str(row.get(reason_field) or "").strip()
        at, malformed_at = _try_parse_time(row.get(timestamp_field))
        if not identity:
            diagnostics.append(f"receipt[{index}]_missing_identity")
            continue
        if not reason:
            diagnostics.append(f"receipt[{index}]_missing_reason")
            continue
        if malformed_at or at is None:
            diagnostics.append(f"receipt[{index}]_invalid_at")
            continue
        indexed[identity].append((at, reason))
    for receipts in indexed.values():
        receipts.sort(key=lambda item: item[0])
    return dict(indexed), diagnostics, selected_count


def _reason_from_immutable_receipt(
    transition: dict[str, Any],
    *,
    transition_at: datetime,
    receipt_index: dict[str, list[tuple[datetime, str]]],
    max_age_seconds: float,
) -> tuple[str, str | None]:
    """Join a legacy reasonless transition to its closest prior receipt."""

    identity = str(transition.get("instance_key") or "").strip()
    if not identity:
        return "", "reason_receipt_missing_identity"
    eligible = [
        (at, reason)
        for at, reason in receipt_index.get(identity, [])
        if at < transition_at
        and (transition_at - at).total_seconds() <= max_age_seconds
    ]
    if not eligible:
        return "", "reason_receipt_unjoinable"
    eligible_reasons = {reason for _, reason in eligible}
    if len(eligible_reasons) != 1:
        return "", "reason_receipt_conflict"
    return next(iter(eligible_reasons)), None


def _classify_incident_transition_reason(
    reason: str,
    *,
    owned_prefixes: tuple[str, ...],
    safe_reasons: frozenset[str],
) -> str:
    """Return the gate-owned domain class for one immutable reason."""

    if any(reason.startswith(prefix) for prefix in owned_prefixes):
        return "owned"
    if reason in safe_reasons:
        return "safe"
    return "unknown"


def _incident_transition_summary_since(
    row: dict[str, Any],
    *,
    window_start: datetime,
    now: datetime,
    reason_prefixes: tuple[str, ...] = (),
    safe_reasons: frozenset[str] = frozenset(),
    receipt_index: dict[str, list[tuple[datetime, str]]] | None = None,
    receipt_max_age_seconds: float = 0,
) -> dict[str, Any]:
    """Summarize immutable incident-edge transitions for one review window.

    ``worker_orphaned`` is an aggregate workspace-adjudication incident: its
    instances include true ownership ambiguity as well as expected terminal
    settlements and merge/test failures.  A gate may therefore select the
    exact reason families it owns.  New transitions carry their opening
    reason; legacy transitions may join only to a time-bounded immutable
    receipt.  Mutable ``instances[].detail`` is deliberately never consulted.
    Missing, conflicting, or unknown reasons fail audit health closed.
    """
    if row.get("instance_transition_tracking") is not True:
        return {
            "count": 0,
            "diagnostics": [],
            "excluded_count": 0,
            "excluded_reasons": {},
            "unknown_count": 0,
            "unknown_reasons": {},
        }
    transitions = row.get("instance_transitions")
    if not isinstance(transitions, list):
        return {
            "count": 0,
            "diagnostics": ["instance_transitions_not_list"],
            "excluded_count": 0,
            "excluded_reasons": {},
            "unknown_count": 0,
            "unknown_reasons": {},
        }
    count = 0
    excluded_count = 0
    excluded_reasons: dict[str, int] = defaultdict(int)
    unknown_count = 0
    unknown_reasons: dict[str, int] = defaultdict(int)
    diagnostics: list[str] = []
    for index, transition in enumerate(transitions):
        if not isinstance(transition, dict):
            diagnostics.append(f"transition[{index}]_not_object")
            continue
        transition_type = str(transition.get("transition") or "")
        if transition_type not in INSTANCE_TRANSITION_TYPES:
            diagnostics.append(
                f"transition[{index}]_invalid_type:{transition_type or '<missing>'}"
            )
            continue
        at, malformed = _try_parse_time(transition.get("at"))
        if malformed or at is None:
            diagnostics.append(f"transition[{index}]_invalid_at")
            continue
        if window_start < at <= now:
            if reason_prefixes:
                reason = str(transition.get("reason") or "").strip()
                if not reason:
                    reason, receipt_error = _reason_from_immutable_receipt(
                        transition,
                        transition_at=at,
                        receipt_index=receipt_index or {},
                        max_age_seconds=receipt_max_age_seconds,
                    )
                    if receipt_error:
                        diagnostics.append(
                            f"transition[{index}]_{receipt_error}"
                        )
                        continue
                classification = _classify_incident_transition_reason(
                    reason,
                    owned_prefixes=reason_prefixes,
                    safe_reasons=safe_reasons,
                )
                if classification == "safe":
                    excluded_count += 1
                    excluded_reasons[reason] += 1
                    continue
                if classification == "unknown":
                    unknown_count += 1
                    unknown_reasons[reason] += 1
                    diagnostics.append(
                        f"transition[{index}]_unknown_reason:{reason}"
                    )
                    continue
            count += 1
    return {
        "count": count,
        "diagnostics": diagnostics,
        "excluded_count": excluded_count,
        "excluded_reasons": dict(sorted(excluded_reasons.items())),
        "unknown_count": unknown_count,
        "unknown_reasons": dict(sorted(unknown_reasons.items())),
    }


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
            or registry_task_id != _review_task_id(gate_id, watermark)
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
    task_id = _review_task_id(gate_id, cycle_at)
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


def _carry_forward_inventory_scope(
    inventory: dict[str, Any],
    *,
    registry: dict[str, Any],
    tasks: list[dict[str, Any]],
) -> None:
    """Keep unresolved inventory identities beyond the discovery window.

    This runs in the read model, not only in task materialization, so alerts,
    dashboards, and the task-completion contract all see the same durable
    inventory scope.
    """

    active_inventory = next(
        (
            row
            for row in tasks
            if row.get("control_gate_inventory_review") is True
            and str(row.get("status") or "") in ACTIVE_TASK_STATUSES
        ),
        None,
    )
    terminal_inventory = next(
        (
            row
            for row in reversed(tasks)
            if row.get("control_gate_inventory_review") is True
            and str(row.get("status") or "") not in ACTIVE_TASK_STATUSES
        ),
        None,
    )
    scope_carrier = active_inventory or terminal_inventory
    if scope_carrier is None:
        return
    carrier_readback = scope_carrier.get("inventory_live_readback")
    carrier_consumed = bool(
        isinstance(carrier_readback, dict)
        and carrier_readback.get("audit_healthy") is True
        and int(carrier_readback.get("unregistered_gate_count") or 0) == 0
        and int(
            carrier_readback.get("unclassified_blocking_count") or 0
        )
        == 0
    )
    if carrier_consumed:
        return

    registered_gate_ids = {
        str(row["gate_id"]) for row in registry["gates"]
    }
    valid_unclassified_resolutions: set[str] = set()
    for resolution in (
        scope_carrier.get("inventory_unclassified_resolutions") or []
    ):
        if not isinstance(resolution, dict):
            continue
        signal_id = str(resolution.get("signal_id") or "").strip()
        disposition = str(resolution.get("disposition") or "").strip()
        rationale = str(resolution.get("rationale") or "").strip()
        live_readback = str(resolution.get("live_readback") or "").strip()
        mapped_gate_id = str(resolution.get("gate_id") or "").strip()
        if (
            not signal_id.startswith("unclassified:")
            or disposition
            not in {
                "mapped_to_registered_gate",
                "producer_fixed",
                "invalid_signal",
            }
            or not rationale
            or not live_readback
            or (
                disposition == "mapped_to_registered_gate"
                and mapped_gate_id not in registered_gate_ids
            )
        ):
            continue
        valid_unclassified_resolutions.add(signal_id)

    gap_by_id = {
        str(row["gate_id"]): row
        for row in inventory["unregistered_gates"]
    }
    carried_forward = False
    for carried in scope_carrier.get("inventory_gaps") or []:
        if not isinstance(carried, dict) or not carried.get("gate_id"):
            continue
        gate_id = str(carried["gate_id"])
        if gate_id in registered_gate_ids or gate_id in gap_by_id:
            continue
        gap_by_id[gate_id] = {
            **carried,
            "registered": False,
            "carried_from_inventory_task_id": scope_carrier.get("id"),
            "reasons": sorted(
                {
                    *(
                        str(reason)
                        for reason in carried.get("reasons") or []
                    ),
                    "durable inventory scope not yet consumed",
                }
            ),
        }
        carried_forward = True

    unclassified_by_id = {
        str(
            row.get("inventory_signal_id")
            or _unclassified_signal_id(row)
        ): {
            **row,
            "inventory_signal_id": str(
                row.get("inventory_signal_id")
                or _unclassified_signal_id(row)
            ),
        }
        for row in inventory["unclassified_blocking"]
        if (
            str(
                row.get("inventory_signal_id")
                or _unclassified_signal_id(row)
            )
            not in valid_unclassified_resolutions
        )
    }
    for carried in (
        scope_carrier.get("inventory_unclassified_blocking") or []
    ):
        if not isinstance(carried, dict):
            continue
        signal_id = str(
            carried.get("inventory_signal_id")
            or _unclassified_signal_id(carried)
        )
        if (
            signal_id in valid_unclassified_resolutions
            or signal_id in unclassified_by_id
        ):
            continue
        unclassified_by_id[signal_id] = {
            **carried,
            "inventory_signal_id": signal_id,
            "carried_from_inventory_task_id": scope_carrier.get("id"),
        }
        carried_forward = True

    inventory["unregistered_gates"] = [
        gap_by_id[gate_id] for gate_id in sorted(gap_by_id)
    ]
    inventory["unclassified_blocking"] = [
        unclassified_by_id[signal_id]
        for signal_id in sorted(unclassified_by_id)
    ]
    inventory["unclassified_blocking_count"] = len(unclassified_by_id)
    if carried_forward:
        inventory["carried_forward_task_id"] = scope_carrier.get("id")
    carrier_watermark = _parse_time(scope_carrier.get("inventory_watermark"))
    newest_gap = _parse_time(inventory.get("newest_gap_at"))
    watermark = max(
        (
            candidate
            for candidate in (carrier_watermark, newest_gap)
            if candidate is not None
        ),
        default=None,
    )
    if watermark is not None:
        inventory["newest_gap_at"] = watermark.isoformat()


def _materialize_inventory_review_task(
    inventory: dict[str, Any],
    *,
    registry: dict[str, Any],
    queue_path: Path,
    tasks: list[dict[str, Any]],
    now: datetime,
) -> tuple[dict[str, Any] | None, bool, bool, bool]:
    """Create one canonical registration task for all current inventory gaps."""

    from .next_tasks import (
        append_task_record,
        rollover_active_task_record,
    )
    gaps = inventory["unregistered_gates"]
    unclassified = inventory["unclassified_blocking"]
    if not gaps and not unclassified:
        return None, False, False, False

    active_inventory = next(
        (
            row
            for row in tasks
            if row.get("control_gate_inventory_review") is True
            and str(row.get("status") or "") in ACTIVE_TASK_STATUSES
        ),
        None,
    )
    terminal_inventory = next(
        (
            row
            for row in reversed(tasks)
            if row.get("control_gate_inventory_review") is True
            and str(row.get("status") or "") not in ACTIVE_TASK_STATUSES
        ),
        None,
    )
    watermark = _parse_time(inventory.get("newest_gap_at")) or now
    identity = {
        "gate_ids": sorted(
            str(row["gate_id"]) for row in gaps
        ),
    }
    digest = control_gate_inventory_snapshot_hash(
        watermark=watermark.isoformat(),
        gaps=gaps,
        unclassified=unclassified,
    )
    cycle = f"{watermark.strftime('%Y%m%dT%H%M%S')}_{digest}"
    defaults = registry.get("review_task") or {}
    def description(
        gap_rows: list[dict[str, Any]],
        unclassified_rows: list[dict[str, Any]],
    ) -> str:
        return "\n".join(
            [
                "Control-gate inventory completeness audit found graph "
                "interventions outside the registry.",
                f"unregistered_gates: {gap_rows}",
                f"unclassified_blocking: {unclassified_rows}",
                "",
                "For each signal choose and record gate_id, owner, invariant, "
                "protected graph nodes/edges, blocked downstream edges, mode, "
                "identity strength, evidence source, outcome join, review "
                "thresholds, review anchor, and incident refs.",
                "Do not suppress the inventory alert by adding an alias unless "
                "the aliased decisions protect the same invariant and graph edge.",
                "For every unclassified signal, annotate "
                "inventory_unclassified_resolutions with signal_id, disposition "
                "(mapped_to_registered_gate/producer_fixed/invalid_signal), "
                "rationale, live_readback, and gate_id when mapped.",
            ]
        )

    record = {
        "id": f"control_gate_inventory_review_{cycle}",
        "title": "[Gate PDCA] register untracked control points",
        "description": description(gaps, unclassified),
        "task_type": str(defaults.get("task_type") or "platform_ops"),
        "priority": int(defaults.get("priority") or 2),
        "status": "pending",
        "source": str(defaults.get("source") or "control_gate_lifecycle"),
        "dispatch_lane": "agent",
        "created_at": now.isoformat(),
        "control_gate_inventory_review": True,
        "inventory_watermark": watermark.isoformat(),
        "inventory_snapshot_hash": digest,
        "inventory_gate_ids": identity["gate_ids"],
        "inventory_gaps": gaps,
        "inventory_unclassified_blocking": unclassified,
        "inventory_refresh_count": 0,
        "acceptance": [
            "register every blocking or high-frequency gate identity",
            "record owner/invariant/protected and blocked graph edges",
            "set trigger, harm, false-positive, and maximum review-age policy",
            "add an outcome join and live read-back test",
            "resolve each unclassified signal with a typed live-readback receipt",
            "rerun inventory audit with zero unregistered/unclassified gaps",
        ],
    }
    if active_inventory is None and terminal_inventory is not None:
        record["supersedes_inventory_task_id"] = terminal_inventory.get("id")
    stored, created = append_task_record(
        record,
        path=queue_path,
        if_exists="skip",
        semantic_dedupe=False,
        active_unique_fields=("control_gate_inventory_review",),
    )
    if created:
        return stored, True, False, False
    if str(stored.get("status") or "") not in ACTIVE_TASK_STATUSES:
        # The previous inventory task reached a terminal state without closing
        # the live gap.  Reusing its id would make append_task_record return the
        # terminal row forever, so start a new generation while retaining the
        # original evidence watermark in the payload.
        generation_identity = {
            **identity,
            "generation_at": now.isoformat(),
        }
        generation_digest = hashlib.sha256(
            json.dumps(
                generation_identity,
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:12]
        retry_record = {
            **record,
            "id": (
                "control_gate_inventory_review_"
                f"{now.strftime('%Y%m%dT%H%M%S')}_{generation_digest}"
            ),
            "inventory_snapshot_hash": digest,
            "inventory_generation_at": now.isoformat(),
            "supersedes_inventory_task_id": stored.get("id"),
        }
        stored, created = append_task_record(
            retry_record,
            path=queue_path,
            if_exists="skip",
            semantic_dedupe=False,
            active_unique_fields=("control_gate_inventory_review",),
        )
        if created:
            return stored, True, False, False

    def build_rollover_replacement(
        current_task: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Merge evidence against the lock-protected current queue row."""

        existing_gaps = {
            str(row.get("gate_id")): row
            for row in current_task.get("inventory_gaps") or []
            if isinstance(row, dict) and row.get("gate_id")
        }
        existing_gaps.update(
            {
                str(row["gate_id"]): row
                for row in gaps
            }
        )
        merged_gaps = [
            existing_gaps[gate_id]
            for gate_id in sorted(existing_gaps)
        ]
        unclassified_by_key = {
            json.dumps(row, ensure_ascii=False, sort_keys=True): row
            for row in [
                *(
                    current_task.get(
                        "inventory_unclassified_blocking"
                    )
                    or []
                ),
                *unclassified,
            ]
            if isinstance(row, dict)
        }
        merged_unclassified = [
            unclassified_by_key[key]
            for key in sorted(unclassified_by_key)
        ]
        existing_watermark = _parse_time(
            current_task.get("inventory_watermark")
        )
        merged_watermark = max(
            candidate
            for candidate in (existing_watermark, watermark)
            if candidate is not None
        )
        merged_digest = control_gate_inventory_snapshot_hash(
            watermark=merged_watermark.isoformat(),
            gaps=merged_gaps,
            unclassified=merged_unclassified,
        )
        if (
            current_task.get("inventory_snapshot_hash")
            == merged_digest
            and current_task.get("inventory_gaps") == merged_gaps
            and current_task.get("inventory_unclassified_blocking")
            == merged_unclassified
        ):
            return None
        cycle = (
            f"{merged_watermark.strftime('%Y%m%dT%H%M%S')}_"
            f"{merged_digest}"
        )
        return {
            **record,
            "id": f"control_gate_inventory_review_{cycle}",
            "created_at": now.isoformat(),
            "description": description(
                merged_gaps,
                merged_unclassified,
            ),
            "inventory_watermark": merged_watermark.isoformat(),
            "inventory_snapshot_hash": merged_digest,
            "inventory_gate_ids": sorted(existing_gaps),
            "inventory_gaps": merged_gaps,
            "inventory_unclassified_blocking": merged_unclassified,
            "inventory_refresh_count": int(
                current_task.get("inventory_refresh_count") or 0
            )
            + 1,
            "inventory_refreshed_at": now.isoformat(),
        }

    replacement, superseded_id = rollover_active_task_record(
        path=queue_path,
        active_unique_fields=("control_gate_inventory_review",),
        identity={"control_gate_inventory_review": True},
        replacement_builder=build_rollover_replacement,
    )
    if superseded_id:
        return replacement or stored, True, False, False
    from .next_tasks import refresh_active_task_record

    def build_running_refresh(
        current_task: dict[str, Any],
    ) -> dict[str, Any] | None:
        proposal = build_rollover_replacement(current_task)
        if proposal is None:
            return None
        prior_updates = list(
            current_task.get("inventory_scope_updates") or []
        )
        prior_updates.append(
            {
                "observed_at": now.isoformat(),
                "previous_snapshot_hash": str(
                    current_task.get("inventory_snapshot_hash") or ""
                ),
                "new_snapshot_hash": proposal[
                    "inventory_snapshot_hash"
                ],
                "added_gate_ids": sorted(
                    set(proposal["inventory_gate_ids"])
                    - set(current_task.get("inventory_gate_ids") or [])
                ),
                "added_unclassified_count": max(
                    0,
                    len(
                        proposal[
                            "inventory_unclassified_blocking"
                        ]
                    )
                    - len(
                        current_task.get(
                            "inventory_unclassified_blocking"
                        )
                        or []
                    ),
                ),
            }
        )
        return {
            **current_task,
            "description": proposal["description"],
            "inventory_watermark": proposal["inventory_watermark"],
            "inventory_snapshot_hash": proposal[
                "inventory_snapshot_hash"
            ],
            "inventory_gate_ids": proposal["inventory_gate_ids"],
            "inventory_gaps": proposal["inventory_gaps"],
            "inventory_unclassified_blocking": proposal[
                "inventory_unclassified_blocking"
            ],
            "inventory_refresh_count": proposal[
                "inventory_refresh_count"
            ],
            "inventory_refreshed_at": proposal[
                "inventory_refreshed_at"
            ],
            "inventory_scope_updates": prior_updates,
        }

    refreshed_task, refreshed = refresh_active_task_record(
        path=queue_path,
        active_unique_fields=("control_gate_inventory_review",),
        identity={"control_gate_inventory_review": True},
        refresh_builder=build_running_refresh,
    )
    if refreshed:
        return refreshed_task or stored, False, True, False
    return refreshed_task or replacement or stored, False, False, False


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
    incidents, incidents_health = _load_incidents(storage_root)
    inventory = _discover_gate_inventory(
        registry,
        storage_root=storage_root,
        now=current,
        incidents=incidents,
        incidents_health=incidents_health,
    )
    tasks, tasks_health = _load_tasks(queue)
    _carry_forward_inventory_scope(
        inventory,
        registry=registry,
        tasks=tasks,
    )
    feed, feed_health = _load_feed(storage_root)
    dispatch_completions, dispatch_health = _load_dispatch_completions(
        storage_root
    )
    transition_reason_receipt_cache: dict[
        str,
        tuple[
            dict[str, list[tuple[datetime, str]]],
            dict[str, Any],
        ],
    ] = {}

    gate_verdicts: list[dict[str, Any]] = []
    created_reviews: list[str] = []
    existing_reviews: list[str] = []
    for gate in registry["gates"]:
        window_hours = float(gate["review_policy"]["window_hours"])
        lookback_start = current - timedelta(hours=window_hours)
        reviewed_through = _review_watermark(gate, tasks)
        lifecycle = gate["lifecycle"]
        review_anchor_at = (
            _parse_time(lifecycle.get("last_reviewed_at"))
            if reviewed_through is not None
            else _parse_time(lifecycle["review_anchor_at"])
        )
        if review_anchor_at is None:  # guarded by registry validation
            raise ValueError(
                f"gate {gate['gate_id']!r} has no valid review anchor"
            )
        window_start = max(
            candidate
            for candidate in (lookback_start, reviewed_through)
            if candidate is not None
        )
        evidence, malformed, incident_hits, source_health = _collect_evidence(
            gate,
            registry=registry,
            storage_root=storage_root,
            window_start=window_start,
            now=current,
            incidents=incidents,
        )
        outcome_join = str(gate["outcome_join"])
        if outcome_join in {
            "candidate_task",
            "candidate_or_event_stage",
            "candidate_or_feed",
        }:
            identity_required_after = _parse_time(
                registry["discovery"][
                    "candidate_identity_required_after"
                ]
            )
            missing_candidate_identity = sum(
                1 for row in evidence if _candidate_id(row) is None
            )
            synthetic_candidate_identity = sum(
                1
                for row in evidence
                for timestamp, malformed_timestamp in [
                    _try_parse_time(_row_timestamp(row))
                ]
                if (
                    not malformed_timestamp
                    and timestamp is not None
                    and identity_required_after is not None
                    and timestamp > identity_required_after
                    and not any(
                        isinstance(row.get(field), str)
                        and str(row.get(field) or "").strip()
                        and not str(row.get(field) or "").startswith(
                            ("title:", "decision:")
                        )
                        for field in (
                            "candidate_id",
                            "target_id",
                            "task_id",
                            "job_id",
                            "rejection_id",
                            "generation_id",
                            "signature",
                        )
                    )
                )
            )
            if missing_candidate_identity:
                source_health.append(
                    {
                        "path": "<control-gate-evidence>",
                        "ok": False,
                        "error": "missing_candidate_identity",
                        "row_count": len(evidence),
                        "missing_candidate_identity_count": (
                            missing_candidate_identity
                        ),
                    }
                )
            if synthetic_candidate_identity:
                source_health.append(
                    {
                        "path": "<control-gate-evidence>",
                        "ok": False,
                        "error": "synthetic_candidate_identity_after_ratchet",
                        "row_count": len(evidence),
                        "synthetic_candidate_identity_count": (
                            synthetic_candidate_identity
                        ),
                        "required_after": (
                            identity_required_after.isoformat()
                            if identity_required_after is not None
                            else None
                        ),
                    }
                )
            source_health.append(tasks_health)
        if outcome_join in {
            "candidate_or_event_stage",
            "candidate_or_feed",
        }:
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
        incident_metric = str(
            gate["review_policy"].get("incident_metric")
            or "raw_observations"
        )
        transition_diagnostics: dict[str, list[str]] = {}
        transition_summaries: dict[str, dict[str, Any]] = {}
        incident_occurrences = 0
        incident_excluded_occurrences = 0
        incident_excluded_reasons: dict[str, int] = defaultdict(int)
        incident_unknown_occurrences = 0
        incident_unknown_reasons: dict[str, int] = defaultdict(int)
        reason_prefixes = tuple(
            str(prefix).strip()
            for prefix in gate["review_policy"].get(
                "incident_transition_reason_prefixes"
            )
            or []
        )
        safe_reasons = frozenset(
            str(reason).strip()
            for reason in gate["review_policy"].get(
                "incident_transition_safe_reasons"
            )
            or []
        )
        receipt_policy = gate["review_policy"].get(
            "incident_transition_reason_receipt"
        )
        receipt_index: dict[str, list[tuple[datetime, str]]] = {}
        receipt_max_age_seconds = 0.0
        if isinstance(receipt_policy, dict):
            receipt_max_age_seconds = float(
                receipt_policy["max_age_seconds"]
            )
            receipt_relative_path = str(receipt_policy["path"])
            cache_key = json.dumps(
                receipt_policy,
                ensure_ascii=False,
                sort_keys=True,
            )
            cached_receipts = transition_reason_receipt_cache.get(cache_key)
            if cached_receipts is None:
                receipt_path = storage_root / receipt_relative_path
                receipt_rows, _, receipt_health = _read_jsonl(receipt_path)
                (
                    receipt_index,
                    receipt_diagnostics,
                    selected_receipt_count,
                ) = _index_transition_reason_receipts(
                    receipt_rows,
                    policy=receipt_policy,
                )
                receipt_health = {
                    **receipt_health,
                    "selected_event_rows": selected_receipt_count,
                    "indexed_identity_count": len(receipt_index),
                }
                if receipt_diagnostics:
                    receipt_health.update(
                        {
                            "ok": False,
                            "error": (
                                "malformed_transition_reason_receipt_rows"
                            ),
                            "receipt_diagnostics": receipt_diagnostics,
                        }
                    )
                cached_receipts = (receipt_index, receipt_health)
                transition_reason_receipt_cache[cache_key] = cached_receipts
            receipt_index, receipt_health = cached_receipts
            source_health.append(receipt_health)
        for row in incident_hits:
            if incident_metric == "instance_transitions":
                incident_id = str(row.get("incident_id") or "<missing>")
                summary = _incident_transition_summary_since(
                    row,
                    window_start=window_start,
                    now=current,
                    reason_prefixes=reason_prefixes,
                    safe_reasons=safe_reasons,
                    receipt_index=receipt_index,
                    receipt_max_age_seconds=receipt_max_age_seconds,
                )
                transition_summaries[incident_id] = summary
                incident_occurrences += int(summary["count"])
                incident_excluded_occurrences += int(
                    summary["excluded_count"]
                )
                for reason, count in summary["excluded_reasons"].items():
                    incident_excluded_reasons[str(reason)] += int(count)
                incident_unknown_occurrences += int(
                    summary["unknown_count"]
                )
                for reason, count in summary["unknown_reasons"].items():
                    incident_unknown_reasons[str(reason)] += int(count)
                if summary["diagnostics"]:
                    transition_diagnostics[incident_id] = list(
                        summary["diagnostics"]
                    )
            else:
                incident_occurrences += int(
                    row.get("occurrence_count") or 1
                )
        if transition_diagnostics:
            source_health.append(
                {
                    **incidents_health,
                    "ok": False,
                    "error": "malformed_instance_transition_rows",
                    "transition_diagnostics": transition_diagnostics,
                }
            )
        incident_observations = sum(
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
            if (
                int(
                    transition_summaries.get(
                        str(row.get("incident_id") or "<missing>"),
                        {"count": 0},
                    )["count"]
                )
                if incident_metric == "instance_transitions"
                else int(row.get("occurrence_count") or 1)
            ) > 1
            or int(row.get("episode_count") or 1) > 1
        )
        retirement_effective = (
            lifecycle.get("last_action") == "retire"
            and reviewed_through is not None
        )
        if retirement_effective:
            retired_evidence_count = len(evidence) + len(incident_hits)
            due = retired_evidence_count > 0
            reasons = (
                [f"retired_gate_evidence={retired_evidence_count}"]
                if due
                else []
            )
        else:
            due, reasons = _review_due(
                gate,
                now=current,
                review_anchor_at=review_anchor_at,
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
                "incident_metric": incident_metric,
                "incident_occurrences": incident_occurrences,
                "incident_excluded_occurrences": (
                    incident_excluded_occurrences
                ),
                "incident_excluded_reasons": dict(
                    sorted(incident_excluded_reasons.items())
                ),
                "incident_unknown_occurrences": (
                    incident_unknown_occurrences
                ),
                "incident_unknown_reasons": dict(
                    sorted(incident_unknown_reasons.items())
                ),
                "incident_observations": incident_observations,
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
                else "retired"
                if retirement_effective
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
                review_cycle_at=newest_evidence_at or current,
            )
            review_id = str(stored.get("id") or "")
            if created:
                created_reviews.append(review_id)
                tasks.append(stored)
            elif review_id:
                existing_reviews.append(review_id)

    inventory_review_ids: list[str] = []
    inventory_review_existing_ids: list[str] = []
    inventory_review_refreshed_ids: list[str] = []
    inventory_review_deferred_ids: list[str] = []
    if materialize_reviews:
        (
            inventory_task,
            inventory_created,
            inventory_refreshed,
            inventory_deferred,
        ) = (
            _materialize_inventory_review_task(
                inventory,
                registry=registry,
                queue_path=queue,
                tasks=tasks,
                now=current,
            )
        )
        if inventory_task is not None:
            inventory_task_id = str(inventory_task.get("id") or "")
            if inventory_created:
                inventory_review_ids.append(inventory_task_id)
                tasks.append(inventory_task)
            elif inventory_refreshed:
                inventory_review_refreshed_ids.append(
                    inventory_task_id
                )
            elif inventory_deferred:
                inventory_review_deferred_ids.append(
                    inventory_task_id
                )
            elif inventory_task_id:
                inventory_review_existing_ids.append(inventory_task_id)

    result = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": current.isoformat(),
        "registry_path": str(Path(registry_path)),
        "registry_owner": registry["owner"],
        "inventory": inventory,
        "gates": gate_verdicts,
        "summary": {
            "gate_count": len(gate_verdicts),
            "unregistered_gate_count": len(
                inventory["unregistered_gates"]
            ),
            "unclassified_blocking_count": inventory[
                "unclassified_blocking_count"
            ],
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
        "inventory_review_tasks": {
            "created_count": len(inventory_review_ids),
            "created_ids": inventory_review_ids,
            "refreshed_ids": inventory_review_refreshed_ids,
            "deferred_ids": inventory_review_deferred_ids,
            "pending_delta": (
                {
                    "gate_ids": [
                        str(row["gate_id"])
                        for row in inventory["unregistered_gates"]
                    ],
                    "unclassified_blocking_count": inventory[
                        "unclassified_blocking_count"
                    ],
                    "watermark": inventory.get("newest_gap_at"),
                }
                if inventory_review_deferred_ids
                else None
            ),
            "existing_ids": sorted(
                set(inventory_review_existing_ids)
            ),
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
    unhealthy_sources.extend(
        {
            "gate_id": "__inventory__",
            **source,
        }
        for source in inventory["source_health"]
        if not source["ok"]
    )
    if inventory["unregistered_gates"]:
        unhealthy_sources.append(
            {
                "gate_id": "__inventory__",
                "path": str(Path(registry_path)),
                "ok": False,
                "error": "unregistered_control_gates",
                "gates": inventory["unregistered_gates"],
            }
        )
    if inventory["unclassified_blocking_count"]:
        unhealthy_sources.append(
            {
                "gate_id": "__inventory__",
                "path": str(Path(registry_path)),
                "ok": False,
                "error": "unclassified_blocking_decisions",
                "decisions": inventory["unclassified_blocking"],
            }
        )
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


def record_control_gate_decision(
    *,
    gate_id: str,
    decision: str,
    candidate_id: str,
    reason: str,
    protected_edge: str,
    storage_dir: str = "storage",
    timestamp: str | None = None,
) -> None:
    """Append one canonical graph-intervention receipt."""

    _append_control_decisions(
        [{
            "ts": timestamp or datetime.now(timezone.utc).isoformat(),
            "gate_id": gate_id,
            "decision": decision,
            "candidate_id": candidate_id,
            "reason": reason,
            "protected_edge": protected_edge,
        }],
        storage_dir=storage_dir,
    )


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
