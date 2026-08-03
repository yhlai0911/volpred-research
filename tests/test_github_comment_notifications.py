from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import github_comment_notifications as cli
from volpred.ops.github_comment_notifications import (
    TELEGRAM_MAX_MESSAGE_CHARS,
    GitHubComment,
    Notification,
    _telegram_payload,
    fetch_github_comments,
    reconcile_github_comments,
)
from volpred.ops.telegram import _chunks

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
        subject_kind=(
            "pull_request" if kind == "pull_review_comment" else "issue"
        ),
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


def test_self_authored_comments_are_audit_only_and_advance_cursor(
    tmp_path: Path,
) -> None:
    own = _comment(13, created_at="2026-07-29T04:01:00+00:00")
    external = GitHubComment(
        source="issue_comment",
        comment_id=14,
        number=42,
        author="reviewer",
        created_at="2026-07-29T04:02:00+00:00",
        url="https://github.com/yhlai0911/volpred-research/issues/42#issuecomment-14",
        body="Please fix the failing gate",
    )
    email: list[Notification] = []
    telegram: list[Notification] = []

    result = reconcile_github_comments(
        fetch_comments=lambda _since: [own, external],
        deliver_email=lambda notification: (
            email.append(notification) or {"sent": True}
        ),
        deliver_telegram=lambda notification: (
            telegram.append(notification) or {"sent": True}
        ),
        state_path=tmp_path / "state.json",
        now=NOW,
        self_authors={"yhlai0911"},
    )

    assert result["comment_count"] == 1
    assert result["ignored_self_authored_count"] == 1
    assert result["delivery_status"] == "delivered"
    assert len(email) == 1
    assert len(telegram) == 1
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["deliveries"]["issue_comment:13"]["status"] == (
        "ignored_self_authored"
    )
    assert state["deliveries"]["issue_comment:14"]["status"] == "delivered"
    assert state["cursors"]["issue_comment"]["comment_id"] == 14


def test_all_self_authored_backfill_sends_nothing_but_records_receipt(
    tmp_path: Path,
) -> None:
    own = _comment(15, created_at="2026-07-29T04:03:00+00:00")
    sent: list[Notification] = []

    result = reconcile_github_comments(
        fetch_comments=lambda _since: [own],
        deliver_email=lambda notification: (sent.append(notification) or {"sent": True}),
        deliver_telegram=lambda notification: (sent.append(notification) or {"sent": True}),
        state_path=tmp_path / "state.json",
        now=NOW,
        self_authors={"yhlai0911"},
    )

    assert result["mode"] == "backfill"
    assert result["delivery_status"] == "idle"
    assert result["comment_count"] == 0
    assert result["ignored_self_authored_count"] == 1
    assert sent == []
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["backfill_completed_at"] == NOW.isoformat()
    assert state["deliveries"]["issue_comment:15"]["status"] == (
        "ignored_self_authored"
    )


def test_incremental_email_batch_retries_without_telegram_mirror(
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
        if email_calls == 1:
            return {"sent": False, "reason": "temporary email failure"}
        return {"sent": True, "receipt_id": "email-12"}

    def deliver_telegram(_notification: Notification) -> dict[str, object]:
        nonlocal telegram_calls
        telegram_calls += 1
        return {"sent": True, "message_ids": [7012]}

    buffered = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=deliver_email,
        deliver_telegram=deliver_telegram,
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 2, tzinfo=UTC),
    )
    first_attempt = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=deliver_email,
        deliver_telegram=deliver_telegram,
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 17, tzinfo=UTC),
    )
    second_attempt = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=deliver_email,
        deliver_telegram=deliver_telegram,
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 18, tzinfo=UTC),
    )

    assert buffered["delivery_status"] == "buffered"
    assert buffered["cursor"]["comment_id"] == 12
    assert first_attempt["delivery_status"] == "pending"
    assert second_attempt["delivery_status"] == "delivered"
    assert second_attempt["pending_batch_count"] == 0
    assert email_calls == 2
    assert telegram_calls == 0


