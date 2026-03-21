#!/usr/bin/env python3
from __future__ import annotations

import argparse

from volpred.ops.jobs import work_loop


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll and execute queued local ops jobs.")
    parser.add_argument("--scope", default="local", help="Job scope to consume")
    parser.add_argument("--worker-id", default=None, help="Explicit worker id")
    parser.add_argument("--poll-interval", type=float, default=10.0, help="Polling interval in seconds")
    parser.add_argument("--once", action="store_true", help="Process at most one available job")
    parser.add_argument("--max-jobs", type=int, default=None, help="Stop after N processed jobs")
    args = parser.parse_args()

    processed = work_loop(
        scope=args.scope,
        worker_id=args.worker_id,
        poll_interval=args.poll_interval,
        once=args.once,
        max_jobs=args.max_jobs,
    )
    print(f"processed={processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
