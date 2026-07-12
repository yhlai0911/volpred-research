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


class _ProbeFailedType:
    """Sentinel: the `ps` subprocess call itself could not be completed
    (OSError / timeout). Distinct from `None`, which means `ps` ran fine and
    confirmed the pid does not exist. Codex review round-2 finding
    (2026-07-04, medium — before real cutover): the prior implementation
    returned `None` for BOTH cases, so `check_identity()` treated a transient
    `ps` hiccup as `IDENTITY_DEAD` — indistinguishable from a confirmed-dead
    pid — which could make `health.check_once()` record `silent_death` and
    clear a perfectly healthy, still-running job on a one-off probe failure.
    """

    def __repr__(self) -> str:
        return "PROBE_FAILED"

    def __bool__(self) -> bool:
        # Falsy so existing `if started_wall:` guards (e.g. worker.py's
        # update_started_wall call) correctly treat this as "no usable
        # fingerprint" rather than accidentally serializing the sentinel.
        return False


PROBE_FAILED = _ProbeFailedType()


def get_process_start_wall(pid: int) -> str | None:
    """Return `ps -o lstart=` output for `pid` (e.g. 'Wed Jul  2 00:57:15 2026'),
    `None` if pid <= 0 or `ps` ran and confirmed the pid doesn't exist, or
    `PROBE_FAILED` if the `ps` call itself could not be completed (OSError /
    timeout) — see `_ProbeFailedType` docstring for why these must NOT be
    conflated."""
    if pid <= 0:
        return None
    try:
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.warning("get_process_start_wall pid=%d ps invocation failed: %s", pid, exc)
        return PROBE_FAILED
    if result.returncode != 0:
        return None  # pid not found — this IS the "does it exist" signal, not an error
    text = result.stdout.strip()
    return text or None


