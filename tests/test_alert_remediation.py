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


def test_cleared_ordinary_alert_closes_its_pending_task(pool) -> None:
    """A self-cleared alert must not leave a pending task for starvation lockout.

    2026-07-17: alert_telegram_reply_backlog sat pending for 24h after the
    condition cleared, then the dispatcher's starvation lockout force-fed it to
    a fire that burned a whole slot re-validating a no-op. remediate_report must
    close the task the moment the condition is present-but-not-breached.
    """
    ar.remediate_condition(_condition("host_cron_fail"), storage_dir=str(pool), now=NOW)
    assert _tasks(pool)[0]["status"] == "pending"

    later = NOW.replace(hour=5)
    report = {"conditions": [_condition("host_cron_fail", breached=False)]}
    dispositions = ar.remediate_report(report, storage_dir=str(pool), now=later)

    task = _tasks(pool)[0]
    assert task["status"] == "succeeded"
    assert task["result"] == "ordinary alert cleared before dispatch"
    assert any(d.get("disposition") == "ordinary_resolution" for d in dispositions)


def test_cleared_sweep_leaves_absent_alerts_untouched(pool) -> None:
    """Only alerts present in the report are cleared; unknown-state alerts stay."""
    ar.remediate_condition(_condition("host_cron_fail"), storage_dir=str(pool), now=NOW)

    later = NOW.replace(hour=5)
    # Report evaluates a *different* alert; host_cron_fail state is unknown here.
    report = {"conditions": [_condition("some_other_alert", breached=False)]}
    ar.remediate_report(report, storage_dir=str(pool), now=later)

    assert _tasks(pool)[0]["status"] == "pending"


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

    monkeypatch.setattr(alerts, "send_routed_alert", fake_send)

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


def test_every_shipped_alert_id_is_covered_by_some_disposition(tmp_path) -> None:
    """Full-population gate: enumerate the real alert registry, not a sample.

    `remediate_condition` cannot leave an alert unhandled by construction (the
    default is `task`), so this asserts the weaker but load-bearing property: the
    real report's ids all resolve to a disposition, and the exemption sets do not
    name alerts that no longer exist (a stale exemption would silently re-enable
    owner-nagging for an alert that was renamed).
    """
    from volpred.ops.alerts import build_alert_condition_report

    # The registry is code-defined; live operational state only changes whether
    # each condition is breached.  Point every detector at an empty, isolated
    # storage tree so this population gate cannot inherit state from an earlier
    # test or from untracked files in a developer checkout.
    report = build_alert_condition_report(
        storage_dir=str(tmp_path),
        paper_root=tmp_path / "paper",
    )
    shipped = {str(c.get("id")) for c in report["conditions"]}

    assert shipped, "alert registry came back empty — the gate would vacuously pass"

    stale_exemptions = (set(ar.SELF_REMEDIATING) | set(ar.OWNER_DECISION)) - shipped
    assert not stale_exemptions, f"exemptions name alerts that no longer ship: {stale_exemptions}"

    unknown_task_types = set(ar.ALERT_TASK_TYPE) - shipped
    assert not unknown_task_types, f"ALERT_TASK_TYPE names alerts that no longer ship: {unknown_task_types}"


# ── internal-remediable alerts: incident-store wiring (P3 rewrite) ───────────
#
# The old episode/attempt machinery (internal_alert_state parasitic in
# next_tasks rows, clean watermarks, disjoint-fingerprint episode resets) was
# plan §2.1/§3.3's root cause and is GONE.  These tests pin the replacement:
# identity + counters live in storage/ops/incidents.json; machine_self kinds
# record + notify without minting repair tasks; resolution needs sustained
# clean; the second episode escalates.


def _store(pool):
    return pool / "ops" / "incidents.json"


def _internal_condition(fingerprint=None) -> dict:
    cond = {
        "id": "silent_fallback_new",
        "breached": True,
        "level": "warn",
        "title": "silent fallback NEW",
        "body": "## 觸發條件\nsomething held\n",
    }
    if fingerprint is not None:
        cond["fingerprint"] = fingerprint
    return cond


