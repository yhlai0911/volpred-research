from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from volpred.ops.execution.registry import (
    DEFAULT_REGISTRY_PATH,
    ProviderRegistryError,
    authorize_provider_spawn,
    load_provider_registry,
)


def _payload() -> dict:
    return json.loads(DEFAULT_REGISTRY_PATH.read_text())


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "provider_registry.json"
    path.write_text(json.dumps(payload, sort_keys=True))
    return path


def test_canonical_registry_is_strict_and_sha_bound() -> None:
    registry = load_provider_registry()

    assert {provider.provider_id for provider in registry.providers} == {
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


def test_authorization_reloads_and_fails_closed_after_config_change(
    tmp_path: Path,
) -> None:
    payload = _payload()
    path = _write(tmp_path, payload)
    first = authorize_provider_spawn(
        provider_id="claude-cli",
        model_id="claude-opus-4-8",
        path=path,
    )

    payload["providers"][0]["billing"]["paid_overflow"] = True
    _write(tmp_path, payload)

    with pytest.raises(ProviderRegistryError, match="paid overflow"):
        authorize_provider_spawn(
            provider_id="claude-cli",
            model_id="claude-opus-4-8",
            path=path,
        )
    assert len(first.registry_sha256) == 64


def test_spawn_receipt_binds_provider_model_and_registry_sha() -> None:
    receipt = authorize_provider_spawn(
        provider_id="codex-cli",
        model_id="codex-failover",
    )

    assert receipt.environment() == {
        "VOLPRED_PROVIDER_ID": "codex-cli",
        "VOLPRED_PROVIDER_MODEL_ID": "codex-failover",
        "VOLPRED_PROVIDER_AUTH_SURFACE": "desktop_subscription",
        "VOLPRED_PROVIDER_FORMAL_GATE_ELIGIBLE": "0",
        "VOLPRED_PROVIDER_REGISTRY_SHA256": receipt.registry_sha256,
    }
