"""A release-blocking fix task must be reachable, not merely filed.

2026-07-19 R3 (老闆 23:36「全部都要合併跑」): three
`platform_ops_release_audit_fix_*` tasks sat pending for 28 hours while the
articles they were meant to unblock stayed invisible to readers. The instinct is
to suspect the dispatcher — a status filter, slot contention, an A0 lane that
could not see them. It was none of those. The arithmetic was simply this:

    old task priority          P3
    P3 starvation threshold    72h   (continue_task_dispatch.STARVATION_HOURS)
    queue ahead of it          13 P1 + 22 P2
    dispatcher throughput      ~1 task/fire

At P3 a task is unreachable by ordinary priority ordering and does not qualify
for the starvation breaker until it is three days old. 28h of waiting was the
system working exactly as configured. The defect was the priority, not the queue.

That priority was fixed the same evening (`_release_audit_task_priority`: open at
P2, escalate to P1 once skips reach the threshold). This test exists so nobody
re-adds a *second*, parallel age-based escalation for the same concern: the two
existing mechanisms — skip-count escalation and the priority-keyed starvation
ladder — already compose into a bound. It pins that composition.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "src"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import continue_task_dispatch as dispatch  # noqa: E402
from volpred.ops import content  # noqa: E402


def _threshold(skips: int) -> float:
    """Hours a fix task filed at `skips` may age before dispatch locks onto it."""
    return dispatch.STARVATION_HOURS[content._release_audit_task_priority(skips)]


def test_a_fresh_blocker_is_reachable_within_a_day():
    """P2, not the old P3 — 24h, not 72h."""
    assert content._release_audit_task_priority(0) == 2
    assert _threshold(0) == 24.0


def test_a_persistent_blocker_is_reachable_within_six_hours():
    assert content._release_audit_task_priority(20) == 1
    assert _threshold(20) == 6.0


def test_the_28_hour_wait_is_no_longer_reachable_at_any_skip_count():
    """The observed failure, stated as the invariant it violated."""
    assert max(_threshold(s) for s in range(0, 40)) <= 24.0


def test_escalation_only_tightens_the_bound():
    """More skips must never buy a *longer* leash."""
    bounds = [_threshold(s) for s in range(0, 40)]
    assert bounds == sorted(bounds, reverse=True)


def test_the_old_hardcoded_priority_would_still_fail_this():
    """Kept as the counter-example: this is what 28h of silence looked like."""
    assert dispatch.STARVATION_HOURS[3] == 72.0
