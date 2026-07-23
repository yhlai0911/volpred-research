from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from volpred.ops.task_pool_selection import (
    evaluate_task_claim,
    select_task_for_claim,
)


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "task_pool_claim.py"
SPEC = importlib.util.spec_from_file_location("task_pool_claim", MODULE_PATH)
task_pool_claim = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(task_pool_claim)

REPO_ROOT = MODULE_PATH.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def burst_fire_requests(monkeypatch) -> list[str]:
    """Keep `complete` from pulling the REAL supervisor's fire forward.

    `cmd_complete` asks the supervisor to fire early whenever a completion may
    have freed a slot, and `request_fire` writes storage/ops/dispatch_state.json
    under its own lock. That path is canonical state, so under
    VOLPRED_NO_CANONICAL_WRITE=1 it raises CanonicalWriteBlocked — a
    BaseException the production fail-open handler deliberately cannot swallow
    (2026-07-19 CI red, run 29674177829). Autouse rather than per-test: any
    `complete` of a task with pending burst work reaches this, so the next test
    to add one would rediscover the same red.

    Returns the recorded reasons so a test can assert the request was made.
    """
    from scripts.dispatch_supervisor import state as sup_state

    reasons: list[str] = []
    monkeypatch.setattr(sup_state, "request_fire", lambda reason, *a, **kw: reasons.append(reason))
    return reasons


def test_claim_is_rejected_while_direct_execution_mode_is_active(
    tmp_path, monkeypatch
) -> None:
    next_tasks = tmp_path / "storage" / "next_tasks.json"
    next_tasks.parent.mkdir(parents=True)
    next_tasks.write_text(
        json.dumps(
            [{"id": "queued", "status": "pending", "task_type": "platform_ops"}]
        ),
        encoding="utf-8",
    )
    state = tmp_path / "storage" / "ops" / "task_pool_mode.json"
    state.parent.mkdir(parents=True)
    state.write_text(
        json.dumps({"enabled": True, "mode": "direct_execution"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)

    result = task_pool_claim.cmd_claim(
        argparse.Namespace(
            id="queued",
            owner="test-worker",
            session=None,
            main_thread=False,
        )
    )

    assert result["ok"] is False
    assert result["reason"] == "direct_execution_mode"
    assert json.loads(next_tasks.read_text())[0]["status"] == "pending"


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
    assert "claimed_by" not in saved[0]
    assert "claimed_at" not in saved[0]
    assert "claim_session_id" not in saved[0]


def test_complete_idempotently_clears_stale_terminal_claim(tmp_path, monkeypatch) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "already_done",
                    "status": "succeeded",
                    "claimed_by": "stale-worker",
                    "claimed_at": "2026-07-14T00:00:00+00:00",
                    "claim_session_id": "stale-session",
                }
            ]
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
            "already_done",
            "--status",
            "succeeded",
        ],
    )

    assert task_pool_claim.main() == 0
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))[0]
    assert saved["status"] == "succeeded"
    assert "claimed_by" not in saved
    assert "claimed_at" not in saved
    assert "claim_session_id" not in saved


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


@pytest.mark.parametrize("task_type", ["trending_repost", "event_article"])
def test_complete_refuses_published_dual_publish_without_fb_draft(
    task_type, tmp_path, monkeypatch
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "publish_example",
                    "task_type": task_type,
                    "status": "in_progress",
                    "claimed_by": "hourly-slot-1",
                    "result": "發佈 mile_deadbeef（feed live）",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(task_pool_claim, "FB_DRAFTS_DIR", drafts)

    with pytest.raises(SystemExit, match="dual-publish completion refused"):
        task_pool_claim.cmd_complete(
            argparse.Namespace(
                id="publish_example",
                status="succeeded",
                result="FB pending",
            )
        )

    saved = json.loads(next_tasks.read_text(encoding="utf-8"))[0]
    assert saved["status"] == "in_progress"
    assert saved["claimed_by"] == "hourly-slot-1"


def test_complete_accepts_published_dual_publish_with_fb_draft(
    tmp_path, monkeypatch
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "fb_mile_deadbeef.md").write_text("## 主貼文\n完成\n", encoding="utf-8")
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "publish_example",
                    "task_type": "trending_repost",
                    "status": "in_progress",
                    "claimed_by": "hourly-slot-1",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(task_pool_claim, "FB_DRAFTS_DIR", drafts)

    out, _burst = task_pool_claim._complete_locked(
        argparse.Namespace(
            id="publish_example",
            status="succeeded",
            result="mile_deadbeef 已發 VolPred feed；FB 稿已備妥",
        )
    )

    assert out["status"] == "succeeded"
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))[0]
    assert saved["status"] == "succeeded"


