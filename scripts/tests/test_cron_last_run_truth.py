"""The cron freshness marker must tell the truth, and the monitor must read all of it.

2026-07-10. Two independent defects made `storage/ops/cron_last_run.json` and its
freshness monitor jointly useless:

  A. `piggy_back_skip: true` jobs are never fired by run_due_jobs (their LaunchAgent
     owns them), and run_due_jobs was the marker's only writer. All five such jobs
     ran on schedule while their marker sat frozen for 6 weeks — `memory_health_daily`
     ran at 05:30 every morning behind a 42-day-old timestamp.

  B. The staleness check keyed tolerance off a hardcoded 7-entry `period_map`.
     Jobs whose cron string was absent hit `period_min is None; continue` — silently.
     Coverage was 7 of 32 jobs (22%). Jobs that had never recorded a run at all hit
     `if not last_iso: continue` and vanished entirely (`indicator_arena_daily`).

Net effect: the monitor could not see a real outage of 25 jobs, and the single
signal it did emit was a false alarm about a healthy one.

These tests pin both fixes, and the last two are the mechanical gate: they read the
REAL config, so a future job added without self-reporting fails CI rather than
silently going unmonitored.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import check_alerts  # noqa: E402
from cron_mark_last_run import (  # noqa: E402
    job_id_for_wrapper,
    mark_last_run,
    merge_last_run,
)

SCHEDULES = ROOT / "config" / "runtime_schedules.json"


def _items() -> list[dict]:
    data = json.loads(SCHEDULES.read_text(encoding="utf-8"))
    return (data.get("system_crontab") or {}).get("items") or []


# ── cron period derivation ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    "cron_expr, expected_min, why",
    [
        ("0 * * * *", 60, "hourly"),
        ("30 5 * * *", 1440, "daily"),
        ("0 6,12,18 * * *", 720, "3×/day — longest gap is 18:00→06:00, not 6h"),
        ("0 15 * * 1-5", 4320, "weekdays — longest honest gap is Fri→Mon (3 days)"),
        ("0 6 * * 1", 10080, "weekly"),
        ("*/30 * * * *", 30, "half-hourly"),
    ],
)
def test_cron_max_gap_uses_longest_legitimate_gap(cron_expr, expected_min, why) -> None:
    # base pinned so weekday/weekend sampling is deterministic (a Wednesday)
    base = datetime(2026, 7, 8, 0, 0, 0)
    assert check_alerts.cron_max_gap_min(cron_expr, base=base) == pytest.approx(expected_min), why


def test_weekday_cron_is_not_stale_over_a_weekend() -> None:
    # The old mean-based/1440 assumption would have alerted every Saturday.
    base = datetime(2026, 7, 8)
    gap = check_alerts.cron_max_gap_min("0 15 * * 1-5", base=base)
    now = datetime(2026, 7, 12, 15, 0, tzinfo=timezone.utc)      # Sunday
    last = datetime(2026, 7, 10, 15, 0, tzinfo=timezone.utc)     # Friday's run
    items = [{"id": "collect_tw_data", "cron": "0 15 * * 1-5"}]
    state = {"collect_tw_data": last.isoformat()}
    rec = check_alerts.evaluate_cron_staleness(items, state, now, base=base)[0]
    assert rec["status"] == "ok", f"weekend gap {rec['age_min']:.0f}min vs period {gap:.0f}min"


# ── the evaluator refuses to skip silently ───────────────────────────────────

def test_never_ran_job_is_reported_not_skipped() -> None:
    # Old code: `if not last_iso: continue` → indicator_arena_daily was invisible.
    items = [{"id": "indicator_arena_daily", "cron": "0 8 * * *"}]
    rec = check_alerts.evaluate_cron_staleness(items, {}, datetime.now(timezone.utc))[0]
    assert rec["status"] == "never_ran"
    assert "no cron_last_run entry" in rec["detail"]


def test_unknown_cron_expression_is_reported_not_skipped() -> None:
    # Old code: `period_min = period_map.get(cron); if None: continue` → 24 jobs skipped.
    items = [{"id": "bogus", "cron": "not a cron"}]
    rec = check_alerts.evaluate_cron_staleness(items, {"bogus": "2026-01-01T00:00:00+00:00"},
                                               datetime.now(timezone.utc))[0]
    assert rec["status"] == "bad_cron"


def test_unparsable_marker_is_reported_not_skipped() -> None:
    items = [{"id": "j", "cron": "0 * * * *"}]
    rec = check_alerts.evaluate_cron_staleness(items, {"j": "garbage"},
                                               datetime.now(timezone.utc))[0]
    assert rec["status"] == "unparsable_marker"


def test_genuinely_stale_job_is_flagged() -> None:
    now = datetime.now(timezone.utc)
    items = [{"id": "j", "cron": "0 * * * *"}]  # hourly → tolerance 2h
    state = {"j": (now - timedelta(hours=5)).isoformat()}
    rec = check_alerts.evaluate_cron_staleness(items, state, now)[0]
    assert rec["status"] == "stale"


# ── marker writer: locking, atomicity, key isolation ─────────────────────────

def test_merge_last_run_preserves_keys_written_by_another_process(tmp_path: Path) -> None:
    # The bug run_due_jobs had: it loaded the whole dict, then blind-wrote it back,
    # reverting any marker a wrapper stamped during the (multi-minute) firing loop.
    path = tmp_path / "cron_last_run.json"
    path.write_text(json.dumps({"a": "2026-01-01T00:00:00+00:00"}), encoding="utf-8")
    merge_last_run({"b": "2026-02-02T00:00:00+00:00"}, path=path)
    merge_last_run({"c": "2026-03-03T00:00:00+00:00"}, path=path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {"a", "b", "c"}, "a merge dropped another writer's key"
    assert data["a"] == "2026-01-01T00:00:00+00:00"


def test_merge_last_run_refuses_to_flatten_a_corrupt_file(tmp_path: Path) -> None:
    # Silently treating corruption as {} would erase every job's marker on next write.
    path = tmp_path / "cron_last_run.json"
    path.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(ValueError):
        merge_last_run({"a": "2026-01-01T00:00:00+00:00"}, path=path)


def test_mark_last_run_is_atomic_leaving_no_partial_file(tmp_path: Path) -> None:
    path = tmp_path / "cron_last_run.json"
    mark_last_run("j", iso="2026-07-10T00:00:00+00:00", path=path)
    assert json.loads(path.read_text(encoding="utf-8")) == {"j": "2026-07-10T00:00:00+00:00"}
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".cron_last_run")]
    assert not [n for n in leftovers if "tmp" in n], f"temp file left behind: {leftovers}"


# ── job id comes from the wrapper PATH, never the log label ──────────────────

def test_job_id_resolves_from_wrapper_path_not_the_drifting_log_label() -> None:
    # cron_market_cal.sh logs itself as "market_cal"; its config id is
    # "market_calendar_sync". Keying on the label writes to a key nobody reads.
    assert job_id_for_wrapper("/Users/x/.volpred/bin/cron_market_cal.sh") == "market_calendar_sync"
    assert job_id_for_wrapper("cron_memory_health.sh") == "memory_health_daily"


def test_unknown_wrapper_raises_rather_than_guessing() -> None:
    with pytest.raises(LookupError):
        job_id_for_wrapper("/nowhere/cron_not_a_real_job.sh")


# ── mechanical gates against the REAL config ─────────────────────────────────

def test_every_configured_job_gets_a_verdict() -> None:
    """No job may fall through the staleness evaluator without a recorded verdict.

    This is the gate. Coverage was 22% precisely because two `continue` statements
    dropped jobs on the floor with no trace.
    """
    items = _items()
    records = check_alerts.evaluate_cron_staleness(items, {}, datetime.now(timezone.utc))
    verdicted = {r["job_id"] for r in records}
    configured = {i["id"] for i in items if i.get("id")}
    assert verdicted == configured, f"no verdict for: {sorted(configured - verdicted)}"


def test_no_configured_cron_expression_is_unparsable() -> None:
    items = _items()
    records = check_alerts.evaluate_cron_staleness(items, {}, datetime.now(timezone.utc))
    bad = [r for r in records if r["status"] == "bad_cron"]
    assert not bad, f"unparsable cron(s): {[(r['job_id'], r['detail']) for r in bad]}"


def test_wrapper_basenames_are_unique_so_reverse_lookup_is_unambiguous() -> None:
    names = [Path(i["wrapper_script"]).name for i in _items() if i.get("wrapper_script")]
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"duplicate wrapper basenames break job_id_for_wrapper: {dupes}"


def test_piggy_back_skip_jobs_self_report_via_cron_lib() -> None:
    """A job run_due_jobs never fires MUST stamp its own marker, or it is unmonitorable.

    This is the invariant whose absence froze five markers for six weeks. Checked
    against the repo's canonical wrapper (the ~/.volpred/bin exec target is
    machine-local and absent in CI).
    """
    offenders = []
    for item in _items():
        if item.get("piggy_back_skip") is not True:
            continue
        canonical = ROOT / "scripts" / Path(item["wrapper_script"]).name
        if not canonical.exists():
            offenders.append(f"{item['id']}: no canonical scripts/{canonical.name}")
            continue
        body = canonical.read_text(encoding="utf-8")
        if "cron_lib.sh" not in body or "cron_emit_exit" not in body:
            offenders.append(f"{item['id']}: {canonical.name} does not source cron_lib / call cron_emit_exit")
    assert not offenders, (
        "piggy_back_skip job(s) cannot record their own run — run_due_jobs will "
        "never fire them, so their cron_last_run marker will freeze:\n  "
        + "\n  ".join(offenders)
    )


# ── end-to-end through the real shell helper ─────────────────────────────────

def _run_wrapper(tmp_path: Path, exit_code: int) -> dict:
    """Drive scripts/cron_lib.sh exactly as a real wrapper does."""
    marker = tmp_path / "cron_last_run.json"
    wrapper = tmp_path / "cron_memory_health.sh"   # a real, configured basename
    wrapper.write_text(
        f'#!/bin/bash\n'
        f'source "{ROOT}/scripts/cron_lib.sh"\n'
        f'cron_emit_exit "some_drifting_label" "{exit_code}" "$SECONDS"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    env = {**os.environ, "VOLPRED_REPO_ROOT": str(ROOT), "VOLPRED_CRON_MARKER_PATH": str(marker)}
    subprocess.run(["/bin/bash", str(wrapper)], check=True, capture_output=True, text=True, env=env)
    return json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else {}


def test_cron_emit_exit_records_marker_on_success_under_the_config_id(tmp_path: Path) -> None:
    data = _run_wrapper(tmp_path, exit_code=0)
    # keyed by CONFIG ID, not by the "some_drifting_label" the wrapper passed
    assert "memory_health_daily" in data, data
    assert "some_drifting_label" not in data


def test_cron_emit_exit_leaves_marker_untouched_on_failure(tmp_path: Path) -> None:
    # A job that runs but always fails MUST go stale — that outage is the signal.
    assert _run_wrapper(tmp_path, exit_code=1) == {}
