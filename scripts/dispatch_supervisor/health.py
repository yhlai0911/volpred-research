"""Health monitor — independent worker liveness check.

Runs as asyncio task inside supervisor.py main loop. Every CHECK_INTERVAL_S
seconds it stamps `state.heartbeat()` (this loop is the liveness owner — it
never blocks on a worker, unlike the scheduler tick) and then polls
`state.get_current_job()`:

  - job.age_seconds > MAX_JOB_AGE_S    → identity-verified SIGKILL pgid, record
                                          killed_timeout, alert
  - PID dead/reused but state has job  → record silent_death / silent_failure, alert

This is the belt-and-suspenders layer behind worker.py's own
`Popen.wait(timeout=)`. If worker.py itself hangs inside `wait()` (shouldn't,
but Python signal handling on macOS can surprise), health.py rescues from
outside via state-file inspection.

Codex review §10 #2 fix (2026-06-15): both branches used to trust a bare
`os.kill(pid, 0)` check. Across a 30s poll interval the OS can recycle a pid
to an unrelated process — killing/misreporting on that stale pid would hit
the WRONG process. Every identity-sensitive decision below goes through
`procutil.check_identity()`, which compares the `ps`-derived start-time
fingerprint captured at spawn and returns one of MATCH / MISMATCH / DEAD /
UNVERIFIED (Codex review fix #4, 2026-07-04 — a bare-bool version of this
check used to *degrade to "assume same process"* when no fingerprint had
been recorded, which is backwards for a kill decision; UNVERIFIED forces
this module to decide explicitly rather than kill on unverified evidence).
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
import traceback
from pathlib import Path
from types import ModuleType

from . import alerts, identity, procutil, selfreload, state

LOG = logging.getLogger(__name__)

CHECK_INTERVAL_S = 30
MAX_JOB_AGE_S = 3000  # 50min — matches worker DEFAULT_TIMEOUT_S
QUARANTINE_PHASES = {
    "kill_failed_orphan", "timeout_unverified", "orphan_unverified_not_killed",
}


def _force_kill_pgid(pgid: int) -> bool:
    """Codex review fix #5 (2026-07-04): this used to be a near-duplicate of
    worker.py's kill routine and missed a PermissionError fix applied there
    (found via a live smoke test) — now both share `procutil.kill_pgid()`.

    Returns whether the group is CONFIRMED gone (2026-07-11) — a denied killpg
    used to be indistinguishable from a successful one here."""
    return procutil.kill_pgid(pgid)


def _task_pool_claim() -> ModuleType:
    """Import `scripts/task_pool_claim.py` — the canonical next_tasks writer.

    It is a top-level script, not a package member, so it is loaded by path
    (same pattern as tests/test_task_pool_claim.py) and cached in sys.modules
    so repeated kills don't re-execute its import side effects.  Loaded lazily:
    the healthy path must not pay for it, and a broken task pool must not stop
    the supervisor from booting.
    """
    cached = sys.modules.get("task_pool_claim")
    if isinstance(cached, ModuleType):
        return cached
    module_path = Path(__file__).resolve().parents[1] / "task_pool_claim.py"
    spec = importlib.util.spec_from_file_location("task_pool_claim", module_path)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging bug
        raise ImportError(f"cannot load task_pool_claim from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["task_pool_claim"] = module
    spec.loader.exec_module(module)
    return module


def _repend_killed_job_claims(*, job_id: str, slot_id: int | str) -> list[str]:
    """Hand a killed fire's task-pool claim back to the queue.

    Killing a worker used to free only the dispatch_state slot: whatever task
    the dead agent had claimed stayed `claimed`/`in_progress` until the stale
    sweep noticed hours later, so a P1 task could sit dead with no process
    behind it (refactor_plan_ops_master_2026_07 §1.2 P1 / WS-A2b).

    Best-effort by construction. The kill is the safety-critical act and it has
    already happened by the time we get here; a task pool that is locked,
    corrupt or missing must therefore produce a WARNING and nothing more. The
    stale-claim sweep stays as the backstop for exactly these cases.
    """
    if not job_id:
        LOG.warning(
            "health: cannot re-pend task claims after kill — no job_id for slot=%s "
            "(claim tokens are slot+job scoped); leaving it to the stale sweep",
            slot_id,
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
    except Exception as exc:  # noqa: BLE001 — kill must complete regardless
        LOG.warning(
            "health: re-pend of task claims for job_id=%s slot=%s FAILED (%s) — the "
            "kill still completed; stale-claim cleanup remains the backstop",
            job_id, slot_token, exc,
        )
        return []
    released = [
        str(entry.get("id") or "") for entry in (result.get("released") or [])
    ]
    if released:
        LOG.warning(
            "health: re-pended %d task(s) after killing job_id=%s slot=%s: %s",
            len(released), job_id, slot_token, ", ".join(released),
        )
    else:
        LOG.info(
            "health: killed job_id=%s slot=%s held no live task-pool claim",
            job_id, slot_token,
        )
    return released


def _check_job(
    job: state.CurrentJob, *, state_path: Path, max_age_s: float,
) -> str | None:
    """Inspect and, if needed, CAS-close exactly one logical job."""
    job_id = job.job_id
    if not job_id:
        matches = [
            raw for raw in (state.read_state(state_path).get("current_jobs") or [])
            if raw.get("pid") == job.pid
        ]
        if len(matches) != 1:
            return None
        job_id = str(matches[0]["job_id"])
    if job.phase in QUARANTINE_PHASES:
        # The leader pid may exit before descendants/subagents in the same
        # process group. Only a *confirmed empty* PGID can drain quarantine;
        # a failed probe is deliberately sticky so PHASE-Z cannot commit while
        # an unobserved descendant may still be writing.
        survivors = procutil.pgid_members_checked(job.pgid)
        if survivors is None or survivors:
            LOG.error(
                "health: quarantined job_id=%s pgid=%d remains blocked survivors=%s",
                job_id, job.pgid, survivors if survivors is not None else "unverified",
            )
            return job.phase
        closed = state.record_completion(
            job_id=job_id, expected_attempt=job.attempt, expected_pid=job.pid,
            expected_phase=job.phase, exit_code=-1,
            outcome=f"{job.phase}_drained", final_model=job.model, path=state_path,
        )
        return "quarantine_drained" if closed is not None else None
    identity_verdict = procutil.check_identity(job.pid, job.started_wall)
    repended_tasks: list[str] = []
    if job.age_seconds > max_age_s:
        if identity_verdict == procutil.IDENTITY_MATCH:
            LOG.warning("health: worker pgid=%d age=%.0fs > %.0fs cap — force-killing", job.pgid, job.age_seconds, max_age_s)
            if _force_kill_pgid(job.pgid):
                exit_code, outcome = -9, "killed_timeout"
                # The process is confirmed gone, so nothing can still be acting
                # on its claim — release it now rather than stranding the task
                # until the stale sweep (WS-A2b).
                repended_tasks = _repend_killed_job_claims(
                    job_id=job_id, slot_id=job.slot_id,
                )
                log_tail = ("(killed by health monitor)\n\n"
                            + alerts.read_log_tail(job.log_path))
            else:
                # The signals were refused and the group is still up. Keep the
                # slot quarantined below: claiming "killed" or releasing it
                # would hide a live orphan still writing to its worktree.
                LOG.error("health: kill_pgid(%d) FAILED — orphan still alive", job.pgid)
                exit_code, outcome = -9, "kill_failed_orphan"
                log_tail = (
                    f"(hang detected but the kill was REFUSED — pid={job.pid} "
                    f"pgid={job.pgid} may still be running. Check `ps -g {job.pgid}` "
                    f"and kill by hand; this slot remains quarantined.)"
                )
        elif identity_verdict == procutil.IDENTITY_UNVERIFIED:
            # Codex review fix #4: no fingerprint was ever recorded for this
            # job — we cannot confirm this pid is still our worker and not a
            # PID-reuse collision, so we must NOT signal it. Quarantine the
            # slot until PGID emptiness is positively observed.
            LOG.warning(
                "health: worker pid=%d aged out with NO identity fingerprint recorded — "
                "NOT killing (unverified target), recording for manual check",
                job.pid,
            )
            exit_code, outcome = -1, "timeout_unverified"
            log_tail = (
                "(aged out but no fingerprint recorded — NOT killed; process may still be "
                "alive. Manual check runbook: docs/runbooks/dispatch-supervisor-unverified-orphan.md)"
            )
        else:
            # IDENTITY_MISMATCH or IDENTITY_DEAD — confirmed NOT our process
            # (already gone, or the OS recycled the pid to something else).
            LOG.warning(
                "health: worker pid=%d aged out but identity=%s (pgid=%d) — skipping kill",
                job.pid, identity_verdict, job.pgid,
            )
            exit_code, outcome = -1, "silent_death"
            log_tail = "(identity mismatch/dead at max-age check — not killed, recorded as silent_death)"
        if outcome in {"kill_failed_orphan", "timeout_unverified"}:
            # Process may still be writing. Multi-slot lets us quarantine only
            # this slot while healthy siblings continue; freeing it would let
            # PHASE-Z commit a live orphan's half-written files.
            owned = state.mark_job_phase(
                job_id=job_id, expected_attempt=job.attempt, expected_pid=job.pid,
                phase=outcome, path=state_path,
            )
            if owned:
                alerts.send_hang_alert(
                    job={
                        "job_id": job_id, "slot_id": job.slot_id,
                        "pid": job.pid, "pgid": job.pgid,
                        "started_at": job.started_at, "attempt": job.attempt,
                        "model": job.model, "log_path": job.log_path,
                        "survivors": procutil.pgid_members(job.pgid),
                        "slot_quarantined": True,
                    },
                    log_tail=log_tail, state_path=state_path,
                )
            return outcome
        # Non-None == we won the atomic close and own the incident report. The
        # worker's own timeout fires on the same hang within ~1s; whoever loses
        # must not mail (see state.record_completion). We still hold a full `job`
        # here, so the alert is built from that, not from a post-close re-read.
        closed = state.record_completion(
            job_id=job_id, expected_attempt=job.attempt, expected_pid=job.pid,
            expected_phase=job.phase,
            exit_code=exit_code, outcome=outcome, final_model=job.model,
            path=state_path,
        )
        if closed is None:
            LOG.info(
                "health: worker pid=%d hang already closed by the worker's own timeout — "
                "it owns the alert, staying silent to avoid a duplicate",
                job.pid,
            )
        else:
            alerts.send_hang_alert(
                job={"job_id": job_id, "slot_id": job.slot_id,
                     "pid": job.pid, "pgid": job.pgid, "started_at": job.started_at,
                     "attempt": job.attempt, "model": job.model,
                     "log_path": job.log_path,
                     "survivors": procutil.pgid_members(job.pgid),
                     # WS-A2b receipt: which task claims this kill handed back.
                     "repended_tasks": repended_tasks},
                log_tail=log_tail,
                state_path=state_path,
            )
        if identity_verdict != procutil.IDENTITY_MATCH:
            return outcome
        return "killed" if outcome == "killed_timeout" else outcome
    if identity_verdict in (procutil.IDENTITY_MISMATCH, procutil.IDENTITY_DEAD):
        LOG.warning(
            "health: worker pid=%d dead/reused (identity=%s) but state has current_job — recording silent failure",
            job.pid, identity_verdict,
        )
        # Same ownership rule as the hang path: only the caller that actually
        # closed the slot reports it.
        closed = state.record_completion(
            job_id=job_id, expected_attempt=job.attempt, expected_pid=job.pid,
            expected_phase=job.phase,
            exit_code=-1, outcome="failure", final_model=job.model,
            path=state_path,
        )
        if closed is None:
            LOG.info(
                "health: worker pid=%d silent death already closed by the worker — "
                "it owns the alert, staying silent",
                job.pid,
            )
        else:
            alerts.send_silent_death_alert(
                job={"job_id": job_id, "slot_id": job.slot_id,
                     "pid": job.pid, "pgid": job.pgid, "started_at": job.started_at,
                     "attempt": job.attempt, "model": job.model,
                     "log_path": job.log_path,
                     "survivors": procutil.pgid_members(job.pgid)},
                state_path=state_path,
            )
        return "silent_death"
    # IDENTITY_MATCH, or IDENTITY_UNVERIFIED while still within budget — leave
    # it alone. An unverified fingerprint here just means it hasn't been
    # captured yet, not that anything is actually wrong.
    return None


def check_once(*, state_path: Path = state.STATE_PATH, max_age_s: float = MAX_JOB_AGE_S) -> str | None:
    """Inspect every process-bearing slot without letting one failure mask siblings."""
    actions: list[str] = []
    jobs = state.get_current_jobs(state_path)
    if not jobs:
        legacy = state.get_current_job(state_path)
        if legacy is not None:
            jobs = [legacy]
    for job in jobs:
        try:
            action = _check_job(job, state_path=state_path, max_age_s=max_age_s)
        except Exception as exc:  # noqa: BLE001 — sibling isolation is the point
            LOG.exception(
                "health: check failed job_id=%s slot=%s: %s",
                job.job_id, job.slot_id, exc,
            )
            alerts.send_loop_crash(
                f"health_job:{job.job_id[:8] or job.pid}",
                traceback.format_exc(), state_path=state_path,
            )
            continue
        if action:
            actions.append(action)
    if not actions:
        return None
    return actions[0] if len(actions) == 1 else ",".join(actions)


async def health_loop(*, state_path: Path = state.STATE_PATH, check_interval_s: int = CHECK_INTERVAL_S) -> None:
    """Long-running health monitor coroutine. Also owns the supervisor
    liveness heartbeat.

    2026-07-10: the heartbeat used to live only in `scheduler._tick_once()`,
    which blocks on `await worker.run_worker()` for the whole dispatch — so
    `dispatch_state.json` reported a frozen `last_heartbeat_at` for up to
    3×50min while the daemon was in fact working normally. This loop never
    blocks on a worker, so a beat from here means "the supervisor process is
    responsive", which is what the field is supposed to assert. Stamped BEFORE
    `check_once()` so a crash inside the health pass still leaves proof the
    process was alive (and the except-branch below alerts on it).

    2026-07-13: this loop also owns self-reload. It is the only place in the
    daemon that runs on a fixed cadence without ever blocking on a worker, which
    is exactly what "notice my own code changed, restart when idle" needs. See
    `selfreload` for why a detector that only emails a human was not enough.
    """
    LOG.info("health_loop start interval=%ds", check_interval_s)
    while True:
        try:
            await asyncio.sleep(check_interval_s)
            state.heartbeat(path=state_path)
            check_once(state_path=state_path)
            # Last: a reload SIGTERMs this process, so anything after it in the
            # tick would not run. The heartbeat and the hang check are what keep
            # the platform safe; deploying a fix is what keeps it improving.
            selfreload.maybe_self_reload(state_path=state_path)
        except asyncio.CancelledError:
            LOG.info("health_loop cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            # Codex review §10 #7 fix: this used to only LOG.exception — a
            # crash-looping health monitor (the belt-and-suspenders layer
            # behind worker.py's own timeout) would silently stop protecting
            # against hangs with zero visibility to the boss.
            LOG.exception("health_loop unexpected error: %s", exc)
            alerts.send_loop_crash("health_loop", traceback.format_exc(), state_path=state_path)
            # don't die — sleep and continue
