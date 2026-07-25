#!/usr/bin/env python3
"""Manually rehearse one synthetic publisher delete, restore, and cleanup.

The command only accepts a pre-seeded remote-only article whose slug starts
with ``ops-core-delete-restore-smoke-``. It freezes the exact live candidate
and canonical feed into one scope, records a scope-bound approval, transfers
the destructive family to Operations Core, deletes the synthetic article,
restores every captured row atomically, and deletes the synthetic article
again through a second EffectRequest. The standing publisher audit must then
prove convergence before ownership returns to ``legacy``.

This command is intentionally absent from unattended schedules. The operator
must supply the exact confirmation phrase on every invocation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from volpred.ops.authority import build_supabase_host_authority_keepalive
from volpred.ops.delivery import (
    OwnedPublisherArticleDelete,
    OwnedPublisherDeleteCommand,
    OwnedPublisherDeleteReceipt,
    PreparedPublisherArticleDelete,
    PublisherArticleDeleteApprovalReadback,
    PublisherArticleDeleteAuthorization,
    PublisherArticleDeleteOwner,
    PublisherArticleDeletePlan,
    PublisherArticleDeleteRestoreExecutor,
    PublisherArticleDeleteRestoreReceipt,
    PublisherArticleDeleteRestoreRequest,
    SupabaseOwnedPublisherDeleteStore,
    SupabasePublisherArticleDeleteRestoreProjection,
    SupabasePublisherDeleteProviderFactory,
    plan_publisher_article_delete,
    prepare_publisher_article_delete,
)

_EFFECT_FAMILY = "publisher.article.supabase.delete"
_AUTHORITY_KEY = "publisher:article.supabase.delete"
_WORKER_ID = "effect-worker:publisher-article-delete"
_SYNTHETIC_PREFIX = "ops-core-delete-restore-smoke-"
_CONFIRMATION = "DELETE-RESTORE-SYNTHETIC"
_REHEARSAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{5,63}")


class DeleteRehearsalStore(Protocol):
    def read_owner(self) -> PublisherArticleDeleteOwner: ...

    def transfer_owner(
        self,
        *,
        expected_owner: str,
        expected_generation: int,
        target_owner: str,
        actor_ref: str,
        reason: str,
        rollback_of_generation: int | None = None,
    ) -> PublisherArticleDeleteOwner: ...

    def record_approval(
        self,
        authorization: PublisherArticleDeleteAuthorization,
        *,
        actor_ref: str,
    ) -> PublisherArticleDeleteApprovalReadback: ...

    def revoke_approval(
        self,
        *,
        approval_ref: str,
        actor_ref: str,
        reason: str,
    ) -> PublisherArticleDeleteApprovalReadback: ...


DeleteDelivery = Callable[
    [PublisherArticleDeleteOwner, PreparedPublisherArticleDelete],
    OwnedPublisherDeleteReceipt,
]
ExactRestore = Callable[
    [PublisherArticleDeleteRestoreRequest],
    PublisherArticleDeleteRestoreReceipt,
]
ConvergenceReadback = Callable[[], Mapping[str, object]]


@dataclass(frozen=True)
class PublisherDeleteRestoreRehearsalReceipt:
    schema_version: str
    rehearsal_id: str
    slug: str
    scope_sha256: str
    recovery_dump_sha256: str
    cutover_generation: int
    delete: Mapping[str, object]
    restore: Mapping[str, object]
    cleanup_delete: Mapping[str, object]
    convergence: Mapping[str, object]
    final_owner: str
    final_generation: int
    rollback_of_generation: int
    approval_revoked: bool


def rehearse_publisher_delete_restore(
    *,
    rehearsal_id: str,
    actor_ref: str,
    plan: PublisherArticleDeletePlan,
    authorization: PublisherArticleDeleteAuthorization,
    recovery_artifact_ref: str,
    store: DeleteRehearsalStore,
    deliver_delete: DeleteDelivery,
    restore_exact: ExactRestore,
    read_convergence: ConvergenceReadback,
) -> PublisherDeleteRestoreRehearsalReceipt:
    """Delete, restore, cleanup-delete, and leave the destructive owner legacy."""

    rehearsal_id = rehearsal_id.strip()
    actor_ref = actor_ref.strip()
    recovery_artifact_ref = recovery_artifact_ref.strip()
    if _REHEARSAL_ID.fullmatch(rehearsal_id) is None:
        raise ValueError("rehearsal_id must be a path-safe 6-64 character token")
    if not actor_ref:
        raise ValueError("actor_ref is required")
    if not recovery_artifact_ref:
        raise ValueError("recovery_artifact_ref is required")
    slug = _synthetic_slug(plan)
    if authorization.scope_sha256 != plan.scope_sha256:
        raise ValueError("approval is not bound to the rehearsal scope")

    primary = _prepare_delete(
        phase="delete",
        rehearsal_id=rehearsal_id,
        actor_ref=actor_ref,
        plan=plan,
        authorization=authorization,
    )
    cleanup = _prepare_delete(
        phase="cleanup",
        rehearsal_id=rehearsal_id,
        actor_ref=actor_ref,
        plan=plan,
        authorization=authorization,
    )
    restore_request = PublisherArticleDeleteRestoreRequest(
        recovery_dump=plan.recovery_dump,
        recovery_dump_sha256=plan.recovery_dump_sha256,
        recovery_artifact_ref=recovery_artifact_ref,
        requester_ref=actor_ref,
    )

    initial = store.read_owner()
    _validate_owner(initial, expected_owner="legacy", minimum_generation=1)
    cutover: PublisherArticleDeleteOwner | None = None
    approval_invoked = False
    cutover_invoked = False
    delete_invoked = False
    restore_complete = False
    cleanup_invoked = False
    cleanup_complete = False
    owner_rolled_back = False
    approval_revoked = False
    completed = False
    try:
        # A lost response can follow a successful remote INSERT. Mark the
        # approval uncertain before calling so failure cleanup always tries
        # the idempotent revoke interface.
        approval_invoked = True
        approval = store.record_approval(
            authorization,
            actor_ref=actor_ref,
        )
        _validate_approval(approval, authorization=authorization, active=True)

        # As with approval, mark the CAS uncertain before crossing the RPC
        # boundary. A lost response after commit must still be discovered by
        # read-back and rolled to legacy.
        cutover_invoked = True
        cutover = store.transfer_owner(
            expected_owner=initial.owner,
            expected_generation=initial.generation,
            target_owner="operations_core",
            actor_ref=actor_ref,
            reason=(f"manual synthetic delete-restore rehearsal {rehearsal_id}"),
        )
        _validate_owner(
            cutover,
            expected_owner="operations_core",
            minimum_generation=initial.generation + 1,
        )

        delete_invoked = True
        deleted = deliver_delete(cutover, primary)
        _validate_delete_receipt(
            deleted,
            owner=cutover,
            phase="delete",
        )

        restored = restore_exact(restore_request)
        _validate_restore_receipt(
            restored,
            plan=plan,
            recovery_artifact_ref=recovery_artifact_ref,
        )
        restore_complete = True

        cleanup_invoked = True
        cleanup_deleted = deliver_delete(cutover, cleanup)
        _validate_delete_receipt(
            cleanup_deleted,
            owner=cutover,
            phase="cleanup delete",
        )
        if cleanup_deleted.effect_id == deleted.effect_id:
            raise RuntimeError(
                "publisher cleanup delete reused the primary delete effect"
            )
        cleanup_complete = True

        convergence = dict(read_convergence())
        _validate_convergence(convergence)

        rollback = _rollback_owner(
            store,
            current=cutover,
            actor_ref=actor_ref,
            reason=(
                "exact rollback after synthetic delete-restore-cleanup "
                f"rehearsal {rehearsal_id}"
            ),
        )
        owner_rolled_back = True
        revoked = store.revoke_approval(
            approval_ref=authorization.approval_ref,
            actor_ref=actor_ref,
            reason=f"completed rehearsal {rehearsal_id}",
        )
        _validate_approval(revoked, authorization=authorization, active=False)
        approval_revoked = True

        receipt = PublisherDeleteRestoreRehearsalReceipt(
            schema_version="publisher-delete-restore-rehearsal.v1",
            rehearsal_id=rehearsal_id,
            slug=slug,
            scope_sha256=plan.scope_sha256,
            recovery_dump_sha256=plan.recovery_dump_sha256,
            cutover_generation=cutover.generation,
            delete=asdict(deleted),
            restore=asdict(restored),
            cleanup_delete=asdict(cleanup_deleted),
            convergence=convergence,
            final_owner=rollback.owner,
            final_generation=rollback.generation,
            rollback_of_generation=cutover.generation,
            approval_revoked=True,
        )
        completed = True
        return receipt
    finally:
        if not completed:
            cleanup_errors: list[Exception] = []
            # An RPC can mutate and then lose its response. If either delete
            # entered an uncertain state, exact restore is the safe default.
            if (delete_invoked and not restore_complete) or (
                cleanup_invoked and not cleanup_complete
            ):
                try:
                    recovered = restore_exact(restore_request)
                    _validate_restore_receipt(
                        recovered,
                        plan=plan,
                        recovery_artifact_ref=recovery_artifact_ref,
                        require_full_restore=False,
                    )
                except Exception as exc:  # noqa: BLE001 - preserve all cleanup.
                    cleanup_errors.append(exc)
            if cutover_invoked and not owner_rolled_back:
                try:
                    current = store.read_owner()
                    if current.owner == "operations_core":
                        _rollback_owner(
                            store,
                            current=current,
                            actor_ref=actor_ref,
                            reason=(
                                "automatic rollback after failed synthetic "
                                f"delete-restore rehearsal {rehearsal_id}"
                            ),
                        )
                    else:
                        _validate_owner(
                            current,
                            expected_owner="legacy",
                            minimum_generation=initial.generation,
                        )
                except Exception as exc:  # noqa: BLE001 - continue cleanup.
                    cleanup_errors.append(exc)
            if approval_invoked and not approval_revoked:
                try:
                    revoked = store.revoke_approval(
                        approval_ref=authorization.approval_ref,
                        actor_ref=actor_ref,
                        reason=f"failed rehearsal {rehearsal_id}",
                    )
                    _validate_approval(
                        revoked,
                        authorization=authorization,
                        active=False,
                    )
                except Exception as exc:  # noqa: BLE001 - report after all cleanup.
                    cleanup_errors.append(exc)
            if cleanup_errors:
                raise RuntimeError(
                    "publisher delete-restore failure cleanup was incomplete: "
                    + "; ".join(
                        f"{type(error).__name__}: {error}" for error in cleanup_errors
                    )
                ) from cleanup_errors[0]


def _prepare_delete(
    *,
    phase: str,
    rehearsal_id: str,
    actor_ref: str,
    plan: PublisherArticleDeletePlan,
    authorization: PublisherArticleDeleteAuthorization,
) -> PreparedPublisherArticleDelete:
    return prepare_publisher_article_delete(
        plan=plan,
        authorization=authorization,
        idempotency_key=(f"publisher-delete-restore-rehearsal:{rehearsal_id}:{phase}"),
        work_item_id=(f"publisher-delete-restore-rehearsal:{rehearsal_id}:{phase}"),
        work_item_version=1,
        payload_ref=(f"private://publisher-delete-restore/{rehearsal_id}/{phase}"),
        requester_ref=actor_ref,
    )


def _synthetic_slug(plan: PublisherArticleDeletePlan) -> str:
    if not isinstance(plan, PublisherArticleDeletePlan):
        raise TypeError("publisher delete rehearsal plan is required")
    try:
        scope = json.loads(plan.scope)
        candidates = scope["candidates"]
        slug = candidates[0]["article"]["slug"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("publisher delete rehearsal scope is malformed") from exc
    if (
        plan.delete_count != 1
        or not isinstance(candidates, list)
        or len(candidates) != 1
        or not isinstance(slug, str)
        or not slug.startswith(_SYNTHETIC_PREFIX)
    ):
        raise ValueError(
            "delete-restore rehearsal requires exactly one synthetic candidate"
        )
    return slug


def _validate_owner(
    owner: PublisherArticleDeleteOwner,
    *,
    expected_owner: str,
    minimum_generation: int,
) -> None:
    if (
        not isinstance(owner, PublisherArticleDeleteOwner)
        or owner.effect_family != _EFFECT_FAMILY
        or owner.owner != expected_owner
        or owner.generation < minimum_generation
    ):
        raise RuntimeError("publisher delete owner failed its typed identity contract")


def _validate_approval(
    readback: PublisherArticleDeleteApprovalReadback,
    *,
    authorization: PublisherArticleDeleteAuthorization,
    active: bool,
) -> None:
    if (
        not isinstance(readback, PublisherArticleDeleteApprovalReadback)
        or readback.authorization != authorization
        or readback.active is not active
        or not readback.evidence_ref.strip()
        or len(readback.evidence_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in readback.evidence_sha256
        )
    ):
        raise RuntimeError(
            "publisher delete approval failed its typed identity contract"
        )


def _validate_delete_receipt(
    receipt: OwnedPublisherDeleteReceipt,
    *,
    owner: PublisherArticleDeleteOwner,
    phase: str,
) -> None:
    if (
        not isinstance(receipt, OwnedPublisherDeleteReceipt)
        or receipt.schema_version != "owned-publisher-delete-receipt.v1"
        or not receipt.delivered
        or receipt.owner_generation != owner.generation
        or not receipt.work_id.strip()
        or receipt.attempt_count != 1
        or not receipt.effect_id.strip()
        or not receipt.evidence_ref.strip()
        or len(receipt.evidence_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in receipt.evidence_sha256
        )
        or not receipt.primary_authority_ref.startswith(
            f"primary-authority:{_AUTHORITY_KEY}:epoch-"
        )
        or not receipt.recorded_at.strip()
    ):
        raise RuntimeError(
            f"publisher {phase} did not return the exact acknowledged receipt"
        )


def _validate_restore_receipt(
    receipt: PublisherArticleDeleteRestoreReceipt,
    *,
    plan: PublisherArticleDeletePlan,
    recovery_artifact_ref: str,
    require_full_restore: bool = True,
) -> None:
    restored_count = getattr(receipt, "restored_count", None)
    if (
        not isinstance(receipt, PublisherArticleDeleteRestoreReceipt)
        or receipt.schema_version
        != "publisher-article-delete-restore-receipt.v1"
        or receipt.recovery_dump_sha256 != plan.recovery_dump_sha256
        or receipt.recovery_artifact_ref != recovery_artifact_ref
        or isinstance(receipt.candidate_count, bool)
        or not isinstance(receipt.candidate_count, int)
        or receipt.candidate_count != plan.delete_count
        or isinstance(restored_count, bool)
        or not isinstance(restored_count, int)
        or restored_count < 0
        or restored_count > plan.delete_count
        or (require_full_restore and restored_count != plan.delete_count)
        or not receipt.evidence_ref.strip()
        or len(receipt.evidence_sha256) != 64
        or any(
            character not in "0123456789abcdef"
            for character in receipt.evidence_sha256
        )
    ):
        raise RuntimeError(
            "publisher restore did not return the exact recovery receipt"
        )


def _validate_convergence(convergence: Mapping[str, object]) -> None:
    if (
        convergence.get("schema_version") != "publisher-projection-convergence.v2"
        or convergence.get("convergence_status") != "converged"
        or convergence.get("mismatch_total") != 0
        or convergence.get("observation_errors") != []
    ):
        raise RuntimeError("publisher projection did not converge after cleanup delete")


def _rollback_owner(
    store: DeleteRehearsalStore,
    *,
    current: PublisherArticleDeleteOwner,
    actor_ref: str,
    reason: str,
) -> PublisherArticleDeleteOwner:
    rollback = store.transfer_owner(
        expected_owner=current.owner,
        expected_generation=current.generation,
        target_owner="legacy",
        actor_ref=actor_ref,
        reason=reason,
        rollback_of_generation=current.generation,
    )
    _validate_owner(
        rollback,
        expected_owner="legacy",
        minimum_generation=current.generation + 1,
    )
    if store.read_owner() != rollback:
        raise RuntimeError("publisher delete rollback read-back diverged")
    return rollback


def _build_delete_delivery(
    store: SupabaseOwnedPublisherDeleteStore,
    *,
    actor_ref: str,
) -> DeleteDelivery:
    def deliver(
        owner: PublisherArticleDeleteOwner,
        prepared: PreparedPublisherArticleDelete,
    ) -> OwnedPublisherDeleteReceipt:
        keepalive = build_supabase_host_authority_keepalive(
            authority_key=_AUTHORITY_KEY,
            holder_ref=_WORKER_ID,
        )
        keepalive.start()
        try:
            return OwnedPublisherArticleDelete(
                store=store,
                provider_factory=(
                    SupabasePublisherDeleteProviderFactory.from_environment()
                ),
                primary_authority=keepalive,
                worker_id=_WORKER_ID,
            ).delete(
                OwnedPublisherDeleteCommand(
                    prepared=prepared,
                    actor_ref=actor_ref,
                )
            )
        finally:
            keepalive.stop()

    return deliver


def _build_restore() -> ExactRestore:
    executor = PublisherArticleDeleteRestoreExecutor(
        projection=(SupabasePublisherArticleDeleteRestoreProjection.from_environment())
    )

    def restore(
        request: PublisherArticleDeleteRestoreRequest,
    ) -> PublisherArticleDeleteRestoreReceipt:
        return executor.restore(
            request,
            authorize_mutation=lambda: None,
        )

    return restore


def _read_convergence() -> Mapping[str, object]:
    from scripts.audit_publish_sync import run_audit

    report, exit_code = run_audit()
    if exit_code != 0:
        raise RuntimeError(f"publisher convergence audit failed with exit {exit_code}")
    return report


def _load_candidate(path: Path) -> Mapping[str, object]:
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, Mapping):
        raise TypeError("synthetic candidate JSON must be one object")
    return decoded


def _atomic_write(
    path: Path,
    payload: bytes,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == payload:
            return
        raise RuntimeError(f"existing artifact has different bytes: {path}")
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(payload)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if path.read_bytes() != payload:
            raise RuntimeError(f"artifact read-back diverged: {path}")
    finally:
        temporary.unlink(missing_ok=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Manually delete, exactly restore, cleanup-delete, and verify one "
            "pre-seeded synthetic publisher article."
        )
    )
    parser.add_argument("--rehearsal-id", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument(
        "--actor",
        default="operator:publisher-delete-restore-rehearsal",
    )
    parser.add_argument("--approver", required=True)
    parser.add_argument("--storage-dir", default="storage")
    parser.add_argument(
        "--recovery-artifact",
        default=None,
        help=(
            "immutable recovery path; defaults to a rehearsal-id-specific "
            "artifact under storage/ops/publisher_delete_restore/"
        ),
    )
    parser.add_argument(
        "--receipt",
        default=None,
        help=(
            "immutable receipt path; defaults to a rehearsal-id-specific "
            "artifact under storage/ops/publisher_delete_restore/"
        ),
    )
    parser.add_argument(
        "--confirm",
        required=True,
        help=f"must equal {_CONFIRMATION}",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.confirm != _CONFIRMATION:
        raise SystemExit(
            f"refusing destructive rehearsal: --confirm must equal {_CONFIRMATION}"
        )
    storage_dir = Path(args.storage_dir)
    candidate = _load_candidate(Path(args.candidate))
    artifact_dir = storage_dir / "ops" / "publisher_delete_restore"
    recovery_path = (
        Path(args.recovery_artifact)
        if args.recovery_artifact
        else artifact_dir / f"{args.rehearsal_id}_recovery.jsonl"
    )
    receipt_path = (
        Path(args.receipt)
        if args.receipt
        else artifact_dir / f"{args.rehearsal_id}_receipt.json"
    )
    if receipt_path.exists():
        raise RuntimeError(
            "refusing to reuse a completed rehearsal receipt path: "
            f"{receipt_path}"
        )
    plan = plan_publisher_article_delete(
        canonical_feed=(storage_dir / "reports" / "feed.json").read_bytes(),
        candidates=(candidate,),
        recovery_artifact_ref=str(recovery_path),
    )
    _synthetic_slug(plan)
    _atomic_write(recovery_path, plan.recovery_dump)

    projection = SupabasePublisherArticleDeleteRestoreProjection.from_environment()
    observed = projection.readback(candidate)
    if observed.absent or observed.candidate != candidate:
        raise RuntimeError(
            "synthetic candidate must be pre-seeded and exact before rehearsal"
        )

    authorization = PublisherArticleDeleteAuthorization(
        approval_ref=(f"approval:publisher-delete-restore/{args.rehearsal_id}"),
        approver_ref=args.approver,
        approved_at=datetime.now(UTC).isoformat(),
        scope_sha256=plan.scope_sha256,
    )
    store = SupabaseOwnedPublisherDeleteStore.from_environment()
    receipt = rehearse_publisher_delete_restore(
        rehearsal_id=args.rehearsal_id,
        actor_ref=args.actor,
        plan=plan,
        authorization=authorization,
        recovery_artifact_ref=str(recovery_path),
        store=store,
        deliver_delete=_build_delete_delivery(
            store,
            actor_ref=args.actor,
        ),
        restore_exact=_build_restore(),
        read_convergence=_read_convergence,
    )
    payload = (
        json.dumps(
            asdict(receipt),
            ensure_ascii=False,
            indent=2,
        ).encode()
        + b"\n"
    )
    _atomic_write(
        receipt_path,
        payload,
    )
    print(payload.decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