IDENTITY_MATCH = "match"            # alive, fingerprint matches — confirmed same process
IDENTITY_MISMATCH = "mismatch"      # alive, fingerprint present but differs — pid was reused
IDENTITY_DEAD = "dead"               # pid confirmed gone (ps ran, reported not-found)
IDENTITY_UNVERIFIED = "unverified"  # alive-or-unknown, but no fingerprint to compare or verify against


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

    A `PROBE_FAILED` result from `get_process_start_wall()` (round-2 fix,
    2026-07-04) is likewise mapped to `IDENTITY_UNVERIFIED`, not
    `IDENTITY_DEAD` — a transient `ps` failure tells us nothing about whether
    the pid is actually alive.
    """
    current = get_process_start_wall(pid)
    if current is PROBE_FAILED:
        return IDENTITY_UNVERIFIED
    if current is None:
        return IDENTITY_DEAD
    if not expected_start_wall:
        return IDENTITY_UNVERIFIED
    return IDENTITY_MATCH if current == expected_start_wall else IDENTITY_MISMATCH


DEFAULT_KILL_GRACE_S = 10.0


def pgid_members_checked(pgid: int) -> list[int] | None:
    """LIVE non-zombie pids, or ``None`` when group liveness is unverified.

    Zombies are the whole reason this function is careful. A SIGKILL'd process
    stays in the process table as `Z` until its parent reaps it, and `ps -g`
    happily lists it. Two consequences, both observed on 2026-07-11:

      - Counting a zombie as a survivor makes every successful kill look like a
        failed one (a live smoke test of the new kill path reported "orphan
        survived" for a group it had definitely just killed).
      - It also explains the original `killpg SIGKILL denied pgid=69948:
        [Errno 1] Operation not permitted` — macOS returns EPERM for a signal
        aimed at a process group whose only remaining member is a zombie. The
        kill HAD landed; the syscall's complaint was about the corpse.

    So "is the group still alive" must mean "does it hold a non-Z process".

    ``[]`` is therefore positive evidence that the group drained. A failed or
    malformed ``ps`` probe must not be collapsed into that answer: quarantine
    and PHASE-Z callers need to distinguish "gone" from "could not check".
    """
    if pgid <= 0:
        return []
    try:
        result = subprocess.run(
            ["ps", "-o", "pid=,stat=", "-g", str(pgid)],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.warning("pgid_members pgid=%d ps invocation failed: %s", pgid, exc)
        return None
    if result.returncode not in (0, 1):
        LOG.warning(
            "pgid_members pgid=%d ps returned rc=%d: %s",
            pgid, result.returncode, (result.stderr or "").strip(),
        )
        return None
    live: list[int] = []
    malformed = False
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            if line.strip():
                LOG.warning("pgid_members pgid=%d unparseable ps row: %r", pgid, line)
                malformed = True
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            LOG.warning("pgid_members pgid=%d unparseable pid: %r", pgid, parts[0])
            malformed = True
            continue
        if parts[1].startswith("Z"):
            continue  # dead already, just not reaped — not a survivor
        if pid != os.getpid():
            live.append(pid)
    return None if malformed else live


def pgid_members(pgid: int) -> list[int]:
    """Compatibility projection of :func:`pgid_members_checked`.

    Observability-only callers historically expect a list. Safety decisions
    must use ``pgid_members_checked`` so probe failure cannot mean "gone".
    """
    return pgid_members_checked(pgid) or []


def kill_pgid(pgid: int, *, grace_s: float = DEFAULT_KILL_GRACE_S) -> bool:
    """SIGTERM the group, SIGKILL after `grace_s`, then VERIFY. Returns True
    only if the group is confirmed empty afterwards.

    2026-07-11 (boss Telegram msg 465): the 14:57 hang-kill logged
    `killpg SIGKILL denied pgid=69948: [Errno 1] Operation not permitted` — the
    kill never landed — and this function returned None anyway, so `health.py`
    recorded `killed_timeout` and alerted "SIGKILL'd a worker" for a process
    that may well have still been running. A kill routine that cannot report
    failure turns an orphan into a silent one.

    Two changes: (1) `killpg` EPERM is no longer terminal — macOS can refuse a
    whole-group signal while still permitting the individual members (a group
    holding one unsignalable member is enough for EPERM), so fall back to
    signalling each pid from `ps -g`; (2) the return value is the *observed*
    state, not the syscall's, so callers stop having to trust the signal path.

    Codex review fix #5 (2026-07-04): `worker.py` and `health.py` each carried a
    near-duplicate copy of this routine and a PermissionError fix applied to one
    was missed in the other. One shared implementation so that cannot recur.
    """
    if pgid <= 0:
        return True

    def _signal_all(sig: int) -> None:
        try:
            os.killpg(pgid, sig)
            return
        except ProcessLookupError:
            return  # silent-ok: group already gone.
        except PermissionError as exc:
            LOG.warning("killpg %s denied pgid=%d: %s — falling back to per-pid",
                        sig, pgid, exc)
        members = pgid_members_checked(pgid)
        if members is None:
            LOG.warning("cannot enumerate pgid=%d for per-pid signal fallback", pgid)
            return
        for pid in members:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                continue  # silent-ok: exited between ps and kill.
            except PermissionError as exc:
                LOG.warning("kill %s denied pid=%d (pgid=%d): %s", sig, pid, pgid, exc)

    _signal_all(signal.SIGTERM)
    deadline = time.time() + grace_s
    while time.time() < deadline:
        members = pgid_members_checked(pgid)
        if members == []:
            return True
        time.sleep(0.5)

    _signal_all(signal.SIGKILL)
    time.sleep(0.5)
    survivors = pgid_members_checked(pgid)
    if survivors is None:
        LOG.error("kill_pgid pgid=%d UNVERIFIED — final liveness probe failed", pgid)
        return False
    if survivors:
        LOG.error("kill_pgid pgid=%d FAILED — survivors still running: %s", pgid, survivors)
        return False
    return True
