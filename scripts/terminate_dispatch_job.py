#!/usr/bin/env python3
"""Terminate one exact live dispatch job through a durable formal command."""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.dispatch_supervisor import state as supervisor_state  # noqa: E402
from volpred.ops import termination, termination_command  # noqa: E402

_SIGNALABLE_PHASES = frozenset({"running", "codex_failover"})


class DispatchTerminationError(RuntimeError):
    """The command is not authorized by exact current supervisor state."""


@dataclass(frozen=True)
class DispatchBinding:
    state_path: Path
    job_id: str
    attempt: int
    target_kind: termination.TargetKind
    target_id: int
    target_identity: str
    ledger_path: Path


def _job_target_id(
    job: supervisor_state.CurrentJob,
    target_kind: termination.TargetKind,
) -> int:
    return job.pgid if target_kind == "pgid" else job.pid


def _assert_exact_current_job(
    binding: DispatchBinding,
) -> supervisor_state.CurrentJob:
    matches = [
        job
        for job in supervisor_state.get_current_jobs(binding.state_path)
        if job.job_id == binding.job_id and job.attempt == binding.attempt
    ]
    if len(matches) != 1:
        raise DispatchTerminationError(
            "binding does not identify exactly one current dispatch job"
        )
    job = matches[0]
    if _job_target_id(job, binding.target_kind) != binding.target_id:
        raise DispatchTerminationError(
            "target does not match the bound current dispatch job"
        )
    if job.phase not in _SIGNALABLE_PHASES:
        raise DispatchTerminationError(
            f"dispatch job phase is not signalable: {job.phase}"
        )
    expected_identity = str(job.started_wall or "").strip()
    if (
        not expected_identity
        or expected_identity.startswith("absent:")
        or expected_identity != binding.target_identity
    ):
        raise DispatchTerminationError(
            "dispatch state has no matching process generation"
        )
    observed_identity = termination.capture_target_identity(
        binding.target_kind,
        binding.target_id,
    )
    if observed_identity != binding.target_identity:
        raise DispatchTerminationError(
            "dispatch process generation differs from supervisor state"
        )
    return job


def _bind_current_job(
    *,
    state_path: Path,
    target_kind: termination.TargetKind,
    target_id: int,
    job_id: str,
    attempt: int,
) -> DispatchBinding:
    if state_path.is_symlink():
        raise DispatchTerminationError(
            "canonical dispatch state path must not be a symlink"
        )
    if attempt <= 0:
        raise DispatchTerminationError("--attempt must be a positive integer")
    matches = [
        job
        for job in supervisor_state.get_current_jobs(state_path)
        if job.job_id == job_id and job.attempt == attempt
    ]
    if len(matches) != 1:
        raise DispatchTerminationError(
            "binding does not identify exactly one current dispatch job"
        )
    expected_identity = str(matches[0].started_wall or "").strip()
    binding = DispatchBinding(
        state_path=state_path,
        job_id=job_id,
        attempt=attempt,
        target_kind=target_kind,
        target_id=target_id,
        target_identity=expected_identity,
        ledger_path=termination.ledger_for_state(state_path),
    )
    _assert_exact_current_job(binding)
    return binding


def main(
    argv: Sequence[str] | None = None,
    *,
    state_path: Path = supervisor_state.STATE_PATH,
) -> int:
    parser = argparse.ArgumentParser()
    termination_command.add_target_signal_arguments(parser)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--attempt", required=True, type=int)
    args = parser.parse_args(argv)

    if os.environ.get(termination.LEDGER_PATH_ENV):
        parser.error("formal dispatch command refuses a termination ledger override")
    sequence = termination_command.signal_sequence(args.signal)
    canonical_state = Path(state_path).expanduser().absolute()
    try:
        binding = _bind_current_job(
            state_path=canonical_state,
            target_kind=args.target_kind,
            target_id=args.target_id,
            job_id=args.job_id,
            attempt=args.attempt,
        )
        intent = termination.arm(
            target_kind=binding.target_kind,
            target_id=binding.target_id,
            reason=args.reason,
            actor=args.actor,
            signal_sequence=sequence,
            job_id=binding.job_id,
            attempt=binding.attempt,
            ledger_path=binding.ledger_path,
            target_identity=binding.target_identity,
        )
        def verify_binding_before_first_signal() -> None:
            _assert_exact_current_job(binding)

        result = termination_command.send_sequence(
            intent,
            sequence,
            grace_seconds=args.grace_seconds,
            ledger_path=binding.ledger_path,
            first_pre_signal_verifier=verify_binding_before_first_signal,
        )
    except (
        DispatchTerminationError,
        termination.TerminationIntentError,
    ) as exc:
        parser.error(str(exc))

    print(
        f"termination intent={intent.intent_id} "
        f"job={binding.job_id} attempt={binding.attempt} "
        f"target={binding.target_kind}:{binding.target_id} "
        f"signals={sequence} result={result}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
