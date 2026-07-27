from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import hashlib
import hmac
import shutil
import socket
import subprocess

import psycopg
import pytest
from psycopg.types.json import Jsonb

from volpred.analytics import AnalyticsEvent, AnalyticsPrivacyTracer
from volpred.analytics.postgres import PostgresAnalyticsStore


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = next(
    (REPO_ROOT / "supabase" / "migrations").glob(
        "*_analytics_privacy_tracer.sql"
    )
)
INGRESS_MIGRATION = next(
    (REPO_ROOT / "supabase" / "migrations").glob(
        "*_analytics_ingress_rpc.sql"
    )
)
TEST_TOMBSTONE_SECRET = b"analytics-postgres-test-secret-32b"
TEST_DIGEST_KEY_ID = "pytest-v1"


def _postgres_bin_dir() -> Path | None:
    homebrew = Path("/opt/homebrew/opt/postgresql@17/bin")
    if (homebrew / "postgres").exists():
        return homebrew
    pg_config = shutil.which("pg_config")
    if pg_config is None:
        return None
    bindir = Path(
        subprocess.check_output(
            (pg_config, "--bindir"),
            text=True,
        ).strip()
    )
    return bindir if (bindir / "postgres").exists() else None


@pytest.fixture(scope="session")
def analytics_postgres_dsn(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[str]:
    bin_dir = _postgres_bin_dir()
    if bin_dir is None:
        if __import__("os").environ.get("CI"):
            pytest.fail("PostgreSQL server binaries are required in CI")
        pytest.skip("PostgreSQL server binaries are required")
    root = tmp_path_factory.mktemp("analytics-privacy-postgres")
    data_dir = root / "data"
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    subprocess.run(
        (
            str(bin_dir / "initdb"),
            "--auth=trust",
            "--encoding=UTF8",
            "--no-locale",
            "-D",
            str(data_dir),
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
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(
                "CREATE ROLE analytics_migration_runner "
                "NOLOGIN CREATEROLE BYPASSRLS"
            )
            connection.execute(
                "GRANT CREATE ON DATABASE postgres "
                "TO analytics_migration_runner"
            )
            connection.execute(
                "GRANT CREATE ON SCHEMA public "
                "TO analytics_migration_runner"
            )
            connection.execute("CREATE ROLE anon NOLOGIN")
            connection.execute("CREATE ROLE authenticated NOLOGIN")
            connection.execute("CREATE ROLE service_role NOLOGIN")
            connection.execute("SET ROLE analytics_migration_runner")
            connection.execute(MIGRATION.read_text(encoding="utf-8"))
            connection.execute(MIGRATION.read_text(encoding="utf-8"))
            connection.execute(INGRESS_MIGRATION.read_text(encoding="utf-8"))
            connection.execute(INGRESS_MIGRATION.read_text(encoding="utf-8"))
            connection.execute("RESET ROLE")
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
def reset_analytics_state(analytics_postgres_dsn: str) -> None:
    with psycopg.connect(
        analytics_postgres_dsn, autocommit=True
    ) as connection:
        connection.execute(
            """
            TRUNCATE TABLE
              volpred_analytics.privacy_action_receipts,
              volpred_analytics.privacy_tombstones,
              volpred_analytics.event_dedupe_tombstones,
              volpred_analytics.identity_merge_receipts,
              volpred_analytics.privacy_preferences,
              volpred_analytics.identity_links,
              volpred_analytics.events
            RESTART IDENTITY
            """
        )


def _worker_connection(dsn: str) -> psycopg.Connection:
    connection = psycopg.connect(dsn)
    connection.execute("SET ROLE volpred_analytics_worker")
    return connection


def _ingress_args(
    *,
    idempotency_key: str = "impression:home:anon-rpc:2026-07-27",
    kind: str = "content_impression",
    properties: Jsonb = Jsonb(
        {"content_id": "article-rpc", "surface": "home"}
    ),
) -> tuple[object, ...]:
    return (
        idempotency_key,
        kind,
        "2026-07-27T00:00:00+00:00",
        "anon-rpc",
        None,
        properties,
        b"p" * 32,
        b"k" * 32,
        TEST_DIGEST_KEY_ID,
        hmac.new(
            TEST_TOMBSTONE_SECRET,
            f"digest-key-verifier:{TEST_DIGEST_KEY_ID}".encode(),
            hashlib.sha256,
        ).digest(),
        b"a" * 32,
        None,
    )


INGRESS_SQL = """
SELECT public.record_volpred_analytics_event(
  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
"""


def test_ingress_is_server_only_and_keeps_tables_private(
    analytics_postgres_dsn: str,
) -> None:
    with psycopg.connect(analytics_postgres_dsn) as connection:
        function_name = (
            "public.record_volpred_analytics_event("
            "text,text,timestamp with time zone,text,text,jsonb,"
            "bytea,bytea,text,bytea,bytea,bytea)"
        )
        privileges = {
            role: connection.execute(
                """
                SELECT
                  has_function_privilege(%s, %s, 'EXECUTE'),
                  has_schema_privilege(
                    %s, 'volpred_analytics', 'USAGE'
                  ),
                  has_table_privilege(
                    %s, 'volpred_analytics.events', 'SELECT'
                  )
                """,
                (role, function_name, role, role),
            ).fetchone()
            for role in ("public", "anon", "authenticated", "service_role")
        }
        owner = connection.execute(
            """
            SELECT pg_get_userbyid(p.proowner), p.prosecdef
            FROM pg_proc AS p
            JOIN pg_namespace AS n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public'
              AND p.proname = 'record_volpred_analytics_event'
            """
        ).fetchone()

    assert privileges["public"] == (False, False, False)
    assert privileges["anon"] == (False, False, False)
    assert privileges["authenticated"] == (False, False, False)
    assert privileges["service_role"] == (True, False, False)
    assert owner == ("analytics_migration_runner", True)


def test_ingress_accepts_once_and_replays_without_duplicate_row(
    analytics_postgres_dsn: str,
) -> None:
    with psycopg.connect(analytics_postgres_dsn) as connection:
        connection.execute("SET ROLE service_role")
        first = connection.execute(
            INGRESS_SQL, _ingress_args()
        ).fetchone()[0]
        replay = connection.execute(
            INGRESS_SQL, _ingress_args()
        ).fetchone()[0]
        connection.execute("RESET ROLE")
        count = connection.execute(
            "SELECT count(*) FROM volpred_analytics.events"
        ).fetchone()[0]

    assert first["accepted"] is True
    assert first["duplicate"] is False
    assert replay["accepted"] is True
    assert replay["duplicate"] is True
    assert count == 1


def test_ingress_rejects_conflicting_replay_and_invalid_contract(
    analytics_postgres_dsn: str,
) -> None:
    with psycopg.connect(analytics_postgres_dsn) as connection:
        connection.execute("SET ROLE service_role")
        connection.execute(INGRESS_SQL, _ingress_args())
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="idempotency_key was reused",
        ):
            connection.execute(
                INGRESS_SQL,
                (*_ingress_args()[:6], b"x" * 32, *_ingress_args()[7:]),
            )
        connection.rollback()
        connection.execute("SET ROLE service_role")
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="undeclared property",
        ):
            connection.execute(
                INGRESS_SQL,
                _ingress_args(
                    idempotency_key="impression:undeclared",
                    properties=Jsonb(
                        {
                            "content_id": "article-rpc",
                            "surface": "home",
                            "portfolio_position": "secret",
                        }
                    ),
                ),
            )


def test_migration_keeps_analytics_private_and_enables_rls(
    analytics_postgres_dsn: str,
) -> None:
    with psycopg.connect(analytics_postgres_dsn) as connection:
        rows = connection.execute(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                   has_table_privilege('public', c.oid, 'SELECT')
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'volpred_analytics'
              AND c.relkind = 'r'
            ORDER BY c.relname
            """
        ).fetchall()
        public_has_schema_usage = connection.execute(
            """
            SELECT has_schema_privilege(
              'public', 'volpred_analytics', 'USAGE'
            )
            """
        ).fetchone()[0]
        worker = connection.execute(
            """
            SELECT rolcanlogin, rolbypassrls, rolsuper
            FROM pg_roles
            WHERE rolname = 'volpred_analytics_worker'
            """
        ).fetchone()
        worker_can_read_events = connection.execute(
            """
            SELECT has_table_privilege(
              'volpred_analytics_worker',
              'volpred_analytics.events',
              'SELECT'
            )
            """
        ).fetchone()[0]

    assert rows
    assert all(row[1] is True for row in rows)
    assert all(row[2] is True for row in rows)
    assert all(row[3] is False for row in rows)
    assert public_has_schema_usage is False
    assert worker == (False, False, False)
    assert worker_can_read_events is True


def test_postgres_adapter_replays_merge_and_privacy_lifecycle(
    analytics_postgres_dsn: str,
) -> None:
    tracer = AnalyticsPrivacyTracer(
        PostgresAnalyticsStore(
            lambda: _worker_connection(analytics_postgres_dsn),
            tombstone_secret=TEST_TOMBSTONE_SECRET,
            digest_key_id=TEST_DIGEST_KEY_ID,
        )
    )
    event = AnalyticsEvent(
        idempotency_key="impression:home:anon-pg:2026-07-26",
        kind="content_impression",
        occurred_at="2026-07-26T15:40:00+00:00",
        anonymous_id="anon-pg",
        user_id=None,
        properties={"content_id": "article-pg", "surface": "home"},
    )

    first = tracer.record(event)
    replay = tracer.record(event)
    merged = tracer.merge_identity(
        idempotency_key="merge:anon-pg:user-pg",
        anonymous_id="anon-pg",
        user_id="user-pg",
        merged_at="2026-07-26T15:45:00+00:00",
    )
    merge_replay = tracer.merge_identity(
        idempotency_key="merge:anon-pg:user-pg",
        anonymous_id="anon-pg",
        user_id="user-pg",
        merged_at="2026-07-26T15:45:00+00:00",
    )
    tracer.set_opt_out(
        "user:user-pg",
        idempotency_key="opt-out:user-pg",
        acted_at="2026-07-26T15:50:00+00:00",
    )

    assert first.duplicate is False
    assert replay.duplicate is True
    assert merged.merged_events == 1
    assert merge_replay.duplicate is True
    assert merge_replay.merged_events == 1
    second_key = tracer.merge_identity(
        idempotency_key="merge:anon-pg:user-pg:second",
        anonymous_id="anon-pg",
        user_id="user-pg",
        merged_at="2026-07-26T15:46:00+00:00",
    )
    second_key_replay = tracer.merge_identity(
        idempotency_key="merge:anon-pg:user-pg:second",
        anonymous_id="anon-pg",
        user_id="user-pg",
        merged_at="2026-07-26T15:46:00+00:00",
    )
    assert second_key.duplicate is False
    assert second_key.merged_events == 0
    assert second_key_replay.duplicate is True
    assert tracer.admin_summary(
        start_at="2026-07-26T00:00:00+00:00",
        end_at="2026-07-27T00:00:00+00:00",
    ) == ()
    assert tracer.inspect_privacy("user:user-pg").projected_event_count == 0

    cleared = tracer.clear(
        "anonymous:anon-pg",
        idempotency_key="clear:anon-pg",
        acted_at="2026-07-26T15:55:00+00:00",
    )
    clear_replay = tracer.clear(
        "anonymous:anon-pg",
        idempotency_key="clear:anon-pg",
        acted_at="2026-07-26T15:55:00+00:00",
    )
    deleted = tracer.delete(
        "user:user-pg",
        idempotency_key="delete:user-pg",
        acted_at="2026-07-26T16:00:00+00:00",
    )
    delete_replay = tracer.delete(
        "user:user-pg",
        idempotency_key="delete:user-pg",
        acted_at="2026-07-26T16:00:00+00:00",
    )

    assert cleared.removed_raw_events == 1
    assert clear_replay.duplicate is True
    assert deleted.removed_identity_links == 1
    assert delete_replay.duplicate is True
    assert tracer.inspect_privacy("user:user-pg").raw_event_count == 0
    assert tracer.inspect_privacy("user:user-pg").identity_link_count == 0
    replay_after_delete = tracer.record(event)
    assert replay_after_delete.accepted is False
    assert replay_after_delete.reason == "deleted"
    with pytest.raises(ValueError, match="deleted analytics identity"):
        tracer.set_opt_out(
            "user:user-pg",
            idempotency_key="opt-out:user-pg",
            acted_at="2026-07-26T16:05:00+00:00",
        )
    assert tracer.inspect_privacy("user:user-pg").opted_out is False


def test_postgres_adapter_enforces_raw_retention(
    analytics_postgres_dsn: str,
) -> None:
    tracer = AnalyticsPrivacyTracer(
        PostgresAnalyticsStore(
            lambda: _worker_connection(analytics_postgres_dsn),
            tombstone_secret=TEST_TOMBSTONE_SECRET,
            digest_key_id=TEST_DIGEST_KEY_ID,
        )
    )
    tracer.record(
        AnalyticsEvent(
            idempotency_key="impression:retention:anon-pg",
            kind="content_impression",
            occurred_at="2026-06-01T00:00:00+00:00",
            anonymous_id="anon-retention-pg",
            user_id=None,
            properties={"content_id": "article-pg", "surface": "home"},
        )
    )

    assert (
        tracer.purge_expired(before="2026-06-30T23:59:59+00:00") == 0
    )
    assert tracer.purge_expired(before="2026-07-01T00:00:00+00:00") == 1
    assert (
        tracer.inspect_privacy(
            "anonymous:anon-retention-pg"
        ).raw_event_count
        == 0
    )
    replay = tracer.record(
        AnalyticsEvent(
            idempotency_key="impression:retention:anon-pg",
            kind="content_impression",
            occurred_at="2026-06-01T00:00:00+00:00",
            anonymous_id="anon-retention-pg",
            user_id=None,
            properties={"content_id": "article-pg", "surface": "home"},
        )
    )
    assert replay.accepted is False
    assert replay.reason == "expired"


def test_postgres_clear_prevents_delayed_event_replay(
    analytics_postgres_dsn: str,
) -> None:
    tracer = AnalyticsPrivacyTracer(
        PostgresAnalyticsStore(
            lambda: _worker_connection(analytics_postgres_dsn),
            tombstone_secret=TEST_TOMBSTONE_SECRET,
            digest_key_id=TEST_DIGEST_KEY_ID,
        )
    )
    event = AnalyticsEvent(
        idempotency_key="impression:clear-replay-pg",
        kind="content_impression",
        occurred_at="2026-07-26T15:40:00+00:00",
        anonymous_id="anon-clear-pg",
        user_id=None,
        properties={"content_id": "article-pg", "surface": "home"},
    )
    tracer.record(event)
    tracer.clear(
        "anonymous:anon-clear-pg",
        idempotency_key="clear:anon-clear-pg",
        acted_at="2026-07-26T15:45:00+00:00",
    )

    replay = tracer.record(event)
    assert replay.accepted is False
    assert replay.reason == "cleared"
    assert (
        tracer.inspect_privacy("anonymous:anon-clear-pg").raw_event_count
        == 0
    )


def test_postgres_privacy_action_key_is_bound_to_action_and_subject(
    analytics_postgres_dsn: str,
) -> None:
    tracer = AnalyticsPrivacyTracer(
        PostgresAnalyticsStore(
            lambda: _worker_connection(analytics_postgres_dsn),
            tombstone_secret=TEST_TOMBSTONE_SECRET,
            digest_key_id=TEST_DIGEST_KEY_ID,
        )
    )
    tracer.set_opt_out(
        "user:user-a",
        idempotency_key="privacy-action:shared-pg",
        acted_at="2026-07-26T16:00:00+00:00",
    )

    with pytest.raises(ValueError, match="idempotency_key was reused"):
        tracer.delete(
            "user:user-a",
            idempotency_key="privacy-action:shared-pg",
            acted_at="2026-07-26T16:01:00+00:00",
        )
    with pytest.raises(ValueError, match="idempotency_key was reused"):
        tracer.set_opt_out(
            "user:user-b",
            idempotency_key="privacy-action:shared-pg",
            acted_at="2026-07-26T16:01:00+00:00",
        )


def test_postgres_event_key_and_identity_are_fail_closed(
    analytics_postgres_dsn: str,
) -> None:
    tracer = AnalyticsPrivacyTracer(
        PostgresAnalyticsStore(
            lambda: _worker_connection(analytics_postgres_dsn),
            tombstone_secret=TEST_TOMBSTONE_SECRET,
            digest_key_id=TEST_DIGEST_KEY_ID,
        )
    )
    original = AnalyticsEvent(
        idempotency_key="impression:bound-pg",
        kind="content_impression",
        occurred_at="2026-07-26T15:40:00+00:00",
        anonymous_id="anon-bound-pg",
        user_id=None,
        properties={"content_id": "article-pg", "surface": "home"},
    )
    tracer.record(original)

    with pytest.raises(ValueError, match="idempotency_key was reused"):
        tracer.record(
            AnalyticsEvent(
                idempotency_key=original.idempotency_key,
                kind=original.kind,
                occurred_at=original.occurred_at,
                anonymous_id=original.anonymous_id,
                user_id=None,
                properties={
                    "content_id": "different-pg",
                    "surface": "home",
                },
            )
        )
    tracer.merge_identity(
        idempotency_key="merge:bound-pg",
        anonymous_id="anon-bound-pg",
        user_id="user-a-pg",
        merged_at="2026-07-26T15:45:00+00:00",
    )
    with pytest.raises(ValueError, match="conflicting analytics identities"):
        tracer.record(
            AnalyticsEvent(
                idempotency_key="impression:conflict-pg",
                kind="content_impression",
                occurred_at="2026-07-26T15:46:00+00:00",
                anonymous_id="anon-bound-pg",
                user_id="user-b-pg",
                properties={"content_id": "article-pg", "surface": "home"},
            )
        )


def test_postgres_late_merge_tombstones_alias_of_deleted_user(
    analytics_postgres_dsn: str,
) -> None:
    tracer = AnalyticsPrivacyTracer(
        PostgresAnalyticsStore(
            lambda: _worker_connection(analytics_postgres_dsn),
            tombstone_secret=TEST_TOMBSTONE_SECRET,
            digest_key_id=TEST_DIGEST_KEY_ID,
        )
    )
    tracer.delete(
        "user:user-deleted-pg",
        idempotency_key="delete:user-deleted-pg",
        acted_at="2026-07-26T15:40:00+00:00",
    )

    with pytest.raises(ValueError, match="deleted analytics identity"):
        tracer.merge_identity(
            idempotency_key="late-merge:anon-late-pg:user-deleted-pg",
            anonymous_id="anon-late-pg",
            user_id="user-deleted-pg",
            merged_at="2026-07-26T15:45:00+00:00",
        )
    replay = tracer.record(
        AnalyticsEvent(
            idempotency_key="late-event:anon-late-pg",
            kind="content_impression",
            occurred_at="2026-07-26T15:46:00+00:00",
            anonymous_id="anon-late-pg",
            user_id=None,
            properties={"content_id": "article-pg", "surface": "home"},
        )
    )
    assert replay.accepted is False
    assert replay.reason == "deleted"


def test_digest_key_drift_and_tombstone_deletion_fail_closed(
    analytics_postgres_dsn: str,
) -> None:
    tracer = AnalyticsPrivacyTracer(
        PostgresAnalyticsStore(
            lambda: _worker_connection(analytics_postgres_dsn),
            tombstone_secret=TEST_TOMBSTONE_SECRET,
            digest_key_id=TEST_DIGEST_KEY_ID,
        )
    )
    event = AnalyticsEvent(
        idempotency_key="delete:key-gate-pg",
        kind="content_impression",
        occurred_at="2026-07-26T15:40:00+00:00",
        anonymous_id="anon-key-gate-pg",
        user_id=None,
        properties={"content_id": "article-pg", "surface": "home"},
    )
    tracer.record(event)
    tracer.delete(
        "anonymous:anon-key-gate-pg",
        idempotency_key="delete-action:key-gate-pg",
        acted_at="2026-07-26T15:45:00+00:00",
    )

    with _worker_connection(analytics_postgres_dsn) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "DELETE FROM volpred_analytics.privacy_tombstones"
            )
    with _worker_connection(analytics_postgres_dsn) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                UPDATE volpred_analytics.privacy_tombstones
                SET subject_digest = %s
                """,
                (b"z" * 32,),
            )
    with _worker_connection(analytics_postgres_dsn) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                UPDATE volpred_analytics.event_dedupe_tombstones
                SET idempotency_digest = %s
                """,
                (b"z" * 32,),
            )

    wrong_key_tracer = AnalyticsPrivacyTracer(
        PostgresAnalyticsStore(
            lambda: _worker_connection(analytics_postgres_dsn),
            tombstone_secret=b"different-valid-secret-for-test-32",
            digest_key_id=TEST_DIGEST_KEY_ID,
        )
    )
    with pytest.raises(ValueError, match="digest key identity mismatch"):
        wrong_key_tracer.record(event)


def test_database_trigger_rejects_future_or_nested_raw_event(
    analytics_postgres_dsn: str,
) -> None:
    insert_sql = """
        INSERT INTO volpred_analytics.events (
          idempotency_key,
          kind,
          occurred_at,
          anonymous_id,
          submitted_user_id,
          user_id,
          properties,
          payload_digest,
          raw_expires_at
        ) VALUES (%s, %s, %s, %s, NULL, NULL, %s, %s, %s)
    """
    with _worker_connection(analytics_postgres_dsn) as connection:
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="too far in the future",
        ):
            connection.execute(
                insert_sql,
                (
                    "direct:future",
                    "content_impression",
                    "2027-07-26T15:40:00+00:00",
                    "anon-direct",
                    Jsonb({"content_id": "article-pg", "surface": "home"}),
                    b"x" * 32,
                    "2027-08-25T15:40:00+00:00",
                ),
            )
    with _worker_connection(analytics_postgres_dsn) as connection:
        connection.execute(
            insert_sql,
            (
                "direct:valid-before-update",
                "content_impression",
                "2026-07-26T15:40:00+00:00",
                "anon-direct-update",
                Jsonb({"content_id": "article-pg", "surface": "home"}),
                b"x" * 32,
                "2026-08-25T15:40:00+00:00",
            ),
        )
    with _worker_connection(analytics_postgres_dsn) as connection:
        with pytest.raises(
            psycopg.errors.InsufficientPrivilege,
        ):
            connection.execute(
                """
                UPDATE volpred_analytics.events
                SET properties = %s
                WHERE idempotency_key = 'direct:valid-before-update'
                """,
                (
                    Jsonb(
                        {
                            "content_id": {"portfolio_position": "long"},
                            "surface": "home",
                        }
                    ),
                ),
            )
    with psycopg.connect(analytics_postgres_dsn) as connection:
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="properties must be strings",
        ):
            connection.execute(
                """
                UPDATE volpred_analytics.events
                SET properties = %s
                WHERE idempotency_key = 'direct:valid-before-update'
                """,
                (
                    Jsonb(
                        {
                            "content_id": {"portfolio_position": "long"},
                            "surface": "home",
                        }
                    ),
                ),
            )
    with _worker_connection(analytics_postgres_dsn) as connection:
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="properties must be strings",
        ):
            connection.execute(
                insert_sql,
                (
                    "direct:nested",
                    "content_impression",
                    "2026-07-26T15:40:00+00:00",
                    "anon-direct",
                    Jsonb(
                        {
                            "content_id": {"portfolio_position": "long"},
                            "surface": "home",
                        }
                    ),
                    b"x" * 32,
                    "2026-08-25T15:40:00+00:00",
                ),
            )
