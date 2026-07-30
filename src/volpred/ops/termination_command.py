"""Shared command policy for durable process-termination adapters."""
from __future__ import annotations

import argparse
import signal
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from volpred.ops import termination

SIGNALS = {
    "HUP": signal.SIGHUP,
    "INT": signal.SIGINT,
    "TERM": signal.SIGTERM,
    "KILL": signal.SIGKILL,
}
SIGNAL_CHOICES = (*SIGNALS, "TERM_KILL")


def add_target_signal_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the target and signal policy shared by command adapters."""
    parser.add_argument("--target-kind", required=True, choices=("pid", "pgid"))
    parser.add_argument("--target-id", required=True, type=int)
    parser.add_argument("--signal", required=True, choices=SIGNAL_CHOICES)
    parser.add_argument("--grace-seconds", type=float, default=2.0)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--actor", required=True)


def signal_sequence(name: str) -> tuple[int, ...]:
    """Translate one CLI policy name into its exact durable capability."""
    if name == "TERM_KILL":
        return signal.SIGTERM, signal.SIGKILL
    return (SIGNALS[name],)


def target_still_exists(
    target_kind: termination.TargetKind,
    target_id: int,
) -> bool:
    probe = subprocess.run(
        (
            ["ps", "-o", "pid=", "-g", str(target_id)]
            if target_kind == "pgid"
            else ["ps", "-o", "pid=", "-p", str(target_id)]
        ),
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    return probe.returncode == 0 and bool(probe.stdout.strip())


def send_sequence(
    intent: termination.TerminationIntent,
    sequence: Sequence[int],
    *,
    grace_seconds: float,
    ledger_path: Path | str | None = None,
    first_pre_signal_verifier: Callable[[], None] | None = None,
    escalation_pre_signal_verifier: Callable[[], None] | None = None,
) -> str:
    """Send an armed sequence, escalating only while the target still exists."""
    sender = (
        termination.send_pgid
        if intent.target_kind == "pgid"
        else termination.send_pid
    )
    result = sender(
        intent,
        sequence[0],
        ledger_path=ledger_path,
        pre_signal_verifier=first_pre_signal_verifier,
    )
    if len(sequence) == 2:
        time.sleep(max(0.0, grace_seconds))
        if target_still_exists(intent.target_kind, intent.target_id):
            # The first signal can retire a dispatch state row while descendants
            # retain the original PGID. The same intent + generation capability
            # authorizes this exact escalation.
            result = sender(
                intent,
                sequence[1],
                ledger_path=ledger_path,
                pre_signal_verifier=escalation_pre_signal_verifier,
            )
    return result
