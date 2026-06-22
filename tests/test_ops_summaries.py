from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

from volpred.ops import summaries


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_build_queue_summary_compacts_snapshot(monkeypatch):
    monkeypatch.setattr(
        summaries,
        "build_control_plane_snapshot",
        lambda storage_dir="storage": {
            "task_counts": {"queued": 4, "running": 1, "blocked": 2, "succeeded": 9},
            "brief_status_counts": {"ready": 3, "pending": 5},
            "pending_user_tasks": 2,
            "discovery_allowed": False,
            "agents": [
                {"session_key": "claude-supervisor", "status": "online"},
                {"session_key": "codex-worker", "status": "offline"},
            ],
            "scheduler": {"last_tick_at": "2026-04-23T03:00:00+00:00", "last_status": "ok"},
        },
    )
    monkeypatch.setattr(
        summaries,
        "scheduler_preview",
        lambda storage_dir="storage": {
            "decision": {
                "task_id": "task_123",
                "title": "Review queue",
                "agent": "claude",
                "mode": "coordinator",
                "brief_status": "ready",
                "advisory_only": False,
            },
            "queue_snapshot": [
                {
                    "task_id": "task_123",
                    "title": "Review queue",
                    "target_agent": "claude",
                    "brief_status": "ready",
                    "runnable": True,
                    "blocked_reason": None,
                }
            ],
        },
    )

    summary = summaries.build_queue_summary()

    assert summary["queued"] == 4
    assert summary["active_agents"] == ["claude-supervisor"]
    assert summary["next_decision"]["task_id"] == "task_123"
    assert summary["queue_head"][0]["runnable"] is True


def test_build_continue_task_maintenance_skips_when_no_work(monkeypatch):
    monkeypatch.setattr(
        summaries,
        "build_control_plane_snapshot",
        lambda storage_dir="storage": {
            "agents": [{"session_key": "claude-worker", "status": "idle"}],
            "pending_user_tasks": 0,
            "discovery_allowed": True,
        },
    )
    monkeypatch.setattr(
        summaries,
        "scheduler_preview",
        lambda storage_dir="storage": {
            "queued_count": 0,
            "queue_snapshot": [],
            "decision": None,
        },
    )
    monkeypatch.setattr(
        summaries,
        "_runtime_idle_policy",
        lambda: {"source_label": "test", "max_concurrent_agents": 4},
    )

    result = summaries.build_continue_task_maintenance()

    assert result["skip"] is True
    assert result["reason"] == "no_work"
    assert result["busy_agent_count"] == 0
    assert result["queued_count"] == 0


def test_build_continue_task_maintenance_skips_when_slot_full(monkeypatch):
    monkeypatch.setattr(
        summaries,
        "build_control_plane_snapshot",
        lambda storage_dir="storage": {
            "agents": [
                {"session_key": "claude-supervisor", "status": "busy"},
                {"session_key": "claude-worker", "status": "busy"},
            ],
            "pending_user_tasks": 0,
            "discovery_allowed": True,
        },
    )
    monkeypatch.setattr(
        summaries,
        "scheduler_preview",
        lambda storage_dir="storage": {
            "queued_count": 2,
            "queue_snapshot": [
                {
                    "task_id": "task_1",
                    "title": "Blocked",
                    "target_agent": "codex",
                    "runnable": False,
                    "blocked_reason": "agent_unavailable",
                    "brief_status": "pending",
                }
            ],
            "decision": None,
        },
    )
    monkeypatch.setattr(
        summaries,
        "_runtime_idle_policy",
        lambda: {"source_label": "test", "max_concurrent_agents": 2},
    )

    result = summaries.build_continue_task_maintenance()

    assert result["skip"] is True
    assert result["reason"] == "slot_full"
    assert result["busy_agent_count"] == 2
    assert result["max_concurrent_agents"] == 2


def test_build_continue_task_maintenance_returns_next_decision(monkeypatch):
    monkeypatch.setattr(
        summaries,
        "build_control_plane_snapshot",
        lambda storage_dir="storage": {
            "agents": [{"session_key": "claude-worker", "status": "idle"}],
            "pending_user_tasks": 1,
            "discovery_allowed": False,
        },
    )
    monkeypatch.setattr(
        summaries,
        "scheduler_preview",
        lambda storage_dir="storage": {
            "queued_count": 3,
            "queue_snapshot": [
                {
                    "task_id": "task_123",
                    "title": "Review queue",
                    "target_agent": "claude",
                    "runnable": True,
                    "blocked_reason": None,
                    "brief_status": "ready",
                }
            ],
            "decision": {
                "task_id": "task_123",
                "title": "Review queue",
                "agent": "claude",
                "mode": "coordinator",
                "brief_status": "ready",
            },
        },
    )
    monkeypatch.setattr(
        summaries,
        "_runtime_idle_policy",
        lambda: {"source_label": "test", "max_concurrent_agents": 4},
    )

    result = summaries.build_continue_task_maintenance()

    assert result["skip"] is False
    assert result["action"] == "review_next_task"
    assert result["reason"] == "dispatch_candidate"
    assert result["next_decision"]["task_id"] == "task_123"
    assert result["pending_user_tasks"] == 1
    assert result["detail_hints"]["maintain"].endswith("continue-task-maintain --stub-if-no-work")


