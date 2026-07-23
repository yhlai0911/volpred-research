from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from ipaddress import ip_address
import os
from pathlib import Path
import shutil
import socket
import subprocess

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from volpred.ops.delivery import (
    AcknowledgementExpectation,
    EffectRequest,
    EffectRequestConflict,
)
from volpred.ops.delivery.postgres import PostgresEffectDelivery
from volpred.ops.work import WorkCoordinator, WorkRequest
from volpred.ops.work.postgres import PostgresCoordinationStore


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = (
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260723062144_operations_core_work_coordinator.sql",
    REPO_ROOT
    / "supabase"
    / "migrations"
    / "20260724020500_operations_core_effect_outbox.sql",
)


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
              volpred_ops.effect_outbox,
              volpred_ops.effect_requests,
              volpred_ops.work_receipts,
              volpred_ops.work_checkpoints,
              volpred_ops.work_events,
              volpred_ops.work_items
            RESTART IDENTITY
            """
        )


def _worker_connection(dsn: str) -> psycopg.Connection:
    connection = psycopg.connect(dsn)
    connection.execute("SET ROLE volpred_ops_worker")
    return connection


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
                ),
                zip(deliveries, ("worker-a", "worker-b"), strict=True),
            )
        )

    acquired = [claim for claim in claims if claim is not None]
    assert len(acquired) == 1
    assert acquired[0].attempt_count == 1
    assert {claim.token for claim in acquired} <= {"claim-a", "claim-b"}


def test_expired_outbox_claim_is_recovered_with_database_clock(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    _delivery(postgres_effect_dsn).request(_request())
    first = _delivery(
        postgres_effect_dsn,
        token="stale-token",
    ).claim_outbox(worker_id="worker-a", lease_seconds=300)
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
    ).claim_outbox(worker_id="worker-b", lease_seconds=300)
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
    claim = delivery.claim_outbox(worker_id="effect-worker", lease_seconds=300)
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
