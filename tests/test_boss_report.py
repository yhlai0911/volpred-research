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
