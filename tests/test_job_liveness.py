"""WS-D1 (refactor_plan_ops_master_2026_07): liveness has ONE definition.

`storage/ops/cron_last_run.json` only records exit-0 markers from piggyback fires
and cron_lib self-reporting wrappers. A launchd-direct job
(`host_crontab_managed: false`) whose wrapper does not self-report never
refreshes there — `daily_update` sat frozen at 2026-04-25 for ~3 months while
running healthy every morning, and every monitor that read the marker alone
misjudged a live job as dead. These tests pin the fix:

  1. managed=False + fresh execution-log banner → alive (the headline bug);
  2. piggyback jobs keep their marker-based verdicts unchanged;
  3. a job that fires but always FAILS still goes stale (success semantics);
  4. the marker file self-documents its scope (`_meta`), and readers skip it.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import check_alerts  # noqa: E402
from volpred.ops.schedules import (  # noqa: E402
    job_liveness,
    load_cron_marker_state,
    marker_eligible,
)

UTC = timezone.utc


def _write_banner_log(path: Path, ts_iso: str, *, exit_code: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"=== [job] start ===\n"
        f"some output\n"
        f"=== [job] exit {exit_code} at {ts_iso} (duration=306s) ===\n",
        encoding="utf-8",
    )


# ── 1. the headline regression: managed=False alive job is ALIVE ─────────────

def test_launchd_direct_job_with_frozen_marker_but_fresh_banner_is_alive(tmp_path) -> None:
    """daily_update scenario: marker frozen for months, log banner fresh."""
    fresh = datetime.now(UTC) - timedelta(minutes=30)
    log = tmp_path / "storage" / "logs" / "cron" / "daily_update.log"
    _write_banner_log(log, fresh.strftime("%Y-%m-%dT%H:%M:%S+0000"))
    item = {
        "id": "daily_update",
        "cron": "3 8 * * 1-6",
        "host_crontab_managed": False,
        "log_path": "storage/logs/cron/daily_update.log",
    }
    state = {"daily_update": "2026-04-25T01:05:47+00:00"}  # the real frozen value

    live = job_liveness(item, marker_state=state, repo_root=tmp_path)
    assert live.last_success is not None
    assert live.success_source == "log_banner", (
        "a frozen piggyback marker must never outrank fresh execution-log evidence"
    )
    assert abs((live.last_success - fresh).total_seconds()) < 120


def test_launchd_jobs_bind_liveness_to_wrapper_execution_logs() -> None:
    """The schedule must point at the log that contains the exit-0 receipt.

    The Gmail poller also writes a domain log under ``storage/``, but that file
    contains no wrapper exit banner.  Handoff regeneration has no such storage
    log at all.  Binding either job to those paths makes the public liveness
    observer report ``never_ran`` while both LaunchAgents are healthy.
    """
    config = json.loads(
        (ROOT / "config" / "runtime_schedules.json").read_text(encoding="utf-8")
    )
    items = {
        item["id"]: item
        for item in config["system_crontab"]["items"]
        if item.get("id") in {"gmail_poll", "handoff_regen"}
    }

    assert items["gmail_poll"]["log_path"] == "~/.volpred/logs/gmail_poll.log"
    assert items["handoff_regen"]["log_path"] == "~/.volpred/logs/handoff_regen.log"


def test_bespoke_wrapper_local_timestamp_is_success_evidence(tmp_path) -> None:
    """Existing LaunchAgent receipts use a space-separated Taipei timestamp."""
    log = tmp_path / "handoff_regen.log"
    log.write_text(
        "=== [handoff_regen] exit 0 at 2026-07-23 23:50:02 CST ===\n",
        encoding="utf-8",
    )

    live = job_liveness(
        {
            "id": "handoff_regen",
            "host_crontab_managed": False,
            "log_path": str(log),
        },
        marker_state={},
        repo_root=tmp_path,
    )

    assert live.last_success == datetime(2026, 7, 23, 15, 50, 2, tzinfo=UTC)
    assert live.success_source == "log_banner"


def test_check_alerts_no_longer_blanket_skips_managed_false_jobs(tmp_path) -> None:
    """The old `unmanaged` verdict hid dead-or-alive launchd jobs entirely."""
    now = datetime.now(UTC)
    fresh = now - timedelta(minutes=30)
    log = tmp_path / "storage" / "logs" / "cron" / "daily_update.log"
    _write_banner_log(log, fresh.strftime("%Y-%m-%dT%H:%M:%S+0000"))
    items = [{
        "id": "daily_update",
        "cron": "3 8 * * 1-6",
        "host_crontab_managed": False,
        "log_path": "storage/logs/cron/daily_update.log",
    }]
    state = {"daily_update": "2026-04-25T01:05:47+00:00"}

    # repo_root is plumbed evaluate → job_liveness via check_alerts.PROJECT_ROOT
    old_project_root = check_alerts.PROJECT_ROOT
    check_alerts.PROJECT_ROOT = tmp_path
    try:
        rec = check_alerts.evaluate_cron_staleness(items, state, now)[0]
    finally:
        check_alerts.PROJECT_ROOT = old_project_root

    assert rec["status"] == "ok", rec
    assert rec["evidence"] == "log_banner"


def test_dead_launchd_job_now_goes_stale_instead_of_invisible(tmp_path) -> None:
    now = datetime.now(UTC)
    old = now - timedelta(days=90)
    log = tmp_path / "storage" / "logs" / "cron" / "daily_update.log"
    _write_banner_log(log, old.strftime("%Y-%m-%dT%H:%M:%S+0000"))
    items = [{
        "id": "daily_update",
        "cron": "3 8 * * 1-6",
        "host_crontab_managed": False,
        "log_path": "storage/logs/cron/daily_update.log",
    }]
    old_project_root = check_alerts.PROJECT_ROOT
    check_alerts.PROJECT_ROOT = tmp_path
    try:
        rec = check_alerts.evaluate_cron_staleness(items, {}, now)[0]
    finally:
        check_alerts.PROJECT_ROOT = old_project_root
    assert rec["status"] == "stale", "a genuinely dead launchd job must surface, not hide"


# ── 2. piggyback jobs: verdicts unchanged ────────────────────────────────────

def test_piggyback_job_marker_only_verdict_unchanged() -> None:
    now = datetime.now(UTC)
    items = [{"id": "feed_sync", "cron": "5 * * * *"}]  # managed (default) piggyback job
    ok_state = {"feed_sync": (now - timedelta(minutes=20)).isoformat()}
    stale_state = {"feed_sync": (now - timedelta(hours=5)).isoformat()}

    ok_rec = check_alerts.evaluate_cron_staleness(items, ok_state, now)[0]
    stale_rec = check_alerts.evaluate_cron_staleness(items, stale_state, now)[0]
    assert ok_rec["status"] == "ok" and ok_rec["evidence"] == "piggyback_marker"
    assert stale_rec["status"] == "stale"


def test_piggyback_job_helper_returns_marker_as_source() -> None:
    ts = datetime(2026, 7, 20, 8, 0, tzinfo=UTC)
    item = {"id": "feed_sync", "cron": "5 * * * *"}  # no log_path → marker only
    live = job_liveness(item, marker_state={"feed_sync": ts.isoformat()}, repo_root=Path("/nonexistent"))
    assert live.last_success == ts
    assert live.success_source == "piggyback_marker"
    assert live.marker_eligible is True


def test_managed_false_with_piggy_back_enabled_is_marker_eligible() -> None:
    # git_push_backup / liveness_reconcile pattern: launchd-independent but
    # piggyback-dispatched — their markers ARE live.
    assert marker_eligible({"id": "git_push_backup",
                            "host_crontab_managed": False,
                            "piggy_back_enabled": True}) is True
    assert marker_eligible({"id": "daily_update", "host_crontab_managed": False}) is False
    assert marker_eligible({"id": "feed_sync"}) is True


# ── 3. success semantics: firing-but-failing still goes stale ────────────────

def test_failing_job_banner_is_activity_but_not_success(tmp_path) -> None:
    now = datetime.now(UTC)
    fresh = now - timedelta(minutes=10)
    log = tmp_path / "storage" / "logs" / "cron" / "daily_update.log"
    _write_banner_log(log, fresh.strftime("%Y-%m-%dT%H:%M:%S+0000"), exit_code=1)
    item = {
        "id": "daily_update",
        "cron": "3 8 * * 1-6",
        "host_crontab_managed": False,
        "log_path": "storage/logs/cron/daily_update.log",
    }
    live = job_liveness(item, marker_state={}, repo_root=tmp_path)
    assert live.last_success is None, "exit!=0 banners must not count as success"
    assert live.last_activity is not None, "the fire itself is still activity (mtime)"


# ── 4. marker-file scope stamp and reader hygiene ────────────────────────────

def test_load_cron_marker_state_skips_meta_keys(tmp_path) -> None:
    path = tmp_path / "cron_last_run.json"
    path.write_text(json.dumps({
        "_meta": {"scope": "piggyback-and-cron_lib-self-report-only"},
        "feed_sync": "2026-07-20T08:00:00+00:00",
    }), encoding="utf-8")
    state = load_cron_marker_state(path)
    assert state == {"feed_sync": "2026-07-20T08:00:00+00:00"}


def test_unparsable_marker_survives_into_helper_and_evaluator() -> None:
    now = datetime.now(UTC)
    live = job_liveness({"id": "j", "cron": "0 * * * *"},
                        marker_state={"j": "garbage"}, repo_root=Path("/nonexistent"))
    assert live.marker_raw == "garbage" and live.marker_at is None

    rec = check_alerts.evaluate_cron_staleness(
        [{"id": "j", "cron": "0 * * * *"}], {"j": "garbage"}, now)[0]
    assert rec["status"] == "unparsable_marker"


def test_unscheduled_daemon_job_gets_explicit_verdict() -> None:
    # telegram_poll pattern: KeepAlive daemon, cron=null — cron staleness has no
    # meaning; it must be labelled, not silently dropped or "unmanaged".
    rec = check_alerts.evaluate_cron_staleness(
        [{"id": "telegram_poll", "cron": None, "host_crontab_managed": False}],
        {}, datetime.now(UTC))[0]
    assert rec["status"] == "unscheduled"


def test_log_path_that_is_a_directory_yields_no_evidence(tmp_path) -> None:
    (tmp_path / "storage" / "logs" / "cron" / "x.log").mkdir(parents=True)
    live = job_liveness(
        {"id": "x", "host_crontab_managed": False, "log_path": "storage/logs/cron/x.log"},
        marker_state={}, repo_root=tmp_path)
    assert live.last_success is None
    assert live.last_activity is None, "a directory mtime must never count as a job run"


def test_banner_local_offset_format_parses() -> None:
    # daily_update's real banner: `exit 0 at 2026-07-20T08:08:09+0800`
    from volpred.ops.schedules import _parse_banner_ts

    ts = _parse_banner_ts("2026-07-20T08:08:09+0800")
    assert ts == datetime(2026, 7, 20, 0, 8, 9, tzinfo=UTC)