def test_build_daily_planning_maintenance_skips_when_no_gaps(monkeypatch):
    monkeypatch.setattr(
        summaries,
        "build_queue_summary",
        lambda storage_dir="storage": {
            "queued": 0,
            "running": 0,
            "pending_user_tasks": 0,
            "discovery_allowed": True,
            "next_decision": None,
            "queue_head": [],
        },
    )
    monkeypatch.setattr(
        summaries,
        "build_scheduler_summary",
        lambda storage_dir="storage": {
            "missing_system_task_count": 0,
            "missing_system_tasks": [],
            "queued_count": 0,
            "scheduler_last_tick_at": "2026-04-23T03:00:00+00:00",
            "scheduler_last_status": "ok",
        },
    )
    monkeypatch.setattr(
        summaries,
        "build_platform_patrol_maintenance",
        lambda storage_dir="storage", source="user", limit=5: {
            "skip": True,
            "action": "skip",
            "trigger_reasons": [],
            "release_due": False,
            "alert_breach_count": 0,
            "pending_questions": 0,
        },
    )

    result = summaries.build_daily_planning_maintenance()

    assert result["skip"] is True
    assert result["action"] == "skip"
    assert result["trigger_reasons"] == []


def test_build_daily_planning_maintenance_collects_queue_scheduler_platform_signals(monkeypatch):
    monkeypatch.setattr(
        summaries,
        "build_queue_summary",
        lambda storage_dir="storage": {
            "queued": 2,
            "running": 1,
            "pending_user_tasks": 1,
            "discovery_allowed": False,
            "next_decision": {"task_id": "task_123", "agent": "claude"},
            "queue_head": [{"task_id": "task_123"}],
        },
    )
    monkeypatch.setattr(
        summaries,
        "build_scheduler_summary",
        lambda storage_dir="storage": {
            "missing_system_task_count": 1,
            "missing_system_tasks": ["shared scheduler tick"],
            "queued_count": 2,
            "scheduler_last_tick_at": "2026-04-23T03:00:00+00:00",
            "scheduler_last_status": "warn",
        },
    )
    monkeypatch.setattr(
        summaries,
        "build_platform_patrol_maintenance",
        lambda storage_dir="storage", source="user", limit=5: {
            "skip": False,
            "action": "inspect_detail",
            "trigger_reasons": ["pending_questions"],
            "release_due": False,
            "alert_breach_count": 0,
            "pending_questions": 2,
        },
    )

    result = summaries.build_daily_planning_maintenance()

    assert result["skip"] is False
    assert result["action"] == "review_planning"
    assert result["trigger_reasons"] == [
        "pending_user_tasks",
        "queued_tasks",
        "scheduler_gap",
        "platform:pending_questions",
    ]
    assert result["queue"]["next_decision"]["task_id"] == "task_123"
    assert result["scheduler"]["missing_system_tasks"] == ["shared scheduler tick"]
    assert result["platform_gate"]["pending_questions"] == 2
    assert result["detail_hints"]["maintain"].endswith("daily-planning-maintain --stub-if-no-work")


def test_build_scheduler_summary_uses_compact_counts(monkeypatch):
    monkeypatch.setattr(
        summaries,
        "build_schedule_report",
        lambda: {
            "expected_system_task_count": 3,
            "matched_system_tasks": ["daily_update", "check_alerts"],
            "missing_system_tasks": ["collect_tw"],
            "session_cron_count": 2,
            "remote_trigger_count": 1,
            "live_system_crontab_available": True,
            "live_system_crontab_count": 4,
        },
    )
    monkeypatch.setattr(
        summaries,
        "get_scheduler_state",
        lambda storage_dir="storage": {
            "last_tick_at": "2026-04-23T03:00:00+00:00",
            "last_status": "ok",
            "last_reason": None,
        },
    )
    monkeypatch.setattr(
        summaries,
        "scheduler_preview",
        lambda storage_dir="storage": {
            "queued_count": 6,
            "decision": {
                "task_id": "task_456",
                "title": "Publish update",
                "agent": "codex",
                "mode": "executor",
                "brief_status": "ready",
            },
        },
    )

    summary = summaries.build_scheduler_summary()

    assert summary["matched_system_task_count"] == 2
    assert summary["missing_system_task_count"] == 1
    assert summary["queued_count"] == 6
    assert summary["next_decision"]["agent"] == "codex"


