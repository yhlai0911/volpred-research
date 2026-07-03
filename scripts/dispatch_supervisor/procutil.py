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
import subprocess

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


def pid_identity_matches(pid: int, expected_start_wall: str | None) -> bool:
    """True iff `pid` is currently alive AND its start time matches `expected_start_wall`.

    If `expected_start_wall` is falsy (state entries recorded before this
    fingerprint existed, or a reservation whose spawn never attached identity),
    degrade to bare liveness rather than treat every legacy entry as a mismatch.
    """
    current = get_process_start_wall(pid)
    if current is None:
        return False  # pid does not exist right now
    if not expected_start_wall:
        return True  # no fingerprint to compare against — best effort
    return current == expected_start_wall
