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
import signal
import stat
import sys
import traceback
from pathlib import Path

from volpred.ops.execution.registry import load_provider_registry
from volpred.ops import termination

from . import (
    __version__,
    alerts,
    custody_receipt,
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
        # `producer_spawn_state` makes the formerly ambiguous Popen crash window
        # explicit.  not_started is positive proof no provider existed; once a
        # kernel custody baseline was bound, that saved coalition can discover
        # and terminate a child even though its PID never reached state.
        spawn_state = str(orphan.get("producer_spawn_state") or "")
        custody = (
            orphan.get("producer_custody")
            if isinstance(orphan.get("producer_custody"), dict)
            else None
        )
        killed = False
        if spawn_state == "not_started":
            exit_code, outcome = -1, "spawn_not_started"
        elif custody is not None:
            survivors = procutil.producer_cohort_members_checked(
                0,
                job_id=job_id,
                custody=custody,
            )
            if survivors is None:
                outcome = "orphan_unverified_no_pid"
                state.mark_job_phase(
                    job_id=job_id,
                    phase=outcome,
                    expected_attempt=int(orphan.get("attempt", 1)),
                    path=state_path,
                )
                alerts.send_orphan_restart_alert(
                    job=orphan,
                    killed=False,
                    outcome=outcome,
                    state_path=state_path,
                )
                return
            if survivors:
                ledger_path = termination.ledger_for_state(state_path)
                intent = termination.arm(
                    target_kind="pid",
                    target_id=int(survivors[0]),
                    target_identity=(
                        "producer-custody:"
                        f"{custody.get('resource_coalition_id', 'unknown')}"
                    ),
                    reason="supervisor_restart_orphan_no_pid",
                    actor="dispatch-supervisor.supervisor",
                    signal_sequence=[signal.SIGTERM, signal.SIGKILL],
                    job_id=job_id,
                    attempt=int(orphan.get("attempt", 1)),
                    ledger_path=ledger_path,
                )
                killed = procutil.kill_producer_cohort(
                    custody,
                    intent=intent,
                    ledger_path=ledger_path,
                )
                if not killed:
                    outcome = "orphan_unverified_no_pid"
                    state.mark_job_phase(
                        job_id=job_id,
                        phase=outcome,
                        expected_attempt=int(orphan.get("attempt", 1)),
                        path=state_path,
                    )
                    alerts.send_orphan_restart_alert(
                        job={**orphan, "survivors": survivors},
                        killed=False,
                        outcome=outcome,
                        state_path=state_path,
                    )
                    return
                exit_code, outcome = -9, "killed_supervisor_restart"
            else:
                exit_code, outcome = -1, "orphan_gone_or_reused"
        else:
            # Legacy/malformed state has neither positive no-spawn proof nor a
            # kernel custody boundary. Never reinterpret absence as safety.
            outcome = "orphan_unverified_no_pid"
            state.mark_job_phase(
                job_id=job_id,
                phase=outcome,
                expected_attempt=int(orphan.get("attempt", 1)),
                path=state_path,
            )
            alerts.send_orphan_restart_alert(
                job=orphan,
                killed=False,
                outcome=outcome,
                state_path=state_path,
            )
            return
        state.append_completion_entry(
            orphan, exit_code=exit_code, outcome=outcome,
            final_model=str(orphan.get("model", "?")), path=state_path,
            mark_cleanup_recorded=True,
        )
        alerts.send_orphan_restart_alert(
            job=orphan, killed=killed, outcome=outcome, state_path=state_path,
        )
        if _finalize_restart_workspace(orphan, outcome=outcome):
            state.finalize_restart_orphan_cleanup(state_path, job_id=job_id)
        return
    pid = int(orphan["pid"])
    custody = (
        orphan.get("producer_custody")
        if isinstance(orphan.get("producer_custody"), dict)
        else None
    )
    if custody is not None:
        # Kernel custody is stronger than the legacy ps wall-clock
        # fingerprint: every target is rechecked by process unique ID
        # immediately before signal, including setsid/reparent descendants.
        survivors = procutil.producer_cohort_members_checked(
            int(orphan.get("pgid") or pid),
            job_id=job_id,
            custody=custody,
        )
        if survivors is None:
            outcome = "orphan_unverified_not_killed"
            state.mark_job_phase(
                job_id=job_id,
                phase=outcome,
                expected_attempt=int(orphan.get("attempt", 1)),
                expected_pid=pid,
                path=state_path,
            )
            alerts.send_orphan_restart_alert(
                job=orphan,
                killed=False,
                outcome=outcome,
                state_path=state_path,
            )
            return
        killed = False
        if survivors:
            ledger_path = termination.ledger_for_state(state_path)
            intent = termination.arm(
                target_kind="pid",
                target_id=int(survivors[0]),
                target_identity=(
                    "producer-custody:"
                    f"{custody.get('resource_coalition_id', 'unknown')}"
                ),
                reason="supervisor_restart_orphan",
                actor="dispatch-supervisor.supervisor",
                signal_sequence=[signal.SIGTERM, signal.SIGKILL],
                job_id=job_id,
                attempt=int(orphan.get("attempt", 1)),
                ledger_path=ledger_path,
            )
            killed = procutil.kill_producer_cohort(
                custody,
                intent=intent,
                ledger_path=ledger_path,
            )
            if not killed:
                outcome = "kill_failed_orphan"
                state.mark_job_phase(
                    job_id=job_id,
                    phase=outcome,
                    expected_attempt=int(orphan.get("attempt", 1)),
                    expected_pid=pid,
                    path=state_path,
                )
                alerts.send_orphan_restart_alert(
                    job={**orphan, "survivors": survivors},
                    killed=False,
                    outcome=outcome,
                    state_path=state_path,
                )
                return
            exit_code, outcome = -9, "killed_supervisor_restart"
        else:
            exit_code, outcome = -1, "orphan_gone_or_reused"
        state.append_completion_entry(
            orphan,
            exit_code=exit_code,
            outcome=outcome,
            final_model=str(orphan.get("model", "?")),
            path=state_path,
            mark_cleanup_recorded=True,
        )
        alerts.send_orphan_restart_alert(
            job=orphan,
            killed=killed,
            outcome=outcome,
            state_path=state_path,
        )
        if _finalize_restart_workspace(orphan, outcome=outcome):
            state.finalize_restart_orphan_cleanup(state_path, job_id=job_id)
        return
    started_wall = orphan.get("started_wall")
    identity = procutil.check_identity(pid, started_wall)
    if identity == procutil.IDENTITY_MATCH:
        pgid = int(orphan.get("pgid") or pid)
        logging.warning(
            "restart: orphan job pid=%d pgid=%d still alive (identity-verified) — killing", pid, pgid,
        )
        killed = worker._kill_pgid(
            pgid, leader_pid=pid,
            reason="supervisor_restart_orphan",
            job_id=job_id,
            attempt=int(orphan.get("attempt", 1)),
            custody=(
                orphan.get("producer_custody")
                if isinstance(orphan.get("producer_custody"), dict)
                else None
            ),
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
        survivors = procutil.producer_cohort_members_checked(
            pgid,
            job_id=job_id,
            custody=(
                orphan.get("producer_custody")
                if isinstance(orphan.get("producer_custody"), dict)
                else None
            ),
        )
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
    job_id = str(orphan.get("job_id") or "")
    final = workspace_mod.finalize_workspace(
        repo_root=ROOT,
        workspace=workspace,
        worker_outcome=outcome,
        job_id=job_id,
        producer_custody=(
            orphan.get("producer_custody")
            if isinstance(orphan.get("producer_custody"), dict)
            else None
        ),
        producer_drain_confirmed=(
            workspace_mod.legacy_workspace_producer_drain_confirmed(
                ROOT,
                workspace_name=str(workspace.get("name") or ""),
                job_id=job_id,
            )
        ),
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


def _initialize_runtime(*, state_path: Path) -> None:
    """Recover every producer-affecting startup gate before serving traffic."""
    prev_started = state.read_state(state_path).get("supervisor_started_at")
    state.mark_supervisor_started(state_path)
    custody_recovery = custody_receipt.reconcile_pending_producer_custodies(
        ROOT,
    )
    if not custody_recovery.get("ok"):
        raise isolation.IsolationUnavailable(
            "global producer custody startup recovery failed closed: "
            f"{custody_recovery}"
        )
    if custody_recovery.get("released"):
        logging.warning(
            "global producer custody startup recovered=%s",
            custody_recovery["released"],
        )
    _handle_restart_orphan()
    # Auth-reaper recovery can Popen a helper. In shared-coalition custody mode
    # it must run only after boot orphan reconciliation has positively drained
    # (or retained) the prior producer. Starting it first contaminates the saved
    # coalition and can make the real provider indistinguishable from control
    # maintenance.
    if state.read_state(state_path).get("current_jobs"):
        logging.info(
            "provider auth startup recovery deferred until producer slot drains"
        )
    else:
        recovery = isolation.recover_provider_auth_reapers()
        if recovery["invalid"]:
            raise isolation.IsolationUnavailable(
                f"provider auth startup recovery failed closed: {recovery}"
            )
        if any(recovery.values()):
            logging.info("provider auth reaper recovery=%s", recovery)
    planned_reason = state.consume_planned_restart_marker()
    alerts.send_supervisor_restart(
        prev_started=prev_started,
        planned_reason=planned_reason,
    )


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
    try:
        _initialize_runtime(state_path=state_path)
    except Exception as exc:  # noqa: BLE001 - startup must remain fail closed
        # The old placement only covered exceptions raised by asyncio.gather.
        # Missing/corrupt custody evidence instead crashed under KeepAlive with
        # no owner-visible signal. Alert before re-raising; no producer can be
        # admitted because trigger/scheduler loops have not started.
        logging.exception("supervisor startup crash: %s", exc)
        alerts.send_loop_crash(
            "supervisor_startup",
            traceback.format_exc(),
            state_path=state_path,
        )
        raise
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
