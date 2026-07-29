"""Hand a killed fire's task-pool claims back to the queue.

Why its own module (WS-A2c, 2026-07-20): this logic was born inside `health.py`
as a private helper, but `worker.py` needs the *same* release on its own
`Popen.wait(timeout=)` path — and that path is the one that actually fires
first in practice (health.py is the belt-and-suspenders layer ~1s behind it).
Two callers meant either a cross-import between two peer modules that already
both import `state`/`alerts`, or a duplicate release path. WS-A1 is collapsing
next_tasks writers, so a duplicate was never an option.

It did not go into `identity.py`: that module is deliberately dependency-free —
pure string tokens shared by the dispatcher and its Codex failover, with no
filesystem, no logging, and no knowledge of the task pool. Importing
`task_pool_claim` from there would drag the whole next_tasks writer (and its
file lock) into every consumer of a naming convention. This module is the
opposite kind of thing: it is an *effect* on canonical state, so it gets its
own home and imports `identity` for the token vocabulary.
"""
from __future__ import annotations

import importlib
import logging
import sys
from types import ModuleType

from . import identity

LOG = logging.getLogger(__name__)


def _task_pool_claim() -> ModuleType:
    """Import `scripts/task_pool_claim.py` — the canonical next_tasks writer.

    ``scripts`` is a namespace package in the checkout and a real package in
    immutable release images, so a package import works in both environments
    without executing a mutable canonical path.  The compatibility alias keeps
    older tests/callers that cache ``task_pool_claim`` working. Loaded lazily:
    the healthy path must not pay for it, and a broken task pool must not stop
    the supervisor from booting.
    """
    cached = sys.modules.get("task_pool_claim")
    if isinstance(cached, ModuleType):
        return cached
    module = importlib.import_module("scripts.task_pool_claim")
    sys.modules["task_pool_claim"] = module
    return module


def repend_killed_job_claims(
    *, job_id: str, slot_id: int | str, source: str = "health",
) -> list[str]:
    """Hand a killed fire's task-pool claim back to the queue.

    Killing a worker used to free only the dispatch_state slot: whatever task
    the dead agent had claimed stayed `claimed`/`in_progress` until the stale
    sweep noticed hours later, so a P1 task could sit dead with no process
    behind it (refactor_plan_ops_master_2026_07 §1.2 P1 / WS-A2b, WS-A2c).

    Idempotent by construction, which is what makes it safe to call from BOTH
    `worker.py`'s own timeout path and `health.py`'s watchdog for the same
    hang: `task_pool_claim.release_owner_claims()` (scripts/task_pool_claim.py
    :579-582) only touches rows whose status is still `claimed`/`in_progress`
    AND whose `claimed_by` is one of the passed owner tokens.  A second call
    therefore matches nothing and reports an empty release.  It cannot steal a
    successor's claim either: the owner token embeds the job_id, which is
    unique per fire, so a re-dispatched task claimed by the NEXT fire carries a
    different token.

    Best-effort by construction. The kill is the safety-critical act and it has
    already happened by the time we get here; a task pool that is locked,
    corrupt or missing must therefore produce a WARNING and nothing more — it
    must never stop `killed_timeout` from landing or the hang alert from being
    sent. The stale-claim sweep stays as the backstop for exactly these cases.
    """
    if not job_id:
        LOG.warning(
            "%s: cannot re-pend task claims after kill — no job_id for slot=%s "
            "(claim tokens are slot+job scoped); leaving it to the stale sweep",
            source, slot_id,
        )
        return []
    slot_token = str(slot_id or "").strip() or "1"
    if not slot_token.startswith("slot-"):
        slot_token = f"slot-{slot_token}"
    try:
        owners = identity.task_claim_owners_for_job(slot_id=slot_token, job_id=job_id)
        result = _task_pool_claim().release_owner_claims(
            owners, reason=f"supervisor_kill_{job_id[:8]}"
        )
        # Parsing lives inside the guard too (WS-A2c): worker.py's call site has
        # no outer sibling-isolation try/except the way health.check_once does,
        # so a malformed result here must not be able to abort a kill report.
        released = [
            str(entry.get("id") or "") for entry in (result.get("released") or [])
        ]
    except Exception as exc:  # noqa: BLE001 — kill must complete regardless
        LOG.warning(
            "%s: re-pend of task claims for job_id=%s slot=%s FAILED (%s) — the "
            "kill still completed; stale-claim cleanup remains the backstop",
            source, job_id, slot_token, exc,
        )
        return []
    if released:
        LOG.warning(
            "%s: re-pended %d task(s) after killing job_id=%s slot=%s: %s",
            source, len(released), job_id, slot_token, ", ".join(released),
        )
    else:
        LOG.info(
            "%s: killed job_id=%s slot=%s held no live task-pool claim",
            source, job_id, slot_token,
        )
    return released
