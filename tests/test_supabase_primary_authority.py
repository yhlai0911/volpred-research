from __future__ import annotations

from io import BytesIO
import json
from urllib import error

import pytest

from volpred.ops.authority import (
    AuthorityRequest,
    PrimaryAuthority,
    PrimaryLease,
    WriteIntent,
)
from volpred.ops.authority.supabase import SupabaseAuthorityStore


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


def _store() -> SupabaseAuthorityStore:
    return SupabaseAuthorityStore(
        supabase_url="https://project.supabase.co/",
        service_role_key="secret-service-role",
        timeout_seconds=9,
    )


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
            "https://project.supabase.co/rest/v1/rpc/"
            "volpred_acquire_primary_authority"
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
            "https://project.supabase.co/rest/v1/rpc/"
            "volpred_renew_primary_authority"
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
            "https://project.supabase.co/rest/v1/rpc/"
            "volpred_authorize_primary_write",
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
            "https://project.supabase.co/rest/v1/rpc/"
            "volpred_release_primary_authority",
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
            _lease_payload(
                lease_expires_at="2026-07-24T10:05:00"
            )
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
        url="https://project.supabase.co/rest/v1/rpc/"
        "volpred_renew_primary_authority",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=BytesIO(
            json.dumps(
                {
                    "message": (
                        "Primary Authority lease lost: "
                        "operations-core-commits"
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
