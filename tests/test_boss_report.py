from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from scripts import audit_silent_fallbacks


def _load_module(name: str, rel_path: str):
    module_path = Path(__file__).resolve().parents[1] / rel_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


boss_report = _load_module("boss_report", "scripts/boss_report.py")


def test_boss_report_surfaces_next_tasks_parse_warning(tmp_path, monkeypatch) -> None:
    (tmp_path / "storage").mkdir(parents=True)
    (tmp_path / "storage" / "next_tasks.json").write_text("{bad json\n", encoding="utf-8")

    monkeypatch.setattr(boss_report, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(boss_report, "_dashboard", lambda: {"overall_status": "ok", "sections": []})
    monkeypatch.setattr(boss_report, "_commits_in_window", lambda: [])
    monkeypatch.setattr(boss_report, "_paper_portfolio", lambda: [])
    monkeypatch.setattr(boss_report, "_autonomous_decisions", lambda: [])
    monkeypatch.setattr(boss_report, "_next_actions", lambda: [])
    monkeypatch.setattr(boss_report, "_cycle_intent", lambda: {})
    monkeypatch.setattr(boss_report, "_blockers", lambda: [])
    monkeypatch.setattr(boss_report, "_cron_review", lambda: "ok")

    _, html_body, plain = boss_report.build_html()

    assert "Report generation warnings" in html_body
    assert "next_tasks read failed" in html_body
    assert "next_tasks read failed" in plain


def test_boss_report_has_no_bare_except_pass() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "boss_report.py"
    tree = ast.parse(script.read_text(encoding="utf-8"))

    offenders: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                offenders.append(node.lineno)

    assert offenders == []


def test_boss_report_has_no_silent_fallback_audit_findings() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "boss_report.py"

    findings = audit_silent_fallbacks.audit_file(script)

    assert findings == []


# ── daily-close collectors (ported 2026-07-20 WS-H2 from retired work_summary_6h;
#    coverage carried over from deleted tests/test_work_summary_6h_warnings.py) ──


def test_work_log_entries_warns_on_bad_json(tmp_path, monkeypatch) -> None:
    (tmp_path / "storage").mkdir(parents=True)
    (tmp_path / "storage" / "work_log.json").write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(boss_report, "PROJECT_ROOT", tmp_path)

    boss_report._REPORT_WARNINGS.clear()
    entries = boss_report._work_log_entries()

    assert entries == []
    assert any("work_log read failed" in w for w in boss_report._REPORT_WARNINGS)
    assert any("JSONDecodeError" in w for w in boss_report._REPORT_WARNINGS)


def test_articles_in_window_warns_on_bad_feed_schema(tmp_path, monkeypatch) -> None:
    reports = tmp_path / "storage" / "reports"
    reports.mkdir(parents=True)
    (reports / "feed.json").write_text('{"not": "a list"}', encoding="utf-8")
    monkeypatch.setattr(boss_report, "PROJECT_ROOT", tmp_path)

    boss_report._REPORT_WARNINGS.clear()
    articles = boss_report._articles_in_window()

    assert articles == {"published": [], "drafts": []}
    assert any("feed schema invalid" in w for w in boss_report._REPORT_WARNINGS)
    assert any("dict" in w for w in boss_report._REPORT_WARNINGS)


def test_daily_close_renders_day_close_sections(monkeypatch) -> None:
    monkeypatch.setattr(boss_report, "_dashboard", lambda: {"overall_status": "ok", "sections": []})
    monkeypatch.setattr(boss_report, "_commits_in_window", lambda: [])
    monkeypatch.setattr(boss_report, "_paper_portfolio", lambda: [])
    monkeypatch.setattr(boss_report, "_pending_tasks", lambda: {"total": 0, "by_type": {}, "by_priority": {}})
    monkeypatch.setattr(boss_report, "_autonomous_decisions", lambda: [])
    monkeypatch.setattr(boss_report, "_next_actions", lambda: [])
    monkeypatch.setattr(boss_report, "_cycle_intent", lambda: {})
    monkeypatch.setattr(boss_report, "_blockers", lambda: [])
    monkeypatch.setattr(boss_report, "_cron_review", lambda: "ok")
    monkeypatch.setattr(boss_report, "_files_changed_in_window", lambda: {"scripts/a.py": 3})
    monkeypatch.setattr(boss_report, "_work_log_entries", lambda: [{"task_type": "experiment", "summary": "K9999 done"}])
    monkeypatch.setattr(boss_report, "_new_notifications", lambda: [{"time": "12:00", "title": "t", "level": "info"}])
    monkeypatch.setattr(
        boss_report, "_articles_in_window",
        lambda: {"published": [{"id": "x", "title": "T", "ts": "10:00", "audience": "general"}], "drafts": []},
    )
    monkeypatch.setattr(boss_report, "_active_worktrees", lambda: ["agent-abc"])

    title, html_body, plain = boss_report.build_html(daily_close=True)

    assert "每日日結" in title
    assert "Mission 5" in html_body
    assert "agent-abc" in html_body
    assert "scripts/a.py" in html_body
    assert "Daily close (24h)" in plain
    assert "published=1" in plain


def test_plain_edition_skips_day_close_sections(monkeypatch) -> None:
    monkeypatch.setattr(boss_report, "_dashboard", lambda: {"overall_status": "ok", "sections": []})
    monkeypatch.setattr(boss_report, "_commits_in_window", lambda: [])
    monkeypatch.setattr(boss_report, "_paper_portfolio", lambda: [])
    monkeypatch.setattr(boss_report, "_pending_tasks", lambda: {"total": 0, "by_type": {}, "by_priority": {}})
    monkeypatch.setattr(boss_report, "_autonomous_decisions", lambda: [])
    monkeypatch.setattr(boss_report, "_next_actions", lambda: [])
    monkeypatch.setattr(boss_report, "_cycle_intent", lambda: {})
    monkeypatch.setattr(boss_report, "_blockers", lambda: [])
    monkeypatch.setattr(boss_report, "_cron_review", lambda: "ok")

    called = []
    monkeypatch.setattr(boss_report, "_articles_in_window", lambda: called.append("articles"))

    title, html_body, plain = boss_report.build_html(daily_close=False)

    assert called == []  # day-close collectors must not run on the 4h editions
    assert "日結" not in html_body
    assert "Daily close" not in plain


def test_configure_window_moves_since() -> None:
    boss_report._configure_window(24.0)
    try:
        assert boss_report.WINDOW.total_seconds() == 24 * 3600
        assert boss_report.SINCE == boss_report.NOW - boss_report.WINDOW
    finally:
        boss_report._configure_window(4.0)
