"""Self-reload — the daemon notices its own code changed and restarts itself.

## Why this exists

The supervisor executes the copy of `scripts/dispatch_supervisor/*.py` it
imported at boot. Editing those files changes nothing until the process is
restarted. A daemon running stale code is *observationally identical* to a
healthy one: fresh heartbeat, jobs completing, zero alerts.

`volpred.ops.alerts._parse_dispatch_supervisor_stale_code_state` already
DETECTS this (added 2026-07-10, after three fixes shipped and none went live).
`scripts/reload_dispatch_supervisor.sh` already RELOADS safely (waits for the
worker to clear, drops a planned-restart marker, `kickstart -k`).

What was missing is the wire between them. The detector's only actuator was an
email asking a human to go press the button — the "alert as a chore" antipattern
the owner has flagged repeatedly. On 2026-07-13 that gap produced the exact
failure it was built to catch, twice in one evening:

  - 15:19  procutil.py descendant-tree kill fix — written, committed, not live.
  - 21:53  phase_z.py livelock fix + 22:04 alert-dedup fix — written, committed,
           not live. The daemon (booted 17:58) kept running the pre-fix code and
           kept emailing the owner every 64 seconds. He asked, reasonably, why
           the thing we said we fixed was still happening. It was still
           happening because *nothing we fixed had ever run*.

This module removes the human from the loop. Detection and reload were both
already correct; they just were not connected to each other.

The monitored image includes both the daemon package and ``src/volpred/ops``.
That second root is load-bearing: ``workspace.py`` imports the legacy queue
writer at boot. On 2026-07-23 the direct-execution admission guard shipped in
``volpred.ops.next_tasks`` while the daemon package itself was unchanged, so
the original single-directory scanner left the live daemon able to append one
new remediation task through its old in-memory writer.

## The rule

A source file whose mtime is newer than `supervisor_started_at` is, by
definition, not the code that is running. When that is true and the daemon is
idle, it reloads itself — same mechanism the reload wrapper uses (planned-restart
marker, then SIGTERM; launchd's `KeepAlive` respawns us on the new code).

## Why it cannot restart-loop

The boot timestamp is restamped on every start, so after a reload every source
file is older than boot and `stale_sources()` returns empty. Files dated in the
*future* (clock skew) are excluded rather than treated as stale, which is the
only other way the comparison could stay true forever. Belt and braces: each
process self-reloads at most once (`_ARMED`).
"""
from __future__ import annotations

import logging
import os
import signal
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from volpred.ops import termination

from . import state

LOG = logging.getLogger(__name__)

CANONICAL_REPO_ROOT = Path(
    os.environ.get("VOLPRED_CANONICAL_REPO_ROOT", Path.cwd())
).resolve()
SRC_DIR = CANONICAL_REPO_ROOT / "scripts" / "dispatch_supervisor"
OPS_CORE_SRC_DIR = CANONICAL_REPO_ROOT / "src" / "volpred" / "ops"
SOURCE_ROOTS = (SRC_DIR, OPS_CORE_SRC_DIR)

# An agent editing several modules writes them seconds apart. Reloading on the
# first save would boot us onto a half-applied change set, so the NEWEST edit
# must have settled this long before we act.
QUIESCE_S = 90

# Reloading mid-fire SIGTERMs the daemon while a worker is running — the worker
# is a child process group and would be orphaned or killed with its work
# uncommitted. Idle means idle.
_IN_FLIGHT_DEFER = "deferred_in_flight"
_QUIESCING_DEFER = "deferred_quiescing"
_NO_STALE = "current"
_RELOAD = "reload"
_RELOAD_REQUESTED = "reload_request_armed"

# One self-reload per process. The boot-time comparison already makes looping
# impossible; this makes it impossible twice.
_ARMED = True


def stale_sources(
    *,
    src_dir: Path = SRC_DIR,
    source_roots: Iterable[Path] | None = None,
    boot: datetime,
    now: datetime,
) -> list[tuple[str, datetime]]:
    """Source files newer than the running process's boot — i.e. not what's running.

    Files with a future mtime are NOT stale. A clock skew or a bad `touch` would
    otherwise keep the comparison true across every restart, turning self-reload
    into a boot loop. Unreadable files are skipped loudly (a supervisor source
    that vanished mid-scan is worth a word, not a shrug).
    """
    out: list[tuple[str, datetime]] = []
    roots = _source_roots(src_dir=src_dir, source_roots=source_roots)
    sources: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root.is_dir():
            candidates = root.rglob("*.py")
        elif root.suffix == ".py":
            candidates = (root,)
        else:
            continue
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            sources.append(candidate)

    for src in sorted(sources):
        try:
            mtime = datetime.fromtimestamp(src.stat().st_mtime, tz=UTC)
        except OSError as exc:
            LOG.warning("selfreload: source unreadable during scan path=%s err=%s", src, exc)
            continue
        if boot < mtime <= now:
            out.append((src.name, mtime))
    return out


def _source_roots(
    *,
    src_dir: Path,
    source_roots: Iterable[Path] | None,
) -> tuple[Path, ...]:
    """Resolve production roots while keeping explicit test roots hermetic."""

    if source_roots is not None:
        return tuple(Path(root) for root in source_roots)
    if Path(src_dir) == SRC_DIR:
        return SOURCE_ROOTS
    return (Path(src_dir),)


