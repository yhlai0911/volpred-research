from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from datetime import UTC, datetime
from types import ModuleType

import pytest


def _load_module(name: str, rel_path: str):
    module_path = Path(__file__).resolve().parents[1] / rel_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


ops_dashboard = _load_module("ops_dashboard", "scripts/ops_dashboard.py")
audit_fb_pipeline = _load_module("audit_fb_pipeline", "scripts/audit_fb_pipeline.py")
mark_fb_post_status = _load_module("mark_fb_post_status", "scripts/mark_fb_post_status.py")
fb_page_post = _load_module("fb_page_post", "scripts/fb_page_post.py")


def test_classify_fb_pipeline_separates_awaiting_interactive() -> None:
    actionable, awaiting = ops_dashboard.classify_fb_pipeline(
        [
            {"mile_id": "mile_pending", "fb_post_status": "pending"},
            {"mile_id": "mile_wait", "fb_post_status": "awaiting_interactive_session"},
            {"mile_id": "mile_done", "fb_post_status": "success"},
        ]
    )

    assert [item["mile_id"] for item in actionable] == ["mile_pending"]
    assert [item["mile_id"] for item in awaiting] == ["mile_wait"]


def test_ops_dashboard_jl_warns_on_json_read_failure(tmp_path, capsys) -> None:
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("{bad json", encoding="utf-8")

    assert ops_dashboard.jl(bad_path, default={"fallback": True}) == {"fallback": True}

    captured = capsys.readouterr()
    assert "[ops_dashboard] WARN JSON read failed" in captured.out
    assert "bad.json" in captured.out
    assert "JSONDecodeError" in captured.out


