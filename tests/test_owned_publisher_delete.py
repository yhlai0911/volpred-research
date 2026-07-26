from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import pytest

from volpred.ops.authority import PrimaryLease
from volpred.ops.delivery import (
    AcknowledgedEffect,
    EffectDelivery,
    OwnedPublisherArticleDelete,
    OwnedPublisherDeleteAttempt,
    OwnedPublisherDeleteCommand,
    OwnedPublisherDeleteReconciliation,
    OwnedPublisherDeleteReconciliationReceipt,
    OwnedPublisherDeleteReconciliationSummary,
    OwnedPublisherDeleteReceipt,
    OwnedPublisherDeleteRequest,
    PublisherArticleDeleteApprovalReadback,
    PublisherArticleDeleteAuthorization,
    PublisherArticleDeleteCandidateReadback,
    PublisherArticleDeleteEffectAdapter,
    PublisherArticleDeleteOwner,
    PublisherArticleDeleteOwnershipLost,
    SupabaseOwnedPublisherDeleteStore,
    SupabasePublisherArticleDeleteApprovalVerifier,
    SupabasePublisherArticleDeleteProjection,
    SupabasePublisherArticleDeleteRestoreProjection,
    plan_publisher_article_delete,
    prepare_publisher_article_delete,
)


def _candidate() -> dict:
    article_id = "article-delete-owned-1"
    return {
        "article": {
            "id": article_id,
            "slug": "mile_owned_delete",
            "title": "Owned delete fixture",
        },
        "dependents": {
            "article_impressions": [
                {"id": "imp-1", "article_id": article_id}
            ],
            "article_reactions": [],
            "article_relations": [
                {
                    "id": "rel-1",
                    "source_id": article_id,
                    "target_id": "article-other",
                }
            ],
            "article_tags": [],
            "comments": [],
            "question_articles": [],
        },
    }


def _authorization(
    scope_sha256: str,
) -> PublisherArticleDeleteAuthorization:
    return PublisherArticleDeleteAuthorization(
        approval_ref="approval:publisher-delete/owned-1",
        approver_ref="owner:telegram/1329",
        approved_at="2026-07-25T00:00:00+00:00",
        scope_sha256=scope_sha256,
    )


