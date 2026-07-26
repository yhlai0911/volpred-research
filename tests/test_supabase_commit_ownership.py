from __future__ import annotations

from io import BytesIO
import json
from urllib import error

import pytest

from volpred.ops.delivery.owned_change import CommitOwnershipLost
from volpred.ops.delivery.supabase_commit_ownership import (
    SupabaseCommitOwnerStore,
)


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


def _owner_payload(**overrides: object) -> dict[str, object]:
    return {
        "schema_version": "commit-owner.v1",
        "capability": "git.commit",
        "owner": "legacy",
        "generation": 1,
        "changed_at": "2026-07-24T07:00:00+00:00",
        "changed_by": "migration:test",
        "change_reason": "test fixture",
        **overrides,
    }


def test_read_owner_uses_service_role_rpc_and_validates_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_urlopen(call, *, timeout: float):
        observed["url"] = call.full_url
        observed["headers"] = dict(call.header_items())
        observed["body"] = json.loads(call.data)
        observed["timeout"] = timeout
        return _Response(_owner_payload())

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        fake_urlopen,
    )
    store = SupabaseCommitOwnerStore(
        supabase_url="https://project.supabase.co/",
        service_role_key="secret-service-role",
        timeout_seconds=9,
    )

    owner = store.read_owner()

    assert (owner.owner, owner.generation) == ("legacy", 1)
    assert observed == {
        "url": (
            "https://project.supabase.co/rest/v1/rpc/"
            "volpred_read_commit_owner"
        ),
        "headers": {
            "Apikey": "secret-service-role",
            "Authorization": "Bearer secret-service-role",
            "Content-type": "application/json",
            "Accept": "application/json",
        },
        "body": {},
        "timeout": 9,
    }


def test_transfer_owner_sends_exact_compare_and_set_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_urlopen(call, *, timeout: float):
        observed["url"] = call.full_url
        observed["body"] = json.loads(call.data)
        return _Response(
            _owner_payload(
                owner="operations_core",
                generation=2,
                changed_by="operator:test",
                change_reason="controlled cutover",
            )
        )

    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        fake_urlopen,
    )
    store = SupabaseCommitOwnerStore(
        supabase_url="https://project.supabase.co",
        service_role_key="secret-service-role",
    )

    owner = store.transfer_owner(
        expected_owner="legacy",
        expected_generation=1,
        target_owner="operations_core",
        actor_ref="operator:test",
        reason="controlled cutover",
    )

    assert (owner.owner, owner.generation) == ("operations_core", 2)
    assert observed == {
        "url": (
            "https://project.supabase.co/rest/v1/rpc/"
            "volpred_transfer_commit_owner"
        ),
        "body": {
            "p_expected_owner": "legacy",
            "p_expected_generation": 1,
            "p_target_owner": "operations_core",
            "p_actor_ref": "operator:test",
            "p_reason": "controlled cutover",
            "p_rollback_of_generation": None,
        },
    }


def test_compare_and_set_failure_is_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = error.HTTPError(
        url="https://project.supabase.co/rest/v1/rpc/"
        "volpred_transfer_commit_owner",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=BytesIO(
            json.dumps(
                {
                    "message": (
                        "commit ownership compare-and-set failed: "
                        "expected legacy/1 found operations_core/2"
                    )
                }
            ).encode("utf-8")
        ),
    )
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(failure),
    )
    store = SupabaseCommitOwnerStore(
        supabase_url="https://project.supabase.co",
        service_role_key="secret-service-role",
    )

    with pytest.raises(
        CommitOwnershipLost,
        match="compare-and-set failed",
    ):
        store.transfer_owner(
            expected_owner="legacy",
            expected_generation=1,
            target_owner="operations_core",
            actor_ref="operator:test",
            reason="controlled cutover",
        )


def test_invalid_or_untrusted_owner_payload_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_rpc.request.urlopen",
        lambda *args, **kwargs: _Response(
            _owner_payload(changed_at="2026-07-24T07:00:00")
        ),
    )
    store = SupabaseCommitOwnerStore(
        supabase_url="https://project.supabase.co",
        service_role_key="secret-service-role",
    )

    with pytest.raises(ValueError, match="must include UTC offset"):
        store.read_owner()


def test_environment_adapter_never_falls_back_to_publishable_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "volpred.ops.delivery.supabase_commit_ownership."
        "runtime_environment",
        lambda: {
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_KEY": "publishable-or-anon-key",
        },
    )

    with pytest.raises(ValueError, match="service-role key"):
        SupabaseCommitOwnerStore.from_environment()
