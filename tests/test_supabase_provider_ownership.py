from __future__ import annotations

import json
from typing import Self

import pytest

from volpred.ops.provider_ownership import SupabaseProviderOwnerStore

pytestmark = pytest.mark.usefixtures("mocked_operations_core_rpc_transport")


class _Response:
    def __init__(self, payload: object) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._raw


def _payload(**overrides: object) -> dict[str, object]:
    return {
        "schema_version": "provider-owner-attestation.v1",
        "capability": "provider.execution",
        "owner": "legacy",
        "generation": 1,
        "contract_ref": "contract://issue-12/zero-paid-provider-registry",
        "changed_at": "2026-07-27T13:35:00+00:00",
        "changed_by": "migration:provider_owner_attestation",
        "change_reason": "initial provider execution owner remains legacy",
        "receipt_sequence": 1,
        "receipt_capability": "provider.execution",
        "receipt_owner": "legacy",
        "receipt_generation": 1,
        "receipt_contract_ref":
            "contract://issue-12/zero-paid-provider-registry",
        "receipt_changed_at": "2026-07-27T13:35:00+00:00",
        "receipt_actor_ref": "migration:provider_owner_attestation",
        "receipt_reason": "initial provider execution owner remains legacy",
        "attested_at": "2026-07-27T13:35:05+00:00",
        **overrides,
    }


def _store() -> SupabaseProviderOwnerStore:
    return SupabaseProviderOwnerStore(
        supabase_url="https://project.supabase.co/",
        service_role_key="secret-service-role",
        timeout_seconds=9,
    )


def test_read_owner_uses_exact_read_only_attestation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_urlopen(call, *, timeout: float):
        observed["url"] = call.full_url
        observed["body"] = json.loads(call.data)
        observed["timeout"] = timeout
        return _Response(_payload())

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        fake_urlopen,
    )

    owner = _store().read_owner()

    assert owner.owner == "legacy"
    assert owner.generation == 1
    assert owner.capability == "provider.execution"
    assert owner.backend_sha256 == _store()._client.backend_sha256
    assert observed == {
        "url": (
            "https://project.supabase.co/rest/v1/rpc/"
            "volpred_read_provider_owner"
        ),
        "body": {},
        "timeout": 9,
    }


def test_read_owner_remains_available_when_remote_writes_are_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from volpred.ops.delivery import supabase_rpc

    monkeypatch.setattr(
        supabase_rpc,
        "_remote_mutations_disabled",
        lambda: True,
    )
    monkeypatch.setattr(
        supabase_rpc.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(_payload()),
    )

    assert _store().read_owner().owner == "legacy"


def test_read_owner_accepts_receipt_bound_operations_core_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            _payload(
                owner="operations_core",
                generation=2,
                changed_by="operator:provider-cutover",
                change_reason="issue 12 acceptance passed",
                receipt_sequence=2,
                receipt_owner="operations_core",
                receipt_generation=2,
                receipt_actor_ref="operator:provider-cutover",
                receipt_reason="issue 12 acceptance passed",
            )
        ),
    )

    owner = _store().read_owner()

    assert (owner.owner, owner.generation, owner.receipt_sequence) == (
        "operations_core",
        2,
        2,
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"schema_version": "provider-owner-attestation.v0"}, "schema"),
        ({"capability": "other"}, "capability"),
        ({"owner": "other"}, "owner"),
        ({"generation": 0, "receipt_generation": 0}, "generation"),
        ({"contract_ref": "other"}, "contract"),
        ({"receipt_owner": "operations_core"}, "receipt owner"),
        ({"receipt_generation": 2}, "receipt generation"),
        ({"receipt_contract_ref": "other"}, "receipt contract"),
        (
            {"receipt_changed_at": "2026-07-27T13:34:59+00:00"},
            "receipt changed_at",
        ),
        ({"receipt_actor_ref": "other"}, "receipt actor"),
        ({"receipt_reason": "other"}, "receipt reason"),
        (
            {
                "changed_at": "2026-07-27T13:35:06+00:00",
                "receipt_changed_at": "2026-07-27T13:35:06+00:00",
            },
            "chronology",
        ),
        ({"unexpected": "field"}, "fields"),
    ],
)
def test_read_owner_rejects_drifted_attestation(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
    message: str,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *_args, **_kwargs: _Response(_payload(**overrides)),
    )

    with pytest.raises(ValueError, match=message):
        _store().read_owner()
