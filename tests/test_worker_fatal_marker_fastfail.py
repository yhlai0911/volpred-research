"""Terse-CLI-fatal fast-fail gate (2026-07-20).

Regression lock for "dead on arrival, reaped 16 minutes later". On 2026-07-20
five dispatch fires produced a worker log of exactly 15 bytes — `Execution
error`, no trailing newline — because `claude -p` hit a fatal before doing any
work and then **failed to exit**. Nothing detected that: the hang cap is the
only reaper, so each fire burned ~960s of its 50-minute slot and mailed a
CRITICAL hang alert about a frozen agent that had never started.

The fix makes the worker itself notice the shape (`failure_class
.is_terse_fatal_only` + an output-stall grace window), kill the group in
seconds, hand the task-pool claim straight back, and classify the attempt as
transient rather than as a hang.

The fixtures below are the real incident bytes, and the false-positive test uses
the real counter-example: worker log `slot-1.4684d8b7` line 15 is ordinary agent
prose that happens to contain the phrase `Execution error`. Matching that would
kill a healthy fire, so the detector must not.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import failure_class, worker

# The exact bytes of dispatch_supervisor_worker.slot-1.46f4806a.log (15 bytes,
# no trailing newline) — five fires on 2026-07-20 produced this file verbatim.
INCIDENT_LOG = "Execution error"
# Real prose from worker log slot-1.4684d8b7 line 15: a healthy fire's own
# narration of an EARLIER incident. Must never be read as a fatal marker.
INCIDENT_PROSE = (
    "盤點才發現父 job 08:00 起跑後即刻 `Execution error`、artifact 是舊的不能當成果；"
    "之後有別的行為者把第三輪 review 推到 round 4。"
)


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (INCIDENT_LOG, True),                 # the 15-byte incident shape
        ("Execution error\n", True),          # same, with the newline a CLI may add
        ("  Execution error  \n\n", True),    # padded / blank-line tolerant
        (INCIDENT_PROSE, False),              # phrase embedded in real agent prose
        ("Execution error\nStarting task 1\n", False),  # it kept working
        ("", False),                          # a healthy in-flight run: empty log
        (None, False),
    ],
)
def test_is_terse_fatal_only_matches_only_the_dead_shape(output, expected) -> None:
    assert failure_class.is_terse_fatal_only(output) is expected


def test_classify_maps_the_sentinel_to_its_own_category() -> None:
    """Fast-fail must NOT land in the hang bucket — hang means no-retry + alert."""
    assert worker._classify(worker.FATAL_FASTFAIL_SENTINEL, INCIDENT_LOG) == "fatal_fastfail"
    assert worker._classify(worker.TIMEOUT_KILLED_SENTINEL, INCIDENT_LOG) == "hang"


def _dead_on_arrival_argv(log_path: Path) -> list[str]:
    """A child that reproduces the incident: print the marker, then never exit.

    Writes the marker with no newline and flushes, exactly like the 15-byte
    logs, then sleeps far past any grace window this test would tolerate.
    """
    return [
        sys.executable, "-c",
        f"import sys,time; sys.stdout.write({INCIDENT_LOG!r}); sys.stdout.flush(); time.sleep(600)",
    ]


def test_dead_on_arrival_child_is_reaped_in_seconds_not_at_the_hang_cap(
    tmp_path: Path,
) -> None:
    """The whole point: seconds, not the 50-minute cap, and killed for real."""
    log_path = tmp_path / "worker.log"
    proc = worker._spawn(argv=_dead_on_arrival_argv(log_path), log_path=log_path)
    started = time.time()
    try:
        verdict, raw_exit = worker._wait_with_fatal_probe(
            proc, log_path=log_path, log_offset=0,
            timeout_s=600,   # stands in for the real hang cap: must NOT be reached
            stall_s=1.0, poll_s=0.1,
        )
        elapsed = time.time() - started
        assert verdict == "fatal_stall", (
            f"probe returned {verdict!r} — a dead-on-arrival CLI would again be "
            "left to the hang cap, costing the rest of the slot"
        )
        assert raw_exit is None
        assert elapsed < 30, f"took {elapsed:.1f}s — that is hang-cap territory, not fast-fail"
    finally:
        worker._kill_pgid(proc.pid and __import__("os").getpgid(proc.pid))
        proc.wait(timeout=15)


def test_working_child_is_never_fast_failed(tmp_path: Path) -> None:
    """Non-hollow control: a child that keeps producing output must survive the
    probe and be allowed to exit normally. If this ever goes red the detector
    has become able to kill healthy fires — the one failure mode worse than the
    bug it fixes."""
    log_path = tmp_path / "worker.log"
    proc = worker._spawn(
        argv=[
            sys.executable, "-c",
            "import sys,time\n"
            f"sys.stdout.write({INCIDENT_LOG!r}); sys.stdout.flush()\n"  # then recovers
            "for i in range(6):\n"
            "    time.sleep(0.2); sys.stdout.write('working %d\\n' % i); sys.stdout.flush()\n",
        ],
        log_path=log_path,
    )
    try:
        verdict, raw_exit = worker._wait_with_fatal_probe(
            proc, log_path=log_path, log_offset=0,
            timeout_s=60, stall_s=0.5, poll_s=0.1,
        )
        assert verdict == "exited", f"a working child was fast-failed ({verdict})"
        assert raw_exit == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_run_worker_releases_the_claim_and_sends_no_hang_alert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end: fast-fail releases the task claim on the spot, records the
    named receipt, and does NOT take the hang path (no CRITICAL, and retry is
    allowed — hang's no-retry contract must not leak onto this shape)."""
    from scripts.dispatch_supervisor import claim_release, state

    state_path = tmp_path / "dispatch_state.json"
    log_path = tmp_path / "worker.log"
    fake_cli = tmp_path / "fake_claude"
    # argv: [bin, -p, ...flags..., prompt] — the fake ignores them all and just
    # reproduces the incident: marker to stdout, no newline, then never exits.
    argv_log = tmp_path / "argv.txt"
    fake_cli.write_text(
        f"#!/bin/sh\necho \"$@\" >> {argv_log}\nprintf 'Execution error'\nsleep 600\n",
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)

    released: list[dict] = []
    monkeypatch.setattr(
        claim_release, "repend_killed_job_claims",
        lambda **kw: released.append(kw) or ["task-under-test"],
    )
    monkeypatch.setattr(
        worker.alerts, "send_hang_alert",
        lambda **kw: pytest.fail("hang alert sent for a fast-fail — the CRITICAL noise is back"),
    )
    monkeypatch.setattr(
        worker.alerts, "send_completion_failure", lambda **kw: None,
    )
    monkeypatch.setattr(worker, "FATAL_STALL_S", 1.0)
    monkeypatch.setattr(worker, "FATAL_POLL_S", 0.1)

    started = time.time()
    result = worker.run_worker(
        prompt_text="noop", log_path=log_path, state_path=state_path,
        claude_bin=str(fake_cli), timeout_s=600, max_attempts=2,
        sleep_fn=lambda _s: None,  # skip the 90s transient backoff
    )
    elapsed = time.time() - started

    assert result.outcome != "killed_timeout", "fast-fail must not be recorded as a hang"
    assert elapsed < 60, f"took {elapsed:.1f}s — the hang cap was still doing the reaping"
    assert released, "the dead fire's task-pool claim was never handed back"
    assert all(kw["source"] == "worker-fatal-fastfail" for kw in released)
    assert len(released) == 2, "each fast-failed attempt must release its own claim"

    outcomes = [c.get("outcome") for c in state.read_state(state_path).get("completions") or []]
    assert "fatal_fastfail" in outcomes, (
        f"no transient receipt naming the shape; completions recorded {outcomes}"
    )

    # Debug sidecar staging (2026-07-21 redesign): EVERY attempt requests one.
    # The sidecar is now the DOA liveness channel, and all observed
    # dead-on-arrivals happened on attempt 1 — exactly the attempt that used to
    # run without it. `--debug-file` writes to its own file, so the main log
    # the marker probe reads stays pristine either way.
    attempts_argv = argv_log.read_text(encoding="utf-8").splitlines()
    assert len(attempts_argv) == 2
    assert all("--debug-file" in line for line in attempts_argv), (
        "an attempt ran without a debug sidecar — the DOA detector is blind "
        "for that attempt and a 2026-07-20/21 Execution-error repeat would "
        "again wait out the hang cap"
    )


