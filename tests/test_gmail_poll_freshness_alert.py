"""Regression gate for the 2026-06-22 gmail-poll silent-stall dead-man switch.

Incident: the gmail-poll LaunchAgent fired every 15min but each run hit the
wrapper's 60s perl-alarm and was SIGALRM-killed (exit=142) before completing the
~20 sequential IMAP fetches → storage/ops/gmail_inbox_state.json froze for 2.5h
→ boss-email replies were not auto-queued, yet zero alerts fired (no outcome was
watched). These tests assert the gmail_poll_freshness check fires on a stale /
missing state file and stays quiet when fresh.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from volpred.ops.alerts import (
    GMAIL_POLL_STALE_CRITICAL_HOURS,
    GMAIL_POLL_STALE_WARN_HOURS,
    _parse_gmail_poll_freshness_state,
)
from datetime import datetime, timezone


def _write_state(storage_dir: Path, age_hours: float) -> None:
    ops = storage_dir / "ops"
    ops.mkdir(parents=True, exist_ok=True)
    state = ops / "gmail_inbox_state.json"
    state.write_text(json.dumps({"last_seen_uid": 1}))
    # backdate mtime by age_hours
    target = time.time() - age_hours * 3600.0
    os.utime(state, (target, target))


def test_fresh_poll_no_breach(tmp_path: Path) -> None:
    _write_state(tmp_path, age_hours=0.2)  # 12 min ago
    state = _parse_gmail_poll_freshness_state(str(tmp_path), datetime.now(timezone.utc))
    assert state["breached"] is False
    assert state["level"] == "info"


def test_stale_beyond_warn_breaches_warn(tmp_path: Path) -> None:
    _write_state(tmp_path, age_hours=GMAIL_POLL_STALE_WARN_HOURS + 0.5)  # ~2.5h
    state = _parse_gmail_poll_freshness_state(str(tmp_path), datetime.now(timezone.utc))
    assert state["breached"] is True
    assert state["level"] == "warn"


def test_stale_beyond_critical_breaches_critical(tmp_path: Path) -> None:
    _write_state(tmp_path, age_hours=GMAIL_POLL_STALE_CRITICAL_HOURS + 1.0)  # ~7h
    state = _parse_gmail_poll_freshness_state(str(tmp_path), datetime.now(timezone.utc))
    assert state["breached"] is True
    assert state["level"] == "critical"


def test_missing_state_file_breaches_critical(tmp_path: Path) -> None:
    # no ops/gmail_inbox_state.json at all
    state = _parse_gmail_poll_freshness_state(str(tmp_path), datetime.now(timezone.utc))
    assert state["breached"] is True
    assert state["level"] == "critical"
    assert state["details"]["age_hours"] is None
