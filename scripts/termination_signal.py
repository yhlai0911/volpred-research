#!/usr/bin/env python3
"""Signal one exact process generation through the durable intent owner."""
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

SIGNALS = {
    "HUP": signal.SIGHUP,
    "INT": signal.SIGINT,
    "TERM": signal.SIGTERM,
    "KILL": signal.SIGKILL,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-kind", required=True, choices=("pid", "pgid"))
    parser.add_argument("--target-id", required=True, type=int)
    parser.add_argument(
        "--signal", required=True, choices=(*SIGNALS, "TERM_KILL"),
    )
    parser.add_argument("--grace-seconds", type=float, default=2.0)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--actor", required=True)
    args = parser.parse_args()

    sequence = (
        [signal.SIGTERM, signal.SIGKILL]
        if args.signal == "TERM_KILL"
        else [SIGNALS[args.signal]]
    )
    intent = termination.arm(
        target_kind=args.target_kind,
        target_id=args.target_id,
        reason=args.reason,
        actor=args.actor,
        signal_sequence=sequence,
    )
    sender = (
        termination.send_pgid
        if args.target_kind == "pgid"
        else termination.send_pid
    )
    result = sender(intent, sequence[0])
    if len(sequence) == 2:
        time.sleep(max(0.0, args.grace_seconds))
        probe = subprocess.run(
            (
                ["ps", "-o", "pid=", "-g", str(args.target_id)]
                if args.target_kind == "pgid"
                else ["ps", "-o", "pid=", "-p", str(args.target_id)]
            ),
            capture_output=True, text=True, timeout=5,
        )
        if probe.returncode == 0 and probe.stdout.strip():
            result = sender(intent, sequence[1])
    print(
        f"termination intent={intent.intent_id} target="
        f"{args.target_kind}:{args.target_id} signals={sequence} result={result}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
