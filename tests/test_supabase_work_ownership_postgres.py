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
    / "20260727123500_work_owner_attestation.sql"
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
        }
        assert "changed_at" in payload
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
            "attested_at",
        }