def test_ops_dashboard_returns_zero_even_when_sections_are_critical(tmp_path, monkeypatch) -> None:
    repo = tmp_path
    (repo / "storage" / "reports").mkdir(parents=True)
    (repo / "storage" / "ops").mkdir(parents=True)
    (repo / "storage" / "notifications").mkdir(parents=True)
    (repo / "config").mkdir(parents=True)

    (repo / "storage" / "next_tasks.json").write_text("[]\n", encoding="utf-8")
    (repo / "storage" / "reports" / "feed.json").write_text("[]\n", encoding="utf-8")
    (repo / "storage" / "ops" / "cron_last_run.json").write_text("{}\n", encoding="utf-8")
    (repo / "storage" / "reports" / "trending_repost_log.json").write_text("[]\n", encoding="utf-8")
    (repo / "config" / "runtime_schedules.json").write_text('{"system_crontab":{"items":[]}}\n', encoding="utf-8")
    recent = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    (repo / "storage" / "notifications" / "notification_log.json").write_text(
        json.dumps([{"timestamp": recent, "level": "critical", "subject": "boom"}], ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(ops_dashboard, "REPO", repo)
    monkeypatch.setattr(ops_dashboard, "http_ok", lambda url, timeout=8: False)

    rc = ops_dashboard.main()
    assert rc == 0


def test_ops_dashboard_health_alerts_reflect_current_breaches_not_old_notifications(tmp_path, monkeypatch) -> None:
    repo = tmp_path
    (repo / "storage" / "reports").mkdir(parents=True)
    (repo / "storage" / "ops").mkdir(parents=True)
    (repo / "storage" / "notifications").mkdir(parents=True)
    (repo / "config").mkdir(parents=True)

    (repo / "storage" / "next_tasks.json").write_text("[]\n", encoding="utf-8")
    (repo / "storage" / "reports" / "feed.json").write_text("[]\n", encoding="utf-8")
    (repo / "storage" / "ops" / "cron_last_run.json").write_text("{}\n", encoding="utf-8")
    (repo / "storage" / "reports" / "trending_repost_log.json").write_text("[]\n", encoding="utf-8")
    (repo / "config" / "runtime_schedules.json").write_text('{"system_crontab":{"items":[]}}\n', encoding="utf-8")
    (repo / "storage" / "notifications" / "notification_log.json").write_text(
        json.dumps(
            [{"timestamp": "2026-05-29T01:11:00", "level": "critical", "subject": "old alert", "resolved_at": None}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(ops_dashboard, "REPO", repo)
    monkeypatch.setattr(ops_dashboard, "http_ok", lambda url, timeout=8: True)
    monkeypatch.setattr(
        ops_dashboard,
        "build_alert_condition_report",
        lambda storage_dir="storage": {"conditions": [], "breach_count": 0},
    )

    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ops_dashboard.main()
    payload = json.loads(buf.getvalue())
    health_section = next(s for s in payload["sections"] if s["section"] == "health_alerts_unhandled")

    assert rc == 0
    assert health_section["status"] == "ok"
    assert health_section["breaches"] == []


def test_ops_dashboard_writes_latest_snapshot(tmp_path, monkeypatch) -> None:
    repo = tmp_path
    (repo / "storage" / "reports").mkdir(parents=True)
    (repo / "storage" / "ops").mkdir(parents=True)
    (repo / "storage" / "notifications").mkdir(parents=True)
    (repo / "config").mkdir(parents=True)

    (repo / "storage" / "next_tasks.json").write_text("[]\n", encoding="utf-8")
    (repo / "storage" / "reports" / "feed.json").write_text("[]\n", encoding="utf-8")
    (repo / "storage" / "ops" / "cron_last_run.json").write_text("{}\n", encoding="utf-8")
    (repo / "storage" / "reports" / "trending_repost_log.json").write_text("[]\n", encoding="utf-8")
    (repo / "storage" / "notifications" / "notification_log.json").write_text("[]\n", encoding="utf-8")
    (repo / "config" / "runtime_schedules.json").write_text('{"system_crontab":{"items":[]}}\n', encoding="utf-8")

    monkeypatch.setattr(ops_dashboard, "REPO", repo)
    monkeypatch.setattr(ops_dashboard, "http_ok", lambda url, timeout=8: True)
    monkeypatch.setattr(
        ops_dashboard,
        "build_alert_condition_report",
        lambda storage_dir="storage": {"conditions": [], "breach_count": 0},
    )

    rc = ops_dashboard.main()

    latest = json.loads((repo / "storage" / "ops" / "dashboard_latest.json").read_text(encoding="utf-8"))
    assert rc == 0
    assert latest["generated_by"] == "scripts/ops_dashboard.py"
    assert latest["age_seconds"] == 0
    assert latest["overall_status"] in {"ok", "warn", "critical"}


def test_ops_dashboard_supabase_query_failure_is_unavailable_not_missing(tmp_path, monkeypatch) -> None:
    repo = tmp_path
    (repo / "storage" / "reports").mkdir(parents=True)
    (repo / "storage" / "ops").mkdir(parents=True)
    (repo / "storage" / "notifications").mkdir(parents=True)
    (repo / "config").mkdir(parents=True)

    (repo / "storage" / "next_tasks.json").write_text("[]\n", encoding="utf-8")
    (repo / "storage" / "reports" / "feed.json").write_text(
        json.dumps(
            [
                {
                    "id": "mile_recent",
                    "status": "published",
                    "published_at": "2999-01-01T00:00:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (repo / "storage" / "ops" / "cron_last_run.json").write_text("{}\n", encoding="utf-8")
    (repo / "storage" / "reports" / "trending_repost_log.json").write_text("[]\n", encoding="utf-8")
    (repo / "storage" / "notifications" / "notification_log.json").write_text("[]\n", encoding="utf-8")
    (repo / "config" / "runtime_schedules.json").write_text('{"system_crontab":{"items":[]}}\n', encoding="utf-8")

    def fail_urlopen(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(ops_dashboard, "REPO", repo)
    monkeypatch.setattr(ops_dashboard, "load_env", lambda: {"SUPABASE_URL": "https://example.invalid", "SUPABASE_KEY": "k"})
    monkeypatch.setattr(ops_dashboard, "http_ok", lambda url, timeout=8: True)
    monkeypatch.setattr(ops_dashboard.request, "urlopen", fail_urlopen)
    monkeypatch.setattr(
        ops_dashboard,
        "build_alert_condition_report",
        lambda storage_dir="storage": {"conditions": [], "breach_count": 0},
    )

    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ops_dashboard.main()
    payload = json.loads(buf.getvalue())
    section = next(s for s in payload["sections"] if s["section"] == "distribution_supabase")

    assert rc == 0
    assert section["status"] == "warn"
    assert section["tldr"].startswith("parity check unavailable")
    assert section["next"] == "fix Supabase env/connectivity before running sync remediation"
    assert "missing" not in section


def test_ops_dashboard_health_cron_surfaces_croniter_failure(tmp_path, monkeypatch) -> None:
    repo = tmp_path
    (repo / "storage" / "reports").mkdir(parents=True)
    (repo / "storage" / "ops").mkdir(parents=True)
    (repo / "storage" / "notifications").mkdir(parents=True)
    (repo / "config").mkdir(parents=True)

    recent = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    (repo / "storage" / "next_tasks.json").write_text("[]\n", encoding="utf-8")
    (repo / "storage" / "reports" / "feed.json").write_text("[]\n", encoding="utf-8")
    (repo / "storage" / "ops" / "cron_last_run.json").write_text(
        json.dumps({"collect_us_data": recent}, ensure_ascii=False),
        encoding="utf-8",
    )
    (repo / "storage" / "reports" / "trending_repost_log.json").write_text("[]\n", encoding="utf-8")
    (repo / "storage" / "notifications" / "notification_log.json").write_text("[]\n", encoding="utf-8")
    (repo / "config" / "runtime_schedules.json").write_text(
        json.dumps(
            {"system_crontab": {"items": [{"id": "collect_us_data", "cron": "* * * * *"}]}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    fake_croniter = ModuleType("croniter")

    def fail_croniter(*args, **kwargs):
        raise RuntimeError("cron parser down")

    fake_croniter.croniter = fail_croniter
    monkeypatch.setitem(sys.modules, "croniter", fake_croniter)
    monkeypatch.setattr(ops_dashboard, "REPO", repo)
    monkeypatch.setattr(ops_dashboard, "http_ok", lambda url, timeout=8: True)
    monkeypatch.setattr(
        ops_dashboard,
        "build_alert_condition_report",
        lambda storage_dir="storage": {"conditions": [], "breach_count": 0},
    )

    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ops_dashboard.main()
    payload = json.loads(buf.getvalue())
    section = next(s for s in payload["sections"] if s["section"] == "health_cron")

    assert rc == 0
    assert any(
        warning["job"] == "collect_us_data"
        and warning["source"] == "croniter"
        and "cron parser down" in warning["error"]
        for warning in section["warnings"]
    )


def test_ops_dashboard_production_pending_counts_pending_main_thread(tmp_path, monkeypatch) -> None:
    repo = tmp_path
    (repo / "storage" / "reports").mkdir(parents=True)
    (repo / "storage" / "ops").mkdir(parents=True)
    (repo / "storage" / "notifications").mkdir(parents=True)
    (repo / "config").mkdir(parents=True)

    tasks = [
        {"id": "t1", "status": "pending_main_thread", "task_type": "paper_review"},
        {"id": "t2", "status": "pending_main_thread", "task_type": "paper_body"},
    ]
    (repo / "storage" / "next_tasks.json").write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
    (repo / "storage" / "reports" / "feed.json").write_text("[]\n", encoding="utf-8")
    (repo / "storage" / "ops" / "cron_last_run.json").write_text("{}\n", encoding="utf-8")
    (repo / "storage" / "reports" / "trending_repost_log.json").write_text("[]\n", encoding="utf-8")
    (repo / "storage" / "notifications" / "notification_log.json").write_text("[]\n", encoding="utf-8")
    (repo / "config" / "runtime_schedules.json").write_text('{"system_crontab":{"items":[]}}\n', encoding="utf-8")

    monkeypatch.setattr(ops_dashboard, "REPO", repo)
    monkeypatch.setattr(ops_dashboard, "http_ok", lambda url, timeout=8: True)
    monkeypatch.setattr(
        ops_dashboard,
        "build_alert_condition_report",
        lambda storage_dir="storage": {"conditions": [], "breach_count": 0},
    )

    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ops_dashboard.main()
    payload = json.loads(buf.getvalue())
    section = next(s for s in payload["sections"] if s["section"] == "production_pending")

    assert rc == 0
    assert section["status"] == "warn"
    assert section["pending_count"] == 0
    assert section["pending_main_thread_count"] == 2


def test_ops_dashboard_marks_claude_only_pending_hint(tmp_path, monkeypatch) -> None:
    repo = tmp_path
    (repo / "storage" / "reports").mkdir(parents=True)
    (repo / "storage" / "ops").mkdir(parents=True)
    (repo / "storage" / "notifications").mkdir(parents=True)
    (repo / "config").mkdir(parents=True)

    tasks = [
        {"id": "trend-1", "status": "pending", "task_type": "trending_repost"},
    ]
    (repo / "storage" / "next_tasks.json").write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
    (repo / "storage" / "reports" / "feed.json").write_text("[]\n", encoding="utf-8")
    (repo / "storage" / "ops" / "cron_last_run.json").write_text("{}\n", encoding="utf-8")
    (repo / "storage" / "reports" / "trending_repost_log.json").write_text("[]\n", encoding="utf-8")
    (repo / "storage" / "notifications" / "notification_log.json").write_text("[]\n", encoding="utf-8")
    (repo / "config" / "runtime_schedules.json").write_text('{"system_crontab":{"items":[]}}\n', encoding="utf-8")

    monkeypatch.setattr(ops_dashboard, "REPO", repo)
    monkeypatch.setattr(ops_dashboard, "http_ok", lambda url, timeout=8: True)
    monkeypatch.setattr(
        ops_dashboard,
        "build_alert_condition_report",
        lambda storage_dir="storage": {"conditions": [], "breach_count": 0},
    )

    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ops_dashboard.main()
    payload = json.loads(buf.getvalue())
    section = next(s for s in payload["sections"] if s["section"] == "production_pending")

    assert rc == 0
    assert section["status"] == "warn"
    assert section["pending_count"] == 1
    assert section["pending_claude_only_count"] == 1
    assert "Claude-only" in section["next"]


def test_audit_terminal_or_handoff_statuses_include_interactive() -> None:
    assert "awaiting_interactive_session" in audit_fb_pipeline.TERMINAL_OR_HANDOFF_STATUSES


def test_audit_auto_expires_stale_pending_and_handoff_statuses(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, cwd=None, check=False, capture_output=False):
        calls.append(cmd)

    monkeypatch.setattr(audit_fb_pipeline.subprocess, "run", fake_run)

    expired = audit_fb_pipeline._auto_expire_stale_pending(
        [
            {
                "mile_id": "mile_permission",
                "fb_post_status": "pending_permission_denied",
                "date": "2026-06-18",
            },
            {
                "mile_id": "mile_wait",
                "fb_post_status": "awaiting_interactive_session",
                "date": "2026-06-18",
            },
            {
                "mile_id": "mile_recent",
                "fb_post_status": "pending",
                "date": "2026-06-21T10:00:00",
            },
            {
                "mile_id": "mile_done",
                "fb_post_status": "success",
                "date": "2026-06-18",
            },
        ],
        "2026-06-19T00:00:00",
    )

    assert [item["mile_id"] for item in expired] == ["mile_permission", "mile_wait"]
    assert len(calls) == 2
    assert all("--status" in call and "expired_skip" in call for call in calls)


def test_audit_load_entries_warns_on_bad_trending_log(tmp_path, monkeypatch, capsys) -> None:
    log_path = tmp_path / "trending_repost_log.json"
    feed_path = tmp_path / "feed.json"
    log_path.write_text("{bad json", encoding="utf-8")
    feed_path.write_text(
        json.dumps(
            [{"id": "mile_feed", "fb_post_status": "awaiting_interactive_session"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(audit_fb_pipeline, "LOG", log_path)
    monkeypatch.setattr(audit_fb_pipeline, "FEED", feed_path)

    entries = audit_fb_pipeline._load_entries()

    assert [entry["mile_id"] for entry in entries] == ["mile_feed"]
    captured = capsys.readouterr()
    assert "[audit_fb_pipeline] WARN trending_repost_log JSON read failed" in captured.err
    assert "JSONDecodeError" in captured.err


def test_audit_load_entries_warns_on_bad_feed_json(tmp_path, monkeypatch, capsys) -> None:
    log_path = tmp_path / "trending_repost_log.json"
    feed_path = tmp_path / "feed.json"
    log_path.write_text(
        json.dumps([{"mile_id": "mile_log", "fb_post_status": "pending"}], ensure_ascii=False),
        encoding="utf-8",
    )
    feed_path.write_text("{bad json", encoding="utf-8")

    monkeypatch.setattr(audit_fb_pipeline, "LOG", log_path)
    monkeypatch.setattr(audit_fb_pipeline, "FEED", feed_path)

    entries = audit_fb_pipeline._load_entries()

    assert [entry["mile_id"] for entry in entries] == ["mile_log"]
    captured = capsys.readouterr()
    assert "[audit_fb_pipeline] WARN feed JSON read failed" in captured.err
    assert "JSONDecodeError" in captured.err


def test_audit_load_entries_warns_on_bad_feed_entry(tmp_path, monkeypatch, capsys) -> None:
    log_path = tmp_path / "trending_repost_log.json"
    feed_path = tmp_path / "feed.json"
    log_path.write_text("[]", encoding="utf-8")
    feed_path.write_text(
        json.dumps(
            ["bad-entry", {"id": "mile_feed", "fb_post_status": "pending"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(audit_fb_pipeline, "LOG", log_path)
    monkeypatch.setattr(audit_fb_pipeline, "FEED", feed_path)

    entries = audit_fb_pipeline._load_entries()

    assert [entry["mile_id"] for entry in entries] == ["mile_feed"]
    captured = capsys.readouterr()
    assert "[audit_fb_pipeline] WARN feed entry schema invalid" in captured.err
    assert "index=0" in captured.err


def test_mark_fb_post_status_updates_feed_and_log(tmp_path, monkeypatch) -> None:
    feed_path = tmp_path / "feed.json"
    log_path = tmp_path / "trending_repost_log.json"
    feed_path.write_text(
        json.dumps([{"id": "mile_abc", "fb_post_status": None}], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    log_path.write_text(
        json.dumps([{"mile_id": "mile_abc", "fb_post_status": "pending"}], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(mark_fb_post_status, "FEED_PATH", feed_path)
    monkeypatch.setattr(mark_fb_post_status, "TRENDING_LOG_PATH", log_path)

    result = mark_fb_post_status.update_fb_status(
        "mile_abc",
        status="awaiting_interactive_session",
        note="Needs Chrome MCP session",
    )

    assert result["updated_feed"] == 1
    assert result["updated_log"] == 1
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    log = json.loads(log_path.read_text(encoding="utf-8"))
    assert feed[0]["fb_post_status"] == "awaiting_interactive_session"
    assert log[0]["fb_post_status"] == "awaiting_interactive_session"
    assert feed[0]["fb_post_note"] == "Needs Chrome MCP session"
    assert log[0]["fb_post_note"] == "Needs Chrome MCP session"


def test_fb_page_graph_api_script_is_withdrawn() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "fb_page_post.py"
    result = subprocess.run(
        [sys.executable, str(script), "--dry-run", "--message", "hello"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "permanently withdrawn" in result.stderr
    assert "fb_pipeline_permanent_fix.md" in result.stderr


def test_fb_page_graph_api_direct_call_is_withdrawn() -> None:
    with pytest.raises(SystemExit) as excinfo:
        fb_page_post.post_article("message", "https://example.com", "token", "page_id")

    assert "permanently withdrawn" in str(excinfo.value)


def test_active_fb_guidance_does_not_recommend_page_graph_api() -> None:
    repo = Path(__file__).resolve().parents[1]
    active_paths = [
        repo / "docs" / "boss_direction_recommendations.md",
        repo / "docs" / "fb_post_handoff_2026_05_18.md",
        repo / "scripts" / "audit_fb_pipeline.py",
    ]
    forbidden_phrases = [
        "OR FB Page + Graph API",
        "pivot to FB Page + Graph API",
        "Page（可用 Graph API 自動發）",
        "VolPred FB Page + Graph API",
    ]

    for path in active_paths:
        text = path.read_text(encoding="utf-8")
        found = [phrase for phrase in forbidden_phrases if phrase in text]
        assert found == [], f"{path} still recommends withdrawn FB Page/Graph flow: {found}"