def test_build_token_summary_rolls_latest_available_reports(tmp_path: Path):
    storage_dir = tmp_path / "storage"
    _write_json(
        storage_dir / "reports" / "token_usage" / "daily_2026-04-20.json",
        {
            "date": "2026-04-20",
            "totals": {
                "estimated_cost_usd": 10.5,
                "billable_total": 100,
                "cache_create_tokens": 20,
                "assistant_messages": 3,
                "unique_sessions": 1,
            },
        },
    )
    _write_json(
        storage_dir / "reports" / "token_usage" / "daily_2026-04-21.json",
        {
            "date": "2026-04-21",
            "totals": {
                "estimated_cost_usd": 12.0,
                "billable_total": 120,
                "cache_create_tokens": 30,
                "assistant_messages": 4,
                "unique_sessions": 2,
            },
        },
    )
    _write_json(
        storage_dir / "reports" / "token_usage" / "weekly_2026-04-17.json",
        {
            "week_start": "2026-04-14",
            "week_end": "2026-04-20",
            "totals": {
                "estimated_cost_usd": 55.5,
                "billable_total": 500,
                "cache_create_tokens": 80,
                "assistant_messages": 20,
                "unique_sessions": 5,
            },
        },
    )

    summary = summaries.build_token_summary(storage_dir=str(storage_dir), days=2)

    assert summary["available"] is True
    assert summary["latest_daily"]["date"] == "2026-04-21"
    assert summary["rolling_window"]["estimated_cost_usd"] == 22.5
    assert summary["rolling_window"]["billable_total"] == 220
    assert summary["latest_weekly"]["week_end"] == "2026-04-20"


def test_build_token_summary_warns_on_bad_daily_report_date(tmp_path: Path, capsys):
    storage_dir = tmp_path / "storage"
    _write_json(
        storage_dir / "reports" / "token_usage" / "daily_bad-date.json",
        {"date": "bad-date", "totals": {"estimated_cost_usd": 99}},
    )
    _write_json(
        storage_dir / "reports" / "token_usage" / "daily_2026-04-21.json",
        {
            "date": "2026-04-21",
            "totals": {
                "estimated_cost_usd": 12.0,
                "billable_total": 120,
                "cache_create_tokens": 30,
            },
        },
    )

    summary = summaries.build_token_summary(storage_dir=str(storage_dir), days=2)

    assert summary["daily_reports_available"] == 1
    assert summary["latest_daily"]["date"] == "2026-04-21"
    assert summary["rolling_window"]["estimated_cost_usd"] == 12.0
    captured = capsys.readouterr()
    assert (
        "[ops_summaries] WARN token usage daily report date parse failed; skipping"
        in captured.err
    )
    assert "daily_bad-date.json" in captured.err
    assert "ValueError" in captured.err


def test_build_token_policy_summary_reads_canonical_thresholds(tmp_path: Path):
    config_path = tmp_path / "token_policy.json"
    _write_json(
        config_path,
        {
            "auto_compact_pct_override": 62,
            "context_boundaries": {
                "normal_max_pct": 55,
                "compact_min_pct": 62,
                "clear_min_pct": 70,
            },
            "statusline_colors": {
                "compact_warn_pct": 62,
                "warn_pct": 75,
                "danger_pct": 90,
            },
            "session_health": {
                "lifetime_cost_usd": 180.0,
                "lifetime_hours": 20.0,
                "cache_read_tokens": 900000000,
                "messages": 1200,
                "active_window_minutes": 45,
            },
            "canonical_sources": {
                "runtime_schedules": "config/runtime_schedules.json",
                "workflow_index": "docs/workflow-index.md",
                "commands": [".claude/commands/task-start.md"],
            },
            "guidance": {
                "between_normal_and_compact": "fork_or_compact",
                "between_compact_and_clear": "compact",
                "above_clear": "clear",
            },
        },
    )

    summary = summaries.build_token_policy_summary(policy_path=str(config_path))

    assert summary["available"] is True
    assert summary["auto_compact_pct_override"] == 62
    assert summary["context_boundaries"]["compact_min_pct"] == 62
    assert summary["statusline_colors"]["danger_pct"] == 90
    assert summary["policy_digest"]["clear_at_or_above_pct"] == 70
    assert summary["session_health"]["lifetime_cost_usd"] == 180.0
    assert summary["session_health"]["active_window_minutes"] == 45
    assert summary["canonical_sources"]["commands"] == [".claude/commands/task-start.md"]


def test_build_token_usage_maintenance_skips_when_daily_is_fresh(tmp_path: Path):
    storage_dir = tmp_path / "storage"
    _write_json(
        storage_dir / "reports" / "token_usage" / "daily_2026-04-23.json",
        {
            "date": "2026-04-23",
            "totals": {
                "estimated_cost_usd": 1.2,
                "billable_total": 20,
                "cache_create_tokens": 5,
                "assistant_messages": 2,
                "unique_sessions": 1,
            },
        },
    )

    summary = summaries.build_token_usage_maintenance(
        storage_dir=str(storage_dir),
        target_date=date(2026, 4, 23),
    )

    assert summary["skip"] is True
    assert summary["action"] == "skip"
    assert summary["daily_report_exists"] is True
    assert summary["weekly_due"] is False
    assert summary["execution_commands"] == []


