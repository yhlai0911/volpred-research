"""Mechanical anti-regression gates for the incident lifecycle (plan §7).

Each test name maps to one gate row in
``docs/refactor_plan_incident_lifecycle.md`` §7 (G1–G7).  The design is only
real if these assertions hold; prose alone is not a disposition.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from volpred.ops import incident
from volpred.ops.next_tasks import append_task_record

T0 = datetime(2026, 7, 21, 0, 0, 0, tzinfo=timezone.utc)


def _load_tasks(queue: Path) -> list[dict]:
    if not queue.exists():
        return []
    return [t for t in json.loads(queue.read_text(encoding="utf-8")) if isinstance(t, dict)]


def _drive_breach(
    store: Path,
    queue: Path,
    *,
    kind: str,
    now: datetime,
    fingerprint_parts=(),
    instance_key: str | None = None,
) -> dict:
    """Mimic the detector wiring: route → (maybe) append via gateway → bind."""
    out = incident.route_breach(
        store,
        kind=kind,
        fingerprint_parts=fingerprint_parts,
        instance_key=instance_key,
        now=now,
        task_status_probe=incident.next_tasks_status_probe(queue),
    )
    if out["action"] == "create_task":
        record = {
            "id": out["suggested_task_id"],
            "title": f"[incident] {kind}",
            "description": f"auto disposition for {out['incident_id']}",
            "task_type": "platform_ops",
            "priority": 2,
            "status": "pending",
            "source": "incident_router",
            "incident_id": out["incident_id"],
            "created_at": now.isoformat(),
        }
        _, created = append_task_record(record, path=queue, if_exists="skip")
        if created:
            incident.bind_task(store, out["incident_id"], record["id"], now=now)
        out["task_created"] = created
    return out


def _set_task_status(queue: Path, task_id: str, status: str, now: datetime) -> None:
    tasks = _load_tasks(queue)
    for task in tasks:
        if task.get("id") == task_id:
            task["status"] = status
            task["completed_at"] = now.isoformat()
    queue.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")


def _incident_row(store: Path, kind: str, parts=()) -> dict:
    row = incident.load_incident(store, incident.incident_id_for(kind, parts))
    assert row is not None
    return row


@pytest.fixture()
def store(tmp_path: Path) -> Path:
    return tmp_path / "ops" / "incidents.json"


@pytest.fixture()
def queue(tmp_path: Path) -> Path:
    return tmp_path / "next_tasks.json"


# ── G1 ───────────────────────────────────────────────────────────────────────


def test_g1_same_fingerprint_ten_triggers_mint_exactly_one_task(store, queue) -> None:
    """G1: 同 fingerprint 連續觸發 10 次 → 只多 1 張任務；occurrence_count == 10。"""
    for i in range(10):
        _drive_breach(store, queue, kind="synthetic_gate_red", now=T0 + timedelta(minutes=i))
    tasks = _load_tasks(queue)
    assert len(tasks) == 1
    row = _incident_row(store, "synthetic_gate_red")
    assert row["occurrence_count"] == 10
    assert row["episode_count"] == 1
    assert row["state"] == incident.STATE_MITIGATING
    assert row["current_task_id"] == tasks[0]["id"]


# ── G2 ───────────────────────────────────────────────────────────────────────


def test_g2_resolve_then_breach_reuses_the_incident_and_keeps_counters(store, queue) -> None:
    """G2: resolve 後再 breach → 同一 incident row、state=open 系、episode_count==2、計數未歸零。

    「不開新單」的意思是不開一張計數歸零的全新 a1（不是新 incident）——復發開的是
    episode 2 的處置，且掛在同一 row 上（plan §4）。
    """
    _drive_breach(store, queue, kind="synthetic_gate_red", now=T0)
    row = _incident_row(store, "synthetic_gate_red")
    task_e1 = row["current_task_id"]
    _set_task_status(queue, task_e1, "succeeded", T0 + timedelta(hours=1))

    # Sustained clean (K=3 spanning >=24h) resolves the incident (G7 criterion).
    for hours in (2, 14, 27):
        incident.observe_clean(
            store, kind="synthetic_gate_red", now=T0 + timedelta(hours=hours)
        )
    row = _incident_row(store, "synthetic_gate_red")
    assert row["state"] == incident.STATE_RESOLVED

    out = _drive_breach(
        store, queue, kind="synthetic_gate_red", now=T0 + timedelta(hours=40)
    )
    rows = incident.list_incidents(store)
    assert len(rows) == 1, "recurrence must NOT mint a second incident row"
    row = rows[0]
    assert row["episode_count"] == 2
    # occurrence counts breach observations only (clean observations不計)。
    assert row["occurrence_count"] == 2

    # The episode-2 disposition is tied to the SAME incident, not a reset a1.
    assert out["action"] in {"create_task", "none"}
    tasks = _load_tasks(queue)
    incident_tasks = [t for t in tasks if t.get("incident_id") == row["incident_id"]]
    assert len(incident_tasks) == 2
    assert incident_tasks[1]["id"].endswith("_e2")


# ── G3 ───────────────────────────────────────────────────────────────────────


def test_g3_five_instances_one_incident_one_task(store, queue) -> None:
    """G3: 同根因 5 個不同實例 → 1 個 incident、len(instances)==5、只 1 張任務。"""
    for i in range(5):
        _drive_breach(
            store,
            queue,
            kind="worktree_unmerged",
            now=T0 + timedelta(minutes=i),
            instance_key=f"agent-worktree-{i}",
        )
    rows = incident.list_incidents(store)
    assert len(rows) == 1
    row = rows[0]
    assert len(row["instances"]) == 5
    assert row["kind"] == "worktree_unmerged"
    tasks = _load_tasks(queue)
    assert len(tasks) == 1, "five instances must share ONE aggregate task"


# ── supporting invariants (P1) ───────────────────────────────────────────────


def test_fingerprint_ignores_order_and_excludes_instances() -> None:
    a = incident.fingerprint("phase_z_test_gate_red", ["node_b", "node_a"])
    b = incident.fingerprint("phase_z_test_gate_red", ["node_a", "node_b"])
    assert a == b
    assert incident.incident_id_for("worker_orphaned") == incident.incident_id_for(
        "worker_orphaned"
    )


def test_counters_never_reset_across_resolutions(store, queue) -> None:
    """plan §3.2 property 1: resolve only changes state; counters are monotone."""
    _drive_breach(store, queue, kind="synthetic_gate_red", now=T0)
    row = _incident_row(store, "synthetic_gate_red")
    _set_task_status(queue, row["current_task_id"], "succeeded", T0 + timedelta(hours=1))
    for hours in (2, 14, 27):
        incident.observe_clean(
            store, kind="synthetic_gate_red", now=T0 + timedelta(hours=hours)
        )
    row = _incident_row(store, "synthetic_gate_red")
    assert row["state"] == incident.STATE_RESOLVED
    assert row["occurrence_count"] >= 1
    assert row["episode_count"] == 1
    before = (row["occurrence_count"], row["episode_count"])
    _drive_breach(store, queue, kind="synthetic_gate_red", now=T0 + timedelta(hours=40))
    row = _incident_row(store, "synthetic_gate_red")
    assert row["occurrence_count"] == before[0] + 1
    assert row["episode_count"] == before[1] + 1


def test_task_vanished_retries_same_episode_without_new_episode(store, queue) -> None:
    """A bound-but-missing task (e.g. throttled append) retries, not escalates."""
    out = incident.route_breach(
        store, kind="synthetic_gate_red", now=T0,
        task_status_probe=incident.next_tasks_status_probe(queue),
    )
    assert out["action"] == "create_task"
    incident.bind_task(store, out["incident_id"], out["suggested_task_id"], now=T0)
    # Task never appended (queue empty) — next breach retries the same episode.
    out2 = incident.route_breach(
        store, kind="synthetic_gate_red", now=T0 + timedelta(minutes=5),
        task_status_probe=incident.next_tasks_status_probe(queue),
    )
    assert out2["action"] == "create_task"
    assert out2["episode_count"] == 1