def test_codex_review_followup_fail_marks_source_failed_and_adds_v2_task(
    tmp_path, monkeypatch, burst_fire_requests
) -> None:
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
    # Whether the completion pulls the next fire forward depends on live slot
    # occupancy, so assert only that nothing escaped to the real supervisor.
    assert all(reason.startswith("burst:") for reason in burst_fire_requests)


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


def test_cleanup_releases_unprovable_claim_with_no_timestamps(tmp_path, monkeypatch, capsys) -> None:
    # WS-A2（refactor_plan_ops_master_2026_07）：claimed_at 壞值且無任何生命週期
    # 欄位可推年齡 = 無法證明活著 → 視為無限 stale 立即回收。
    # 舊行為（warn 後跳過、永不回收）正是 2026-07-20 稽核實證的殭屍任務盲點。
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
    assert payload["count"] == 1
    assert payload["released"][0]["id"] == "bad_cleanup_timestamp"
    assert payload["released"][0]["age_h"] is None
    assert payload["released"][0]["age_source"] is None
    assert "[claim] WARN claimed_at parse failed" in captured.err
    assert "site=cleanup_stale" in captured.err
    assert "task_id=bad_cleanup_timestamp" in captured.err
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "pending"
    assert "claimed_by" not in saved[0]
    assert "claim_session_id" not in saved[0]


def test_cleanup_missing_claimed_at_falls_back_to_created_at(tmp_path, monkeypatch, capsys) -> None:
    # WS-A2：in_progress 但 claimed_at 全空（實證殭屍 k1731_armB_rev7_* 形態）
    # → 用 created_at 推年齡；夠老就回收、新鮮就留著。
    stale_created = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    fresh_created = datetime.now(timezone.utc).isoformat()
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "zombie_no_claimed_at",
                    "task_type": "platform_ops",
                    "status": "in_progress",
                    "created_at": stale_created,
                },
                {
                    "id": "fresh_no_claimed_at",
                    "task_type": "platform_ops",
                    "status": "in_progress",
                    "created_at": fresh_created,
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
            "cleanup",
            "--stale-hours",
            "2",
        ],
    )

    rc = task_pool_claim.main()

    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["count"] == 1
    assert payload["released"][0]["id"] == "zombie_no_claimed_at"
    assert payload["released"][0]["age_source"] == "created_at"
    assert payload["released"][0]["age_h"] is not None
    saved = {t["id"]: t for t in json.loads(next_tasks.read_text(encoding="utf-8"))}
    assert saved["zombie_no_claimed_at"]["status"] == "pending"
    assert saved["fresh_no_claimed_at"]["status"] == "in_progress"


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
    # pending_main_thread is refused by the earlier main-thread-lane gate
    # (2026-07-20, refactor_plan_ops_master_2026_07 s5); other claude-only
    # types still fall through to the codex-eligibility refusal.
    expected = "main_thread_lane" if status == "pending_main_thread" else "not_codex_eligible"
    assert payload["reason"] == expected
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


def test_claim_atomically_expires_managed_event_after_deadline(
    tmp_path, monkeypatch, capsys
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "event_article_cpi_2000-01-01_tplus0",
                    "task_type": "event_article",
                    "source": "event_expander",
                    "ref_event_job_id": "cpi-2000-01-01-t0",
                    "status": "pending",
                    "deadline": "2000-01-01T01:00:00+00:00",
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
            "event_article_cpi_2000-01-01_tplus0",
            "--owner",
            "hourly-dispatch",
        ],
    )

    rc = task_pool_claim.main()

    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == "deadline_expired"
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))[0]
    assert saved["status"] == "expired"
    assert saved["last_error"] == "deadline_expired_never_dispatched"
    assert "claimed_by" not in saved
    assert saved["status_history"][-1]["to"] == "expired"


@pytest.mark.parametrize(
    ("deadline", "reason"),
    [(None, "missing_deadline"), ("not-an-iso-date", "invalid_deadline")],
)
def test_claim_terminally_fails_managed_event_with_bad_deadline(
    deadline, reason, tmp_path, monkeypatch, capsys
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    task = {
        "id": f"event_article_bad_{reason}",
        "task_type": "event_article",
        "source": "event_expander",
        "ref_event_job_id": f"bad-{reason}",
        "status": "pending",
    }
    if deadline is not None:
        task["deadline"] = deadline
    next_tasks.write_text(json.dumps([task]), encoding="utf-8")
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "task_pool_claim.py",
            "claim",
            "--id",
            task["id"],
            "--owner",
            "hourly-dispatch",
        ],
    )

    rc = task_pool_claim.main()

    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == reason
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))[0]
    assert saved["status"] == "failed"
    assert saved["last_error"] == reason
    assert saved["status_history"][-1]["to"] == "failed"


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


