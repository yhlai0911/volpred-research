from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
import os
from pathlib import Path
import shutil
import socket
import subprocess
from threading import Barrier

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from volpred.ops.work import (
    ApprovalGranted,
    Checkpointed,
    ClaimLost,
    Completed,
    Released,
    Started,
    WorkCoordinator,
    WorkQuery,
    WorkRequest,
    WorkerOffer,
)
from volpred.ops.work.postgres import PostgresCoordinationStore
from volpred.ops.work.ownership import WorkOwnershipLost
from volpred.ops.work.postgres_ownership import PostgresWorkOwnerStore


FIXED_NOW = datetime(2026, 7, 23, 6, 30, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = next(
    (REPO_ROOT / "supabase" / "migrations").glob(
        "*_operations_core_work_coordinator.sql"
    )
)
OWNERSHIP_MIGRATION = next(
    (REPO_ROOT / "supabase" / "migrations").glob(
        "*_operations_core_work_ownership.sql"
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
        or params.get("dbname") != "volpred_ops_test"
        or os.environ.get("VOLPRED_ALLOW_DESTRUCTIVE_POSTGRES_TEST") != "1"
    ):
        raise RuntimeError(
            "external Postgres tests require localhost, database "
            "'volpred_ops_test', and "
            "VOLPRED_ALLOW_DESTRUCTIVE_POSTGRES_TEST=1"
        )


@pytest.fixture(scope="session")
def postgres_dsn(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    external_dsn = os.environ.get("VOLPRED_POSTGRES_TEST_DSN")
    if external_dsn:
        _validate_external_test_dsn(external_dsn)
        with psycopg.connect(external_dsn, autocommit=True) as connection:
            connection.execute(
                "DROP SCHEMA IF EXISTS volpred_ops CASCADE"
            )
            connection.execute(MIGRATION.read_text(encoding="utf-8"))
            connection.execute(
                OWNERSHIP_MIGRATION.read_text(encoding="utf-8")
            )
        yield external_dsn
        return
    bin_dir = _postgres_bin_dir()
    if bin_dir is None:
        if os.environ.get("CI"):
            pytest.fail(
                "PostgreSQL server binaries or VOLPRED_POSTGRES_TEST_DSN "
                "are required in CI"
            )
        pytest.skip("PostgreSQL server binaries are required for adapter contracts")
    root = tmp_path_factory.mktemp("work-coordinator-postgres")
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
            connection.execute(
                OWNERSHIP_MIGRATION.read_text(encoding="utf-8")
            )
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
def reset_postgres_contract_state(postgres_dsn: str) -> None:
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute(
            """
            TRUNCATE TABLE
              volpred_ops.work_owner_receipts,
              volpred_ops.work_receipts,
              volpred_ops.work_checkpoints,
              volpred_ops.work_events,
              volpred_ops.work_items
            RESTART IDENTITY
            """
        )
        connection.execute(
            """
            UPDATE volpred_ops.work_owners
            SET owner = 'legacy',
                generation = 1,
                cutover_manifest_sha256 = NULL,
                changed_at = clock_timestamp(),
                changed_by = 'pytest:reset',
                change_reason = 'reset owner fixture'
            WHERE capability = 'work.coordinate'
            """
        )
        connection.execute(
            """
            INSERT INTO volpred_ops.work_owner_receipts (
              capability, generation, previous_owner, owner,
              actor_ref, reason, cutover_manifest_sha256,
              rollback_of_generation, changed_at
            )
            SELECT
              capability, generation, NULL, owner,
              changed_by, change_reason, cutover_manifest_sha256,
              NULL, changed_at
            FROM volpred_ops.work_owners
            WHERE capability = 'work.coordinate'
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


def _expire_claim(postgres_dsn: str, work_id: str) -> None:
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute(
            """
            UPDATE volpred_ops.work_items
            SET claim_expires_at = clock_timestamp() - interval '1 second'
            WHERE id = %s
            """,
            (work_id,),
        )


def test_postgres_submit_is_idempotent_and_inspectable(postgres_dsn: str) -> None:
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work_postgres_0001",
    )
    request = WorkRequest(
        idempotency_key="owner:postgres:submit",
        source="user",
        kind="platform_ops",
        title="Postgres 保存 durable work identity",
        priority=1,
        required_capabilities=frozenset({"code"}),
        required_attestations=frozenset(),
        risk="safe",
        approval="auto",
        payload_ref="owner:postgres:submit",
        requester_ref="owner:user",
    )

    first = coordinator.submit(request)
    replay = coordinator.submit(request)
    snapshot = coordinator.inspect(WorkQuery(work_id=first.id))

    assert replay == first
    assert first.requester_ref == "owner:user"
    assert first.updated_at == first.created_at
    assert first.blocked_reason is None
    assert snapshot.items == (first,)
    assert tuple(event.kind for event in snapshot.events) == ("submitted",)


def test_external_postgres_dsn_requires_local_dedicated_database_and_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VOLPRED_ALLOW_DESTRUCTIVE_POSTGRES_TEST", raising=False)
    with pytest.raises(RuntimeError, match="external Postgres tests require"):
        _validate_external_test_dsn(
            "postgresql://postgres@example.supabase.co/postgres"
        )
    monkeypatch.setenv("VOLPRED_ALLOW_DESTRUCTIVE_POSTGRES_TEST", "1")
    with pytest.raises(RuntimeError, match="external Postgres tests require"):
        _validate_external_test_dsn(
            "postgresql://postgres@127.0.0.1/postgres"
        )
    with pytest.raises(RuntimeError, match="external Postgres tests require"):
        _validate_external_test_dsn(
            "host=localhost hostaddr=203.0.113.7 "
            "dbname=volpred_ops_test user=postgres"
        )
    _validate_external_test_dsn(
        "postgresql://postgres@127.0.0.1/volpred_ops_test"
    )


def test_work_owner_cutover_fences_legacy_mutations_atomically(
    postgres_dsn: str,
) -> None:
    connection_factory = lambda: psycopg.connect(postgres_dsn)
    owner_store = PostgresWorkOwnerStore(connection_factory)

    initial = owner_store.read_owner()
    cutover = owner_store.transfer_owner(
        expected_owner="legacy",
        expected_generation=1,
        target_owner="operations_core",
        actor_ref="operator:pytest",
        reason="exercise owner fencing",
        cutover_manifest_sha256="a" * 64,
    )

    assert (initial.owner, initial.generation) == ("legacy", 1)
    assert (
        cutover.owner,
        cutover.generation,
        cutover.cutover_manifest_sha256,
    ) == ("operations_core", 2, "a" * 64)

    request = WorkRequest(
        idempotency_key="owner:postgres:cutover-fence",
        source="user",
        kind="platform_ops",
        title="only current owner may submit",
        priority=1,
        required_capabilities=frozenset({"code"}),
        required_attestations=frozenset(),
        risk="safe",
        approval="auto",
        payload_ref="owner:postgres:cutover-fence",
        requester_ref="owner:user",
    )
    legacy = WorkCoordinator(
        PostgresCoordinationStore(
            lambda: _worker_connection(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "legacy-must-not-write",
    )
    with pytest.raises(
        WorkOwnershipLost,
        match="legacy mutation lost",
    ):
        legacy.submit(request)

    operations_core = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory,
            owner_generation=cutover.generation,
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work-owned-generation-2",
    )
    submitted = operations_core.submit(request)

    assert submitted.id == "work-owned-generation-2"
    assert owner_store.read_owner() == cutover


def test_operations_core_generation_owns_full_lifecycle_and_rollback(
    postgres_dsn: str,
) -> None:
    connection_factory = lambda: psycopg.connect(postgres_dsn)
    owner_store = PostgresWorkOwnerStore(connection_factory)
    manifest_sha256 = "b" * 64
    cutover = owner_store.transfer_owner(
        expected_owner="legacy",
        expected_generation=1,
        target_owner="operations_core",
        actor_ref="operator:pytest",
        reason="exercise full owned lifecycle",
        cutover_manifest_sha256=manifest_sha256,
    )
    tokens = iter(("owned-claim-1", "owned-claim-2"))
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory,
            owner_generation=cutover.generation,
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work-owned-lifecycle",
        token_factory=lambda: next(tokens),
        checkpoint_id_factory=lambda: "owned-checkpoint",
    )
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:postgres:owned-lifecycle",
            source="user",
            kind="platform_ops",
            title="generation owns every mutation",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:owned-lifecycle",
            requester_ref="owner:user",
        )
    )
    offer = WorkerOffer(
        worker_id="owned-worker",
        capabilities=frozenset({"code"}),
        attestations=frozenset(),
        lease_seconds=300,
    )
    first_lease = coordinator.acquire(offer)
    assert first_lease is not None
    running = coordinator.record(
        Started(
            work_id=work.id,
            lease_token=first_lease.token,
            expected_version=first_lease.work_item.version,
        )
    )
    checkpointed = coordinator.record(
        Checkpointed(
            report_id="owned-checkpoint-report",
            work_id=work.id,
            lease_token=first_lease.token,
            expected_version=running.version,
            artifact_ref="artifact:owned",
            artifact_sha256="c" * 64,
            verification_ref="pytest:owned",
        )
    )
    released = coordinator.record(
        Released(
            work_id=work.id,
            lease_token=first_lease.token,
            expected_version=checkpointed.version,
            reason="exercise owner-fenced resume",
        )
    )
    assert released.status == "pending"
    second_lease = coordinator.acquire(offer)
    assert second_lease is not None
    resumed = coordinator.record(
        Started(
            work_id=work.id,
            lease_token=second_lease.token,
            expected_version=second_lease.work_item.version,
        )
    )
    completed = coordinator.record(
        Completed(
            report_id="owned-completion",
            work_id=work.id,
            lease_token=second_lease.token,
            expected_version=resumed.version,
            result_ref="receipt:owned",
            summary="owner-fenced lifecycle complete",
        )
    )
    assert completed.status == "succeeded"

    rollback = owner_store.transfer_owner(
        expected_owner="operations_core",
        expected_generation=cutover.generation,
        target_owner="legacy",
        actor_ref="operator:pytest",
        reason="exercise exact rollback",
        cutover_manifest_sha256=manifest_sha256,
        rollback_of_generation=cutover.generation,
    )
    assert (rollback.owner, rollback.generation) == ("legacy", 3)

    with pytest.raises(
        WorkOwnershipLost,
        match="operations_core mutation lost",
    ):
        coordinator.submit(
            WorkRequest(
                idempotency_key="owner:postgres:stale-generation",
                source="user",
                kind="platform_ops",
                title="stale generation cannot write",
                priority=1,
                required_capabilities=frozenset(),
                required_attestations=frozenset(),
                risk="safe",
                approval="auto",
                payload_ref="owner:postgres:stale-generation",
                requester_ref="owner:user",
            )
        )

    legacy = WorkCoordinator(
        PostgresCoordinationStore(
            lambda: _worker_connection(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work-legacy-after-rollback",
    )
    restored = legacy.submit(
        WorkRequest(
            idempotency_key="owner:postgres:legacy-after-rollback",
            source="user",
            kind="platform_ops",
            title="rollback restores legacy runtime mutation access",
            priority=1,
            required_capabilities=frozenset(),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:legacy-after-rollback",
            requester_ref="owner:user",
        )
    )
    assert restored.id == "work-legacy-after-rollback"


def test_work_owner_transfer_rejects_active_lease_without_state_change(
    postgres_dsn: str,
) -> None:
    connection_factory = lambda: psycopg.connect(postgres_dsn)
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(connection_factory),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work-active-owner-fence",
        token_factory=lambda: "active-owner-fence-claim",
    )
    coordinator.submit(
        WorkRequest(
            idempotency_key="owner:postgres:active-owner-fence",
            source="user",
            kind="platform_ops",
            title="active lease blocks owner transfer",
            priority=1,
            required_capabilities=frozenset(),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:active-owner-fence",
            requester_ref="owner:user",
        )
    )
    assert coordinator.acquire(
        WorkerOffer(
            worker_id="active-worker",
            capabilities=frozenset(),
            attestations=frozenset(),
            lease_seconds=300,
        )
    ) is not None
    owner_store = PostgresWorkOwnerStore(connection_factory)

    with pytest.raises(
        WorkOwnershipLost,
        match="requires zero active leases",
    ):
        owner_store.transfer_owner(
            expected_owner="legacy",
            expected_generation=1,
            target_owner="operations_core",
            actor_ref="operator:pytest",
            reason="must not strand active lease",
            cutover_manifest_sha256="d" * 64,
        )

    assert (owner_store.read_owner().owner, owner_store.read_owner().generation) == (
        "legacy",
        1,
    )
    with psycopg.connect(postgres_dsn) as connection:
        receipt_count = connection.execute(
            "SELECT count(*) FROM volpred_ops.work_owner_receipts"
        ).fetchone()[0]
    assert receipt_count == 1


@pytest.mark.parametrize("start_before_expiry", [False, True])
def test_work_owner_rollback_reconciles_expired_lease_without_losing_identity(
    postgres_dsn: str,
    start_before_expiry: bool,
) -> None:
    connection_factory = lambda: psycopg.connect(postgres_dsn)
    owner_store = PostgresWorkOwnerStore(connection_factory)
    manifest_sha256 = "8" * 64
    cutover = owner_store.transfer_owner(
        expected_owner="legacy",
        expected_generation=1,
        target_owner="operations_core",
        actor_ref="operator:pytest",
        reason="exercise expired lease rollback",
        cutover_manifest_sha256=manifest_sha256,
    )
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory,
            owner_generation=cutover.generation,
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work-expired-owner-rollback",
        token_factory=lambda: "expired-owner-rollback-token",
    )
    submitted = coordinator.submit(
        WorkRequest(
            idempotency_key=(
                "owner:postgres:expired-owner-rollback:"
                f"{start_before_expiry}"
            ),
            source="user",
            kind="platform_ops",
            title="expired lease must not strand owner rollback",
            priority=1,
            required_capabilities=frozenset(),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:expired-owner-rollback",
            requester_ref="owner:user",
        )
    )
    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="expired-owner-worker",
            capabilities=frozenset(),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )
    assert lease is not None
    before_expiry = lease.work_item
    if start_before_expiry:
        before_expiry = coordinator.record(
            Started(
                work_id=submitted.id,
                lease_token=lease.token,
                expected_version=lease.work_item.version,
            )
        )
    _expire_claim(postgres_dsn, submitted.id)

    rollback = owner_store.transfer_owner(
        expected_owner="operations_core",
        expected_generation=cutover.generation,
        target_owner="legacy",
        actor_ref="operator:pytest",
        reason="rollback after worker expiry",
        cutover_manifest_sha256=manifest_sha256,
        rollback_of_generation=cutover.generation,
    )

    assert (rollback.owner, rollback.generation) == ("legacy", 3)
    with psycopg.connect(postgres_dsn) as connection:
        row = connection.execute(
            """
            SELECT id, idempotency_key, status, version, claimed_by,
                   claim_token, claim_expires_at, last_release_reason
            FROM volpred_ops.work_items
            WHERE id = %s
            """,
            (submitted.id,),
        ).fetchone()
        event = connection.execute(
            """
            SELECT kind, version, actor_ref
            FROM volpred_ops.work_events
            WHERE work_id = %s
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (submitted.id,),
        ).fetchone()
    assert row == (
        submitted.id,
        submitted.idempotency_key,
        "pending",
        before_expiry.version + 1,
        None,
        None,
        None,
        "ownership transfer reconciled expired lease",
    )
    assert event == (
        "released",
        before_expiry.version + 1,
        "system:work-owner-transfer",
    )


def test_work_owner_transfer_replay_is_exact_and_idempotent(
    postgres_dsn: str,
) -> None:
    owner_store = PostgresWorkOwnerStore(
        lambda: psycopg.connect(postgres_dsn)
    )
    command = {
        "expected_owner": "legacy",
        "expected_generation": 1,
        "target_owner": "operations_core",
        "actor_ref": "operator:pytest",
        "reason": "lost response replay",
        "cutover_manifest_sha256": "e" * 64,
    }

    first = owner_store.transfer_owner(**command)
    replay = owner_store.transfer_owner(**command)

    assert replay == first
    with pytest.raises(
        WorkOwnershipLost,
        match="compare-and-set failed",
    ):
        owner_store.transfer_owner(
            **{**command, "reason": "different command"}
        )


def test_work_owner_security_exposes_only_fenced_public_functions(
    postgres_dsn: str,
) -> None:
    with psycopg.connect(postgres_dsn) as connection:
        worker_privileges = connection.execute(
            """
            SELECT
              has_function_privilege(
                'volpred_ops_worker',
                'volpred_ops.submit_work_unfenced('
                'text,text,text,text,text,integer,text[],text[],text,text,'
                'text,text,timestamptz,text,text,integer,'
                'timestamptz,timestamptz)',
                'EXECUTE'
              ),
              has_function_privilege(
                'volpred_ops_worker',
                'volpred_ops.transfer_work_owner('
                'text,bigint,text,text,text,text,bigint)',
                'EXECUTE'
              ),
              has_function_privilege(
                'volpred_ops_worker',
                'volpred_ops.submit_work('
                'text,text,text,text,text,integer,text[],text[],text,text,'
                'text,text,timestamptz,text,text,integer,'
                'timestamptz,timestamptz,bigint)',
                'EXECUTE'
              )
            """
        ).fetchone()
        approver_privileges = connection.execute(
            """
            SELECT
              has_function_privilege(
                'volpred_ops_approver',
                'volpred_ops.transfer_work_owner('
                'text,bigint,text,text,text,text,bigint)',
                'EXECUTE'
              ),
              has_function_privilege(
                'volpred_ops_approver',
                'volpred_ops.approve_work('
                'text,integer,text,text,bigint)',
                'EXECUTE'
              )
            """
        ).fetchone()
        worker_table_access = connection.execute(
            """
            SELECT
              has_table_privilege(
                'volpred_ops_worker',
                'volpred_ops.work_owners',
                'SELECT,INSERT,UPDATE,DELETE'
              ),
              has_table_privilege(
                'volpred_ops_worker',
                'volpred_ops.work_owner_receipts',
                'SELECT,INSERT,UPDATE,DELETE'
              )
            """
        ).fetchone()

    assert worker_privileges == (False, False, True)
    assert approver_privileges == (False, True)
    assert worker_table_access == (False, False)

    with _approver_connection(postgres_dsn) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                SELECT *
                FROM volpred_ops.transfer_work_owner(
                  'legacy', 1, 'operations_core', 'operator:pytest',
                  'must pass durable gate', %s, NULL
                )
                """,
                ("9" * 64,),
            ).fetchall()


def test_postgres_worker_role_runs_adapter_but_cannot_delete(
    postgres_dsn: str,
) -> None:
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: _worker_connection(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work_postgres_worker_role",
    )
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:postgres:worker-role",
            source="user",
            kind="platform_ops",
            title="least privilege worker",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:worker-role",
        )
    )

    assert coordinator.inspect(WorkQuery(work_id=work.id)).items == (work,)
    with _worker_connection(postgres_dsn) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                INSERT INTO volpred_ops.work_items
                SELECT work_items.* FROM volpred_ops.work_items
                WHERE false
                """
            )
        connection.rollback()
        connection.execute("SET ROLE volpred_ops_worker")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                """
                UPDATE volpred_ops.work_items
                SET status = 'succeeded'
                WHERE id = %s
                """,
                (work.id,),
            )
        connection.rollback()
        connection.execute("SET ROLE volpred_ops_worker")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "DELETE FROM volpred_ops.work_items WHERE id = %s",
                (work.id,),
            )
    with _worker_connection(postgres_dsn) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "SELECT claim_token FROM volpred_ops.work_items"
            ).fetchall()
    with _worker_connection(postgres_dsn) as connection:
        columns = {
            description.name
            for description in connection.execute(
                "SELECT * FROM volpred_ops.work_item_reads LIMIT 0"
            ).description
        }
    assert "claim_token" not in columns
    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="least-privilege-worker",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )
    assert lease is not None
    running = coordinator.record(
        Started(
            work_id=work.id,
            lease_token=lease.token,
            expected_version=lease.work_item.version,
        )
    )
    completed = coordinator.record(
        Completed(
            report_id="worker-role-completion",
            work_id=work.id,
            lease_token=lease.token,
            expected_version=running.version,
            result_ref="changeset:worker-role",
            summary="named RPC lifecycle",
        )
    )
    assert completed.status == "succeeded"
    owner = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work_requires_separate_approver",
    )
    awaiting = owner.submit(
        WorkRequest(
            idempotency_key="owner:postgres:separate-approver",
            source="user",
            kind="platform_ops",
            title="separate approval authority",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="destructive",
            approval="required",
            payload_ref="owner:postgres:separate-approver",
        )
    )
    approval = ApprovalGranted(
        work_id=awaiting.id,
        expected_version=awaiting.version,
        approved_by="owner:user",
        evidence_ref="approval:separate-role",
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        coordinator.record(approval)
    approver = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: _approver_connection(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "unused",
    )
    assert approver.record(approval).status == "pending"


def test_postgres_approval_rpc_rejects_null_evidence(
    postgres_dsn: str,
) -> None:
    submitter = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: _worker_connection(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work_postgres_null_approval",
    )
    awaiting = submitter.submit(
        WorkRequest(
            idempotency_key="owner:postgres:null-approval",
            source="user",
            kind="platform_ops",
            title="null evidence must fail closed",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="destructive",
            approval="required",
            payload_ref="owner:postgres:null-approval",
        )
    )
    with _approver_connection(postgres_dsn) as connection:
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="approval requires actor and evidence references",
        ):
            connection.execute(
                "SELECT * FROM volpred_ops.approve_work(%s, %s, NULL, NULL)",
                (awaiting.id, awaiting.version),
            ).fetchall()

    assert submitter.inspect(WorkQuery(work_id=awaiting.id)).items == (awaiting,)


