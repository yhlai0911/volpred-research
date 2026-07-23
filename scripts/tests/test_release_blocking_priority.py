"""Release-blocking work must not queue behind hour-long compute.

2026-07-19 (boss 20:14「為什麼文章沒有照排程釋出」, then Telegram「拉成同一批次
一次完成修復」): two finished general drafts — mile_21e45133 and mile_47c4bc3e —
each skipped 20 release cycles. Two independent defects held them there, and both
were invisible from the outside:

  1. the compute queue was pure FIFO, so a few-minute lazypack render (the last
     thing between a finished draft and a reader) waited out 60-90 minute GARCH
     and agent jobs that happened to arrive first;
  2. the release gate *assumed* a render job existed and printed
     `lazypack-<id>` as the thing to go inspect. For those two articles no job
     had ever been queued, so the instruction pointed at a file that does not
     exist — a gate that reports a state it never checked spends human
     attention on a dead end.

These tests pin both: priority beats arrival order, and the gate says only what
it actually looked up.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "src"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import compute_queue as cq  # noqa: E402
from volpred.ops import content  # noqa: E402


def _job(job_id: str, queued_at: str, **extra) -> dict:
    job = {"id": job_id, "status": "queued", "queued_at": queued_at}
    job.update(extra)
    return job


# ----------------------------------------------------------------- priority --

def test_lazypack_job_outranks_compute_by_default():
    """No caller has to remember to ask: the id says it blocks a reader."""
    assert cq._default_queue_priority("lazypack-mile_47c4bc3e") == cq.RELEASE_BLOCKING_PRIORITY
    assert cq._default_queue_priority("compute-garch-multistart-123") == cq.DEFAULT_QUEUE_PRIORITY


def test_explicit_priority_overrides_the_id_derived_default():
    assert cq._scheduling_priority(_job("lazypack-x", "", queue_priority=9)) == 9
    assert cq._scheduling_priority(_job("compute-x", "", queue_priority=0)) == 0


def test_priority_is_read_from_the_id_for_jobs_queued_before_the_field_existed():
    """Backfilling every queue file would only have to be redone by the next
    stale code path that enqueues without the field."""
    assert cq._scheduling_priority(_job("lazypack-mile_47c4bc3e", "2026-07-19T14:23:02Z")) == 1


def test_a_p1_job_is_not_stuck_behind_p2_work_that_merely_arrived_first():
    """The originally reported inversion, as the worker sorts it.

    assign_98a32740 (P1, K1730 remediation, queued 06:18Z) sat behind two P2
    agent jobs queued 04:44Z and waited ~3h on a single-slot serial worker.
    Nobody passed --queue-priority, so all three collapsed onto
    DEFAULT_QUEUE_PRIORITY and the sort fell back to the FIFO it replaced.
    """
    p2_early_a = _job("agent-brief_k1623_rev2", "2026-07-19T04:44:00Z",
                      claude_followup={"priority": 2})
    p2_early_b = _job("agent-brief_k1698_rev2", "2026-07-19T04:44:30Z",
                      claude_followup={"priority": 2})
    p1_late = _job("agent-assign_98a32740", "2026-07-19T06:18:00Z",
                   claude_followup={"priority": 1})

    order = sorted(
        (cq._scheduling_priority(j), j["queued_at"], j["id"])
        for j in (p2_early_a, p2_early_b, p1_late)
    )
    assert [row[2] for row in order] == [
        "agent-assign_98a32740",
        "agent-brief_k1623_rev2",
        "agent-brief_k1698_rev2",
    ], "the P1 job must run first, and the P2 pair must keep arrival order"


def test_a_release_blocking_render_keeps_its_floor_under_a_low_priority_followup():
    """Inheriting followup urgency must not be able to demote a reader-blocking render."""
    render = _job("lazypack-mile_47c4bc3e", "2026-07-19T14:23:02Z",
                  claude_followup={"priority": 4})
    assert cq._scheduling_priority(render) == cq.RELEASE_BLOCKING_PRIORITY


def test_a_job_without_a_followup_still_falls_back_to_the_id_derived_default():
    assert cq._scheduling_priority(_job("compute-x", "")) == cq.DEFAULT_QUEUE_PRIORITY
    assert cq._scheduling_priority(_job("compute-x", "", claude_followup=None)) == (
        cq.DEFAULT_QUEUE_PRIORITY
    )


def test_a_render_queued_last_still_runs_before_an_hour_long_job_queued_first():
    """The exact ordering that starved the two drafts, as the worker sorts it."""
    heavy = _job("compute-garch-pooled-mle", "2026-07-19T10:00:00Z")
    agent = _job("agent-k1730-remediation", "2026-07-19T11:00:00Z")
    render = _job("lazypack-mile_47c4bc3e", "2026-07-19T14:23:02Z")

    order = sorted(
        (cq._scheduling_priority(j), j["queued_at"], j["id"]) for j in (heavy, agent, render)
    )
    assert [row[2] for row in order][0] == "lazypack-mile_47c4bc3e"
    # ...and within one priority, arrival order still decides.
    assert [row[2] for row in order][1:] == ["compute-garch-pooled-mle", "agent-k1730-remediation"]


def test_enqueue_records_the_priority_it_scheduled_with(tmp_path, monkeypatch):
    monkeypatch.setattr(cq, "QUEUE_DIR", tmp_path / "queue")
    monkeypatch.setattr(cq, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(cq, "ensure_dirs", lambda: (tmp_path / "queue").mkdir(parents=True, exist_ok=True))

    args = argparse.Namespace(
        id="lazypack-mile_test", title="t", script="s.py", interpreter="uv run python",
        script_args=[], env=None, result_artifact=None, output_paths=None,
        followup_brief=None, followup_task_type=None, followup_priority=None,
        queue_priority=None, timeout=600,
    )
    assert cq.enqueue(args) == 0
    written = json.loads((tmp_path / "queue" / "lazypack-mile_test.json").read_text())
    assert written["queue_priority"] == cq.RELEASE_BLOCKING_PRIORITY


# --------------------------------------------------------------- gate truth --

def test_gate_reports_missing_when_no_job_was_ever_queued(tmp_path, monkeypatch):
    """The mile_21e45133 failure mode: never name a job id you did not find."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "storage" / "ops" / "compute_queue").mkdir(parents=True)

    assert content._lazypack_job_state("mile_21e45133") == ("missing", None)
    issue = content._lazypack_gate_issue("mile_21e45133", may_enqueue=False)
    assert "NO render job was ever queued" in issue
    # The old message pointed at this id as though it existed.
    assert "compute_queue.py show lazypack-mile_21e45133" not in issue


