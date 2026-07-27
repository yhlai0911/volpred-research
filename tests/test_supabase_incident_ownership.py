from __future__ import annotations

import json
from typing import Self

import pytest

from volpred.ops.incident_ownership import SupabaseIncidentOwnerStore

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
        "schema_version": "incident-owner-attestation.v1",
        "capability": "incident.lifecycle",
        "owner": "legacy",
        "generation": 1,
        "contract_ref": "contract://issue-13/durable-incident-owner",
        "changed_at": "2026-07-27T13:15:00+00:00",
        "changed_by": "migration:incident_owner_attestation",
        "change_reason": "initial incident lifecycle owner remains legacy",
        "receipt_sequence": 1,
        "receipt_capability": "incident.lifecycle",
        "receipt_owner": "legacy",
        "receipt_generation": 1,
        "receipt_contract_ref":
            "contract://issue-13/durable-incident-owner",
        "receipt_changed_at": "2026-07-27T13:15:00+00:00",
        "receipt_actor_ref": "migration:incident_owner_attestation",
        "receipt_reason":
            "initial incident lifecycle owner remains legacy",
        "attested_at": "2026-07-27T13:15:05+00:00",
        **overrides,
    }


def _store() -> SupabaseIncidentOwnerStore:
    return SupabaseIncidentOwnerStore(
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
    assert owner.capability == "incident.lifecycle"
    assert owner.backend_sha256 == _store()._client.backend_sha256
    assert observed == {
        "url": (
            "https://project.supabase.co/rest/v1/rpc/"
            "volpred_read_incident_owner"
        ),
        "body": {},
        "timeout": 9,
    }


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"schema_version": "incident-owner-attestation.v0"}, "schema"),
        ({"capability": "other"}, "capability"),
        ({"owner": "other"}, "owner"),
        ({"owner": "operations_core"}, "owner"),
        ({"owner": " legacy "}, "owner"),
        ({"generation": 0}, "generation"),
        (
            {
                "generation": 2,
                "receipt_generation": 2,
            },
            "generation",
        ),
        ({"contract_ref": "other"}, "contract"),
        ({"changed_at": "not-a-time"}, "changed_at"),
        ({"changed_by": ""}, "changed_by"),
        ({"change_reason": ""}, "change_reason"),
        ({"attested_at": "not-a-time"}, "attested_at"),
        ({"receipt_sequence": 0}, "receipt sequence"),
        ({"receipt_capability": "other"}, "receipt capability"),
        ({"receipt_owner": "operations_core"}, "receipt owner"),
        ({"receipt_generation": 2}, "receipt generation"),
        ({"receipt_contract_ref": "other"}, "receipt contract"),
        (
            {"receipt_changed_at": "2026-07-27T13:14:59+00:00"},
            "receipt changed_at",
        ),
        ({"receipt_actor_ref": "other"}, "receipt actor"),
        ({"receipt_reason": "other"}, "receipt reason"),
        (
            {
                "changed_at": "2026-07-27T13:15:06+00:00",
                "receipt_changed_at": "2026-07-27T13:15:06+00:00",
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
