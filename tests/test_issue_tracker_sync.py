from __future__ import annotations

import json
from types import SimpleNamespace

from volpred.ops.issue_tracker_sync import (
    assign_issue,
    close_issue,
    settle_completed_task_issues,
)


def test_assign_issue_uses_absolute_gh_without_shell(tmp_path) -> None:
    calls = []

    def fake_runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = assign_issue(
        "#37",
        repo_root=tmp_path,
        gh_binary="/opt/homebrew/bin/gh",
        runner=fake_runner,
    )

    assert result["ok"] is True
    assert calls[0][0] == [
        "/opt/homebrew/bin/gh",
        "issue",
        "edit",
        "37",
        "--add-assignee",
        "@me",
    ]
    assert calls[0][1]["shell"] is False


def test_close_issue_replay_recognizes_existing_task_commit_marker(
    tmp_path,
) -> None:
    commit_sha = "a" * 40
    marker = f"volpred-task:linked-ticket:commit:{commit_sha}"
    calls = []

    def fake_runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "state": "CLOSED",
                    "comments": [{"body": f"done\n<!-- {marker} -->"}],
                }
            ),
            stderr="",
        )

    result = close_issue(
        issue_ref="#37",
        commit_sha=commit_sha,
        task_id="linked-ticket",
        summary="done",
        repo_root=tmp_path,
        gh_binary="/opt/homebrew/bin/gh",
        runner=fake_runner,
    )

    assert result["ok"] is True
    assert result["already_closed"] is True
    assert len(calls) == 1
    assert calls[0][0][1:4] == ["issue", "view", "37"]


def test_close_issue_refuses_to_claim_foreign_closed_issue(tmp_path) -> None:
    calls = []

    def fake_runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {"state": "CLOSED", "comments": [{"body": "closed manually"}]}
            ),
            stderr="",
        )

    result = close_issue(
        issue_ref="#37",
        commit_sha="b" * 40,
        task_id="linked-ticket",
        summary="done",
        repo_root=tmp_path,
        gh_binary="/opt/homebrew/bin/gh",
        runner=fake_runner,
    )

    assert result["ok"] is False
    assert result["reason"] == "issue_closed_without_receipt"
    assert len(calls) == 1


def test_close_issue_requires_closed_state_and_marker_readback(tmp_path) -> None:
    responses = [
        SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"state": "OPEN", "comments": []}),
            stderr="",
        ),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
        SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"state": "CLOSED", "comments": []}),
            stderr="",
        ),
    ]

    result = close_issue(
        issue_ref="#37",
        commit_sha="c" * 40,
        task_id="linked-ticket",
        summary="done",
        repo_root=tmp_path,
        gh_binary="/opt/homebrew/bin/gh",
        runner=lambda *_args, **_kwargs: responses.pop(0),
    )

    assert result["ok"] is False
    assert result["reason"] == "close_readback_mismatch"


def test_close_issue_succeeds_after_exact_marker_readback(tmp_path) -> None:
    commit_sha = "d" * 40
    marker = f"volpred-task:linked-ticket:commit:{commit_sha}"
    responses = [
        SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"state": "OPEN", "comments": []}),
            stderr="",
        ),
        SimpleNamespace(returncode=0, stdout="", stderr=""),
        SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "state": "CLOSED",
                    "comments": [{"body": f"done\n<!-- {marker} -->"}],
                }
            ),
            stderr="",
        ),
    ]

    result = close_issue(
        issue_ref="#37",
        commit_sha=commit_sha,
        task_id="linked-ticket",
        summary="done",
        repo_root=tmp_path,
        gh_binary="/opt/homebrew/bin/gh",
        runner=lambda *_args, **_kwargs: responses.pop(0),
    )

    assert result["ok"] is True
    assert result["already_closed"] is False
    assert responses == []