@pytest.mark.parametrize(
    ("lease_seconds", "claim_token", "message"),
    (
        (0, "claim", "lease_seconds must be positive"),
        (None, "claim", "lease_seconds must be positive"),
        (300, None, "claim token is required"),
        (300, "   ", "claim token is required"),
    ),
)
def test_postgres_acquire_rpc_rejects_invalid_lease(
    postgres_dsn: str,
    lease_seconds: int | None,
    claim_token: str | None,
    message: str,
) -> None:
    with _worker_connection(postgres_dsn) as connection:
        with pytest.raises(
            psycopg.errors.RaiseException,
            match=message,
        ):
            connection.execute(
                """
                SELECT *
                FROM volpred_ops.acquire_work(
                  'worker', ARRAY[]::text[], ARRAY[]::text[], %s, %s
                )
                """,
                (lease_seconds, claim_token),
            ).fetchall()


def test_postgres_acquire_waits_for_parent_and_orders_by_deadline(
    postgres_dsn: str,
) -> None:
    ids = iter(("pg_parent", "pg_child", "pg_earlier"))
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: next(ids),
        token_factory=lambda: "pg_parent_deadline_claim",
    )
    parent = coordinator.submit(
        WorkRequest(
            idempotency_key="pg-parent",
            source="user",
            kind="platform_ops",
            title="parent",
            priority=5,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="pg-parent",
            deadline="2026-07-25T00:00:00+00:00",
        )
    )
    coordinator.submit(
        WorkRequest(
            idempotency_key="pg-child",
            source="user",
            kind="platform_ops",
            title="blocked child",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="pg-child",
            parent_id=parent.id,
            deadline="2026-07-23T00:00:00+00:00",
        )
    )
    earlier = coordinator.submit(
        WorkRequest(
            idempotency_key="pg-earlier",
            source="user",
            kind="platform_ops",
            title="earlier ready",
            priority=5,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="pg-earlier",
            deadline="2026-07-24T00:00:00+00:00",
        )
    )

    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="postgres-worker",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )

    assert lease is not None
    assert lease.work_item.id == earlier.id
    assert lease.work_item.deadline == "2026-07-24T00:00:00+00:00"


