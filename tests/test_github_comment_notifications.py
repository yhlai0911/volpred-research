from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from volpred.ops.github_comment_notifications import (
    GitHubComment,
    Notification,
    fetch_github_comments,
    reconcile_github_comments,
)

NOW = datetime(2026, 7, 29, 4, 0, tzinfo=UTC)


def _comment(
    comment_id: int,
    *,
    created_at: str,
    number: int = 42,
    kind: str = "issue_comment",
) -> GitHubComment:
    return GitHubComment(
        source=kind,
        comment_id=comment_id,
        number=number,
        author="yhlai0911",
        created_at=created_at,
        url=f"https://github.com/yhlai0911/volpred-research/issues/{number}"
        f"#issuecomment-{comment_id}",
        body=f"comment {comment_id}\nsecond line",
    )


def test_initial_reconcile_delivers_one_digest_then_replay_is_quiet(
    tmp_path: Path,
) -> None:
    comments = [
        _comment(10, created_at="2026-07-28T02:00:00+00:00"),
        _comment(11, created_at="2026-07-29T02:00:00+00:00", number=46),
    ]
    email: list[Notification] = []
    telegram: list[Notification] = []

    def deliver_email(notification: Notification) -> dict[str, object]:
        email.append(notification)
        return {"sent": True, "receipt_id": "email-1"}

    def deliver_telegram(notification: Notification) -> dict[str, object]:
        telegram.append(notification)
        return {"sent": True, "message_ids": [7001]}

    first = reconcile_github_comments(
        fetch_comments=lambda _since: comments,
        deliver_email=deliver_email,
        deliver_telegram=deliver_telegram,
        state_path=tmp_path / "state.json",
        now=NOW,
    )
    second = reconcile_github_comments(
        fetch_comments=lambda _since: comments,
        deliver_email=deliver_email,
        deliver_telegram=deliver_telegram,
        state_path=tmp_path / "state.json",
        now=NOW,
    )

    assert first["mode"] == "backfill"
    assert first["comment_count"] == 2
    assert first["delivery_status"] == "delivered"
    assert first["receipt_count"] == 2
    assert email[0].title == "[新架構派發][GitHub] 近 7 日留言摘要（2 則）"
    assert "#42" in email[0].body
    assert "#46" in email[0].body
    assert telegram[0] == email[0]
    assert second["mode"] == "incremental"
    assert second["comment_count"] == 0
    assert second["receipt_count"] == 2
    assert len(email) == 1
    assert len(telegram) == 1
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert len(state["receipts"]) == 2
    assert state["deliveries"]["issue_comment:10"]["status"] == "delivered"
    assert set(state["deliveries"]["issue_comment:10"]["receipt_keys"]) == {
        "email",
        "telegram",
    }


def test_incremental_partial_delivery_retries_only_missing_channel(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    reconcile_github_comments(
        fetch_comments=lambda _since: [],
        deliver_email=lambda _notification: {"sent": True, "receipt_id": "baseline-email"},
        deliver_telegram=lambda _notification: {"sent": True, "message_ids": [1]},
        state_path=state_path,
        now=NOW,
    )
    comment = _comment(12, created_at="2026-07-29T04:01:00+00:00")
    email_calls = 0
    telegram_calls = 0

    def deliver_email(_notification: Notification) -> dict[str, object]:
        nonlocal email_calls
        email_calls += 1
        return {"sent": True, "receipt_id": "email-12"}

    def deliver_telegram(_notification: Notification) -> dict[str, object]:
        nonlocal telegram_calls
        telegram_calls += 1
        if telegram_calls == 1:
            return {"sent": False, "reason": "temporary Telegram failure"}
        return {"sent": True, "message_ids": [7012]}

    first = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=deliver_email,
        deliver_telegram=deliver_telegram,
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 2, tzinfo=UTC),
    )
    second = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=deliver_email,
        deliver_telegram=deliver_telegram,
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 3, tzinfo=UTC),
    )
    third = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=deliver_email,
        deliver_telegram=deliver_telegram,
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 4, tzinfo=UTC),
    )

    assert first["delivery_status"] == "pending"
    assert second["delivery_status"] == "delivered"
    assert second["cursor"]["comment_id"] == 12
    assert third["comment_count"] == 0
    assert email_calls == 1
    assert telegram_calls == 2


