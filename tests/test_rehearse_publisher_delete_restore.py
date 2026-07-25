from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from scripts.rehearse_publisher_delete_restore import (
    rehearse_publisher_delete_restore,
)
from volpred.ops.delivery import (
    OwnedPublisherDeleteReceipt,
    PublisherArticleDeleteApprovalReadback,
    PublisherArticleDeleteAuthorization,
    PublisherArticleDeleteRestoreReceipt,
    plan_publisher_article_delete,
)
from volpred.ops.delivery.owned_publisher_delete import (
    PublisherArticleDeleteOwner,
)


def _candidate() -> dict:
    article_id = "00000000-0000-0000-0000-000000000777"
    return {
        "article": {
            "id": article_id,
            "slug": "ops-core-delete-restore-smoke-777",
            "status": "published",
            "title": "Synthetic delete restore rehearsal",
        },
        "dependents": {
            "article_impressions": [],
            "article_reactions": [],
            "article_relations": [],
            "article_tags": [],
            "comments": [],
            "question_articles": [],
        },
    }


def _plan():
    return plan_publisher_article_delete(
        canonical_feed=json.dumps(
            [{"id": f"mile_{index}"} for index in range(500)],
            separators=(",", ":"),
        ).encode(),
        candidates=(_candidate(),),
        recovery_artifact_ref="storage/ops/recovery.jsonl",
    )


def _authorization(scope_sha256: str):
    return PublisherArticleDeleteAuthorization(
        approval_ref="approval:publisher-delete-restore/test-1",
        approver_ref="operator:test",
        approved_at="2026-07-25T03:00:00+00:00",
        scope_sha256=scope_sha256,
    )


def _owner(
    *,
    owner: str = "legacy",
    generation: int = 1,
) -> PublisherArticleDeleteOwner:
    return PublisherArticleDeleteOwner(
        schema_version="publisher-article-delete-owner.v1",
        effect_family="publisher.article.supabase.delete",
        owner=owner,
        generation=generation,
        changed_at=f"2026-07-25T03:0{generation}:00+00:00",
        changed_by="operator:test",
        change_reason="test state",
    )


class _Store:
    def __init__(self, authorization) -> None:
        self.owner = _owner()
        self.authorization = authorization
        self.transfers: list[tuple[str, int, str, int | None]] = []
        self.approval_states: list[bool] = []

    def read_owner(self):
        return self.owner

    def transfer_owner(
        self,
        *,
        expected_owner,
        expected_generation,
        target_owner,
        actor_ref,
        reason,
        rollback_of_generation=None,
    ):
        assert self.owner.owner == expected_owner
        assert self.owner.generation == expected_generation
        assert actor_ref and reason
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

    def record_approval(self, authorization, *, actor_ref):
        assert authorization == self.authorization
        assert actor_ref
        self.approval_states.append(True)
        return _approval(authorization, active=True)

    def revoke_approval(
        self,
        *,
        approval_ref,
        actor_ref,
        reason,
    ):
        assert approval_ref == self.authorization.approval_ref
        assert actor_ref and reason
        self.approval_states.append(False)
        return _approval(self.authorization, active=False)


def _approval(authorization, *, active):
    return PublisherArticleDeleteApprovalReadback(
        authorization=authorization,
        active=active,
        evidence_ref="supabase:publisher-delete-approval:test",
        evidence_sha256="a" * 64,
    )


def _delete_receipt(owner, prepared, *, suffix="ok"):
    return OwnedPublisherDeleteReceipt(
        schema_version="owned-publisher-delete-receipt.v1",
        owner_generation=owner.generation,
        work_id=prepared.request.work_item_id,
        work_status="succeeded",
        effect_id=f"effect-{suffix}",
        effect_status="delivered",
        attempt_count=1,
        disposition="delivered",
        evidence_ref=f"supabase:publisher-delete:{suffix}",
        evidence_sha256="b" * 64,
        primary_authority_ref=(
            "primary-authority:publisher:article.supabase.delete:epoch-1"
        ),
        recorded_at="2026-07-25T03:05:00+00:00",
    )


