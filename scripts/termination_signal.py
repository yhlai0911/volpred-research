#!/usr/bin/env python3
"""Signal a standalone non-dispatch process through the durable intent owner.

Dispatch workers use ``terminate_dispatch_job.py`` so their signal receipt is
bound to the supervisor job and attempt identity.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.dispatch_supervisor import state as supervisor_state  # noqa: E402
from volpred.ops import termination, termination_command  # noqa: E402


def _reject_dispatch_target(
    *,
    target_kind: termination.TargetKind,
    target_id: int,
    state_path: Path,
) -> None:
    for job in supervisor_state.get_current_jobs(state_path):
        current_target = job.pgid if target_kind == "pgid" else job.pid
        if current_target == target_id:
            raise termination.TerminationIntentMismatch(
                "standalone adapter refuses a canonical dispatch target; "
                "use terminate_dispatch_job.py with job identity"
            )


def main(
    argv: Sequence[str] | None = None,
    *,
    state_path: Path = supervisor_state.STATE_PATH,
) -> int:
    parser = argparse.ArgumentParser()
    termination_command.add_target_signal_arguments(parser)
    args = parser.parse_args(argv)

    try:
        _reject_dispatch_target(
            target_kind=args.target_kind,
            target_id=args.target_id,
            state_path=Path(state_path),
        )
        sequence = termination_command.signal_sequence(args.signal)
        intent = termination.arm(
            target_kind=args.target_kind,
            target_id=args.target_id,
            reason=args.reason,
            actor=args.actor,
            signal_sequence=sequence,
        )

        def reject_dispatch_target_before_signal() -> None:
            _reject_dispatch_target(
                target_kind=args.target_kind,
                target_id=args.target_id,
                state_path=Path(state_path),
            )

        result = termination_command.send_sequence(
            intent,
            sequence,
            grace_seconds=args.grace_seconds,
            first_pre_signal_verifier=reject_dispatch_target_before_signal,
            escalation_pre_signal_verifier=reject_dispatch_target_before_signal,
        )
    except termination.TerminationIntentError as exc:
        parser.error(str(exc))
    print(
        f"termination intent={intent.intent_id} target="
        f"{args.target_kind}:{args.target_id} signals={sequence} result={result}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
