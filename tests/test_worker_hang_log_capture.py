"""Hang-log capture gate (2026-07-18).

Regression lock for the "hang SIGKILL'd → worker log 0 bytes → diagnosis
impossible" bug. `worker._spawn` redirects a child's combined stdout+stderr to
a plain-file fd. Such an fd is block-buffered by default, so a child that writes
a line and then hangs keeps that line in its in-process buffer; when the
supervisor SIGKILL's the hung process group the buffer dies with it and the log
lands 0 bytes — precisely the fires the hang alert (`alerts.read_log_tail`) most
needs to show. The fix: `_spawn` forces `PYTHONUNBUFFERED=1` into the child env
so python children flush each line to the OS page cache, which survives SIGKILL.

The test is deliberately NOT hollow: the same block-buffered, must-hang child is
run once through `_spawn` (marker MUST survive the kill) and once through a bare
`subprocess.Popen(stdout=file)` WITHOUT the unbuffering fix (marker MUST be lost).
The control proves both that the bug is real and that `_spawn`'s fix is what makes
the difference — if the fix regresses, the _spawn assertion goes red.

Scope note (honest): the fix helps python children only. The real hourly child
is the `claude` CLI (Node), which writes to a regular-file fd synchronously and
already survives SIGKILL regardless — see `_spawn` docstring.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
import uuid
from pathlib import Path

from scripts.dispatch_supervisor import worker


def _hang_child_argv(marker: str) -> list[str]:
    """A child that writes `marker` then sleeps ~forever.

    No `-u`: with stdout pointed at a file this is block-buffered, so the marker
    stays in-process until an explicit flush that never comes before SIGKILL.
    This is the exact shape that produced the 0-byte hang logs.
    """
    import sys

    return [
        sys.executable,
        "-c",
        f"import sys,time; sys.stdout.write({marker!r} + '\\n'); time.sleep(600)",
    ]


def _clean_env_without_unbuffered() -> dict[str, str]:
    """Parent env minus PYTHONUNBUFFERED, so neither branch inherits the fix by
    accident (the test must not depend on how the suite itself was launched)."""
    return {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}


def _kill_group_and_wait(pid: int) -> None:
    os.killpg(os.getpgid(pid), signal.SIGKILL)
    # reap so the pgid is free and the fd is closed before we read the log
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass  # silent-ok: already reaped — the only outcome we wanted anyway


def test_spawn_preserves_stdout_when_child_sigkilled(tmp_path: Path) -> None:
    """FIX path: a hung child SIGKILL'd mid-run still leaves its line in the log."""
    marker = f"HANGMARKER_{uuid.uuid4().hex}"
    log_path = tmp_path / "worker.log"

    proc = worker._spawn(
        argv=_hang_child_argv(marker),
        log_path=log_path,
        env=_clean_env_without_unbuffered(),  # _spawn itself must add the unbuffer
    )
    try:
        time.sleep(1.0)  # let the child start and write its line
        _kill_group_and_wait(proc.pid)
    finally:
        if proc.poll() is None:
            _kill_group_and_wait(proc.pid)

    contents = log_path.read_text(encoding="utf-8")
    assert marker in contents, (
        "hang-killed child's stdout was lost — worker log would be 0 bytes and "
        f"the hang alert unusable. got {len(contents)} bytes: {contents!r}"
    )


def test_bare_popen_control_loses_stdout_proving_bug_is_real(tmp_path: Path) -> None:
    """NON-HOLLOW control: the identical child under a bare block-buffered Popen
    (no unbuffering) loses its line on SIGKILL. If this ever passes, the bug the
    fix targets isn't being reproduced and the fix test is meaningless."""
    marker = f"HANGMARKER_{uuid.uuid4().hex}"
    log_path = tmp_path / "bare.log"

    with log_path.open("ab") as log_fh:
        proc = subprocess.Popen(
            _hang_child_argv(marker),
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # own pgid, matches _spawn's kill model
            env=_clean_env_without_unbuffered(),
        )
    try:
        time.sleep(1.0)
        _kill_group_and_wait(proc.pid)
    finally:
        if proc.poll() is None:
            _kill_group_and_wait(proc.pid)

    contents = log_path.read_text(encoding="utf-8")
    assert marker not in contents, (
        "control child unexpectedly flushed before SIGKILL — the block-buffer "
        f"bug is not being reproduced, so the fix test proves nothing. got: {contents!r}"
    )
