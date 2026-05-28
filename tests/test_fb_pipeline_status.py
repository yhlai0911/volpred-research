from __future__ import annotations

import importlib.util
import json
from pathlib import Path


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


def test_audit_terminal_or_handoff_statuses_include_interactive() -> None:
    assert "awaiting_interactive_session" in audit_fb_pipeline.TERMINAL_OR_HANDOFF_STATUSES


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
