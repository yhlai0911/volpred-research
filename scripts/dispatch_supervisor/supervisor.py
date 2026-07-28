"""Dispatch executor daemon entry point.

Runs under launchd Aqua agent `com.volpred.dispatch-supervisor.plist`
(RunAtLoad=true, KeepAlive=true, NOT StartCalendarInterval).

Boot sequence::

    1. _set_runtime_env()                    — ulimit -Sn 65536; source-like env hygiene
    2. state.mark_supervisor_started()        — heartbeat timestamps + supervisor_pid
    3. _handle_restart_orphan()               — identity-verified kill of any job
                                                 left `current_job` by a crashed
                                                 prior instance (Codex review §10 #3)
    4. alerts.send_supervisor_restart()       — info-level breadcrumb (dedup 60s)
    5. asyncio.gather(trigger_server, health_loop) — Operations Core is the only
                                                    schedule owner; this process
                                                    receives ticks and executes them

CLI::
    uv run python -m scripts.dispatch_supervisor.supervisor          # production
    uv run python -m scripts.dispatch_supervisor.supervisor --dry-run # shadow phase
    uv run python -m scripts.dispatch_supervisor.supervisor --version
    uv run python -m scripts.dispatch_supervisor.supervisor --once    # single tick for smoke

`--once` runs a single decision tick for smoke testing. Production never uses
it: Operations Core calls ``scripts.dispatch_supervisor.trigger`` through a
local Unix socket, preserving the worker pool while removing this daemon's
independent schedule clock.

Deliverable 5/8 — all 7 Codex review must-fix items landed (2026-07-04).
Deliverables 6-8 cover shadow run, cutover, deprecate, retro.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import resource
import stat
import sys
import traceback
from pathlib import Path

from volpred.ops.execution.registry import load_provider_registry

from . import (
    __version__,
    alerts,
    health,
    isolation,
    procutil,
    scheduler,
    state,
    trigger,
    worker,
)
from . import workspace as workspace_mod

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = Path(os.environ.get("VOLPRED_HOME_DIR", str(Path.home() / ".volpred"))) / "logs"
SUPERVISOR_LOG = LOG_DIR / "dispatch_supervisor.log"
_MODEL_TOKEN_MAX_BYTES = 16 * 1024


def _setup_logging(level: int = logging.INFO) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(SUPERVISOR_LOG, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    # also echo to stderr so launchd StandardErrorPath captures
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root.addHandler(sh)


def _set_runtime_env() -> None:
    """Apply env hygiene that the legacy shell wrapper used to do per-fire.

    Set ONCE at supervisor boot so all worker children inherit:
      - RLIMIT_NOFILE soft to 65536 (strike 3 mitigation)
      - VOLPRED_ACTOR=dispatch-supervisor so the daemon's OWN shared-state writes
        (writer_log; phase_z runs in this same process) are attributed instead of
        logging actor="unknown" (2026-07-10 attribution gap, docs/error_log.md).
        setdefault so an operator/launchd override wins; worker children override
        it per-fire (worker._dispatch_actor) so AGENT writes carry the fire.
    """
    os.environ.setdefault("VOLPRED_ACTOR", "dispatch-supervisor")
    _load_model_auth_token()
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = 65536
        if soft < target:
            new_soft = min(target, hard if hard > 0 else target)
            resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
            logging.info("RLIMIT_NOFILE %d -> %d (hard=%s)", soft, new_soft, hard)
    except (ValueError, OSError) as exc:
        logging.warning("setrlimit NOFILE failed: %s", exc)


def _load_model_auth_token() -> None:
    """Load the model-only OAuth token before entering a synthetic HOME.

    The isolated worker must not read the operator's ``~/.volpred`` tree, but
    the Claude CLI still needs model-provider authentication.  The supervisor
    therefore reads one exact, owner-only file and exports one exact env key;
    ``isolated_environment`` passes that key while continuing to strip
    SSH/Git/cloud/Telegram authority.
    """
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return
    volpred_home = Path(
        os.environ.get("VOLPRED_HOME_DIR", str(Path.home() / ".volpred"))
    )
    token_path = volpred_home / "secrets" / "claude_oauth_token"
    try:
        info = token_path.lstat()
    except FileNotFoundError:
        logging.warning(
            "model OAuth token file absent; isolated workers cannot use keychain auth"
        )
        return
    except OSError as exc:
        logging.warning("model OAuth token metadata unavailable: %s", exc)
        return
    mode = stat.S_IMODE(info.st_mode)
    if (
        not stat.S_ISREG(info.st_mode)
        or token_path.is_symlink()
        or info.st_uid != os.getuid()
        or mode & 0o077
        or info.st_size <= 0
        or info.st_size > _MODEL_TOKEN_MAX_BYTES
    ):
        logging.error(
            "refusing insecure model OAuth token file path=%s mode=%04o owner=%s size=%s",
            token_path, mode, info.st_uid, info.st_size,
        )
        return
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        logging.warning("model OAuth token read failed: %s", exc)
        return
    if not token or any(ch.isspace() for ch in token):
        logging.error("refusing malformed model OAuth token file path=%s", token_path)
        return
    os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token
    logging.info("loaded model-only OAuth token for isolated workers")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="dispatch-supervisor")
    parser.add_argument("--dry-run", action="store_true",
                        help="Shadow mode: log decisions but do not spawn workers.")
    parser.add_argument("--once", action="store_true",
                        help="Run a single scheduler tick (no async loop) and exit.")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def _handle_restart_orphan() -> None:
    """Identity-verified orphan cleanup on boot (Codex review §10 #3, #2, #4
    fixes — 2026-06-15 original + 2026-07-04 gate-blocking follow-ups).

    `state.mark_supervisor_started()` no longer silently discards a stale
    `current_job` (see its docstring). This flags it via
    `mark_restart_orphan_pending()` (NOT cleared yet — see that function's
    docstring for why: a second crash mid-cleanup must be able to retry the
    same orphan, not lose it), and — ONLY if the pid still exists AND its
    `ps`-derived start-time fingerprint still matches what was recorded at
    spawn (`procutil.IDENTITY_MATCH`; a `ps` failure yielding
    `IDENTITY_UNVERIFIED` does NOT count — do not kill an unverified target)
    — force-kills its process group. `finalize_restart_orphan_cleanup()` is
    the last call in every branch, only after the outcome is recorded, so a
    crash before that point leaves the slot intact for the next restart to
    retry. Runs before `send_supervisor_restart()` so the restart alert body
    would reflect it if we later want to fold this in; kept as its own alert
    for now since it's a materially different event (an actual orphan found).
    """
    # NOTE: read `state.STATE_PATH` here (call-time attribute lookup) rather
    # than relying on downstream functions' own `path=STATE_PATH` defaults —
    # those defaults bind at function-DEFINITION time, so monkeypatching
    # `state.STATE_PATH` in a test would silently not apply to them.
    state_path = state.STATE_PATH
    orphans = state.mark_restart_orphans_pending(state_path)
    for orphan in orphans:
        try:
            _handle_one_restart_orphan(orphan, state_path=state_path)
        except Exception:  # one bad orphan must not hide/clear its siblings
            logging.exception(
                "restart: orphan cleanup failed job_id=%s slot=%s; leaving it pending",
                orphan.get("job_id"), orphan.get("slot_id"),
            )


def _handle_one_restart_orphan(orphan: dict, *, state_path) -> None:
    """Identity-check, record, and exact-finalize one restart orphan."""
    job_id = str(orphan.get("job_id") or "")
    if orphan.get("cleanup_recorded"):
        # Codex review round-2 low finding (2026-07-04): a prior restart's
        # cleanup already appended this orphan's completion entry (the
        # `cleanup_recorded` flag is set atomically WITH that append — see
        # state.append_completion_entry) but crashed before finalize. Do not
        # append a duplicate entry; just finish the deferred finalize.
        logging.info(
            "restart: orphan pid=%s cleanup already recorded by a prior attempt — finalizing only",
            orphan.get("pid"),
        )
        # Codex review round-3 medium #1 (2026-07-04): the crash-before-alert
        # gap could suppress the ONLY runbook prompt for an orphan we did NOT
        # kill and cannot verify is dead. Re-emit the orphan alert here (its
        # 60s dedup prevents spam on a fast retry, while a genuine restart
        # minutes later re-surfaces a still-alive unverified orphan). Only
        # re-alert for the not-killed outcomes — a killed orphan is resolved.
        recorded_outcome = str(orphan.get("cleanup_outcome") or "")
        if recorded_outcome and recorded_outcome != "killed_supervisor_restart":
            alerts.send_orphan_restart_alert(
                job=orphan, killed=False, outcome=recorded_outcome, state_path=state_path,
            )
        if _finalize_restart_workspace(orphan, outcome=recorded_outcome):
            state.finalize_restart_orphan_cleanup(state_path, job_id=job_id)
        return
    if orphan.get("pid") is None:
        # Codex review fix #2 (2026-07-04): supervisor crashed between
        # reserve_fire() (writes the pid=None placeholder) and worker.py's
        # attach_process() call, which now runs immediately after Popen()
        # returns (narrowed to just that syscall — see worker.py). We cannot
        # identify or kill a child we were never told the pid of; the best
        # we can do is stop this slot from being wedged forever and make the
        # gap loudly visible instead of silently swallowing it.
        logging.warning(
            "restart: abandoned pid=None reservation (schedule_id=%s attempt=%s) — "
            "clearing stuck slot; if Popen had already succeeded before the crash, "
            "that child is now untracked and will only be found by max-age/health checks "
            "once/if it (re)acquires a pid we happen to observe",
            orphan.get("schedule_id"), orphan.get("attempt"),
        )
        if orphan.get("workspace") is not None:
            # Once a workspace is bound, pid=None is not proof that no producer
            # exists: the old supervisor may have crashed in Popen's tiny
            # return→attach window. Keep both the slot and workspace protected
            # until an operator can prove the process group is absent.
            state.mark_job_phase(
                job_id=job_id,
                phase="orphan_unverified_no_pid",
                expected_attempt=int(orphan.get("attempt", 1)),
                path=state_path,
            )
            alerts.send_orphan_restart_alert(
                job=orphan,
                killed=False,
                outcome="orphan_unverified_no_pid",
                state_path=state_path,
            )
            return
        state.append_completion_entry(
            orphan, exit_code=-1, outcome="reservation_abandoned_no_pid",
            final_model=str(orphan.get("model", "?")), path=state_path,
            mark_cleanup_recorded=True,
        )
        alerts.send_orphan_restart_alert(
            job=orphan, killed=False, outcome="reservation_abandoned_no_pid", state_path=state_path,
        )
        state.finalize_restart_orphan_cleanup(state_path, job_id=job_id)
        return
    pid = int(orphan["pid"])
    started_wall = orphan.get("started_wall")
    identity = procutil.check_identity(pid, started_wall)
    if identity == procutil.IDENTITY_MATCH:
        pgid = int(orphan.get("pgid") or pid)
        logging.warning(
            "restart: orphan job pid=%d pgid=%d still alive (identity-verified) — killing", pid, pgid,
        )
        killed = worker._kill_pgid(
            pgid,
            reason="supervisor_restart_orphan",
            job_id=job_id,
            attempt=int(orphan.get("attempt", 1)),
            state_path=state_path,
        )
        if not killed:
            outcome = "kill_failed_orphan"
            state.mark_job_phase(
                job_id=job_id, phase=outcome,
                expected_attempt=int(orphan.get("attempt", 1)), expected_pid=pid,
                path=state_path,
            )
            alerts.send_orphan_restart_alert(
                job=orphan, killed=False, outcome=outcome, state_path=state_path,
            )
            return
        exit_code, outcome = -9, "killed_supervisor_restart"
    elif identity == procutil.IDENTITY_UNVERIFIED:
        # Codex review fix #4: no fingerprint was recorded (attach raced
        # ahead of a slow/failed `ps` call). Do NOT kill an unverified
        # target — record distinctly so ops can check by hand instead of
        # trusting a bare "pid is alive" as proof it's ours.
        logging.warning(
            "restart: orphan job pid=%d alive but NO identity fingerprint recorded — "
            "NOT killing (unverified target), recording for manual check", pid,
        )
        outcome, killed = "orphan_unverified_not_killed", False
        state.mark_job_phase(
            job_id=job_id, phase=outcome, expected_attempt=int(orphan.get("attempt", 1)),
            expected_pid=pid, path=state_path,
        )
        alerts.send_orphan_restart_alert(
            job=orphan, killed=False, outcome=outcome, state_path=state_path,
        )
        return
    else:
        pgid = int(orphan.get("pgid") or pid)
        survivors = procutil.pgid_members_checked(pgid)
        if survivors is None or survivors:
            # The leader can be dead while a descendant/subagent in its process
            # group keeps writing. A failed probe is also not evidence of
            # group death. Preserve the slot and block PHASE-Z until health can
            # positively observe an empty group.
            outcome = "kill_failed_orphan"
            state.mark_job_phase(
                job_id=job_id, phase=outcome,
                expected_attempt=int(orphan.get("attempt", 1)), expected_pid=pid,
                path=state_path,
            )
            alerts.send_orphan_restart_alert(
                job={**orphan, "survivors": survivors}, killed=False,
                outcome=outcome, state_path=state_path,
            )
            return
        logging.info(
            "restart: stale current_job pid=%d already gone / pid reused and pgid=%d empty",
            pid, pgid,
        )
        exit_code, outcome, killed = -1, "orphan_gone_or_reused", False
    state.append_completion_entry(
        orphan, exit_code=exit_code, outcome=outcome,
        final_model=str(orphan.get("model", "?")), path=state_path,
        mark_cleanup_recorded=True,
    )
    alerts.send_orphan_restart_alert(job=orphan, killed=killed, outcome=outcome, state_path=state_path)
    if _finalize_restart_workspace(orphan, outcome=outcome):
        state.finalize_restart_orphan_cleanup(state_path, job_id=job_id)


def _finalize_restart_workspace(orphan: dict, *, outcome: str) -> bool:
    """Adjudicate a verified-dead orphan before releasing its state identity."""
    workspace = orphan.get("workspace")
    if not isinstance(workspace, dict):
        return True
    final = workspace_mod.finalize_workspace(
        repo_root=ROOT,
        workspace=workspace,
        worker_outcome="orphaned",
        job_id=str(orphan.get("job_id") or ""),
    )
    disposition = str(final.get("disposition") or "")
    settlement_disposition = scheduler._settlement_disposition(final)
    if workspace.get("task_id") and settlement_disposition is not None:
        settled = scheduler._settle_mutating_task(
            repo_root=ROOT,
            workspace=workspace,
            disposition=settlement_disposition,
            result=f"restart orphan adjudication: {disposition}",
        )
        if not settled.get("ok"):
            logging.error(
                "restart: task settlement failed job_id=%s task_id=%s result=%s",
                orphan.get("job_id"),
                workspace.get("task_id"),
                settled,
            )
            return False
        if not workspace_mod.complete_task_settlement(
            ROOT,
            task_id=str(workspace["task_id"]),
            claim_session_id=str(workspace["claim_session_id"]),
            disposition=settlement_disposition,
            status=str(settled.get("status") or ""),
        ):
            logging.error(
                "restart: task settlement receipt failed job_id=%s task_id=%s",
                orphan.get("job_id"),
                workspace.get("task_id"),
            )
            return False
    terminal = disposition in {"empty_removed", "merged"} or (
        disposition == "remediation_opened"
        and bool((final.get("checkpoint") or {}).get("released"))
    )
    if not terminal:
        logging.error(
            "restart: workspace adjudication not terminal job_id=%s "
            "disposition=%s; retaining restart_cleanup identity",
            orphan.get("job_id"),
            disposition,
        )
    return terminal


async def _run_async(*, dry_run: bool) -> int:
    await asyncio.gather(
        trigger.serve_forever(dry_run=dry_run),
        health.health_loop(),
    )
    return 0


async def _run_once_async(*, dry_run: bool) -> int:
    cron_expr = scheduler.load_cron_expr()
    decision = await scheduler._tick_once(
        state_path=state.STATE_PATH,
        cron_expr=cron_expr,
        prompt_path=scheduler.DEFAULT_PROMPT_PATH,
        log_path=scheduler.DEFAULT_LOG_PATH,
        dry_run=dry_run,
    )
    logging.info("--once decision=%s", decision)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.version:
        print(f"dispatch-supervisor {__version__}")
        return 0
    _setup_logging(getattr(logging, args.log_level.upper(), logging.INFO))
    _set_runtime_env()
    # Startup half of the zero-paid guard. Worker attempts reload the same
    # canonical bytes immediately before each provider Popen.
    load_provider_registry()
    recovery = isolation.recover_provider_auth_reapers()
    if recovery["invalid"]:
        raise isolation.IsolationUnavailable(
            f"provider auth startup recovery failed closed: {recovery}"
        )
    if any(recovery.values()):
        logging.info("provider auth reaper recovery=%s", recovery)
    # NOTE: resolve `state.STATE_PATH` here and pass it down explicitly — the
    # same definition-time default-binding trap `_handle_restart_orphan()`
    # documents. These two calls used to rely on `mark_supervisor_started`'s own
    # `path=STATE_PATH` default, which binds at function-DEFINITION time, so a
    # test monkeypatching `state.STATE_PATH` did not redirect them and every run
    # of `test_supervisor_main_top_level_crash_sends_alert_and_reraises` wrote a
    # bogus boot time / heartbeat / pid into the LIVE `dispatch_state.json`
    # (caught 2026-07-10, when the new `supervisor_pid` field made a dead pytest
    # pid show up as the running daemon's).
    state_path = state.STATE_PATH
    prev_started = state.read_state(state_path).get("supervisor_started_at")
    state.mark_supervisor_started(state_path)
    _handle_restart_orphan()
    # Deploy-aware restart alert (2026-07-10): a fresh marker means this boot is
    # a deliberate `kickstart -k` reload (supervisor code change) → suppress the
    # INFO alert. No marker → genuine/unexpected KeepAlive respawn → alert.
    planned_reason = state.consume_planned_restart_marker()
    alerts.send_supervisor_restart(prev_started=prev_started, planned_reason=planned_reason)
    try:
        if args.once:
            return asyncio.run(_run_once_async(dry_run=args.dry_run))
        return asyncio.run(_run_async(dry_run=args.dry_run))
    except KeyboardInterrupt:
        logging.info("supervisor interrupted")
        return 130
    except Exception as exc:  # noqa: BLE001
        # Codex review §10 #7 fix: an uncaught exception escaping
        # asyncio.gather() used to just crash to stderr — launchd's
        # KeepAlive restarts the process (send_supervisor_restart covers
        # the NEXT boot) but nothing alerts on THIS crash's traceback.
        logging.exception("supervisor top-level crash: %s", exc)
        alerts.send_loop_crash("supervisor_main", traceback.format_exc())
        raise


if __name__ == "__main__":
    sys.exit(main())
