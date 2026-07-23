import os
import shutil
import socket
import subprocess
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from volpred.ops.delivery import (
    AcknowledgedEffect,
    AcknowledgementExpectation,
    EffectRequest,
    EffectRequestConflict,
    FailedEffect,
)
from volpred.ops.delivery.postgres import (
    EffectOutboxLease,
    EffectSettlementAuthority,
    PostgresEffectDelivery,
)
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


def _verify_non_superuser_migration_executor(dsn: str) -> None:
    """Exercise the production PG17 CREATEROLE ownership/privilege path."""

    manager = "volpred_ops_migration_test_manager"
    with psycopg.connect(dsn, autocommit=True) as connection:
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
    try:
        with psycopg.connect(
            dsn,
            user=manager,
            autocommit=True,
        ) as connection:
            for migration in MIGRATIONS:
                connection.execute(migration.read_text(encoding="utf-8"))

        with psycopg.connect(dsn, autocommit=True) as connection:
            (
                worker_execute,
                public_execute,
                worker_settle,
                public_settle,
                definer_create,
                receipt_outbox_index,
                unsafe_memberships,
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
        assert unsafe_memberships == 0
    finally:
        with psycopg.connect(dsn, autocommit=True) as connection:
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
              volpred_ops.effect_attempt_receipts,
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


def _authority(**overrides: object) -> EffectSettlementAuthority:
    authority = EffectSettlementAuthority(
        request_sha256="d" * 64,
        outbox_claim_ref="effect-outbox:effect-postgres-1:attempt",
        primary_authority_ref="primary-authority:epoch-42",
    )
    return replace(authority, **overrides)


def _settle(
    delivery: PostgresEffectDelivery,
    *,
    lease: EffectOutboxLease,
    outcome: AcknowledgedEffect | FailedEffect,
    authority: EffectSettlementAuthority | None = None,
):
    return delivery.settle_outbox(
        lease=lease,
        outcome=outcome,
        authority=authority or _authority(),
    )


def test_acknowledged_attempt_atomically_delivers_and_replays_receipt(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    delivery = _delivery(postgres_effect_dsn)
    effect = delivery.request(_request())
    lease = delivery.claim_outbox(worker_id="effect-worker", lease_seconds=300)
    assert lease is not None

    receipt = _settle(
        delivery,
        lease=lease,
        outcome=_acknowledged(),
    )
    replay_delivery = _delivery(
        postgres_effect_dsn,
        token="unused-replay-token",
    )
    replay = _settle(
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
    assert receipt.authority_request_sha256 == "d" * 64
    assert receipt.outbox_claim_ref == (
        "effect-outbox:effect-postgres-1:attempt"
    )
    assert receipt.primary_authority_ref == "primary-authority:epoch-42"
    assert receipt.retry_at is None
    assert delivery.inspect(effect.id).status == "delivered"
    assert delivery.claim_outbox(
        worker_id="other-worker",
        lease_seconds=300,
    ) is None
    assert outbox == ("delivered", None, None, None)
    assert receipt_count == 1


def test_concurrent_equivalent_settlement_returns_one_immutable_receipt(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    delivery = _delivery(postgres_effect_dsn)
    delivery.request(_request())
    lease = delivery.claim_outbox(worker_id="effect-worker", lease_seconds=300)
    assert lease is not None

    deliveries = (
        _delivery(postgres_effect_dsn, token="unused-a"),
        _delivery(postgres_effect_dsn, token="unused-b"),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = tuple(
            executor.map(
                lambda item: _settle(
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
    lease = delivery.claim_outbox(worker_id="effect-worker", lease_seconds=300)
    assert lease is not None

    with pytest.raises(ValueError, match="acknowledgement mismatch"):
        _settle(
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
    )
    assert first_lease is not None

    first_receipt = _settle(
        delivery,
        lease=first_lease,
        outcome=_failed(),
    )
    assert first_receipt.disposition == "retry_scheduled"
    assert first_receipt.retry_at is not None
    assert delivery.claim_outbox(
        worker_id="too-early",
        lease_seconds=300,
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
    )
    assert second_lease is not None
    assert second_lease.attempt_count == 2

    replay = _settle(
        delivery,
        lease=first_lease,
        outcome=_failed(),
    )
    assert replay == first_receipt
    with pytest.raises(ValueError, match="original outcome"):
        _settle(
            delivery,
            lease=first_lease,
            outcome=_failed(),
            authority=_authority(primary_authority_ref="primary-authority:wrong"),
        )
    with pytest.raises(ValueError, match="original outcome"):
        _settle(
            delivery,
            lease=first_lease,
            outcome=_failed(evidence_sha256="d" * 64),
        )

    stale_second = replace(second_lease, token=first_lease.token)
    with pytest.raises(ValueError, match="token mismatch"):
        _settle(
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
    lease = delivery.claim_outbox(worker_id="effect-worker", lease_seconds=300)
    assert lease is not None
    with psycopg.connect(postgres_effect_dsn, autocommit=True) as connection:
        connection.execute(
            """
            UPDATE volpred_ops.effect_outbox
            SET claim_expires_at = clock_timestamp() - interval '1 second'
            """
        )

    with pytest.raises(ValueError, match="lease expired"):
        _settle(delivery, lease=lease, outcome=_acknowledged())

    recovered = _delivery(
        postgres_effect_dsn,
        token="recovered-token",
    ).claim_outbox(worker_id="recovery-worker", lease_seconds=300)
    assert recovered is not None
    assert recovered.attempt_count == 2


def test_terminal_failure_dead_letters_without_another_claim(
    postgres_effect_dsn: str,
) -> None:
    _seed_work(postgres_effect_dsn)
    delivery = _delivery(postgres_effect_dsn)
    effect = delivery.request(_request())
    lease = delivery.claim_outbox(worker_id="effect-worker", lease_seconds=300)
    assert lease is not None

    receipt = _settle(
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
        )
        assert lease is not None
        assert lease.attempt_count == attempt
        final_receipt = _settle(
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
    lease = delivery.claim_outbox(worker_id="effect-worker", lease_seconds=300)
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
    lease = delivery.claim_outbox(worker_id="effect-worker", lease_seconds=300)
    assert lease is not None
    _settle(delivery, lease=lease, outcome=_acknowledged())

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
