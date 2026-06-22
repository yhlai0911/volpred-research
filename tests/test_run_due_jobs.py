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

from run_due_jobs import _job_is_due, _parse_iso, _write_pending_sessions  # noqa: E402

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


def test_write_pending_sessions_records_due_and_dedupes(tmp_path, monkeypatch):
    """Session cron piggy-back writer: records due items, skips on re-scan
    within same fire window. Replays on next fire after last_ref moves."""
    import run_due_jobs as rdj

    pending_path = tmp_path / "pending_sessions.json"
    monkeypatch.setattr(rdj, "PENDING_SESSIONS_PATH", pending_path)

    items = [
        {"id": "daily_planning", "cron": "3 9 * * *", "prompt": "p1", "recurring": True, "description": "d1"},
        {"id": "hourly_fake", "cron": "0 * * * *", "prompt": "p2", "recurring": True},
        {"id": "oneshot_foo", "cron": "0 0 1 1 *", "prompt": "p3", "recurring": False},
    ]

    # 10:00 Mon CST — daily_planning fired at 09:03 today (in last 24h, due).
    now_local = datetime(2026, 4, 20, 10, 0, tzinfo=TAIPEI)
    now_utc = now_local.astimezone(timezone.utc)

    r1 = _write_pending_sessions(items, last_run_state={}, now_local=now_local, now_utc=now_utc)
    assert "daily_planning" in r1["recorded"]
    assert "hourly_fake" in r1["recorded"]
    assert "oneshot_foo" not in r1["recorded"]  # recurring=False → skipped
    assert "oneshot_foo" not in r1["skipped"]

    # Re-scan 5 min later (same fire window for daily_planning 9:03 and hourly_fake 10:00):
    # daily_planning: prev_fire_today 09:03 < recorded_at 10:00 → not due → skip
    # hourly_fake: prev_fire 10:00 < recorded_at 10:00? need newer now for re-fire
    now2_local = datetime(2026, 4, 20, 10, 5, tzinfo=TAIPEI)
    now2_utc = now2_local.astimezone(timezone.utc)
    r2 = _write_pending_sessions(items, last_run_state={}, now_local=now2_local, now_utc=now2_utc)
    assert "daily_planning" in r2["skipped"]  # already recorded this window
    assert "daily_planning" not in r2["recorded"]

    # Next day 10:00 — new daily_planning 09:03 fire happened, should re-record.
    now3_local = datetime(2026, 4, 21, 10, 0, tzinfo=TAIPEI)
    now3_utc = now3_local.astimezone(timezone.utc)
    r3 = _write_pending_sessions(items, last_run_state={}, now_local=now3_local, now_utc=now3_utc)
    assert "daily_planning" in r3["recorded"]

    # Verify persisted schema
    import json
    data = json.loads(pending_path.read_text())
    assert data["schema_version"] == 1
    assert "description" in data
    assert "daily_planning" in data["jobs"]
    assert data["jobs"]["daily_planning"]["recorded_count"] >= 2
    assert data["jobs"]["daily_planning"]["replayed_at"] is None


def test_load_pending_sessions_normalizes_legacy_schema(tmp_path, monkeypatch):
    import json
    import run_due_jobs as rdj

    pending_path = tmp_path / "pending_sessions.json"
    monkeypatch.setattr(rdj, "PENDING_SESSIONS_PATH", pending_path)
    pending_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pending": {"legacy_a": {"recorded_count": 2}},
                "session_crons": {"legacy_b": {"recorded_count": 1}},
            }
        ),
        encoding="utf-8",
    )

    state = rdj._load_pending_sessions()

    assert state["schema_version"] == 1
    assert "description" in state
    assert state["jobs"]["legacy_a"]["recorded_count"] == 2
    assert state["jobs"]["legacy_b"]["recorded_count"] == 1


def test_load_last_run_warns_on_corrupt_json(tmp_path, monkeypatch, capsys):
    import run_due_jobs as rdj

    last_run_path = tmp_path / "cron_last_run.json"
    monkeypatch.setattr(rdj, "LAST_RUN_PATH", last_run_path)
    last_run_path.write_text("{bad json", encoding="utf-8")

    assert rdj._load_last_run() == {}

    captured = capsys.readouterr()
    assert "[run_due_jobs] WARN cron_last_run JSON read failed; using empty state" in captured.err
    assert "cron_last_run.json" in captured.err


def test_load_pending_sessions_warns_on_corrupt_json(tmp_path, monkeypatch, capsys):
    import run_due_jobs as rdj

    pending_path = tmp_path / "pending_sessions.json"
    monkeypatch.setattr(rdj, "PENDING_SESSIONS_PATH", pending_path)
    pending_path.write_text("{bad json", encoding="utf-8")

    state = rdj._load_pending_sessions()

    captured = capsys.readouterr()
    assert state["jobs"] == {}
    assert "[run_due_jobs] WARN pending_sessions JSON read failed; using default state" in captured.err
    assert "pending_sessions.json" in captured.err


def test_run_due_jobs_skips_piggy_back_skip_items(tmp_path, monkeypatch):
    """piggy_back_skip=true items should be skipped by run_due_jobs even if due.

    Distinct from host_crontab_managed=false (which removes from host crontab).
    Used for items whose host-cron pattern fires reliably and would double-fire
    if piggy-back also dispatched them. Verified 2026-05-29 collect_us_data
    incident (host cron 07:03 + piggy-back 00:00 UTC = 2 yfinance fetches/day).
    """
    import json
    import run_due_jobs as rdj

    config_path = tmp_path / "schedules.json"
    last_run_path = tmp_path / "cron_last_run.json"
    state = {}
    last_run_path.write_text(json.dumps(state))

    config_path.write_text(json.dumps({
        "system_crontab": {
            "items": [
                {
                    "id": "collect_us_test",
                    "cron": "3 7 * * 2-6",
                    "wrapper_script": "/nonexistent/wrapper.sh",
                    "log_path": "storage/logs/cron/test.log",
                    "piggy_back_skip": True,
                },
                {
                    "id": "regular_test",
                    "cron": "0 8 * * 1",
                    "wrapper_script": "/nonexistent/wrapper.sh",
                    "log_path": "storage/logs/cron/test2.log",
                },
            ]
        }
    }))
    monkeypatch.setattr(rdj, "CONFIG_PATH", config_path)
    monkeypatch.setattr(rdj, "LAST_RUN_PATH", last_run_path)

    result = rdj.run_due_jobs()

    jobs = {r["job_id"]: r for r in result["jobs"]}
    assert jobs["collect_us_test"]["action"] == "skip"
    assert jobs["collect_us_test"]["reason"] == "piggy_back_skip_host_managed"
    # regular_test fails wrapper_missing (not piggy_back_skip) — confirms flag isolation
    assert jobs["regular_test"]["reason"] != "piggy_back_skip_host_managed"
