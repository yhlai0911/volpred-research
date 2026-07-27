from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from test_postgres_effect_delivery import postgres_effect_dsn

PRIMARY_AUTHORITY_RPC_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "supabase"
    / "migrations"
    / "20260724160000_operations_core_primary_authority_rpc.sql"
)
LIFECYCLE_AUDIT_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "supabase"
    / "migrations"
    / "20260727080000_primary_authority_lifecycle_audit.sql"
)


@pytest.fixture(scope="module")
def primary_authority_rpc_dsn(
    postgres_effect_dsn: str,
) -> Iterator[str]:
    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        for path in (
            PRIMARY_AUTHORITY_RPC_MIGRATION,
            LIFECYCLE_AUDIT_MIGRATION,
        ):
            migration = path.read_text(encoding="utf-8")
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
                "operations-core-primary",
                "host:primary-rpc-test",
                300,
                "primary-rpc-secret",
            ),
        ).fetchone()[0]
        assert lease["authority_key"] == "operations-core-primary"
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
                "operations-core-primary",
                "host:primary-rpc-test",
                1,
                "primary-rpc-secret",
                "a" * 64,
                "git.commit:work-primary-rpc-test",
            ),
        ).fetchone()[0]
        assert grant["request_sha256"] == "a" * 64
        assert grant["resource_ref"] == ("git.commit:work-primary-rpc-test")
        assert grant["primary_authority_ref"] == (
            "primary-authority:operations-core-primary:epoch-1"
        )
        assert "fencing_token" not in grant

        renewed = connection.execute(
            """
            SELECT public.volpred_renew_primary_authority(
              %s, %s, %s, %s, %s
            )
            """,
            (
                "operations-core-primary",
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
                "operations-core-primary",
                "host:primary-rpc-test",
                1,
                "primary-rpc-secret",
            ),
        ).fetchone()[0]
        assert receipt["primary_authority_ref"] == (
            "primary-authority:operations-core-primary:epoch-1"
        )
        assert "fencing_token" not in receipt

        replay = connection.execute(
            """
            SELECT public.volpred_release_primary_authority(
              %s, %s, %s, %s
            )
            """,
            (
                "operations-core-primary",
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
        "public.volpred_acquire_primary_authority(text,text,integer,text)",
        "public.volpred_renew_primary_authority(text,text,bigint,integer,text)",
        "public.volpred_authorize_primary_write(text,text,bigint,text,text,text)",
        "public.volpred_release_primary_authority(text,text,bigint,text)",
        "public.volpred_reconcile_primary_authority_demotion(text,text,bigint)",
        "public.volpred_read_primary_authority_events(text,integer)",
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

        owned_relations = connection.execute(
            """
            SELECT relation.relname, relation.relkind, owner.rolname
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            JOIN pg_roles AS owner
              ON owner.oid = relation.relowner
            WHERE namespace.nspname = 'volpred_ops'
              AND relation.relname IN (
                'primary_authority_events',
                'primary_authority_event_reads',
                'primary_authority_events_sequence_seq'
              )
            ORDER BY relation.relname
            """
        ).fetchall()
        assert owned_relations == [
            (
                "primary_authority_event_reads",
                "v",
                "volpred_ops_definer",
            ),
            ("primary_authority_events", "r", "volpred_ops_definer"),
            (
                "primary_authority_events_sequence_seq",
                "S",
                "volpred_ops_definer",
            ),
        ]

        connection.execute("SET ROLE service_role")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT * FROM volpred_ops.primary_authority_leases"
            )


def test_lifecycle_events_are_append_only_and_rejections_return_receipts(
    primary_authority_rpc_dsn: str,
) -> None:
    authority_key = "primary-lifecycle-audit-test"
    primary_holder = "host:lifecycle-primary"
    standby_holder = "host:lifecycle-standby"
    with psycopg.connect(
        primary_authority_rpc_dsn,
        autocommit=True,
    ) as connection:
        connection.execute(
            """
            DELETE FROM volpred_ops.primary_authority_events
            WHERE authority_key = %s
            """,
            (authority_key,),
        )
        connection.execute(
            """
            DELETE FROM volpred_ops.primary_authority_receipts
            WHERE authority_key = %s
            """,
            (authority_key,),
        )
        connection.execute(
            """
            DELETE FROM volpred_ops.primary_authority_leases
            WHERE authority_key = %s
            """,
            (authority_key,),
        )
        connection.execute("SET ROLE service_role")

        acquired = connection.execute(
            """
            SELECT public.volpred_acquire_primary_authority(
              %s, %s, %s, %s
            )
            """,
            (authority_key, primary_holder, 300, "primary-secret"),
        ).fetchone()[0]
        renewed = connection.execute(
            """
            SELECT public.volpred_renew_primary_authority(
              %s, %s, %s, %s, %s
            )
            """,
            (
                authority_key,
                primary_holder,
                acquired["epoch"],
                300,
                "primary-secret",
            ),
        ).fetchone()[0]
        rejected = connection.execute(
            """
            SELECT public.volpred_acquire_primary_authority(
              %s, %s, %s, %s
            )
            """,
            (authority_key, standby_holder, 300, "standby-secret"),
        ).fetchone()[0]

        assert renewed["lease_expires_at"] > acquired["lease_expires_at"]
        assert rejected["schema_version"] == ("primary-authority-rejection.v1")
        assert rejected["status"] == "rejected"
        assert rejected["operation"] == "acquire"
        assert rejected["reason_code"] == "already_held"
        assert rejected["event_ref"].startswith("primary-authority-event:")
        assert "primary-secret" not in str(rejected)
        assert "standby-secret" not in str(rejected)

        connection.execute("RESET ROLE")
        connection.execute(
            """
            UPDATE volpred_ops.primary_authority_leases
            SET acquired_at = clock_timestamp() - interval '10 seconds',
                lease_expires_at =
                  clock_timestamp() - interval '1 second'
            WHERE authority_key = %s
            """,
            (authority_key,),
        )
        connection.execute("SET ROLE service_role")
        takeover = connection.execute(
            """
            SELECT public.volpred_acquire_primary_authority(
              %s, %s, %s, %s
            )
            """,
            (authority_key, standby_holder, 300, "standby-secret"),
        ).fetchone()[0]
        released = connection.execute(
            """
            SELECT public.volpred_release_primary_authority(
              %s, %s, %s, %s
            )
            """,
            (
                authority_key,
                standby_holder,
                takeover["epoch"],
                "standby-secret",
            ),
        ).fetchone()[0]
        events = connection.execute(
            """
            SELECT public.volpred_read_primary_authority_events(%s, %s)
            """,
            (authority_key, 20),
        ).fetchone()[0]

    assert takeover["epoch"] == acquired["epoch"] + 1
    assert released["epoch"] == takeover["epoch"]
    assert [event["event_type"] for event in events] == [
        "acquired",
        "renewed",
        "rejected",
        "expired",
        "acquired",
        "demoted",
    ]
    assert events[2]["event_ref"] == rejected["event_ref"]
    assert events[3]["holder_ref"] == primary_holder
    assert events[3]["epoch"] == acquired["epoch"]
    assert events[-1]["holder_ref"] == standby_holder
    assert all("fencing_token" not in event for event in events)


def test_read_materializes_natural_expiry_without_takeover(
    primary_authority_rpc_dsn: str,
) -> None:
    authority_key = "primary-natural-expiry-test"
    holder_ref = "host:natural-expiry"
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
            (authority_key, holder_ref, 300, "expiry-secret"),
        ).fetchone()[0]
        connection.execute("RESET ROLE")
        connection.execute(
            """
            UPDATE volpred_ops.primary_authority_leases
            SET acquired_at = clock_timestamp() - interval '10 seconds',
                lease_expires_at =
                  clock_timestamp() - interval '1 second'
            WHERE authority_key = %s
            """,
            (authority_key,),
        )
        connection.execute("SET ROLE service_role")
        events = connection.execute(
            """
            SELECT public.volpred_read_primary_authority_events(%s, 20)
            """,
            (authority_key,),
        ).fetchone()[0]
        connection.execute("RESET ROLE")
        current = connection.execute(
            """
            SELECT holder_ref, lease_expires_at
            FROM volpred_ops.primary_authority_leases
            WHERE authority_key = %s
            """,
            (authority_key,),
        ).fetchone()

    assert lease["epoch"] == 1
    assert [event["event_type"] for event in events] == [
        "acquired",
        "expired",
        "demoted",
    ]
    assert events[1]["operation"] == "reconcile"
    assert events[2]["operation"] == "reconcile"
    assert current == (None, None)