def test_build_token_usage_maintenance_requests_daily_and_weekly_when_friday_reports_missing(tmp_path: Path):
    storage_dir = tmp_path / "storage"
    _write_json(
        storage_dir / "reports" / "token_usage" / "daily_2026-04-23.json",
        {
            "date": "2026-04-23",
            "totals": {
                "estimated_cost_usd": 1.0,
                "billable_total": 10,
                "cache_create_tokens": 2,
                "assistant_messages": 1,
                "unique_sessions": 1,
            },
        },
    )

    summary = summaries.build_token_usage_maintenance(
        storage_dir=str(storage_dir),
        target_date=date(2026, 4, 24),
    )

    assert summary["skip"] is False
    assert summary["action"] == "generate_daily_and_weekly"
    assert summary["weekly_due"] is True
    assert summary["recommended_actions"] == ["generate_daily_report", "generate_weekly_report"]
    assert summary["execution_commands"][0].endswith("--date 2026-04-24")
    assert summary["execution_commands"][1].endswith("--week-start 2026-04-24")


def test_run_token_usage_maintenance_executes_missing_reports(monkeypatch):
    before = {
        "storage_dir": "storage",
        "skip": False,
        "action": "generate_daily_and_weekly",
        "target_date": "2026-04-24",
        "execution_commands": [
            "uv run python scripts/token_usage_report.py --date 2026-04-24",
            "uv run python scripts/token_usage_report.py --weekly --week-start 2026-04-24",
        ],
    }
    after = {
        "storage_dir": "storage",
        "skip": True,
        "action": "skip",
        "target_date": "2026-04-24",
        "execution_commands": [],
    }
    snapshots = iter([before, after])
    monkeypatch.setattr(
        summaries,
        "build_token_usage_maintenance",
        lambda storage_dir="storage", days=7, target_date=None: next(snapshots),
    )

    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], cwd: str | None, capture_output: bool, text: bool) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(cmd, 0, stdout="saved\nok\n", stderr="")

    monkeypatch.setattr(summaries.subprocess, "run", _fake_run)

    result = summaries.run_token_usage_maintenance(
        storage_dir="storage",
        target_date=date(2026, 4, 24),
        tail_lines=1,
    )

    assert result["skip"] is False
    assert result["executed"] is True
    assert result["success"] is True
    assert result["after_action"] == "skip"
    assert result["needs_followup"] is False
    assert len(result["runs"]) == 2
    assert result["runs"][0]["stdout_tail"] == ["ok"]
    assert calls[0][-1] == "2026-04-24"
    assert calls[1][-1] == "2026-04-24"


def test_build_git_sync_maintenance_skips_when_branch_is_clean(monkeypatch):
    def _fake_run(cmd: list[str], cwd: str | None, capture_output: bool, text: bool) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout="## main...origin/main\n", stderr="")

    monkeypatch.setattr(summaries.subprocess, "run", _fake_run)

    summary = summaries.build_git_sync_maintenance()

    assert summary["available"] is True
    assert summary["skip"] is True
    assert summary["action"] == "skip"
    assert summary["branch"] == "main"
    assert summary["working_tree_changes"] == 0


def test_build_git_sync_maintenance_detects_dirty_worktree(monkeypatch):
    stdout = "\n".join(
        [
            "## main...origin/main [ahead 1]",
            " M docs/project_improvement_status.md",
            "?? tests/test_ops_summaries.py",
        ]
    )

    def _fake_run(cmd: list[str], cwd: str | None, capture_output: bool, text: bool) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(summaries.subprocess, "run", _fake_run)

    summary = summaries.build_git_sync_maintenance()

    assert summary["skip"] is False
    assert summary["action"] == "review_changes"
    assert summary["reason"] == "working_tree_dirty"
    assert summary["ahead"] == 1
    assert summary["unstaged_count"] == 1
    assert summary["untracked_count"] == 1
    assert summary["changed_paths"][0]["path"] == "docs/project_improvement_status.md"


def test_build_ndc_indicator_maintenance_skips_when_required_series_are_fresh(tmp_path: Path):
    storage_dir = tmp_path / "storage"
    csv_path = storage_dir / "macro" / "tw_dgbas_bci_m.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(
        "\n".join(
            [
                "item,unit,freq,period,value",
                "景氣領先指標不含趨勢指數(點),點,M,2026M02,103.88",
                "景氣對策信號(分),,M,2026M02,40.0",
            ]
        ),
        encoding="utf-8",
    )

    summary = summaries.build_ndc_indicator_maintenance(
        storage_dir=str(storage_dir),
        target_date=date(2026, 4, 23),
    )

    assert summary["skip"] is True
    assert summary["action"] == "skip"
    assert summary["expected_period"] == "2026M02"
    assert summary["stale_series_count"] == 0
    assert summary["required_series"]["leading_indicator"]["latest_period"] == "2026M02"


