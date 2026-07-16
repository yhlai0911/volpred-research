"""PHASE-Z must not re-report machine-written state as「沒人收」(boss msg 806, 2026-07-16).

The alert repeated every fire — `storage/work_log.json` and
`storage/next_tasks_archive/2026-07.jsonl` had each been named for 35 consecutive
fires. Both are written by machines with no commit step of their own, so no author
was ever going to come back for them, and the streak counter escalated a permanent
condition to `critical` hour after hour. Repeated un-actionable criticals are how a
real leak gets ignored, which is the actual cost.

The fix is the same namespace test the module already uses (_is_machine_state), so
these pins guard the two boundaries that make it safe rather than the list itself:

  1. machine state gets adopted; agent-authored output stays foreign (adopting THAT
     blindly caused incidents #1-#3 — see docs/error_log.md 2026-07-10);
  2. the parse gate covers `.jsonl`, because the queue archive is appended to (not
     replaced by rename), so a killed writer leaves a truncated final line — the
     exact way a truncated `next_tasks.json` once became "valid history".
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.dispatch_supervisor.phase_z import _classify_machine_churn, _is_machine_state


# ── boundary 1: who owns what ────────────────────────────────────────────────

def test_machine_written_runtime_state_is_owned_not_reported() -> None:
    """The paths boss msg 806 named — a machine writes them, PHASE-Z owns them."""
    assert _is_machine_state("storage/work_log.json")
    assert _is_machine_state("storage/next_tasks_archive/2026-07.jsonl")
    # a new month's archive appears without anyone editing a list
    assert _is_machine_state("storage/next_tasks_archive/2027-01.jsonl")


def test_agent_authored_output_stays_foreign() -> None:
    """Real orphans must still be caught — the alert has to keep meaning something.

    `experiments/k1695/review_*` was in the same alert and is NOT machine state: an
    agent wrote it and is expected to commit it with a message. So is
    paper_pipeline_status.json, despite being named in the task — it is the papers'
    decision-of-record, edited by whoever advances a stage and committed with a real
    message (see its git log). Only paper_pipeline_check.py reads it; no scheduled
    writer produces it.
    """
    for rel in (
        "experiments/k1695/review_summary.md",
        "experiments/k1695/review_findings.json",
        "storage/paper_pipeline_status.json",
        "scripts/dispatch_supervisor/phase_z.py",
        "paper/vt-crowding-abm/body_v6.tex",
        "storage/memory/knowledge.json",
    ):
        assert not _is_machine_state(rel), rel


# ── boundary 2: adoption is gated on the content parsing ─────────────────────

def _churn(tmp_path: Path, rel: str, body: str) -> tuple[list, list, list]:
    dest = tmp_path / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body, encoding="utf-8")
    return _classify_machine_churn(tmp_path, [rel])


def test_intact_archive_is_committable(tmp_path: Path) -> None:
    body = "".join(json.dumps({"id": f"t{i}"}) + "\n" for i in range(3))
    committable, deferred, corrupt = _churn(tmp_path, "storage/next_tasks_archive/2026-07.jsonl", body)
    assert committable == ["storage/next_tasks_archive/2026-07.jsonl"]
    assert not deferred and not corrupt


def test_truncated_archive_line_escalates_instead_of_entering_history(tmp_path: Path) -> None:
    """A writer killed mid-append leaves half a line; committing it is the incident."""
    body = json.dumps({"id": "t0"}) + "\n" + '{"id": "t1", "sta'
    committable, deferred, corrupt = _churn(tmp_path, "storage/next_tasks_archive/2026-07.jsonl", body)
    assert corrupt == ["storage/next_tasks_archive/2026-07.jsonl"]
    assert not committable


def test_blank_lines_in_archive_are_not_corruption(tmp_path: Path) -> None:
    body = json.dumps({"id": "t0"}) + "\n\n" + json.dumps({"id": "t1"}) + "\n"
    committable, _, corrupt = _churn(tmp_path, "storage/next_tasks_archive/2026-07.jsonl", body)
    assert committable and not corrupt


def test_corrupt_work_log_is_refused(tmp_path: Path) -> None:
    committable, _, corrupt = _churn(tmp_path, "storage/work_log.json", '[{"task": "trunc')
    assert corrupt == ["storage/work_log.json"]
    assert not committable
