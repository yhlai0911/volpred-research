from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "unblock_expired_blocked_tasks.py"
SPEC = importlib.util.spec_from_file_location("unblock_expired_blocked_tasks", MODULE_PATH)
unblock_expired_blocked_tasks = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(unblock_expired_blocked_tasks)


def test_invalid_blocked_until_warns_and_stays_blocked(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "blocked_bad_until",
                    "task_type": "platform_ops",
                    "status": "blocked",
                    "blocked_reason": "awaiting_event_window",
                    "blocked_until": "!!!",
                    "blocked_note": "bad metadata should not unblock",
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(unblock_expired_blocked_tasks, "PATH", next_tasks)

    rc = unblock_expired_blocked_tasks.main(apply=True)

    assert rc == 0
    captured = capsys.readouterr()
    assert "[unblock] WARN invalid blocked_until; keeping task blocked" in captured.err
    assert "task_id=blocked_bad_until" in captured.err
    assert "blocked_until='!!!'" in captured.err
    assert "[unblock] applied: 0 tasks" in captured.out
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "blocked"
    assert saved[0]["blocked_reason"] == "awaiting_event_window"
    assert saved[0]["blocked_until"] == "!!!"


def test_apply_unblocks_expired_iso_timestamp(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "blocked_expired",
                    "task_type": "platform_ops",
                    "status": "blocked",
                    "blocked_reason": "awaiting_event_window",
                    "blocked_at": "2026-01-01T00:00:00+00:00",
                    "blocked_until": "2000-01-01T00:00:00+00:00",
                    "blocked_note": "expired",
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(unblock_expired_blocked_tasks, "PATH", next_tasks)

    rc = unblock_expired_blocked_tasks.main(apply=True)

    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "[unblock] applied: 1 tasks" in captured.out
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "pending"
    assert "blocked_reason" not in saved[0]
    assert "blocked_at" not in saved[0]
    assert "blocked_until" not in saved[0]
    assert "blocked_note" not in saved[0]
    assert saved[0]["status_history"][-1]["from"] == "blocked"
    assert saved[0]["status_history"][-1]["to"] == "pending"
