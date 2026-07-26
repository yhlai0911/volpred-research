#!/usr/bin/env python3
"""Recover crashed or due owned publisher article sync attempts."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from volpred.ops.authority import (  # noqa: E402
    build_supabase_host_authority_keepalive,
)
from volpred.ops.delivery._publisher_article_sync import (  # noqa: E402
    PublisherArticleSyncEffectAdapter,
    SupabaseArticleProjectionAdapter,
)
from volpred.ops.delivery.owned_publisher_article import (  # noqa: E402
    OwnedPublisherArticleRecovery,
    SupabaseOwnedPublisherArticleStore,
)
from volpred.ops.delivery.owned_publisher_delete import (  # noqa: E402
    OwnedPublisherDeleteReconciliation,
    SupabaseOwnedPublisherDeleteStore,
)

WORKER_ID = "effect-worker:publisher-article-sync"
AUTHORITY_KEY = "publisher:article.supabase.sync"
DELETE_RECONCILIATION_ACTOR = (
    "effect-worker:publisher-delete-reconciliation"
)


def recover_owned_publisher_articles(
    *,
    limit: int,
) -> dict[str, object]:
    delete_summary = OwnedPublisherDeleteReconciliation(
        store=SupabaseOwnedPublisherDeleteStore.from_environment(),
        actor_ref=DELETE_RECONCILIATION_ACTOR,
    ).reconcile(limit=limit)
    keepalive = build_supabase_host_authority_keepalive(
        authority_key=AUTHORITY_KEY,
        holder_ref=WORKER_ID,
    )
    keepalive.start()
    try:
        summary = OwnedPublisherArticleRecovery(
            store=SupabaseOwnedPublisherArticleStore.from_environment(),
            provider=PublisherArticleSyncEffectAdapter(
                projection=SupabaseArticleProjectionAdapter(
                    storage_dir="storage"
                )
            ),
            primary_authority=keepalive,
            worker_id=WORKER_ID,
        ).recover(limit=limit)
    finally:
        keepalive.stop()
    return {
        "schema_version": "owned-publisher-article-recovery-run.v2",
        "recovered_count": summary.recovered_count,
        "delivered_count": summary.delivered_count,
        "retry_scheduled_count": summary.retry_scheduled_count,
        "receipts": [
            {
                key: value
                for key, value in asdict(receipt).items()
                if key != "primary_authority_ref"
            }
            for receipt in summary.receipts
        ],
        "publisher_delete_reconciliation": {
            "schema_version": delete_summary.schema_version,
            "reconciled_count": delete_summary.reconciled_count,
            "receipts": [
                asdict(receipt)
                for receipt in delete_summary.receipts
            ],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Recover due publisher article sync attempts and terminalize "
            "stale revoked delete retries through canonical transactions"
        )
    )
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args(argv)
    if args.limit <= 0:
        parser.error("--limit must be positive")
    print(
        json.dumps(
            recover_owned_publisher_articles(limit=args.limit),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