def test_postgres_submit_rolls_back_when_event_append_fails(
    postgres_dsn: str,
) -> None:
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute(
            """
            CREATE FUNCTION volpred_ops.fail_submitted_event()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              IF NEW.kind = 'submitted' THEN
                RAISE EXCEPTION 'injected event failure';
              END IF;
              RETURN NEW;
            END;
            $$
            """
        )
        connection.execute(
            """
            CREATE TRIGGER fail_submitted_event
            BEFORE INSERT ON volpred_ops.work_events
            FOR EACH ROW
            EXECUTE FUNCTION volpred_ops.fail_submitted_event()
            """
        )
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work_postgres_rollback",
    )
    request = WorkRequest(
        idempotency_key="owner:postgres:rollback",
        source="user",
        kind="platform_ops",
        title="Postgres mutation rollback",
        priority=1,
        required_capabilities=frozenset({"code"}),
        required_attestations=frozenset(),
        risk="safe",
        approval="auto",
        payload_ref="owner:postgres:rollback",
    )

    try:
        with pytest.raises(psycopg.errors.RaiseException):
            coordinator.submit(request)
        assert coordinator.inspect(WorkQuery(work_id="work_postgres_rollback")).items == ()
    finally:
        with psycopg.connect(postgres_dsn, autocommit=True) as connection:
            connection.execute(
                "DROP TRIGGER IF EXISTS fail_submitted_event "
                "ON volpred_ops.work_events"
            )
            connection.execute(
                "DROP FUNCTION IF EXISTS volpred_ops.fail_submitted_event()"
            )


