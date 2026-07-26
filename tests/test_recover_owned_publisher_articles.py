from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import recover_owned_publisher_articles as recovery_script
from volpred.ops.delivery.owned_publisher_article import (
    OwnedPublisherArticleReceipt,
)
from volpred.ops.delivery.owned_publisher_delete import (
    OwnedPublisherDeleteReconciliationReceipt,
    OwnedPublisherDeleteReconciliationSummary,
)

ROOT = Path(__file__).resolve().parents[1]


def test_recovery_script_binds_keepalive_store_and_projection(
    monkeypatch,
) -> None:
    calls: list[tuple[str, object]] = []

    class Keepalive:
        def start(self) -> None:
            calls.append(("keepalive_start", None))

        def stop(self) -> None:
            calls.append(("keepalive_stop", None))

    class Recovery:
        def __init__(self, **kwargs) -> None:
            calls.append(("recovery_init", kwargs))

        def recover(self, *, limit: int):
            calls.append(("recover", limit))
            return SimpleNamespace(
                recovered_count=1,
                delivered_count=1,
                retry_scheduled_count=0,
                receipts=(
                    OwnedPublisherArticleReceipt(
                        schema_version=(
                            "owned-publisher-article-receipt.v1"
                        ),
                        owner_generation=8,
                        work_id="work-1",
                        work_status="succeeded",
                        effect_id="effect-1",
                        effect_status="delivered",
                        attempt_count=2,
                        disposition="delivered",
                        evidence_ref="supabase:articles/mile_1",
                        evidence_sha256="a" * 64,
                        primary_authority_ref="primary-authority:1",
                        recorded_at="2026-07-26T09:30:00+00:00",
                    ),
                ),
            )

    class DeleteReconciliation:
        def __init__(self, **kwargs) -> None:
            calls.append(("delete_reconciliation_init", kwargs))

        def reconcile(self, *, limit: int):
            calls.append(("delete_reconcile", limit))
            return OwnedPublisherDeleteReconciliationSummary(
                schema_version=(
                    "owned-publisher-delete-reconciliation-summary.v1"
                ),
                reconciled_count=1,
                receipts=(
                    OwnedPublisherDeleteReconciliationReceipt(
                        schema_version=(
                            "owned-publisher-delete-reconciliation-"
                            "receipt.v1"
                        ),
                        effect_id="effect-delete-1",
                        attempt_count=1,
                        stale_owner_generation=4,
                        current_owner_generation=5,
                        approval_ref="approval:delete-1",
                        reason_code=(
                            "stale_generation_revoked_approval"
                        ),
                        evidence_ref="reconciliation:delete-1",
                        evidence_sha256="b" * 64,
                        recorded_at="2026-07-26T10:00:00+00:00",
                    ),
                ),
            )

    store = object()
    delete_store = object()
    projection = object()
    monkeypatch.setattr(
        recovery_script,
        "build_supabase_host_authority_keepalive",
        lambda **kwargs: (
            calls.append(("keepalive_factory", kwargs)) or Keepalive()
        ),
    )
    monkeypatch.setattr(
        recovery_script.SupabaseOwnedPublisherArticleStore,
        "from_environment",
        lambda: store,
    )
    monkeypatch.setattr(
        recovery_script,
        "SupabaseArticleProjectionAdapter",
        lambda **kwargs: (
            calls.append(("projection", kwargs)) or projection
        ),
    )
    monkeypatch.setattr(
        recovery_script,
        "OwnedPublisherArticleRecovery",
        Recovery,
    )
    monkeypatch.setattr(
        recovery_script.SupabaseOwnedPublisherDeleteStore,
        "from_environment",
        lambda: delete_store,
    )
    monkeypatch.setattr(
        recovery_script,
        "OwnedPublisherDeleteReconciliation",
        DeleteReconciliation,
    )

    result = recovery_script.recover_owned_publisher_articles(limit=25)

    assert result["schema_version"] == (
        "owned-publisher-article-recovery-run.v2"
    )
    assert result["recovered_count"] == 1
    assert result["receipts"][0]["effect_id"] == "effect-1"
    assert result["publisher_delete_reconciliation"][
        "reconciled_count"
    ] == 1
    assert calls[:2] == [
        (
            "delete_reconciliation_init",
            {
                "store": delete_store,
                "actor_ref": (
                    "effect-worker:publisher-delete-reconciliation"
                ),
            },
        ),
        ("delete_reconcile", 25),
    ]
    assert calls[2] == (
        "keepalive_factory",
        {
            "authority_key": "publisher:article.supabase.sync",
            "holder_ref": "effect-worker:publisher-article-sync",
        },
    )
    assert calls[-1] == ("keepalive_stop", None)


def test_recovery_has_one_canonical_hourly_schedule() -> None:
    schedules = json.loads(
        (ROOT / "config/runtime_schedules.json").read_text()
    )
    matching = [
        item
        for item in schedules["system_crontab"]["items"]
        if item["id"] == "owned_publisher_article_recovery"
    ]

    assert matching == [
        {
            "id": "owned_publisher_article_recovery",
            "label": "owned publisher article retry recovery",
            "cron": "15 * * * *",
            "wrapper_script": (
                "/Users/yhlai0911/.volpred/bin/"
                "cron_owned_publisher_article_recovery.sh"
            ),
            "log_path": (
                "storage/logs/cron/"
                "owned_publisher_article_recovery.log"
            ),
            "host_crontab_managed": False,
            "piggy_back_enabled": True,
            "description": (
                "每小時由 check_alerts → run_due_jobs 單一 piggy-back "
                "owner 回收 publisher sync 的 expired started 與 due "
                "retry；exact-family RPC 以 SKIP LOCKED 原子領取並由"
                "既有 Supabase read-back provider 收斂。"
            ),
            "matchers": [
                "recover_owned_publisher_articles.py",
                "cron_owned_publisher_article_recovery.sh",
                "volpred_recover_due_owned_publisher_article_sync",
            ],
        }
    ]
    ownership = json.loads(
        (ROOT / "config/scheduled_writer_ownership.json").read_text()
    )
    assert ownership["jobs"]["owned_publisher_article_recovery"] == {
        "entrypoint": "scripts/recover_owned_publisher_articles.py",
        "policy": "no_repo_tracked_output",
        "tracked_outputs": [],
        "reason": (
            "Mutates only the fenced Supabase publisher-sync transaction "
            "and ignored log evidence; it never writes or commits "
            "Git-tracked repository state."
        ),
    }
    assert (
        ROOT / "scripts/cron_owned_publisher_article_recovery.sh"
    ).is_file()
