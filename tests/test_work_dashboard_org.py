"""Dashboard org view: the operating surface for the department architecture.

Hermetic — every source points at tmp_path, never at canonical storage/org.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO / "scripts" / "work_dashboard_server.py"
ORG_ADMIN = REPO / "scripts" / "org" / "org_admin.py"
DEPT_SEND = REPO / "scripts" / "org" / "dept_send.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("work_dashboard_org_module", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _org(tmp_path: Path) -> Path:
    """Build a real org via the canonical CLI, so the view is tested against real layout."""
    root = tmp_path / "org"
    assert subprocess.run(
        [sys.executable, str(ORG_ADMIN), "--root", str(root), "init"],
        capture_output=True, text=True,
    ).returncode == 0
    assert subprocess.run(
        [sys.executable, str(ORG_ADMIN), "--root", str(root), "create", "content",
         "--title", "內容部", "--task-types", "daily_article"],
        capture_output=True, text=True,
    ).returncode == 0
    return root


def test_uninitialized_org_is_not_a_warning(tmp_path, monkeypatch) -> None:
    dashboard = _load_module()
    monkeypatch.setattr(dashboard, "ORG_ROOT", tmp_path / "nope")
    warnings: list[str] = []

    org = dashboard.build_org(warnings)

    assert org["available"] is False
    assert warnings == [], "an org that was never initialized is a valid state, not a fault"


def test_malformed_registry_warns(tmp_path, monkeypatch) -> None:
    dashboard = _load_module()
    root = tmp_path / "org"
    root.mkdir()
    (root / "registry.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(dashboard, "ORG_ROOT", root)
    warnings: list[str] = []

    org = dashboard.build_org(warnings)

    assert org["available"] is False
    assert len(warnings) >= 1


def test_departments_and_inbox_depth_surface(tmp_path, monkeypatch) -> None:
    dashboard = _load_module()
    root = _org(tmp_path)
    monkeypatch.setattr(dashboard, "ORG_ROOT", root)
    warnings: list[str] = []

    org = dashboard.build_org(warnings)
    assert org["available"] is True
    assert [d["name"] for d in org["departments"]] == ["content"]
    content = org["departments"][0]
    assert content["title"] == "內容部"
    assert content["inbox"] == 0
    assert content["last_run"] == "未執行"
    assert content["task_types"] == ["daily_article"]

    assert subprocess.run(
        [sys.executable, str(DEPT_SEND), "content", "--root", str(root),
         "--from", "manager", "--task", "寫每日文章"],
        capture_output=True, text=True,
    ).returncode == 0

    org = dashboard.build_org(warnings)
    assert org["departments"][0]["inbox"] == 1, "a queued work item must be visible on the dashboard"
    assert warnings == []


def test_retired_department_is_hidden(tmp_path, monkeypatch) -> None:
    dashboard = _load_module()
    root = _org(tmp_path)
    assert subprocess.run(
        [sys.executable, str(ORG_ADMIN), "--root", str(root), "retire", "content", "--reason", "t"],
        capture_output=True, text=True,
    ).returncode == 0
    monkeypatch.setattr(dashboard, "ORG_ROOT", root)

    org = dashboard.build_org([])

    assert org["departments"] == []


def test_manager_gate_receipt_surfaces(tmp_path, monkeypatch) -> None:
    dashboard = _load_module()
    root = _org(tmp_path)
    receipt = root / "receipts" / "20260805T000000Z_shadow_manager_skip.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({
        "kind": "shadow_manager_skip", "fire": False, "reasons": [],
        "at": "2026-08-05T00:00:00Z",
    }), encoding="utf-8")
    monkeypatch.setattr(dashboard, "ORG_ROOT", root)

    org = dashboard.build_org([])

    assert org["manager"]["gate"]["kind"] == "shadow_manager_skip"
    assert org["manager"]["gate"]["fire"] is False


def test_daemon_job_without_cron_does_not_warn(tmp_path, monkeypatch) -> None:
    """A resident daemon has no cron by design — parsing it produced a false warning."""
    dashboard = _load_module()
    for name in ("NEXT_TASKS", "DASHBOARD", "CRON_LAST", "FEED", "RELEASE"):
        monkeypatch.setattr(dashboard, name, tmp_path / f"{name.lower()}.json")
    monkeypatch.setattr(dashboard, "CRON_LOG_DIR", tmp_path / "cron")
    monkeypatch.setattr(dashboard, "ORG_ROOT", tmp_path / "org")
    monkeypatch.setattr(dashboard, "_daemon_alive", lambda *a, **k: False)
    monkeypatch.setattr(dashboard, "_proc_count", lambda *a, **k: 0)
    monkeypatch.setattr(dashboard, "_git_recent", lambda *a, **k: [])
    sched = tmp_path / "runtime_schedules.json"
    sched.write_text(json.dumps({"system_crontab": {"items": [
        {"id": "telegram_poll", "cron": None, "label": "long-poll daemon"},
        {"id": "hourly", "cron": "0 * * * *", "label": "hourly job"},
    ]}}), encoding="utf-8")
    monkeypatch.setattr(dashboard, "SCHEDULES", sched)

    payload = dashboard.build_work()

    daemon_tile = next(s for s in payload["schedule"] if s["id"] == "telegram_poll")
    assert daemon_tile["cron"] == "daemon"
    assert daemon_tile["next_tw"] == "常駐"
    assert not any("telegram_poll" in w for w in payload["warnings"])
