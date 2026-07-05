from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "task_pool_claim.py"
SPEC = importlib.util.spec_from_file_location("task_pool_claim", MODULE_PATH)
task_pool_claim = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(task_pool_claim)


def test_complete_accepts_blocked_status(tmp_path, monkeypatch) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "fb_post_example",
                    "status": "in_progress",
                    "claimed_by": "codex-cli",
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "task_pool_claim.py",
            "complete",
            "--id",
            "fb_post_example",
            "--status",
            "blocked",
            "--result",
            "Needs interactive session",
        ],
    )

    rc = task_pool_claim.main()

    assert rc == 0
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "blocked"
    assert "Needs interactive session" in saved[0]["result"]


def test_handoff_main_thread_clears_claim_and_sets_note(tmp_path, monkeypatch) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "paper_body_example",
                    "status": "in_progress",
                    "claimed_by": "codex-cli",
                    "claimed_at": "2026-05-27T00:00:00+00:00",
                    "claim_session_id": "abc123",
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "task_pool_claim.py",
            "handoff-main-thread",
            "--id",
            "paper_body_example",
            "--note",
            "paper_body main-thread only",
        ],
    )

    rc = task_pool_claim.main()

    assert rc == 0
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "pending_main_thread"
    assert saved[0]["handoff_note"] == "paper_body main-thread only"
    assert "handoff_at" in saved[0]
    assert "claimed_by" not in saved[0]
    assert "claimed_at" not in saved[0]
    assert "claim_session_id" not in saved[0]


def test_codex_review_followup_fail_marks_source_failed_and_adds_v2_task(tmp_path, monkeypatch) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "K2001",
                    "task_type": "experiment",
                    "status": "succeeded",
                    "priority": 3,
                    "result": "Original experiment self-verdict was PASS.",
                },
                {
                    "id": "K2001_codex_review_followup",
                    "task_type": "experiment",
                    "status": "in_progress",
                    "priority": "P3",
                    "claimed_by": "codex-desktop",
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "task_pool_claim.py",
            "complete",
            "--id",
            "K2001_codex_review_followup",
            "--status",
            "succeeded",
            "--result",
            "正式verdict=FAIL: unmatched refit cadence.",
        ],
    )

    rc = task_pool_claim.main()

    assert rc == 0
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    source = next(t for t in saved if t["id"] == "K2001")
    review = next(t for t in saved if t["id"] == "K2001_codex_review_followup")
    v2 = next(t for t in saved if t["id"] == "K2001_v2_fix_methodology")

    assert source["status"] == "failed"
    assert source["failed_by"] == "task_pool_claim:codex_review_followup"
    assert "K2001_codex_review_followup" in source["failure_reason"]
    assert "unmatched refit cadence" in source["failure_reason"]
    assert review["status"] == "succeeded"
    assert review["priority"] == 3
    assert v2["status"] == "pending"
    assert v2["priority"] == 3
    assert v2["task_type"] == "experiment"
    assert v2["predecessor"] == "K2001"
    assert v2["predecessor_codex_review_task"] == "K2001_codex_review_followup"
    assert v2["dispatch_lane"] == "agent"


def test_codex_review_followup_conditional_pass_does_not_mark_source_failed(tmp_path, monkeypatch) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "K2002",
                    "task_type": "experiment",
                    "status": "succeeded",
                    "priority": 3,
                },
                {
                    "id": "K2002_codex_review_followup",
                    "task_type": "experiment",
                    "status": "in_progress",
                    "priority": "P3",
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "task_pool_claim.py",
            "complete",
            "--id",
            "K2002_codex_review_followup",
            "--status",
            "succeeded",
            "--result",
            "Review completed. final verdict=CONDITIONAL_PASS; do not promote yet.",
        ],
    )

    rc = task_pool_claim.main()

    assert rc == 0
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    source = next(t for t in saved if t["id"] == "K2002")
    assert source["status"] == "succeeded"
    assert all(t["id"] != "K2002_v2_fix_methodology" for t in saved)


