"""Strict, reload-on-dispatch registry for zero-paid CLI providers.

This module authorizes provider process creation; it does not transfer
``provider.execution`` ownership or grant any formal-effect capability.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_REGISTRY_PATH = ROOT / "config" / "provider_registry.json"

_TOP_LEVEL_FIELDS = frozenset({"schema_version", "probe_policy", "providers"})
_PROBE_FIELDS = frozenset(
    {
        "minimum_interval_seconds",
        "maximum_backoff_seconds",
        "window_seconds",
        "max_probe_cost_units",
        "reservation_ttl_seconds",
    }
)
_PROVIDER_FIELDS = frozenset(
    {
        "provider_id",
        "executables",
        "model_ids",
        "reasoning_effort",
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
_AUTH_FIELDS = frozenset(
    {
        "surface",
        "api_key_env",
        "auto_reload",
        "forbidden_env",
        "settings_surface",
    }
)
_EXECUTABLE_FIELDS = frozenset({"realpath", "sha256"})
_SETTINGS_FIELDS = frozenset({"path", "sha256"})
_BILLING_FIELDS = frozenset(
    {"mode", "metered", "uses_credits", "paid_overflow"}
)
_HEALTH_FIELDS = frozenset({"initial", "probe_required"})
_REASONING_EFFORT_FIELDS = frozenset({"supported_values", "profiles"})
_ALLOWED_AUTH_SURFACES = frozenset(
    {"subscription_oauth", "desktop_subscription"}
)
_REQUIRED_FORBIDDEN_ENV = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_BEDROCK_BASE_URL",
        "ANTHROPIC_CUSTOM_HEADERS",
        "ANTHROPIC_FOUNDRY_API_KEY",
        "ANTHROPIC_FOUNDRY_BASE_URL",
        "ANTHROPIC_VERTEX_BASE_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_PROFILE",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_ENDPOINT",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_FOUNDRY",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_SKIP_BEDROCK_AUTH",
        "CLAUDE_CODE_SKIP_VERTEX_AUTH",
        "CODEX_API_KEY",
        "CODEX_HOME",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_BASE",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_ORGANIZATION",
    }
)


class ProviderRegistryError(ValueError):
    """Registry content or a requested provider spawn violated policy."""


@dataclass(frozen=True)
class ExecutableIdentity:
    realpath: str
    sha256: str


@dataclass(frozen=True)
class SettingsSurface:
    path: str
    sha256: str


@dataclass(frozen=True)
class ReasoningEffortPolicy:
    supported_values: frozenset[str]
    profiles: tuple[tuple[str, str], ...]

    def resolve(self, profile: str) -> str:
        matches = [value for name, value in self.profiles if name == profile]
        if len(matches) != 1:
            raise ProviderRegistryError(
                f"unknown provider reasoning effort profile {profile!r}"
            )
        return matches[0]


@dataclass(frozen=True)
class ProviderExecutionContract:
    provider_id: str
    launch_contract_id: str
    model_id: str
    reasoning_effort_profile: str
    reasoning_effort: str
    registry_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            "provider_id": self.provider_id,
            "launch_contract_id": self.launch_contract_id,
            "model_id": self.model_id,
            "reasoning_effort_profile": self.reasoning_effort_profile,
            "reasoning_effort": self.reasoning_effort,
            "registry_sha256": self.registry_sha256,
        }


CODEX_FAILOVER_TIMEOUT_EXIT_CODE = -5


@dataclass(frozen=True)
class ProviderCompletionPolicy:
    launch_contract_id: str
    exact_exit_code: int | None = None
    require_nonzero_exit: bool = False
    forbidden_exit_codes: frozenset[int] = frozenset()

    def validate_exit_code(self, *, outcome: str, exit_code: int) -> None:
        if self.exact_exit_code is not None and exit_code != self.exact_exit_code:
            raise ProviderRegistryError(
                f"provider completion outcome {outcome!r} requires exit code "
                f"{self.exact_exit_code}, got {exit_code}"
            )
        if self.require_nonzero_exit and exit_code == 0:
            raise ProviderRegistryError(
                f"provider completion outcome {outcome!r} requires a nonzero "
                "exit code"
            )
        if exit_code in self.forbidden_exit_codes:
            raise ProviderRegistryError(
                f"provider completion outcome {outcome!r} forbids exit code "
                f"{exit_code}"
            )


@dataclass(frozen=True)
class RegisteredProvider:
    provider_id: str
    executables: tuple[ExecutableIdentity, ...]
    model_ids: frozenset[str]
    reasoning_effort: ReasoningEffortPolicy | None
    auth_surface: str
    forbidden_env: frozenset[str]
    settings_surface: SettingsSurface | None
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
class ProviderProbeAuthorization:
    provider_id: str
    model_id: str
    resolved_executable: str
    executable_sha256: str
    auth_surface: str
    registry_sha256: str
    cost_units: int
    minimum_interval_seconds: int
    maximum_backoff_seconds: int
    window_seconds: int
    max_probe_cost_units: int
    reservation_ttl_seconds: int
    settings_path: str | None
    settings_sha256: str | None


@dataclass(frozen=True)
class LaunchContract:
    provider_id: str
    semantic_class: str
    required_capabilities: frozenset[str]
    requires_formal_gate: bool
    reasoning_effort_profile: str | None = None


_LAUNCH_CONTRACTS = {
    "dispatch-supervisor.claude": LaunchContract(
        provider_id="claude-cli",
        semantic_class="task-orchestration",
        required_capabilities=frozenset(
            {"filesystem", "shell", "task-routing"}
        ),
        requires_formal_gate=False,
    ),
    "compute-agent.claude": LaunchContract(
        provider_id="claude-cli",
        semantic_class="research-compute",
        required_capabilities=frozenset({"filesystem", "python", "shell"}),
        requires_formal_gate=False,
    ),
    "org-manager.claude": LaunchContract(
        provider_id="claude-cli",
        semantic_class="task-orchestration",
        required_capabilities=frozenset(
            {"filesystem", "shell", "task-routing"}
        ),
        requires_formal_gate=False,
    ),
    "dispatch-supervisor.codex-probe": LaunchContract(
        provider_id="codex-cli",
        semantic_class="task-orchestration",
        required_capabilities=frozenset(
            {"filesystem", "shell", "task-routing"}
        ),
        requires_formal_gate=False,
        reasoning_effort_profile="probe",
    ),
    "dispatch-supervisor.codex-failover": LaunchContract(
        provider_id="codex-cli",
        semantic_class="task-orchestration",
        required_capabilities=frozenset(
            {"filesystem", "shell", "task-routing"}
        ),
        requires_formal_gate=False,
        reasoning_effort_profile="work",
    ),
    "execution-brief.claude": LaunchContract(
        provider_id="claude-cli",
        semantic_class="task-orchestration",
        required_capabilities=frozenset(
            {"filesystem", "shell", "task-routing"}
        ),
        requires_formal_gate=False,
    ),
    "execution-brief.codex": LaunchContract(
        provider_id="codex-cli",
        semantic_class="task-orchestration",
        required_capabilities=frozenset(
            {"filesystem", "shell", "task-routing"}
        ),
        requires_formal_gate=False,
    ),
    "lazypack.codex": LaunchContract(
        provider_id="codex-cli",
        semantic_class="code-change",
        required_capabilities=frozenset({"filesystem", "python", "shell"}),
        requires_formal_gate=False,
    ),
    "lazypack.agy": LaunchContract(
        provider_id="agy-cli",
        semantic_class="code-change",
        required_capabilities=frozenset({"filesystem", "python", "shell"}),
        requires_formal_gate=False,
    ),
    "trending-scan.agy": LaunchContract(
        provider_id="agy-cli",
        semantic_class="content-discovery",
        required_capabilities=frozenset(
            {"current-events-discovery", "text-reasoning"}
        ),
        requires_formal_gate=False,
    ),
    "member-qa-adjudicator.agy": LaunchContract(
        provider_id="agy-cli",
        semantic_class="semantic-adjudication",
        required_capabilities=frozenset({"text-reasoning"}),
        requires_formal_gate=False,
    ),
    "prepublish-audit.agy": LaunchContract(
        provider_id="agy-cli",
        semantic_class="research-review",
        required_capabilities=frozenset(
            {"source-consistency-review", "text-reasoning"}
        ),
        requires_formal_gate=False,
    ),
    "bounded-codex.agentic": LaunchContract(
        provider_id="codex-cli",
        semantic_class="agentic-execution",
        required_capabilities=frozenset({"filesystem", "shell"}),
        requires_formal_gate=False,
    ),
    "telegram-responder.claude": LaunchContract(
        provider_id="claude-cli",
        semantic_class="task-orchestration",
        required_capabilities=frozenset(
            {"filesystem", "shell", "task-routing"}
        ),
        requires_formal_gate=False,
    ),
    "telegram-responder.codex": LaunchContract(
        provider_id="codex-cli",
        semantic_class="task-orchestration",
        required_capabilities=frozenset(
            {"filesystem", "shell", "task-routing"}
        ),
        requires_formal_gate=False,
    ),
}


_PROVIDER_COMPLETION_POLICIES = {
    "codex_failover_recovered": ProviderCompletionPolicy(
        launch_contract_id="dispatch-supervisor.codex-failover",
        exact_exit_code=0,
    ),
    "codex_failover_failed": ProviderCompletionPolicy(
        launch_contract_id="dispatch-supervisor.codex-failover",
        require_nonzero_exit=True,
        forbidden_exit_codes=frozenset({CODEX_FAILOVER_TIMEOUT_EXIT_CODE}),
    ),
    "codex_failover_timeout": ProviderCompletionPolicy(
        launch_contract_id="dispatch-supervisor.codex-failover",
        exact_exit_code=CODEX_FAILOVER_TIMEOUT_EXIT_CODE,
    ),
}
PROVIDER_EXECUTION_OUTCOMES = frozenset(_PROVIDER_COMPLETION_POLICIES)


@dataclass(frozen=True)
class ProviderSpawnReceipt:
    contract_id: str
    provider_id: str
    model_id: str
    resolved_executable: str
    executable_sha256: str
    auth_surface: str
    formal_gate_eligible: bool
    registry_sha256: str
    semantic_class: str
    required_capabilities: frozenset[str]
    settings_path: str | None
    settings_sha256: str | None
    reasoning_effort_profile: str | None
    reasoning_effort: str | None

    def execution_contract(self) -> ProviderExecutionContract:
        if (
            self.reasoning_effort_profile is None
            or self.reasoning_effort is None
        ):
            raise ProviderRegistryError(
                "provider spawn receipt has no reasoning effort contract"
            )
        return ProviderExecutionContract(
            provider_id=self.provider_id,
            launch_contract_id=self.contract_id,
            model_id=self.model_id,
            reasoning_effort_profile=self.reasoning_effort_profile,
            reasoning_effort=self.reasoning_effort,
            registry_sha256=self.registry_sha256,
        )

    def environment(self) -> dict[str, str]:
        """Auditable identity inherited by the authorized provider process."""
        environment = {
            "VOLPRED_PROVIDER_ID": self.provider_id,
            "VOLPRED_PROVIDER_LAUNCH_CONTRACT": self.contract_id,
            "VOLPRED_PROVIDER_MODEL_ID": self.model_id,
            "VOLPRED_PROVIDER_AUTH_SURFACE": self.auth_surface,
            "VOLPRED_PROVIDER_EXECUTABLE": self.resolved_executable,
            "VOLPRED_PROVIDER_EXECUTABLE_SHA256": self.executable_sha256,
            "VOLPRED_PROVIDER_FORMAL_GATE_ELIGIBLE": (
                "1" if self.formal_gate_eligible else "0"
            ),
            "VOLPRED_PROVIDER_REGISTRY_SHA256": self.registry_sha256,
            "VOLPRED_PROVIDER_SEMANTIC_CLASS": self.semantic_class,
            "VOLPRED_PROVIDER_REQUIRED_CAPABILITIES": ",".join(
                sorted(self.required_capabilities)
            ),
            "VOLPRED_PROVIDER_SETTINGS_SHA256": self.settings_sha256 or "",
        }
        if self.reasoning_effort_profile is not None:
            environment["VOLPRED_PROVIDER_REASONING_EFFORT_PROFILE"] = (
                self.reasoning_effort_profile
            )
        if self.reasoning_effort is not None:
            environment["VOLPRED_PROVIDER_REASONING_EFFORT"] = (
                self.reasoning_effort
            )
        return environment


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


def _validate_reasoning_effort_policy(
    value: object,
    *,
    provider_id: str,
) -> ReasoningEffortPolicy | None:
    if value is None:
        return None
    payload = _exact_fields(
        value,
        _REASONING_EFFORT_FIELDS,
        label=f"{provider_id}.reasoning_effort",
    )
    supported_values = _string_set(
        payload["supported_values"],
        field=f"{provider_id}.reasoning_effort.supported_values",
    )
    raw_profiles = payload["profiles"]
    if not isinstance(raw_profiles, Mapping) or not raw_profiles:
        raise ProviderRegistryError(
            f"{provider_id}.reasoning_effort.profiles must be a non-empty object"
        )
    profiles = tuple(
        sorted(
            (
                _nonempty_text(
                    name,
                    field=f"{provider_id}.reasoning_effort profile name",
                ),
                _nonempty_text(
                    effort,
                    field=(
                        f"{provider_id}.reasoning_effort.profiles.{name}"
                    ),
                ),
            )
            for name, effort in raw_profiles.items()
        )
    )
    unsupported = sorted(
        effort for _name, effort in profiles if effort not in supported_values
    )
    if unsupported:
        raise ProviderRegistryError(
            f"{provider_id}.reasoning_effort profiles contain values outside "
            f"supported_values: {unsupported}"
        )
    return ReasoningEffortPolicy(
        supported_values=supported_values,
        profiles=profiles,
    )


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
    if policy["reservation_ttl_seconds"] > policy["minimum_interval_seconds"]:
        raise ProviderRegistryError(
            "probe reservation TTL cannot exceed minimum interval"
        )
    return policy


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ProviderRegistryError(
            f"provider executable unreadable: {exc}"
        ) from None
    return digest.hexdigest()


def _validate_executables(
    value: object,
    *,
    provider_id: str,
) -> tuple[ExecutableIdentity, ...]:
    if not isinstance(value, list) or not value:
        raise ProviderRegistryError(
            f"{provider_id}.executables must be a non-empty list"
        )
    result: list[ExecutableIdentity] = []
    for index, item in enumerate(value):
        payload = _exact_fields(
            item,
            _EXECUTABLE_FIELDS,
            label=f"{provider_id}.executables[{index}]",
        )
        realpath = _nonempty_text(
            payload["realpath"],
            field=f"{provider_id}.executables[{index}].realpath",
        )
        if not Path(realpath).is_absolute():
            raise ProviderRegistryError(
                f"{provider_id} executable realpath must be absolute"
            )
        sha256 = _nonempty_text(
            payload["sha256"],
            field=f"{provider_id}.executables[{index}].sha256",
        )
        if len(sha256) != 64 or any(ch not in "0123456789abcdef" for ch in sha256):
            raise ProviderRegistryError(
                f"{provider_id} executable SHA-256 is invalid"
            )
        result.append(ExecutableIdentity(realpath=realpath, sha256=sha256))
    if len({item.realpath for item in result}) != len(result):
        raise ProviderRegistryError(
            f"{provider_id} executable realpaths must be unique"
        )
    return tuple(result)


def _sha256_text(value: object, *, field: str) -> str:
    sha256 = _nonempty_text(value, field=field)
    if len(sha256) != 64 or any(
        ch not in "0123456789abcdef" for ch in sha256
    ):
        raise ProviderRegistryError(f"{field} is not a valid SHA-256")
    return sha256


def _validate_settings_surface(
    value: object,
    *,
    provider_id: str,
) -> SettingsSurface | None:
    if value is None:
        return None
    payload = _exact_fields(
        value,
        _SETTINGS_FIELDS,
        label=f"{provider_id}.auth.settings_surface",
    )
    relative_path = _nonempty_text(
        payload["path"],
        field=f"{provider_id}.auth.settings_surface.path",
    )
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise ProviderRegistryError(
            f"{provider_id} settings path must be repo-relative"
        )
    return SettingsSurface(
        path=relative_path,
        sha256=_sha256_text(
            payload["sha256"],
            field=f"{provider_id}.auth.settings_surface.sha256",
        ),
    )


def _validate_provider(value: object) -> RegisteredProvider:
    payload = _exact_fields(value, _PROVIDER_FIELDS, label="provider")
    provider_id = _nonempty_text(payload["provider_id"], field="provider_id")

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
    forbidden_env = _string_set(
        auth["forbidden_env"], field=f"{provider_id}.auth.forbidden_env"
    )
    missing_forbidden_env = _REQUIRED_FORBIDDEN_ENV - forbidden_env
    if missing_forbidden_env:
        raise ProviderRegistryError(
            f"{provider_id} auth policy omits forbidden environment variables "
            f"{sorted(missing_forbidden_env)}"
        )

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
        executables=_validate_executables(
            payload["executables"], provider_id=provider_id
        ),
        model_ids=_string_set(
            payload["model_ids"], field=f"{provider_id}.model_ids"
        ),
        reasoning_effort=_validate_reasoning_effort_policy(
            payload["reasoning_effort"],
            provider_id=provider_id,
        ),
        auth_surface=auth_surface,
        forbidden_env=forbidden_env,
        settings_surface=_validate_settings_surface(
            auth["settings_surface"], provider_id=provider_id
        ),
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


def validate_provider_execution_contract(
    contract: ProviderExecutionContract,
    *,
    path: Path = DEFAULT_REGISTRY_PATH,
) -> None:
    """Verify a completion contract against the exact authorized generation."""
    if not isinstance(contract, ProviderExecutionContract):
        raise ProviderRegistryError(
            "provider execution contract must use the canonical typed receipt"
        )
    registry = load_provider_registry(path)
    if contract.registry_sha256 != registry.sha256:
        raise ProviderRegistryError(
            "provider execution contract registry generation does not match"
        )
    launch_contract = _LAUNCH_CONTRACTS.get(contract.launch_contract_id)
    if launch_contract is None:
        raise ProviderRegistryError(
            "provider execution contract has unknown launch contract "
            f"{contract.launch_contract_id!r}"
        )
    if launch_contract.provider_id != contract.provider_id:
        raise ProviderRegistryError(
            "provider execution contract provider does not match launch contract"
        )
    if launch_contract.reasoning_effort_profile is None:
        raise ProviderRegistryError(
            "provider execution contract launch contract has no reasoning "
            "effort profile"
        )
    if (
        contract.reasoning_effort_profile
        != launch_contract.reasoning_effort_profile
    ):
        raise ProviderRegistryError(
            "provider execution contract reasoning effort profile does not "
            "match launch contract"
        )
    matches = [
        provider
        for provider in registry.providers
        if provider.provider_id == contract.provider_id
    ]
    if len(matches) != 1:
        raise ProviderRegistryError(
            f"provider execution contract has unknown provider "
            f"{contract.provider_id!r}"
        )
    provider = matches[0]
    if contract.model_id not in provider.model_ids:
        raise ProviderRegistryError(
            f"provider execution contract has unknown model "
            f"{contract.model_id!r}"
        )
    if provider.reasoning_effort is None:
        raise ProviderRegistryError(
            f"provider {provider.provider_id!r} has no reasoning effort policy"
        )
    expected = provider.reasoning_effort.resolve(
        contract.reasoning_effort_profile
    )
    if contract.reasoning_effort != expected:
        raise ProviderRegistryError(
            "provider execution contract reasoning effort does not match "
            f"profile {contract.reasoning_effort_profile!r}"
        )


def validate_provider_execution_settlement(
    contract: ProviderExecutionContract,
    *,
    outcome: str,
    exit_code: int,
    path: Path = DEFAULT_REGISTRY_PATH,
) -> None:
    """Reject a completion whose provider, launch contract, or exit lies."""
    policy = _PROVIDER_COMPLETION_POLICIES.get(outcome)
    if policy is None:
        raise ProviderRegistryError(
            f"provider execution contract is invalid for outcome {outcome!r}"
        )
    validate_provider_execution_contract(contract, path=path)
    if contract.launch_contract_id != policy.launch_contract_id:
        raise ProviderRegistryError(
            "provider execution launch contract is invalid for completion "
            f"outcome {outcome!r}: expected {policy.launch_contract_id!r}, got "
            f"{contract.launch_contract_id!r}"
        )
    policy.validate_exit_code(outcome=outcome, exit_code=exit_code)


def _authorize_registered_provider(
    *,
    provider_id: str,
    model_id: str,
    executable_path: str,
    environment: Mapping[str, str],
    path: Path,
) -> tuple[
    ProviderRegistry,
    RegisteredProvider,
    str,
    str,
    str | None,
    str | None,
]:
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
        raise ProviderRegistryError(
            f"provider {provider.provider_id!r} is disabled"
        )
    if model_id not in provider.model_ids:
        raise ProviderRegistryError(
            f"model {model_id!r} is not registered for {provider.provider_id!r}"
        )
    executable = Path(executable_path)
    try:
        resolved_executable = str(executable.resolve(strict=True))
    except OSError as exc:
        raise ProviderRegistryError(
            f"provider executable cannot be resolved: {exc}"
        ) from None
    executable_sha256 = _sha256_file(Path(resolved_executable))
    identity_matches = [
        identity
        for identity in provider.executables
        if identity.realpath == resolved_executable
        and identity.sha256 == executable_sha256
    ]
    if len(identity_matches) != 1:
        raise ProviderRegistryError(
            f"executable identity is not pinned for provider "
            f"{provider.provider_id!r}: path={resolved_executable!r} "
            f"sha256={executable_sha256}"
        )
    forbidden_present = sorted(
        key
        for key in provider.forbidden_env
        if environment.get(key)
    )
    if forbidden_present:
        raise ProviderRegistryError(
            f"provider environment contains forbidden API-key/alternate-auth "
            f"variables {forbidden_present}"
        )
    settings_path: str | None = None
    settings_sha256: str | None = None
    if provider.provider_id == "claude-cli" and provider.settings_surface is None:
        raise ProviderRegistryError(
            "Claude provider requires a pinned settings surface"
        )
    if provider.settings_surface is not None:
        settings = ROOT / provider.settings_surface.path
        settings_path = str(settings.resolve(strict=False))
        settings_sha256 = _sha256_file(settings)
        if settings_sha256 != provider.settings_surface.sha256:
            raise ProviderRegistryError(
                "provider settings bytes do not match the pinned auth surface"
            )
        try:
            settings_payload = json.loads(settings.read_bytes())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderRegistryError(
                f"provider settings are unreadable: {exc}"
            ) from None
        if not isinstance(settings_payload, Mapping):
            raise ProviderRegistryError("provider settings must be an object")
        if settings_payload.get("apiKeyHelper"):
            raise ProviderRegistryError(
                "provider settings apiKeyHelper is forbidden"
            )
        settings_env = settings_payload.get("env") or {}
        if not isinstance(settings_env, Mapping):
            raise ProviderRegistryError("provider settings env must be an object")
        forbidden_settings_env = sorted(
            key
            for key in provider.forbidden_env
            if settings_env.get(key)
        )
        if forbidden_settings_env:
            raise ProviderRegistryError(
                "provider settings contain forbidden alternate-auth variables "
                f"{forbidden_settings_env}"
            )
    if "zero-paid" not in provider.attestations:
        raise ProviderRegistryError(
            f"provider {provider.provider_id!r} lacks zero-paid attestation"
        )
    return (
        registry,
        provider,
        resolved_executable,
        executable_sha256,
        settings_path,
        settings_sha256,
    )


def authorize_provider_probe(
    *,
    provider_id: str,
    model_id: str,
    executable_path: str,
    environment: Mapping[str, str],
    path: Path = DEFAULT_REGISTRY_PATH,
) -> ProviderProbeAuthorization:
    """Authorize one bounded diagnostic probe without granting business work."""
    (
        registry,
        provider,
        resolved_executable,
        executable_sha256,
        settings_path,
        settings_sha256,
    ) = _authorize_registered_provider(
        provider_id=provider_id,
        model_id=model_id,
        executable_path=executable_path,
        environment=environment,
        path=path,
    )
    return ProviderProbeAuthorization(
        provider_id=provider.provider_id,
        model_id=model_id,
        resolved_executable=resolved_executable,
        executable_sha256=executable_sha256,
        auth_surface=provider.auth_surface,
        registry_sha256=registry.sha256,
        cost_units=provider.probe_cost_units,
        minimum_interval_seconds=registry.probe_policy[
            "minimum_interval_seconds"
        ],
        maximum_backoff_seconds=registry.probe_policy[
            "maximum_backoff_seconds"
        ],
        window_seconds=registry.probe_policy["window_seconds"],
        max_probe_cost_units=registry.probe_policy[
            "max_probe_cost_units"
        ],
        reservation_ttl_seconds=registry.probe_policy[
            "reservation_ttl_seconds"
        ],
        settings_path=settings_path,
        settings_sha256=settings_sha256,
    )


def sanitize_provider_spawn_environment(
    *,
    contract_id: str,
    environment: Mapping[str, str],
    path: Path = DEFAULT_REGISTRY_PATH,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Drop the contract's forbidden auth variables before authorization.

    Fail-safe counterpart to the fail-closed check in
    ``authorize_provider_spawn``: a provider child never legitimately needs a
    forbidden alternate-auth variable, but a long-lived daemon can absorb one
    into ``os.environ`` at runtime through library import side effects that a
    boot-time environment audit cannot see (2026-08-04: an in-process alert
    primed .env's OPENAI_API_KEY into the dispatch supervisor and every
    subsequent spawn was denied). Spawn sites strip here and log the stripped
    NAMES ONLY; the authorize check stays authoritative for anything that
    still reaches it.
    """
    contract = _LAUNCH_CONTRACTS.get(contract_id)
    if contract is None:
        raise ProviderRegistryError(
            f"unknown provider launch contract {contract_id!r}"
        )
    registry = load_provider_registry(path)
    matches = [
        provider
        for provider in registry.providers
        if provider.provider_id == contract.provider_id
    ]
    if len(matches) != 1:
        raise ProviderRegistryError(
            f"provider {contract.provider_id!r} is not uniquely registered"
        )
    forbidden = matches[0].forbidden_env
    stripped = tuple(sorted(key for key in environment if key in forbidden))
    if not stripped:
        return dict(environment), ()
    return (
        {key: value for key, value in environment.items() if key not in forbidden},
        stripped,
    )


