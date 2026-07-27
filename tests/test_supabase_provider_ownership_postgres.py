from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from test_postgres_effect_delivery import postgres_effect_dsn  # noqa: F401

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "supabase"
    / "migrations"
    / "20260727133500_provider_owner_attestation.sql"
)


@pytest.fixture(scope="module")
def provider_owner_attestation_dsn(
    request: pytest.FixtureRequest,
) -> Iterator[str]:
    dsn = request.getfixturevalue("postgres_effect_dsn")
    with psycopg.connect(dsn, autocommit=True) as connection:
        for _ in range(2):
            connection.execute(MIGRATION.read_text(encoding="utf-8"))
    yield dsn


def test_provider_owner_attestation_is_private_and_read_only(
    provider_owner_attestation_dsn: str,
) -> None:
    with psycopg.connect(
        provider_owner_attestation_dsn,
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
              'public.volpred_read_provider_owner()'::regprocedure
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
            "SELECT public.volpred_read_provider_owner()"
        ).fetchone()[0]
        assert payload == {
            **payload,
            "schema_version": "provider-owner-attestation.v1",
            "capability": "provider.execution",
            "owner": "legacy",
            "generation": 1,
            "contract_ref":
                "contract://issue-12/zero-paid-provider-registry",
            "receipt_sequence": 1,
            "receipt_capability": "provider.execution",
            "receipt_owner": "legacy",
            "receipt_generation": 1,
            "receipt_contract_ref":
                "contract://issue-12/zero-paid-provider-registry",
        }

        for table in (
            "volpred_ops.provider_owners",
            "volpred_ops.provider_owner_receipts",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(f"SELECT * FROM {table}")
            connection.rollback()
            connection.execute("SET ROLE service_role")


def test_provider_owner_rpc_fails_closed_on_owner_drift(
    provider_owner_attestation_dsn: str,
) -> None:
    with psycopg.connect(provider_owner_attestation_dsn) as connection:
        connection.execute(
            """
            UPDATE volpred_ops.provider_owners
            SET owner = 'operations_core',
                generation = 2,
                changed_at = statement_timestamp(),
                changed_by = 'operator:drift',
                change_reason = 'ungated drift'
            WHERE capability = 'provider.execution'
            """
        )
        connection.execute("SET LOCAL ROLE service_role")
        with pytest.raises(psycopg.errors.NoDataFound):
            connection.execute(
                "SELECT public.volpred_read_provider_owner()"
            )
        connection.rollback()


def test_provider_owner_rpc_fails_closed_on_extra_receipt(
    provider_owner_attestation_dsn: str,
) -> None:
    with psycopg.connect(provider_owner_attestation_dsn) as connection:
        connection.execute(
            """
            INSERT INTO volpred_ops.provider_owner_receipts (
              capability,
              owner,
              generation,
              contract_ref,
              changed_at,
              actor_ref,
              reason
            )
            VALUES (
              'provider.execution',
              'operations_core',
              2,
              'contract://issue-12/zero-paid-provider-registry',
              statement_timestamp(),
              'operator:drift',
              'ungated extra receipt'
            )
            """
        )
        connection.execute("SET LOCAL ROLE service_role")
        with pytest.raises(psycopg.errors.NoDataFound):
            connection.execute(
                "SELECT public.volpred_read_provider_owner()"
            )
        connection.rollback()


def test_migration_replay_rejects_drift_without_minting_receipt(
    provider_owner_attestation_dsn: str,
) -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    with psycopg.connect(
        provider_owner_attestation_dsn,
        autocommit=True,
    ) as connection:
        connection.execute(
            """
            UPDATE volpred_ops.provider_owners
            SET owner = 'operations_core',
                generation = 2,
                changed_at = statement_timestamp(),
                changed_by = 'operator:drift',
                change_reason = 'ungated drift'
            WHERE capability = 'provider.execution'
            """
        )
        before = connection.execute(
            "SELECT count(*) FROM volpred_ops.provider_owner_receipts"
        ).fetchone()[0]

        with pytest.raises(
            psycopg.errors.RaiseException,
            match="Provider owner attestation drifted",
        ):
            connection.execute(migration)

        after = connection.execute(
            "SELECT count(*) FROM volpred_ops.provider_owner_receipts"
        ).fetchone()[0]
        assert after == before


def test_provider_owner_tables_force_rls_and_have_one_bound_receipt(
    provider_owner_attestation_dsn: str,
) -> None:
    with psycopg.connect(
        provider_owner_attestation_dsn,
        autocommit=True,
    ) as connection:
        rows = connection.execute(
            """
            SELECT
              class.relname,
              class.relrowsecurity,
              class.relforcerowsecurity,
              has_table_privilege(
                'service_role', class.oid, 'SELECT'
              )
            FROM pg_class AS class
            JOIN pg_namespace AS namespace
              ON namespace.oid = class.relnamespace
            WHERE namespace.nspname = 'volpred_ops'
              AND class.relname IN (
                'provider_owners',
                'provider_owner_receipts'
              )
            ORDER BY class.relname
            """
        ).fetchall()
        assert rows == [
            ("provider_owner_receipts", True, True, False),
            ("provider_owners", True, True, False),
        ]
        assert connection.execute(
            "SELECT count(*) FROM volpred_ops.provider_owners"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT count(*) FROM volpred_ops.provider_owner_receipts"
        ).fetchone()[0] == 1
