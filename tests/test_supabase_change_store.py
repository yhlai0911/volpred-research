from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import json
from urllib import error

import pytest

from volpred.ops.delivery import (
    ChangeSetConflict,
    ChangeSetProposal,
    ChangeSetView,
    CheckEvidence,
    ContentHash,
    _proposal_sha256,
)
from volpred.ops.delivery.supabase_change_store import (
    SupabaseChangeSetStore,
)
from volpred.ops.delivery._change_settlement import (
    CommitSettlement,
    commit_settlement_sha256,
)
from volpred.ops.delivery._git_actuator import CommitActuationReceipt


pytestmark = pytest.mark.usefixtures(
    "mocked_operations_core_rpc_transport"
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
    proposal = ChangeSetProposal(
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
    )
    return ChangeSetView(
        schema_version="changeset.v1",
        id="change-1",
        idempotency_key=proposal.idempotency_key,
        work_item_id=proposal.work_item_id,
        work_item_version=proposal.work_item_version,
        base_commit=proposal.base_commit,
        workspace_ref=proposal.workspace_ref,
        exact_paths=proposal.exact_paths,
        content_hashes=proposal.content_hashes,
        required_checks=proposal.required_checks,
        author_ref=proposal.author_ref,
        author_evidence_ref=proposal.author_evidence_ref,
        proposal_sha256=_proposal_sha256(proposal),
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


def _landed_row(**overrides: object) -> dict[str, object]:
    view = _view()
    authority_sha = "d" * 64
    commit_sha = "e" * 40
    actor = "commit-worker:operations-core"
    repository = "/repo"
    change_set_id = view.id
    actuation = {
        "schema_version": "commit-actuation.v1",
        "proposal_sha256": view.proposal_sha256,
        "work_item_id": view.work_item_id,
        "work_item_version": view.work_item_version,
        "commit_owner_generation": 2,
        "commit_owner_ref": "commit-owner:git.commit:generation-2",
        "authority_request_sha256": authority_sha,
        "work_lease_ref": "work-lease:work-1:v3",
        "primary_authority_ref": "primary-authority:test:epoch-1",
        "commit_sha": commit_sha,
        "parent_sha": view.base_commit,
        "exact_paths": list(view.exact_paths),
        "actor": actor,
        "status": "committed",
        "observed_at": "2026-07-24T08:00:01+00:00",
    }
    actuation_receipt = CommitActuationReceipt(
        schema_version=str(actuation["schema_version"]),
        proposal_sha256=str(actuation["proposal_sha256"]),
        work_item_id=str(actuation["work_item_id"]),
        work_item_version=int(actuation["work_item_version"]),
        commit_owner_generation=int(
            actuation["commit_owner_generation"]
        ),
        commit_owner_ref=str(actuation["commit_owner_ref"]),
        authority_request_sha256=str(
            actuation["authority_request_sha256"]
        ),
        work_lease_ref=str(actuation["work_lease_ref"]),
        primary_authority_ref=str(actuation["primary_authority_ref"]),
        commit_sha=str(actuation["commit_sha"]),
        parent_sha=str(actuation["parent_sha"]),
        exact_paths=tuple(actuation["exact_paths"]),
        actor=str(actuation["actor"]),
        status=str(actuation["status"]),
        observed_at=str(actuation["observed_at"]),
    )
    settlement_ref = f"change-delivery:{change_set_id}:{commit_sha}"
    row = _row(
        status="landed",
        land_command_sha256="f" * 64,
        actuation_receipt=actuation,
        delivery_schema_version="change-delivery-receipt.v1",
        delivery_authority_request_sha256=authority_sha,
        delivery_work_lease_ref=actuation["work_lease_ref"],
        delivery_primary_authority_ref=actuation["primary_authority_ref"],
        delivery_repository=repository,
        delivery_commit_sha=commit_sha,
        delivery_parent_sha=view.base_commit,
        delivery_exact_paths=list(view.exact_paths),
        delivery_commit_worker_ref=actor,
        delivery_status="landed",
        delivery_actuation_observed_at=actuation["observed_at"],
        delivery_settled_at="2026-07-24T08:00:02+00:00",
        delivery_settlement_ref=settlement_ref,
        delivery_settlement_sha256=commit_settlement_sha256(
            CommitSettlement(
                change_set_id=change_set_id,
                repository=repository,
                work_lease_token="unused",
                primary_fencing_token="unused",
                actuation=actuation_receipt,
            )
        ),
        delivery_commit_owner_generation=2,
        delivery_commit_owner_ref="commit-owner:git.commit:generation-2",
    )
    row.update(overrides)
    return row


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
        "p_proposal_sha256": _view().proposal_sha256,
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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "changeset.v2"),
        ("work_item_version", True),
        ("proposal_sha256", "not-a-sha"),
        ("status", "mystery"),
        ("exact_paths", ["../escape"]),
    ],
)
def test_rpc_readback_rejects_malformed_change_set_records(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    malformed = deepcopy(_row())
    malformed[field] = value
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: _Response(malformed),
    )

    with pytest.raises(RuntimeError, match="malformed ChangeSet record"):
        _store().load("change-1")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("delivery_settlement_ref", "bogus-ref"),
        ("delivery_settlement_sha256", "a" * 64),
        ("delivery_commit_owner_ref", "arbitrary-owner-ref"),
    ],
)
def test_rpc_readback_rejects_derived_delivery_identity_drift(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    malformed = _landed_row(**{field: value})
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: _Response(malformed),
    )

    with pytest.raises(RuntimeError, match="malformed ChangeSet record"):
        _store().load("change-1")
