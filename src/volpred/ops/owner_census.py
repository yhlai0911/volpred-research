"""Fail-closed ownership census for formal Operations Core capabilities.

The census deliberately separates the capability inventory from observed
claims.  A declaration is not evidence that an owner is live: every registered
capability must have exactly one active claim, while dormant rollback surfaces
remain visible without counting as a second business executor.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

FORMAL_OWNER_DOMAINS = (
    "task",
    "schedule",
    "commit",
    "effect",
    "incident",
    "provider",
    "host_authority",
)
_DOMAIN_ORDER = {domain: index for index, domain in enumerate(FORMAL_OWNER_DOMAINS)}
_CLAIM_STATES = frozenset({"active", "dormant", "retired"})


class OwnerCensusInputError(ValueError):
    """The inventory or its ownership evidence is incomplete or malformed."""


@dataclass(frozen=True)
class CapabilitySpec:
    domain: str
    capability: str
    source_ref: str
    required_owner: str = "operations_core"


@dataclass(frozen=True)
class CapabilityClaim:
    domain: str
    capability: str
    owner: str
    source_ref: str
    observed_at: str
    state: str = "active"


@dataclass(frozen=True)
class OwnershipBlocker:
    domain: str
    capability: str
    reason: str
    owner_refs: tuple[str, ...]


@dataclass(frozen=True)
class CapabilityOwnership:
    domain: str
    capability: str
    source_ref: str
    status: str
    owner: str | None
    required_owner: str
    active_claim_count: int
    evidence_claim_count: int
    claims: tuple[CapabilityClaim, ...]


@dataclass(frozen=True)
class OwnerCensusReport:
    schema_version: str
    status: str
    ok: bool
    inventory_sha256: str
    capabilities: tuple[CapabilityOwnership, ...]
    blockers: tuple[OwnershipBlocker, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OwnerCensusInputError(f"{field} is required")
    if value != value.strip():
        raise OwnerCensusInputError(f"{field} must be normalized")
    return value


def _domain(value: object) -> str:
    normalized = _required_text(value, field="domain")
    if normalized not in _DOMAIN_ORDER:
        raise OwnerCensusInputError(f"unsupported owner domain: {normalized}")
    return normalized


def _observed_at(value: object) -> str:
    normalized = _required_text(value, field="observed_at")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise OwnerCensusInputError("observed_at must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OwnerCensusInputError("observed_at must include a real UTC offset")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _normalize_spec(spec: CapabilitySpec) -> CapabilitySpec:
    if not isinstance(spec, CapabilitySpec):
        raise OwnerCensusInputError("capability inventory rows must be CapabilitySpec")
    return CapabilitySpec(
        domain=_domain(spec.domain),
        capability=_required_text(
            spec.capability,
            field="capability",
        ),
        source_ref=_required_text(
            spec.source_ref,
            field="source_ref",
        ),
        required_owner=_required_text(
            spec.required_owner,
            field="required_owner",
        ),
    )


def _normalize_claim(claim: CapabilityClaim) -> CapabilityClaim:
    if not isinstance(claim, CapabilityClaim):
        raise OwnerCensusInputError("ownership evidence rows must be CapabilityClaim")
    state = _required_text(claim.state, field="state")
    if state not in _CLAIM_STATES:
        raise OwnerCensusInputError(f"unsupported claim state: {state}")
    return CapabilityClaim(
        domain=_domain(claim.domain),
        capability=_required_text(
            claim.capability,
            field="capability",
        ),
        owner=_required_text(claim.owner, field="owner"),
        source_ref=_required_text(
            claim.source_ref,
            field="source_ref",
        ),
        observed_at=_observed_at(claim.observed_at),
        state=state,
    )


def _spec_sort_key(spec: CapabilitySpec) -> tuple[int, str]:
    return (_DOMAIN_ORDER[spec.domain], spec.capability)


def _claim_sort_key(
    claim: CapabilityClaim,
) -> tuple[int, str, str, str, str, str]:
    return (
        _DOMAIN_ORDER[claim.domain],
        claim.capability,
        claim.state,
        claim.owner,
        claim.source_ref,
        claim.observed_at,
    )


def _inventory_sha256(
    specs: tuple[CapabilitySpec, ...],
    claims: tuple[CapabilityClaim, ...],
) -> str:
    canonical = json.dumps(
        {
            "schema_version": "formal-owner-census-input.v1",
            "specs": [asdict(spec) for spec in specs],
            "claims": [asdict(claim) for claim in claims],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_owner_census(
    *,
    specs: Iterable[CapabilitySpec],
    claims: Iterable[CapabilityClaim],
) -> OwnerCensusReport:
    """Return a deterministic census or reject an incomplete inventory.

    Missing formal domains and claims for unregistered capabilities are input
    defects, because either would make the report silently incomplete.
    Registered capabilities with zero or multiple active claims are ordinary
    blockers and remain present in the machine-readable report.
    """

    normalized_specs = tuple(
        sorted((_normalize_spec(spec) for spec in specs), key=_spec_sort_key)
    )
    spec_keys = [(spec.domain, spec.capability) for spec in normalized_specs]
    if len(spec_keys) != len(set(spec_keys)):
        raise OwnerCensusInputError("duplicate capability in formal inventory")
    present_domains = {spec.domain for spec in normalized_specs}
    for domain in FORMAL_OWNER_DOMAINS:
        if domain not in present_domains:
            raise OwnerCensusInputError(f"missing formal owner domain: {domain}")

    normalized_claims = tuple(
        sorted(
            (_normalize_claim(claim) for claim in claims),
            key=_claim_sort_key,
        )
    )
    registered = set(spec_keys)
    for claim in normalized_claims:
        if (claim.domain, claim.capability) not in registered:
            raise OwnerCensusInputError(
                "claim references unregistered capability: "
                f"{claim.domain}/{claim.capability}"
            )

    grouped: dict[tuple[str, str], list[CapabilityClaim]] = {
        key: [] for key in spec_keys
    }
    for claim in normalized_claims:
        grouped[(claim.domain, claim.capability)].append(claim)

    rows: list[CapabilityOwnership] = []
    blockers: list[OwnershipBlocker] = []
    for spec in normalized_specs:
        evidence = tuple(grouped[(spec.domain, spec.capability)])
        active = tuple(claim for claim in evidence if claim.state == "active")
        if len(active) == 1:
            owner: str | None = active[0].owner
            status = "unique_owner" if owner == spec.required_owner else "wrong_owner"
        elif not active:
            status = "unknown_owner"
            owner = None
        else:
            status = "duplicate_owner"
            owner = None
        rows.append(
            CapabilityOwnership(
                domain=spec.domain,
                capability=spec.capability,
                source_ref=spec.source_ref,
                status=status,
                owner=owner,
                required_owner=spec.required_owner,
                active_claim_count=len(active),
                evidence_claim_count=len(evidence),
                claims=evidence,
            )
        )
        if status != "unique_owner":
            blockers.append(
                OwnershipBlocker(
                    domain=spec.domain,
                    capability=spec.capability,
                    reason=status,
                    owner_refs=tuple(
                        sorted(f"{claim.owner}@{claim.source_ref}" for claim in active)
                    ),
                )
            )

    ok = not blockers
    return OwnerCensusReport(
        schema_version="formal-owner-census.v1",
        status=("unique_owners_verified" if ok else "ownership_blocked"),
        ok=ok,
        inventory_sha256=_inventory_sha256(
            normalized_specs,
            normalized_claims,
        ),
        capabilities=tuple(rows),
        blockers=tuple(blockers),
    )


__all__ = [
    "FORMAL_OWNER_DOMAINS",
    "CapabilityClaim",
    "CapabilityOwnership",
    "CapabilitySpec",
    "OwnerCensusInputError",
    "OwnerCensusReport",
    "OwnershipBlocker",
    "build_owner_census",
]
