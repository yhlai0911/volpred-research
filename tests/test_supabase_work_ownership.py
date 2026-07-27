from __future__ import annotations

import json
from typing import Self

import pytest

from volpred.ops.work.supabase_ownership import SupabaseWorkOwnerStore

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
        "schema_version": "work-owner-attestation.v1",
        "capability": "work.coordinate",
        "owner": "legacy",
        "generation": 1,
        "cutover_manifest_sha256": None,
        "changed_at": "2026-07-26T03:47:20+00:00",
        "changed_by": "migration:operations_core_work_ownership",
        "change_reason": "initial Work Coordinator owner remains legacy",
        "attested_at": "2026-07-27T12:30:00+00:00",
        **overrides,
    }


def _store() -> SupabaseWorkOwnerStore:
    return SupabaseWorkOwnerStore(
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
    assert owner.capability == "work.coordinate"
    assert owner.backend_sha256 == _store()._client.backend_sha256
    assert observed == {
        "url": (
            "https://project.supabase.co/rest/v1/rpc/"
            "volpred_read_work_owner"
        ),
        "body": {},
        "timeout": 9,
    }


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"schema_version": "work-owner-attestation.v0"}, "schema"),
        ({"capability": "other"}, "capability"),
        ({"owner": "other"}, "owner"),
        ({"generation": 0}, "generation"),
        ({"cutover_manifest_sha256": "not-a-hash"}, "manifest"),
        ({"changed_at": "not-a-time"}, "changed_at"),
        ({"changed_by": ""}, "changed_by"),
        ({"change_reason": ""}, "change_reason"),
        ({"attested_at": "not-a-time"}, "attested_at"),
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


def test_operations_core_owner_requires_cutover_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            _payload(owner="operations_core", generation=2)
        ),
    )

    with pytest.raises(ValueError, match="manifest"):
        _store().read_owner()
