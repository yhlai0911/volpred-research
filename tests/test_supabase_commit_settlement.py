from __future__ import annotations

import json
from io import BytesIO
from typing import Self
from urllib import error

import pytest

from volpred.ops.authority import PrimaryLease
from volpred.ops.delivery._change_settlement import (
    CommitSettlement,
    CommitSettlementBlocked,
    commit_settlement_sha256,
)
from volpred.ops.delivery._git_actuator import CommitActuationReceipt
from volpred.ops.delivery.supabase_commit_settlement import (
    SupabaseCommitSettlement,
)


pytestmark = pytest.mark.usefixtures(
    "mocked_operations_core_rpc_transport"
)


class _Response:
    def __init__(self, payload: object) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._raw


def _lease() -> PrimaryLease:
    return PrimaryLease(
        schema_version="primary-lease.v1",
        authority_key="operations-core-commits",
        holder_ref="host:commit-primary",
        epoch=4,
        fencing_token="primary-secret",
        lease_seconds=300,
        acquired_at="2026-07-24T08:00:00+00:00",
        expires_at="2026-07-24T08:05:00+00:00",
    )


def _command() -> CommitSettlement:
    return CommitSettlement(
        change_set_id="change-1",
        repository="/repo",
        work_lease_token="work-secret",
        primary_fencing_token="primary-secret",
        actuation=CommitActuationReceipt(
            schema_version="commit-actuation.v1",
            proposal_sha256="a" * 64,
            work_item_id="work-1",
            work_item_version=3,
            commit_owner_generation=2,
            commit_owner_ref="commit-owner:git.commit:generation-2",
            authority_request_sha256="b" * 64,
            work_lease_ref="work-lease:work-1:v3",
            primary_authority_ref=("primary-authority:operations-core-commits:epoch-4"),
            commit_sha="c" * 40,
            parent_sha="d" * 40,
            exact_paths=("docs/result.md",),
            actor="commit-worker:test",
            status="committed",
            observed_at="2026-07-24T08:02:00+00:00",
        ),
    )


def _receipt(**overrides: object) -> dict[str, object]:
    command = _command()
    actuation = command.actuation
    return {
        "schema_version": "change-delivery-receipt.v1",
        "change_set_id": command.change_set_id,
        "proposal_sha256": actuation.proposal_sha256,
        "work_item_id": actuation.work_item_id,
        "work_item_version": actuation.work_item_version,
        "commit_owner_generation": actuation.commit_owner_generation,
        "commit_owner_ref": actuation.commit_owner_ref,
        "authority_request_sha256": (actuation.authority_request_sha256),
        "work_lease_ref": actuation.work_lease_ref,
        "primary_authority_ref": actuation.primary_authority_ref,
        "repository": command.repository,
        "commit_sha": actuation.commit_sha,
        "parent_sha": actuation.parent_sha,
        "exact_paths": list(actuation.exact_paths),
        "commit_worker_ref": actuation.actor,
        "status": "landed",
        "actuation_observed_at": actuation.observed_at,
        "settled_at": "2026-07-24T08:02:01+00:00",
        "settlement_ref": (
            f"change-delivery:{command.change_set_id}:{actuation.commit_sha}"
        ),
        "settlement_sha256": commit_settlement_sha256(command),
        **overrides,
    }


def _settlement() -> SupabaseCommitSettlement:
    return SupabaseCommitSettlement(
        supabase_url="https://project.supabase.co/",
        service_role_key="secret-service-role",
        primary_lease=_lease(),
        timeout_seconds=9,
    )


def test_settle_uses_service_role_rpc_and_decodes_redacted_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    command = _command()

    def fake_urlopen(call, *, timeout: float):
        observed["url"] = call.full_url
        observed["headers"] = dict(call.header_items())
        observed["body"] = json.loads(call.data)
        observed["timeout"] = timeout
        return _Response(_receipt())

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        fake_urlopen,
    )

    receipt = _settlement().settle(command)

    assert receipt.settlement_sha256 == commit_settlement_sha256(command)
    assert observed == {
        "url": ("https://project.supabase.co/rest/v1/rpc/volpred_settle_commit_write"),
        "headers": {
            "Apikey": "secret-service-role",
            "Authorization": "Bearer secret-service-role",
            "Content-type": "application/json",
            "Accept": "application/json",
        },
        "body": {
            "p_authority_key": "operations-core-commits",
            "p_authority_holder_ref": "host:commit-primary",
            "p_authority_epoch": 4,
            "p_primary_fencing_token": "primary-secret",
            "p_authority_request_sha256": "b" * 64,
            "p_commit_owner_generation": 2,
            "p_commit_owner_ref": ("commit-owner:git.commit:generation-2"),
            "p_settlement_sha256": commit_settlement_sha256(command),
            "p_change_set_id": "change-1",
            "p_work_lease_token": "work-secret",
            "p_work_lease_ref": "work-lease:work-1:v3",
            "p_primary_authority_ref": (
                "primary-authority:operations-core-commits:epoch-4"
            ),
            "p_repository": "/repo",
            "p_commit_sha": "c" * 40,
            "p_parent_sha": "d" * 40,
            "p_exact_paths": ["docs/result.md"],
            "p_commit_worker_ref": "commit-worker:test",
            "p_actuation_observed_at": ("2026-07-24T08:02:00+00:00"),
            "p_actuation_status": "committed",
        },
        "timeout": 9,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("commit_sha", "e" * 40),
        ("settlement_sha256", "f" * 64),
        ("commit_owner_generation", True),
        ("exact_paths", "docs/result.md"),
        ("actuation_observed_at", "not-a-timestamp"),
    ],
)
def test_untrusted_receipt_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: _Response(_receipt(**{field: value})),
    )

    with pytest.raises(CommitSettlementBlocked):
        _settlement().settle(_command())


def test_fencing_failure_is_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = error.HTTPError(
        url="https://project.supabase.co/rest/v1/rpc/volpred_settle_commit_write",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=BytesIO(
            json.dumps(
                {"message": "commit ownership lost: expected generation 2"}
            ).encode("utf-8")
        ),
    )
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(failure),
    )

    with pytest.raises(CommitSettlementBlocked, match="ownership lost"):
        _settlement().settle(_command())


def test_environment_adapter_never_uses_publishable_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_commit_settlement.runtime_environment",
        lambda: {
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_KEY": "publishable-or-anon-key",
        },
    )

    with pytest.raises(ValueError, match="service-role key"):
        SupabaseCommitSettlement.from_environment(primary_lease=_lease())


def test_command_type_is_checked_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_urlopen(*args, **kwargs):
        nonlocal called
        called = True
        return _Response(_receipt())

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        fake_urlopen,
    )

    with pytest.raises(TypeError, match="CommitSettlement"):
        _settlement().settle(object())  # type: ignore[arg-type]
    assert called is False