def _restore_receipt(plan, *, restored_count=1):
    return PublisherArticleDeleteRestoreReceipt(
        schema_version="publisher-article-delete-restore-receipt.v1",
        recovery_dump_sha256=plan.recovery_dump_sha256,
        recovery_artifact_ref="storage/ops/recovery.jsonl",
        candidate_count=1,
        restored_count=restored_count,
        evidence_ref="supabase:articles:restore:test",
        evidence_sha256="c" * 64,
    )


def _converged():
    return {
        "schema_version": "publisher-projection-convergence.v2",
        "convergence_status": "converged",
        "mismatch_total": 0,
        "observation_errors": [],
    }


def test_rehearsal_deletes_restores_cleans_up_and_rolls_back():
    plan = _plan()
    authorization = _authorization(plan.scope_sha256)
    store = _Store(authorization)
    phases: list[str] = []

    def deliver(owner, prepared):
        phase = prepared.request.work_item_id.rsplit(":", 1)[-1]
        phases.append(phase)
        return _delete_receipt(owner, prepared, suffix=phase)

    receipt = rehearse_publisher_delete_restore(
        rehearsal_id="smoke-777",
        actor_ref="operator:test",
        plan=plan,
        authorization=authorization,
        recovery_artifact_ref="storage/ops/recovery.jsonl",
        store=store,
        deliver_delete=deliver,
        restore_exact=lambda request: _restore_receipt(plan),
        read_convergence=_converged,
    )

    assert receipt.schema_version == "publisher-delete-restore-rehearsal.v1"
    assert receipt.slug == "ops-core-delete-restore-smoke-777"
    assert receipt.cutover_generation == 2
    assert (receipt.final_owner, receipt.final_generation) == ("legacy", 3)
    assert receipt.rollback_of_generation == 2
    assert receipt.approval_revoked is True
    assert phases == ["delete", "cleanup"]
    assert store.transfers == [
        ("legacy", 1, "operations_core", None),
        ("operations_core", 2, "legacy", 2),
    ]
    assert store.approval_states == [True, False]


def test_delete_receipt_requires_a_materialized_work_identity():
    plan = _plan()
    authorization = _authorization(plan.scope_sha256)
    store = _Store(authorization)

    def deliver(owner, prepared):
        receipt = _delete_receipt(owner, prepared)
        return replace(receipt, work_id="")

    with pytest.raises(RuntimeError, match="exact acknowledged receipt"):
        rehearse_publisher_delete_restore(
            rehearsal_id="smoke-777",
            actor_ref="operator:test",
            plan=plan,
            authorization=authorization,
            recovery_artifact_ref="storage/ops/recovery.jsonl",
            store=store,
            deliver_delete=deliver,
            restore_exact=lambda request: _restore_receipt(plan),
            read_convergence=_converged,
        )

    assert (store.owner.owner, store.owner.generation) == ("legacy", 3)
    assert store.approval_states == [True, False]


def test_delete_phases_must_not_reuse_one_effect_identity():
    plan = _plan()
    authorization = _authorization(plan.scope_sha256)
    store = _Store(authorization)

    with pytest.raises(RuntimeError, match="reused the primary delete effect"):
        rehearse_publisher_delete_restore(
            rehearsal_id="smoke-777",
            actor_ref="operator:test",
            plan=plan,
            authorization=authorization,
            recovery_artifact_ref="storage/ops/recovery.jsonl",
            store=store,
            deliver_delete=lambda owner, prepared: _delete_receipt(
                owner,
                prepared,
                suffix="same-effect",
            ),
            restore_exact=lambda request: _restore_receipt(plan),
            read_convergence=_converged,
        )

    assert (store.owner.owner, store.owner.generation) == ("legacy", 3)
    assert store.approval_states == [True, False]


def test_restore_receipt_must_match_the_exact_artifact_identity():
    plan = _plan()
    authorization = _authorization(plan.scope_sha256)
    store = _Store(authorization)

    with pytest.raises(RuntimeError, match="exact recovery receipt"):
        rehearse_publisher_delete_restore(
            rehearsal_id="smoke-777",
            actor_ref="operator:test",
            plan=plan,
            authorization=authorization,
            recovery_artifact_ref="storage/ops/recovery.jsonl",
            store=store,
            deliver_delete=lambda owner, prepared: _delete_receipt(
                owner,
                prepared,
            ),
            restore_exact=lambda request: replace(
                _restore_receipt(plan),
                recovery_artifact_ref="storage/ops/other.jsonl",
            ),
            read_convergence=_converged,
        )

    assert (store.owner.owner, store.owner.generation) == ("legacy", 3)
    assert store.approval_states == [True, False]


