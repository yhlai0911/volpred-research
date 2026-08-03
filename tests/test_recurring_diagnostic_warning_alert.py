"""A `warn()` that repeats for hours is a repair that never happened.

Background: `compute_queue` warned "cancelled source task settlement did not
match" on every compute-worker tick from 2026-07-21 to 2026-08-03 — roughly
2,500 emissions — because its reconciler had no terminal edge for a source task
that had already settled elsewhere. Nothing alerted, because the canonical
`warn()` helper wrote to stderr only and every scheduled wrapper redirects
stderr into a per-job log file that no detector reads.

These lock the detector that closes that gap: persistent repetition breaches,
bursts and recovered loops do not.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from volpred.ops import alerts


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def _write_records(
    storage_dir: Path,
    tag: str,
    msg: str,
    *,
    count: int,
    first_offset_hours: float,
    last_offset_hours: float,
    ctx: dict | None = None,
) -> None:
    """Spread `count` identical warnings evenly across a window before NOW."""
    log_dir = storage_dir / "logs" / "diagnostics"
    log_dir.mkdir(parents=True, exist_ok=True)
    span = first_offset_hours - last_offset_hours
    step = span / max(count - 1, 1)
    lines = []
    for i in range(count):
        ts = NOW - timedelta(hours=first_offset_hours - step * i)
        lines.append(
            json.dumps(
                {
                    "ts": ts.isoformat(),
                    "tag": tag,
                    "msg": msg,
                    "ctx": ctx or {},
                },
                ensure_ascii=False,
            )
        )
    (log_dir / f"{tag}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_stuck_warning_breaches_and_reports_the_loop(tmp_path: Path) -> None:
    _write_records(
        tmp_path,
        "compute_queue",
        "cancelled source task settlement did not match",
        count=400,
        first_offset_hours=72.0,
        last_offset_hours=0.2,
        ctx={"job": "k1380-stage1-forecasts-a"},
    )

    state = alerts._parse_recurring_diagnostic_warning_state(str(tmp_path), NOW)

    assert state["id"] == "recurring_diagnostic_warning"
    assert state["breached"] is True
    # 72h span is past the critical threshold — this is not a transient.
    assert state["level"] == "critical"
    assert state["details"]["stuck_count"] == 1
    stuck = state["details"]["stuck"][0]
    assert stuck["tag"] == "compute_queue"
    assert stuck["count"] == 400
    assert stuck["sample_ctx"] == {"job": "k1380-stage1-forecasts-a"}
    assert "cancelled source task settlement did not match" in state["body"]


def test_short_burst_does_not_breach(tmp_path: Path) -> None:
    """Fifty warnings in five minutes is noisy, not stuck."""
    _write_records(
        tmp_path,
        "dispatch",
        "transient claim retry",
        count=50,
        first_offset_hours=0.1,
        last_offset_hours=0.01,
    )

    state = alerts._parse_recurring_diagnostic_warning_state(str(tmp_path), NOW)

    assert state["breached"] is False
    assert state["details"]["stuck_count"] == 0


def test_resolved_loop_stops_breaching(tmp_path: Path) -> None:
    """A loop that was fixed yesterday must clear, not alert forever."""
    _write_records(
        tmp_path,
        "compute_queue",
        "cancelled source task settlement did not match",
        count=400,
        first_offset_hours=96.0,
        last_offset_hours=30.0,
    )

    state = alerts._parse_recurring_diagnostic_warning_state(str(tmp_path), NOW)

    assert state["breached"] is False


def test_rare_but_long_lived_warning_does_not_breach(tmp_path: Path) -> None:
    """Five warnings over a week is a rare event, not a spinning loop."""
    _write_records(
        tmp_path,
        "supabase",
        "sync retry",
        count=5,
        first_offset_hours=140.0,
        last_offset_hours=0.5,
    )

    state = alerts._parse_recurring_diagnostic_warning_state(str(tmp_path), NOW)

    assert state["breached"] is False


def test_identity_ignores_ctx_so_a_stuck_class_is_still_one_finding(
    tmp_path: Path,
) -> None:
    """Varying ids with one repeated message is the same defect, not many."""
    log_dir = tmp_path / "logs" / "diagnostics"
    log_dir.mkdir(parents=True)
    lines = []
    for i in range(60):
        ts = NOW - timedelta(hours=24.0 - i * 0.39)
        lines.append(
            json.dumps(
                {
                    "ts": ts.isoformat(),
                    "tag": "compute_queue",
                    "msg": "settlement did not match",
                    "ctx": {"job": f"job-{i}"},
                }
            )
        )
    (log_dir / "compute_queue.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    state = alerts._parse_recurring_diagnostic_warning_state(str(tmp_path), NOW)

    assert state["breached"] is True
    assert state["details"]["stuck_count"] == 1
    assert state["details"]["stuck"][0]["count"] == 60


def test_missing_log_dir_is_not_a_breach(tmp_path: Path) -> None:
    state = alerts._parse_recurring_diagnostic_warning_state(str(tmp_path), NOW)

    assert state["breached"] is False
    assert state["details"]["stuck_count"] == 0


def test_torn_final_line_is_skipped_without_losing_the_rest(
    tmp_path: Path,
) -> None:
    """Another process is appending; a half-written line proves nothing."""
    _write_records(
        tmp_path,
        "compute_queue",
        "settlement did not match",
        count=400,
        first_offset_hours=72.0,
        last_offset_hours=0.2,
    )
    log = tmp_path / "logs" / "diagnostics" / "compute_queue.jsonl"
    with log.open("a", encoding="utf-8") as fh:
        fh.write('{"ts": "2026-08-03T11:5')

    state = alerts._parse_recurring_diagnostic_warning_state(str(tmp_path), NOW)

    assert state["breached"] is True
    assert state["details"]["stuck"][0]["count"] == 400
    assert state["details"]["read_errors"] == []


def test_condition_is_wired_into_the_report_and_creates_a_task(
    tmp_path: Path,
) -> None:
    """Registration is the point: an unregistered detector alerts nobody."""
    from volpred.ops import alert_remediation

    assert "recurring_diagnostic_warning" in alert_remediation.ALERT_TASK_TYPE
    # Deliberately NOT self-remediating: the repair differs per stuck path, so
    # the framework's default disposition (create a task) is the correct one.
    assert "recurring_diagnostic_warning" not in alert_remediation.SELF_REMEDIATING
    assert "recurring_diagnostic_warning" not in alert_remediation.OWNER_DECISION

    # Built against an empty storage dir: this asserts registration, and must
    # not read or touch live platform state to do it.
    report = alerts.build_alert_condition_report(storage_dir=str(tmp_path))
    ids = {item.get("id") for item in report["conditions"]}
    assert "recurring_diagnostic_warning" in ids


def test_breach_materializes_a_platform_ops_task_end_to_end(tmp_path: Path) -> None:
    """The whole point of the detector: a stuck loop becomes work, not an email."""
    from volpred.ops import alert_remediation

    (tmp_path / "next_tasks.json").write_text("[]", encoding="utf-8")
    _write_records(
        tmp_path,
        "compute_queue",
        "cancelled source task settlement did not match",
        count=400,
        first_offset_hours=72.0,
        last_offset_hours=0.2,
    )
    condition = alerts._parse_recurring_diagnostic_warning_state(str(tmp_path), NOW)
    assert condition["breached"] is True

    result = alert_remediation.remediate_condition(
        condition,
        storage_dir=str(tmp_path),
        now=NOW,
    )

    assert result["disposition"] == "task"
    tasks = json.loads((tmp_path / "next_tasks.json").read_text(encoding="utf-8"))
    created = [t for t in tasks if t.get("task_type") == "platform_ops"]
    assert len(created) == 1
    assert created[0]["status"] == "pending"
    # The email now reports queued work rather than handing the owner a chore.
    assert "建議行動" not in condition["body"]
