#!/usr/bin/env python3
"""Restart one KeepAlive launchd service through its exact current PID."""
from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from volpred.ops import termination  # noqa: E402
from volpred.ops.diagnostics import warn  # noqa: E402


def _service_pid(service: str) -> int:
    result = subprocess.run(
        ["launchctl", "print", service],
        capture_output=True, text=True, timeout=10, check=True,
    )
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("pid = "):
            return int(stripped.removeprefix("pid = ").strip())
    raise RuntimeError(f"launchd service has no current pid: {service}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    pid = _service_pid(args.service)
    intent = termination.arm(
        target_kind="pid", target_id=pid, reason=args.reason,
        actor="termination_launchd_restart",
        signal_sequence=[signal.SIGTERM],
    )
    termination.send_pid(intent, signal.SIGTERM)
    deadline = time.monotonic() + 30
    probe_error_reported = False
    while time.monotonic() < deadline:
        try:
            replacement_pid = _service_pid(args.service)
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            if not probe_error_reported:
                warn(
                    "termination_launchd_restart",
                    "replacement pid temporarily unavailable",
                    err=str(exc),
                    service=args.service,
                    previous_pid=pid,
                )
                probe_error_reported = True
            time.sleep(0.1)
            continue
        if replacement_pid != pid:
            print(f"launchd KeepAlive restarted {args.service}: {pid} -> {replacement_pid}")
            return 0
        time.sleep(0.1)
    raise RuntimeError(
        f"launchd service did not respawn within 30s: {args.service} (pid={pid})"
    )


if __name__ == "__main__":
    raise SystemExit(main())
