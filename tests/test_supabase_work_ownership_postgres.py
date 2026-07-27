from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from test_postgres_effect_delivery import postgres_effect_dsn  # noqa: F401

WORK_OWNER_ATTESTATION_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "supabase"
    / "migrations"
    / "20260727124801_work_owner_attestation.sql"
)


@pytest.fixture(scope="module")
def work_owner_attestation_dsn(
    request: pytest.FixtureRequest,
) -> Iterator[str]:
    dsn = request.getfixturevalue("postgres_effect_dsn")
    with psycopg.connect(
        dsn,
        autocommit=True,
    ) as connection:
        migration = WORK_OWNER_ATTESTATION_MIGRATION.read_text(
            encoding="utf-8"
        )
        for _ in range(2):
            connection.execute(migration)
    yield dsn


def test_work_owner_attestation_is_private_and_read_only(
    work_owner_attestation_dsn: str,
) -> None:
    with psycopg.connect(
        work_owner_attestation_dsn,
        autocommit=True,
    ) as connection:
        row = connection.execute(
            """
            SELECT
              procedure.prosecdef,
              procedure.provolatile,
              procedure.proconfig,
              owner.rolname,
              has_function_privilege(
                'service_role', procedure.oid, 'EXECUTE'
              ),
              has_function_privilege('anon', procedure.oid, 'EXECUTE'),
              has_function_privilege(
                'authenticated', procedure.oid, 'EXECUTE'
              ),
              has_function_privilege('public', procedure.oid, 'EXECUTE')
            FROM pg_proc AS procedure
            JOIN pg_roles AS owner ON owner.oid = procedure.proowner
            WHERE procedure.oid =
              'public.volpred_read_work_owner()'::regprocedure
            """
        ).fetchone()
        assert row == (
            True,
            "s",
            ['search_path=""'],
            "volpred_ops_definer",
            True,
            False,
            False,
            False,
        )

        connection.execute("SET ROLE service_role")
        payload = connection.execute(
            "SELECT public.volpred_read_work_owner()"
        ).fetchone()[0]
        assert payload == {
            **payload,
            "schema_version": "work-owner-attestation.v1",
            "capability": "work.coordinate",
            "owner": "legacy",
            "generation": 1,
            "cutover_manifest_sha256": None,
            "changed_by": "migration:operations_core_work_ownership",
            "change_reason": "initial Work Coordinator owner remains legacy",
            "ownership_receipt_sequence": 1,
            "ownership_receipt_capability": "work.coordinate",
            "ownership_receipt_owner": "legacy",
            "ownership_receipt_generation": 1,
            "ownership_receipt_manifest_sha256": None,
            "ownership_receipt_actor_ref":
                "migration:operations_core_work_ownership",
            "ownership_receipt_reason":
                "initial Work Coordinator owner remains legacy",
            "ownership_receipt_rollback_of_generation": None,
            "cutover_gate_manifest_sha256": None,
            "cutover_gate_status": None,
            "cutover_gate_consumed_generation": None,
            "cutover_gate_consumed_at": None,
            "cutover_gate_rolled_back_at": None,
        }
        assert "changed_at" in payload
        assert "ownership_receipt_changed_at" in payload
        assert "attested_at" in payload
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT * FROM volpred_ops.work_owners"
            )


