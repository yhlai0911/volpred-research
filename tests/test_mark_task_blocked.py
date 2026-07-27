from __future__ import annotations

import fcntl
import importlib.util
import json
import sys
import threading
from pathlib import Path

import pytest

from volpred.ops.next_tasks import write_tasks_to_handle

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
    assert saved[0]["blocked_until"]
    out = capsys.readouterr().out
    assert "awaiting_interactive_session" in out


def test_mark_blocked_retires_incompatible_claim_and_terminal_fields(
    tmp_path,
    monkeypatch,
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "reopened-data-task",
                    "status": "in_progress",
                    "claimed_by": "worker",
                    "claimed_at": "2026-07-21T09:36:35+00:00",
                    "claim_expires_at": "2026-07-21T11:36:35+00:00",
                    "claim_session_id": "session-1",
                    "started_at": "2026-07-21T09:36:36+00:00",
                    "completed_at": "2026-06-09T10:28:11+00:00",
                }
            ]
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
            "reopened-data-task",
            "--reason",
            "awaiting_external_data",
        ],
    )

    assert mark_task_blocked.main() == 0

    saved = json.loads(next_tasks.read_text(encoding="utf-8"))[0]
    assert saved["status"] == "blocked"
    assert all(
        field not in saved
        for field in (
            "claimed_by",
            "claimed_at",
            "claim_expires_at",
            "claim_session_id",
            "started_at",
            "completed_at",
        )
    )
    assert saved["block_transition_previous"]["claimed_by"] == "worker"
    assert saved["block_transition_previous"]["claim_expires_at"] == (
        "2026-07-21T11:36:35+00:00"
    )
    assert saved["block_transition_previous"]["completed_at"] == (
        "2026-06-09T10:28:11+00:00"
    )


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


