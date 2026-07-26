from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from volpred.ops.schedule_materialization import (
    ExecutionResult,
    FileReceiptStore,
    MemoryReceiptStore,
    ScheduleConfigurationError,
    ScheduleJob,
    ScheduleMaterializer,
    SchedulePolicy,
    due_fires,
    load_schedule_jobs,
    load_schedule_policy,
)

UTC = timezone.utc


def job(**overrides) -> ScheduleJob:
    values = {
        "id": "hourly",
        "cron": "0 * * * *",
        "command": "/bin/true",
        "timezone": "Asia/Taipei",
        "catch_up": "latest_only",
        "grace_seconds": 120,
        "max_catchup_seconds": 86_400,
        "max_attempts": 3,
        "retry_delay_seconds": 60,
        "lease_seconds": 300,
        "timeout_seconds": 30,
    }
    values.update(overrides)
    return ScheduleJob(**values)


def success(at: datetime) -> ExecutionResult:
    stamp = at.isoformat().replace("+00:00", "Z")
    return ExecutionResult(
        state="succeeded",
        exit_code=0,
        started_at=stamp,
        finished_at=stamp,
        duration_seconds=0.0,
    )


def test_fire_identity_is_stable_and_utc() -> None:
    now = datetime(2026, 7, 26, 9, 0, 30, tzinfo=UTC)
    first = due_fires(job(), generation="g1", now=now)
    second = due_fires(job(), generation="g1", now=now + timedelta(seconds=20))

    assert first == second
    assert first[0].scheduled_for == "2026-07-26T09:00:00Z"
    assert first[0].fire_key.startswith("g1:hourly:")


def test_skip_policy_does_not_replay_old_fire() -> None:
    now = datetime(2026, 7, 26, 9, 10, tzinfo=UTC)
    assert due_fires(
        job(catch_up="skip", grace_seconds=120),
        generation="g1",
        now=now,
    ) == []


def test_replay_all_is_bounded_and_ordered() -> None:
    now = datetime(2026, 7, 26, 9, 5, tzinfo=UTC)
    fires = due_fires(
        job(catch_up="replay_all", max_catchup_seconds=7_200),
        generation="g1",
        now=now,
    )
    assert [fire.scheduled_for for fire in fires] == [
        "2026-07-26T08:00:00Z",
        "2026-07-26T09:00:00Z",
    ]


def test_activation_boundary_prevents_pre_cutover_replay() -> None:
    now = datetime(2026, 7, 26, 9, 5, tzinfo=UTC)
    fires = due_fires(
        job(catch_up="replay_all", max_catchup_seconds=86_400),
        generation="g1",
        now=now,
        activated_at=datetime(2026, 7, 26, 8, 30, tzinfo=UTC),
    )
    assert [fire.scheduled_for for fire in fires] == ["2026-07-26T09:00:00Z"]


def test_shadow_never_invokes_executor() -> None:
    calls: list[str] = []
    receipts = MemoryReceiptStore()
    materializer = ScheduleMaterializer(
        policy=SchedulePolicy(
            generation="g1",
            mode="shadow",
            timezone="Asia/Taipei",
            shadow_grace_seconds=120,
        ),
        jobs=[job()],
        receipts=receipts,
        repo_root=Path("."),
        executor=lambda _job, fire: calls.append(fire.fire_key),  # type: ignore[arg-type,return-value]
        legacy_last_success={"hourly": "2026-07-26T09:00:05Z"},
    )
    report = materializer.tick(now=datetime(2026, 7, 26, 9, 0, 30, tzinfo=UTC))

    assert calls == []
    assert len(report["shadow"]) == 1
    observed = next(iter(receipts.payload["shadow"].values()))
    assert observed["legacy_observed"] is True


def test_canary_executes_only_explicit_active_job() -> None:
    calls: list[str] = []
    now = datetime(2026, 7, 26, 9, 0, 30, tzinfo=UTC)

    def execute(_job: ScheduleJob, fire) -> ExecutionResult:
        calls.append(fire.job_id)
        return success(now)

    materializer = ScheduleMaterializer(
        policy=SchedulePolicy(
            generation="g1",
            mode="canary",
            timezone="Asia/Taipei",
            active_jobs={"active": now - timedelta(minutes=1)},
        ),
        jobs=[job(id="active"), job(id="legacy")],
        receipts=MemoryReceiptStore(),
        repo_root=Path("."),
        executor=execute,
    )
    report = materializer.tick(now=now)

    assert calls == ["active"]
    assert [item["job_id"] for item in report["shadow"]] == ["legacy"]
    assert report["completed"][0]["state"] == "succeeded"


def test_success_receipt_prevents_duplicate_execution() -> None:
    calls: list[str] = []
    now = datetime(2026, 7, 26, 9, 0, 30, tzinfo=UTC)
    receipts = MemoryReceiptStore()

    def execute(_job: ScheduleJob, fire) -> ExecutionResult:
        calls.append(fire.fire_key)
        return success(now)

    materializer = ScheduleMaterializer(
        policy=SchedulePolicy(
            generation="g1",
            mode="active",
            timezone="Asia/Taipei",
            active_since=now - timedelta(minutes=1),
        ),
        jobs=[job()],
        receipts=receipts,
        repo_root=Path("."),
        executor=execute,
    )
    materializer.tick(now=now)
    second = materializer.tick(now=now + timedelta(seconds=20))

    assert len(calls) == 1
    assert second["claims"][0]["reason"] == "succeeded"


