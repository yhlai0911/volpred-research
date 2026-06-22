from __future__ import annotations

import json
import sys
import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "mark_task_blocked.py"
SPEC = importlib.util.spec_from_file_location("mark_task_blocked", MODULE_PATH)
mark_task_blocked = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mark_task_blocked)


def test_valid_reasons_includes_awaiting_interactive_session() -> None:
    assert "awaiting_interactive_session" in mark_task_blocked.VALID_REASONS


def test_mark_task_blocked_sets_awaiting_interactive_session(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "fb_post_example",
                    "status": "pending",
                }
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mark_task_blocked, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mark_task_blocked.py",
            "--id",
            "fb_post_example",
            "--reason",
            "awaiting_interactive_session",
            "--note",
            "Needs logged-in Chrome session",
        ],
    )

    rc = mark_task_blocked.main()

    assert rc == 0
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "blocked"
    assert saved[0]["blocked_reason"] == "awaiting_interactive_session"
    assert saved[0]["blocked_note"] == "Needs logged-in Chrome session"
    out = capsys.readouterr().out
    assert "awaiting_interactive_session" in out


def test_unblock_restores_pending_status(tmp_path, monkeypatch) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "fb_post_example",
                    "status": "blocked",
                    "blocked_reason": "awaiting_interactive_session",
                    "blocked_note": "Needs logged-in Chrome session",
                }
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mark_task_blocked, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mark_task_blocked.py",
            "--id",
            "fb_post_example",
            "--unblock",
        ],
    )

    rc = mark_task_blocked.main()

    assert rc == 0
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "pending"
    assert "blocked_reason" not in saved[0]


def test_load_warns_and_refuses_bad_next_tasks_json(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(mark_task_blocked, "NEXT_TASKS", next_tasks)

    try:
        mark_task_blocked._load()
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("_load should raise JSONDecodeError")

    err = capsys.readouterr().err
    assert "[mark_task_blocked] WARN next_tasks read failed; refusing to update" in err
    assert "next_tasks.json" in err
    assert "JSONDecodeError" in err


def test_mark_task_blocked_skips_bad_entries_and_updates_valid(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                "bad-entry",
                {"id": "target", "status": "pending"},
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mark_task_blocked, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mark_task_blocked.py",
            "--id",
            "target",
            "--reason",
            "awaiting_interactive_session",
        ],
    )

    rc = mark_task_blocked.main()

    assert rc == 0
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[1]["status"] == "blocked"
    err = capsys.readouterr().err
    assert "[mark_task_blocked] WARN next_tasks entry schema invalid; skipping" in err
    assert "index=0" in err
