from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


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
    assert v2["status"] == "pending"
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
        "code_review_spaced",
        "explicit_codex_task",
    ]
