from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "work_dashboard_server.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("work_dashboard_server_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _point_sources_at_tmp(module, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(module, "NEXT_TASKS", tmp_path / "next_tasks.json")
    monkeypatch.setattr(module, "DASHBOARD", tmp_path / "dashboard_latest.json")
    monkeypatch.setattr(module, "SCHEDULES", tmp_path / "runtime_schedules.json")
    monkeypatch.setattr(module, "CRON_LAST", tmp_path / "cron_last_run.json")
    monkeypatch.setattr(module, "FEED", tmp_path / "feed.json")
    monkeypatch.setattr(module, "RELEASE", tmp_path / ".release_settings.json")
    monkeypatch.setattr(module, "CRON_LOG_DIR", tmp_path / "cron")
    monkeypatch.setattr(module, "_daemon_alive", lambda _label, *args, **kwargs: False)
    monkeypatch.setattr(module, "_proc_count", lambda _pattern, *args, **kwargs: 0)
    monkeypatch.setattr(module, "_git_recent", lambda *args, **kwargs: [])


def test_build_work_reports_json_source_warning(tmp_path, monkeypatch, capsys) -> None:
    dashboard = _load_module()
    _point_sources_at_tmp(dashboard, tmp_path, monkeypatch)
    (tmp_path / "next_tasks.json").write_text("{bad json", encoding="utf-8")

    payload = dashboard.build_work()

    assert payload["counts"] == {}
    assert payload["health"]["warning_count"] == 1
    assert "next_tasks.json" in payload["warnings"][0]
    assert "JSONDecodeError" in payload["warnings"][0]
    assert "[work_dashboard] WARN" in capsys.readouterr().err


def test_build_work_reports_non_list_feed_warning(tmp_path, monkeypatch) -> None:
    dashboard = _load_module()
    _point_sources_at_tmp(dashboard, tmp_path, monkeypatch)
    (tmp_path / "next_tasks.json").write_text("[]", encoding="utf-8")
    (tmp_path / "feed.json").write_text('{"items": []}', encoding="utf-8")

    payload = dashboard.build_work()

    assert payload["content"]["published"] == 0
    assert payload["content"]["draft"] == 0
    assert payload["health"]["warning_count"] == 1
    assert "feed is not a list" in payload["warnings"][0]


def test_work_dashboard_probe_helpers_warn_on_fail_open(monkeypatch, capsys) -> None:
    dashboard = _load_module()

    def boom(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="probe", timeout=5)

    monkeypatch.setattr(dashboard.subprocess, "run", boom)
    warnings: list[str] = []

    assert dashboard._daemon_alive("com.volpred.test", warnings) is False
    assert dashboard._proc_count("codex_loop.sh", warnings) == -1
    assert dashboard._git_recent(warnings=warnings) == []

    assert len(warnings) == 3
    assert "launchctl daemon probe failed" in warnings[0]
    assert "process-count probe failed" in warnings[1]
    assert "git recent commits read failed" in warnings[2]
    assert capsys.readouterr().err.count("[work_dashboard] WARN") == 3


def test_work_dashboard_cron_parse_warns_on_fail_open(capsys) -> None:
    dashboard = _load_module()
    warnings: list[str] = []

    assert dashboard._next_fire_dt("not a cron", warnings, "bad_job") is None

    assert len(warnings) == 1
    assert "cron next-fire parse failed job=bad_job" in warnings[0]
    assert "[work_dashboard] WARN" in capsys.readouterr().err
