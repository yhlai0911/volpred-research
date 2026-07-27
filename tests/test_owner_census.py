from __future__ import annotations

from dataclasses import replace

import pytest

from volpred.ops.owner_census import (
    FORMAL_OWNER_DOMAINS,
    CapabilityClaim,
    CapabilitySpec,
    OwnerCensusInputError,
    build_owner_census,
)


def _specs() -> tuple[CapabilitySpec, ...]:
    return tuple(
        CapabilitySpec(
            domain=domain,
            capability=f"{domain}.formal",
            source_ref=f"contract://{domain}",
        )
        for domain in FORMAL_OWNER_DOMAINS
    )


def _claims() -> tuple[CapabilityClaim, ...]:
    return tuple(
        CapabilityClaim(
            domain=spec.domain,
            capability=spec.capability,
            owner="operations_core",
            source_ref=f"live://{spec.domain}/owner",
            observed_at="2026-07-27T09:00:00+00:00",
        )
        for spec in _specs()
    )


def test_census_accepts_exactly_one_active_claim_per_formal_capability() -> None:
    report = build_owner_census(specs=_specs(), claims=_claims())

    assert report.ok is True
    assert report.status == "unique_owners_verified"
    assert report.blockers == ()
    assert len(report.capabilities) == len(FORMAL_OWNER_DOMAINS)
    assert {
        row.domain: (row.owner, row.active_claim_count) for row in report.capabilities
    } == {domain: ("operations_core", 1) for domain in FORMAL_OWNER_DOMAINS}
    assert len(report.inventory_sha256) == 64


@pytest.mark.parametrize("missing_domain", FORMAL_OWNER_DOMAINS)
def test_census_rejects_an_omitted_formal_domain(missing_domain: str) -> None:
    specs = tuple(spec for spec in _specs() if spec.domain != missing_domain)

    with pytest.raises(
        OwnerCensusInputError,
        match=f"missing formal owner domain: {missing_domain}",
    ):
        build_owner_census(specs=specs, claims=_claims())


def test_census_reports_unknown_owner_as_a_blocker() -> None:
    missing = _claims()[0]
    claims = tuple(claim for claim in _claims() if claim != missing)

    report = build_owner_census(specs=_specs(), claims=claims)

    assert report.ok is False
    assert report.status == "ownership_blocked"
    assert report.capabilities[0].owner is None
    assert report.capabilities[0].status == "unknown_owner"
    assert report.blockers[0].reason == "unknown_owner"
    assert report.blockers[0].capability == missing.capability


def test_census_treats_two_active_surfaces_as_duplicate_even_for_same_owner() -> None:
    original = _claims()[0]
    duplicate = replace(
        original,
        source_ref="live://second-business-execution-surface",
    )

    report = build_owner_census(
        specs=_specs(),
        claims=(*_claims(), duplicate),
    )

    assert report.ok is False
    assert report.capabilities[0].status == "duplicate_owner"
    assert report.capabilities[0].owner is None
    blocker = report.blockers[0]
    assert blocker.reason == "duplicate_owner"
    assert blocker.owner_refs == (
        "operations_core@live://second-business-execution-surface",
        "operations_core@live://task/owner",
    )


def test_non_active_evidence_does_not_create_a_second_owner() -> None:
    dormant = replace(
        _claims()[0],
        owner="legacy",
        source_ref="live://owner-gated-rollback-surface",
        state="dormant",
    )

    report = build_owner_census(
        specs=_specs(),
        claims=(*_claims(), dormant),
    )

    assert report.ok is True
    assert report.capabilities[0].active_claim_count == 1
    assert report.capabilities[0].evidence_claim_count == 2


def test_unique_legacy_owner_is_still_a_replacement_blocker() -> None:
    legacy = replace(_claims()[0], owner="legacy")

    report = build_owner_census(
        specs=_specs(),
        claims=(legacy, *_claims()[1:]),
    )

    row = report.capabilities[0]
    assert report.ok is False
    assert row.status == "wrong_owner"
    assert row.owner == "legacy"
    assert row.required_owner == "operations_core"
    assert report.blockers[0].reason == "wrong_owner"
    assert report.blockers[0].owner_refs == ("legacy@live://task/owner",)


def test_unknown_capability_claim_fails_closed() -> None:
    unknown = CapabilityClaim(
        domain="effect",
        capability="effect.not-in-inventory",
        owner="operations_core",
        source_ref="live://unregistered",
        observed_at="2026-07-27T09:00:00+00:00",
    )

    with pytest.raises(
        OwnerCensusInputError,
        match="claim references unregistered capability",
    ):
        build_owner_census(specs=_specs(), claims=(*_claims(), unknown))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("domain", "unknown", "unsupported owner domain"),
        ("capability", " ", "capability is required"),
        ("owner", " ", "owner is required"),
        ("source_ref", " ", "source_ref is required"),
        ("state", "candidate", "unsupported claim state"),
        ("observed_at", "2026-07-27T09:00:00", "UTC offset"),
    ],
)
def test_malformed_claim_evidence_is_rejected(
    field: str,
    value: str,
    message: str,
) -> None:
    malformed = replace(_claims()[0], **{field: value})

    with pytest.raises(OwnerCensusInputError, match=message):
        build_owner_census(
            specs=_specs(),
            claims=(malformed, *_claims()[1:]),
        )


def test_inventory_hash_is_order_independent_and_binds_evidence() -> None:
    first = build_owner_census(specs=_specs(), claims=_claims())
    reordered = build_owner_census(
        specs=tuple(reversed(_specs())),
        claims=tuple(reversed(_claims())),
    )
    changed = build_owner_census(
        specs=_specs(),
        claims=(
            replace(_claims()[0], observed_at="2026-07-27T09:01:00+00:00"),
            *_claims()[1:],
        ),
    )

    assert first.inventory_sha256 == reordered.inventory_sha256
    assert first.inventory_sha256 != changed.inventory_sha256
