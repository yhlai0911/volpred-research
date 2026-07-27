import hashlib
import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from pathlib import Path
from threading import Barrier

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from volpred.ops.authority import (
    AuthorityRequest,
    PrimaryAuthority,
    WriteIntent,
)
from volpred.ops.authority.postgres import PostgresAuthorityStore
from volpred.ops.delivery import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    ChangeSetConflict,
    ChangeSetProposal,
    ChangeSetView,
    CheckEvidence,
    ContentHash,
    EffectRequest,
    EffectRequestConflict,
    FailedEffect,
    _proposal_sha256,
)
from volpred.ops.delivery._change_settlement import (
    CommitSettlement,
    CommitSettlementBlocked,
    commit_settlement_sha256,
)
from volpred.ops.delivery._effect_worker import (
    EffectWorkerBlocked,
    EffectWorkerCommand,
    _authority_request,
)
from volpred.ops.delivery._git_actuator import (
    CommitActuation,
    CommitActuationReceipt,
    CommitActuatorBlocked,
    CommitAuthorityRequest,
    GitCommitActuator,
    _authority_request_sha256,
)
from volpred.ops.delivery._git_actuator import (
    _authority_request as commit_authority_request,
)
from volpred.ops.delivery.owned_change import (
    CommitOwnershipLost,
    OwnedChangeCommand,
    build_postgres_owned_change_delivery,
)
from volpred.ops.delivery.postgres import (
    EffectOutboxLease,
    EffectSettlementAuthority,
    PostgresEffectDelivery,
)
from volpred.ops.delivery.postgres_authority import PostgresEffectAuthority
from volpred.ops.delivery.postgres_change_store import PostgresChangeSetStore
from volpred.ops.delivery.postgres_commit_authority import (
    PostgresCommitAuthority,
)
from volpred.ops.delivery.postgres_commit_ownership import (
    PostgresCommitOwnerStore,
)
from volpred.ops.delivery.postgres_commit_settlement import (
    PostgresCommitSettlement,
)
from volpred.ops.delivery.postgres_payload import (
    EffectPayloadConflict,
    PostgresEffectPayloadStore,
)
from volpred.ops.work import (
    Started,
    WorkCoordinator,
    WorkerOffer,
    WorkItemView,
    WorkLease,
    WorkRequest,
)
from volpred.ops.work.postgres import PostgresCoordinationStore
from volpred.ops.work.postgres_ownership import PostgresWorkOwnerStore
from volpred.ops.work_cutover import WorkOwnershipCutoverManifest

REPO_ROOT = Path(__file__).resolve().parents[1]
TELEGRAM_EFFECT_KINDS = frozenset({"telegram.message.send"})
MIGRATIONS = (
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260723062144_operations_core_work_coordinator.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260723230547_operations_core_effect_payload_primary_authority_receipt.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260723234435_operations_core_notification_ownership.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260723235106_operations_core_notification_ownership_index.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724020500_operations_core_effect_outbox.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724030000_operations_core_effect_outbox_settlement.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724040000_operations_core_effect_worker_authority.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724050000_operations_core_effect_receipt_index.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724060000_operations_core_effect_payload_primary_authority.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724070000_operations_core_notification_ownership.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724071000_operations_core_notification_ownership_index.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724090000_operations_core_commit_authority.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724100000_operations_core_commit_settlement.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724110000_operations_core_commit_ownership.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724113000_operations_core_change_set_store.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724114500_operations_core_change_set_receipt_index.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724120000_operations_core_commit_ownership_rpc.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724130000_operations_core_change_set_rpc.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724140000_operations_core_commit_authority_rpc.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724150000_operations_core_commit_settlement_rpc.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724100512_operations_core_work_read_model_rpc.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724160000_operations_core_primary_authority_rpc.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724131707_operations_core_owned_email_keepalive_gate.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724134742_operations_core_effect_family_routing.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724170000_operations_core_publisher_article_ownership.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724180000_operations_core_publisher_article_terminal_replay.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724213739_operations_core_publisher_reconcile_ownership.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260726034720_operations_core_work_ownership.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260726050256_operations_core_work_cutover_gate.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260726074028_operations_core_owned_email_recovery.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260726081120_fence_owned_email_expired_retry.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260726081532_operations_core_owned_email_due_retry_recovery.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260726083559_fence_owned_email_recovery_family.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260726083856_fence_owned_email_recovery_family.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260726093801_operations_core_owned_publisher_article_recovery.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260726125016_boss_report_owned_email_terminal_replay.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260726181931_owned_publisher_reconcile_recovery.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260727001900_commit_authority_terminal_recovery.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260727080000_primary_authority_lifecycle_audit.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260727121500_primary_authority_owner_attestation.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260727123500_work_owner_attestation.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260727110626_operations_core_duplicate_effect_retirement_signal.sql",
)
IDEMPOTENT_REPLAY_MIGRATION = (
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724213739_operations_core_publisher_reconcile_ownership.sql"
)
OWNED_EMAIL_FENCE_MIGRATION_RECEIPTS = (
    (
        REPO_ROOT
        / "supabase"
        / "migrations"
        / "20260726083559_fence_owned_email_recovery_family.sql",
        1688,
        "622db1864a3fa5da4d26fb91a2a516f83b306749c52ed34087ff238ca1704ea9",
        False,
    ),
    (
        REPO_ROOT
        / "supabase"
        / "migrations"
        / "20260726083856_fence_owned_email_recovery_family.sql",
        2519,
        "d95ec5e4824e38b7067cc443b3c1983a04d3c34c1b60cf8298188ab4a2336781",
        True,
    ),
)


def test_owned_email_fence_migrations_match_production_receipts() -> None:
    for migration, expected_bytes, expected_sha256, strip_terminal_newline in (
        OWNED_EMAIL_FENCE_MIGRATION_RECEIPTS
    ):
        statement = migration.read_bytes()
        if strip_terminal_newline:
            assert statement.endswith(b"\n")
            statement = statement.removesuffix(b"\n")
        assert len(statement) == expected_bytes
        assert hashlib.sha256(statement).hexdigest() == expected_sha256


def _postgres_bin_dir() -> Path | None:
    homebrew = Path("/opt/homebrew/opt/postgresql@17/bin")
    if (homebrew / "postgres").exists():
        return homebrew
    pg_config = shutil.which("pg_config")
    if pg_config is None:
        return None
    bin_dir = Path(
        subprocess.check_output((pg_config, "--bindir"), text=True).strip()
    )
    return bin_dir if (bin_dir / "postgres").exists() else None


def _work_cutover_manifest(seed: str) -> WorkOwnershipCutoverManifest:
    prepared_at = datetime.now(timezone.utc)
    evidence_sha256 = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    manifest = WorkOwnershipCutoverManifest(
        schema_version="work-owner-cutover-manifest.v3",
        legacy_row_count=1,
        coordinator_row_count=1,
        queue_owner_state_sha256=evidence_sha256,
        legacy_snapshot_sha256=evidence_sha256,
        assessment_sha256=evidence_sha256,
        import_report_sha256=evidence_sha256,
        projection_schema_version="next-tasks-read-projection.v1",
        projection_sha256=evidence_sha256,
        prepared_at=prepared_at.isoformat(),
        valid_until=(prepared_at + timedelta(minutes=15)).isoformat(),
        sha256="",
    )
    return replace(
        manifest,
        sha256=hashlib.sha256(manifest.canonical_bytes()).hexdigest(),
    )


def _validate_external_test_dsn(dsn: str) -> None:
    params = conninfo_to_dict(dsn)
    hostaddr = params.get("hostaddr")
    hostaddr_is_loopback = hostaddr is None
    if hostaddr is not None:
        try:
            hostaddr_is_loopback = all(
                ip_address(address).is_loopback
                for address in hostaddr.split(",")
            )
        except ValueError:
            hostaddr_is_loopback = False
    if (
        params.get("host") not in {"127.0.0.1", "localhost", "::1"}
        or not hostaddr_is_loopback
        or params.get("dbname") != "volpred_ops_effect_test"
        or os.environ.get("VOLPRED_ALLOW_DESTRUCTIVE_POSTGRES_TEST") != "1"
    ):
        raise RuntimeError(
            "external effect tests require localhost, database "
            "'volpred_ops_effect_test', and "
            "VOLPRED_ALLOW_DESTRUCTIVE_POSTGRES_TEST=1"
        )


def _commit_authority_security_readback(
    dsn: str,
) -> tuple[bool, bool, bool, bool, bool, bool, bool]:
    owner_fenced = (
        "volpred_ops.authorize_commit_write("
        "text,text,bigint,text,text,text,text,integer,bigint,"
        "text,text,text,text)"
    )
    legacy = (
        "volpred_ops.authorize_commit_write("
        "text,text,bigint,text,text,text,text,integer,text,text,text,text)"
    )
    with psycopg.connect(dsn, autocommit=True) as connection:
        return connection.execute(
            """
            SELECT
              has_function_privilege(
                'volpred_ops_worker', %s, 'EXECUTE'
              ),
              has_function_privilege(
                'volpred_ops_worker', %s, 'EXECUTE'
              ),
              has_function_privilege(
                'public', %s, 'EXECUTE'
              ),
              (
                SELECT relrowsecurity AND relforcerowsecurity
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'volpred_ops'
                  AND relation.relname = 'commit_authority_grants'
              ),
              has_table_privilege(
                'public',
                'volpred_ops.commit_authority_grants',
                'SELECT'
              ),
              (
                SELECT procedure.proowner = (
                  SELECT oid FROM pg_roles
                  WHERE rolname = 'volpred_ops_definer'
                )
                FROM pg_proc AS procedure
                WHERE procedure.oid = %s::regprocedure
              ),
              (
                SELECT procedure.prosecdef
                  AND procedure.proconfig @>
                    ARRAY['search_path=pg_catalog, volpred_ops']
                FROM pg_proc AS procedure
                WHERE procedure.oid = %s::regprocedure
              )
            """,
            (owner_fenced, legacy, owner_fenced, owner_fenced, owner_fenced),
        ).fetchone()


def _commit_settlement_security_readback(
    dsn: str,
) -> tuple[bool, bool, bool, bool, bool, bool, bool]:
    owner_fenced = (
        "volpred_ops.settle_commit_write("
        "text,text,bigint,text,text,bigint,text,text,text,text,text,"
        "text,text,text,text,jsonb,text,timestamp with time zone,text)"
    )
    legacy = (
        "volpred_ops.settle_commit_write("
        "text,text,bigint,text,text,text,text,text,text,text,text,text,"
        "text,jsonb,text,timestamp with time zone,text)"
    )
    with psycopg.connect(dsn, autocommit=True) as connection:
        return connection.execute(
            """
            SELECT
              has_function_privilege(
                'volpred_ops_worker', %s, 'EXECUTE'
              ),
              has_function_privilege(
                'volpred_ops_worker', %s, 'EXECUTE'
              ),
              has_function_privilege(
                'public', %s, 'EXECUTE'
              ),
              (
                SELECT relrowsecurity AND relforcerowsecurity
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'volpred_ops'
                  AND relation.relname = 'commit_delivery_receipts'
              ),
              has_table_privilege(
                'public',
                'volpred_ops.commit_delivery_receipts',
                'SELECT'
              ),
              (
                SELECT procedure.proowner = (
                  SELECT oid FROM pg_roles
                  WHERE rolname = 'volpred_ops_definer'
                )
                FROM pg_proc AS procedure
                WHERE procedure.oid = %s::regprocedure
              ),
              (
                SELECT procedure.prosecdef
                  AND procedure.proconfig @>
                    ARRAY['search_path=pg_catalog, volpred_ops']
                FROM pg_proc AS procedure
                WHERE procedure.oid = %s::regprocedure
              )
            """,
            (
                owner_fenced,
                legacy,
                owner_fenced,
                owner_fenced,
                owner_fenced,
            ),
        ).fetchone()


def _commit_ownership_security_readback(
    dsn: str,
) -> tuple[bool, bool, bool, bool, bool, bool, bool]:
    read_owner = "volpred_ops.read_commit_owner()"
    transfer_owner = (
        "volpred_ops.transfer_commit_owner("
        "text,bigint,text,text,text,bigint)"
    )
    with psycopg.connect(dsn, autocommit=True) as connection:
        return connection.execute(
            """
            SELECT
              has_function_privilege(
                'volpred_ops_worker', %s, 'EXECUTE'
              ),
              has_function_privilege(
                'volpred_ops_approver', %s, 'EXECUTE'
              ),
              has_function_privilege(
                'volpred_ops_worker', %s, 'EXECUTE'
              ),
              has_function_privilege(
                'public', %s, 'EXECUTE'
              ),
              (
                SELECT bool_and(relrowsecurity AND relforcerowsecurity)
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'volpred_ops'
                  AND relation.relname IN (
                    'commit_owners',
                    'commit_owner_receipts'
                  )
              ),
              (
                NOT has_table_privilege(
                  'public', 'volpred_ops.commit_owners', 'SELECT'
                )
                AND NOT has_table_privilege(
                  'public',
                  'volpred_ops.commit_owner_receipts',
                  'SELECT'
                )
              ),
              (
                SELECT bool_and(
                  procedure.proowner = (
                    SELECT oid FROM pg_roles
                    WHERE rolname = 'volpred_ops_definer'
                  )
                  AND procedure.prosecdef
                  AND procedure.proconfig @>
                    ARRAY['search_path=pg_catalog, volpred_ops']
                )
                FROM pg_proc AS procedure
                WHERE procedure.oid IN (
                  %s::regprocedure,
                  %s::regprocedure
                )
              )
            """,
            (
                read_owner,
                transfer_owner,
                transfer_owner,
                transfer_owner,
                read_owner,
                transfer_owner,
            ),
        ).fetchone()