def test_uncertain_first_delete_restores_before_owner_rollback():
    plan = _plan()
    authorization = _authorization(plan.scope_sha256)
    store = _Store(authorization)
    events: list[str] = []

    def fail_delete(owner, prepared):
        events.append("delete")
        raise RuntimeError("response lost after delete")

    def restore(request):
        events.append("restore")
        return _restore_receipt(plan)

    with pytest.raises(RuntimeError, match="response lost"):
        rehearse_publisher_delete_restore(
            rehearsal_id="smoke-777",
            actor_ref="operator:test",
            plan=plan,
            authorization=authorization,
            recovery_artifact_ref="storage/ops/recovery.jsonl",
            store=store,
            deliver_delete=fail_delete,
            restore_exact=restore,
            read_convergence=_converged,
        )

    assert events == ["delete", "restore"]
    assert (store.owner.owner, store.owner.generation) == ("legacy", 3)
    assert store.approval_states == [True, False]


def test_uncertain_delete_accepts_read_only_exact_restore():
    plan = _plan()
    authorization = _authorization(plan.scope_sha256)
    store = _Store(authorization)

    with pytest.raises(RuntimeError, match="response lost before delete"):
        rehearse_publisher_delete_restore(
            rehearsal_id="smoke-777",
            actor_ref="operator:test",
            plan=plan,
            authorization=authorization,
            recovery_artifact_ref="storage/ops/recovery.jsonl",
            store=store,
            deliver_delete=lambda owner, prepared: (_ for _ in ()).throw(
                RuntimeError("response lost before delete")
            ),
            restore_exact=lambda request: _restore_receipt(
                plan,
                restored_count=0,
            ),
            read_convergence=_converged,
        )

    assert (store.owner.owner, store.owner.generation) == ("legacy", 3)
    assert store.approval_states == [True, False]


def test_lost_approval_response_still_attempts_revoke():
    plan = _plan()
    authorization = _authorization(plan.scope_sha256)
    store = _Store(authorization)

    def lose_record_response(authorization, *, actor_ref):
        store.approval_states.append(True)
        raise RuntimeError("approval response lost")

    store.record_approval = lose_record_response

    with pytest.raises(RuntimeError, match="approval response lost"):
        rehearse_publisher_delete_restore(
            rehearsal_id="smoke-777",
            actor_ref="operator:test",
            plan=plan,
            authorization=authorization,
            recovery_artifact_ref="storage/ops/recovery.jsonl",
            store=store,
            deliver_delete=lambda owner, prepared: _delete_receipt(
                owner,
                prepared,
            ),
            restore_exact=lambda request: _restore_receipt(plan),
            read_convergence=_converged,
        )

    assert store.transfers == []
    assert store.approval_states == [True, False]


def test_lost_cutover_response_reads_back_and_rolls_owner_to_legacy():
    plan = _plan()
    authorization = _authorization(plan.scope_sha256)
    store = _Store(authorization)
    transfer = store.transfer_owner
    transfer_calls = 0

    def lose_cutover_response(**kwargs):
        nonlocal transfer_calls
        transfer_calls += 1
        owner = transfer(**kwargs)
        if transfer_calls == 1:
            raise RuntimeError("cutover response lost")
        return owner

    store.transfer_owner = lose_cutover_response

    with pytest.raises(RuntimeError, match="cutover response lost"):
        rehearse_publisher_delete_restore(
            rehearsal_id="smoke-777",
            actor_ref="operator:test",
            plan=plan,
            authorization=authorization,
            recovery_artifact_ref="storage/ops/recovery.jsonl",
            store=store,
            deliver_delete=lambda owner, prepared: _delete_receipt(
                owner,
                prepared,
            ),
            restore_exact=lambda request: _restore_receipt(plan),
            read_convergence=_converged,
        )

    assert (store.owner.owner, store.owner.generation) == ("legacy", 3)
    assert store.approval_states == [True, False]


