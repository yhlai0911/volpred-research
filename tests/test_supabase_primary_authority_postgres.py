from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from test_postgres_effect_delivery import postgres_effect_dsn


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "supabase"
    / "migrations"
    / "20260724160000_operations_core_primary_authority_rpc.sql"
)


@pytest.fixture(scope="module")
def primary_authority_rpc_dsn(
    postgres_effect_dsn: str,
) -> Iterator[str]:
    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        migration = MIGRATION.read_text(encoding="utf-8")
        connection.execute(migration)
        connection.execute(migration)
    yield postgres_effect_dsn


def test_service_role_lifecycle_is_db_clock_fenced_and_token_redacted(
    primary_authority_rpc_dsn: str,
) -> None:
    with psycopg.connect(
        primary_authority_rpc_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("SET ROLE service_role")
        lease = connection.execute(
            """
            SELECT public.volpred_acquire_primary_authority(
              %s, %s, %s, %s
            )
            """,
            (
                "primary-rpc-test",
                "host:primary-rpc-test",
                300,
                "primary-rpc-secret",
            ),
        ).fetchone()[0]
        assert lease["authority_key"] == "primary-rpc-test"
        assert lease["epoch"] == 1
        assert lease["holder_ref"] == "host:primary-rpc-test"
        assert "fencing_token" not in lease

        grant = connection.execute(
            """
            SELECT public.volpred_authorize_primary_write(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                "primary-rpc-test",
                "host:primary-rpc-test",
                1,
                "primary-rpc-secret",
                "a" * 64,
                "git.commit:work-primary-rpc-test",
            ),
        ).fetchone()[0]
        assert grant["request_sha256"] == "a" * 64
        assert grant["resource_ref"] == (
            "git.commit:work-primary-rpc-test"
        )
        assert grant["primary_authority_ref"] == (
            "primary-authority:primary-rpc-test:epoch-1"
        )
        assert "fencing_token" not in grant

        renewed = connection.execute(
            """
            SELECT public.volpred_renew_primary_authority(
              %s, %s, %s, %s, %s
            )
            """,
            (
                "primary-rpc-test",
                "host:primary-rpc-test",
                1,
                300,
                "primary-rpc-secret",
            ),
        ).fetchone()[0]
        assert renewed["epoch"] == 1
        assert renewed["lease_expires_at"] > lease["lease_expires_at"]

        receipt = connection.execute(
            """
            SELECT public.volpred_release_primary_authority(
              %s, %s, %s, %s
            )
            """,
            (
                "primary-rpc-test",
                "host:primary-rpc-test",
                1,
                "primary-rpc-secret",
            ),
        ).fetchone()[0]
        assert receipt["primary_authority_ref"] == (
            "primary-authority:primary-rpc-test:epoch-1"
        )
        assert "fencing_token" not in receipt

        replay = connection.execute(
            """
            SELECT public.volpred_release_primary_authority(
              %s, %s, %s, %s
            )
            """,
            (
                "primary-rpc-test",
                "host:primary-rpc-test",
                1,
                "primary-rpc-secret",
            ),
        ).fetchone()[0]
        assert replay == receipt


def test_public_rpc_acl_is_service_role_only(
    primary_authority_rpc_dsn: str,
) -> None:
    signatures = (
        "public.volpred_acquire_primary_authority"
        "(text,text,integer,text)",
        "public.volpred_renew_primary_authority"
        "(text,text,bigint,integer,text)",
        "public.volpred_authorize_primary_write"
        "(text,text,bigint,text,text,text)",
        "public.volpred_release_primary_authority"
        "(text,text,bigint,text)",
    )
    with psycopg.connect(
        primary_authority_rpc_dsn,
        autocommit=True,
    ) as connection:
        for signature in signatures:
            row = connection.execute(
                """
                SELECT
                  procedure.prosecdef,
                  procedure.proconfig,
                  owner.rolname,
                  has_function_privilege(
                    'service_role', procedure.oid, 'EXECUTE'
                  ),
                  has_function_privilege(
                    'anon', procedure.oid, 'EXECUTE'
                  ),
                  has_function_privilege(
                    'authenticated', procedure.oid, 'EXECUTE'
                  ),
                  has_function_privilege(
                    'public', procedure.oid, 'EXECUTE'
                  )
                FROM pg_proc AS procedure
                JOIN pg_roles AS owner
                  ON owner.oid = procedure.proowner
                WHERE procedure.oid = %s::regprocedure
                """,
                (signature,),
            ).fetchone()
            assert row == (
                True,
                ['search_path=""'],
                "volpred_ops_definer",
                True,
                False,
                False,
                False,
            )

        connection.execute("SET ROLE service_role")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT * FROM volpred_ops.primary_authority_leases"
            )