def _prepared():
    canonical_feed = json.dumps(
        [{"id": f"mile_{index:03d}"} for index in range(500)],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    plan = plan_publisher_article_delete(
        canonical_feed=canonical_feed,
        candidates=[_candidate()],
        recovery_artifact_ref="recovery:publisher-delete/owned-1",
    )
    return prepare_publisher_article_delete(
        plan=plan,
        authorization=_authorization(plan.scope_sha256),
        idempotency_key="publisher:delete:owned-1",
        work_item_id="work-placeholder-delete-1",
        work_item_version=1,
        payload_ref="effect-payload:placeholder-delete-1",
        requester_ref="operator:publisher-delete",
    )


def _owner(
    owner: str = "operations_core",
) -> PublisherArticleDeleteOwner:
    return PublisherArticleDeleteOwner(
        schema_version="publisher-article-delete-owner.v1",
        effect_family="publisher.article.supabase.delete",
        owner=owner,
        generation=4,
        changed_at="2026-07-25T00:00:00+00:00",
        changed_by="operator:test",
        change_reason="test owner",
    )


def _effect(prepared):
    effect = EffectDelivery(
        clock=lambda: datetime(2026, 7, 25, tzinfo=UTC),
        id_factory=lambda: "effect-owned-publisher-delete-1",
    ).request(prepared.request)
    return replace(
        effect,
        id="effect-owned-publisher-delete-1",
        work_item_id="work-owned-publisher-delete-1",
        work_item_version=3,
        payload_ref="effect-payload:owned-publisher-delete-1",
        request_sha256="a" * 64,
        created_at="2026-07-25T00:00:00+00:00",
    )


def _attempt(prepared) -> OwnedPublisherDeleteAttempt:
    return OwnedPublisherDeleteAttempt(
        owner_generation=4,
        work_id="work-owned-publisher-delete-1",
        work_version=3,
        work_lease_token="work-token",
        effect=_effect(prepared),
        payload=prepared.payload,
        outbox_sequence=41,
        attempt_count=1,
        outbox_claim_token="outbox-token",
        worker_id="effect-worker:publisher-article-delete",
        primary_authority_key="publisher:article.supabase.delete",
        primary_authority_holder_ref=(
            "effect-worker:publisher-article-delete"
        ),
        primary_authority_epoch=7,
        primary_fencing_token="primary-token",
        authority_request_sha256="b" * 64,
        outbox_claim_ref="effect-outbox:41:attempt-1",
        primary_authority_ref=(
            "primary-authority:"
            "publisher:article.supabase.delete:epoch-7"
        ),
        lease_expires_at="2026-07-25T00:05:00+00:00",
    )


def test_stale_retry_reconciliation_has_no_provider_mutation_seam():
    expected = OwnedPublisherDeleteReconciliationSummary(
        schema_version="owned-publisher-delete-reconciliation-summary.v1",
        reconciled_count=1,
        receipts=(
            OwnedPublisherDeleteReconciliationReceipt(
                schema_version=(
                    "owned-publisher-delete-reconciliation-receipt.v1"
                ),
                effect_id="effect-owned-publisher-delete-1",
                attempt_count=1,
                stale_owner_generation=4,
                current_owner_generation=5,
                approval_ref="approval:publisher-delete/owned-1",
                reason_code="stale_generation_revoked_approval",
                evidence_ref=(
                    "owned-publisher-delete-reconciliation:"
                    "effect-owned-publisher-delete-1:attempt-1"
                ),
                evidence_sha256="e" * 64,
                recorded_at="2026-07-26T10:00:00+00:00",
            ),
        ),
    )

    class Store:
        def __init__(self) -> None:
            self.calls: list[tuple[int, str]] = []

        def reconcile_stale_retries(
            self,
            *,
            limit: int,
            actor_ref: str,
        ) -> OwnedPublisherDeleteReconciliationSummary:
            self.calls.append((limit, actor_ref))
            return expected

    store = Store()
    result = OwnedPublisherDeleteReconciliation(
        store=store,
        actor_ref="effect-worker:publisher-delete-reconciliation",
    ).reconcile(limit=25)

    assert result == expected
    assert store.calls == [
        (25, "effect-worker:publisher-delete-reconciliation")
    ]


class _Approval:
    def readback(self, authorization):
        return PublisherArticleDeleteApprovalReadback(
            authorization=authorization,
            active=True,
            evidence_ref="approval-readback:owned-1",
            evidence_sha256="c" * 64,
        )


class _Projection:
    def __init__(self, candidate: dict) -> None:
        self.candidate = json.loads(json.dumps(candidate))
        self.delete_calls = 0

    def readback(self, expected_candidate):
        article_id = expected_candidate["article"]["id"]
        candidate = (
            None
            if self.candidate is None
            else json.loads(json.dumps(self.candidate))
        )
        return PublisherArticleDeleteCandidateReadback(
            article_id=article_id,
            candidate=candidate,
            evidence_ref=f"supabase:articles:{article_id}",
            evidence_sha256="d" * 64,
        )

    def delete(self, expected_candidate):
        assert self.candidate == expected_candidate
        self.delete_calls += 1
        self.candidate = None
        return True


class _Store:
    def __init__(self, prepared, owner=None) -> None:
        self.owner = owner or _owner()
        self.request_view = OwnedPublisherDeleteRequest(
            owner_generation=self.owner.generation,
            work_id="work-owned-publisher-delete-1",
            effect_id="effect-owned-publisher-delete-1",
            request_sha256="e" * 64,
        )
        self.attempt = _attempt(prepared)
        self.calls: list[str] = []

    def read_owner(self):
        self.calls.append("owner")
        return self.owner

    def request(self, command, *, owner_generation):
        self.calls.append("request")
        assert owner_generation == self.owner.generation
        assert command.prepared.payload == self.attempt.payload
        return self.request_view

    def begin(self, request_view, **kwargs):
        self.calls.append("begin")
        return replace(
            self.attempt,
            work_lease_token=kwargs["work_lease_token"],
            outbox_claim_token=kwargs["outbox_claim_token"],
            primary_fencing_token=kwargs["primary_fencing_token"],
        )

    def settle(self, attempt, outcome):
        self.calls.append("settle")
        assert isinstance(outcome, AcknowledgedEffect)
        return OwnedPublisherDeleteReceipt(
            schema_version="owned-publisher-delete-receipt.v1",
            owner_generation=attempt.owner_generation,
            work_id=attempt.work_id,
            work_status="succeeded",
            effect_id=attempt.effect.id,
            effect_status="delivered",
            attempt_count=attempt.attempt_count,
            disposition="delivered",
            evidence_ref=outcome.evidence_ref,
            evidence_sha256=outcome.evidence_sha256,
            primary_authority_ref=attempt.primary_authority_ref,
            recorded_at="2026-07-25T00:00:01+00:00",
        )


class _LeaseGate:
    def current_lease(self):
        return PrimaryLease(
            schema_version="primary-lease.v1",
            authority_key="publisher:article.supabase.delete",
            holder_ref="effect-worker:publisher-article-delete",
            epoch=7,
            fencing_token="primary-token",
            lease_seconds=300,
            acquired_at="2026-07-25T00:00:00+00:00",
            expires_at="2026-07-25T00:05:00+00:00",
        )


def test_owned_delete_runs_durable_lifecycle_and_attempt_bound_provider():
    prepared = _prepared()
    store = _Store(prepared)
    projection = _Projection(_candidate())
    seen_attempts: list[OwnedPublisherDeleteAttempt] = []

    def provider_factory(attempt):
        seen_attempts.append(attempt)
        return PublisherArticleDeleteEffectAdapter(
            approval=_Approval(),
            projection=projection,
        )

    receipt = OwnedPublisherArticleDelete(
        store=store,
        provider_factory=provider_factory,
        primary_authority=_LeaseGate(),
        token_factory=iter(["work-token", "outbox-token"]).__next__,
    ).delete(
        OwnedPublisherDeleteCommand(
            prepared=prepared,
            actor_ref="operator:publisher-delete",
        )
    )

    assert receipt.delivered is True
    assert store.calls == ["owner", "request", "begin", "settle"]
    assert seen_attempts == [store.attempt]
    assert projection.delete_calls == 1


def test_owned_delete_refuses_legacy_owner_before_request():
    prepared = _prepared()
    store = _Store(prepared, owner=_owner("legacy"))

    with pytest.raises(
        PublisherArticleDeleteOwnershipLost,
        match="does not own",
    ):
        OwnedPublisherArticleDelete(
            store=store,
            provider_factory=lambda _attempt: pytest.fail(
                "provider must not be built"
            ),
            primary_authority=_LeaseGate(),
        ).delete(
            OwnedPublisherDeleteCommand(
                prepared=prepared,
                actor_ref="operator:publisher-delete",
            )
        )

    assert store.calls == ["owner"]


class _RpcClient:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def call(self, function: str, payload: dict):
        self.calls.append((function, payload))
        response = self.responses[function]
        if isinstance(response, Exception):
            raise response
        return response


def _approval_response(*, active: bool = True) -> dict:
    authorization = _authorization(_prepared().scope_sha256)
    return {
        "schema_version": "publisher-article-delete-approval-readback.v1",
        "authorization": {
            "approval_ref": authorization.approval_ref,
            "approver_ref": authorization.approver_ref,
            "approved_at": authorization.approved_at,
            "scope_sha256": authorization.scope_sha256,
        },
        "active": active,
        "evidence_ref": "supabase:publisher-delete-approval:owned-1",
        "evidence_sha256": "f" * 64,
    }


def test_supabase_store_preserves_exact_canonical_payload_text():
    prepared = _prepared()
    client = _RpcClient(
        {
            "volpred_request_owned_publisher_article_delete": {
                "schema_version": "owned-publisher-delete-request.v1",
                "owner_generation": 4,
                "work_id": "work-owned-publisher-delete-1",
                "effect_id": "effect-owned-publisher-delete-1",
                "request_sha256": "a" * 64,
                "receipt": None,
            }
        }
    )
    store = object.__new__(SupabaseOwnedPublisherDeleteStore)
    store._client = client

    store.request(
        OwnedPublisherDeleteCommand(
            prepared=prepared,
            actor_ref="operator:publisher-delete",
        ),
        owner_generation=4,
    )

    function, payload = client.calls[0]
    assert function == "volpred_request_owned_publisher_article_delete"
    assert payload["p_payload_text"].encode() == prepared.payload
    assert "p_payload" not in payload


def test_supabase_store_reconciles_stale_retries_through_exact_rpc():
    response = {
        "schema_version": (
            "owned-publisher-delete-reconciliation-summary.v1"
        ),
        "reconciled_count": 1,
        "receipts": [
            {
                "schema_version": (
                    "owned-publisher-delete-reconciliation-receipt.v1"
                ),
                "effect_id": "effect-owned-publisher-delete-1",
                "attempt_count": 1,
                "stale_owner_generation": 4,
                "current_owner_generation": 5,
                "approval_ref": "approval:publisher-delete/owned-1",
                "reason_code": "stale_generation_revoked_approval",
                "evidence_ref": (
                    "owned-publisher-delete-reconciliation:"
                    "effect-owned-publisher-delete-1:attempt-1"
                ),
                "evidence_sha256": "e" * 64,
                "recorded_at": "2026-07-26T10:00:00+00:00",
            }
        ],
    }
    client = _RpcClient(
        {
            "volpred_reconcile_stale_owned_publisher_article_delete": (
                response
            )
        }
    )
    store = object.__new__(SupabaseOwnedPublisherDeleteStore)
    store._client = client

    summary = store.reconcile_stale_retries(
        limit=25,
        actor_ref="effect-worker:publisher-delete-reconciliation",
    )

    assert summary.reconciled_count == 1
    assert summary.receipts[0].stale_owner_generation == 4
    assert client.calls == [
        (
            "volpred_reconcile_stale_owned_publisher_article_delete",
            {
                "p_limit": 25,
                "p_actor_ref": (
                    "effect-worker:publisher-delete-reconciliation"
                ),
            },
        )
    ]


def test_projection_compare_delete_sends_attempt_and_approval_identity():
    prepared = _prepared()
    candidate = _candidate()
    client = _RpcClient(
        {
            "volpred_read_publisher_article_delete_candidate": {
                "article_id": candidate["article"]["id"],
                "candidate": candidate,
                "evidence_ref": "supabase:publisher-delete-candidate:owned-1",
                "evidence_sha256": "1" * 64,
            },
            "volpred_execute_publisher_article_compare_delete": {
                "schema_version": (
                    "publisher-article-compare-delete-execution.v1"
                ),
                "ok": True,
                "result": {"deleted": True},
                "error": None,
            },
        }
    )
    projection = SupabasePublisherArticleDeleteProjection(
        client=client,
        attempt=_attempt(prepared),
        authorization=_authorization(prepared.scope_sha256),
    )

    assert projection.readback(candidate).candidate == candidate
    assert projection.delete(candidate) is True

    _, payload = client.calls[-1]
    assert payload["p_owner_generation"] == 4
    assert payload["p_attempt_count"] == 1
    assert payload["p_primary_authority_epoch"] == 7
    assert payload["p_expected_candidate"] == candidate
    assert (
        payload["p_authorization"]["scope_sha256"]
        == prepared.scope_sha256
    )


def test_projection_reports_read_only_preflight_when_compare_rpc_fails():
    prepared = _prepared()
    candidate = _candidate()
    diagnostic = {
        "schema_version": "publisher-article-compare-delete-diagnostic.v1",
        "owner_match": True,
        "request_match": True,
        "attempt_match": False,
        "effect_match": True,
        "payload_match": True,
        "approval_match": True,
        "primary_lease_match": True,
        "dependency_contract_match": True,
        "candidate_exact": True,
    }
    client = _RpcClient(
        {
            "volpred_execute_publisher_article_compare_delete": {
                "schema_version": (
                    "publisher-article-compare-delete-execution.v1"
                ),
                "ok": False,
                "result": None,
                "error": {
                    "sqlstate": "P0002",
                    "message": "query returned no rows",
                    "detail": None,
                    "hint": None,
                    "context": (
                        "PL/pgSQL function "
                        "volpred_compare_delete_publisher_article line 99"
                    ),
                },
            },
            "volpred_diagnose_publisher_article_compare_delete": diagnostic,
        }
    )
    projection = SupabasePublisherArticleDeleteProjection(
        client=client,
        attempt=_attempt(prepared),
        authorization=_authorization(prepared.scope_sha256),
    )

    with pytest.raises(
        RuntimeError,
        match=r'preflight_failed_checks=\["attempt_match"\]',
    ):
        projection.delete(candidate)

    assert [function for function, _ in client.calls] == [
        "volpred_execute_publisher_article_compare_delete",
        "volpred_diagnose_publisher_article_compare_delete",
    ]
    assert client.calls[0][1] == client.calls[1][1]


def test_restore_projection_sends_one_exact_batch_and_reuses_readback():
    candidate = _candidate()
    client = _RpcClient(
        {
            "volpred_read_publisher_article_delete_candidate": {
                "article_id": candidate["article"]["id"],
                "candidate": candidate,
                "evidence_ref": "supabase:publisher-delete-candidate:owned-1",
                "evidence_sha256": "1" * 64,
            },
            "volpred_restore_publisher_article_delete_batch": {
                "schema_version": (
                    "publisher-article-delete-restore-batch.v1"
                ),
                "candidate_count": 1,
                "restored_count": 1,
                "restored": True,
            },
        }
    )
    projection = SupabasePublisherArticleDeleteRestoreProjection(
        client=client,
    )

    assert projection.readback(candidate).candidate == candidate
    assert projection.restore_batch((candidate,)) is True
    assert client.calls[-1] == (
        "volpred_restore_publisher_article_delete_batch",
        {"p_expected_candidates": [candidate]},
    )


@pytest.mark.parametrize(
    "response",
    [
        {
            "schema_version": "publisher-article-delete-restore-batch.v0",
            "candidate_count": 1,
            "restored_count": 1,
            "restored": True,
        },
        {
            "schema_version": "publisher-article-delete-restore-batch.v1",
            "candidate_count": 2,
            "restored_count": 1,
            "restored": True,
        },
        {
            "schema_version": "publisher-article-delete-restore-batch.v1",
            "candidate_count": 1,
            "restored_count": 2,
            "restored": True,
        },
        {
            "schema_version": "publisher-article-delete-restore-batch.v1",
            "candidate_count": 1,
            "restored_count": 1,
            "restored": False,
        },
    ],
)
def test_restore_projection_fails_closed_on_rpc_receipt_drift(response):
    candidate = _candidate()
    client = _RpcClient(
        {"volpred_restore_publisher_article_delete_batch": response}
    )

    with pytest.raises(RuntimeError, match="restore response"):
        SupabasePublisherArticleDeleteRestoreProjection(
            client=client,
        ).restore_batch((candidate,))


def test_approval_verifier_requires_typed_durable_readback():
    prepared = _prepared()
    response = _approval_response()
    client = _RpcClient(
        {"volpred_read_publisher_article_delete_approval": response}
    )
    verifier = SupabasePublisherArticleDeleteApprovalVerifier(client=client)

    readback = verifier.readback(
        _authorization(prepared.scope_sha256)
    )

    assert readback.active is True
    assert readback.authorization.scope_sha256 == prepared.scope_sha256
    assert client.calls == [
        (
            "volpred_read_publisher_article_delete_approval",
            {"p_approval_ref": "approval:publisher-delete/owned-1"},
        )
    ]


def test_delete_migration_fences_every_destructive_boundary():
    sql = Path(
        "supabase/migrations/"
        "20260725002427_operations_core_publisher_delete_ownership.sql"
    ).read_text()

    required = (
        "publisher.article.supabase.delete",
        "publisher:article.supabase.delete",
        "publisher_article_delete_approvals",
        "p_payload_text text",
        "'destructive'",
        "owned_notification_attempts",
        "primary_authority_leases",
        "FOR SHARE",
        "FOR UPDATE",
        "volpred_read_article_delete_dependency_contract",
        "volpred_compare_delete_publisher_article",
        "p_expected_candidate",
        "effect_payload -> 'authorization'",
        "REVOKE ALL ON FUNCTION",
        "FROM PUBLIC, anon, authenticated",
        "TO service_role",
    )
    assert all(fragment in sql for fragment in required)
    assert "publisher safe reconcile" not in sql
    assert "bigint, text, jsonb, text" not in sql


def test_compare_delete_diagnostic_is_read_only_and_service_role_only():
    sql = Path(
        "supabase/migrations/"
        "20260725204038_publisher_delete_compare_preflight_diagnostics.sql"
    ).read_text()

    required = (
        "publisher-article-compare-delete-diagnostic.v1",
        "'owner_match', EXISTS",
        "'request_match', EXISTS",
        "'attempt_match', EXISTS",
        "'effect_match', EXISTS",
        "'payload_match', EXISTS",
        "'approval_match', EXISTS",
        "'primary_lease_match', EXISTS",
        "'dependency_contract_match'",
        "'candidate_exact'",
        "SECURITY DEFINER",
        "SET search_path = ''",
        "FROM PUBLIC, anon, authenticated",
        "TO service_role",
    )
    assert all(fragment in sql for fragment in required)
    assert "DELETE FROM" not in sql
    assert "UPDATE " not in sql
    assert "INSERT INTO" not in sql


def test_compare_delete_execution_preserves_typed_exception_context():
    sql = Path(
        "supabase/migrations/"
        "20260725204444_publisher_delete_compare_exception_context.sql"
    ).read_text()

    required = (
        "publisher-article-compare-delete-execution.v1",
        "volpred_compare_delete_publisher_article(",
        "EXCEPTION WHEN OTHERS",
        "GET STACKED DIAGNOSTICS",
        "RETURNED_SQLSTATE",
        "PG_EXCEPTION_CONTEXT",
        "SECURITY DEFINER",
        "SET search_path = ''",
        "FROM PUBLIC, anon, authenticated",
        "TO service_role",
    )
    assert all(fragment in sql for fragment in required)


def test_compare_delete_does_not_lock_the_immutable_owned_request():
    sql = Path(
        "supabase/migrations/"
        "20260725205013_remove_owned_request_share_lock.sql"
    ).read_text()

    request_read = (
        "SELECT * INTO STRICT owned_request\n"
        "  FROM volpred_ops.owned_notification_requests\n"
        "  WHERE effect_id = btrim(p_effect_id)\n"
        "    AND effect_family = ownership.effect_family\n"
        "    AND owner_generation = ownership.generation;"
    )
    assert request_read in sql
    assert request_read.replace(";", "\n  FOR SHARE;") not in sql


def test_approval_record_fix_qualifies_column_and_preserves_definer_owner():
    sql = Path(
        "supabase/migrations/"
        "20260725004020_fix_publisher_delete_approval_record_ambiguity.sql"
    ).read_text()

    assert "requested_approval_ref" in sql
    assert (
        "approval.approval_ref = btrim(requested_approval_ref)"
        in sql
    )
    assert "WHERE approval_ref = btrim(approval_ref)" not in sql
    assert "SET ROLE volpred_ops_definer" in sql
    assert "REVOKE CREATE ON SCHEMA public FROM volpred_ops_definer" in sql


def test_restore_migration_is_atomic_exact_and_service_role_only():
    sql = Path(
        "supabase/migrations/"
        "20260725015352_operations_core_publisher_delete_restore.sql"
    ).read_text()

    required = (
        "volpred_restore_publisher_article_delete_batch",
        "volpred_read_article_delete_dependency_contract",
        "volpred_ops.read_publisher_article_delete_candidate",
        "FOR UPDATE",
        "jsonb_populate_record",
        "jsonb_populate_recordset",
        "INSERT INTO public.articles",
        "INSERT INTO public.article_impressions",
        "INSERT INTO public.article_reactions",
        "INSERT INTO public.article_relations",
        "INSERT INTO public.article_tags",
        "INSERT INTO public.comments",
        "INSERT INTO public.question_articles",
        "REVOKE ALL ON FUNCTION",
        "FROM PUBLIC, anon, authenticated, service_role",
        "TO service_role",
        "SET search_path = ''",
    )
    assert all(fragment in sql for fragment in required)
    assert "GRANT SELECT, INSERT, UPDATE ON" in sql
    assert "GRANT INSERT ON" not in sql.split("TO service_role")[-1]


def test_restore_null_binding_fix_is_forward_only_and_hides_v1():
    sql = Path(
        "supabase/migrations/"
        "20260725020832_fix_publisher_delete_restore_null_binding.sql"
    ).read_text()

    assert "IS DISTINCT FROM target_article_id" in sql
    assert (
        "volpred_restore_publisher_article_delete_batch_v1(jsonb)"
        in sql
    )
    assert "FROM PUBLIC, anon, authenticated, service_role" in sql
    assert "SET search_path = ''" in sql
    assert "TO service_role" in sql


def test_payload_hash_is_preserved_across_json_text_transport():
    prepared = _prepared()
    payload_text = prepared.payload.decode("utf-8")

    assert json.dumps(
        json.loads(payload_text),
        sort_keys=True,
        separators=(",", ":"),
    ) == payload_text
    assert (
        hashlib.sha256(payload_text.encode()).hexdigest()
        == prepared.request.payload_sha256
    )