def test_work_owner_rpc_returns_exactly_one_owner(
    work_owner_attestation_dsn: str,
) -> None:
    with psycopg.connect(
        work_owner_attestation_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("SET ROLE service_role")
        payload = connection.execute(
            "SELECT public.volpred_read_work_owner()"
        ).fetchone()[0]
        assert set(payload) == {
            "schema_version",
            "capability",
            "owner",
            "generation",
            "cutover_manifest_sha256",
            "changed_at",
            "changed_by",
            "change_reason",
            "ownership_receipt_sequence",
            "ownership_receipt_capability",
            "ownership_receipt_owner",
            "ownership_receipt_generation",
            "ownership_receipt_manifest_sha256",
            "ownership_receipt_changed_at",
            "ownership_receipt_actor_ref",
            "ownership_receipt_reason",
            "ownership_receipt_rollback_of_generation",
            "cutover_gate_manifest_sha256",
            "cutover_gate_status",
            "cutover_gate_consumed_generation",
            "cutover_gate_consumed_at",
            "cutover_gate_rolled_back_at",
            "attested_at",
        }


def test_work_owner_rpc_binds_consumed_gate_and_owner_receipt(
    work_owner_attestation_dsn: str,
) -> None:
    manifest = "a" * 64
    with psycopg.connect(work_owner_attestation_dsn) as connection:
        prepared_at = connection.execute(
            "SELECT statement_timestamp() - interval '5 minutes'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO volpred_ops.work_cutover_gates (
              manifest_sha256,
              canonical_payload,
              source_owner,
              source_generation,
              status,
              prepared_at,
              valid_until,
              staged_at,
              staged_by
            )
            VALUES (%s, %s, 'legacy', 1, 'ready',
                    %s, %s + interval '15 minutes', %s, %s)
            """,
            (
                manifest,
                b"{}",
                prepared_at,
                prepared_at,
                prepared_at,
                "operator:test",
            ),
        )
        connection.execute(
            """
            SELECT *
            FROM volpred_ops.transfer_work_owner(
              'legacy', 1, 'operations_core', 'operator:test',
              'cutover', %s, NULL
            )
            """,
            (manifest,),
        )
        connection.execute("SET LOCAL ROLE service_role")
        payload = connection.execute(
            "SELECT public.volpred_read_work_owner()"
        ).fetchone()[0]

        assert payload["owner"] == "operations_core"
        assert payload["generation"] == 2
        assert payload["cutover_manifest_sha256"] == manifest
        assert payload["ownership_receipt_generation"] == 2
        assert payload["ownership_receipt_manifest_sha256"] == manifest
        assert payload["cutover_gate_status"] == "consumed"
        assert payload["cutover_gate_consumed_generation"] == 2
        connection.rollback()


@pytest.mark.parametrize("drift", ["missing_receipt", "future_chronology"])
def test_work_owner_rpc_rejects_unbound_or_future_owner_state(
    work_owner_attestation_dsn: str,
    drift: str,
) -> None:
    with psycopg.connect(work_owner_attestation_dsn) as connection:
        if drift == "missing_receipt":
            connection.execute(
                """
                ALTER TABLE volpred_ops.work_owners
                DISABLE TRIGGER work_owner_cutover_gate_before_update
                """
            )
            connection.execute(
                """
                UPDATE volpred_ops.work_owners
                SET owner = 'operations_core',
                    generation = 999,
                    cutover_manifest_sha256 = %s,
                    changed_at = statement_timestamp(),
                    changed_by = 'operator:drift',
                    change_reason = 'drift'
                WHERE capability = 'work.coordinate'
                """,
                ("b" * 64,),
            )
            connection.execute(
                """
                ALTER TABLE volpred_ops.work_owners
                ENABLE TRIGGER work_owner_cutover_gate_before_update
                """
            )
        else:
            connection.execute(
                """
                UPDATE volpred_ops.work_owners
                SET changed_at = statement_timestamp() + interval '1 minute'
                WHERE capability = 'work.coordinate'
                """
            )
            connection.execute(
                """
                UPDATE volpred_ops.work_owner_receipts
                SET changed_at = statement_timestamp() + interval '1 minute'
                WHERE capability = 'work.coordinate'
                  AND generation = 1
                """
            )
        connection.execute("SET LOCAL ROLE service_role")
        with pytest.raises(psycopg.errors.NoDataFound):
            connection.execute(
                "SELECT public.volpred_read_work_owner()"
            )
        connection.rollback()