def test_postgres_owner_approval_is_versioned_and_auditable(
    postgres_dsn: str,
) -> None:
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work_postgres_approval",
    )
    waiting = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:postgres:approval",
            source="user",
            kind="platform_ops",
            title="Postgres 等待 owner 核准",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="destructive",
            approval="required",
            payload_ref="owner:postgres:approval",
        )
    )
    offer = WorkerOffer(
        worker_id="postgres-worker",
        capabilities=frozenset({"code"}),
        attestations=frozenset(),
        lease_seconds=300,
    )

    assert coordinator.acquire(offer) is None

    approved = coordinator.record(
        ApprovalGranted(
            work_id=waiting.id,
            expected_version=waiting.version,
            approved_by="owner:yhlai0911",
            evidence_ref="approval:postgres:2026-07-23",
        )
    )
    snapshot = coordinator.inspect(WorkQuery(work_id=waiting.id))

    assert approved.status == "pending"
    assert approved.approval == "approved"
    assert approved.version == 2
    assert tuple(event.kind for event in snapshot.events) == (
        "submitted",
        "approval_granted",
    )
    assert snapshot.events[-1].actor_ref == "owner:yhlai0911"
    assert snapshot.events[-1].evidence_ref == "approval:postgres:2026-07-23"


def test_postgres_acquire_skips_capability_mismatch(postgres_dsn: str) -> None:
    ids = iter(("work_postgres_research", "work_postgres_code"))
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: next(ids),
        token_factory=lambda: "claim_postgres_code",
    )
    coordinator.submit(
        WorkRequest(
            idempotency_key="schedule:postgres:research",
            source="schedule",
            kind="research",
            title="需要研究能力",
            priority=1,
            required_capabilities=frozenset({"research"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="schedule:postgres:research",
        )
    )
    code_work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:postgres:code",
            source="user",
            kind="platform_ops",
            title="需要程式能力",
            priority=2,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:code",
        )
    )

    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="postgres-worker",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )

    assert lease is not None
    assert lease.work_item.id == code_work.id