def _verify_non_superuser_migration_executor(dsn: str) -> None:
    """Exercise the production PG17 CREATEROLE ownership/privilege path."""

    manager = "volpred_ops_migration_test_manager"
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(
            """
            DO $$
            BEGIN
              CREATE ROLE service_role NOLOGIN;
            EXCEPTION WHEN duplicate_object THEN NULL;
            END;
            $$;
            DO $$
            BEGIN
              CREATE ROLE anon NOLOGIN;
            EXCEPTION WHEN duplicate_object THEN NULL;
            END;
            $$;
            DO $$
            BEGIN
              CREATE ROLE authenticated NOLOGIN;
            EXCEPTION WHEN duplicate_object THEN NULL;
            END;
            $$;
            """
        )
        connection.execute(
            f"""
            CREATE ROLE {manager}
              LOGIN CREATEROLE NOSUPERUSER NOCREATEDB
              NOREPLICATION NOBYPASSRLS
            """
        )
        connection.execute(
            f"GRANT CREATE ON DATABASE {connection.info.dbname} TO {manager}"
        )
        connection.execute(
            f"GRANT USAGE, CREATE ON SCHEMA public TO {manager} "
            "WITH GRANT OPTION"
        )
    try:
        with psycopg.connect(
            dsn,
            user=manager,
            autocommit=True,
        ) as connection:
            for migration in MIGRATIONS:
                connection.execute(migration.read_text(encoding="utf-8"))
            connection.execute(
                IDEMPOTENT_REPLAY_MIGRATION.read_text(encoding="utf-8")
            )

        with psycopg.connect(dsn, autocommit=True) as connection:
            (
                worker_execute,
                public_execute,
                worker_settle,
                public_settle,
                definer_create,
                receipt_outbox_index,
                worker_authorize_effect,
                public_authorize_effect,
                public_payload_select,
                new_tables_force_rls,
                definer_function_owners,
                fixed_function_search_paths,
                unsafe_memberships,
                owned_service_execute,
                owned_anon_execute,
                owned_authenticated_execute,
                owned_public_execute,
                owned_tables_force_rls,
                service_owned_table_select,
                public_rpc_definer_owners,
                public_rpc_fixed_search_paths,
                definer_public_create,
                owned_indexes,
            ) = connection.execute(
                    """
                    SELECT
                      has_function_privilege(
                        'volpred_ops_worker',
                        'volpred_ops.start_work(text,text,integer)',
                        'EXECUTE'
                      ),
                      has_function_privilege(
                        'public',
                        'volpred_ops.start_work(text,text,integer)',
                        'EXECUTE'
                      ),
                      has_function_privilege(
                        'volpred_ops_worker',
                        'volpred_ops.settle_effect_outbox('
                          'bigint,text,integer,text,text,text,text,text,'
                          'text,text,text,text,text,text)',
                        'EXECUTE'
                      ),
                      has_function_privilege(
                        'public',
                        'volpred_ops.settle_effect_outbox('
                          'bigint,text,integer,text,text,text,text,text,'
                          'text,text,text,text,text,text)',
                        'EXECUTE'
                      ),
                      has_schema_privilege(
                        'volpred_ops_definer',
                        'volpred_ops',
                        'CREATE'
                      ),
                      to_regclass(
                        'volpred_ops.'
                        'effect_attempt_receipts_outbox_sequence_idx'
                      ) IS NOT NULL,
                      has_function_privilege(
                        'volpred_ops_worker',
                        'volpred_ops.authorize_effect_write('
                          'text,text,bigint,text,text,text,text,text,integer,'
                          'bigint,integer,text,timestamptz,text,text,text,text,'
                          'text,text,text)',
                        'EXECUTE'
                      ),
                      has_function_privilege(
                        'public',
                        'volpred_ops.authorize_effect_write('
                          'text,text,bigint,text,text,text,text,text,integer,'
                          'bigint,integer,text,timestamptz,text,text,text,text,'
                          'text,text,text)',
                        'EXECUTE'
                      ),
                      has_table_privilege(
                        'public',
                        'volpred_ops.effect_payloads',
                        'SELECT'
                      ),
                      (
                        SELECT bool_and(
                          relation.relrowsecurity
                          AND relation.relforcerowsecurity
                        )
                        FROM pg_class AS relation
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = relation.relnamespace
                        WHERE namespace.nspname = 'volpred_ops'
                          AND relation.relname IN (
                            'effect_payloads',
                            'primary_authority_leases',
                            'primary_authority_grants',
                            'primary_authority_receipts',
                            'effect_authority_grants'
                          )
                      ),
                      (
                        SELECT bool_and(
                          procedure.proowner = (
                            SELECT oid FROM pg_roles
                            WHERE rolname = 'volpred_ops_definer'
                          )
                        )
                        FROM pg_proc AS procedure
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = procedure.pronamespace
                        WHERE namespace.nspname = 'volpred_ops'
                          AND procedure.proname IN (
                            'put_effect_payload',
                            'read_effect_payload',
                            'verify_durable_effect_payload',
                            'acquire_primary_authority',
                            'renew_primary_authority',
                            'authorize_primary_write',
                            'release_primary_authority',
                            'authorize_effect_write',
                            'require_effect_authority_grant'
                          )
                      ),
                      (
                        SELECT bool_and(
                          procedure.prosecdef
                          AND procedure.proconfig @>
                            ARRAY['search_path=pg_catalog, volpred_ops']
                        )
                        FROM pg_proc AS procedure
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = procedure.pronamespace
                        WHERE namespace.nspname = 'volpred_ops'
                          AND procedure.proname IN (
                            'put_effect_payload',
                            'read_effect_payload',
                            'verify_durable_effect_payload',
                            'acquire_primary_authority',
                            'renew_primary_authority',
                            'authorize_primary_write',
                            'release_primary_authority',
                            'authorize_effect_write',
                            'require_effect_authority_grant'
                          )
                      ),
                      (
                        SELECT count(*)
                        FROM pg_auth_members AS memberships
                        JOIN pg_roles AS granted
                          ON granted.oid = memberships.roleid
                        WHERE granted.rolname LIKE 'volpred_ops_%%'
                          AND NOT (
                            memberships.member = (
                              SELECT oid FROM pg_roles
                              WHERE rolname = %s
                            )
                            AND memberships.admin_option
                            AND NOT memberships.set_option
                            AND NOT memberships.inherit_option
                          )
                      ),
                      (
                        SELECT bool_and(
                          has_function_privilege(
                            'service_role', procedure.oid, 'EXECUTE'
                          )
                        )
                        FROM pg_proc AS procedure
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = procedure.pronamespace
                        WHERE namespace.nspname = 'public'
                          AND procedure.proname IN (
                            'volpred_read_notification_owner',
                            'volpred_transfer_notification_owner',
                            'volpred_request_owned_email_notification',
                            'volpred_begin_owned_email_notification',
                            'volpred_settle_owned_email_notification'
                          )
                      ),
                      (
                        SELECT bool_and(
                          has_function_privilege(
                            'anon', procedure.oid, 'EXECUTE'
                          )
                        )
                        FROM pg_proc AS procedure
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = procedure.pronamespace
                        WHERE namespace.nspname = 'public'
                          AND procedure.proname IN (
                            'volpred_read_notification_owner',
                            'volpred_transfer_notification_owner',
                            'volpred_request_owned_email_notification',
                            'volpred_begin_owned_email_notification',
                            'volpred_settle_owned_email_notification'
                          )
                      ),
                      (
                        SELECT bool_and(
                          has_function_privilege(
                            'authenticated', procedure.oid, 'EXECUTE'
                          )
                        )
                        FROM pg_proc AS procedure
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = procedure.pronamespace
                        WHERE namespace.nspname = 'public'
                          AND procedure.proname IN (
                            'volpred_read_notification_owner',
                            'volpred_transfer_notification_owner',
                            'volpred_request_owned_email_notification',
                            'volpred_begin_owned_email_notification',
                            'volpred_settle_owned_email_notification'
                          )
                      ),
                      (
                        SELECT bool_and(
                          has_function_privilege(
                            'public', procedure.oid, 'EXECUTE'
                          )
                        )
                        FROM pg_proc AS procedure
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = procedure.pronamespace
                        WHERE namespace.nspname = 'public'
                          AND procedure.proname IN (
                            'volpred_read_notification_owner',
                            'volpred_transfer_notification_owner',
                            'volpred_request_owned_email_notification',
                            'volpred_begin_owned_email_notification',
                            'volpred_settle_owned_email_notification'
                          )
                      ),
                      (
                        SELECT count(*) = 4
                          AND bool_and(
                            relation.relrowsecurity
                            AND relation.relforcerowsecurity
                          )
                        FROM pg_class AS relation
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = relation.relnamespace
                        WHERE namespace.nspname = 'volpred_ops'
                          AND relation.relname IN (
                            'notification_owners',
                            'notification_owner_receipts',
                            'owned_notification_requests',
                            'owned_notification_attempts'
                          )
                      ),
                      (
                        SELECT bool_or(
                          has_table_privilege(
                            'service_role', relation.oid, 'SELECT'
                          )
                        )
                        FROM pg_class AS relation
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = relation.relnamespace
                        WHERE namespace.nspname = 'volpred_ops'
                          AND relation.relname IN (
                            'notification_owners',
                            'notification_owner_receipts',
                            'owned_notification_requests',
                            'owned_notification_attempts'
                          )
                      ),
                      (
                        SELECT count(*) = 5
                          AND bool_and(
                            procedure.proowner = (
                              SELECT oid FROM pg_roles
                              WHERE rolname = 'volpred_ops_definer'
                            )
                            AND procedure.prosecdef
                          )
                        FROM pg_proc AS procedure
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = procedure.pronamespace
                        WHERE namespace.nspname = 'public'
                          AND procedure.proname IN (
                            'volpred_read_notification_owner',
                            'volpred_transfer_notification_owner',
                            'volpred_request_owned_email_notification',
                            'volpred_begin_owned_email_notification',
                            'volpred_settle_owned_email_notification'
                          )
                      ),
                      (
                        SELECT count(*) = 5
                          AND bool_and(
                            procedure.proconfig = ARRAY['search_path=""']
                          )
                        FROM pg_proc AS procedure
                        JOIN pg_namespace AS namespace
                          ON namespace.oid = procedure.pronamespace
                        WHERE namespace.nspname = 'public'
                          AND procedure.proname IN (
                            'volpred_read_notification_owner',
                            'volpred_transfer_notification_owner',
                            'volpred_request_owned_email_notification',
                            'volpred_begin_owned_email_notification',
                            'volpred_settle_owned_email_notification'
                          )
                      ),
                      has_schema_privilege(
                        'volpred_ops_definer', 'public', 'CREATE'
                      ),
                      (
                        SELECT count(*) = 5
                        FROM pg_indexes
                        WHERE schemaname = 'volpred_ops'
                          AND indexname IN (
                            'notification_owner_receipts_family_changed_idx',
                            'owned_notification_requests_owner_generation_idx',
                            'owned_notification_attempts_work_idx',
                            'owned_notification_attempts_outbox_idx',
                            'owned_notification_attempts_active_idx'
                          )
                      )
                    """,
                    (manager,),
                ).fetchone()
        assert worker_execute is True
        assert public_execute is False
        assert worker_settle is True
        assert public_settle is False
        assert definer_create is False
        assert receipt_outbox_index is True
        assert worker_authorize_effect is True
        assert public_authorize_effect is False
        assert public_payload_select is False
        assert new_tables_force_rls is True
        assert definer_function_owners is True
        assert fixed_function_search_paths is True
        assert unsafe_memberships == 0
        assert owned_service_execute is True
        assert owned_anon_execute is False
        assert owned_authenticated_execute is False
        assert owned_public_execute is False
        assert owned_tables_force_rls is True
        assert service_owned_table_select is False
        assert public_rpc_definer_owners is True
        assert public_rpc_fixed_search_paths is True
        assert definer_public_create is False
        assert owned_indexes is True
        (
            commit_worker_execute,
            legacy_commit_worker_execute,
            commit_public_execute,
            commit_grants_force_rls,
            commit_grants_public_select,
            commit_function_owner,
            commit_function_search_path,
        ) = _commit_authority_security_readback(dsn)
        assert commit_worker_execute is True
        assert legacy_commit_worker_execute is False
        assert commit_public_execute is False
        assert commit_grants_force_rls is True
        assert commit_grants_public_select is False
        assert commit_function_owner is True
        assert commit_function_search_path is True
        (
            settlement_worker_execute,
            legacy_settlement_worker_execute,
            settlement_public_execute,
            settlement_receipts_force_rls,
            settlement_receipts_public_select,
            settlement_function_owner,
            settlement_function_search_path,
        ) = _commit_settlement_security_readback(dsn)
        assert settlement_worker_execute is True
        assert legacy_settlement_worker_execute is False
        assert settlement_public_execute is False
        assert settlement_receipts_force_rls is True
        assert settlement_receipts_public_select is False
        assert settlement_function_owner is True
        assert settlement_function_search_path is True
        (
            ownership_worker_read,
            ownership_approver_transfer,
            ownership_worker_transfer,
            ownership_public_transfer,
            ownership_tables_force_rls,
            ownership_public_table_select_revoked,
            ownership_functions_hardened,
        ) = _commit_ownership_security_readback(dsn)
        assert ownership_worker_read is True
        assert ownership_approver_transfer is True
        assert ownership_worker_transfer is False
        assert ownership_public_transfer is False
        assert ownership_tables_force_rls is True
        assert ownership_public_table_select_revoked is True
        assert ownership_functions_hardened is True
        with psycopg.connect(dsn, autocommit=True) as connection:
            service_rpc_security = connection.execute(
                """
                SELECT
                  (
                    SELECT count(*) = 2
                      AND bool_and(
                        procedure.proowner = (
                          SELECT oid FROM pg_roles
                          WHERE rolname = 'volpred_ops_definer'
                        )
                        AND procedure.prosecdef
                        AND procedure.proconfig = ARRAY['search_path=""']
                      )
                    FROM pg_proc AS procedure
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = procedure.pronamespace
                    WHERE namespace.nspname = 'public'
                      AND procedure.proname IN (
                        'volpred_read_commit_owner',
                        'volpred_transfer_commit_owner'
                      )
                  ),
                  has_function_privilege(
                    'service_role',
                    'public.volpred_read_commit_owner()',
                    'EXECUTE'
                  ),
                  has_function_privilege(
                    'service_role',
                    'public.volpred_transfer_commit_owner('
                      'text,bigint,text,text,text,bigint)',
                    'EXECUTE'
                  ),
                  NOT has_function_privilege(
                    'anon',
                    'public.volpred_read_commit_owner()',
                    'EXECUTE'
                  ),
                  NOT has_function_privilege(
                    'authenticated',
                    'public.volpred_transfer_commit_owner('
                      'text,bigint,text,text,text,bigint)',
                    'EXECUTE'
                  ),
                  NOT has_function_privilege(
                    'public',
                    'public.volpred_read_commit_owner()',
                    'EXECUTE'
                  ),
                  NOT has_table_privilege(
                    'service_role',
                    'volpred_ops.commit_owners',
                    'SELECT'
                  ),
                  NOT has_schema_privilege(
                    'volpred_ops_definer',
                    'public',
                    'CREATE'
                  ),
                  (
                    SELECT count(*) = 5
                      AND bool_and(
                        procedure.proowner = (
                          SELECT oid FROM pg_roles
                          WHERE rolname = 'volpred_ops_definer'
                        )
                        AND procedure.prosecdef
                        AND procedure.proconfig = ARRAY['search_path=""']
                      )
                    FROM pg_proc AS procedure
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = procedure.pronamespace
                    WHERE namespace.nspname = 'public'
                      AND procedure.proname IN (
                        'volpred_create_change_set',
                        'volpred_read_change_set',
                        'volpred_read_change_set_by_idempotency_key',
                        'volpred_checkpoint_change_set_actuation',
                        'volpred_mark_change_set_landed'
                      )
                  ),
                  (
                    SELECT bool_and(
                      has_function_privilege(
                        'service_role', procedure.oid, 'EXECUTE'
                      )
                    )
                    FROM pg_proc AS procedure
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = procedure.pronamespace
                    WHERE namespace.nspname = 'public'
                      AND procedure.proname IN (
                        'volpred_create_change_set',
                        'volpred_read_change_set',
                        'volpred_read_change_set_by_idempotency_key',
                        'volpred_checkpoint_change_set_actuation',
                        'volpred_mark_change_set_landed'
                      )
                  ),
                  (
                    SELECT NOT bool_or(
                      has_function_privilege(
                        'anon', procedure.oid, 'EXECUTE'
                      )
                      OR has_function_privilege(
                        'authenticated', procedure.oid, 'EXECUTE'
                      )
                      OR has_function_privilege(
                        'public', procedure.oid, 'EXECUTE'
                      )
                    )
                    FROM pg_proc AS procedure
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = procedure.pronamespace
                    WHERE namespace.nspname = 'public'
                      AND procedure.proname IN (
                        'volpred_create_change_set',
                        'volpred_read_change_set',
                        'volpred_read_change_set_by_idempotency_key',
                        'volpred_checkpoint_change_set_actuation',
                        'volpred_mark_change_set_landed'
                      )
                  ),
                  NOT has_table_privilege(
                    'service_role',
                    'volpred_ops.change_sets',
                    'SELECT'
                  ),
                  NOT has_table_privilege(
                    'service_role',
                    'volpred_ops.change_set_reads',
                    'SELECT'
                  )
                """
            ).fetchone()
        assert service_rpc_security == (True,) * 13
        with psycopg.connect(dsn, autocommit=True) as connection:
            commit_authority_rpc_security = connection.execute(
                """
                SELECT
                  (
                    SELECT procedure.proowner = (
                      SELECT oid FROM pg_roles
                      WHERE rolname = 'volpred_ops_definer'
                    )
                      AND procedure.prosecdef
                      AND procedure.proconfig = ARRAY['search_path=""']
                    FROM pg_proc AS procedure
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = procedure.pronamespace
                    WHERE namespace.nspname = 'public'
                      AND procedure.proname =
                        'volpred_authorize_commit_write'
                  ),
                  has_function_privilege(
                    'service_role',
                    'public.volpred_authorize_commit_write('
                      'text,text,bigint,text,text,text,text,integer,'
                      'bigint,text,text,text,text)',
                    'EXECUTE'
                  ),
                  NOT has_function_privilege(
                    'anon',
                    'public.volpred_authorize_commit_write('
                      'text,text,bigint,text,text,text,text,integer,'
                      'bigint,text,text,text,text)',
                    'EXECUTE'
                  ),
                  NOT has_function_privilege(
                    'authenticated',
                    'public.volpred_authorize_commit_write('
                      'text,text,bigint,text,text,text,text,integer,'
                      'bigint,text,text,text,text)',
                    'EXECUTE'
                  ),
                  NOT has_function_privilege(
                    'public',
                    'public.volpred_authorize_commit_write('
                      'text,text,bigint,text,text,text,text,integer,'
                      'bigint,text,text,text,text)',
                    'EXECUTE'
                  ),
                  NOT has_table_privilege(
                    'service_role',
                    'volpred_ops.commit_authority_grants',
                    'SELECT'
                  ),
                  NOT has_table_privilege(
                    'service_role',
                    'volpred_ops.commit_authority_grant_reads',
                    'SELECT'
                  ),
                  NOT has_schema_privilege(
                    'volpred_ops_definer', 'public', 'CREATE'
                  )
                """
            ).fetchone()
        assert commit_authority_rpc_security == (True,) * 8
        with psycopg.connect(dsn, autocommit=True) as connection:
            commit_settlement_rpc_security = connection.execute(
                """
                SELECT
                  (
                    SELECT procedure.proowner = (
                      SELECT oid FROM pg_roles
                      WHERE rolname = 'volpred_ops_definer'
                    )
                      AND procedure.prosecdef
                      AND procedure.proconfig = ARRAY['search_path=""']
                    FROM pg_proc AS procedure
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = procedure.pronamespace
                    WHERE namespace.nspname = 'public'
                      AND procedure.proname =
                        'volpred_settle_commit_write'
                  ),
                  has_function_privilege(
                    'service_role',
                    'public.volpred_settle_commit_write('
                      'text,text,bigint,text,text,bigint,text,text,text,'
                      'text,text,text,text,text,text,jsonb,text,'
                      'timestamp with time zone,text)',
                    'EXECUTE'
                  ),
                  NOT has_function_privilege(
                    'anon',
                    'public.volpred_settle_commit_write('
                      'text,text,bigint,text,text,bigint,text,text,text,'
                      'text,text,text,text,text,text,jsonb,text,'
                      'timestamp with time zone,text)',
                    'EXECUTE'
                  ),
                  NOT has_function_privilege(
                    'authenticated',
                    'public.volpred_settle_commit_write('
                      'text,text,bigint,text,text,bigint,text,text,text,'
                      'text,text,text,text,text,text,jsonb,text,'
                      'timestamp with time zone,text)',
                    'EXECUTE'
                  ),
                  NOT has_function_privilege(
                    'public',
                    'public.volpred_settle_commit_write('
                      'text,text,bigint,text,text,bigint,text,text,text,'
                      'text,text,text,text,text,text,jsonb,text,'
                      'timestamp with time zone,text)',
                    'EXECUTE'
                  ),
                  NOT has_table_privilege(
                    'service_role',
                    'volpred_ops.commit_delivery_receipts',
                    'SELECT'
                  ),
                  NOT has_table_privilege(
                    'service_role',
                    'volpred_ops.commit_delivery_receipt_reads',
                    'SELECT'
                  ),
                  NOT has_schema_privilege(
                    'volpred_ops_definer', 'public', 'CREATE'
                  )
                """
            ).fetchone()
        assert commit_settlement_rpc_security == (True,) * 8
        with psycopg.connect(dsn, autocommit=True) as connection:
            work_read_rpc_security = connection.execute(
                """
                SELECT
                  (
                    SELECT procedure.proowner = (
                      SELECT oid FROM pg_roles
                      WHERE rolname = 'volpred_ops_definer'
                    )
                      AND procedure.prosecdef
                      AND procedure.proconfig = ARRAY['search_path=""']
                    FROM pg_proc AS procedure
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = procedure.pronamespace
                    WHERE namespace.nspname = 'public'
                      AND procedure.proname =
                        'volpred_read_work_snapshot'
                  ),
                  has_function_privilege(
                    'service_role',
                    'public.volpred_read_work_snapshot(text)',
                    'EXECUTE'
                  ),
                  NOT has_function_privilege(
                    'anon',
                    'public.volpred_read_work_snapshot(text)',
                    'EXECUTE'
                  ),
                  NOT has_function_privilege(
                    'authenticated',
                    'public.volpred_read_work_snapshot(text)',
                    'EXECUTE'
                  ),
                  NOT has_function_privilege(
                    'public',
                    'public.volpred_read_work_snapshot(text)',
                    'EXECUTE'
                  ),
                  NOT has_table_privilege(
                    'service_role',
                    'volpred_ops.work_item_reads',
                    'SELECT'
                  ),
                  NOT has_table_privilege(
                    'service_role',
                    'volpred_ops.work_events',
                    'SELECT'
                  ),
                  NOT has_table_privilege(
                    'service_role',
                    'volpred_ops.work_checkpoints',
                    'SELECT'
                  ),
                  NOT has_table_privilege(
                    'service_role',
                    'volpred_ops.work_receipts',
                    'SELECT'
                  ),
                  NOT has_schema_privilege(
                    'volpred_ops_definer', 'public', 'CREATE'
                  )
                """
            ).fetchone()
        assert work_read_rpc_security == (True,) * 10
    finally:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(
                """
                DROP FUNCTION IF EXISTS
                  public.volpred_read_commit_owner(),
                  public.volpred_transfer_commit_owner(
                    text, bigint, text, text, text, bigint
                  ),
                  public.volpred_create_change_set(
                    text, text, text, integer, text, text, jsonb, jsonb,
                    jsonb, text, text, text, text, timestamptz
                  ),
                  public.volpred_read_change_set(text),
                  public.volpred_read_change_set_by_idempotency_key(text),
                  public.volpred_checkpoint_change_set_actuation(
                    text, text, text, jsonb
                  ),
                  public.volpred_mark_change_set_landed(
                    text, text, text, text
                  ),
                  public.volpred_authorize_commit_write(
                    text, text, bigint, text, text, text, text, integer,
                    bigint, text, text, text, text
                  ),
                  public.volpred_read_commit_authority_grant(text),
                  public.volpred_abandon_commit_write(
                    text, bigint, text, text
                  ),
                  public.volpred_settle_commit_write(
                    text, text, bigint, text, text, bigint, text, text,
                    text, text, text, text, text, text, text, jsonb,
                    text, timestamptz, text
                  ),
                  public.volpred_read_work_snapshot(text),
                  public.volpred_read_work_owner(),
                  public.volpred_acquire_primary_authority(
                    text, text, integer, text
                  ),
                  public.volpred_renew_primary_authority(
                    text, text, bigint, integer, text
                  ),
                  public.volpred_authorize_primary_write(
                    text, text, bigint, text, text, text
                  ),
                  public.volpred_release_primary_authority(
                    text, text, bigint, text
                  ),
                  public.volpred_reconcile_primary_authority_demotion(
                    text, text, bigint
                  ),
                  public.volpred_read_primary_authority_owner(),
                  public.volpred_read_notification_owner(),
                  public.volpred_read_owned_email_request(text),
                  public.volpred_transfer_notification_owner(
                    text, bigint, text, text, text, bigint
                  ),
                  public.volpred_request_owned_email_notification(
                    bigint, text, text, text, text, jsonb, text
                  ),
                  public.volpred_begin_owned_email_notification(
                    bigint, text, text, integer, text, text, text
                  ),
                  public.volpred_settle_owned_email_notification(
                    bigint, text, integer, text, text, bigint, integer,
                    text, text, text, text, bigint, text, text, text,
                    text, text, text, text, text, text, text
                  ),
                  public.volpred_recover_expired_owned_email_notification(
                    bigint, text, integer, text, text, text
                  ),
                  public.volpred_read_publisher_article_sync_owner(),
                  public.volpred_transfer_publisher_article_sync_owner(
                    text, bigint, text, text, text, bigint
                  ),
                  public.volpred_request_owned_publisher_article_sync(
                    bigint, text, jsonb, text
                  ),
                  public.volpred_begin_owned_publisher_article_sync(
                    bigint, text, text, integer, text, text, text
                  ),
                  public.volpred_recover_due_owned_publisher_article_sync(
                    bigint, text, integer, text, text, text
                  ),
                  public.volpred_settle_owned_publisher_article_sync(
                    bigint, text, integer, text, text, bigint, integer,
                    text, text, text, text, bigint, text, text, text,
                    text, text, text, text, text, text, text
                  ),
                  public.volpred_read_publisher_article_reconcile_owner(),
                  public.volpred_transfer_publisher_article_reconcile_owner(
                    text, bigint, text, text, text, bigint
                  ),
                  public.volpred_request_owned_publisher_article_reconcile(
                    bigint, text, jsonb, text
                  ),
                  public.volpred_begin_owned_publisher_article_reconcile(
                    bigint, text, text, integer, text, text, text
                  ),
                  public.volpred_recover_due_owned_publisher_article_reconcile(
                    bigint, text, integer, text, text, text
                  ),
                  public.volpred_settle_owned_publisher_article_reconcile(
                    bigint, text, integer, text, text, bigint, integer,
                    text, text, text, text, bigint, text, text, text,
                    text, text, text, text, text, text, text
                  ),
                  public.volpred_read_duplicate_effect_retirement_events(bigint),
                  public.volpred_read_primary_authority_events(text, integer)
                """
            )
            connection.execute("DROP SCHEMA IF EXISTS volpred_ops CASCADE")
            connection.execute(
                """
                DROP ROLE IF EXISTS
                  volpred_ops_worker,
                  volpred_ops_approver,
                  volpred_ops_definer
                """
            )
            connection.execute(
                f"REVOKE CREATE ON DATABASE {connection.info.dbname} "
                f"FROM {manager}"
            )
            connection.execute(
                f"REVOKE USAGE, CREATE ON SCHEMA public FROM {manager}"
            )
            connection.execute(f"DROP ROLE IF EXISTS {manager}")


@pytest.fixture(scope="session")
def postgres_effect_dsn(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[str]:
    external_dsn = os.environ.get("VOLPRED_EFFECT_POSTGRES_TEST_DSN")
    if external_dsn:
        _validate_external_test_dsn(external_dsn)
        with psycopg.connect(external_dsn, autocommit=True) as connection:
            connection.execute("DROP SCHEMA IF EXISTS volpred_ops CASCADE")
            for migration in MIGRATIONS:
                connection.execute(migration.read_text(encoding="utf-8"))
        yield external_dsn
        return

    bin_dir = _postgres_bin_dir()
    if bin_dir is None:
        if os.environ.get("CI"):
            pytest.fail(
                "PostgreSQL server binaries or "
                "VOLPRED_EFFECT_POSTGRES_TEST_DSN are required in CI"
            )
        pytest.skip("PostgreSQL server binaries are required for effect contracts")

    root = tmp_path_factory.mktemp("effect-outbox-postgres")
    data_dir = root / "data"
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    subprocess.run(
        (
            str(bin_dir / "initdb"),
            "-D",
            str(data_dir),
            "--auth=trust",
            "--no-locale",
            "--encoding=UTF8",
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        (
            str(bin_dir / "pg_ctl"),
            "-D",
            str(data_dir),
            "-l",
            str(root / "postgres.log"),
            "-o",
            f"-F -h 127.0.0.1 -p {port} -k /tmp",
            "-w",
            "start",
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    dsn = f"postgresql://127.0.0.1:{port}/postgres"
    try:
        _verify_non_superuser_migration_executor(dsn)
        with psycopg.connect(dsn, autocommit=True) as connection:
            for migration in MIGRATIONS:
                connection.execute(migration.read_text(encoding="utf-8"))
        yield dsn
    finally:
        subprocess.run(
            (
                str(bin_dir / "pg_ctl"),
                "-D",
                str(data_dir),
                "-m",
                "fast",
                "-w",
                "stop",
            ),
            check=True,
            capture_output=True,
            text=True,
        )


@pytest.fixture(autouse=True)
def reset_effect_state(postgres_effect_dsn: str) -> None:
    with psycopg.connect(postgres_effect_dsn, autocommit=True) as connection:
        connection.execute(
            """
            TRUNCATE TABLE
              volpred_ops.legacy_retirement_duplicate_effect_events,
              volpred_ops.work_cutover_gate_receipts,
              volpred_ops.work_cutover_gates,
                  volpred_ops.work_owner_receipts,
                  volpred_ops.work_owners,
                  volpred_ops.owned_publisher_reconcile_recovery_receipts,
                  volpred_ops.owned_publisher_article_recovery_receipts,
                  volpred_ops.owned_notification_recovery_receipts,
              volpred_ops.owned_notification_attempts,
              volpred_ops.owned_notification_requests,
              volpred_ops.notification_owner_receipts,
              volpred_ops.notification_owners,
              volpred_ops.effect_attempt_receipts,
                  volpred_ops.effect_authority_grants,
                  volpred_ops.change_sets,
                  volpred_ops.commit_delivery_receipts,
                  volpred_ops.commit_authority_abandonments,
                  volpred_ops.commit_authority_grants,
              volpred_ops.commit_owner_receipts,
              volpred_ops.commit_owners,
              volpred_ops.primary_authority_events,
              volpred_ops.primary_authority_grants,
              volpred_ops.primary_authority_receipts,
              volpred_ops.primary_authority_leases,
              volpred_ops.effect_outbox,
              volpred_ops.effect_requests,
              volpred_ops.effect_payloads,
              volpred_ops.work_receipts,
              volpred_ops.work_checkpoints,
              volpred_ops.work_events,
              volpred_ops.work_items
            RESTART IDENTITY
            """
        )
        connection.execute(
            """
            UPDATE volpred_ops.legacy_retirement_duplicate_effect_head
            SET high_watermark = 0
            WHERE singleton
            """
        )
        connection.execute(
            """
            INSERT INTO volpred_ops.work_owners (
              capability, owner, generation, cutover_manifest_sha256,
              changed_at, changed_by, change_reason
            )
            VALUES (
              'work.coordinate',
              'legacy',
              1,
              NULL,
              clock_timestamp(),
              'test-reset',
              'restore canonical legacy Work Coordinator owner'
            );
            INSERT INTO volpred_ops.work_owner_receipts (
              capability, generation, previous_owner, owner, actor_ref,
              reason, cutover_manifest_sha256, rollback_of_generation,
              changed_at
            )
            SELECT
              capability, generation, NULL, owner, changed_by,
              change_reason, cutover_manifest_sha256, NULL, changed_at
            FROM volpred_ops.work_owners
            WHERE capability = 'work.coordinate';
            INSERT INTO volpred_ops.notification_owners (
              effect_family, owner, generation, changed_at, changed_by,
              change_reason
            )
            VALUES (
              'email.ops_alert',
              'legacy',
              1,
              clock_timestamp(),
              'test-reset',
              'restore canonical legacy fixture owner'
            );
            INSERT INTO volpred_ops.notification_owner_receipts (
              effect_family, generation, previous_owner, owner, actor_ref,
              reason, rollback_of_generation, changed_at
            )
            SELECT
              effect_family, generation, NULL, owner, changed_by,
              change_reason, NULL, changed_at
            FROM volpred_ops.notification_owners
            WHERE effect_family = 'email.ops_alert';
            INSERT INTO volpred_ops.notification_owners (
              effect_family, owner, generation, changed_at, changed_by,
              change_reason
            )
            VALUES (
              'publisher.article.supabase.sync',
              'legacy',
              1,
              clock_timestamp(),
              'test-reset',
              'restore canonical legacy publisher fixture owner'
            );
            INSERT INTO volpred_ops.notification_owner_receipts (
              effect_family, generation, previous_owner, owner, actor_ref,
              reason, rollback_of_generation, changed_at
            )
            SELECT
              effect_family, generation, NULL, owner, changed_by,
              change_reason, NULL, changed_at
            FROM volpred_ops.notification_owners
            WHERE effect_family = 'publisher.article.supabase.sync';
            INSERT INTO volpred_ops.notification_owners (
              effect_family, owner, generation, changed_at, changed_by,
              change_reason
            )
            VALUES (
              'publisher.article.supabase.reconcile',
              'legacy',
              1,
              clock_timestamp(),
              'test-reset',
              'restore canonical legacy reconcile fixture owner'
            );
            INSERT INTO volpred_ops.notification_owner_receipts (
              effect_family, generation, previous_owner, owner, actor_ref,
              reason, rollback_of_generation, changed_at
            )
            SELECT
              effect_family, generation, NULL, owner, changed_by,
              change_reason, NULL, changed_at
            FROM volpred_ops.notification_owners
            WHERE effect_family = 'publisher.article.supabase.reconcile';
            INSERT INTO volpred_ops.commit_owners (
              capability, owner, generation, changed_at, changed_by,
              change_reason
            )
            VALUES (
              'git.commit',
              'legacy',
              1,
              clock_timestamp(),
              'test-reset',
              'restore canonical legacy fixture owner'
            );
            INSERT INTO volpred_ops.commit_owner_receipts (
              capability, generation, previous_owner, owner, actor_ref,
              reason, rollback_of_generation, changed_at
            )
            SELECT
              capability, generation, NULL, owner, changed_by,
              change_reason, NULL, changed_at
            FROM volpred_ops.commit_owners
            WHERE capability = 'git.commit';
            """
        )
        connection.execute(
            "SELECT volpred_ops.set_legacy_work_mutation_access(true)"
        )


def _worker_connection(dsn: str) -> psycopg.Connection:
    connection = psycopg.connect(dsn)
    connection.execute("SET ROLE volpred_ops_worker")
    return connection


def _approver_connection(dsn: str) -> psycopg.Connection:
    connection = psycopg.connect(dsn)
    connection.execute("SET ROLE volpred_ops_approver")
    return connection


def test_commit_owner_service_rpc_cutover_rollback_and_acl(
    postgres_effect_dsn: str,
) -> None:
    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("SET ROLE service_role")
        initial = connection.execute(
            "SELECT public.volpred_read_commit_owner()"
        ).fetchone()[0]
        assert (initial["owner"], initial["generation"]) == ("legacy", 1)

        cutover = connection.execute(
            """
            SELECT public.volpred_transfer_commit_owner(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                "legacy",
                1,
                "operations_core",
                "test:service-rpc",
                "exercise service-role operator seam",
                None,
            ),
        ).fetchone()[0]
        assert (cutover["owner"], cutover["generation"]) == (
            "operations_core",
            2,
        )

        rollback = connection.execute(
            """
            SELECT public.volpred_transfer_commit_owner(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                "operations_core",
                2,
                "legacy",
                "test:service-rpc",
                "exercise exact rollback",
                2,
            ),
        ).fetchone()[0]
        assert (rollback["owner"], rollback["generation"]) == ("legacy", 3)

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT * FROM volpred_ops.commit_owners"
            )

    for role in ("anon", "authenticated"):
        with psycopg.connect(
            postgres_effect_dsn,
            autocommit=True,
        ) as connection:
            connection.execute(f"SET ROLE {role}")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    "SELECT public.volpred_read_commit_owner()"
                )


def test_formal_workflows_are_rebound_to_definer_only_work_seams(
    postgres_effect_dsn: str,
) -> None:
    with psycopg.connect(postgres_effect_dsn) as connection:
        rows = connection.execute(
            """
            SELECT namespace.nspname, procedure.proname, procedure.prosrc
            FROM pg_catalog.pg_proc AS procedure
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = procedure.pronamespace
            WHERE (
              namespace.nspname,
              procedure.proname
            ) IN (
              ('public', 'volpred_request_owned_email_notification'),
              ('public', 'volpred_settle_owned_email_notification'),
              ('volpred_ops', 'settle_commit_write'),
              ('public', 'volpred_request_owned_publisher_article_sync'),
              ('public', 'volpred_settle_owned_publisher_article_sync'),
              ('public', 'volpred_request_owned_publisher_article_reconcile'),
              ('public', 'volpred_settle_owned_publisher_article_reconcile')
            )
              AND procedure.prosrc LIKE '%_work_internal(%'
            ORDER BY namespace.nspname, procedure.proname
            """
        ).fetchall()
        worker_internal_access = connection.execute(
            """
            SELECT has_function_privilege(
              'volpred_ops_worker',
              'volpred_ops.submit_work_internal('
              'text,text,text,text,text,integer,text[],text[],text,text,'
              'text,text,timestamptz,text,text,integer,'
              'timestamptz,timestamptz)',
              'EXECUTE'
            )
            """
        ).fetchone()[0]

    assert len(rows) == 7
    assert all(
        not any(
            legacy_name in source
            for legacy_name in (
                "volpred_ops.submit_work(",
                "volpred_ops.approve_work(",
                "volpred_ops.complete_work(",
                "volpred_ops.release_work(",
            )
        )
        for _, _, source in rows
    )
    assert worker_internal_access is False


def _ensure_commit_owner(dsn: str) -> None:
    store = PostgresCommitOwnerStore(
        connection_factory=lambda: _approver_connection(dsn)
    )
    owner = store.read_owner()
    if owner.owner == "legacy":
        store.transfer_owner(
            expected_owner="legacy",
            expected_generation=owner.generation,
            target_owner="operations_core",
            actor_ref="test:commit-owner-cutover",
            reason="isolated PostgreSQL commit contract",
        )


def _git_text(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", "-C", str(repository), *arguments),
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()


def _seed_work(dsn: str, *, work_id: str = "work-effect-1") -> None:
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: _worker_connection(dsn)
        ),
        id_factory=lambda: work_id,
        clock=lambda: datetime.now(timezone.utc),
    )
    coordinator.submit(
        WorkRequest(
            idempotency_key=f"owner:effect:{work_id}",
            source="user",
            kind="platform_ops",
            title="Durable effect request",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref=f"owner:effect:{work_id}",
        )
    )


def _seed_running_work(
    dsn: str,
    *,
    work_id: str = "work-commit-1",
    lease_token: str = "work-lease-commit-1",
    required_attestations: frozenset[str] = frozenset(),
) -> tuple[WorkLease, WorkItemView]:
    _ensure_commit_owner(dsn)
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: _worker_connection(dsn)
        ),
        id_factory=lambda: work_id,
        token_factory=lambda: lease_token,
        clock=lambda: datetime.now(timezone.utc),
    )
    coordinator.submit(
        WorkRequest(
            idempotency_key=f"owner:commit:{work_id}",
            source="user",
            kind="platform_ops",
            title="Land a durable ChangeSet",
            priority=1,
            required_capabilities=frozenset({"commit"}),
            required_attestations=required_attestations,
            risk="safe",
            approval="auto",
            payload_ref=f"changeset:{work_id}",
        )
    )
    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="agent:change-author",
            capabilities=frozenset({"commit"}),
            attestations=required_attestations,
            lease_seconds=300,
        )
    )
    assert lease is not None
    running = coordinator.record(
        Started(
            work_id=lease.work_item.id,
            lease_token=lease.token,
            expected_version=lease.work_item.version,
        )
    )
    return lease, running


