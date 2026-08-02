from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from test_postgres_effect_delivery import postgres_effect_dsn  # noqa: F401

from volpred.ops.formal_owner_cutover import (
    prepare_formal_owner_cutover,
)
from volpred.ops.formal_owner_postgres import (
    FormalOwnerCutoverRejected,
    PostgresFormalOwnerStore,
)
from volpred.ops.work.postgres_ownership import PostgresWorkOwnerStore
from volpred.ops.work_cutover import WorkOwnershipCutoverManifest

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260802054000_gated_incident_provider_owner_transfer.sql"
)


@pytest.fixture(scope="module")
def formal_owner_cutover_dsn(
    request: pytest.FixtureRequest,
) -> Iterator[str]:
    dsn = request.getfixturevalue("postgres_effect_dsn")
    with psycopg.connect(dsn, autocommit=True) as connection:
        for _ in range(2):
            connection.execute(MIGRATION.read_text(encoding="utf-8"))
    yield dsn


def _reset(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            """
            TRUNCATE TABLE
              volpred_ops.formal_owner_cutover_gate_receipts,
              volpred_ops.formal_owner_cutover_gates,
              volpred_ops.incident_owner_receipts,
              volpred_ops.incident_owners,
              volpred_ops.provider_owner_receipts,
              volpred_ops.provider_owners,
              volpred_ops.work_cutover_gate_receipts,
              volpred_ops.work_cutover_gates,
              volpred_ops.work_owner_receipts,
              volpred_ops.work_owners
            RESTART IDENTITY CASCADE
            """
        )
        connection.execute(
            """
            INSERT INTO volpred_ops.work_owners (
              capability, owner, generation, cutover_manifest_sha256,
              changed_at, changed_by, change_reason
            ) VALUES (
              'work.coordinate', 'legacy', 1, NULL,
              clock_timestamp(), 'test-reset', 'legacy work owner'
            );
            INSERT INTO volpred_ops.work_owner_receipts (
              capability, generation, previous_owner, owner, actor_ref,
              reason, cutover_manifest_sha256, rollback_of_generation,
              changed_at
            )
            SELECT capability, generation, NULL, owner, changed_by,
              change_reason, NULL, NULL, changed_at
            FROM volpred_ops.work_owners;

            INSERT INTO volpred_ops.incident_owners (
              capability, owner, generation, contract_ref, changed_at,
              changed_by, change_reason
            ) VALUES (
              'incident.lifecycle', 'legacy', 1,
              'contract://issue-13/durable-incident-owner',
              clock_timestamp(), 'test-reset', 'legacy incident owner'
            );
            INSERT INTO volpred_ops.incident_owner_receipts (
              capability, owner, generation, contract_ref, actor_ref,
              reason, changed_at, previous_owner, rollback_of_generation
            )
            SELECT capability, owner, generation, contract_ref, changed_by,
              change_reason, changed_at, NULL, NULL
            FROM volpred_ops.incident_owners;

            INSERT INTO volpred_ops.provider_owners (
              capability, owner, generation, contract_ref, changed_at,
              changed_by, change_reason
            ) VALUES (
              'provider.execution', 'legacy', 1,
              'contract://issue-12/zero-paid-provider-registry',
              clock_timestamp(), 'test-reset', 'legacy provider owner'
            );
            INSERT INTO volpred_ops.provider_owner_receipts (
              capability, owner, generation, contract_ref, actor_ref,
              reason, changed_at, previous_owner, rollback_of_generation
            )
            SELECT capability, owner, generation, contract_ref, changed_by,
              change_reason, changed_at, NULL, NULL
            FROM volpred_ops.provider_owners;
            """
        )


@pytest.fixture(autouse=True)
def reset_formal_owner_state(
    formal_owner_cutover_dsn: str,
) -> Iterator[None]:
    _reset(formal_owner_cutover_dsn)
    yield
    _reset(formal_owner_cutover_dsn)


def _work_manifest() -> WorkOwnershipCutoverManifest:
    now = datetime.now(UTC)
    digest = hashlib.sha256(b"work-cutover-ready").hexdigest()
    manifest = WorkOwnershipCutoverManifest(
        schema_version="work-owner-cutover-manifest.v3",
        legacy_row_count=0,
        coordinator_row_count=0,
        queue_owner_state_sha256=digest,
        legacy_snapshot_sha256=digest,
        assessment_sha256=digest,
        import_report_sha256=digest,
        projection_schema_version="next-tasks-read-projection.v1",
        projection_sha256=digest,
        prepared_at=now.isoformat(),
        valid_until=(now + timedelta(minutes=15)).isoformat(),
        sha256="",
    )
    return replace(
        manifest,
        sha256=hashlib.sha256(manifest.canonical_bytes()).hexdigest(),
    )


