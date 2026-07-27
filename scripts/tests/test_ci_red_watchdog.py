"""CI fix-first incident watchdog regressions (boss msg 738, 2026-07-14)."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for extra in (PROJECT_ROOT / "scripts", PROJECT_ROOT / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import check_alerts  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_ci_incident_store(tmp_path, monkeypatch):
    """Keep the incident mirror on the same per-test boundary as watch state."""
    monkeypatch.setattr(
        check_alerts,
        "CI_INCIDENT_STORE",
        tmp_path / "incidents.json",
    )

BASE_URL = "https://github.com/yhlai0911/volpred-research/actions/runs"
RED1 = {
    "databaseId": 29233920234,
    "attempt": 1,
    "status": "completed",
    "conclusion": "failure",
    "url": f"{BASE_URL}/29233920234",
    "headSha": "deadbeefcafe0000000000000000000000000000",
    "createdAt": "2026-07-13T09:00:00Z",
    "startedAt": "2026-07-13T09:00:00Z",
}
RED2 = {
    **RED1,
    "databaseId": 29233920235,
    "url": f"{BASE_URL}/29233920235",
    "headSha": "feedfacecafe0000000000000000000000000000",
    "createdAt": "2026-07-13T09:10:00Z",
    "startedAt": "2026-07-13T09:10:00Z",
}
RED3 = {
    **RED1,
    "databaseId": 29233920236,
    "url": f"{BASE_URL}/29233920236",
    "headSha": "badc0ffee000000000000000000000000000000",
    "createdAt": "2026-07-13T09:20:00Z",
    "startedAt": "2026-07-13T09:20:00Z",
}
GREEN = {
    **RED1,
    "databaseId": 29234963362,
    "conclusion": "success",
    "url": f"{BASE_URL}/29234963362",
    "headSha": "0123456789abcdef0123456789abcdef01234567",
    "createdAt": "2026-07-13T09:30:00Z",
    "startedAt": "2026-07-13T09:30:00Z",
}
CANCELLED = {
    **GREEN,
    "databaseId": 29234963363,
    "conclusion": "cancelled",
    "url": f"{BASE_URL}/29234963363",
    "createdAt": "2026-07-13T09:35:00Z",
    "startedAt": "2026-07-13T09:35:00Z",
}
NOW = "2026-07-13T10:00:00+00:00"
CAUSE = "ImportError: cannot import name 'ARC_SIGNATURE_SCHEMA_VERSION'"
# A *different* failure surfacing later in the same incident (see the retry-cause test).
LATER_CAUSE = "AssertionError: [canonical-writers] FAIL: 1 unguarded"


def _commit_covered(repair: str, head: str) -> bool:
    failed_heads = {RED1["headSha"], RED2["headSha"], RED3["headSha"]}
    if head in failed_heads:
        return repair == head
    return True


def _ahead(n=0, head="localsha123", run_sha="deadbeefcafe"):
    return lambda run: {
        "probe_ok": True,
        "ahead": n,
        "head_sha": head,
        "run_sha": run_sha,
        "ci_saw_head": head == run_sha,
    }


def _harness(
    tmp_path,
    *,
    send_results=None,
    probe=None,
    pusher=None,
    summarizer=None,
    covered=None,
):
    sent = []
    detections = []
    dispatches = []
    send_results = list(send_results or [])

    def sender(level, title, body, **kwargs):
        record = {"level": level, "title": title, "body": body}
        # The msg-822 detection heads-up is warn-level and its own stream; it must
        # not consume the terminal (recovery/escalation) ``send_results`` queue nor
        # pollute the ``sent`` list existing assertions read.
        if level == "warn":
            detections.append(record)
            return {"sent": True, "notification_id": f"d-{len(detections)}"}
        sent.append(record)
        if send_results:
            result = send_results.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        return {"sent": True, "notification_id": f"n-{len(sent)}"}

    def dispatcher(task_id):
        dispatches.append(task_id)
        return {"requested": True, "task_id": task_id}

    def run(run, *, runs=None, now_iso=NOW):
        kwargs = {
            "now_iso": now_iso,
            "next_tasks_path": tmp_path / "next_tasks.json",
            "state_path": tmp_path / "ci_watch_state.json",
            "sender": sender,
            "ahead_probe": probe or _ahead(),
            "pusher": pusher or (lambda: {"pushed": True, "rc": 0, "outcome": "pushed"}),
            "failure_summarizer": summarizer or (lambda _run: CAUSE),
            "dispatcher": dispatcher,
            # A normal repair is covered by GREEN but was not already covered by
            # the failed head. Tests that need a rejection override this probe.
            "commit_covered_probe": covered or _commit_covered,
        }
        if runs is not None:
            return check_alerts._handle_ci_runs(runs, **kwargs)
        return check_alerts._handle_ci_run(run, **kwargs)

    run.detections = detections
    return run, sent, dispatches


def _tasks(tmp_path):
    return json.loads((tmp_path / "next_tasks.json").read_text(encoding="utf-8"))


def _state(tmp_path):
    return json.loads((tmp_path / "ci_watch_state.json").read_text(encoding="utf-8"))


def _complete_repair_task(tmp_path, *, commit="abc1234", cause=CAUSE):
    tasks = _tasks(tmp_path)
    tasks[0]["status"] = "succeeded"
    tasks[0]["result"] = f"root_cause={cause}; repair_commit={commit}"
    (tmp_path / "next_tasks.json").write_text(json.dumps(tasks), encoding="utf-8")


def test_first_red_starts_repair_without_boss_notification(tmp_path):
    run, sent, dispatches = _harness(tmp_path)

    summary = run(RED1)

    assert summary["task_added"] is True
    assert summary["alert_sent"] is False
    assert sent == []
    assert dispatches == ["ci-red-29233920234"]
    task = _tasks(tmp_path)[0]
    # 2026-07-21 dispatch-lanes absorb: the builder declares P1, but the append
    # now rides the single gateway whose admission clamp caps machine-source P1
    # at P2. Timeliness is carried by dispatch_preempt + the watcher's
    # request_fire loop (asserted below / in dispatches), not the digit.
    assert task["priority"] == 2
    assert task["priority_capped_from"] == 1
    assert task["task_type"] == "platform_ops"
    assert task["dispatch_lane"] == "agent"
    assert task["dispatch_preempt"] is True
    assert "log-failed" in task["description"]
    assert "不得自行寄 email/Telegram" in task["description"]
    assert CAUSE in task["description"]
    incident = _state(tmp_path)["active_incident"]
    assert incident["phase"] == "remediating"
    assert incident["failure_cycles"] == 1


def test_repair_task_and_fire_request_exist_before_slow_push_path(tmp_path):
    dispatches = []

    def pusher():
        assert (tmp_path / "next_tasks.json").exists()
        assert dispatches == ["ci-red-29233920234"]
        persisted = _state(tmp_path)["active_incident"]
        assert persisted["push_intent"]["head_sha"] == "localsha123"
        return {"pushed": True, "rc": 0, "outcome": "pushed"}

    sent = []

    def sender(level, title, body, **kwargs):
        if level == "warn":  # detection heads-up — not a terminal notice
            return {"sent": True}
        sent.append(body)
        return {"sent": True}

    summary = check_alerts._handle_ci_run(
        RED1,
        now_iso=NOW,
        next_tasks_path=tmp_path / "next_tasks.json",
        state_path=tmp_path / "ci_watch_state.json",
        sender=sender,
        ahead_probe=_ahead(1),
        pusher=pusher,
        failure_summarizer=lambda _run: CAUSE,
        dispatcher=lambda task_id: (
            dispatches.append(task_id) or {"requested": True, "task_id": task_id}
        ),
        commit_covered_probe=lambda _repair, _green: True,
    )

    assert summary["task_added"] is True
    assert sent == []


def test_same_red_is_idempotent_but_late_local_fix_still_pushes(tmp_path):
    pushes = []

    def pusher():
        pushes.append(True)
        return {"pushed": True, "rc": 0, "outcome": "pushed"}

    run, sent, dispatches = _harness(tmp_path, probe=_ahead(1), pusher=pusher)
    run(RED1)
    summary = run(RED1)

    assert pushes == [True, True]
    assert len(_tasks(tmp_path)) == 1
    assert dispatches == ["ci-red-29233920234", "ci-red-29233920234"]
    assert sent == []
    assert summary["failure_cycles"] == 1
    assert _state(tmp_path)["active_incident"]["remediation_checks"] == 1


def test_red_then_green_sends_exactly_one_verified_notice(tmp_path):
    run, sent, _dispatches = _harness(tmp_path, probe=_ahead(1))
    run(RED1)
    _complete_repair_task(tmp_path)

    summary = run(GREEN)
    run(GREEN)

    assert summary["notification_kind"] == "recovery"
    assert summary["notification_delivered"] is True
    assert len(sent) == 1
    assert sent[0]["level"] == "info"
    assert "已修復並驗證" in sent[0]["title"]
    assert CAUSE in sent[0]["body"]
    assert str(GREEN["databaseId"]) in sent[0]["body"]
    assert GREEN["url"] in sent[0]["body"]
    assert GREEN["headSha"][:12] in sent[0]["body"]
    state = _state(tmp_path)
    assert "active_incident" not in state
    assert state["last_closed_incident"]["phase"] == "recovered"
    assert _tasks(tmp_path)[0]["status"] == "succeeded"


def test_retry_task_carries_the_new_runs_cause_not_the_first_failures(tmp_path):
    """One incident spans many red runs, and each can fail for a different reason.

    2026-07-19: incident ``ci-red-29651115228`` stayed red across 7 runs. Run 1 failed
    on an ImportError; by run 7 that was long fixed and the tree was failing the
    canonical-writers audit instead. Because ``root_cause`` was computed once per
    *incident*, all three repair tasks quoted run 1's ImportError — the live root cause
    never appeared in any task description, and the fixer was sent chasing a ghost.
    """
    causes = {RED1["databaseId"]: CAUSE, RED2["databaseId"]: LATER_CAUSE}
    calls = []

    def summarizer(run_payload):
        calls.append(run_payload["databaseId"])
        return causes[run_payload["databaseId"]]

    run, _sent, _dispatches = _harness(tmp_path, summarizer=summarizer)
    run(RED1)
    run(RED1)  # same run re-polled: must not re-fetch the log
    _complete_repair_task(tmp_path)
    run(RED2)

    assert calls == [RED1["databaseId"], RED2["databaseId"]]
    incident = _state(tmp_path)["active_incident"]
    assert incident["root_cause"] == LATER_CAUSE
    assert incident["root_cause_run_key"] == check_alerts._ci_run_key(RED2)
    retry_task = {task["id"]: task for task in _tasks(tmp_path)}[
        check_alerts._ci_task_id(RED2)
    ]
    assert LATER_CAUSE in retry_task["description"]
    assert CAUSE not in retry_task["description"]


def test_verified_watcher_push_head_is_not_automatically_called_repair_commit(tmp_path):
    run, sent, _dispatches = _harness(tmp_path, probe=_ahead(1))
    run(RED1)

    run(GREEN)

    # The green closes the incident (it carries the failing commit in its
    # history), but no specific commit may be named as the repair: a shared-main
    # HEAD can contain unrelated work.
    incident = _state(tmp_path)["last_closed_incident"]
    assert incident["last_verified_push_head"] == "localsha123"
    assert "repair_commit" not in incident
    assert incident["repair_commit_source"] == "green_descendant"
    assert "localsha123" not in sent[0]["body"]


def test_green_descendant_closes_incident_when_repair_task_never_reports(tmp_path):
    """A fix landing outside the repair task must still close the incident.

    boss msg 749/758 (2026-07-14): the PHASE-Z refactor fixed main, the repair
    task stayed pending, and the incident could only close through a repair-task
    receipt — so it escalated against an already-green main once an hour.
    """
    run, sent, _dispatches = _harness(tmp_path)
    run(RED1)
    run(RED2)
    assert _tasks(tmp_path)[0]["status"] == "pending"

    summary = run(GREEN, now_iso="2026-07-13T11:00:00+00:00")

    assert summary["reason"] == "recovery_notified"
    state = _state(tmp_path)
    assert "active_incident" not in state
    assert state["last_closed_incident"]["phase"] == "recovered"
    # Recovery, not another CRITICAL escalation at an already-green main.
    assert [msg["level"] for msg in sent] == ["info"]
    # The repair task never ran — closing it as "succeeded" would be a lie.
    assert _tasks(tmp_path)[0]["status"] == "closed_no_action"


def test_green_that_does_not_descend_from_every_failure_stays_open(tmp_path):
    """Fail closed: an unprovable ancestry is not evidence of recovery."""
    run, sent, _dispatches = _harness(tmp_path)
    run(RED1)

    summary = check_alerts._handle_ci_run(
        GREEN,
        now_iso=NOW,
        next_tasks_path=tmp_path / "next_tasks.json",
        state_path=tmp_path / "ci_watch_state.json",
        sender=lambda level, title, body, **kwargs: {"sent": True},
        ahead_probe=_ahead(),
        pusher=lambda: {"pushed": True, "outcome": "pushed"},
        failure_summarizer=lambda _run: CAUSE,
        dispatcher=lambda _task_id: {"requested": True},
        commit_covered_probe=lambda _a, _b: False,
    )

    assert summary["reason"] == "green_without_repair_evidence"
    assert _state(tmp_path)["active_incident"]["phase"] == "verifying"


def test_same_sha_green_without_repair_evidence_is_not_misreported(tmp_path):
    run, sent, _dispatches = _harness(tmp_path)
    same_sha_green = {**GREEN, "headSha": RED1["headSha"]}
    run(RED1)

    summary = run(same_sha_green)

    assert sent == []
    assert summary["reason"] == "green_without_repair_evidence"
    incident = _state(tmp_path)["active_incident"]
    assert incident["phase"] == "verifying"
    assert "repair_commit" not in incident
    assert _tasks(tmp_path)[0]["status"] == "pending"


def test_same_sha_green_is_rejected_even_if_task_claims_failed_head_as_repair(tmp_path):
    run, sent, _dispatches = _harness(tmp_path)
    run(RED1)
    tasks = _tasks(tmp_path)
    tasks[0]["status"] = "succeeded"
    tasks[0]["result"] = f"root_cause=flake; repair_commit={RED1['headSha']}"
    (tmp_path / "next_tasks.json").write_text(json.dumps(tasks), encoding="utf-8")

    summary = run({**GREEN, "headSha": RED1["headSha"]})

    assert sent == []
    assert summary["reason"] == "green_head_already_observed_failing"
    assert _state(tmp_path)["active_incident"]["phase"] == "verifying"


def test_repair_commit_that_later_failed_cannot_be_relabelled_fixed_by_rerun(tmp_path):
    repair_head = RED2["headSha"]
    run, sent, _dispatches = _harness(tmp_path)
    run(RED1)
    _complete_repair_task(tmp_path, commit=repair_head)
    run(RED2)

    summary = run({**GREEN, "headSha": repair_head})

    assert sent == []
    assert summary["reason"] == "green_head_already_observed_failing"
    incident = _state(tmp_path)["active_incident"]
    assert incident["latest_failure"]["run_id"] == RED2["databaseId"]


def test_confirmed_task_root_cause_is_used_in_recovery_notice(tmp_path):
    run, sent, _dispatches = _harness(tmp_path)
    run(RED1)
    tasks = _tasks(tmp_path)
    tasks[0]["status"] = "succeeded"
    tasks[0]["result"] = "root_cause=confirmed fixture race; repair_commit=abc1234"
    (tmp_path / "next_tasks.json").write_text(json.dumps(tasks), encoding="utf-8")

    run(GREEN)

    assert len(sent) == 1
    assert "confirmed fixture race" in sent[0]["body"]
    assert CAUSE not in sent[0]["body"]


def test_late_task_commit_promotes_stored_green_even_after_neutral_run(tmp_path):
    """A green whose ancestry cannot be proven still promotes on a late receipt.

    Ancestry is unprovable here (shallow clone / ungraftable head), so the green
    cannot self-verify as a descendant and has to wait for the repair task.
    """
    sent = []

    def sender(level, title, body, **kwargs):
        if level == "warn":  # detection heads-up — not a terminal notice
            return {"sent": True, "notification_id": "d-inline"}
        sent.append({"level": level, "title": title, "body": body})
        return {"sent": True, "notification_id": f"n-{len(sent)}"}

    # Only the repair commit's coverage of the green head is provable.
    def probe(commit, head):
        return commit == "abc1234" and head == GREEN["headSha"]

    def run(run_payload):
        return check_alerts._handle_ci_run(
            run_payload,
            now_iso=NOW,
            next_tasks_path=tmp_path / "next_tasks.json",
            state_path=tmp_path / "ci_watch_state.json",
            sender=sender,
            ahead_probe=_ahead(),
            pusher=lambda: {"pushed": True, "rc": 0, "outcome": "pushed"},
            failure_summarizer=lambda _run: CAUSE,
            dispatcher=lambda task_id: {"requested": True, "task_id": task_id},
            commit_covered_probe=probe,
        )

    run(RED1)
    run(GREEN)
    assert sent == []
    tasks = _tasks(tmp_path)
    tasks[0]["status"] = "succeeded"
    tasks[0]["result"] = "root_cause=flake; repair_commit=abc1234"
    (tmp_path / "next_tasks.json").write_text(json.dumps(tasks), encoding="utf-8")

    summary = run(CANCELLED)

    assert summary["notification_kind"] == "recovery"
    assert len(sent) == 1
    assert "abc1234" in sent[0]["body"]
    assert str(GREEN["databaseId"]) in sent[0]["body"]


def test_second_red_stays_silent_and_third_red_escalates_once(tmp_path):
    run, sent, _dispatches = _harness(tmp_path)
    run(RED1)
    run(RED2)
    assert sent == []

    summary = run(RED3)
    run(RED3)

    assert summary["failure_cycles"] == 3
    assert len(sent) == 1
    assert sent[0]["level"] == "critical"
    assert "ci_failed_more_than_two_cycles: 3" in sent[0]["body"]


def test_rerun_attempt_is_a_distinct_cycle_but_repeat_attempt_is_not(tmp_path):
    run, sent, _dispatches = _harness(tmp_path)
    rerun = {
        **RED1,
        "attempt": 2,
        "createdAt": "2026-07-13T09:15:00Z",
        "startedAt": "2026-07-13T09:15:00Z",
    }
    run(RED1)

    first = run(rerun)
    repeat = run(rerun)

    assert first["failure_cycles"] == 2
    assert repeat["failure_cycles"] == 2
    assert sent == []


def test_rerun_green_waits_for_complete_attempt_history(tmp_path):
    run, sent, _dispatches = _harness(tmp_path)
    run(RED1)
    _complete_repair_task(tmp_path)
    rerun_green = {
        **GREEN,
        "attempt": 2,
        "attemptHistoryComplete": False,
    }

    blocked = run(rerun_green)
    recovered = run({**rerun_green, "attemptHistoryComplete": True})

    assert blocked["reason"] == "rerun_attempt_history_incomplete"
    assert recovered["notification_kind"] == "recovery"
    assert len(sent) == 1


def test_completed_attempt_expansion_can_promote_stored_green_behind_newer_neutral(tmp_path):
    run, sent, _dispatches = _harness(tmp_path)
    run(RED1)
    _complete_repair_task(tmp_path)
    rerun_green = {
        **GREEN,
        "attempt": 2,
        "attemptHistoryComplete": False,
    }
    run(rerun_green)
    prior_neutral = {
        **GREEN,
        "attempt": 1,
        "conclusion": "cancelled",
        "attemptHistoryComplete": True,
        "createdAt": "2026-07-13T09:25:00Z",
        "startedAt": "2026-07-13T09:25:00Z",
    }

    summary = run(
        None,
        runs=[
            CANCELLED,
            {**rerun_green, "attemptHistoryComplete": True},
            prior_neutral,
        ],
    )

    assert summary["notification_kind"] == "recovery"
    assert len(sent) == 1
    assert str(rerun_green["databaseId"]) in sent[0]["body"]


def test_late_hidden_attempt_is_counted_without_regressing_latest_failure(tmp_path):
    run, sent, _dispatches = _harness(tmp_path)
    run(RED1)
    run(RED3)  # attempt/run RED2 was temporarily absent from provider output

    summary = run(None, runs=[RED1, RED2, RED3])

    assert summary["processed_run_ids"] == [RED2["databaseId"]]
    assert summary["failure_cycles"] == 3
    assert len(sent) == 1
    state = _state(tmp_path)
    incident = state["active_incident"]
    assert incident["latest_failure"]["run_id"] == RED3["databaseId"]
    assert "29233920235:1" in state["processed_run_keys"]


def test_late_hidden_failure_before_closed_green_does_not_reopen_incident(tmp_path):
    run, sent, _dispatches = _harness(tmp_path, probe=_ahead(1))
    run(RED1)
    _complete_repair_task(tmp_path)
    run(GREEN)

    summary = run(None, runs=[RED1, RED2, GREEN])

    assert summary["processed_run_ids"] == [RED2["databaseId"]]
    assert summary["reason"] == "late_failure_precedes_closed_green"
    assert len(sent) == 1
    state = _state(tmp_path)
    assert "active_incident" not in state
    assert "29233920235:1" in state["last_closed_incident"]["late_discovered_failure_run_keys"]


def test_late_hidden_failure_before_healthy_success_does_not_open_incident(tmp_path):
    run, sent, dispatches = _harness(tmp_path)
    prior = {
        **GREEN,
        "databaseId": 29230000000,
        "createdAt": "2026-07-13T08:00:00Z",
        "startedAt": "2026-07-13T08:00:00Z",
    }
    run(prior)
    run(GREEN)

    summary = run(None, runs=[prior, RED1, GREEN])

    assert summary["processed_run_ids"] == [RED1["databaseId"]]
    assert summary["reason"] == "late_failure_precedes_completed_green"
    assert sent == [] and dispatches == []
    state = _state(tmp_path)
    assert "active_incident" not in state
    assert "29233920234:1" in state["late_discovered_failure_run_keys"]


def test_late_success_before_latest_failure_cannot_create_recovery(tmp_path):
    run, sent, _dispatches = _harness(tmp_path)
    prior = {
        **GREEN,
        "databaseId": 29230000000,
        "createdAt": "2026-07-13T08:00:00Z",
        "startedAt": "2026-07-13T08:00:00Z",
    }
    late_green = {
        **GREEN,
        "databaseId": 29233920235,
        "createdAt": "2026-07-13T09:10:00Z",
        "startedAt": "2026-07-13T09:10:00Z",
    }
    run(prior)
    run(RED3)
    _complete_repair_task(tmp_path)

    summary = run(None, runs=[prior, late_green, RED3])

    assert summary["processed_run_ids"] == [late_green["databaseId"]]
    assert summary["reason"] == "late_success_precedes_latest_failure"
    assert sent == []
    assert "recovery_candidate" not in _state(tmp_path)["active_incident"]


def test_batch_red_red_red_green_only_sends_recovery(tmp_path):
    run, sent, _dispatches = _harness(tmp_path)
    run(RED1)
    _complete_repair_task(tmp_path)

    summary = run(None, runs=[GREEN, RED3, RED1, RED2])

    assert summary["processed_run_ids"] == [
        RED2["databaseId"], RED3["databaseId"], GREEN["databaseId"]
    ]
    assert len(sent) == 1
    assert sent[0]["level"] == "info"
    assert str(GREEN["databaseId"]) in sent[0]["body"]
    assert any(task["status"] == "closed_no_action" for task in _tasks(tmp_path))


def test_newer_neutral_run_does_not_mask_verified_recovery(tmp_path):
    run, sent, _dispatches = _harness(tmp_path)
    run(RED1)
    _complete_repair_task(tmp_path)

    summary = run(None, runs=[CANCELLED, GREEN, RED1])

    assert summary["notification_kind"] == "recovery"
    assert len(sent) == 1
    assert sent[0]["level"] == "info"
    assert str(GREEN["databaseId"]) in sent[0]["body"]
    assert str(CANCELLED["databaseId"]) not in sent[0]["body"]
    assert _tasks(tmp_path)[0]["status"] == "succeeded"


def test_newer_neutral_run_does_not_mask_three_cycle_escalation(tmp_path):
    run, sent, _dispatches = _harness(tmp_path)
    prior = {
        **GREEN,
        "databaseId": 29230000000,
        "createdAt": "2026-07-13T08:00:00Z",
        "startedAt": "2026-07-13T08:00:00Z",
    }
    run(prior)

    summary = run(None, runs=[CANCELLED, RED3, RED2, RED1, prior])
    run(None, runs=[CANCELLED, RED3, RED2, RED1, prior])

    assert summary["notification_kind"] == "escalation"
    assert len(sent) == 1
    assert sent[0]["level"] == "critical"
    assert "ci_failed_more_than_two_cycles: 3" in sent[0]["body"]


def test_newer_in_progress_run_defers_green_notification(tmp_path):
    run, sent, _dispatches = _harness(tmp_path)
    run(RED1)
    _complete_repair_task(tmp_path)
    in_progress = {
        **GREEN,
        "databaseId": 29234963399,
        "status": "in_progress",
        "conclusion": "",
        "createdAt": "2026-07-13T09:40:00Z",
        "startedAt": "2026-07-13T09:40:00Z",
    }

    summary = run(None, runs=[in_progress, GREEN, RED1])

    assert sent == []
    assert summary["reason"] == "newer_run_in_progress"
    assert _state(tmp_path)["active_incident"]["phase"] == "recovery_pending"


def test_recovery_notification_failure_retries_until_delivered(tmp_path):
    run, sent, _dispatches = _harness(
        tmp_path,
        send_results=[{"sent": False}, {"sent": True, "notification_id": "n-ok"}],
    )
    run(RED1)
    _complete_repair_task(tmp_path)

    first = run(GREEN)
    second = run(GREEN)
    run(GREEN)

    assert first["reason"] == "recovery_notification_pending"
    assert second["notification_delivered"] is True
    assert len(sent) == 2  # delivery attempts; only the second actually sent
    assert "active_incident" not in _state(tmp_path)


def test_github_poll_outage_retries_verified_recovery_notification(tmp_path):
    run, sent, _dispatches = _harness(
        tmp_path,
        send_results=[{"sent": False}],
    )
    run(RED1)
    _complete_repair_task(tmp_path)
    first = run(GREEN)
    assert first["reason"] == "recovery_notification_pending"

    outage_sends = []
    summary = check_alerts._handle_ci_unavailable(
        now_iso="2026-07-13T11:00:00+00:00",
        next_tasks_path=tmp_path / "next_tasks.json",
        state_path=tmp_path / "ci_watch_state.json",
        sender=lambda level, title, body, **_kwargs: (
            outage_sends.append({"level": level, "title": title, "body": body})
            or {"sent": True, "notification_id": "n-outage-retry"}
        ),
        dispatcher=lambda _task_id: {"requested": True},
    )

    assert summary["ci_provider_available"] is False
    assert summary["notification_kind"] == "recovery"
    assert summary["notification_delivered"] is True
    assert len(sent) == 1
    assert len(outage_sends) == 1
    assert outage_sends[0]["level"] == "info"
    assert "active_incident" not in _state(tmp_path)


def test_dedup_skip_is_accepted_after_send_before_state_save_crash(tmp_path):
    run, sent, _dispatches = _harness(
        tmp_path,
        send_results=[{
            "sent": False,
            "skipped": True,
            "skip_reason": "dedup_24h",
            "notification_id": "already-sent",
        }],
    )
    run(RED1)
    _complete_repair_task(tmp_path)

    summary = run(GREEN)

    assert summary["notification_delivered"] is True
    assert len(sent) == 1
    assert "active_incident" not in _state(tmp_path)


def test_cleanup_then_process_crash_is_idempotent_on_dedup_retry(tmp_path):
    run, sent, _dispatches = _harness(
        tmp_path,
        send_results=[
            SystemExit("simulated crash after external delivery"),
            {"sent": False, "skipped": True, "skip_reason": "dedup_24h"},
        ],
    )
    run(RED1)
    _complete_repair_task(tmp_path)
    run(RED2)  # creates a fresh pending retry task inside the same incident

    with pytest.raises(SystemExit):
        run(GREEN)
    retry_task_id = check_alerts._ci_task_id(RED2)
    assert {task["id"]: task["status"] for task in _tasks(tmp_path)}[retry_task_id] == (
        "closed_no_action"
    )

    summary = run(GREEN)

    assert summary["notification_delivered"] is True
    assert len(sent) == 2
    closed = _state(tmp_path)["last_closed_incident"]
    assert retry_task_id in closed["retired_pending_task_ids"]
    assert closed["repair_task_statuses"][retry_task_id] == "closed_no_action"


def test_malformed_none_sender_result_does_not_close_incident(tmp_path):
    run, sent, _dispatches = _harness(
        tmp_path,
        send_results=[None],
    )
    run(RED1)
    _complete_repair_task(tmp_path)

    summary = run(GREEN)

    assert len(sent) == 1
    assert summary["notification_delivered"] is False
    assert summary["reason"] == "recovery_notification_pending"
    assert _state(tmp_path)["active_incident"]["phase"] == "recovery_notification_pending"


def test_cancelled_run_does_not_resolve_incident(tmp_path):
    run, sent, _dispatches = _harness(tmp_path)
    run(RED1)

    summary = run(CANCELLED)

    assert sent == []
    assert summary["reason"] == "neutral_run"
    assert _state(tmp_path)["active_incident"]["phase"] == "remediating"


def test_failed_repair_task_escalates_immediately(tmp_path):
    run, sent, _dispatches = _harness(tmp_path)
    run(RED1)
    tasks = _tasks(tmp_path)
    tasks[0]["status"] = "failed"
    (tmp_path / "next_tasks.json").write_text(json.dumps(tasks), encoding="utf-8")

    summary = run(RED1)

    assert summary["notification_kind"] == "escalation"
    assert len(sent) == 1
    assert sent[0]["level"] == "critical"
    assert "repair_task_terminal_failure" in sent[0]["body"]


def test_stalled_pending_repair_escalates_after_more_than_two_polls(tmp_path):
    run, sent, dispatches = _harness(tmp_path)

    run(RED1, now_iso="2026-07-13T10:00:00+00:00")
    run(RED1, now_iso="2026-07-13T11:00:00+00:00")
    assert sent == []
    summary = run(RED1, now_iso="2026-07-13T12:00:00+00:00")

    assert summary["notification_kind"] == "escalation"
    assert len(sent) == 1
    assert "remediation_stalled_more_than_two_checks: 3" in sent[0]["body"]
    assert dispatches == ["ci-red-29233920234"] * 3


def test_github_poll_outage_still_advances_active_incident_timeout(tmp_path):
    run, sent, dispatches = _harness(tmp_path)
    run(RED1, now_iso="2026-07-13T10:00:00+00:00")

    kwargs = {
        "next_tasks_path": tmp_path / "next_tasks.json",
        "state_path": tmp_path / "ci_watch_state.json",
        "sender": lambda level, title, body, **_kw: (
            sent.append({"level": level, "title": title, "body": body})
            or {"sent": True}
        ),
        "dispatcher": lambda task_id: (
            dispatches.append(task_id) or {"requested": True, "task_id": task_id}
        ),
    }
    check_alerts._handle_ci_unavailable(
        now_iso="2026-07-13T11:00:00+00:00",
        **kwargs,
    )
    summary = check_alerts._handle_ci_unavailable(
        now_iso="2026-07-13T12:00:00+00:00",
        **kwargs,
    )

    assert summary["ci_provider_available"] is False
    assert summary["notification_kind"] == "escalation"
    assert len(sent) == 1
    assert "remediation_stalled_more_than_two_checks: 3" in sent[0]["body"]
    assert dispatches == ["ci-red-29233920234"] * 3


def test_task_append_hard_failure_escalates_once(tmp_path, monkeypatch):
    def fail_append(_task, _path):
        raise OSError("disk unavailable")

    monkeypatch.setattr(check_alerts, "_append_next_task_record", fail_append)
    run, sent, _dispatches = _harness(tmp_path)

    summary = run(RED1)
    run(RED1)

    assert summary["notification_kind"] == "escalation"
    assert len(sent) == 1
    assert sent[0]["level"] == "critical"
    assert "append_failed: OSError: disk unavailable" in sent[0]["body"]


def test_existing_pending_task_is_adopted_without_duplicate_or_alert(tmp_path):
    task = check_alerts._build_ci_repair_task(RED1, now_iso=NOW, failure_cause=CAUSE)
    (tmp_path / "next_tasks.json").write_text(json.dumps([task]), encoding="utf-8")
    run, sent, dispatches = _harness(tmp_path)

    summary = run(RED1)

    assert summary["task_added"] is False
    assert len(_tasks(tmp_path)) == 1
    assert sent == []
    assert dispatches == [task["id"]]


def test_known_repair_commit_must_be_covered_by_green_head(tmp_path):
    run, sent, _dispatches = _harness(tmp_path)
    run(RED1)
    _complete_repair_task(tmp_path, commit="abc1234")
    # Build a second harness over the same files with an ancestry rejection.
    sent2 = []

    def sender(level, title, body, **kwargs):
        sent2.append(body)
        return {"sent": True}

    summary = check_alerts._handle_ci_run(
        GREEN,
        now_iso=NOW,
        next_tasks_path=tmp_path / "next_tasks.json",
        state_path=tmp_path / "ci_watch_state.json",
        sender=sender,
        ahead_probe=_ahead(),
        pusher=lambda: {"pushed": True, "outcome": "pushed"},
        failure_summarizer=lambda _run: CAUSE,
        dispatcher=lambda _task_id: {"requested": True},
        commit_covered_probe=lambda _repair, _green: False,
    )

    assert sent == [] and sent2 == []
    assert summary["reason"] == "green_does_not_cover_repair_commit"
    assert _state(tmp_path)["active_incident"]["phase"] == "verifying"


def test_push_held_by_pre_push_gate_is_not_bypassed_or_notified(tmp_path):
    pushes = []

    def pusher():
        pushes.append(True)
        return {"pushed": False, "rc": 120, "outcome": "held"}

    run, sent, _dispatches = _harness(tmp_path, probe=_ahead(2), pusher=pusher)
    summary = run(RED1)

    assert pushes == [True]
    assert summary["push"]["outcome"] == "held"
    assert sent == []


def test_no_push_when_ci_already_tested_local_head(tmp_path):
    pushes = []
    same_sha = RED1["headSha"]
    run, sent, _dispatches = _harness(
        tmp_path,
        probe=_ahead(1, head=same_sha, run_sha=same_sha),
        pusher=lambda: pushes.append(True),
    )

    summary = run(RED1)

    assert pushes == []
    assert summary["push"]["reason"] == "ci_already_tested_head"
    assert sent == []


def test_push_wrapper_rc_zero_requires_origin_postcondition(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[0] == "bash":
            assert kwargs["env"]["VOLPRED_SUPPRESS_PUSH_ALERTS"] == "1"
            return subprocess.CompletedProcess(cmd, 0, stdout="SUPPRESSED", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="1\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = check_alerts._ci_push_local_commits()

    assert result["pushed"] is False
    assert result["outcome"] == "push_unverified"
    assert len(calls) == 2


def test_recent_run_provider_keeps_history_and_in_progress(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps([RED1, {**GREEN, "status": "in_progress", "conclusion": ""}]),
            stderr="",
        )

    monkeypatch.setattr(check_alerts, "_gh_bin", lambda: "/usr/bin/gh")
    monkeypatch.setattr(subprocess, "run", fake_run)

    runs = check_alerts._ci_recent_runs(limit=7)

    assert len(runs) == 2
    assert "--status" not in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--limit") + 1] == "7"
    fields = captured["cmd"][captured["cmd"].index("--json") + 1]
    assert "attempt" in fields and "status" in fields and "startedAt" in fields


def test_historical_attempt_provider_expands_attempts_hidden_by_run_list(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        attempt = int(cmd[cmd.index("--attempt") + 1])
        payload = {
            **RED1,
            "attempt": attempt,
            "conclusion": "failure" if attempt == 1 else "timed_out",
            "startedAt": f"2026-07-13T09:0{attempt}:00Z",
        }
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    latest = {**RED1, "attempt": 3}
    attempts = check_alerts._ci_historical_attempts(
        "/usr/bin/gh",
        [latest],
    )

    assert [item["attempt"] for item in attempts] == [1, 2]
    assert all("--attempt" in cmd for cmd in calls)
    assert latest["attemptHistoryComplete"] is True
    assert all(item["attemptHistoryComplete"] is True for item in attempts)


def test_historical_attempt_fetch_failure_marks_latest_rerun_incomplete(monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="temporary API failure")

    monkeypatch.setattr(subprocess, "run", fake_run)
    latest = {**GREEN, "attempt": 2}

    attempts = check_alerts._ci_historical_attempts("/usr/bin/gh", [latest])

    assert attempts == []
    assert latest["attemptHistoryComplete"] is False


def test_large_attempt_history_rotates_bounded_windows_until_complete():
    requests = [(999, attempt) for attempt in range(1, 96)]

    windows = [
        check_alerts._ci_attempt_request_window(requests, limit=40, cycle=cycle)
        for cycle in range(3)
    ]

    assert [len(window) for window in windows] == [40, 40, 15]
    assert set().union(*(set(window) for window in windows)) == set(requests)
    state = {"processed_run_keys": [f"999:{attempt}" for attempt in range(1, 96)]}
    assert check_alerts._ci_attempt_history_complete(
        state,
        {"databaseId": 999, "attempt": 96, "attemptHistoryComplete": False},
    )


def test_failure_summary_reads_the_exact_attempt(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="E   AssertionError: boom\n", stderr="")

    monkeypatch.setattr(check_alerts, "_gh_bin", lambda: "/usr/bin/gh")
    monkeypatch.setattr(subprocess, "run", fake_run)

    cause = check_alerts._ci_failure_summary({**RED1, "attempt": 2})

    assert cause == "E AssertionError: boom"
    assert captured["cmd"][captured["cmd"].index("--attempt") + 1] == "2"


def test_ci_poll_has_a_dedicated_small_entrypoint():
    source = (PROJECT_ROOT / "scripts" / "check_alerts.py").read_text(encoding="utf-8")
    main_source = source[source.index("def main()") :]
    ci_source = source[source.index("def ci_watch_main()") :]

    assert "ci_watch = _auto_remediate_ci_red()" not in main_source.split(
        "def ci_watch_main()"
    )[0]
    assert "result = _auto_remediate_ci_red()" in ci_source


def test_failure_cause_extractor_prefers_specific_error():
    log = """