def _commit_authority_request(
    *,
    work_id: str,
    work_version: int,
    work_lease_token: str,
    primary_fencing_token: str,
) -> CommitAuthorityRequest:
    command = CommitActuation(
        proposal_sha256="a" * 64,
        work_item_id=work_id,
        work_item_version=work_version,
        commit_owner_generation=2,
        work_lease_token=work_lease_token,
        primary_fencing_token=primary_fencing_token,
        repository="/tmp/volpred-commit-authority-test",
        expected_head="b" * 40,
        exact_paths=("src/volpred/example.py",),
        content_hashes=(
            ContentHash(
                path="src/volpred/example.py",
                sha256="c" * 64,
            ),
        ),
        message="[change-delivery] land durable grant",
        actor="commit-worker:postgres-test",
    )
    return commit_authority_request(command)


def _commit_actuation_receipt(
    request: CommitAuthorityRequest,
    grant,
) -> CommitActuationReceipt:
    return CommitActuationReceipt(
        schema_version="commit-actuation.v1",
        proposal_sha256=request.proposal_sha256,
        work_item_id=request.work_item_id,
        work_item_version=request.work_item_version,
        commit_owner_generation=request.commit_owner_generation,
        commit_owner_ref=grant.commit_owner_ref,
        authority_request_sha256=request.request_sha256,
        work_lease_ref=grant.work_lease_ref,
        primary_authority_ref=grant.primary_authority_ref,
        commit_sha="d" * 40,
        parent_sha=request.expected_head,
        exact_paths=request.exact_paths,
        actor=request.actor,
        status="committed",
        observed_at=datetime.now(timezone.utc).isoformat(),
    )


def _commit_settlement(
    request: CommitAuthorityRequest,
    grant,
) -> CommitSettlement:
    return CommitSettlement(
        change_set_id="changeset-postgres-1",
        repository=request.repository,
        work_lease_token=request.work_lease_token,
        primary_fencing_token=request.primary_fencing_token,
        actuation=_commit_actuation_receipt(request, grant),
    )


def _change_set_view(
    running: WorkItemView,
    request: CommitAuthorityRequest,
) -> ChangeSetView:
    proposal = ChangeSetProposal(
        idempotency_key="changeset:work-commit-1:attempt-1",
        work_item_id=running.id,
        work_item_version=running.version,
        base_commit=request.expected_head,
        workspace_ref=str(Path("/tmp/shadow-change-worktree").resolve()),
        exact_paths=request.exact_paths,
        content_hashes=request.content_hashes,
        required_checks=(
            CheckEvidence(
                name="pytest",
                status="passed",
                evidence_ref="test:postgres-change-store",
            ),
        ),
        author_ref="agent:change-author",
        author_evidence_ref="execution:work-commit-1:attempt-1",
    )
    return ChangeSetView(
        schema_version="changeset.v1",
        id="changeset-postgres-1",
        idempotency_key=proposal.idempotency_key,
        work_item_id=proposal.work_item_id,
        work_item_version=proposal.work_item_version,
        base_commit=proposal.base_commit,
        workspace_ref=proposal.workspace_ref,
        exact_paths=proposal.exact_paths,
        content_hashes=proposal.content_hashes,
        required_checks=proposal.required_checks,
        author_ref=proposal.author_ref,
        author_evidence_ref=proposal.author_evidence_ref,
        proposal_sha256=_proposal_sha256(proposal),
        status="proposed",
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _request(**overrides: object) -> EffectRequest:
    request = EffectRequest(
        idempotency_key="effect:work-effect-1:telegram:completion",
        work_item_id="work-effect-1",
        work_item_version=1,
        effect_kind="telegram.message.send",
        target_ref="telegram:owner-chat",
        payload_ref="artifact:completion-message-v1",
        payload_sha256="a" * 64,
        risk="sensitive",
        acknowledgement=AcknowledgementExpectation(
            kind="telegram.message.readback",
            target_ref="telegram:owner-chat",
        ),
        requester_ref="agent:codex-worker",
    )
    return replace(request, **overrides)


def _delivery(
    dsn: str,
    *,
    effect_id: str = "effect-postgres-1",
    token: str = "effect-token-1",
) -> PostgresEffectDelivery:
    return PostgresEffectDelivery(
        connection_factory=lambda: _worker_connection(dsn),
        id_factory=lambda: effect_id,
        token_factory=lambda: token,
    )


def test_request_and_outbox_are_atomic_durable_and_replay_safe(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    first = _delivery(postgres_effect_dsn).request(_request())
    replay = _delivery(
        postgres_effect_dsn,
        effect_id="unused-replay-id",
    ).request(_request())
    inspected = _delivery(postgres_effect_dsn).inspect(first.id)

    with psycopg.connect(postgres_effect_dsn) as connection:
        rows = connection.execute(
            """
            SELECT effect_id, status, attempt_count
            FROM volpred_ops.effect_outbox
            """
        ).fetchall()

    assert replay == first
    assert inspected == first
    assert first.created_at.endswith("+00:00")
    assert rows == [("effect-postgres-1", "pending", 0)]


def test_duplicate_delivered_receipt_appends_private_retirement_event(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    _delivery(postgres_effect_dsn).request(_request())
    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        # Production migration runners may replay an already-recorded file.
        # The schema and backfill must remain idempotent.
        connection.execute(MIGRATIONS[-1].read_text(encoding="utf-8"))
        sequence = connection.execute(
            """
            SELECT sequence
            FROM volpred_ops.effect_outbox
            WHERE effect_id = 'effect-postgres-1'
            """
        ).fetchone()[0]
        connection.execute(
            """
            ALTER TABLE volpred_ops.effect_attempt_receipts
            DISABLE TRIGGER require_effect_authority_grant
            """
        )
        try:
            barrier = Barrier(2)

            def insert_delivered(attempt: int) -> None:
                with psycopg.connect(
                    postgres_effect_dsn,
                    autocommit=True,
                ) as worker_connection:
                    barrier.wait()
                    worker_connection.execute(
                        """
                        INSERT INTO volpred_ops.effect_attempt_receipts (
                          effect_id, outbox_sequence, attempt_count, worker_id,
                          claim_token_sha256, reported_outcome, disposition,
                          acknowledgement_kind, acknowledgement_target_ref,
                          reason_code, evidence_ref, evidence_sha256, retry_at,
                          recorded_at
                        )
                        VALUES (
                          'effect-postgres-1', %s, %s, 'test-worker',
                          %s, 'acknowledged', 'delivered',
                          'telegram.message.readback', 'telegram:owner-chat',
                          NULL, %s, %s, NULL, clock_timestamp()
                        )
                        """,
                        (
                            sequence,
                            attempt,
                            hashlib.sha256(
                                f"token-{attempt}".encode()
                            ).hexdigest(),
                            f"test:duplicate-effect:{attempt}",
                            hashlib.sha256(
                                f"evidence-{attempt}".encode()
                            ).hexdigest(),
                        ),
                    )

            with ThreadPoolExecutor(max_workers=2) as executor:
                list(executor.map(insert_delivered, (1, 2)))
        finally:
            connection.execute(
                """
                ALTER TABLE volpred_ops.effect_attempt_receipts
                ENABLE TRIGGER require_effect_authority_grant
                """
            )

        # Replaying after a captured violation must not duplicate the backfill
        # or advance its transactional cursor.
        connection.execute(MIGRATIONS[-1].read_text(encoding="utf-8"))
        event = connection.execute(
            """
            SELECT sequence, effect_id, first_delivered_attempt_count,
                   offending_attempt_count
            FROM volpred_ops.legacy_retirement_duplicate_effect_events
            """
        ).fetchone()
        assert event[0:2] == (1, "effect-postgres-1")
        assert {event[2], event[3]} == {1, 2}
        assert event[2] != event[3]

        connection.execute("SET ROLE service_role")
        snapshot = connection.execute(
            """
            SELECT public.volpred_read_duplicate_effect_retirement_events(0)
            """
        ).fetchone()[0]
        assert snapshot["schema_version"] == (
            "duplicate-effect-retirement-events.v1"
        )
        assert snapshot["after_sequence"] == 0
        assert snapshot["high_watermark"] == 1
        assert len(snapshot["events"]) == 1
        assert {
            snapshot["events"][0]["first_delivered_attempt_count"],
            snapshot["events"][0]["offending_attempt_count"],
        } == {1, 2}
        empty = connection.execute(
            """
            SELECT public.volpred_read_duplicate_effect_retirement_events(1)
            """
        ).fetchone()[0]
        assert empty["events"] == []
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                SELECT *
                FROM volpred_ops.legacy_retirement_duplicate_effect_events
                """
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                SELECT *
                FROM volpred_ops.legacy_retirement_duplicate_effect_head
                """
            )

    for role in ("anon", "authenticated"):
        with psycopg.connect(
            postgres_effect_dsn,
            autocommit=True,
        ) as connection:
            connection.execute(f"SET ROLE {role}")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    """
                    SELECT public.volpred_read_duplicate_effect_retirement_events(0)
                    """
                )


def test_duplicate_effect_sequence_does_not_gap_after_transaction_rollback(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    _delivery(postgres_effect_dsn).request(_request())
    with psycopg.connect(postgres_effect_dsn, autocommit=True) as connection:
        outbox_sequence = connection.execute(
            """
            SELECT sequence
            FROM volpred_ops.effect_outbox
            WHERE effect_id = 'effect-postgres-1'
            """
        ).fetchone()[0]
        connection.execute(
            """
            ALTER TABLE volpred_ops.effect_attempt_receipts
            DISABLE TRIGGER require_effect_authority_grant
            """
        )
        try:
            connection.execute(
                """
                INSERT INTO volpred_ops.effect_attempt_receipts (
                  effect_id, outbox_sequence, attempt_count, worker_id,
                  claim_token_sha256, reported_outcome, disposition,
                  acknowledgement_kind, acknowledgement_target_ref,
                  reason_code, evidence_ref, evidence_sha256, retry_at,
                  recorded_at
                )
                VALUES (
                  'effect-postgres-1', %s, 3, 'test-worker',
                  %s, 'acknowledged', 'delivered',
                  'telegram.message.readback', 'telegram:owner-chat',
                  NULL, 'test:original', %s, NULL, clock_timestamp()
                )
                """,
                (
                    outbox_sequence,
                    hashlib.sha256(b"token-3").hexdigest(),
                    hashlib.sha256(b"evidence-3").hexdigest(),
                ),
            )
            with (
                pytest.raises(RuntimeError, match="rollback duplicate"),
                connection.transaction(),
            ):
                connection.execute(
                    """
                    INSERT INTO volpred_ops.effect_attempt_receipts (
                      effect_id, outbox_sequence, attempt_count, worker_id,
                      claim_token_sha256, reported_outcome, disposition,
                      acknowledgement_kind, acknowledgement_target_ref,
                      reason_code, evidence_ref, evidence_sha256, retry_at,
                      recorded_at
                    )
                    VALUES (
                      'effect-postgres-1', %s, 2, 'test-worker',
                      %s, 'acknowledged', 'delivered',
                      'telegram.message.readback', 'telegram:owner-chat',
                      NULL, 'test:rolled-back', %s, NULL, clock_timestamp()
                    )
                    """,
                    (
                        outbox_sequence,
                        hashlib.sha256(b"token-2").hexdigest(),
                        hashlib.sha256(b"evidence-2").hexdigest(),
                    ),
                )
                raise RuntimeError("rollback duplicate")
            connection.execute(
                """
                INSERT INTO volpred_ops.effect_attempt_receipts (
                  effect_id, outbox_sequence, attempt_count, worker_id,
                  claim_token_sha256, reported_outcome, disposition,
                  acknowledgement_kind, acknowledgement_target_ref,
                  reason_code, evidence_ref, evidence_sha256, retry_at,
                  recorded_at
                )
                VALUES (
                  'effect-postgres-1', %s, 1, 'test-worker',
                  %s, 'acknowledged', 'delivered',
                  'telegram.message.readback', 'telegram:owner-chat',
                  NULL, 'test:committed', %s, NULL, clock_timestamp()
                )
                """,
                (
                    outbox_sequence,
                    hashlib.sha256(b"token-1").hexdigest(),
                    hashlib.sha256(b"evidence-1").hexdigest(),
                ),
            )
        finally:
            connection.execute(
                """
                ALTER TABLE volpred_ops.effect_attempt_receipts
                ENABLE TRIGGER require_effect_authority_grant
                """
            )
        rows = connection.execute(
            """
            SELECT sequence, offending_attempt_count
            FROM volpred_ops.legacy_retirement_duplicate_effect_events
            ORDER BY sequence
            """
        ).fetchall()
        connection.execute("SET ROLE service_role")
        head = connection.execute(
            """
            SELECT (
              public.volpred_read_duplicate_effect_retirement_events(0)
            )->>'high_watermark'
            """
        ).fetchone()[0]
    assert rows == [(1, 1)]
    assert head == "1"


def test_conflicting_replay_does_not_append_an_outbox_row(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    delivery = _delivery(postgres_effect_dsn)
    delivery.request(_request())

    with pytest.raises(EffectRequestConflict, match="original payload"):
        delivery.request(_request(payload_sha256="b" * 64))

    with psycopg.connect(postgres_effect_dsn) as connection:
        counts = connection.execute(
            """
            SELECT
              (SELECT count(*) FROM volpred_ops.effect_requests),
              (SELECT count(*) FROM volpred_ops.effect_outbox)
            """
        ).fetchone()
    assert counts == (1, 1)


def test_equivalent_replay_survives_later_work_version_progress(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    first = _delivery(postgres_effect_dsn).request(_request())
    with psycopg.connect(postgres_effect_dsn, autocommit=True) as connection:
        connection.execute(
            "UPDATE volpred_ops.work_items SET version = 2 "
            "WHERE id = 'work-effect-1'"
        )

    replay = _delivery(
        postgres_effect_dsn,
        effect_id="unused-after-progress",
    ).request(_request())

    assert replay == first


def test_concurrent_request_replays_create_one_effect_and_one_outbox(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    deliveries = (
        _delivery(postgres_effect_dsn, effect_id="effect-concurrent-a"),
        _delivery(postgres_effect_dsn, effect_id="effect-concurrent-b"),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        views = tuple(executor.map(lambda item: item.request(_request()), deliveries))

    with psycopg.connect(postgres_effect_dsn) as connection:
        counts = connection.execute(
            """
            SELECT
              (SELECT count(*) FROM volpred_ops.effect_requests),
              (SELECT count(*) FROM volpred_ops.effect_outbox)
            """
        ).fetchone()

    assert views[0] == views[1]
    assert views[0].id in {"effect-concurrent-a", "effect-concurrent-b"}
    assert counts == (1, 1)


def test_outbox_insert_failure_rolls_back_effect_request(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    with psycopg.connect(postgres_effect_dsn, autocommit=True) as connection:
        connection.execute(
            """
            CREATE FUNCTION volpred_ops.fail_effect_outbox_insert()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              RAISE EXCEPTION 'injected outbox failure';
            END;
            $$
            """
        )
        connection.execute(
            """
            CREATE TRIGGER fail_effect_outbox_insert
            BEFORE INSERT ON volpred_ops.effect_outbox
            FOR EACH ROW
            EXECUTE FUNCTION volpred_ops.fail_effect_outbox_insert()
            """
        )
    try:
        with pytest.raises(psycopg.errors.RaiseException, match="outbox failure"):
            _delivery(postgres_effect_dsn).request(_request())
        with psycopg.connect(postgres_effect_dsn) as connection:
            counts = connection.execute(
                """
                SELECT
                  (SELECT count(*) FROM volpred_ops.effect_requests),
                  (SELECT count(*) FROM volpred_ops.effect_outbox)
                """
            ).fetchone()
        assert counts == (0, 0)
    finally:
        with psycopg.connect(
            postgres_effect_dsn,
            autocommit=True,
        ) as connection:
            connection.execute(
                "DROP TRIGGER fail_effect_outbox_insert "
                "ON volpred_ops.effect_outbox"
            )
            connection.execute(
                "DROP FUNCTION volpred_ops.fail_effect_outbox_insert()"
            )


def test_concurrent_workers_claim_one_outbox_row(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    _delivery(postgres_effect_dsn).request(_request())
    deliveries = (
        _delivery(postgres_effect_dsn, token="claim-a"),
        _delivery(postgres_effect_dsn, token="claim-b"),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = tuple(
            executor.map(
                lambda pair: pair[0].claim_outbox(
                    worker_id=pair[1],
                    lease_seconds=300,
                    effect_kinds=TELEGRAM_EFFECT_KINDS,
                ),
                zip(deliveries, ("worker-a", "worker-b"), strict=True),
            )
        )

    acquired = [claim for claim in claims if claim is not None]
    assert len(acquired) == 1
    assert acquired[0].attempt_count == 1
    assert {claim.token for claim in acquired} <= {"claim-a", "claim-b"}


def test_outbox_claim_routes_only_effects_supported_by_the_provider(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    _seed_work(postgres_effect_dsn, work_id="work-effect-2")
    telegram = _delivery(
        postgres_effect_dsn,
        effect_id="effect-telegram-first",
    ).request(_request())
    publisher = _delivery(
        postgres_effect_dsn,
        effect_id="effect-publisher-second",
    ).request(
        _request(
            idempotency_key="effect:work-effect-2:publisher:sync",
            work_item_id="work-effect-2",
            effect_kind="publisher.article.supabase.sync",
            target_ref="supabase:articles/mile_routed",
            acknowledgement=AcknowledgementExpectation(
                kind="publisher.article.supabase.readback",
                target_ref="supabase:articles/mile_routed",
            ),
        )
    )

    publisher_claim = _delivery(
        postgres_effect_dsn,
        token="publisher-claim",
    ).claim_outbox(
        worker_id="effect-worker:publisher",
        lease_seconds=300,
        effect_kinds=frozenset({"publisher.article.supabase.sync"}),
    )
    telegram_claim = _delivery(
        postgres_effect_dsn,
        token="telegram-claim",
    ).claim_outbox(
        worker_id="effect-worker:telegram",
        lease_seconds=300,
        effect_kinds=TELEGRAM_EFFECT_KINDS,
    )

    assert publisher_claim is not None
    assert publisher_claim.effect_id == publisher.id
    assert telegram_claim is not None
    assert telegram_claim.effect_id == telegram.id
    with pytest.raises(ValueError, match="effect kind"):
        _delivery(postgres_effect_dsn).claim_outbox(
            worker_id="effect-worker:invalid",
            lease_seconds=300,
            effect_kinds=frozenset(),
        )


def test_effect_family_claim_rpc_removes_unfiltered_escape_hatch(
    postgres_effect_dsn: str,
) -> None:
    with psycopg.connect(postgres_effect_dsn) as connection:
        security = connection.execute(
            """
            SELECT
              to_regprocedure(
                'volpred_ops.claim_effect_outbox(text,integer,text)'
              ) IS NULL,
              has_function_privilege(
                'volpred_ops_worker',
                'volpred_ops.claim_effect_outbox('
                  'text,integer,text,text[])',
                'EXECUTE'
              ),
              NOT has_function_privilege(
                'public',
                'volpred_ops.claim_effect_outbox('
                  'text,integer,text,text[])',
                'EXECUTE'
              ),
              procedure.proowner = (
                SELECT oid FROM pg_roles
                WHERE rolname = 'volpred_ops_definer'
              ),
              procedure.prosecdef,
              procedure.proconfig @>
                ARRAY['search_path=pg_catalog, volpred_ops']
            FROM pg_proc AS procedure
            JOIN pg_namespace AS namespace
              ON namespace.oid = procedure.pronamespace
            WHERE namespace.nspname = 'volpred_ops'
              AND procedure.proname = 'claim_effect_outbox'
            """
        ).fetchone()

    assert security == (True,) * 6


def test_expired_outbox_claim_is_recovered_with_database_clock(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    _delivery(postgres_effect_dsn).request(_request())
    first = _delivery(
        postgres_effect_dsn,
        token="stale-token",
    ).claim_outbox(
        worker_id="worker-a",
        lease_seconds=300,
        effect_kinds=TELEGRAM_EFFECT_KINDS,
    )
    assert first is not None

    with psycopg.connect(postgres_effect_dsn, autocommit=True) as connection:
        connection.execute(
            """
            UPDATE volpred_ops.effect_outbox
            SET claim_expires_at = clock_timestamp() - interval '1 second'
            WHERE effect_id = %s
            """,
            (first.effect_id,),
        )

    recovered = _delivery(
        postgres_effect_dsn,
        token="fresh-token",
    ).claim_outbox(
        worker_id="worker-b",
        lease_seconds=300,
        effect_kinds=TELEGRAM_EFFECT_KINDS,
    )
    assert recovered is not None
    assert recovered.effect_id == first.effect_id
    assert recovered.attempt_count == 2
    assert recovered.claimed_by == "worker-b"
    assert recovered.token == "fresh-token"


def test_request_fails_closed_on_unknown_or_stale_work_identity(
    postgres_effect_dsn: str,
) -> None:
    with pytest.raises(ValueError, match="unknown effect work item"):
        _delivery(postgres_effect_dsn).request(_request())

    _seed_work(postgres_effect_dsn)
    with psycopg.connect(postgres_effect_dsn, autocommit=True) as connection:
        connection.execute(
            "UPDATE volpred_ops.work_items SET version = 2 "
            "WHERE id = 'work-effect-1'"
        )
    with pytest.raises(ValueError, match="stale effect work item version"):
        _delivery(postgres_effect_dsn).request(_request())


def test_worker_uses_named_functions_but_cannot_mutate_or_read_claim_token(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    delivery = _delivery(postgres_effect_dsn)
    effect = delivery.request(_request())
    claim = delivery.claim_outbox(
        worker_id="effect-worker",
        lease_seconds=300,
        effect_kinds=TELEGRAM_EFFECT_KINDS,
    )
    assert claim is not None

    with _worker_connection(postgres_effect_dsn) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "DELETE FROM volpred_ops.effect_requests WHERE id = %s",
                (effect.id,),
            )
        connection.rollback()
        connection.execute("SET ROLE volpred_ops_worker")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT claim_token FROM volpred_ops.effect_outbox"
            ).fetchall()
        connection.rollback()
        connection.execute("SET ROLE volpred_ops_worker")
        columns = {
            description.name
            for description in connection.execute(
                "SELECT * FROM volpred_ops.effect_outbox_reads LIMIT 0"
            ).description
        }
    assert "claim_token" not in columns


def _acknowledged(**overrides: object) -> AcknowledgedEffect:
    outcome = AcknowledgedEffect(
        acknowledgement=AcknowledgementExpectation(
            kind="telegram.message.readback",
            target_ref="telegram:owner-chat",
        ),
        evidence_ref="telegram:message:4321",
        evidence_sha256="b" * 64,
    )
    return replace(outcome, **overrides)


def _failed(**overrides: object) -> FailedEffect:
    outcome = FailedEffect(
        reason_code="provider_timeout",
        evidence_ref="attempt-log:effect-postgres-1:1",
        evidence_sha256="c" * 64,
        retryable=True,
    )
    return replace(outcome, **overrides)


def _grant_authority(
    dsn: str,
    delivery: PostgresEffectDelivery,
    lease: EffectOutboxLease,
) -> EffectSettlementAuthority:
    with _worker_connection(dsn) as connection:
        existing = connection.execute(
            """
            SELECT request_sha256, outbox_claim_ref, primary_authority_ref
            FROM volpred_ops.effect_authority_grant_reads
            WHERE outbox_sequence = %s AND attempt_count = %s
            """,
            (lease.sequence, lease.attempt_count),
        ).fetchone()
    if existing is not None:
        return EffectSettlementAuthority(
            request_sha256=existing[0],
            outbox_claim_ref=existing[1],
            primary_authority_ref=existing[2],
        )

    primary = PrimaryAuthority(
        PostgresAuthorityStore(
            connection_factory=lambda: _worker_connection(dsn),
        ),
        token_factory=lambda: "primary-fence-effect-test",
    )
    primary_lease = primary.acquire(
        AuthorityRequest(
            authority_key="operations-core-primary",
            holder_ref="host:effect-test-primary",
            lease_seconds=300,
        )
    )
    request = _authority_request(
        command=EffectWorkerCommand(
            worker_id=lease.claimed_by,
            lease_seconds=300,
        ),
        primary_lease=primary_lease,
        lease=lease,
        effect=delivery.inspect(lease.effect_id),
    )
    grant = PostgresEffectAuthority(
        connection_factory=lambda: _worker_connection(dsn),
    ).authorize(request)
    return EffectSettlementAuthority(
        request_sha256=grant.request_sha256,
        outbox_claim_ref=grant.outbox_claim_ref,
        primary_authority_ref=grant.primary_authority_ref,
    )


def _settle(
    dsn: str,
    delivery: PostgresEffectDelivery,
    *,
    lease: EffectOutboxLease,
    outcome: AcknowledgedEffect | FailedEffect,
    authority: EffectSettlementAuthority | None = None,
):
    granted = _grant_authority(dsn, delivery, lease)
    return delivery.settle_outbox(
        lease=lease,
        outcome=outcome,
        authority=authority or granted,
    )


def test_durable_payload_write_is_hash_bound_replay_safe_and_private(
    postgres_effect_dsn: str,
) -> None:
    store = PostgresEffectPayloadStore(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn),
    )
    payload = b'{"schema_version":"email-notification.v1","subject":"hello"}'
    first = store.write(
        payload_ref="effect-payload:work-effect-1:email",
        payload=payload,
        writer_ref="work-coordinator:effect-test",
    )
    replay = store.write(
        payload_ref=first.payload_ref,
        payload=payload,
        writer_ref="work-coordinator:effect-test",
    )

    assert replay == first
    assert first.byte_size == len(payload)
    assert store.read(first.payload_ref) == payload
    with pytest.raises(EffectPayloadConflict, match="original bytes"):
        store.write(
            payload_ref=first.payload_ref,
            payload=b"different",
            writer_ref="work-coordinator:effect-test",
        )

    with _worker_connection(postgres_effect_dsn) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT payload_bytes FROM volpred_ops.effect_payloads"
            ).fetchall()
        connection.rollback()
        connection.execute("SET ROLE volpred_ops_worker")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT * FROM volpred_ops.effect_payload_reads"
            ).fetchall()


def test_effect_request_requires_matching_durable_payload(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    payload = b"durable effect body"
    payload_store = PostgresEffectPayloadStore(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn),
    )
    view = payload_store.write(
        payload_ref="effect-payload:work-effect-1:telegram",
        payload=payload,
        writer_ref="work-coordinator:effect-test",
    )
    request = _request(
        payload_ref=view.payload_ref,
        payload_sha256=view.payload_sha256,
    )

    assert _delivery(postgres_effect_dsn).request(request).payload_ref == (
        view.payload_ref
    )

    _seed_work(postgres_effect_dsn, work_id="work-effect-2")
    with pytest.raises(ValueError, match="durable bytes"):
        _delivery(
            postgres_effect_dsn,
            effect_id="effect-postgres-2",
        ).request(
            replace(
                request,
                idempotency_key="effect:work-effect-2:telegram",
                work_item_id="work-effect-2",
                payload_sha256="0" * 64,
            )
        )


def test_primary_authority_fences_concurrent_and_stale_holders(
    postgres_effect_dsn: str,
) -> None:
    first = PrimaryAuthority(
        PostgresAuthorityStore(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            ),
        ),
        token_factory=lambda: "primary-token-a",
    )
    second = PrimaryAuthority(
        PostgresAuthorityStore(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            ),
        ),
        token_factory=lambda: "primary-token-b",
    )
    request = AuthorityRequest(
        authority_key="operations-core-primary",
        holder_ref="host:primary-a",
        lease_seconds=300,
    )
    lease = first.acquire(request)
    replay = first.acquire(request)
    assert replay == lease
    assert lease.epoch == 1
    assert "primary-token-a" not in repr(
        first.authorize(
            WriteIntent(
                authority_key=lease.authority_key,
                holder_ref=lease.holder_ref,
                epoch=lease.epoch,
                fencing_token=lease.fencing_token,
                request_sha256="e" * 64,
                resource_ref="changeset:shadow-1",
            )
        )
    )

    with pytest.raises(ValueError, match="already held"):
        second.acquire(replace(request, holder_ref="host:primary-b"))

    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        connection.execute(
            """
            UPDATE volpred_ops.primary_authority_leases
            SET acquired_at = clock_timestamp() - interval '2 seconds',
                lease_expires_at =
                  clock_timestamp() - interval '1 second'
            WHERE authority_key = %s
            """,
            (lease.authority_key,),
        )
    replacement = second.acquire(
        replace(request, holder_ref="host:primary-b")
    )
    assert replacement.epoch == 2
    with pytest.raises(ValueError, match="lease lost|epoch mismatch"):
        first.authorize(
            WriteIntent(
                authority_key=lease.authority_key,
                holder_ref=lease.holder_ref,
                epoch=lease.epoch,
                fencing_token=lease.fencing_token,
                request_sha256="f" * 64,
                resource_ref="changeset:stale",
            )
        )

    receipt = second.release(replacement)
    assert receipt.epoch == 2
    assert second.release(replacement) == receipt


def test_primary_authority_owner_attestation_is_typed_and_read_only(
    postgres_effect_dsn: str,
) -> None:
    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        security = connection.execute(
            """
            SELECT
              has_function_privilege(
                'service_role',
                'public.volpred_read_primary_authority_owner()',
                'EXECUTE'
              ),
              has_function_privilege(
                'anon',
                'public.volpred_read_primary_authority_owner()',
                'EXECUTE'
              ),
              has_table_privilege(
                'service_role',
                'volpred_ops.primary_authority_ownership',
                'SELECT,INSERT,UPDATE,DELETE'
              ),
              (
                SELECT relrowsecurity AND relforcerowsecurity
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'volpred_ops'
                  AND relation.relname = 'primary_authority_ownership'
              ),
              (
                SELECT procedure.prosecdef
                  AND procedure.proowner = (
                    SELECT oid
                    FROM pg_roles
                    WHERE rolname = 'volpred_ops_definer'
                  )
                FROM pg_proc AS procedure
                WHERE procedure.oid =
                  'public.volpred_read_primary_authority_owner()'::regprocedure
              )
            """
        ).fetchone()
        connection.execute("SET ROLE service_role")
        payload = connection.execute(
            "SELECT public.volpred_read_primary_authority_owner()"
        ).fetchone()[0]

    assert security == (True, False, False, True, True)
    assert payload["schema_version"] == "primary-authority-owner.v1"
    assert payload["capability"] == "operations-core-primary"
    assert payload["authority_key"] == "operations-core-primary"
    assert payload["owner"] == "operations_core"
    assert payload["generation"] == 1
    assert payload["contract_ref"] == "primary-authority-contract.v1"
    assert datetime.fromisoformat(payload["attested_at"]).tzinfo is not None


def test_commit_authority_atomically_verifies_both_leases(
    postgres_effect_dsn: str,
) -> None:
    work_lease, running = _seed_running_work(postgres_effect_dsn)
    primary = PrimaryAuthority(
        PostgresAuthorityStore(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            ),
        ),
        token_factory=lambda: "primary-commit-token",
    )
    primary_lease = primary.acquire(
        AuthorityRequest(
            authority_key="operations-core-primary",
            holder_ref="host:commit-primary",
            lease_seconds=300,
        )
    )
    authority = PostgresCommitAuthority(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn),
        primary_lease=primary_lease,
    )
    request = _commit_authority_request(
        work_id=running.id,
        work_version=running.version,
        work_lease_token=work_lease.token,
        primary_fencing_token=primary_lease.fencing_token,
    )

    grant = authority.authorize(request)
    assert authority.authorize(request) == grant
    assert grant.request_sha256 == request.request_sha256
    assert grant.work_lease_ref == (
        f"work-lease:{running.id}:v{running.version}"
    )
    assert grant.primary_authority_ref == (
        "primary-authority:operations-core-primary:epoch-1"
    )

    with psycopg.connect(postgres_effect_dsn) as connection:
        durable = connection.execute(
            """
            SELECT
              proposal_sha256, work_item_id, work_item_version,
              work_holder_ref, commit_worker_ref, repository,
              expected_head, work_lease_ref, primary_authority_ref
            FROM volpred_ops.commit_authority_grants
            WHERE request_sha256 = %s
            """,
            (request.request_sha256,),
        ).fetchone()
    assert durable == (
        request.proposal_sha256,
        running.id,
        running.version,
        "agent:change-author",
        request.actor,
        request.repository,
        request.expected_head,
        grant.work_lease_ref,
        grant.primary_authority_ref,
    )
    assert work_lease.token not in repr(durable)
    assert primary_lease.fencing_token not in repr(durable)


@pytest.mark.parametrize(
    ("lost_fence", "message"),
    [
        ("work_lease", "WorkLease is stale"),
        ("commit_owner", "commit ownership lost"),
        ("primary_authority", "Primary Authority"),
    ],
)
def test_git_actuator_revalidates_existing_database_grant_at_mutation_boundary(
    postgres_effect_dsn: str,
    tmp_path: Path,
    lost_fence: str,
    message: str,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ("git", "-C", str(repo), "init", "-b", "main"),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ("git", "-C", str(repo), "config", "user.name", "Fence Test"),
        check=True,
    )
    subprocess.run(
        (
            "git",
            "-C",
            str(repo),
            "config",
            "user.email",
            "fence-test@example.invalid",
        ),
        check=True,
    )
    target = repo / "tracked.txt"
    target.write_text("base\n", encoding="utf-8")
    subprocess.run(
        ("git", "-C", str(repo), "add", "tracked.txt"),
        check=True,
    )
    subprocess.run(
        ("git", "-C", str(repo), "commit", "-m", "base"),
        check=True,
        capture_output=True,
        text=True,
    )
    base_commit = _git_text(repo, "rev-parse", "HEAD")
    target.write_text("candidate\n", encoding="utf-8")

    work_lease, running = _seed_running_work(
        postgres_effect_dsn,
        work_id=f"work-commit-revalidation-{lost_fence}",
        lease_token=f"work-lease-revalidation-{lost_fence}",
    )
    primary = PrimaryAuthority(
        PostgresAuthorityStore(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            ),
        ),
        token_factory=lambda: f"primary-revalidation-{lost_fence}",
    )
    primary_lease = primary.acquire(
        AuthorityRequest(
            authority_key="operations-core-primary",
            holder_ref=f"host:revalidation-{lost_fence}",
            lease_seconds=300,
        )
    )
    delegate = PostgresCommitAuthority(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn),
        primary_lease=primary_lease,
    )

    class FenceDroppingAuthority:
        def __init__(self) -> None:
            self.calls = 0

        def authorize(self, request: CommitAuthorityRequest):
            self.calls += 1
            grant = delegate.authorize(request)
            if self.calls == 1:
                with psycopg.connect(
                    postgres_effect_dsn,
                    autocommit=True,
                ) as connection:
                    if lost_fence == "work_lease":
                        connection.execute(
                            """
                            UPDATE volpred_ops.work_items
                            SET claim_expires_at =
                              clock_timestamp() - interval '1 second'
                            WHERE id = %s
                            """,
                            (running.id,),
                        )
                    elif lost_fence == "commit_owner":
                        connection.execute(
                            """
                            UPDATE volpred_ops.commit_owners
                            SET generation = generation + 1
                            WHERE capability = 'git.commit'
                            """
                        )
                    else:
                        connection.execute(
                            """
                            UPDATE volpred_ops.primary_authority_leases
                            SET acquired_at =
                                  clock_timestamp() - interval '2 seconds',
                                lease_expires_at =
                                  clock_timestamp() - interval '1 second'
                            WHERE authority_key = %s
                            """,
                            (primary_lease.authority_key,),
                        )
            return grant

        def recover(self, request: CommitAuthorityRequest):
            return delegate.recover(request)

        def abandon(self, request, grant, *, reason):
            return delegate.abandon(request, grant, reason=reason)

    authority = FenceDroppingAuthority()
    command = CommitActuation(
        proposal_sha256="a" * 64,
        work_item_id=running.id,
        work_item_version=running.version,
        commit_owner_generation=2,
        work_lease_token=work_lease.token,
        primary_fencing_token=primary_lease.fencing_token,
        repository=str(repo),
        expected_head=base_commit,
        exact_paths=("tracked.txt",),
        content_hashes=(
            ContentHash(
                path="tracked.txt",
                sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            ),
        ),
        message="[change-delivery] mutation-boundary fence",
        actor="commit-worker:postgres-revalidation",
    )

    with pytest.raises(CommitActuatorBlocked, match=message):
        GitCommitActuator(
            clock=lambda: datetime.now(timezone.utc),
            authority=authority,
        ).commit(command)

    assert authority.calls == 2
    assert _git_text(repo, "rev-parse", "HEAD") == base_commit
    assert _git_text(repo, "diff", "--cached", "--name-only") == ""
    with psycopg.connect(postgres_effect_dsn) as connection:
        grant_count = connection.execute(
            "SELECT count(*) FROM volpred_ops.commit_authority_grants"
        ).fetchone()[0]
    assert grant_count == 1


def test_commit_authority_service_rpc_returns_token_redacted_grant(
    postgres_effect_dsn: str,
) -> None:
    _ensure_commit_owner(postgres_effect_dsn)
    work_lease, running = _seed_running_work(postgres_effect_dsn)
    primary = PrimaryAuthority(
        PostgresAuthorityStore(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            ),
        ),
        token_factory=lambda: "primary-commit-rpc-token",
    )
    primary_lease = primary.acquire(
        AuthorityRequest(
            authority_key="operations-core-primary",
            holder_ref="host:commit-rpc-primary",
            lease_seconds=300,
        )
    )
    request = _commit_authority_request(
        work_id=running.id,
        work_version=running.version,
        work_lease_token=work_lease.token,
        primary_fencing_token=primary_lease.fencing_token,
    )

    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("SET ROLE service_role")
        grant = connection.execute(
            """
            SELECT public.volpred_authorize_commit_write(
              %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s
            )
            """,
            (
                primary_lease.authority_key,
                primary_lease.holder_ref,
                primary_lease.epoch,
                primary_lease.fencing_token,
                request.request_sha256,
                request.proposal_sha256,
                request.work_item_id,
                request.work_item_version,
                request.commit_owner_generation,
                request.work_lease_token,
                request.repository,
                request.expected_head,
                request.actor,
            ),
        ).fetchone()[0]
        replay = connection.execute(
            """
            SELECT public.volpred_authorize_commit_write(
              %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s
            )
            """,
            (
                primary_lease.authority_key,
                primary_lease.holder_ref,
                primary_lease.epoch,
                primary_lease.fencing_token,
                request.request_sha256,
                request.proposal_sha256,
                request.work_item_id,
                request.work_item_version,
                request.commit_owner_generation,
                request.work_lease_token,
                request.repository,
                request.expected_head,
                request.actor,
            ),
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT * FROM volpred_ops.commit_authority_grants"
            )

    assert replay == grant
    assert grant["request_sha256"] == request.request_sha256
    assert grant["commit_owner_generation"] == 2
    assert grant["commit_owner_ref"] == (
        "commit-owner:git.commit:generation-2"
    )
    assert work_lease.token not in repr(grant)
    assert primary_lease.fencing_token not in repr(grant)