def test_incremental_comments_batch_per_issue_for_fifteen_minutes_email_only(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    email: list[Notification] = []
    telegram: list[Notification] = []
    reconcile_github_comments(
        fetch_comments=lambda _since: [],
        deliver_email=lambda _notification: {"sent": True},
        deliver_telegram=lambda _notification: {"sent": True},
        state_path=state_path,
        now=NOW,
    )
    first_comment = _comment(
        60,
        created_at="2026-07-29T04:01:00+00:00",
    )
    second_comment = _comment(
        61,
        created_at="2026-07-29T04:06:00+00:00",
    )

    buffered = reconcile_github_comments(
        fetch_comments=lambda _since: [first_comment],
        deliver_email=lambda notification: (
            email.append(notification) or {"sent": True, "receipt_id": "email-batch"}
        ),
        deliver_telegram=lambda notification: (
            telegram.append(notification) or {"sent": True, "message_ids": [7060]}
        ),
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 2, tzinfo=UTC),
    )
    coalesced = reconcile_github_comments(
        fetch_comments=lambda _since: [first_comment, second_comment],
        deliver_email=lambda notification: (
            email.append(notification) or {"sent": True, "receipt_id": "email-batch"}
        ),
        deliver_telegram=lambda notification: (
            telegram.append(notification) or {"sent": True, "message_ids": [7060]}
        ),
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 7, tzinfo=UTC),
    )
    delivered = reconcile_github_comments(
        fetch_comments=lambda _since: [first_comment, second_comment],
        deliver_email=lambda notification: (
            email.append(notification) or {"sent": True, "receipt_id": "email-batch"}
        ),
        deliver_telegram=lambda notification: (
            telegram.append(notification) or {"sent": True, "message_ids": [7060]}
        ),
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 17, tzinfo=UTC),
    )

    assert buffered["delivery_status"] == "buffered"
    assert buffered["pending_batch_count"] == 1
    assert buffered["cursors"]["issue_comment"]["comment_id"] == 60
    assert coalesced["delivery_status"] == "buffered"
    assert coalesced["pending_batch_count"] == 1
    assert coalesced["cursors"]["issue_comment"]["comment_id"] == 61
    assert delivered["delivery_status"] == "delivered"
    assert delivered["pending_batch_count"] == 0
    assert len(email) == 1
    assert telegram == []
    assert email[0].title == "[新架構派發][GitHub #42] Issue 留言摘要（2 則）"
    assert "issue_comment:60" in email[0].body
    assert "issue_comment:61" in email[0].body


def test_comment_observed_after_due_time_starts_the_next_fixed_window(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    email: list[Notification] = []
    reconcile_github_comments(
        fetch_comments=lambda _since: [],
        deliver_email=lambda _notification: {"sent": True},
        deliver_telegram=lambda _notification: {"sent": True},
        state_path=state_path,
        now=NOW,
    )
    first = _comment(70, created_at="2026-07-29T04:01:00+00:00")
    after_due = _comment(71, created_at="2026-07-29T04:19:00+00:00")
    sender = lambda notification: (
        email.append(notification)
        or {"sent": True, "receipt_id": f"email-{len(email)}"}
    )

    reconcile_github_comments(
        fetch_comments=lambda _since: [first],
        deliver_email=sender,
        deliver_telegram=lambda _notification: {"sent": True},
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 2, tzinfo=UTC),
    )
    split = reconcile_github_comments(
        fetch_comments=lambda _since: [first, after_due],
        deliver_email=sender,
        deliver_telegram=lambda _notification: {"sent": True},
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 20, tzinfo=UTC),
    )
    final = reconcile_github_comments(
        fetch_comments=lambda _since: [first, after_due],
        deliver_email=sender,
        deliver_telegram=lambda _notification: {"sent": True},
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 35, tzinfo=UTC),
    )

    assert split["delivered_batch_count"] == 1
    assert split["pending_batch_count"] == 1
    assert split["delivery_status"] == "buffered"
    assert len(email) == 2
    assert "issue_comment:70" in email[0].body
    assert "issue_comment:71" not in email[0].body
    assert "issue_comment:71" in email[1].body
    assert "issue_comment:70" not in email[1].body
    assert final["delivery_status"] == "delivered"
    assert final["pending_batch_count"] == 0


def test_schema_v2_state_migrates_in_place_without_replaying_deliveries(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    comment = _comment(
        10,
        created_at="2026-07-29T04:01:00+00:00",
    )
    legacy_notification = Notification(
        idempotency_key="github-comment:issue_comment:10",
        title="legacy",
        body="legacy",
    )
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "backfill_completed_at": NOW.isoformat(),
                "cursors": {
                    source: {
                        "created_at": NOW.isoformat(),
                        "source": source,
                        "comment_id": 0,
                    }
                    for source in ("issue_comment", "pull_review_comment")
                },
                "pending_backfill": None,
                "deliveries": {
                    "issue_comment:10": {
                        "comment": asdict(comment),
                        "notification": asdict(legacy_notification),
                        "email": {
                            "status": "delivered",
                            "receipt": {"sent": True, "receipt_id": "email-10"},
                        },
                        "telegram": {
                            "status": "delivered",
                            "receipt": {"sent": True, "message_ids": [10]},
                        },
                    }
                },
                "receipts": {},
            }
        ),
        encoding="utf-8",
    )
    sent: list[Notification] = []

    result = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=lambda notification: (
            sent.append(notification) or {"sent": True}
        ),
        deliver_telegram=lambda notification: (
            sent.append(notification) or {"sent": True}
        ),
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 2, tzinfo=UTC),
    )

    migrated = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["delivery_status"] == "idle"
    assert migrated["schema_version"] == 3
    assert migrated["pending_batches"] == {}
    assert migrated["deliveries"]["issue_comment:10"]["status"] == "delivered"
    assert migrated["cursors"]["issue_comment"]["comment_id"] == 10
    assert set(migrated["deliveries"]["issue_comment:10"]["receipt_keys"]) == {
        "email",
        "telegram",
    }
    assert sent == []