def test_postgres_two_workers_cannot_acquire_the_same_work(
    postgres_dsn: str,
) -> None:
    tokens = iter(("claim_postgres_a", "claim_postgres_b"))
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work_postgres_atomic",
        token_factory=lambda: next(tokens),
    )
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:postgres:atomic",
            source="user",
            kind="platform_ops",
            title="Postgres atomic claim",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:atomic",
        )
    )
    start_together = Barrier(2)

    def acquire(worker_id: str):
        start_together.wait()
        return coordinator.acquire(
            WorkerOffer(
                worker_id=worker_id,
                capabilities=frozenset({"code"}),
                attestations=frozenset(),
                lease_seconds=300,
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        leases = tuple(
            executor.map(acquire, ("postgres-worker-a", "postgres-worker-b"))
        )

    acquired = tuple(lease for lease in leases if lease is not None)
    snapshot = coordinator.inspect(WorkQuery(work_id=work.id))

    assert len(acquired) == 1
    assert snapshot.items[0].status == "claimed"
    assert snapshot.items[0].claimed_by in {
        "postgres-worker-a",
        "postgres-worker-b",
    }
    assert tuple(event.kind for event in snapshot.events) == (
        "submitted",
        "acquired",
    )


def test_postgres_database_clock_prevents_fast_host_from_stealing_live_lease(
    postgres_dsn: str,
) -> None:
    owner = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work_database_clock",
        token_factory=lambda: "claim_database_clock_owner",
    )
    owner.submit(
        WorkRequest(
            idempotency_key="owner:postgres:database-clock",
            source="user",
            kind="platform_ops",
            title="Database clock owns lease expiry",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:database-clock",
        )
    )
    owner_lease = owner.acquire(
        WorkerOffer(
            worker_id="lease-owner",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )
    assert owner_lease is not None

    fast_host = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW + timedelta(days=1),
        id_factory=lambda: "unused",
        token_factory=lambda: "claim_fast_host",
    )
    stolen = fast_host.acquire(
        WorkerOffer(
            worker_id="fast-host",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )

    assert stolen is None


def test_postgres_acquire_honors_capabilities_and_attestations(
    postgres_dsn: str,
) -> None:
    work_ids = iter(("work_postgres_research", "work_postgres_code"))
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: next(work_ids),
        token_factory=lambda: "claim_postgres_capability",
    )
    coordinator.submit(
        WorkRequest(
            idempotency_key="owner:postgres:research",
            source="user",
            kind="research",
            title="需要 research 與 review attestation",
            priority=1,
            required_capabilities=frozenset({"research"}),
            required_attestations=frozenset({"review"}),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:research",
        )
    )
    code_work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:postgres:code",
            source="user",
            kind="platform_ops",
            title="只需要 code",
            priority=2,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:code",
        )
    )

    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="postgres-code-worker",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )

    assert lease is not None
    assert lease.work_item.id == code_work.id


def test_postgres_claimed_work_starts_with_lease_and_version(
    postgres_dsn: str,
) -> None:
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work_postgres_start",
        token_factory=lambda: "claim_postgres_start",
    )
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:postgres:start",
            source="user",
            kind="platform_ops",
            title="Postgres claimed to running",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:start",
        )
    )
    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="postgres-worker",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )
    assert lease is not None

    running = coordinator.record(
        Started(
            work_id=work.id,
            lease_token=lease.token,
            expected_version=lease.work_item.version,
        )
    )
    snapshot = coordinator.inspect(WorkQuery(work_id=work.id))

    assert running.status == "running"
    assert running.version == 3
    assert tuple(event.kind for event in snapshot.events) == (
        "submitted",
        "acquired",
        "started",
    )


@pytest.mark.parametrize(
    "mutation",
    ("start", "checkpoint", "release", "complete"),
)
def test_postgres_expired_lease_cannot_mutate_before_reacquire(
    postgres_dsn: str,
    mutation: str,
) -> None:
    now = [FIXED_NOW]
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: now[0],
        id_factory=lambda: f"work_postgres_expired_{mutation}",
        token_factory=lambda: "claim_postgres_expired",
        checkpoint_id_factory=lambda: "checkpoint_postgres_expired",
    )
    work = coordinator.submit(
        WorkRequest(
            idempotency_key=f"owner:postgres:expired:{mutation}",
            source="user",
            kind="platform_ops",
            title="Postgres expired lease fencing",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:expired",
        )
    )
    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="postgres-worker",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=1,
        )
    )
    assert lease is not None

    if mutation == "start":
        report = Started(
            work_id=work.id,
            lease_token=lease.token,
            expected_version=lease.work_item.version,
        )
    else:
        running = coordinator.record(
            Started(
                work_id=work.id,
                lease_token=lease.token,
                expected_version=lease.work_item.version,
            )
        )
        if mutation == "checkpoint":
            report = Checkpointed(
                report_id="checkpoint_postgres_expired",
                work_id=work.id,
                lease_token=lease.token,
                expected_version=running.version,
                artifact_ref="workspace:postgres-expired",
                artifact_sha256="f" * 64,
                verification_ref="pytest:postgres-expired",
            )
        elif mutation == "release":
            report = Released(
                work_id=work.id,
                lease_token=lease.token,
                expected_version=running.version,
                reason="lease_expired",
            )
        else:
            report = Completed(
                report_id="completion_postgres_expired",
                work_id=work.id,
                lease_token=lease.token,
                expected_version=running.version,
                result_ref="changeset:postgres-expired",
                summary="must not complete",
            )

    _expire_claim(postgres_dsn, work.id)

    with pytest.raises(ClaimLost):
        coordinator.record(report)


@pytest.mark.parametrize(
    ("invalidity", "expected_exception", "message"),
    (
        ("token", ClaimLost, "work_postgres_invalid_start"),
        ("version", ValueError, "stale work item version"),
        ("status", ValueError, "cannot mutate work item"),
    ),
)
def test_postgres_start_rejects_invalid_fencing_and_transition(
    postgres_dsn: str,
    invalidity: str,
    expected_exception: type[Exception],
    message: str,
) -> None:
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work_postgres_invalid_start",
        token_factory=lambda: "claim_postgres_invalid_start",
    )
    work = coordinator.submit(
        WorkRequest(
            idempotency_key=f"owner:postgres:invalid-start:{invalidity}",
            source="user",
            kind="platform_ops",
            title="Postgres invalid transition fencing",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref=f"owner:postgres:invalid-start:{invalidity}",
        )
    )
    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="postgres-worker",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )
    assert lease is not None
    token = "claim_wrong" if invalidity == "token" else lease.token
    version = (
        lease.work_item.version + 1
        if invalidity == "version"
        else lease.work_item.version
    )
    if invalidity == "status":
        running = coordinator.record(
            Started(
                work_id=work.id,
                lease_token=lease.token,
                expected_version=lease.work_item.version,
            )
        )
        version = running.version

    with pytest.raises(expected_exception, match=message):
        coordinator.record(
            Started(
                work_id=work.id,
                lease_token=token,
                expected_version=version,
            )
        )


