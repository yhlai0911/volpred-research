"""Primary-authority-fenced worker for durable external effects.

The worker owns the full claim → authorize → provider → settle sequence.  Its
public interface is deliberately one ``run_once`` method; provider selection,
payload storage, Primary Authority, and PostgreSQL are injected at internal
seams so tests exercise the same orchestration as production.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from volpred.ops.authority import PrimaryLease

from ._effect import EffectAttemptOutcome, EffectView, FailedEffect
from .postgres import (
    EffectAttemptReceipt,
    EffectOutboxLease,
    EffectSettlementAuthority,
)

_RECEIPT_SCHEMA = "effect-worker-receipt.v1"
_AUTHORITY_SCHEMA = "effect-authority-request.v1"
_EFFECT_AUTHORITY_KEY = "operations-core-effects"
_SHA256 = frozenset("0123456789abcdef")


class _EffectOutboxStore(Protocol):
    def claim_outbox(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
    ) -> EffectOutboxLease | None: ...

    def inspect(self, effect_id: str) -> EffectView: ...

    def settle_outbox(
        self,
        *,
        lease: EffectOutboxLease,
        outcome: EffectAttemptOutcome,
        authority: EffectSettlementAuthority,
    ) -> EffectAttemptReceipt: ...


class EffectPayloadReader(Protocol):
    """Read the immutable raw bytes named by an EffectRequest."""

    def read(self, payload_ref: str) -> bytes: ...


class EffectProvider(Protocol):
    """Execute one typed effect and return provider/read-back evidence."""

    def deliver(
        self,
        effect: EffectView,
        payload: bytes,
    ) -> EffectAttemptOutcome: ...


class _PrimaryLeaseGate(Protocol):
    """Expose the live host lease only while its keepalive gate is open."""

    def current_lease(self) -> PrimaryLease: ...


@dataclass(frozen=True)
class EffectWorkerCommand:
    worker_id: str
    lease_seconds: int


@dataclass(frozen=True)
class EffectAuthorityRequest:
    request_sha256: str
    effect_id: str
    effect_request_sha256: str
    work_item_id: str
    work_item_version: int
    outbox_sequence: int
    outbox_attempt_count: int
    outbox_claim_token: str
    outbox_claim_expires_at: str
    worker_id: str
    primary_authority_key: str
    primary_authority_holder_ref: str
    primary_authority_epoch: int
    primary_fencing_token: str
    effect_kind: str
    target_ref: str
    payload_ref: str
    payload_sha256: str
    acknowledgement_kind: str
    acknowledgement_target_ref: str


@dataclass(frozen=True)
class EffectAuthorityGrant:
    request_sha256: str
    outbox_claim_ref: str
    primary_authority_ref: str


class EffectAuthority(Protocol):
    """Verify the live outbox claim and Primary Authority fencing token."""

    def authorize(self, request: EffectAuthorityRequest) -> EffectAuthorityGrant: ...


@dataclass(frozen=True)
class EffectWorkerReceipt:
    """Token-redacted result returned after durable settlement read-back."""

    schema_version: str
    effect_id: str
    outbox_sequence: int
    attempt_count: int
    worker_id: str
    authority_request_sha256: str
    outbox_claim_ref: str
    primary_authority_ref: str
    reported_outcome: str
    disposition: str
    evidence_ref: str
    evidence_sha256: str
    recorded_at: str


class EffectWorkerBlocked(RuntimeError):
    """The worker refused an external write or could not verify settlement."""


class EffectOutboxWorker:
    """Run one authority-fenced durable effect attempt."""

    def __init__(
        self,
        *,
        delivery: _EffectOutboxStore,
        authority: EffectAuthority,
        primary_authority: _PrimaryLeaseGate,
        payload_reader: EffectPayloadReader,
        provider: EffectProvider,
    ) -> None:
        self._delivery = delivery
        self._authority = authority
        self._primary_authority = primary_authority
        self._payload_reader = payload_reader
        self._provider = provider

    def run_once(
        self,
        command: EffectWorkerCommand,
    ) -> EffectWorkerReceipt | None:
        normalized = _normalize_command(command)
        primary_lease = self._current_primary_lease()
        lease = self._delivery.claim_outbox(
            worker_id=normalized.worker_id,
            lease_seconds=normalized.lease_seconds,
        )
        if lease is None:
            return None

        effect = self._delivery.inspect(lease.effect_id)
        if effect.id != lease.effect_id:
            raise EffectWorkerBlocked(
                "effect store returned a request for a different outbox claim"
            )
        primary_lease = self._current_primary_lease(
            expected=primary_lease,
        )
        authority_request = _authority_request(
            command=normalized,
            primary_lease=primary_lease,
            lease=lease,
            effect=effect,
        )
        try:
            authority_grant = self._authority.authorize(authority_request)
        except EffectWorkerBlocked:
            raise
        except Exception as exc:
            raise EffectWorkerBlocked(
                "Primary Authority could not authorize the effect"
            ) from exc
        authority_grant = _validate_authority_grant(
            authority_grant,
            request=authority_request,
        )
        self._current_primary_lease(expected=primary_lease)

        try:
            payload = self._payload_reader.read(effect.payload_ref)
            if not isinstance(payload, bytes):
                raise TypeError("effect payload reader returned non-bytes")
        except Exception:  # noqa: BLE001 - adapter errors become typed outcomes.
            outcome: EffectAttemptOutcome = _worker_failure(
                effect,
                reason_code="effect_payload_unavailable",
                retryable=True,
            )
        else:
            if hashlib.sha256(payload).hexdigest() != effect.payload_sha256:
                outcome = _worker_failure(
                    effect,
                    reason_code="effect_payload_integrity_mismatch",
                    retryable=False,
                )
            else:
                try:
                    outcome = self._provider.deliver(effect, payload)
                except Exception:  # noqa: BLE001 - adapter errors become evidence.
                    outcome = _worker_failure(
                        effect,
                        reason_code="effect_provider_error",
                        retryable=True,
                    )

        authority_evidence = EffectSettlementAuthority(
            request_sha256=authority_grant.request_sha256,
            outbox_claim_ref=authority_grant.outbox_claim_ref,
            primary_authority_ref=authority_grant.primary_authority_ref,
        )
        receipt = self._delivery.settle_outbox(
            lease=lease,
            outcome=outcome,
            authority=authority_evidence,
        )
        return _verified_receipt(
            receipt,
            lease=lease,
            grant=authority_grant,
        )

    def _current_primary_lease(
        self,
        *,
        expected: PrimaryLease | None = None,
    ) -> PrimaryLease:
        try:
            observed = _normalize_primary_lease(
                self._primary_authority.current_lease()
            )
        except EffectWorkerBlocked:
            raise
        except Exception as exc:
            raise EffectWorkerBlocked(
                "Primary Authority keepalive gate is not active"
            ) from exc
        if observed.authority_key != _EFFECT_AUTHORITY_KEY:
            raise EffectWorkerBlocked(
                "Primary Authority keepalive gate returned the wrong "
                "effect authority"
            )
        if (
            expected is not None
            and _primary_lease_identity(observed)
            != _primary_lease_identity(expected)
        ):
            raise EffectWorkerBlocked(
                "Primary Authority keepalive gate changed during the "
                "effect attempt"
            )
        return observed


class FileEffectPayloadReader:
    """Read ``file:<repo-relative-path>`` refs without path traversal."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve(strict=True)
        if not self._root.is_dir():
            raise ValueError("effect payload root must be a directory")

    def read(self, payload_ref: str) -> bytes:
        prefix = "file:"
        if not isinstance(payload_ref, str) or not payload_ref.startswith(prefix):
            raise ValueError("effect payload_ref must use file:")
        raw_path = payload_ref.removeprefix(prefix)
        path = PurePosixPath(raw_path)
        if (
            not raw_path
            or path.is_absolute()
            or raw_path != path.as_posix()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("effect payload_ref must be one normalized relative file")
        candidate = (self._root / Path(*path.parts)).resolve(strict=True)
        if not candidate.is_file() or not candidate.is_relative_to(self._root):
            raise ValueError("effect payload_ref escapes its configured root")
        return candidate.read_bytes()


def _normalize_command(command: EffectWorkerCommand) -> EffectWorkerCommand:
    if not isinstance(command, EffectWorkerCommand):
        raise TypeError("effect worker command is required")
    worker_id = _required_text(command.worker_id, field="effect worker_id")
    if (
        isinstance(command.lease_seconds, bool)
        or not isinstance(command.lease_seconds, int)
        or command.lease_seconds <= 0
    ):
        raise ValueError("effect worker lease_seconds must be positive")
    return EffectWorkerCommand(
        worker_id=worker_id,
        lease_seconds=command.lease_seconds,
    )


def _authority_request(
    *,
    command: EffectWorkerCommand,
    primary_lease: PrimaryLease,
    lease: EffectOutboxLease,
    effect: EffectView,
) -> EffectAuthorityRequest:
    payload = {
        "schema_version": _AUTHORITY_SCHEMA,
        "effect_id": effect.id,
        "effect_request_sha256": effect.request_sha256,
        "work_item_id": effect.work_item_id,
        "work_item_version": effect.work_item_version,
        "outbox_sequence": lease.sequence,
        "outbox_attempt_count": lease.attempt_count,
        "outbox_claim_token": lease.token,
        "outbox_claim_expires_at": lease.expires_at,
        "worker_id": command.worker_id,
        "primary_authority_key": primary_lease.authority_key,
        "primary_authority_holder_ref": primary_lease.holder_ref,
        "primary_authority_epoch": primary_lease.epoch,
        "primary_fencing_token": primary_lease.fencing_token,
        "effect_kind": effect.effect_kind,
        "target_ref": effect.target_ref,
        "payload_ref": effect.payload_ref,
        "payload_sha256": effect.payload_sha256,
        "acknowledgement_kind": effect.acknowledgement.kind,
        "acknowledgement_target_ref": effect.acknowledgement.target_ref,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return EffectAuthorityRequest(
        request_sha256=hashlib.sha256(encoded).hexdigest(),
        effect_id=effect.id,
        effect_request_sha256=effect.request_sha256,
        work_item_id=effect.work_item_id,
        work_item_version=effect.work_item_version,
        outbox_sequence=lease.sequence,
        outbox_attempt_count=lease.attempt_count,
        outbox_claim_token=lease.token,
        outbox_claim_expires_at=lease.expires_at,
        worker_id=command.worker_id,
        primary_authority_key=primary_lease.authority_key,
        primary_authority_holder_ref=primary_lease.holder_ref,
        primary_authority_epoch=primary_lease.epoch,
        primary_fencing_token=primary_lease.fencing_token,
        effect_kind=effect.effect_kind,
        target_ref=effect.target_ref,
        payload_ref=effect.payload_ref,
        payload_sha256=effect.payload_sha256,
        acknowledgement_kind=effect.acknowledgement.kind,
        acknowledgement_target_ref=effect.acknowledgement.target_ref,
    )


def _normalize_primary_lease(lease: PrimaryLease) -> PrimaryLease:
    if not isinstance(lease, PrimaryLease):
        raise EffectWorkerBlocked(
            "Primary Authority keepalive gate returned an invalid lease"
        )
    if (
        isinstance(lease.epoch, bool)
        or not isinstance(lease.epoch, int)
        or lease.epoch <= 0
    ):
        raise EffectWorkerBlocked(
            "Primary Authority keepalive gate returned an invalid epoch"
        )
    if (
        isinstance(lease.lease_seconds, bool)
        or not isinstance(lease.lease_seconds, int)
        or lease.lease_seconds <= 0
    ):
        raise EffectWorkerBlocked(
            "Primary Authority keepalive gate returned an invalid duration"
        )
    try:
        return PrimaryLease(
            schema_version=_required_text(
                lease.schema_version,
                field="PrimaryLease schema_version",
            ),
            authority_key=_required_text(
                lease.authority_key,
                field="Primary Authority key",
            ),
            holder_ref=_required_text(
                lease.holder_ref,
                field="Primary Authority holder_ref",
            ),
            epoch=lease.epoch,
            fencing_token=_required_text(
                lease.fencing_token,
                field="Primary Authority fencing token",
            ),
            lease_seconds=lease.lease_seconds,
            acquired_at=_required_text(
                lease.acquired_at,
                field="Primary Authority acquired_at",
            ),
            expires_at=_required_text(
                lease.expires_at,
                field="Primary Authority expires_at",
            ),
        )
    except (TypeError, ValueError) as exc:
        raise EffectWorkerBlocked(
            "Primary Authority keepalive gate returned an invalid lease"
        ) from exc


def _primary_lease_identity(lease: PrimaryLease) -> tuple[object, ...]:
    return (
        lease.schema_version,
        lease.authority_key,
        lease.holder_ref,
        lease.epoch,
        lease.fencing_token,
        lease.lease_seconds,
        lease.acquired_at,
    )


def _validate_authority_grant(
    grant: EffectAuthorityGrant,
    *,
    request: EffectAuthorityRequest,
) -> EffectAuthorityGrant:
    try:
        if grant.request_sha256 != request.request_sha256:
            raise EffectWorkerBlocked(
                "Primary Authority grant does not match the effect write intent"
            )
        return EffectAuthorityGrant(
            request_sha256=_required_sha256(
                grant.request_sha256,
                field="authority request_sha256",
            ),
            outbox_claim_ref=_required_text(
                grant.outbox_claim_ref,
                field="authority outbox claim reference",
            ),
            primary_authority_ref=_required_text(
                grant.primary_authority_ref,
                field="Primary Authority reference",
            ),
        )
    except EffectWorkerBlocked:
        raise
    except (AttributeError, TypeError, ValueError) as exc:
        raise EffectWorkerBlocked(
            "Primary Authority returned an invalid effect grant"
        ) from exc


def _verified_receipt(
    receipt: EffectAttemptReceipt,
    *,
    lease: EffectOutboxLease,
    grant: EffectAuthorityGrant,
) -> EffectWorkerReceipt:
    expected = (
        lease.effect_id,
        lease.sequence,
        lease.attempt_count,
        lease.claimed_by,
        grant.request_sha256,
        grant.outbox_claim_ref,
        grant.primary_authority_ref,
    )
    observed = (
        receipt.effect_id,
        receipt.outbox_sequence,
        receipt.attempt_count,
        receipt.worker_id,
        receipt.authority_request_sha256,
        receipt.outbox_claim_ref,
        receipt.primary_authority_ref,
    )
    if observed != expected:
        raise EffectWorkerBlocked(
            "durable effect settlement read-back does not match its fenced attempt"
        )
    return EffectWorkerReceipt(
        schema_version=_RECEIPT_SCHEMA,
        effect_id=receipt.effect_id,
        outbox_sequence=receipt.outbox_sequence,
        attempt_count=receipt.attempt_count,
        worker_id=receipt.worker_id,
        authority_request_sha256=grant.request_sha256,
        outbox_claim_ref=grant.outbox_claim_ref,
        primary_authority_ref=grant.primary_authority_ref,
        reported_outcome=receipt.reported_outcome,
        disposition=receipt.disposition,
        evidence_ref=receipt.evidence_ref,
        evidence_sha256=receipt.evidence_sha256,
        recorded_at=receipt.recorded_at,
    )


def _worker_failure(
    effect: EffectView,
    *,
    reason_code: str,
    retryable: bool,
) -> FailedEffect:
    evidence = json.dumps(
        {
            "effect_id": effect.id,
            "request_sha256": effect.request_sha256,
            "reason_code": reason_code,
            "retryable": retryable,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return FailedEffect(
        reason_code=reason_code,
        evidence_ref=f"effect-attempt:{effect.id}:{reason_code}",
        evidence_sha256=hashlib.sha256(evidence).hexdigest(),
        retryable=retryable,
    )


def _required_text(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be text")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _required_sha256(value: str, *, field: str) -> str:
    normalized = _required_text(value, field=field)
    if len(normalized) != 64 or any(
        character not in _SHA256 for character in normalized
    ):
        raise ValueError(f"{field} must be lowercase SHA-256")
    return normalized


__all__ = [
    "EffectAuthority",
    "EffectAuthorityGrant",
    "EffectAuthorityRequest",
    "EffectOutboxWorker",
    "EffectPayloadReader",
    "EffectProvider",
    "EffectWorkerBlocked",
    "EffectWorkerCommand",
    "EffectWorkerReceipt",
    "FileEffectPayloadReader",
]
