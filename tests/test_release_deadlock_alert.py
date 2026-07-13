"""Release gate-deadlock must be visible BEFORE the reader-facing gap, not after.

2026-07-13 (boss msg 660: 「不是補救，是立刻從底層徹底處理」). The release cron fired at
07:00/08:00/09:00 UTC, exited 0 every time, and released nothing — every draft in the
pool was blocked by the narrative-cluster gate. Nothing said a word for 6.5 hours,
because "the machinery fired" and "an article went out" were never the same event, and
the only condition watching was the lagging one (it waits 2x the release interval).

These tests pin the leading indicator: due + drafts present + eligible == 0 is provably
a dead next fire, and it must surface at CRITICAL the moment it is true.
"""

from __future__ import annotations

import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from volpred.ops import alerts


def _preview(*, due_now: bool, draft: int, eligible: int, blocked: list[str] | None = None) -> dict:
    return {
        "due_now": due_now,
        "pool_counts": {
            "draft": draft,
            "scheduled": 0,
            "eligible_before_dedup": draft,
            "dedup_flagged": max(draft - eligible, 0),
            "eligible": eligible,
        },
        "narrative_cluster_pressure": {
            "clusters": ["taiwan", "vix"],
            "blocked_clusters": blocked or [],
        },
        "next_candidates": [],
    }


@pytest.fixture
def healthy_machinery(tmp_path, monkeypatch):
    """A release cron that is firing perfectly happily — the 2026-07-13 situation.

    The point of the incident is that nothing was broken *upstream*: settings are
    fresh, the log is fresh, the lagging starvation check is nowhere near tripping.
    Only the gate outcome is dead.
    """
    storage = tmp_path / "storage"
    (storage / "ops").mkdir(parents=True)
    (storage / "logs" / "cron").mkdir(parents=True)
    now = datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc)
    fresh = (now - timedelta(minutes=5)).isoformat()
    (storage / ".release_settings.json").write_text(
        '{"interval_minutes": 240, "last_released_at": "%s", "updated_at": "%s"}' % (fresh, fresh),
        encoding="utf-8",
    )
    return str(storage), now


def test_deadlock_fires_critical_when_pool_has_drafts_but_none_eligible(healthy_machinery, monkeypatch):
    storage, now = healthy_machinery
    monkeypatch.setattr(
        alerts,
        "_release_pool_preview_for_alert",
        lambda _sd: _preview(due_now=True, draft=5, eligible=0, blocked=["taiwan"]),
    )
    result = alerts._parse_release_pool_state(storage, now)

    assert result["breached"] is True
    assert result["level"] == "critical"
    assert result["id"] == "release_pool_deadlock"
    # The boss must be able to see WHICH gate is holding it shut, and that the
    # system already acted — not be handed a to-do list.
    assert "taiwan" in result["body"]
    assert "系統已自動執行" in result["body"]
    assert result["details"]["blocked_clusters"] == ["taiwan"]


def test_empty_pool_is_not_a_deadlock(healthy_machinery, monkeypatch):
    """0 drafts is a refill problem, not a gate deadlock. Naming it deadlock would
    send the remediator hunting for a gate to unblock that does not exist."""
    storage, now = healthy_machinery
    monkeypatch.setattr(
        alerts,
        "_release_pool_preview_for_alert",
        lambda _sd: _preview(due_now=True, draft=0, eligible=0),
    )
    result = alerts._parse_release_pool_state(storage, now)
    assert result["id"] != "release_pool_deadlock"


def test_not_due_is_not_a_deadlock(healthy_machinery, monkeypatch):
    """Between releases, eligible==0 is normal and says nothing about the gate."""
    storage, now = healthy_machinery
    monkeypatch.setattr(
        alerts,
        "_release_pool_preview_for_alert",
        lambda _sd: _preview(due_now=False, draft=5, eligible=0, blocked=["taiwan"]),
    )
    result = alerts._parse_release_pool_state(storage, now)
    assert result["breached"] is False


def test_releasable_pool_does_not_breach(healthy_machinery, monkeypatch):
    storage, now = healthy_machinery
    monkeypatch.setattr(
        alerts,
        "_release_pool_preview_for_alert",
        lambda _sd: _preview(due_now=True, draft=6, eligible=4),
    )
    result = alerts._parse_release_pool_state(storage, now)
    assert result["breached"] is False


def test_body_flags_a_remediation_that_never_ran(healthy_machinery, monkeypatch):
    """A deadlock alert whose remediation silently no-opped is worse than useless —
    it reads as 'handled'. With no receipt on disk, the body must say so out loud."""
    storage, now = healthy_machinery
    monkeypatch.setattr(
        alerts,
        "_release_pool_preview_for_alert",
        lambda _sd: _preview(due_now=True, draft=5, eligible=0, blocked=["taiwan"]),
    )
    result = alerts._parse_release_pool_state(storage, now)
    assert "沒有執行" in result["body"]
    assert result["details"]["remediation"]["attempted"] is False


def test_stale_receipt_is_not_credited_to_this_deadlock(healthy_machinery, monkeypatch):
    """Yesterday's fix must not be reported as today's. Otherwise a permanently
    deadlocked pool looks permanently remediated."""
    storage, now = healthy_machinery
    (pathlib.Path(storage) / "ops" / "release_deadlock_remediation.json").write_text(
        '{"attempted": true, "ran_at": "%s", "task_id": "old_task"}'
        % (now - timedelta(hours=9)).isoformat(),
        encoding="utf-8",
    )
    receipt = alerts._read_release_deadlock_receipt(storage, now)
    assert receipt["attempted"] is False
    assert receipt["reason"] == "receipt_stale"
