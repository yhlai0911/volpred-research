from __future__ import annotations

import hashlib
import json
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Jsonb

REPO_ROOT = Path(__file__).resolve().parents[1]
ANALYTICS_MIGRATIONS = tuple(
    REPO_ROOT / "supabase" / "migrations" / name
    for name in (
        "20260726154115_analytics_privacy_tracer.sql",
        "20260727094656_analytics_ingress_rpc.sql",
    )
)
GROWTH_MIGRATION = (
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260728223739_growth_experiment_registry.sql"
)
EXPERIMENT_ID = "article-share-cta-copy-v1"


def _iso(value: datetime) -> str:
    return value.isoformat()


def _spec(now: datetime | None = None) -> dict:
    preregistered_at = now or datetime.now(UTC)
    starts_at = preregistered_at + timedelta(seconds=1)
    ends_at = starts_at + timedelta(hours=2)
    return {
        "schema_version": "growth-experiment.v1",
        "experiment_id": EXPERIMENT_ID,
        "hypothesis": (
            "A clearer share CTA increases qualified article shares "
            "without reducing 75% read depth."
        ),
        "channel": "organic_first_party",
        "surface": "article_share_cta",
        "status": "preregistered",
        "preregistered_at": _iso(preregistered_at),
        "assignment_salt": "share-v1-0",
        "window": {
            "starts_at": _iso(starts_at),
            "ends_at": _iso(ends_at),
        },
        "primary_metric": {
            "name": "qualified_action_rate",
            "action": "share",
        },
        "guardrail": {
            "name": "read_depth_75_rate",
            "minimum_ratio_to_control": 0.95,
        },
        "attribution": {
            "event_kind": "qualified_action",
            "action": "share",
            "window_hours": 1,
            "delivery_grace_minutes": 1,
        },
        "decision_rule": {
            "method": "non_overlapping_wilson_95",
            "confidence_level": 0.95,
            "minimum_absolute_uplift": 0.01,
        },
        "stop_rule": {
            "minimum_exposures_per_variant": 200,
            "maximum_exposures_total": 400,
            "maximum_exposure_hours": 2,
            "maximum_lifecycle_hours": 4,
        },
        "policy": {
            "paid_ads": False,
            "dark_patterns": False,
            "research_fact_changes": False,
            "retain_null_result": True,
        },
        "variants": [
            {
                "variant_id": "control",
                "weight_bps": 5000,
                "reversible": True,
                "payload": {"share_label": "分享"},
            },
            {
                "variant_id": "treatment",
                "weight_bps": 5000,
                "reversible": True,
                "payload": {"share_label": "分享這篇研究"},
            },
        ],
    }


def _digest(value: object) -> bytes:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).digest()


def _postgres_bin_dir() -> Path | None:
    homebrew = Path("/opt/homebrew/opt/postgresql@17/bin")
    if (homebrew / "postgres").exists():
        return homebrew
    pg_config = shutil.which("pg_config")
    if pg_config is None:
        return None
    bindir = Path(
        subprocess.check_output((pg_config, "--bindir"), text=True).strip()
    )
    return bindir if (bindir / "postgres").exists() else None