def test_release_after_expiry_records_expired_before_demotion(
    primary_authority_rpc_dsn: str,
) -> None:
    authority_key = "primary-expired-release-test"
    holder_ref = "host:expired-release"
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
            (authority_key, holder_ref, 300, "expiry-secret"),
        ).fetchone()[0]
        connection.execute("RESET ROLE")
        connection.execute(
            """
            UPDATE volpred_ops.primary_authority_leases
            SET acquired_at = clock_timestamp() - interval '10 seconds',
                lease_expires_at =
                  clock_timestamp() - interval '1 second'
            WHERE authority_key = %s
            """,
            (authority_key,),
        )
        connection.execute("SET ROLE service_role")
        released = connection.execute(
            """
            SELECT public.volpred_release_primary_authority(
              %s, %s, %s, %s
            )
            """,
            (
                authority_key,
                holder_ref,
                lease["epoch"],
                "expiry-secret",
            ),
        ).fetchone()[0]
        events = connection.execute(
            """
            SELECT public.volpred_read_primary_authority_events(%s, 20)
            """,
            (authority_key,),
        ).fetchone()[0]

    assert released["epoch"] == lease["epoch"]
    assert [event["event_type"] for event in events] == [
        "acquired",
        "expired",
        "demoted",
    ]
    assert events[1]["operation"] == "release"
    assert events[2]["operation"] == "release"


