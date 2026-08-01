"""Incident-first lifecycle for the auto-remediation loop.

Design: docs/refactor_plan_incident_lifecycle.md (boss-approved 2026-07-21,
assign_10927b4e).  The one-sentence inversion:

    老制：偵測 → 查任務池有沒有活 row → 沒有就開一張任務
    新制：偵測 → 對映到 incident（持久身分）→ incident 狀態機決定要不要開任務

The task pool records *dispositions*; dispositions end.  The prior dedup
anchored identity on live task rows, so every resolve re-armed the loop
(19 fresh ``a1`` tasks for one alert_key, 35 per-instance tasks for two root
causes — plan §1/§2).  Here the incident itself is the first-class entity:

* ``occurrence_count`` / ``episode_count`` NEVER reset (plan §3.2 #1).
* An incident row is NEVER deleted (plan §3.2 #2) — there is no delete API.
* Multiple instances of one root cause live in ``instances[]``; they do not
  each become an incident (plan §3.2 #3).

This module owns identity (fingerprint), the state machine
(open → mitigating → resolved / escalated / suppressed), and the store CRUD.
It does NOT append tasks or send mail itself except through the escalation
actuator (P4), which routes task creation through the single
``append_task_record`` gateway.  Detector wirings live in
``alert_remediation.py`` (internal alerts), ``scripts/check_alerts.py`` (CI),
``scripts/dispatch_supervisor/workspace.py`` (WS-B) and
``scripts/reclaim_stale_worktrees.py`` (worktree salvage).
"""

from __future__ import annotations

import fcntl
import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from volpred.canonical_write import guard_canonical_write
from volpred.ops.diagnostics import warn

# ── vocabulary ───────────────────────────────────────────────────────────────

STATE_OPEN = "open"
STATE_MITIGATING = "mitigating"
STATE_SUPPRESSED = "suppressed"
STATE_ESCALATED = "escalated"
STATE_RESOLVED = "resolved"
INCIDENT_STATES = frozenset(
    {STATE_OPEN, STATE_MITIGATING, STATE_SUPPRESSED, STATE_ESCALATED, STATE_RESOLVED}
)

CLASS_MACHINE_SELF = "machine_self"
CLASS_ORDINARY = "ordinary"

#: How the incident's episodes get a disposition (plan §6 + design ruling):
#: * ``auto_repair``   — ordinary loop: one repair task per episode.
#: * ``adjudication``  — one AGGREGATE main-thread adjudication task per
#:                       episode; instances accumulate in ``instances[]``.
#:                       This is not the broken machine repairing itself (the
#:                       §6 contradiction) — it is a hand-off to the main
#:                       thread, so machine_self kinds may use it.
#: * ``none``          — observe an alert whose concrete self-healing actuator
#:                       is owned elsewhere; never double-book that work here.
#: * ``external``      — identity/counting shared here, but the repair flow is
#:                       owned elsewhere (CI watch already does incidents
#:                       right, plan §2.2 — its semantics are preserved).
TASK_MODE_AUTO_REPAIR = "auto_repair"
TASK_MODE_ADJUDICATION = "adjudication"
TASK_MODE_NONE = "none"
TASK_MODE_EXTERNAL = "external"

#: Canonical WS-B producer scopes for the five machine-owned repair kinds.
#: The alert bridge reads this same registry when it materialises a task, so a
#: new kind cannot become auto-repairable without an execution contract.
MACHINE_SELF_REPAIR_OUTPUT_PATHS: dict[str, tuple[str, ...]] = {
    "phase_z_test_gate_red": (
        "scripts/dispatch_supervisor/phase_z.py",
        "tests/test_dispatch_supervisor.py",
    ),
    "silent_fallback_new": (
        "scripts/dispatch_supervisor",
        "tests/test_dispatch_supervisor.py",
    ),
    "git_push_backup_hold": (
        "scripts/cron_git_push_backup.sh",
        "scripts/audit_silent_fallbacks.py",
        "tests/test_alerts.py",
    ),
    "phase_z_baseline_missing": (
        "scripts/dispatch_supervisor/phase_z.py",
        "tests/test_dispatch_supervisor.py",
    ),
    "phase_z_generation_rejected": (
        "scripts/dispatch_supervisor/scheduler.py",
        "scripts/dispatch_supervisor/state.py",
        "tests/test_dispatch_supervisor.py",
    ),
}

#: kind → (class, task_mode).  All five current internal-remediable alert keys
#: are machine_self/auto_repair: they get exactly ONE isolated repair attempt.
#: If that task becomes terminal while the detector still sees the breach,
#: episode 2 reaches the machine_self threshold and hands one root-cause task
#: to the independent main-thread authority.  This is bounded autonomy: no
#: notification-only dead end and no unbounded broken-machine repair loop.
#: worker_orphaned / worktree_unmerged are "worktree 生命週期" (machine_self in
#: §6) but their disposition is a main-thread adjudication hand-off, so they
#: keep one aggregate task per episode instead of going silent.
KIND_POLICY: dict[str, tuple[str, str]] = {
    **{
        kind: (CLASS_MACHINE_SELF, TASK_MODE_AUTO_REPAIR)
        for kind in MACHINE_SELF_REPAIR_OUTPUT_PATHS
    },
    "worker_orphaned": (CLASS_MACHINE_SELF, TASK_MODE_ADJUDICATION),
    "worktree_unmerged": (CLASS_MACHINE_SELF, TASK_MODE_ADJUDICATION),
    "ci_red": (CLASS_ORDINARY, TASK_MODE_EXTERNAL),
    # These conditions already have a concrete self-healing owner.  Re-enqueuing
    # the same repair would double-book it, so persistent occurrences are only
    # observed here.  Three consecutive breached observations escalate to one
    # root-cause task; no ordinary repair task is created.
    "publishing_freshness": (CLASS_ORDINARY, TASK_MODE_NONE),
    "lazypack_render_stuck": (CLASS_ORDINARY, TASK_MODE_NONE),
    "draft_pool_low": (CLASS_ORDINARY, TASK_MODE_NONE),
}
DEFAULT_POLICY: tuple[str, str] = (CLASS_ORDINARY, TASK_MODE_AUTO_REPAIR)