def test_fetcher_combines_paginated_issue_and_pr_review_comments() -> None:
    commands: list[list[str]] = []

    def runner(
        command: list[str],
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if any(part.endswith("issues/comments") for part in command):
            stdout = """[[{"id":101,"issue_url":"https://api.github.com/repos/o/r/issues/42","html_url":"https://github.com/o/r/issues/42#issuecomment-101","user":{"login":"ops"},"created_at":"2026-07-29T04:01:00Z","body":"issue update"},{"id":102,"issue_url":"https://api.github.com/repos/o/r/issues/8","html_url":"https://github.com/o/r/pull/8#issuecomment-102","user":{"login":"ops"},"created_at":"2026-07-29T04:01:30Z","body":"PR conversation update"}],[]]"""
        else:
            stdout = """[[{"id":201,"pull_request_url":"https://api.github.com/repos/o/r/pulls/7","html_url":"https://github.com/o/r/pull/7#discussion_r201","user":{"login":"reviewer"},"created_at":"2026-07-29T04:02:00Z","body":"review update"}]]"""
        return subprocess.CompletedProcess(command, 0, stdout, "")

    comments = fetch_github_comments(
        repo="o/r",
        since=datetime(2026, 7, 29, 4, 0, tzinfo=UTC),
        runner=runner,
    )

    assert [(comment.source, comment.comment_id, comment.number) for comment in comments] == [
        ("issue_comment", 101, 42),
        ("issue_comment", 102, 8),
        ("pull_review_comment", 201, 7),
    ]
    assert [comment.subject_kind for comment in comments] == [
        "issue",
        "pull_request",
        "pull_request",
    ]
    assert all("--paginate" in command and "--slurp" in command for command in commands)
    assert all("since=2026-07-29T04:00:00+00:00" in command for command in commands)


def test_direct_cli_entrypoint_is_runnable_outside_repo(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "github_comment_notifications.py"),
            "--help",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "GitHub comment" in completed.stdout


def test_operations_core_schedule_owns_github_comment_notifications() -> None:
    root = Path(__file__).resolve().parents[1]
    config = json.loads(
        (root / "config" / "runtime_schedules.json").read_text(encoding="utf-8")
    )
    jobs = {
        item["id"]: item
        for item in config["system_crontab"]["items"]
    }

    job = jobs["github_comment_notifications"]
    assert config["schedule_materialization"]["mode"] == "active"
    assert job["cron"] == "*/5 * * * *"
    assert job["host_crontab_managed"] is False
    assert job["wrapper_script"].endswith(
        "/.volpred/bin/cron_github_comment_notifications.sh"
    )
    wrapper = (
        root / "scripts" / "cron_github_comment_notifications.sh"
    ).read_text(encoding="utf-8")
    assert "github_comment_notifications.py" in wrapper
    assert 'cron_emit_exit "github_comment_notifications"' in wrapper


def test_indeterminate_telegram_attempt_blocks_without_duplicate_replay(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    reconcile_github_comments(
        fetch_comments=lambda _since: [],
        deliver_email=lambda _notification: {"sent": True},
        deliver_telegram=lambda _notification: {"sent": True},
        state_path=state_path,
        now=NOW,
    )
    comment = _comment(30, created_at="2026-07-29T04:10:00+00:00")
    telegram_calls = 0

    def interrupted(_notification: Notification) -> dict[str, object]:
        nonlocal telegram_calls
        telegram_calls += 1
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        reconcile_github_comments(
            fetch_comments=lambda _since: [comment],
            deliver_email=lambda _notification: {"sent": True},
            deliver_telegram=interrupted,
            state_path=state_path,
            now=datetime(2026, 7, 29, 4, 11, tzinfo=UTC),
        )

    replay = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=lambda _notification: {"sent": True},
        deliver_telegram=interrupted,
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 12, tzinfo=UTC),
    )

    assert replay["delivery_status"] == "blocked"
    assert replay["blocked_reason"] == "delivery_unknown"
    assert replay["channels"]["telegram"]["status"] == "delivery_unknown"
    assert telegram_calls == 1