def test_postgres_expired_claim_is_reacquired_and_stale_token_is_fenced(
    postgres_dsn: str,
) -> None:
    now = [FIXED_NOW]
    tokens = iter(("claim_postgres_old", "claim_postgres_new"))
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: now[0],
        id_factory=lambda: "work_postgres_reclaim",
        token_factory=lambda: next(tokens),
    )
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:postgres:reclaim",
            source="user",
            kind="platform_ops",
            title="Postgres stale claim recovery",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:reclaim",
        )
    )
    offer = WorkerOffer(
        worker_id="postgres-old-worker",
        capabilities=frozenset({"code"}),
        attestations=frozenset(),
        lease_seconds=1,
    )
    stale_lease = coordinator.acquire(offer)
    assert stale_lease is not None

    _expire_claim(postgres_dsn, work.id)
    new_lease = coordinator.acquire(
        WorkerOffer(
            worker_id="postgres-new-worker",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )

    assert new_lease is not None
    assert new_lease.token == "claim_postgres_new"
    assert new_lease.work_item.version == 3
    with pytest.raises(ClaimLost):
        coordinator.record(
            Started(
                work_id=work.id,
                lease_token=stale_lease.token,
                expected_version=stale_lease.work_item.version,
            )
        )


def test_postgres_checkpoint_is_durable_and_visible_through_inspect(
    postgres_dsn: str,
) -> None:
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work_postgres_checkpoint",
        token_factory=lambda: "claim_postgres_checkpoint",
        checkpoint_id_factory=lambda: "checkpoint_postgres_0001",
    )
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:postgres:checkpoint",
            source="user",
            kind="platform_ops",
            title="Postgres durable checkpoint",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:checkpoint",
        )
    )
    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="postgres-worker",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )
    assert lease is not None
    running = coordinator.record(
        Started(
            work_id=work.id,
            lease_token=lease.token,
            expected_version=lease.work_item.version,
        )
    )

    report = Checkpointed(
        report_id="checkpoint_postgres_0001",
        work_id=work.id,
        lease_token=lease.token,
        expected_version=running.version,
        artifact_ref="workspace:postgres-checkpoint",
        artifact_sha256="d" * 64,
        verification_ref="pytest:postgres-checkpoint",
    )
    checkpointed = coordinator.record(report)
    replay = coordinator.record(report)
    snapshot = coordinator.inspect(WorkQuery(work_id=work.id))

    assert replay == checkpointed
    assert checkpointed.version == 4
    assert checkpointed.latest_verified_checkpoint_id == "checkpoint_postgres_0001"
    assert len(snapshot.checkpoints) == 1
    assert snapshot.checkpoints[0].artifact_sha256 == "d" * 64
    assert tuple(event.kind for event in snapshot.events) == (
        "submitted",
        "acquired",
        "started",
        "checkpointed",
    )


def test_postgres_checkpoint_rolls_back_when_event_append_fails(
    postgres_dsn: str,
) -> None:
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work_postgres_checkpoint_rollback",
        token_factory=lambda: "claim_postgres_checkpoint_rollback",
        checkpoint_id_factory=lambda: "checkpoint_postgres_rollback",
    )
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:postgres:checkpoint-rollback",
            source="user",
            kind="platform_ops",
            title="checkpoint transaction rollback",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:checkpoint-rollback",
        )
    )
    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="postgres-worker",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )
    assert lease is not None
    running = coordinator.record(
        Started(
            work_id=work.id,
            lease_token=lease.token,
            expected_version=lease.work_item.version,
        )
    )
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute(
            """
            CREATE FUNCTION volpred_ops.fail_checkpoint_event()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
              IF NEW.kind = 'checkpointed' THEN
                RAISE EXCEPTION 'injected checkpoint event failure';
              END IF;
              RETURN NEW;
            END;
            $$
            """
        )
        connection.execute(
            """
            CREATE TRIGGER fail_checkpoint_event
            BEFORE INSERT ON volpred_ops.work_events
            FOR EACH ROW
            EXECUTE FUNCTION volpred_ops.fail_checkpoint_event()
            """
        )
    try:
        with pytest.raises(psycopg.errors.RaiseException):
            coordinator.record(
                Checkpointed(
                    report_id="checkpoint_postgres_rollback",
                    work_id=work.id,
                    lease_token=lease.token,
                    expected_version=running.version,
                    artifact_ref="workspace:must-roll-back",
                    artifact_sha256="a" * 64,
                    verification_ref="pytest:injected-failure",
                )
            )
        snapshot = coordinator.inspect(WorkQuery(work_id=work.id))
        assert snapshot.items[0] == running
        assert snapshot.checkpoints == ()
        assert tuple(event.kind for event in snapshot.events) == (
            "submitted",
            "acquired",
            "started",
        )
    finally:
        with psycopg.connect(postgres_dsn, autocommit=True) as connection:
            connection.execute(
                "DROP TRIGGER IF EXISTS fail_checkpoint_event "
                "ON volpred_ops.work_events"
            )
            connection.execute(
                "DROP FUNCTION IF EXISTS volpred_ops.fail_checkpoint_event()"
            )


def test_postgres_release_resumes_from_verified_checkpoint(
    postgres_dsn: str,
) -> None:
    tokens = iter(("claim_postgres_release", "claim_postgres_resume"))
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work_postgres_resume",
        token_factory=lambda: next(tokens),
        checkpoint_id_factory=lambda: "checkpoint_postgres_resume",
    )
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:postgres:resume",
            source="user",
            kind="platform_ops",
            title="Postgres checkpoint resume",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:resume",
        )
    )
    offer = WorkerOffer(
        worker_id="postgres-worker",
        capabilities=frozenset({"code"}),
        attestations=frozenset(),
        lease_seconds=300,
    )
    first_lease = coordinator.acquire(offer)
    assert first_lease is not None
    running = coordinator.record(
        Started(
            work_id=work.id,
            lease_token=first_lease.token,
            expected_version=first_lease.work_item.version,
        )
    )
    checkpointed = coordinator.record(
        Checkpointed(
            report_id="checkpoint_postgres_resume",
            work_id=work.id,
            lease_token=first_lease.token,
            expected_version=running.version,
            artifact_ref="workspace:postgres-resume",
            artifact_sha256="e" * 64,
            verification_ref="pytest:postgres-resume",
        )
    )

    released = coordinator.record(
        Released(
            work_id=work.id,
            lease_token=first_lease.token,
            expected_version=checkpointed.version,
            reason="cooperative_preemption",
        )
    )
    resumed = coordinator.acquire(offer)

    assert released.status == "pending"
    assert released.claimed_by is None
    assert resumed is not None
    assert resumed.token == "claim_postgres_resume"
    assert resumed.resume_checkpoint_id == "checkpoint_postgres_resume"


