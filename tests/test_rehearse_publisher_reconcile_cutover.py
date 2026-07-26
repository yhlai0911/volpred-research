from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.rehearse_publisher_reconcile_cutover import (
    rehearse_publisher_reconcile_cutover,
)
from volpred.ops.delivery import (
    OwnedPublisherReconcileReceipt,
    PublisherArticleReconcileOwner,
)


def _owner(
    *,
    owner: str = "legacy",
    generation: int = 1,
) -> PublisherArticleReconcileOwner:
    return PublisherArticleReconcileOwner(
        schema_version="publisher-article-reconcile-owner.v1",
        effect_family="publisher.article.supabase.reconcile",
        owner=owner,
        generation=generation,
        changed_at=f"2026-07-25T00:0{generation}:00+00:00",
        changed_by="operator:test",
        change_reason="test state",
    )


class _Store:
    def __init__(self) -> None:
        self.owner = _owner()
        self.transfers: list[tuple[str, int, str, int | None]] = []

    def read_owner(self) -> PublisherArticleReconcileOwner:
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
    ) -> PublisherArticleReconcileOwner:
        assert self.owner.owner == expected_owner
        assert self.owner.generation == expected_generation
        assert actor_ref
        assert reason
        self.transfers.append(
            (
                expected_owner,
                expected_generation,
                target_owner,
                rollback_of_generation,
            )
        )
        self.owner = replace(
            self.owner,
            owner=target_owner,
            generation=expected_generation + 1,
            change_reason=reason,
        )
        return self.owner


def _feed(path: Path) -> Path:
    feed_path = path / "feed.json"
    feed_path.write_text(
        json.dumps(
            [
                {
                    "id": "mile_reconcile_rehearsal",
                    "title": "Reconcile rehearsal",
                    "content": "Canonical article.",
                    "status": "published",
                    "tags": ["K1708"],
                }
            ]
        ),
        encoding="utf-8",
    )
    return feed_path


def _delivery(
    owner: PublisherArticleReconcileOwner,
    _feed_sha256: str,
    _articles,
) -> OwnedPublisherReconcileReceipt:
    return OwnedPublisherReconcileReceipt(
        schema_version="owned-publisher-reconcile-receipt.v1",
        owner_generation=owner.generation,
        work_id="work-reconcile-1",
        work_status="succeeded",
        effect_id="effect-reconcile-1",
        effect_status="delivered",
        attempt_count=1,
        disposition="delivered",
        evidence_ref="supabase:articles:reconcile:" + "f" * 64,
        evidence_sha256="e" * 64,
        primary_authority_ref=(
            "primary-authority:"
            "publisher:article.supabase.reconcile:epoch-1"
        ),
        recorded_at="2026-07-25T00:01:00+00:00",
    )


def _converged() -> dict[str, object]:
    return {
        "schema_version": "publisher-projection-convergence.v2",
        "public_projection_contract": {
            "schema_version": "public-article-projection-contract.v1",
            "policy_sha256": (
                "6d125ff39bdb951026cdecf6e314d4cd"
                "56eb6877cc1cf478333375bc78306888"
            ),
            "matches": True,
        },
        "convergence_status": "converged",
        "mismatch_total": 0,
        "observation_errors": [],
    }


def test_rehearsal_acknowledges_rolls_back_and_recuts_over(
    tmp_path: Path,
) -> None:
    store = _Store()

    receipt = rehearse_publisher_reconcile_cutover(
        slug="mile_reconcile_rehearsal",
        actor_ref="operator:test",
        feed_path=_feed(tmp_path),
        store=store,
        deliver_batch=_delivery,
        read_convergence=_converged,
    )

    assert receipt.cutover_generation == 2
    assert receipt.rollback_generation == 3
    assert receipt.rollback_of_generation == 2
    assert (receipt.final_owner, receipt.final_generation) == (
        "operations_core",
        4,
    )
    assert store.transfers == [
        ("legacy", 1, "operations_core", None),
        ("operations_core", 2, "legacy", 2),
        ("legacy", 3, "operations_core", None),
    ]


def test_rehearsal_failure_automatically_returns_to_legacy(
    tmp_path: Path,
) -> None:
    store = _Store()

    with pytest.raises(RuntimeError, match="did not converge"):
        rehearse_publisher_reconcile_cutover(
            slug="mile_reconcile_rehearsal",
            actor_ref="operator:test",
            feed_path=_feed(tmp_path),
            store=store,
            deliver_batch=_delivery,
            read_convergence=lambda: {
                **_converged(),
                "convergence_status": "drifted",
                "mismatch_total": 1,
            },
        )

    assert (store.owner.owner, store.owner.generation) == ("legacy", 3)
    assert store.transfers == [
        ("legacy", 1, "operations_core", None),
        ("operations_core", 2, "legacy", 2),
    ]


def test_rehearsal_preflight_fails_before_owner_mutation(
    tmp_path: Path,
) -> None:
    store = _Store()

    with pytest.raises(ValueError, match="absent from canonical feed"):
        rehearse_publisher_reconcile_cutover(
            slug="missing",
            actor_ref="operator:test",
            feed_path=_feed(tmp_path),
            store=store,
            deliver_batch=_delivery,
            read_convergence=_converged,
        )

    assert store.transfers == []
