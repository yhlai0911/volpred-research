"""Regression tests for the paper_adjudication_gap alert condition.

Incident (2026-07-14, K1686): the gating task `k1686_fix_ambient_sign_spec`
reached `succeeded` on 2026-07-12 19:19 with a gate-PASSING result that
reverses a retracted FRL-reframe ruling — and sat unadjudicated for ~43h while
`storage/paper_pipeline_status.json` still said "Blocked on next_tasks
k1686_fix_ambient_sign_spec" and a hand-written handoff copied the RETRACTED
ruling. These tests reproduce that exact state and assert the detector fires;
any regression that lets a completed gating task hide behind a stale blocker
must fail here.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from volpred.ops.alerts import (
    PAPER_ADJUDICATION_GRACE_HOURS,
    _parse_paper_adjudication_gap_state,
)

NOW = datetime(2026, 7, 14, 6, 0, 0, tzinfo=timezone.utc)


def _write_state(
    tmp_path: Path,
    *,
    blocker: str,
    task_status: str = "succeeded",
    completed_at: str | None = None,
    include_pipeline: bool = True,
    blocked_on_tasks: list[str] | None = None,
) -> str:
    storage = tmp_path / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    if include_pipeline:
        paper: dict = {
            "paper": "volatility-absorption",
            "stage": "revision",
            "blocker": blocker,
        }
        if blocked_on_tasks is not None:
            paper["blocked_on_tasks"] = blocked_on_tasks
        (storage / "paper_pipeline_status.json").write_text(
            json.dumps({"papers": [paper]})
        )
    task = {
        "id": "k1686_fix_ambient_sign_spec",
        "status": task_status,
        "priority": 1,
    }
    if completed_at is not None:
        task["completed_at"] = completed_at
    (storage / "next_tasks.json").write_text(json.dumps([task]))
    return str(storage)


def test_incident_regression_stale_blocker_on_succeeded_task_breaches(tmp_path):
    """The exact 2026-07-14 state: task succeeded ~43h ago, blocker still references it."""
    completed = (NOW - timedelta(hours=43)).isoformat()
    storage = _write_state(
        tmp_path,
        blocker=(
            "K1686 gating + Codex primary-path review FAIL ... "
            "Blocked on next_tasks k1686_fix_ambient_sign_spec (ambient x sign spec)."
        ),
        completed_at=completed,
    )
    state = _parse_paper_adjudication_gap_state(storage, NOW)
    assert state["breached"] is True
    assert state["level"] == "warn"
    gaps = state["details"]["gaps"]
    assert len(gaps) == 1
    assert gaps[0]["paper"] == "volatility-absorption"
    assert gaps[0]["task_id"] == "k1686_fix_ambient_sign_spec"
    assert gaps[0]["age_hours"] == pytest.approx(43, abs=0.2)


def test_adjudicated_blocker_no_longer_references_task_clears(tmp_path):
    """Post-adjudication state: blocker rewritten without the task id -> no breach."""
    completed = (NOW - timedelta(hours=43)).isoformat()
    storage = _write_state(
        tmp_path,
        blocker=(
            "P0 COMPLETE 2026-07-14: K1686 R2 adjudicated; absorption survives gate; "
            "remaining: P1-2 prior-art + multi-round review."
        ),
        completed_at=completed,
    )
    state = _parse_paper_adjudication_gap_state(storage, NOW)
    assert state["breached"] is False


def test_within_grace_window_does_not_breach(tmp_path):
    """A task completed an hour ago is still inside the same working session."""
    completed = (NOW - timedelta(hours=1)).isoformat()
    storage = _write_state(
        tmp_path,
        blocker="Blocked on next_tasks k1686_fix_ambient_sign_spec.",
        completed_at=completed,
    )
    state = _parse_paper_adjudication_gap_state(storage, NOW)
    assert state["breached"] is False
    assert PAPER_ADJUDICATION_GRACE_HOURS > 1


def test_blocked_on_failed_task_also_breaches(tmp_path):
    """A blocker referencing a FAILED terminal task equally needs a ruling (re-dispatch or re-plan)."""
    completed = (NOW - timedelta(hours=30)).isoformat()
    storage = _write_state(
        tmp_path,
        blocker="Blocked on next_tasks k1686_fix_ambient_sign_spec.",
        task_status="failed",
        completed_at=completed,
    )
    state = _parse_paper_adjudication_gap_state(storage, NOW)
    assert state["breached"] is True
    assert state["details"]["gaps"][0]["task_status"] == "failed"


def test_pending_task_reference_is_a_live_dependency_not_a_gap(tmp_path):
    storage = _write_state(
        tmp_path,
        blocker="Blocked on next_tasks k1686_fix_ambient_sign_spec.",
        task_status="pending",
    )
    state = _parse_paper_adjudication_gap_state(storage, NOW)
    assert state["breached"] is False


def test_missing_completed_at_counts_as_old_enough(tmp_path):
    """A terminal task without a timestamp must not hide the gap forever."""
    storage = _write_state(
        tmp_path,
        blocker="Blocked on next_tasks k1686_fix_ambient_sign_spec.",
        completed_at=None,
    )
    state = _parse_paper_adjudication_gap_state(storage, NOW)
    assert state["breached"] is True
    assert state["details"]["gaps"][0]["age_hours"] is None


def test_partial_id_match_does_not_false_positive(tmp_path):
    """Word-boundary guard: `k1686_fix_ambient_sign_spec_v2` in the blocker must not match `..._spec`."""
    completed = (NOW - timedelta(hours=43)).isoformat()
    storage = _write_state(
        tmp_path,
        blocker="Blocked on next_tasks k1686_fix_ambient_sign_spec_v2.",
        completed_at=completed,
    )
    state = _parse_paper_adjudication_gap_state(storage, NOW)
    assert state["breached"] is False


def test_provenance_mention_is_not_a_live_dependency(tmp_path):
    """False positives from the first cut (real production texts): a blocker that cites
    the task as COMPLETED HISTORY must not breach — only forward-looking dependencies do."""
    completed = (NOW - timedelta(hours=298)).isoformat()
    for text in (
        "Fresh IJF multi-round review completed 2026-07-02 (task "
        "k1686_fix_ambient_sign_spec) with overall FAIL_DO_NOT_ADVANCE. "
        "Blocking findings: allocation table drift.",
        "Version divergence RESOLVED 2026-07-05 (hourly-19, task "
        "k1686_fix_ambient_sign_spec): canonical = main_v3.tex.",
    ):
        storage = _write_state(tmp_path, blocker=text, completed_at=completed)
        state = _parse_paper_adjudication_gap_state(storage, NOW)
        assert state["breached"] is False, text


def test_structured_blocked_on_tasks_field_is_primary_contract(tmp_path):
    """`blocked_on_tasks: [...]` declares a live dependency regardless of prose wording."""
    completed = (NOW - timedelta(hours=43)).isoformat()
    storage = _write_state(
        tmp_path,
        blocker="Review completed (see history).",
        completed_at=completed,
        blocked_on_tasks=["k1686_fix_ambient_sign_spec"],
    )
    state = _parse_paper_adjudication_gap_state(storage, NOW)
    assert state["breached"] is True
    assert state["details"]["gaps"][0]["task_id"] == "k1686_fix_ambient_sign_spec"


def test_fail_open_when_pipeline_missing(tmp_path):
    storage = _write_state(
        tmp_path,
        blocker="irrelevant",
        include_pipeline=False,
    )
    Path(storage, "paper_pipeline_status.json").unlink(missing_ok=True)
    state = _parse_paper_adjudication_gap_state(storage, NOW)
    assert state["breached"] is False
    assert state["details"].get("degraded") is True