def test_gate_reads_the_real_status_of_a_job_that_does_exist(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    queue = tmp_path / "storage" / "ops" / "compute_queue"
    queue.mkdir(parents=True)
    (queue / "lazypack-mile_47c4bc3e.json").write_text(json.dumps(
        {"id": "lazypack-mile_47c4bc3e", "status": "queued", "queued_at": "2026-07-19T14:23:02Z"}
    ))

    assert content._lazypack_job_state("mile_47c4bc3e") == ("queued", "lazypack-mile_47c4bc3e")
    assert "no action needed" in content._lazypack_gate_issue("mile_47c4bc3e", may_enqueue=False)


def test_gate_prefers_the_latest_retry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    queue = tmp_path / "storage" / "ops" / "compute_queue"
    queue.mkdir(parents=True)
    (queue / "lazypack-mile_x.json").write_text(json.dumps(
        {"id": "lazypack-mile_x", "status": "failed", "queued_at": "2026-07-19T01:00:00Z"}))
    (queue / "lazypack-mile_x-r2.json").write_text(json.dumps(
        {"id": "lazypack-mile_x-r2", "status": "running", "queued_at": "2026-07-19T02:00:00Z"}))

    assert content._lazypack_job_state("mile_x") == ("running", "lazypack-mile_x-r2")


def test_a_prefix_neighbour_does_not_answer_for_another_article(tmp_path, monkeypatch):
    """glob is a prefix match; mile_ab must not inherit mile_abcdef's job."""
    monkeypatch.chdir(tmp_path)
    queue = tmp_path / "storage" / "ops" / "compute_queue"
    queue.mkdir(parents=True)
    (queue / "lazypack-mile_abcdef.json").write_text(json.dumps(
        {"id": "lazypack-mile_abcdef", "status": "completed", "queued_at": "2026-07-19T01:00:00Z"}))

    assert content._lazypack_job_state("mile_ab") == ("missing", None)


def test_a_completed_job_with_no_section_is_reported_as_an_install_failure(tmp_path, monkeypatch):
    """Distinct from 'still rendering' — it needs a human, and says so."""
    monkeypatch.chdir(tmp_path)
    queue = tmp_path / "storage" / "ops" / "compute_queue"
    queue.mkdir(parents=True)
    (queue / "lazypack-mile_y.json").write_text(json.dumps(
        {"id": "lazypack-mile_y", "status": "completed", "queued_at": "2026-07-19T01:00:00Z"}))

    issue = content._lazypack_gate_issue("mile_y", may_enqueue=False)
    assert "COMPLETED" in issue and "not installed" in issue


def test_the_readonly_preview_never_enqueues(tmp_path, monkeypatch):
    """`record=False` is documented as side-effect free; a plan on disk must not
    turn the preview instrument into a writer."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "storage" / "ops" / "compute_queue").mkdir(parents=True)
    plan_dir = tmp_path / "storage" / "lazypack_jobs" / "mile_z"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.json").write_text("{}")

    called = []
    monkeypatch.setattr("subprocess.run", lambda *a, **k: called.append(a))

    issue = content._lazypack_gate_issue("mile_z", may_enqueue=False)
    assert called == []
    assert "never queued" in issue and "storage/lazypack_jobs/mile_z/plan.json" in issue


def test_a_plan_on_disk_with_no_job_is_queued_on_the_spot(tmp_path, monkeypatch):
    """The gate is the one code path that reliably notices. A draft that needs
    exactly one command is an omission to close, not a finding to file."""
    import subprocess as sp

    monkeypatch.chdir(tmp_path)
    (tmp_path / "storage" / "ops" / "compute_queue").mkdir(parents=True)
    plan_dir = tmp_path / "storage" / "lazypack_jobs" / "mile_q"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.json").write_text("{}")

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return sp.CompletedProcess(cmd, 0, stdout="enqueued", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    issue = content._lazypack_gate_issue("mile_q")

    assert calls and "enqueue" in calls[0] and "mile_q" in calls[0]
    assert "auto-enqueued just now" in issue


def test_a_failed_auto_enqueue_says_so_instead_of_claiming_success(tmp_path, monkeypatch):
    import subprocess as sp

    monkeypatch.chdir(tmp_path)
    (tmp_path / "storage" / "ops" / "compute_queue").mkdir(parents=True)
    plan_dir = tmp_path / "storage" / "lazypack_jobs" / "mile_r"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.json").write_text("{}")

    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kw: sp.CompletedProcess(cmd, 2, stdout="", stderr="plan invalid"),
    )
    issue = content._lazypack_gate_issue("mile_r")
    assert "FAILED" in issue and "plan invalid" in issue


@pytest.mark.parametrize("state", ["queued", "running"])
def test_pending_states_tell_the_reader_to_do_nothing(tmp_path, monkeypatch, state):
    monkeypatch.chdir(tmp_path)
    queue = tmp_path / "storage" / "ops" / "compute_queue"
    queue.mkdir(parents=True)
    (queue / "lazypack-mile_w.json").write_text(json.dumps(
        {"id": "lazypack-mile_w", "status": state, "queued_at": "2026-07-19T01:00:00Z"}))

    assert "no action needed" in content._lazypack_gate_issue("mile_w", may_enqueue=False)