def test_post_commit_settlement_closes_issue_and_binds_exact_commit(
    tmp_path,
) -> None:
    queue = tmp_path / "next_tasks.json"
    pending = {
        "issue_ref": "#37",
        "task_id": "linked-ticket",
        "completion_owner": "codex-vscode",
        "completed_at": "2026-07-26T12:00:00+00:00",
        "completion_base_commit": "0" * 40,
    }
    queue.write_text(
        json.dumps(
            [
                {
                    "id": "linked-ticket",
                    "status": "succeeded",
                    "priority": 2,
                    "result": "implemented acceptance criteria",
                    "issue_ref": "#37",
                    "issue_close_pending": pending,
                }
            ]
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_closer(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "action": "close",
            "issue_ref": "#37",
            "issue_number": 37,
            "already_closed": False,
        }

    commit_sha = "a" * 40
    settled = settle_completed_task_issues(
        path=queue,
        claim_owners={"codex-vscode"},
        commit_sha=commit_sha,
        commit_parent_sha="0" * 40,
        repo_root=tmp_path,
        closer=fake_closer,
    )

    assert settled == [
        {
            "task_id": "linked-ticket",
            "issue_ref": "#37",
            "issue_number": 37,
            "commit_sha": commit_sha,
        }
    ]
    assert calls == [
        {
            "issue_ref": "#37",
            "commit_sha": commit_sha,
            "task_id": "linked-ticket",
            "summary": "implemented acceptance criteria",
            "repo_root": tmp_path,
        }
    ]
    saved = json.loads(queue.read_text(encoding="utf-8"))[0]
    assert saved["issue_closed_commit"] == commit_sha
    assert saved["issue_closed_at"]
    assert "issue_close_pending" not in saved


def test_post_commit_issue_failure_stays_retryable(tmp_path) -> None:
    queue = tmp_path / "next_tasks.json"
    pending = {
        "issue_ref": "#37",
        "task_id": "linked-ticket",
        "completion_owner": "codex-vscode",
        "completed_at": "2026-07-26T12:00:00+00:00",
        "completion_base_commit": "1" * 40,
    }
    original = [
        {
            "id": "linked-ticket",
            "status": "succeeded",
            "priority": 2,
            "issue_ref": "#37",
            "issue_close_pending": pending,
        }
    ]
    queue.write_text(json.dumps(original), encoding="utf-8")

    settled = settle_completed_task_issues(
        path=queue,
        claim_owners={"codex-vscode"},
        commit_sha="b" * 40,
        commit_parent_sha="1" * 40,
        repo_root=tmp_path,
        closer=lambda **_kwargs: {
            "ok": False,
            "action": "close",
            "reason": "gh_unavailable",
        },
    )

    assert settled == []
    saved = json.loads(queue.read_text(encoding="utf-8"))
    assert saved[0]["issue_close_pending"]["commit_sha"] == "b" * 40


def test_failed_close_retries_original_commit_not_later_owner_commit(tmp_path) -> None:
    queue = tmp_path / "next_tasks.json"
    pending = {
        "issue_ref": "#37",
        "task_id": "task-a",
        "completion_owner": "codex-vscode",
        "completed_at": "2026-07-26T12:00:00+00:00",
        "completion_base_commit": "1" * 40,
    }
    queue.write_text(
        json.dumps(
            [
                {
                    "id": "task-a",
                    "status": "succeeded",
                    "issue_ref": "#37",
                    "issue_close_pending": pending,
                }
            ]
        ),
        encoding="utf-8",
    )

    first = settle_completed_task_issues(
        path=queue,
        claim_owners={"codex-vscode"},
        commit_sha="2" * 40,
        commit_parent_sha="1" * 40,
        repo_root=tmp_path,
        closer=lambda **_kwargs: {"ok": False, "reason": "gh_unavailable"},
    )
    calls = []

    second = settle_completed_task_issues(
        path=queue,
        claim_owners={"codex-vscode"},
        commit_sha="3" * 40,
        commit_parent_sha="2" * 40,
        repo_root=tmp_path,
        closer=lambda **kwargs: calls.append(kwargs)
        or {"ok": True, "issue_number": 37},
    )

    assert first == []
    assert second[0]["commit_sha"] == "2" * 40
    assert calls[0]["commit_sha"] == "2" * 40
    saved = json.loads(queue.read_text(encoding="utf-8"))[0]
    assert saved["issue_closed_commit"] == "2" * 40
