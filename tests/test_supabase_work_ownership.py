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
        "ownership_receipt_sequence": 1,
        "ownership_receipt_capability": "work.coordinate",
        "ownership_receipt_owner": "legacy",
        "ownership_receipt_generation": 1,
        "ownership_receipt_manifest_sha256": None,
        "ownership_receipt_changed_at": "2026-07-26T03:47:20+00:00",
        "ownership_receipt_actor_ref":
            "migration:operations_core_work_ownership",
        "ownership_receipt_reason":
            "initial Work Coordinator owner remains legacy",
        "ownership_receipt_rollback_of_generation": None,
        "cutover_gate_manifest_sha256": None,
        "cutover_gate_status": None,
        "cutover_gate_consumed_generation": None,
        "cutover_gate_consumed_at": None,
        "cutover_gate_rolled_back_at": None,
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
        ({"owner": " legacy "}, "owner"),
        ({"capability": " work.coordinate "}, "capability"),
        ({"generation": 0}, "generation"),
        ({"cutover_manifest_sha256": "not-a-hash"}, "manifest"),
        ({"changed_at": "not-a-time"}, "changed_at"),
        ({"changed_by": ""}, "changed_by"),
        ({"changed_by": " actor "}, "changed_by"),
        ({"change_reason": ""}, "change_reason"),
        ({"change_reason": " reason "}, "change_reason"),
        ({"attested_at": "not-a-time"}, "attested_at"),
        ({"ownership_receipt_sequence": 0}, "receipt sequence"),
        (
            {"ownership_receipt_capability": "other"},
            "receipt capability",
        ),
        ({"ownership_receipt_owner": "operations_core"}, "receipt owner"),
        ({"ownership_receipt_generation": 2}, "receipt generation"),
        (
            {"ownership_receipt_manifest_sha256": "a" * 64},
            "receipt manifest",
        ),
        (
            {
                "ownership_receipt_changed_at":
                    "2026-07-26T03:47:21+00:00"
            },
            "receipt changed_at",
        ),
        (
            {"ownership_receipt_actor_ref": "other"},
            "receipt actor",
        ),
        (
            {"ownership_receipt_reason": "other"},
            "receipt reason",
        ),
        (
            {
                "changed_at": "2026-07-27T12:30:01+00:00",
                "ownership_receipt_changed_at":
                    "2026-07-27T12:30:01+00:00",
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


def _operations_core_payload(**overrides: object) -> dict[str, object]:
    manifest = "a" * 64
    payload = _payload(
        owner="operations_core",
        generation=2,
        cutover_manifest_sha256=manifest,
        changed_at="2026-07-27T12:29:58+00:00",
        changed_by="operator:test",
        change_reason="cutover",
        ownership_receipt_sequence=2,
        ownership_receipt_owner="operations_core",
        ownership_receipt_generation=2,
        ownership_receipt_manifest_sha256=manifest,
        ownership_receipt_changed_at="2026-07-27T12:29:58+00:00",
        ownership_receipt_actor_ref="operator:test",
        ownership_receipt_reason="cutover",
        cutover_gate_manifest_sha256=manifest,
        cutover_gate_status="consumed",
        cutover_gate_consumed_generation=2,
        cutover_gate_consumed_at="2026-07-27T12:29:59+00:00",
    )
    payload.update(overrides)
    return payload


def test_operations_core_owner_requires_consumed_cutover_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *_args, **_kwargs: _Response(_operations_core_payload()),
    )

    owner = _store().read_owner()

    assert owner.owner == "operations_core"
    assert owner.generation == 2
    assert owner.cutover_gate_status == "consumed"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"ownership_receipt_generation": 999}, "receipt generation"),
        (
            {
                "cutover_manifest_sha256": "b" * 64,
                "ownership_receipt_manifest_sha256": "b" * 64,
            },
            "cutover manifest",
        ),
        (
            {"ownership_receipt_manifest_sha256": "b" * 64},
            "receipt manifest",
        ),
        (
            {"cutover_gate_status": "ready"},
            "consumed cutover gate",
        ),
        (
            {"cutover_gate_consumed_generation": 999},
            "consumed generation",
        ),
        (
            {
                "cutover_gate_consumed_at":
                    "2026-07-27T12:29:57+00:00"
            },
            "chronology",
        ),
        (
            {
                "cutover_gate_consumed_at":
                    "2026-07-27T12:30:01+00:00"
            },
            "chronology",
        ),
    ],
)
def test_operations_core_owner_rejects_unbound_cutover_evidence(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
    message: str,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            _operations_core_payload(**overrides)
        ),
    )

    with pytest.raises(ValueError, match=message):
        _store().read_owner()
