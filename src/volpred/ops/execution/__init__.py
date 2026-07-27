"""Zero-paid provider continuity behind one Operations Core seam.

Provider adapters may compute and return immutable candidates, but they never
receive commit, notification, publish, or other formal-effect authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Protocol


class BlockerKind(str, Enum):
    QUOTA = "quota"
    AUTH = "auth"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    POLICY_DENIAL = "policy_denial"


@dataclass(frozen=True)
class VerifiedExecutionCheckpoint:
    checkpoint_id: str
    artifact_ref: str
    artifact_sha256: str
    verification_ref: str

    def __post_init__(self) -> None:
        if not self.checkpoint_id or not self.artifact_ref or not self.verification_ref:
            raise ValueError("verified checkpoint identity and evidence are required")
        if re.fullmatch(r"[0-9a-f]{64}", self.artifact_sha256) is None:
            raise ValueError("verified checkpoint artifact SHA-256 is invalid")


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    semantic_classes: frozenset[str]
    capabilities: frozenset[str]
    attestations: frozenset[str]
    auth_surface: str
    metered_paid: bool
    api_key_env: str | None
    probe_cost_units: int
    enabled: bool = True


@dataclass(frozen=True)
class ProbePolicy:
    minimum_interval: timedelta = timedelta(minutes=5)
    maximum_backoff: timedelta = timedelta(hours=1)
    window: timedelta = timedelta(hours=1)
    max_probe_cost_units: int = 6

    def __post_init__(self) -> None:
        if self.minimum_interval <= timedelta(0):
            raise ValueError("minimum probe interval must be positive")
        if self.maximum_backoff < self.minimum_interval:
            raise ValueError("maximum probe backoff must cover the minimum interval")
        if self.window <= timedelta(0) or self.max_probe_cost_units <= 0:
            raise ValueError("probe window and cost budget must be positive")


@dataclass(frozen=True)
class ProviderObservation:
    provider_id: str
    observed_at: datetime
    blocker: BlockerKind | None
    evidence_ref: str

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("provider observation timestamp must include a timezone")
        if not self.evidence_ref:
            raise ValueError("provider observation requires evidence")


@dataclass(frozen=True)
class ProviderStateView:
    provider_id: str
    blocker: BlockerKind | None
    observed_at: datetime
    evidence_ref: str
    consecutive_failures: int
    next_probe_at: datetime
    probe_window_started_at: datetime
    probe_cost_used: int


@dataclass(frozen=True)
class ExecutionRequest:
    idempotency_key: str
    work_id: str
    semantic_class: str
    required_capabilities: frozenset[str]
    required_attestations: frozenset[str]
    payload_ref: str
    resume_checkpoint: VerifiedExecutionCheckpoint | None = None

    def __post_init__(self) -> None:
        if not all(
            (
                self.idempotency_key,
                self.work_id,
                self.semantic_class,
                self.payload_ref,
            )
        ):
            raise ValueError("execution request identity is incomplete")


_ATTEMPT_KINDS = frozenset(
    {
        "completed",
        "checkpointed",
        "blocked",
        "candidate_change_set",
        "candidate_effect_request",
        "terminal_failure",
    }
)
_REPLAYABLE_KINDS = frozenset(
    {
        "completed",
        "candidate_change_set",
        "candidate_effect_request",
        "terminal_failure",
    }
)


@dataclass(frozen=True)
class ExecutionAttempt:
    kind: str
    result_ref: str | None
    evidence_ref: str
    blocker: BlockerKind | None = None

    def __post_init__(self) -> None:
        if self.kind not in _ATTEMPT_KINDS:
            raise ValueError(f"unsupported execution attempt kind: {self.kind!r}")
        if not self.evidence_ref:
            raise ValueError("execution attempt evidence is required")
        if (self.kind == "blocked") != (self.blocker is not None):
            raise ValueError("only blocked attempts carry a typed blocker")
        if self.kind not in {"blocked", "terminal_failure"} and not self.result_ref:
            raise ValueError(f"{self.kind} attempt requires a result reference")


@dataclass(frozen=True)
class ExecutionOutcome:
    kind: str
    work_id: str
    provider_id: str | None
    result_ref: str | None
    blocker: BlockerKind | None
    evidence_refs: tuple[str, ...]
    resume_checkpoint_id: str | None


class ProviderAdapter(Protocol):
    def probe(
        self,
        descriptor: ProviderDescriptor,
        *,
        observed_at: datetime,
    ) -> ProviderObservation: ...

    def execute(
        self,
        request: ExecutionRequest,
        *,
        resume_checkpoint: VerifiedExecutionCheckpoint | None,
    ) -> ExecutionAttempt: ...


class InMemoryProviderExecutionStore:
    """Deterministic reference store; production stores implement the same rules."""

    def __init__(self) -> None:
        self._request_fingerprints: dict[str, str] = {}
        self._terminal_outcomes: dict[str, ExecutionOutcome] = {}
        self._provider_states: dict[str, ProviderStateView] = {}

    def bind_request(self, key: str, fingerprint: str) -> None:
        previous = self._request_fingerprints.setdefault(key, fingerprint)
        if previous != fingerprint:
            raise ValueError("idempotency key is already bound to another request")

    def terminal_outcome(self, key: str) -> ExecutionOutcome | None:
        return self._terminal_outcomes.get(key)

    def save_terminal(self, key: str, outcome: ExecutionOutcome) -> None:
        previous = self._terminal_outcomes.setdefault(key, outcome)
        if previous != outcome:
            raise RuntimeError("terminal provider outcome conflicts with durable replay")

    def provider_state(self, provider_id: str) -> ProviderStateView | None:
        return self._provider_states.get(provider_id)

    def save_provider_state(self, state: ProviderStateView) -> None:
        self._provider_states[state.provider_id] = state


class ProviderExecution:
    """Select, probe, and execute zero-paid providers without formal write power."""

    _ALLOWED_AUTH_SURFACES = frozenset(
        {"subscription_oauth", "desktop_subscription"}
    )

    def __init__(
        self,
        *,
        providers: Iterable[tuple[ProviderDescriptor, ProviderAdapter]],
        store: InMemoryProviderExecutionStore,
        clock,
        probe_policy: ProbePolicy | None = None,
    ) -> None:
        self._providers = tuple(providers)
        self._store = store
        self._clock = clock
        self._probe_policy = probe_policy or ProbePolicy()
        provider_ids = [descriptor.provider_id for descriptor, _ in self._providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("provider ids must be unique")
        for descriptor, _adapter in self._providers:
            self._validate_descriptor(descriptor)

    @classmethod
    def _validate_descriptor(cls, descriptor: ProviderDescriptor) -> None:
        if not descriptor.provider_id:
            raise ValueError("provider id is required")
        if descriptor.metered_paid:
            raise ValueError("metered-paid providers are forbidden")
        if descriptor.api_key_env is not None:
            raise ValueError("AI API-key providers are forbidden")
        if descriptor.auth_surface not in cls._ALLOWED_AUTH_SURFACES:
            raise ValueError("provider must use an allowlisted subscription/OAuth surface")
        if descriptor.probe_cost_units <= 0:
            raise ValueError("provider probe cost must be positive and bounded")

    def observe(
        self,
        observation: ProviderObservation,
        *,
        _probe_cost_units: int = 0,
    ) -> ProviderStateView:
        known_ids = {
            descriptor.provider_id for descriptor, _adapter in self._providers
        }
        if observation.provider_id not in known_ids:
            raise ValueError("observation names an unknown provider")
        observed_at = observation.observed_at.astimezone(timezone.utc)
        previous = self._store.provider_state(observation.provider_id)
        if (
            previous is None
            or observed_at - previous.probe_window_started_at
            >= self._probe_policy.window
        ):
            window_started_at = observed_at
            prior_cost = 0
        else:
            window_started_at = previous.probe_window_started_at
            prior_cost = previous.probe_cost_used
        descriptor = self._descriptor(observation.provider_id)
        failures = (
            0
            if observation.blocker is None
            else (previous.consecutive_failures if previous else 0) + 1
        )
        multiplier = 1 if failures == 0 else 2 ** (failures - 1)
        delay = min(
            self._probe_policy.minimum_interval * multiplier,
            self._probe_policy.maximum_backoff,
        )
        state = ProviderStateView(
            provider_id=observation.provider_id,
            blocker=observation.blocker,
            observed_at=observed_at,
            evidence_ref=observation.evidence_ref,
            consecutive_failures=failures,
            next_probe_at=observed_at + delay,
            probe_window_started_at=window_started_at,
            probe_cost_used=prior_cost + _probe_cost_units,
        )
        self._store.save_provider_state(state)
        return state

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        fingerprint = _request_fingerprint(request)
        self._store.bind_request(request.idempotency_key, fingerprint)
        replay = self._store.terminal_outcome(request.idempotency_key)
        if replay is not None:
            return replay

        now = self._clock().astimezone(timezone.utc)
        candidates = tuple(
            (descriptor, adapter)
            for descriptor, adapter in self._providers
            if descriptor.enabled
            and request.semantic_class in descriptor.semantic_classes
            and request.required_capabilities <= descriptor.capabilities
            and request.required_attestations <= descriptor.attestations
        )
        if not candidates:
            return self._blocked(
                request,
                BlockerKind.POLICY_DENIAL,
                evidence_refs=("policy://no-semantically-equivalent-provider",),
            )

        evidence: list[str] = []
        blockers: list[BlockerKind] = []
        for descriptor, adapter in candidates:
            state = self._store.provider_state(descriptor.provider_id)
            if state is None or now >= state.next_probe_at:
                if not self._probe_budget_available(descriptor, state, now):
                    blockers.append(
                        state.blocker
                        if state is not None and state.blocker is not None
                        else BlockerKind.PROVIDER_UNAVAILABLE
                    )
                    evidence.append(
                        f"probe-budget://{descriptor.provider_id}/exhausted"
                    )
                    continue
                observation = adapter.probe(descriptor, observed_at=now)
                if observation.provider_id != descriptor.provider_id:
                    raise RuntimeError("provider probe returned the wrong identity")
                state = self.observe(
                    observation,
                    _probe_cost_units=descriptor.probe_cost_units,
                )
                evidence.append(observation.evidence_ref)
            else:
                evidence.append(state.evidence_ref)

            if state.blocker is not None:
                blockers.append(state.blocker)
                continue

            attempt = adapter.execute(
                request,
                resume_checkpoint=request.resume_checkpoint,
            )
            evidence.append(attempt.evidence_ref)
            if attempt.kind == "blocked":
                observation = ProviderObservation(
                    provider_id=descriptor.provider_id,
                    observed_at=now,
                    blocker=attempt.blocker,
                    evidence_ref=attempt.evidence_ref,
                )
                self.observe(observation)
                blockers.append(attempt.blocker)
                continue
            outcome = ExecutionOutcome(
                kind=attempt.kind,
                work_id=request.work_id,
                provider_id=descriptor.provider_id,
                result_ref=attempt.result_ref,
                blocker=None,
                evidence_refs=tuple(evidence),
                resume_checkpoint_id=(
                    request.resume_checkpoint.checkpoint_id
                    if request.resume_checkpoint is not None
                    else None
                ),
            )
            if attempt.kind in _REPLAYABLE_KINDS:
                self._store.save_terminal(request.idempotency_key, outcome)
            return outcome

        return self._blocked(
            request,
            blockers[0] if blockers else BlockerKind.PROVIDER_UNAVAILABLE,
            evidence_refs=tuple(evidence),
        )

    def _probe_budget_available(
        self,
        descriptor: ProviderDescriptor,
        state: ProviderStateView | None,
        now: datetime,
    ) -> bool:
        used = 0
        if (
            state is not None
            and now - state.probe_window_started_at < self._probe_policy.window
        ):
            used = state.probe_cost_used
        return (
            used + descriptor.probe_cost_units
            <= self._probe_policy.max_probe_cost_units
        )

    def _descriptor(self, provider_id: str) -> ProviderDescriptor:
        return next(
            descriptor
            for descriptor, _adapter in self._providers
            if descriptor.provider_id == provider_id
        )

    @staticmethod
    def _blocked(
        request: ExecutionRequest,
        blocker: BlockerKind,
        *,
        evidence_refs: tuple[str, ...],
    ) -> ExecutionOutcome:
        return ExecutionOutcome(
            kind="blocked",
            work_id=request.work_id,
            provider_id=None,
            result_ref=None,
            blocker=blocker,
            evidence_refs=evidence_refs,
            resume_checkpoint_id=(
                request.resume_checkpoint.checkpoint_id
                if request.resume_checkpoint is not None
                else None
            ),
        )


def _request_fingerprint(request: ExecutionRequest) -> str:
    payload = asdict(request)
    payload["required_capabilities"] = sorted(request.required_capabilities)
    payload["required_attestations"] = sorted(request.required_attestations)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "BlockerKind",
    "ExecutionAttempt",
    "ExecutionOutcome",
    "ExecutionRequest",
    "InMemoryProviderExecutionStore",
    "ProbePolicy",
    "ProviderAdapter",
    "ProviderDescriptor",
    "ProviderExecution",
    "ProviderObservation",
    "ProviderStateView",
    "VerifiedExecutionCheckpoint",
]
