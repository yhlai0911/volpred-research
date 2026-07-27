from __future__ import annotations

import os

import pytest

from scripts import authorized_provider_exec


def test_policy_denial_precedes_execve(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        authorized_provider_exec,
        "authorize_provider_spawn",
        lambda **_kwargs: (_ for _ in ()).throw(
            authorized_provider_exec.ProviderRegistryError("paid path denied")
        ),
    )
    monkeypatch.setattr(
        authorized_provider_exec.os,
        "execve",
        lambda *_args: pytest.fail("policy denial must precede execve"),
    )

    rc = authorized_provider_exec.main(
        [
            "--contract",
            "telegram-responder.claude",
            "--model",
            "claude-opus-4-8",
            "--executable",
            "/usr/local/bin/claude",
            "--",
            "-p",
            "work",
        ]
    )

    assert rc == 126
    assert "paid path denied" in capsys.readouterr().err


def test_verified_receipt_replaces_executable_and_stamps_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, list[str], dict[str, str]]] = []

    class Receipt:
        resolved_executable = "/pinned/provider"

        @staticmethod
        def environment() -> dict[str, str]:
            return {"VOLPRED_PROVIDER_ID": "test-provider"}

    monkeypatch.setattr(
        authorized_provider_exec,
        "authorize_provider_spawn",
        lambda **_kwargs: Receipt(),
    )
    monkeypatch.setattr(
        authorized_provider_exec,
        "verify_spawn_receipt",
        lambda _receipt: None,
    )
    monkeypatch.setattr(
        authorized_provider_exec.os,
        "execve",
        lambda executable, argv, env: calls.append((executable, argv, env)),
    )
    monkeypatch.setenv("PARENT_SENTINEL", "kept")

    rc = authorized_provider_exec.main(
        [
            "--contract",
            "telegram-responder.codex",
            "--model",
            "gpt-5.6-sol",
            "--executable",
            "/untrusted/codex",
            "--",
            "exec",
            "work",
        ]
    )

    assert rc == 0
    executable, argv, env = calls[0]
    assert executable == "/pinned/provider"
    assert argv == ["/pinned/provider", "exec", "work"]
    assert env["VOLPRED_PROVIDER_ID"] == "test-provider"
    assert env["PARENT_SENTINEL"] == "kept"
    assert env is not os.environ