def authorize_provider_spawn(
    *,
    contract_id: str,
    model_id: str,
    executable_path: str,
    environment: Mapping[str, str],
    path: Path = DEFAULT_REGISTRY_PATH,
) -> ProviderSpawnReceipt:
    """Reload the registry and fail closed before provider process creation."""
    contract = _LAUNCH_CONTRACTS.get(contract_id)
    if contract is None:
        raise ProviderRegistryError(
            f"unknown provider launch contract {contract_id!r}"
        )
    (
        registry,
        provider,
        resolved_executable,
        executable_sha256,
        settings_path,
        settings_sha256,
    ) = _authorize_registered_provider(
        provider_id=contract.provider_id,
        model_id=model_id,
        executable_path=executable_path,
        environment=environment,
        path=path,
    )
    if contract.semantic_class not in provider.semantic_classes:
        raise ProviderRegistryError(
            f"provider {provider.provider_id!r} does not attest semantic class "
            f"{contract.semantic_class!r}"
        )
    missing_capabilities = contract.required_capabilities - provider.capabilities
    if missing_capabilities:
        raise ProviderRegistryError(
            f"provider {provider.provider_id!r} lacks capabilities "
            f"{sorted(missing_capabilities)}"
        )
    if contract.requires_formal_gate and not provider.formal_gate_eligible:
        raise ProviderRegistryError(
            f"provider {provider.provider_id!r} is not formal-gate eligible"
        )
    reasoning_effort_profile = contract.reasoning_effort_profile
    reasoning_effort: str | None = None
    if reasoning_effort_profile is not None:
        if provider.reasoning_effort is None:
            raise ProviderRegistryError(
                f"provider {provider.provider_id!r} has no reasoning effort policy"
            )
        reasoning_effort = provider.reasoning_effort.resolve(
            reasoning_effort_profile
        )
    return ProviderSpawnReceipt(
        contract_id=contract_id,
        provider_id=provider.provider_id,
        model_id=model_id,
        resolved_executable=resolved_executable,
        executable_sha256=executable_sha256,
        auth_surface=provider.auth_surface,
        formal_gate_eligible=provider.formal_gate_eligible,
        registry_sha256=registry.sha256,
        semantic_class=contract.semantic_class,
        required_capabilities=contract.required_capabilities,
        settings_path=settings_path,
        settings_sha256=settings_sha256,
        reasoning_effort_profile=reasoning_effort_profile,
        reasoning_effort=reasoning_effort,
    )


def verify_spawn_receipt(receipt: ProviderSpawnReceipt) -> None:
    """Re-read the pinned executable immediately before process creation."""
    executable = Path(receipt.resolved_executable)
    try:
        if str(executable.resolve(strict=True)) != receipt.resolved_executable:
            raise ProviderRegistryError(
                "provider executable realpath changed after authorization"
            )
    except OSError as exc:
        raise ProviderRegistryError(
            f"provider executable disappeared after authorization: {exc}"
        ) from None
    if _sha256_file(executable) != receipt.executable_sha256:
        raise ProviderRegistryError(
            "provider executable bytes changed after authorization"
        )
    if (
        receipt.settings_path is not None
        and receipt.settings_sha256 is not None
        and _sha256_file(Path(receipt.settings_path))
        != receipt.settings_sha256
    ):
        raise ProviderRegistryError(
            "provider settings bytes changed after authorization"
        )
