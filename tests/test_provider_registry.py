from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import volpred.ops.execution.registry as registry_module
from volpred.ops.execution.registry import (
    DEFAULT_REGISTRY_PATH,
    ProviderRegistryError,
    authorize_provider_spawn,
    load_provider_registry,
    verify_spawn_receipt,
)


def _payload() -> dict:
    return json.loads(DEFAULT_REGISTRY_PATH.read_text())


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "provider_registry.json"
    path.write_text(json.dumps(payload, sort_keys=True))
    return path


def _fixture_executable(
    tmp_path: Path,
    *,
    provider_index: int,
    name: str,
) -> tuple[Path, Path]:
    executable = tmp_path / "installed" / name
    executable.parent.mkdir()
    executable.write_bytes(f"provider={name}\n".encode())
    executable.chmod(0o755)
    payload = _payload()
    payload["providers"][provider_index]["executables"] = [
        {
            "realpath": str(executable.resolve()),
            "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        }
    ]
    return executable, _write(tmp_path, payload)


def test_canonical_registry_is_strict_and_sha_bound() -> None:
    registry = load_provider_registry()

    assert {provider.provider_id for provider in registry.providers} == {
        "agy-cli",
        "claude-cli",
        "codex-cli",
    }
    assert registry.sha256 == hashlib.sha256(
        DEFAULT_REGISTRY_PATH.read_bytes()
    ).hexdigest()
    assert all(
        provider.formal_gate_eligible is False
        for provider in registry.providers
    )


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("billing", "mode", "api_key_metered", "billing mode"),
        ("billing", "metered", True, "metered billing"),
        ("billing", "uses_credits", True, "credits"),
        ("billing", "paid_overflow", True, "paid overflow"),
        ("auth", "api_key_env", "ANTHROPIC_API_KEY", "API-key"),
        ("auth", "auto_reload", True, "auto-reload"),
        ("auth", "surface", "api_key", "subscription surface"),
    ],
)
def test_paid_and_auto_reload_paths_are_rejected(
    tmp_path: Path,
    section: str,
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _payload()
    payload["providers"][0][section][field] = value

    with pytest.raises(ProviderRegistryError, match=message):
        load_provider_registry(_write(tmp_path, payload))


def test_unknown_fields_are_rejected(tmp_path: Path) -> None:
    payload = _payload()
    payload["providers"][0]["billing"]["future_paid_mode"] = False

    with pytest.raises(ProviderRegistryError, match="fields must be exact"):
        load_provider_registry(_write(tmp_path, payload))


def test_forbidden_environment_policy_cannot_omit_api_keys(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["providers"][0]["auth"]["forbidden_env"].remove(
        "ANTHROPIC_API_KEY"
    )

    with pytest.raises(ProviderRegistryError, match="omits forbidden"):
        load_provider_registry(_write(tmp_path, payload))


def test_authorization_reloads_and_fails_closed_after_config_change(
    tmp_path: Path,
) -> None:
    executable, path = _fixture_executable(
        tmp_path, provider_index=0, name="claude"
    )
    first = authorize_provider_spawn(
        contract_id="compute-agent.claude",
        model_id="claude-opus-4-8",
        executable_path=str(executable),
        environment={},
        path=path,
    )
    payload = json.loads(path.read_text())
    payload["providers"][0]["billing"]["paid_overflow"] = True
    _write(tmp_path, payload)

    with pytest.raises(ProviderRegistryError, match="paid overflow"):
        authorize_provider_spawn(
            contract_id="compute-agent.claude",
            model_id="claude-opus-4-8",
            executable_path=str(executable),
            environment={},
            path=path,
        )
    assert len(first.registry_sha256) == 64


def test_spawn_receipt_binds_contract_model_executable_and_registry(
    tmp_path: Path,
) -> None:
    executable, path = _fixture_executable(
        tmp_path, provider_index=1, name="codex"
    )
    receipt = authorize_provider_spawn(
        contract_id="dispatch-supervisor.codex-failover",
        model_id="gpt-5.6-sol",
        executable_path=str(executable),
        environment={},
        path=path,
    )
    environment = receipt.environment()

    assert environment["VOLPRED_PROVIDER_ID"] == "codex-cli"
    assert environment["VOLPRED_PROVIDER_MODEL_ID"] == "gpt-5.6-sol"
    assert environment["VOLPRED_PROVIDER_LAUNCH_CONTRACT"] == (
        "dispatch-supervisor.codex-failover"
    )
    assert environment["VOLPRED_PROVIDER_SEMANTIC_CLASS"] == (
        "task-orchestration"
    )
    assert environment["VOLPRED_PROVIDER_FORMAL_GATE_ELIGIBLE"] == "0"
    assert environment["VOLPRED_PROVIDER_EXECUTABLE"] == str(
        executable.resolve()
    )
    assert len(environment["VOLPRED_PROVIDER_EXECUTABLE_SHA256"]) == 64
    assert len(environment["VOLPRED_PROVIDER_REGISTRY_SHA256"]) == 64


def test_launcher_contract_cannot_be_downgraded_by_caller(
    tmp_path: Path,
) -> None:
    executable, path = _fixture_executable(
        tmp_path, provider_index=0, name="claude"
    )
    compute = authorize_provider_spawn(
        contract_id="compute-agent.claude",
        model_id="claude-opus-4-8",
        executable_path=str(executable),
        environment={},
        path=path,
    )
    orchestrator = authorize_provider_spawn(
        contract_id="dispatch-supervisor.claude",
        model_id="claude-opus-4-8",
        executable_path=str(executable),
        environment={},
        path=path,
    )

    assert compute.semantic_class == "research-compute"
    assert compute.required_capabilities == frozenset(
        {"filesystem", "python", "shell"}
    )
    assert orchestrator.semantic_class == "task-orchestration"
    assert orchestrator.required_capabilities == frozenset(
        {"filesystem", "shell", "task-routing"}
    )
    assert compute.formal_gate_eligible is False
    with pytest.raises(ProviderRegistryError, match="unknown.*contract"):
        authorize_provider_spawn(
            contract_id="caller-invented-formal-review",
            model_id="claude-opus-4-8",
            executable_path=str(executable),
            environment={},
            path=path,
        )


@pytest.mark.parametrize(
    "key",
    [
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_BEDROCK_BASE_URL",
        "ANTHROPIC_VERTEX_BASE_URL",
        "CLAUDE_CODE_SKIP_BEDROCK_AUTH",
        "CLAUDE_CODE_SKIP_VERTEX_AUTH",
        "OPENAI_API_KEY",
    ],
)
def test_nonempty_api_key_environment_is_denied_before_spawn(
    tmp_path: Path,
    key: str,
) -> None:
    executable, path = _fixture_executable(
        tmp_path, provider_index=0, name="claude"
    )

    with pytest.raises(ProviderRegistryError, match="forbidden.*variables"):
        authorize_provider_spawn(
            contract_id="compute-agent.claude",
            model_id="claude-opus-4-8",
            executable_path=str(executable),
            environment={key: "secret"},
            path=path,
        )


def test_same_basename_wrapper_and_symlink_to_it_are_denied(
    tmp_path: Path,
) -> None:
    genuine, path = _fixture_executable(
        tmp_path, provider_index=1, name="codex"
    )
    fake = tmp_path / "attacker" / "codex"
    fake.parent.mkdir()
    fake.write_bytes(genuine.read_bytes())
    fake.chmod(0o755)
    symlink = tmp_path / "codex-link"
    symlink.symlink_to(fake)

    for candidate in (fake, symlink):
        with pytest.raises(ProviderRegistryError, match="not pinned"):
            authorize_provider_spawn(
                contract_id="dispatch-supervisor.codex-failover",
                model_id="gpt-5.6-sol",
                executable_path=str(candidate),
                environment={},
                path=path,
            )


def test_executable_replacement_invalidates_receipt(tmp_path: Path) -> None:
    executable, path = _fixture_executable(
        tmp_path, provider_index=1, name="codex"
    )
    receipt = authorize_provider_spawn(
        contract_id="dispatch-supervisor.codex-failover",
        model_id="gpt-5.6-sol",
        executable_path=str(executable),
        environment={},
        path=path,
    )
    executable.write_bytes(b"replaced after authorization\n")

    with pytest.raises(ProviderRegistryError, match="bytes changed"):
        verify_spawn_receipt(receipt)


def test_api_key_helper_settings_surface_is_denied(
    tmp_path: Path,
    monkeypatch,
) -> None:
    executable, path = _fixture_executable(
        tmp_path, provider_index=0, name="claude"
    )
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(
        json.dumps({"apiKeyHelper": "/usr/local/bin/paid-key-helper"})
    )
    payload = json.loads(path.read_text())
    payload["providers"][0]["auth"]["settings_surface"] = {
        "path": ".claude/settings.json",
        "sha256": hashlib.sha256(settings.read_bytes()).hexdigest(),
    }
    path = _write(tmp_path, payload)
    monkeypatch.setattr(registry_module, "ROOT", tmp_path)

    with pytest.raises(ProviderRegistryError, match="apiKeyHelper"):
        authorize_provider_spawn(
            contract_id="compute-agent.claude",
            model_id="claude-opus-4-8",
            executable_path=str(executable),
            environment={},
            path=path,
        )
