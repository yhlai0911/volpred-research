from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import json
from urllib import error

import pytest

from volpred.ops.authority import PrimaryLease
from volpred.ops.delivery import ContentHash
from volpred.ops.delivery._git_actuator import (
    CommitActuatorBlocked,
    CommitAuthorityRequest,
    _authority_request_sha256,
)
from volpred.ops.delivery.supabase_commit_authority import (
    SupabaseCommitAuthority,
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


def _request() -> CommitAuthorityRequest:
    request = CommitAuthorityRequest(
        request_sha256="0" * 64,
        proposal_sha256="a" * 64,
        work_item_id="work-1",
        work_item_version=3,
        commit_owner_generation=2,
        work_lease_token="work-secret",
        primary_fencing_token="primary-secret",
        repository="/repo",
        expected_head="b" * 40,
        exact_paths=("docs/result.md",),
        content_hashes=(
            ContentHash(path="docs/result.md", sha256="c" * 64),
        ),
        message="[codex] test commit authority",
        actor="commit-worker:test",
    )
    return replace(
        request,
        request_sha256=_authority_request_sha256(request),
    )


def _authority() -> SupabaseCommitAuthority:
    return SupabaseCommitAuthority(
        supabase_url="https://project.supabase.co/",
        service_role_key="secret-service-role",
        primary_lease=_lease(),
        timeout_seconds=9,
    )


def test_authorize_uses_service_role_rpc_and_decodes_token_redacted_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    request = _request()

    def fake_urlopen(call, *, timeout: float):
        observed["url"] = call.full_url
        observed["headers"] = dict(call.header_items())
        observed["body"] = json.loads(call.data)
        observed["timeout"] = timeout
        return _Response(
            {
                "request_sha256": request.request_sha256,
                "commit_owner_generation": 2,
                "commit_owner_ref": (
                    "commit-owner:git.commit:generation-2"
                ),
                "work_lease_ref": "work-lease:work-1:v3",
                "primary_authority_ref": (
                    "primary-authority:operations-core-commits:epoch-4"
                ),
            }
        )

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        fake_urlopen,
    )

    grant = _authority().authorize(request)

    assert grant.request_sha256 == request.request_sha256
    assert grant.work_lease_ref == "work-lease:work-1:v3"
    assert observed == {
        "url": (
            "https://project.supabase.co/rest/v1/rpc/"
            "volpred_authorize_commit_write"
        ),
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
            "p_request_sha256": request.request_sha256,
            "p_proposal_sha256": "a" * 64,
            "p_work_item_id": "work-1",
            "p_work_item_version": 3,
            "p_commit_owner_generation": 2,
            "p_work_lease_token": "work-secret",
            "p_repository": "/repo",
            "p_expected_head": "b" * 40,
            "p_commit_worker_ref": "commit-worker:test",
        },
        "timeout": 9,
    }


def test_request_hash_is_recomputed_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_urlopen(*args, **kwargs):
        nonlocal called
        called = True
        return _Response({})

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        fake_urlopen,
    )

    with pytest.raises(
        CommitActuatorBlocked,
        match="hash does not match",
    ):
        _authority().authorize(
            replace(_request(), repository="/forged-repository")
        )
    assert called is False


def test_fencing_failure_and_untrusted_grant_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = error.HTTPError(
        url="https://project.supabase.co/rest/v1/rpc/"
        "volpred_authorize_commit_write",
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
    with pytest.raises(CommitActuatorBlocked, match="ownership lost"):
        _authority().authorize(_request())

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: _Response(
            {
                "request_sha256": _request().request_sha256,
                "commit_owner_generation": True,
                "commit_owner_ref": (
                    "commit-owner:git.commit:generation-2"
                ),
                "work_lease_ref": "work-lease:work-1:v3",
                "primary_authority_ref": (
                    "primary-authority:operations-core-commits:epoch-4"
                ),
            }
        ),
    )
    with pytest.raises(
        CommitActuatorBlocked,
        match="invalid owner generation",
    ):
        _authority().authorize(_request())


def test_environment_adapter_never_uses_publishable_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_commit_authority."
        "runtime_environment",
        lambda: {
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_KEY": "publishable-or-anon-key",
        },
    )

    with pytest.raises(ValueError, match="service-role key"):
        SupabaseCommitAuthority.from_environment(primary_lease=_lease())