# Exact control-graph classification.  Incident names are presentation
# vocabulary, not a reliable way to infer whether an observation cut a graph
# edge.  New control incidents must be added here (or carry an explicit
# ``control_gate_id`` at creation); lifecycle inventory never guesses from
# substrings.
CONTROL_GATE_BY_KIND: dict[str, str] = {
    "phase_z_test_gate_red": "phase_z_baseline_ownership",
    "silent_fallback_new": "candidate_silent_fallback_audit",
    "git_push_backup_hold": "worktree_merge_ownership",
    "phase_z_baseline_missing": "phase_z_baseline_ownership",
    "phase_z_generation_rejected": "phase_z_baseline_ownership",
    "worker_orphaned": "dispatch_worker_ownership",
    "worktree_unmerged": "worktree_merge_ownership",
}

#: Episode threshold at which a NEW episode escalates instead of opening yet
#: another disposition (plan §5/§6).  machine_self uses 2 because these
#: failures block everything else; ordinary uses the 3-strike number.
ESCALATION_THRESHOLD: dict[str, int] = {CLASS_MACHINE_SELF: 2, CLASS_ORDINARY: 3}

#: Resolution needs sustained clean, not one clean observation (plan §4, G7).
RESOLVE_MIN_CLEAN_OBSERVATIONS = 3
RESOLVE_MIN_CLEAN_SPAN = timedelta(hours=24)
#: Instance kinds resolve only when every instance is cleared AND no new
#: instance appeared for this long (plan §4 row 2).
INSTANCE_QUIET_SPAN = timedelta(hours=24)

# A machine-owned repair must either clear the detector or yield control to the
# independent root-cause lane.  The supervisor worker cap is shorter than this;
# two hours also matches stale-claim cleanup, so an active status past this age
# is evidence that the disposition itself stopped converging.
MACHINE_REPAIR_DEADLINE = timedelta(hours=2)

#: Task statuses that count as "disposition in flight" (mirrors the internal
#: remediation contract: pending/claimed work is not a failed attempt).
ACTIVE_TASK_STATUSES = frozenset(
    {"", "pending", "pending_main_thread", "claimed", "in_progress"}
)

_CLEAN_OBS_LIMIT = 12
_TASK_HISTORY_LIMIT = 24
_EPISODE_FAILURE_LIMIT = 12
_INSTANCE_LIMIT = 500
_INSTANCE_TRANSITION_LIMIT = 1000

DEFAULT_STORE_RELPATH = Path("ops") / "incidents.json"


def store_path_for(storage_dir: str | Path = "storage") -> Path:
    """Canonical incidents store path for a storage dir (repo-root anchored)."""
    root = Path(storage_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[3] / storage_dir
    return root / DEFAULT_STORE_RELPATH


# ── identity ─────────────────────────────────────────────────────────────────


def _normalize_parts(parts: Iterable[Any]) -> list[str]:
    return sorted({text for item in (parts or ()) if (text := str(item or "").strip())})


def fingerprint(kind: str, parts: Iterable[Any] = ()) -> str:
    """Stable identity from the event's invariant properties ONLY (plan §3.3).

    No timestamps, no run ids, no worktree names — those are instances, not
    identity.  ``parts`` order does not matter.
    """
    normalized_kind = str(kind or "").strip().lower()
    if not normalized_kind:
        raise ValueError("incident kind must not be empty")
    material = "\x1f".join([normalized_kind, *_normalize_parts(parts)])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def incident_id_for(kind: str, parts: Iterable[Any] = ()) -> str:
    return f"inc_{fingerprint(kind, parts)[:12]}"


def policy_for(kind: str) -> tuple[str, str]:
    return KIND_POLICY.get(str(kind or "").strip().lower(), DEFAULT_POLICY)


# ── time helpers ─────────────────────────────────────────────────────────────


def _utc(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):  # silent-ok: parse helper returns None for non-ISO input by design
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ── store I/O ────────────────────────────────────────────────────────────────


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "updated_at": None, "incidents": {}}


