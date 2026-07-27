"""Strict, reload-on-dispatch registry for zero-paid CLI providers.

This module authorizes provider process creation; it does not transfer
``provider.execution`` ownership or grant any formal-effect capability.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_REGISTRY_PATH = ROOT / "config" / "provider_registry.json"

_TOP_LEVEL_FIELDS = frozenset({"schema_version", "probe_policy", "providers"})
_PROBE_FIELDS = frozenset(
    {
        "minimum_interval_seconds",
        "maximum_backoff_seconds",
        "window_seconds",
        "max_probe_cost_units",
    }
)
_PROVIDER_FIELDS = frozenset(
    {
        "provider_id",
        "executable",
        "model_ids",
        "auth",
        "billing",
        "semantic_classes",
        "capabilities",
        "attestations",
        "formal_gate_eligible",
        "enabled",
        "probe_cost_units",
        "health_state",
    }
)
_AUTH_FIELDS = frozenset({"surface", "api_key_env", "auto_reload"})
_BILLING_FIELDS = frozenset(
    {"mode", "metered", "uses_credits", "paid_overflow"}
)
_HEALTH_FIELDS = frozenset({"initial", "probe_required"})
_ALLOWED_AUTH_SURFACES = frozenset(
    {"subscription_oauth", "desktop_subscription"}
)


class ProviderRegistryError(ValueError):
    """Registry content or a requested provider spawn violated policy."""


@dataclass(frozen=True)
class RegisteredProvider:
    provider_id: str
    executable: str
    model_ids: frozenset[str]
    auth_surface: str
    semantic_classes: frozenset[str]
    capabilities: frozenset[str]
    attestations: frozenset[str]
    formal_gate_eligible: bool
    enabled: bool
    probe_cost_units: int


@dataclass(frozen=True)
class ProviderRegistry:
    schema_version: str
    sha256: str
    providers: tuple[RegisteredProvider, ...]
    probe_policy: Mapping[str, int]


@dataclass(frozen=True)
class ProviderSpawnReceipt:
    provider_id: str
    model_id: str
    executable: str
    auth_surface: str
    formal_gate_eligible: bool
    registry_sha256: str

    def environment(self) -> dict[str, str]:
        """Auditable identity inherited by the authorized provider process."""
        return {
            "VOLPRED_PROVIDER_ID": self.provider_id,
            "VOLPRED_PROVIDER_MODEL_ID": self.model_id,
            "VOLPRED_PROVIDER_AUTH_SURFACE": self.auth_surface,
            "VOLPRED_PROVIDER_FORMAL_GATE_ELIGIBLE": (
                "1" if self.formal_gate_eligible else "0"
            ),
            "VOLPRED_PROVIDER_REGISTRY_SHA256": self.registry_sha256,
        }


def _exact_fields(
    value: object,
    expected: frozenset[str],
    *,
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProviderRegistryError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        unknown = sorted(actual - expected)
        missing = sorted(expected - actual)
        raise ProviderRegistryError(
            f"{label} fields must be exact; unknown={unknown}, missing={missing}"
        )
    return value


def _nonempty_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProviderRegistryError(f"{field} must be non-empty normalized text")
    return value


def _positive_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProviderRegistryError(f"{field} must be a positive integer")
    return value


def _string_set(value: object, *, field: str) -> frozenset[str]:
    if not isinstance(value, list) or not value:
        raise ProviderRegistryError(f"{field} must be a non-empty list")
    result = frozenset(
        _nonempty_text(item, field=field) for item in value
    )
    if len(result) != len(value):
        raise ProviderRegistryError(f"{field} contains duplicates")
    return result


def _validate_probe_policy(value: object) -> Mapping[str, int]:
    payload = _exact_fields(value, _PROBE_FIELDS, label="probe_policy")
    policy = {
        key: _positive_integer(payload[key], field=f"probe_policy.{key}")
        for key in _PROBE_FIELDS
    }
    if policy["maximum_backoff_seconds"] < policy["minimum_interval_seconds"]:
        raise ProviderRegistryError(
            "probe maximum backoff must cover minimum interval"
        )
    return policy


def _validate_provider(value: object) -> RegisteredProvider:
    payload = _exact_fields(value, _PROVIDER_FIELDS, label="provider")
    provider_id = _nonempty_text(payload["provider_id"], field="provider_id")
    executable = _nonempty_text(payload["executable"], field="executable")

    auth = _exact_fields(
        payload["auth"], _AUTH_FIELDS, label=f"{provider_id}.auth"
    )
    auth_surface = _nonempty_text(
        auth["surface"], field=f"{provider_id}.auth.surface"
    )
    if auth_surface not in _ALLOWED_AUTH_SURFACES:
        raise ProviderRegistryError(
            f"{provider_id} auth must use an approved subscription surface"
        )
    if auth["api_key_env"] is not None:
        raise ProviderRegistryError(f"{provider_id} API-key auth is forbidden")
    if auth["auto_reload"] is not False:
        raise ProviderRegistryError(f"{provider_id} auto-reload is forbidden")

    billing = _exact_fields(
        payload["billing"], _BILLING_FIELDS, label=f"{provider_id}.billing"
    )
    if billing["mode"] != "subscription_included":
        raise ProviderRegistryError(
            f"{provider_id} billing mode is not zero-paid"
        )
    if billing["metered"] is not False:
        raise ProviderRegistryError(f"{provider_id} metered billing is forbidden")
    if billing["uses_credits"] is not False:
        raise ProviderRegistryError(f"{provider_id} credits are forbidden")
    if billing["paid_overflow"] is not False:
        raise ProviderRegistryError(f"{provider_id} paid overflow is forbidden")

    health = _exact_fields(
        payload["health_state"],
        _HEALTH_FIELDS,
        label=f"{provider_id}.health_state",
    )
    if health != {"initial": "unknown", "probe_required": True}:
        raise ProviderRegistryError(
            f"{provider_id} health must start unknown and require a probe"
        )
    formal_gate_eligible = payload["formal_gate_eligible"]
    enabled = payload["enabled"]
    if not isinstance(formal_gate_eligible, bool) or not isinstance(enabled, bool):
        raise ProviderRegistryError(
            f"{provider_id} formal/enabled flags must be booleans"
        )

    return RegisteredProvider(
        provider_id=provider_id,
        executable=executable,
        model_ids=_string_set(
            payload["model_ids"], field=f"{provider_id}.model_ids"
        ),
        auth_surface=auth_surface,
        semantic_classes=_string_set(
            payload["semantic_classes"], field=f"{provider_id}.semantic_classes"
        ),
        capabilities=_string_set(
            payload["capabilities"], field=f"{provider_id}.capabilities"
        ),
        attestations=_string_set(
            payload["attestations"], field=f"{provider_id}.attestations"
        ),
        formal_gate_eligible=formal_gate_eligible,
        enabled=enabled,
        probe_cost_units=_positive_integer(
            payload["probe_cost_units"],
            field=f"{provider_id}.probe_cost_units",
        ),
    )


def load_provider_registry(
    path: Path = DEFAULT_REGISTRY_PATH,
) -> ProviderRegistry:
    """Read and validate exact bytes. No cache: callers reload before each spawn."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ProviderRegistryError(f"provider registry unreadable: {exc}") from None
    try:
        decoded = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderRegistryError(f"provider registry is invalid JSON: {exc}") from None
    payload = _exact_fields(decoded, _TOP_LEVEL_FIELDS, label="registry")
    if payload["schema_version"] != "provider-registry.v1":
        raise ProviderRegistryError("unsupported provider registry schema")
    providers_raw = payload["providers"]
    if not isinstance(providers_raw, list) or not providers_raw:
        raise ProviderRegistryError("registry providers must be a non-empty list")
    providers = tuple(_validate_provider(item) for item in providers_raw)
    provider_ids = [provider.provider_id for provider in providers]
    if len(set(provider_ids)) != len(provider_ids):
        raise ProviderRegistryError("provider ids must be unique")
    all_models = [
        model_id
        for provider in providers
        for model_id in provider.model_ids
    ]
    if len(set(all_models)) != len(all_models):
        raise ProviderRegistryError("model ids must resolve to exactly one provider")
    return ProviderRegistry(
        schema_version="provider-registry.v1",
        sha256=hashlib.sha256(raw).hexdigest(),
        providers=providers,
        probe_policy=_validate_probe_policy(payload["probe_policy"]),
    )


def authorize_provider_spawn(
    *,
    provider_id: str,
    model_id: str,
    path: Path = DEFAULT_REGISTRY_PATH,
) -> ProviderSpawnReceipt:
    """Reload the registry and fail closed before provider process creation."""
    registry = load_provider_registry(path)
    matches = [
        provider
        for provider in registry.providers
        if provider.provider_id == provider_id
    ]
    if len(matches) != 1:
        raise ProviderRegistryError(
            f"provider {provider_id!r} is not uniquely registered"
        )
    provider = matches[0]
    if not provider.enabled:
        raise ProviderRegistryError(f"provider {provider_id!r} is disabled")
    if model_id not in provider.model_ids:
        raise ProviderRegistryError(
            f"model {model_id!r} is not registered for {provider_id!r}"
        )
    if "zero-paid" not in provider.attestations:
        raise ProviderRegistryError(
            f"provider {provider_id!r} lacks zero-paid attestation"
        )
    return ProviderSpawnReceipt(
        provider_id=provider.provider_id,
        model_id=model_id,
        executable=provider.executable,
        auth_surface=provider.auth_surface,
        formal_gate_eligible=provider.formal_gate_eligible,
        registry_sha256=registry.sha256,
    )
