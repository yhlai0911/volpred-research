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


def test_instance_polling_records_one_graph_transition_but_all_observations(
    store, queue
) -> None:
    """Repeated sweeps of one unchanged edge are observations, not incidents."""
    for i in range(3):
        incident.route_breach(
            store,
            kind="worker_orphaned",
            instance_key="dispatch-slot-1-same",
            instance_detail={"reason": "worker_orphaned", "branch": "same"},
            now=T0 + timedelta(minutes=i),
        )

    row = _incident_row(store, "worker_orphaned")
    assert row["occurrence_count"] == 3
    assert row["instance_transitions"] == [
        {
            "at": T0.isoformat(),
            "instance_key": "dispatch-slot-1-same",
            "transition": "opened",
        }
    ]


def test_only_instance_open_and_reopen_are_graph_transitions(
    store, queue
) -> None:
    incident.route_breach(
        store,
        kind="worker_orphaned",
        instance_key="dispatch-slot-1-changing",
        instance_detail={"reason": "gate_red"},
        now=T0,
    )
    incident.route_breach(
        store,
        kind="worker_orphaned",
        instance_key="dispatch-slot-1-changing",
        instance_detail={"reason": "undeclared_output_path"},
        now=T0 + timedelta(hours=1),
    )
    incident.clear_instance(
        store,
        kind="worker_orphaned",
        instance_key="dispatch-slot-1-changing",
        now=T0 + timedelta(hours=2),
    )
    incident.route_breach(
        store,
        kind="worker_orphaned",
        instance_key="dispatch-slot-1-changing",
        instance_detail={"reason": "undeclared_output_path"},
        now=T0 + timedelta(hours=3),
    )

    row = _incident_row(store, "worker_orphaned")
    assert [
        transition["transition"]
        for transition in row["instance_transitions"]
    ] == ["opened", "reopened"]
    assert row["instances"][0]["detail"] == {
        "reason": "undeclared_output_path"
    }


# ── G6 ───────────────────────────────────────────────────────────────────────


def _auto_remediation_record(i: int, now: datetime) -> dict:
    return {
        "id": f"inc_syntheticfp{i:02d}_e1",
        "title": f"[incident] synthetic {i}",
        "description": "auto disposition",
        "task_type": "platform_ops",
        "priority": 2,
        "status": "pending",
        "source": "incident_router",
        "incident_id": f"inc_syntheticfp{i:02d}",
        "created_at": now.isoformat(),
    }


