from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

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
from volpred.ops.work.memory import InMemoryCoordinationStore


FIXED_NOW = datetime(2026, 7, 23, 4, 0, tzinfo=timezone.utc)


def build_coordinator() -> WorkCoordinator:
    work_ids = iter(("work_0001", "work_0002", "work_0003"))
    claim_tokens = iter(("claim_0001", "claim_0002", "claim_0003"))
    return WorkCoordinator(
        InMemoryCoordinationStore(),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: next(work_ids),
        token_factory=lambda: next(claim_tokens),
        checkpoint_id_factory=lambda: "checkpoint_0001",
    )


def test_submit_is_idempotent_and_the_work_item_is_inspectable() -> None:
    coordinator = build_coordinator()
    request = WorkRequest(
        idempotency_key="owner:platform-rebuild:phase-0",
        source="user",
        kind="platform_ops",
        title="建立 shadow Work Coordinator",
        priority=1,
        required_capabilities=frozenset({"code"}),
        required_attestations=frozenset(),
        risk="safe",
        approval="auto",
        payload_ref="plan:phase-1:work-coordinator",
        requester_ref="owner:user",
    )

    first = coordinator.submit(request)
    replay = coordinator.submit(request)
    snapshot = coordinator.inspect(WorkQuery(work_id="work_0001"))

    assert replay == first
    assert first.id == "work_0001"
    assert first.status == "pending"
    assert first.version == 1
    assert first.created_at == "2026-07-23T04:00:00+00:00"
    assert first.updated_at == first.created_at
    assert first.requester_ref == "owner:user"
    assert first.blocked_reason is None
    assert snapshot.items == (first,)


def test_acquire_waits_for_parent_and_orders_ready_work_by_deadline() -> None:
    coordinator = build_coordinator()
    parent = coordinator.submit(
        WorkRequest(
            idempotency_key="parent",
            source="user",
            kind="platform_ops",
            title="parent",
            priority=5,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="parent",
            deadline="2026-07-25T00:00:00+00:00",
        )
    )
    coordinator.submit(
        WorkRequest(
            idempotency_key="child",
            source="user",
            kind="platform_ops",
            title="blocked child",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="child",
            parent_id=parent.id,
            deadline="2026-07-23T00:00:00+00:00",
        )
    )
    earlier_ready = coordinator.submit(
        WorkRequest(
            idempotency_key="earlier-ready",
            source="user",
            kind="platform_ops",
            title="earlier ready deadline",
            priority=5,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="earlier-ready",
            deadline="2026-07-24T00:00:00+00:00",
        )
    )

    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="worker",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )

    assert lease is not None
    assert lease.work_item.id == earlier_ready.id
    assert lease.work_item.parent_id is None
    assert lease.work_item.deadline == "2026-07-24T00:00:00+00:00"


def test_high_risk_work_waiting_for_approval_cannot_be_acquired() -> None:
    coordinator = build_coordinator()
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:platform:destructive",
            source="user",
            kind="platform_ops",
            title="等待 owner 核准的破壞性操作",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="destructive",
            approval="required",
            payload_ref="owner:platform:destructive",
        )
    )

    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="codex-worker",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )
    snapshot = coordinator.inspect(WorkQuery(work_id=work.id))

    assert work.status == "awaiting_approval"
    assert lease is None
    assert snapshot.items == (work,)


def test_owner_approval_makes_waiting_work_ready_and_is_auditable() -> None:
    coordinator = build_coordinator()
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:platform:approve",
            source="user",
            kind="platform_ops",
            title="經 owner 核准後才能執行",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="destructive",
            approval="required",
            payload_ref="owner:platform:approve",
        )
    )

    approved = coordinator.record(
        ApprovalGranted(
            work_id=work.id,
            expected_version=work.version,
            approved_by="owner:yhlai0911",
            evidence_ref="approval:platform:approve:2026-07-23",
        )
    )
    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="codex-worker",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )
    snapshot = coordinator.inspect(WorkQuery(work_id=work.id))

    assert approved.status == "pending"
    assert approved.approval == "approved"
    assert approved.version == 2
    assert lease is not None
    assert lease.work_item.version == 3
    assert tuple(event.kind for event in snapshot.events) == (
        "submitted",
        "approval_granted",
        "acquired",
    )
    assert snapshot.events[1].actor_ref == "owner:yhlai0911"
    assert (
        snapshot.events[1].evidence_ref
        == "approval:platform:approve:2026-07-23"
    )


