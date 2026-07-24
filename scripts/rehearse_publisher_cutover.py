#!/usr/bin/env python3
"""Rehearse the production publisher owner cutover and exact rollback.

The command deliberately leaves the production owner on ``legacy``.  It
preflights the canonical single-report artifact before changing ownership,
proves that the deployed frontend fences both legacy article-write routes,
delivers one article through the operations-core formal caller, reads the
durable terminal receipt, and rolls the owner back with generation CAS.

Any failure after cutover triggers the same exact rollback in ``finally``.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from volpred.config.runtime import get_default_remote_url
from volpred.ops.delivery.owned_publisher_article import (
    OwnedPublisherArticleCommand,
    OwnedPublisherArticleReceipt,
    PublisherArticleSyncOwner,
    SupabaseOwnedPublisherArticleStore,
)

_EFFECT_FAMILY = "publisher.article.supabase.sync"


class PublisherOwnerStore(Protocol):
    def read_owner(self) -> PublisherArticleSyncOwner: ...

    def transfer_owner(
        self,
        *,
        expected_owner: str,
        expected_generation: int,
        target_owner: str,
        actor_ref: str,
        reason: str,
        rollback_of_generation: int | None = None,
    ) -> PublisherArticleSyncOwner: ...


LiveFenceProbe = Callable[
    [PublisherArticleSyncOwner, Mapping[str, object]],
    tuple[Mapping[str, object], Mapping[str, object]],
]
ArticleDelivery = Callable[
    [PublisherArticleSyncOwner, Mapping[str, object], str],
    OwnedPublisherArticleReceipt,
]


@dataclass(frozen=True)
class PublisherCutoverRehearsalReceipt:
    schema_version: str
    deployment_id: str
    slug: str
    cutover_generation: int
    full_feed_fence: Mapping[str, object]
    single_report_fence: Mapping[str, object]
    delivery: Mapping[str, object]
    final_owner: str
    final_generation: int
    rollback_of_generation: int


def rehearse_publisher_cutover(
    *,
    deployment_id: str,
    slug: str,
    actor_ref: str,
    article_path: Path,
    store: PublisherOwnerStore,
    live_fence_probe: LiveFenceProbe,
    deliver_article: ArticleDelivery,
) -> PublisherCutoverRehearsalReceipt:
    """Run one owner-fenced acknowledgement and leave ownership on legacy."""

    deployment_id = deployment_id.strip()
    slug = slug.strip()
    actor_ref = actor_ref.strip()
    if not deployment_id:
        raise ValueError("deployment_id is required")
    if not slug or Path(slug).name != slug:
        raise ValueError("slug must be one path-safe filename component")
    if not actor_ref:
        raise ValueError("actor_ref is required")

    # Preflight every local input before the first remote mutation.  A missing
    # single-report artifact must never be discovered while the owner is live
    # on operations_core.
    if not article_path.is_file():
        raise FileNotFoundError(
            f"canonical single-report input is missing: {article_path}"
        )
    decoded = json.loads(article_path.read_text())
    if not isinstance(decoded, dict):
        raise ValueError("canonical single-report input must be a JSON object")
    article: Mapping[str, object] = decoded
    if article.get("id") != slug:
        raise ValueError("canonical article id does not match slug")
    if article.get("status") != "published":
        raise ValueError("cutover rehearsal requires a published article")

    initial = store.read_owner()
    _validate_owner(
        initial,
        expected_owner="legacy",
        minimum_generation=1,
    )

    cutover: PublisherArticleSyncOwner | None = None
    rolled_back = False
    try:
        cutover = store.transfer_owner(
            expected_owner=initial.owner,
            expected_generation=initial.generation,
            target_owner="operations_core",
            actor_ref=actor_ref,
            reason=(
                f"frontend {deployment_id} owner-fence and "
                "single-article acknowledgement rehearsal"
            ),
        )
        _validate_owner(
            cutover,
            expected_owner="operations_core",
            minimum_generation=initial.generation + 1,
        )
        if cutover.generation <= initial.generation:
            raise RuntimeError("publisher owner generation did not advance")

        full_feed_fence, single_report_fence = live_fence_probe(
            cutover,
            article,
        )
        idempotency_key = (
            f"publisher-cutover-rehearsal:{deployment_id}:"
            f"generation-{cutover.generation}:{slug}"
        )
        delivery = deliver_article(
            cutover,
            article,
            idempotency_key,
        )
        if (
            not isinstance(delivery, OwnedPublisherArticleReceipt)
            or not delivery.delivered
            or delivery.owner_generation != cutover.generation
            or delivery.attempt_count != 1
        ):
            raise RuntimeError(
                "publisher delivery did not return the exact acknowledged "
                "terminal receipt"
            )

        rollback = store.transfer_owner(
            expected_owner=cutover.owner,
            expected_generation=cutover.generation,
            target_owner="legacy",
            actor_ref=actor_ref,
            reason=(
                "exact rollback rehearsal after acknowledgement "
                f"{delivery.effect_id}"
            ),
            rollback_of_generation=cutover.generation,
        )
        _validate_owner(
            rollback,
            expected_owner="legacy",
            minimum_generation=cutover.generation + 1,
        )
        rolled_back = True
        final = store.read_owner()
        if final != rollback:
            raise RuntimeError(
                "publisher owner rollback response and read-back diverged"
            )

        return PublisherCutoverRehearsalReceipt(
            schema_version="publisher-cutover-rehearsal.v1",
            deployment_id=deployment_id,
            slug=slug,
            cutover_generation=cutover.generation,
            full_feed_fence=dict(full_feed_fence),
            single_report_fence=dict(single_report_fence),
            delivery=asdict(delivery),
            final_owner=final.owner,
            final_generation=final.generation,
            rollback_of_generation=cutover.generation,
        )
    finally:
        if cutover is not None and not rolled_back:
            current = store.read_owner()
            if current.owner == "operations_core":
                emergency = store.transfer_owner(
                    expected_owner=current.owner,
                    expected_generation=current.generation,
                    target_owner="legacy",
                    actor_ref=actor_ref,
                    reason=(
                        "automatic rollback after publisher cutover "
                        "rehearsal failure"
                    ),
                    rollback_of_generation=current.generation,
                )
                _validate_owner(
                    emergency,
                    expected_owner="legacy",
                    minimum_generation=current.generation + 1,
                )
                if store.read_owner() != emergency:
                    raise RuntimeError(
                        "automatic publisher rollback read-back diverged"
                    )


def _validate_owner(
    owner: PublisherArticleSyncOwner,
    *,
    expected_owner: str,
    minimum_generation: int,
) -> None:
    if (
        not isinstance(owner, PublisherArticleSyncOwner)
        or owner.effect_family != _EFFECT_FAMILY
        or owner.owner != expected_owner
        or owner.generation < minimum_generation
    ):
        raise RuntimeError(
            "publisher owner read-back failed its typed identity contract"
        )


def _read_env_value(path: Path, key: str) -> str:
    prefix = f"{key}="
    for line in path.read_text().splitlines():
        if not line.startswith(prefix):
            continue
        value = line[len(prefix) :].strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        if value:
            return value
    raise RuntimeError(f"{key} is missing from {path}")


def _post_live(
    *,
    site_url: str,
    path: str,
    payload: Mapping[str, object] | list[object],
    token: str,
) -> tuple[int, Mapping[str, object]]:
    request = Request(
        f"{site_url.rstrip('/')}{path}",
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={
            "content-type": "application/json",
            "x-ops-key": token,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            status = response.status
            body = json.loads(response.read())
    except HTTPError as exc:
        status = exc.code
        body = json.loads(exc.read())
    if not isinstance(body, dict):
        raise RuntimeError(f"live sync route returned non-object JSON: {path}")
    return status, body


def _build_live_fence_probe(
    *,
    site_url: str,
    token: str,
    slug: str,
) -> LiveFenceProbe:
    def probe(
        owner: PublisherArticleSyncOwner,
        article: Mapping[str, object],
    ) -> tuple[Mapping[str, object], Mapping[str, object]]:
        feed_status, feed_body = _post_live(
            site_url=site_url,
            path="/api/sync/feed.json",
            payload=[],
            token=token,
        )
        if (
            feed_status != 409
            or feed_body.get("status") != "rejected"
            or feed_body.get("reason")
            != "operations_core_owns_publisher_article_sync"
            or feed_body.get("owner_generation") != owner.generation
        ):
            raise RuntimeError(
                "live full-feed route did not prove the operations-core fence"
            )

        # Send the complete canonical article.  The full-feed 409 is checked
        # first, but using the real payload also prevents a partial row from
        # being written if the single-report branch ever drifts independently.
        report_status, report_body = _post_live(
            site_url=site_url,
            path=f"/api/sync/reports/{slug}.json",
            payload=article,
            token=token,
        )
        if (
            report_status != 200
            or report_body.get("status") != "delegated"
            or report_body.get("slug") != slug
            or report_body.get("owner") != "operations_core"
            or report_body.get("owner_generation") != owner.generation
        ):
            raise RuntimeError(
                "live single-report route did not prove the delegated fence"
            )
        return feed_body, report_body

    return probe


def _build_article_delivery(
    store: SupabaseOwnedPublisherArticleStore,
    *,
    actor_ref: str,
) -> ArticleDelivery:
    def deliver(
        owner: PublisherArticleSyncOwner,
        article: Mapping[str, object],
        idempotency_key: str,
    ) -> OwnedPublisherArticleReceipt:
        from scripts.supabase_sync import sync_article

        if (
            sync_article(
                dict(article),
                actor_ref=actor_ref,
                idempotency_key=idempotency_key,
            )
            is not True
        ):
            raise RuntimeError(
                "formal publisher caller did not acknowledge delivery"
            )
        replay = store.request(
            OwnedPublisherArticleCommand(
                idempotency_key=idempotency_key,
                article=article,
                actor_ref=actor_ref,
            ),
            owner_generation=owner.generation,
        )
        if replay.terminal_receipt is None:
            raise RuntimeError(
                "durable publisher terminal receipt recovery failed"
            )
        return replay.terminal_receipt

    return deliver


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rehearse publisher operations-core ownership, verify the live "
            "frontend fence, acknowledge one article, and roll back to legacy."
        )
    )
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument(
        "--actor",
        default="operator:codex-vscode:publisher-cutover",
    )
    parser.add_argument("--storage-dir", default="storage")
    parser.add_argument(
        "--site-url",
        default=get_default_remote_url(),
    )
    parser.add_argument(
        "--frontend-env",
        default="frontend-v2-fix/.env.production",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    store = SupabaseOwnedPublisherArticleStore.from_environment()
    token = _read_env_value(Path(args.frontend_env), "OPS_ADMIN_TOKEN")
    receipt = rehearse_publisher_cutover(
        deployment_id=args.deployment_id,
        slug=args.slug,
        actor_ref=args.actor,
        article_path=Path(args.storage_dir) / "reports" / f"{args.slug}.json",
        store=store,
        live_fence_probe=_build_live_fence_probe(
            site_url=args.site_url,
            token=token,
            slug=args.slug,
        ),
        deliver_article=_build_article_delivery(
            store,
            actor_ref=args.actor,
        ),
    )
    print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
