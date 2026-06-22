from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_platform_health_records_pending_task_read_warning(
    tmp_path, monkeypatch
) -> None:
    import work_summary_6h as ws  # type: ignore

    monkeypatch.setattr(ws, "STORAGE", tmp_path)
    (tmp_path / "next_tasks.json").write_text("{bad json", encoding="utf-8")

    alerts = ModuleType("volpred.ops.alerts")
    alerts.build_alert_condition_report = lambda: {"conditions": []}
    monkeypatch.setitem(sys.modules, "volpred.ops.alerts", alerts)

    health = ws._platform_health()

    assert health["pending_tasks"] is None
    assert any("pending tasks read failed" in w for w in health["warnings"])
    assert any("JSONDecodeError" in w for w in health["warnings"])


def test_build_html_renders_health_warnings(monkeypatch) -> None:
    import work_summary_6h as ws  # type: ignore

    monkeypatch.setattr(ws, "_commits_in_window", lambda: [])
    monkeypatch.setattr(ws, "_files_changed_in_window", lambda: {})
    monkeypatch.setattr(ws, "_work_log_entries", lambda: [])
    monkeypatch.setattr(ws, "_new_notifications", lambda: [])
    monkeypatch.setattr(ws, "_articles_in_window", lambda: {"published": [], "drafts": []})
    monkeypatch.setattr(ws, "_active_worktrees", lambda: [])
    monkeypatch.setattr(
        ws,
        "_platform_health",
        lambda: {
            "warnings": ["pending tasks read failed: JSONDecodeError: bad json"],
            "draft_count": 0,
            "published_total": 0,
            "release_interval_min": 180,
            "alert_breaches": 0,
            "alert_total_checked": 0,
            "pending_tasks": None,
        },
    )

    _, html_body, text_body = ws.build_html()

    assert "Health warnings" in html_body
    assert "pending tasks read failed" in html_body
    assert "- Health warnings:" in text_body
    assert "JSONDecodeError" in text_body
