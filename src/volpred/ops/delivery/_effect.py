"""Immutable EffectRequest and delivery-attempt outcome contracts.

This module owns payload-bound request identity plus the typed evidence a
worker may return after an external attempt. Provider execution, durable
outbox state, retry policy, and acknowledgement verification remain hidden
behind delivery adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from threading import RLock
from typing import Callable


_SCHEMA_VERSION = "effect-request.v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SUPPORTED_RISKS = frozenset({"safe", "sensitive", "destructive"})


@dataclass(frozen=True)
class AcknowledgementExpectation:
    """Typed downstream read-back expected after an effect is delivered."""

    kind: str
    target_ref: str


@dataclass(frozen=True)
class EffectRequest:
    idempotency_key: str
    work_item_id: str
    work_item_version: int
    effect_kind: str
    target_ref: str
    payload_ref: str
    payload_sha256: str
    risk: str
    acknowledgement: AcknowledgementExpectation
    requester_ref: str


@dataclass(frozen=True)
class AcknowledgedEffect:
    """Evidence that the request's typed downstream read-back succeeded."""

    acknowledgement: AcknowledgementExpectation
    evidence_ref: str
    evidence_sha256: str


@dataclass(frozen=True)
class FailedEffect:
    """Evidence that one provider attempt failed.

    ``retryable`` is provider classification, not retry policy. The delivery
    implementation owns backoff, attempt limits, and dead-letter disposition.
    """

    reason_code: str
    evidence_ref: str
    evidence_sha256: str
    retryable: bool


EffectAttemptOutcome = AcknowledgedEffect | FailedEffect


@dataclass(frozen=True)
class EffectView:
    schema_version: str
    id: str
    idempotency_key: str
    work_item_id: str
    work_item_version: int
    effect_kind: str
    target_ref: str
    payload_ref: str
    payload_sha256: str
    risk: str
    acknowledgement: AcknowledgementExpectation
    requester_ref: str
    request_sha256: str
    status: str
    created_at: str


class EffectRequestConflict(ValueError):
    """An idempotency key was replayed with a different request payload."""