def test_manual_unblock_cannot_bypass_live_gate(
    tmp_path, monkeypatch, capsys
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    original = [
        {
            "id": "shadow_soak",
            "status": "blocked",
            "blocked_reason": "awaiting_event_window",
            "blocked_until": "2000-01-01T00:00:00+00:00",
            "unblock_gate": "work_shadow_cutover_ready_v1",
        }
    ]
    next_tasks.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(mark_task_blocked, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        ["mark_task_blocked.py", "--id", "shadow_soak", "--unblock"],
    )

    assert mark_task_blocked.main() == 2
    assert json.loads(next_tasks.read_text(encoding="utf-8")) == original
    assert "unresolved unblock_gate" in capsys.readouterr().err


def test_event_window_block_sets_allowlisted_live_gate(
    tmp_path, monkeypatch
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps([{"id": "shadow_soak", "status": "pending"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(mark_task_blocked, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mark_task_blocked.py",
            "--id",
            "shadow_soak",
            "--reason",
            "awaiting_event_window",
            "--until",
            "2026-08-03T04:56:16+00:00",
            "--unblock-gate",
            "work_shadow_cutover_ready_v1",
        ],
    )

    assert mark_task_blocked.main() == 0

    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "blocked"
    assert saved[0]["unblock_gate"] == "work_shadow_cutover_ready_v1"


def test_live_gate_rejects_non_event_window_reason(
    tmp_path, monkeypatch, capsys
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    original = [{"id": "external", "status": "pending"}]
    next_tasks.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(mark_task_blocked, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mark_task_blocked.py",
            "--id",
            "external",
            "--reason",
            "awaiting_external_data",
            "--unblock-gate",
            "work_shadow_cutover_ready_v1",
        ],
    )

    assert mark_task_blocked.main() == 2
    assert json.loads(next_tasks.read_text(encoding="utf-8")) == original
    assert (
        "--unblock-gate requires --reason awaiting_event_window"
        in capsys.readouterr().err
    )


def test_reblock_preserves_gate_and_expiry_sweeper_still_fails_closed(
    tmp_path, monkeypatch
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "shadow-soak",
                    "status": "blocked",
                    "blocked_reason": "awaiting_event_window",
                    "blocked_until": "2000-01-01T00:00:00+00:00",
                    "unblock_gate": "work_shadow_cutover_ready_v1",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mark_task_blocked, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mark_task_blocked.py",
            "--id",
            "shadow-soak",
            "--reason",
            "awaiting_event_window",
            "--until",
            "2000-01-01T00:00:00+00:00",
        ],
    )

    assert mark_task_blocked.main() == 0
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["unblock_gate"] == "work_shadow_cutover_ready_v1"

    sweep_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "unblock_expired_blocked_tasks.py"
    )
    sweep_spec = importlib.util.spec_from_file_location(
        "reblock_expiry_sweep",
        sweep_path,
    )
    sweep = importlib.util.module_from_spec(sweep_spec)
    assert sweep_spec and sweep_spec.loader
    sweep_spec.loader.exec_module(sweep)
    monkeypatch.setattr(sweep, "PATH", next_tasks)
    monkeypatch.setattr(
        sweep,
        "_probe_unblock_gate",
        lambda _task: (False, "observation_window_too_short"),
    )

    assert sweep.main(apply=True) == 0
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "blocked"
    assert saved[0]["unblock_gate"] == "work_shadow_cutover_ready_v1"


def test_mark_blocked_holds_queue_lock_across_read_modify_write(
    tmp_path, monkeypatch
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {"id": "target", "status": "pending"},
                {"id": "peer", "status": "pending"},
            ]
        ),
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
            "awaiting_event_window",
            "--until",
            "2099-01-01T00:00:00+00:00",
        ],
    )
    mutation_reached = threading.Event()
    allow_mark_write = threading.Event()
    writer_attempted = threading.Event()
    failures: list[BaseException] = []
    original_validate = mark_task_blocked._validate_task_schema

    def pause_after_mutation(task: dict) -> None:
        original_validate(task)
        mutation_reached.set()
        assert allow_mark_write.wait(timeout=5)

    monkeypatch.setattr(
        mark_task_blocked,
        "_validate_task_schema",
        pause_after_mutation,
    )

    def run_mark() -> None:
        try:
            assert mark_task_blocked.main() == 0
        except BaseException as exc:
            failures.append(exc)

    def concurrent_writer() -> None:
        try:
            with next_tasks.open("r+", encoding="utf-8") as fh:
                writer_attempted.set()
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                tasks = json.loads(fh.read())
                next(task for task in tasks if task["id"] == "peer")[
                    "status"
                ] = "succeeded"
                write_tasks_to_handle(fh, tasks)
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except BaseException as exc:
            failures.append(exc)

    mark_thread = threading.Thread(target=run_mark)
    mark_thread.start()
    assert mutation_reached.wait(timeout=5)
    peer_thread = threading.Thread(target=concurrent_writer)
    peer_thread.start()
    assert writer_attempted.wait(timeout=5)
    assert peer_thread.is_alive()
    allow_mark_write.set()
    mark_thread.join(timeout=5)
    peer_thread.join(timeout=5)

    assert failures == []
    assert not mark_thread.is_alive()
    assert not peer_thread.is_alive()
    saved = {
        task["id"]: task
        for task in json.loads(next_tasks.read_text(encoding="utf-8"))
    }
    assert saved["target"]["status"] == "blocked"
    assert saved["peer"]["status"] == "succeeded"


def test_load_warns_and_refuses_bad_next_tasks_json(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(mark_task_blocked, "NEXT_TASKS", next_tasks)

    with pytest.raises(json.JSONDecodeError):
        mark_task_blocked._load()

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


def test_deprecated_reason_terminalizes_instead_of_blocking(tmp_path, monkeypatch) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "duplicate_article",
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
            "duplicate_article",
            "--reason",
            "deprecated",
            "--note",
            "Already covered by a published article",
        ],
    )

    rc = mark_task_blocked.main()

    assert rc == 0
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "closed_no_action"
    assert saved[0]["blocked_reason"] == "deprecated"
    assert saved[0]["blocked_note"] == "Already covered by a published article"
    assert "blocked_until" not in saved[0]
    assert saved[0]["terminalized_reason"] == "deprecated"


def test_schema_guard_rejects_blocked_without_reason() -> None:
    with pytest.raises(ValueError, match="blocked_reason"):
        mark_task_blocked._validate_task_schema({"id": "bad", "status": "blocked"})


def test_schema_guard_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="not canonical"):
        mark_task_blocked._validate_task_schema({"id": "bad", "status": "surprise"})


def test_schema_guard_rejects_unknown_unblock_gate() -> None:
    with pytest.raises(ValueError, match="unblock_gate"):
        mark_task_blocked._validate_task_schema(
            {
                "id": "bad",
                "status": "blocked",
                "blocked_reason": "awaiting_event_window",
                "blocked_until": "2099-01-01T00:00:00+00:00",
                "unblock_gate": "arbitrary-command",
            }
        )
