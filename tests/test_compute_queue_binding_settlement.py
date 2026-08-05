from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from scripts import compute_queue
from scripts import task_pool_claim as task_pool


def _patch_state(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    queue_dir = tmp_path / "compute_queue"
    queue_dir.mkdir()
    pool_path = tmp_path / "next_tasks.json"
    monkeypatch.setattr(compute_queue, "QUEUE_DIR", queue_dir)
    monkeypatch.setattr(compute_queue, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(compute_queue, "LOCK_FILE", queue_dir / ".worker.lock")
    monkeypatch.setattr(task_pool, "NEXT_TASKS", pool_path)
    monkeypatch.setattr(task_pool, "guard_canonical_write", lambda *_a, **_k: None)
    return queue_dir, pool_path


def test_mark_followup_dispatched_releases_source_task_binding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Collection completion transfers ownership out of the terminal job."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text(
        json.dumps(
            [
                {
                    "id": "task-a",
                    "status": "awaiting_agent_job",
                    "compute_job_id": "job-old",
                    "blocked_reason": "external_compute_receipt_pending_collection",
                    "compute_finished_at": "2026-07-28T01:00:00Z",
                }
            ]
        ),
        encoding="utf-8",
    )
    receipt_path = queue_dir / "job-old.json"
    receipt_path.write_text(
        json.dumps(
            {
                "id": "job-old",
                "status": "completed",
                "source_task_id": "task-a",
                "followup_dispatched": False,
            }
        ),
        encoding="utf-8",
    )

    rc = compute_queue.mark_followup_dispatched(
        SimpleNamespace(id="job-old", next_task_id="task-a-followup")
    )

    assert rc == 0
    task = json.loads(pool_path.read_text(encoding="utf-8"))[0]
    assert task["status"] == "pending"
    assert "compute_job_id" not in task
    assert "blocked_reason" not in task
    assert "compute_finished_at" not in task
    assert task["status_history"][-1] == {
        "ts": task["status_history"][-1]["ts"],
        "from": "awaiting_agent_job",
        "to": "pending",
        "by": "compute-followup:job-old",
        "note": "terminal receipt collected; followup=task-a-followup",
    }

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["followup_dispatched"] is True
    assert receipt["followup_next_task_id"] == "task-a-followup"
    assert receipt["source_task_settlement"]["state"] == "settled"
    assert receipt["source_task_settlement"]["task_id"] == "task-a"


def test_worker_repairs_pre_fix_followup_split_before_claim(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A collected terminal owner may be atomically replaced by its successor."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text(
        json.dumps(
            [
                {
                    "id": "task-a",
                    "status": "awaiting_agent_job",
                    "compute_job_id": "job-old",
                    "blocked_reason": "external_compute_receipt_pending_collection",
                }
            ]
        ),
        encoding="utf-8",
    )
    (queue_dir / "job-old.json").write_text(
        json.dumps(
            {
                "id": "job-old",
                "status": "completed",
                "source_task_id": "task-a",
                "followup_dispatched": True,
                "followup_next_task_id": "job-new",
            }
        ),
        encoding="utf-8",
    )
    successor_path = queue_dir / "job-new.json"
    successor_path.write_text(
        json.dumps(
            {
                "id": "job-new",
                "status": "queued",
                "title": "successor",
                "queued_at": "2026-07-28T01:00:00Z",
                "source_task_id": "task-a",
                "source_task_link": {
                    "state": "error",
                    "error": "legacy split",
                },
            }
        ),
        encoding="utf-8",
    )

    ready, sleeping = compute_queue._ready_queued_jobs("test-followup-split")

    assert sleeping == 0
    assert [item[2] for item in ready] == [successor_path]
    task = json.loads(pool_path.read_text(encoding="utf-8"))[0]
    assert task["status"] == "awaiting_agent_job"
    assert task["compute_job_id"] == "job-new"
    assert task["blocked_reason"] == "external_compute_job_active"
    assert task["status_history"][-2]["by"] == "compute-followup:job-old"
    assert task["status_history"][-1]["by"] == "compute-job:job-new"
    successor = json.loads(successor_path.read_text(encoding="utf-8"))
    assert successor["source_task_link"]["state"] == "linked"
    assert successor["source_task_link"]["recovered_from_job_id"] == "job-old"


def test_worker_explicitly_terminates_job_for_terminal_source_task(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A failed source task is not executable ownership and must not stay queued."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text(
        json.dumps([{"id": "task-failed", "status": "failed"}]),
        encoding="utf-8",
    )
    job_path = queue_dir / "job-invalid.json"
    job_path.write_text(
        json.dumps(
            {
                "id": "job-invalid",
                "status": "queued",
                "title": "invalid successor",
                "queued_at": "2026-07-27T01:00:00Z",
                "source_task_id": "task-failed",
            }
        ),
        encoding="utf-8",
    )

    ready, sleeping = compute_queue._ready_queued_jobs("test-terminal-owner")

    assert ready == []
    assert sleeping == 0
    receipt = json.loads(job_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "cancelled"
    assert receipt["cancel_reason"] == "source_task_terminal:failed"
    assert receipt["followup_dispatched"] is True
    assert receipt["source_task_link"] == {
        "state": "terminal",
        "reason": "source_task_terminal",
        "source_task_status": "failed",
    }


def test_survives_source_success_job_is_not_cancelled_when_source_succeeds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A post-success review gate is exactly the job meant to run next.

    2026-08-05 incident: an erratum-review gate job (K1259 knowledge-write
    precondition) was auto-cancelled the same minute its source task reached
    "succeeded", because the terminal-status check treated success the same
    as failure/cancellation. The research artifact's promotion chain broke
    silently until a human happened to notice days later.
    """
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text(
        json.dumps([{"id": "task-succeeded", "status": "succeeded"}]),
        encoding="utf-8",
    )
    job_path = queue_dir / "job-gate.json"
    job_path.write_text(
        json.dumps(
            {
                "id": "job-gate",
                "status": "queued",
                "title": "erratum review gate",
                "queued_at": "2026-08-05T13:45:00Z",
                "source_task_id": "task-succeeded",
                "survives_source_success": True,
            }
        ),
        encoding="utf-8",
    )

    ready, sleeping = compute_queue._ready_queued_jobs("test-survives-owner")

    assert sleeping == 0
    receipt = json.loads(job_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "queued"  # NOT cancelled
    assert receipt["source_task_link"] == {
        "state": "linked",
        "reason": "source_task_succeeded_survives_by_design",
        "source_task_status": "succeeded",
    }


def test_survives_source_success_still_cancels_on_failed_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The exemption is for success specifically, not "any terminal state"."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text(
        json.dumps([{"id": "task-failed", "status": "failed"}]),
        encoding="utf-8",
    )
    job_path = queue_dir / "job-gate-2.json"
    job_path.write_text(
        json.dumps(
            {
                "id": "job-gate-2",
                "status": "queued",
                "title": "gate on a source that never produced an artifact",
                "queued_at": "2026-08-05T13:45:00Z",
                "source_task_id": "task-failed",
                "survives_source_success": True,
            }
        ),
        encoding="utf-8",
    )

    compute_queue._ready_queued_jobs("test-survives-owner-2")

    receipt = json.loads(job_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "cancelled"
    assert receipt["cancel_reason"] == "source_task_terminal:failed"


def test_auto_cancel_on_terminal_source_leaves_a_diagnostics_trace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A silent auto-cancel is what let the 2026-08-05 gate loss go unnoticed."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text(
        json.dumps([{"id": "task-failed", "status": "failed"}]),
        encoding="utf-8",
    )
    job_path = queue_dir / "job-invalid-2.json"
    job_path.write_text(
        json.dumps(
            {
                "id": "job-invalid-2",
                "status": "queued",
                "title": "invalid successor",
                "queued_at": "2026-07-27T01:00:00Z",
                "source_task_id": "task-failed",
            }
        ),
        encoding="utf-8",
    )

    warned: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        compute_queue,
        "warn",
        lambda tag, msg, **ctx: warned.append((tag, msg, ctx)),
    )

    compute_queue._ready_queued_jobs("test-terminal-owner-2")

    assert len(warned) == 1
    tag, _msg, ctx = warned[0]
    assert tag == "compute_queue_auto_cancel"
    assert ctx["job_id"] == "job-invalid-2"
    assert ctx["source_task_status"] == "failed"


def test_worker_explicitly_terminates_missing_source_after_creation_grace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A missing source may be an enqueue split briefly, never for hours."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text("[]", encoding="utf-8")
    job_path = queue_dir / "job-orphan.json"
    job_path.write_text(
        json.dumps(
            {
                "id": "job-orphan",
                "status": "queued",
                "title": "orphan",
                "queued_at": "2026-07-27T01:00:00Z",
                "source_task_id": "task-missing",
            }
        ),
        encoding="utf-8",
    )

    ready, sleeping = compute_queue._ready_queued_jobs("test-missing-owner")

    assert ready == []
    assert sleeping == 0
    receipt = json.loads(job_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "cancelled"
    assert receipt["cancel_reason"] == "source_task_missing_after_grace"
    assert receipt["source_task_link"] == {
        "state": "terminal",
        "reason": "source_task_missing_after_grace",
    }


def test_run_loop_reports_automatically_terminalized_bindings(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """Invalid jobs may resolve cleanly, but never look like an empty queue."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text(
        json.dumps([{"id": "task-failed", "status": "failed"}]),
        encoding="utf-8",
    )
    (queue_dir / "job-invalid.json").write_text(
        json.dumps(
            {
                "id": "job-invalid",
                "status": "queued",
                "title": "invalid successor",
                "queued_at": "2026-07-27T01:00:00Z",
                "source_task_id": "task-failed",
            }
        ),
        encoding="utf-8",
    )

    rc = compute_queue.run_loop(SimpleNamespace(max_parallel=1))

    output = capsys.readouterr().out
    assert rc == 0
    assert "jobs_run=0" in output
    assert "binding_terminalized=1" in output
    assert "source_task_terminal=1" in output


def test_run_next_reports_terminalized_job_even_when_another_job_runs(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """Single-shot execution must not hide reconciliation from the same scan."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text(
        json.dumps([{"id": "task-failed", "status": "failed"}]),
        encoding="utf-8",
    )
    (queue_dir / "job-invalid.json").write_text(
        json.dumps(
            {
                "id": "job-invalid",
                "status": "queued",
                "title": "invalid",
                "queued_at": "2026-07-27T01:00:00Z",
                "source_task_id": "task-failed",
            }
        ),
        encoding="utf-8",
    )
    (queue_dir / "job-ready.json").write_text(
        json.dumps(
            {
                "id": "job-ready",
                "status": "queued",
                "title": "ready",
                "queued_at": "2026-07-27T02:00:00Z",
                "script_path": "unused.py",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(compute_queue, "_run_claimed", lambda *_args: None)

    rc = compute_queue.run_next(SimpleNamespace())

    output = capsys.readouterr().out
    assert rc == 0
    assert "running: job-ready" in output
    assert "binding_terminalized=1" in output
    assert "source_task_terminal=1" in output


def test_run_loop_fails_loud_when_binding_remains_blocked(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """A non-empty but unclaimable queue is unhealthy, not an empty success."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text(
        json.dumps(
            [
                {
                    "id": "task-a",
                    "status": "awaiting_agent_job",
                    "compute_job_id": "job-owner-receipt-missing",
                    "blocked_reason": "external_compute_job_active",
                }
            ]
        ),
        encoding="utf-8",
    )
    (queue_dir / "job-waiting.json").write_text(
        json.dumps(
            {
                "id": "job-waiting",
                "status": "queued",
                "title": "waiting",
                "queued_at": "2026-07-28T01:00:00Z",
                "source_task_id": "task-a",
            }
        ),
        encoding="utf-8",
    )

    rc = compute_queue.run_loop(SimpleNamespace(max_parallel=1))

    output = capsys.readouterr().out
    assert rc == 3
    assert "jobs_run=0" in output
    assert "binding_blocked=1" in output
    assert "source_task_owner_receipt_missing=1" in output


def test_amend_can_upgrade_model_only_while_agent_job_is_queued(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Frozen work orders need a sanctioned model migration before claim."""
    queue_dir, _pool_path = _patch_state(tmp_path, monkeypatch)
    job_path = queue_dir / "agent-old-model.json"
    job_path.write_text(
        json.dumps(
            {
                "id": "agent-old-model",
                "status": "queued",
                "kind": "agent",
                "args": [
                    "--brief-file",
                    "brief.md",
                    "--model",
                    "claude-opus-4-8",
                ],
            }
        ),
        encoding="utf-8",
    )

    rc = compute_queue.amend(
        SimpleNamespace(
            id="agent-old-model",
            brief_file=None,
            followup_brief=None,
            followup_task_type=None,
            followup_priority=None,
            timeout=None,
            model="claude-opus-5",
        )
    )

    assert rc == 0
    amended = json.loads(job_path.read_text(encoding="utf-8"))
    assert amended["args"] == [
        "--brief-file",
        "brief.md",
        "--model",
        "claude-opus-5",
    ]


def test_amend_refuses_model_outside_canonical_router(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """A typo must not turn a queued work order into a guaranteed spawn failure."""
    queue_dir, _pool_path = _patch_state(tmp_path, monkeypatch)
    job_path = queue_dir / "agent-model-typo.json"
    original = {
        "id": "agent-model-typo",
        "status": "queued",
        "kind": "agent",
        "args": ["--model", "claude-opus-5"],
    }
    job_path.write_text(json.dumps(original), encoding="utf-8")

    rc = compute_queue.amend(
        SimpleNamespace(
            id="agent-model-typo",
            brief_file=None,
            followup_brief=None,
            followup_task_type=None,
            followup_priority=None,
            timeout=None,
            model="claude-opus-500",
        )
    )

    assert rc == 2
    assert "canonical model router" in capsys.readouterr().err
    assert json.loads(job_path.read_text(encoding="utf-8")) == original


def test_execution_settlement_failure_is_durable_and_collection_recovers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A crash split after child exit must remain visible and recoverable."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text(
        json.dumps(
            [
                {
                    "id": "task-a",
                    "status": "awaiting_agent_job",
                    "compute_job_id": "job-a",
                    "blocked_reason": "external_compute_job_active",
                }
            ]
        ),
        encoding="utf-8",
    )
    job = {"id": "job-a", "source_task_id": "task-a"}
    original_locked_load = task_pool._locked_load
    calls = 0

    @contextmanager
    def fail_second_queue_write():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected settlement failure")
        with original_locked_load() as locked:
            yield locked

    monkeypatch.setattr(task_pool, "_locked_load", fail_second_queue_write)
    with compute_queue._source_task_execution_fence(job) as valid:
        assert valid is True

    assert job["source_task_settlement"]["state"] == "error"
    assert "injected settlement failure" in job["source_task_settlement"]["error"]
    task = json.loads(pool_path.read_text(encoding="utf-8"))[0]
    assert task["blocked_reason"] == "external_compute_job_running"

    receipt_path = queue_dir / "job-a.json"
    receipt_path.write_text(
        json.dumps(
            {
                **job,
                "status": "completed",
                "followup_dispatched": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_pool, "_locked_load", original_locked_load)

    rc = compute_queue.mark_followup_dispatched(
        SimpleNamespace(id="job-a", next_task_id="task-a-followup")
    )

    assert rc == 0
    task = json.loads(pool_path.read_text(encoding="utf-8"))[0]
    assert task["status"] == "pending"
    assert "compute_job_id" not in task
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["followup_dispatched"] is True
    assert receipt["source_task_settlement"]["state"] == "settled"


def test_followup_ack_preserves_newer_source_binding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An older receipt may settle without stealing a newer job's ownership."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text(
        json.dumps(
            [
                {
                    "id": "task-a",
                    "status": "awaiting_agent_job",
                    "compute_job_id": "some-other-job",
                    "blocked_reason": "external_compute_job_running",
                }
            ]
        ),
        encoding="utf-8",
    )
    receipt_path = queue_dir / "job-a.json"
    original = {
        "id": "job-a",
        "status": "completed",
        "source_task_id": "task-a",
        "followup_dispatched": False,
    }
    receipt_path.write_text(json.dumps(original), encoding="utf-8")

    rc = compute_queue.mark_followup_dispatched(
        SimpleNamespace(id="job-a", next_task_id="task-a-followup")
    )

    assert rc == 0
    assert json.loads(pool_path.read_text(encoding="utf-8"))[0] == {
        "id": "task-a",
        "status": "awaiting_agent_job",
        "compute_job_id": "some-other-job",
        "blocked_reason": "external_compute_job_running",
        "priority": 3,
    }
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["followup_dispatched"] is True
    assert receipt["source_task_settlement"] == {
        "state": "settled",
        "task_id": "task-a",
        "reason": "newer_compute_owner_preserved",
        "owner_job_id": "some-other-job",
        "settled_at": receipt["source_task_settlement"]["settled_at"],
    }


def test_followup_ack_preserves_terminal_source_and_clears_own_stale_binding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Terminal settlement is stronger than release-to-pending."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text(
        json.dumps(
            [
                {
                    "id": "task-a",
                    "status": "failed",
                    "compute_job_id": "job-a",
                    "blocked_reason": "external_compute_receipt_pending_collection",
                    "compute_finished_at": "2026-07-28T01:00:00Z",
                    "result": "review failed",
                }
            ]
        ),
        encoding="utf-8",
    )
    receipt_path = queue_dir / "job-a.json"
    receipt_path.write_text(
        json.dumps(
            {
                "id": "job-a",
                "status": "completed",
                "source_task_id": "task-a",
                "followup_dispatched": False,
            }
        ),
        encoding="utf-8",
    )

    rc = compute_queue.mark_followup_dispatched(
        SimpleNamespace(id="job-a", next_task_id="task-a-followup")
    )

    assert rc == 0
    task = json.loads(pool_path.read_text(encoding="utf-8"))[0]
    assert task == {
        "id": "task-a",
        "status": "failed",
        "result": "review failed",
        "priority": 3,
        "compute_released_at": task["compute_released_at"],
        "compute_release_reason": "terminal_source_task_settled",
    }
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["followup_dispatched"] is True
    assert receipt["source_task_settlement"] == {
        "state": "settled",
        "task_id": "task-a",
        "reason": "terminal_source_task_settled",
        "source_task_status": "failed",
        "settled_at": receipt["source_task_settlement"]["settled_at"],
    }


def test_followup_ack_accepts_source_task_already_released_to_pending(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A prior release must make acknowledgement idempotent."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    original_task = {"id": "task-a", "status": "pending", "priority": 2}
    pool_path.write_text(json.dumps([original_task]), encoding="utf-8")
    receipt_path = queue_dir / "job-a.json"
    receipt_path.write_text(
        json.dumps(
            {
                "id": "job-a",
                "status": "failed",
                "source_task_id": "task-a",
                "followup_dispatched": False,
            }
        ),
        encoding="utf-8",
    )

    rc = compute_queue.mark_followup_dispatched(
        SimpleNamespace(id="job-a", next_task_id="task-a-followup")
    )

    assert rc == 0
    assert json.loads(pool_path.read_text(encoding="utf-8")) == [original_task]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["source_task_settlement"] == {
        "state": "settled",
        "task_id": "task-a",
        "reason": "source_task_already_released",
        "settled_at": receipt["source_task_settlement"]["settled_at"],
    }


def test_followup_ack_preserves_non_compute_terminal_block_reason(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Clearing a stale compute binding must not erase a business blocker."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text(
        json.dumps(
            [
                {
                    "id": "task-a",
                    "status": "blocked",
                    "compute_job_id": "job-a",
                    "blocked_reason": "awaiting_prerequisite_fix",
                    "blocked_until": "2026-08-01T00:00:00+00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    (queue_dir / "job-a.json").write_text(
        json.dumps(
            {
                "id": "job-a",
                "status": "completed",
                "source_task_id": "task-a",
                "followup_dispatched": False,
            }
        ),
        encoding="utf-8",
    )

    rc = compute_queue.mark_followup_dispatched(
        SimpleNamespace(id="job-a", next_task_id="task-a-followup")
    )

    assert rc == 0
    task = json.loads(pool_path.read_text(encoding="utf-8"))[0]
    assert task["status"] == "blocked"
    assert task["blocked_reason"] == "awaiting_prerequisite_fix"
    assert task["blocked_until"] == "2026-08-01T00:00:00+00:00"
    assert "compute_job_id" not in task


def test_followup_still_refuses_missing_source_task(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """A missing canonical source is not evidence of prior settlement."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text("[]", encoding="utf-8")
    receipt_path = queue_dir / "job-a.json"
    original = {
        "id": "job-a",
        "status": "completed",
        "source_task_id": "task-missing",
        "followup_dispatched": False,
    }
    receipt_path.write_text(json.dumps(original), encoding="utf-8")

    rc = compute_queue.mark_followup_dispatched(
        SimpleNamespace(id="job-a", next_task_id="task-a-followup")
    )

    assert rc == 2
    assert "source task settlement failed" in capsys.readouterr().err
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == original


def test_reconcile_bindings_repairs_ownership_without_claiming_payload(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """Operators can repair lifecycle state before authorizing execution."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text(
        json.dumps(
            [
                {
                    "id": "task-a",
                    "status": "awaiting_agent_job",
                    "compute_job_id": "job-old",
                    "blocked_reason": "external_compute_receipt_pending_collection",
                }
            ]
        ),
        encoding="utf-8",
    )
    (queue_dir / "job-old.json").write_text(
        json.dumps(
            {
                "id": "job-old",
                "status": "completed",
                "source_task_id": "task-a",
                "followup_dispatched": True,
            }
        ),
        encoding="utf-8",
    )
    successor_path = queue_dir / "job-new.json"
    successor_path.write_text(
        json.dumps(
            {
                "id": "job-new",
                "status": "queued",
                "title": "successor",
                "queued_at": "2026-07-28T01:00:00Z",
                "source_task_id": "task-a",
            }
        ),
        encoding="utf-8",
    )

    rc = compute_queue.reconcile_bindings(SimpleNamespace(json=True))

    report = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert report == {
        "queued_before": 1,
        "ready": 1,
        "sleeping": 0,
        "blocked": 0,
        "terminalized": 0,
        "blocked_reasons": {},
    }
    assert json.loads(successor_path.read_text(encoding="utf-8"))["status"] == "queued"


def test_parallel_source_task_fences_do_not_conflict_across_tasks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """D6 parallel slots may fence distinct tasks at the same time."""
    _queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    jobs = [
        {"id": f"job-{index}", "source_task_id": f"task-{index}"}
        for index in range(6)
    ]
    pool_path.write_text(
        json.dumps(
            [
                {
                    "id": job["source_task_id"],
                    "status": "awaiting_agent_job",
                    "compute_job_id": job["id"],
                    "blocked_reason": "external_compute_job_active",
                }
                for job in jobs
            ]
        ),
        encoding="utf-8",
    )
    all_active = threading.Barrier(len(jobs), timeout=5)

    def hold_distinct_fence(job: dict[str, str]) -> bool:
        with compute_queue._source_task_execution_fence(job) as valid:
            assert valid is True
            all_active.wait()
            return valid

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        assert list(pool.map(hold_distinct_fence, jobs)) == [True] * len(jobs)

    tasks = json.loads(pool_path.read_text(encoding="utf-8"))
    assert {task["blocked_reason"] for task in tasks} == {
        "external_compute_receipt_pending_collection"
    }


def test_source_task_fence_takes_queue_lock_before_task_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The canonical lock order prevents an observable metadata-less fence."""
    _queue_dir, _pool_path = _patch_state(tmp_path, monkeypatch)
    tasks = [
        {
            "id": "task-a",
            "status": "awaiting_agent_job",
            "compute_job_id": "job-a",
            "blocked_reason": "external_compute_job_active",
        }
    ]
    queue_lock_held = False
    events: list[str] = []

    @contextmanager
    def observed_queue_lock(_tpc):
        nonlocal queue_lock_held
        assert queue_lock_held is False
        queue_lock_held = True
        events.append("queue_enter")
        try:
            yield None, tasks
        finally:
            events.append("queue_exit")
            queue_lock_held = False

    real_flock = compute_queue.fcntl.flock

    def observed_flock(fd: int, operation: int) -> None:
        if operation & compute_queue.fcntl.LOCK_EX:
            events.append("task_fence_ex")
            assert queue_lock_held is True
        real_flock(fd, operation)

    monkeypatch.setattr(compute_queue, "_task_pool_locked_load", observed_queue_lock)
    monkeypatch.setattr(compute_queue.fcntl, "flock", observed_flock)

    with compute_queue._source_task_execution_fence(
        {"id": "job-a", "source_task_id": "task-a"}
    ) as valid:
        assert valid is True

    assert events[:3] == ["queue_enter", "task_fence_ex", "queue_exit"]


def test_readiness_scan_and_worker_settlement_share_process_local_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Main-thread scans cannot overlap worker-thread task-pool rewrites."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text(
        json.dumps(
            [
                {
                    "id": "task-running",
                    "status": "awaiting_agent_job",
                    "compute_job_id": "job-running",
                    "blocked_reason": "external_compute_job_active",
                },
                {
                    "id": "task-queued",
                    "status": "awaiting_agent_job",
                    "compute_job_id": "job-queued",
                    "blocked_reason": "external_compute_job_active",
                },
            ]
        ),
        encoding="utf-8",
    )
    queued_path = queue_dir / "job-queued.json"
    queued_path.write_text(
        json.dumps(
            {
                "id": "job-queued",
                "status": "queued",
                "title": "queued",
                "queued_at": "2026-07-28T01:00:00Z",
                "source_task_id": "task-queued",
                "source_task_link": {"state": "linked"},
            }
        ),
        encoding="utf-8",
    )
    original_load = task_pool._locked_load
    original_readonly = task_pool._locked_readonly
    counter_lock = threading.Lock()
    active_underlying = 0
    max_active = 0
    fence_active = threading.Event()
    release_fence = threading.Event()

    @contextmanager
    def observed_load():
        nonlocal active_underlying, max_active
        with original_load() as locked:
            with counter_lock:
                active_underlying += 1
                max_active = max(max_active, active_underlying)
            try:
                yield locked
            finally:
                with counter_lock:
                    active_underlying -= 1

    @contextmanager
    def observed_readonly():
        nonlocal active_underlying, max_active
        with original_readonly() as tasks:
            with counter_lock:
                active_underlying += 1
                max_active = max(max_active, active_underlying)
            release_fence.set()
            time.sleep(0.05)
            try:
                yield tasks
            finally:
                with counter_lock:
                    active_underlying -= 1

    monkeypatch.setattr(task_pool, "_locked_load", observed_load)
    monkeypatch.setattr(task_pool, "_locked_readonly", observed_readonly)

    def finish_worker_fence() -> None:
        job = {"id": "job-running", "source_task_id": "task-running"}
        with compute_queue._source_task_execution_fence(job) as valid:
            assert valid is True
            fence_active.set()
            assert release_fence.wait(timeout=2)

    worker = threading.Thread(target=finish_worker_fence)
    worker.start()
    assert fence_active.wait(timeout=2)
    scan = compute_queue._scan_queue_readiness("scan-vs-settlement")
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert [path for _priority, _queued_at, path in scan.ready] == [queued_path]
    assert max_active == 1
    tasks = json.loads(pool_path.read_text(encoding="utf-8"))
    running = next(task for task in tasks if task["id"] == "task-running")
    assert running["blocked_reason"] == "external_compute_receipt_pending_collection"


def _cancelled_receipt(queue_dir: Path, job_id: str, task_id: str) -> Path:
    path = queue_dir / f"{job_id}.json"
    path.write_text(
        json.dumps(
            {
                "id": job_id,
                "status": "cancelled",
                "source_task_id": task_id,
                "cancel_reason": "staged script not merged yet",
                "cancelled_at": "2026-07-21T06:56:05Z",
                "followup_dispatched": True,
                "source_task_settlement": None,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_cancelled_job_settles_when_source_task_already_terminal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A source task that finished elsewhere owes this cancelled job nothing.

    Regression for `k1380-stage1-forecasts-a`, which re-warned on every
    compute-worker tick for 13 days because a `succeeded` source task was read
    as a binding mismatch rather than as nothing-left-to-release.
    """
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text(
        json.dumps([{"id": "task-done", "status": "succeeded"}]),
        encoding="utf-8",
    )
    job_path = _cancelled_receipt(queue_dir, "job-cancelled", "task-done")
    warnings: list[tuple] = []
    monkeypatch.setattr(
        compute_queue,
        "warn",
        lambda *a, **k: warnings.append((a, k)),
    )

    compute_queue._scan_queue_readiness("test-terminal-source-settlement")

    settlement = json.loads(job_path.read_text(encoding="utf-8"))[
        "source_task_settlement"
    ]
    assert settlement["state"] == "not_required"
    assert settlement["reason"] == "source_task_unbound:succeeded"
    assert warnings == []

    # Second scan must be a no-op: the settlement is what stops the loop.
    compute_queue._scan_queue_readiness("test-terminal-source-settlement-again")
    assert warnings == []
    assert (
        json.loads(job_path.read_text(encoding="utf-8"))["source_task_settlement"]
        == settlement
    )


def test_cancelled_job_settles_when_source_task_missing_from_pool(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An archived source task must not take the readiness scan down with it."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text("[]", encoding="utf-8")
    job_path = _cancelled_receipt(queue_dir, "job-orphaned", "task-archived")
    warnings: list[tuple] = []
    monkeypatch.setattr(
        compute_queue,
        "warn",
        lambda *a, **k: warnings.append((a, k)),
    )

    compute_queue._scan_queue_readiness("test-missing-source-settlement")

    settlement = json.loads(job_path.read_text(encoding="utf-8"))[
        "source_task_settlement"
    ]
    assert settlement["state"] == "not_required"
    assert settlement["reason"] == "source_task_absent"
    # The unresolvable id is still reported once, but only once.
    assert len(warnings) == 1
    compute_queue._scan_queue_readiness("test-missing-source-settlement-again")
    assert len(warnings) == 1


def test_cancelled_job_releases_still_bound_source_task(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The ordinary case still hands the task back to the pool."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text(
        json.dumps(
            [
                {
                    "id": "task-bound",
                    "status": "awaiting_agent_job",
                    "compute_job_id": "job-bound",
                    "blocked_reason": "external_compute_job_active",
                }
            ]
        ),
        encoding="utf-8",
    )
    job_path = _cancelled_receipt(queue_dir, "job-bound", "task-bound")

    compute_queue._scan_queue_readiness("test-bound-source-settlement")

    task = json.loads(pool_path.read_text(encoding="utf-8"))[0]
    assert task["status"] == "pending"
    assert "compute_job_id" not in task
    assert "blocked_reason" not in task
    settlement = json.loads(job_path.read_text(encoding="utf-8"))[
        "source_task_settlement"
    ]
    assert settlement["state"] == "settled"
    assert "reason" not in settlement


def test_cancelled_job_still_warns_on_genuine_binding_ambiguity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Bound but un-unwindable is the one case a human still has to look at."""
    queue_dir, pool_path = _patch_state(tmp_path, monkeypatch)
    pool_path.write_text(
        json.dumps(
            [
                {
                    "id": "task-weird",
                    "status": "in_progress",
                    "compute_job_id": "job-weird",
                    "blocked_reason": "external_compute_job_active",
                }
            ]
        ),
        encoding="utf-8",
    )
    job_path = _cancelled_receipt(queue_dir, "job-weird", "task-weird")
    warnings: list[tuple] = []
    monkeypatch.setattr(
        compute_queue,
        "warn",
        lambda *a, **k: warnings.append((a, k)),
    )

    compute_queue._scan_queue_readiness("test-ambiguous-source-settlement")

    assert len(warnings) == 1
    assert warnings[0][0][1] == "cancelled source task settlement did not match"
    assert warnings[0][1]["task_status"] == "in_progress"
    assert json.loads(job_path.read_text(encoding="utf-8"))[
        "source_task_settlement"
    ] is None
