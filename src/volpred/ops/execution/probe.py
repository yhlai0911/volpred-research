"""Durable, bounded capability probes for zero-paid provider identities.

This module owns probe admission and evidence only.  It never selects a
provider for business work, resumes a task, or grants formal-effect authority.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from volpred.ops.diagnostics import warn

from .probe_policy import ProbePolicy
from .registry import (
    DEFAULT_REGISTRY_PATH,
    ProviderProbeAuthorization,
    ProviderRegistryError,
    authorize_provider_probe,
)

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_LEDGER_PATH = ROOT / "storage" / "ops" / "provider_probe_ledger.json"
_SCHEMA = "provider-probe-ledger.v1"
_TOP_FIELDS = frozenset(
    {
        "schema_version",
        "reservations",
        "receipts",
        "policy_denials",
        "integrity_sha256",
    }
)
_RESERVATION_FIELDS = frozenset(
    {
        "token",
        "provider_id",
        "model_id",
        "executable_realpath",
        "executable_sha256",
        "auth_surface",
        "registry_sha256",
        "cost_units",
        "minimum_interval_seconds",
        "maximum_backoff_seconds",
        "window_seconds",
        "max_probe_cost_units",
        "reservation_ttl_seconds",
        "reserved_at",
        "expires_at",
    }
)
_RECEIPT_FIELDS = frozenset(
    {
        "receipt_id",
        "provider_id",
        "model_id",
        "executable_realpath",
        "executable_sha256",
        "auth_surface",
        "registry_sha256",
        "cost_units",
        "outcome",
        "evidence_ref",
        "observed_at",
        "consecutive_failures",
        "next_probe_at",
        "previous_receipt_sha256",
        "receipt_sha256",
    }
)
_DENIAL_FIELDS = frozenset(
    {
        "denial_id",
        "provider_id",
        "model_id",
        "requested_executable",
        "registry_sha256",
        "outcome",
        "evidence_ref",
        "observed_at",
        "previous_denial_sha256",
        "denial_sha256",
    }
)
_ALLOWED_AUTH_SURFACES = frozenset(
    {"subscription_oauth", "desktop_subscription"}
)


class ProbePolicyError(RuntimeError):
    """Probe admission or durable evidence violated the probe contract."""


class ProbeOutcome(StrEnum):
    HEALTHY = "healthy"
    QUOTA_BLOCKED = "quota_blocked"
    AUTH_BLOCKED = "auth_blocked"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    POLICY_DENIED = "policy_denied"


class ProbeAdmission(StrEnum):
    ACQUIRED = "acquired"
    PROBE_IN_PROGRESS = "probe_in_progress"
    MINIMUM_INTERVAL = "minimum_interval"
    BACKOFF = "backoff"
    BUDGET_EXHAUSTED = "budget_exhausted"
    POLICY_DENIED = "policy_denied"


@dataclass(frozen=True)
class ProbeReservation:
    token: str
    provider_id: str
    model_id: str
    executable_realpath: str
    executable_sha256: str
    auth_surface: str
    registry_sha256: str
    cost_units: int
    minimum_interval_seconds: int
    maximum_backoff_seconds: int
    window_seconds: int
    max_probe_cost_units: int
    reservation_ttl_seconds: int
    reserved_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class ProbeReceipt:
    receipt_id: str
    provider_id: str
    model_id: str
    executable_realpath: str
    executable_sha256: str
    auth_surface: str
    registry_sha256: str
    cost_units: int
    outcome: ProbeOutcome
    evidence_ref: str
    observed_at: datetime
    consecutive_failures: int
    next_probe_at: datetime
    previous_receipt_sha256: str | None
    receipt_sha256: str


@dataclass(frozen=True)
class ProbePolicyDenialReceipt:
    denial_id: str
    provider_id: str
    model_id: str
    requested_executable: str
    registry_sha256: str | None
    outcome: ProbeOutcome
    evidence_ref: str
    observed_at: datetime
    previous_denial_sha256: str | None
    denial_sha256: str


@dataclass(frozen=True)
class ProbeDecision:
    acquired: bool
    reason: str
    registry_sha256: str | None
    next_probe_at: datetime | None
    reservation: ProbeReservation | None = None

    @property
    def token(self) -> str:
        if self.reservation is None:
            raise ProbePolicyError("probe decision has no reservation token")
        return self.reservation.token


@dataclass(frozen=True)
class ProbeObservation:
    outcome: ProbeOutcome
    evidence_ref: str


@dataclass(frozen=True)
class ProbeRunResult:
    admission: ProbeAdmission
    outcome: ProbeOutcome | None
    provider_io_attempted: bool
    reason: str
    receipt: ProbeReceipt | ProbePolicyDenialReceipt | None
    next_probe_at: datetime | None


@dataclass(frozen=True)
class ProviderProbeState:
    provider_id: str
    outcome: ProbeOutcome
    observed_at: datetime
    consecutive_failures: int
    next_probe_at: datetime
    registry_sha256: str


def _utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProbePolicyError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _parse_time(value: object, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise ProbePolicyError(f"{label} must be an ISO-8601 string")
    try:
        return _utc(datetime.fromisoformat(value), label=label)
    except ValueError:
        raise ProbePolicyError(f"{label} is not valid ISO-8601") from None


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _normalized(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _empty_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": _SCHEMA,
        "reservations": [],
        "receipts": [],
        "policy_denials": [],
    }
    payload["integrity_sha256"] = _sha(payload)
    return payload


def _payload_with_integrity(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "schema_version": payload["schema_version"],
        "reservations": payload["reservations"],
        "receipts": payload["receipts"],
        "policy_denials": payload["policy_denials"],
    }
    result["integrity_sha256"] = _sha(result)
    return result


def _reservation_to_record(value: ProbeReservation) -> dict[str, Any]:
    record = asdict(value)
    record["reserved_at"] = value.reserved_at.isoformat()
    record["expires_at"] = value.expires_at.isoformat()
    return record


def _reservation_from_record(value: object) -> ProbeReservation:
    if not isinstance(value, Mapping) or set(value) != _RESERVATION_FIELDS:
        raise ProbePolicyError("provider probe ledger reservation schema drift")
    try:
        reservation = ProbeReservation(
            token=str(value["token"]),
            provider_id=str(value["provider_id"]),
            model_id=str(value["model_id"]),
            executable_realpath=str(value["executable_realpath"]),
            executable_sha256=str(value["executable_sha256"]),
            auth_surface=str(value["auth_surface"]),
            registry_sha256=str(value["registry_sha256"]),
            cost_units=int(value["cost_units"]),
            minimum_interval_seconds=int(value["minimum_interval_seconds"]),
            maximum_backoff_seconds=int(value["maximum_backoff_seconds"]),
            window_seconds=int(value["window_seconds"]),
            max_probe_cost_units=int(value["max_probe_cost_units"]),
            reservation_ttl_seconds=int(value["reservation_ttl_seconds"]),
            reserved_at=_parse_time(value["reserved_at"], label="reserved_at"),
            expires_at=_parse_time(value["expires_at"], label="expires_at"),
        )
    except (TypeError, ValueError):
        raise ProbePolicyError("provider probe ledger reservation is invalid") from None
    if (
        not all(
            _normalized(item)
            for item in (
                reservation.token,
                reservation.provider_id,
                reservation.model_id,
                reservation.executable_realpath,
            )
        )
        or not Path(reservation.executable_realpath).is_absolute()
        or not _is_sha256(reservation.executable_sha256)
        or not _is_sha256(reservation.registry_sha256)
        or reservation.auth_surface not in _ALLOWED_AUTH_SURFACES
        or reservation.cost_units <= 0
        or reservation.minimum_interval_seconds <= 0
        or reservation.maximum_backoff_seconds
        < reservation.minimum_interval_seconds
        or reservation.window_seconds <= 0
        or reservation.max_probe_cost_units <= 0
        or reservation.reservation_ttl_seconds <= 0
        or reservation.reservation_ttl_seconds
        > reservation.minimum_interval_seconds
        or reservation.expires_at <= reservation.reserved_at
    ):
        raise ProbePolicyError("provider probe ledger reservation fields are invalid")
    return reservation


def _receipt_core(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in _RECEIPT_FIELDS - {"receipt_sha256"}}


def _receipt_to_record(value: ProbeReceipt) -> dict[str, Any]:
    record = asdict(value)
    record["outcome"] = value.outcome.value
    record["observed_at"] = value.observed_at.isoformat()
    record["next_probe_at"] = value.next_probe_at.isoformat()
    return record


def _receipt_from_record(value: object) -> ProbeReceipt:
    if not isinstance(value, Mapping) or set(value) != _RECEIPT_FIELDS:
        raise ProbePolicyError("provider probe ledger receipt schema drift")
    if _sha(_receipt_core(value)) != value["receipt_sha256"]:
        raise ProbePolicyError("provider probe receipt hash mismatch")
    try:
        outcome = ProbeOutcome(str(value["outcome"]))
        receipt = ProbeReceipt(
            receipt_id=str(value["receipt_id"]),
            provider_id=str(value["provider_id"]),
            model_id=str(value["model_id"]),
            executable_realpath=str(value["executable_realpath"]),
            executable_sha256=str(value["executable_sha256"]),
            auth_surface=str(value["auth_surface"]),
            registry_sha256=str(value["registry_sha256"]),
            cost_units=int(value["cost_units"]),
            outcome=outcome,
            evidence_ref=str(value["evidence_ref"]),
            observed_at=_parse_time(value["observed_at"], label="observed_at"),
            consecutive_failures=int(value["consecutive_failures"]),
            next_probe_at=_parse_time(
                value["next_probe_at"], label="next_probe_at"
            ),
            previous_receipt_sha256=(
                str(value["previous_receipt_sha256"])
                if value["previous_receipt_sha256"] is not None
                else None
            ),
            receipt_sha256=str(value["receipt_sha256"]),
        )
    except (TypeError, ValueError):
        raise ProbePolicyError("provider probe ledger receipt is invalid") from None
    if (
        not receipt.receipt_id
        or not receipt.provider_id
        or not receipt.model_id
        or not receipt.evidence_ref
        or not Path(receipt.executable_realpath).is_absolute()
        or not _is_sha256(receipt.executable_sha256)
        or not _is_sha256(receipt.registry_sha256)
        or receipt.auth_surface not in _ALLOWED_AUTH_SURFACES
        or receipt.cost_units <= 0
        or receipt.consecutive_failures < 0
        or receipt.next_probe_at < receipt.observed_at
        or (
            receipt.outcome is ProbeOutcome.HEALTHY
            and receipt.consecutive_failures != 0
        )
        or (
            receipt.outcome is not ProbeOutcome.HEALTHY
            and receipt.consecutive_failures <= 0
        )
        or (
            receipt.previous_receipt_sha256 is not None
            and not _is_sha256(receipt.previous_receipt_sha256)
        )
    ):
        raise ProbePolicyError("provider probe ledger receipt fields are invalid")
    return receipt


def _denial_core(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in _DENIAL_FIELDS - {"denial_sha256"}}


def _denial_from_record(value: object) -> ProbePolicyDenialReceipt:
    if not isinstance(value, Mapping) or set(value) != _DENIAL_FIELDS:
        raise ProbePolicyError("provider probe policy-denial schema drift")
    if _sha(_denial_core(value)) != value["denial_sha256"]:
        raise ProbePolicyError("provider probe policy-denial hash mismatch")
    try:
        denial = ProbePolicyDenialReceipt(
            denial_id=str(value["denial_id"]),
            provider_id=str(value["provider_id"]),
            model_id=str(value["model_id"]),
            requested_executable=str(value["requested_executable"]),
            registry_sha256=(
                str(value["registry_sha256"])
                if value["registry_sha256"] is not None
                else None
            ),
            outcome=ProbeOutcome(str(value["outcome"])),
            evidence_ref=str(value["evidence_ref"]),
            observed_at=_parse_time(value["observed_at"], label="observed_at"),
            previous_denial_sha256=(
                str(value["previous_denial_sha256"])
                if value["previous_denial_sha256"] is not None
                else None
            ),
            denial_sha256=str(value["denial_sha256"]),
        )
    except (TypeError, ValueError):
        raise ProbePolicyError(
            "provider probe policy-denial receipt is invalid"
        ) from None
    if (
        denial.outcome is not ProbeOutcome.POLICY_DENIED
        or not all(
            _normalized(item)
            for item in (
                denial.denial_id,
                denial.provider_id,
                denial.model_id,
                denial.requested_executable,
                denial.evidence_ref,
            )
        )
        or (
            denial.registry_sha256 is not None
            and not _is_sha256(denial.registry_sha256)
        )
        or (
            denial.previous_denial_sha256 is not None
            and not _is_sha256(denial.previous_denial_sha256)
        )
    ):
        raise ProbePolicyError(
            "provider probe policy-denial fields are invalid"
        )
    return denial


def _validate_payload(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _TOP_FIELDS:
        raise ProbePolicyError("provider probe ledger schema drift")
    if value["schema_version"] != _SCHEMA:
        raise ProbePolicyError("provider probe ledger version is unsupported")
    unsigned = {
        "schema_version": value["schema_version"],
        "reservations": value["reservations"],
        "receipts": value["receipts"],
        "policy_denials": value["policy_denials"],
    }
    if _sha(unsigned) != value["integrity_sha256"]:
        raise ProbePolicyError("provider probe ledger integrity hash mismatch")
    if not all(
        isinstance(value[field], list)
        for field in ("reservations", "receipts", "policy_denials")
    ):
        raise ProbePolicyError("provider probe ledger collections are invalid")
    reservations = [
        _reservation_from_record(item) for item in value["reservations"]
    ]
    receipts = [_receipt_from_record(item) for item in value["receipts"]]
    denials = [
        _denial_from_record(item) for item in value["policy_denials"]
    ]
    tokens = [item.token for item in reservations]
    if len(tokens) != len(set(tokens)):
        raise ProbePolicyError("provider probe reservation tokens are duplicated")
    previous: str | None = None
    for receipt in receipts:
        if receipt.previous_receipt_sha256 != previous:
            raise ProbePolicyError("provider probe receipt chain is broken")
        previous = receipt.receipt_sha256
    previous_denial: str | None = None
    for denial in denials:
        if denial.previous_denial_sha256 != previous_denial:
            raise ProbePolicyError(
                "provider probe policy-denial chain is broken"
            )
        previous_denial = denial.denial_sha256
    return {
        "schema_version": _SCHEMA,
        "reservations": [_reservation_to_record(item) for item in reservations],
        "receipts": [_receipt_to_record(item) for item in receipts],
        "policy_denials": [dict(item) for item in value["policy_denials"]],
        "integrity_sha256": value["integrity_sha256"],
    }


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_canonical(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:  # silent-ok: os.replace consumed the temp path
            pass


class DurableProviderProbeLedger:
    """Cross-process probe admission with a hash-bound atomic JSON ledger."""

    def __init__(
        self,
        *,
        path: Path = DEFAULT_LEDGER_PATH,
        registry_path: Path = DEFAULT_REGISTRY_PATH,
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self.path = path
        self.registry_path = registry_path
        self._clock = clock or (lambda: datetime.now(UTC))
        self._token_factory = token_factory or (lambda: uuid4().hex)

    @property
    def _lock_path(self) -> Path:
        return self.path.with_suffix(f"{self.path.suffix}.lock")

    def _now(self) -> datetime:
        return _utc(self._clock(), label="probe clock")

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_payload()
        try:
            return _validate_payload(json.loads(self.path.read_bytes()))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProbePolicyError(
                f"provider probe ledger is unreadable: {exc}"
            ) from None

    def _locked(self):
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._lock_path.open("a+b")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle

    @staticmethod
    def _latest(
        receipts: list[ProbeReceipt],
        provider_id: str,
    ) -> ProbeReceipt | None:
        matches = [item for item in receipts if item.provider_id == provider_id]
        return matches[-1] if matches else None

    def _reserve(
        self,
        *,
        provider_id: str,
        model_id: str,
        executable_path: str,
        environment: Mapping[str, str],
    ) -> ProbeDecision:
        authorization = authorize_provider_probe(
            provider_id=provider_id,
            model_id=model_id,
            executable_path=executable_path,
            environment=environment,
            path=self.registry_path,
        )
        now = self._now()
        lock = self._locked()
        try:
            payload = self._read()
            reservations = [
                _reservation_from_record(item)
                for item in payload["reservations"]
            ]
            receipts = [
                _receipt_from_record(item) for item in payload["receipts"]
            ]
            active = [
                item
                for item in reservations
                if item.provider_id == provider_id and item.expires_at > now
            ]
            if active:
                return ProbeDecision(
                    acquired=False,
                    reason="probe_in_progress",
                    registry_sha256=authorization.registry_sha256,
                    next_probe_at=min(item.expires_at for item in active),
                )
            latest = self._latest(receipts, provider_id)
            if latest is not None and now < latest.next_probe_at:
                return ProbeDecision(
                    acquired=False,
                    reason=(
                        "minimum_interval"
                        if latest.outcome is ProbeOutcome.HEALTHY
                        else "backoff"
                    ),
                    registry_sha256=authorization.registry_sha256,
                    next_probe_at=latest.next_probe_at,
                )
            policy = ProbePolicy.from_seconds(
                minimum_interval_seconds=authorization.minimum_interval_seconds,
                maximum_backoff_seconds=authorization.maximum_backoff_seconds,
                window_seconds=authorization.window_seconds,
                max_probe_cost_units=authorization.max_probe_cost_units,
                reservation_ttl_seconds=authorization.reservation_ttl_seconds,
            )
            budget_next = policy.budget_next_at(
                now=now,
                requested_cost_units=authorization.cost_units,
                events=[
                    (item.observed_at, item.cost_units) for item in receipts
                ]
                + [
                    (item.reserved_at, item.cost_units)
                    for item in reservations
                ],
            )
            if budget_next is not None:
                return ProbeDecision(
                    acquired=False,
                    reason="budget_exhausted",
                    registry_sha256=authorization.registry_sha256,
                    next_probe_at=budget_next,
                )
            token = self._token_factory()
            if not token or any(item.token == token for item in reservations):
                raise ProbePolicyError(
                    "probe reservation token is empty or duplicated"
                )
            reservation = self._new_reservation(
                authorization=authorization,
                token=token,
                now=now,
            )
            payload["reservations"].append(
                _reservation_to_record(reservation)
            )
            _atomic_write(self.path, _payload_with_integrity(payload))
            return ProbeDecision(
                acquired=True,
                reason="acquired",
                registry_sha256=authorization.registry_sha256,
                next_probe_at=reservation.expires_at,
                reservation=reservation,
            )
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()

    @staticmethod
    def _new_reservation(
        *,
        authorization: ProviderProbeAuthorization,
        token: str,
        now: datetime,
    ) -> ProbeReservation:
        return ProbeReservation(
            token=token,
            provider_id=authorization.provider_id,
            model_id=authorization.model_id,
            executable_realpath=authorization.resolved_executable,
            executable_sha256=authorization.executable_sha256,
            auth_surface=authorization.auth_surface,
            registry_sha256=authorization.registry_sha256,
            cost_units=authorization.cost_units,
            minimum_interval_seconds=authorization.minimum_interval_seconds,
            maximum_backoff_seconds=authorization.maximum_backoff_seconds,
            window_seconds=authorization.window_seconds,
            max_probe_cost_units=authorization.max_probe_cost_units,
            reservation_ttl_seconds=authorization.reservation_ttl_seconds,
            reserved_at=now,
            expires_at=now
            + timedelta(seconds=authorization.reservation_ttl_seconds),
        )

    def _settle(
        self,
        *,
        token: str,
        outcome: ProbeOutcome,
        evidence_ref: str,
    ) -> ProbeReceipt:
        if not isinstance(outcome, ProbeOutcome):
            raise ProbePolicyError("probe outcome must use ProbeOutcome")
        if not evidence_ref or evidence_ref != evidence_ref.strip():
            raise ProbePolicyError("probe evidence_ref is required")
        now = self._now()
        lock = self._locked()
        try:
            payload = self._read()
            reservations = [
                _reservation_from_record(item)
                for item in payload["reservations"]
            ]
            matches = [item for item in reservations if item.token == token]
            if len(matches) != 1:
                raise ProbePolicyError("probe reservation is missing")
            reservation = matches[0]
            if now >= reservation.expires_at:
                raise ProbePolicyError("probe reservation expired before settlement")
            newer = [
                item
                for item in reservations
                if item.provider_id == reservation.provider_id
                and item.reserved_at > reservation.reserved_at
            ]
            if newer:
                raise ProbePolicyError("probe reservation was superseded")
            receipts = [
                _receipt_from_record(item) for item in payload["receipts"]
            ]
            latest = self._latest(receipts, reservation.provider_id)
            failures = (
                0
                if outcome is ProbeOutcome.HEALTHY
                else (latest.consecutive_failures if latest else 0) + 1
            )
            policy = ProbePolicy.from_seconds(
                minimum_interval_seconds=reservation.minimum_interval_seconds,
                maximum_backoff_seconds=reservation.maximum_backoff_seconds,
                window_seconds=reservation.window_seconds,
                max_probe_cost_units=reservation.max_probe_cost_units,
                reservation_ttl_seconds=reservation.reservation_ttl_seconds,
            )
            delay = policy.backoff_delay(failures)
            previous_hash = (
                receipts[-1].receipt_sha256 if receipts else None
            )
            core = {
                "receipt_id": uuid4().hex,
                "provider_id": reservation.provider_id,
                "model_id": reservation.model_id,
                "executable_realpath": reservation.executable_realpath,
                "executable_sha256": reservation.executable_sha256,
                "auth_surface": reservation.auth_surface,
                "registry_sha256": reservation.registry_sha256,
                "cost_units": reservation.cost_units,
                "outcome": outcome.value,
                "evidence_ref": evidence_ref,
                "observed_at": now.isoformat(),
                "consecutive_failures": failures,
                "next_probe_at": (
                    now + delay
                ).isoformat(),
                "previous_receipt_sha256": previous_hash,
            }
            record = {**core, "receipt_sha256": _sha(core)}
            receipt = _receipt_from_record(record)
            payload["receipts"].append(record)
            payload["reservations"] = [
                item for item in payload["reservations"] if item["token"] != token
            ]
            _atomic_write(self.path, _payload_with_integrity(payload))
            return receipt
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()

    def receipts(self) -> tuple[ProbeReceipt, ...]:
        lock = self._locked()
        try:
            payload = self._read()
            return tuple(
                _receipt_from_record(item) for item in payload["receipts"]
            )
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()

    def provider_state(self, provider_id: str) -> ProviderProbeState:
        receipts = list(self.receipts())
        latest = self._latest(receipts, provider_id)
        if latest is None:
            raise ProbePolicyError(
                f"provider {provider_id!r} has no durable probe receipt"
            )
        return ProviderProbeState(
            provider_id=provider_id,
            outcome=latest.outcome,
            observed_at=latest.observed_at,
            consecutive_failures=latest.consecutive_failures,
            next_probe_at=latest.next_probe_at,
            registry_sha256=latest.registry_sha256,
        )

    def policy_denials(self) -> tuple[ProbePolicyDenialReceipt, ...]:
        lock = self._locked()
        try:
            payload = self._read()
            return tuple(
                _denial_from_record(item)
                for item in payload["policy_denials"]
            )
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()

    def _record_policy_denial(
        self,
        *,
        provider_id: str,
        model_id: str,
        executable_path: str,
        evidence_ref: str,
    ) -> ProbePolicyDenialReceipt:
        now = self._now()
        try:
            registry_sha256 = hashlib.sha256(
                self.registry_path.read_bytes()
            ).hexdigest()
        except OSError as exc:
            warn(
                "provider-probe",
                "registry bytes unavailable while recording policy denial",
                path=str(self.registry_path),
                error=type(exc).__name__,
            )
            registry_sha256 = None
        lock = self._locked()
        try:
            payload = self._read()
            denials = [
                _denial_from_record(item)
                for item in payload["policy_denials"]
            ]
            requested_executable = (
                executable_path
                if _normalized(executable_path)
                else "<invalid>"
            )
            normalized_provider = (
                provider_id if _normalized(provider_id) else "<invalid>"
            )
            normalized_model = (
                model_id if _normalized(model_id) else "<invalid>"
            )
            if denials:
                previous = denials[-1]
                if (
                    previous.provider_id == normalized_provider
                    and previous.model_id == normalized_model
                    and previous.requested_executable == requested_executable
                    and previous.registry_sha256 == registry_sha256
                    and previous.evidence_ref == evidence_ref
                ):
                    return previous
            core = {
                "denial_id": uuid4().hex,
                "provider_id": normalized_provider,
                "model_id": normalized_model,
                "requested_executable": requested_executable,
                "registry_sha256": registry_sha256,
                "outcome": ProbeOutcome.POLICY_DENIED.value,
                "evidence_ref": evidence_ref,
                "observed_at": now.isoformat(),
                "previous_denial_sha256": (
                    denials[-1].denial_sha256 if denials else None
                ),
            }
            record = {**core, "denial_sha256": _sha(core)}
            denial = _denial_from_record(record)
            payload["policy_denials"].append(record)
            _atomic_write(self.path, _payload_with_integrity(payload))
            return denial
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()

    def run(
        self,
        *,
        provider_id: str,
        model_id: str,
        executable_path: str,
        environment: Mapping[str, str],
        perform_probe: Callable[[ProbeReservation], ProbeObservation],
    ) -> ProbeRunResult:
        try:
            decision = self._reserve(
                provider_id=provider_id,
                model_id=model_id,
                executable_path=executable_path,
                environment=environment,
            )
        except ProviderRegistryError as exc:
            error_fingerprint = hashlib.sha256(str(exc).encode()).hexdigest()[:16]
            denial = self._record_policy_denial(
                provider_id=provider_id,
                model_id=model_id,
                executable_path=executable_path,
                evidence_ref=(
                    f"probe://policy/denied/{type(exc).__name__}/"
                    f"{error_fingerprint}"
                ),
            )
            return ProbeRunResult(
                admission=ProbeAdmission.POLICY_DENIED,
                outcome=ProbeOutcome.POLICY_DENIED,
                provider_io_attempted=False,
                reason=f"policy_denied:{exc}",
                receipt=denial,
                next_probe_at=None,
            )
        if not decision.acquired:
            return ProbeRunResult(
                admission=ProbeAdmission(decision.reason),
                outcome=None,
                provider_io_attempted=False,
                reason=decision.reason,
                receipt=None,
                next_probe_at=decision.next_probe_at,
            )
        reservation = decision.reservation
        assert reservation is not None
        try:
            current = authorize_provider_probe(
                provider_id=provider_id,
                model_id=model_id,
                executable_path=executable_path,
                environment=environment,
                path=self.registry_path,
            )
            identity = (
                current.registry_sha256,
                current.resolved_executable,
                current.executable_sha256,
                current.cost_units,
            )
            reserved_identity = (
                reservation.registry_sha256,
                reservation.executable_realpath,
                reservation.executable_sha256,
                reservation.cost_units,
            )
            if identity != reserved_identity:
                receipt = self._settle(
                    token=reservation.token,
                    outcome=ProbeOutcome.POLICY_DENIED,
                    evidence_ref="probe://policy/changed-after-reservation",
                )
                return ProbeRunResult(
                    admission=ProbeAdmission.ACQUIRED,
                    outcome=receipt.outcome,
                    provider_io_attempted=False,
                    reason="policy_changed_after_reservation",
                    receipt=receipt,
                    next_probe_at=receipt.next_probe_at,
                )
            try:
                observation = perform_probe(reservation)
            except Exception as exc:  # noqa: BLE001 - typed adapter boundary
                receipt = self._settle(
                    token=reservation.token,
                    outcome=ProbeOutcome.PROVIDER_UNAVAILABLE,
                    evidence_ref=f"probe://adapter/error/{type(exc).__name__}",
                )
                return ProbeRunResult(
                    admission=ProbeAdmission.ACQUIRED,
                    outcome=receipt.outcome,
                    provider_io_attempted=True,
                    reason=f"probe_adapter_error:{type(exc).__name__}",
                    receipt=receipt,
                    next_probe_at=receipt.next_probe_at,
                )
            if not isinstance(observation, ProbeObservation):
                receipt = self._settle(
                    token=reservation.token,
                    outcome=ProbeOutcome.POLICY_DENIED,
                    evidence_ref="probe://adapter/invalid-observation",
                )
                return ProbeRunResult(
                    admission=ProbeAdmission.ACQUIRED,
                    outcome=receipt.outcome,
                    provider_io_attempted=True,
                    reason="probe_adapter_contract_violation",
                    receipt=receipt,
                    next_probe_at=receipt.next_probe_at,
                )
            receipt = self._settle(
                token=reservation.token,
                outcome=observation.outcome,
                evidence_ref=observation.evidence_ref,
            )
            return ProbeRunResult(
                admission=ProbeAdmission.ACQUIRED,
                outcome=receipt.outcome,
                provider_io_attempted=True,
                reason="settled",
                receipt=receipt,
                next_probe_at=receipt.next_probe_at,
            )
        except ProviderRegistryError as exc:
            receipt = self._settle(
                token=reservation.token,
                outcome=ProbeOutcome.POLICY_DENIED,
                evidence_ref=f"probe://policy/denied/{type(exc).__name__}",
            )
            return ProbeRunResult(
                admission=ProbeAdmission.ACQUIRED,
                outcome=receipt.outcome,
                provider_io_attempted=False,
                reason=f"policy_denied:{exc}",
                receipt=receipt,
                next_probe_at=receipt.next_probe_at,
            )
