"""Every breached alert must become work the platform does, not a chore for the owner.

2026-07-13: the owner replied to two consecutive `member_qa_stale` alerts with
「你要立即處理 不是只建議我」. A sweep found 24 of 27 alert bodies carried a
`## 建議行動` section addressed to a human. These tests pin the inversion: task
creation is the *default*, exemptions must be declared and justified, and the
email leads with what the system already did.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

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