def test_burst_fire_request_is_intercepted_not_written_to_canonical_state(
    burst_fire_requests,
) -> None:
    """Non-vacuity guard for the autouse fixture above.

    Whether a given `complete` reaches `_request_burst_fire` depends on live slot
    occupancy, so no completion test can prove the interception deterministically.
    This one calls the helper directly: it must report success (the real
    `request_fire` would raise CanonicalWriteBlocked under the CI gate) and the
    reason must land in the recorder instead of dispatch_state.json.
    """
    result = task_pool_claim._request_burst_fire("K9999_example", 3)

    assert result == {"requested": True, "pending_left": 3}
    assert burst_fire_requests == ["burst:K9999_example"]


def _dreaming_orphan_task(kid: str = "k1697") -> dict:
    return {
        "id": f"dreaming_orphaned_experiment_{kid}",
        "title": f"[dreaming] orphaned_experiment:{kid}",
        "status": "pending",
        "source": "dreaming",
        "task_type": "experiment",
        "dreaming": {
            "signature": f"orphaned_experiment:{kid}",
            "pattern_type": "orphaned_experiment",
        },
    }


def test_claim_refuses_dreaming_task_whose_condition_already_cleared(
    tmp_path, monkeypatch
) -> None:
    """A dissolved snapshot is closed as a no-op instead of being dispatched.

    2026-07-17: four orphaned_experiment tasks were claimed and worked three days
    after backfill had already written the knowledge entries they demanded. An
    agent obeying the stale description writes duplicate entries.
    """
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(json.dumps([_dreaming_orphan_task()]), encoding="utf-8")
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)

    from volpred.ops import dreaming_revalidate as dr

    monkeypatch.setattr(
        dr,
        "revalidate",
        lambda task, storage_dir=None: dr.Revalidation(
            "orphaned_experiment", True, dr.CLEARED_REASON, "k1697 consumed by knowledge.json"
        ),
    )

    result = task_pool_claim.cmd_claim(
        argparse.Namespace(id="dreaming_orphaned_experiment_k1697", owner="hourly-slot-4", session="s1")
    )

    assert result["ok"] is False
    assert result["reason"] == "dreaming_condition_cleared"
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "succeeded"
    assert saved[0]["claimed_by"] is None
    assert "fresh no-op" in saved[0]["result"]


def test_claim_proceeds_when_dreaming_condition_still_holds(tmp_path, monkeypatch) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(json.dumps([_dreaming_orphan_task("k1800")]), encoding="utf-8")
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)

    from volpred.ops import dreaming_revalidate as dr

    monkeypatch.setattr(
        dr,
        "revalidate",
        lambda task, storage_dir=None: dr.Revalidation(
            "orphaned_experiment", False, "still_orphaned", "k1800 has no downstream consumer"
        ),
    )

    result = task_pool_claim.cmd_claim(
        argparse.Namespace(id="dreaming_orphaned_experiment_k1800", owner="hourly-slot-4", session="s1")
    )

    assert result["ok"] is True
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "claimed"


def test_claim_refuses_main_thread_lane_for_dispatch_agents(tmp_path, monkeypatch, capsys) -> None:
    # Independent refactor track gate (refactor_plan_ops_master_2026_07 s5):
    # lane filtering in candidate ranking is not enough -- burst/urgent fires
    # name a task id and claim it directly (observed twice on 2026-07-20), so
    # isolation must be enforced at the single claim entrance.
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "refactor_lane_task",
                    "task_type": "platform_ops",
                    "status": "pending",
                    "priority": 1,
                    "dispatch_lane": "main_thread",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys, "argv",
        ["task_pool_claim.py", "claim", "--id", "refactor_lane_task", "--owner", "hourly-slot-2-abc"],
    )
    task_pool_claim.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["reason"] == "main_thread_lane"
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "pending"
    assert "claimed_by" not in saved[0]


def test_claim_main_thread_flag_allows_interactive_claim(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "refactor_lane_task",
                    "task_type": "platform_ops",
                    "status": "pending",
                    "priority": 1,
                    "dispatch_lane": "main_thread",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(
        sys, "argv",
        ["task_pool_claim.py", "claim", "--id", "refactor_lane_task", "--owner", "claude-main", "--main-thread"],
    )
    task_pool_claim.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "claimed"
    assert saved[0]["claimed_by"] == "claude-main"


SELECTION_OBSERVED_AT = datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc)