@pytest.fixture(scope="module")
def growth_postgres_dsn(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[str]:
    assert GROWTH_MIGRATION.exists(), "growth registry migration is required"
    bin_dir = _postgres_bin_dir()
    if bin_dir is None:
        if __import__("os").environ.get("CI"):
            pytest.fail("PostgreSQL server binaries are required in CI")
        pytest.skip("PostgreSQL server binaries are required")
    root = tmp_path_factory.mktemp("growth-registry-postgres")
    data_dir = root / "data"
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    completed = subprocess.run(
        (
            str(bin_dir / "initdb"),
            "--auth=trust",
            "--encoding=UTF8",
            "--no-locale",
            "-D",
            str(data_dir),
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    completed = subprocess.run(
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
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    dsn = f"postgresql://127.0.0.1:{port}/postgres"
    try:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(
                "CREATE ROLE growth_migration_runner "
                "NOLOGIN CREATEROLE BYPASSRLS"
            )
            connection.execute(
                "GRANT CREATE ON DATABASE postgres TO growth_migration_runner"
            )
            connection.execute(
                "GRANT USAGE, CREATE ON SCHEMA public "
                "TO growth_migration_runner WITH GRANT OPTION"
            )
            connection.execute("CREATE ROLE anon NOLOGIN")
            connection.execute("CREATE ROLE authenticated NOLOGIN")
            connection.execute("CREATE ROLE service_role NOLOGIN")
            connection.execute("SET ROLE growth_migration_runner")
            for _ in range(2):
                for migration in ANALYTICS_MIGRATIONS:
                    connection.execute(migration.read_text(encoding="utf-8"))
            connection.execute(GROWTH_MIGRATION.read_text(encoding="utf-8"))
            connection.execute(GROWTH_MIGRATION.read_text(encoding="utf-8"))
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
def reset_growth_state(growth_postgres_dsn: str) -> None:
    with psycopg.connect(growth_postgres_dsn, autocommit=True) as connection:
        connection.execute(
            """
            TRUNCATE TABLE
              volpred_growth.audit_log,
              volpred_growth.command_receipts,
              volpred_growth.experiments,
              volpred_analytics.events
            RESTART IDENTITY
            """
        )


def _command(
    connection: psycopg.Connection,
    *,
    command_id: str,
    action: str,
    payload: dict,
    now: str,
) -> dict:
    return connection.execute(
        """
        SELECT public.command_volpred_growth_experiment(
          %s, %s, %s, %s, %s
        )
        """,
        (command_id, action, Jsonb(payload), _digest(payload), now),
    ).fetchone()[0]


def _preregister_and_activate(
    connection: psycopg.Connection,
) -> dict:
    spec = _spec()
    _command(
        connection,
        command_id="growth-preregister-1",
        action="preregister",
        payload=spec,
        now=spec["preregistered_at"],
    )
    wait_seconds = max(
        0.0,
        datetime.fromisoformat(
            spec["window"]["starts_at"]
        ).timestamp() - datetime.now(UTC).timestamp(),
    )
    time.sleep(wait_seconds + 0.05)
    _command(
        connection,
        command_id="growth-activate-1",
        action="activate",
        payload={"experiment_id": EXPERIMENT_ID},
        now=_iso(datetime.now(UTC)),
    )
    return spec


def _insert_events(
    connection: psycopg.Connection,
    *,
    variant: str,
    exposures: int,
    shares: int,
    depth_75: int,
    observed_at: str,
) -> None:
    for kind, count, extra in (
        ("content_impression", exposures, {}),
        ("qualified_action", shares, {"action": "share"}),
        ("read_depth", depth_75, {"depth_bucket": "75"}),
    ):
        connection.execute(
            """
            INSERT INTO volpred_analytics.events (
              idempotency_key, kind, occurred_at, anonymous_id,
              properties, payload_digest, raw_expires_at
            )
            SELECT
              %s || ':' || series.value,
              %s,
              %s::timestamptz,
              'growth-anon-' || %s || '-' || series.value,
              %s::jsonb || jsonb_build_object(
                'content_id', 'report:k1700',
                'surface', 'article',
                'experiment_id', %s::text,
                'variant_id', %s::text
              ),
              decode(repeat('ab', 32), 'hex'),
              %s::timestamptz
                + interval '30 days'
            FROM generate_series(1, %s) AS series(value)
            """,
            (
                f"{variant}:{kind}",
                kind,
                observed_at,
                variant,
                Jsonb(extra),
                EXPERIMENT_ID,
                variant,
                observed_at,
                count,
            ),
        )


def _record_growth_event(
    connection: psycopg.Connection,
    *,
    event_id: str,
    anonymous_id: str,
    subject_digest: bytes,
    variant: str,
    occurred_at: str,
    kind: str = "content_impression",
    extra_properties: dict | None = None,
) -> dict:
    return connection.execute(
        """
        SELECT public.record_volpred_growth_analytics_event(
          %s, %s, %s, %s, NULL,
          jsonb_build_object(
            'content_id', 'report:k1700',
            'surface', 'article',
            'experiment_id', %s::text,
            'variant_id', %s::text
          ) || %s::jsonb,
          %s, %s, 'growth-test-v1', %s, %s, NULL
        )
        """,
        (
            event_id,
            kind,
            occurred_at,
            anonymous_id,
            EXPERIMENT_ID,
            variant,
            Jsonb(extra_properties or {}),
            bytes.fromhex("ab" * 32),
            bytes.fromhex("cd" * 32),
            bytes.fromhex("ef" * 32),
            subject_digest,
        ),
    ).fetchone()[0]


def test_growth_migration_uses_bounded_managed_owner_transfer() -> None:
    source = GROWTH_MIGRATION.read_text(encoding="utf-8")
    assert "CURRENT_USER = 'postgres'" in source
    assert "WITH INHERIT FALSE" in source
    assert "WITH SET TRUE" in source
    assert "GRANTED BY CURRENT_USER" in source
    assert "SET LOCAL ROLE volpred_growth_worker" in source
    assert "RESET ROLE" in source


def test_preregistration_receipt_cannot_backdate_the_declared_time(
    growth_postgres_dsn: str,
) -> None:
    spec = _spec()
    mismatched = datetime.fromisoformat(
        spec["preregistered_at"]
    ) + timedelta(seconds=1)
    with (
        psycopg.connect(growth_postgres_dsn) as connection,
        pytest.raises(
            psycopg.errors.RaiseException,
            match="preregistration timestamp",
        ),
    ):
        connection.execute("SET ROLE service_role")
        _command(
            connection,
            command_id="growth-backdated-preregister",
            action="preregister",
            payload=spec,
            now=_iso(mismatched),
        )


def test_lifecycle_rejects_time_travel_beyond_clock_skew(
    growth_postgres_dsn: str,
) -> None:
    backdated = datetime.now(UTC) - timedelta(minutes=2)
    spec = _spec(backdated)
    with (
        psycopg.connect(growth_postgres_dsn) as connection,
        pytest.raises(
            psycopg.errors.RaiseException,
            match="growth command is invalid",
        ),
    ):
        connection.execute("SET ROLE service_role")
        _command(
            connection,
            command_id="growth-time-travel-preregister",
            action="preregister",
            payload=spec,
            now=spec["preregistered_at"],
        )


def test_preregistration_rejects_a_lifecycle_shorter_than_attribution(
    growth_postgres_dsn: str,
) -> None:
    spec = _spec()
    spec["stop_rule"]["maximum_lifecycle_hours"] = 3
    with (
        psycopg.connect(growth_postgres_dsn) as connection,
        pytest.raises(
            psycopg.errors.RaiseException,
            match="window or stop rule",
        ),
    ):
        connection.execute("SET ROLE service_role")
        _command(
            connection,
            command_id="growth-short-lifecycle",
            action="preregister",
            payload=spec,
            now=spec["preregistered_at"],
        )


def test_registry_is_receipt_backed_private_and_assignment_is_stable(
    growth_postgres_dsn: str,
) -> None:
    spec = _spec()
    with psycopg.connect(growth_postgres_dsn) as connection:
        connection.execute("SET ROLE service_role")
        first = _command(
            connection,
            command_id="growth-preregister-1",
            action="preregister",
            payload=spec,
            now=spec["preregistered_at"],
        )
        replay = _command(
            connection,
            command_id="growth-preregister-1",
            action="preregister",
            payload=spec,
            now=_iso(
                datetime.fromisoformat(spec["preregistered_at"])
                - timedelta(minutes=5)
            ),
        )
        receipt_readback = connection.execute(
            "SELECT public.read_volpred_growth_command_receipt(%s)",
            ("growth-preregister-1",),
        ).fetchone()[0]
        wait_seconds = max(
            0.0,
            datetime.fromisoformat(
                spec["window"]["starts_at"]
            ).timestamp() - datetime.now(UTC).timestamp(),
        )
        time.sleep(wait_seconds + 0.05)
        assignment_time = _iso(datetime.now(UTC))
        _command(
            connection,
            command_id="growth-activate-1",
            action="activate",
            payload={"experiment_id": EXPERIMENT_ID},
            now=assignment_time,
        )
        alpha = connection.execute(
            "SELECT public.resolve_volpred_growth_assignment(%s, %s, %s)",
            (
                EXPERIMENT_ID,
                hashlib.sha256(b"subject:alpha").hexdigest(),
                    assignment_time,
            ),
        ).fetchone()[0]
        beta = connection.execute(
            "SELECT public.resolve_volpred_growth_assignment(%s, %s, %s)",
            (
                EXPERIMENT_ID,
                hashlib.sha256(b"subject:beta").hexdigest(),
                    assignment_time,
            ),
        ).fetchone()[0]
        before_window = connection.execute(
            "SELECT public.resolve_volpred_growth_assignment(%s, %s, %s)",
            (
                EXPERIMENT_ID,
                hashlib.sha256(b"subject:alpha").hexdigest(),
                    _iso(
                        datetime.fromisoformat(
                            spec["window"]["starts_at"]
                        ) - timedelta(milliseconds=1)
                    ),
            ),
        ).fetchone()[0]
        alpha_digest = hashlib.sha256(b"subject:alpha").digest()
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="assignment mismatch",
        ), connection.transaction():
            _record_growth_event(
                connection,
                event_id="forged-growth-attribution",
                anonymous_id="forged-anon",
                subject_digest=alpha_digest,
                variant="control",
                occurred_at=assignment_time,
            )
        accepted = _record_growth_event(
            connection,
            event_id="verified-growth-attribution",
            anonymous_id="verified-anon",
            subject_digest=alpha_digest,
            variant="treatment",
            occurred_at=assignment_time,
        )
        connection.execute("RESET ROLE")

        privileges = {
            role: connection.execute(
                """
                SELECT has_function_privilege(
                  %s,
                  'public.command_volpred_growth_experiment(text,text,jsonb,bytea,timestamp with time zone)',
                  'EXECUTE'
                )
                """,
                (role,),
            ).fetchone()[0]
            for role in ("public", "anon", "authenticated", "service_role")
        }
        tables = tuple(
            row[0]
            for row in connection.execute(
                """
                SELECT tablename
                FROM pg_catalog.pg_tables
                WHERE schemaname = 'volpred_growth'
                ORDER BY tablename
                """
            )
        )
        private_access = connection.execute(
            """
            SELECT bool_or(
              has_table_privilege('service_role', schemaname || '.' || tablename, 'SELECT')
            )
            FROM pg_catalog.pg_tables
            WHERE schemaname = 'volpred_growth'
            """
        ).fetchone()[0]
        receipt_privileges = {
            role: connection.execute(
                """
                SELECT has_function_privilege(
                  %s,
                  'public.read_volpred_growth_command_receipt(text)',
                  'EXECUTE'
                )
                """,
                (role,),
            ).fetchone()[0]
            for role in ("public", "anon", "authenticated", "service_role")
        }

    assert first["duplicate"] is False
    assert replay["duplicate"] is True
    assert receipt_readback["request_payload"] == spec
    assert receipt_readback["receipt"] == first
    assert alpha["variant_id"] == "treatment"
    assert beta["variant_id"] == "control"
    assert before_window is None
    assert accepted["accepted"] is True
    assert privileges == {
        "public": False,
        "anon": False,
        "authenticated": False,
        "service_role": True,
    }
    assert tables == ("audit_log", "command_receipts", "experiments")
    assert private_access is False
    assert receipt_privileges == privileges


def test_close_preserves_an_honest_null_after_raw_events_are_removed(
    growth_postgres_dsn: str,
) -> None:
    with psycopg.connect(growth_postgres_dsn) as connection:
        connection.execute("SET ROLE service_role")
        _preregister_and_activate(connection)
        cohort_observed_at = _iso(datetime.now(UTC))
        cohort_digest = hashlib.sha256(b"subject:alpha").digest()
        cohort_assignment = connection.execute(
            "SELECT public.resolve_volpred_growth_assignment(%s, %s, %s)",
            (
                EXPERIMENT_ID,
                cohort_digest.hex(),
                cohort_observed_at,
            ),
        ).fetchone()[0]
        assert cohort_assignment["variant_id"] == "treatment"
        _record_growth_event(
            connection,
            event_id="verified-growth-cohort",
            anonymous_id="verified-growth-cohort",
            subject_digest=cohort_digest,
            variant="treatment",
            occurred_at=cohort_observed_at,
        )
        connection.execute("RESET ROLE")
        observed_at = _iso(datetime.now(UTC))
        _insert_events(
            connection,
            variant="control",
            exposures=200,
            shares=10,
            depth_75=180,
            observed_at=observed_at,
        )
        _insert_events(
            connection,
            variant="treatment",
            exposures=199,
            shares=14,
            depth_75=180,
            observed_at=observed_at,
        )
        connection.execute(
            """
            INSERT INTO volpred_analytics.events (
              idempotency_key, kind, occurred_at, anonymous_id,
              properties, payload_digest, raw_expires_at
            )
            SELECT
              'control:second-content:' || event.kind,
              event.kind,
              %s::timestamptz,
              'growth-anon-control-1',
              event.extra || jsonb_build_object(
                'content_id', 'report:k1701',
                'surface', 'article',
                'experiment_id', %s::text,
                'variant_id', 'control'
              ),
              decode(repeat('ab', 32), 'hex'),
              %s::timestamptz + interval '30 days'
            FROM (
              VALUES
                ('content_impression', '{}'::jsonb),
                ('qualified_action', '{"action":"share"}'::jsonb),
                ('read_depth', '{"depth_bucket":"75"}'::jsonb)
            ) AS event(kind, extra)
            """,
            (observed_at, EXPERIMENT_ID, observed_at),
        )
        connection.execute(
            """
            INSERT INTO volpred_analytics.events (
              idempotency_key, kind, occurred_at, anonymous_id,
              properties, payload_digest, raw_expires_at
            ) VALUES
              (
                'control:share:duplicate',
                'qualified_action',
                %s,
                'growth-anon-control-1',
                jsonb_build_object(
                  'content_id', 'report:k1700',
                  'surface', 'article',
                  'action', 'share',
                  'experiment_id', %s::text,
                  'variant_id', 'control'
                ),
                decode(repeat('ab', 32), 'hex'),
                %s::timestamptz + interval '30 days'
              ),
              (
                'control:share:orphan',
                'qualified_action',
                %s,
                'growth-anon-control-orphan',
                jsonb_build_object(
                  'content_id', 'report:k1700',
                  'surface', 'article',
                  'action', 'share',
                  'experiment_id', %s::text,
                  'variant_id', 'control'
                ),
                decode(repeat('ab', 32), 'hex'),
                %s::timestamptz + interval '30 days'
              )
            """,
            (
                observed_at,
                EXPERIMENT_ID,
                observed_at,
                observed_at,
                EXPERIMENT_ID,
                observed_at,
            ),
        )
        late_at = _iso(
            datetime.fromisoformat(observed_at)
            + timedelta(minutes=90)
        )
        connection.execute("SET session_replication_role = replica")
        connection.execute(
            """
            INSERT INTO volpred_analytics.events (
              idempotency_key, kind, occurred_at, anonymous_id,
              properties, payload_digest, raw_expires_at
            ) VALUES (
              'control:share:late',
              'qualified_action',
              %s,
              'growth-anon-control-50',
              jsonb_build_object(
                'content_id', 'report:k1700',
                'surface', 'article',
                'action', 'share',
                'experiment_id', %s::text,
                'variant_id', 'control'
              ),
              decode(repeat('ab', 32), 'hex'),
              %s::timestamptz + interval '30 days'
            )
            """,
            (late_at, EXPERIMENT_ID, late_at),
        )
        connection.execute("SET session_replication_role = origin")
        connection.execute("SET ROLE service_role")
        stopped = _command(
            connection,
            command_id="growth-stop-1",
            action="stop",
            payload={
                "experiment_id": EXPERIMENT_ID,
                "reason": "stop_rule_reached",
            },
            now=_iso(datetime.now(UTC)),
        )
        attributed_after_stop = _record_growth_event(
            connection,
            event_id="verified-growth-cohort-share",
            anonymous_id="verified-growth-cohort",
            subject_digest=cohort_digest,
            variant="treatment",
            occurred_at=_iso(datetime.now(UTC)),
            kind="qualified_action",
            extra_properties={"action": "share"},
        )
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="cohort has not matured",
        ), connection.transaction():
            _command(
                connection,
                command_id="growth-close-too-early",
                action="close",
                payload={
                    "experiment_id": EXPERIMENT_ID,
                    "reason": "stop_rule_reached",
                },
                now=_iso(datetime.now(UTC)),
            )
        connection.execute("RESET ROLE")
        connection.execute(
            """
            UPDATE volpred_growth.experiments
            SET observation_ends_at = clock_timestamp() - interval '1 second'
            WHERE experiment_id = %s
            """,
            (EXPERIMENT_ID,),
        )
        connection.execute("SET ROLE service_role")
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="cohort has not matured",
        ), connection.transaction():
            _command(
                connection,
                command_id="growth-close-wrong-reason",
                action="close",
                payload={
                    "experiment_id": EXPERIMENT_ID,
                    "reason": "window_ended",
                },
                now=_iso(datetime.now(UTC)),
            )
        closed = _command(
            connection,
            command_id="growth-close-1",
            action="close",
            payload={
                "experiment_id": EXPERIMENT_ID,
                "reason": "stop_rule_reached",
            },
            now=_iso(datetime.now(UTC)),
        )
        readback = connection.execute(
            "SELECT public.read_volpred_growth_experiment(%s)",
            (EXPERIMENT_ID,),
        ).fetchone()[0]
        connection.execute("RESET ROLE")
        receipt_request = connection.execute(
            """
            SELECT request_payload
            FROM volpred_growth.command_receipts
            WHERE command_id = 'growth-close-1'
            """
        ).fetchone()[0]
        audit_request = connection.execute(
            """
            SELECT request_payload
            FROM volpred_growth.audit_log
            WHERE command_id = 'growth-close-1'
            """
        ).fetchone()[0]
        connection.execute(
            """
            DELETE FROM volpred_analytics.events
            WHERE properties ->> 'experiment_id' = %s
            """,
            (EXPERIMENT_ID,),
        )
        connection.execute("SET ROLE service_role")
        after_delete = connection.execute(
            "SELECT public.read_volpred_growth_experiment(%s)",
            (EXPERIMENT_ID,),
        ).fetchone()[0]

    result = closed["result"]
    assert stopped["status"] == "observing"
    assert stopped["stop_reason"] == "stop_rule_reached"
    assert attributed_after_stop["accepted"] is True
    assert closed["closure_reason"] == "stop_rule_reached"
    assert result["outcome"] == "null"
    assert result["closure_reason"] == "stop_rule_reached"
    assert result["null_result_retained"] is True
    assert result["measurement"]["control"] == {
        "exposures": 200,
        "qualified_actions": 10,
        "read_depth_75": 180,
        "qualified_action_rate": 0.05,
        "read_depth_75_rate": 0.9,
    }
    assert result["measurement"]["treatment"] == {
        "exposures": 200,
        "qualified_actions": 15,
        "read_depth_75": 180,
        "qualified_action_rate": 0.075,
        "read_depth_75_rate": 0.9,
    }
    assert readback["status"] == "closed"
    assert readback["closure_reason"] == "stop_rule_reached"
    assert receipt_request["reason"] == "stop_rule_reached"
    assert audit_request["reason"] == "stop_rule_reached"
    assert after_delete["result"] == readback["result"]