def test_unconfirmed_demotion_reconciles_after_backend_recovery(
    primary_authority_rpc_dsn: str,
) -> None:
    authority_key = "primary-demotion-recovery-test"
    holder_ref = "host:demotion-recovery"
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
            (authority_key, holder_ref, 300, "demotion-secret"),
        ).fetchone()[0]
        pending = connection.execute(
            """
            SELECT public.volpred_reconcile_primary_authority_demotion(
              %s, %s, %s
            )
            """,
            (authority_key, holder_ref, lease["epoch"]),
        ).fetchone()[0]
        assert pending["status"] == "pending"

        connection.execute("RESET ROLE")
        connection.execute(
            """
            UPDATE volpred_ops.primary_authority_leases
            SET acquired_at = clock_timestamp() - interval '10 seconds',
                lease_expires_at =
                  clock_timestamp() - interval '1 second'
            WHERE authority_key = %s
            """,
            (authority_key,),
        )
        connection.execute("SET ROLE service_role")
        reconciled = connection.execute(
            """
            SELECT public.volpred_reconcile_primary_authority_demotion(
              %s, %s, %s
            )
            """,
            (authority_key, holder_ref, lease["epoch"]),
        ).fetchone()[0]
        replay = connection.execute(
            """
            SELECT public.volpred_reconcile_primary_authority_demotion(
              %s, %s, %s
            )
            """,
            (authority_key, holder_ref, lease["epoch"]),
        ).fetchone()[0]
        events = connection.execute(
            """
            SELECT public.volpred_read_primary_authority_events(%s, 20)
            """,
            (authority_key,),
        ).fetchone()[0]

    assert reconciled["status"] == "reconciled"
    assert replay["event_ref"] == reconciled["event_ref"]
    assert [event["event_type"] for event in events] == [
        "acquired",
        "expired",
        "demoted",
    ]
    assert sum(event["event_type"] == "demoted" for event in events) == 1


def test_formal_grant_rejects_capability_scoped_primary_lease(
    primary_authority_rpc_dsn: str,
) -> None:
    authority_key = "publisher:article.supabase.sync"
    holder_ref = "host:capability-scoped"
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
            (authority_key, holder_ref, 300, "capability-token"),
        ).fetchone()[0]
        rejected = connection.execute(
            """
            SELECT public.volpred_authorize_primary_write(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                authority_key,
                holder_ref,
                lease["epoch"],
                "capability-token",
                "d" * 64,
                "effect:publisher-sync",
            ),
        ).fetchone()[0]

        assert rejected["status"] == "rejected"
        assert rejected["reason_code"] == "formal_primary_required"
        connection.execute("RESET ROLE")
        count = connection.execute(
            """
            SELECT count(*)
            FROM volpred_ops.primary_authority_grants
            WHERE request_sha256 = %s
            """,
            ("d" * 64,),
        ).fetchone()[0]

    assert count == 0
