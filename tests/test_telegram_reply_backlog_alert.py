"""Regression gate for the Telegram reply-backlog dead-man switch.

2026-07-16 incident: telegram_poll's heartbeat stayed green the whole time
(messages arrived, tasks were enqueued), but telegram_responder.sh died —
first on exhausted Claude weekly quota (exit=1), then on a hardcoded
/opt/homebrew/bin/jq that brew had removed (FATAL). The boss's messages went
unanswered for 20 hours and only surfaced because he asked about it himself.

Ingress freshness and egress delivery are independent failure surfaces; this
gate pins the outcome measure (did the message actually get answered) so a
dead responder cannot hide behind a healthy poller again.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from volpred.ops.alerts import (
    TELEGRAM_REPLY_BACKLOG_CRITICAL_MINUTES,
    TELEGRAM_REPLY_BACKLOG_WARN_MINUTES,
    _parse_telegram_reply_backlog_state,
)

NOW = datetime(2026, 7, 16, 12, 40, tzinfo=timezone.utc)
RESPONDER = Path(__file__).resolve().parents[1] / "scripts" / "telegram_responder.sh"


def _write_tasks(storage_dir: Path, tasks: list[dict]) -> None:
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / "next_tasks.json").write_text(
        json.dumps(tasks, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _task(*, age_minutes: float, status: str = "pending", task_id: str = "telegram-1") -> dict:
    return {
        "id": task_id,
        "task_type": "telegram_reply",
        "status": status,
        "created_at": (NOW - timedelta(minutes=age_minutes)).isoformat(),
    }


def test_no_telegram_tasks_is_quiet(tmp_path: Path) -> None:
    """Steady state: no inbound messages must not manufacture noise."""
    _write_tasks(tmp_path, [])

    state = _parse_telegram_reply_backlog_state(str(tmp_path), NOW)

    assert state["breached"] is False
    assert state["level"] == "info"
    assert state["details"]["stuck_count"] == 0


def test_recent_pending_reply_no_breach(tmp_path: Path) -> None:
    """A reply in flight below the warn threshold is normal, not a failure."""
    _write_tasks(tmp_path, [_task(age_minutes=TELEGRAM_REPLY_BACKLOG_WARN_MINUTES - 10)])

    state = _parse_telegram_reply_backlog_state(str(tmp_path), NOW)

    assert state["breached"] is False
    assert state["level"] == "info"


def test_pending_beyond_warn_breaches_warn(tmp_path: Path) -> None:
    _write_tasks(tmp_path, [_task(age_minutes=TELEGRAM_REPLY_BACKLOG_WARN_MINUTES + 5)])

    state = _parse_telegram_reply_backlog_state(str(tmp_path), NOW)

    assert state["breached"] is True
    assert state["level"] == "warn"
    assert state["details"]["stuck_count"] == 1


def test_pending_beyond_critical_breaches_critical(tmp_path: Path) -> None:
    """The 2026-07-16 shape: responder FATAL, message rotting past the fallback."""
    _write_tasks(tmp_path, [_task(age_minutes=TELEGRAM_REPLY_BACKLOG_CRITICAL_MINUTES + 60)])

    state = _parse_telegram_reply_backlog_state(str(tmp_path), NOW)

    assert state["breached"] is True
    assert state["level"] == "critical"


def test_claimed_but_never_completed_still_breaches(tmp_path: Path) -> None:
    """Claim is not delivery — a responder that dies mid-task must still alert."""
    _write_tasks(
        tmp_path,
        [_task(age_minutes=TELEGRAM_REPLY_BACKLOG_CRITICAL_MINUTES + 30, status="claimed")],
    )

    state = _parse_telegram_reply_backlog_state(str(tmp_path), NOW)

    assert state["breached"] is True
    assert state["level"] == "critical"


def test_answered_replies_are_ignored(tmp_path: Path) -> None:
    """Terminal rows must not keep alerting after the boss got his answer."""
    _write_tasks(
        tmp_path,
        [
            _task(age_minutes=600, status="succeeded", task_id="telegram-old-1"),
            _task(age_minutes=900, status="failed", task_id="telegram-old-2"),
        ],
    )

    state = _parse_telegram_reply_backlog_state(str(tmp_path), NOW)

    assert state["breached"] is False
    assert state["details"]["stuck_count"] == 0


def test_other_task_types_do_not_count(tmp_path: Path) -> None:
    """Only the Telegram lane; a stale daily_article is a different alert's job."""
    _write_tasks(
        tmp_path,
        [{
            "id": "article-1",
            "task_type": "daily_article",
            "status": "pending",
            "created_at": (NOW - timedelta(hours=12)).isoformat(),
        }],
    )

    state = _parse_telegram_reply_backlog_state(str(tmp_path), NOW)

    assert state["breached"] is False
    assert state["details"]["stuck_count"] == 0


def test_oldest_message_drives_severity(tmp_path: Path) -> None:
    """Report the worst-case wait, not the newest arrival."""
    _write_tasks(
        tmp_path,
        [
            _task(age_minutes=5, task_id="telegram-new"),
            _task(age_minutes=TELEGRAM_REPLY_BACKLOG_CRITICAL_MINUTES + 90, task_id="telegram-old"),
        ],
    )

    state = _parse_telegram_reply_backlog_state(str(tmp_path), NOW)

    assert state["level"] == "critical"
    assert state["details"]["stuck_count"] == 2
    assert state["details"]["stuck"][0]["id"] == "telegram-old"


def test_missing_next_tasks_is_quiet_not_crash(tmp_path: Path) -> None:
    """Alert parsers must stay non-fatal; a missing queue is not a reply backlog."""
    state = _parse_telegram_reply_backlog_state(str(tmp_path), NOW)

    assert state["breached"] is False
    assert state["details"]["read_error"] == "missing_next_tasks"


def test_codex_fallback_is_bounded_and_uses_isolated_scratch() -> None:
    source = RESPONDER.read_text(encoding="utf-8")

    assert 'CODEX_BOUNDED="${CODEX_BOUNDED:-$REPO_ROOT/scripts/codex_exec_bounded.sh}"' in source
    assert 'bash "$CODEX_BOUNDED" --timeout "$CAP_SEC"' in source
    assert '-C "$RESPONDER_WORKDIR" --add-dir "$REPO_ROOT"' in source
    assert 'codex exec ' not in source


def test_codex_only_runs_after_primary_failure_with_pending_work() -> None:
    source = RESPONDER.read_text(encoding="utf-8")
    guard = (
        'if [ "$LEFT" != "0" ] && [ "$RC" -ne 0 ] '
        '&& [ "$CODEX_FAILOVER_ENABLED" = "1" ]; then'
    )

    assert guard in source
    assert source.index(guard) < source.index("run_codex_pass; RC=$?")
    assert 'CLAUDE_UNAVAILABLE=1' in source


def test_primary_and_fallback_share_a_unique_claim_owner() -> None:
    source = RESPONDER.read_text(encoding="utf-8")

    assert 'export VOLPRED_TASK_CLAIM_OWNER="telegram-responder-$$"' in source
    assert 'claim 必須帶 `--owner "$VOLPRED_TASK_CLAIM_OWNER"`' in source