def test_lease_fences_concurrent_claim_and_allows_expired_retry() -> None:
    store = MemoryReceiptStore()
    now = datetime(2026, 7, 26, 9, 0, 30, tzinfo=UTC)
    fire = due_fires(job(), generation="g1", now=now)[0]
    first = store.claim(
        fire,
        actor="one",
        now=now,
        lease_seconds=60,
        max_attempts=3,
        retry_delay_seconds=10,
    )
    held = store.claim(
        fire,
        actor="two",
        now=now + timedelta(seconds=30),
        lease_seconds=60,
        max_attempts=3,
        retry_delay_seconds=10,
    )
    retried = store.claim(
        fire,
        actor="two",
        now=now + timedelta(seconds=61),
        lease_seconds=60,
        max_attempts=3,
        retry_delay_seconds=10,
    )

    assert first.acquired is True
    assert held.reason == "lease_held"
    assert retried.acquired is True
    assert retried.attempt == 2
    assert retried.fence_token != first.fence_token


def test_failed_attempt_waits_then_retries_and_exhausts() -> None:
    store = MemoryReceiptStore()
    now = datetime(2026, 7, 26, 9, 0, 30, tzinfo=UTC)
    fire = due_fires(job(max_attempts=2), generation="g1", now=now)[0]
    first = store.claim(
        fire,
        actor="one",
        now=now,
        lease_seconds=60,
        max_attempts=2,
        retry_delay_seconds=30,
    )
    store.mark_running(first, now=now)
    failed = ExecutionResult(
        state="failed",
        exit_code=1,
        started_at="2026-07-26T09:00:30Z",
        finished_at="2026-07-26T09:00:35Z",
        duration_seconds=5,
    )
    store.settle(first, failed, max_attempts=2, retry_delay_seconds=30)

    early = store.claim(
        fire,
        actor="two",
        now=now + timedelta(seconds=20),
        lease_seconds=60,
        max_attempts=2,
        retry_delay_seconds=30,
    )
    second = store.claim(
        fire,
        actor="two",
        now=now + timedelta(seconds=40),
        lease_seconds=60,
        max_attempts=2,
        retry_delay_seconds=30,
    )
    store.mark_running(second, now=now + timedelta(seconds=40))
    store.settle(second, failed, max_attempts=2, retry_delay_seconds=30)

    assert early.reason == "retry_not_due"
    assert second.attempt == 2
    assert store.status(fire.fire_key)["state"] == "retry_exhausted"


def test_file_store_has_same_claim_contract(tmp_path: Path) -> None:
    store = FileReceiptStore(tmp_path / "receipts.json")
    now = datetime(2026, 7, 26, 9, 0, 30, tzinfo=UTC)
    fire = due_fires(job(), generation="g1", now=now)[0]
    claim = store.claim(
        fire,
        actor="test",
        now=now,
        lease_seconds=60,
        max_attempts=3,
        retry_delay_seconds=10,
    )
    store.mark_running(claim, now=now)
    store.settle(claim, success(now), max_attempts=3, retry_delay_seconds=10)

    assert store.status(fire.fire_key)["state"] == "succeeded"
    assert not list(tmp_path.glob("*.tmp"))


def test_loader_rejects_unknown_canary_job() -> None:
    config = {
        "metadata": {"timezone": "Asia/Taipei"},
        "schedule_materialization": {
            "generation": "g1",
            "mode": "canary",
            "active_jobs": {"missing": "2026-07-26T09:00:00Z"},
        },
        "system_crontab": {
            "items": [
                {
                    "id": "present",
                    "cron": "0 * * * *",
                    "wrapper_script": "/bin/true",
                }
            ]
        },
    }
    policy = load_schedule_policy(config)
    jobs = load_schedule_jobs(config)

    with pytest.raises(ScheduleConfigurationError, match="active_jobs not found"):
        ScheduleMaterializer(
            policy=policy,
            jobs=jobs,
            receipts=MemoryReceiptStore(),
            repo_root=Path("."),
        )


def test_active_mode_requires_explicit_activation_boundary() -> None:
    with pytest.raises(ScheduleConfigurationError, match="active_since"):
        SchedulePolicy(
            generation="g1",
            mode="active",
            timezone="Asia/Taipei",
        )


def test_dst_fallback_produces_distinct_utc_fire_keys() -> None:
    dst_job = job(
        cron="30 1 * * *",
        timezone="America/New_York",
        catch_up="replay_all",
        max_catchup_seconds=10_800,
    )
    fires = due_fires(
        dst_job,
        generation="g1",
        now=datetime(2026, 11, 1, 7, 0, tzinfo=UTC),
    )
    utc_slots = [fire.scheduled_for for fire in fires]

    assert len(fires) == 2
    assert len(set(fire.fire_key for fire in fires)) == len(fires)
    assert utc_slots == ["2026-11-01T05:30:00Z", "2026-11-01T06:30:00Z"]