@pytest.mark.parametrize(
    ("risk", "approval"),
    (
        ("unknown", "auto"),
        ("safe", "denied"),
        ("destructive", "approved"),
    ),
)
def test_submit_rejects_unsupported_request_policy_values(
    risk: str,
    approval: str,
) -> None:
    coordinator = build_coordinator()
    request = WorkRequest(
        idempotency_key=f"owner:platform:invalid:{risk}:{approval}",
        source="user",
        kind="platform_ops",
        title="未知政策不得進入 queue",
        priority=1,
        required_capabilities=frozenset({"code"}),
        required_attestations=frozenset(),
        risk=risk,
        approval=approval,
        payload_ref="owner:platform:invalid-policy",
    )

    with pytest.raises(ValueError, match="unsupported work policy"):
        coordinator.submit(request)

    assert coordinator.inspect(WorkQuery()).items == ()


def test_acquire_skips_higher_priority_work_when_capabilities_do_not_match() -> None:
    coordinator = build_coordinator()
    coordinator.submit(
        WorkRequest(
            idempotency_key="schedule:research:001",
            source="schedule",
            kind="research",
            title="需要研究能力",
            priority=1,
            required_capabilities=frozenset({"research"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="schedule:research",
        )
    )
    code_work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:code:001",
            source="user",
            kind="platform_ops",
            title="需要程式能力",
            priority=2,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:code",
        )
    )

    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="codex-worker",
            capabilities=frozenset({"code", "review"}),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )

    assert lease is not None
    assert lease.token == "claim_0001"
    assert lease.work_item.id == code_work.id
    assert lease.work_item.status == "claimed"
    assert lease.work_item.version == 2
    assert lease.expires_at == "2026-07-23T04:05:00+00:00"


def test_two_workers_cannot_acquire_the_same_work_item() -> None:
    coordinator = build_coordinator()
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:code:atomic-claim",
            source="user",
            kind="platform_ops",
            title="只能由一個 worker 領取",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:code:atomic-claim",
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
            executor.map(acquire, ("codex-worker-a", "codex-worker-b"))
        )

    acquired = tuple(lease for lease in leases if lease is not None)
    snapshot = coordinator.inspect(WorkQuery(work_id=work.id))

    assert len(acquired) == 1
    assert snapshot.items[0].status == "claimed"
    assert snapshot.items[0].claimed_by in {"codex-worker-a", "codex-worker-b"}


def test_claimed_work_can_start_only_with_its_lease_and_expected_version() -> None:
    coordinator = build_coordinator()
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:code:started",
            source="user",
            kind="platform_ops",
            title="開始 shadow 工作",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:code:started",
        )
    )
    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="codex-worker",
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

    assert running.status == "running"
    assert running.version == 3
    assert running.claimed_by == "codex-worker"


@pytest.mark.parametrize(
    ("invalidity", "expected_exception", "message"),
    (
        ("token", ClaimLost, "work_0001"),
        ("version", ValueError, "stale work item version"),
        ("status", ValueError, "cannot mutate work item"),
    ),
)
def test_start_rejects_invalid_ownership_version_and_transition(
    invalidity: str,
    expected_exception: type[Exception],
    message: str,
) -> None:
    coordinator = build_coordinator()
    work = coordinator.submit(
        WorkRequest(
            idempotency_key=f"owner:code:invalid-start:{invalidity}",
            source="user",
            kind="platform_ops",
            title="拒絕無效 start",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref=f"owner:code:invalid-start:{invalidity}",
        )
    )
    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="codex-worker",
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


