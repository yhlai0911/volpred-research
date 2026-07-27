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
import math
import re
from threading import RLock
from typing import Callable, Iterable, Protocol
from uuid import uuid4

from volpred.diagnostics import warn

from .registry import (
    ProviderRegistry as ProviderRegistry,
    ProviderRegistryError as ProviderRegistryError,
    ProviderSpawnReceipt as ProviderSpawnReceipt,
    RegisteredProvider as RegisteredProvider,
    authorize_provider_spawn as authorize_provider_spawn,
    load_provider_registry as load_provider_registry,
    verify_spawn_receipt as verify_spawn_receipt,
)


class BlockerKind(str, Enum):
    QUOTA = "quota"
    AUTH = "auth"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    POLICY_DENIAL = "policy_denial"
    EXECUTION_IN_PROGRESS = "execution_in_progress"


def _aware(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include a real timezone offset")
    return value.astimezone(timezone.utc)


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
    probe_reservation_ttl: timedelta = timedelta(minutes=2)

    def __post_init__(self) -> None:
        if self.minimum_interval <= timedelta(0):
            raise ValueError("minimum probe interval must be positive")
        if self.maximum_backoff < self.minimum_interval:
            raise ValueError("maximum probe backoff must cover the minimum interval")
        if self.window <= timedelta(0) or self.max_probe_cost_units <= 0:
            raise ValueError("probe window and cost budget must be positive")
        if self.probe_reservation_ttl <= timedelta(0):
            raise ValueError("probe reservation TTL must be positive")


@dataclass(frozen=True)
class ProviderObservation:
    provider_id: str
    observed_at: datetime
    blocker: BlockerKind | None
    evidence_ref: str

    def __post_init__(self) -> None:
        _aware(self.observed_at, field="provider observation timestamp")
        if not self.evidence_ref:
            raise ValueError("provider observation requires evidence")
        if self.blocker is not None and not isinstance(self.blocker, BlockerKind):
            raise ValueError("provider observation blocker must be a BlockerKind")


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
        "checkpointed",
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
    checkpoint: VerifiedExecutionCheckpoint | None = None

    def __post_init__(self) -> None:
        if self.kind not in _ATTEMPT_KINDS:
            raise ValueError(f"unsupported execution attempt kind: {self.kind!r}")
        if not self.evidence_ref:
            raise ValueError("execution attempt evidence is required")
        if self.blocker is not None and not isinstance(self.blocker, BlockerKind):
            raise ValueError("execution attempt blocker must be a BlockerKind")
        if (self.kind == "blocked") != (self.blocker is not None):
            raise ValueError("only blocked attempts carry a typed blocker")
        if self.kind not in {"blocked", "terminal_failure"} and not self.result_ref:
            raise ValueError(f"{self.kind} attempt requires a result reference")
        if (self.kind == "checkpointed") != (self.checkpoint is not None):
            raise ValueError(
                "only checkpointed attempts carry a verified checkpoint"
            )
        if (
            self.kind == "checkpointed"
            and self.checkpoint is not None
            and self.result_ref != self.checkpoint.artifact_ref
        ):
            raise ValueError(
                "checkpoint result_ref must exactly match its verified artifact_ref"
            )


@dataclass(frozen=True)
class ExecutionOutcome:
    kind: str
    work_id: str
    provider_id: str | None
    result_ref: str | None
    blocker: BlockerKind | None
    evidence_refs: tuple[str, ...]
    resume_checkpoint_id: str | None
    checkpoint: VerifiedExecutionCheckpoint | None = None


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


@dataclass(frozen=True)
class ExecutionReservation:
    acquired: bool
    replay: ExecutionOutcome | None = None


@dataclass(frozen=True)
class ProbeReservation:
    acquired: bool
    state: ProviderStateView
    usable_without_probe: bool = False


class ProviderExecutionStore(Protocol):
    def reserve_execution(
        self,
        *,
        key: str,
        fingerprint: str,
        owner: str,
        observed_at: datetime,
    ) -> ExecutionReservation: ...

    def settle_execution(
        self, *, key: str, owner: str, outcome: ExecutionOutcome
    ) -> None: ...

    def release_execution(self, *, key: str, owner: str) -> None: ...

    def recover_execution(
        self,
        *,
        key: str,
        expected_owner: str,
        liveness_evidence_ref: str,
    ) -> None: ...

    def reserve_probe(
        self,
        *,
        provider_id: str,
        owner: str,
        observed_at: datetime,
        cost_units: int,
        policy: ProbePolicy,
    ) -> ProbeReservation: ...

    def settle_probe(
        self,
        *,
        provider_id: str,
        owner: str,
        observation: ProviderObservation,
        policy: ProbePolicy,
    ) -> ProviderStateView: ...

    def release_probe(self, *, provider_id: str, owner: str) -> None: ...

    def observe(
        self,
        *,
        observation: ProviderObservation,
        observed_now: datetime,
        policy: ProbePolicy,
    ) -> ProviderStateView: ...


class _InMemoryProviderExecutionStore:
    """Deterministic reference store; production stores implement the same rules."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._request_fingerprints: dict[str, str] = {}
        self._terminal_outcomes: dict[str, ExecutionOutcome] = {}
        self._execution_reservations: dict[str, str] = {}
        self._provider_states: dict[str, ProviderStateView] = {}
        self._probe_reservations: dict[str, tuple[str, datetime, datetime]] = {}

    def reserve_execution(
        self,
        *,
        key: str,
        fingerprint: str,
        owner: str,
        observed_at: datetime,
    ) -> ExecutionReservation:
        with self._lock:
            _aware(observed_at, field="execution reservation clock")
            previous = self._request_fingerprints.setdefault(key, fingerprint)
            if previous != fingerprint:
                raise ValueError("idempotency key is already bound to another request")
            replay = self._terminal_outcomes.get(key)
            if replay is not None:
                return ExecutionReservation(acquired=False, replay=replay)
            reservation = self._execution_reservations.get(key)
            if reservation is not None:
                return ExecutionReservation(acquired=False)
            self._execution_reservations[key] = owner
            return ExecutionReservation(acquired=True)

    def settle_execution(
        self, *, key: str, owner: str, outcome: ExecutionOutcome
    ) -> None:
        with self._lock:
            reservation = self._execution_reservations.get(key)
            if reservation is None or reservation != owner:
                raise RuntimeError("execution reservation was lost before settlement")
            previous = self._terminal_outcomes.setdefault(key, outcome)
            if previous != outcome:
                raise RuntimeError("terminal provider outcome conflicts with durable replay")
            self._execution_reservations.pop(key, None)

    def release_execution(self, *, key: str, owner: str) -> None:
        with self._lock:
            reservation = self._execution_reservations.get(key)
            if reservation is not None and reservation == owner:
                self._execution_reservations.pop(key, None)

    def recover_execution(
        self,
        *,
        key: str,
        expected_owner: str,
        liveness_evidence_ref: str,
    ) -> None:
        if not liveness_evidence_ref:
            raise ValueError("execution recovery requires liveness evidence")
        with self._lock:
            reservation = self._execution_reservations.get(key)
            if reservation is None:
                return
            if reservation != expected_owner:
                raise RuntimeError("execution recovery owner does not match")
            self._execution_reservations.pop(key, None)

    def reserve_probe(
        self,
        *,
        provider_id: str,
        owner: str,
        observed_at: datetime,
        cost_units: int,
        policy: ProbePolicy,
    ) -> ProbeReservation:
        with self._lock:
            previous = self._provider_states.get(provider_id)
            if previous is not None and observed_at < previous.observed_at:
                raise ValueError("probe clock is older than provider state")
            reservation = self._probe_reservations.get(provider_id)
            expired_reservation = False
            if reservation is not None and reservation[1] <= observed_at:
                self._probe_reservations.pop(provider_id, None)
                reservation = None
                expired_reservation = True
            if reservation is not None:
                state = previous or _unknown_provider_state(provider_id, observed_at)
                return ProbeReservation(acquired=False, state=state)
            if (
                not expired_reservation
                and previous is not None
                and observed_at < previous.next_probe_at
            ):
                return ProbeReservation(
                    acquired=False,
                    state=previous,
                    usable_without_probe=True,
                )
            used = 0
            window_started_at = observed_at
            if (
                previous is not None
                and observed_at - previous.probe_window_started_at < policy.window
            ):
                used = previous.probe_cost_used
                window_started_at = previous.probe_window_started_at
            if used + cost_units > policy.max_probe_cost_units:
                state = previous or _unknown_provider_state(provider_id, observed_at)
                return ProbeReservation(acquired=False, state=state)
            provisional = ProviderStateView(
                provider_id=provider_id,
                blocker=(
                    previous.blocker
                    if previous is not None
                    else BlockerKind.PROVIDER_UNAVAILABLE
                ),
                observed_at=observed_at,
                evidence_ref=(
                    previous.evidence_ref
                    if previous is not None
                    else f"probe://{provider_id}/reserved"
                ),
                consecutive_failures=(
                    previous.consecutive_failures if previous is not None else 0
                ),
                next_probe_at=observed_at + policy.minimum_interval,
                probe_window_started_at=window_started_at,
                probe_cost_used=used + cost_units,
            )
            self._provider_states[provider_id] = provisional
            self._probe_reservations[provider_id] = (
                owner,
                observed_at + policy.probe_reservation_ttl,
                observed_at,
            )
            return ProbeReservation(acquired=True, state=provisional)

    def settle_probe(
        self,
        *,
        provider_id: str,
        owner: str,
        observation: ProviderObservation,
        policy: ProbePolicy,
    ) -> ProviderStateView:
        with self._lock:
            reservation = self._probe_reservations.get(provider_id)
            if reservation is None or reservation[0] != owner:
                raise RuntimeError("probe reservation was lost before settlement")
            try:
                return self._observe_locked(
                    observation=observation,
                    observed_now=reservation[2],
                    policy=policy,
                )
            finally:
                self._probe_reservations.pop(provider_id, None)

    def release_probe(self, *, provider_id: str, owner: str) -> None:
        with self._lock:
            reservation = self._probe_reservations.get(provider_id)
            if reservation is not None and reservation[0] == owner:
                self._probe_reservations.pop(provider_id, None)

    def observe(
        self,
        *,
        observation: ProviderObservation,
        observed_now: datetime,
        policy: ProbePolicy,
    ) -> ProviderStateView:
        with self._lock:
            return self._observe_locked(
                observation=observation,
                observed_now=observed_now,
                policy=policy,
            )

    def _observe_locked(
        self,
        *,
        observation: ProviderObservation,
        observed_now: datetime,
        policy: ProbePolicy,
    ) -> ProviderStateView:
        observed_at = _aware(
            observation.observed_at, field="provider observation timestamp"
        )
        now = _aware(observed_now, field="provider observation clock")
        if observed_at > now + timedelta(seconds=5):
            raise ValueError("provider observation is implausibly in the future")
        previous = self._provider_states.get(observation.provider_id)
        if previous is not None and observed_at < previous.observed_at:
            raise ValueError("provider observation is older than current state")
        window_started_at = (
            previous.probe_window_started_at if previous else observed_at
        )
        cost = previous.probe_cost_used if previous else 0
        if observed_at - window_started_at >= policy.window:
            window_started_at = observed_at
            cost = 0
        failures = (
            0
            if observation.blocker is None
            else (previous.consecutive_failures if previous else 0) + 1
        )
        exponent = max(0, failures - 1)
        ratio = (
            policy.maximum_backoff.total_seconds()
            / policy.minimum_interval.total_seconds()
        )
        saturation_exponent = max(0, math.ceil(math.log2(ratio)))
        delay = (
            policy.maximum_backoff
            if exponent >= saturation_exponent
            else policy.minimum_interval * (2**exponent)
        )
        state = ProviderStateView(
            provider_id=observation.provider_id,
            blocker=observation.blocker,
            observed_at=observed_at,
            evidence_ref=observation.evidence_ref,
            consecutive_failures=failures,
            next_probe_at=observed_at + delay,
            probe_window_started_at=window_started_at,
            probe_cost_used=cost,
        )
        self._provider_states[observation.provider_id] = state
        return state


def _unknown_provider_state(
    provider_id: str,
    observed_at: datetime,
) -> ProviderStateView:
    return ProviderStateView(
        provider_id=provider_id,
        blocker=BlockerKind.PROVIDER_UNAVAILABLE,
        observed_at=observed_at,
        evidence_ref=f"probe://{provider_id}/unavailable",
        consecutive_failures=0,
        next_probe_at=observed_at,
        probe_window_started_at=observed_at,
        probe_cost_used=0,
    )


class ProviderExecution:
    """Select, probe, and execute zero-paid providers without formal write power."""

    _ALLOWED_AUTH_SURFACES = frozenset(
        {"subscription_oauth", "desktop_subscription"}
    )

    def __init__(
        self,
        *,
        providers: Iterable[tuple[ProviderDescriptor, ProviderAdapter]],
        store: ProviderExecutionStore,
        clock: Callable[[], datetime],
        probe_policy: ProbePolicy | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._providers = tuple(providers)
        self._store = store
        self._clock = clock
        self._probe_policy = probe_policy or ProbePolicy()
        self._token_factory = token_factory or (lambda: uuid4().hex)
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

    def observe(self, observation: ProviderObservation) -> ProviderStateView:
        known_ids = {
            descriptor.provider_id for descriptor, _adapter in self._providers
        }
        if observation.provider_id not in known_ids:
            raise ValueError("observation names an unknown provider")
        return self._store.observe(
            observation=observation,
            observed_now=_aware(self._clock(), field="provider execution clock"),
            policy=self._probe_policy,
        )

    def execute(self, request: ExecutionRequest) -> ExecutionOutcome:
        fingerprint = _request_fingerprint(request)
        now = _aware(self._clock(), field="provider execution clock")
        # Startup validation is not enough: a long-lived process may observe a
        # config reload or adapter registry drift. Re-run the zero-paid guard at
        # every dispatch before any reservation, probe, or provider I/O.
        for descriptor, _adapter in self._providers:
            self._validate_descriptor(descriptor)
        owner = self._token_factory()
        if not owner:
            raise ValueError("provider execution reservation token is required")
        reservation = self._store.reserve_execution(
            key=request.idempotency_key,
            fingerprint=fingerprint,
            owner=owner,
            observed_at=now,
        )
        if reservation.replay is not None:
            return reservation.replay
        if not reservation.acquired:
            return self._blocked(
                request,
                BlockerKind.EXECUTION_IN_PROGRESS,
                evidence_refs=("execution://reservation/in-progress",),
            )
        candidates = tuple(
            (descriptor, adapter)
            for descriptor, adapter in self._providers
            if descriptor.enabled
            and request.semantic_class in descriptor.semantic_classes
            and request.required_capabilities <= descriptor.capabilities
            and request.required_attestations <= descriptor.attestations
        )
        if not candidates:
            outcome = self._blocked(
                request,
                BlockerKind.POLICY_DENIAL,
                evidence_refs=("policy://no-semantically-equivalent-provider",),
            )
            self._store.release_execution(key=request.idempotency_key, owner=owner)
            return outcome

        evidence: list[str] = []
        blockers: list[BlockerKind] = []
        try:
            for descriptor, adapter in candidates:
                probe_owner = self._token_factory()
                probe = self._store.reserve_probe(
                    provider_id=descriptor.provider_id,
                    owner=probe_owner,
                    observed_at=now,
                    cost_units=descriptor.probe_cost_units,
                    policy=self._probe_policy,
                )
                state = probe.state
                if probe.acquired:
                    try:
                        observation = adapter.probe(descriptor, observed_at=now)
                        if not isinstance(observation, ProviderObservation):
                            raise TypeError(
                                "provider probe must return ProviderObservation"
                            )
                        if observation.provider_id != descriptor.provider_id:
                            raise RuntimeError(
                                "provider probe returned the wrong identity"
                            )
                    except Exception as exc:
                        warn(
                            "provider-execution",
                            "provider probe failed; trying an equivalent provider",
                            provider_id=descriptor.provider_id,
                            error_type=type(exc).__name__,
                        )
                        observation = ProviderObservation(
                            provider_id=descriptor.provider_id,
                            observed_at=now,
                            blocker=BlockerKind.PROVIDER_UNAVAILABLE,
                            evidence_ref=(
                                f"provider-exception://{descriptor.provider_id}/"
                                f"{type(exc).__name__}"
                            ),
                        )
                    except BaseException:
                        self._store.release_probe(
                            provider_id=descriptor.provider_id,
                            owner=probe_owner,
                        )
                        raise
                    try:
                        state = self._store.settle_probe(
                            provider_id=descriptor.provider_id,
                            owner=probe_owner,
                            observation=observation,
                            policy=self._probe_policy,
                        )
                    except Exception as exc:
                        warn(
                            "provider-execution",
                            "provider probe evidence violated its contract",
                            provider_id=descriptor.provider_id,
                            error_type=type(exc).__name__,
                        )
                        state = self.observe(
                            ProviderObservation(
                                provider_id=descriptor.provider_id,
                                observed_at=now,
                                blocker=BlockerKind.PROVIDER_UNAVAILABLE,
                                evidence_ref=(
                                    f"provider-contract://"
                                    f"{descriptor.provider_id}/"
                                    f"{type(exc).__name__}"
                                ),
                            )
                        )
                elif not probe.usable_without_probe:
                    evidence.append(
                        f"probe-reservation://{descriptor.provider_id}/unavailable"
                    )
                    blockers.append(BlockerKind.PROVIDER_UNAVAILABLE)
                    continue
                evidence.append(state.evidence_ref)

                if state.blocker is not None:
                    blockers.append(state.blocker)
                    continue

                try:
                    attempt = adapter.execute(
                        request,
                        resume_checkpoint=request.resume_checkpoint,
                    )
                    if not isinstance(attempt, ExecutionAttempt):
                        raise TypeError(
                            "provider execute must return ExecutionAttempt"
                        )
                except Exception as exc:
                    warn(
                        "provider-execution",
                        "provider execution failed; trying an equivalent provider",
                        provider_id=descriptor.provider_id,
                        error_type=type(exc).__name__,
                    )
                    observation = ProviderObservation(
                        provider_id=descriptor.provider_id,
                        observed_at=now,
                        blocker=BlockerKind.PROVIDER_UNAVAILABLE,
                        evidence_ref=(
                            f"provider-exception://{descriptor.provider_id}/"
                            f"{type(exc).__name__}"
                        ),
                    )
                    state = self.observe(observation)
                    evidence.append(state.evidence_ref)
                    blockers.append(BlockerKind.PROVIDER_UNAVAILABLE)
                    continue
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
                    checkpoint=attempt.checkpoint,
                )
                if attempt.kind in _REPLAYABLE_KINDS:
                    self._store.settle_execution(
                        key=request.idempotency_key,
                        owner=owner,
                        outcome=outcome,
                    )
                else:
                    self._store.release_execution(
                        key=request.idempotency_key, owner=owner
                    )
                return outcome

            outcome = self._blocked(
                request,
                blockers[0] if blockers else BlockerKind.PROVIDER_UNAVAILABLE,
                evidence_refs=tuple(evidence),
            )
            self._store.release_execution(key=request.idempotency_key, owner=owner)
            return outcome
        except BaseException:
            self._store.release_execution(key=request.idempotency_key, owner=owner)
            raise

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
    "ProbePolicy",
    "ProviderAdapter",
    "ProviderDescriptor",
    "ProviderExecution",
    "ProviderExecutionStore",
    "ProviderObservation",
    "ProviderStateView",
    "VerifiedExecutionCheckpoint",
]