def test_commit_settlement_service_rpc_returns_token_redacted_receipt(
    postgres_effect_dsn: str,
) -> None:
    work_lease, running = _seed_running_work(postgres_effect_dsn)
    primary = PrimaryAuthority(
        PostgresAuthorityStore(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            ),
        ),
        token_factory=lambda: "primary-commit-settlement-rpc-token",
    )
    primary_lease = primary.acquire(
        AuthorityRequest(
            authority_key="operations-core-primary",
            holder_ref="host:commit-settlement-rpc-primary",
            lease_seconds=300,
        )
    )
    request = _commit_authority_request(
        work_id=running.id,
        work_version=running.version,
        work_lease_token=work_lease.token,
        primary_fencing_token=primary_lease.fencing_token,
    )
    grant = PostgresCommitAuthority(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn),
        primary_lease=primary_lease,
    ).authorize(request)
    command = _commit_settlement(request, grant)

    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("SET ROLE service_role")
        receipt = connection.execute(
            """
            SELECT public.volpred_settle_commit_write(
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                primary_lease.authority_key,
                primary_lease.holder_ref,
                primary_lease.epoch,
                command.primary_fencing_token,
                command.actuation.authority_request_sha256,
                command.actuation.commit_owner_generation,
                command.actuation.commit_owner_ref,
                commit_settlement_sha256(command),
                command.change_set_id,
                command.work_lease_token,
                command.actuation.work_lease_ref,
                command.actuation.primary_authority_ref,
                command.repository,
                command.actuation.commit_sha,
                command.actuation.parent_sha,
                Jsonb(list(command.actuation.exact_paths)),
                command.actuation.actor,
                command.actuation.observed_at,
                command.actuation.status,
            ),
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT * FROM volpred_ops.commit_delivery_receipts"
            )

    assert receipt["schema_version"] == "change-delivery-receipt.v1"
    assert receipt["status"] == "landed"
    assert receipt["change_set_id"] == command.change_set_id
    assert receipt["settlement_sha256"] == commit_settlement_sha256(
        command
    )
    assert receipt["commit_owner_generation"] == 2
    assert receipt["commit_owner_ref"] == (
        "commit-owner:git.commit:generation-2"
    )
    assert work_lease.token not in repr(receipt)
    assert primary_lease.fencing_token not in repr(receipt)


def test_work_read_model_service_rpc_returns_one_bounded_snapshot(
    postgres_effect_dsn: str,
) -> None:
    work_id = "work-service-read-model-1"
    _seed_work(postgres_effect_dsn, work_id=work_id)

    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("SET ROLE service_role")
        snapshot = connection.execute(
            "SELECT public.volpred_read_work_snapshot(%s)",
            (work_id,),
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT * FROM volpred_ops.work_item_reads"
            )

    assert snapshot["schema_version"] == "work-snapshot.v1"
    assert [item["id"] for item in snapshot["items"]] == [work_id]
    assert [event["kind"] for event in snapshot["events"]] == [
        "submitted"
    ]
    assert snapshot["checkpoints"] == []
    assert snapshot["receipts"] == []

    for role in ("anon", "authenticated"):
        with psycopg.connect(
            postgres_effect_dsn,
            autocommit=True,
        ) as connection:
            connection.execute(f"SET ROLE {role}")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    "SELECT public.volpred_read_work_snapshot(%s)",
                    (work_id,),
                )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("work_lease_token", "stale-work-token", "WorkLease is stale"),
        (
            "primary_fencing_token",
            "stale-primary-token",
            "Primary Authority lease lost",
        ),
    ],
)
def test_commit_authority_rejects_stale_fences(
    postgres_effect_dsn: str,
    field: str,
    value: str,
    message: str,
) -> None:
    work_lease, running = _seed_running_work(postgres_effect_dsn)
    primary = PrimaryAuthority(
        PostgresAuthorityStore(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            ),
        ),
        token_factory=lambda: "primary-commit-token",
    )
    primary_lease = primary.acquire(
        AuthorityRequest(
            authority_key="operations-core-primary",
            holder_ref="host:commit-primary",
            lease_seconds=300,
        )
    )
    authority = PostgresCommitAuthority(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn),
        primary_lease=primary_lease,
    )
    request = _commit_authority_request(
        work_id=running.id,
        work_version=running.version,
        work_lease_token=work_lease.token,
        primary_fencing_token=primary_lease.fencing_token,
    )
    request = replace(request, **{field: value})
    request = replace(
        request,
        request_sha256=_authority_request_sha256(request),
    )

    with pytest.raises(CommitActuatorBlocked, match=message):
        authority.authorize(request)

    with psycopg.connect(postgres_effect_dsn) as connection:
        grant_count = connection.execute(
            "SELECT count(*) FROM volpred_ops.commit_authority_grants"
        ).fetchone()[0]
    assert grant_count == 0


def test_commit_authority_rejects_forged_request_hash_before_database(
    postgres_effect_dsn: str,
) -> None:
    work_lease, running = _seed_running_work(postgres_effect_dsn)
    primary = PrimaryAuthority(
        PostgresAuthorityStore(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            ),
        ),
        token_factory=lambda: "primary-commit-token",
    )
    primary_lease = primary.acquire(
        AuthorityRequest(
            authority_key="operations-core-primary",
            holder_ref="host:commit-primary",
            lease_seconds=300,
        )
    )
    authority = PostgresCommitAuthority(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn),
        primary_lease=primary_lease,
    )
    request = _commit_authority_request(
        work_id=running.id,
        work_version=running.version,
        work_lease_token=work_lease.token,
        primary_fencing_token=primary_lease.fencing_token,
    )

    with pytest.raises(CommitActuatorBlocked, match="request hash"):
        authority.authorize(replace(request, repository="/tmp/forged"))

    with psycopg.connect(postgres_effect_dsn) as connection:
        grant_count = connection.execute(
            "SELECT count(*) FROM volpred_ops.commit_authority_grants"
        ).fetchone()[0]
    assert grant_count == 0


def test_commit_owner_rollback_blocks_unsettled_generation(
    postgres_effect_dsn: str,
) -> None:
    work_lease, running = _seed_running_work(postgres_effect_dsn)
    primary = PrimaryAuthority(
        PostgresAuthorityStore(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            ),
        ),
        token_factory=lambda: "primary-commit-token",
    )
    primary_lease = primary.acquire(
        AuthorityRequest(
            authority_key="operations-core-primary",
            holder_ref="host:commit-primary",
            lease_seconds=300,
        )
    )
    request = _commit_authority_request(
        work_id=running.id,
        work_version=running.version,
        work_lease_token=work_lease.token,
        primary_fencing_token=primary_lease.fencing_token,
    )
    PostgresCommitAuthority(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn),
        primary_lease=primary_lease,
    ).authorize(request)
    owner_store = PostgresCommitOwnerStore(
        connection_factory=lambda: _approver_connection(
            postgres_effect_dsn
        )
    )

    with pytest.raises(
        CommitOwnershipLost,
        match="zero unsettled grants",
    ):
        owner_store.transfer_owner(
            expected_owner="operations_core",
            expected_generation=2,
            target_owner="legacy",
            actor_ref="approver:blocked-rollback",
            reason="must not strand an unsettled commit",
            rollback_of_generation=2,
        )

    owner = owner_store.read_owner()
    assert (owner.owner, owner.generation) == ("operations_core", 2)


def test_commit_settlement_revalidates_both_leases_and_replays_receipt(
    postgres_effect_dsn: str,
) -> None:
    work_lease, running = _seed_running_work(postgres_effect_dsn)
    primary = PrimaryAuthority(
        PostgresAuthorityStore(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            ),
        ),
        token_factory=lambda: "primary-commit-token",
    )
    primary_lease = primary.acquire(
        AuthorityRequest(
            authority_key="operations-core-primary",
            holder_ref="host:commit-primary",
            lease_seconds=300,
        )
    )
    authority = PostgresCommitAuthority(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn),
        primary_lease=primary_lease,
    )
    request = _commit_authority_request(
        work_id=running.id,
        work_version=running.version,
        work_lease_token=work_lease.token,
        primary_fencing_token=primary_lease.fencing_token,
    )
    grant = authority.authorize(request)
    command = _commit_settlement(request, grant)
    settlement = PostgresCommitSettlement(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn),
        primary_lease=primary_lease,
    )

    receipt = settlement.settle(command)
    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        connection.execute(
            """
            UPDATE volpred_ops.work_items
            SET claim_expires_at = clock_timestamp() - interval '1 second'
            WHERE id = %s
            """,
            (running.id,),
        )
        connection.execute(
            """
            UPDATE volpred_ops.primary_authority_leases
            SET acquired_at = clock_timestamp() - interval '2 seconds',
                lease_expires_at = clock_timestamp() - interval '1 second'
            WHERE authority_key = %s
            """,
            (primary_lease.authority_key,),
        )
    replay = settlement.settle(command)

    assert replay == receipt
    assert receipt.schema_version == "change-delivery-receipt.v1"
    assert receipt.status == "landed"
    assert receipt.change_set_id == command.change_set_id
    assert receipt.proposal_sha256 == request.proposal_sha256
    assert receipt.authority_request_sha256 == request.request_sha256
    assert receipt.commit_sha == command.actuation.commit_sha
    assert receipt.parent_sha == request.expected_head
    assert receipt.exact_paths == request.exact_paths
    assert receipt.settlement_ref == (
        f"change-delivery:{command.change_set_id}:"
        f"{command.actuation.commit_sha}"
    )
    with psycopg.connect(postgres_effect_dsn) as connection:
        durable = connection.execute(
            """
            SELECT settlement_sha256, change_set_id, commit_sha, parent_sha,
                   exact_paths, commit_worker_ref
            FROM volpred_ops.commit_delivery_receipts
            WHERE authority_request_sha256 = %s
            """,
            (request.request_sha256,),
        ).fetchone()
        receipt_count = connection.execute(
            "SELECT count(*) FROM volpred_ops.commit_delivery_receipts"
        ).fetchone()[0]
    assert durable == (
        receipt.settlement_sha256,
        command.change_set_id,
        command.actuation.commit_sha,
        command.actuation.parent_sha,
        list(command.actuation.exact_paths),
        request.actor,
    )
    assert receipt_count == 1
    assert work_lease.token not in repr(durable)
    assert primary_lease.fencing_token not in repr(durable)


@pytest.mark.parametrize("expired_lease", ["work", "primary"])
def test_commit_settlement_rejects_lease_loss_during_external_write(
    postgres_effect_dsn: str,
    expired_lease: str,
) -> None:
    work_lease, running = _seed_running_work(postgres_effect_dsn)
    primary = PrimaryAuthority(
        PostgresAuthorityStore(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            ),
        ),
        token_factory=lambda: "primary-commit-token",
    )
    primary_lease = primary.acquire(
        AuthorityRequest(
            authority_key="operations-core-primary",
            holder_ref="host:commit-primary",
            lease_seconds=300,
        )
    )
    request = _commit_authority_request(
        work_id=running.id,
        work_version=running.version,
        work_lease_token=work_lease.token,
        primary_fencing_token=primary_lease.fencing_token,
    )
    grant = PostgresCommitAuthority(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn),
        primary_lease=primary_lease,
    ).authorize(request)

    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        if expired_lease == "work":
            connection.execute(
                """
                UPDATE volpred_ops.work_items
                SET claim_expires_at = clock_timestamp() - interval '1 second'
                WHERE id = %s
                """,
                (running.id,),
            )
        else:
            connection.execute(
                """
                UPDATE volpred_ops.primary_authority_leases
                SET acquired_at = clock_timestamp() - interval '2 seconds',
                    lease_expires_at =
                      clock_timestamp() - interval '1 second'
                WHERE authority_key = %s
                """,
                (primary_lease.authority_key,),
            )

    settlement = PostgresCommitSettlement(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn),
        primary_lease=primary_lease,
    )
    expected = "WorkLease was lost|Primary Authority lease expired"
    with pytest.raises(CommitSettlementBlocked, match=expected):
        settlement.settle(_commit_settlement(request, grant))

    with psycopg.connect(postgres_effect_dsn) as connection:
        count = connection.execute(
            "SELECT count(*) FROM volpred_ops.commit_delivery_receipts"
        ).fetchone()[0]
    assert count == 0


def test_commit_settlement_conflicting_replay_fails_closed(
    postgres_effect_dsn: str,
) -> None:
    work_lease, running = _seed_running_work(postgres_effect_dsn)
    primary = PrimaryAuthority(
        PostgresAuthorityStore(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            ),
        ),
        token_factory=lambda: "primary-commit-token",
    )
    primary_lease = primary.acquire(
        AuthorityRequest(
            authority_key="operations-core-primary",
            holder_ref="host:commit-primary",
            lease_seconds=300,
        )
    )
    request = _commit_authority_request(
        work_id=running.id,
        work_version=running.version,
        work_lease_token=work_lease.token,
        primary_fencing_token=primary_lease.fencing_token,
    )
    grant = PostgresCommitAuthority(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn),
        primary_lease=primary_lease,
    ).authorize(request)
    settlement = PostgresCommitSettlement(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn),
        primary_lease=primary_lease,
    )
    command = _commit_settlement(request, grant)
    settlement.settle(command)

    with pytest.raises(CommitSettlementBlocked, match="conflicts"):
        settlement.settle(
            replace(command, change_set_id="changeset-conflicting-replay")
        )

    with psycopg.connect(postgres_effect_dsn) as connection:
        durable = connection.execute(
            """
            SELECT change_set_id
            FROM volpred_ops.commit_delivery_receipts
            """
        ).fetchall()
    assert durable == [(command.change_set_id,)]


def test_owned_change_shadow_path_settles_work_and_rehearses_rollback(
    postgres_effect_dsn: str,
    tmp_path: Path,
) -> None:
    repository = tmp_path / "canonical"
    workspace = tmp_path / "candidate"
    repository.mkdir()
    _git_text(repository, "init", "-b", "main")
    _git_text(repository, "config", "user.name", "Owned Change Test")
    _git_text(
        repository,
        "config",
        "user.email",
        "owned-change@example.invalid",
    )
    candidate_path = repository / "owned.txt"
    candidate_path.write_text("legacy\n", encoding="utf-8")
    _git_text(repository, "add", "owned.txt")
    _git_text(repository, "commit", "-m", "base")
    base_commit = _git_text(repository, "rev-parse", "HEAD")
    _git_text(
        repository,
        "worktree",
        "add",
        "-b",
        "shadow-owned-change",
        str(workspace),
        base_commit,
    )
    workspace_candidate = workspace / "owned.txt"
    workspace_candidate.write_text(
        "operations core\n",
        encoding="utf-8",
    )

    work_lease, running = _seed_running_work(
        postgres_effect_dsn,
        work_id="work-owned-change-shadow",
        lease_token="work-lease-owned-change-shadow",
        required_attestations=frozenset({"shadow-contract"}),
    )
    primary = PrimaryAuthority(
        PostgresAuthorityStore(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            )
        ),
        token_factory=lambda: "primary-owned-change-shadow",
    )
    primary_lease = primary.acquire(
        AuthorityRequest(
            authority_key="operations-core-primary",
            holder_ref="host:owned-change-shadow",
            lease_seconds=300,
        )
    )
    delivery = build_postgres_owned_change_delivery(
        lambda: _worker_connection(postgres_effect_dsn),
        primary_lease=primary_lease,
        clock=lambda: datetime.now(timezone.utc),
        change_set_id_factory=lambda: "changeset-owned-change-shadow",
        writer_cli=REPO_ROOT / "scripts" / "git_writer_lock.py",
        check_commands={"shadow-contract": ("git", "diff", "--check")},
    )
    proposal = ChangeSetProposal(
        idempotency_key="changeset:owned-change-shadow:attempt-1",
        work_item_id=running.id,
        work_item_version=running.version,
        base_commit=base_commit,
        workspace_ref=str(workspace),
        exact_paths=("owned.txt",),
        content_hashes=(
            ContentHash(
                path="owned.txt",
                sha256=hashlib.sha256(
                    workspace_candidate.read_bytes()
                ).hexdigest(),
            ),
        ),
        required_checks=(
            CheckEvidence(
                name="shadow-contract",
                status="passed",
                evidence_ref="pytest:owned-change-shadow",
            ),
        ),
        author_ref="agent:change-author",
        author_evidence_ref="execution:owned-change-shadow",
    )

    receipt = delivery.deliver(
        OwnedChangeCommand(
            proposal=proposal,
            work_lease_token=work_lease.token,
            primary_fencing_token=primary_lease.fencing_token,
            repository=str(repository),
            message="[codex] shadow owner-fenced ChangeSet",
        )
    )
    primary.release(primary_lease)

    assert receipt.owner.owner == "operations_core"
    assert receipt.owner.generation == 2
    assert receipt.delivery.commit_owner_generation == 2
    assert receipt.delivery.commit_owner_ref == (
        "commit-owner:git.commit:generation-2"
    )
    assert receipt.work_item.status == "succeeded"
    assert _git_text(repository, "show", "HEAD:owned.txt") == (
        "operations core"
    )
    assert _git_text(repository, "rev-parse", "HEAD") == (
        receipt.delivery.commit_sha
    )

    with psycopg.connect(postgres_effect_dsn) as connection:
        durable = connection.execute(
            """
            SELECT
              change_set.status,
              authority.commit_owner_generation,
              authority.commit_owner_ref,
              work.status,
              work.result_ref
            FROM volpred_ops.change_sets AS change_set
            JOIN volpred_ops.commit_authority_grants AS authority
              ON authority.request_sha256 =
                change_set.delivery_authority_request_sha256
            JOIN volpred_ops.work_items AS work
              ON work.id = change_set.work_item_id
            WHERE change_set.id = %s
            """,
            (receipt.delivery.change_set_id,),
        ).fetchone()
    assert durable == (
        "landed",
        2,
        "commit-owner:git.commit:generation-2",
        "succeeded",
        receipt.delivery.settlement_ref,
    )
    assert work_lease.token not in repr(durable)
    assert primary_lease.fencing_token not in repr(durable)

    owner_store = PostgresCommitOwnerStore(
        connection_factory=lambda: _approver_connection(
            postgres_effect_dsn
        )
    )
    rolled_back = owner_store.transfer_owner(
        expected_owner="operations_core",
        expected_generation=2,
        target_owner="legacy",
        actor_ref="approver:shadow-rollback",
        reason="verify deployment rollback before live cutover",
        rollback_of_generation=2,
    )
    replay = owner_store.transfer_owner(
        expected_owner="operations_core",
        expected_generation=2,
        target_owner="legacy",
        actor_ref="approver:shadow-rollback",
        reason="verify deployment rollback before live cutover",
        rollback_of_generation=2,
    )
    assert replay == rolled_back
    assert (rolled_back.owner, rolled_back.generation) == ("legacy", 3)

    with pytest.raises(CommitOwnershipLost, match="compare-and-set"):
        owner_store.transfer_owner(
            expected_owner="operations_core",
            expected_generation=2,
            target_owner="legacy",
            actor_ref="approver:stale-rollback",
            reason="stale rollback must fail closed",
            rollback_of_generation=2,
        )

    recutover = owner_store.transfer_owner(
        expected_owner="legacy",
        expected_generation=3,
        target_owner="operations_core",
        actor_ref="approver:shadow-recutover",
        reason="restore shadow owner after rollback rehearsal",
    )
    assert (recutover.owner, recutover.generation) == (
        "operations_core",
        4,
    )


def test_stale_change_set_creates_no_grant_and_allows_owner_rollback(
    postgres_effect_dsn: str,
    tmp_path: Path,
) -> None:
    repository = tmp_path / "stale-repository"
    workspace = tmp_path / "stale-workspace"
    repository.mkdir()
    _git_text(repository, "init", "-b", "main")
    _git_text(repository, "config", "user.name", "Change Delivery Test")
    _git_text(
        repository,
        "config",
        "user.email",
        "change-delivery@example.invalid",
    )
    candidate_path = repository / "owned.txt"
    candidate_path.write_text("legacy\n", encoding="utf-8")
    _git_text(repository, "add", "owned.txt")
    _git_text(repository, "commit", "-m", "base")
    base_commit = _git_text(repository, "rev-parse", "HEAD")
    _git_text(
        repository,
        "worktree",
        "add",
        "-b",
        "stale-change",
        str(workspace),
        base_commit,
    )
    workspace_candidate = workspace / "owned.txt"
    workspace_candidate.write_text("candidate\n", encoding="utf-8")
    (repository / "unrelated.txt").write_text(
        "concurrent\n",
        encoding="utf-8",
    )
    _git_text(repository, "add", "unrelated.txt")
    _git_text(repository, "commit", "-m", "concurrent unrelated change")

    work_lease, running = _seed_running_work(
        postgres_effect_dsn,
        work_id="work-stale-change-shadow",
        lease_token="work-lease-stale-change-shadow",
        required_attestations=frozenset({"shadow-contract"}),
    )
    primary = PrimaryAuthority(
        PostgresAuthorityStore(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            )
        ),
        token_factory=lambda: "primary-stale-change-shadow",
    )
    primary_lease = primary.acquire(
        AuthorityRequest(
            authority_key="operations-core-primary",
            holder_ref="host:stale-change-shadow",
            lease_seconds=300,
        )
    )
    delivery = build_postgres_owned_change_delivery(
        lambda: _worker_connection(postgres_effect_dsn),
        primary_lease=primary_lease,
        clock=lambda: datetime.now(timezone.utc),
        change_set_id_factory=lambda: "changeset-stale-change-shadow",
        writer_cli=REPO_ROOT / "scripts" / "git_writer_lock.py",
        check_commands={"shadow-contract": ("git", "diff", "--check")},
    )
    proposal = ChangeSetProposal(
        idempotency_key="changeset:stale-change-shadow:attempt-1",
        work_item_id=running.id,
        work_item_version=running.version,
        base_commit=base_commit,
        workspace_ref=str(workspace),
        exact_paths=("owned.txt",),
        content_hashes=(
            ContentHash(
                path="owned.txt",
                sha256=hashlib.sha256(
                    workspace_candidate.read_bytes()
                ).hexdigest(),
            ),
        ),
        required_checks=(
            CheckEvidence(
                name="shadow-contract",
                status="passed",
                evidence_ref="pytest:stale-change-shadow",
            ),
        ),
        author_ref="agent:change-author",
        author_evidence_ref="execution:stale-change-shadow",
    )

    with pytest.raises(
        CommitActuatorBlocked,
        match="no exact prior ChangeSet commit",
    ):
        delivery.deliver(
            OwnedChangeCommand(
                proposal=proposal,
                work_lease_token=work_lease.token,
                primary_fencing_token=primary_lease.fencing_token,
                repository=str(repository),
                message="[codex] stale shadow ChangeSet",
            )
        )

    with psycopg.connect(postgres_effect_dsn) as connection:
        grant_count = connection.execute(
            """
            SELECT count(*)
            FROM volpred_ops.commit_authority_grants
            WHERE work_item_id = %s
            """,
            (running.id,),
        ).fetchone()[0]
    assert grant_count == 0

    primary.release(primary_lease)
    owner_store = PostgresCommitOwnerStore(
        connection_factory=lambda: _approver_connection(
            postgres_effect_dsn
        )
    )
    rolled_back = owner_store.transfer_owner(
        expected_owner="operations_core",
        expected_generation=2,
        target_owner="legacy",
        actor_ref="approver:stale-change-rollback",
        reason="stale ChangeSet must not strand a grant",
        rollback_of_generation=2,
    )
    assert (rolled_back.owner, rolled_back.generation) == ("legacy", 3)


def test_terminal_commit_abandonment_unblocks_owner_rollback(
    postgres_effect_dsn: str,
) -> None:
    work_lease, running = _seed_running_work(
        postgres_effect_dsn,
        work_id="work-abandoned-commit",
        lease_token="work-lease-abandoned-commit",
    )
    primary = PrimaryAuthority(
        PostgresAuthorityStore(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            )
        ),
        token_factory=lambda: "primary-abandoned-commit",
    )
    primary_lease = primary.acquire(
        AuthorityRequest(
            authority_key="operations-core-primary",
            holder_ref="host:abandoned-commit",
            lease_seconds=300,
        )
    )
    request = _commit_authority_request(
        work_id=running.id,
        work_version=running.version,
        work_lease_token=work_lease.token,
        primary_fencing_token=primary_lease.fencing_token,
    )
    authority = PostgresCommitAuthority(
        connection_factory=lambda: _worker_connection(
            postgres_effect_dsn
        ),
        primary_lease=primary_lease,
    )
    assert authority.recover(request) is None
    with psycopg.connect(postgres_effect_dsn) as connection:
        assert connection.execute(
            """
            SELECT count(*)
            FROM volpred_ops.commit_authority_grants
            WHERE request_sha256 = %s
            """,
            (request.request_sha256,),
        ).fetchone() == (0,)
    grant = authority.authorize(request)
    abandonment = authority.abandon(
        request,
        grant,
        reason="canonical_writer_terminal_failure",
    )

    assert abandonment.request_sha256 == request.request_sha256
    assert abandonment.reason == "canonical_writer_terminal_failure"
    assert authority.abandon(
        request,
        grant,
        reason="canonical_writer_terminal_failure",
    ) == abandonment
    with pytest.raises(
        CommitActuatorBlocked,
        match="terminally abandoned",
    ):
        authority.recover(request)
    with pytest.raises(
        CommitSettlementBlocked,
        match="terminally abandoned",
    ):
        PostgresCommitSettlement(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            ),
            primary_lease=primary_lease,
        ).settle(_commit_settlement(request, grant))

    with psycopg.connect(postgres_effect_dsn) as connection:
        durable = connection.execute(
            """
            SELECT reason
            FROM volpred_ops.commit_authority_abandonments
            WHERE request_sha256 = %s
            """,
            (request.request_sha256,),
        ).fetchone()
    assert durable == ("canonical_writer_terminal_failure",)

    primary.release(primary_lease)
    rolled_back = PostgresCommitOwnerStore(
        connection_factory=lambda: _approver_connection(
            postgres_effect_dsn
        )
    ).transfer_owner(
        expected_owner="operations_core",
        expected_generation=2,
        target_owner="legacy",
        actor_ref="approver:abandoned-commit-rollback",
        reason="terminally abandoned grant is settled for rollback",
        rollback_of_generation=2,
    )
    assert (rolled_back.owner, rolled_back.generation) == ("legacy", 3)


def test_abandonment_and_settlement_share_one_terminal_lock(
    postgres_effect_dsn: str,
) -> None:
    work_lease, running = _seed_running_work(
        postgres_effect_dsn,
        work_id="work-terminal-lock",
        lease_token="work-lease-terminal-lock",
    )
    primary = PrimaryAuthority(
        PostgresAuthorityStore(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            )
        ),
        token_factory=lambda: "primary-terminal-lock",
    )
    primary_lease = primary.acquire(
        AuthorityRequest(
            authority_key="operations-core-primary",
            holder_ref="host:terminal-lock",
            lease_seconds=300,
        )
    )
    request = _commit_authority_request(
        work_id=running.id,
        work_version=running.version,
        work_lease_token=work_lease.token,
        primary_fencing_token=primary_lease.fencing_token,
    )
    grant = PostgresCommitAuthority(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn),
        primary_lease=primary_lease,
    ).authorize(request)
    abandonment_connection = _worker_connection(postgres_effect_dsn)
    try:
        abandonment_connection.execute(
            """
            SELECT *
            FROM volpred_ops.abandon_commit_write(%s, %s, %s, %s)
            """,
            (
                request.request_sha256,
                grant.commit_owner_generation,
                grant.commit_owner_ref,
                "canonical_writer_terminal_failure",
            ),
        ).fetchone()

        def timed_worker_connection() -> psycopg.Connection:
            connection = _worker_connection(postgres_effect_dsn)
            connection.execute("SET LOCAL statement_timeout = '250ms'")
            return connection

        with pytest.raises(psycopg.errors.QueryCanceled):
            PostgresCommitSettlement(
                connection_factory=timed_worker_connection,
                primary_lease=primary_lease,
            ).settle(_commit_settlement(request, grant))
        abandonment_connection.commit()
    finally:
        abandonment_connection.close()

    with pytest.raises(
        CommitSettlementBlocked,
        match="terminally abandoned",
    ):
        PostgresCommitSettlement(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            ),
            primary_lease=primary_lease,
        ).settle(_commit_settlement(request, grant))
    with psycopg.connect(postgres_effect_dsn) as connection:
        assert connection.execute(
            """
            SELECT
              (SELECT count(*)
               FROM volpred_ops.commit_authority_abandonments
               WHERE request_sha256 = %s),
              (SELECT count(*)
               FROM volpred_ops.commit_delivery_receipts
               WHERE authority_request_sha256 = %s)
            """,
            (request.request_sha256, request.request_sha256),
        ).fetchone() == (1, 0)


def test_change_set_service_rpc_creates_and_reads_token_redacted_view(
    postgres_effect_dsn: str,
) -> None:
    _, running = _seed_running_work(postgres_effect_dsn)
    request = _commit_authority_request(
        work_id=running.id,
        work_version=running.version,
        work_lease_token="never-send-through-change-set-rpc",
        primary_fencing_token="never-send-through-change-set-rpc",
    )
    view = _change_set_view(running, request)

    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("SET ROLE service_role")
        created = connection.execute(
            """
            SELECT public.volpred_create_change_set(
              %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s
            )
            """,
            (
                view.id,
                view.idempotency_key,
                view.work_item_id,
                view.work_item_version,
                view.base_commit,
                view.workspace_ref,
                Jsonb(list(view.exact_paths)),
                Jsonb(
                    [
                        {"path": item.path, "sha256": item.sha256}
                        for item in view.content_hashes
                    ]
                ),
                Jsonb(
                    [
                        {
                            "name": item.name,
                            "status": item.status,
                            "evidence_ref": item.evidence_ref,
                        }
                        for item in view.required_checks
                    ]
                ),
                view.author_ref,
                view.author_evidence_ref,
                view.proposal_sha256,
                view.schema_version,
                view.created_at,
            ),
        ).fetchone()[0]
        by_id = connection.execute(
            "SELECT public.volpred_read_change_set(%s)",
            (view.id,),
        ).fetchone()[0]
        by_key = connection.execute(
            """
            SELECT public.volpred_read_change_set_by_idempotency_key(%s)
            """,
            (view.idempotency_key,),
        ).fetchone()[0]
        missing = connection.execute(
            "SELECT public.volpred_read_change_set(%s)",
            ("missing-change-set",),
        ).fetchone()[0]

    assert created == by_id == by_key
    assert created["status"] == "proposed"
    assert created["proposal_sha256"] == view.proposal_sha256
    assert missing is None
    assert "work_lease_token" not in created
    assert "primary_fencing_token" not in created


def test_change_set_store_survives_restart_and_resumes_settlement(
    postgres_effect_dsn: str,
) -> None:
    work_lease, running = _seed_running_work(postgres_effect_dsn)
    primary = PrimaryAuthority(
        PostgresAuthorityStore(
            connection_factory=lambda: _worker_connection(
                postgres_effect_dsn
            ),
        ),
        token_factory=lambda: "primary-commit-token",
    )
    primary_lease = primary.acquire(
        AuthorityRequest(
            authority_key="operations-core-primary",
            holder_ref="host:commit-primary",
            lease_seconds=300,
        )
    )
    request = _commit_authority_request(
        work_id=running.id,
        work_version=running.version,
        work_lease_token=work_lease.token,
        primary_fencing_token=primary_lease.fencing_token,
    )
    request = replace(
        request,
        proposal_sha256=_change_set_view(
            running,
            request,
        ).proposal_sha256,
    )
    request = replace(
        request,
        request_sha256=_authority_request_sha256(request),
    )
    grant = PostgresCommitAuthority(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn),
        primary_lease=primary_lease,
    ).authorize(request)
    actuation = _commit_actuation_receipt(request, grant)
    command_sha256 = "e" * 64
    first_process = PostgresChangeSetStore(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn)
    )
    proposed = first_process.create(_change_set_view(running, request))

    checkpoint = first_process.checkpoint_actuation(
        change_set_id=proposed.view.id,
        proposal_sha256=proposed.view.proposal_sha256,
        land_command_sha256=command_sha256,
        actuation=actuation,
    )
    assert checkpoint.view.status == "commit_unsettled"

    restarted_process = PostgresChangeSetStore(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn)
    )
    recovered = restarted_process.load(proposed.view.id)
    assert recovered == checkpoint
    assert recovered.actuation == actuation
    assert recovered.delivery is None

    settlement = PostgresCommitSettlement(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn),
        primary_lease=primary_lease,
    )
    receipt = settlement.settle(
        CommitSettlement(
            change_set_id=proposed.view.id,
            repository=request.repository,
            work_lease_token=work_lease.token,
            primary_fencing_token=primary_lease.fencing_token,
            actuation=actuation,
        )
    )
    owner_store = PostgresCommitOwnerStore(
        connection_factory=lambda: _approver_connection(
            postgres_effect_dsn
        )
    )
    with pytest.raises(
        CommitOwnershipLost,
        match="zero unsettled ChangeSets",
    ):
        owner_store.transfer_owner(
            expected_owner="operations_core",
            expected_generation=2,
            target_owner="legacy",
            actor_ref="approver:checkpoint-rollback",
            reason="must not strand a checkpoint before landed linkage",
            rollback_of_generation=2,
        )
    landed = restarted_process.mark_landed(
        change_set_id=proposed.view.id,
        proposal_sha256=proposed.view.proposal_sha256,
        land_command_sha256=command_sha256,
        delivery=receipt,
    )

    final_process = PostgresChangeSetStore(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn)
    )
    assert final_process.load(proposed.view.id) == landed
    assert landed.view.status == "landed"
    assert landed.delivery == receipt
    assert final_process.create(
        replace(
            _change_set_view(running, request),
            id="unused-replay-id",
        )
    ) == landed

    with psycopg.connect(postgres_effect_dsn) as connection:
        durable = connection.execute(
            """
            SELECT status, land_command_sha256, actuation_receipt,
                   delivery_authority_request_sha256
            FROM volpred_ops.change_sets
            WHERE id = %s
            """,
            (proposed.view.id,),
        ).fetchone()
    assert durable[0] == "landed"
    assert durable[1] == command_sha256
    assert durable[2]["commit_sha"] == actuation.commit_sha
    assert durable[3] == actuation.authority_request_sha256
    assert work_lease.token not in repr(durable)
    assert primary_lease.fencing_token not in repr(durable)


def test_change_set_store_conflicts_and_privileges_fail_closed(
    postgres_effect_dsn: str,
) -> None:
    _, running = _seed_running_work(postgres_effect_dsn)
    request = _commit_authority_request(
        work_id=running.id,
        work_version=running.version,
        work_lease_token="unused-for-proposal",
        primary_fencing_token="unused-for-proposal",
    )
    store = PostgresChangeSetStore(
        connection_factory=lambda: _worker_connection(postgres_effect_dsn)
    )
    view = _change_set_view(running, request)
    store.create(view)

    with pytest.raises(ValueError, match="unknown ChangeSet"):
        store.load("missing-change-set")
    with pytest.raises(ChangeSetConflict, match="original payload"):
        store.create(
            replace(
                view,
                id="conflicting-id",
                proposal_sha256="f" * 64,
            )
        )

    with _worker_connection(postgres_effect_dsn) as connection:
        assert connection.execute(
            "SELECT status FROM volpred_ops.change_set_reads WHERE id = %s",
            (view.id,),
        ).fetchone() == ("proposed",)
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="actuation receipt is invalid",
        ):
            connection.execute(
                """
                SELECT *
                FROM volpred_ops.checkpoint_change_set_actuation(
                  %s, %s, %s, %s
                )
                """,
                (
                    view.id,
                    view.proposal_sha256,
                    "e" * 64,
                    Jsonb(
                        {
                            "schema_version": "commit-actuation.v1",
                            "proposal_sha256": view.proposal_sha256,
                            "work_item_id": view.work_item_id,
                            "work_item_version": view.work_item_version,
                            "commit_sha": "d" * 40,
                            "parent_sha": view.base_commit,
                            "exact_paths": list(view.exact_paths),
                            "actor": "commit-worker:postgres-test",
                            "status": "committed",
                            "observed_at": datetime.now(
                                timezone.utc
                            ).isoformat(),
                            "work_lease_token": "must-never-be-durable",
                        }
                    ),
                ),
            ).fetchall()
        connection.rollback()
        connection.execute("SET ROLE volpred_ops_worker")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT * FROM volpred_ops.change_sets"
            ).fetchall()
        connection.rollback()

    with psycopg.connect(postgres_effect_dsn) as connection:
        security = connection.execute(
            """
            SELECT
              (
                SELECT relrowsecurity AND relforcerowsecurity
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'volpred_ops'
                  AND relation.relname = 'change_sets'
              ),
              has_table_privilege(
                'public', 'volpred_ops.change_sets', 'SELECT'
              ),
              has_function_privilege(
                'volpred_ops_worker',
                'volpred_ops.checkpoint_change_set_actuation('
                  'text,text,text,jsonb)',
                'EXECUTE'
              ),
              has_function_privilege(
                'public',
                'volpred_ops.checkpoint_change_set_actuation('
                  'text,text,text,jsonb)',
                'EXECUTE'
              ),
              (
                SELECT indexdef LIKE
                  '%(delivery_authority_request_sha256)%'
                  AND indexdef LIKE '%WHERE %'
                FROM pg_indexes
                WHERE schemaname = 'volpred_ops'
                  AND indexname =
                    'change_sets_delivery_authority_request_idx'
              )
            """
        ).fetchone()
    assert security == (True, False, True, False, True)


def test_acknowledged_attempt_atomically_delivers_and_replays_receipt(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    delivery = _delivery(postgres_effect_dsn)
    effect = delivery.request(_request())
    lease = delivery.claim_outbox(
        worker_id="effect-worker",
        lease_seconds=300,
        effect_kinds=TELEGRAM_EFFECT_KINDS,
    )
    assert lease is not None

    receipt = _settle(
        postgres_effect_dsn,
        delivery,
        lease=lease,
        outcome=_acknowledged(),
    )
    replay_delivery = _delivery(
        postgres_effect_dsn,
        token="unused-replay-token",
    )
    replay = _settle(
        postgres_effect_dsn,
        replay_delivery,
        lease=lease,
        outcome=_acknowledged(),
    )

    with psycopg.connect(postgres_effect_dsn) as connection:
        outbox = connection.execute(
            """
            SELECT status, claimed_by, claim_token, claim_expires_at
            FROM volpred_ops.effect_outbox
            WHERE effect_id = %s
            """,
            (effect.id,),
        ).fetchone()
        receipt_count = connection.execute(
            "SELECT count(*) FROM volpred_ops.effect_attempt_receipts"
        ).fetchone()[0]

    assert replay == receipt
    assert receipt.disposition == "delivered"
    assert receipt.acknowledgement == _acknowledged().acknowledgement
    assert receipt.authority_request_sha256 is not None
    assert receipt.outbox_claim_ref == (
        "effect-outbox:1:attempt-1"
    )
    assert receipt.primary_authority_ref == (
        "primary-authority:operations-core-primary:epoch-1"
    )
    assert receipt.retry_at is None
    assert delivery.inspect(effect.id).status == "delivered"
    assert delivery.claim_outbox(
        worker_id="other-worker",
        lease_seconds=300,
        effect_kinds=TELEGRAM_EFFECT_KINDS,
    ) is None
    assert outbox == ("delivered", None, None, None)
    assert receipt_count == 1


def test_settlement_without_durable_authority_grant_is_rejected(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    delivery = _delivery(postgres_effect_dsn)
    delivery.request(_request())
    lease = delivery.claim_outbox(
        worker_id="effect-worker",
        lease_seconds=300,
        effect_kinds=TELEGRAM_EFFECT_KINDS,
    )
    assert lease is not None

    with pytest.raises(ValueError, match="authority grant is missing"):
        delivery.settle_outbox(
            lease=lease,
            outcome=_acknowledged(),
            authority=EffectSettlementAuthority(
                request_sha256="d" * 64,
                outbox_claim_ref="effect-outbox:1:attempt-1",
                primary_authority_ref=(
                    "primary-authority:operations-core-primary:epoch-1"
                ),
            ),
        )


def test_concurrent_equivalent_settlement_returns_one_immutable_receipt(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    delivery = _delivery(postgres_effect_dsn)
    delivery.request(_request())
    lease = delivery.claim_outbox(
        worker_id="effect-worker",
        lease_seconds=300,
        effect_kinds=TELEGRAM_EFFECT_KINDS,
    )
    assert lease is not None

    deliveries = (
        _delivery(postgres_effect_dsn, token="unused-a"),
        _delivery(postgres_effect_dsn, token="unused-b"),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = tuple(
            executor.map(
                lambda item: _settle(
                    postgres_effect_dsn,
                    item,
                    lease=lease,
                    outcome=_acknowledged(),
                ),
                deliveries,
            )
        )

    assert receipts[0] == receipts[1]
    with psycopg.connect(postgres_effect_dsn) as connection:
        receipt_count = connection.execute(
            "SELECT count(*) FROM volpred_ops.effect_attempt_receipts"
        ).fetchone()[0]
    assert receipt_count == 1


def test_acknowledgement_mismatch_rolls_back_before_terminal_state(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    delivery = _delivery(postgres_effect_dsn)
    effect = delivery.request(_request())
    lease = delivery.claim_outbox(
        worker_id="effect-worker",
        lease_seconds=300,
        effect_kinds=TELEGRAM_EFFECT_KINDS,
    )
    assert lease is not None

    with pytest.raises(ValueError, match="acknowledgement mismatch"):
        _settle(
            postgres_effect_dsn,
            delivery,
            lease=lease,
            outcome=_acknowledged(
                acknowledgement=AcknowledgementExpectation(
                    kind="telegram.message.readback",
                    target_ref="telegram:another-chat",
                )
            ),
        )

    with psycopg.connect(postgres_effect_dsn) as connection:
        state = connection.execute(
            """
            SELECT
              (SELECT status FROM volpred_ops.effect_requests WHERE id = %s),
              (SELECT status FROM volpred_ops.effect_outbox WHERE effect_id = %s),
              (SELECT count(*) FROM volpred_ops.effect_attempt_receipts)
            """,
            (effect.id, effect.id),
        ).fetchone()
    assert state == ("requested", "claimed", 0)


def test_retryable_failure_uses_database_backoff_and_fences_stale_claim(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    delivery = _delivery(postgres_effect_dsn, token="attempt-token-1")
    delivery.request(_request())
    first_lease = delivery.claim_outbox(
        worker_id="effect-worker-a",
        lease_seconds=300,
        effect_kinds=TELEGRAM_EFFECT_KINDS,
    )
    assert first_lease is not None

    first_receipt = _settle(
        postgres_effect_dsn,
        delivery,
        lease=first_lease,
        outcome=_failed(),
    )
    assert first_receipt.disposition == "retry_scheduled"
    assert first_receipt.retry_at is not None
    assert delivery.claim_outbox(
        worker_id="too-early",
        lease_seconds=300,
        effect_kinds=TELEGRAM_EFFECT_KINDS,
    ) is None

    with psycopg.connect(postgres_effect_dsn, autocommit=True) as connection:
        connection.execute(
            """
            UPDATE volpred_ops.effect_outbox
            SET available_at = clock_timestamp() - interval '1 second'
            """
        )

    second_delivery = _delivery(
        postgres_effect_dsn,
        token="attempt-token-2",
    )
    second_lease = second_delivery.claim_outbox(
        worker_id="effect-worker-b",
        lease_seconds=300,
        effect_kinds=TELEGRAM_EFFECT_KINDS,
    )
    assert second_lease is not None
    assert second_lease.attempt_count == 2

    replay = _settle(
        postgres_effect_dsn,
        delivery,
        lease=first_lease,
        outcome=_failed(),
    )
    assert replay == first_receipt
    with pytest.raises(ValueError, match="original outcome"):
        _settle(
            postgres_effect_dsn,
            delivery,
            lease=first_lease,
            outcome=_failed(),
            authority=replace(
                _grant_authority(
                    postgres_effect_dsn,
                    delivery,
                    first_lease,
                ),
                primary_authority_ref="primary-authority:wrong",
            ),
        )
    with pytest.raises(ValueError, match="original outcome"):
        _settle(
            postgres_effect_dsn,
            delivery,
            lease=first_lease,
            outcome=_failed(evidence_sha256="d" * 64),
        )

    stale_second = replace(second_lease, token=first_lease.token)
    with pytest.raises(EffectWorkerBlocked, match="outbox claim is stale"):
        _settle(
            postgres_effect_dsn,
            second_delivery,
            lease=stale_second,
            outcome=_failed(),
        )


def test_expired_claim_cannot_settle_before_recovery(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    delivery = _delivery(postgres_effect_dsn, token="expired-token")
    delivery.request(_request())
    lease = delivery.claim_outbox(
        worker_id="effect-worker",
        lease_seconds=300,
        effect_kinds=TELEGRAM_EFFECT_KINDS,
    )
    assert lease is not None
    with psycopg.connect(postgres_effect_dsn, autocommit=True) as connection:
        connection.execute(
            """
            UPDATE volpred_ops.effect_outbox
            SET claim_expires_at = clock_timestamp() - interval '1 second'
            """
        )

    with pytest.raises(EffectWorkerBlocked, match="outbox claim is stale"):
        _settle(
            postgres_effect_dsn,
            delivery,
            lease=lease,
            outcome=_acknowledged(),
        )

    recovered = _delivery(
        postgres_effect_dsn,
        token="recovered-token",
    ).claim_outbox(
        worker_id="recovery-worker",
        lease_seconds=300,
        effect_kinds=TELEGRAM_EFFECT_KINDS,
    )
    assert recovered is not None
    assert recovered.attempt_count == 2


def test_terminal_failure_dead_letters_without_another_claim(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    delivery = _delivery(postgres_effect_dsn)
    effect = delivery.request(_request())
    lease = delivery.claim_outbox(
        worker_id="effect-worker",
        lease_seconds=300,
        effect_kinds=TELEGRAM_EFFECT_KINDS,
    )
    assert lease is not None

    receipt = _settle(
        postgres_effect_dsn,
        delivery,
        lease=lease,
        outcome=_failed(
            retryable=False,
            reason_code="provider_rejected_target",
        ),
    )

    assert receipt.disposition == "dead_lettered"
    assert receipt.reported_outcome == "terminal_failure"
    assert delivery.inspect(effect.id).status == "dead_lettered"
    assert delivery.claim_outbox(
        worker_id="other-worker",
        lease_seconds=300,
        effect_kinds=TELEGRAM_EFFECT_KINDS,
    ) is None


def test_retry_exhaustion_dead_letters_on_fifth_attempt(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    _delivery(postgres_effect_dsn).request(_request())
    final_receipt = None
    for attempt in range(1, 6):
        delivery = _delivery(
            postgres_effect_dsn,
            token=f"attempt-token-{attempt}",
        )
        lease = delivery.claim_outbox(
            worker_id=f"effect-worker-{attempt}",
            lease_seconds=300,
            effect_kinds=TELEGRAM_EFFECT_KINDS,
        )
        assert lease is not None
        assert lease.attempt_count == attempt
        final_receipt = _settle(
            postgres_effect_dsn,
            delivery,
            lease=lease,
            outcome=_failed(
                evidence_ref=f"attempt-log:effect-postgres-1:{attempt}",
            ),
        )
        if attempt < 5:
            assert final_receipt.disposition == "retry_scheduled"
            with psycopg.connect(
                postgres_effect_dsn,
                autocommit=True,
            ) as connection:
                connection.execute(
                    """
                    UPDATE volpred_ops.effect_outbox
                    SET available_at = clock_timestamp() - interval '1 second'
                    """
                )

    assert final_receipt is not None
    assert final_receipt.disposition == "dead_lettered"
    assert final_receipt.reported_outcome == "retryable_failure"
    with psycopg.connect(postgres_effect_dsn) as connection:
        states = connection.execute(
            """
            SELECT
              (SELECT status FROM volpred_ops.effect_requests),
              (SELECT status FROM volpred_ops.effect_outbox),
              (SELECT count(*) FROM volpred_ops.effect_attempt_receipts)
            """
        ).fetchone()
    assert states == ("dead_lettered", "dead_lettered", 5)


def test_settlement_failure_rolls_back_attempt_receipt_and_state(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    delivery = _delivery(postgres_effect_dsn)
    effect = delivery.request(_request())
    lease = delivery.claim_outbox(
        worker_id="effect-worker",
        lease_seconds=300,
        effect_kinds=TELEGRAM_EFFECT_KINDS,
    )
    assert lease is not None
    with psycopg.connect(postgres_effect_dsn, autocommit=True) as connection:
        connection.execute(
            """
            CREATE FUNCTION volpred_ops.fail_effect_terminal_update()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF NEW.status = 'delivered' THEN
                RAISE EXCEPTION 'injected terminal update failure';
              END IF;
              RETURN NEW;
            END;
            $$
            """
        )
        connection.execute(
            """
            CREATE TRIGGER fail_effect_terminal_update
            BEFORE UPDATE ON volpred_ops.effect_outbox
            FOR EACH ROW
            EXECUTE FUNCTION volpred_ops.fail_effect_terminal_update()
            """
        )
    try:
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="terminal update failure",
        ):
            _settle(
                postgres_effect_dsn,
                delivery,
                lease=lease,
                outcome=_acknowledged(),
            )
        with psycopg.connect(postgres_effect_dsn) as connection:
            state = connection.execute(
                """
                SELECT
                  (SELECT status FROM volpred_ops.effect_requests WHERE id = %s),
                  (SELECT status FROM volpred_ops.effect_outbox WHERE effect_id = %s),
                  (SELECT count(*) FROM volpred_ops.effect_attempt_receipts)
                """,
                (effect.id, effect.id),
            ).fetchone()
        assert state == ("requested", "claimed", 0)
    finally:
        with psycopg.connect(
            postgres_effect_dsn,
            autocommit=True,
        ) as connection:
            connection.execute(
                "DROP TRIGGER fail_effect_terminal_update "
                "ON volpred_ops.effect_outbox"
            )
            connection.execute(
                "DROP FUNCTION volpred_ops.fail_effect_terminal_update()"
            )


def test_worker_cannot_mutate_attempt_receipts_or_read_token_digest(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    delivery = _delivery(postgres_effect_dsn)
    delivery.request(_request())
    lease = delivery.claim_outbox(
        worker_id="effect-worker",
        lease_seconds=300,
        effect_kinds=TELEGRAM_EFFECT_KINDS,
    )
    assert lease is not None
    _settle(
        postgres_effect_dsn,
        delivery,
        lease=lease,
        outcome=_acknowledged(),
    )

    with _worker_connection(postgres_effect_dsn) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "DELETE FROM volpred_ops.effect_attempt_receipts"
            )
        connection.rollback()
        connection.execute("SET ROLE volpred_ops_worker")
        columns = {
            description.name
            for description in connection.execute(
                "SELECT * FROM "
                "volpred_ops.effect_attempt_receipt_reads LIMIT 0"
            ).description
        }
    assert "claim_token_sha256" not in columns


def test_unfenced_settlement_function_is_removed(
    postgres_effect_dsn: str,
) -> None:
    with psycopg.connect(postgres_effect_dsn) as connection:
        signatures = connection.execute(
            """
            SELECT pg_get_function_identity_arguments(procedure.oid)
            FROM pg_proc AS procedure
            JOIN pg_namespace AS namespace
              ON namespace.oid = procedure.pronamespace
            WHERE namespace.nspname = 'volpred_ops'
              AND procedure.proname = 'settle_effect_outbox'
            """
        ).fetchall()

    assert len(signatures) == 1
    assert signatures[0][0].count(",") + 1 == 14


def test_owned_email_transaction_cutover_delivery_rollback_and_recutover(
    postgres_effect_dsn: str,
) -> None:
    payload = {
        "schema_version": "email-notification.v1",
        "subject": "[VolPred Alert][INFO] PG17 ownership transaction",
        "text_body": "PG17 owned email transaction fixture.",
        "html_body": "<p>PG17 owned email transaction fixture.</p>",
    }
    work_token = "work-owned-email-token"
    outbox_token = "outbox-owned-email-token"
    primary_token = "primary-owned-email-token"
    work_owner_store = PostgresWorkOwnerStore(
        lambda: psycopg.connect(postgres_effect_dsn)
    )
    work_manifest = _work_cutover_manifest("owned email transaction")
    work_owner_store.stage_cutover_manifest(
        manifest=work_manifest,
        expected_owner="legacy",
        expected_generation=1,
        actor_ref="test:pg17",
    )
    work_owner = work_owner_store.transfer_owner(
        expected_owner="legacy",
        expected_generation=1,
        target_owner="operations_core",
        actor_ref="test:pg17",
        reason="exercise owned workflow after Work Coordinator cutover",
        cutover_manifest_sha256=work_manifest.sha256,
    )
    assert (work_owner.owner, work_owner.generation) == (
        "operations_core",
        2,
    )

    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("SET ROLE service_role")
        initial = connection.execute(
            "SELECT public.volpred_read_notification_owner()"
        ).fetchone()[0]
        assert initial["owner"] == "legacy"
        assert initial["generation"] == 1

        cutover = connection.execute(
            """
            SELECT public.volpred_transfer_notification_owner(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                "legacy",
                1,
                "operations_core",
                "test:pg17",
                "exercise production ownership transaction",
                None,
            ),
        ).fetchone()[0]
        assert cutover["owner"] == "operations_core"
        assert cutover["generation"] == 2

        owned_request = connection.execute(
            """
            SELECT public.volpred_request_owned_email_notification(
              %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                2,
                "ops-alert:pg17-transaction:2026-07-24",
                "info",
                payload["subject"],
                "owner@example.com",
                Jsonb(payload),
                "test:pg17",
            ),
        ).fetchone()[0]
        replayed_request = connection.execute(
            """
            SELECT public.volpred_request_owned_email_notification(
              %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                2,
                "ops-alert:pg17-transaction:2026-07-24",
                "info",
                payload["subject"],
                "owner@example.com",
                Jsonb(payload),
                "test:pg17",
            ),
        ).fetchone()[0]
        assert replayed_request == owned_request
        shared_request = connection.execute(
            """
            SELECT public.volpred_read_owned_email_request(%s)
            """,
            ("ops-alert:pg17-transaction:2026-07-24",),
        ).fetchone()[0]
        assert shared_request["schema_version"] == (
            "owned-email-request-read.v1"
        )
        assert shared_request["command"] == {
            "schema_version": "owned-email-command.v1",
            "idempotency_key": (
                "ops-alert:pg17-transaction:2026-07-24"
            ),
            "level": "info",
            "title": payload["subject"],
            "recipient": "owner@example.com",
            "text_body": payload["text_body"],
            "html_body": payload["html_body"],
            "actor_ref": "test:pg17",
        }
        assert shared_request["request"]["receipt"] is None
        assert connection.execute(
            "SELECT public.volpred_read_owned_email_request(%s)",
            ("ops-alert:missing",),
        ).fetchone()[0] is None

        with pytest.raises(
            psycopg.errors.NoDataFound,
            match="query returned no rows",
        ):
            connection.execute(
                """
                SELECT public.volpred_begin_owned_email_notification(
                  %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    2,
                    owned_request["effect_id"],
                    "effect-worker:pg17",
                    300,
                    work_token,
                    outbox_token,
                    primary_token,
                ),
            )

        primary_lease = connection.execute(
            """
            SELECT public.volpred_acquire_primary_authority(
              %s, %s, %s, %s
            )
            """,
            (
                "operations-core-primary",
                "effect-worker:pg17",
                300,
                primary_token,
            ),
        ).fetchone()[0]

        attempt = connection.execute(
            """
            SELECT public.volpred_begin_owned_email_notification(
              %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                2,
                owned_request["effect_id"],
                "effect-worker:pg17",
                300,
                work_token,
                outbox_token,
                primary_token,
            ),
        ).fetchone()[0]
        assert attempt["owner_generation"] == 2
        assert attempt["effect"]["status"] == "requested"

        with pytest.raises(
            psycopg.errors.RaiseException,
            match="requires zero active delivery fences",
        ):
            connection.execute(
                """
                SELECT public.volpred_transfer_notification_owner(
                  %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    "operations_core",
                    2,
                    "legacy",
                    "test:pg17",
                    "must reject transfer during active delivery",
                    2,
                ),
            )

        receipt = connection.execute(
            """
            SELECT public.volpred_settle_owned_email_notification(
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                2,
                attempt["work_id"],
                attempt["work_version"],
                work_token,
                attempt["effect"]["id"],
                attempt["outbox_sequence"],
                attempt["attempt_count"],
                attempt["worker_id"],
                outbox_token,
                attempt["primary_authority_key"],
                attempt["primary_authority_holder_ref"],
                attempt["primary_authority_epoch"],
                primary_token,
                attempt["authority_request_sha256"],
                attempt["outbox_claim_ref"],
                attempt["primary_authority_ref"],
                "acknowledged",
                attempt["effect"]["acknowledgement"]["kind"],
                attempt["effect"]["acknowledgement"]["target_ref"],
                None,
                "imap-sent:pg17-owned-email",
                "e" * 64,
            ),
        ).fetchone()[0]
        assert receipt["work_status"] == "succeeded"
        assert receipt["effect_status"] == "delivered"
        assert receipt["disposition"] == "delivered"
        terminal_replay = connection.execute(
            """
            SELECT public.volpred_request_owned_email_notification(
              %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                2,
                "ops-alert:pg17-transaction:2026-07-24",
                "info",
                payload["subject"],
                "owner@example.com",
                Jsonb(payload),
                "test:pg17",
            ),
        ).fetchone()[0]
        assert terminal_replay["work_id"] == owned_request["work_id"]
        assert terminal_replay["effect_id"] == owned_request["effect_id"]
        assert terminal_replay["receipt"] == receipt
        shared_terminal = connection.execute(
            """
            SELECT public.volpred_read_owned_email_request(%s)
            """,
            ("ops-alert:pg17-transaction:2026-07-24",),
        ).fetchone()[0]
        assert shared_terminal["command"] == shared_request["command"]
        assert shared_terminal["request"]["receipt"] == receipt

        connection.execute("RESET ROLE")
        held_after_settlement = connection.execute(
            """
            SELECT holder_ref, epoch
            FROM volpred_ops.primary_authority_lease_reads
            WHERE authority_key = 'operations-core-primary'
            """
        ).fetchone()
        assert held_after_settlement == (
            "effect-worker:pg17",
            primary_lease["epoch"],
        )
        connection.execute("SET ROLE service_role")

        released = connection.execute(
            """
            SELECT public.volpred_release_primary_authority(
              %s, %s, %s, %s
            )
            """,
            (
                "operations-core-primary",
                "effect-worker:pg17",
                primary_lease["epoch"],
                primary_token,
            ),
        ).fetchone()[0]
        assert released["epoch"] == primary_lease["epoch"]

        rollback = connection.execute(
            """
            SELECT public.volpred_transfer_notification_owner(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                "operations_core",
                2,
                "legacy",
                "test:pg17",
                "rehearse exact ownership rollback",
                2,
            ),
        ).fetchone()[0]
        assert rollback["owner"] == "legacy"
        assert rollback["generation"] == 3

        replayed_rollback = connection.execute(
            """
            SELECT public.volpred_transfer_notification_owner(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                "operations_core",
                2,
                "legacy",
                "test:pg17",
                "rehearse exact ownership rollback",
                2,
            ),
        ).fetchone()[0]
        assert replayed_rollback == rollback

        legacy_primary_token = "legacy-primary-owned-email-token"

        def competing_transfer() -> None:
            with psycopg.connect(
                postgres_effect_dsn,
                autocommit=True,
            ) as transfer_connection:
                transfer_connection.execute(
                    "SET application_name = "
                    "'volpred-owned-email-transfer-race'"
                )
                transfer_connection.execute("SET ROLE service_role")
                transfer_connection.execute(
                    """
                    SELECT public.volpred_transfer_notification_owner(
                      %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        "legacy",
                        3,
                        "operations_core",
                        "test:pg17",
                        "must reject cutover during legacy provider fence",
                        None,
                    ),
                )

        with psycopg.connect(postgres_effect_dsn) as lease_connection:
            lease_connection.execute("SET ROLE service_role")
            lease_connection.execute(
                """
                SELECT pg_advisory_xact_lock(
                  hashtextextended(
                    'primary:operations-core-primary',
                    0
                  )
                )
                """
            )
            with ThreadPoolExecutor(max_workers=1) as executor:
                transfer_future = executor.submit(competing_transfer)
                deadline = time.monotonic() + 2
                wait_event = None
                with psycopg.connect(
                    postgres_effect_dsn,
                    autocommit=True,
                ) as observer_connection:
                    while time.monotonic() < deadline:
                        wait_event = observer_connection.execute(
                            """
                            SELECT wait_event
                            FROM pg_stat_activity
                            WHERE application_name =
                              'volpred-owned-email-transfer-race'
                            """
                        ).fetchone()
                        if (
                            wait_event is not None
                            and str(wait_event[0]).lower() == "advisory"
                        ):
                            break
                        time.sleep(0.01)
                observed_advisory_wait = (
                    wait_event is not None
                    and str(wait_event[0]).lower() == "advisory"
                )
                legacy_primary_lease = lease_connection.execute(
                    """
                    SELECT public.volpred_acquire_primary_authority(
                      %s, %s, %s, %s
                    )
                    """,
                    (
                        "operations-core-primary",
                        "effect-worker:ops-alert-email-legacy",
                        300,
                        legacy_primary_token,
                    ),
                ).fetchone()[0]
                lease_connection.commit()
                with pytest.raises(
                    psycopg.errors.RaiseException,
                    match="zero active delivery fences",
                ):
                    transfer_future.result(timeout=2)
                assert observed_advisory_wait is True
        connection.execute(
            """
            SELECT public.volpred_release_primary_authority(
              %s, %s, %s, %s
            )
            """,
            (
                "operations-core-primary",
                "effect-worker:ops-alert-email-legacy",
                legacy_primary_lease["epoch"],
                legacy_primary_token,
            ),
        )

        with pytest.raises(
            psycopg.errors.RaiseException,
            match="does not own email.ops_alert generation 2",
        ):
            connection.execute(
                """
                SELECT public.volpred_request_owned_email_notification(
                  %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    2,
                    "ops-alert:pg17-stale-owner:2026-07-24",
                    "info",
                    payload["subject"],
                    "owner@example.com",
                    Jsonb(payload),
                    "test:pg17",
                ),
            )

        recutover = connection.execute(
            """
            SELECT public.volpred_transfer_notification_owner(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                "legacy",
                3,
                "operations_core",
                "test:pg17",
                "restore operations core after rollback rehearsal",
                None,
            ),
        ).fetchone()[0]
        assert recutover["owner"] == "operations_core"
        assert recutover["generation"] == 4

        with pytest.raises(
            psycopg.errors.RaiseException,
            match="compare-and-set failed",
        ):
            connection.execute(
                """
                SELECT public.volpred_transfer_notification_owner(
                  %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    "legacy",
                    3,
                    "operations_core",
                    "test:other-actor",
                    "stale competing cutover",
                    None,
                ),
            )

    with psycopg.connect(postgres_effect_dsn) as connection:
        durable_state = connection.execute(
            """
            SELECT
              (SELECT status
               FROM volpred_ops.work_items
               WHERE id = %s),
              (SELECT status
               FROM volpred_ops.effect_requests
               WHERE id = %s),
              (SELECT status
               FROM volpred_ops.effect_outbox
               WHERE effect_id = %s),
              (SELECT status
               FROM volpred_ops.owned_notification_attempts
               WHERE effect_id = %s),
              (SELECT count(*)
               FROM volpred_ops.effect_attempt_receipts
               WHERE effect_id = %s),
              (SELECT count(*)
               FROM volpred_ops.primary_authority_receipts
               WHERE authority_key = 'operations-core-primary'),
              (SELECT array_agg(owner ORDER BY generation)
               FROM volpred_ops.notification_owner_receipts
               WHERE effect_family = 'email.ops_alert')
            """,
            (
                owned_request["work_id"],
                owned_request["effect_id"],
                owned_request["effect_id"],
                owned_request["effect_id"],
                owned_request["effect_id"],
            ),
        ).fetchone()

    assert durable_state == (
        "succeeded",
        "delivered",
        "delivered",
        "delivered",
        1,
        2,
        ["legacy", "operations_core", "legacy", "operations_core"],
    )


def test_expired_owned_email_attempt_is_atomically_recovered(
    postgres_effect_dsn: str,
) -> None:
    payload = {
        "schema_version": "email-notification.v1",
        "subject": "[VolPred Alert][WARN] PG17 expired attempt",
        "text_body": "PG17 expired owned-email recovery fixture.",
        "html_body": "<p>PG17 expired owned-email recovery fixture.</p>",
    }
    worker_id = "effect-worker:ops-alert-email"
    primary_token = "primary-owned-email-recovery-token"

    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("SET ROLE service_role")
        owner = connection.execute(
            """
            SELECT public.volpred_transfer_notification_owner(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                "legacy",
                1,
                "operations_core",
                "test:pg17-recovery",
                "exercise expired owned-email recovery",
                None,
            ),
        ).fetchone()[0]
        connection.execute(
            """
            SELECT public.volpred_acquire_primary_authority(
              %s, %s, %s, %s
            )
            """,
            (
                "operations-core-primary",
                worker_id,
                300,
                primary_token,
            ),
        )
        owned_request = connection.execute(
            """
            SELECT public.volpred_request_owned_email_notification(
              %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                "ops-alert:pg17-expired-attempt:2026-07-26",
                "warn",
                payload["subject"],
                "owner@example.com",
                Jsonb(payload),
                "test:pg17-recovery",
            ),
        ).fetchone()[0]
        first_attempt = connection.execute(
            """
            SELECT public.volpred_begin_owned_email_notification(
              %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                owned_request["effect_id"],
                worker_id,
                300,
                "work-recovery-attempt-1",
                "outbox-recovery-attempt-1",
                primary_token,
            ),
        ).fetchone()[0]

        connection.execute("RESET ROLE")
        connection.execute(
            """
            UPDATE volpred_ops.owned_notification_attempts
            SET lease_expires_at = clock_timestamp() - interval '1 minute'
            WHERE effect_id = %s
              AND attempt_count = 1
            """,
            (owned_request["effect_id"],),
        )
        connection.execute(
            """
            UPDATE volpred_ops.work_items
            SET claim_expires_at = clock_timestamp() - interval '1 minute'
            WHERE id = %s
            """,
            (owned_request["work_id"],),
        )
        connection.execute(
            """
            UPDATE volpred_ops.effect_outbox
            SET claim_expires_at = clock_timestamp() - interval '1 minute'
            WHERE effect_id = %s
            """,
            (owned_request["effect_id"],),
        )
        connection.execute("SET ROLE service_role")
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="expired attempt requires recovery actuator",
        ):
            connection.execute(
                """
                SELECT public.volpred_begin_owned_email_notification(
                  %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    owner["generation"],
                    owned_request["effect_id"],
                    worker_id,
                    300,
                    "work-ordinary-retry-must-fail",
                    "outbox-ordinary-retry-must-fail",
                    primary_token,
                ),
            )
        connection.execute("RESET ROLE")
        ordinary_retry_state = connection.execute(
            """
            SELECT
              (SELECT count(*)
               FROM volpred_ops.owned_notification_attempts
               WHERE effect_id = %s),
              (SELECT status
               FROM volpred_ops.owned_notification_attempts
               WHERE effect_id = %s AND attempt_count = 1),
              (SELECT attempt_count
               FROM volpred_ops.effect_outbox
               WHERE effect_id = %s),
              (SELECT status
               FROM volpred_ops.work_items
               WHERE id = %s)
            """,
            (
                owned_request["effect_id"],
                owned_request["effect_id"],
                owned_request["effect_id"],
                owned_request["work_id"],
            ),
        ).fetchone()
        connection.execute("SET ROLE service_role")
        recovered = connection.execute(
            """
            SELECT public.volpred_recover_expired_owned_email_notification(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                worker_id,
                300,
                "work-recovery-attempt-2",
                "outbox-recovery-attempt-2",
                primary_token,
            ),
        ).fetchone()[0]
        retry_receipt = connection.execute(
            """
            SELECT public.volpred_settle_owned_email_notification(
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                recovered["work_id"],
                recovered["work_version"],
                "work-recovery-attempt-2",
                recovered["effect"]["id"],
                recovered["outbox_sequence"],
                recovered["attempt_count"],
                recovered["worker_id"],
                "outbox-recovery-attempt-2",
                recovered["primary_authority_key"],
                recovered["primary_authority_holder_ref"],
                recovered["primary_authority_epoch"],
                primary_token,
                recovered["authority_request_sha256"],
                recovered["outbox_claim_ref"],
                recovered["primary_authority_ref"],
                "retryable_failure",
                None,
                None,
                "email_provider_error",
                "effect-attempt:pg17-retryable-provider-error",
                "f" * 64,
            ),
        ).fetchone()[0]
        connection.execute("RESET ROLE")
        connection.execute(
            """
            UPDATE volpred_ops.effect_outbox
            SET available_at = clock_timestamp() - interval '1 minute'
            WHERE effect_id = %s
            """,
            (owned_request["effect_id"],),
        )
        connection.execute("SET ROLE service_role")
        retried = connection.execute(
            """
            SELECT public.volpred_recover_expired_owned_email_notification(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                worker_id,
                300,
                "work-recovery-attempt-3",
                "outbox-recovery-attempt-3",
                primary_token,
            ),
        ).fetchone()[0]
        connection.execute("RESET ROLE")

        recovery_state = connection.execute(
            """
            SELECT
              (SELECT status
               FROM volpred_ops.owned_notification_attempts
               WHERE effect_id = %s AND attempt_count = 1),
              (SELECT disposition
               FROM volpred_ops.owned_notification_attempts
               WHERE effect_id = %s AND attempt_count = 1),
              (SELECT status
               FROM volpred_ops.owned_notification_attempts
               WHERE effect_id = %s AND attempt_count = 2),
              (SELECT status
               FROM volpred_ops.owned_notification_attempts
               WHERE effect_id = %s AND attempt_count = 3),
              (SELECT count(*)
               FROM volpred_ops.owned_notification_recovery_receipts
               WHERE effect_id = %s
                 AND (
                   (expired_attempt_count = 1
                    AND recovery_attempt_count = 2
                    AND reason_code =
                      'worker_interrupted_after_begin')
                   OR
                   (expired_attempt_count = 2
                    AND recovery_attempt_count = 3
                    AND reason_code =
                      'retry_due_without_actuator')
                 )),
              has_function_privilege(
                'service_role',
                'public.volpred_recover_expired_owned_email_notification(bigint,text,integer,text,text,text)',
                'EXECUTE'
              ),
              NOT has_function_privilege(
                'anon',
                'public.volpred_recover_expired_owned_email_notification(bigint,text,integer,text,text,text)',
                'EXECUTE'
              ),
              NOT has_table_privilege(
                'service_role',
                'volpred_ops.owned_notification_recovery_receipts',
                'SELECT'
              ),
              (SELECT relrowsecurity AND relforcerowsecurity
               FROM pg_class AS relation
               JOIN pg_namespace AS namespace
                 ON namespace.oid = relation.relnamespace
               WHERE namespace.nspname = 'volpred_ops'
                 AND relation.relname =
                   'owned_notification_recovery_receipts'),
              (SELECT procedure.proowner = (
                         SELECT oid FROM pg_roles
                         WHERE rolname = 'volpred_ops_definer'
                       )
                     AND procedure.prosecdef
                     AND procedure.proconfig = ARRAY['search_path=""']
               FROM pg_proc AS procedure
               WHERE procedure.oid =
                 'public.volpred_recover_expired_owned_email_notification(bigint,text,integer,text,text,text)'::regprocedure),
              (SELECT position(
                        'owned_request.effect_family = ownership.effect_family'
                        IN pg_get_functiondef(procedure.oid)
                      ) > 0
               FROM pg_proc AS procedure
               WHERE procedure.oid =
                 'public.volpred_recover_expired_owned_email_notification(bigint,text,integer,text,text,text)'::regprocedure),
              (SELECT position(
                        'effect.effect_kind = ''email.notification.send'''
                        IN pg_get_functiondef(procedure.oid)
                      ) > 0
               FROM pg_proc AS procedure
               WHERE procedure.oid =
                 'public.volpred_recover_expired_owned_email_notification(bigint,text,integer,text,text,text)'::regprocedure)
            """,
            (owned_request["effect_id"],) * 5,
        ).fetchone()
        connection.execute("SET ROLE service_role")
        connection.execute(
            """
            SELECT public.volpred_settle_owned_email_notification(
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                retried["work_id"],
                retried["work_version"],
                "work-recovery-attempt-3",
                retried["effect"]["id"],
                retried["outbox_sequence"],
                retried["attempt_count"],
                retried["worker_id"],
                "outbox-recovery-attempt-3",
                retried["primary_authority_key"],
                retried["primary_authority_holder_ref"],
                retried["primary_authority_epoch"],
                primary_token,
                retried["authority_request_sha256"],
                retried["outbox_claim_ref"],
                retried["primary_authority_ref"],
                "retryable_failure",
                None,
                None,
                "email_provider_error",
                "effect-attempt:pg17-cross-family-fixture",
                "e" * 64,
            ),
        )
        connection.execute(
            """
            SELECT public.volpred_transfer_publisher_article_sync_owner(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                "legacy",
                1,
                "operations_core",
                "test:pg17-recovery",
                "create same-generation cross-family retry fixture",
                None,
            ),
        )
        connection.execute("RESET ROLE")
        connection.execute(
            """
            UPDATE volpred_ops.effect_outbox
            SET available_at = clock_timestamp() - interval '1 minute'
            WHERE effect_id = %s
            """,
            (owned_request["effect_id"],),
        )
        connection.execute(
            """
            UPDATE volpred_ops.owned_notification_requests
            SET effect_family = 'publisher.article.supabase.sync'
            WHERE effect_id = %s
            """,
            (owned_request["effect_id"],),
        )
        connection.execute("SET ROLE service_role")
        cross_family = connection.execute(
            """
            SELECT public.volpred_recover_expired_owned_email_notification(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                worker_id,
                300,
                "work-cross-family-must-not-recover",
                "outbox-cross-family-must-not-recover",
                primary_token,
            ),
        ).fetchone()[0]

    assert first_attempt["attempt_count"] == 1
    assert ordinary_retry_state == (1, "started", 1, "running")
    assert recovered["effect"]["id"] == owned_request["effect_id"]
    assert recovered["attempt_count"] == 2
    assert retry_receipt["disposition"] == "retry_scheduled"
    assert retried["effect"]["id"] == owned_request["effect_id"]
    assert retried["attempt_count"] == 3
    assert recovery_state == (
        "retry_scheduled",
        "recovered_after_expired_lease",
        "retry_scheduled",
        "started",
        2,
        True,
        True,
        True,
        True,
        True,
        True,
        True,
    )
    assert cross_family["recovered"] is False


def test_owned_publisher_transaction_cutover_delivery_and_rollback(
    postgres_effect_dsn: str,
) -> None:
    payload = {
        "schema_version": "publisher-article-sync.v1",
        "article": {
            "id": "mile_pg17_owned_publisher",
            "title": "PG17 owned publisher transaction",
            "content": "Canonical PG17 publisher fixture.",
            "description": "Publisher ownership fixture.",
            "status": "published",
            "audience": "research",
            "category": "milestone",
            "phase": "robustness",
            "published_at": "2026-07-24T12:00:00+00:00",
            "details": {"experiment_refs": ["K1708"]},
            "tags": ["K1708", "SPY"],
        },
    }
    work_token = "work-owned-publisher-token"
    outbox_token = "outbox-owned-publisher-token"
    primary_token = "primary-owned-publisher-token"
    worker_id = "effect-worker:publisher-article-sync"
    authority_key = "operations-core-primary"

    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("SET ROLE service_role")
        initial = connection.execute(
            "SELECT public.volpred_read_publisher_article_sync_owner()"
        ).fetchone()[0]
        assert (initial["owner"], initial["generation"]) == ("legacy", 1)

        with pytest.raises(
            psycopg.errors.RaiseException,
            match="does not own publisher article generation 1",
        ):
            connection.execute(
                """
                SELECT public.volpred_request_owned_publisher_article_sync(
                  %s, %s, %s, %s
                )
                """,
                (
                    1,
                    "publisher:pg17:pre-cutover",
                    Jsonb(payload),
                    "test:pg17",
                ),
            )

        cutover = connection.execute(
            """
            SELECT public.volpred_transfer_publisher_article_sync_owner(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                "legacy",
                1,
                "operations_core",
                "test:pg17",
                "exercise publisher ownership transaction",
                None,
            ),
        ).fetchone()[0]
        assert (cutover["owner"], cutover["generation"]) == (
            "operations_core",
            2,
        )

        owned_request = connection.execute(
            """
            SELECT public.volpred_request_owned_publisher_article_sync(
              %s, %s, %s, %s
            )
            """,
            (
                2,
                "publisher:pg17:owned-transaction",
                Jsonb(payload),
                "test:pg17",
            ),
        ).fetchone()[0]
        replayed_request = connection.execute(
            """
            SELECT public.volpred_request_owned_publisher_article_sync(
              %s, %s, %s, %s
            )
            """,
            (
                2,
                "publisher:pg17:owned-transaction",
                Jsonb(payload),
                "test:pg17",
            ),
        ).fetchone()[0]
        assert replayed_request == owned_request

        with pytest.raises(
            psycopg.errors.NoDataFound,
            match="query returned no rows",
        ):
            connection.execute(
                """
                SELECT public.volpred_begin_owned_publisher_article_sync(
                  %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    2,
                    owned_request["effect_id"],
                    worker_id,
                    300,
                    work_token,
                    outbox_token,
                    primary_token,
                ),
            )
        connection.execute("RESET ROLE")
        no_lease_state = connection.execute(
            """
            SELECT
              (SELECT status FROM volpred_ops.work_items WHERE id = %s),
              (SELECT version FROM volpred_ops.work_items WHERE id = %s),
              (SELECT status FROM volpred_ops.effect_outbox
               WHERE effect_id = %s),
              (SELECT count(*) FROM volpred_ops.owned_notification_attempts
               WHERE effect_id = %s)
            """,
            (
                owned_request["work_id"],
                owned_request["work_id"],
                owned_request["effect_id"],
                owned_request["effect_id"],
            ),
        ).fetchone()
        assert no_lease_state == ("pending", 1, "pending", 0)
        connection.execute("SET ROLE service_role")

        primary_lease = connection.execute(
            """
            SELECT public.volpred_acquire_primary_authority(
              %s, %s, %s, %s
            )
            """,
            (authority_key, worker_id, 300, primary_token),
        ).fetchone()[0]
        attempt = connection.execute(
            """
            SELECT public.volpred_begin_owned_publisher_article_sync(
              %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                2,
                owned_request["effect_id"],
                worker_id,
                300,
                work_token,
                outbox_token,
                primary_token,
            ),
        ).fetchone()[0]
        assert attempt["effect"]["effect_kind"] == (
            "publisher.article.supabase.sync"
        )
        assert attempt["effect"]["target_ref"] == (
            "supabase:articles/mile_pg17_owned_publisher"
        )

        with pytest.raises(
            psycopg.errors.RaiseException,
            match="requires zero active attempts",
        ):
            connection.execute(
                """
                SELECT public.volpred_transfer_publisher_article_sync_owner(
                  %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    "operations_core",
                    2,
                    "legacy",
                    "test:pg17",
                    "must reject transfer during active delivery",
                    2,
                ),
            )

        receipt = connection.execute(
            """
            SELECT public.volpred_settle_owned_publisher_article_sync(
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                2,
                attempt["work_id"],
                attempt["work_version"],
                work_token,
                attempt["effect"]["id"],
                attempt["outbox_sequence"],
                attempt["attempt_count"],
                attempt["worker_id"],
                outbox_token,
                attempt["primary_authority_key"],
                attempt["primary_authority_holder_ref"],
                attempt["primary_authority_epoch"],
                primary_token,
                attempt["authority_request_sha256"],
                attempt["outbox_claim_ref"],
                attempt["primary_authority_ref"],
                "acknowledged",
                attempt["effect"]["acknowledgement"]["kind"],
                attempt["effect"]["acknowledgement"]["target_ref"],
                None,
                "supabase:articles/mile_pg17_owned_publisher",
                "e" * 64,
            ),
        ).fetchone()[0]
        assert (
            receipt["work_status"],
            receipt["effect_status"],
            receipt["disposition"],
        ) == ("succeeded", "delivered", "delivered")
        terminal_replay = connection.execute(
            """
            SELECT public.volpred_request_owned_publisher_article_sync(
              %s, %s, %s, %s
            )
            """,
            (
                2,
                "publisher:pg17:owned-transaction",
                Jsonb(payload),
                "test:pg17",
            ),
        ).fetchone()[0]
        assert terminal_replay["work_id"] == owned_request["work_id"]
        assert terminal_replay["effect_id"] == owned_request["effect_id"]
        assert terminal_replay["receipt"] == receipt
        connection.execute("RESET ROLE")
        assert connection.execute(
            """
            SELECT count(*)
            FROM volpred_ops.owned_notification_attempts
            WHERE effect_id = %s
            """,
            (owned_request["effect_id"],),
        ).fetchone()[0] == 1

        held_after_settlement = connection.execute(
            """
            SELECT holder_ref, epoch
            FROM volpred_ops.primary_authority_lease_reads
            WHERE authority_key = %s
            """,
            (authority_key,),
        ).fetchone()
        assert held_after_settlement == (
            worker_id,
            primary_lease["epoch"],
        )
        connection.execute("SET ROLE service_role")
        connection.execute(
            """
            SELECT public.volpred_release_primary_authority(
              %s, %s, %s, %s
            )
            """,
            (
                authority_key,
                worker_id,
                primary_lease["epoch"],
                primary_token,
            ),
        )

        rollback = connection.execute(
            """
            SELECT public.volpred_transfer_publisher_article_sync_owner(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                "operations_core",
                2,
                "legacy",
                "test:pg17",
                "rehearse exact publisher rollback",
                2,
            ),
        ).fetchone()[0]
        assert (rollback["owner"], rollback["generation"]) == (
            "legacy",
            3,
        )
        assert connection.execute(
            """
            SELECT public.volpred_transfer_publisher_article_sync_owner(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                "operations_core",
                2,
                "legacy",
                "test:pg17",
                "rehearse exact publisher rollback",
                2,
            ),
        ).fetchone()[0] == rollback

        with pytest.raises(
            psycopg.errors.RaiseException,
            match="does not own publisher article generation 2",
        ):
            connection.execute(
                """
                SELECT public.volpred_request_owned_publisher_article_sync(
                  %s, %s, %s, %s
                )
                """,
                (
                    2,
                    "publisher:pg17:stale-owner",
                    Jsonb(payload),
                    "test:pg17",
                ),
            )

        recutover = connection.execute(
            """
            SELECT public.volpred_transfer_publisher_article_sync_owner(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                "legacy",
                3,
                "operations_core",
                "test:pg17",
                "restore publisher owner after rollback rehearsal",
                None,
            ),
        ).fetchone()[0]
        assert (recutover["owner"], recutover["generation"]) == (
            "operations_core",
            4,
        )

    with psycopg.connect(postgres_effect_dsn) as connection:
        durable_state = connection.execute(
            """
            SELECT
              (SELECT status FROM volpred_ops.work_items WHERE id = %s),
              (SELECT status FROM volpred_ops.effect_requests WHERE id = %s),
              (SELECT status FROM volpred_ops.effect_outbox
               WHERE effect_id = %s),
              (SELECT status FROM volpred_ops.owned_notification_attempts
               WHERE effect_id = %s),
              (SELECT count(*) FROM volpred_ops.effect_attempt_receipts
               WHERE effect_id = %s),
              (SELECT count(*) FROM volpred_ops.primary_authority_receipts
               WHERE authority_key = %s),
              (SELECT array_agg(owner ORDER BY generation)
               FROM volpred_ops.notification_owner_receipts
               WHERE effect_family =
                 'publisher.article.supabase.sync')
            """,
            (
                owned_request["work_id"],
                owned_request["effect_id"],
                owned_request["effect_id"],
                owned_request["effect_id"],
                owned_request["effect_id"],
                authority_key,
            ),
        ).fetchone()
    assert durable_state == (
        "succeeded",
        "delivered",
        "delivered",
        "delivered",
        1,
        1,
        ["legacy", "operations_core", "legacy", "operations_core"],
    )


def test_owned_publisher_recovery_consumes_due_retry_atomically(
    postgres_effect_dsn: str,
) -> None:
    payload = {
        "schema_version": "publisher-article-sync.v1",
        "article": {
            "id": "mile_pg17_owned_publisher_recovery",
            "title": "PG17 owned publisher recovery",
            "content": "Durable recovery fixture.",
            "description": "Publisher retry actuator fixture.",
            "status": "published",
            "audience": "research",
            "category": "milestone",
            "phase": "robustness",
            "published_at": "2026-07-26T09:00:00+00:00",
            "details": {},
            "tags": ["recovery"],
        },
    }
    worker_id = "effect-worker:publisher-article-sync"
    authority_key = "operations-core-primary"
    primary_token = "primary-owned-publisher-recovery-token"

    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("SET ROLE service_role")
        owner = connection.execute(
            """
            SELECT public.volpred_transfer_publisher_article_sync_owner(
              'legacy', 1, 'operations_core', 'test:recovery',
              'exercise due retry recovery', NULL
            )
            """
        ).fetchone()[0]
        request_view = connection.execute(
            """
            SELECT public.volpred_request_owned_publisher_article_sync(
              %s, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                "publisher:pg17:due-retry-recovery",
                Jsonb(payload),
                "test:recovery",
            ),
        ).fetchone()[0]
        connection.execute(
            """
            SELECT public.volpred_acquire_primary_authority(
              %s, %s, 300, %s
            )
            """,
            (authority_key, worker_id, primary_token),
        )
        attempt = connection.execute(
            """
            SELECT public.volpred_begin_owned_publisher_article_sync(
              %s, %s, %s, 300, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                request_view["effect_id"],
                worker_id,
                "work-retry-attempt-1",
                "outbox-retry-attempt-1",
                primary_token,
            ),
        ).fetchone()[0]
        retry_receipt = connection.execute(
            """
            SELECT public.volpred_settle_owned_publisher_article_sync(
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                attempt["work_id"],
                attempt["work_version"],
                "work-retry-attempt-1",
                attempt["effect"]["id"],
                attempt["outbox_sequence"],
                attempt["attempt_count"],
                attempt["worker_id"],
                "outbox-retry-attempt-1",
                attempt["primary_authority_key"],
                attempt["primary_authority_holder_ref"],
                attempt["primary_authority_epoch"],
                primary_token,
                attempt["authority_request_sha256"],
                attempt["outbox_claim_ref"],
                attempt["primary_authority_ref"],
                "retryable_failure",
                None,
                None,
                "publisher_projection_temporarily_unavailable",
                "test:publisher-recovery:attempt-1",
                "a" * 64,
            ),
        ).fetchone()[0]
        assert retry_receipt["disposition"] == "retry_scheduled"

        connection.execute("RESET ROLE")
        connection.execute(
            """
            UPDATE volpred_ops.effect_outbox
            SET available_at = clock_timestamp() - interval '1 second'
            WHERE effect_id = %s
            """,
            (request_view["effect_id"],),
        )
        connection.execute("SET ROLE service_role")
        recovered = connection.execute(
            """
            SELECT public.volpred_recover_due_owned_publisher_article_sync(
              %s, %s, 300, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                worker_id,
                "work-retry-attempt-2",
                "outbox-retry-attempt-2",
                primary_token,
            ),
        ).fetchone()[0]
        assert recovered["recovered"] is True
        assert recovered["attempt_count"] == 2
        assert recovered["effect"]["id"] == request_view["effect_id"]

        connection.execute("RESET ROLE")
        durable = connection.execute(
            """
            SELECT
              (SELECT status
               FROM volpred_ops.owned_notification_attempts
               WHERE effect_id = %s AND attempt_count = 1),
              (SELECT evidence_ref
               FROM volpred_ops.owned_notification_attempts
               WHERE effect_id = %s AND attempt_count = 1),
              (SELECT status
               FROM volpred_ops.owned_notification_attempts
               WHERE effect_id = %s AND attempt_count = 2),
              (SELECT reason_code
               FROM volpred_ops.owned_publisher_article_recovery_receipts
               WHERE effect_id = %s AND candidate_attempt_count = 1)
            """,
            (
                request_view["effect_id"],
                request_view["effect_id"],
                request_view["effect_id"],
                request_view["effect_id"],
            ),
        ).fetchone()
        assert durable == (
            "retry_scheduled",
            "test:publisher-recovery:attempt-1",
            "started",
            "retry_due_without_actuator",
        )


def test_owned_publisher_expired_attempt_requires_recovery_seam(
    postgres_effect_dsn: str,
) -> None:
    payload = {
        "schema_version": "publisher-article-sync.v1",
        "article": {
            "id": "mile_pg17_owned_publisher_expired",
            "title": "Expired publisher attempt",
            "content": "Expired-attempt fixture.",
            "description": "Ordinary begin must fail closed.",
            "status": "published",
            "audience": "research",
            "category": "milestone",
            "phase": "robustness",
            "published_at": "2026-07-26T09:05:00+00:00",
            "details": {},
            "tags": ["recovery"],
        },
    }
    worker_id = "effect-worker:publisher-article-sync"
    primary_token = "primary-owned-publisher-expired-token"

    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("SET ROLE service_role")
        owner = connection.execute(
            """
            SELECT public.volpred_transfer_publisher_article_sync_owner(
              'legacy', 1, 'operations_core', 'test:expired-recovery',
              'exercise expired attempt recovery', NULL
            )
            """
        ).fetchone()[0]
        request_view = connection.execute(
            """
            SELECT public.volpred_request_owned_publisher_article_sync(
              %s, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                "publisher:pg17:expired-recovery",
                Jsonb(payload),
                "test:expired-recovery",
            ),
        ).fetchone()[0]
        connection.execute(
            """
            SELECT public.volpred_acquire_primary_authority(
              'operations-core-primary', %s, 300, %s
            )
            """,
            (worker_id, primary_token),
        )
        first = connection.execute(
            """
            SELECT public.volpred_begin_owned_publisher_article_sync(
              %s, %s, %s, 300, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                request_view["effect_id"],
                worker_id,
                "work-expired-attempt-1",
                "outbox-expired-attempt-1",
                primary_token,
            ),
        ).fetchone()[0]

        connection.execute("RESET ROLE")
        connection.execute(
            """
            UPDATE volpred_ops.work_items
            SET claim_expires_at = clock_timestamp() - interval '1 second'
            WHERE id = %s
            """,
            (first["work_id"],),
        )
        connection.execute(
            """
            UPDATE volpred_ops.effect_outbox
            SET claim_expires_at = clock_timestamp() - interval '1 second'
            WHERE effect_id = %s
            """,
            (first["effect"]["id"],),
        )
        connection.execute(
            """
            UPDATE volpred_ops.owned_notification_attempts
            SET lease_expires_at = clock_timestamp() - interval '1 second'
            WHERE effect_id = %s AND attempt_count = 1
            """,
            (first["effect"]["id"],),
        )
        before = connection.execute(
            """
            SELECT
              (SELECT version FROM volpred_ops.work_items WHERE id = %s),
              (SELECT attempt_count FROM volpred_ops.effect_outbox
               WHERE effect_id = %s),
              (SELECT count(*) FROM volpred_ops.owned_notification_attempts
               WHERE effect_id = %s)
            """,
            (
                first["work_id"],
                first["effect"]["id"],
                first["effect"]["id"],
            ),
        ).fetchone()

        connection.execute("SET ROLE service_role")
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="predecessor requires recovery",
        ):
            connection.execute(
                """
                SELECT public.volpred_begin_owned_publisher_article_sync(
                  %s, %s, %s, 300, %s, %s, %s
                )
                """,
                (
                    owner["generation"],
                    request_view["effect_id"],
                    worker_id,
                    "ordinary-work-token",
                    "ordinary-outbox-token",
                    primary_token,
                ),
            )
        connection.execute("RESET ROLE")
        after_failed_begin = connection.execute(
            """
            SELECT
              (SELECT version FROM volpred_ops.work_items WHERE id = %s),
              (SELECT attempt_count FROM volpred_ops.effect_outbox
               WHERE effect_id = %s),
              (SELECT count(*) FROM volpred_ops.owned_notification_attempts
               WHERE effect_id = %s)
            """,
            (
                first["work_id"],
                first["effect"]["id"],
                first["effect"]["id"],
            ),
        ).fetchone()
        assert after_failed_begin == before

        connection.execute("SET ROLE service_role")
        recovered = connection.execute(
            """
            SELECT public.volpred_recover_due_owned_publisher_article_sync(
              %s, %s, 300, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                worker_id,
                "work-expired-attempt-2",
                "outbox-expired-attempt-2",
                primary_token,
            ),
        ).fetchone()[0]
        assert recovered["attempt_count"] == 2

        connection.execute("RESET ROLE")
        assert connection.execute(
            """
            SELECT candidate_status, reason_code
            FROM volpred_ops.owned_publisher_article_recovery_receipts
            WHERE effect_id = %s
            """,
            (first["effect"]["id"],),
        ).fetchone() == (
            "started",
            "worker_interrupted_after_begin",
        )