def test_running_work_records_a_verified_checkpoint_through_the_same_seam() -> None:
    coordinator = build_coordinator()
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:code:checkpoint",
            source="user",
            kind="platform_ops",
            title="保存可續跑檢查點",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:code:checkpoint",
        )
    )
    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="codex-worker",
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
        report_id="checkpoint_0001",
        work_id=work.id,
        lease_token=lease.token,
        expected_version=running.version,
        artifact_ref="workspace:dispatch-slot-1",
        artifact_sha256="a" * 64,
        verification_ref="pytest:test_work_coordinator",
    )
    checkpointed = coordinator.record(report)
    replay = coordinator.record(report)
    snapshot = coordinator.inspect(WorkQuery(work_id=work.id))

    assert replay == checkpointed
    assert checkpointed.status == "running"
    assert checkpointed.version == 4
    assert checkpointed.latest_verified_checkpoint_id == "checkpoint_0001"
    assert len(snapshot.checkpoints) == 1
    assert snapshot.checkpoints[0].artifact_ref == "workspace:dispatch-slot-1"
    assert snapshot.checkpoints[0].artifact_sha256 == "a" * 64
    assert snapshot.checkpoints[0].verification_ref == "pytest:test_work_coordinator"


def test_acquire_rejects_non_positive_lease_seconds() -> None:
    coordinator = build_coordinator()

    with pytest.raises(ValueError, match="lease_seconds must be positive"):
        coordinator.acquire(
            WorkerOffer(
                worker_id="worker",
                capabilities=frozenset(),
                attestations=frozenset(),
                lease_seconds=0,
            )
        )


def test_acquire_rejects_empty_claim_token_from_factory() -> None:
    coordinator = WorkCoordinator(
        InMemoryCoordinationStore(),
        clock=lambda: FIXED_NOW,
        id_factory=lambda: "work",
        token_factory=lambda: "",
    )

    with pytest.raises(ValueError, match="claim token is required"):
        coordinator.acquire(
            WorkerOffer(
                worker_id="worker",
                capabilities=frozenset(),
                attestations=frozenset(),
                lease_seconds=300,
            )
        )


def test_cooperative_release_resumes_from_the_latest_verified_checkpoint() -> None:
    coordinator = build_coordinator()
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:code:preempt",
            source="user",
            kind="platform_ops",
            title="可安全讓出資源的工作",
            priority=2,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:code:preempt",
        )
    )
    offer = WorkerOffer(
        worker_id="codex-worker",
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
            report_id="checkpoint_0001",
            work_id=work.id,
            lease_token=first_lease.token,
            expected_version=running.version,
            artifact_ref="workspace:dispatch-slot-1",
            artifact_sha256="b" * 64,
            verification_ref="pytest:preempt-ready",
        )
    )

    released = coordinator.record(
        Released(
            work_id=work.id,
            lease_token=first_lease.token,
            expected_version=checkpointed.version,
            reason="preempted_by_user_work",
        )
    )
    resumed = coordinator.acquire(offer)

    assert released.status == "pending"
    assert released.version == 5
    assert released.claimed_by is None
    assert released.last_release_reason == "preempted_by_user_work"
    assert released.latest_verified_checkpoint_id == "checkpoint_0001"
    assert resumed is not None
    assert resumed.token == "claim_0002"
    assert resumed.resume_checkpoint_id == "checkpoint_0001"
    assert resumed.work_item.version == 6


def test_completion_report_is_terminal_and_idempotent() -> None:
    coordinator = build_coordinator()
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:code:complete",
            source="user",
            kind="platform_ops",
            title="完成 shadow 工作",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:code:complete",
        )
    )
    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="codex-worker",
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
        report_id="completion_0001",
        work_id=work.id,
        lease_token=lease.token,
        expected_version=running.version,
        result_ref="changeset:shadow-work-coordinator",
        summary="interface contract passed",
    )

    completed = coordinator.record(report)
    replay = coordinator.record(report)
    snapshot = coordinator.inspect(WorkQuery(work_id=work.id))

    assert replay == completed
    assert completed.status == "succeeded"
    assert completed.version == 4
    assert completed.claimed_by is None
    assert completed.result_ref == "changeset:shadow-work-coordinator"
    assert len(snapshot.receipts) == 1
    assert snapshot.receipts[0].id == "completion_0001"
    assert snapshot.receipts[0].outcome == "succeeded"


