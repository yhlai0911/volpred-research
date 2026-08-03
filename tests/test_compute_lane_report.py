"""The report exists to separate two causes of an idle CPU, so test that split.

"We have compute but nothing runs" has been answered by raising a slot count
before. It is only ever answerable with evidence: either no model-free work is
queued (nothing is broken, and more slots change nothing), or work is queued and
sitting (then the wait numbers say where). These lock that verdict.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import compute_lane_report as report


@pytest.fixture()
def lane(tmp_path: Path, monkeypatch) -> Path:
    queue = tmp_path / "compute_queue"
    queue.mkdir()
    monkeypatch.setattr(report, "QUEUE_DIR", queue)
    monkeypatch.setattr(report, "NEXT_TASKS", tmp_path / "next_tasks.json")
    monkeypatch.setattr(report, "_max_parallel", lambda: 3)
    (tmp_path / "next_tasks.json").write_text("[]", encoding="utf-8")
    return tmp_path


def _pool(lane: Path, tasks: list[dict]) -> None:
    (lane / "next_tasks.json").write_text(json.dumps(tasks), encoding="utf-8")


def _job(lane: Path, job_id: str, **fields) -> None:
    payload = {"id": job_id, **fields}
    (lane / "compute_queue" / f"{job_id}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_idle_lane_with_no_admissible_work_is_not_a_failure(lane: Path) -> None:
    """131 agent tasks and zero compute_spec means there is nothing to run."""
    _pool(
        lane,
        [
            {"id": "a", "status": "pending", "task_type": "daily_article"},
            {"id": "b", "status": "pending", "task_type": "experiment"},
        ],
    )

    out = report.build_report(7.0)

    assert out["verdict"] == "no_model_free_work_queued"
    assert out["supply"]["pending_total"] == 2
    assert out["supply"]["pending_with_compute_spec"] == 0


def test_queued_work_that_is_not_running_is_called_out(lane: Path) -> None:
    _pool(
        lane,
        [
            {
                "id": "cpu-1",
                "status": "pending",
                "compute_spec": {"script": "scripts/x.py"},
            }
        ],
    )

    out = report.build_report(7.0)

    assert out["verdict"] == "queued_work_not_running"
    assert out["supply"]["admissible_task_ids"] == ["cpu-1"]


def test_agent_and_compute_statistics_never_merge(lane: Path) -> None:
    """Agent jobs answer to quota; averaging them in hides a healthy lane."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    _job(
        lane,
        "fast-compute",
        kind="compute",
        status="completed",
        queued_at=(now - timedelta(hours=2)).isoformat(),
        started_at=(now - timedelta(hours=2)).isoformat(),
        completed_at=(now - timedelta(hours=1)).isoformat(),
    )
    _job(
        lane,
        "slow-agent",
        kind="agent",
        status="failed",
        queued_at=(now - timedelta(hours=30)).isoformat(),
        started_at=(now - timedelta(hours=5)).isoformat(),
        completed_at=(now - timedelta(hours=4)).isoformat(),
    )

    out = report.build_report(7.0)
    by_kind = out["lane"]["by_kind"]

    assert by_kind["compute"]["settled"] == 1
    assert by_kind["compute"]["failed"] == 0
    assert by_kind["compute"]["wait_p90_h"] == 0.0
    assert by_kind["agent"]["settled"] == 1
    assert by_kind["agent"]["failed"] == 1
    assert by_kind["agent"]["wait_p90_h"] > 20
    # Utilization is reported against the canonical parallelism bound.
    assert out["lane"]["capacity_core_hours"] == pytest.approx(3 * 7 * 24)


def test_in_flight_jobs_are_not_counted_as_settled(lane: Path) -> None:
    _job(lane, "running-now", kind="compute", status="running")

    out = report.build_report(7.0)

    assert out["lane"]["in_flight"] == {"compute:running": 1}
    assert "compute" not in out["lane"]["by_kind"]


def test_torn_receipt_does_not_abort_the_report(lane: Path) -> None:
    (lane / "compute_queue" / "broken.json").write_text("{not json", encoding="utf-8")
    _job(lane, "ok", kind="compute", status="running")

    out = report.build_report(7.0)

    assert out["lane"]["in_flight"] == {"compute:running": 1}
