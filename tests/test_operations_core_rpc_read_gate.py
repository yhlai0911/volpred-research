from __future__ import annotations

import pytest

from volpred.ops.delivery import supabase_rpc
from volpred.ops.delivery.supabase_rpc import ServiceRoleRpcClient


class _Response:
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return b"{}"


@pytest.mark.parametrize(
    "function",
    [
        "volpred_read_work_owner",
        "volpred_read_primary_authority_events",
        "read_volpred_growth_experiment",
        "volpred_read_future_contract",
    ],
)
def test_service_role_rpc_blocks_read_before_transport_when_remote_reads_disabled(
    monkeypatch: pytest.MonkeyPatch,
    function: str,
) -> None:
    network_calls = 0

    def fail_if_called(*args: object, **kwargs: object) -> object:
        nonlocal network_calls
        network_calls += 1
        raise AssertionError("network attempted")

    monkeypatch.setenv("VOLPRED_NO_REMOTE_READ", "1")
    monkeypatch.setattr(supabase_rpc.request, "urlopen", fail_if_called)
    client = ServiceRoleRpcClient(
        supabase_url="https://project.supabase.co",
        service_role_key="fake-service-role-key",
    )

    with pytest.raises(RuntimeError, match="remote reads are disabled"):
        client.call(function, {})

    assert network_calls == 0


def test_remote_read_guard_does_not_replace_the_independent_write_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network_calls = 0

    def respond(*args: object, **kwargs: object) -> _Response:
        nonlocal network_calls
        network_calls += 1
        return _Response()

    monkeypatch.setenv("VOLPRED_NO_REMOTE_READ", "1")
    monkeypatch.setattr(
        supabase_rpc,
        "_remote_mutations_disabled",
        lambda: False,
    )
    monkeypatch.setattr(supabase_rpc.request, "urlopen", respond)
    client = ServiceRoleRpcClient(
        supabase_url="https://project.supabase.co",
        service_role_key="fake-service-role-key",
    )

    assert client.call("volpred_request_change_set", {}) == {}
    assert network_calls == 1
