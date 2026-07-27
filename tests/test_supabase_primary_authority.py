from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from urllib import error

import pytest

from volpred.ops.authority import (
    AuthorityRequest,
    PrimaryAuthority,
    PrimaryLease,
    WriteIntent,
)
from volpred.ops.authority.supabase import SupabaseAuthorityStore

pytestmark = pytest.mark.usefixtures("mocked_operations_core_rpc_transport")


class _Response:
    def __init__(self, payload: object) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._raw


def _lease_payload(**overrides: object) -> dict[str, object]:
    return {
        "authority_key": "operations-core-commits",
        "epoch": 4,
        "holder_ref": "host:primary",
        "acquired_at": "2026-07-24T10:00:00+00:00",
        "lease_expires_at": "2026-07-24T10:05:00+00:00",
        "updated_at": "2026-07-24T10:00:00+00:00",
        **overrides,
    }


def _lease(**overrides: object) -> PrimaryLease:
    return PrimaryLease(
        schema_version="primary-lease.v1",
        authority_key="operations-core-commits",
        holder_ref="host:primary",
        epoch=4,
        fencing_token="primary-secret",
        lease_seconds=300,
        acquired_at="2026-07-24T10:00:00+00:00",
        expires_at="2026-07-24T10:05:00+00:00",
        **overrides,
    )


def _store(
    *,
    demotion_intent_dir: Path | None = None,
) -> SupabaseAuthorityStore:
    return SupabaseAuthorityStore(
        supabase_url="https://project.supabase.co/",
        service_role_key="secret-service-role",
        timeout_seconds=9,
        demotion_intent_dir=demotion_intent_dir,
    )


def _owner_payload(**overrides: object) -> dict[str, object]:
    return {
        "schema_version": "primary-authority-owner.v1",
        "capability": "operations-core-primary",
        "authority_key": "operations-core-primary",
        "owner": "operations_core",
        "generation": 1,
        "contract_ref": "primary-authority-contract.v1",
        "attested_at": "2026-07-27T12:00:00+00:00",
        **overrides,
    }


def test_read_owner_uses_typed_read_only_attestation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_urlopen(call, *, timeout: float):
        observed["url"] = call.full_url
        observed["body"] = json.loads(call.data)
        return _Response(_owner_payload())

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        fake_urlopen,
    )

    owner = _store().read_owner()

    assert owner.owner == "operations_core"
    assert owner.generation == 1
    assert owner.authority_key == "operations-core-primary"
    assert owner.backend_sha256 == _store()._client.backend_sha256
    assert observed == {
        "url": (
            "https://project.supabase.co/rest/v1/rpc/"
            "volpred_read_primary_authority_owner"
        ),
        "body": {},
    }


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"schema_version": "primary-authority-owner.v0"}, "schema"),
        ({"capability": "other"}, "capability"),
        ({"authority_key": "other"}, "authority key"),
        ({"owner": "legacy"}, "owner"),
        ({"generation": 2}, "generation"),
        ({"contract_ref": "other"}, "contract"),
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
        lambda *_args, **_kwargs: _Response(_owner_payload(**overrides)),
    )

    with pytest.raises(ValueError, match=message):
        _store().read_owner()


def test_acquire_uses_service_role_rpc_without_returning_raw_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_urlopen(call, *, timeout: float):
        observed["url"] = call.full_url
        observed["headers"] = dict(call.header_items())
        observed["body"] = json.loads(call.data)
        observed["timeout"] = timeout
        return _Response(_lease_payload())

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        fake_urlopen,
    )
    authority = PrimaryAuthority(
        _store(),
        token_factory=lambda: "primary-secret",
    )

    lease = authority.acquire(
        AuthorityRequest(
            authority_key="operations-core-commits",
            holder_ref="host:primary",
            lease_seconds=300,
        )
    )

    assert lease == _lease()
    assert observed == {
        "url": (
            "https://project.supabase.co/rest/v1/rpc/volpred_acquire_primary_authority"
        ),
        "headers": {
            "Apikey": "secret-service-role",
            "Authorization": "Bearer secret-service-role",
            "Content-type": "application/json",
            "Accept": "application/json",
        },
        "body": {
            "p_authority_key": "operations-core-commits",
            "p_holder_ref": "host:primary",
            "p_lease_seconds": 300,
            "p_fencing_token": "primary-secret",
        },
        "timeout": 9,
    }