# ── sidecar-liveness DOA detection (2026-07-21, third strike redesign) ────────
# The marker almost never reaches the main log while the child is alive — the
# CLI flushes it at kill time (every incident log has mtime == kill time), and
# a healthy run writes nothing to the main log for tens of minutes. These pins
# hold the replacement signal: debug-sidecar growth as positive proof of life.


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0


class _NeverExits:
    """A child that never exits: wait() consumes the poll interval and times out."""

    def __init__(self, clock: _Clock) -> None:
        self._clock = clock

    def wait(self, timeout: float | None = None):
        self._clock.t += timeout or 0.0
        raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout or 0.0)


def _probe(clock: _Clock, proc, *, log: Path, debug: Path, timeout_s: float):
    return worker._wait_with_fatal_probe(
        proc, log_path=log, log_offset=0, timeout_s=timeout_s,
        debug_path=debug, poll_s=5.0, now_fn=lambda: clock.t,
    )


def test_sidecar_frozen_at_startup_is_fast_failed(tmp_path: Path) -> None:
    """The 00:07 incident shape: debug wrote a little at birth, froze, main log
    stayed empty until the kill flushed the marker. Must be reaped in minutes."""
    log = tmp_path / "worker.log"
    log.write_bytes(b"")
    debug = tmp_path / "worker.attempt1.debug.log"
    debug.write_bytes(b"[DEBUG] startup\n" * 20)
    clock = _Clock()

    verdict, _ = _probe(clock, _NeverExits(clock), log=log, debug=debug, timeout_s=3000)

    assert verdict == "fatal_stall"
    assert clock.t < 600, f"reaped at t={clock.t:.0f}s — the hang cap was still the reaper"


