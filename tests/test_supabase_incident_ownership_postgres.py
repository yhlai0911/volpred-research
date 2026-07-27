from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from test_postgres_effect_delivery import postgres_effect_dsn  # noqa: F401

MIGRATION_ROOT = (
    Path(__file__).resolve().parents[1] / "supabase" / "migrations"
)
INCIDENT_OWNER_ATTESTATION_MIGRATIONS = (
    MIGRATION_ROOT / "20260727130815_incident_owner_attestation.sql",
    MIGRATION_ROOT
    / "20260727132000_harden_incident_owner_attestation.sql",
)


@pytest.fixture(scope="module")
def incident_owner_attestation_dsn(
    request: pytest.FixtureRequest,
) -> Iterator[str]:
    dsn = request.getfixturevalue("postgres_effect_dsn")
    with psycopg.connect(dsn, autocommit=True) as connection:
        for _ in range(2):
            for migration_path in INCIDENT_OWNER_ATTESTATION_MIGRATIONS:
                connection.execute(
                    migration_path.read_text(encoding="utf-8")
                )
    yield dsn


def test_incident_owner_attestation_is_private_and_read_only(
    incident_owner_attestation_dsn: str,
) -> None:
    with psycopg.connect(
        incident_owner_attestation_dsn,
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
              'public.volpred_read_incident_owner()'::regprocedure
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
            "SELECT public.volpred_read_incident_owner()"
        ).fetchone()[0]
        assert payload == {
            **payload,
            "schema_version": "incident-owner-attestation.v1",
            "capability": "incident.lifecycle",
            "owner": "legacy",
            "generation": 1,
            "contract_ref":
                "contract://issue-13/durable-incident-owner",
            "receipt_sequence": 1,
            "receipt_capability": "incident.lifecycle",
            "receipt_owner": "legacy",
            "receipt_generation": 1,
            "receipt_contract_ref":
                "contract://issue-13/durable-incident-owner",
        }
        assert "changed_at" in payload
        assert "receipt_changed_at" in payload
        assert "attested_at" in payload

        for table in (
            "volpred_ops.incident_owners",
            "volpred_ops.incident_owner_receipts",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(f"SELECT * FROM {table}")
            connection.rollback()
            connection.execute("SET ROLE service_role")


def test_incident_owner_rpc_fails_closed_on_unbound_owner_state(
    incident_owner_attestation_dsn: str,
) -> None:
    with psycopg.connect(
        incident_owner_attestation_dsn,
    ) as connection:
        connection.execute(
            """
            UPDATE volpred_ops.incident_owners
            SET owner = 'operations_core',
                generation = 2,
                changed_at = statement_timestamp(),
                changed_by = 'operator:drift',
                change_reason = 'ungated drift'
            WHERE capability = 'incident.lifecycle'
            """
        )
        connection.execute("SET LOCAL ROLE service_role")
        with pytest.raises(psycopg.errors.NoDataFound):
            connection.execute(
                "SELECT public.volpred_read_incident_owner()"
            )
        connection.rollback()


def test_incident_owner_rpc_fails_closed_on_extra_receipt(
    incident_owner_attestation_dsn: str,
) -> None:
    with psycopg.connect(
        incident_owner_attestation_dsn,
    ) as connection:
        connection.execute(
            """
            INSERT INTO volpred_ops.incident_owner_receipts (
              capability,
              owner,
              generation,
              contract_ref,
              changed_at,
              actor_ref,
              reason
            )
            VALUES (
              'incident.lifecycle',
              'operations_core',
              2,
              'contract://issue-13/durable-incident-owner',
              statement_timestamp(),
              'operator:drift',
              'ungated extra receipt'
            )
            """
        )
        connection.execute("SET LOCAL ROLE service_role")
        with pytest.raises(psycopg.errors.NoDataFound):
            connection.execute(
                "SELECT public.volpred_read_incident_owner()"
            )
        connection.rollback()


def test_migration_replay_rejects_drift_without_minting_receipt(
    incident_owner_attestation_dsn: str,
) -> None:
    migration = INCIDENT_OWNER_ATTESTATION_MIGRATIONS[0].read_text(
        encoding="utf-8"
    )
    with psycopg.connect(
        incident_owner_attestation_dsn,
        autocommit=True,
    ) as connection:
        connection.execute(
            """
            UPDATE volpred_ops.incident_owners
            SET owner = 'operations_core',
                generation = 2,
                changed_at = statement_timestamp(),
                changed_by = 'operator:drift',
                change_reason = 'ungated drift'
            WHERE capability = 'incident.lifecycle'
            """
        )
        before = connection.execute(
            """
            SELECT count(*)
            FROM volpred_ops.incident_owner_receipts
            """
        ).fetchone()[0]

        with pytest.raises(
            psycopg.errors.RaiseException,
            match="Incident owner attestation drifted",
        ):
            connection.execute(migration)

        after = connection.execute(
            """
            SELECT count(*)
            FROM volpred_ops.incident_owner_receipts
            """
        ).fetchone()[0]
        assert after == before

        connection.execute(
            """
            UPDATE volpred_ops.incident_owners AS ownership
            SET owner = receipt.owner,
                generation = receipt.generation,
                contract_ref = receipt.contract_ref,
                changed_at = receipt.changed_at,
                changed_by = receipt.actor_ref,
                change_reason = receipt.reason
            FROM volpred_ops.incident_owner_receipts AS receipt
            WHERE ownership.capability = receipt.capability
              AND receipt.generation = 1
            """
        )


def test_incident_owner_tables_are_force_rls_singletons(
    incident_owner_attestation_dsn: str,
) -> None:
    with psycopg.connect(
        incident_owner_attestation_dsn,
        autocommit=True,
    ) as connection:
        rows = connection.execute(
            """
            SELECT
              class.relname,
              class.relrowsecurity,
              class.relforcerowsecurity,
              has_table_privilege(
                'service_role',
                format('volpred_ops.%I', class.relname),
                'SELECT'
              )
            FROM pg_class AS class
            JOIN pg_namespace AS namespace
              ON namespace.oid = class.relnamespace
            WHERE namespace.nspname = 'volpred_ops'
              AND class.relname IN (
                'incident_owners',
                'incident_owner_receipts'
              )
            ORDER BY class.relname
            """
        ).fetchall()
        assert rows == [
            ("incident_owner_receipts", True, True, False),
            ("incident_owners", True, True, False),
        ]
        assert connection.execute(
            "SELECT count(*) FROM volpred_ops.incident_owners"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT count(*) FROM volpred_ops.incident_owner_receipts"
        ).fetchone()[0] == 1