def test_renew_preserves_lease_identity_and_validates_read_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_urlopen(call, *, timeout: float):
        observed["url"] = call.full_url
        observed["body"] = json.loads(call.data)
        return _Response(
            _lease_payload(
                lease_expires_at="2026-07-24T10:06:00+00:00",
                updated_at="2026-07-24T10:01:00+00:00",
            )
        )

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        fake_urlopen,
    )

    renewed = _store().renew(_lease())

    assert renewed.expires_at == "2026-07-24T10:06:00+00:00"
    assert observed == {
        "url": (
            "https://project.supabase.co/rest/v1/rpc/volpred_renew_primary_authority"
        ),
        "body": {
            "p_authority_key": "operations-core-commits",
            "p_holder_ref": "host:primary",
            "p_epoch": 4,
            "p_lease_seconds": 300,
            "p_fencing_token": "primary-secret",
        },
    }

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: _Response(
            _lease_payload(holder_ref="host:other")
        ),
    )
    with pytest.raises(ValueError, match="read-back drifted"):
        _store().renew(_lease())


def test_authorize_and_release_validate_token_redacted_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_sha256 = "a" * 64
    responses = iter(
        (
            {
                "request_sha256": request_sha256,
                "authority_key": "operations-core-commits",
                "epoch": 4,
                "holder_ref": "host:primary",
                "resource_ref": "git.commit:work-1",
                "primary_authority_ref": (
                    "primary-authority:operations-core-commits:epoch-4"
                ),
                "granted_at": "2026-07-24T10:01:00+00:00",
            },
            {
                "authority_key": "operations-core-commits",
                "epoch": 4,
                "holder_ref": "host:primary",
                "primary_authority_ref": (
                    "primary-authority:operations-core-commits:epoch-4"
                ),
                "released_at": "2026-07-24T10:02:00+00:00",
            },
        )
    )
    calls: list[tuple[str, object]] = []

    def fake_urlopen(call, *, timeout: float):
        calls.append((call.full_url, json.loads(call.data)))
        return _Response(next(responses))

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        fake_urlopen,
    )
    store = _store()
    grant = store.authorize(
        WriteIntent(
            authority_key="operations-core-commits",
            holder_ref="host:primary",
            epoch=4,
            fencing_token="primary-secret",
            request_sha256=request_sha256,
            resource_ref="git.commit:work-1",
        )
    )
    receipt = store.release(_lease())

    assert grant.primary_authority_ref == (
        "primary-authority:operations-core-commits:epoch-4"
    )
    assert receipt.released_at == "2026-07-24T10:02:00+00:00"
    assert calls == [
        (
            "https://project.supabase.co/rest/v1/rpc/volpred_authorize_primary_write",
            {
                "p_authority_key": "operations-core-commits",
                "p_holder_ref": "host:primary",
                "p_epoch": 4,
                "p_fencing_token": "primary-secret",
                "p_request_sha256": request_sha256,
                "p_resource_ref": "git.commit:work-1",
            },
        ),
        (
            "https://project.supabase.co/rest/v1/rpc/volpred_release_primary_authority",
            {
                "p_authority_key": "operations-core-commits",
                "p_holder_ref": "host:primary",
                "p_epoch": 4,
                "p_fencing_token": "primary-secret",
            },
        ),
    ]


def test_untrusted_payload_and_fencing_failure_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: _Response(
            _lease_payload(lease_expires_at="2026-07-24T10:05:00")
        ),
    )
    with pytest.raises(ValueError, match="lease_expires_at"):
        _store().acquire(
            AuthorityRequest(
                authority_key="operations-core-commits",
                holder_ref="host:primary",
                lease_seconds=300,
            ),
            fencing_token="primary-secret",
        )

    failure = error.HTTPError(
        url="https://project.supabase.co/rest/v1/rpc/volpred_renew_primary_authority",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=BytesIO(
            json.dumps(
                {
                    "message": (
                        "Primary Authority lease lost: operations-core-commits"
                    )
                }
            ).encode("utf-8")
        ),
    )
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(failure),
    )
    with pytest.raises(ValueError, match="lease lost"):
        _store().renew(_lease())


