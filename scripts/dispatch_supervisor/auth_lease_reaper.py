"""Durable cleanup owner for a Codex auth lease with live descendants."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

from . import isolation, procutil

_POLL_SECONDS = 1.0
_CLOSE_RETRY_SECONDS = 5.0


def wait_until_process_group_drained(
    pgid: int,
    *,
    leader_pid: int | None = None,
    leader_started_wall: str | None = None,
) -> None:
    """Require two consecutive authoritative empty process-group reads."""
    if leader_pid is None or leader_started_wall is None:
        empty_reads = 0
        while empty_reads < 2:
            members = procutil.pgid_members_checked(pgid)
            if members == []:
                empty_reads += 1
            else:
                empty_reads = 0
            time.sleep(_POLL_SECONDS)
        return
    isolation.wait_for_process_group_generation_drained(
        pgid=pgid,
        leader_pid=leader_pid or pgid,
        leader_started_wall=leader_started_wall or "legacy-unverified",
        poll_seconds=_POLL_SECONDS,
    )


def reap(args: argparse.Namespace) -> int:
    receipt_path = Path(args.receipt_path).resolve()
    lease = isolation.ProviderAuthLease(
        source_home=args.source_home,
        run_dir=args.run_dir,
        destination_path=args.destination_path,
        baseline_sha256=args.baseline_sha256,
        lease_id=getattr(args, "lease_id", "legacy-test-lease"),
        _authority_lock_fd=args.lock_fd,
        _destination_unlinked=getattr(
            args, "destination_unlinked", False,
        ),
    )
    isolation._transition_provider_auth_reaper_receipt(
        receipt_path,
        {
            "schema_version": "provider-auth-reaper.v2",
            "state": "waiting_for_process_group",
            "reaper_pid": os.getpid(),
        },
    )
    ack_fd = getattr(args, "ack_fd", None)
    if ack_fd is not None:
        os.write(ack_fd, b"READY\n")
        os.close(ack_fd)
    wait_until_process_group_drained(
        args.pgid,
        leader_pid=getattr(args, "leader_pid", None),
        leader_started_wall=getattr(args, "leader_started_wall", None),
    )
    attempts = 0
    while True:
        attempts += 1
        isolation._transition_provider_auth_reaper_receipt(
            receipt_path,
            {
                "schema_version": "provider-auth-reaper.v2",
                "state": "cleanup_started",
                "attempts": attempts,
            },
        )
        receipt = lease.close(
            checkpoint=lambda phase: (
                isolation._transition_provider_auth_reaper_receipt(
                    receipt_path,
                    {
                        "schema_version": "provider-auth-reaper.v2",
                        "state": "cleanup_started",
                        "close_phase": phase,
                    },
                )
            ),
        )
        isolation._transition_provider_auth_reaper_receipt(
            receipt_path,
            {
                "schema_version": "provider-auth-reaper.v2",
                "state": "cleaned" if receipt.ok else "cleanup_retry",
                "reaper_pid": os.getpid(),
                "pgid": args.pgid,
                "run_dir": args.run_dir,
                "attempts": attempts,
                "close": {
                    "ok": receipt.ok,
                    "reconciled": receipt.reconciled,
                    "source_advanced": receipt.source_advanced,
                    "cleaned": receipt.cleaned,
                    "reason": receipt.reason,
                },
            },
        )
        if receipt.ok:
            return 0
        time.sleep(_CLOSE_RETRY_SECONDS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pgid", type=int, required=True)
    parser.add_argument("--leader-pid", type=int, required=True)
    parser.add_argument("--leader-started-wall", required=True)
    parser.add_argument("--source-home", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--destination-path", required=True)
    parser.add_argument("--baseline-sha256", required=True)
    parser.add_argument("--lease-id", required=True)
    parser.add_argument("--lock-fd", type=int, required=True)
    parser.add_argument("--ack-fd", type=int, required=True)
    parser.add_argument("--receipt-path", required=True)
    parser.add_argument("--destination-unlinked", action="store_true")
    return parser.parse_args()


def main() -> int:
    return reap(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
