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
    # 2026-07-04: the warn was migrated to the shared structured `warn()`
    # diagnostics helper (no-silent-fallback rule) — wording changed from
    # "invalid blocked_until; keeping task blocked" to a structured line.
    # Assert on the stable semantic fields, not the old prose.
    assert "[unblock] WARN blocked_until parse failed" in captured.err
    assert "task_id=blocked_bad_until" in captured.err
    assert "raw=!!!" in captured.err
    # 2026-07-14: b61789d26 folded tombstone compaction into this script, so the
    # summary line now reports both sweeps under a `[queue-maint]` tag.
    assert "[queue-maint] applied: 0 unblocked" in captured.out
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
    assert "[queue-maint] applied: 1 unblocked" in captured.out
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "pending"
    assert "blocked_reason" not in saved[0]
    assert "blocked_at" not in saved[0]
    assert "blocked_until" not in saved[0]
    assert "blocked_note" not in saved[0]
    assert saved[0]["status_history"][-1]["from"] == "blocked"
    assert saved[0]["status_history"][-1]["to"] == "pending"


def test_successful_codex_probe_unblocks_before_reset_date(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "quota_future_a",
                    "task_type": "paper_review",
                    "status": "blocked",
                    "blocked_reason": "codex_quota_reset_pending",
                    "blocked_until": "2999-01-01T00:00:00+00:00",
                },
                {
                    "id": "ordinary_future",
                    "task_type": "platform_ops",
                    "status": "blocked",
                    "blocked_reason": "awaiting_event_window",
                    "blocked_until": "2999-01-01T00:00:00+00:00",
                },
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(unblock_expired_blocked_tasks, "PATH", next_tasks)
    monkeypatch.setattr(
        unblock_expired_blocked_tasks,
        "_probe_codex_available",
        lambda: (True, "ChatGPT answered"),
    )

    assert unblock_expired_blocked_tasks.main(apply=True) == 0

    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "pending"
    assert "blocked_until" not in saved[0]
    assert saved[0]["status_history"][-1]["reason"] == "codex_reachability_probe_succeeded"
    assert saved[1]["status"] == "blocked"
    assert "codex quota probe: available; blocked=1" in capsys.readouterr().out


def test_failed_codex_probe_keeps_expired_quota_blocked(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "quota_expired_but_still_down",
                    "task_type": "paper_review",
                    "status": "blocked",
                    "blocked_reason": "codex_quota_reset_pending",
                    "blocked_until": "2000-01-01T00:00:00+00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(unblock_expired_blocked_tasks, "PATH", next_tasks)
    monkeypatch.setattr(
        unblock_expired_blocked_tasks,
        "_probe_codex_available",
        lambda: (False, "usage limit still active"),
    )

    assert unblock_expired_blocked_tasks.main(apply=True) == 0

    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "blocked"
    assert saved[0]["blocked_until"] == "2000-01-01T00:00:00+00:00"
    assert "codex quota probe: unavailable; blocked=1" in capsys.readouterr().out


def test_dry_run_reports_quota_probe_without_calling_it(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    original = [
        {
            "id": "quota_dry_run",
            "task_type": "paper_review",
            "status": "blocked",
            "blocked_reason": "codex_quota_reset_pending",
            "blocked_until": "2000-01-01T00:00:00+00:00",
        }
    ]
    next_tasks.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(unblock_expired_blocked_tasks, "PATH", next_tasks)

    def unexpected_probe() -> tuple[bool, str]:
        raise AssertionError("dry-run must not spend a Codex probe")

    monkeypatch.setattr(unblock_expired_blocked_tasks, "_probe_codex_available", unexpected_probe)

    assert unblock_expired_blocked_tasks.main(apply=False) == 0

    assert json.loads(next_tasks.read_text(encoding="utf-8")) == original
    assert "would actively probe Codex for 1 quota-blocked task(s); no probe sent" in capsys.readouterr().out
