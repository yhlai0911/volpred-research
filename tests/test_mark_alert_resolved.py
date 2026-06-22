from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "mark_alert_resolved.py"
SPEC = importlib.util.spec_from_file_location("mark_alert_resolved", MODULE_PATH)
mark_alert_resolved = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mark_alert_resolved)


def test_non_object_notification_log_entry_warns_and_skips(tmp_path, monkeypatch, capsys) -> None:
    log_path = tmp_path / "notification_log.json"
    log_path.write_text(
        json.dumps(
            [
                "bad-entry",
                {
                    "timestamp": "2026-06-23T01:00:00+00:00",
                    "level": "warn",
                    "subject": "hourly-dispatch failed",
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mark_alert_resolved, "LOG", log_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mark_alert_resolved.py",
            "--subject-contains",
            "hourly-dispatch",
            "--note",
            "dry run",
            "--dry-run",
        ],
    )

    rc = mark_alert_resolved.main()

    assert rc == 0
    captured = capsys.readouterr()
    assert "[mark_alert_resolved] WARN non-object notification log entry" in captured.err
    assert "index=0" in captured.err
    assert "type=str" in captured.err
    payload = json.loads(captured.out)
    assert payload["dry_run"] is True
    assert payload["would_resolve"] == 1
    assert payload["entries"][0]["subject"] == "hourly-dispatch failed"