def test_g6_rolling_24h_cap_refuses_task_nine_and_ledgers_it(queue, tmp_path) -> None:
    """G6: 滾動 24h 自動補救任務 > 上限（8）→ 超出的一律不開單、記 ledger。"""
    from volpred.ops import remediation_throttle as throttle

    now = datetime.now(timezone.utc)
    for i in range(throttle.MAX_AUTO_REMEDIATION_PER_DAY):
        _, created = append_task_record(
            _auto_remediation_record(i, now - timedelta(hours=1)), path=queue
        )
        assert created
    ninth = _auto_remediation_record(99, now)
    record, created = append_task_record(ninth, path=queue)
    assert created is False
    assert record.get("throttled_by_remediation_cap") is True
    assert len(_load_tasks(queue)) == throttle.MAX_AUTO_REMEDIATION_PER_DAY

    ledger = throttle.ledger_path_for(queue)
    lines = [json.loads(l) for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
    assert lines[0]["task_id"] == ninth["id"]

    # 非補救類任務不受 cap 影響（cap 只擋 auto-remediation class）。
    ordinary = {
        "id": "assign_deadbeef",
        "title": "daily article",
        "description": "x",
        "task_type": "daily_article",
        "priority": 3,
        "status": "pending",
        "source": "auto_discovered",
        "created_at": now.isoformat(),
    }
    _, created = append_task_record(ordinary, path=queue)
    assert created is True


def test_g6_tasks_older_than_24h_leave_the_window(queue) -> None:
    from volpred.ops import remediation_throttle as throttle

    now = datetime.now(timezone.utc)
    for i in range(throttle.MAX_AUTO_REMEDIATION_PER_DAY):
        append_task_record(
            _auto_remediation_record(i, now - timedelta(hours=30)), path=queue
        )
    _, created = append_task_record(_auto_remediation_record(50, now), path=queue)
    assert created is True


def test_g6_daily_summary_is_one_mail_with_date_stable_title(queue, tmp_path) -> None:
    """G6 尾款：每日彙整 1 封 — title 內嵌日期，transport 24h dedup 收斂為一封。"""
    from volpred.ops import remediation_throttle as throttle

    now = datetime.now(timezone.utc)
    ledger = throttle.ledger_path_for(queue)
    for i in range(3):
        throttle.record_denial(_auto_remediation_record(i, now), ledger_path=ledger, now=now)

    calls: list[tuple] = []

    def notify(level, title, body):
        calls.append((level, title))
        return {"sent": True}

    first = throttle.flush_denial_summary(ledger_path=ledger, now=now, notify=notify)
    second = throttle.flush_denial_summary(ledger_path=ledger, now=now, notify=notify)
    assert first["denials"] == 3
    assert first["sent"] and second["sent"]
    # 同一天兩次 flush 的 title 完全相同 ⇒ transport sha256(level|title) 24h dedup
    # 機械上收斂為一封（dedup owner = alerts transport，不在本模組疊第二層）。
    assert calls[0][1] == calls[1][1]
    assert now.date().isoformat() in calls[0][1]


def test_g6_internal_alert_path_is_capped_and_recorded_on_incident(tmp_path) -> None:
    """內部路的開單走 gateway，同受 cap；且拒絕記到 incident（G6 尾款）。"""
    from volpred.ops import incident
    from volpred.ops import remediation_throttle as throttle
    from volpred.ops.alert_remediation import remediate_internal_alert

    storage = tmp_path / "storage"
    storage.mkdir()
    queue_path = storage / "next_tasks.json"
    now = datetime.now(timezone.utc)
    rows = [
        _auto_remediation_record(i, now - timedelta(hours=2))
        for i in range(throttle.MAX_AUTO_REMEDIATION_PER_DAY)
    ]
    queue_path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    # synthetic kind → DEFAULT_POLICY = ordinary/auto_repair → create_task 路。
    outcome = remediate_internal_alert(
        {"id": "synthetic_gate_red", "breached": True, "level": "warn",
         "title": "gate red", "body": "x"},
        alert_key="synthetic_gate_red",
        storage_dir=str(storage),
        now=now,
    )
    assert outcome.get("created") is False
    assert outcome.get("reason") == "remediation_throttled"
    assert len(json.loads(queue_path.read_text(encoding="utf-8"))) == (
        throttle.MAX_AUTO_REMEDIATION_PER_DAY
    )
    row = incident.load_incident(
        storage / "ops" / "incidents.json",
        incident.incident_id_for("synthetic_gate_red"),
    )
    assert row is not None
    assert row["throttled"]["count"] == 1  # G6: 拒絕記在 incident row 上


# ── G4 ───────────────────────────────────────────────────────────────────────


def _fail_current_task(store: Path, queue: Path, kind: str, now: datetime) -> None:
    row = _incident_row(store, kind)
    _set_task_status(queue, row["current_task_id"], "failed", now)


def test_g4_three_unconverged_episodes_escalate_exactly_once(store, queue) -> None:
    """G4: 連續 episode 未收斂 → escalated；恰 1 張[根因重構]任務、恰 1 封信；
    之後再觸發 10 次 → 0 張新任務。

    門檻語意（§5「episode_count >= 3 且未達 resolution → escalated」）：第 3 個
    episode 的處置**就是**升級本身，不再開第 3 張自動修復單。
    """
    kind = "synthetic_gate_red"
    # episode 1 disposition fails, breach persists -> episode 2
    _drive_breach(store, queue, kind=kind, now=T0)
    _fail_current_task(store, queue, kind, T0 + timedelta(hours=1))
    _drive_breach(store, queue, kind=kind, now=T0 + timedelta(hours=2))
    # episode 2 disposition fails, breach persists -> episode 3 => escalate
    _fail_current_task(store, queue, kind, T0 + timedelta(hours=3))
    out = _drive_breach(store, queue, kind=kind, now=T0 + timedelta(hours=4))
    assert out["action"] == "escalate"
    assert out["episode_count"] == 3
    assert out["state"] == incident.STATE_ESCALATED

    mails: list[str] = []

    def notify(level, title, body):
        mails.append(title)
        return {"sent": True, "notification_id": "esc-1"}

    receipt = incident.actuate_escalation(
        store, out["incident_id"], queue_path=queue,
        now=T0 + timedelta(hours=4), notify=notify,
    )
    assert receipt["task_created"] is True
    assert receipt["notified"] is True
    assert len(mails) == 1

    tasks = _load_tasks(queue)
    root = [t for t in tasks if t.get("source") == "incident_escalation"]
    assert len(root) == 1
    assert root[0]["title"].startswith("[根因重構]")
    assert root[0]["priority"] == 2  # 裁決：不偽裝 boss 來源、不搶 P1

    # 之後再觸發 10 次 → 0 張新任務（suppressed），occurrence 續計。
    before = len(tasks)
    for i in range(10):
        out = _drive_breach(
            store, queue, kind=kind, now=T0 + timedelta(hours=5 + i)
        )
        assert out["action"] == "suppressed"
    assert len(_load_tasks(queue)) == before
    row = _incident_row(store, kind)
    assert row["state"] == incident.STATE_ESCALATED
    assert row["occurrence_count"] == 13


def test_g4_root_cause_success_lifts_suppression(store, queue) -> None:
    """§5 尾款：suppression 直到根因任務 succeeded 才解除（resolved）。"""
    kind = "synthetic_gate_red"
    _drive_breach(store, queue, kind=kind, now=T0)
    _fail_current_task(store, queue, kind, T0 + timedelta(hours=1))
    _drive_breach(store, queue, kind=kind, now=T0 + timedelta(hours=2))
    _fail_current_task(store, queue, kind, T0 + timedelta(hours=3))
    out = _drive_breach(store, queue, kind=kind, now=T0 + timedelta(hours=4))
    receipt = incident.actuate_escalation(
        store, out["incident_id"], queue_path=queue,
        now=T0 + timedelta(hours=4), notify=lambda *a: {"sent": True},
    )
    _set_task_status(
        queue, receipt["root_cause_task_id"], "succeeded", T0 + timedelta(hours=30)
    )
    after = _drive_breach(store, queue, kind=kind, now=T0 + timedelta(hours=31))
    # root cause fixed -> resolved -> the relapse is a NEW episode of the same
    # row (counters keep history; being over threshold it escalates again).
    row = _incident_row(store, kind)
    assert row["episode_count"] == 4
    assert after["action"] == "escalate"
    resolutions = row["resolutions"]
    assert any(r["criterion"] == "root_cause_task_succeeded" for r in resolutions)


# ── G5 ───────────────────────────────────────────────────────────────────────


def test_g5_machine_self_escalates_at_episode_two_without_ever_mitigating(
    store, queue
) -> None:
    """G5: class=machine_self 且 episode_count==2 → 直接 escalated，
    不曾進 mitigating、不曾開過自動修復單。"""
    kind = "phase_z_test_gate_red"  # machine_self / task_mode none
    out1 = _drive_breach(store, queue, kind=kind, now=T0)
    assert out1["action"] == "notify"
    assert _load_tasks(queue) == []

    # sustained clean resolves episode 1
    for hours in (2, 14, 27):
        incident.observe_clean(store, kind=kind, now=T0 + timedelta(hours=hours))
    assert _incident_row(store, kind)["state"] == incident.STATE_RESOLVED

    out2 = _drive_breach(store, queue, kind=kind, now=T0 + timedelta(hours=40))
    assert out2["action"] == "escalate"
    assert out2["episode_count"] == 2
    row = _incident_row(store, kind)
    assert row["state"] == incident.STATE_ESCALATED
    assert row["task_history"] == []  # 從未開過自動修復單（不曾 mitigating）
    assert _load_tasks(queue) == []

    receipt = incident.actuate_escalation(
        store, row["incident_id"], queue_path=queue,
        now=T0 + timedelta(hours=40), notify=lambda *a: {"sent": True},
    )
    root = _load_tasks(queue)
    assert len(root) == 1
    assert root[0]["source"] == "incident_escalation"
    # machine_self 根因 = 執行機器本身 → 主線程 lane（§6）。
    assert root[0]["dispatch_lane"] == "main_thread"
    assert receipt["root_cause_task_id"] == root[0]["id"]


# ── G7 ───────────────────────────────────────────────────────────────────────


def test_g7_one_clean_is_not_resolution(store, queue) -> None:
    """G7: 單次乾淨後 state 仍為 mitigating；滿足 K 次 + 24h 才 resolved。"""
    kind = "synthetic_gate_red"
    _drive_breach(store, queue, kind=kind, now=T0)
    out = incident.observe_clean(store, kind=kind, now=T0 + timedelta(hours=1))
    assert out["resolved"] is False
    assert _incident_row(store, kind)["state"] == incident.STATE_MITIGATING

    # K=3 但跨度 < 24h → 仍不 resolve
    incident.observe_clean(store, kind=kind, now=T0 + timedelta(hours=2))
    out = incident.observe_clean(store, kind=kind, now=T0 + timedelta(hours=3))
    assert out["resolved"] is False
    assert _incident_row(store, kind)["state"] == incident.STATE_MITIGATING

    # 第 4 次乾淨拉開 >=24h 跨度 → resolved
    out = incident.observe_clean(store, kind=kind, now=T0 + timedelta(hours=26))
    assert out["resolved"] is True
    assert _incident_row(store, kind)["state"] == incident.STATE_RESOLVED


def test_g7_breach_resets_the_clean_streak(store, queue) -> None:
    kind = "synthetic_gate_red"
    _drive_breach(store, queue, kind=kind, now=T0)
    incident.observe_clean(store, kind=kind, now=T0 + timedelta(hours=1))
    incident.observe_clean(store, kind=kind, now=T0 + timedelta(hours=13))
    _drive_breach(store, queue, kind=kind, now=T0 + timedelta(hours=14))  # streak 歸零
    out = incident.observe_clean(store, kind=kind, now=T0 + timedelta(hours=26))
    assert out["resolved"] is False  # 舊 streak 不得跨過 breach 累積
    assert _incident_row(store, kind)["clean_streak_started_at"] == (
        T0 + timedelta(hours=26)
    ).isoformat()


def test_g7_high_frequency_observations_can_outlive_the_ring_buffer(store, queue) -> None:
    """A 24h streak must resolve even when its first sample has been trimmed."""
    kind = "synthetic_gate_red"
    _drive_breach(store, queue, kind=kind, now=T0)

    out = None
    for hour in range(1, 26):
        out = incident.observe_clean(
            store,
            kind=kind,
            now=T0 + timedelta(hours=hour),
        )

    assert out is not None
    assert out["resolved"] is True
    row = _incident_row(store, kind)
    assert row["state"] == incident.STATE_RESOLVED
    assert row["resolution"]["criterion"] == "clean_streak_k3_24h"


def test_g7_old_rows_lazily_migrate_from_the_oldest_retained_observation(
    store,
    queue,
) -> None:
    """Migration must be conservative and must not require store surgery."""
    kind = "synthetic_gate_red"
    _drive_breach(store, queue, kind=kind, now=T0)
    for hour in range(1, 13):
        incident.observe_clean(
            store,
            kind=kind,
            now=T0 + timedelta(hours=hour),
        )

    payload = json.loads(store.read_text(encoding="utf-8"))
    row = payload["incidents"][incident.incident_id_for(kind)]
    row.pop("clean_streak_started_at")
    store.write_text(json.dumps(payload), encoding="utf-8")

    out = incident.observe_clean(
        store,
        kind=kind,
        now=T0 + timedelta(hours=25),
    )

    assert out["resolved"] is True
    assert _incident_row(store, kind)["state"] == incident.STATE_RESOLVED


# ── plan 附註: dispatch contradiction ────────────────────────────────────────


def test_appendix_main_thread_reserved_task_never_requests_hourly_fire() -> None:
    """plan 附註 regression: `request_fire` 不得對 main_thread lane 任務發
    hourly fire —— 沒有 interactive session 就永遠沒有合法執行者。

    Owner = next_tasks.is_main_thread_reserved（status pending_main_thread 與
    dispatch_lane 兩個欄位收編成一個判定）；task_urgency 與 claim gate 共用。
    """
    from volpred.ops import task_urgency
    from volpred.ops.next_tasks import _request_urgent_fire, is_main_thread_reserved

    by_status = {
        "id": "assign_10927b4e",
        "title": "[refactor-master] incident lifecycle",
        "priority": 1,
        "source": "user",
        "status": "pending_main_thread",
        "task_type": "platform_ops",
    }
    by_lane = {**by_status, "status": "pending", "dispatch_lane": "main_thread"}
    for task in (by_status, by_lane):
        assert is_main_thread_reserved(task) is True
        assert task_urgency.classify(task) == task_urgency.LANE_DEFERRED
        assert task_urgency.is_urgent(task) is False
        # is_urgent False short-circuits before any supervisor state is touched.
        assert _request_urgent_fire(task, Path("storage/next_tasks.json")) is False

    plain_urgent = {**by_status, "status": "pending"}
    assert is_main_thread_reserved(plain_urgent) is False
    assert task_urgency.is_urgent(plain_urgent) is True  # boss 急件不受影響


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