@pytest.mark.parametrize("legacy_status", ["pending", "failed"])
def test_schema_v2_retryable_email_migrates_to_due_batch(
    tmp_path: Path,
    legacy_status: str,
) -> None:
    state_path = tmp_path / "state.json"
    comment = _comment(20, created_at="2026-07-29T04:01:00+00:00")
    legacy_notification = Notification(
        idempotency_key="github-comment:issue_comment:20",
        title="legacy",
        body="legacy",
    )
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "backfill_completed_at": NOW.isoformat(),
                "cursors": {
                    source: {
                        "created_at": NOW.isoformat(),
                        "source": source,
                        "comment_id": 0,
                    }
                    for source in ("issue_comment", "pull_review_comment")
                },
                "pending_backfill": None,
                "deliveries": {
                    comment.delivery_key: {
                        "comment": asdict(comment),
                        "notification": asdict(legacy_notification),
                        "email": {"status": legacy_status},
                        "telegram": {"status": "pending"},
                    }
                },
                "receipts": {},
            }
        ),
        encoding="utf-8",
    )
    email: list[Notification] = []
    telegram: list[Notification] = []

    result = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=lambda notification: (
            email.append(notification)
            or {"sent": True, "receipt_id": "migrated-email-20"}
        ),
        deliver_telegram=lambda notification: (
            telegram.append(notification) or {"sent": True}
        ),
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 2, tzinfo=UTC),
    )

    migrated = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["delivery_status"] == "delivered"
    assert result["pending_batch_count"] == 0
    assert migrated["schema_version"] == 3
    assert migrated["cursors"]["issue_comment"]["comment_id"] == 20
    assert migrated["deliveries"][comment.delivery_key]["status"] == "delivered"
    assert len(email) == 1
    assert email[0].title == "[新架構派發][GitHub #42] Issue 留言摘要（1 則）"
    assert telegram == []


@pytest.mark.parametrize("legacy_status", ["in_flight", "delivery_unknown"])
def test_schema_v2_indeterminate_email_migrates_without_replaying(
    tmp_path: Path,
    legacy_status: str,
) -> None:
    state_path = tmp_path / "state.json"
    comment = _comment(21, created_at="2026-07-29T04:01:00+00:00")
    legacy_notification = Notification(
        idempotency_key="github-comment:issue_comment:21",
        title="legacy",
        body="legacy",
    )
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "backfill_completed_at": NOW.isoformat(),
                "cursors": {
                    source: {
                        "created_at": NOW.isoformat(),
                        "source": source,
                        "comment_id": 0,
                    }
                    for source in ("issue_comment", "pull_review_comment")
                },
                "pending_backfill": None,
                "deliveries": {
                    comment.delivery_key: {
                        "comment": asdict(comment),
                        "notification": asdict(legacy_notification),
                        "email": {"status": legacy_status},
                        "telegram": {"status": "pending"},
                    }
                },
                "receipts": {},
            }
        ),
        encoding="utf-8",
    )
    sent: list[Notification] = []

    result = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=lambda notification: (
            sent.append(notification) or {"sent": True}
        ),
        deliver_telegram=lambda notification: (
            sent.append(notification) or {"sent": True}
        ),
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 2, tzinfo=UTC),
    )

    migrated = json.loads(state_path.read_text(encoding="utf-8"))
    batch = next(iter(migrated["pending_batches"].values()))
    assert result["delivery_status"] == "blocked"
    assert result["blocked_reason"] == "delivery_unknown"
    assert migrated["schema_version"] == 3
    assert migrated["cursors"]["issue_comment"]["comment_id"] == 21
    assert migrated["deliveries"][comment.delivery_key]["status"] == "buffered"
    assert batch["email"]["status"] == "delivery_unknown"
    assert sent == []


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


def test_cli_treats_durably_buffered_comments_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "run_github_comment_notifications",
        lambda **_kwargs: {"delivery_status": "buffered"},
    )

    assert cli.main([]) == 0


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