def test_sidecar_never_written_is_fast_failed(tmp_path: Path) -> None:
    """CLI died before creating its sidecar at all: zero positive signal ever."""
    log = tmp_path / "worker.log"
    log.write_bytes(b"")
    debug = tmp_path / "never_created.debug.log"
    clock = _Clock()

    verdict, _ = _probe(clock, _NeverExits(clock), log=log, debug=debug, timeout_s=3000)

    assert verdict == "fatal_stall"
    assert clock.t <= worker.SIDECAR_DEAD_S + 10


def test_growing_sidecar_is_never_fast_failed(tmp_path: Path) -> None:
    """A healthy silent agent: main log empty for the whole run, sidecar alive."""
    log = tmp_path / "worker.log"
    log.write_bytes(b"")
    debug = tmp_path / "worker.attempt1.debug.log"
    debug.write_bytes(b"")
    clock = _Clock()

    class _HealthyNeverExits(_NeverExits):
        def wait(self, timeout: float | None = None):
            with debug.open("ab") as fh:
                fh.write(b"[DEBUG] api event\n")
            return super().wait(timeout)

    verdict, _ = _probe(clock, _HealthyNeverExits(clock), log=log, debug=debug,
                        timeout_s=900)

    assert verdict == "timeout", "a live sidecar must leave the reaping to the hang cap"


def test_sidecar_freeze_after_startup_window_is_left_to_the_hang_cap(tmp_path: Path) -> None:
    """Went quiet AFTER real progress (long tool run shape) — never fast-failed."""
    log = tmp_path / "worker.log"
    log.write_bytes(b"")
    debug = tmp_path / "worker.attempt1.debug.log"
    debug.write_bytes(b"")
    clock = _Clock()

    class _GrowsThenFreezes(_NeverExits):
        def wait(self, timeout: float | None = None):
            if self._clock.t < worker.SIDECAR_STARTUP_WINDOW_S + 60:
                with debug.open("ab") as fh:
                    fh.write(b"[DEBUG] api event\n")
            return super().wait(timeout)

    verdict, _ = _probe(clock, _GrowsThenFreezes(clock), log=log, debug=debug,
                        timeout_s=1200)

    assert verdict == "timeout", (
        "sidecar froze outside the startup window — killing here would shoot "
        "healthy agents mid-long-tool-run"
    )


def test_real_main_log_output_disables_the_sidecar_verdict(tmp_path: Path) -> None:
    """Frozen sidecar but the agent wrote real output — it IS working."""
    log = tmp_path / "worker.log"
    log.write_text("Starting task 1\n", encoding="utf-8")
    debug = tmp_path / "worker.attempt1.debug.log"
    debug.write_bytes(b"[DEBUG] startup\n")
    clock = _Clock()

    verdict, _ = _probe(clock, _NeverExits(clock), log=log, debug=debug, timeout_s=900)

    assert verdict == "timeout"