@contextmanager
def _locked_store(path: str | Path) -> Iterator[dict[str, Any]]:
    """Exclusive read-modify-write on the incidents store.

    The schema is created by code on first touch; the canonical file itself is
    initialised post-merge by the main thread (plan Phase P5 boundary).
    """
    p = Path(path)
    guard_canonical_write(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(json.dumps(_empty_store(), ensure_ascii=False) + "\n", encoding="utf-8")
    with p.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            raw = fh.read()
            try:
                store = json.loads(raw) if raw.strip() else _empty_store()
            except json.JSONDecodeError as exc:
                # Fail loud: a corrupt incident store silently replaced would
                # reset every counter — exactly the reset behaviour this module
                # exists to kill.  Refuse and surface.
                raise ValueError(f"incident store is not valid JSON: {p}") from exc
            if not isinstance(store, dict) or not isinstance(store.get("incidents"), dict):
                raise ValueError(f"incident store root shape invalid: {p}")
            yield store
            store["updated_at"] = datetime.now(timezone.utc).isoformat()
            serialized = json.dumps(store, ensure_ascii=False, indent=1, sort_keys=True)
            fh.seek(0)
            fh.truncate()
            fh.write(serialized + "\n")
            fh.flush()
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def load_incident(path: str | Path, incident_id: str) -> dict[str, Any] | None:
    """Read-only fetch of one incident row (no lock upgrade needed for reads)."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        store = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warn("incident_store", "load failed", path=str(p), err=str(exc))
        return None
    row = (store.get("incidents") or {}).get(incident_id)
    return dict(row) if isinstance(row, dict) else None


def list_incidents(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        store = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warn("incident_store", "list failed", path=str(p), err=str(exc))
        return []
    rows = store.get("incidents") or {}
    return [dict(row) for row in rows.values() if isinstance(row, dict)]


# ── row construction / episode bookkeeping ───────────────────────────────────


def _new_row(kind: str, parts: Iterable[Any], now: datetime) -> dict[str, Any]:
    class_, task_mode = policy_for(kind)
    normalized_kind = str(kind).strip().lower()
    control_gate_id = CONTROL_GATE_BY_KIND.get(normalized_kind)
    return {
        "incident_id": incident_id_for(kind, parts),
        "fingerprint": fingerprint(kind, parts),
        "fingerprint_parts": _normalize_parts(parts),
        "kind": normalized_kind,
        "is_control_intervention": control_gate_id is not None,
        "control_gate_id": control_gate_id,
        "class": class_,
        "task_mode": task_mode,
        "first_seen_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "occurrence_count": 0,
        "episode_count": 0,
        "state": STATE_OPEN,
        "current_task_id": None,
        "task_history": [],
        "episode_failures": [],
        "instances": [],
        "clean_observations": [],
        "clean_streak_started_at": None,
        "resolution": None,
        "resolutions": [],
        "suppressed_until": None,
        "escalation": None,
        "notified_at": None,
        "throttled": {"count": 0, "last_at": None},
    }


def _refresh_declared_policy(row: dict[str, Any], kind: str, now: datetime) -> None:
    """Apply a shipped kind's canonical policy to durable pre-cutover rows.

    Incident rows intentionally outlive releases.  Without this forward
    migration, changing ``KIND_POLICY`` would affect only brand-new incident
    identities while every already-observed failure remained stuck on the old
    notification-only behavior.  Unknown/custom kinds keep their stored policy.
    """
    if kind not in KIND_POLICY:
        return
    expected_class, expected_task_mode = KIND_POLICY[kind]
    previous_class = str(row.get("class") or "")
    previous_task_mode = str(row.get("task_mode") or "")
    if (
        previous_class == expected_class
        and previous_task_mode == expected_task_mode
    ):
        return
    row["class"] = expected_class
    row["task_mode"] = expected_task_mode
    history = row.setdefault("policy_history", [])
    history.append(
        {
            "at": now.isoformat(),
            "from_class": previous_class,
            "to_class": expected_class,
            "from_task_mode": previous_task_mode,
            "to_task_mode": expected_task_mode,
            "reason": "canonical_kind_policy_refresh",
        }
    )
    del history[:-8]


def _upsert_instance(
    row: dict[str, Any],
    instance_key: str,
    now: datetime,
    detail: dict[str, Any] | None = None,
) -> str | None:
    """Update one instance and return the graph transition, if any.

    A detector may observe the same still-open edge thousands of times.  Such
    polling moves ``last_seen_at`` but is not a new lifecycle occurrence.
    """
    instances = row.setdefault("instances", [])
    for item in instances:
        if isinstance(item, dict) and item.get("key") == instance_key:
            was_cleared = bool(item.get("cleared_at"))
            was_resolved = row.get("state") == STATE_RESOLVED
            item["last_seen_at"] = now.isoformat()
            if was_cleared or was_resolved:
                item["cleared_at"] = None  # re-appeared ⇒ not cleared any more
            if detail:
                item["detail"] = detail
            if was_cleared or was_resolved:
                return "reopened"
            return None
    if len(instances) >= _INSTANCE_LIMIT:
        warn("incident_store", "instance limit reached; dropping oldest",
             incident_id=str(row.get("incident_id")), limit=_INSTANCE_LIMIT)
        del instances[0]
    entry: dict[str, Any] = {
        "key": instance_key,
        "first_seen_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "cleared_at": None,
    }
    if detail:
        entry["detail"] = detail
    instances.append(entry)
    return "opened"


def _record_instance_transition(
    row: dict[str, Any],
    *,
    instance_key: str,
    transition: str | None,
    now: datetime,
) -> None:
    """Persist failure-edge changes separately from raw detector polls."""
    row["instance_transition_tracking"] = True
    transitions = row.setdefault("instance_transitions", [])
    if transition is None:
        return
    transitions.append(
        {
            "at": now.isoformat(),
            "instance_key": instance_key,
            "transition": transition,
        }
    )
    del transitions[:-_INSTANCE_TRANSITION_LIMIT]


def _ensure_instance_transition_tracking(
    row: dict[str, Any],
    *,
    now: datetime,
) -> None:
    """Start edge-transition tracking without hiding live legacy risk.

    Legacy incident rows only counted detector polls.  On the first
    instance-aware observation after the metric cutover, snapshot each edge
    that is *currently* open exactly once.  Cleared historical edges are not
    replayed, and later polls see ``instance_transition_tracking`` and remain
    observation-only.
    """
    if row.get("instance_transition_tracking") is True:
        return
    at = now.isoformat()
    transitions: list[dict[str, Any]] = []
    for item in row.get("instances") or []:
        if not isinstance(item, dict) or item.get("cleared_at"):
            continue
        if row.get("state") == STATE_RESOLVED:
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        transitions.append(
            {
                "at": at,
                "instance_key": key,
                "transition": "opened",
                "migration_baseline": True,
            }
        )
    row["instance_transition_tracking"] = True
    row["instance_transition_baselined_at"] = at
    row["instance_transitions"] = transitions[-_INSTANCE_TRANSITION_LIMIT:]


def _open_new_episode(row: dict[str, Any], now: datetime) -> None:
    """episode_count is monotone: it increments and never resets (plan §3.2)."""
    row["episode_count"] = int(row.get("episode_count") or 0) + 1
    row["state"] = STATE_OPEN
    row["current_task_id"] = None
    row["notified_at"] = None
    row["episode_opened_at"] = now.isoformat()


def _record_episode_failure(row: dict[str, Any], *, task_id: str, status: str,
                            failure_reason: str, now: datetime) -> None:
    failures = row.setdefault("episode_failures", [])
    failures.append(
        {
            "episode": int(row.get("episode_count") or 0),
            "task_id": task_id,
            "status": status,
            "failure_reason": failure_reason[:500],
            "at": now.isoformat(),
        }
    )
    del failures[:-_EPISODE_FAILURE_LIMIT]


def _threshold(row: dict[str, Any]) -> int:
    return ESCALATION_THRESHOLD.get(str(row.get("class")), ESCALATION_THRESHOLD[CLASS_ORDINARY])


def suggested_task_id(row: dict[str, Any]) -> str:
    """Deterministic per-episode task id — idempotency key for the gateway."""
    return f"{row['incident_id']}_e{int(row.get('episode_count') or 0)}"


def suggested_root_cause_task_id(row: dict[str, Any]) -> str:
    return f"{row['incident_id']}_rootcause_e{int(row.get('episode_count') or 0)}"


def _sync_escalation(row: dict[str, Any],
                     task_status_probe: Callable[[str], str | None] | None,
                     now: datetime) -> None:
    """Escalated stays suppressed until the root-cause task SUCCEEDS (plan §5)."""
    if row.get("state") not in {STATE_ESCALATED, STATE_SUPPRESSED}:
        return
    escalation = row.get("escalation")
    if not isinstance(escalation, dict) or task_status_probe is None:
        return
    task_id = str(escalation.get("root_cause_task_id") or "")
    if not task_id:
        return
    status = task_status_probe(task_id)
    if str(status or "").strip().lower() in {"succeeded", "succeeded_null_result"}:
        _resolve(row, criterion="root_cause_task_succeeded", by=task_id, now=now)


def _resolve(row: dict[str, Any], *, criterion: str, by: str, now: datetime) -> None:
    """resolve changes state and writes resolution; counters are untouched."""
    resolution = {"at": now.isoformat(), "criterion": criterion, "by": by}
    row["state"] = STATE_RESOLVED
    row["resolution"] = resolution
    history = row.setdefault("resolutions", [])
    history.append(resolution)
    del history[:-_EPISODE_FAILURE_LIMIT]
    row["current_task_id"] = None
    row["clean_observations"] = []
    row["clean_streak_started_at"] = None


# ── breach routing (the state machine, plan §3.4) ────────────────────────────


def route_breach(
    store_path: str | Path,
    *,
    kind: str,
    fingerprint_parts: Iterable[Any] = (),
    instance_key: str | None = None,
    instance_keys: Iterable[str] | None = None,
    instance_detail: dict[str, Any] | None = None,
    details: str | None = None,
    now: datetime | None = None,
    task_status_probe: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    """Map one breach observation onto its incident and decide the disposition.

    Returns an outcome dict; ``action`` ∈:

    * ``create_task``  — caller appends the suggested task via the
                         ``append_task_record`` gateway, then calls
                         :func:`bind_task`.
    * ``notify``       — machine_self/none first-episode notification is due;
                         caller sends it, then calls :func:`record_notified`.
    * ``escalate``     — a new episode crossed the class threshold; caller runs
                         the escalation actuator (P4) exactly once.
    * ``none``         — disposition already in flight (or already notified);
                         only counters moved.
    * ``suppressed``   — escalated/suppressed incident: counted, never tasked.
    * ``external``     — kind's flow is owned elsewhere (CI); identity/counters
                         updated here only.
    """
    current = _utc(now)
    normalized_kind = str(kind or "").strip().lower()
    with _locked_store(store_path) as store:
        incidents: dict[str, Any] = store["incidents"]
        iid = incident_id_for(normalized_kind, fingerprint_parts)
        row = incidents.get(iid)
        if not isinstance(row, dict):
            row = _new_row(normalized_kind, fingerprint_parts, current)
            incidents[iid] = row
        else:
            control_gate_id = CONTROL_GATE_BY_KIND.get(normalized_kind)
            row["is_control_intervention"] = control_gate_id is not None
            row["control_gate_id"] = control_gate_id
            _refresh_declared_policy(row, normalized_kind, current)

        row["occurrence_count"] = int(row.get("occurrence_count") or 0) + 1
        last_seen = _parse_iso(row.get("last_seen_at"))
        if last_seen is None or current > last_seen:
            row["last_seen_at"] = current.isoformat()
        if details:
            row["last_breach_detail"] = str(details)[:600]
        if instance_key:
            key = str(instance_key)
            _ensure_instance_transition_tracking(row, now=current)
            _record_instance_transition(
                row,
                instance_key=key,
                transition=_upsert_instance(
                    row, key, current, instance_detail
                ),
                now=current,
            )
        for key in instance_keys or ():
            text = str(key or "").strip()
            if text:
                _ensure_instance_transition_tracking(row, now=current)
                _record_instance_transition(
                    row,
                    instance_key=text,
                    transition=_upsert_instance(
                        row, text, current, None
                    ),
                    now=current,
                )
        # A breach breaks any clean streak — one clean is never enough (G7).
        row["clean_observations"] = []
        row["clean_streak_started_at"] = None

        _sync_escalation(row, task_status_probe, current)
        outcome = _decide_breach(row, task_status_probe, current)
        outcome.update(
            incident_id=iid,
            kind=normalized_kind,
            state=row["state"],
            occurrence_count=row["occurrence_count"],
            episode_count=row["episode_count"],
            task_mode=row["task_mode"],
            incident_class=row["class"],
        )
        return outcome


def _decide_breach(
    row: dict[str, Any],
    task_status_probe: Callable[[str], str | None] | None,
    now: datetime,
) -> dict[str, Any]:
    task_mode = str(row.get("task_mode") or TASK_MODE_AUTO_REPAIR)
    state = str(row.get("state") or STATE_OPEN)

    if task_mode == TASK_MODE_EXTERNAL:
        # External owners (CI watch) run their own repair flow; the store only
        # keeps identity + monotone counters.  A recurrence after resolution is
        # still a new episode of the SAME incident.
        if int(row.get("episode_count") or 0) == 0 or state == STATE_RESOLVED:
            _open_new_episode(row, now)
        return {"action": "external"}

    if state == STATE_SUPPRESSED:
        return {"action": "suppressed"}
    if state == STATE_ESCALATED:
        escalation = row.get("escalation") if isinstance(row.get("escalation"), dict) else {}
        root_cause_task_id = str(escalation.get("root_cause_task_id") or "")
        task_present = bool(root_cause_task_id)
        if task_present and task_status_probe is not None:
            # The incident receipt is not proof that the canonical queue row
            # survived admission/compaction.  In particular, semantic task
            # dedupe used to reject a distinct incident root task while the
            # actuator still recorded its candidate id.  Re-enter the
            # idempotent actuator whenever the durable id is absent.
            task_present = task_status_probe(root_cause_task_id) is not None
        actuated = task_present and bool(escalation.get("notified_at"))
        if actuated:
            # Escalated ⇒ permanently suppressed for auto-dispositions (§5):
            # 「修不好 → 承認修不好 → 交給人 → 閉嘴」。
            return {"action": "suppressed"}
        # Crash between escalation decision and actuation: retry idempotently.
        return {
            "action": "escalate",
            "suggested_root_cause_task_id": suggested_root_cause_task_id(row),
        }

    if state == STATE_RESOLVED:
        # Recurrence is the SAME incident relapsing — never a fresh row, never
        # a counter reset (plan §4: 第 8 次復發時系統知道這是第 8 次).
        _open_new_episode(row, now)
        return _maybe_escalate_or_dispose(row, task_status_probe, now)

    # open / mitigating
    if int(row.get("episode_count") or 0) == 0:
        _open_new_episode(row, now)
        return _maybe_escalate_or_dispose(row, task_status_probe, now)
    return _dispose_current_episode(row, task_status_probe, now)


def _maybe_escalate_or_dispose(
    row: dict[str, Any],
    task_status_probe: Callable[[str], str | None] | None,
    now: datetime,
) -> dict[str, Any]:
    """A NEW episode just opened; threshold check happens before any new task.

    Escalation rule (plan §5/§6, G4/G5): the Nth episode where
    N >= class threshold does not get another auto disposition — it becomes
    the escalation itself.  machine_self therefore receives one bounded
    episode-1 repair and escalates on episode 2 instead of retrying forever.
    """
    if int(row.get("episode_count") or 0) >= _threshold(row):
        row["state"] = STATE_ESCALATED
        row.setdefault("escalation", None)
        return {
            "action": "escalate",
            "suggested_root_cause_task_id": suggested_root_cause_task_id(row),
        }
    return _dispose_current_episode(row, task_status_probe, now)


def _dispose_current_episode(
    row: dict[str, Any],
    task_status_probe: Callable[[str], str | None] | None,
    now: datetime,
) -> dict[str, Any]:
    task_mode = str(row.get("task_mode") or TASK_MODE_AUTO_REPAIR)

    if task_mode == TASK_MODE_NONE:
        row["state"] = STATE_OPEN
        if str(row.get("class")) == CLASS_ORDINARY:
            if int(row.get("occurrence_count") or 0) >= _threshold(row):
                row["state"] = STATE_ESCALATED
                row.setdefault("escalation", None)
                return {
                    "action": "escalate",
                    "suggested_root_cause_task_id": suggested_root_cause_task_id(row),
                }
            return {"action": "none"}
        if not row.get("notified_at"):
            return {"action": "notify"}
        return {"action": "none"}

    task_id = str(row.get("current_task_id") or "")
    if not task_id:
        return {"action": "create_task", "suggested_task_id": suggested_task_id(row)}

    status = task_status_probe(task_id) if task_status_probe is not None else None
    normalized = str(status or "").strip().lower() if status is not None else None
    if status is None:
        # Bound task never landed (e.g. throttled append) — retry same episode.
        return {"action": "create_task", "suggested_task_id": suggested_task_id(row)}
    if normalized in ACTIVE_TASK_STATUSES:
        if (
            str(row.get("class")) == CLASS_MACHINE_SELF
            and task_mode == TASK_MODE_AUTO_REPAIR
        ):
            opened_at = next(
                (
                    _parse_iso(item.get("opened_at"))
                    for item in reversed(row.get("task_history") or [])
                    if isinstance(item, dict) and item.get("task_id") == task_id
                ),
                None,
            )
            if (
                opened_at is not None
                and now - opened_at >= MACHINE_REPAIR_DEADLINE
            ):
                handoff = row.get("deadline_handoff")
                if not isinstance(handoff, dict) or handoff.get("task_id") != task_id:
                    row["deadline_handoff"] = {
                        "task_id": task_id,
                        "deadline_at": (
                            opened_at + MACHINE_REPAIR_DEADLINE
                        ).isoformat(),
                        "detected_at": now.isoformat(),
                        "observed_status": normalized or "pending",
                    }
                if normalized in {"", "pending", "pending_main_thread"}:
                    # Queue CAS must happen BEFORE incident advancement.  The
                    # caller acknowledges it through settle_expired_task(); if
                    # the CAS loses a race, this incident remains mitigating.
                    return {"action": "expire_task", "expired_task_id": task_id}
                # claimed/in_progress still has producer custody.  Its formal
                # supervisor work-cap/termination owner must drain that custody;
                # opening a second repair here would create two writers.
                row["state"] = STATE_MITIGATING
                return {
                    "action": "none",
                    "active_task_id": task_id,
                    "deadline_handoff_required": True,
                }
        row["state"] = STATE_MITIGATING
        return {"action": "none", "active_task_id": task_id}

    # Terminal disposition + the detector still sees the breach ⇒ the episode
    # failed (a succeeded task that did not clear the condition is a failure
    # of the episode, not a success — same contract as the old router).
    _record_episode_failure(
        row,
        task_id=task_id,
        status=normalized or "unknown",
        failure_reason=f"disposition terminal ({normalized}) but breach persists",
        now=now,
    )
    _open_new_episode(row, now)
    return _maybe_escalate_or_dispose(row, task_status_probe, now)


def settle_expired_task(
    store_path: str | Path,
    incident_id: str,
    task_id: str,
    *,
    task_status_probe: Callable[[str], str | None],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Advance an incident only after the expired queue task is terminal.

    This is phase two of the deadline handoff.  Phase one CAS-settles the queue
    row; a crash between phases is safe because the next detector poll observes
    that terminal row and follows the normal persistent-breach path.
    """
    current = _utc(now)
    with _locked_store(store_path) as store:
        row = store["incidents"].get(incident_id)
        if not isinstance(row, dict):
            return {"action": "none", "reason": "unknown_incident"}
        if str(row.get("current_task_id") or "") != task_id:
            return {"action": "none", "reason": "task_binding_changed"}
        status = task_status_probe(task_id)
        normalized = str(status or "").strip().lower() if status is not None else None
        if status is None or normalized in ACTIVE_TASK_STATUSES:
            return {
                "action": "none",
                "reason": "task_not_terminal",
                "active_task_id": task_id,
            }
        _record_episode_failure(
            row,
            task_id=task_id,
            status="deadline_exceeded",
            failure_reason=(
                "machine repair deadline elapsed; queue settlement acknowledged "
                f"as {normalized or 'unknown'}"
            ),
            now=current,
        )
        row["deadline_handoff"] = {
            **(
                row.get("deadline_handoff")
                if isinstance(row.get("deadline_handoff"), dict)
                else {}
            ),
            "task_id": task_id,
            "settled_at": current.isoformat(),
            "settled_status": normalized or "unknown",
        }
        _open_new_episode(row, current)
        outcome = _maybe_escalate_or_dispose(row, task_status_probe, current)
        outcome.update(
            incident_id=incident_id,
            kind=row.get("kind"),
            state=row["state"],
            occurrence_count=row["occurrence_count"],
            episode_count=row["episode_count"],
            task_mode=row["task_mode"],
            incident_class=row["class"],
            expired_task_id=task_id,
        )
        return outcome


# ── clean-side observations (plan §4, G7) ────────────────────────────────────


def observe_clean(
    store_path: str | Path,
    *,
    kind: str,
    fingerprint_parts: Iterable[Any] = (),
    now: datetime | None = None,
    criterion: str | None = None,
    by: str = "detector",
    task_status_probe: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    """Record a clean observation; resolve ONLY on sustained clean.

    An explicit ``criterion`` is the one-shot escape hatch (plan §4 row 3) for
    kinds whose external verification IS the resolution (``task_succeeded``,
    ``ci_verified_green``) — callers must name it; the default path demands a
    sustained clean streak.
    """
    current = _utc(now)
    with _locked_store(store_path) as store:
        iid = incident_id_for(kind, fingerprint_parts)
        row = store["incidents"].get(iid)
        if not isinstance(row, dict):
            return {"resolved": False, "reason": "unknown_incident", "incident_id": iid}

        _sync_escalation(row, task_status_probe, current)
        state = str(row.get("state") or STATE_OPEN)
        if state == STATE_RESOLVED:
            return {"resolved": True, "changed": False, "incident_id": iid,
                    "state": state, "reason": "already_resolved"}
        if state in {STATE_ESCALATED, STATE_SUPPRESSED}:
            # A self-healed condition does not un-escalate: the root-cause work
            # is still owed.  Only root-cause task success resolves (plan §5).
            return {"resolved": False, "changed": False, "incident_id": iid,
                    "state": row["state"], "reason": "escalated_awaits_root_cause"}

        if criterion:
            closable = str(row.get("current_task_id") or "") or None
            _resolve(row, criterion=criterion, by=by, now=current)
            return {"resolved": True, "changed": True, "incident_id": iid,
                    "state": row["state"], "closable_task_id": closable}

        observations = row.setdefault("clean_observations", [])
        _ensure_clean_streak_started_at(row, observations, current)
        last = _parse_iso(observations[-1]["at"]) if observations else None
        if last is None or current > last:
            observations.append({"at": current.isoformat()})
            del observations[:-_CLEAN_OBS_LIMIT]

        if _clean_criterion_met(row, current):
            closable = str(row.get("current_task_id") or "") or None
            _resolve(row, criterion=_criterion_name(row), by=by, now=current)
            return {"resolved": True, "changed": True, "incident_id": iid,
                    "state": row["state"], "closable_task_id": closable}
        if row.get("state") == STATE_OPEN and row.get("current_task_id"):
            row["state"] = STATE_MITIGATING
        return {"resolved": False, "changed": True, "incident_id": iid,
                "state": row["state"], "clean_observations": len(observations)}


def _criterion_name(row: dict[str, Any]) -> str:
    if str(row.get("task_mode")) == TASK_MODE_ADJUDICATION:
        return "instances_cleared_quiet_24h"
    return (
        f"clean_streak_k{RESOLVE_MIN_CLEAN_OBSERVATIONS}"
        f"_{int(RESOLVE_MIN_CLEAN_SPAN.total_seconds() // 3600)}h"
    )


def _ensure_clean_streak_started_at(
    row: dict[str, Any],
    observations: list[dict[str, Any]],
    current: datetime,
) -> datetime:
    """Return the durable streak origin, lazily migrating pre-field rows.

    ``clean_observations`` is a bounded diagnostic ring buffer, not durable
    lifecycle state.  Old rows therefore migrate from the oldest observation
    still available.  That is conservative: the true streak may have begun
    earlier, but never later, so migration cannot resolve an incident early.
    """
    if not observations:
        started = current
    else:
        started = _parse_iso(row.get("clean_streak_started_at"))
        if started is None:
            started = _parse_iso(observations[0].get("at")) or current
    row["clean_streak_started_at"] = started.isoformat()
    return started


def _clean_criterion_met(row: dict[str, Any], now: datetime) -> bool:
    if str(row.get("task_mode")) == TASK_MODE_ADJUDICATION:
        return _instances_quiet(row, now)
    observations = row.get("clean_observations") or []
    if len(observations) < RESOLVE_MIN_CLEAN_OBSERVATIONS:
        return False
    first = _parse_iso(row.get("clean_streak_started_at"))
    if first is None:
        # Read-only compatibility for callers that inspect an old row without
        # passing through observe_clean's lazy migration first.
        first = _parse_iso(observations[0].get("at"))
    last = _parse_iso(observations[-1].get("at"))
    if first is None or last is None:
        return False
    return (last - first) >= RESOLVE_MIN_CLEAN_SPAN


def _instances_quiet(row: dict[str, Any], now: datetime) -> bool:
    instances = row.get("instances") or []
    if not instances:
        return False
    latest_activity: datetime | None = _parse_iso(row.get("last_seen_at"))
    for item in instances:
        if not isinstance(item, dict):
            continue
        if not item.get("cleared_at"):
            return False
        seen = _parse_iso(item.get("last_seen_at")) or _parse_iso(item.get("first_seen_at"))
        if seen is not None and (latest_activity is None or seen > latest_activity):
            latest_activity = seen
    if latest_activity is None:
        return False
    return (now - latest_activity) >= INSTANCE_QUIET_SPAN


def clear_instance(
    store_path: str | Path,
    *,
    kind: str,
    fingerprint_parts: Iterable[Any] = (),
    instance_key: str,
    now: datetime | None = None,
    by: str = "detector",
) -> dict[str, Any]:
    """Mark one instance cleared; resolve when ALL are cleared and quiet ≥24h."""
    current = _utc(now)
    with _locked_store(store_path) as store:
        iid = incident_id_for(kind, fingerprint_parts)
        row = store["incidents"].get(iid)
        if not isinstance(row, dict):
            return {"cleared": False, "reason": "unknown_incident", "incident_id": iid}
        changed = False
        for item in row.get("instances") or []:
            if isinstance(item, dict) and item.get("key") == instance_key:
                if not item.get("cleared_at"):
                    item["cleared_at"] = current.isoformat()
                    changed = True
                break
        else:
            return {"cleared": False, "reason": "unknown_instance", "incident_id": iid}
        resolved = False
        if (
            row.get("state") in {STATE_OPEN, STATE_MITIGATING}
            and _instances_quiet(row, current)
        ):
            _resolve(row, criterion=_criterion_name(row), by=by, now=current)
            resolved = True
        return {"cleared": True, "changed": changed, "resolved": resolved,
                "incident_id": iid, "state": row["state"]}


# ── receipts written back after caller side effects ──────────────────────────


def bind_task(
    store_path: str | Path,
    incident_id: str,
    task_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _utc(now)
    with _locked_store(store_path) as store:
        row = store["incidents"].get(incident_id)
        if not isinstance(row, dict):
            return {"bound": False, "reason": "unknown_incident"}
        row["current_task_id"] = task_id
        history = row.setdefault("task_history", [])
        if task_id not in [h.get("task_id") for h in history if isinstance(h, dict)]:
            history.append(
                {
                    "task_id": task_id,
                    "episode": int(row.get("episode_count") or 0),
                    "opened_at": current.isoformat(),
                }
            )
            del history[:-_TASK_HISTORY_LIMIT]
        if str(row.get("task_mode")) in {TASK_MODE_AUTO_REPAIR, TASK_MODE_ADJUDICATION}:
            row["state"] = STATE_MITIGATING
        return {"bound": True, "incident_id": incident_id, "task_id": task_id}


def record_notified(
    store_path: str | Path,
    incident_id: str,
    *,
    now: datetime | None = None,
    notification_id: str | None = None,
) -> dict[str, Any]:
    current = _utc(now)
    with _locked_store(store_path) as store:
        row = store["incidents"].get(incident_id)
        if not isinstance(row, dict):
            return {"recorded": False, "reason": "unknown_incident"}
        row["notified_at"] = current.isoformat()
        if notification_id:
            row["notification_id"] = str(notification_id)
        return {"recorded": True, "incident_id": incident_id}


def record_escalation(
    store_path: str | Path,
    incident_id: str,
    *,
    root_cause_task_id: str | None = None,
    notified: bool = False,
    notification_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist escalation actuation receipts (task opened / mail delivered).

    State stays ``escalated`` — for auto-disposition purposes escalated IS
    suppressed (plan §3.4/§5); the distinct ``suppressed`` state remains for
    manual suppression.
    """
    current = _utc(now)
    with _locked_store(store_path) as store:
        row = store["incidents"].get(incident_id)
        if not isinstance(row, dict):
            return {"recorded": False, "reason": "unknown_incident"}
        escalation = row.get("escalation")
        if not isinstance(escalation, dict):
            escalation = {"at": current.isoformat()}
            row["escalation"] = escalation
        if root_cause_task_id:
            escalation["root_cause_task_id"] = str(root_cause_task_id)
        if notified:
            escalation["notified_at"] = current.isoformat()
            if notification_id:
                escalation["notification_id"] = str(notification_id)
        row["state"] = STATE_ESCALATED
        row["suppressed_until"] = None  # permanent until root-cause succeeds
        return {"recorded": True, "incident_id": incident_id, "escalation": dict(escalation)}


def record_throttled(
    store_path: str | Path,
    incident_id: str,
    *,
    now: datetime | None = None,
    reason: str = "remediation_cap_24h",
) -> dict[str, Any]:
    """G6 receipt: the global 24h cap refused this incident's disposition."""
    current = _utc(now)
    with _locked_store(store_path) as store:
        row = store["incidents"].get(incident_id)
        if not isinstance(row, dict):
            return {"recorded": False, "reason": "unknown_incident"}
        throttled = row.setdefault("throttled", {"count": 0, "last_at": None})
        throttled["count"] = int(throttled.get("count") or 0) + 1
        throttled["last_at"] = current.isoformat()
        throttled["last_reason"] = reason
        return {"recorded": True, "incident_id": incident_id,
                "throttled_count": throttled["count"]}


# ── escalation actuator (plan §5) ────────────────────────────────────────────


def _escalation_task_record(row: dict[str, Any], now: datetime) -> dict[str, Any]:
    failures = row.get("episode_failures") or []
    history = row.get("task_history") or []
    instances = row.get("instances") or []
    failure_lines = "\n".join(
        f"- e{f.get('episode')} `{f.get('task_id')}`（{f.get('status')}）: "
        f"{str(f.get('failure_reason') or '')[:160]}"
        for f in failures[-6:]
    ) or "-（本類不開自動修復單，無處置任務史）"
    instance_lines = "\n".join(
        f"- `{i.get('key')}`（first_seen {i.get('first_seen_at')}，"
        f"cleared={'yes' if i.get('cleared_at') else 'no'}）"
        for i in instances[:12]
    )
    if len(instances) > 12:
        instance_lines += f"\n- …及另外 {len(instances) - 12} 個（見 incidents.json）"
    record: dict[str, Any] = {
        "id": suggested_root_cause_task_id(row),
        "title": f"[根因重構] {row.get('kind')}（incident {row.get('incident_id')}，"
                 f"第 {row.get('episode_count')} 個 episode 未收斂）",
        "description": (
            f"Incident `{row.get('incident_id')}`（kind `{row.get('kind')}`，"
            f"class {row.get('class')}）自動處置未收斂，依 3-strike 升級為根因重構。\n\n"
            f"- fingerprint: `{row.get('fingerprint')}`\n"
            f"- first_seen_at: {row.get('first_seen_at')}\n"
            f"- occurrence_count: {row.get('occurrence_count')}（偵測次數，永不歸零）\n"
            f"- episode_count: {row.get('episode_count')}\n"
            f"- 前次處置任務: {[h.get('task_id') for h in history[-6:]]}\n"
            f"- 各次失敗原因:\n{failure_lines}\n"
            + (f"- instances:\n{instance_lines}\n" if instance_lines else "")
            + "\n此後本 incident 永久停止自動開修復單（suppressed），直到本任務 "
            "succeeded 才解除。交付物 = 三層（底層邏輯/流程/架構）根因修正 + regression "
            "gate，不是再一張補丁。來源: src/volpred/ops/incident.py actuate_escalation。"
        ),
        "task_type": "platform_ops",
        # 老闆裁決（2026-07-21 dispatch-lanes 重構後）：escalation 單不得偽裝
        # boss 來源（plan §5 原案 source=user 已被否決）——P1 是「boss 當下要的 +
        # 時效性」的語意，機器升級單靠 P1 搶位等於取消 priority。escalated 單接受
        # P2 + time-insensitive；「恰好一張、不重複」的機械保證來自 escalated 狀態
        # 的唯一性（G4：actuated 後永不再開），不靠 priority 搶位。
        "priority": 2,
        "status": "pending",
        "source": "incident_escalation",
        "incident_id": row.get("incident_id"),
        "created_at": now.isoformat(),
    }
    if str(row.get("class")) == CLASS_MACHINE_SELF:
        # machine_self 根因 = 執行機器本身；修它的人不能是那台壞掉的機器 → 主線程 lane。
        record["dispatch_lane"] = "main_thread"
    return record


def actuate_escalation(
    store_path: str | Path,
    incident_id: str,
    *,
    queue_path: str | Path,
    now: datetime | None = None,
    notify: Callable[..., dict[str, Any]] | None = None,
    send_mail: bool = True,
) -> dict[str, Any]:
    """Do the *exactly three things* of plan §5, idempotently.

    1. ONE ``[根因重構]`` task via the ``append_task_record`` gateway
       (deterministic id ⇒ replays dedup; source=incident_escalation is exempt
       from the G6 cap — the loop's exit is never capped).
    2. ONE escalation mail (stable title ⇒ transport 24h dedup).
    3. The incident stops auto-dispositions permanently (escalated state; the
       breach router treats it as suppressed once both receipts exist).

    A crash between steps leaves the receipt missing, and the next breach
    observation returns ``escalate`` again — both steps are idempotent.
    """
    current = _utc(now)
    row = load_incident(store_path, incident_id)
    if row is None:
        return {"actuated": False, "reason": "unknown_incident", "incident_id": incident_id}
    escalation = row.get("escalation") if isinstance(row.get("escalation"), dict) else {}
    receipt: dict[str, Any] = {"incident_id": incident_id, "actuated": True}

    task_id = str(escalation.get("root_cause_task_id") or "")
    task_status = next_tasks_status_probe(queue_path)(task_id) if task_id else None
    if not task_id or task_status is None:
        from volpred.ops.next_tasks import (  # lazy: avoid import cycle
            append_task_record,
        )

        record = _escalation_task_record(row, current)
        expected_task_id = str(record["id"])
        if task_id and task_id != expected_task_id:
            raise ValueError(
                "incident escalation receipt task id does not match deterministic identity: "
                f"receipt={task_id!r} expected={expected_task_id!r}"
            )
        # Incident identity already provides exact dedupe.  Generic semantic
        # dedupe must not merge distinct incidents merely because both mention
        # incident.py / first_seen_at; that produced a receipt for a task that
        # never entered next_tasks.json in production.
        stored, created = append_task_record(
            record,
            path=queue_path,
            if_exists="skip",
            semantic_dedupe=False,
        )
        task_id = str(stored.get("id") or record["id"])
        if task_id != expected_task_id:
            raise ValueError(
                "incident escalation admission returned a different task identity: "
                f"returned={task_id!r} expected={expected_task_id!r}"
            )
        receipt["task_created"] = created
        record_escalation(store_path, incident_id, root_cause_task_id=task_id, now=current)
    else:
        receipt["task_created"] = False
    receipt["root_cause_task_id"] = task_id

    if send_mail and not escalation.get("notified_at"):
        title = f"[根因重構升級] {row.get('kind')}（incident {incident_id}）"
        body = "\n".join(
            [
                "## 觸發條件",
                f"incident `{incident_id}`（kind `{row.get('kind')}`）已達 "
                f"{row.get('episode_count')} 個 episode 未收斂"
                f"（class {row.get('class')} 門檻 "
                f"{ESCALATION_THRESHOLD.get(str(row.get('class')), 3)}）。",
                "",
                "## 系統已自動執行",
                f"已開立唯一根因重構任務 `{task_id}`；本 incident 此後永久停止自動開"
                "修復單（知道但不吵），直到該任務 succeeded 才解除。",
                "",
                "## 影響",
                f"occurrence_count={row.get('occurrence_count')}，"
                f"任務池不再因此根因增生新單。",
            ]
        )
        if notify is None:
            from volpred.ops.alerts import send_alert as notify  # lazy: alerts is heavy
        try:
            delivery = notify("warn", title, body)
        except Exception as exc:  # noqa: BLE001 — mail failure leaves the due bit; next breach retries
            warn("incident_store", "escalation mail failed", incident_id=incident_id,
                 err=f"{type(exc).__name__}: {exc}")
            delivery = {"sent": False, "error": str(exc)[:200]}
        receipt["delivery"] = delivery
        owner_reached = bool(
            delivery.get("sent")
            or (delivery.get("skipped") and delivery.get("skip_reason") == "dedup_24h")
        )
        if owner_reached:
            record_escalation(
                store_path,
                incident_id,
                notified=True,
                notification_id=(
                    str(delivery.get("notification_id"))
                    if delivery.get("notification_id")
                    else None
                ),
                now=current,
            )
        receipt["notified"] = owner_reached
    elif not send_mail:
        receipt["notified"] = False
        receipt["notify_suppressed"] = True
    else:
        receipt["notified"] = True
    return receipt


# ── task-status probe helper ─────────────────────────────────────────────────


def next_tasks_status_probe(next_tasks_path: str | Path) -> Callable[[str], str | None]:
    """Probe factory: task_id → status string, or None when the id is absent."""
    path = Path(next_tasks_path)

    def probe(task_id: str) -> str | None:
        if not task_id or not path.exists():
            return None
        try:
            tasks = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warn("incident_store", "task status probe failed", path=str(path), err=str(exc))
            return None
        if not isinstance(tasks, list):
            return None
        for task in tasks:
            if isinstance(task, dict) and task.get("id") == task_id:
                return str(task.get("status") or "")
        return None

    return probe
