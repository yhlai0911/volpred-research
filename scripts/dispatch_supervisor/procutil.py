"""Process identity helpers — PID-reuse safe liveness/kill checks.

Codex review §10 #2 fix (2026-06-15): state only ever stored `pid`/`pgid`.
`os.kill(pid, 0)` merely confirms *some* process holds that number — after
enough wall-clock time (health-check tick 30s later, or a supervisor restart
minutes/hours later), the OS can and does recycle a pid to an unrelated
process. Treating that recycled pid as "our worker" would `killpg()` an
innocent process group or misreport liveness.

macOS has no `/proc`, so we fingerprint a pid by its `ps -o lstart=` wall-clock
start time captured immediately at spawn and compared before every later
identity-sensitive operation (health check, restart orphan cleanup).
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import time

LOG = logging.getLogger(__name__)


def get_process_start_wall(pid: int) -> str | None:
    """Return `ps -o lstart=` output for `pid` (e.g. 'Wed Jul  2 00:57:15 2026'),
    or None if pid <= 0, doesn't exist, or `ps` itself fails."""
    if pid <= 0:
        return None
    try:
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.warning("get_process_start_wall pid=%d ps invocation failed: %s", pid, exc)
        return None
    if result.returncode != 0:
        return None  # pid not found — this IS the "does it exist" signal, not an error
    text = result.stdout.strip()
    return text or None


IDENTITY_MATCH = "match"            # alive, fingerprint matches — confirmed same process
IDENTITY_MISMATCH = "mismatch"      # alive, fingerprint present but differs — pid was reused
IDENTITY_DEAD = "dead"               # pid no longer exists
IDENTITY_UNVERIFIED = "unverified"  # alive, but no fingerprint was ever recorded to compare


def check_identity(pid: int, expected_start_wall: str | None) -> str:
    """Return one of IDENTITY_MATCH / IDENTITY_MISMATCH / IDENTITY_DEAD /
    IDENTITY_UNVERIFIED for `pid` against the fingerprint captured at spawn.

    Codex review fix #4 (2026-07-04, gate-blocking finding): the prior
    `pid_identity_matches()` returned a bare bool and, when `expected_start_wall`
    was missing, *degraded to True* ("assume it's the same process"). That is
    backwards for a kill decision: a missing fingerprint (attach raced ahead
    of a slow/failed `ps` call, or supervisor crashed mid-attach) means we
    have made NO verification at all, yet the caller would proceed to SIGKILL
    the pid as if verified — reopening the exact PID-reuse risk this whole
    fingerprint mechanism exists to close. Returning a distinct
    `IDENTITY_UNVERIFIED` forces every kill-decision call site to make that
    choice explicitly instead of silently trusting an absent fingerprint.
    """
    current = get_process_start_wall(pid)
    if current is None:
        return IDENTITY_DEAD
    if not expected_start_wall:
        return IDENTITY_UNVERIFIED
    return IDENTITY_MATCH if current == expected_start_wall else IDENTITY_MISMATCH


DEFAULT_KILL_GRACE_S = 10.0


def kill_pgid(pgid: int, *, grace_s: float = DEFAULT_KILL_GRACE_S) -> None:
    """SIGTERM whole process group; SIGKILL after `grace_s` if still alive.

    Codex review fix #5 (2026-07-04, gate-blocking finding): `worker.py` and
    `health.py` each carried their own near-duplicate copy of this routine.
    A real bug found via a live (non-mocked) smoke test — spawning a genuine
    orphan process and running restart-cleanup against it — was fixed in
    worker's copy (a sandboxed `os.killpg(pgid, 0)` liveness probe can raise
    `PermissionError`, not just `ProcessLookupError`) but NOT in health's,
    which would have silently skipped the SIGKILL and let a caller believe
    the job was killed when the process was, in fact, still alive. One
    shared implementation so a future fix here cannot miss a second copy.
    """
    if pgid <= 0:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return  # silent-ok: process group was already gone before SIGTERM.
    except PermissionError as exc:
        LOG.warning("killpg SIGTERM denied pgid=%d: %s", pgid, exc)
    deadline = time.time() + grace_s
    while time.time() < deadline:
        try:
            os.killpg(pgid, 0)  # liveness probe
        except ProcessLookupError:
            return  # silent-ok: process group exited between SIGTERM and probe.
        except PermissionError as exc:
            LOG.warning("killpg liveness probe denied pgid=%d: %s", pgid, exc)
            break
        time.sleep(0.5)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # silent-ok: process group exited before final SIGKILL.
    except PermissionError as exc:
        LOG.warning("killpg SIGKILL denied pgid=%d: %s", pgid, exc)