def test_list_codex_eligible_filters_claude_only_tasks(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "trending_repost_example",
                    "task_type": "trending_repost",
                    "status": "pending",
                    "priority": 1,
                },
                {
                    "id": "email_reply_example",
                    "task_type": "email_reply",
                    "status": "pending",
                    "priority": 2,
                },
                {
                    "id": "platform_ops_example",
                    "task_type": "platform_ops",
                    "status": "pending",
                    "priority": 3,
                },
                {
                    "id": "paper_review_example",
                    "task_type": "paper_review",
                    "status": "pending",
                    "priority": 4,
                },
                {
                    "id": "paper_body_example",
                    "task_type": "paper_body",
                    "status": "pending",
                    "priority": 5,
                },
                {
                    "id": "main_thread_governance",
                    "task_type": "governance",
                    "status": "pending",
                    "priority": 6,
                    "dispatch_lane": "main_thread",
                },
                {
                    "id": "daily_article_example",
                    "task_type": "daily_article",
                    "status": "pending",
                    "priority": 7,
                },
                {
                    "id": "daily_digest_example",
                    "task_type": "daily_digest",
                    "status": "pending",
                    "priority": 7,
                },
                {
                    "id": "code_review_spaced",
                    "task_type": "code review",
                    "status": "pending",
                    "priority": 8,
                },
                {
                    "id": "explicit_codex_task",
                    "task_type": "custom_review",
                    "status": "pending",
                    "priority": 9,
                    "preferred_agent": "codex",
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "task_pool_claim.py",
            "list",
            "--status",
            "pending",
            "--codex-eligible",
        ],
    )

    rc = task_pool_claim.main()

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert [task["id"] for task in payload["tasks"]] == [
        "platform_ops_example",
        "paper_review_example",
        "daily_article_example",
        "daily_digest_example",
        "code_review_spaced",
        "explicit_codex_task",
    ]


def test_list_does_not_rewrite_next_tasks_file(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    original = (
        json.dumps(
            [
                {
                    "id": "platform_ops_example",
                    "task_type": "platform_ops",
                    "status": "pending",
                    "priority": 3,
                }
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    next_tasks.write_text(original, encoding="utf-8")
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "task_pool_claim.py",
            "list",
            "--status",
            "pending",
            "--codex-eligible",
        ],
    )

    rc = task_pool_claim.main()

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert next_tasks.read_text(encoding="utf-8") == original


def test_normalize_priorities_command_sweeps_legacy_string_values(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {"id": "p3", "status": "pending", "priority": "P3"},
                {"id": "pp1", "status": "pending", "priority": "PP1"},
                {"id": "int2", "status": "pending", "priority": 2},
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(sys, "argv", ["task_pool_claim.py", "normalize-priorities"])

    rc = task_pool_claim.main()

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["changed"] == 2
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert [task["priority"] for task in saved] == [3, 1, 2]


def test_legacy_task_id_field_is_claimable_and_listed(tmp_path, monkeypatch, capsys) -> None:
    """Legacy queue rows may use `task_id`; claim flow must still be atomic."""
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "task_id": "platform_ops_legacy_key",
                    "task_type": "platform_ops",
                    "status": "pending",
                    "priority": 2,
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "task_pool_claim.py",
            "list",
            "--status",
            "pending",
            "--codex-eligible",
        ],
    )

    rc = task_pool_claim.main()

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tasks"][0]["id"] == "platform_ops_legacy_key"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "task_pool_claim.py",
            "claim",
            "--id",
            "platform_ops_legacy_key",
            "--owner",
            "codex-cli",
        ],
    )
    rc = task_pool_claim.main()

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "claimed"
    assert saved[0]["claimed_by"] == "codex-cli"


def test_list_stale_warns_on_invalid_claimed_at(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "bad_claim_timestamp",
                    "task_type": "platform_ops",
                    "status": "claimed",
                    "claimed_by": "codex-vscode",
                    "claimed_at": "not-a-timestamp",
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "task_pool_claim.py",
            "list",
            "--status",
            "stale",
            "--stale-hours",
            "2",
        ],
    )

    rc = task_pool_claim.main()

    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["count"] == 0
    assert "[claim] WARN claimed_at parse failed" in captured.err
    assert "site=list_stale" in captured.err
    assert "task_id=bad_claim_timestamp" in captured.err


def test_cleanup_warns_on_invalid_claimed_at_without_releasing(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "bad_cleanup_timestamp",
                    "task_type": "platform_ops",
                    "status": "in_progress",
                    "claimed_by": "codex-vscode",
                    "claimed_at": "not-a-timestamp",
                    "claim_session_id": "abc123",
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "task_pool_claim.py",
            "cleanup",
            "--stale-hours",
            "2",
        ],
    )

    rc = task_pool_claim.main()

    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["count"] == 0
    assert "[claim] WARN claimed_at parse failed" in captured.err
    assert "site=cleanup_stale" in captured.err
    assert "task_id=bad_cleanup_timestamp" in captured.err
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "in_progress"
    assert saved[0]["claimed_by"] == "codex-vscode"
    assert saved[0]["claim_session_id"] == "abc123"


