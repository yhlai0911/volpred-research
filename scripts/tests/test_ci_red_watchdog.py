"""CI red watchdog (check_alerts._handle_ci_run) — 2026-07-13 boss msgs 632-653.

Contract: a failed main Test Suite run must, within one hourly tick, become a
P1 platform_ops repair task in the pending queue (deduped by run id) plus a
critical alert whose body says what the system already did. A green run must
add nothing and record recovery.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for extra in (PROJECT_ROOT / "scripts", PROJECT_ROOT / "src"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import check_alerts  # noqa: E402

RED_RUN = {
    "databaseId": 29233920234,
    "conclusion": "failure",
    "url": "https://github.com/yhlai0911/volpred-research/actions/runs/29233920234",
    "headSha": "deadbeefcafe",
}
GREEN_RUN = {**RED_RUN, "databaseId": 29234963362, "conclusion": "success"}
NOW = "2026-07-13T09:00:00+00:00"


def _run(tmp_path, run, sent, *, probe=None, pushes=None, push_result=None):
    def sender(level, title, body, **kwargs):
        sent.append({"level": level, "title": title, "body": body})
        return {"sent": True}

    def pusher():
        if pushes is not None:
            pushes.append(True)
        return push_result or {"pushed": True, "rc": 0, "outcome": "pushed"}

    return check_alerts._handle_ci_run(
        run,
        now_iso=NOW,
        next_tasks_path=tmp_path / "next_tasks.json",
        state_path=tmp_path / "ci_watch_state.json",
        sender=sender,
        # default probe: nothing local to push (the pre-2026-07-13 happy path)
        ahead_probe=probe or (lambda run: {"probe_ok": True, "ahead": 0}),
        pusher=pusher,
    )


def _ahead(n=2, head="localsha123", run_sha="deadbeefcafe"):
    """Local main holds n commits GitHub has not seen."""
    return lambda run: {"probe_ok": True, "ahead": n, "head_sha": head,
                        "run_sha": run_sha, "ci_saw_head": head == run_sha}


def test_red_run_appends_p1_task_and_alerts(tmp_path):
    sent = []
    summary = _run(tmp_path, RED_RUN, sent)
    assert summary["task_added"] is True
    assert summary["alert_sent"] is True

    tasks = json.loads((tmp_path / "next_tasks.json").read_text())
    assert len(tasks) == 1
    task = tasks[0]
    assert task["id"] == "ci-red-29233920234"
    assert task["priority"] == 1
    assert task["task_type"] == "platform_ops"
    assert task["status"] == "pending"
    assert "log-failed" in task["description"]  # repair recipe embedded

    assert sent[0]["level"] == "critical"
    assert "已自動" in sent[0]["body"]  # auto-acted framing, not a boss to-do


def test_same_red_run_is_handled_once(tmp_path):
    sent = []
    _run(tmp_path, RED_RUN, sent)
    summary = _run(tmp_path, RED_RUN, sent)
    assert summary["task_added"] is False
    assert summary["reason"] == "already_handled"
    assert len(sent) == 1
    tasks = json.loads((tmp_path / "next_tasks.json").read_text())
    assert len(tasks) == 1


def test_new_red_run_after_first_gets_its_own_task(tmp_path):
    sent = []
    _run(tmp_path, RED_RUN, sent)
    second = {**RED_RUN, "databaseId": 99999999999}
    summary = _run(tmp_path, second, sent)
    assert summary["task_added"] is True
    tasks = json.loads((tmp_path / "next_tasks.json").read_text())
    assert {t["id"] for t in tasks} == {"ci-red-29233920234", "ci-red-99999999999"}


def test_red_run_with_local_unpushed_commits_pushes_them(tmp_path):
    """2026-07-13 boss msg 677: the fix commit sat local for 75 min while CI re-ran stale code."""
    sent, pushes = [], []
    summary = _run(tmp_path, RED_RUN, sent, probe=_ahead(1), pushes=pushes)
    assert pushes == [True]
    assert summary["push"]["outcome"] == "pushed"
    assert "已自動 push" in sent[0]["body"]


def test_repeat_sighting_of_same_red_run_still_pushes(tmp_path):
    """The regression that bit us: the unpushed window lives entirely behind the dedup gate.

    A red run stays the newest completed run until a push produces a newer one, so
    every tick after the first hits `already_handled`. Pushing must not be gated on it.
    """
    sent, pushes = [], []
    _run(tmp_path, RED_RUN, sent)                                    # tick 1: nothing local yet
    summary = _run(tmp_path, RED_RUN, sent, probe=_ahead(1), pushes=pushes)  # tick 2: fix committed
    assert summary["reason"] == "already_handled"
    assert summary["task_added"] is False   # no duplicate task
    assert len(sent) == 1                   # no duplicate alert
    assert pushes == [True]                 # but the fix DID get pushed


def test_push_held_by_pre_push_gate_is_not_bypassed(tmp_path):
    held = {"pushed": False, "rc": 120, "outcome": "held"}
    sent, pushes = [], []
    summary = _run(tmp_path, RED_RUN, sent, probe=_ahead(2), pushes=pushes, push_result=held)
    assert pushes == [True]
    assert summary["push"]["outcome"] == "held"
    assert "閘門" in sent[0]["body"]  # hold surfaced to the boss, not silently swallowed


def test_no_push_when_ci_already_tested_local_head(tmp_path):
    """HEAD == the sha CI ran → the red is real code, not a stale-code artifact."""
    sent, pushes = [], []
    same = _ahead(1, head="deadbeefcafe", run_sha="deadbeefcafe")
    summary = _run(tmp_path, RED_RUN, sent, probe=same, pushes=pushes)
    assert pushes == []
    assert summary["push"]["reason"] == "ci_already_tested_head"


def test_no_push_when_nothing_local(tmp_path):
    sent, pushes = [], []
    summary = _run(tmp_path, RED_RUN, sent, pushes=pushes)
    assert pushes == []
    assert summary["push"]["reason"] == "nothing_unpushed"
    assert _ci_push_line(sent) == ""  # nothing to say → no noise in the alert body


def _ci_push_line(sent):
    return check_alerts._ci_push_body_line({"attempted": False, "reason": "nothing_unpushed"})


def test_green_run_adds_nothing_and_records_recovery(tmp_path):
    sent = []
    summary = _run(tmp_path, GREEN_RUN, sent)
    assert summary["task_added"] is False
    assert sent == []
    assert not (tmp_path / "next_tasks.json").exists()
    state = json.loads((tmp_path / "ci_watch_state.json").read_text())
    assert state["last_seen_conclusion"] == "success"