def _promote_work_owner(dsn: str) -> int:
    store = PostgresWorkOwnerStore(lambda: psycopg.connect(dsn))
    manifest = _work_manifest()
    store.stage_cutover_manifest(
        manifest=manifest,
        expected_owner="legacy",
        expected_generation=1,
        actor_ref="operator:test-work-cutover",
    )
    owner = store.transfer_owner(
        expected_owner="legacy",
        expected_generation=1,
        target_owner="operations_core",
        actor_ref="operator:test-work-cutover",
        reason="seven-day work gate passed",
        cutover_manifest_sha256=manifest.sha256,
    )
    return owner.generation


def _formal_manifest(capability: str, work_generation: int):
    return prepare_formal_owner_cutover(
        capability=capability,
        source_owner="legacy",
        source_generation=1,
        parent_work_owner_generation=work_generation,
        acceptance_receipt=f"{capability}:acceptance".encode(),
        regression_receipt=f"{capability}:regression".encode(),
        live_preflight_receipt=f"{capability}:preflight".encode(),
    )


def test_stage_fails_closed_before_work_owner_cutover(
    formal_owner_cutover_dsn: str,
) -> None:
    store = PostgresFormalOwnerStore(
        lambda: psycopg.connect(formal_owner_cutover_dsn)
    )
    manifest = _formal_manifest("incident.lifecycle", 2)

    with pytest.raises(
        FormalOwnerCutoverRejected,
        match="work owner is not operations_core",
    ):
        store.stage_cutover_manifest(
            manifest=manifest,
            actor_ref="operator:incident-cutover",
        )

    assert store.read_owner("incident.lifecycle").owner == "legacy"


@pytest.mark.parametrize(
    "capability",
    ["incident.lifecycle", "provider.execution"],
)
def test_cutover_exact_replay_and_rollback_restore_one_owner(
    formal_owner_cutover_dsn: str,
    capability: str,
) -> None:
    work_generation = _promote_work_owner(formal_owner_cutover_dsn)
    store = PostgresFormalOwnerStore(
        lambda: psycopg.connect(formal_owner_cutover_dsn)
    )
    manifest = _formal_manifest(capability, work_generation)
    gate = store.stage_cutover_manifest(
        manifest=manifest,
        actor_ref=f"operator:{capability}:cutover",
    )
    assert gate.status == "ready"

    command = {
        "capability": capability,
        "expected_owner": "legacy",
        "expected_generation": 1,
        "target_owner": "operations_core",
        "actor_ref": f"operator:{capability}:cutover",
        "reason": f"{capability} acceptance passed",
        "cutover_manifest_sha256": manifest.sha256,
    }
    owner = store.transfer_owner(**command)
    replay = store.transfer_owner(**command)
    stage_replay = store.stage_cutover_manifest(
        manifest=manifest,
        actor_ref=f"operator:{capability}:cutover",
    )
    assert (owner.owner, owner.generation) == ("operations_core", 2)
    assert replay == owner
    assert stage_replay.status == "consumed"
    assert stage_replay.consumed_generation == 2
    assert store.read_owner(capability) == owner

    rollback_command = {
        "capability": capability,
        "expected_owner": "operations_core",
        "expected_generation": 2,
        "target_owner": "legacy",
        "actor_ref": f"operator:{capability}:rollback",
        "reason": f"{capability} rollback rehearsal",
        "cutover_manifest_sha256": manifest.sha256,
        "rollback_of_generation": 2,
    }
    rollback = store.transfer_owner(**rollback_command)
    rollback_replay = store.transfer_owner(**rollback_command)
    assert (rollback.owner, rollback.generation) == ("legacy", 3)
    assert rollback_replay == rollback

    gate = store.read_cutover_gate(manifest.sha256)
    assert gate.status == "rolled_back"
    assert gate.consumed_generation == 2
    assert gate.rolled_back_generation == 3
    with psycopg.connect(
        formal_owner_cutover_dsn,
        autocommit=True,
    ) as connection:
        assert connection.execute(
            """
            SELECT count(*)
            FROM volpred_ops.formal_owner_cutover_gate_receipts
            WHERE manifest_sha256 = %s
            """,
            (manifest.sha256,),
        ).fetchone()[0] == 3