def test_internal_breach_records_incident_without_minting_tasks(pool) -> None:
    """machine_self（§6）：記錄 + 通知，不再每次 breach 開一張 a1。"""
    from volpred.ops import incident

    first = ar.remediate_internal_alert(
        _internal_condition(), alert_key="silent_fallback_new",
        storage_dir=str(pool), now=NOW,
    )
    assert first["notify_due"] is True
    assert first["created"] is False
    assert _tasks(pool) == []

    second = ar.remediate_internal_alert(
        _internal_condition(), alert_key="silent_fallback_new",
        storage_dir=str(pool), now=NOW + timedelta(hours=1),
    )
    # notified_at is unset (transport not yet acknowledged) so notify stays due;
    # either way NO task rows appear and the SAME incident row counts up.
    assert second["created"] is False
    assert _tasks(pool) == []
    rows = incident.list_incidents(_store(pool))
    assert len(rows) == 1
    assert rows[0]["occurrence_count"] == 2
    assert rows[0]["class"] == incident.CLASS_MACHINE_SELF
    assert rows[0]["task_mode"] == incident.TASK_MODE_NONE


def test_registered_self_heal_observes_then_escalates_without_duplicate_repair_task(
    pool,
) -> None:
    """An existing actuator gets three observations, not a second repair loop."""

    from volpred.ops import incident

    condition = {
        "id": "draft_pool_low",
        "breached": True,
        "level": "warn",
        "title": "Draft pool below threshold",
        "body": "dispatcher refill owner is active",
    }
    first = ar.remediate_internal_alert(
        condition,
        alert_key="draft_pool_low",
        storage_dir=str(pool),
        now=NOW,
    )
    second = ar.remediate_internal_alert(
        condition,
        alert_key="draft_pool_low",
        storage_dir=str(pool),
        now=NOW + timedelta(hours=1),
    )
    third = ar.remediate_internal_alert(
        condition,
        alert_key="draft_pool_low",
        storage_dir=str(pool),
        now=NOW + timedelta(hours=2),
    )

    assert first["reason"] == "incident_recorded"
    assert second["reason"] == "incident_recorded"
    assert third["escalate"] is True
    assert third["reason"] == "incident_escalation_due"
    assert _tasks(pool) == []
    [row] = incident.list_incidents(_store(pool))
    assert row["class"] == incident.CLASS_ORDINARY
    assert row["task_mode"] == incident.TASK_MODE_NONE
    assert row["occurrence_count"] == 3
    assert row["state"] == incident.STATE_ESCALATED


def test_internal_fingerprints_become_instances_not_new_incidents(pool) -> None:
    """plan §3.3 inversion: fingerprint 決定 incident；file:line 實例只進陣列。

    舊制把 disjoint fingerprint 當「全新 episode + 計數歸零」——方向相反，正是
    19 張 a1 的機械成因。
    """
    from volpred.ops import incident

    ar.remediate_internal_alert(
        _internal_condition(["a.py:10"]), alert_key="silent_fallback_new",
        storage_dir=str(pool), now=NOW,
    )
    ar.remediate_internal_alert(
        _internal_condition(["b.py:99"]), alert_key="silent_fallback_new",
        storage_dir=str(pool), now=NOW + timedelta(hours=3),
    )
    rows = incident.list_incidents(_store(pool))
    assert len(rows) == 1
    keys = {i["key"] for i in rows[0]["instances"]}
    assert keys == {"a.py:10", "b.py:99"}
    assert rows[0]["occurrence_count"] == 2


def test_internal_resolution_needs_sustained_clean_then_relapse_escalates(pool) -> None:
    """G7 於 wiring 層：一次乾淨不 resolve；復發（episode 2）觸發 machine_self 升級。"""
    from volpred.ops import incident

    ar.remediate_internal_alert(
        _internal_condition(), alert_key="silent_fallback_new",
        storage_dir=str(pool), now=NOW,
    )
    one_clean = ar.resolve_internal_alert(
        alert_key="silent_fallback_new", storage_dir=str(pool), now=NOW + timedelta(hours=1)
    )
    assert one_clean["resolved"] is False  # 一次乾淨不足以 resolve

    for hours in (2, 14, 27):
        outcome = ar.resolve_internal_alert(
            alert_key="silent_fallback_new", storage_dir=str(pool),
            now=NOW + timedelta(hours=hours),
        )
    assert outcome["resolved"] is True
    row = incident.list_incidents(_store(pool))[0]
    assert row["state"] == incident.STATE_RESOLVED
    assert row["episode_count"] == 1

    relapse = ar.remediate_internal_alert(
        _internal_condition(), alert_key="silent_fallback_new",
        storage_dir=str(pool), now=NOW + timedelta(hours=40),
    )
    assert relapse["escalate"] is True
    assert relapse["episode_count"] == 2  # machine_self threshold = 2 (G5)
    assert _tasks(pool) == []  # 升級的開單由 actuator 負責，不在 route 這層


