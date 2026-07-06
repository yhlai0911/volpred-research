"""Regression gate for Telegram poller heartbeat freshness.

Telegram long-polling is the boss-facing instant message ingress. The daemon
now writes storage/ops/telegram_state.json:last_success_at after every
successful getUpdates call, including empty polls; check_alerts owns the
dead-man switch.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from volpred.ops.alerts import (
    TELEGRAM_POLL_STALE_CRITICAL_HOURS,
    TELEGRAM_POLL_STALE_WARN_HOURS,
    _parse_telegram_poll_freshness_state,
)


def _write_state(storage_dir: Path, now: datetime, age_hours: float) -> None:
    ops = storage_dir / "ops"
    ops.mkdir(parents=True, exist_ok=True)
    state = {
        "chat_id": 12345,
        "update_offset": 987,
        "handshake_at": (now - timedelta(days=1)).isoformat(),
        "last_success_at": (now - timedelta(hours=age_hours)).isoformat(),
    }
    (ops / "telegram_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_fresh_telegram_poll_no_breach(tmp_path: Path) -> None:
    now = datetime(2026, 7, 6, 6, 0, tzinfo=timezone.utc)
    _write_state(tmp_path, now, age_hours=0.2)

    state = _parse_telegram_poll_freshness_state(str(tmp_path), now)

    assert state["breached"] is False
    assert state["level"] == "info"


def test_stale_telegram_poll_beyond_warn_breaches_warn(tmp_path: Path) -> None:
    now = datetime(2026, 7, 6, 6, 0, tzinfo=timezone.utc)
    _write_state(tmp_path, now, age_hours=TELEGRAM_POLL_STALE_WARN_HOURS + 0.5)

    state = _parse_telegram_poll_freshness_state(str(tmp_path), now)

    assert state["breached"] is True
    assert state["level"] == "warn"


def test_stale_telegram_poll_beyond_critical_breaches_critical(tmp_path: Path) -> None:
    now = datetime(2026, 7, 6, 6, 0, tzinfo=timezone.utc)
    _write_state(tmp_path, now, age_hours=TELEGRAM_POLL_STALE_CRITICAL_HOURS + 1.0)

    state = _parse_telegram_poll_freshness_state(str(tmp_path), now)

    assert state["breached"] is True
    assert state["level"] == "critical"


def test_missing_last_success_at_is_not_yet_observed_info(tmp_path: Path) -> None:
    now = datetime(2026, 7, 6, 6, 0, tzinfo=timezone.utc)
    ops = tmp_path / "ops"
    ops.mkdir(parents=True, exist_ok=True)
    (ops / "telegram_state.json").write_text(
        json.dumps(
            {
                "chat_id": 12345,
                "update_offset": 987,
                "handshake_at": (now - timedelta(days=1)).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    state = _parse_telegram_poll_freshness_state(str(tmp_path), now)

    assert state["breached"] is False
    assert state["level"] == "info"
    assert state["details"]["age_hours"] is None
