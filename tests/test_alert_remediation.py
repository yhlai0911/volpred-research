"""Every breached alert must become work the platform does, not a chore for the owner.

2026-07-13: the owner replied to two consecutive `member_qa_stale` alerts with
「你要立即處理 不是只建議我」. A sweep found 24 of 27 alert bodies carried a
`## 建議行動` section addressed to a human. These tests pin the inversion: task
creation is the *default*, exemptions must be declared and justified, and the
email leads with what the system already did.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from volpred.ops import alert_remediation as ar

NOW = datetime(2026, 7, 13, 1, 30, tzinfo=timezone.utc)


def _condition(alert_id: str, *, breached: bool = True, level: str = "warn") -> dict:
    return {
        "id": alert_id,
        "breached": breached,
        "level": level,
        "title": f"{alert_id} title",
        "body": "## 觸發條件\n某某壞了。\n\n## 建議行動\n1. 主線程立即跑 some-command\n",
    }


@pytest.fixture()
def pool(tmp_path):
    (tmp_path / "next_tasks.json").write_text("[]\n", encoding="utf-8")
    return tmp_path


def _tasks(pool) -> list[dict]:
    return json.loads((pool / "next_tasks.json").read_text(encoding="utf-8"))


def _finish_only_task(pool, *, status: str, at: datetime, result: str) -> None:
    tasks = _tasks(pool)
    active = [
        task
        for task in tasks
        if task.get("status") in {"pending", "claimed", "in_progress"}
    ]
    assert len(active) == 1
    active[0]["status"] = status
    active[0]["completed_at"] = at.isoformat()
    active[0]["result"] = result
    (pool / "next_tasks.json").write_text(
        json.dumps(tasks, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_unknown_alert_defaults_to_creating_a_task(pool) -> None:
    """The default branch is 'do the work' — not 'tell the owner to'.

    A newly added alert gets a task whether or not anyone remembered to classify
    it. That is the whole point: there is no path that quietly falls back to nagging.
    """
    cond = _condition("some_brand_new_alert_nobody_classified")

    result = ar.remediate_condition(cond, storage_dir=str(pool), now=NOW)

    assert result["disposition"] == "task"
    assert result["created"] is True
    queued = _tasks(pool)
    assert [t["id"] for t in queued] == ["alert_some_brand_new_alert_nobody_classified_20260713"]
    assert queued[0]["task_type"] == "platform_ops"
    assert queued[0]["status"] == "pending"


def test_member_qa_stale_the_incident_alert_now_queues_work(pool) -> None:
    cond = _condition("member_qa_stale")

    result = ar.remediate_condition(cond, storage_dir=str(pool), now=NOW)

    assert result["disposition"] == "task"
    assert _tasks(pool)[0]["task_type"] == "member_qa"


def test_alert_task_requires_fresh_revalidation_before_state_change(pool) -> None:
    ar.remediate_condition(_condition("release_pool_gap"), storage_dir=str(pool), now=NOW)

    description = _tasks(pool)[0]["description"]
    assert "原 detector 重新驗證" in description
    assert "若已自然解除" in description
    assert "不得照舊快照執行" in description


def test_body_leads_with_what_was_done_and_demotes_the_todo_list(pool) -> None:
    cond = _condition("member_qa_stale")

    ar.remediate_condition(cond, storage_dir=str(pool), now=NOW)

    body = cond["body"]
    assert body.startswith("## 已自動處理")
    assert "老闆無需動作" in body
    # The steps survive for whoever executes the task — they just stop being
    # addressed to the owner as an action item.
    assert "## 建議行動" not in body
    assert "供執行者稽核" in body
    assert "some-command" in body


def test_critical_outranks_warn(pool) -> None:
    ar.remediate_condition(_condition("a_critical", level="critical"), storage_dir=str(pool), now=NOW)
    ar.remediate_condition(_condition("a_warn", level="warn"), storage_dir=str(pool), now=NOW)

    by_id = {t["id"]: t for t in _tasks(pool)}
    assert by_id["alert_a_critical_20260713"]["priority"] == 1
    assert by_id["alert_a_warn_20260713"]["priority"] == 2


def test_hourly_alert_does_not_mint_twenty_four_tasks(pool) -> None:
    """The member_qa alert fired every hour for 25h. Idempotency is not optional."""
    first = ar.remediate_condition(_condition("member_qa_stale"), storage_dir=str(pool), now=NOW)
    later = NOW.replace(hour=5)
    second = ar.remediate_condition(_condition("member_qa_stale"), storage_dir=str(pool), now=later)

    assert first["created"] is True
    assert second["created"] is False
    assert second["reason"] == "already_queued_today"
    assert len(_tasks(pool)) == 1


def test_internal_alert_uses_stable_p1_task_and_suppresses_active_repeats(
    pool,
) -> None:
    first = ar.remediate_internal_alert(
        _condition("silent_fallback_new"),
        alert_key="silent_fallback_new",
        storage_dir=str(pool),
        now=NOW,
    )
    changed_title = _condition("silent_fallback_new")
    changed_title["title"] = "push held — 17 NEW findings"
    second = ar.remediate_internal_alert(
        changed_title,
        alert_key="silent_fallback_new",
        storage_dir=str(pool),
        now=NOW + timedelta(hours=1),
    )

    assert first["created"] is True
    assert first["priority"] == 1
    assert first["escalate"] is False
    assert second["reason"] == "remediation_active"
    assert second["escalate"] is False
    queued = _tasks(pool)
    assert len(queued) == 1
    assert queued[0]["id"].startswith(
        ar.task_id_for_alert_key("silent_fallback_new") + "_"
    )
    assert queued[0]["priority"] == 1
    assert queued[0]["task_type"] == "platform_ops"
    assert queued[0]["internal_alert_state"]["consecutive_remediation_failures"] == 0


def test_internal_alert_escalates_only_after_two_completed_repairs_still_fail(
    pool,
    monkeypatch,
) -> None:
    from volpred.ops import alerts

    deliveries: list[dict] = []

    def fake_send(level, title, body, **kwargs):
        deliveries.append({"level": level, "title": title, "body": body, **kwargs})
        return {"sent": True, "skipped": False, "notification_id": "n-1", "title": title}

    monkeypatch.setattr(alerts, "send_alert", fake_send)
    first = alerts.route_internal_remediable_alert(
        alert_key="phase_z_baseline_missing",
        level="warn",
        title="PHASE-Z baseline missing",
        body="first fire",
        storage_dir=str(pool),
        now=NOW,
    )
    assert first["sent"] is False
    assert first["skip_reason"] == "internal_auto_remediation"

    _finish_only_task(
        pool,
        status="succeeded",
        at=NOW + timedelta(minutes=20),
        result="restored snapshot",
    )
    second = alerts.route_internal_remediable_alert(
        alert_key="phase_z_baseline_missing",
        level="warn",
        title="PHASE-Z baseline missing — another count",
        body="second fire",
        storage_dir=str(pool),
        now=NOW + timedelta(hours=8),
    )
    assert second["sent"] is False
    assert second["remediation"]["consecutive_remediation_failures"] == 1
    assert deliveries == []

    _finish_only_task(
        pool,
        status="failed",
        at=NOW + timedelta(hours=8, minutes=20),
        result="snapshot writer still unavailable",
    )
    third = alerts.route_internal_remediable_alert(
        alert_key="phase_z_baseline_missing",
        level="warn",
        title="PHASE-Z baseline missing — count changed again",
        body="third fire",
        storage_dir=str(pool),
        now=NOW + timedelta(hours=16),
    )

    assert third["escalated"] is True
    assert len(deliveries) == 1
    assert deliveries[0]["title"].startswith(
        "內部自動修復連續失敗（phase_z_baseline_missing；episode "
    )
    assert "已自動嘗試 2 次" in deliveries[0]["body"]
    assert "snapshot writer still unavailable" in deliveries[0]["body"]
    queued = _tasks(pool)
    assert len({task["id"] for task in queued}) == 3
    assert [task["status"] for task in queued].count("pending") == 1
    assert queued[-1]["internal_alert_state"]["escalation_sent_at"]


def test_internal_alert_resolution_resets_a_later_episode(pool, monkeypatch) -> None:
    from volpred.ops import alerts

    monkeypatch.setattr(
        alerts,
        "send_alert",
        lambda *args, **kwargs: pytest.fail("fresh episode must not email"),
    )
    alerts.route_internal_remediable_alert(
        alert_key="silent_fallback_new",
        level="warn",
        title="held",
        body="NEW one",
        storage_dir=str(pool),
        now=NOW,
    )
    _finish_only_task(
        pool,
        status="succeeded",
        at=NOW + timedelta(minutes=10),
        result="fixed",
    )
    resolved = alerts.resolve_internal_remediable_alert(
        alert_key="silent_fallback_new",
        storage_dir=str(pool),
        now=NOW + timedelta(minutes=20),
    )
    recurrence = alerts.route_internal_remediable_alert(
        alert_key="silent_fallback_new",
        level="warn",
        title="held again",
        body="unrelated NEW later",
        storage_dir=str(pool),
        now=NOW + timedelta(minutes=40),
    )

    assert resolved["resolved"] is True
    assert recurrence["escalated"] is False
    assert recurrence["remediation"]["consecutive_remediation_failures"] == 0


def test_internal_attempt_ids_prevent_stale_completion_from_terminalising_new_worker(
    pool,
) -> None:
    first = ar.remediate_internal_alert(
        _condition("silent_fallback_new"),
        alert_key="silent_fallback_new",
        storage_dir=str(pool),
        now=NOW,
    )
    _finish_only_task(
        pool,
        status="succeeded",
        at=NOW + timedelta(minutes=20),
        result="attempt A done",
    )
    second = ar.remediate_internal_alert(
        _condition("silent_fallback_new"),
        alert_key="silent_fallback_new",
        storage_dir=str(pool),
        now=NOW + timedelta(hours=1),
    )
    assert first["task_id"] != second["task_id"]

    # A late idempotent completion receipt for attempt A can only touch A's row.
    tasks = _tasks(pool)
    attempt_a = next(task for task in tasks if task["id"] == first["task_id"])
    attempt_a["status"] = "failed"
    attempt_a["result"] = "late stale receipt"
    (pool / "next_tasks.json").write_text(
        json.dumps(tasks, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    repeated = ar.remediate_internal_alert(
        _condition("silent_fallback_new"),
        alert_key="silent_fallback_new",
        storage_dir=str(pool),
        now=NOW + timedelta(hours=2),
    )
    active = next(task for task in _tasks(pool) if task["id"] == second["task_id"])
    assert repeated["reason"] == "remediation_active"
    assert repeated["task_id"] == second["task_id"]
    assert repeated["escalate"] is False
    assert active["status"] == "pending"


def test_internal_router_orders_clean_breach_and_completion_observations(pool) -> None:
    key = "git_push_backup_hold"
    clean_first = ar.resolve_internal_alert(
        alert_key=key,
        storage_dir=str(pool),
        now=NOW + timedelta(hours=10),
    )
    stale_breach = ar.remediate_internal_alert(
        _condition(key),
        alert_key=key,
        storage_dir=str(pool),
        now=NOW + timedelta(hours=5),
    )
    first = ar.remediate_internal_alert(
        _condition(key),
        alert_key=key,
        storage_dir=str(pool),
        now=NOW + timedelta(hours=11),
    )

    assert clean_first["resolved"] is True
    assert stale_breach["reason"] == "stale_breach_observation"
    assert first["attempt_number"] == 1

    _finish_only_task(
        pool,
        status="failed",
        at=NOW + timedelta(hours=20),
        result="repair completed after an old observation",
    )
    precompletion_breach = ar.remediate_internal_alert(
        _condition(key),
        alert_key=key,
        storage_dir=str(pool),
        now=NOW + timedelta(hours=19),
    )
    second = ar.remediate_internal_alert(
        _condition(key),
        alert_key=key,
        storage_dir=str(pool),
        now=NOW + timedelta(hours=21),
    )
    stale_clean = ar.resolve_internal_alert(
        alert_key=key,
        storage_dir=str(pool),
        now=NOW + timedelta(hours=20),
    )

    assert precompletion_breach["reason"] == "awaiting_post_completion_observation"
    assert second["consecutive_remediation_failures"] == 1
    assert stale_clean["reason"] == "stale_resolution_observation"
    active = next(task for task in _tasks(pool) if task["id"] == second["task_id"])
    assert active["status"] == "pending"


def test_due_escalation_survives_transport_crash_until_acknowledged(
    pool,
    monkeypatch,
) -> None:
    from volpred.ops import alerts

    alerts.route_internal_remediable_alert(
        alert_key="phase_z_baseline_missing",
        level="warn",
        title="missing",
        body="attempt zero",
        storage_dir=str(pool),
        now=NOW,
    )
    _finish_only_task(
        pool,
        status="failed",
        at=NOW + timedelta(minutes=20),
        result="first repair failed",
    )
    alerts.route_internal_remediable_alert(
        alert_key="phase_z_baseline_missing",
        level="warn",
        title="missing",
        body="attempt one",
        storage_dir=str(pool),
        now=NOW + timedelta(hours=1),
    )
    _finish_only_task(
        pool,
        status="failed",
        at=NOW + timedelta(hours=1, minutes=20),
        result="second repair failed",
    )

    monkeypatch.setattr(
        alerts,
        "send_alert",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("transport crashed")),
    )
    with pytest.raises(RuntimeError, match="transport crashed"):
        alerts.route_internal_remediable_alert(
            alert_key="phase_z_baseline_missing",
            level="warn",
            title="missing",
            body="attempt two",
            storage_dir=str(pool),
            now=NOW + timedelta(hours=2),
        )

    latest = _tasks(pool)[-1]
    assert latest["status"] == "pending"
    assert latest["internal_alert_state"]["escalation_due"] is True
    assert "escalation_sent_at" not in latest["internal_alert_state"]

    deliveries: list[str] = []
    monkeypatch.setattr(
        alerts,
        "send_alert",
        lambda level, title, body, **kwargs: deliveries.append(title) or {
            "sent": True,
            "skipped": False,
            "notification_id": "retry-ok",
        },
    )
    retried = alerts.route_internal_remediable_alert(
        alert_key="phase_z_baseline_missing",
        level="warn",
        title="missing",
        body="retry delivery",
        storage_dir=str(pool),
        now=NOW + timedelta(hours=2, minutes=5),
    )
    quiet = alerts.route_internal_remediable_alert(
        alert_key="phase_z_baseline_missing",
        level="warn",
        title="missing",
        body="already acknowledged",
        storage_dir=str(pool),
        now=NOW + timedelta(hours=2, minutes=10),
    )

    assert retried["escalated"] is True
    assert retried["escalation_ack"]["recorded"] is True
    assert quiet["escalated"] is False
    assert len(deliveries) == 1
    assert deliveries[0].startswith(
        "內部自動修復連續失敗（phase_z_baseline_missing；episode "
    )


def test_parent_owned_transport_suppression_keeps_escalation_due_for_retry(
    pool,
    monkeypatch,
) -> None:
    from volpred.ops import alerts

    for attempt, base in enumerate((NOW, NOW + timedelta(hours=1)), start=1):
        alerts.route_internal_remediable_alert(
            alert_key="git_push_backup_hold",
            level="warn",
            title="push held",
            body=f"attempt {attempt}",
            storage_dir=str(pool),
            now=base,
        )
        _finish_only_task(
            pool,
            status="failed",
            at=base + timedelta(minutes=20),
            result=f"repair {attempt} failed",
        )

    monkeypatch.setattr(
        alerts,
        "send_alert",
        lambda *args, **kwargs: pytest.fail("parent-owned invocation must not transport"),
    )
    suppressed = alerts.route_internal_remediable_alert(
        alert_key="git_push_backup_hold",
        level="warn",
        title="push held",
        body="CI watcher owns this invocation",
        storage_dir=str(pool),
        now=NOW + timedelta(hours=2),
        suppress_owner_transport=True,
    )

    active = next(
        task for task in _tasks(pool)
        if task.get("status") in {"pending", "claimed", "in_progress"}
    )
    assert suppressed["skip_reason"] == "internal_owner_transport_suppressed"
    assert suppressed["remediation"]["consecutive_remediation_failures"] == 2
    assert active["internal_alert_state"]["escalation_due"] is True
    assert "escalation_sent_at" not in active["internal_alert_state"]

    monkeypatch.setattr(
        alerts,
        "send_alert",
        lambda *args, **kwargs: {
            "sent": True,
            "skipped": False,
            "notification_id": "standalone-retry",
        },
    )
    retried = alerts.route_internal_remediable_alert(
        alert_key="git_push_backup_hold",
        level="warn",
        title="push held",
        body="standalone detector retry",
        storage_dir=str(pool),
        now=NOW + timedelta(hours=2, minutes=5),
    )

    assert retried["escalated"] is True
    assert retried["escalation_ack"]["recorded"] is True


def test_explicitly_resolved_episode_gets_a_fresh_escalation_dedup_identity(
    pool,
    monkeypatch,
) -> None:
    from volpred.ops import alerts

    titles: list[str] = []
    monkeypatch.setattr(
        alerts,
        "send_alert",
        lambda level, title, body, **kwargs: titles.append(title) or {
            "sent": True,
            "skipped": False,
            "notification_id": f"n-{len(titles)}",
        },
    )

    for episode in range(2):
        base = NOW + timedelta(hours=episode * 6)
        alerts.route_internal_remediable_alert(
            alert_key="phase_z_baseline_missing",
            level="warn",
            title="missing",
            body=f"episode {episode}",
            storage_dir=str(pool),
            now=base,
        )
        _finish_only_task(
            pool,
            status="failed",
            at=base + timedelta(minutes=10),
            result="repair one failed",
        )
        alerts.route_internal_remediable_alert(
            alert_key="phase_z_baseline_missing",
            level="warn",
            title="missing",
            body=f"episode {episode}",
            storage_dir=str(pool),
            now=base + timedelta(hours=1),
        )
        _finish_only_task(
            pool,
            status="failed",
            at=base + timedelta(hours=1, minutes=10),
            result="repair two failed",
        )
        alerts.route_internal_remediable_alert(
            alert_key="phase_z_baseline_missing",
            level="warn",
            title="missing",
            body=f"episode {episode}",
            storage_dir=str(pool),
            now=base + timedelta(hours=2),
        )
        alerts.resolve_internal_remediable_alert(
            alert_key="phase_z_baseline_missing",
            storage_dir=str(pool),
            now=base + timedelta(hours=2, minutes=5),
        )

    assert len(titles) == 2
    assert titles[0] != titles[1]


def test_internal_alert_router_failure_is_not_silently_suppressed(pool, monkeypatch) -> None:
    from volpred.ops import alert_remediation, alerts

    monkeypatch.setattr(
        alert_remediation,
        "remediate_internal_alert",
        lambda *args, **kwargs: {
            "reason": "enqueue_failed",
            "error": "next_tasks is unavailable",
            "escalate": False,
        },
    )
    deliveries: list[dict] = []

    def fake_send(level, title, body, **kwargs):
        deliveries.append({"level": level, "title": title, "body": body, **kwargs})
        return {"sent": True, "skipped": False, "notification_id": "router-failure"}

    monkeypatch.setattr(alerts, "send_alert", fake_send)

    result = alerts.route_internal_remediable_alert(
        alert_key="silent_fallback_new",
        level="warn",
        title="held",
        body="NEW one",
        storage_dir=str(pool),
        now=NOW,
    )

    assert result["routing_failure"] is True
    assert result["escalated"] is False
    assert deliveries[0]["level"] == "critical"
    assert "P1 任務未能建立" in deliveries[0]["body"]


def test_self_remediating_alerts_do_not_double_book(pool) -> None:
    for alert_id in ar.SELF_REMEDIATING:
        result = ar.remediate_condition(_condition(alert_id), storage_dir=str(pool), now=NOW)
        assert result["disposition"] == "self_remediating"
    assert _tasks(pool) == []


def test_owner_decision_alerts_are_declared_with_a_reason(pool) -> None:
    """Owner-facing alerts are allowed — but each is a standing admission, so justify it."""
    for alert_id, why in ar.OWNER_DECISION.items():
        result = ar.remediate_condition(_condition(alert_id), storage_dir=str(pool), now=NOW)
        assert result["disposition"] == "owner_decision"
        assert why.strip(), f"{alert_id} must document why the platform cannot self-serve"
    assert _tasks(pool) == []


def test_exemptions_are_disjoint() -> None:
    assert not (set(ar.SELF_REMEDIATING) & set(ar.OWNER_DECISION))


def test_non_breached_conditions_queue_nothing(pool) -> None:
    result = ar.remediate_condition(_condition("member_qa_stale", breached=False), storage_dir=str(pool), now=NOW)

    assert result["disposition"] == "not_breached"
    assert _tasks(pool) == []


def test_enqueue_failure_is_surfaced_in_the_email_not_swallowed(pool) -> None:
    """A bridge that fails silently reverts to nagging without anyone noticing."""
    (pool / "next_tasks.json").write_text('{"not": "a list"}\n', encoding="utf-8")
    cond = _condition("member_qa_stale")

    result = ar.remediate_condition(cond, storage_dir=str(pool), now=NOW)

    assert result["created"] is False
    assert cond["body"].startswith("## ⚠️ 自動建任務失敗")


def test_every_shipped_alert_id_is_covered_by_some_disposition() -> None:
    """Full-population gate: enumerate the real alert registry, not a sample.

    `remediate_condition` cannot leave an alert unhandled by construction (the
    default is `task`), so this asserts the weaker but load-bearing property: the
    real report's ids all resolve to a disposition, and the exemption sets do not
    name alerts that no longer exist (a stale exemption would silently re-enable
    owner-nagging for an alert that was renamed).
    """
    from volpred.ops.alerts import build_alert_condition_report

    report = build_alert_condition_report(storage_dir="storage")
    shipped = {str(c.get("id")) for c in report["conditions"]}

    assert shipped, "alert registry came back empty — the gate would vacuously pass"

    stale_exemptions = (set(ar.SELF_REMEDIATING) | set(ar.OWNER_DECISION)) - shipped
    assert not stale_exemptions, f"exemptions name alerts that no longer ship: {stale_exemptions}"

    unknown_task_types = set(ar.ALERT_TASK_TYPE) - shipped
    assert not unknown_task_types, f"ALERT_TASK_TYPE names alerts that no longer ship: {unknown_task_types}"


def test_disjoint_fingerprint_is_a_new_incident_not_a_failed_repair(pool, monkeypatch) -> None:
    """2026-07-15: three different files each tripped `silent_fallback_new` once.

    Each repair succeeded, but the coarse alert_key conflated the distinct
    findings into「同一修復連續失敗」and false-escalated to the owner. A disjoint
    fingerprint must open a fresh episode (counter reset), never escalate.
    """
    from volpred.ops import alerts

    deliveries: list[dict] = []

    def fake_send(level, title, body, **kwargs):
        deliveries.append({"title": title})
        return {"sent": True, "skipped": False, "notification_id": "n", "title": title}

    monkeypatch.setattr(alerts, "send_alert", fake_send)

    alerts.route_internal_remediable_alert(
        alert_key="silent_fallback_new",
        level="warn",
        title="blocked A",
        body="fileA",
        storage_dir=str(pool),
        now=NOW,
        fingerprint=["scripts/a.py:10"],
    )
    _finish_only_task(pool, status="succeeded", at=NOW + timedelta(minutes=20), result="marked a.py")

    # A *different* file trips the gate — not a failed repair of a.py.
    second = alerts.route_internal_remediable_alert(
        alert_key="silent_fallback_new",
        level="warn",
        title="blocked B",
        body="fileB",
        storage_dir=str(pool),
        now=NOW + timedelta(hours=2),
        fingerprint=["scripts/b.py:20"],
    )
    assert second["remediation"]["reason"] == "distinct_incident_new_episode"
    assert second["remediation"]["consecutive_remediation_failures"] == 0
    _finish_only_task(pool, status="succeeded", at=NOW + timedelta(hours=2, minutes=20), result="marked b.py")

    # A third distinct file — still must not escalate.
    third = alerts.route_internal_remediable_alert(
        alert_key="silent_fallback_new",
        level="warn",
        title="blocked C",
        body="fileC",
        storage_dir=str(pool),
        now=NOW + timedelta(hours=4),
        fingerprint=["scripts/c.py:30"],
    )
    assert third["remediation"]["consecutive_remediation_failures"] == 0
    assert deliveries == [], "distinct one-off findings must never page the owner"
    # The superseded episodes are retired, not left dangling unresolved.
    resolved = [t for t in _tasks(pool) if t.get("internal_alert_state", {}).get("resolved_at")]
    assert len(resolved) == 2


def test_same_fingerprint_surviving_repair_still_escalates(pool, monkeypatch) -> None:
    """Regression guard: a genuinely persistent finding (same file:line after a
    claimed repair) must still count as a failure and escalate at two."""
    from volpred.ops import alerts

    deliveries: list[dict] = []

    def fake_send(level, title, body, **kwargs):
        deliveries.append({"title": title, "body": body})
        return {"sent": True, "skipped": False, "notification_id": "n", "title": title}

    monkeypatch.setattr(alerts, "send_alert", fake_send)
    fp = ["scripts/stubborn.py:42"]

    alerts.route_internal_remediable_alert(
        alert_key="silent_fallback_new", level="warn", title="t1", body="b1",
        storage_dir=str(pool), now=NOW, fingerprint=fp,
    )
    _finish_only_task(pool, status="succeeded", at=NOW + timedelta(minutes=20), result="claimed fixed")
    second = alerts.route_internal_remediable_alert(
        alert_key="silent_fallback_new", level="warn", title="t2", body="b2",
        storage_dir=str(pool), now=NOW + timedelta(hours=8), fingerprint=fp,
    )
    assert second["remediation"]["consecutive_remediation_failures"] == 1
    _finish_only_task(pool, status="succeeded", at=NOW + timedelta(hours=8, minutes=20), result="claimed fixed again")
    third = alerts.route_internal_remediable_alert(
        alert_key="silent_fallback_new", level="warn", title="t3", body="b3",
        storage_dir=str(pool), now=NOW + timedelta(hours=16), fingerprint=fp,
    )
    assert third["escalated"] is True
    assert len(deliveries) == 1
    assert "已自動嘗試 2 次" in deliveries[0]["body"]
