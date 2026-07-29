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

import ctypes
import errno
import functools
import logging
import os
import signal
import subprocess
import sys
import time
import uuid

from volpred.ops import termination

LOG = logging.getLogger(__name__)

# Keep OS process-table probes independent from payload runners that also use
# the stdlib subprocess module. Binding the adapter once prevents a narrow
# job-runner test double in another module from replacing `ps` transitively.
_run_ps_probe = subprocess.run


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
        result = _run_ps_probe(
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
        result = _run_ps_probe(
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


_PROC_PIDUNIQIDENTIFIERINFO = 17
_PROC_PIDCOALITIONINFO = 20
_COALITION_TYPE_RESOURCE = 0
_COALITION_NUM_TYPES = 2
_COALITION_INFO_PID_LIST_MAX_PIDS = 512
_CUSTODY_VERSION = 2
_COALITION_DRAIN_REFERENCE_VERSION = 1


class _ProcUniqueIdentifierInfo(ctypes.Structure):
    """ABI from Apple's ``sys/proc_info_private.h`` (56 bytes)."""

    _fields_ = [
        ("p_uuid", ctypes.c_uint8 * 16),
        ("p_uniqueid", ctypes.c_uint64),
        ("p_puniqueid", ctypes.c_uint64),
        ("p_idversion", ctypes.c_int32),
        ("p_orig_ppidversion", ctypes.c_int32),
        ("p_reserve2", ctypes.c_uint64),
        ("p_reserve3", ctypes.c_uint64),
    ]


class _ProcPidCoalitionInfo(ctypes.Structure):
    """ABI from Apple's ``sys/proc_info_private.h`` (40 bytes on macOS)."""

    _fields_ = [
        ("coalition_id", ctypes.c_uint64 * _COALITION_NUM_TYPES),
        ("reserved1", ctypes.c_uint64),
        ("reserved2", ctypes.c_uint64),
        ("reserved3", ctypes.c_uint64),
    ]


class _Timespec(ctypes.Structure):
    """Darwin ``struct timespec`` used by ``gethostuuid(3)``."""

    _fields_ = [
        ("tv_sec", ctypes.c_long),
        ("tv_nsec", ctypes.c_long),
    ]


class _DarwinCustodyProbeError(RuntimeError):
    """The kernel custody answer was absent, truncated, or ABI-incompatible."""


_CUSTODY_PROBE_ERRORS = (
    OSError,
    TypeError,
    ValueError,
    OverflowError,
    AttributeError,
    ctypes.ArgumentError,
    _DarwinCustodyProbeError,
)


class _DarwinCustodyAPI:
    """Narrow, secret-free adapter over exported libSystem process APIs."""

    def __init__(self) -> None:
        if ctypes.sizeof(_ProcUniqueIdentifierInfo) != 56:
            raise _DarwinCustodyProbeError("unexpected unique-id ABI size")
        if ctypes.sizeof(_ProcPidCoalitionInfo) != 40:
            raise _DarwinCustodyProbeError("unexpected coalition ABI size")
        try:
            libsystem = ctypes.CDLL(
                "/usr/lib/libSystem.B.dylib",
                use_errno=True,
            )
            proc_pidinfo = libsystem.proc_pidinfo
            coalition_info_pid_list = libsystem.coalition_info_pid_list
            gethostuuid = libsystem.gethostuuid
            sysctlbyname = libsystem.sysctlbyname
        except (AttributeError, OSError) as exc:
            raise _DarwinCustodyProbeError(
                "required libSystem custody API unavailable"
            ) from exc
        proc_pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        proc_pidinfo.restype = ctypes.c_int
        coalition_info_pid_list.argtypes = [
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_size_t),
        ]
        coalition_info_pid_list.restype = ctypes.c_int
        gethostuuid.argtypes = [
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.POINTER(_Timespec),
        ]
        gethostuuid.restype = ctypes.c_int
        sysctlbyname.argtypes = [
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        sysctlbyname.restype = ctypes.c_int
        self._proc_pidinfo = proc_pidinfo
        self._coalition_info_pid_list = coalition_info_pid_list
        self._gethostuuid = gethostuuid
        self._sysctlbyname = sysctlbyname

    @staticmethod
    def _os_error(operation: str) -> OSError:
        error_number = ctypes.get_errno() or errno.EIO
        return OSError(error_number, f"{operation} failed")

    def resource_coalition_id(self, pid: int) -> int:
        info = _ProcPidCoalitionInfo()
        ctypes.set_errno(0)
        copied = self._proc_pidinfo(
            int(pid),
            _PROC_PIDCOALITIONINFO,
            0,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if copied != ctypes.sizeof(info):
            if copied <= 0:
                raise self._os_error("proc_pidinfo coalition probe")
            raise _DarwinCustodyProbeError(
                "proc_pidinfo returned a partial coalition record"
            )
        coalition_id = int(info.coalition_id[_COALITION_TYPE_RESOURCE])
        if coalition_id <= 0:
            raise _DarwinCustodyProbeError("invalid resource coalition id")
        return coalition_id

    def host_uuid(self) -> str:
        """Return a stable physical-host UUID without spawning a helper."""
        raw = (ctypes.c_uint8 * 16)()
        timeout = _Timespec(5, 0)
        ctypes.set_errno(0)
        result = self._gethostuuid(raw, ctypes.byref(timeout))
        if result != 0:
            raise self._os_error("gethostuuid")
        try:
            value = str(uuid.UUID(bytes=bytes(raw)))
        except (ValueError, AttributeError) as exc:
            raise _DarwinCustodyProbeError(
                "gethostuuid returned malformed identity"
            ) from exc
        if value == str(uuid.UUID(int=0)):
            raise _DarwinCustodyProbeError("gethostuuid returned zero identity")
        return value

    def boot_session_uuid(self) -> str:
        """Return the kernel boot-session UUID without spawning a helper."""
        name = b"kern.bootsessionuuid"
        size = ctypes.c_size_t()
        ctypes.set_errno(0)
        if self._sysctlbyname(
            name,
            None,
            ctypes.byref(size),
            None,
            0,
        ) != 0:
            raise self._os_error("sysctlbyname boot-session size")
        if size.value <= 1 or size.value > 128:
            raise _DarwinCustodyProbeError(
                "sysctlbyname returned invalid boot-session size"
            )
        raw = ctypes.create_string_buffer(size.value)
        ctypes.set_errno(0)
        if self._sysctlbyname(
            name,
            raw,
            ctypes.byref(size),
            None,
            0,
        ) != 0:
            raise self._os_error("sysctlbyname boot-session read")
        try:
            return str(uuid.UUID(raw.value.decode("ascii")))
        except (UnicodeError, ValueError) as exc:
            raise _DarwinCustodyProbeError(
                "sysctlbyname returned malformed boot-session identity"
            ) from exc

    def coalition_pids(self, coalition_id: int) -> list[int]:
        if isinstance(coalition_id, bool) or int(coalition_id) <= 0:
            raise _DarwinCustodyProbeError("invalid resource coalition id")
        pid_buffer = (
            ctypes.c_int * _COALITION_INFO_PID_LIST_MAX_PIDS
        )()
        size_bytes = ctypes.c_size_t(ctypes.sizeof(pid_buffer))
        ctypes.set_errno(0)
        result = self._coalition_info_pid_list(
            int(coalition_id),
            pid_buffer,
            ctypes.byref(size_bytes),
        )
        if result != 0:
            raise self._os_error("coalition_info_pid_list")
        returned_bytes = int(size_bytes.value)
        pid_size = ctypes.sizeof(ctypes.c_int)
        if (
            returned_bytes < 0
            or returned_bytes > ctypes.sizeof(pid_buffer)
            or returned_bytes % pid_size
        ):
            raise _DarwinCustodyProbeError(
                "malformed coalition pid-list size"
            )
        count = returned_bytes // pid_size
        # The API truncates silently. A full buffer is not proof that every
        # member was observed, even when the true cardinality happens to be 512.
        if count >= _COALITION_INFO_PID_LIST_MAX_PIDS:
            raise _DarwinCustodyProbeError("coalition pid-list cap reached")
        pids = [int(pid_buffer[index]) for index in range(count)]
        if any(pid <= 0 for pid in pids) or len(set(pids)) != len(pids):
            raise _DarwinCustodyProbeError("malformed coalition pid list")
        return pids

    def process_identity(self, pid: int) -> tuple[int, int] | None:
        """Return ``(uniqueid, parent_uniqueid)``; ``None`` means confirmed gone.

        Flavor 17 with ``arg=0`` excludes zombies in XNU. Thus a successful
        exact-size record is both the PID-reuse fingerprint and the non-zombie
        liveness proof needed by custody.
        """
        info = _ProcUniqueIdentifierInfo()
        ctypes.set_errno(0)
        copied = self._proc_pidinfo(
            int(pid),
            _PROC_PIDUNIQIDENTIFIERINFO,
            0,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if copied == 0 and ctypes.get_errno() == errno.ESRCH:
            return None
        if copied != ctypes.sizeof(info):
            if copied <= 0:
                raise self._os_error("proc_pidinfo unique-id probe")
            raise _DarwinCustodyProbeError(
                "proc_pidinfo returned a partial unique-id record"
            )
        uniqueid = int(info.p_uniqueid)
        parent_uniqueid = int(info.p_puniqueid)
        if uniqueid <= 0 or parent_uniqueid < 0:
            raise _DarwinCustodyProbeError("malformed process identity")
        return uniqueid, parent_uniqueid


@functools.lru_cache(maxsize=1)
def _get_darwin_custody_api() -> _DarwinCustodyAPI:
    return _DarwinCustodyAPI()


def _coalition_identities(
    api: _DarwinCustodyAPI,
    coalition_id: int,
) -> dict[int, tuple[int, int]]:
    """Snapshot live coalition members as pid -> (uniqueid, parent uniqueid)."""
    identities: dict[int, tuple[int, int]] = {}
    uniqueids: set[int] = set()
    pids = api.coalition_pids(coalition_id)
    if len(pids) >= _COALITION_INFO_PID_LIST_MAX_PIDS:
        raise _DarwinCustodyProbeError("coalition pid-list cap reached")
    for pid in pids:
        identity_before = api.process_identity(pid)
        if identity_before is None:
            continue  # exited or became a zombie after the coalition snapshot
        try:
            observed_coalition_id = api.resource_coalition_id(pid)
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                continue
            raise
        identity_after = api.process_identity(pid)
        if identity_after is None:
            continue
        if identity_after != identity_before:
            # A PID changed owners while the multi-call userspace snapshot was
            # being formed. No conclusion about that number is safe.
            raise _DarwinCustodyProbeError(
                "pid reused during coalition identity probe"
            )
        if observed_coalition_id != coalition_id:
            # The coalition list raced with exit + PID reuse into an unrelated
            # coalition. It is not a member and must never gain kill authority.
            continue
        identity = identity_after
        uniqueid, _parent_uniqueid = identity
        if uniqueid in uniqueids:
            raise _DarwinCustodyProbeError(
                "duplicate process unique id in coalition"
            )
        identities[pid] = identity
        uniqueids.add(uniqueid)
    return identities


def _verified_ancestor_uniqueids(
    identities: dict[int, tuple[int, int]],
    current_pid: int,
) -> set[int]:
    """Kernel-verified current process plus its live same-coalition ancestors."""
    current_identity = identities.get(current_pid)
    if current_identity is None:
        raise _DarwinCustodyProbeError(
            "current process absent from coalition snapshot"
        )
    by_uniqueid = {
        uniqueid: parent_uniqueid
        for uniqueid, parent_uniqueid in identities.values()
    }
    trusted: set[int] = set()
    cursor = current_identity[0]
    while cursor in by_uniqueid:
        if cursor in trusted:
            raise _DarwinCustodyProbeError("process ancestry cycle")
        trusted.add(cursor)
        cursor = by_uniqueid[cursor]
    return trusted


def capture_producer_custody() -> dict[str, object] | None:
    """Capture a clean Darwin coalition baseline immediately before spawn.

    The baseline cannot be every existing coalition member: doing so would
    permanently bless an already-detached producer as "pre-existing". Only
    the current process and its kernel-verified same-coalition ancestor chain
    are trusted. Any other live member makes capture fail closed, so callers
    must not spawn a provider from a shared/dirty coalition.
    """
    return capture_existing_producer_custody(os.getpid())


def capture_existing_producer_custody(
    anchor_pid: int,
) -> dict[str, object] | None:
    """Capture one clean Darwin coalition around an existing leaf process.

    The installer uses this before unloading the legacy supervisor.  A clean
    capture proves that the saved anchor plus its same-coalition ancestors are
    the *only* live members at the migration boundary.  A detached child,
    sibling helper, PID reuse, or probe ambiguity therefore fails closed.
    """
    if (
        sys.platform != "darwin"
        or isinstance(anchor_pid, bool)
        or not isinstance(anchor_pid, int)
        or anchor_pid <= 0
    ):
        return None
    try:
        api = _get_darwin_custody_api()
        coalition_id = api.resource_coalition_id(anchor_pid)
        identities = _coalition_identities(api, coalition_id)
        trusted = _verified_ancestor_uniqueids(identities, anchor_pid)
        observed = {identity[0] for identity in identities.values()}
        if observed != trusted:
            return None
        return {
            "version": _CUSTODY_VERSION,
            "host_uuid": api.host_uuid(),
            "boot_session_uuid": api.boot_session_uuid(),
            "resource_coalition_id": coalition_id,
            "trusted_unique_ids": sorted(trusted),
        }
    except _CUSTODY_PROBE_ERRORS as exc:
        LOG.warning(
            "producer custody capture failed closed: %s",
            type(exc).__name__,
        )
        return None


def _parse_producer_custody(
    custody: dict[str, object] | None,
) -> tuple[int, set[int], str, str] | None:
    if not isinstance(custody, dict) or custody.get("version") != _CUSTODY_VERSION:
        return None
    if set(custody) != {
        "version",
        "host_uuid",
        "boot_session_uuid",
        "resource_coalition_id",
        "trusted_unique_ids",
    }:
        return None
    coalition_id = custody.get("resource_coalition_id")
    trusted_raw = custody.get("trusted_unique_ids")
    host_uuid_raw = custody.get("host_uuid")
    boot_uuid_raw = custody.get("boot_session_uuid")
    if (
        isinstance(coalition_id, bool)
        or not isinstance(coalition_id, int)
        or coalition_id <= 0
        or not isinstance(trusted_raw, list)
        or not trusted_raw
        or len(trusted_raw) >= _COALITION_INFO_PID_LIST_MAX_PIDS
    ):
        return None
    if any(
        isinstance(uniqueid, bool)
        or not isinstance(uniqueid, int)
        or uniqueid <= 0
        for uniqueid in trusted_raw
    ):
        return None
    trusted = set(trusted_raw)
    if len(trusted) != len(trusted_raw):
        return None
    try:
        host_uuid = str(uuid.UUID(host_uuid_raw))
        boot_uuid = str(uuid.UUID(boot_uuid_raw))
    except (AttributeError, TypeError, ValueError) as exc:
        LOG.warning(
            "producer custody UUID contract rejected: %s",
            type(exc).__name__,
        )
        return None
    # Canonical lower-case UUIDs make ledger comparison and strict replay
    # deterministic; alternative textual forms are rejected, not normalized.
    if host_uuid_raw != host_uuid or boot_uuid_raw != boot_uuid:
        return None
    return coalition_id, trusted, host_uuid, boot_uuid


def _unknown_custody_members(
    custody: dict[str, object] | None,
) -> dict[int, int] | None:
    """Return pid -> uniqueid for live, non-trusted members of saved custody."""
    parsed = _parse_producer_custody(custody)
    if parsed is None:
        return None
    coalition_id, saved_trusted, saved_host_uuid, saved_boot_uuid = parsed
    try:
        api = _get_darwin_custody_api()
        current_host_uuid = api.host_uuid()
        current_boot_uuid = api.boot_session_uuid()
        if current_host_uuid != saved_host_uuid:
            # A foreign host cannot prove anything about producers on the
            # authority host. Cross-host release requires an explicit remote
            # drain acknowledgement, which this local ledger does not carry.
            return None
        if current_boot_uuid != saved_boot_uuid:
            # Same physical Mac, later boot: no process or coalition from the
            # saved boot can still exist. Avoid probing a possibly reused ID.
            return {}
        identities = _coalition_identities(api, coalition_id)
        dynamic_trusted: set[int] = set()
        current_pid = os.getpid()
        current_cid = api.resource_coalition_id(current_pid)
        if current_cid == coalition_id:
            dynamic_trusted = _verified_ancestor_uniqueids(
                identities,
                current_pid,
            )
        trusted = saved_trusted | dynamic_trusted
        return {
            pid: uniqueid
            for pid, (uniqueid, _parent_uniqueid) in identities.items()
            if uniqueid not in trusted
        }
    except _CUSTODY_PROBE_ERRORS as exc:
        LOG.warning(
            "producer custody probe failed closed: %s",
            type(exc).__name__,
        )
        return None


def producer_cohort_members_checked(
    pgid: int,
    *,
    job_id: str | None,
    custody: dict[str, object] | None = None,
) -> list[int] | None:
    """Return live producer members, including descendants that called setsid.

    Darwin uses resource-coalition membership plus kernel process unique IDs;
    no command line or environment (and therefore no credential) is read.
    ``job_id`` remains in the interface for caller attribution but is never
    used as a process identity.
    """
    _ = job_id
    if sys.platform == "darwin":
        # The saved resource coalition is the complete Darwin producer
        # authority. Never union a bare PGID into it: once the original group
        # drains, a recycled PGID could name an unrelated process. Avoiding the
        # PGID probe also prevents this observer's `ps` helper from briefly
        # appearing as an unknown member of the shared launchd coalition.
        unknown = _unknown_custody_members(custody)
        if unknown is None:
            return None
        return sorted(unknown)
    group_members = pgid_members_checked(pgid)
    if group_members is None:
        return None
    return sorted(set(group_members))


def producer_custody_all_members_checked(
    custody: dict[str, object] | None,
) -> list[int] | None:
    """Return every live member of one saved Darwin coalition.

    This is deliberately stricter than :func:`producer_cohort_members_checked`:
    it does not exclude the trusted pre-spawn ancestry.  Migration uses it
    after unloading the legacy service so the old wrapper and supervisor must
    both disappear along with every descendant before a new custody ledger can
    be initialized.
    """
    if sys.platform != "darwin":
        return None
    parsed = _parse_producer_custody(custody)
    if parsed is None:
        return None
    coalition_id, _trusted, saved_host_uuid, saved_boot_uuid = parsed
    try:
        api = _get_darwin_custody_api()
        if api.host_uuid() != saved_host_uuid:
            return None
        if api.boot_session_uuid() != saved_boot_uuid:
            return []
        return sorted(_coalition_identities(api, coalition_id))
    except _CUSTODY_PROBE_ERRORS as exc:
        LOG.warning(
            "complete producer custody probe failed closed: %s",
            type(exc).__name__,
        )
        return None


def capture_coalition_drain_reference(
    coalition_id: int,
) -> dict[str, object] | None:
    """Pin one directly identified Darwin coalition for a later drain proof.

    This narrow migration primitive is used only when launchd reports a loaded
    service coalition with no live process to anchor (for example, between two
    crash-loop attempts).  The initial kernel probe must succeed and be empty;
    the caller enforces emptiness before accepting the reference.
    """
    if (
        sys.platform != "darwin"
        or isinstance(coalition_id, bool)
        or not isinstance(coalition_id, int)
        or coalition_id <= 0
    ):
        return None
    try:
        api = _get_darwin_custody_api()
        _coalition_identities(api, coalition_id)
        return {
            "version": _COALITION_DRAIN_REFERENCE_VERSION,
            "host_uuid": api.host_uuid(),
            "boot_session_uuid": api.boot_session_uuid(),
            "resource_coalition_id": coalition_id,
        }
    except _CUSTODY_PROBE_ERRORS as exc:
        LOG.warning(
            "coalition drain reference capture failed closed: %s",
            type(exc).__name__,
        )
        return None


def coalition_drain_members_checked(
    reference: dict[str, object] | None,
) -> list[int] | None:
    """Return all members of a previously pinned Darwin coalition.

    A same-host later boot or kernel-confirmed missing coalition is positively
    drained.  Foreign-host, malformed, and ambiguous probe results fail closed.
    """
    expected_keys = {
        "version",
        "host_uuid",
        "boot_session_uuid",
        "resource_coalition_id",
    }
    if (
        sys.platform != "darwin"
        or not isinstance(reference, dict)
        or set(reference) != expected_keys
        or reference.get("version") != _COALITION_DRAIN_REFERENCE_VERSION
    ):
        return None
    coalition_id = reference.get("resource_coalition_id")
    if (
        isinstance(coalition_id, bool)
        or not isinstance(coalition_id, int)
        or coalition_id <= 0
    ):
        return None
    try:
        saved_host_uuid = str(uuid.UUID(reference.get("host_uuid")))
        saved_boot_uuid = str(uuid.UUID(reference.get("boot_session_uuid")))
    except (AttributeError, TypeError, ValueError) as exc:
        LOG.warning(
            "coalition drain reference UUID contract rejected: %s",
            type(exc).__name__,
        )
        return None
    if (
        reference.get("host_uuid") != saved_host_uuid
        or reference.get("boot_session_uuid") != saved_boot_uuid
    ):
        return None
    try:
        api = _get_darwin_custody_api()
        if api.host_uuid() != saved_host_uuid:
            return None
        if api.boot_session_uuid() != saved_boot_uuid:
            return []
    except _CUSTODY_PROBE_ERRORS as exc:
        LOG.warning(
            "coalition drain probe failed closed: %s",
            type(exc).__name__,
        )
        return None
    try:
        return sorted(_coalition_identities(api, coalition_id))
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return []
        LOG.warning(
            "coalition drain probe failed closed: %s",
            type(exc).__name__,
        )
        return None
    except _DarwinCustodyProbeError as exc:
        LOG.warning(
            "coalition drain probe failed closed: %s",
            type(exc).__name__,
        )
        return None


def kill_producer_cohort(
    custody: dict[str, object] | None,
    *,
    intent: termination.TerminationIntent | None,
    ledger_path=None,
    grace_s: float = DEFAULT_KILL_GRACE_S,
) -> bool:
    """Terminate every unknown custody member and prove the coalition drained.

    Each PID is rechecked against its kernel unique ID immediately before each
    signal. A recycled PID therefore cannot inherit the prior process's kill
    authority. The final answer comes from a fresh kernel coalition probe, not
    from successful signal syscalls.
    """
    if sys.platform != "darwin":
        return False
    if intent is None:
        raise termination.TerminationIntentRequired(
            "kill_producer_cohort requires a durable termination intent"
        )
    if signal.SIGTERM not in intent.signal_sequence or signal.SIGKILL not in intent.signal_sequence:
        raise termination.TerminationIntentMismatch(
            "producer custody requires TERM and KILL authority"
        )
    parsed_custody = _parse_producer_custody(custody)
    if parsed_custody is None:
        return False
    coalition_id, _trusted_uniqueids, _host_uuid, _boot_uuid = parsed_custody
    members = _unknown_custody_members(custody)
    if members is None:
        return False
    if not members:
        return True
    try:
        api = _get_darwin_custody_api()
    except _CUSTODY_PROBE_ERRORS as exc:
        LOG.warning(
            "producer custody kill unavailable: %s",
            type(exc).__name__,
        )
        return False

    def _signal_members(
        members: dict[int, int],
        signum: int,
    ) -> bool:
        all_sent = True
        for pid, expected_uniqueid in members.items():
            def _identity_matches(
                target_pid: int,
                expected: int = expected_uniqueid,
            ) -> bool:
                try:
                    identity_before = api.process_identity(target_pid)
                    if identity_before is None or identity_before[0] != expected:
                        return False
                    observed_cid = api.resource_coalition_id(target_pid)
                    identity_after = api.process_identity(target_pid)
                except _CUSTODY_PROBE_ERRORS as exc:
                    LOG.warning(
                        "producer custody identity recheck failed pid=%d: %s",
                        target_pid,
                        type(exc).__name__,
                    )
                    return False
                return (
                    observed_cid == coalition_id
                    and identity_after == identity_before
                )

            try:
                termination.send_member_pid(
                    intent,
                    pid,
                    signum,
                    ledger_path=ledger_path,
                    identity_verifier=_identity_matches,
                )
            except (
                OSError,
                termination.TerminationIntentError,
            ) as exc:
                LOG.warning(
                    "producer custody signal failed pid=%d signal=%d: %s",
                    pid,
                    signum,
                    type(exc).__name__,
                )
                all_sent = False
        return all_sent

    _signal_members(members, signal.SIGTERM)
    deadline = time.monotonic() + max(0.0, grace_s)
    survivors = members
    while survivors and time.monotonic() < deadline:
        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        survivors = _unknown_custody_members(custody)
        if survivors is None:
            return False
    if grace_s <= 0:
        survivors = _unknown_custody_members(custody)
    if survivors is None:
        return False
    if not survivors:
        return True
    _signal_members(survivors, signal.SIGKILL)
    time.sleep(0.5)
    survivors = _unknown_custody_members(custody)
    return survivors == {}


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
        result = _run_ps_probe(
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
        result = _run_ps_probe(
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
