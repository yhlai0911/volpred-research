from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import hourly_dispatch_pregate as pregate  # type: ignore


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# ── has_critical(): 2026-07-01 bug fix regression coverage ──
# Root cause: previously read nonexistent breach_count/breaches/critical/
# critical_count keys (always 0) and fell through to overall_status != ok,
# which is "warn" almost continuously (loop_health soft-tracking, reference-
# only host_cron_fail false-positive) -> signal was always True, defeating
# the gate. Fix reads the REAL scripts/ops_dashboard.py field
# `section_critical` (count of sections whose status is literally "critical").
def test_has_critical_false_when_only_warn_sections(tmp_path, monkeypatch):
    dashboard = tmp_path / "dashboard_latest.json"
    _write_json(dashboard, {"overall_status": "warn", "section_breaches": 2, "section_critical": 0})
    monkeypatch.setattr(pregate, "DASHBOARD", dashboard)
    assert pregate.has_critical() is False


def test_has_critical_true_when_section_critical_positive(tmp_path, monkeypatch):
    dashboard = tmp_path / "dashboard_latest.json"
    _write_json(dashboard, {"overall_status": "critical", "section_breaches": 3, "section_critical": 1})
    monkeypatch.setattr(pregate, "DASHBOARD", dashboard)
    assert pregate.has_critical() is True


def test_has_critical_unparseable_section_critical_fails_open(tmp_path, monkeypatch):
    dashboard = tmp_path / "dashboard_latest.json"
    _write_json(dashboard, {"overall_status": "warn", "section_critical": "not-a-number"})
    monkeypatch.setattr(pregate, "DASHBOARD", dashboard)
    assert pregate.has_critical() is True


def test_has_critical_falls_back_to_overall_status_when_field_missing(tmp_path, monkeypatch):
    # Older/missing schema without section_critical at all.
    dashboard = tmp_path / "dashboard_latest.json"
    _write_json(dashboard, {"overall_status": "warn"})
    monkeypatch.setattr(pregate, "DASHBOARD", dashboard)
    assert pregate.has_critical() is True

    _write_json(dashboard, {"overall_status": "ok"})
    assert pregate.has_critical() is False


# ── has_email_backlog() ──
def test_has_email_backlog_detects_pending_email_reply():
    tasks = [{"task_type": "email_reply", "status": "pending"}, {"task_type": "experiment", "status": "pending"}]
    assert pregate.has_email_backlog(tasks) is True


def test_has_email_backlog_false_when_none_pending():
    tasks = [{"task_type": "email_reply", "status": "succeeded"}, {"task_type": "experiment", "status": "pending"}]
    assert pregate.has_email_backlog(tasks) is False


# ── decide(): integration, real dashboard schema, gate now produces a meaningful skip ──
def test_decide_would_skip_true_when_all_signals_quiet(tmp_path, monkeypatch):
    dashboard = tmp_path / "dashboard_latest.json"
    next_tasks = tmp_path / "next_tasks.json"
    work_log = tmp_path / "work_log.json"
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=1)).isoformat()

    _write_json(dashboard, {"overall_status": "warn", "section_breaches": 1, "section_critical": 0})
    _write_json(
        next_tasks,
        [
            {"task_type": "experiment", "status": "succeeded", "priority": 3},
            {
                "task_type": "daily_article",
                "status": "succeeded",
                "claimed_by": "hourly-dispatch",
                "claimed_at": recent,
            },
        ],
    )
    _write_json(work_log, [])

    monkeypatch.setattr(pregate, "DASHBOARD", dashboard)
    monkeypatch.setattr(pregate, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(pregate, "WORK_LOG", work_log)
    monkeypatch.setattr(pregate, "has_high_prio", lambda tasks: False)

    result = pregate.decide(window_hours=3.0)
    assert result["proceed"] is False
    assert result["reasons"]["critical"] is False
    assert result["reasons"]["cadence_due"] is False


def test_decide_proceeds_on_true_critical(tmp_path, monkeypatch):
    dashboard = tmp_path / "dashboard_latest.json"
    next_tasks = tmp_path / "next_tasks.json"
    work_log = tmp_path / "work_log.json"
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=1)).isoformat()

    _write_json(dashboard, {"overall_status": "critical", "section_breaches": 3, "section_critical": 1})
    _write_json(
        next_tasks,
        [
            {
                "task_type": "daily_article",
                "status": "succeeded",
                "claimed_by": "hourly-dispatch",
                "claimed_at": recent,
            }
        ],
    )
    _write_json(work_log, [])

    monkeypatch.setattr(pregate, "DASHBOARD", dashboard)
    monkeypatch.setattr(pregate, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(pregate, "WORK_LOG", work_log)
    monkeypatch.setattr(pregate, "has_high_prio", lambda tasks: False)

    result = pregate.decide(window_hours=3.0)
    assert result["proceed"] is True
    assert result["reasons"]["critical"] is True
