#!/usr/bin/env python3
"""Keep the reader-facing draft pipeline moving without a model invocation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from volpred.ops.article_continuity import maintain_article_continuity
from volpred.ops.content import preview_release_pool_by_settings

from scripts.dispatch_supervisor import state as dispatch_state

ROOT = Path(__file__).resolve().parents[1]


def run(*, queue_path: Path, storage_dir: Path) -> dict:
    preview = preview_release_pool_by_settings(storage_dir=str(storage_dir))
    counts = preview.get("pool_counts") or {}
    eligible = int(counts.get("eligible") or 0)
    result = maintain_article_continuity(
        queue_path=queue_path,
        releasable_count=eligible,
        request_fire=dispatch_state.request_fire,
    )

    # No existing article work means the canonical refill owner gets one chance
    # to materialize it.  Re-run the actuator so the new row is nominated during
    # the same Operations Core tick instead of waiting for another control loop.
    if eligible == 0 and result["reason"] == "no_pending_article":
        import continue_task_dispatch as dispatch_report

        dispatch_report.NEXT_TASKS = queue_path
        refill = dispatch_report._maybe_refill_draft_pool(auto_refill=True)
        result = maintain_article_continuity(
            queue_path=queue_path,
            releasable_count=0,
            request_fire=dispatch_state.request_fire,
        )
        result["refill"] = refill

    result["pool_counts"] = counts
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--queue",
        type=Path,
        default=ROOT / "storage" / "next_tasks.json",
    )
    parser.add_argument(
        "--storage-dir",
        type=Path,
        default=ROOT / "storage",
    )
    args = parser.parse_args(argv)
    result = run(queue_path=args.queue, storage_dir=args.storage_dir)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

