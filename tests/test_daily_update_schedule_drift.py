"""Regression tests for the 2026-06-28 daily_update schedule-source drift.

Root cause: scripts/cron_review.py hardcoded daily_update's cron as '0 6 * * *'
(daily 06:00) while canonical config is '3 8 * * 1-6' (Mon-Sat 08:03), and
src/volpred/ops/health.py hardcoded the same Mon-Sat 08:03 as module constants.
Both monitors therefore drifted from the single canonical schedule and the
cron_review monitor false-flagged every Sunday as a ~22h missed run.

Fix: both monitors now resolve the cron from canonical config via
volpred.ops.schedules.get_job_cron(). These tests pin that single source and
assert no Sunday false-alarm + genuine-miss detection still fires.
"""
from __future__ import annotations

import importlib.util
from datetime import datetime, timezone, timedelta
from pathlib import Path

from volpred.ops.schedules import get_job_cron, previous_scheduled_fire
from volpred.ops.health import _last_expected_metrics_refresh

REPO = Path(__file__).resolve().parents[1]
TPE = timezone(timedelta(hours=8))

# Load cron_review.py the same way its own test module does.
_SPEC = importlib.util.spec_from_file_location(
    "cron_review_module_drift", REPO / "scripts" / "cron_review.py"
)
assert _SPEC and _SPEC.loader
cron_review = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cron_review)


# --------------------------------------------------------------------------- #
# Single source of truth
# --------------------------------------------------------------------------- #
def test_canonical_daily_update_cron_is_mon_sat_0803():
    """The exact drift: anything other than '3 8 * * 1-6' means config changed
    or a duplicate source crept back in."""
    assert get_job_cron("daily_update") == "3 8 * * 1-6"


def test_cron_review_jobs_all_resolve_to_canonical_cron():
    """Every cron_review JOBS entry must point at a config job id that resolves
    to a real canonical cron — a None means the monitor would silently fall back
    to a wallclock max-gap and re-introduce weekend false-alarms."""
    for job, spec in cron_review.JOBS.items():
        config_job_id = spec[4]
        cron = get_job_cron(config_job_id)
        assert cron is not None, f"{job}: config_job_id={config_job_id!r} not in canonical schedule"


def test_cron_review_no_hardcoded_cron_expressions():
    """JOBS entries carry config ids, not raw 5-field cron expressions (which is
    what drifted). A space-separated 5-field token in the last column would be a
    hardcoded cron — the regression we are guarding against."""
    for job, spec in cron_review.JOBS.items():
        last = spec[4]
        assert last is None or len(str(last).split()) == 1, (
            f"{job}: last column looks like a hardcoded cron {last!r}; use a config job id"
        )


# --------------------------------------------------------------------------- #
# cron_review staleness — no Sunday false alarm, genuine miss still flagged
# --------------------------------------------------------------------------- #
def test_cron_review_daily_update_not_stale_on_sunday():
    """Sunday with Saturday's completed run must NOT false-flag (the exact bug:
    'predicted 2026-06-28 06:00 should fire, missed 21.9h')."""
    cron = get_job_cron("daily_update")
    now = datetime(2026, 6, 28, 20, 0, tzinfo=TPE)       # Sunday evening
    last_end = datetime(2026, 6, 27, 8, 6, tzinfo=TPE)   # Saturday run completed
    stale, flag = cron_review.is_stale(
        now=now, last_end=last_end, cron_expr=cron, fallback_max_gap_h=30
    )
    assert stale is False
    assert flag is None


def test_cron_review_daily_update_not_stale_after_monday_run():
    """Once the Monday 08:03 run has completed, Monday daytime is OK. (cron_review
    uses a 2h slack from the scheduled fire — by 09:00 the run should be done, so
    a Saturday-only last_end at Monday 09:00 is a genuine miss, not tested here.)"""
    cron = get_job_cron("daily_update")
    now = datetime(2026, 6, 29, 9, 0, tzinfo=TPE)
    last_end = datetime(2026, 6, 29, 8, 6, tzinfo=TPE)   # Monday run completed
    stale, _ = cron_review.is_stale(
        now=now, last_end=last_end, cron_expr=cron, fallback_max_gap_h=30
    )
    assert stale is False


def test_cron_review_daily_update_flags_genuine_weekday_miss():
    """A real miss must still fire: Tuesday afternoon, file still from Saturday."""
    cron = get_job_cron("daily_update")
    now = datetime(2026, 6, 30, 14, 0, tzinfo=TPE)        # Tuesday afternoon
    last_end = datetime(2026, 6, 27, 8, 6, tzinfo=TPE)    # still Saturday
    stale, flag = cron_review.is_stale(
        now=now, last_end=last_end, cron_expr=cron, fallback_max_gap_h=30
    )
    assert stale is True
    assert flag is not None


# --------------------------------------------------------------------------- #
# health.py schedule-aware freshness — derived from the same single source
# --------------------------------------------------------------------------- #
def test_previous_scheduled_fire_mon_sat_resolves_saturday_on_sunday():
    now = datetime(2026, 6, 28, 20, 0, tzinfo=TPE)  # Sunday
    prev = previous_scheduled_fire("3 8 * * 1-6", now=now, tz=TPE, grace_hours=3.0)
    assert prev == datetime(2026, 6, 27, 8, 3, tzinfo=TPE)  # Saturday 08:03


def test_health_last_expected_refresh_skips_sunday():
    now_utc = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)  # Sunday
    last = _last_expected_metrics_refresh(now_utc).astimezone(TPE)
    assert last == datetime(2026, 6, 27, 8, 3, tzinfo=TPE)  # Saturday, not Sunday


def test_health_last_expected_refresh_monday_after_grace():
    now_utc = datetime(2026, 6, 29, 4, 0, tzinfo=timezone.utc)  # Mon 12:00 TPE
    last = _last_expected_metrics_refresh(now_utc).astimezone(TPE)
    assert last == datetime(2026, 6, 29, 8, 3, tzinfo=TPE)  # Monday 08:03