def test_owned_publisher_reconcile_cutover_delivery_and_rollback(
    postgres_effect_dsn: str,
) -> None:
    payload = {
        "schema_version": "publisher-article-reconcile.v1",
        "canonical_feed_sha256": "f" * 64,
        "articles": [
            {
                "id": "mile_pg17_reconcile",
                "title": "PG17 reconcile transaction",
                "content": "Canonical reconcile fixture.",
                "status": "published",
                "tags": ["K1708"],
            }
        ],
    }
    worker_id = "effect-worker:publisher-article-reconcile"
    authority_key = "operations-core-primary"
    work_token = "work-owned-reconcile-token"
    outbox_token = "outbox-owned-reconcile-token"
    primary_token = "primary-owned-reconcile-token"

    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("SET ROLE service_role")
        initial = connection.execute(
            "SELECT public.volpred_read_publisher_article_reconcile_owner()"
        ).fetchone()[0]
        assert (initial["owner"], initial["generation"]) == ("legacy", 1)

        with pytest.raises(
            psycopg.errors.RaiseException,
            match="does not own publisher reconcile batch generation 1",
        ):
            connection.execute(
                """
                SELECT public.volpred_request_owned_publisher_article_reconcile(
                  %s, %s, %s, %s
                )
                """,
                (1, "reconcile:pre-cutover", Jsonb(payload), "test:pg17"),
            )

        cutover = connection.execute(
            """
            SELECT public.volpred_transfer_publisher_article_reconcile_owner(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                "legacy",
                1,
                "operations_core",
                "test:pg17",
                "exercise safe reconcile ownership",
                None,
            ),
        ).fetchone()[0]
        assert (cutover["owner"], cutover["generation"]) == (
            "operations_core",
            2,
        )

        owned_request = connection.execute(
            """
            SELECT public.volpred_request_owned_publisher_article_reconcile(
              %s, %s, %s, %s
            )
            """,
            (
                2,
                "reconcile:owned-transaction",
                Jsonb(payload),
                "test:pg17",
            ),
        ).fetchone()[0]
        replay = connection.execute(
            """
            SELECT public.volpred_request_owned_publisher_article_reconcile(
              %s, %s, %s, %s
            )
            """,
            (
                2,
                "reconcile:owned-transaction",
                Jsonb(payload),
                "test:pg17",
            ),
        ).fetchone()[0]
        assert replay == owned_request
        assert owned_request["receipt"] is None

        connection.execute(
            """
            SELECT public.volpred_acquire_primary_authority(
              %s, %s, %s, %s
            )
            """,
            (authority_key, worker_id, 300, primary_token),
        )
        attempt = connection.execute(
            """
            SELECT public.volpred_begin_owned_publisher_article_reconcile(
              %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                2,
                owned_request["effect_id"],
                worker_id,
                300,
                work_token,
                outbox_token,
                primary_token,
            ),
        ).fetchone()[0]
        assert attempt["effect"]["effect_kind"] == (
            "publisher.article.supabase.reconcile"
        )
        assert attempt["effect"]["target_ref"] == "supabase:articles"
        assert attempt["effect"]["risk"] == "safe"
        assert attempt["effect"]["acknowledgement"] == {
            "kind": "publisher.article.supabase.reconcile.readback",
            "target_ref": "supabase:articles",
        }

        with pytest.raises(
            psycopg.errors.RaiseException,
            match="requires zero active attempts",
        ):
            connection.execute(
                """
                SELECT public.volpred_transfer_publisher_article_reconcile_owner(
                  %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    "operations_core",
                    2,
                    "legacy",
                    "test:pg17",
                    "reject active rollback",
                    2,
                ),
            )

        receipt = connection.execute(
            """
            SELECT public.volpred_settle_owned_publisher_article_reconcile(
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                2,
                attempt["work_id"],
                attempt["work_version"],
                work_token,
                attempt["effect"]["id"],
                attempt["outbox_sequence"],
                attempt["attempt_count"],
                attempt["worker_id"],
                outbox_token,
                attempt["primary_authority_key"],
                attempt["primary_authority_holder_ref"],
                attempt["primary_authority_epoch"],
                primary_token,
                attempt["authority_request_sha256"],
                attempt["outbox_claim_ref"],
                attempt["primary_authority_ref"],
                "acknowledged",
                attempt["effect"]["acknowledgement"]["kind"],
                attempt["effect"]["acknowledgement"]["target_ref"],
                None,
                "supabase:articles:reconcile:" + "f" * 64,
                "e" * 64,
            ),
        ).fetchone()[0]
        assert (
            receipt["work_status"],
            receipt["effect_status"],
            receipt["disposition"],
        ) == ("succeeded", "delivered", "delivered")

        terminal = connection.execute(
            """
            SELECT public.volpred_request_owned_publisher_article_reconcile(
              %s, %s, %s, %s
            )
            """,
            (
                2,
                "reconcile:owned-transaction",
                Jsonb(payload),
                "test:pg17",
            ),
        ).fetchone()[0]
        assert terminal["receipt"] == receipt

        connection.execute(
            """
            SELECT public.volpred_release_primary_authority(
              %s, %s, %s, %s
            )
            """,
            (
                authority_key,
                worker_id,
                attempt["primary_authority_epoch"],
                primary_token,
            ),
        )
        rollback = connection.execute(
            """
            SELECT public.volpred_transfer_publisher_article_reconcile_owner(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                "operations_core",
                2,
                "legacy",
                "test:pg17",
                "exact reconcile rollback",
                2,
            ),
        ).fetchone()[0]
        assert (rollback["owner"], rollback["generation"]) == ("legacy", 3)

        with pytest.raises(
            psycopg.errors.RaiseException,
            match="does not own publisher reconcile batch generation 2",
        ):
            connection.execute(
                """
                SELECT public.volpred_request_owned_publisher_article_reconcile(
                  %s, %s, %s, %s
                )
                """,
                (2, "reconcile:stale", Jsonb(payload), "test:pg17"),
            )

        recutover = connection.execute(
            """
            SELECT public.volpred_transfer_publisher_article_reconcile_owner(
              %s, %s, %s, %s, %s, %s
            )
            """,
            (
                "legacy",
                3,
                "operations_core",
                "test:pg17",
                "restore reconcile owner",
                None,
            ),
        ).fetchone()[0]
        assert (recutover["owner"], recutover["generation"]) == (
            "operations_core",
            4,
        )

    with psycopg.connect(postgres_effect_dsn) as connection:
        durable = connection.execute(
            """
            SELECT
              (SELECT status FROM volpred_ops.work_items WHERE id = %s),
              (SELECT status FROM volpred_ops.effect_requests WHERE id = %s),
              (SELECT status FROM volpred_ops.effect_outbox
               WHERE effect_id = %s),
              (SELECT count(*) FROM volpred_ops.effect_attempt_receipts
               WHERE effect_id = %s),
              (SELECT array_agg(owner ORDER BY generation)
               FROM volpred_ops.notification_owner_receipts
               WHERE effect_family =
                 'publisher.article.supabase.reconcile')
            """,
            (
                owned_request["work_id"],
                owned_request["effect_id"],
                owned_request["effect_id"],
                owned_request["effect_id"],
            ),
        ).fetchone()
    assert durable == (
        "succeeded",
        "delivered",
        "delivered",
        1,
        ["legacy", "operations_core", "legacy", "operations_core"],
    )


def test_owned_publisher_reconcile_rpc_security_shape(
    postgres_effect_dsn: str,
) -> None:
    functions = (
        "volpred_read_publisher_article_reconcile_owner",
        "volpred_transfer_publisher_article_reconcile_owner",
        "volpred_request_owned_publisher_article_reconcile",
        "volpred_begin_owned_publisher_article_reconcile",
        "volpred_recover_due_owned_publisher_article_reconcile",
        "volpred_settle_owned_publisher_article_reconcile",
    )
    with psycopg.connect(postgres_effect_dsn) as connection:
        rows = connection.execute(
            """
            SELECT
              procedure.proname,
              procedure.proowner = (
                SELECT oid FROM pg_roles
                WHERE rolname = 'volpred_ops_definer'
              ),
              procedure.prosecdef,
              procedure.proconfig = ARRAY['search_path=""'],
              has_function_privilege(
                'service_role', procedure.oid, 'EXECUTE'
              ),
              has_function_privilege('anon', procedure.oid, 'EXECUTE'),
              has_function_privilege(
                'authenticated', procedure.oid, 'EXECUTE'
              ),
              has_function_privilege('public', procedure.oid, 'EXECUTE'),
              pg_get_functiondef(procedure.oid)
            FROM pg_proc AS procedure
            JOIN pg_namespace AS namespace
              ON namespace.oid = procedure.pronamespace
            WHERE namespace.nspname = 'public'
              AND procedure.proname = ANY(%s)
            ORDER BY procedure.proname
            """,
            (list(functions),),
        ).fetchall()
        service_table_access = connection.execute(
            """
            SELECT bool_or(
              has_table_privilege('service_role', relation.oid, 'SELECT')
              OR has_table_privilege(
                'service_role', relation.oid, 'INSERT,UPDATE,DELETE'
              )
            )
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'volpred_ops'
              AND relation.relname IN (
                'notification_owners',
                'owned_notification_requests',
                'owned_notification_attempts',
                'effect_payloads',
                'effect_requests',
                'effect_outbox'
              )
            """
        ).fetchone()[0]

    assert len(rows) == 6
    expected_privileges = (True, True, True, True, False, False, False)
    assert all(row[1:8] == expected_privileges for row in rows)
    assert service_table_access is False
    definitions = "\n".join(row[8] for row in rows)
    assert "publisher.article.supabase.reconcile" in definitions
    assert "operations-core-primary" in definitions
    assert "publisher:article.supabase.reconcile" not in definitions
    assert "publisher.article.supabase.reconcile.readback" in definitions
    assert "supabase:articles" in definitions
    assert "FOR UPDATE OF attempt SKIP LOCKED" in definitions


def test_due_publisher_reconcile_retry_recovers_original_effect(
    postgres_effect_dsn: str,
) -> None:
    payload = {
        "schema_version": "publisher-article-reconcile.v1",
        "canonical_feed_sha256": "8" * 64,
        "articles": [
            {
                "id": "mile_partial_a",
                "title": "Partial A",
                "content": "A",
                "status": "published",
            },
            {
                "id": "mile_partial_b",
                "title": "Partial B",
                "content": "B",
                "status": "published",
            },
        ],
    }
    worker = "effect-worker:publisher-article-reconcile"
    authority = "operations-core-primary"
    with psycopg.connect(
        postgres_effect_dsn,
        autocommit=True,
    ) as connection:
        connection.execute("SET ROLE service_role")
        owner = connection.execute(
            """
            SELECT public.volpred_transfer_publisher_article_reconcile_owner(
              'legacy', 1, 'operations_core', 'test:recovery',
              'exercise due batch recovery', NULL
            )
            """
        ).fetchone()[0]
        request_view = connection.execute(
            """
            SELECT public.volpred_request_owned_publisher_article_reconcile(
              %s, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                "reconcile:partial-recovery",
                Jsonb(payload),
                "test:recovery",
            ),
        ).fetchone()[0]
        connection.execute(
            """
            SELECT public.volpred_acquire_primary_authority(
              %s, %s, 300, 'primary-recovery-token'
            )
            """,
            (authority, worker),
        )
        attempt_one = connection.execute(
            """
            SELECT public.volpred_begin_owned_publisher_article_reconcile(
              %s, %s, %s, 300, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                request_view["effect_id"],
                worker,
                "work-recovery-1",
                "outbox-recovery-1",
                "primary-recovery-token",
            ),
        ).fetchone()[0]
        retry = connection.execute(
            """
            SELECT public.volpred_settle_owned_publisher_article_reconcile(
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                attempt_one["work_id"],
                attempt_one["work_version"],
                "work-recovery-1",
                attempt_one["effect"]["id"],
                attempt_one["outbox_sequence"],
                attempt_one["attempt_count"],
                worker,
                "outbox-recovery-1",
                attempt_one["primary_authority_key"],
                attempt_one["primary_authority_holder_ref"],
                attempt_one["primary_authority_epoch"],
                "primary-recovery-token",
                attempt_one["authority_request_sha256"],
                attempt_one["outbox_claim_ref"],
                attempt_one["primary_authority_ref"],
                "retryable_failure",
                None,
                None,
                "publisher_article_reconcile_provider_error",
                (
                    "effect-attempt:"
                    + attempt_one["effect"]["id"]
                    + ":partial|mirror:cache/mile_partial_b#status=503"
                ),
                "7" * 64,
            ),
        ).fetchone()[0]
        assert retry["disposition"] == "retry_scheduled"

        connection.execute("RESET ROLE")
        connection.execute(
            """
            UPDATE volpred_ops.effect_outbox
            SET available_at = clock_timestamp() - interval '1 second'
            WHERE effect_id = %s
            """,
            (request_view["effect_id"],),
        )
        connection.execute("SET ROLE service_role")
        attempt_two = connection.execute(
            """
            SELECT public.volpred_recover_due_owned_publisher_article_reconcile(
              %s, %s, 300, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                worker,
                "work-recovery-2",
                "outbox-recovery-2",
                "primary-recovery-token",
            ),
        ).fetchone()[0]
        assert attempt_two["recovered"] is True
        assert attempt_two["effect"]["id"] == request_view["effect_id"]
        assert attempt_two["payload_base64"] == attempt_one["payload_base64"]
        assert attempt_two["attempt_count"] == 2

        delivered = connection.execute(
            """
            SELECT public.volpred_settle_owned_publisher_article_reconcile(
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                owner["generation"],
                attempt_two["work_id"],
                attempt_two["work_version"],
                "work-recovery-2",
                attempt_two["effect"]["id"],
                attempt_two["outbox_sequence"],
                attempt_two["attempt_count"],
                worker,
                "outbox-recovery-2",
                attempt_two["primary_authority_key"],
                attempt_two["primary_authority_holder_ref"],
                attempt_two["primary_authority_epoch"],
                "primary-recovery-token",
                attempt_two["authority_request_sha256"],
                attempt_two["outbox_claim_ref"],
                attempt_two["primary_authority_ref"],
                "acknowledged",
                attempt_two["effect"]["acknowledgement"]["kind"],
                attempt_two["effect"]["acknowledgement"]["target_ref"],
                None,
                "supabase:articles:reconcile:" + "8" * 64,
                "6" * 64,
            ),
        ).fetchone()[0]
        assert delivered["disposition"] == "delivered"

        connection.execute("RESET ROLE")
        state = connection.execute(
            """
            SELECT
              (SELECT status FROM volpred_ops.work_items WHERE id = %s),
              (SELECT status FROM volpred_ops.effect_requests WHERE id = %s),
              (SELECT status FROM volpred_ops.effect_outbox
               WHERE effect_id = %s),
              (SELECT count(*)
               FROM volpred_ops.owned_publisher_reconcile_recovery_receipts
               WHERE effect_id = %s)
            """,
            (
                request_view["work_id"],
                request_view["effect_id"],
                request_view["effect_id"],
                request_view["effect_id"],
            ),
        ).fetchone()
        assert state == ("succeeded", "delivered", "delivered", 1)


