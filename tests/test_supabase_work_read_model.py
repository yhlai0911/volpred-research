from __future__ import annotations

import json

import pytest

from volpred.ops.work import (
    VerifiedCheckpointView,
    WorkEventView,
    WorkItemView,
    WorkQuery,
    WorkReceiptView,
    WorkSnapshot,
)
from volpred.ops.work.supabase import SupabaseWorkReadModel, WorkReadModelError


class _Response:
    def __init__(self, payload: object) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._raw


def _snapshot_payload() -> dict[str, object]:
    return {
        "schema_version": "work-snapshot.v1",
        "items": [
            {
                "id": "work-1",
                "idempotency_key": "work:1",
                "source": "user",
                "kind": "platform_ops",
                "title": "Land exact ChangeSet",
                "priority": 1,
                "required_capabilities": ["code", "git.commit"],
                "required_attestations": ["trusted_writer"],
                "risk": "safe",
                "approval": "auto",
                "payload_ref": "changeset:1",
                "parent_id": None,
                "deadline": None,
                "requester_ref": "user",
                "status": "succeeded",
                "version": 4,
                "created_at": "2026-07-24T08:00:00+00:00",
                "updated_at": "2026-07-24T08:03:00+00:00",
                "claimed_by": None,
                "claim_expires_at": None,
                "latest_verified_checkpoint_id": "checkpoint-1",
                "blocked_reason": None,
                "last_release_reason": None,
                "result_ref": "change-delivery:changeset-1:abc",
                "result_summary": (
                    "ChangeSet landed with verified commit read-back"
                ),
                "finished_at": "2026-07-24T08:03:00+00:00",
            }
        ],
        "events": [
            {
                "work_id": "work-1",
                "kind": "completed",
                "version": 4,
                "created_at": "2026-07-24T08:03:00+00:00",
                "actor_ref": "commit-worker:test",
                "evidence_ref": "change-delivery:changeset-1:abc",
            }
        ],
        "checkpoints": [
            {
                "id": "checkpoint-1",
                "work_id": "work-1",
                "artifact_ref": "workspace:test",
                "artifact_sha256": "a" * 64,
                "verification_ref": "pytest:1",
                "created_at": "2026-07-24T08:02:00+00:00",
            }
        ],
        "receipts": [
            {
                "id": "receipt-1",
                "work_id": "work-1",
                "outcome": "succeeded",
                "result_ref": "change-delivery:changeset-1:abc",
                "summary": "ChangeSet landed with verified commit read-back",
                "created_at": "2026-07-24T08:03:00+00:00",
            }
        ],
    }


def test_inspect_reads_exact_work_snapshot_through_service_role_rpc(
    monkeypatch: pytest.MonkeyPatch,
    mocked_operations_core_rpc_transport: None,
) -> None:
    observed: dict[str, object] = {}

    def fake_urlopen(call, *, timeout: float):
        observed["url"] = call.full_url
        observed["headers"] = dict(call.header_items())
        observed["body"] = json.loads(call.data)
        observed["timeout"] = timeout
        return _Response(_snapshot_payload())

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        fake_urlopen,
    )
    model = SupabaseWorkReadModel(
        supabase_url="https://project.supabase.co/",
        service_role_key="secret-service-role",
        timeout_seconds=9,
    )

    snapshot = model.inspect(WorkQuery(work_id="work-1"))

    assert snapshot == WorkSnapshot(
        items=(
            WorkItemView(
                id="work-1",
                idempotency_key="work:1",
                source="user",
                kind="platform_ops",
                title="Land exact ChangeSet",
                priority=1,
                required_capabilities=frozenset({"code", "git.commit"}),
                required_attestations=frozenset({"trusted_writer"}),
                risk="safe",
                approval="auto",
                payload_ref="changeset:1",
                parent_id=None,
                deadline=None,
                requester_ref="user",
                status="succeeded",
                version=4,
                created_at="2026-07-24T08:00:00+00:00",
                updated_at="2026-07-24T08:03:00+00:00",
                claimed_by=None,
                claim_expires_at=None,
                latest_verified_checkpoint_id="checkpoint-1",
                blocked_reason=None,
                last_release_reason=None,
                result_ref="change-delivery:changeset-1:abc",
                result_summary=(
                    "ChangeSet landed with verified commit read-back"
                ),
                finished_at="2026-07-24T08:03:00+00:00",
            ),
        ),
        events=(
            WorkEventView(
                work_id="work-1",
                kind="completed",
                version=4,
                created_at="2026-07-24T08:03:00+00:00",
                actor_ref="commit-worker:test",
                evidence_ref="change-delivery:changeset-1:abc",
            ),
        ),
        checkpoints=(
            VerifiedCheckpointView(
                id="checkpoint-1",
                work_id="work-1",
                artifact_ref="workspace:test",
                artifact_sha256="a" * 64,
                verification_ref="pytest:1",
                created_at="2026-07-24T08:02:00+00:00",
            ),
        ),
        receipts=(
            WorkReceiptView(
                id="receipt-1",
                work_id="work-1",
                outcome="succeeded",
                result_ref="change-delivery:changeset-1:abc",
                summary="ChangeSet landed with verified commit read-back",
                created_at="2026-07-24T08:03:00+00:00",
            ),
        ),
    )
    assert observed == {
        "url": (
            "https://project.supabase.co/rest/v1/rpc/"
            "volpred_read_work_snapshot"
        ),
        "headers": {
            "Apikey": "secret-service-role",
            "Authorization": "Bearer secret-service-role",
            "Content-type": "application/json",
            "Accept": "application/json",
        },
        "body": {"p_work_id": "work-1"},
        "timeout": 9,
    }


def test_inspect_rejects_unsupported_work_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
    mocked_operations_core_rpc_transport: None,
) -> None:
    payload = _snapshot_payload()
    payload["items"][0]["status"] = "apparently_done"
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: _Response(payload),
    )

    with pytest.raises(
        WorkReadModelError,
        match="unsupported WorkItem lifecycle",
    ):
        SupabaseWorkReadModel(
            supabase_url="https://project.supabase.co",
            service_role_key="secret-service-role",
        ).inspect(WorkQuery(work_id="work-1"))


def test_inspect_rejects_unverified_checkpoint_identity(
    monkeypatch: pytest.MonkeyPatch,
    mocked_operations_core_rpc_transport: None,
) -> None:
    payload = _snapshot_payload()
    payload["checkpoints"][0]["artifact_sha256"] = "not-a-sha256"
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: _Response(payload),
    )

    with pytest.raises(
        WorkReadModelError,
        match="checkpoint artifact SHA-256",
    ):
        SupabaseWorkReadModel(
            supabase_url="https://project.supabase.co",
            service_role_key="secret-service-role",
        ).inspect(WorkQuery(work_id="work-1"))
