"""Install Ubuntu CI dependencies without surrendering the whole job timeout.

GitHub's Azure Ubuntu mirror once stalled for more than 17 minutes while
downloading ``fonts-noto-cjk``.  A raw ``apt-get`` therefore consumed the
20-minute pytest job budget before pytest started.  This installer keeps the
real runtime dependencies, but bounds each process group and retries only a
finite number of times.  Apt's partial-download cache is deliberately preserved
between attempts.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

ATTEMPTS = 2
UPDATE_TIMEOUT_SECONDS = 30
INSTALL_TIMEOUT_SECONDS = 120
BACKOFF_SECONDS = 3
TERM_GRACE_SECONDS = 5
KILL_GRACE_SECONDS = 5
PROCESS_GROUP_POLL_SECONDS = 0.05
PROCESS_GROUP_CLEANUP_FAILED = 125

APT_NETWORK_OPTIONS = (
    "-o",
    "Acquire::Retries=2",
    "-o",
    "Acquire::http::Timeout=20",
    "-o",
    "Acquire::https::Timeout=20",
    "-o",
    "DPkg::Lock::Timeout=20",
)
UPDATE_COMMAND = ("apt-get", *APT_NETWORK_OPTIONS, "update")
INSTALL_COMMAND = (
    "apt-get",
    *APT_NETWORK_OPTIONS,
    "install",
    "-y",
    "--no-install-recommends",
    "ripgrep",
    "fonts-noto-cjk",
)


@dataclass(frozen=True)
class AttemptResult:
    returncode: int
    timed_out: bool = False


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:  # silent-ok: signal-0 uses ESRCH as the normal "group exited" verdict
        return False
    except PermissionError:  # silent-ok: uncertain liveness is conservatively treated as still alive
        return True
    return True


def _wait_for_process_group_exit(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: int,
) -> bool:
    process_group_id = process.pid
    deadline = time.monotonic() + timeout_seconds
    while True:
        # Reap the direct leader without blocking. Otherwise a dead sudo zombie
        # can keep killpg(pgid, 0) positive and masquerade as a live descendant.
        process.poll()
        if not _process_group_exists(process_group_id):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(PROCESS_GROUP_POLL_SECONDS, remaining))


def _terminate_process_group(process: subprocess.Popen[bytes]) -> bool:
    process_group_id = process.pid
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:  # silent-ok: group exited between the liveness probe and TERM
        process.poll()
        return True
    except PermissionError:  # silent-ok: False becomes explicit rc125 and aborts retry
        return False
    if _wait_for_process_group_exit(
        process,
        timeout_seconds=TERM_GRACE_SECONDS,
    ):
        return True

    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:  # silent-ok: group exited during the TERM grace window
        process.poll()
        return True
    except PermissionError:  # silent-ok: False becomes explicit rc125 and aborts retry
        return False
    terminated = _wait_for_process_group_exit(
        process,
        timeout_seconds=KILL_GRACE_SECONDS,
    )
    return terminated


def run_bounded(
    command: Sequence[str],
    *,
    timeout_seconds: int,
) -> AttemptResult:
    """Run one command in its own process group and kill the whole group on timeout."""
    process = subprocess.Popen(tuple(command), start_new_session=True)
    try:
        return AttemptResult(process.wait(timeout=timeout_seconds))
    except subprocess.TimeoutExpired:
        terminated = _terminate_process_group(process)
        return AttemptResult(
            returncode=124 if terminated else PROCESS_GROUP_CLEANUP_FAILED,
            timed_out=True,
        )


Runner = Callable[..., AttemptResult]
Sleeper = Callable[[float], None]


def run_with_retry(
    label: str,
    command: Sequence[str],
    *,
    timeout_seconds: int,
    runner: Runner = run_bounded,
    sleeper: Sleeper = time.sleep,
) -> bool:
    for attempt in range(1, ATTEMPTS + 1):
        print(
            f"[ci-deps] {label} attempt={attempt}/{ATTEMPTS} "
            f"timeout={timeout_seconds}s",
            flush=True,
        )
        result = runner(command, timeout_seconds=timeout_seconds)
        if result.returncode == 0:
            return True
        print(
            f"[ci-deps] {label} failed rc={result.returncode} "
            f"timed_out={str(result.timed_out).lower()}",
            flush=True,
        )
        if result.returncode == PROCESS_GROUP_CLEANUP_FAILED:
            print(
                f"[ci-deps] {label} cleanup incomplete; refusing overlapping retry",
                flush=True,
            )
            return False
        if attempt < ATTEMPTS:
            sleeper(BACKOFF_SECONDS)
    return False


def main() -> int:
    if os.geteuid() != 0:
        print(
            "[ci-deps] must run as root so timeout cleanup can kill apt/dpkg descendants",
            flush=True,
        )
        return 2
    if not run_with_retry(
        "apt-index",
        UPDATE_COMMAND,
        timeout_seconds=UPDATE_TIMEOUT_SECONDS,
    ):
        return 1
    if not run_with_retry(
        "runtime-packages",
        INSTALL_COMMAND,
        timeout_seconds=INSTALL_TIMEOUT_SECONDS,
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
