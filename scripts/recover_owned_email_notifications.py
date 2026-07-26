#!/usr/bin/env python3
"""Recover process-interrupted owned ops-alert email deliveries."""

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
from volpred.ops.delivery._email_notification import (  # noqa: E402
    EmailNotificationEffectAdapter,
    ImapSentMailReader,
)
from volpred.ops.delivery.owned_email import (  # noqa: E402
    OwnedEmailRecovery,
    SupabaseOwnedEmailStore,
)
from volpred.publisher.email_notifier import EmailNotifier  # noqa: E402

WORKER_ID = "effect-worker:ops-alert-email"


def recover_owned_email_notifications(
    *,
    limit: int,
    max_age_seconds: int,
) -> dict[str, object]:
    keepalive = build_supabase_host_authority_keepalive(
        authority_key="notification:email.ops_alert",
        holder_ref=WORKER_ID,
    )
    keepalive.start()
    try:
        summary = OwnedEmailRecovery(
            store=SupabaseOwnedEmailStore.from_environment(),
            provider=EmailNotificationEffectAdapter(
                notifier=EmailNotifier(storage_dir="storage"),
                sent_mail_reader=ImapSentMailReader.from_environment(),
            ),
            primary_authority=keepalive,
            worker_id=WORKER_ID,
            max_age_seconds=max_age_seconds,
        ).recover(limit=limit)
    finally:
        keepalive.stop()
    return {
        "schema_version": "owned-email-recovery-run.v1",
        "recovered_count": summary.recovered_count,
        "delivered_count": summary.delivered_count,
        "stale_count": summary.stale_count,
        "retry_scheduled_count": summary.retry_scheduled_count,
        "receipts": [
            {
                key: value
                for key, value in asdict(receipt).items()
                if key
                not in {
                    "primary_authority_ref",
                }
            }
            for receipt in summary.receipts
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Recover expired owned-email attempts through the canonical "
            "fenced transaction"
        )
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-age-seconds", type=int, default=3600)
    args = parser.parse_args(argv)
    if args.limit <= 0:
        parser.error("--limit must be positive")
    if args.max_age_seconds <= 0:
        parser.error("--max-age-seconds must be positive")
    result = recover_owned_email_notifications(
        limit=args.limit,
        max_age_seconds=args.max_age_seconds,
    )
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
