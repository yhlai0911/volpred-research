from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import shutil
import socket
import subprocess

import psycopg
import pytest

from volpred.analytics import AnalyticsEvent, AnalyticsPrivacyTracer
from volpred.analytics.postgres import PostgresAnalyticsStore


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = next(
    (REPO_ROOT / "supabase" / "migrations").glob(
        "*_analytics_privacy_tracer.sql"
    )
)


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
            connection.execute(MIGRATION.read_text(encoding="utf-8"))
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
              volpred_analytics.privacy_preferences,
              volpred_analytics.identity_links,
              volpred_analytics.events
            RESTART IDENTITY
            """
        )


def test_migration_keeps_analytics_private_and_enables_rls(
    analytics_postgres_dsn: str,
) -> None:
    with psycopg.connect(analytics_postgres_dsn) as connection:
        rows = connection.execute(
            """
            SELECT c.relname, c.relrowsecurity,
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

    assert rows
    assert all(row[1] is True for row in rows)
    assert all(row[2] is False for row in rows)
    assert public_has_schema_usage is False


def test_postgres_adapter_replays_merge_and_privacy_lifecycle(
    analytics_postgres_dsn: str,
) -> None:
    tracer = AnalyticsPrivacyTracer(
        PostgresAnalyticsStore(
            lambda: psycopg.connect(analytics_postgres_dsn)
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


def test_postgres_adapter_enforces_raw_retention(
    analytics_postgres_dsn: str,
) -> None:
    tracer = AnalyticsPrivacyTracer(
        PostgresAnalyticsStore(
            lambda: psycopg.connect(analytics_postgres_dsn)
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
