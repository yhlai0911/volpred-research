"""Evidence-bound cutover manifests for formal incident/provider owners.

This module prepares immutable evidence only.  Staging and owner mutation are
separate privileged PostgreSQL transactions; preparing a manifest never grants
execution authority and never changes a live owner.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

SCHEMA_VERSION = "formal-owner-cutover-manifest.v1"
MANIFEST_TTL = timedelta(minutes=15)
FORMAL_OWNER_CONTRACTS = {
    "incident.lifecycle": "contract://issue-13/durable-incident-owner",
    "provider.execution": "contract://issue-12/zero-paid-provider-registry",
}
_FIELDS = frozenset(
    {
        "schema_version",
        "capability",
        "contract_ref",
        "source_owner",
        "source_generation",
        "target_owner",
        "parent_work_owner_generation",
        "acceptance_receipt_sha256",
        "regression_receipt_sha256",
        "live_preflight_receipt_sha256",
        "prepared_at",
        "valid_until",
    }
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _positive_integer(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be positive")
    return value


def _digest(value: object, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{label} must be a SHA-256 digest")
    return value


def _timestamp(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be an ISO-8601 timestamp")
    try:
        observed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(
            f"{label} must be an ISO-8601 timestamp"
        ) from None
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return observed.astimezone(UTC).isoformat()


@dataclass(frozen=True)
class FormalOwnerCutoverManifest:
    schema_version: str
    capability: str
    contract_ref: str
    source_owner: str
    source_generation: int
    target_owner: str
    parent_work_owner_generation: int
    acceptance_receipt_sha256: str
    regression_receipt_sha256: str
    live_preflight_receipt_sha256: str
    prepared_at: str
    valid_until: str
    sha256: str

    def identity_dict(self) -> dict[str, str | int]:
        return {
            "schema_version": self.schema_version,
            "capability": self.capability,
            "contract_ref": self.contract_ref,
            "source_owner": self.source_owner,
            "source_generation": self.source_generation,
            "target_owner": self.target_owner,
            "parent_work_owner_generation": (
                self.parent_work_owner_generation
            ),
            "acceptance_receipt_sha256": (
                self.acceptance_receipt_sha256
            ),
            "regression_receipt_sha256": (
                self.regression_receipt_sha256
            ),
            "live_preflight_receipt_sha256": (
                self.live_preflight_receipt_sha256
            ),
            "prepared_at": self.prepared_at,
            "valid_until": self.valid_until,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.identity_dict())

    def as_dict(self) -> dict[str, str | int]:
        return {**self.identity_dict(), "sha256": self.sha256}

    @classmethod
    def from_canonical_bytes(
        cls,
        payload: bytes,
    ) -> FormalOwnerCutoverManifest:
        try:
            decoded = json.loads(payload)
        except (UnicodeError, json.JSONDecodeError):
            raise ValueError(
                "formal owner cutover manifest is not valid JSON"
            ) from None
        if not isinstance(decoded, dict) or set(decoded) != _FIELDS:
            raise ValueError(
                "formal owner cutover manifest has invalid fields"
            )
        capability = decoded.get("capability")
        if capability not in FORMAL_OWNER_CONTRACTS:
            raise ValueError("unsupported capability")
        contract_ref = decoded.get("contract_ref")
        if contract_ref != FORMAL_OWNER_CONTRACTS[capability]:
            raise ValueError("formal owner cutover contract drifted")
        if decoded.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("formal owner cutover schema drifted")
        if decoded.get("source_owner") != "legacy":
            raise ValueError("formal owner cutover source owner is invalid")
        if decoded.get("target_owner") != "operations_core":
            raise ValueError("formal owner cutover target owner is invalid")
        source_generation = _positive_integer(
            decoded.get("source_generation"),
            label="source generation",
        )
        parent_generation = _positive_integer(
            decoded.get("parent_work_owner_generation"),
            label="parent work owner generation",
        )
        acceptance = _digest(
            decoded.get("acceptance_receipt_sha256"),
            label="acceptance receipt",
        )
        regression = _digest(
            decoded.get("regression_receipt_sha256"),
            label="regression receipt",
        )
        preflight = _digest(
            decoded.get("live_preflight_receipt_sha256"),
            label="live preflight receipt",
        )
        prepared_at = _timestamp(
            decoded.get("prepared_at"),
            label="prepared_at",
        )
        valid_until = _timestamp(
            decoded.get("valid_until"),
            label="valid_until",
        )
        if (
            datetime.fromisoformat(valid_until)
            != datetime.fromisoformat(prepared_at) + MANIFEST_TTL
        ):
            raise ValueError(
                "formal owner cutover validity window is invalid"
            )
        canonical = _canonical_bytes(decoded)
        if canonical != payload:
            raise ValueError(
                "formal owner cutover manifest is not canonical"
            )
        return cls(
            schema_version=SCHEMA_VERSION,
            capability=capability,
            contract_ref=contract_ref,
            source_owner="legacy",
            source_generation=source_generation,
            target_owner="operations_core",
            parent_work_owner_generation=parent_generation,
            acceptance_receipt_sha256=acceptance,
            regression_receipt_sha256=regression,
            live_preflight_receipt_sha256=preflight,
            prepared_at=prepared_at,
            valid_until=valid_until,
            sha256=_sha256(payload),
        )


def _evidence_digest(payload: bytes, *, label: str) -> str:
    if not isinstance(payload, bytes) or not payload:
        raise ValueError(f"{label} is required")
    return _sha256(payload)


def prepare_formal_owner_cutover(
    *,
    capability: str,
    source_owner: str,
    source_generation: int,
    parent_work_owner_generation: int,
    acceptance_receipt: bytes,
    regression_receipt: bytes,
    live_preflight_receipt: bytes,
    prepared_at: datetime | None = None,
) -> FormalOwnerCutoverManifest:
    """Bind exact acceptance, regression and live-preflight evidence bytes."""

    if capability not in FORMAL_OWNER_CONTRACTS:
        raise ValueError("unsupported capability")
    if source_owner != "legacy":
        raise ValueError("source owner must be legacy")
    source_generation = _positive_integer(
        source_generation,
        label="source generation",
    )
    parent_work_owner_generation = _positive_integer(
        parent_work_owner_generation,
        label="parent work owner generation",
    )
    instant = prepared_at or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("prepared_at must include a UTC offset")
    instant = instant.astimezone(UTC)
    manifest = FormalOwnerCutoverManifest(
        schema_version=SCHEMA_VERSION,
        capability=capability,
        contract_ref=FORMAL_OWNER_CONTRACTS[capability],
        source_owner=source_owner,
        source_generation=source_generation,
        target_owner="operations_core",
        parent_work_owner_generation=parent_work_owner_generation,
        acceptance_receipt_sha256=_evidence_digest(
            acceptance_receipt,
            label="acceptance receipt",
        ),
        regression_receipt_sha256=_evidence_digest(
            regression_receipt,
            label="regression receipt",
        ),
        live_preflight_receipt_sha256=_evidence_digest(
            live_preflight_receipt,
            label="live preflight receipt",
        ),
        prepared_at=instant.isoformat(),
        valid_until=(instant + MANIFEST_TTL).isoformat(),
        sha256="",
    )
    return replace(
        manifest,
        sha256=_sha256(manifest.canonical_bytes()),
    )


__all__ = [
    "FORMAL_OWNER_CONTRACTS",
    "FormalOwnerCutoverManifest",
    "prepare_formal_owner_cutover",
]