def test_build_ndc_indicator_maintenance_flags_stale_series(tmp_path: Path):
    storage_dir = tmp_path / "storage"
    csv_path = storage_dir / "macro" / "tw_dgbas_bci_m.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(
        "\n".join(
            [
                "item,unit,freq,period,value",
                "景氣領先指標不含趨勢指數(點),點,M,2026M01,103.63",
                "景氣對策信號(分),,M,2026M02,40.0",
            ]
        ),
        encoding="utf-8",
    )

    summary = summaries.build_ndc_indicator_maintenance(
        storage_dir=str(storage_dir),
        target_date=date(2026, 4, 23),
    )

    assert summary["skip"] is False
    assert summary["action"] == "manual_refresh"
    assert summary["expected_period"] == "2026M02"
    assert summary["stale_series_count"] == 1
    assert summary["stale_series"] == ["leading_indicator"]
    assert summary["required_series"]["signal_score"]["fresh"] is True
    assert summary["detail_hints"]["maintain"].endswith("ndc-indicator-maintain --stub-if-no-work")


def test_build_log_summary_returns_recent_tail(tmp_path: Path):
    storage_dir = tmp_path / "storage"
    cron_log = storage_dir / "logs" / "cron" / "daily_update.log"
    hook_log = storage_dir / "logs" / "hooks" / "test_1.log"
    cron_log.parent.mkdir(parents=True, exist_ok=True)
    hook_log.parent.mkdir(parents=True, exist_ok=True)
    cron_log.write_text("line1\nline2\nline3\n", encoding="utf-8")
    hook_log.write_text("setup\nFAIL test_demo\nTraceback details\n", encoding="utf-8")

    summary = summaries.build_log_summary(storage_dir=str(storage_dir), limit=2, tail_lines=2)

    assert summary["cron_logs"]["count"] == 1
    assert summary["cron_logs"]["latest"][0]["tail"] == ["line2", "line3"]
    assert summary["hook_logs"]["latest"][0]["tail"] == ["FAIL test_demo", "Traceback details"]


def test_build_knowledge_index_summary_detects_drift(tmp_path: Path, monkeypatch):
    storage_dir = tmp_path / "storage"
    memory_dir = storage_dir / "memory"
    reports_dir = storage_dir / "reports"
    index_dir = storage_dir / "knowledge_index"
    memory_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)

    knowledge = memory_dir / "knowledge.json"
    feed = reports_dir / "feed.json"
    knowledge.write_text("[]", encoding="utf-8")
    feed.write_text("[]", encoding="utf-8")

    old_mtime = knowledge.stat().st_mtime - 10
    _write_json(
        storage_dir / ".knowledge_index_state.json",
        {
            "knowledge.json": old_mtime,
            "feed.json": feed.stat().st_mtime,
        },
    )

    monkeypatch.setattr(
        summaries,
        "_knowledge_index_table_summary",
        lambda index_dir: {
            "available": True,
            "total_entries": 128,
            "top_sources": [{"source": "knowledge", "count": 80}],
        },
    )
    monkeypatch.setattr(
        summaries,
        "_knowledge_index_watch_files",
        lambda storage_dir="storage": [knowledge, feed],
    )

    summary = summaries.build_knowledge_index_summary(storage_dir=str(storage_dir))

    assert summary["status"] == "stale"
    assert summary["drift_detected"] is True
    assert summary["changed_files_count"] == 1
    assert summary["changed_files"] == ["knowledge.json"]
    assert summary["total_entries"] == 128
    assert summary["top_sources"][0]["source"] == "knowledge"
    assert summary["recommended_action"] == "auto"
    assert summary["recommended_command"].endswith("build_knowledge_index.py auto")
    assert summary["detail_hints"]["maintain"].endswith("knowledge-index-maintain --stub-if-no-work")
    assert summary["detail_hints"]["build"].endswith("build_knowledge_index.py build")


def test_run_knowledge_index_maintenance_skips_when_fresh(monkeypatch):
    before = {
        "storage_dir": "storage",
        "status": "fresh",
        "recommended_action": "skip",
        "recommended_command": None,
        "fallback_command": None,
    }
    monkeypatch.setattr(summaries, "build_knowledge_index_summary", lambda storage_dir="storage": before)

    result = summaries.run_knowledge_index_maintenance(storage_dir="storage")

    assert result["skip"] is True
    assert result["executed"] is False
    assert result["mode"] == "skip"
    assert result["after"] == before
    assert result["needs_followup"] is False