def test_same_second_comment_from_other_source_is_not_skipped(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    delivered: list[str] = []

    def sender(notification: Notification) -> dict[str, object]:
        delivered.append(notification.idempotency_key)
        return {"sent": True, "receipt_id": f"receipt-{len(delivered)}"}

    reconcile_github_comments(
        fetch_comments=lambda _since: [],
        deliver_email=sender,
        deliver_telegram=sender,
        state_path=state_path,
        now=NOW,
    )
    delivered.clear()
    pull_comment = _comment(
        300,
        created_at="2026-07-29T04:01:00+00:00",
        number=9,
        kind="pull_review_comment",
    )
    issue_comment = _comment(
        200,
        created_at="2026-07-29T04:01:00+00:00",
        number=52,
    )

    first = reconcile_github_comments(
        fetch_comments=lambda _since: [pull_comment],
        deliver_email=sender,
        deliver_telegram=sender,
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 2, tzinfo=UTC),
    )
    second = reconcile_github_comments(
        fetch_comments=lambda _since: [issue_comment, pull_comment],
        deliver_email=sender,
        deliver_telegram=sender,
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 3, tzinfo=UTC),
    )
    third = reconcile_github_comments(
        fetch_comments=lambda _since: [issue_comment, pull_comment],
        deliver_email=sender,
        deliver_telegram=sender,
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 4, tzinfo=UTC),
    )

    assert first["delivery_status"] == "delivered"
    assert second["delivery_status"] == "delivered"
    assert second["cursors"]["issue_comment"]["comment_id"] == 200
    assert third["comment_count"] == 0
    assert delivered == [
        "github-comment:pull_review_comment:300",
        "github-comment:pull_review_comment:300",
        "github-comment:issue_comment:200",
        "github-comment:issue_comment:200",
    ]


def test_partial_telegram_chunk_does_not_advance_cursor(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    reconcile_github_comments(
        fetch_comments=lambda _since: [],
        deliver_email=lambda _notification: {"sent": True},
        deliver_telegram=lambda _notification: {"sent": True},
        state_path=state_path,
        now=NOW,
    )
    comment = _comment(40, created_at="2026-07-29T04:10:00+00:00")
    email_calls = 0
    telegram_calls = 0

    def email_sender(_notification: Notification) -> dict[str, object]:
        nonlocal email_calls
        email_calls += 1
        return {"sent": True, "receipt_id": "email-40"}

    def telegram_sender(_notification: Notification) -> dict[str, object]:
        nonlocal telegram_calls
        telegram_calls += 1
        if telegram_calls == 1:
            return {
                "sent": True,
                "reason": "second chunk failed",
                "message_ids": [7040],
            }
        return {"sent": True, "message_ids": [7041, 7042]}

    first = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=email_sender,
        deliver_telegram=telegram_sender,
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 11, tzinfo=UTC),
    )
    second = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=email_sender,
        deliver_telegram=telegram_sender,
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 12, tzinfo=UTC),
    )

    assert first["delivery_status"] == "pending"
    assert first["channels"]["telegram"]["status"] == "failed"
    assert first["cursors"]["issue_comment"]["comment_id"] == 0
    assert second["delivery_status"] == "delivered"
    assert second["cursors"]["issue_comment"]["comment_id"] == 40
    assert email_calls == 1
    assert telegram_calls == 2


def test_fetch_failure_is_observable() -> None:
    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "HTTP 401: Bad credentials")

    with pytest.raises(RuntimeError, match="401"):
        fetch_github_comments(
            repo="o/r",
            since=NOW,
            runner=runner,
        )


def test_malformed_github_response_is_observable() -> None:
    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "{not-json", "")

    with pytest.raises(json.JSONDecodeError):
        fetch_github_comments(
            repo="o/r",
            since=NOW,
            runner=runner,
        )


def test_mailbox_trash_state_cannot_suppress_github_ingress(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    mailbox_state = tmp_path / "mailbox-trash.json"
    reconcile_github_comments(
        fetch_comments=lambda _since: [],
        deliver_email=lambda _notification: {"sent": True},
        deliver_telegram=lambda _notification: {"sent": True},
        state_path=state_path,
        now=NOW,
    )
    mailbox_state.write_text('{"github_notifications":"trashed"}', encoding="utf-8")
    comment = _comment(50, created_at="2026-07-29T04:20:00+00:00")

    result = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=lambda _notification: {"sent": True, "receipt_id": "email-50"},
        deliver_telegram=lambda _notification: {"sent": True, "message_ids": [7050]},
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 21, tzinfo=UTC),
    )

    assert result["delivery_status"] == "delivered"
    assert result["cursors"]["issue_comment"]["comment_id"] == 50