class EffectDelivery:
    """Retain immutable effect intents without performing external writes.

    ``request`` is concurrency-safe within this shadow process. A replay with
    the same normalized payload returns the original EffectView; a reused key
    with any semantic drift fails closed. Durable adapters preserve this
    contract while adding outbox ownership and attempt settlement.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        id_factory: Callable[[], str],
    ) -> None:
        self._clock = clock
        self._id_factory = id_factory
        self._lock = RLock()
        self._by_id: dict[str, EffectView] = {}
        self._id_by_idempotency_key: dict[str, str] = {}

    def request(self, request: EffectRequest) -> EffectView:
        normalized = _normalize_request(request)
        request_sha256 = _request_sha256(normalized)

        with self._lock:
            existing_id = self._id_by_idempotency_key.get(
                normalized.idempotency_key
            )
            if existing_id is not None:
                existing = self._by_id[existing_id]
                if existing.request_sha256 != request_sha256:
                    raise EffectRequestConflict(
                        "EffectRequest idempotency key conflicts with its "
                        "original payload"
                    )
                return existing

            observed_at = self._clock()
            if observed_at.tzinfo is None:
                raise ValueError(
                    "EffectRequest clock must return a timezone-aware value"
                )
            effect_id = _required_text(
                self._id_factory(),
                field="EffectRequest id",
            )
            if effect_id in self._by_id:
                raise ValueError(f"duplicate EffectRequest id: {effect_id}")

            view = EffectView(
                schema_version=_SCHEMA_VERSION,
                id=effect_id,
                idempotency_key=normalized.idempotency_key,
                work_item_id=normalized.work_item_id,
                work_item_version=normalized.work_item_version,
                effect_kind=normalized.effect_kind,
                target_ref=normalized.target_ref,
                payload_ref=normalized.payload_ref,
                payload_sha256=normalized.payload_sha256,
                risk=normalized.risk,
                acknowledgement=normalized.acknowledgement,
                requester_ref=normalized.requester_ref,
                request_sha256=request_sha256,
                status="requested",
                created_at=observed_at.isoformat(),
            )
            self._by_id[view.id] = view
            self._id_by_idempotency_key[view.idempotency_key] = view.id
            return view

    def inspect(self, effect_id: str) -> EffectView:
        normalized_id = _required_text(effect_id, field="EffectRequest id")
        with self._lock:
            try:
                return self._by_id[normalized_id]
            except KeyError as exc:
                raise ValueError(
                    f"unknown EffectRequest: {normalized_id}"
                ) from exc


def _required_text(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _normalize_request(request: EffectRequest) -> EffectRequest:
    if (
        isinstance(request.work_item_version, bool)
        or not isinstance(request.work_item_version, int)
        or request.work_item_version <= 0
    ):
        raise ValueError("work_item_version must be positive")
    if (
        not isinstance(request.payload_sha256, str)
        or _SHA256.fullmatch(request.payload_sha256) is None
    ):
        raise ValueError(
            "payload_sha256 must be 64 lowercase hexadecimal characters"
        )
    risk = _required_text(request.risk, field="risk")
    if risk not in _SUPPORTED_RISKS:
        raise ValueError(f"unsupported effect risk: {risk!r}")
    if not isinstance(request.acknowledgement, AcknowledgementExpectation):
        raise ValueError("acknowledgement expectation is required")

    acknowledgement = AcknowledgementExpectation(
        kind=_required_text(
            request.acknowledgement.kind,
            field="acknowledgement kind",
        ),
        target_ref=_required_text(
            request.acknowledgement.target_ref,
            field="acknowledgement target_ref",
        ),
    )
    return EffectRequest(
        idempotency_key=_required_text(
            request.idempotency_key,
            field="idempotency_key",
        ),
        work_item_id=_required_text(request.work_item_id, field="work_item_id"),
        work_item_version=request.work_item_version,
        effect_kind=_required_text(request.effect_kind, field="effect_kind"),
        target_ref=_required_text(request.target_ref, field="target_ref"),
        payload_ref=_required_text(request.payload_ref, field="payload_ref"),
        payload_sha256=request.payload_sha256,
        risk=risk,
        acknowledgement=acknowledgement,
        requester_ref=_required_text(
            request.requester_ref,
            field="requester_ref",
        ),
    )


def _normalize_attempt_outcome(
    outcome: EffectAttemptOutcome,
) -> EffectAttemptOutcome:
    if isinstance(outcome, AcknowledgedEffect):
        if not isinstance(
            outcome.acknowledgement,
            AcknowledgementExpectation,
        ):
            raise ValueError("acknowledgement expectation is required")
        acknowledgement = AcknowledgementExpectation(
            kind=_required_text(
                outcome.acknowledgement.kind,
                field="acknowledgement kind",
            ),
            target_ref=_required_text(
                outcome.acknowledgement.target_ref,
                field="acknowledgement target_ref",
            ),
        )
        return AcknowledgedEffect(
            acknowledgement=acknowledgement,
            evidence_ref=_required_text(
                outcome.evidence_ref,
                field="effect attempt evidence_ref",
            ),
            evidence_sha256=_normalize_sha256(
                outcome.evidence_sha256,
                field="effect attempt evidence_sha256",
            ),
        )
    if isinstance(outcome, FailedEffect):
        if not isinstance(outcome.retryable, bool):
            raise ValueError("effect failure retryable must be boolean")
        return FailedEffect(
            reason_code=_required_text(
                outcome.reason_code,
                field="effect failure reason_code",
            ),
            evidence_ref=_required_text(
                outcome.evidence_ref,
                field="effect attempt evidence_ref",
            ),
            evidence_sha256=_normalize_sha256(
                outcome.evidence_sha256,
                field="effect attempt evidence_sha256",
            ),
            retryable=outcome.retryable,
        )
    raise ValueError("unsupported effect attempt outcome")


def _normalize_sha256(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(
            f"{field} must be 64 lowercase hexadecimal characters"
        )
    return value


def _request_sha256(request: EffectRequest) -> str:
    encoded = json.dumps(
        {
            "schema_version": _SCHEMA_VERSION,
            "idempotency_key": request.idempotency_key,
            "work_item_id": request.work_item_id,
            "work_item_version": request.work_item_version,
            "effect_kind": request.effect_kind,
            "target_ref": request.target_ref,
            "payload_ref": request.payload_ref,
            "payload_sha256": request.payload_sha256,
            "risk": request.risk,
            "acknowledgement": {
                "kind": request.acknowledgement.kind,
                "target_ref": request.acknowledgement.target_ref,
            },
            "requester_ref": request.requester_ref,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "AcknowledgedEffect",
    "AcknowledgementExpectation",
    "EffectAttemptOutcome",
    "EffectDelivery",
    "EffectRequest",
    "EffectRequestConflict",
    "EffectView",
    "FailedEffect",
]