def test_indeterminate_batch_email_blocks_without_duplicate_replay(
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
    email_calls = 0

    def interrupted(_notification: Notification) -> dict[str, object]:
        nonlocal email_calls
        email_calls += 1
        raise KeyboardInterrupt

    reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=interrupted,
        deliver_telegram=lambda _notification: {"sent": True},
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 11, tzinfo=UTC),
    )
    with pytest.raises(KeyboardInterrupt):
        reconcile_github_comments(
            fetch_comments=lambda _since: [comment],
            deliver_email=interrupted,
            deliver_telegram=lambda _notification: {"sent": True},
            state_path=state_path,
            now=datetime(2026, 7, 29, 4, 26, tzinfo=UTC),
        )

    replay = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=interrupted,
        deliver_telegram=lambda _notification: {"sent": True},
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 27, tzinfo=UTC),
    )

    assert replay["delivery_status"] == "blocked"
    assert replay["blocked_reason"] == "delivery_unknown"
    assert replay["channels"]["email"]["status"] == "delivery_unknown"
    assert email_calls == 1


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
        now=datetime(2026, 7, 29, 4, 20, tzinfo=UTC),
    )

    assert first["delivery_status"] == "buffered"
    assert second["delivery_status"] == "buffered"
    assert second["cursors"]["issue_comment"]["comment_id"] == 200
    assert second["cursors"]["pull_review_comment"]["comment_id"] == 300
    assert third["delivery_status"] == "delivered"
    assert third["pending_batch_count"] == 0
    assert delivered == [
        "github-comments:batch:pull_request:9:pull_review_comment:300",
        "github-comments:batch:issue:52:issue_comment:200",
    ]


def test_partial_email_receipt_retries_without_duplicate_batch(
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
        if email_calls == 1:
            return {
                "sent": True,
                "reason": "provider accepted but receipt was incomplete",
                "receipt_id": "email-40-partial",
            }
        return {"sent": True, "receipt_id": "email-40"}

    def telegram_sender(_notification: Notification) -> dict[str, object]:
        nonlocal telegram_calls
        telegram_calls += 1
        return {"sent": True, "message_ids": [7040]}

    buffered = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=email_sender,
        deliver_telegram=telegram_sender,
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 11, tzinfo=UTC),
    )
    first = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=email_sender,
        deliver_telegram=telegram_sender,
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 26, tzinfo=UTC),
    )
    second = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=email_sender,
        deliver_telegram=telegram_sender,
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 27, tzinfo=UTC),
    )

    assert buffered["delivery_status"] == "buffered"
    assert buffered["cursors"]["issue_comment"]["comment_id"] == 40
    assert first["delivery_status"] == "pending"
    assert first["channels"]["email"]["status"] == "failed"
    assert second["delivery_status"] == "delivered"
    assert second["cursors"]["issue_comment"]["comment_id"] == 40
    assert email_calls == 2
    assert telegram_calls == 0


def test_large_backfill_is_bounded_to_one_telegram_message(
    tmp_path: Path,
) -> None:
    comments = [
        _comment(
            10_000 + index,
            created_at=f"2026-07-28T02:{index % 60:02d}:00+00:00",
            number=20 + (index % 30),
        )
        for index in range(150)
    ]
    telegram: list[Notification] = []

    result = reconcile_github_comments(
        fetch_comments=lambda _since: comments,
        deliver_email=lambda _notification: {"sent": True, "receipt_id": "email"},
        deliver_telegram=lambda notification: (
            telegram.append(notification)
            or {"sent": True, "message_ids": [9001]}
        ),
        state_path=tmp_path / "state.json",
        now=NOW,
    )

    payload = _telegram_payload(telegram[0])
    assert len(payload) <= TELEGRAM_MAX_MESSAGE_CHARS
    assert len(_chunks(payload)) == 1
    assert "另有" in payload
    assert result["comment_count"] == 150
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert len(state["deliveries"]) == 150


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

    buffered = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=lambda _notification: {"sent": True, "receipt_id": "email-50"},
        deliver_telegram=lambda _notification: {"sent": True, "message_ids": [7050]},
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 21, tzinfo=UTC),
    )
    result = reconcile_github_comments(
        fetch_comments=lambda _since: [comment],
        deliver_email=lambda _notification: {"sent": True, "receipt_id": "email-50"},
        deliver_telegram=lambda _notification: {"sent": True, "message_ids": [7050]},
        state_path=state_path,
        now=datetime(2026, 7, 29, 4, 36, tzinfo=UTC),
    )

    assert buffered["delivery_status"] == "buffered"
    assert buffered["cursors"]["issue_comment"]["comment_id"] == 50
    assert result["delivery_status"] == "delivered"
    assert result["cursors"]["issue_comment"]["comment_id"] == 50
