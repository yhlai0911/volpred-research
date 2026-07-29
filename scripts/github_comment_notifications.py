#!/usr/bin/env python3
"""Reconcile GitHub comments into durable per-issue email batches."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from volpred.ops.github_comment_notifications import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_REPO,
    DEFAULT_STATE_PATH,
    run_github_comment_notifications,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Buffer GitHub comments by Issue/PR and deliver Operations Core "
            "email batches."
        )
    )
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--storage-dir", default="storage")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
    )
    args = parser.parse_args(argv)
    result = run_github_comment_notifications(
        repo=args.repo,
        state_path=args.state,
        storage_dir=args.storage_dir,
        lookback_days=args.lookback_days,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("delivery_status") in {
        "delivered", "buffered", "idle",
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
