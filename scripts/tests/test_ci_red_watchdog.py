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


def _run(tmp_path, run, sent):
    def sender(level, title, body, **kwargs):
        sent.append({"level": level, "title": title, "body": body})
        return {"sent": True}

    return check_alerts._handle_ci_run(
        run,
        now_iso=NOW,
        next_tasks_path=tmp_path / "next_tasks.json",
        state_path=tmp_path / "ci_watch_state.json",
        sender=sender,
    )


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


def test_green_run_adds_nothing_and_records_recovery(tmp_path):
    sent = []
    summary = _run(tmp_path, GREEN_RUN, sent)
    assert summary["task_added"] is False
    assert sent == []
    assert not (tmp_path / "next_tasks.json").exists()
    state = json.loads((tmp_path / "ci_watch_state.json").read_text())
    assert state["last_seen_conclusion"] == "success"
