#!/usr/bin/env python3
"""Rehearse safe publisher reconcile ownership and leave it cut over.

The operator interface preflights one canonical published article, transfers
the safe reconcile family with generation CAS, delivers one immutable batch,
requires the standing projection-convergence receipt, performs an exact
rollback, and recuts over. Any failure while Operations Core owns the family
automatically rolls back to ``legacy``.

Destructive delete reconciliation is deliberately outside this interface.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from volpred.ops.authority import build_supabase_host_authority_keepalive
from volpred.ops.delivery import (
    OwnedPublisherArticleReconcile,
    OwnedPublisherReconcileCommand,
    OwnedPublisherReconcileReceipt,
    PublisherArticleReconcileEffectAdapter,
    PublisherArticleReconcileOwner,
    SupabaseArticleProjectionAdapter,
    SupabaseOwnedPublisherReconcileStore,
)

_EFFECT_FAMILY = "publisher.article.supabase.reconcile"
_AUTHORITY_KEY = "publisher:article.supabase.reconcile"
_WORKER_ID = "effect-worker:publisher-article-reconcile"


class ReconcileOwnerStore(Protocol):
    def read_owner(self) -> PublisherArticleReconcileOwner: ...

    def transfer_owner(
        self,
        *,
        expected_owner: str,
        expected_generation: int,
        target_owner: str,
        actor_ref: str,
        reason: str,
        rollback_of_generation: int | None = None,
    ) -> PublisherArticleReconcileOwner: ...


BatchDelivery = Callable[
    [PublisherArticleReconcileOwner, str, tuple[Mapping[str, object], ...]],
    OwnedPublisherReconcileReceipt,
]
ConvergenceReadback = Callable[[], Mapping[str, object]]


@dataclass(frozen=True)
class PublisherReconcileCutoverReceipt:
    schema_version: str
    slug: str
    canonical_feed_sha256: str
    cutover_generation: int
    delivery: Mapping[str, object]
    convergence: Mapping[str, object]
    rollback_generation: int
    rollback_of_generation: int
    final_owner: str
    final_generation: int


def rehearse_publisher_reconcile_cutover(
    *,
    slug: str,
    actor_ref: str,
    feed_path: Path,
    store: ReconcileOwnerStore,
    deliver_batch: BatchDelivery,
    read_convergence: ConvergenceReadback,
) -> PublisherReconcileCutoverReceipt:
    """Deliver, read back, roll back exactly, then restore Operations Core."""

    slug = slug.strip()
    actor_ref = actor_ref.strip()
    if not slug or Path(slug).name != slug:
        raise ValueError("slug must be one path-safe filename component")
    if not actor_ref:
        raise ValueError("actor_ref is required")

    feed_bytes = feed_path.read_bytes()
    decoded = json.loads(feed_bytes)
    feed = decoded.get("items") if isinstance(decoded, dict) else decoded
    if not isinstance(feed, list):
        raise ValueError("canonical feed must be a list or contain items")
    article = next(
        (
            item
            for item in feed
            if isinstance(item, Mapping) and item.get("id") == slug
        ),
        None,
    )
    if article is None:
        raise ValueError("reconcile rehearsal slug is absent from canonical feed")
    if article.get("status") != "published":
        raise ValueError("reconcile rehearsal requires a published article")
    canonical_feed_sha256 = hashlib.sha256(feed_bytes).hexdigest()
    articles = (dict(article),)

    initial = store.read_owner()
    _validate_owner(initial, expected_owner="legacy", minimum_generation=1)
    cutover: PublisherArticleReconcileOwner | None = None
    safe_owner = False
    completed = False
    try:
        cutover = store.transfer_owner(
            expected_owner=initial.owner,
            expected_generation=initial.generation,
            target_owner="operations_core",
            actor_ref=actor_ref,
            reason="safe reconcile acknowledgement and rollback rehearsal",
        )
        _validate_owner(
            cutover,
            expected_owner="operations_core",
            minimum_generation=initial.generation + 1,
        )
        safe_owner = True
        delivery = deliver_batch(
            cutover,
            canonical_feed_sha256,
            articles,
        )
        if (
            not isinstance(delivery, OwnedPublisherReconcileReceipt)
            or not delivery.delivered
            or delivery.owner_generation != cutover.generation
            or delivery.attempt_count != 1
        ):
            raise RuntimeError(
                "safe reconcile did not return the exact acknowledged receipt"
            )

        convergence = dict(read_convergence())
        from volpred.ops.public_article_projection_contract import (
            public_projection_contract_evidence_matches,
        )

        if (
            convergence.get("schema_version")
            != "publisher-projection-convergence.v2"
            or convergence.get("convergence_status") != "converged"
            or convergence.get("mismatch_total") != 0
            or convergence.get("observation_errors") != []
            or not public_projection_contract_evidence_matches(
                convergence.get("public_projection_contract")
            )
        ):
            raise RuntimeError(
                "publisher projection did not converge after reconcile effect"
            )

        rollback = store.transfer_owner(
            expected_owner=cutover.owner,
            expected_generation=cutover.generation,
            target_owner="legacy",
            actor_ref=actor_ref,
            reason=f"exact rollback after effect {delivery.effect_id}",
            rollback_of_generation=cutover.generation,
        )
        _validate_owner(
            rollback,
            expected_owner="legacy",
            minimum_generation=cutover.generation + 1,
        )
        safe_owner = False
        if store.read_owner() != rollback:
            raise RuntimeError("reconcile rollback response and read-back diverged")

        final = store.transfer_owner(
            expected_owner=rollback.owner,
            expected_generation=rollback.generation,
            target_owner="operations_core",
            actor_ref=actor_ref,
            reason="restore safe reconcile owner after rollback rehearsal",
        )
        _validate_owner(
            final,
            expected_owner="operations_core",
            minimum_generation=rollback.generation + 1,
        )
        safe_owner = True
        if store.read_owner() != final:
            raise RuntimeError("reconcile recutover response and read-back diverged")

        receipt = PublisherReconcileCutoverReceipt(
            schema_version="publisher-reconcile-cutover-rehearsal.v1",
            slug=slug,
            canonical_feed_sha256=canonical_feed_sha256,
            cutover_generation=cutover.generation,
            delivery=asdict(delivery),
            convergence=convergence,
            rollback_generation=rollback.generation,
            rollback_of_generation=cutover.generation,
            final_owner=final.owner,
            final_generation=final.generation,
        )
        completed = True
        return receipt
    finally:
        if cutover is not None and safe_owner and not completed:
            current = store.read_owner()
            if current.owner == "operations_core":
                emergency = store.transfer_owner(
                    expected_owner=current.owner,
                    expected_generation=current.generation,
                    target_owner="legacy",
                    actor_ref=actor_ref,
                    reason="automatic rollback after reconcile rehearsal failure",
                    rollback_of_generation=current.generation,
                )
                _validate_owner(
                    emergency,
                    expected_owner="legacy",
                    minimum_generation=current.generation + 1,
                )
                if store.read_owner() != emergency:
                    raise RuntimeError(
                        "automatic reconcile rollback read-back diverged"
                    )


def _validate_owner(
    owner: PublisherArticleReconcileOwner,
    *,
    expected_owner: str,
    minimum_generation: int,
) -> None:
    if (
        not isinstance(owner, PublisherArticleReconcileOwner)
        or owner.effect_family != _EFFECT_FAMILY
        or owner.owner != expected_owner
        or owner.generation < minimum_generation
    ):
        raise RuntimeError(
            "publisher reconcile owner failed its typed identity contract"
        )


def _build_delivery(
    store: SupabaseOwnedPublisherReconcileStore,
    *,
    storage_dir: Path,
    actor_ref: str,
) -> BatchDelivery:
    def deliver(
        owner: PublisherArticleReconcileOwner,
        canonical_feed_sha256: str,
        articles: tuple[Mapping[str, object], ...],
    ) -> OwnedPublisherReconcileReceipt:
        keepalive = build_supabase_host_authority_keepalive(
            authority_key=_AUTHORITY_KEY,
            holder_ref=_WORKER_ID,
        )
        keepalive.start()
        try:
            payload_identity = hashlib.sha256(
                json.dumps(
                    {
                        "canonical_feed_sha256": canonical_feed_sha256,
                        "article_ids": [article["id"] for article in articles],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            return OwnedPublisherArticleReconcile(
                store=store,
                provider=PublisherArticleReconcileEffectAdapter(
                    projection=SupabaseArticleProjectionAdapter(
                        storage_dir=storage_dir
                    )
                ),
                primary_authority=keepalive,
                worker_id=_WORKER_ID,
            ).reconcile(
                OwnedPublisherReconcileCommand(
                    idempotency_key=(
                        "publisher-reconcile-cutover-rehearsal:"
                        f"generation-{owner.generation}:{payload_identity}"
                    ),
                    canonical_feed_sha256=canonical_feed_sha256,
                    articles=articles,
                    actor_ref=actor_ref,
                )
            )
        finally:
            keepalive.stop()

    return deliver


def _read_convergence() -> Mapping[str, object]:
    from scripts.audit_publish_sync import run_audit

    report, exit_code = run_audit()
    if exit_code != 0:
        raise RuntimeError(
            f"publisher convergence audit failed with exit {exit_code}"
        )
    return report


def _atomic_write_receipt(path: Path, receipt: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    payload = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    try:
        temporary.write_text(payload, encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if json.loads(path.read_text(encoding="utf-8")) != receipt:
            raise RuntimeError("reconcile rehearsal receipt read-back diverged")
    finally:
        temporary.unlink(missing_ok=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Cut over safe publisher reconcile, acknowledge one immutable "
            "batch, verify convergence, roll back exactly, and recut over."
        )
    )
    parser.add_argument("--slug", required=True)
    parser.add_argument(
        "--actor",
        default="operator:codex-vscode:publisher-reconcile-cutover",
    )
    parser.add_argument("--storage-dir", default="storage")
    parser.add_argument(
        "--receipt",
        default=(
            "storage/ops/"
            "publisher_reconcile_cutover_rehearsal_latest.json"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    storage_dir = Path(args.storage_dir)
    store = SupabaseOwnedPublisherReconcileStore.from_environment()
    receipt = rehearse_publisher_reconcile_cutover(
        slug=args.slug,
        actor_ref=args.actor,
        feed_path=storage_dir / "reports" / "feed.json",
        store=store,
        deliver_batch=_build_delivery(
            store,
            storage_dir=storage_dir,
            actor_ref=args.actor,
        ),
        read_convergence=_read_convergence,
    )
    payload = asdict(receipt)
    _atomic_write_receipt(Path(args.receipt), payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
