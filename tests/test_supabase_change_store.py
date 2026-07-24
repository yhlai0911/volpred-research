from __future__ import annotations

from io import BytesIO
import json
from urllib import error

import pytest

from volpred.ops.delivery import (
    ChangeSetConflict,
    ChangeSetView,
    CheckEvidence,
    ContentHash,
)
from volpred.ops.delivery.supabase_change_store import (
    SupabaseChangeSetStore,
)


class _Response:
    def __init__(self, payload: object) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._raw


def _view() -> ChangeSetView:
    return ChangeSetView(
        schema_version="changeset.v1",
        id="change-1",
        idempotency_key="change:test:1",
        work_item_id="work-1",
        work_item_version=3,
        base_commit="a" * 40,
        workspace_ref="/repo/worktree",
        exact_paths=("docs/result.md",),
        content_hashes=(
            ContentHash(path="docs/result.md", sha256="b" * 64),
        ),
        required_checks=(
            CheckEvidence(
                name="pytest",
                status="passed",
                evidence_ref="check:pytest:1",
            ),
        ),
        author_ref="agent:test",
        author_evidence_ref="session:test",
        proposal_sha256="c" * 64,
        status="proposed",
        created_at="2026-07-24T08:00:00+00:00",
    )


def _row(**overrides: object) -> dict[str, object]:
    view = _view()
    return {
        "schema_version": view.schema_version,
        "id": view.id,
        "idempotency_key": view.idempotency_key,
        "work_item_id": view.work_item_id,
        "work_item_version": view.work_item_version,
        "base_commit": view.base_commit,
        "workspace_ref": view.workspace_ref,
        "exact_paths": list(view.exact_paths),
        "content_hashes": [
            {"path": item.path, "sha256": item.sha256}
            for item in view.content_hashes
        ],
        "required_checks": [
            {
                "name": item.name,
                "status": item.status,
                "evidence_ref": item.evidence_ref,
            }
            for item in view.required_checks
        ],
        "author_ref": view.author_ref,
        "author_evidence_ref": view.author_evidence_ref,
        "proposal_sha256": view.proposal_sha256,
        "status": view.status,
        "land_command_sha256": None,
        "actuation_receipt": None,
        "created_at": view.created_at,
        "updated_at": view.created_at,
        "delivery_schema_version": None,
        "delivery_authority_request_sha256": None,
        "delivery_work_lease_ref": None,
        "delivery_primary_authority_ref": None,
        "delivery_repository": None,
        "delivery_commit_sha": None,
        "delivery_parent_sha": None,
        "delivery_exact_paths": None,
        "delivery_commit_worker_ref": None,
        "delivery_status": None,
        "delivery_actuation_observed_at": None,
        "delivery_settled_at": None,
        "delivery_settlement_ref": None,
        "delivery_settlement_sha256": None,
        "delivery_commit_owner_generation": None,
        "delivery_commit_owner_ref": None,
        **overrides,
    }


def _store() -> SupabaseChangeSetStore:
    return SupabaseChangeSetStore(
        supabase_url="https://project.supabase.co/",
        service_role_key="secret-service-role",
        timeout_seconds=9,
    )


def test_create_uses_service_role_rpc_and_decodes_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_urlopen(call, *, timeout: float):
        observed["url"] = call.full_url
        observed["headers"] = dict(call.header_items())
        observed["body"] = json.loads(call.data)
        observed["timeout"] = timeout
        return _Response(_row())

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        fake_urlopen,
    )

    record = _store().create(_view())

    assert record.view == _view()
    assert observed["url"] == (
        "https://project.supabase.co/rest/v1/rpc/"
        "volpred_create_change_set"
    )
    assert observed["body"] == {
        "p_id": "change-1",
        "p_idempotency_key": "change:test:1",
        "p_work_item_id": "work-1",
        "p_work_item_version": 3,
        "p_base_commit": "a" * 40,
        "p_workspace_ref": "/repo/worktree",
        "p_exact_paths": ["docs/result.md"],
        "p_content_hashes": [
            {"path": "docs/result.md", "sha256": "b" * 64}
        ],
        "p_required_checks": [
            {
                "name": "pytest",
                "status": "passed",
                "evidence_ref": "check:pytest:1",
            }
        ],
        "p_author_ref": "agent:test",
        "p_author_evidence_ref": "session:test",
        "p_proposal_sha256": "c" * 64,
        "p_schema_version": "changeset.v1",
        "p_created_at": "2026-07-24T08:00:00+00:00",
    }
    assert observed["timeout"] == 9
    assert observed["headers"] == {
        "Apikey": "secret-service-role",
        "Authorization": "Bearer secret-service-role",
        "Content-type": "application/json",
        "Accept": "application/json",
    }


def test_read_and_idempotency_lookup_preserve_missing_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: _Response(None),
    )
    store = _store()

    with pytest.raises(ValueError, match="unknown ChangeSet: missing"):
        store.load("missing")
    assert store.load_by_idempotency_key("missing-key") is None


def test_structured_conflict_is_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = error.HTTPError(
        url="https://project.supabase.co/rest/v1/rpc/"
        "volpred_create_change_set",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=BytesIO(
            json.dumps(
                {
                    "message": (
                        "ChangeSet idempotency key conflicts with its "
                        "original payload"
                    )
                }
            ).encode("utf-8")
        ),
    )
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(failure),
    )

    with pytest.raises(ChangeSetConflict, match="idempotency key"):
        _store().create(_view())


def test_environment_adapter_never_uses_publishable_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_change_store.runtime_environment",
        lambda: {
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_KEY": "publishable-or-anon-key",
        },
    )

    with pytest.raises(ValueError, match="service-role key"):
        SupabaseChangeSetStore.from_environment()