def decide(
    *,
    stale: list[tuple[str, datetime]],
    in_flight: int,
    now: datetime,
    quiesce_s: float = QUIESCE_S,
) -> tuple[str, str]:
    """Pure decision: (action, human-readable reason). No side effects."""
    if not stale:
        return _NO_STALE, "running code matches disk"

    names = ", ".join(name for name, _ in stale)
    newest = max(mtime for _, mtime in stale)
    settled_for = (now - newest).total_seconds()

    if in_flight > 0:
        # Not an error — the common case is a fire that just edited these very
        # files. We reload the moment it lands.
        return _IN_FLIGHT_DEFER, f"{len(stale)} stale module(s) ({names}); {in_flight} job(s) in flight"

    if settled_for < quiesce_s:
        return _QUIESCING_DEFER, (
            f"{len(stale)} stale module(s) ({names}); newest edit only "
            f"{settled_for:.0f}s old, waiting for {quiesce_s:.0f}s of quiet"
        )

    return _RELOAD, f"{len(stale)} module(s) newer than boot ({names})"


def maybe_self_reload(
    *,
    state_path: Path = state.STATE_PATH,
    src_dir: Path = SRC_DIR,
    source_roots: Iterable[Path] | None = None,
    now: datetime | None = None,
    quiesce_s: float = QUIESCE_S,
    marker_path: Path | None = None,
    exit_fn=None,
    arm_fn=None,
) -> str:
    """Reload this daemon if its own code changed and it is idle. Returns the action.

    Fail-open in the strictest sense: every failure path here leaves the daemon
    running the (stale) code it already had. A self-reload that cannot happen is
    a missed improvement; a self-reload that fires mid-fire would destroy work.
    """
    now = now or datetime.now(UTC)

    snapshot = state.read_state(state_path)
    boot_raw = snapshot.get("supervisor_started_at")
    boot = _parse_iso(boot_raw)
    if boot is None:
        LOG.warning("selfreload: no supervisor_started_at in %s — cannot judge code freshness",
                    state_path)
        return _NO_STALE

    stale = stale_sources(
        src_dir=src_dir,
        source_roots=source_roots,
        boot=boot,
        now=now,
    )
    # Worker exit is not fire completion: the durable PHASE-Z generation still
    # owns a closeout token until ``finish_phase_z`` commits or rejects it.
    # Reloading in that narrow window caused the fresh process to execute the
    # old token against a missing singleton baseline (Issue #42).
    # Use one atomic-file snapshot for both sides of the transition. Mixing an
    # old pending list with a fresh current_jobs read recreates the exact race:
    # the worker can move current_jobs -> phase_z_pending between those reads
    # and momentarily appear in neither collection.
    pending_closeouts = len(snapshot.get("phase_z_pending") or [])
    in_flight = len(snapshot.get("current_jobs") or []) + pending_closeouts
    action, reason = decide(stale=stale, in_flight=in_flight, now=now, quiesce_s=quiesce_s)

    if action == _NO_STALE:
        return action

    if action != _RELOAD:
        LOG.info("selfreload: %s — %s", action, reason)
        return action

    # Never signal directly from the mutable authoring checkout.  Arm an
    # immutable committed release; the health loop consumes it on the next
    # tick and the stable bootstrap loads only those pinned bytes.
    if arm_fn is None:
        from . import deferred_reload

        arm_fn = deferred_reload.arm
    explicit_roots = _source_roots(
        src_dir=src_dir,
        source_roots=source_roots,
    )
    production_roots = source_roots is None and Path(src_dir) == SRC_DIR
    try:
        request = arm_fn(
            reason=f"self-reload: {reason}",
            state_path=state_path,
            source_roots=None if production_roots else explicit_roots,
        )
    except Exception:
        LOG.exception("selfreload: immutable release request failed")
        return _NO_STALE
    LOG.warning(
        "selfreload: immutable release request armed request_id=%s — %s",
        str(request.get("request_id") or "")[:12],
        reason,
    )
    return _RELOAD_REQUESTED


def reload_now(
    *,
    reason: str,
    marker_path: Path | None = None,
    exit_fn=None,
) -> bool:
    """Perform one planned self-termination for this exact process image.

    This is the single reload actuator shared by mtime self-reload and the
    durable deferred-request owner.  ``False`` means another path already armed
    this process; callers must not create a second termination intent.
    """
    global _ARMED
    if not _ARMED:
        LOG.warning(
            "selfreload: process reload already armed — refusing duplicate (%s)",
            reason,
        )
        return False
    _ARMED = False

    # Same order the reload wrapper uses: the marker must exist BEFORE we die, or
    # the fresh boot reports itself as an unexpected crash and emails the owner
    # deploy noise.
    try:
        # Resolve the marker path at CALL time, not definition time. `state`'s own
        # `path=RESTART_MARKER_PATH` default binds when the function is defined, so
        # a test redirecting `state.RESTART_MARKER_PATH` would still write to the
        # LIVE marker — the same trap supervisor.py documents at `mark_supervisor_started`.
        state.write_planned_restart_marker(
            reason=reason,
            path=marker_path or state.RESTART_MARKER_PATH,
        )
    except OSError as exc:
        # Losing the marker costs one spurious "supervisor restarted" INFO alert.
        # It does not justify continuing to run code we know is stale.
        LOG.warning("selfreload: could not write planned-restart marker (%s) — "
                    "reloading anyway; expect one restart alert", exc)

    (exit_fn or _sigterm_self)()
    return True


def _sigterm_self() -> None:
    """Exactly what `launchctl kickstart -k` delivers (exit 143). `KeepAlive` in
    the plist respawns us — on the new code."""
    intent = termination.arm(
        target_kind="pid",
        target_id=os.getpid(),
        reason="supervisor_self_reload",
        actor="dispatch-supervisor.selfreload",
        signal_sequence=[signal.SIGTERM],
    )
    termination.send_pid(intent, signal.SIGTERM)


def _parse_iso(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError as exc:
        LOG.warning("selfreload: unparseable supervisor_started_at=%r (%s)", raw, exc)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
