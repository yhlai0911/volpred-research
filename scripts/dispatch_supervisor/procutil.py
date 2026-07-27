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

from volpred.ops import termination

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


def kill_pgid(
    pgid: int,
    *,
    intent: termination.TerminationIntent | None = None,
    ledger_path=None,
    grace_s: float = DEFAULT_KILL_GRACE_S,
) -> bool:
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
    if intent is None:
        raise termination.TerminationIntentRequired(
            f"kill_pgid({pgid}) requires a durable termination intent"
        )

    def _signal_all(sig: int) -> None:
        try:
            result = termination.send_pgid(
                intent,
                sig,
                ledger_path=ledger_path,
            )
            if result == "gone":
                return
            return
        except PermissionError as exc:
            LOG.warning("killpg %s denied pgid=%d: %s — falling back to per-pid",
                        sig, pgid, exc)
        members = pgid_members_checked(pgid)
        if members is None:
            LOG.warning("cannot enumerate pgid=%d for per-pid signal fallback", pgid)
            return
        for pid in members:
            expected_start = get_process_start_wall(pid)
            if not expected_start or expected_start is PROBE_FAILED:
                LOG.warning(
                    "cannot identity-pin pgid=%d member pid=%d; refusing signal",
                    pgid, pid,
                )
                continue
            try:
                termination.send_member_pid(
                    intent,
                    pid,
                    sig,
                    ledger_path=ledger_path,
                    identity_verifier=lambda target, expected=expected_start: (
                        check_identity(target, expected) == IDENTITY_MATCH
                    ),
                )
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


def live_pids(pids: list[int]) -> list[int] | None:
    """Which of `pids` are alive and not zombies. ``None`` if the probe failed.

    Same zombie caveat as :func:`pgid_members_checked`: a SIGKILL'd process sits
    in the table as `Z` until reaped, and counting a corpse as a survivor makes
    every successful kill look failed.
    """
    if not pids:
        return []
    try:
        result = subprocess.run(
            ["ps", "-o", "pid=,stat=", "-p", ",".join(str(p) for p in pids)],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.warning("live_pids ps invocation failed: %s", exc)
        return None
    if result.returncode not in (0, 1):  # 1 = none of the pids exist
        LOG.warning("live_pids ps returned rc=%d: %s",
                    result.returncode, (result.stderr or "").strip())
        return None
    live: list[int] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            LOG.warning("live_pids unparseable pid: %r", parts[0])
            return None
        if parts[1].startswith("Z"):
            continue  # dead already, just not reaped — not a survivor
        if pid != os.getpid():
            live.append(pid)
    return live


def descendants_of(root_pid: int) -> list[int] | None:
    """Every live descendant of `root_pid`, at any depth. ``None`` on probe failure.

    Walks the full `ps -eo pid=,ppid=` parent table rather than asking about a
    process group, because the whole point of this function is to find children
    that are NOT in the group any more. macOS has no `/proc`, so `ps` is it.
    """
    if root_pid <= 0:
        return []
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,ppid="], capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.warning("descendants_of pid=%d ps invocation failed: %s", root_pid, exc)
        return None
    if result.returncode != 0:
        LOG.warning("descendants_of pid=%d ps returned rc=%d", root_pid, result.returncode)
        return None
    children: dict[int, list[int]] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue  # silent-ok: ps header/blank rows carry no pid
        children.setdefault(ppid, []).append(pid)
    found: list[int] = []
    stack = [root_pid]
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in found and child != os.getpid():
                found.append(child)
                stack.append(child)
    return found


def kill_tree(
    pid: int,
    *,
    intent: termination.TerminationIntent | None = None,
    ledger_path=None,
    grace_s: float = DEFAULT_KILL_GRACE_S,
) -> bool:
    """Kill `pid`, its process group, AND any descendant that left the group.

    Returns True only when every target is confirmed gone.

    `kill_pgid` is not enough on its own. A child that calls `setsid()` gets a
    brand-new session and process group, so `killpg(our_group)` never reaches
    it — and `subprocess.Popen(start_new_session=True)` on the parent does
    nothing to stop the child from doing the same. That is not hypothetical:
    codex's worker does exactly this. On 2026-07-11 (mile_531e4c87) and again on
    2026-07-13 (mile_aa4713db) a codex render worker outlived a killpg-based
    timeout and wrote render_lazypack.py 11 and 5 minutes respectively after the
    job had been declared dead. Both times the pipeline was quietly depending on
    a process it believed it had killed.

    The escaped child is invisible to every group-shaped query, so we reach it
    the only way macOS allows: walk the `ps` parent table and signal the
    descendants by pid. Enumerate BEFORE signalling — once the parent dies its
    children reparent to launchd and the trail to them is gone.
    """
    if pid <= 0:
        return True
    if intent is None:
        raise termination.TerminationIntentRequired(
            f"kill_tree({pid}) requires a durable termination intent"
        )

    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, PermissionError):
        pgid = 0  # already gone, or not ours — descendants still worth checking

    kin = descendants_of(pid)
    if kin is None:
        LOG.warning("kill_tree pid=%d could not enumerate descendants — "
                    "group kill only, escaped children may survive", pid)
        kin = []
    targets = [pid, *kin]

    def _signal(sig: int, pids: list[int]) -> None:
        for target in pids:
            expected_start = get_process_start_wall(target)
            if not expected_start or expected_start is PROBE_FAILED:
                LOG.warning(
                    "kill_tree cannot identity-pin pid=%d; refusing signal",
                    target,
                )
                continue
            try:
                termination.send_member_pid(
                    intent, target, sig, ledger_path=ledger_path,
                    identity_verifier=lambda pid, expected=expected_start: (
                        check_identity(pid, expected) == IDENTITY_MATCH
                    ),
                )
            except ProcessLookupError:
                continue  # silent-ok: exited between ps and kill.
            except PermissionError as exc:
                LOG.warning("kill_tree kill %s denied pid=%d: %s", sig, target, exc)

    _signal(signal.SIGTERM, targets)
    if pgid > 0:
        kill_pgid(
            pgid, intent=intent, ledger_path=ledger_path, grace_s=grace_s,
        )  # group path: TERM → grace → KILL → verify

    # Re-enumerate: the group kill may have freed children, and a slow spawner
    # may have produced new ones while we were signalling.
    late = descendants_of(pid)
    survivors = live_pids(sorted(set(targets + (late or []))))
    if survivors is None:
        LOG.error("kill_tree pid=%d UNVERIFIED — liveness probe failed", pid)
        return False
    if not survivors:
        return True

    LOG.warning("kill_tree pid=%d SIGKILLing %d escaped survivor(s): %s",
                pid, len(survivors), survivors)
    _signal(signal.SIGKILL, survivors)
    time.sleep(0.5)

    final = live_pids(survivors)
    if final is None:
        LOG.error("kill_tree pid=%d UNVERIFIED — final liveness probe failed", pid)
        return False
    if final:
        LOG.error("kill_tree pid=%d FAILED — survivors still running: %s", pid, final)
        return False
    return True