def test_run_knowledge_index_maintenance_executes_recommended_command(monkeypatch):
    before = {
        "storage_dir": "storage",
        "status": "broken",
        "recommended_action": "auto",
        "recommended_command": "uv run python scripts/build_knowledge_index.py auto",
        "fallback_command": "uv run python scripts/build_knowledge_index.py build",
    }
    after = {
        "storage_dir": "storage",
        "status": "fresh",
        "recommended_action": "skip",
        "recommended_command": None,
        "fallback_command": None,
    }
    snapshots = iter([before, after])
    monkeypatch.setattr(
        summaries,
        "build_knowledge_index_summary",
        lambda storage_dir="storage": next(snapshots),
    )

    sync_calls: list[str] = []
    monkeypatch.setattr(
        summaries,
        "_sync_knowledge_index_state",
        lambda storage_dir="storage": sync_calls.append(storage_dir) or {"knowledge.json": 1.0},
    )

    run_calls: list[tuple[object, str | None]] = []

    def _fake_run(cmd: list[str], cwd: str | None, capture_output: bool, text: bool) -> subprocess.CompletedProcess[str]:
        run_calls.append((cmd, cwd))
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(cmd, 0, stdout="step1\nstep2\n", stderr="")

    monkeypatch.setattr(summaries.subprocess, "run", _fake_run)

    result = summaries.run_knowledge_index_maintenance(storage_dir="storage", tail_lines=1)

    assert result["skip"] is False
    assert result["executed"] is True
    assert result["mode"] == "executed"
    assert result["success"] is True
    assert result["before_status"] == "broken"
    assert result["after_status"] == "fresh"
    assert result["needs_followup"] is False
    assert result["stdout_tail"] == ["step2"]
    assert result["stderr_tail"] == []
    assert sync_calls == ["storage"]
    assert run_calls[0][0][-1] == "auto"


def test_build_publication_candidates_summary_compacts_candidate_lists(tmp_path: Path):
    storage_dir = tmp_path / "storage"
    _write_json(
        storage_dir / "publication_candidates.json",
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_k": 12,
                "uncovered": 4,
                "high_priority_uncovered": 2,
                "missing_general_audience": 3,
                "missing_research_audience": 1,
            },
            "top_10_uncovered": [
                {"k_id": "K1001", "score": 7, "title": "First uncovered"},
                {"k_id": "K1002", "score": 6, "title": "Second uncovered"},
                {"k_id": "K1003", "score": 5, "title": "Third uncovered"},
            ],
            "missing_general_top5": [
                {
                    "k_id": "K2001",
                    "score": 6,
                    "title": "Needs general",
                    "already_covered_for": ["research"],
                }
            ],
            "missing_research_top5": [
                {
                    "k_id": "K3001",
                    "score": 5,
                    "title": "Needs research",
                    "already_covered_for": ["general"],
                }
            ],
        },
    )

    summary = summaries.build_publication_candidates_summary(storage_dir=str(storage_dir), limit=2)

    assert summary["available"] is True
    assert summary["total_k"] == 12
    assert summary["high_priority_uncovered"] == 2
    assert len(summary["top_uncovered"]) == 2
    assert summary["top_uncovered"][0]["k_id"] == "K1001"
    assert summary["missing_general"][0]["already_covered_for"] == ["research"]
    assert summary["missing_research"][0]["already_covered_for"] == ["general"]
    assert summary["source_age_hours"] is not None


def test_build_platform_patrol_summary_combines_existing_checks(monkeypatch):
    monkeypatch.setattr(
        summaries,
        "build_platform_cycle_summary",
        lambda storage_dir="storage", source="user", limit=5, write_latest=False: {
            "release_preview": {
                "mode": "scheduled",
                "due_now": True,
                "next_release_at": "2026-04-23T08:00:00+00:00",
                "pool_counts": {"draft": 4, "scheduled": 1, "eligible": 2},
                "next_candidates": [
                    {
                        "id": "mile_1",
                        "title": "Macro update",
                        "status": "scheduled",
                        "audience": "general",
                    }
                ],
            },
            "question_ranking": {
                "health": {
                    "pending_evaluation": 3,
                    "active_ranked": 7,
                    "candidate_pool": 11,
                }
            },
            "suggestions": ["內容池已到節奏釋出時間，可評估執行 release-pool-by-settings。"],
        },
    )
    monkeypatch.setattr(
        summaries,
        "build_alert_condition_report",
        lambda storage_dir="storage": {
            "breach_count": 1,
            "conditions": [
                {"id": "release_pool_gap", "level": "warn", "title": "Release pool cron gap > 2h", "breached": True},
                {"id": "draft_pool_low", "level": "info", "title": "Draft pool healthy", "breached": False},
            ],
        },
    )
    monkeypatch.setattr(
        summaries,
        "build_scheduler_summary",
        lambda storage_dir="storage": {
            "scheduler_last_tick_at": "2026-04-23T07:00:00+00:00",
            "scheduler_last_status": "ok",
            "scheduler_last_reason": None,
            "missing_system_task_count": 0,
            "queued_count": 2,
        },
    )
    monkeypatch.setattr(
        summaries,
        "health_snapshot",
        lambda storage_dir="storage": {
            "failed_supabase_syncs": 0,
            "open_questions": 5,
            "event_ledger_entries": 12,
            "rollback_points": 8,
            "agent_cli_health": {"status": "ready"},
        },
    )

    summary = summaries.build_platform_patrol_summary(limit=3)

    assert summary["release_due"] is True
    assert summary["alert_breach_count"] == 1
    assert summary["breached_alerts"][0]["id"] == "release_pool_gap"
    assert summary["scheduler"]["queued_count"] == 2
    assert summary["health"]["agent_cli_health"] == "ready"
    assert summary["pending_questions"] == 3
    assert summary["next_release_candidates"][0]["id"] == "mile_1"
    assert summary["detail_hints"]["maintain"].endswith("platform-patrol-maintain --stub-if-no-work")