def test_transfer_fails_closed_if_work_owner_rolls_back_after_stage(
    formal_owner_cutover_dsn: str,
) -> None:
    work_generation = _promote_work_owner(formal_owner_cutover_dsn)
    formal_store = PostgresFormalOwnerStore(
        lambda: psycopg.connect(formal_owner_cutover_dsn)
    )
    manifest = _formal_manifest("incident.lifecycle", work_generation)
    formal_store.stage_cutover_manifest(
        manifest=manifest,
        actor_ref="operator:incident-cutover",
    )

    work_store = PostgresWorkOwnerStore(
        lambda: psycopg.connect(formal_owner_cutover_dsn)
    )
    work_owner = work_store.read_owner()
    work_store.transfer_owner(
        expected_owner="operations_core",
        expected_generation=work_owner.generation,
        target_owner="legacy",
        actor_ref="operator:test-work-rollback",
        reason="exercise parent owner fence",
        cutover_manifest_sha256=work_owner.cutover_manifest_sha256 or "",
        rollback_of_generation=work_owner.generation,
    )

    with pytest.raises(
        FormalOwnerCutoverRejected,
        match="gate does not authorize transfer",
    ):
        formal_store.transfer_owner(
            capability="incident.lifecycle",
            expected_owner="legacy",
            expected_generation=1,
            target_owner="operations_core",
            actor_ref="operator:incident-cutover",
            reason="incident acceptance passed",
            cutover_manifest_sha256=manifest.sha256,
        )

    assert formal_store.read_owner("incident.lifecycle").owner == "legacy"
    assert formal_store.read_cutover_gate(manifest.sha256).status == "ready"


def test_migration_replay_preserves_transferred_owner_and_receipts(
    formal_owner_cutover_dsn: str,
) -> None:
    work_generation = _promote_work_owner(formal_owner_cutover_dsn)
    store = PostgresFormalOwnerStore(
        lambda: psycopg.connect(formal_owner_cutover_dsn)
    )
    manifest = _formal_manifest("provider.execution", work_generation)
    store.stage_cutover_manifest(
        manifest=manifest,
        actor_ref="operator:provider-cutover",
    )
    owner = store.transfer_owner(
        capability="provider.execution",
        expected_owner="legacy",
        expected_generation=1,
        target_owner="operations_core",
        actor_ref="operator:provider-cutover",
        reason="provider acceptance passed",
        cutover_manifest_sha256=manifest.sha256,
    )

    with psycopg.connect(
        formal_owner_cutover_dsn,
        autocommit=True,
    ) as connection:
        before = connection.execute(
            "SELECT count(*) FROM volpred_ops.provider_owner_receipts"
        ).fetchone()[0]
        connection.execute(MIGRATION.read_text(encoding="utf-8"))
        after = connection.execute(
            "SELECT count(*) FROM volpred_ops.provider_owner_receipts"
        ).fetchone()[0]

    assert store.read_owner("provider.execution") == owner
    assert (before, after) == (2, 2)


def test_service_role_can_read_but_cannot_stage_or_mutate(
    formal_owner_cutover_dsn: str,
) -> None:
    with psycopg.connect(
        formal_owner_cutover_dsn,
        autocommit=True,
    ) as connection:
        assert connection.execute(
            """
            SELECT
              has_function_privilege(
                'service_role',
                'public.volpred_read_incident_owner()',
                'EXECUTE'
              ),
              has_function_privilege(
                'service_role',
                'public.volpred_read_provider_owner()',
                'EXECUTE'
              ),
              has_function_privilege(
                'service_role',
                'volpred_ops.stage_formal_owner_cutover(text,bytea,text)',
                'EXECUTE'
              ),
              has_function_privilege(
                'service_role',
                'volpred_ops.transfer_formal_owner(text,text,bigint,text,text,text,text,bigint)',
                'EXECUTE'
              ),
              has_function_privilege(
                'service_role',
                'volpred_ops.read_formal_owner_after_mutation(text)',
                'EXECUTE'
              )
            """
        ).fetchone() == (True, True, False, False, False)
        connection.execute("SET ROLE service_role")
        for table in (
            "formal_owner_cutover_gates",
            "formal_owner_cutover_gate_receipts",
            "incident_owners",
            "provider_owners",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(f"SELECT * FROM volpred_ops.{table}")
            connection.rollback()
            connection.execute("SET ROLE service_role")
