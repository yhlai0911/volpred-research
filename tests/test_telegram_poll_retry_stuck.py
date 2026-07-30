"""Regression gate for the Telegram responder retry driver.

2026-07-16: the responder is purely event-driven — spawned only when a new
message arrives. When it died (Claude quota exit=1, missing dep FATAL), nothing
retried it, so the boss's 21:46 message sat unanswered even after quota reset at
22:20; it took the boss asking again to surface it.

The code claimed "hourly dispatch 兜底, 最壞 ~1h" in three comments, but
task-routing.md explicitly excludes telegram_reply from hourly/Codex claim —
the fallback never existed. The poll daemon's while-loop is the retry driver.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import scripts.telegram_poll as poll


@pytest.fixture(autouse=True)
def _reset_backoff(monkeypatch, tmp_path):
    poll._last_retry_spawn = None
    monkeypatch.setattr(
        poll,
        "TELEGRAM_POLL_LOG",
        tmp_path / "telegram_poll.log",
    )
    yield
    poll._last_retry_spawn = None


@pytest.fixture
def spawned(monkeypatch):
    """Capture responder spawns without launching a real headless Claude."""
    calls: list[str] = []
    monkeypatch.setattr(poll, "_spawn_responder", lambda *a, **k: calls.append("spawn") or True)
    return calls


def _install_queue(monkeypatch, tmp_path: Path, tasks: list[dict]) -> None:
    storage = tmp_path / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    (storage / "next_tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
    monkeypatch.setattr(poll, "ROOT", tmp_path)


def _reply(*, age_seconds: float, status: str = "pending", task_id: str = "telegram-1") -> dict:
    created = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return {
        "id": task_id,
        "task_type": "telegram_reply",
        "status": status,
        "created_at": created.isoformat(),
    }


def test_stuck_pending_reply_triggers_respawn(monkeypatch, tmp_path, spawned):
    """The 2026-07-16 shape: responder died, message still pending."""
    _install_queue(monkeypatch, tmp_path, [_reply(age_seconds=poll.RETRY_AGE_THRESHOLD_SEC + 60)])

    poll._retry_stuck_replies()

    assert spawned == ["spawn"]
    assert poll.TELEGRAM_POLL_LOG.parent == tmp_path


def test_fresh_reply_is_left_alone(monkeypatch, tmp_path, spawned):
    """A responder spawned seconds ago deserves a chance before we pile on."""
    _install_queue(monkeypatch, tmp_path, [_reply(age_seconds=5)])

    poll._retry_stuck_replies()

    assert spawned == []


def test_claimed_reply_is_not_respawned(monkeypatch, tmp_path, spawned):
    """Claimed means a responder is on it; respawning would duplicate work."""
    _install_queue(
        monkeypatch, tmp_path, [_reply(age_seconds=3600, status="claimed")]
    )

    poll._retry_stuck_replies()

    assert spawned == []


def test_answered_reply_is_not_respawned(monkeypatch, tmp_path, spawned):
    _install_queue(
        monkeypatch, tmp_path, [_reply(age_seconds=7200, status="succeeded")]
    )

    poll._retry_stuck_replies()

    assert spawned == []


def test_backoff_prevents_burning_quota_every_pass(monkeypatch, tmp_path, spawned):
    """Quota-exhausted responders fail instantly; a poll pass is ~25s.

    Without backoff the daemon would respawn opus every pass while the queue
    stays stuck — exactly when quota is already the problem.
    """
    _install_queue(monkeypatch, tmp_path, [_reply(age_seconds=poll.RETRY_AGE_THRESHOLD_SEC + 60)])

    poll._retry_stuck_replies()
    poll._retry_stuck_replies()
    poll._retry_stuck_replies()

    assert spawned == ["spawn"], "backoff must collapse repeated passes into one spawn"


def test_backoff_expires_and_retries_again(monkeypatch, tmp_path, spawned):
    """Backoff must not become a permanent mute."""
    _install_queue(monkeypatch, tmp_path, [_reply(age_seconds=poll.RETRY_AGE_THRESHOLD_SEC + 60)])

    poll._retry_stuck_replies()
    poll._last_retry_spawn = datetime.now(timezone.utc) - timedelta(
        seconds=poll.RETRY_MIN_INTERVAL_SEC + 10
    )
    poll._retry_stuck_replies()

    assert spawned == ["spawn", "spawn"]


def test_other_task_types_do_not_trigger_responder(monkeypatch, tmp_path, spawned):
    _install_queue(
        monkeypatch,
        tmp_path,
        [{
            "id": "article-1",
            "task_type": "daily_article",
            "status": "pending",
            "created_at": (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat(),
        }],
    )

    poll._retry_stuck_replies()

    assert spawned == []


def test_unreadable_queue_does_not_kill_daemon(monkeypatch, tmp_path, spawned):
    """The poll daemon must survive a corrupt queue, not crash the boss channel."""
    storage = tmp_path / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    (storage / "next_tasks.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(poll, "ROOT", tmp_path)

    poll._retry_stuck_replies()  # must not raise

    assert spawned == []


def test_missing_queue_does_not_crash(monkeypatch, tmp_path, spawned):
    monkeypatch.setattr(poll, "ROOT", tmp_path)

    poll._retry_stuck_replies()  # must not raise

    assert spawned == []
