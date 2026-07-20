"""Pure dispatch decision pipeline — WS-H4 step 2 (single fire/skip owner).

`decide()` is the ONE place the supervisor's admission verdict lives
(docs/dispatch-decision-pipeline-design.md §3.5). `scheduler._tick_once()`
collects every input (state snapshot, capacity, cron due-ness, pending fire
request, pregate demand) and consumes the returned `Decision`; the dry-run and
real-fire paths walk the SAME `decide()` on the SAME `DecisionInput`, so their
verdicts cannot diverge by construction — the only difference left is what the
caller does with a FIRE verdict (reserve_fire + worker spawn vs a log line).

Hard constraints (§3.5, enforced by tests/test_dispatch_decision.py's source
audit): no file/subprocess I/O, no wall-clock reads (due-ness arrives
pre-computed), no randomness. Every write (`state.reserve_fire`,
`last_fire_at` stamps, request consumption) stays in the caller.

Scope note (incremental, per the approved plan): this stage owns the tick-level
fire/skip verdict. Candidate-level ranking (priority sort / starvation /
rotation / categorize in `scripts/continue_task_dispatch.py`) deliberately
stays a library-side input source — `DecisionInput.candidates` is the seam it
plugs into in the later H4 shadow phase (design §5 H4-2); the supervisor does
not consume it yet.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

ACTION_FIRE = "fire"
ACTION_SKIP = "skip"
# decide() cannot finalize a plain-cron verdict while the pregate demand signal
# is uncollected: running the pregate is I/O (a subprocess), so the caller runs
# it and re-invokes decide() with `demand` filled. Both dry-run and fire pass
# through this same two-phase protocol.
ACTION_COLLECT_DEMAND = "collect_demand"

# Modes in which the pregate subprocess runs at all. Shadow logs the would-be
# verdict but never skips (the subprocess exits 1 by construction); only
# enforce may turn demand into a skip.
PREGATE_GATED_MODES = ("shadow", "enforce")


@dataclass(frozen=True)
class DecisionInput:
    """Everything `decide()` may look at. All I/O happens in the caller.

    `fire_request` is the *peeked* out-of-band request (burst / boss email via
    `state.request_fire`); the caller consumes it atomically only after the
    admission gates pass, then re-decides if the consumed value differs.
    `capacity` already folds the quota de-rate (load_max_slots owns that);
    `quota_derated` is carried for receipt transparency, not branched on.
    """

    auth_blocked: bool
    active_slots: int
    capacity: int
    quota_derated: bool
    last_fire_known: bool          # _parse_last_fire(last_fire_at) is not None
    due: bool                      # _due_to_fire(...) verdict, pre-computed
    prev_fire: str | None          # ISO prev scheduled slot (receipt only)
    fire_request: str | None       # pending request reason, or None
    pregate_mode: str              # "off" | "shadow" | "enforce"
    demand: Mapping[str, Any] | None = None   # {"pregate_skip": bool} once collected
    candidates: tuple[Mapping[str, Any], ...] = ()  # ctd library outputs (unused yet)

    def digest(self) -> str:
        """Stable content hash for dry-run vs fire consistency comparison."""
        payload = {
            "auth_blocked": self.auth_blocked,
            "active_slots": self.active_slots,
            "capacity": self.capacity,
            "quota_derated": self.quota_derated,
            "last_fire_known": self.last_fire_known,
            "due": self.due,
            "prev_fire": self.prev_fire,
            "fire_request": self.fire_request,
            "pregate_mode": self.pregate_mode,
            "demand": dict(self.demand) if self.demand is not None else None,
            "candidates": [dict(c) for c in self.candidates],
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Decision:
    """The verdict. `fire_reason` is set only when action == "fire"."""

    action: str                    # ACTION_FIRE | ACTION_SKIP | ACTION_COLLECT_DEMAND
    reason: str                    # machine-readable why (skip reason / "due")
    fire_reason: str | None        # "cron" | "requested:<r>" | "cron+requested:<r>"
    inputs_digest: str


def _fire_reason(inp: DecisionInput) -> str | None:
    """None = nothing to fire (not due, no request)."""
    if inp.due and inp.fire_request:
        return f"cron+requested:{inp.fire_request}"
    if inp.due:
        return "cron"
    if inp.fire_request:
        return f"requested:{inp.fire_request}"
    return None


def decide(inp: DecisionInput) -> Decision:
    """Pure function: same DecisionInput → same Decision, no side effects.

    Ladder order mirrors the pre-H4 `_tick_once` exactly (auth → capacity →
    bootstrap → due/request → pregate), so the extraction changes no verdict.
    """
    digest = inp.digest()
    if inp.auth_blocked:
        return Decision(ACTION_SKIP, "auth_blocked", None, digest)
    if inp.active_slots >= inp.capacity:
        # A pending request deliberately survives a full-pool skip and is
        # consumed only after a later tick sees capacity (caller contract).
        return Decision(ACTION_SKIP, "slots_full", None, digest)
    if not inp.last_fire_known:
        # Unknown is NOT due (2026-07-10 off-slot duplicate-fire fix). The
        # caller bootstraps the stamp; the next real slot fires normally.
        return Decision(ACTION_SKIP, "bootstrap_last_fire_at", None, digest)
    fire_reason = _fire_reason(inp)
    if fire_reason is None:
        return Decision(ACTION_SKIP, "not_due", None, digest)
    # Pregate gates ONLY plain cron fires — any requested component bypasses it
    # (the boss asked for it). Demand is an input, not an I/O call: when it has
    # not been collected yet the verdict is "collect it and ask me again".
    if fire_reason == "cron" and inp.pregate_mode in PREGATE_GATED_MODES:
        if inp.demand is None:
            return Decision(ACTION_COLLECT_DEMAND, "pregate_demand_required", fire_reason, digest)
        if inp.demand.get("pregate_skip"):  # only reachable in enforce mode
            return Decision(ACTION_SKIP, "pregate_skip", None, digest)
    return Decision(ACTION_FIRE, "due", fire_reason, digest)
