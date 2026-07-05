"""Tests for `volpred.ops.loop_health` — the loop-engineering fast loop.

Covers the four derived metrics + fail-open + aggregate. All scenarios use
crafted tmp storage so the metrics are deterministic and offline.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from volpred.ops import loop_health as lh

NOW = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)


def _storage(tmp_path: Path) -> Path:
    s = tmp_path / "storage"
    (s / "logs" / "cron").mkdir(parents=True)
    return s


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


# ---------------------------------------------------------------------------
# first_pass_success
# ---------------------------------------------------------------------------
def test_first_pass_derives_rate_from_worklog_failure_traces(tmp_path):
    storage = _storage(tmp_path)
    _write(
        storage / "next_tasks.json",
        [
            {"id": "A", "k_id": "K1", "status": "succeeded", "completed_at": _iso(1)},
            {"id": "B", "k_id": "K2", "status": "succeeded", "completed_at": _iso(2)},
        ],
    )
    # A traceable + clean → first-pass; B traceable + prior failure → retried.
    _write(
        storage / "work_log.json",
        [
            {"task_id": "A", "outcome": "done", "timestamp": _iso(1)},
            {"task_id": "B", "outcome": "FAIL - requires_revision", "timestamp": _iso(3)},
            {"task_id": "B", "outcome": "succeeded", "timestamp": _iso(2)},
        ],
    )
    r = lh.compute_first_pass_success(str(storage), now=NOW)
    assert r["signal"] == "derived"
    assert r["traced"] == 2
    assert r["first_pass"] == 1
    assert r["retried"] == 1
    assert r["first_pass_rate"] == 0.5
    assert r["status"] == "degrading"  # 0.5 < FIRST_PASS_WARN


def test_first_pass_low_coverage_when_untraceable(tmp_path):
    storage = _storage(tmp_path)
    _write(
        storage / "next_tasks.json",
        [{"id": f"T{i}", "status": "succeeded", "completed_at": _iso(1)} for i in range(5)],
    )
    _write(storage / "work_log.json", [])  # nothing traceable
    r = lh.compute_first_pass_success(str(storage), now=NOW)
    assert r["status"] == "low_coverage"
    assert r["signal"] == "derived_low_coverage"
    assert r["traced"] == 0


def test_first_pass_null_verdict_is_not_a_failure(tmp_path):
    storage = _storage(tmp_path)
    _write(
        storage / "next_tasks.json",
        [{"id": "A", "k_id": "K1", "status": "succeeded", "completed_at": _iso(1)}],
    )
    # NULL / CONDITIONAL_PASS are research verdicts, not execution failures.
    _write(
        storage / "work_log.json",
        [{"task_id": "A", "verdict": "NULL", "outcome": "succeeded", "timestamp": _iso(1)}],
    )
    r = lh.compute_first_pass_success(str(storage), now=NOW)
    assert r["first_pass"] == 1  # not counted as retried
    assert r["retried"] == 0


# ---------------------------------------------------------------------------
# task_outcome
# ---------------------------------------------------------------------------
def test_task_outcome_success_share(tmp_path):
    storage = _storage(tmp_path)
    tasks = (
        [{"id": f"s{i}", "status": "succeeded", "completed_at": _iso(1)} for i in range(8)]
        + [{"id": "f1", "status": "failed", "completed_at": _iso(1)}]
        + [{"id": "b1", "status": "blocked", "completed_at": _iso(1)}]
    )
    _write(storage / "next_tasks.json", tasks)
    r = lh.compute_task_outcome(str(storage), now=NOW)
    assert r["success"] == 8 and r["fail"] == 1 and r["blocked"] == 1
    assert r["success_rate"] == 0.8
    assert r["status"] == "ok"


def test_task_outcome_window_excludes_old(tmp_path):
    storage = _storage(tmp_path)
    _write(
        storage / "next_tasks.json",
        [
            {"id": "recent", "status": "succeeded", "completed_at": _iso(1)},
            {"id": "old", "status": "failed", "completed_at": _iso(40)},
        ],
    )
    r = lh.compute_task_outcome(str(storage), now=NOW)
    assert r["success"] == 1 and r["fail"] == 0  # old failure outside 14d window


# ---------------------------------------------------------------------------
# error_recurrence
# ---------------------------------------------------------------------------
def _cron_log(storage: Path, name: str, code: int, times: list[float]) -> None:
    lines = [
        f"=== [{name}] exit {code} at {(NOW - timedelta(days=t)).strftime('%Y-%m-%d %H:%M:%S')} CST ==="
        for t in times
    ]
    (storage / "logs" / "cron" / f"{name}.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_error_recurrence_flags_repeated_exit(tmp_path):
    storage = _storage(tmp_path)
    _cron_log(storage, "myjob", 1, [1, 2, 3, 4, 5])  # 5 non-zero exits over 4d
    r = lh.compute_error_recurrence(str(storage), now=NOW)
    assert r["recurring"] >= 1
    top = r["top_recurring"][0]
    assert top["signature"] == "myjob.log:exit1"
    assert top["count"] == 5
    assert r["status"] in ("warn", "degrading")


def test_error_recurrence_recovered_job_does_not_escalate(tmp_path):
    """Boss 2026-06-29: a failure cluster whose latest fire is exit 0 and whose last
    failure is older than RECOVERY_GRACE_HOURS is RECOVERED (root fixed) — it must
    NOT keep reading degrading/critical just because the historical spike is still
    in the 14d window (the 06-28-fixed hourly_dispatch keychain false-critical)."""
    storage = _storage(tmp_path)
    # 8 old exit1 (≥2 days ago) then a recent exit 0 (the job recovered).
    lines = [
        f"=== [myjob] exit 1 at {(NOW - timedelta(days=t)).strftime('%Y-%m-%d %H:%M:%S')} CST ==="
        for t in [8, 7, 6, 5, 4, 3, 2.5, 2]
    ]
    lines.append(
        f"=== [myjob] exit 0 at {(NOW - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')} CST ==="
    )
    (storage / "logs" / "cron" / "myjob.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

    r = lh.compute_error_recurrence(str(storage), now=NOW)
    top = r["top_recurring"][0]
    assert top["signature"] == "myjob.log:exit1"
    assert top["recovered"] is True  # latest fire exit0 + failures >6h old
    assert r["status"] == "ok"  # recovered → does not escalate


def test_error_recurrence_still_active_failure_escalates(tmp_path):
    """A failure whose LATEST fire is still non-zero (not recovered) keeps escalating."""
    storage = _storage(tmp_path)
    _cron_log(storage, "myjob", 1, [4, 3, 2, 1, 0.1])  # most recent is still exit1
    r = lh.compute_error_recurrence(str(storage), now=NOW)
    assert r["top_recurring"][0].get("recovered") is False
    assert r["status"] in ("warn", "degrading")


def test_error_recurrence_exit142_marked_known_and_not_escalating(tmp_path):
    storage = _storage(tmp_path)
    _cron_log(storage, "hourly_dispatch", 142, [1, 2, 3, 4, 5, 6, 7, 8])  # would degrade if not known
    r = lh.compute_error_recurrence(str(storage), now=NOW)
    top = r["top_recurring"][0]
    assert top["signature"].endswith(":exit142")
    assert top["known"] is True
    assert r["status"] == "ok"  # self-healing signature must not escalate


def test_error_recurrence_skips_audit_logs(tmp_path):
    storage = _storage(tmp_path)
    _cron_log(storage, "audit_fb_pipeline", 1, [1, 2, 3, 4, 5])  # findings-as-exit, not error
    r = lh.compute_error_recurrence(str(storage), now=NOW)
    assert r["distinct_signatures"] == 0


def _dispatch_completion(days_ago: float, outcome: str, exit_code: int = 1) -> dict:
    ts = _iso(days_ago)
    return {
        "fire_at": ts,
        "completed_at": ts,
        "exit_code": exit_code,
        "duration_s": 5.0,
        "attempts": 1,
        "final_model": "claude-opus-4-8",
        "outcome": outcome,
    }


def test_error_recurrence_counts_dispatch_supervisor_completions(tmp_path):
    storage = _storage(tmp_path)
    _write(
        storage / "ops" / "dispatch_state.json",
        {"completions": [_dispatch_completion(t, "failure", 1) for t in [1, 2, 3, 4, 5]]},
    )
    r = lh.compute_error_recurrence(str(storage), now=NOW)
    top = r["top_recurring"][0]
    assert top["signature"] == "dispatch_supervisor:failure:exit1"
    assert top["source"] == "dispatch_state.completions"
    assert top["count"] == 5
    assert r["status"] in ("warn", "degrading")


def test_error_recurrence_dispatch_supervisor_success_marks_recovered(tmp_path):
    storage = _storage(tmp_path)
    failures = [_dispatch_completion(t, "failure", 1) for t in [8, 7, 6, 5, 4, 3, 2.5, 2]]
    success = _dispatch_completion(1 / 24, "success", 0)
    _write(storage / "ops" / "dispatch_state.json", {"completions": failures + [success]})

    r = lh.compute_error_recurrence(str(storage), now=NOW)
    top = r["top_recurring"][0]
    assert top["signature"] == "dispatch_supervisor:failure:exit1"
    assert top["recovered"] is True
    assert r["status"] == "ok"


def test_error_recurrence_dispatch_supervisor_log_fallback(tmp_path, monkeypatch):
    storage = _storage(tmp_path)
    home = tmp_path / "home"
    log_dir = home / "logs"
    log_dir.mkdir(parents=True)
    lines = [
        "2026-06-28 20:08:33,059 INFO [scripts.dispatch_supervisor.scheduler] "
        "worker returned outcome=failure attempts=3 duration=13.8s",
        "2026-06-29 20:08:33,059 INFO [scripts.dispatch_supervisor.scheduler] "
        "worker returned outcome=failure attempts=3 duration=13.8s",
        "2026-06-30 20:08:33,059 INFO [scripts.dispatch_supervisor.scheduler] "
        "worker returned outcome=failure attempts=3 duration=13.8s",
        "2026-07-01 20:08:33,059 INFO [scripts.dispatch_supervisor.scheduler] "
        "worker returned outcome=failure attempts=3 duration=13.8s",
        "2026-07-02 20:08:33,059 INFO [scripts.dispatch_supervisor.scheduler] "
        "worker returned outcome=failure attempts=3 duration=13.8s",
    ]
    (log_dir / "dispatch_supervisor.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setenv("VOLPRED_HOME_DIR", str(home))

    r = lh.compute_error_recurrence(str(storage), now=NOW)
    top = r["top_recurring"][0]
    assert top["signature"] == "dispatch_supervisor:failure"
    assert top["source"] == "dispatch_supervisor.log"
    assert top["count"] == 5
    assert r["status"] == "warn"


# ---------------------------------------------------------------------------
# correction_trend
# ---------------------------------------------------------------------------
def test_correction_trend_rising_is_worsening(tmp_path):
    storage = _storage(tmp_path)
    # week 0 (recent) heavy, older weeks light → rising → worsening
    rows = (
        [{"outcome": "self_correction", "timestamp": _iso(1)} for _ in range(4)]
        + [{"outcome": "correction", "timestamp": _iso(8)} for _ in range(1)]
    )
    _write(storage / "work_log.json", rows)
    r = lh.compute_correction_trend(str(storage), now=NOW)
    assert r["trend"] == "worsening"
    assert r["status"] == "warn"


def test_correction_trend_flat_when_no_corrections(tmp_path):
    storage = _storage(tmp_path)
    _write(storage / "work_log.json", [{"outcome": "done", "timestamp": _iso(1)}])
    r = lh.compute_correction_trend(str(storage), now=NOW)
    assert r["trend"] == "flat"
    assert r["status"] == "ok"


# ---------------------------------------------------------------------------
# fail-open + aggregate
# ---------------------------------------------------------------------------
def test_metrics_fail_open_on_corrupt_files(tmp_path):
    storage = _storage(tmp_path)
    (storage / "next_tasks.json").write_text("{not json", encoding="utf-8")
    (storage / "work_log.json").write_text("[[[", encoding="utf-8")
    # Must not raise; returns unknown/usable dicts.
    fp = lh.compute_first_pass_success(str(storage), now=NOW)
    to = lh.compute_task_outcome(str(storage), now=NOW)
    assert fp["status"] in ("unknown", "low_coverage")
    assert to["status"] == "unknown"


def test_snapshot_overall_is_worst_substatus(tmp_path):
    storage = _storage(tmp_path)
    _cron_log(storage, "myjob", 1, [1, 2, 3, 4, 5, 6, 7, 8])  # degrading recurrence
    _write(storage / "next_tasks.json", [])
    _write(storage / "work_log.json", [])
    snap = lh.loop_health_snapshot(str(storage), now=NOW)
    assert snap["overall"] == "degrading"
    assert set(snap).issuperset(
        {"first_pass_success", "task_outcome", "error_recurrence", "correction_trend"}
    )