def test_typed_rejection_receipt_fails_closed_with_auditable_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: _Response(
            {
                "schema_version": "primary-authority-rejection.v1",
                "status": "rejected",
                "operation": "acquire",
                "authority_key": "operations-core-commits",
                "event_ref": "primary-authority-event:17",
                "reason_code": "already_held",
                "reason": (
                    "Primary Authority is already held: operations-core-commits"
                ),
                "occurred_at": "2026-07-24T10:01:00+00:00",
            }
        ),
    )

    with pytest.raises(ValueError, match="already held"):
        _store().acquire(
            AuthorityRequest(
                authority_key="operations-core-commits",
                holder_ref="host:standby",
                lease_seconds=300,
            ),
            fencing_token="must-not-appear-in-receipt",
        )


def test_release_outage_journals_and_replays_token_redacted_demotion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    intent_dir = tmp_path / "demotion-intents"
    store = _store(demotion_intent_dir=intent_dir)
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            error.URLError("backend unavailable")
        ),
    )

    with pytest.raises(RuntimeError, match="RPC unavailable"):
        store.release(_lease())

    intent_paths = list(intent_dir.glob("*.json"))
    assert len(intent_paths) == 1
    raw_intent = intent_paths[0].read_text(encoding="utf-8")
    assert "primary-secret" not in raw_intent
    assert json.loads(raw_intent) == {
        "schema_version": "primary-authority-demotion-intent.v2",
        "backend_sha256": store._client.backend_sha256,
        "authority_key": "operations-core-commits",
        "holder_ref": "host:primary",
        "epoch": 4,
        "reason_code": "release_unconfirmed",
        "recorded_at": json.loads(raw_intent)["recorded_at"],
    }

    calls: list[str] = []

    def recovered_urlopen(call, *, timeout: float):
        calls.append(call.full_url.rsplit("/", 1)[-1])
        if calls[-1] == "volpred_reconcile_primary_authority_demotion":
            return _Response(
                {
                    "schema_version": (
                        "primary-authority-demotion-reconcile.v1"
                    ),
                    "status": "reconciled",
                    "authority_key": "operations-core-commits",
                    "holder_ref": "host:primary",
                    "epoch": 4,
                    "event_ref": "primary-authority-event:19",
                    "occurred_at": "2026-07-24T10:06:00+00:00",
                }
            )
        return _Response(_lease_payload())

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        recovered_urlopen,
    )
    store.acquire(
        AuthorityRequest(
            authority_key="operations-core-commits",
            holder_ref="host:primary",
            lease_seconds=300,
        ),
        fencing_token="primary-secret",
    )

    assert calls == [
        "volpred_reconcile_primary_authority_demotion",
        "volpred_acquire_primary_authority",
    ]
    assert list(intent_dir.glob("*.json")) == []


def test_release_readback_drift_journals_and_recovers_demotion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    intent_dir = tmp_path / "demotion-intents"
    store = _store(demotion_intent_dir=intent_dir)
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: _Response(
            {
                "authority_key": "operations-core-commits",
                "holder_ref": "host:wrong",
                "epoch": 4,
                "primary_authority_ref": "primary-authority:wrong",
                "released_at": "2026-07-24T10:06:00+00:00",
            }
        ),
    )

    with pytest.raises(ValueError, match="release read-back drifted"):
        store.release(_lease())

    intent_paths = list(intent_dir.glob("*.json"))
    assert len(intent_paths) == 1
    assert "primary-secret" not in intent_paths[0].read_text(encoding="utf-8")

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: _Response(
            {
                "schema_version": ("primary-authority-demotion-reconcile.v1"),
                "status": "reconciled",
                "authority_key": "operations-core-commits",
                "holder_ref": "host:primary",
                "epoch": 4,
                "event_ref": "primary-authority-event:20",
                "occurred_at": "2026-07-24T10:06:00+00:00",
            }
        ),
    )

    assert store.reconcile_pending_demotions() == 1
    assert list(intent_dir.glob("*.json")) == []


def test_demotion_intent_refuses_replay_to_a_different_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    intent_dir = tmp_path / "demotion-intents"
    original = _store(demotion_intent_dir=intent_dir)
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            error.URLError("backend unavailable")
        ),
    )
    with pytest.raises(RuntimeError, match="RPC unavailable"):
        original.release(_lease())

    different = SupabaseAuthorityStore(
        supabase_url="https://different-project.supabase.co/",
        service_role_key="secret-service-role",
        demotion_intent_dir=intent_dir,
    )
    with pytest.raises(ValueError, match="intent backend drifted"):
        different.reconcile_pending_demotions()