def test_owned_publisher_rpc_security_and_definition_shape(
    postgres_effect_dsn: str,
) -> None:
    function_names = (
        "volpred_read_publisher_article_sync_owner",
        "volpred_transfer_publisher_article_sync_owner",
        "volpred_request_owned_publisher_article_sync",
        "volpred_begin_owned_publisher_article_sync",
        "volpred_recover_due_owned_publisher_article_sync",
        "volpred_settle_owned_publisher_article_sync",
    )
    with psycopg.connect(postgres_effect_dsn) as connection:
        rows = connection.execute(
            """
            SELECT
              procedure.proname,
              procedure.proowner = (
                SELECT oid FROM pg_roles
                WHERE rolname = 'volpred_ops_definer'
              ) AS owned_by_definer,
              procedure.prosecdef,
              procedure.proconfig = ARRAY['search_path=""'],
              has_function_privilege(
                'service_role', procedure.oid, 'EXECUTE'
              ) AS service_execute,
              has_function_privilege(
                'anon', procedure.oid, 'EXECUTE'
              ) AS anon_execute,
              has_function_privilege(
                'authenticated', procedure.oid, 'EXECUTE'
              ) AS authenticated_execute,
              has_function_privilege(
                'public', procedure.oid, 'EXECUTE'
              ) AS public_execute,
              pg_get_functiondef(procedure.oid)
            FROM pg_proc AS procedure
            JOIN pg_namespace AS namespace
              ON namespace.oid = procedure.pronamespace
            WHERE namespace.nspname = 'public'
              AND procedure.proname = ANY(%s)
            ORDER BY procedure.proname
            """,
            (list(function_names),),
        ).fetchall()
        service_table_access = connection.execute(
            """
            SELECT bool_or(
              has_table_privilege(
                'service_role', relation.oid, 'SELECT'
              )
            )
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'volpred_ops'
              AND relation.relname IN (
                'notification_owners',
                'notification_owner_receipts',
                'owned_notification_requests',
                'owned_notification_attempts'
              )
            """
        ).fetchone()[0]
        definer_public_create = connection.execute(
            """
            SELECT has_schema_privilege(
              'volpred_ops_definer', 'public', 'CREATE'
            )
            """
        ).fetchone()[0]

    assert len(rows) == 6
    assert all(
        row[1:8] == (True, True, True, True, False, False, False)
        for row in rows
    )
    definitions = {row[0]: row[8] for row in rows}
    assert (
        "FROM volpred_ops.primary_authority_lease_reads"
        in definitions["volpred_begin_owned_publisher_article_sync"]
    )
    recovery_definition = definitions[
        "volpred_recover_due_owned_publisher_article_sync"
    ]
    assert (
        "owned_request.effect_family = ownership.effect_family"
        in recovery_definition
    )
    assert (
        "effect.effect_kind = ownership.effect_family"
        in recovery_definition
    )
    assert "FOR UPDATE OF attempt SKIP LOCKED" in recovery_definition
    settlement_definition = definitions[
        "volpred_settle_owned_publisher_article_sync"
    ]
    assert (
        "FROM volpred_ops.primary_authority_leases"
        in settlement_definition
    )
    assert (
        "FROM volpred_ops.primary_authority_lease_reads"
        not in settlement_definition
    )
    assert "fencing_token_sha256" in settlement_definition
    assert (
        "acquire_primary_authority"
        not in definitions["volpred_begin_owned_publisher_article_sync"]
    )
    assert (
        "release_primary_authority"
        not in definitions["volpred_settle_owned_publisher_article_sync"]
    )
    assert service_table_access is False
    assert definer_public_create is False