@pytest.mark.parametrize(
    ("task_id", "task_type", "status"),
    [
        ("trending_repost_example", "trending_repost", "pending"),
        ("email_reply_example", "email_reply", "pending"),
        ("paper_body_main_thread", "paper_body", "pending_main_thread"),
    ],
)
def test_codex_owner_cannot_claim_claude_only_task(
    task_id,
    task_type,
    status,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": task_id,
                    "task_type": task_type,
                    "status": status,
                    "priority": 1,
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "task_pool_claim.py",
            "claim",
            "--id",
            task_id,
            "--owner",
            "codex-vscode",
        ],
    )

    rc = task_pool_claim.main()

    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["reason"] == "not_codex_eligible"
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == status
    assert "claimed_by" not in saved[0]


def test_non_codex_owner_can_claim_reader_facing_task(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "trending_repost_example",
                    "task_type": "trending_repost",
                    "status": "pending",
                    "priority": 1,
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "task_pool_claim.py",
            "claim",
            "--id",
            "trending_repost_example",
            "--owner",
            "hourly-dispatch",
        ],
    )

    rc = task_pool_claim.main()

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "claimed"
    assert saved[0]["claimed_by"] == "hourly-dispatch"


def _run(monkeypatch, *argv) -> int:
    monkeypatch.setattr(sys, "argv", ["task_pool_claim.py", *argv])
    return task_pool_claim.main()


def test_status_history_recorded_across_full_lifecycle(tmp_path, monkeypatch) -> None:
    """claim → start → complete writes 3 status_history entries with from/to/by."""
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps([{"id": "tk1", "status": "pending"}], ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)

    assert _run(monkeypatch, "claim", "--id", "tk1", "--owner", "hourly-22") == 0
    assert _run(monkeypatch, "start", "--id", "tk1") == 0
    assert _run(monkeypatch, "complete", "--id", "tk1", "--status", "succeeded", "--result", "ok") == 0

    saved = json.loads(next_tasks.read_text(encoding="utf-8"))[0]
    hist = saved["status_history"]
    assert [(h["from"], h["to"]) for h in hist] == [
        ("pending", "claimed"),
        ("claimed", "in_progress"),
        ("in_progress", "succeeded"),
    ]
    assert all(h.get("ts") and h.get("by") for h in hist)
    assert hist[0]["by"] == "hourly-22"


def test_status_history_release_records_manual_release(tmp_path, monkeypatch) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps([{"id": "tk2", "status": "pending"}], ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)

    assert _run(monkeypatch, "claim", "--id", "tk2", "--owner", "hourly-22") == 0
    assert _run(monkeypatch, "release", "--id", "tk2") == 0

    saved = json.loads(next_tasks.read_text(encoding="utf-8"))[0]
    hist = saved["status_history"]
    assert hist[-1]["from"] == "claimed"
    assert hist[-1]["to"] == "pending"
    assert hist[-1].get("note") == "manual_release"


def test_status_history_handoff_main_thread_records_note(tmp_path, monkeypatch) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "tk3",
                    "status": "in_progress",
                    "claimed_by": "hourly-22",
                    "claimed_at": "2026-06-30T14:00:00+00:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)

    assert _run(
        monkeypatch,
        "handoff-main-thread",
        "--id",
        "tk3",
        "--note",
        "paper_body owner",
    ) == 0

    saved = json.loads(next_tasks.read_text(encoding="utf-8"))[0]
    hist = saved["status_history"]
    assert hist[-1]["from"] == "in_progress"
    assert hist[-1]["to"] == "pending_main_thread"
    assert hist[-1].get("note") == "paper_body owner"
    assert hist[-1]["by"] == "hourly-22"


def test_status_history_cleanup_auto_release_marks_note(tmp_path, monkeypatch) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    # Claim aged 24h → cleanup should release with note.
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "tk4",
                    "status": "claimed",
                    "claimed_by": "hourly-old",
                    "claimed_at": "2026-06-29T14:00:00+00:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)

    assert _run(monkeypatch, "cleanup", "--stale-hours", "6") == 0

    saved = json.loads(next_tasks.read_text(encoding="utf-8"))[0]
    hist = saved["status_history"]
    assert hist[-1]["from"] == "claimed"
    assert hist[-1]["to"] == "pending"
    assert "auto_release_stale_6h" in hist[-1].get("note", "")
    assert hist[-1]["by"] == "hourly-old"