def test_postgres_completion_is_terminal_and_idempotent(
    postgres_dsn: str,
) -> None:
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work_postgres_complete",
        token_factory=lambda: "claim_postgres_complete",
    )
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:postgres:complete",
            source="user",
            kind="platform_ops",
            title="Postgres terminal receipt",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:complete",
        )
    )
    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="postgres-worker",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )
    assert lease is not None
    running = coordinator.record(
        Started(
            work_id=work.id,
            lease_token=lease.token,
            expected_version=lease.work_item.version,
        )
    )
    report = Completed(
        report_id="completion_postgres_0001",
        work_id=work.id,
        lease_token=lease.token,
        expected_version=running.version,
        result_ref="changeset:postgres",
        summary="postgres contract complete",
    )

    completed = coordinator.record(report)
    replay = coordinator.record(report)
    snapshot = coordinator.inspect(WorkQuery(work_id=work.id))

    assert replay == completed
    assert completed.status == "succeeded"
    assert completed.version == 4
    assert len(snapshot.receipts) == 1
    assert snapshot.receipts[0].id == "completion_postgres_0001"
    assert tuple(event.kind for event in snapshot.events) == (
        "submitted",
        "acquired",
        "started",
        "completed",
    )


def test_postgres_concurrent_completion_replays_single_terminal_receipt(
    postgres_dsn: str,
) -> None:
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work_postgres_concurrent_complete",
        token_factory=lambda: "claim_postgres_concurrent_complete",
    )
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:postgres:concurrent-complete",
            source="user",
            kind="platform_ops",
            title="Concurrent completion remains idempotent",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:concurrent-complete",
        )
    )
    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="postgres-worker",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )
    assert lease is not None
    running = coordinator.record(
        Started(
            work_id=work.id,
            lease_token=lease.token,
            expected_version=lease.work_item.version,
        )
    )
    report = Completed(
        report_id="completion_postgres_concurrent",
        work_id=work.id,
        lease_token=lease.token,
        expected_version=running.version,
        result_ref="changeset:postgres-concurrent",
        summary="one durable completion",
    )
    receipt_reads = Barrier(2)

    class BarrierCursor:
        def __init__(self, cursor):
            self._cursor = cursor

        def fetchone(self):
            row = self._cursor.fetchone()
            receipt_reads.wait()
            return row

    class BarrierConnection:
        def __init__(self):
            self._connection = psycopg.connect(postgres_dsn)
            self._work_lock_requested = False

        @property
        def row_factory(self):
            return self._connection.row_factory

        @row_factory.setter
        def row_factory(self, value):
            self._connection.row_factory = value

        def __enter__(self):
            self._connection.__enter__()
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return self._connection.__exit__(exc_type, exc_value, traceback)

        def execute(self, query, params=None):
            if (
                "FROM volpred_ops.work_items" in query
                and "FOR UPDATE" in query
            ):
                self._work_lock_requested = True
            cursor = self._connection.execute(query, params)
            if (
                not self._work_lock_requested
                and "FROM volpred_ops.work_receipts" in query
                and "WHERE id = %s" in query
            ):
                return BarrierCursor(cursor)
            return cursor

    completer = WorkCoordinator(
        PostgresCoordinationStore(connection_factory=BarrierConnection),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "unused",
    )
    start_together = Barrier(2)

    def complete() -> object:
        start_together.wait()
        return completer.record(report)

    with ThreadPoolExecutor(max_workers=2) as executor:
        completed = tuple(executor.map(lambda _: complete(), range(2)))

    snapshot = coordinator.inspect(WorkQuery(work_id=work.id))
    assert completed[0] == completed[1]
    assert len(snapshot.receipts) == 1
    assert tuple(event.kind for event in snapshot.events).count("completed") == 1
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute(
            "DROP TRIGGER IF EXISTS delay_terminal_update "
            "ON volpred_ops.work_items"
        )
        connection.execute(
            "DROP FUNCTION IF EXISTS volpred_ops.delay_terminal_update()"
        )


def test_postgres_release_resume_and_completion_are_durable(
    postgres_dsn: str,
) -> None:
    tokens = iter(("claim_postgres_first", "claim_postgres_resumed"))
    coordinator = WorkCoordinator(
        PostgresCoordinationStore(
            connection_factory=lambda: psycopg.connect(postgres_dsn)
        ),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work_postgres_lifecycle",
        token_factory=lambda: next(tokens),
        checkpoint_id_factory=lambda: "checkpoint_postgres_resume",
    )
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:postgres:lifecycle",
            source="user",
            kind="platform_ops",
            title="Postgres release resume complete",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:postgres:lifecycle",
        )
    )
    offer = WorkerOffer(
        worker_id="postgres-worker",
        capabilities=frozenset({"code"}),
        attestations=frozenset(),
        lease_seconds=300,
    )
    first_lease = coordinator.acquire(offer)
    assert first_lease is not None
    running = coordinator.record(
        Started(
            work_id=work.id,
            lease_token=first_lease.token,
            expected_version=first_lease.work_item.version,
        )
    )
    checkpointed = coordinator.record(
        Checkpointed(
            report_id="checkpoint_postgres_resume",
            work_id=work.id,
            lease_token=first_lease.token,
            expected_version=running.version,
            artifact_ref="workspace:postgres-resume",
            artifact_sha256="e" * 64,
            verification_ref="pytest:postgres-resume",
        )
    )
    released = coordinator.record(
        Released(
            work_id=work.id,
            lease_token=first_lease.token,
            expected_version=checkpointed.version,
            reason="cooperative_preemption",
        )
    )
    resumed_lease = coordinator.acquire(offer)
    assert resumed_lease is not None
    resumed = coordinator.record(
        Started(
            work_id=work.id,
            lease_token=resumed_lease.token,
            expected_version=resumed_lease.work_item.version,
        )
    )
    report = Completed(
        report_id="completion_postgres_lifecycle",
        work_id=work.id,
        lease_token=resumed_lease.token,
        expected_version=resumed.version,
        result_ref="changeset:postgres-lifecycle",
        summary="postgres lifecycle complete",
    )
    completed = coordinator.record(report)
    replay = coordinator.record(report)
    snapshot = coordinator.inspect(WorkQuery(work_id=work.id))

    assert released.status == "pending"
    assert resumed_lease.resume_checkpoint_id == "checkpoint_postgres_resume"
    assert replay == completed
    assert completed.status == "succeeded"
    assert len(snapshot.receipts) == 1
    assert tuple(event.kind for event in snapshot.events) == (
        "submitted",
        "acquired",
        "started",
        "checkpointed",
        "released",
        "acquired",
        "started",
        "completed",
    )


def test_postgres_migration_enables_rls_and_denies_untrusted_schema_access(
    postgres_dsn: str,
) -> None:
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        rows = connection.execute(
            """
            SELECT c.relname, c.relrowsecurity
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'volpred_ops'
              AND c.relkind = 'r'
            ORDER BY c.relname
            """
        ).fetchall()
        connection.execute("CREATE ROLE volpred_ops_untrusted NOLOGIN")
        try:
            can_use_schema = connection.execute(
                """
                SELECT has_schema_privilege(
                  'volpred_ops_untrusted',
                  'volpred_ops',
                  'USAGE'
                )
                """
            ).fetchone()[0]
        finally:
            connection.execute("DROP ROLE volpred_ops_untrusted")

    assert rows == [
        ("work_checkpoints", True),
        ("work_events", True),
        ("work_items", True),
        ("work_owner_receipts", True),
        ("work_owners", True),
        ("work_receipts", True),
    ]
    assert can_use_schema is False


