from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from scripts.rehearse_publisher_cutover import (
    rehearse_publisher_cutover,
)
from volpred.ops.delivery.owned_publisher_article import (
    OwnedPublisherArticleReceipt,
    PublisherArticleSyncOwner,
)


def _owner(*, owner: str, generation: int) -> PublisherArticleSyncOwner:
    return PublisherArticleSyncOwner(
        schema_version="publisher-article-sync-owner.v1",
        effect_family="publisher.article.supabase.sync",
        owner=owner,
        generation=generation,
        changed_at=f"2026-07-25T00:00:0{generation}+00:00",
        changed_by="operator:test",
        change_reason="test",
    )


def _receipt(*, generation: int) -> OwnedPublisherArticleReceipt:
    return OwnedPublisherArticleReceipt(
        schema_version="owned-publisher-article-receipt.v1",
        owner_generation=generation,
        work_id="work-1",
        work_status="succeeded",
        effect_id="effect-1",
        effect_status="delivered",
        attempt_count=1,
        disposition="delivered",
        evidence_ref="supabase:articles/article-1",
        evidence_sha256="a" * 64,
        primary_authority_ref="primary-authority:publisher:epoch-1",
        recorded_at="2026-07-25T00:01:00+00:00",
    )


class FakeStore:
    def __init__(self) -> None:
        self.owner = _owner(owner="legacy", generation=1)
        self.transfers: list[dict[str, object]] = []

    def read_owner(self) -> PublisherArticleSyncOwner:
        return self.owner

    def transfer_owner(
        self,
        *,
        expected_owner: str,
        expected_generation: int,
        target_owner: str,
        actor_ref: str,
        reason: str,
        rollback_of_generation: int | None = None,
    ) -> PublisherArticleSyncOwner:
        assert self.owner.owner == expected_owner
        assert self.owner.generation == expected_generation
        self.transfers.append(
            {
                "expected_owner": expected_owner,
                "expected_generation": expected_generation,
                "target_owner": target_owner,
                "actor_ref": actor_ref,
                "reason": reason,
                "rollback_of_generation": rollback_of_generation,
            }
        )
        self.owner = _owner(
            owner=target_owner,
            generation=expected_generation + 1,
        )
        return self.owner


def _article_file(tmp_path: Path) -> Path:
    path = tmp_path / "article-1.json"
    path.write_text(
        json.dumps(
            {
                "id": "article-1",
                "status": "published",
                "title": "Canonical article",
                "content": "Body",
            }
        )
    )
    return path


def test_rehearsal_preflights_article_before_owner_transfer(
    tmp_path: Path,
) -> None:
    store = FakeStore()

    with pytest.raises(FileNotFoundError, match="single-report"):
        rehearse_publisher_cutover(
            deployment_id="deployment-1",
            slug="article-1",
            actor_ref="operator:test",
            article_path=tmp_path / "missing.json",
            store=store,
            live_fence_probe=lambda owner, article: ({}, {}),
            deliver_article=lambda owner, article, key: _receipt(
                generation=owner.generation
            ),
        )

    assert store.owner == _owner(owner="legacy", generation=1)
    assert store.transfers == []


def test_rehearsal_acknowledges_and_exactly_rolls_back(
    tmp_path: Path,
) -> None:
    store = FakeStore()
    observed: dict[str, object] = {}

    def probe(
        owner: PublisherArticleSyncOwner,
        article: Mapping[str, object],
    ) -> tuple[Mapping[str, object], Mapping[str, object]]:
        observed["probe_owner"] = owner
        observed["probe_article"] = article
        return (
            {"status": "rejected", "owner_generation": owner.generation},
            {"status": "delegated", "owner_generation": owner.generation},
        )

    def deliver(
        owner: PublisherArticleSyncOwner,
        article: Mapping[str, object],
        idempotency_key: str,
    ) -> OwnedPublisherArticleReceipt:
        observed["delivery_owner"] = owner
        observed["idempotency_key"] = idempotency_key
        return _receipt(generation=owner.generation)

    result = rehearse_publisher_cutover(
        deployment_id="deployment-1",
        slug="article-1",
        actor_ref="operator:test",
        article_path=_article_file(tmp_path),
        store=store,
        live_fence_probe=probe,
        deliver_article=deliver,
    )

    assert result.schema_version == "publisher-cutover-rehearsal.v1"
    assert result.cutover_generation == 2
    assert result.delivery["work_id"] == "work-1"
    assert result.final_owner == "legacy"
    assert result.final_generation == 3
    assert result.rollback_of_generation == 2
    assert (
        observed["idempotency_key"]
        == "publisher-cutover-rehearsal:deployment-1:"
        "generation-2:article-1"
    )
    assert [call["target_owner"] for call in store.transfers] == [
        "operations_core",
        "legacy",
    ]
    assert store.transfers[1]["rollback_of_generation"] == 2


def test_rehearsal_failure_automatically_rolls_back(
    tmp_path: Path,
) -> None:
    store = FakeStore()

    def fail_probe(
        owner: PublisherArticleSyncOwner,
        article: Mapping[str, object],
    ) -> tuple[Mapping[str, object], Mapping[str, object]]:
        raise RuntimeError("live fence mismatch")

    with pytest.raises(RuntimeError, match="live fence mismatch"):
        rehearse_publisher_cutover(
            deployment_id="deployment-1",
            slug="article-1",
            actor_ref="operator:test",
            article_path=_article_file(tmp_path),
            store=store,
            live_fence_probe=fail_probe,
            deliver_article=lambda owner, article, key: _receipt(
                generation=owner.generation
            ),
        )

    assert store.owner.owner == "legacy"
    assert store.owner.generation == 3
    assert [call["target_owner"] for call in store.transfers] == [
        "operations_core",
        "legacy",
    ]
    assert "automatic rollback" in str(store.transfers[1]["reason"])
    assert store.transfers[1]["rollback_of_generation"] == 2


def test_rehearsal_rejects_receipt_from_another_generation(
    tmp_path: Path,
) -> None:
    store = FakeStore()

    with pytest.raises(RuntimeError, match="exact acknowledged"):
        rehearse_publisher_cutover(
            deployment_id="deployment-1",
            slug="article-1",
            actor_ref="operator:test",
            article_path=_article_file(tmp_path),
            store=store,
            live_fence_probe=lambda owner, article: ({}, {}),
            deliver_article=lambda owner, article, key: _receipt(
                generation=owner.generation + 1
            ),
        )

    assert store.owner.owner == "legacy"
    assert store.owner.generation == 3
    assert store.transfers[1]["rollback_of_generation"] == 2