def test_build_platform_patrol_maintenance_skips_when_no_signals(monkeypatch):
    monkeypatch.setattr(
        summaries,
        "build_platform_patrol_summary",
        lambda storage_dir="storage", source="user", limit=5: {
            "generated_at": "2026-04-23T08:00:00+00:00",
            "storage_dir": "storage",
            "release_due": False,
            "alert_breach_count": 0,
            "pending_questions": 0,
            "next_release_at": "2026-04-23T12:00:00+00:00",
            "breached_alerts": [],
            "next_release_candidates": [],
            "suggestions": ["平台狀態正常。"],
            "detail_hints": {"maintain": "uv run volpred ops platform-patrol-maintain --stub-if-no-work"},
        },
    )

    result = summaries.build_platform_patrol_maintenance(limit=3)

    assert result["skip"] is True
    assert result["action"] == "skip"
    assert result["trigger_reasons"] == []
    assert result["needs_followup"] is False


def test_build_platform_patrol_maintenance_requests_detail_when_signals_exist(monkeypatch):
    monkeypatch.setattr(
        summaries,
        "build_platform_patrol_summary",
        lambda storage_dir="storage", source="user", limit=5: {
            "generated_at": "2026-04-23T08:00:00+00:00",
            "storage_dir": "storage",
            "release_due": True,
            "alert_breach_count": 1,
            "pending_questions": 2,
            "next_release_at": "2026-04-23T12:00:00+00:00",
            "breached_alerts": [{"id": "release_pool_gap"}],
            "next_release_candidates": [{"id": "mile_1"}],
            "suggestions": ["需要下鑽細節。"],
            "detail_hints": {
                "alerts": "uv run volpred ops check-alerts",
                "cycle": "uv run volpred ops platform-cycle-summary --limit 3",
                "scheduler": "uv run volpred ops scheduler-summary",
                "logs": "uv run volpred ops log-summary",
            },
        },
    )

    result = summaries.build_platform_patrol_maintenance(limit=3)

    assert result["skip"] is False
    assert result["action"] == "inspect_detail"
    assert result["trigger_reasons"] == ["alert_breach", "release_due", "pending_questions"]
    assert result["needs_followup"] is True
    assert "uv run volpred ops check-alerts" in result["followup_commands"]
    assert "uv run volpred ops platform-cycle-summary --limit 3" in result["followup_commands"]
    assert "uv run volpred ops scheduler-summary" in result["followup_commands"]
    assert "uv run volpred ops log-summary" in result["followup_commands"]


def test_build_question_ops_summary_compacts_rerank_state(monkeypatch):
    monkeypatch.setattr(
        summaries,
        "get_member_question_ranking_summary",
        lambda source="user", limit=5: {
            "generated_at": "2026-04-23T08:00:00+00:00",
            "health": {
                "active_ranked": 4,
                "pending_evaluation": 2,
                "researching": 1,
                "answered": 8,
                "candidate_pool": 3,
                "latest_member_question_at": "2026-04-23T07:00:00+00:00",
                "latest_answered_at": "2026-04-22T07:00:00+00:00",
            },
            "ranked_table": [
                {
                    "rank": 1,
                    "question_id": "q1",
                    "proposer": "Alice",
                    "status": "researching",
                    "score": 9,
                    "linked_articles_count": 0,
                    "question": "How should I hedge?",
                }
            ],
            "pending_questions": [
                {
                    "question_id": "q2",
                    "proposer": "Bob",
                    "status": "pending",
                    "linked_articles_count": 1,
                    "created_at": "2026-04-23T06:00:00+00:00",
                    "question": "What about GLD?",
                }
            ],
            "candidate_pool": [
                {
                    "question_id": "q3",
                    "status": "queued",
                    "requested_by": "system",
                    "claimed_by": None,
                    "linked_articles_count": 0,
                }
            ],
            "suggestions": ["目前有 2 題待評分會員問題，可在下一次 6 小時評分週期生成 evaluation payload。"],
        },
    )

    summary = summaries.build_question_ops_summary(source="user", limit=3)

    assert summary["pending_questions"] == 2
    assert summary["active_ranked_questions"] == 4
    assert summary["researching_questions"] == 1
    assert summary["candidate_pool"] == 3
    assert summary["top_ranked"][0]["question_id"] == "q1"
    assert summary["pending_preview"][0]["question_id"] == "q2"
    assert summary["candidate_preview"][0]["question_id"] == "q3"
    assert summary["detail_hints"]["maintain"].endswith("question-ops-maintain --source user --auto-create-task --stub-if-no-work")
    assert summary["detail_hints"]["workflow"].endswith("--source user --limit 3")


