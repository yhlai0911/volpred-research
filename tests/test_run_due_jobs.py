"""Tests for scripts/run_due_jobs.py — universal piggy-back scheduler.

Covers 2026-04-20 root-cause fix for macOS cron daemon reliability:
check_alerts (`0 * * * *`) is the only reliable host-cron trigger, so
run_due_jobs dispatches all other due jobs from that single entry point.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

# Allow importing from scripts/ (sibling to tests/).
PROJECT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from run_due_jobs import _job_is_due, _parse_iso  # noqa: E402

TAIPEI = ZoneInfo("Asia/Taipei")


def test_job_is_due_fires_when_never_ran_and_scheduled_in_last_24h():
    # 08:00 Monday (DoW=1) local → match pattern `0 8 * * 1`
    now_local = datetime(2026, 4, 20, 8, 5, tzinfo=TAIPEI)  # Mon 08:05 CST
    assert _job_is_due("0 8 * * 1", last_run=None, now_local=now_local) is True


def test_job_is_due_skips_when_last_run_covers_latest_fire():
    now_local = datetime(2026, 4, 20, 8, 5, tzinfo=TAIPEI)
    # Job last ran 1 min after the 08:00 Mon fire → no missed fire
    last_run = datetime(2026, 4, 20, 8, 1, tzinfo=TAIPEI).astimezone(timezone.utc)
    assert _job_is_due("0 8 * * 1", last_run=last_run, now_local=now_local) is False


def test_job_is_due_fires_after_missed_scheduled_run():
    # 10:00 Monday local, job last ran Sunday 00:00 — should fire the 08:00 Mon
    now_local = datetime(2026, 4, 20, 10, 0, tzinfo=TAIPEI)
    last_run = datetime(2026, 4, 19, 0, 0, tzinfo=TAIPEI).astimezone(timezone.utc)
    assert _job_is_due("0 8 * * 1", last_run=last_run, now_local=now_local) is True


def test_job_is_due_respects_dow_filter():
    # Sunday = DoW 0, job runs only `2-6` (Tue-Sat)
    now_local = datetime(2026, 4, 19, 8, 5, tzinfo=TAIPEI)  # Sun 08:05
    # Last fire was Sat 08:03 = 2026-04-18 08:03 CST → UTC 2026-04-18 00:03
    last_run = datetime(2026, 4, 18, 8, 5, tzinfo=TAIPEI).astimezone(timezone.utc)
    # Sunday has no fire in crontab pattern; between Sat 08:03 (last fire, <=last_run)
    # and now (Sun 08:05), no new fire exists → not due.
    assert _job_is_due("3 8 * * 2-6", last_run=last_run, now_local=now_local) is False


def test_job_is_due_every_2h_fires_multiple_times_post_stale():
    # Job `3 */2 * * *` fires every 2 hours. last_run 26 hours ago but anchor
    # is 24h → only fires where prev_fire within last 24h from now.
    now_local = datetime(2026, 4, 20, 8, 5, tzinfo=TAIPEI)
    last_run_old = datetime(2026, 4, 19, 6, 0, tzinfo=TAIPEI).astimezone(timezone.utc)  # 26h ago
    # Most recent prev fire is 08:03... wait 8:05 comes after 8:03 so prev=08:03 today
    assert _job_is_due("3 */2 * * *", last_run=last_run_old, now_local=now_local) is True


def test_job_is_due_skipped_when_anchor_exceeded():
    # last_run = None, crontab `0 8 * * 1` at Sun 10:00 local, no Monday
    # fire within 24h → skip (not due).
    now_local = datetime(2026, 4, 19, 10, 0, tzinfo=TAIPEI)  # Sunday
    # For a Mon-only cron, prev fire before Sun 10:00 is Mon Apr 13 08:00,
    # which is 6+ days ago (>24h anchor). Not due.
    assert _job_is_due("0 8 * * 1", last_run=None, now_local=now_local) is False


def test_parse_iso_handles_z_suffix_and_naive():
    assert _parse_iso("2026-04-20T00:00:00Z").tzinfo is not None
    assert _parse_iso("2026-04-20T00:00:00") is not None
    assert _parse_iso(None) is None
    assert _parse_iso("not-a-date") is None
