from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "dedupe_next_tasks.py"
SPEC = importlib.util.spec_from_file_location("dedupe_next_tasks", MODULE_PATH)
dedupe_next_tasks = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(dedupe_next_tasks)


def test_load_tasks_warns_and_fails_on_bad_json(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "storage" / "next_tasks.json"
    next_tasks.parent.mkdir(parents=True)
    next_tasks.write_text("[", encoding="utf-8")
    monkeypatch.setattr(dedupe_next_tasks, "NEXT_TASKS", next_tasks)

    with next_tasks.open("r+", encoding="utf-8") as fh:
        try:
            dedupe_next_tasks._load_tasks(fh)
        except SystemExit as exc:
            assert "failed to parse" in str(exc)
        else:
            raise AssertionError("_load_tasks should reject malformed next_tasks.json")

    captured = capsys.readouterr()
    assert "[dedupe_next_tasks] WARN next_tasks read failed" in captured.err
    assert str(next_tasks) in captured.err
    assert "JSONDecodeError" in captured.err


def test_dedupe_warns_and_preserves_non_object_entries(capsys) -> None:
    tasks = [
        "bad-entry",
        {"id": "dup", "status": "pending", "created_at": "2026-06-23T00:00:00Z"},
        {
            "id": "dup",
            "status": "succeeded",
            "created_at": "2026-06-23T00:01:00Z",
            "completed_at": "2026-06-23T00:02:00Z",
        },
    ]

    deduped, dropped = dedupe_next_tasks.dedupe(tasks)

    assert len(deduped) == 2
    assert deduped[0]["id"] == "dup"
    assert deduped[0]["status"] == "succeeded"
    assert deduped[1] == "bad-entry"
    assert dropped == [
        {
            "id": "dup",
            "dropped_status": "pending",
            "kept_status": "succeeded",
            "created_at": "2026-06-23T00:00:00Z",
        }
    ]
    captured = capsys.readouterr()
    assert "[dedupe_next_tasks] WARN next_tasks entry schema invalid" in captured.err
    assert "index=0" in captured.err
    assert "type=str" in captured.err


def test_load_tasks_warns_and_fails_on_non_list_schema(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "storage" / "next_tasks.json"
    next_tasks.parent.mkdir(parents=True)
    next_tasks.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    monkeypatch.setattr(dedupe_next_tasks, "NEXT_TASKS", next_tasks)

    with next_tasks.open("r+", encoding="utf-8") as fh:
        try:
            dedupe_next_tasks._load_tasks(fh)
        except SystemExit as exc:
            assert str(exc) == "next_tasks.json is not a list"
        else:
            raise AssertionError("_load_tasks should reject non-list next_tasks.json")

    captured = capsys.readouterr()
    assert "[dedupe_next_tasks] WARN next_tasks schema invalid" in captured.err
    assert "expected=list actual=dict" in captured.err