def test_uncertain_cleanup_restores_candidate_and_fails_closed():
    plan = _plan()
    authorization = _authorization(plan.scope_sha256)
    store = _Store(authorization)
    restore_calls = 0
    delete_calls = 0

    def deliver(owner, prepared):
        nonlocal delete_calls
        delete_calls += 1
        if delete_calls == 2:
            raise RuntimeError("cleanup acknowledgement lost")
        return _delete_receipt(owner, prepared)

    def restore(request):
        nonlocal restore_calls
        restore_calls += 1
        return _restore_receipt(plan)

    with pytest.raises(RuntimeError, match="cleanup acknowledgement"):
        rehearse_publisher_delete_restore(
            rehearsal_id="smoke-777",
            actor_ref="operator:test",
            plan=plan,
            authorization=authorization,
            recovery_artifact_ref="storage/ops/recovery.jsonl",
            store=store,
            deliver_delete=deliver,
            restore_exact=restore,
            read_convergence=_converged,
        )

    assert restore_calls == 2
    assert (store.owner.owner, store.owner.generation) == ("legacy", 3)
    assert store.approval_states == [True, False]


def test_restore_failure_does_not_skip_owner_rollback_or_approval_revoke():
    plan = _plan()
    authorization = _authorization(plan.scope_sha256)
    store = _Store(authorization)

    def fail_delete(owner, prepared):
        raise RuntimeError("delete response lost")

    def fail_restore(request):
        raise RuntimeError("restore unavailable")

    with pytest.raises(RuntimeError, match="cleanup was incomplete"):
        rehearse_publisher_delete_restore(
            rehearsal_id="smoke-777",
            actor_ref="operator:test",
            plan=plan,
            authorization=authorization,
            recovery_artifact_ref="storage/ops/recovery.jsonl",
            store=store,
            deliver_delete=fail_delete,
            restore_exact=fail_restore,
            read_convergence=_converged,
        )

    assert (store.owner.owner, store.owner.generation) == ("legacy", 3)
    assert store.approval_states == [True, False]


def test_rehearsal_rejects_non_synthetic_scope_before_remote_mutation():
    candidate = _candidate()
    candidate["article"]["slug"] = "real-reader-article"
    plan = plan_publisher_article_delete(
        canonical_feed=json.dumps(
            [{"id": f"mile_{index}"} for index in range(500)]
        ).encode(),
        candidates=(candidate,),
        recovery_artifact_ref="storage/ops/recovery.jsonl",
    )
    authorization = _authorization(plan.scope_sha256)
    store = _Store(authorization)

    with pytest.raises(ValueError, match="synthetic candidate"):
        rehearse_publisher_delete_restore(
            rehearsal_id="smoke-777",
            actor_ref="operator:test",
            plan=plan,
            authorization=authorization,
            recovery_artifact_ref="storage/ops/recovery.jsonl",
            store=store,
            deliver_delete=lambda owner, prepared: _delete_receipt(
                owner,
                prepared,
            ),
            restore_exact=lambda request: _restore_receipt(plan),
            read_convergence=_converged,
        )

    assert store.transfers == []
    assert store.approval_states == []


def test_delete_phases_have_distinct_immutable_request_identities():
    plan = _plan()
    authorization = _authorization(plan.scope_sha256)
    store = _Store(authorization)
    identities: list[tuple[str, str]] = []

    def deliver(owner, prepared):
        phase = prepared.request.work_item_id.rsplit(":", 1)[-1]
        identities.append(
            (
                prepared.request.idempotency_key,
                hashlib.sha256(prepared.payload).hexdigest(),
            )
        )
        return _delete_receipt(owner, prepared, suffix=phase)

    rehearse_publisher_delete_restore(
        rehearsal_id="smoke-777",
        actor_ref="operator:test",
        plan=plan,
        authorization=authorization,
        recovery_artifact_ref="storage/ops/recovery.jsonl",
        store=store,
        deliver_delete=deliver,
        restore_exact=lambda request: _restore_receipt(plan),
        read_convergence=_converged,
    )

    assert identities[0][0] != identities[1][0]
    assert identities[0][1] == identities[1][1]