def _selection_task(task_id: str, **overrides: object) -> dict[str, object]:
    task: dict[str, object] = {
        "id": task_id,
        "status": "pending",
        "task_type": "platform_ops",
        "title": task_id,
        "priority": 2,
        "source": "user",
        "created_at": "2026-07-23T09:00:00+00:00",
    }
    task.update(overrides)
    return task


@pytest.mark.parametrize(
    ("task", "owner", "main_thread", "eligible", "primary_reason"),
    (
        (
            _selection_task("manual", dispatch_lane="manual"),
            "hourly-slot-1",
            False,
            False,
            "main_thread_lane",
        ),
        (
            _selection_task(
                "preferred_codex",
                task_type="paper_body",
                preferred_agent="codex",
            ),
            "codex-vscode",
            False,
            True,
            "eligible",
        ),
        (
            _selection_task(
                "owned",
                status="claimed",
                claimed_by="other-worker",
                claimed_at="2026-07-23T09:30:00+00:00",
            ),
            "codex-vscode",
            False,
            False,
            "already_claimed",
        ),
        (
            _selection_task("terminal", status="succeeded"),
            "codex-vscode",
            False,
            False,
            "wrong_status",
        ),
    ),
)
def test_legacy_claim_policy_exposes_production_reason_codes(
    task: dict[str, object],
    owner: str,
    main_thread: bool,
    eligible: bool,
    primary_reason: str,
) -> None:
    decision = evaluate_task_claim(
        task,
        owner=owner,
        main_thread=main_thread,
        observed_at=SELECTION_OBSERVED_AT,
    )

    assert (decision.eligible, decision.primary_reason) == (
        eligible,
        primary_reason,
    )


def test_legacy_selection_uses_normalized_priority_then_task_id() -> None:
    selection = select_task_for_claim(
        (
            _selection_task("z_second", priority="P1"),
            _selection_task("a_first", priority=1),
            _selection_task("p2", priority=2),
        ),
        owner="hourly-slot-1",
        main_thread=False,
        observed_at=SELECTION_OBSERVED_AT,
    )

    assert selection.selected_task_id == "a_first"
    assert selection.eligible_task_ids == ("a_first", "z_second", "p2")


def test_duplicate_identity_is_rejected_by_shared_selection_and_direct_find() -> None:
    tasks = [
        _selection_task("duplicate", priority=1),
        _selection_task("duplicate", priority=1),
    ]

    selection = select_task_for_claim(
        tasks,
        owner="hourly-slot-1",
        main_thread=False,
        observed_at=SELECTION_OBSERVED_AT,
    )

    assert selection.selected_task_id is None
    assert selection.eligible_task_ids == ()
    assert {
        decision.primary_reason for decision in selection.decisions
    } == {"duplicate_task_id"}
    with pytest.raises(SystemExit, match="duplicate task id detected"):
        task_pool_claim._find(tasks, "duplicate")


def test_decision_lookup_requires_one_exact_identity() -> None:
    selection = select_task_for_claim(
        (
            _selection_task("duplicate"),
            _selection_task("duplicate"),
        ),
        owner="hourly-slot-1",
        main_thread=False,
        observed_at=SELECTION_OBSERVED_AT,
    )

    with pytest.raises(ValueError, match="ambiguous decision identity"):
        selection.decision_for("duplicate")
    with pytest.raises(LookupError, match="decision identity not found"):
        selection.decision_for("missing")


def test_production_list_and_replay_selection_share_the_same_rank(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tasks = [
        _selection_task("z_second", priority="P1"),
        _selection_task("a_first", priority=1),
        _selection_task("p2", priority=2),
    ]
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(json.dumps(tasks), encoding="utf-8")
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)

    listed = task_pool_claim.cmd_list(
        argparse.Namespace(
            status="pending",
            owner=None,
            codex_eligible=False,
            stale_hours=6,
            limit=None,
        )
    )
    replay_selection = select_task_for_claim(
        tasks,
        owner="hourly-slot-1",
        main_thread=False,
        observed_at=SELECTION_OBSERVED_AT,
    )

    assert tuple(task["id"] for task in listed["tasks"]) == (
        replay_selection.eligible_task_ids
    )


