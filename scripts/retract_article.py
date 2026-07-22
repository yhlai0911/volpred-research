#!/usr/bin/env python3
"""Retract one article through the canonical locked feed writer.

Examples:
  uv run python scripts/retract_article.py --id mile_old --reason duplicate \
    --superseded-by mile_new --sync
  uv run python scripts/retract_article.py --id mile_old --reason invalid_claim \
    --no-successor "no replacement has been approved"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from volpred.ops.retraction import RetractionError, retract_article  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True, help="feed article id (mile_...)")
    parser.add_argument("--reason", required=True, help="why the article is retracted")
    outcome = parser.add_mutually_exclusive_group(required=True)
    outcome.add_argument(
        "--superseded-by",
        action="append",
        help="successor article id; repeat for multiple successors",
    )
    outcome.add_argument(
        "--no-successor",
        metavar="REASON",
        help="explicit reason no successor can be recorded",
    )
    parser.add_argument(
        "--errata-ref",
        help="optional correction task, document, or URL that explains the retraction",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="after the verified local write, sync this article and purge frontend cache",
    )
    parser.add_argument("--storage-dir", default=str(ROOT / "storage"), help=argparse.SUPPRESS)
    return parser


def _sync_article(article_id: str, storage_dir: Path) -> None:
    feed = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    article = next(
        (row for row in feed if isinstance(row, dict) and row.get("id") == article_id),
        None,
    )
    if article is None:
        raise RuntimeError(f"cannot sync missing article: {article_id}")
    from supabase_sync import _REVALIDATE_FAILURES, sync_article

    failure_mark = len(_REVALIDATE_FAILURES)
    if not sync_article(article, storage_dir=storage_dir):
        raise RuntimeError(f"Supabase sync failed for {article_id}")
    failed_purges = _REVALIDATE_FAILURES[failure_mark:]
    if article_id in failed_purges:
        raise RuntimeError(f"frontend cache purge failed for {article_id}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        receipt = retract_article(
            args.id,
            reason=args.reason,
            superseded_by=args.superseded_by,
            errata_ref=args.errata_ref,
            no_successor_reason=args.no_successor,
            storage_dir=args.storage_dir,
            actor=os.environ.get("VOLPRED_TASK_CLAIM_OWNER"),
        )
        if args.sync:
            _sync_article(args.id, Path(args.storage_dir))
            receipt["projection_synced"] = True
    except (RetractionError, OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