def test_wrapper_sends_first_notification_then_stays_silent(pool, monkeypatch) -> None:
    from volpred.ops import alerts, incident

    deliveries: list[dict] = []

    def fake_send(level, title, body, **kwargs):
        deliveries.append({"level": level, "title": title, "body": body})
        return {"sent": True, "skipped": False, "notification_id": f"n{len(deliveries)}"}

    monkeypatch.setattr(alerts, "send_routed_alert", fake_send)

    first = alerts.route_internal_remediable_alert(
        alert_key="silent_fallback_new", level="warn", title="held",
        body="NEW one", storage_dir=str(pool), now=NOW,
    )
    assert first["sent"] is True
    assert len(deliveries) == 1
    assert "Incident 已記錄" in deliveries[0]["body"]

    second = alerts.route_internal_remediable_alert(
        alert_key="silent_fallback_new", level="warn", title="held",
        body="NEW one", storage_dir=str(pool), now=NOW + timedelta(hours=2),
    )
    assert second["skipped"] is True
    assert second["skip_reason"] == "internal_auto_remediation"
    assert len(deliveries) == 1  # 已通知過的 episode 不再寄
    row = incident.list_incidents(_store(pool))[0]
    assert row["notified_at"] is not None
    assert _tasks(pool) == []


def test_git_push_hold_has_one_stable_edge_and_records_recurrence(
    pool,
) -> None:
    from volpred.ops import incident

    def fire(now):
        return ar.remediate_internal_alert(
            {
                "id": "git_push_backup_hold",
                "level": "warn",
                "title": "push held",
                "body": "silent fallback gate held main",
                "fingerprint": ["file-a:10", "file-b:20"],
            },
            alert_key="git_push_backup_hold",
            storage_dir=str(pool),
            now=now,
        )

    fire(NOW)
    fire(NOW + timedelta(hours=1))
    row = incident.list_incidents(_store(pool))[0]
    assert [
        transition["transition"]
        for transition in row["instance_transitions"]
    ] == ["opened"]
    assert row["instance_transitions"][0]["instance_key"] == "main_branch->push"

    for hours in (2, 14, 27):
        ar.resolve_internal_alert(
            alert_key="git_push_backup_hold",
            storage_dir=str(pool),
            now=NOW + timedelta(hours=hours),
        )
    assert incident.list_incidents(_store(pool))[0]["state"] == incident.STATE_RESOLVED

    fire(NOW + timedelta(hours=40))
    row = incident.list_incidents(_store(pool))[0]
    assert [
        transition["transition"]
        for transition in row["instance_transitions"]
    ] == ["opened", "reopened"]


def test_wrapper_escalation_opens_one_root_cause_task_and_one_mail(pool, monkeypatch) -> None:
    from volpred.ops import alerts, incident

    deliveries: list[dict] = []

    def fake_send(level, title, body, **kwargs):
        deliveries.append({"level": level, "title": title})
        return {"sent": True, "skipped": False, "notification_id": f"n{len(deliveries)}"}

    monkeypatch.setattr(alerts, "send_routed_alert", fake_send)

    def fire(now):
        return alerts.route_internal_remediable_alert(
            alert_key="silent_fallback_new", level="warn", title="held",
            body="NEW one", storage_dir=str(pool), now=now,
        )

    fire(NOW)  # episode 1 + notification
    for hours in (2, 14, 27):  # sustained clean ⇒ resolved
        ar.resolve_internal_alert(
            alert_key="silent_fallback_new", storage_dir=str(pool),
            now=NOW + timedelta(hours=hours),
        )
    result = fire(NOW + timedelta(hours=40))  # relapse ⇒ escalate (threshold 2)
    assert result["escalated"] is True

    tasks = _tasks(pool)
    root = [t for t in tasks if t.get("source") == "incident_escalation"]
    assert len(root) == 1
    assert root[0]["title"].startswith("[根因重構]")
    # 裁決（2026-07-21）：不偽裝 boss 來源、不搶 P1 —— P2 + main_thread lane；
    # 唯一性靠 escalated 狀態，不靠 priority。
    assert root[0]["priority"] == 2
    assert root[0]["source"] == "incident_escalation"
    assert root[0]["dispatch_lane"] == "main_thread"
    mails_after_escalation = len(deliveries)

    # 之後再觸發 10 次：0 張新任務、0 封新信（suppressed 但 occurrence 續計）。
    for i in range(10):
        out = fire(NOW + timedelta(hours=41 + i))
        assert out.get("escalated") in {True, False}
    assert len(_tasks(pool)) == len(tasks)
    assert len(deliveries) == mails_after_escalation
    row = incident.list_incidents(_store(pool))[0]
    assert row["state"] == incident.STATE_ESCALATED
    assert row["occurrence_count"] == 12