def test_legacy_selection_uses_the_production_pending_list_before_claim() -> None:
    selection = select_task_for_claim(
        (
            _selection_task("blocked_p1", status="blocked", priority=1),
            _selection_task(
                "same_owner_claimed_p1",
                status="claimed",
                claimed_by="codex-vscode",
                priority=1,
            ),
            _selection_task("pending_p2", priority=2),
        ),
        owner="codex-vscode",
        main_thread=False,
        observed_at=SELECTION_OBSERVED_AT,
    )

    assert selection.selected_task_id == "pending_p2"
    assert selection.eligible_task_ids == ("pending_p2",)
    assert selection.decision_for("blocked_p1").eligible is True
    assert selection.decision_for("same_owner_claimed_p1").eligible is True


def test_registered_dreaming_claim_requires_live_revalidation() -> None:
    task = _selection_task(
        "dreaming_orphan",
        task_type="experiment",
        source="dreaming",
        dreaming={
            "signature": "orphaned_experiment:k1800",
            "pattern_type": "orphaned_experiment",
        },
    )

    unchecked = evaluate_task_claim(
        task,
        owner="codex-vscode",
        main_thread=False,
        observed_at=SELECTION_OBSERVED_AT,
    )
    checked = evaluate_task_claim(
        task,
        owner="codex-vscode",
        main_thread=False,
        observed_at=SELECTION_OBSERVED_AT,
        revalidation_checked=True,
    )

    assert unchecked.eligible is False
    assert unchecked.primary_reason == "live_revalidation_required"
    assert checked.eligible is True
    assert checked.primary_reason == "eligible"
    assert "legacy_dreaming_revalidation_gate" in unchecked.policy_codes


@pytest.mark.parametrize(
    ("deadline", "primary_reason"),
    (
        (None, "missing_deadline"),
        ("not-an-iso-date", "invalid_deadline"),
        ("2026-07-23T09:59:59+00:00", "deadline_expired"),
        ("2026-07-23T10:00:00+00:00", "eligible"),
        ("2026-07-23T10:00:01+00:00", "eligible"),
    ),
)
def test_legacy_claim_policy_owns_managed_event_deadline_admission(
    deadline: str | None,
    primary_reason: str,
) -> None:
    task = _selection_task(
        "managed_event",
        task_type="event_article",
        source="event_expander",
        ref_event_job_id="event-1",
    )
    if deadline is not None:
        task["deadline"] = deadline

    decision = evaluate_task_claim(
        task,
        owner="hourly-slot-1",
        main_thread=False,
        observed_at=SELECTION_OBSERVED_AT,
    )

    assert decision.primary_reason == primary_reason
    assert decision.eligible is (primary_reason == "eligible")
    assert "legacy_managed_event_deadline_gate" in decision.policy_codes


# --- annotate (WS-A1b: replaces the cron-prompt jq-rewrite instruction) ------


def _annotate_args(**kw) -> argparse.Namespace:
    return argparse.Namespace(id=kw.get("id"), set=kw.get("set"), set_json=kw.get("set_json"))


def test_annotate_sets_string_and_json_fields_under_lock(tmp_path, monkeypatch) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps([{"id": "email-1", "status": "in_progress", "priority": 1}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    out = task_pool_claim.cmd_annotate(
        _annotate_args(
            id="email-1",
            set=["plan=step one; step two"],
            set_json=['linked_task_ids=["a","b"]', "needs_close_reply=true"],
        )
    )
    assert out == {
        "ok": True,
        "task_id": "email-1",
        "fields": ["linked_task_ids", "needs_close_reply", "plan"],
    }
    row = json.loads(next_tasks.read_text(encoding="utf-8"))[0]
    assert row["plan"] == "step one; step two"
    assert row["linked_task_ids"] == ["a", "b"]
    assert row["needs_close_reply"] is True
    assert row["status"] == "in_progress"  # untouched


def test_annotate_refuses_lifecycle_fields(tmp_path, monkeypatch) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(json.dumps([{"id": "t1", "status": "pending"}]), encoding="utf-8")
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    with pytest.raises(SystemExit, match="lifecycle/identity"):
        task_pool_claim.cmd_annotate(_annotate_args(id="t1", set=["status=succeeded"]))
    assert json.loads(next_tasks.read_text(encoding="utf-8"))[0]["status"] == "pending"


def test_annotate_rejects_bad_json_and_empty_updates(tmp_path, monkeypatch) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(json.dumps([{"id": "t1", "status": "pending"}]), encoding="utf-8")
    monkeypatch.setattr(task_pool_claim, "NEXT_TASKS", next_tasks)
    with pytest.raises(SystemExit, match="invalid JSON"):
        task_pool_claim.cmd_annotate(_annotate_args(id="t1", set_json=["linked=[broken"]))
    with pytest.raises(SystemExit, match="nothing to set"):
        task_pool_claim.cmd_annotate(_annotate_args(id="t1"))