def test_build_question_ops_maintenance_skips_without_pending_questions(monkeypatch):
    monkeypatch.setattr(
        summaries,
        "build_question_ops_summary",
        lambda source="user", limit=5: {
            "generated_at": "2026-04-23T08:00:00+00:00",
            "source": source,
            "pending_questions": 0,
            "active_ranked_questions": 4,
            "researching_questions": 1,
            "candidate_pool": 3,
            "pending_preview": [],
            "top_ranked": [{"question_id": "q1"}],
            "suggestions": ["目前沒有待評分問題。"],
            "detail_hints": {"workflow": "uv run volpred ops question-ranking-workflow --source user --limit 3"},
        },
    )

    result = summaries.build_question_ops_maintenance(source="user", limit=3)

    assert result["skip"] is True
    assert result["action"] == "skip"
    assert result["needs_followup"] is False
    assert result["followup_commands"] == []


def test_build_question_ops_maintenance_requests_workflow_when_pending(monkeypatch):
    monkeypatch.setattr(
        summaries,
        "build_question_ops_summary",
        lambda source="user", limit=5: {
            "generated_at": "2026-04-23T08:00:00+00:00",
            "source": source,
            "pending_questions": 2,
            "active_ranked_questions": 4,
            "researching_questions": 1,
            "candidate_pool": 3,
            "pending_preview": [{"question_id": "q2"}],
            "top_ranked": [{"question_id": "q1"}],
            "suggestions": ["目前有 2 題待評分。"],
            "detail_hints": {
                "workflow": "uv run volpred ops question-ranking-workflow --source user --limit 3",
                "rerank": "uv run volpred ops question-rerank --evaluations-json /path/to/evaluations.json",
            },
        },
    )

    result = summaries.build_question_ops_maintenance(source="user", limit=3)

    assert result["skip"] is False
    assert result["action"] == "load_workflow"
    assert result["needs_followup"] is True
    assert result["followup_commands"] == [
        "uv run volpred ops question-ranking-workflow --source user --limit 3",
        "uv run volpred ops question-rerank --evaluations-json /path/to/evaluations.json",
    ]


def test_build_memory_health_summary_flags_size_duplicates_and_orphans(tmp_path: Path, monkeypatch):
    storage_dir = tmp_path / "storage"
    memory_dir = storage_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        memory_dir / "knowledge.json",
        [
            {"id": "k1", "content": "same"},
            {"id": "k1", "content": "same"},
            {"id": "k2", "content": "other"},
        ],
    )
    _write_json(memory_dir / "thinking_journal.json", [{"id": "t1"}])
    _write_json(memory_dir / "experiment_experiences.json", [{"id": "e1"}])
    _write_json(memory_dir / "experiments.json", [{"id": "x1"}])

    worktrees_dir = tmp_path / ".claude" / "worktrees"
    (worktrees_dir / "agent-good").mkdir(parents=True, exist_ok=True)
    (worktrees_dir / "agent-good" / ".git").write_text("gitdir: /tmp/example\n", encoding="utf-8")
    (worktrees_dir / "agent-orphan").mkdir(parents=True, exist_ok=True)

    original_specs = summaries._memory_health_specs
    monkeypatch.setattr(
        summaries,
        "_memory_health_specs",
        lambda storage_dir="storage": [
            {
                **spec,
                "warn_bytes": 10 if spec["label"] == "knowledge" else spec["warn_bytes"],
                "danger_bytes": 1000 if spec["label"] == "knowledge" else spec["danger_bytes"],
            }
            for spec in original_specs(storage_dir=storage_dir)
        ],
    )
    monkeypatch.setattr(summaries, "_memory_health_worktrees_dir", lambda: worktrees_dir)

    summary = summaries.build_memory_health_summary(storage_dir=str(storage_dir))

    assert summary["overall_status"] == "warn"
    assert summary["knowledge_duplicates"]["duplicates"] == 1
    assert summary["worktrees"]["orphan_count"] == 1
    assert summary["highlights"]["knowledge"]["status"] == "warn"
    assert any("記憶檔偏大" in s for s in summary["suggestions"])
    assert any("重複" in s for s in summary["suggestions"])
    assert any("orphan" in s for s in summary["suggestions"])