def test_full_work_lifecycle_is_auditable_through_inspect() -> None:
    coordinator = build_coordinator()
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:code:audit",
            source="user",
            kind="platform_ops",
            title="保留完整生命週期稽核",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:code:audit",
        )
    )
    offer = WorkerOffer(
        worker_id="codex-worker",
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
            report_id="checkpoint_0001",
            work_id=work.id,
            lease_token=first_lease.token,
            expected_version=running.version,
            artifact_ref="workspace:audit",
            artifact_sha256="c" * 64,
            verification_ref="pytest:audit",
        )
    )
    coordinator.record(
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
    coordinator.record(
        Completed(
            report_id="completion_audit",
            work_id=work.id,
            lease_token=resumed_lease.token,
            expected_version=resumed.version,
            result_ref="changeset:audit",
            summary="audit trail complete",
        )
    )

    snapshot = coordinator.inspect(WorkQuery(work_id=work.id))

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
    assert tuple(event.version for event in snapshot.events) == tuple(range(1, 9))
    assert len(snapshot.receipts) == 1


def test_expired_claim_is_reacquired_and_the_stale_lease_cannot_mutate() -> None:
    now = [FIXED_NOW]
    claim_tokens = iter(("claim_old", "claim_new"))
    coordinator = WorkCoordinator(
        InMemoryCoordinationStore(),
        clock=lambda: now[0],
        id_factory=lambda: "work_expiring",
        token_factory=lambda: next(claim_tokens),
        checkpoint_id_factory=lambda: "checkpoint_unused",
    )
    work = coordinator.submit(
        WorkRequest(
            idempotency_key="owner:code:expiring",
            source="user",
            kind="platform_ops",
            title="可回收過期 claim",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref="owner:code:expiring",
        )
    )
    offer = WorkerOffer(
        worker_id="worker-old",
        capabilities=frozenset({"code"}),
        attestations=frozenset(),
        lease_seconds=1,
    )
    stale_lease = coordinator.acquire(offer)
    assert stale_lease is not None

    now[0] = FIXED_NOW + timedelta(seconds=2)
    new_lease = coordinator.acquire(
        WorkerOffer(
            worker_id="worker-new",
            capabilities=frozenset({"code"}),
            attestations=frozenset(),
            lease_seconds=300,
        )
    )

    assert new_lease is not None
    assert new_lease.token == "claim_new"
    assert new_lease.work_item.claimed_by == "worker-new"
    assert new_lease.work_item.version == 3
    with pytest.raises(ClaimLost):
        coordinator.record(
            Started(
                work_id=work.id,
                lease_token=stale_lease.token,
                expected_version=stale_lease.work_item.version,
            )
        )


@pytest.mark.parametrize(
    "mutation",
    ("start", "checkpoint", "release", "complete"),
)
def test_expired_lease_cannot_mutate_before_another_worker_reacquires(
    mutation: str,
) -> None:
    now = [FIXED_NOW]
    coordinator = WorkCoordinator(
        InMemoryCoordinationStore(),
        clock=lambda: now[0],
        id_factory=lambda: "work_expired",
        token_factory=lambda: "claim_expired",
        checkpoint_id_factory=lambda: "checkpoint_expired",
    )
    work = coordinator.submit(
        WorkRequest(
            idempotency_key=f"owner:code:expired:{mutation}",
            source="user",
            kind="platform_ops",
            title="過期 lease 不得再寫入",
            priority=1,
            required_capabilities=frozenset({"code"}),
            required_attestations=frozenset(),
            risk="safe",
            approval="auto",
            payload_ref=f"owner:code:expired:{mutation}",
        )
    )
    lease = coordinator.acquire(
        WorkerOffer(
            worker_id="worker-expiring",
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
                report_id="checkpoint_expired",
                work_id=work.id,
                lease_token=lease.token,
                expected_version=running.version,
                artifact_ref="workspace:expired",
                artifact_sha256="e" * 64,
                verification_ref="pytest:expired",
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
                report_id="completion_expired",
                work_id=work.id,
                lease_token=lease.token,
                expected_version=running.version,
                result_ref="changeset:expired",
                summary="must not complete",
            )

    now[0] = FIXED_NOW + timedelta(seconds=2)
    with pytest.raises(ClaimLost):
        coordinator.record(report)
