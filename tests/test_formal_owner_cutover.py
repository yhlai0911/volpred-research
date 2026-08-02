from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from volpred.ops.formal_owner_cutover import (
    FormalOwnerCutoverManifest,
    prepare_formal_owner_cutover,
)


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@pytest.mark.parametrize(
    ("capability", "contract_ref"),
    [
        (
            "incident.lifecycle",
            "contract://issue-13/durable-incident-owner",
        ),
        (
            "provider.execution",
            "contract://issue-12/zero-paid-provider-registry",
        ),
    ],
)
def test_prepare_manifest_binds_exact_evidence_and_ttl(
    capability: str,
    contract_ref: str,
) -> None:
    prepared_at = datetime(2026, 8, 2, 6, 0, tzinfo=UTC)

    manifest = prepare_formal_owner_cutover(
        capability=capability,
        source_owner="legacy",
        source_generation=1,
        parent_work_owner_generation=2,
        acceptance_receipt=b"acceptance receipt",
        regression_receipt=b"regression receipt",
        live_preflight_receipt=b"live preflight receipt",
        prepared_at=prepared_at,
    )

    assert manifest.schema_version == "formal-owner-cutover-manifest.v1"
    assert manifest.capability == capability
    assert manifest.contract_ref == contract_ref
    assert manifest.source_owner == "legacy"
    assert manifest.source_generation == 1
    assert manifest.target_owner == "operations_core"
    assert manifest.parent_work_owner_generation == 2
    assert manifest.acceptance_receipt_sha256 == _digest(
        b"acceptance receipt"
    )
    assert manifest.regression_receipt_sha256 == _digest(
        b"regression receipt"
    )
    assert manifest.live_preflight_receipt_sha256 == _digest(
        b"live preflight receipt"
    )
    assert datetime.fromisoformat(manifest.valid_until) == (
        prepared_at + timedelta(minutes=15)
    )
    assert manifest.sha256 == _digest(manifest.canonical_bytes())
    assert FormalOwnerCutoverManifest.from_canonical_bytes(
        manifest.canonical_bytes()
    ) == manifest


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"capability": "unknown"}, "unsupported capability"),
        ({"source_owner": "operations_core"}, "source owner"),
        ({"source_generation": 0}, "source generation"),
        ({"parent_work_owner_generation": 0}, "work owner generation"),
        ({"acceptance_receipt": b""}, "acceptance receipt"),
        ({"regression_receipt": b""}, "regression receipt"),
        ({"live_preflight_receipt": b""}, "live preflight receipt"),
    ],
)
def test_prepare_manifest_rejects_unbound_or_invalid_evidence(
    overrides: dict[str, object],
    message: str,
) -> None:
    arguments: dict[str, object] = {
        "capability": "incident.lifecycle",
        "source_owner": "legacy",
        "source_generation": 1,
        "parent_work_owner_generation": 2,
        "acceptance_receipt": b"acceptance",
        "regression_receipt": b"regression",
        "live_preflight_receipt": b"preflight",
        "prepared_at": datetime(2026, 8, 2, tzinfo=UTC),
    }
    arguments.update(overrides)

    with pytest.raises(ValueError, match=message):
        prepare_formal_owner_cutover(**arguments)  # type: ignore[arg-type]


def test_manifest_parser_rejects_hash_or_field_drift() -> None:
    manifest = prepare_formal_owner_cutover(
        capability="provider.execution",
        source_owner="legacy",
        source_generation=1,
        parent_work_owner_generation=2,
        acceptance_receipt=b"acceptance",
        regression_receipt=b"regression",
        live_preflight_receipt=b"preflight",
        prepared_at=datetime(2026, 8, 2, tzinfo=UTC),
    )
    payload = manifest.canonical_bytes()

    with pytest.raises(ValueError, match="fields"):
        FormalOwnerCutoverManifest.from_canonical_bytes(
            payload[:-1] + b',"extra":true}'
        )

    drifted = payload.replace(
        b'"source_generation":1',
        b'"source_generation":2',
    )
    parsed = FormalOwnerCutoverManifest.from_canonical_bytes(drifted)
    assert parsed.source_generation == 2
    assert parsed.sha256 == _digest(drifted)