job\tstep\t2026-07-13T09:00:00Z\tError: Process completed with exit code 1.
job\tstep\t2026-07-13T09:00:00Z\tE   AssertionError: expected green, got red
job\tstep\t2026-07-13T09:00:00Z\tFAILED tests/test_ci.py::test_green
"""
    assert check_alerts._ci_pick_failure_cause(log) == (
        "E AssertionError: expected green, got red"
    )


# ---------------------------------------------------------------------------
# Detection notice (boss msg 822, 2026-07-18): CI going red must push one
# plain-language, boss-facing heads-up the moment it is detected — not stay
# silent until verified recovery / exhaustion. First line = plain cause; the
# original run link/id/attempt/head_sha follow; one notice per incident.
# ---------------------------------------------------------------------------
DETECTION_FIXTURE_LOG = """
job\tstep\t2026-07-13T09:00:00Z\tError: Process completed with exit code 1.
job\tstep\t2026-07-13T09:00:00Z\tE   AssertionError: QLIKE regression exceeded tolerance
job\tstep\t2026-07-13T09:00:00Z\tFAILED tests/test_metrics.py::test_qlike
"""


def test_red_detection_notice_leads_with_plain_cause(tmp_path):
    cause = check_alerts._ci_pick_failure_cause(DETECTION_FIXTURE_LOG)
    run, sent, _dispatches = _harness(tmp_path, summarizer=lambda _run: cause)

    summary = run(RED1)

    # Fix-first: no terminal recovery/escalation notice yet, but a detection
    # heads-up must fire immediately.
    assert sent == []
    assert len(run.detections) == 1
    notice = run.detections[0]
    assert notice["level"] == "warn"  # heads-up, not a critical call for help
    assert "紅燈偵測" in notice["title"]
    first_line = notice["body"].splitlines()[0]
    assert first_line == f"白話原因：{cause}"
    assert "AssertionError" in first_line  # the plain cause leads the body
    # Original run link/id/attempt/head_sha preserved for anyone wanting detail.
    assert RED1["url"] in notice["body"]
    assert str(RED1["databaseId"]) in notice["body"]
    assert RED1["headSha"][:12] in notice["body"]
    assert summary["detection"]["reason"] == "detection_notified"
    notices = _state(tmp_path)["active_incident"]["notifications"]["detection"]
    assert notices["status"] == "sent"


def test_detection_notice_is_sent_once_per_incident(tmp_path):
    run, sent, _dispatches = _harness(tmp_path)

    run(RED1)
    summary = run(RED1)

    assert len(run.detections) == 1  # idempotent: second tick does not resend
    assert summary["detection"]["reason"] == "detection_already_notified"
    assert sent == []


def test_throttled_ci_repair_falls_back_to_one_uncapped_root_task(tmp_path):
    """G6 may collapse repair work, but it must never strand a red main."""
    created_at = datetime.now(timezone.utc).isoformat()
    capped = [
        {
            "id": f"alert_fixture_{index}",
            "source": "auto_discovered",
            "task_type": "platform_ops",
            "priority": 2,
            "status": "pending",
            "created_at": created_at,
        }
        for index in range(8)
    ]
    (tmp_path / "next_tasks.json").write_text(
        json.dumps(capped),
        encoding="utf-8",
    )
    run, _sent, dispatches = _harness(tmp_path)

    summary = run(RED1)

    tasks = _tasks(tmp_path)
    root_task = next(task for task in tasks if task["id"] == "ci-root-29233920234")
    assert root_task["source"] == "incident_escalation"
    assert root_task["ci_incident_id"] == "ci-red-29233920234"
    assert root_task["status"] == "pending"
    assert not any(task["id"] == "ci-red-29233920234" for task in tasks)
    incident = _state(tmp_path)["active_incident"]
    assert incident["repair_task_ids"] == [root_task["id"]]
    assert incident["repair_admission"]["status"] == "fallback_escalation_admitted"
    assert incident["repair_admission"]["denied_task_id"] == "ci-red-29233920234"
    assert dispatches == [root_task["id"]]
    assert summary["task_added"] is True
    assert "已啟動自動修復" in run.detections[0]["body"]
    assert root_task["id"] in run.detections[0]["body"]


def test_detection_does_not_claim_repair_started_when_all_admission_fails(
    tmp_path,
    monkeypatch,
):
    """A detection notice must report the durable admission fact, not intent."""

    def deny_every_task(task, _path):
        return {
            **task,
            "throttled_by_remediation_cap": True,
        }, False

    monkeypatch.setattr(
        check_alerts,
        "_append_next_task_record",
        deny_every_task,
    )
    run, _sent, dispatches = _harness(tmp_path)

    run(RED1)

    incident = _state(tmp_path)["active_incident"]
    assert incident["repair_task_ids"] == []
    assert incident["repair_admission"]["status"] == "failed"
    assert dispatches == []
    body = run.detections[0]["body"]
    assert "尚未啟動自動修復" in body
    assert "已啟動自動修復" not in body


def test_legacy_phantom_task_is_rebuilt_before_dispatch(tmp_path):
    run, _sent, dispatches = _harness(tmp_path)
    run(RED1)
    (tmp_path / "next_tasks.json").write_text("[]\n", encoding="utf-8")
    dispatches.clear()

    summary = run(RED1)

    assert summary["task_added"] is True
    assert [task["id"] for task in _tasks(tmp_path)] == ["ci-red-29233920234"]
    assert dispatches == ["ci-red-29233920234"]
    incident = _state(tmp_path)["active_incident"]
    assert incident["missing_repair_task_ids"] == ["ci-red-29233920234"]


def test_missing_task_is_never_dispatched_as_pending():
    dispatches = []
    incident = {
        "repair_task_ids": ["ci-red-missing"],
        "dispatch_requested_task_ids": [],
    }

    result, error = check_alerts._ci_dispatch_pending_task(
        incident,
        {},
        dispatcher=lambda task_id: dispatches.append(task_id),
        now_iso=NOW,
    )

    assert result is None
    assert error == "repair_task_missing_from_queue: ci-red-missing"
    assert dispatches == []


# --- stale-red supersession (assign_cb9c9fd1, second recurrence 2026-07-19) ----
# A red run against a commit main has already moved past is not proof main is red
# now. Twice the watchdog opened a P1 incident and fired a whole dispatch shift at
# a failure whose fix had already landed, while the run verifying the new HEAD was
# still running.

NEWER_HEAD = "999859933aaaa0000000000000000000000000aa"
VERIFYING = {
    **RED1,
    "databaseId": 29234963400,
    "url": f"{BASE_URL}/29234963400",
    "status": "in_progress",
    "conclusion": "",
    "headSha": NEWER_HEAD,
    "createdAt": "2026-07-13T09:50:00Z",
    "startedAt": "2026-07-13T09:50:00Z",
}
VERIFIED_GREEN = {
    **VERIFYING,
    "databaseId": 29234963401,
    "url": f"{BASE_URL}/29234963401",
    "status": "completed",
    "conclusion": "success",
    "createdAt": "2026-07-13T09:55:00Z",
    "startedAt": "2026-07-13T09:55:00Z",
}
VERIFIED_RED = {
    **VERIFIED_GREEN,
    "databaseId": 29234963402,
    "url": f"{BASE_URL}/29234963402",
    "conclusion": "failure",
}
PRIOR_GREEN = {
    **GREEN,
    "databaseId": 29230000000,
    "url": f"{BASE_URL}/29230000000",
    "headSha": "aaa0000000000000000000000000000000000001",
    "createdAt": "2026-07-13T08:00:00Z",
    "startedAt": "2026-07-13T08:00:00Z",
}


def test_stale_red_with_newer_run_in_flight_does_not_dispatch_or_escalate(tmp_path):
    run, sent, dispatches = _harness(tmp_path)

    summary = run(None, runs=[VERIFYING, RED1])

    assert summary["reason"] == "failure_head_superseded_by_newer_in_progress_run"
    assert summary["task_added"] is False
    assert dispatches == []  # no repair fire at already-fixed code
    assert not (tmp_path / "next_tasks.json").exists()
    assert sent == []  # neither CRITICAL escalation ...
    assert run.detections == []  # ... nor a red-detection heads-up
    state = _state(tmp_path)
    assert "active_incident" not in state
    # The defer is recorded, not silently swallowed, and the run stays unprocessed
    # so the next poll re-judges it once the verifying run lands.
    deferred = state["deferred_superseded_failures"][check_alerts._ci_run_key(RED1)]
    assert deferred["superseding_run"]["run_id"] == VERIFYING["databaseId"]
    assert state.get("processed_run_keys", []) == []


def test_rerun_of_the_same_failing_head_still_dispatches(tmp_path):
    """Fix not landed: the in-flight run tests the very commit that failed."""
    run, sent, dispatches = _harness(tmp_path)
    same_head_rerun = {**VERIFYING, "headSha": RED1["headSha"], "attempt": 2}

    summary = run(None, runs=[same_head_rerun, RED1])

    assert summary["task_added"] is True
    assert dispatches == ["ci-red-29233920234"]
    assert len(run.detections) == 1
    assert _state(tmp_path)["active_incident"]["phase"] in {"remediating", "verifying"}


def test_newer_run_that_does_not_carry_the_failing_commit_still_dispatches(tmp_path):
    """Ungraftable/unrelated head: ancestry fails closed, so the red still fires."""
    run, sent, dispatches = _harness(tmp_path, covered=lambda _a, _b: False)

    summary = run(None, runs=[VERIFYING, RED1])

    assert summary["task_added"] is True
    assert dispatches == ["ci-red-29233920234"]
    assert _state(tmp_path)["active_incident"]["failure_cycles"] == 1


def test_no_newer_run_at_all_still_dispatches(tmp_path):
    run, _sent, dispatches = _harness(tmp_path)

    summary = run(None, runs=[RED1])

    assert summary["task_added"] is True
    assert dispatches == ["ci-red-29233920234"]


def test_deferred_stale_red_is_retired_when_the_newer_head_goes_green(tmp_path):
    run, sent, dispatches = _harness(tmp_path)
    run(PRIOR_GREEN)  # seed history so the poll cursor is past first boot

    run(None, runs=[VERIFYING, RED1, PRIOR_GREEN])
    summary = run(None, runs=[VERIFIED_GREEN, RED1, PRIOR_GREEN])

    assert dispatches == []
    assert not (tmp_path / "next_tasks.json").exists()
    assert sent == []
    assert run.detections == []
    state = _state(tmp_path)
    assert "active_incident" not in state
    assert state["deferred_superseded_failures"] == {}
    resolved = state["resolved_superseded_failures"][-1]
    assert resolved["resolved_by_green_run"]["run_id"] == VERIFIED_GREEN["databaseId"]
    assert summary["reason"] == "healthy_no_incident"


def test_deferred_stale_red_still_opens_an_incident_if_the_newer_head_is_red(tmp_path):
    """Deferral is a wait, never an amnesty: a genuinely red main still fires."""
    run, _sent, dispatches = _harness(tmp_path)
    run(PRIOR_GREEN)

    run(None, runs=[VERIFYING, RED1, PRIOR_GREEN])
    run(None, runs=[VERIFIED_RED, RED1, PRIOR_GREEN])

    assert dispatches  # repair work was requested once main was provably red
    assert len(run.detections) == 1
    incident = _state(tmp_path)["active_incident"]
    assert incident["failure_cycles"] == 2


def test_detection_notice_marks_unknown_cause_but_still_fires(tmp_path):
    unresolved = check_alerts._ci_pick_failure_cause("no parseable signal here\n")
    assert unresolved.startswith("failed log")  # extractor found no root cause
    run, sent, _dispatches = _harness(tmp_path, summarizer=lambda _run: unresolved)

    run(RED1)

    # Extraction failed, but msg 822 forbids silence: still notify, mark unknown.
    assert len(run.detections) == 1
    first_line = run.detections[0]["body"].splitlines()[0]
    assert first_line == "白話原因：原因待查"
    assert RED1["url"] in run.detections[0]["body"]
    assert sent == []


def _complete_repair_task_at(tmp_path, completed_at, *, commit="abc1234"):
    tasks = _tasks(tmp_path)
    tasks[0]["status"] = "succeeded"
    tasks[0]["result"] = f"root_cause={CAUSE}; repair_commit={commit}"
    tasks[0]["completed_at"] = completed_at
    (tmp_path / "next_tasks.json").write_text(json.dumps(tasks), encoding="utf-8")


def test_red_run_queued_before_the_repair_landed_does_not_open_a_second_task(tmp_path):
    """A run created before the repair completed is stale evidence, not a retry.

    2026-07-20: incident ``ci-red-29703582195``'s repair completed at 22:38:29Z,
    but run 29705358452 had been queued at 22:01:20Z against a tree three commits
    older. The watcher read "repair succeeded yet still red" and opened a second
    P1 repair task; the fixer that claimed it found all four failing tests already
    green on HEAD and had nothing to repair.
    """
    run, sent, dispatches = _harness(tmp_path)
    run(RED1)
    _complete_repair_task_at(tmp_path, "2026-07-13T09:05:00+00:00")

    # RED2 was created at 09:00, i.e. before the repair completed at 09:05.
    stale_red = {**RED2, "createdAt": "2026-07-13T09:00:00Z"}
    summary = run(stale_red)

    assert summary["task_added"] is False
    assert summary["stale_failure"]["repair_task_id"] == "ci-red-29233920234"
    assert len(_tasks(tmp_path)) == 1
    assert dispatches == ["ci-red-29233920234"]
    assert sent == []


def test_red_run_created_after_the_repair_still_opens_a_retry_task(tmp_path):
    """The staleness guard defers by one cycle at most, it must not swallow a real retry."""
    run, _sent, _dispatches = _harness(tmp_path)
    run(RED1)
    _complete_repair_task_at(tmp_path, "2026-07-13T09:05:00+00:00")

    fresh_red = {**RED2, "createdAt": "2026-07-13T09:10:00Z"}
    summary = run(fresh_red)

    assert summary["task_added"] is True
    assert "stale_failure" not in summary
    assert {task["id"] for task in _tasks(tmp_path)} == {
        "ci-red-29233920234",
        check_alerts._ci_task_id(fresh_red),
    }


def test_stale_reds_do_not_escalate_to_the_boss(tmp_path):
    """Stale evidence must not inflate the "fixer keeps failing" counter either.

    Same defect as the duplicate-task path, different surface: while a fix is in
    flight, hourly CI keeps producing reds on pre-fix shas. Three of them cross
    CI_MAX_SILENT_FAILURE_CYCLES and mail the boss an escalation for a bug that
    was already repaired.
    """
    run, sent, _dispatches = _harness(tmp_path)
    run(RED1)
    _complete_repair_task_at(tmp_path, "2026-07-13T09:30:00+00:00")

    summaries = [
        run({**red, "createdAt": stamp})
        for red, stamp in (
            (RED2, "2026-07-13T09:05:00Z"),
            (RED3, "2026-07-13T09:10:00Z"),
            ({**RED2, "databaseId": 29233920237}, "2026-07-13T09:15:00Z"),
        )
    ]

    assert all(summary["task_added"] is False for summary in summaries)
    incident = _state(tmp_path)["active_incident"]
    assert len(incident["stale_failure_run_keys"]) == 3
    assert "escalation_reason" not in incident
    assert sent == []
    assert len(_tasks(tmp_path)) == 1