def test_postgres_catalog_contains_canonical_audit_fields_and_fk_indexes(
    postgres_dsn: str,
) -> None:
    with psycopg.connect(postgres_dsn) as connection:
        columns = {
            row[0]
            for row in connection.execute(
                """
                SELECT a.attname
                FROM pg_attribute AS a
                WHERE a.attrelid = 'volpred_ops.work_items'::regclass
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                """
            ).fetchall()
        }
        indexes = {
            row[0]
            for row in connection.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'volpred_ops'
                  AND tablename = 'work_items'
                """
            ).fetchall()
        }
        runtime_roles = connection.execute(
            """
            SELECT rolname, rolsuper, rolcreatedb, rolcreaterole,
                   rolbypassrls, rolinherit
            FROM pg_roles
            WHERE rolname IN (
              'volpred_ops_worker',
              'volpred_ops_approver',
              'volpred_ops_definer'
            )
            ORDER BY rolname
            """
        ).fetchall()
        unsafe_memberships = connection.execute(
            """
            SELECT member_role.rolname, granted_role.rolname
            FROM pg_auth_members AS membership
            JOIN pg_roles AS member_role
              ON member_role.oid = membership.member
            JOIN pg_roles AS granted_role
              ON granted_role.oid = membership.roleid
            WHERE member_role.rolname IN (
              'volpred_ops_worker',
              'volpred_ops_approver',
              'volpred_ops_definer'
            )
               OR granted_role.rolname IN (
                 'volpred_ops_worker',
                 'volpred_ops_approver',
                 'volpred_ops_definer'
               )
            """
        ).fetchall()
        function_owners = connection.execute(
            """
            SELECT DISTINCT owner.rolname
            FROM pg_proc AS function
            JOIN pg_namespace AS namespace
              ON namespace.oid = function.pronamespace
            JOIN pg_roles AS owner
              ON owner.oid = function.proowner
            WHERE namespace.nspname = 'volpred_ops'
              AND function.prosecdef
            """
            ).fetchall()
        function_return_types = connection.execute(
            """
            SELECT DISTINCT function.prorettype::regtype::text
            FROM pg_proc AS function
            JOIN pg_namespace AS namespace
              ON namespace.oid = function.pronamespace
            WHERE namespace.nspname = 'volpred_ops'
              AND function.prosecdef
            """
        ).fetchall()
        definer_write_privileges = connection.execute(
            """
            SELECT table_name,
                   has_table_privilege(
                     'volpred_ops_definer',
                     format('volpred_ops.%I', table_name),
                     'INSERT'
                   ),
                   has_table_privilege(
                     'volpred_ops_definer',
                     format('volpred_ops.%I', table_name),
                     'UPDATE'
                   ),
                   has_table_privilege(
                     'volpred_ops_definer',
                     format('volpred_ops.%I', table_name),
                     'DELETE'
                   )
                FROM information_schema.tables
                WHERE table_schema = 'volpred_ops'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """
        ).fetchall()

    assert {
        "parent_id",
        "deadline",
        "requester_ref",
        "created_at",
        "updated_at",
        "blocked_reason",
    } <= columns
    assert {
        "work_items_parent_idx",
        "work_items_latest_checkpoint_idx",
    } <= indexes
    assert runtime_roles == [
        ("volpred_ops_approver", False, False, False, False, False),
        ("volpred_ops_definer", False, False, False, False, False),
        ("volpred_ops_worker", False, False, False, False, False),
    ]
    assert unsafe_memberships == []
    assert function_owners == [("volpred_ops_definer",)]
    assert {row[0] for row in function_return_types} == {
        "void",
        "volpred_ops.work_item_reads",
        "volpred_ops.work_owner_reads",
    }
    assert definer_write_privileges == [
        ("work_checkpoints", True, False, False),
        ("work_events", True, False, False),
        ("work_items", True, True, False),
        ("work_owner_receipts", True, False, False),
        ("work_owners", False, True, False),
        ("work_receipts", True, False, False),
    ]


def test_postgres_migration_can_be_rolled_back_and_reapplied(
    postgres_dsn: str,
) -> None:
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA volpred_ops CASCADE")
        assert connection.execute(
            "SELECT to_regnamespace('volpred_ops')"
        ).fetchone()[0] is None
        connection.execute("ALTER ROLE volpred_ops_worker LOGIN")
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="unsafe attributes",
        ):
            connection.execute(MIGRATION.read_text(encoding="utf-8"))
        connection.execute("ALTER ROLE volpred_ops_worker NOLOGIN")
        connection.execute("DROP SCHEMA IF EXISTS volpred_ops CASCADE")
        connection.execute(
            "GRANT pg_read_all_data TO volpred_ops_worker"
        )
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="unsafe attributes",
        ):
            connection.execute(MIGRATION.read_text(encoding="utf-8"))
        connection.execute(
            "REVOKE pg_read_all_data FROM volpred_ops_worker"
        )
        connection.execute("DROP SCHEMA IF EXISTS volpred_ops CASCADE")
        connection.execute("CREATE ROLE volpred_ops_test_incoming NOLOGIN")
        connection.execute(
            "GRANT volpred_ops_definer TO volpred_ops_test_incoming"
        )
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="unsafe attributes",
        ):
            connection.execute(MIGRATION.read_text(encoding="utf-8"))
        connection.execute(
            "REVOKE volpred_ops_definer FROM volpred_ops_test_incoming"
        )
        connection.execute("DROP ROLE volpred_ops_test_incoming")
        connection.execute("DROP SCHEMA IF EXISTS volpred_ops CASCADE")
        connection.execute(MIGRATION.read_text(encoding="utf-8"))
        connection.execute(
            OWNERSHIP_MIGRATION.read_text(encoding="utf-8")
        )

        table_count = connection.execute(
            """
            SELECT count(*)
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'volpred_ops'
              AND c.relkind = 'r'
            """
        ).fetchone()[0]

    assert table_count == 6


def test_postgres_schema_is_private_rls_enabled_and_transactionally_removable(
    postgres_dsn: str,
) -> None:
    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        connection.execute("CREATE ROLE volpred_untrusted NOLOGIN")
        try:
            usage = connection.execute(
                """
                SELECT has_schema_privilege(
                  'volpred_untrusted', 'volpred_ops', 'USAGE'
                )
                """
            ).fetchone()
            rls = connection.execute(
                """
                SELECT bool_and(c.relrowsecurity), count(*)
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname = 'volpred_ops'
                  AND c.relname IN (
                    'work_items',
                    'work_events',
                    'work_checkpoints',
                    'work_receipts',
                    'work_owners',
                    'work_owner_receipts'
                  )
                """
            ).fetchone()
        finally:
            connection.execute("DROP ROLE volpred_untrusted")

    assert usage == (False,)
    assert rls == (True, 6)

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("DROP SCHEMA volpred_ops CASCADE")
        removed = connection.execute(
            "SELECT to_regnamespace('volpred_ops')"
        ).fetchone()
        connection.rollback()
        restored = connection.execute(
            "SELECT to_regnamespace('volpred_ops')::text"
        ).fetchone()

    assert removed == (None,)
    assert restored == ("volpred_ops",)
