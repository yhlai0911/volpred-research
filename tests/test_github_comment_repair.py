from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from volpred.ops.github_comment_notifications import (
    GitHubComment,
    reconcile_github_comments,
)
from volpred.ops.github_comment_repair import (
    repair_kind,
    resolve_github_comment_repair,
)


NOW = datetime(2026, 8, 3, 4, 0, tzinfo=UTC)


def _comment(body: str) -> GitHubComment:
    return GitHubComment(
        source="issue_comment",
        comment_id=901,
        number=13,
        author="reviewer",
        created_at=NOW.isoformat(),
        url="https://github.com/yhlai0911/volpred-research/issues/13#issuecomment-901",
        body=body,
    )


def test_repair_marker_is_explicit_and_bounded() -> None:
    assert repair_kind("plain request") is None
    assert repair_kind("<!-- volpred-repair kind=silent_fallback_new -->") == (
        "silent_fallback_new"
    )
    assert repair_kind("<!-- volpred-repair kind=arbitrary_code -->") == (
        "arbitrary_code"
    )


def test_unmarked_comment_is_notification_only(tmp_path: Path) -> None:
    result = resolve_github_comment_repair(
        _comment("Please take a look"), storage_dir=str(tmp_path), now=NOW
    )

    assert result["action"] == "notify_only"
    assert not (tmp_path / "next_tasks.json").exists()


def test_marked_comment_enters_incident_task_and_keeps_issue_link(tmp_path: Path) -> None:
    (tmp_path / "next_tasks.json").write_text("[]\n", encoding="utf-8")
    result = resolve_github_comment_repair(
        _comment("<!-- volpred-repair kind=silent_fallback_new -->\nPlease repair"),
        storage_dir=str(tmp_path),
        now=NOW,
    )

    assert result["action"] == "repair_admitted"
    tasks = json.loads((tmp_path / "next_tasks.json").read_text(encoding="utf-8"))
    assert len(tasks) == 1
    assert tasks[0]["issue_ref"] == "#13"
    assert tasks[0]["github_comment_key"] == "issue_comment:901"
    assert tasks[0]["source"] == "internal_alert_remediation_router"


def test_marked_comment_with_unknown_kind_is_blocked(tmp_path: Path) -> None:
    result = resolve_github_comment_repair(
        _comment("<!-- volpred-repair kind=unknown_kind -->"),
        storage_dir=str(tmp_path),
        now=NOW,
    )

    assert result["action"] == "blocked"
    assert result["reason"] == "unsupported_repair_kind"


def test_incremental_ingress_persists_repair_admission_receipt(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    reconcile_github_comments(
        fetch_comments=lambda _since: [],
        deliver_email=lambda _notification: {"sent": True},
        deliver_telegram=lambda _notification: {"sent": True},
        state_path=state_path,
        now=NOW,
    )
    comment = _comment("<!-- volpred-repair kind=silent_fallback_new -->")

    result = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=lambda _notification: {"sent": True},
        deliver_telegram=lambda _notification: {"sent": True},
        state_path=state_path,
        now=NOW.replace(minute=2),
        resolve_repair=lambda item: {
            "comment_key": item.delivery_key,
            "action": "repair_admitted",
            "task_id": "task-1",
        },
    )

    assert result["repair_results"] == [
        {
            "comment_key": "issue_comment:901",
            "action": "repair_admitted",
            "task_id": "task-1",
        }
    ]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    delivery = state["deliveries"]["issue_comment:901"]
    assert delivery["repair"]["task_id"] == "task-1"
