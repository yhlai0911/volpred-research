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
from datetime import datetime, timezone
from pathlib import Path

from . import state

LOG = logging.getLogger(__name__)

SRC_DIR = Path(__file__).resolve().parent

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

# One self-reload per process. The boot-time comparison already makes looping
# impossible; this makes it impossible twice.
_ARMED = True


def stale_sources(
    *,
    src_dir: Path = SRC_DIR,
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
    if not src_dir.is_dir():
        return out
    for src in sorted(src_dir.glob("*.py")):
        try:
            mtime = datetime.fromtimestamp(src.stat().st_mtime, tz=timezone.utc)
        except OSError as exc:
            LOG.warning("selfreload: source unreadable during scan path=%s err=%s", src, exc)
            continue
        if boot < mtime <= now:
            out.append((src.name, mtime))
    return out


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
    now: datetime | None = None,
    quiesce_s: float = QUIESCE_S,
    marker_path: Path | None = None,
    exit_fn=None,
) -> str:
    """Reload this daemon if its own code changed and it is idle. Returns the action.

    Fail-open in the strictest sense: every failure path here leaves the daemon
    running the (stale) code it already had. A self-reload that cannot happen is
    a missed improvement; a self-reload that fires mid-fire would destroy work.
    """
    global _ARMED

    now = now or datetime.now(timezone.utc)

    snapshot = state.read_state(state_path)
    boot_raw = snapshot.get("supervisor_started_at")
    boot = _parse_iso(boot_raw)
    if boot is None:
        LOG.warning("selfreload: no supervisor_started_at in %s — cannot judge code freshness",
                    state_path)
        return _NO_STALE

    stale = stale_sources(src_dir=src_dir, boot=boot, now=now)
    in_flight = len(state.get_current_jobs(state_path))
    action, reason = decide(stale=stale, in_flight=in_flight, now=now, quiesce_s=quiesce_s)

    if action == _NO_STALE:
        return action

    if action != _RELOAD:
        LOG.info("selfreload: %s — %s", action, reason)
        return action

    if not _ARMED:
        LOG.warning("selfreload: already reloaded once this process — not firing again (%s)", reason)
        return _NO_STALE
    _ARMED = False

    LOG.warning("selfreload: RELOADING — %s", reason)
    # Same order the reload wrapper uses: the marker must exist BEFORE we die, or
    # the fresh boot reports itself as an unexpected crash and emails the owner
    # deploy noise.
    try:
        # Resolve the marker path at CALL time, not definition time. `state`'s own
        # `path=RESTART_MARKER_PATH` default binds when the function is defined, so
        # a test redirecting `state.RESTART_MARKER_PATH` would still write to the
        # LIVE marker — the same trap supervisor.py documents at `mark_supervisor_started`.
        state.write_planned_restart_marker(
            reason=f"self-reload: {reason}",
            path=marker_path or state.RESTART_MARKER_PATH,
        )
    except OSError as exc:
        # Losing the marker costs one spurious "supervisor restarted" INFO alert.
        # It does not justify continuing to run code we know is stale.
        LOG.warning("selfreload: could not write planned-restart marker (%s) — "
                    "reloading anyway; expect one restart alert", exc)

    (exit_fn or _sigterm_self)()
    return _RELOAD


def _sigterm_self() -> None:
    """Exactly what `launchctl kickstart -k` delivers (exit 143). `KeepAlive` in
    the plist respawns us — on the new code."""
    os.kill(os.getpid(), signal.SIGTERM)


def _parse_iso(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError as exc:
        LOG.warning("selfreload: unparseable supervisor_started_at=%r (%s)", raw, exc)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