def test_concurrent_reconcilers_ignore_peer_cleaned_stale_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    intent_dir = tmp_path / "demotion-intents"
    first = _store(demotion_intent_dir=intent_dir)
    second = _store(demotion_intent_dir=intent_dir)
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            error.URLError("backend unavailable")
        ),
    )
    with pytest.raises(RuntimeError, match="RPC unavailable"):
        first.release(_lease())

    calls = 0

    def recovered_urlopen(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _Response(
            {
                "schema_version": (
                    "primary-authority-demotion-reconcile.v1"
                ),
                "status": "reconciled",
                "authority_key": "operations-core-commits",
                "holder_ref": "host:primary",
                "epoch": 4,
                "event_ref": "primary-authority-event:21",
                "occurred_at": "2026-07-24T10:06:00+00:00",
            }
        )

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        recovered_urlopen,
    )
    read_intent = second._read_demotion_intent

    def peer_cleans_before_read(path: Path) -> dict[str, object]:
        assert first.reconcile_pending_demotions() == 1
        return read_intent(path)

    monkeypatch.setattr(
        second,
        "_read_demotion_intent",
        peer_cleans_before_read,
    )

    assert second.reconcile_pending_demotions() == 0
    assert calls == 1
    assert list(intent_dir.glob("*.json")) == []


def test_read_events_returns_typed_token_redacted_lifecycle_receipts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_urlopen(call, *, timeout: float):
        observed["url"] = call.full_url
        observed["body"] = json.loads(call.data)
        return _Response(
            [
                {
                    "schema_version": "primary-authority-event.v1",
                    "event_ref": "primary-authority-event:21",
                    "authority_key": "operations-core-commits",
                    "event_type": "renewed",
                    "operation": "renew",
                    "epoch": 4,
                    "holder_ref": "host:primary",
                    "reason_code": None,
                    "reason": None,
                    "lease_expires_at": ("2026-07-24T10:06:00+00:00"),
                    "occurred_at": "2026-07-24T10:01:00+00:00",
                },
                {
                    "schema_version": "primary-authority-event.v1",
                    "event_ref": "primary-authority-event:22",
                    "authority_key": "operations-core-commits",
                    "event_type": "rejected",
                    "operation": "acquire",
                    "epoch": None,
                    "holder_ref": "host:standby",
                    "reason_code": "already_held",
                    "reason": (
                        "Primary Authority is already held: operations-core-commits"
                    ),
                    "lease_expires_at": None,
                    "occurred_at": "2026-07-24T10:01:01+00:00",
                },
            ]
        )

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        fake_urlopen,
    )

    events = _store().read_events(
        "operations-core-commits",
        limit=20,
    )

    assert [event.event_type for event in events] == [
        "renewed",
        "rejected",
    ]
    assert events[0].epoch == 4
    assert events[1].reason_code == "already_held"
    assert "fencing_token" not in repr(events)
    assert observed == {
        "url": (
            "https://project.supabase.co/rest/v1/rpc/"
            "volpred_read_primary_authority_events"
        ),
        "body": {
            "p_authority_key": "operations-core-commits",
            "p_limit": 20,
        },
    }


def test_grant_identity_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: _Response(
            {
                "request_sha256": "a" * 64,
                "authority_key": "operations-core-commits",
                "epoch": 4,
                "holder_ref": "host:primary",
                "resource_ref": "git.commit:other",
                "primary_authority_ref": "primary-authority:forged",
                "granted_at": "2026-07-24T10:01:00+00:00",
            }
        ),
    )
    intent = WriteIntent(
        authority_key="operations-core-commits",
        holder_ref="host:primary",
        epoch=4,
        fencing_token="primary-secret",
        request_sha256="a" * 64,
        resource_ref="git.commit:work-1",
    )

    with pytest.raises(ValueError, match="grant read-back drifted"):
        _store().authorize(intent)


def test_environment_adapter_never_uses_publishable_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.authority.supabase.runtime_environment",
        lambda: {
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_KEY": "publishable-or-anon-key",
        },
    )

    with pytest.raises(ValueError, match="service-role key"):
        SupabaseAuthorityStore.from_environment()
