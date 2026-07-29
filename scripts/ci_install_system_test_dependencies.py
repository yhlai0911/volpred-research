"""Install Ubuntu CI dependencies without surrendering the whole job timeout.

GitHub's Azure Ubuntu mirror once stalled for more than 17 minutes while
downloading ``fonts-noto-cjk``.  A raw ``apt-get`` therefore consumed the
20-minute pytest job budget before pytest started.  This installer keeps the
real runtime dependencies, but bounds each process group and retries only a
finite number of times.  Apt's partial-download cache is deliberately preserved
between attempts.

Every terminating signal is sent through the stdlib-only durable termination
owner.  The installer runs under ``sudo python3`` before the project environment
exists, so it loads that owner directly from its canonical file instead of
importing the dependency-heavy ``volpred.ops`` package.
"""

from __future__ import annotations

import importlib.util
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_TERMINATION_OWNER_PATH = ROOT / "src" / "volpred" / "ops" / "termination.py"
_TERMINATION_SPEC = importlib.util.spec_from_file_location(
    "_volpred_ci_termination_owner",
    _TERMINATION_OWNER_PATH,
)
if _TERMINATION_SPEC is None or _TERMINATION_SPEC.loader is None:
    raise SystemExit(f"cannot load termination owner: {_TERMINATION_OWNER_PATH}")
termination = importlib.util.module_from_spec(_TERMINATION_SPEC)
sys.modules[_TERMINATION_SPEC.name] = termination
_TERMINATION_SPEC.loader.exec_module(termination)

_DEFAULT_TERMINATION_LEDGER = (
    Path(tempfile.gettempdir())
    / f"volpred-ci-termination-{os.getpid()}-{secrets.token_hex(8)}.jsonl"
)

ATTEMPTS = 2
UPDATE_TIMEOUT_SECONDS = 30
INSTALL_TIMEOUT_SECONDS = 120
BACKOFF_SECONDS = 3
TERM_GRACE_SECONDS = 5
KILL_GRACE_SECONDS = 5
PROCESS_GROUP_POLL_SECONDS = 0.05
PROCESS_GROUP_CLEANUP_FAILED = 125
TERMINATION_ACTOR = "ci-install-system-test-dependencies"
TERMINATION_REASON = "apt_attempt_timeout"

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


def _termination_ledger_path() -> Path:
    """Return a runner-local receipt ledger outside the canonical checkout."""
    override = os.environ.get(termination.LEDGER_PATH_ENV)
    return Path(override) if override else _DEFAULT_TERMINATION_LEDGER


def _process_group_drained(process: subprocess.Popen[bytes]) -> bool:
    process.poll()
    return not _process_group_exists(process.pid)


def _terminate_process_group(process: subprocess.Popen[bytes]) -> bool:
    process_group_id = process.pid
    try:
        intent = termination.arm(
            target_kind="pgid",
            target_id=process_group_id,
            reason=TERMINATION_REASON,
            actor=TERMINATION_ACTOR,
            signal_sequence=[signal.SIGTERM, signal.SIGKILL],
            ledger_path=_termination_ledger_path(),
        )
    except (termination.TerminationIntentError, OSError) as exc:
        # Fail closed: without a durable pre-signal receipt, no system-owned
        # terminating syscall may be issued.
        print(f"[ci-deps] cannot arm termination intent: {exc}", flush=True)
        return _process_group_drained(process)

    for signum, grace_seconds in (
        (signal.SIGTERM, TERM_GRACE_SECONDS),
        (signal.SIGKILL, KILL_GRACE_SECONDS),
    ):
        try:
            status = termination.send_pgid(
                intent,
                signum,
                ledger_path=_termination_ledger_path(),
            )
        except (termination.TerminationIntentError, OSError) as exc:
            print(
                f"[ci-deps] termination refused signum={signum}: {exc}",
                flush=True,
            )
            return _process_group_drained(process)
        except PermissionError:  # silent-ok: False becomes explicit rc125 and aborts retry
            return False
        if status == "gone":
            process.poll()
            return True
        if _wait_for_process_group_exit(
            process,
            timeout_seconds=grace_seconds,
        ):
            return True
    return False


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
