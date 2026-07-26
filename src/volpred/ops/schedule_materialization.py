"""Single-owner schedule materialization and execution receipts.

This module is the execution boundary for recurring business jobs.  The OS owns
only one clock (the operations-core daemon); this module owns every decision
after that clock ticks:

* derive immutable fire identities from the canonical schedule;
* decide shadow versus active ownership;
* atomically claim one attempt with a fenced lease;
* execute the configured wrapper with the fire identity in its environment;
* settle a durable terminal receipt.

The public surface is intentionally small: load a policy, construct a
``ScheduleMaterializer``, and call ``tick``.  Tests use ``MemoryReceiptStore``;
production uses ``FileReceiptStore``.  The policy and receipt adapters are the
only seams.

Delivery is at-least-once.  A host can die after a wrapper performs an external
effect but before the receipt is settled, so callers must use
``VOLPRED_SCHEDULE_FIRE_KEY`` as their idempotency key when an effect API
supports one.  The module never claims impossible exactly-once semantics.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import socket
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol
from zoneinfo import ZoneInfo

from croniter import croniter

from volpred.canonical_write import guard_canonical_write

UTC = timezone.utc
TERMINAL_STATES = frozenset({"succeeded", "retry_exhausted", "disabled"})
RETRYABLE_STATES = frozenset({"failed", "timed_out"})
LIVE_STATES = frozenset({"claimed", "running"})
VALID_MODES = frozenset({"shadow", "canary", "active", "disabled"})
VALID_CATCH_UP = frozenset({"skip", "latest_only", "replay_all"})


class ScheduleConfigurationError(ValueError):
    """The canonical schedule cannot produce one unambiguous owner."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime, *, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _iso(value: datetime) -> str:
    return _aware(value, name="datetime").astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return _aware(parsed, name="timestamp")


@dataclass(frozen=True)
class ScheduleJob:
    id: str
    cron: str
    command: str
    timezone: str
    catch_up: str = "latest_only"
    grace_seconds: int = 120
    max_catchup_seconds: int = 86_400
    max_attempts: int = 3
    retry_delay_seconds: int = 300
    lease_seconds: int = 3_600
    timeout_seconds: int = 3_000
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ScheduleConfigurationError("schedule job id is required")
        if not self.command.strip():
            raise ScheduleConfigurationError(f"{self.id}: executable command is required")
        if self.catch_up not in VALID_CATCH_UP:
            raise ScheduleConfigurationError(
                f"{self.id}: catch_up must be one of {sorted(VALID_CATCH_UP)}"
            )
        if self.max_attempts < 1:
            raise ScheduleConfigurationError(f"{self.id}: max_attempts must be >= 1")
        if min(
            self.grace_seconds,
            self.max_catchup_seconds,
            self.retry_delay_seconds,
            self.lease_seconds,
            self.timeout_seconds,
        ) < 0:
            raise ScheduleConfigurationError(f"{self.id}: timing values cannot be negative")
        try:
            ZoneInfo(self.timezone)
            croniter(self.cron, datetime.now(ZoneInfo(self.timezone)))
        except Exception as exc:
            raise ScheduleConfigurationError(f"{self.id}: invalid schedule: {exc}") from exc


@dataclass(frozen=True)
class SchedulePolicy:
    generation: str
    mode: str
    timezone: str
    active_jobs: Mapping[str, datetime] = field(default_factory=dict)
    active_since: datetime | None = None
    max_parallel: int = 4
    shadow_grace_seconds: int = 120

    def __post_init__(self) -> None:
        if not self.generation.strip():
            raise ScheduleConfigurationError("schedule generation is required")
        if self.mode not in VALID_MODES:
            raise ScheduleConfigurationError(
                f"schedule mode must be one of {sorted(VALID_MODES)}"
            )
        if self.max_parallel < 1:
            raise ScheduleConfigurationError("max_parallel must be >= 1")
        ZoneInfo(self.timezone)
        if self.active_since is not None:
            _aware(self.active_since, name="active_since")
        if self.mode == "active" and self.active_since is None:
            raise ScheduleConfigurationError(
                "active mode requires active_since to prevent pre-cutover replay"
            )
        for job_id, activated_at in self.active_jobs.items():
            if not job_id:
                raise ScheduleConfigurationError("active_jobs contains an empty id")
            _aware(activated_at, name=f"active_jobs.{job_id}")

    def owner_for(self, job_id: str) -> str:
        if self.mode in {"disabled", "shadow"}:
            return "legacy"
        if self.mode == "active":
            return "operations_core"
        return "operations_core" if job_id in self.active_jobs else "legacy"

    def activation_for(self, job_id: str) -> datetime | None:
        if self.owner_for(job_id) != "operations_core":
            return None
        return self.active_jobs.get(job_id) or self.active_since


@dataclass(frozen=True)
class ScheduleFire:
    fire_key: str
    generation: str
    job_id: str
    scheduled_for: str
    scheduled_local: str


@dataclass(frozen=True)
class Claim:
    acquired: bool
    reason: str
    fire: ScheduleFire
    attempt: int = 0
    fence_token: str = ""


@dataclass(frozen=True)
class ExecutionResult:
    state: str
    exit_code: int | None
    started_at: str
    finished_at: str
    duration_seconds: float
    stdout_tail: str = ""
    stderr_tail: str = ""
    error: str = ""


class ReceiptStore(Protocol):
    def status(self, fire_key: str) -> Mapping[str, Any] | None: ...

    def claim(
        self,
        fire: ScheduleFire,
        *,
        actor: str,
        now: datetime,
        lease_seconds: int,
        max_attempts: int,
        retry_delay_seconds: int,
    ) -> Claim: ...

    def mark_running(self, claim: Claim, *, now: datetime) -> None: ...

    def settle(
        self,
        claim: Claim,
        result: ExecutionResult,
        *,
        max_attempts: int,
        retry_delay_seconds: int,
    ) -> None: ...

    def observe_shadow(
        self,
        fire: ScheduleFire,
        *,
        now: datetime,
        legacy_last_success: str | None,
    ) -> None: ...


def _new_payload() -> dict[str, Any]:
    return {"schema": 1, "fires": {}, "shadow": {}}


def _claim_in_payload(
    payload: dict[str, Any],
    fire: ScheduleFire,
    *,
    actor: str,
    now: datetime,
    lease_seconds: int,
    max_attempts: int,
    retry_delay_seconds: int,
) -> Claim:
    fires = payload.setdefault("fires", {})
    current = fires.get(fire.fire_key)
    now_iso = _iso(now)
    if isinstance(current, dict):
        state = str(current.get("state") or "")
        attempt = int(current.get("attempt") or 0)
        if state in TERMINAL_STATES or state == "succeeded":
            return Claim(False, state or "terminal", fire, attempt=attempt)
        if state in LIVE_STATES:
            lease_until = _parse_iso(current.get("lease_until"))
            if lease_until is not None and lease_until > now:
                return Claim(False, "lease_held", fire, attempt=attempt)
        if state in RETRYABLE_STATES:
            retry_at = _parse_iso(current.get("retry_at"))
            if retry_at is not None and retry_at > now:
                return Claim(False, "retry_not_due", fire, attempt=attempt)
        if attempt >= max_attempts:
            current["state"] = "retry_exhausted"
            current["finished_at"] = current.get("finished_at") or now_iso
            return Claim(False, "retry_exhausted", fire, attempt=attempt)
    else:
        attempt = 0

    attempt += 1
    token_seed = f"{fire.fire_key}:{attempt}:{actor}:{now_iso}:{os.getpid()}"
    fence_token = hashlib.sha256(token_seed.encode("utf-8")).hexdigest()
    fires[fire.fire_key] = {
        **asdict(fire),
        "state": "claimed",
        "attempt": attempt,
        "actor": actor,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "fence_token": fence_token,
        "claimed_at": now_iso,
        "started_at": None,
        "finished_at": None,
        "lease_until": _iso(now + timedelta(seconds=lease_seconds)),
        "retry_at": None,
        "exit_code": None,
        "duration_seconds": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "error": "",
        "retry_policy": {
            "max_attempts": max_attempts,
            "retry_delay_seconds": retry_delay_seconds,
        },
    }
    return Claim(True, "acquired", fire, attempt=attempt, fence_token=fence_token)


def _mutate_claimed_record(
    payload: dict[str, Any],
    claim: Claim,
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    current = payload.setdefault("fires", {}).get(claim.fire.fire_key)
    if not isinstance(current, dict):
        raise RuntimeError(f"missing receipt for claimed fire {claim.fire.fire_key}")
    if current.get("fence_token") != claim.fence_token:
        raise RuntimeError(f"stale fence token for fire {claim.fire.fire_key}")
    mutation(current)


class MemoryReceiptStore:
    """Deterministic receipt adapter for interface tests."""

    def __init__(self) -> None:
        self.payload = _new_payload()

    def status(self, fire_key: str) -> Mapping[str, Any] | None:
        current = self.payload["fires"].get(fire_key)
        return dict(current) if isinstance(current, dict) else None

    def claim(
        self,
        fire: ScheduleFire,
        *,
        actor: str,
        now: datetime,
        lease_seconds: int,
        max_attempts: int,
        retry_delay_seconds: int,
    ) -> Claim:
        return _claim_in_payload(
            self.payload,
            fire,
            actor=actor,
            now=now,
            lease_seconds=lease_seconds,
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
        )

    def mark_running(self, claim: Claim, *, now: datetime) -> None:
        _mutate_claimed_record(
            self.payload,
            claim,
            lambda record: record.update(state="running", started_at=_iso(now)),
        )

    def settle(
        self,
        claim: Claim,
        result: ExecutionResult,
        *,
        max_attempts: int,
        retry_delay_seconds: int,
    ) -> None:
        def mutation(record: dict[str, Any]) -> None:
            record.update(asdict(result))
            if result.state in RETRYABLE_STATES and claim.attempt >= max_attempts:
                record["state"] = "retry_exhausted"
            elif result.state in RETRYABLE_STATES:
                record["retry_at"] = _iso(
                    _parse_iso(result.finished_at)
                    + timedelta(seconds=retry_delay_seconds)  # type: ignore[operator]
                )

        _mutate_claimed_record(self.payload, claim, mutation)

    def observe_shadow(
        self,
        fire: ScheduleFire,
        *,
        now: datetime,
        legacy_last_success: str | None,
    ) -> None:
        shadow = self.payload["shadow"].setdefault(
            fire.fire_key,
            {
                **asdict(fire),
                "first_seen_at": _iso(now),
                "last_seen_at": _iso(now),
                "observations": 0,
                "legacy_last_success": None,
                "legacy_observed": False,
            },
        )
        shadow["last_seen_at"] = _iso(now)
        shadow["observations"] = int(shadow.get("observations") or 0) + 1
        shadow["legacy_last_success"] = legacy_last_success
        marker = _parse_iso(legacy_last_success)
        scheduled = _parse_iso(fire.scheduled_for)
        shadow["legacy_observed"] = bool(
            marker is not None and scheduled is not None and marker >= scheduled
        )


class FileReceiptStore:
    """Atomic JSON receipt adapter shared by every local scheduler process."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_name(f"{self.path.name}.lock")

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return _new_payload()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("fires"), dict):
            raise RuntimeError(f"invalid schedule receipt ledger: {self.path}")
        payload.setdefault("shadow", {})
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        guard_canonical_write(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=f".{self.path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def _mutate(self, callback: Callable[[dict[str, Any]], Any]) -> Any:
        guard_canonical_write(self.path)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                payload = self._read()
                result = callback(payload)
                self._write(payload)
                return result
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def status(self, fire_key: str) -> Mapping[str, Any] | None:
        # Writers publish with os.replace, so an unlocked read sees either the
        # complete old file or the complete new file.  Avoid creating a lock
        # sentinel for what is semantically a read-only operation.
        current = self._read()["fires"].get(fire_key)
        return dict(current) if isinstance(current, dict) else None

    def claim(
        self,
        fire: ScheduleFire,
        *,
        actor: str,
        now: datetime,
        lease_seconds: int,
        max_attempts: int,
        retry_delay_seconds: int,
    ) -> Claim:
        return self._mutate(
            lambda payload: _claim_in_payload(
                payload,
                fire,
                actor=actor,
                now=now,
                lease_seconds=lease_seconds,
                max_attempts=max_attempts,
                retry_delay_seconds=retry_delay_seconds,
            )
        )

    def mark_running(self, claim: Claim, *, now: datetime) -> None:
        self._mutate(
            lambda payload: _mutate_claimed_record(
                payload,
                claim,
                lambda record: record.update(state="running", started_at=_iso(now)),
            )
        )

    def settle(
        self,
        claim: Claim,
        result: ExecutionResult,
        *,
        max_attempts: int,
        retry_delay_seconds: int,
    ) -> None:
        def settle_payload(payload: dict[str, Any]) -> None:
            def mutation(record: dict[str, Any]) -> None:
                record.update(asdict(result))
                if result.state in RETRYABLE_STATES and claim.attempt >= max_attempts:
                    record["state"] = "retry_exhausted"
                elif result.state in RETRYABLE_STATES:
                    finished = _parse_iso(result.finished_at)
                    if finished is None:
                        raise RuntimeError("execution result has no finished_at")
                    record["retry_at"] = _iso(
                        finished + timedelta(seconds=retry_delay_seconds)
                    )

            _mutate_claimed_record(payload, claim, mutation)

        self._mutate(settle_payload)

    def observe_shadow(
        self,
        fire: ScheduleFire,
        *,
        now: datetime,
        legacy_last_success: str | None,
    ) -> None:
        def observe(payload: dict[str, Any]) -> None:
            shadow = payload["shadow"].setdefault(
                fire.fire_key,
                {
                    **asdict(fire),
                    "first_seen_at": _iso(now),
                    "last_seen_at": _iso(now),
                    "observations": 0,
                    "legacy_last_success": None,
                    "legacy_observed": False,
                },
            )
            shadow["last_seen_at"] = _iso(now)
            shadow["observations"] = int(shadow.get("observations") or 0) + 1
            shadow["legacy_last_success"] = legacy_last_success
            marker = _parse_iso(legacy_last_success)
            scheduled = _parse_iso(fire.scheduled_for)
            shadow["legacy_observed"] = bool(
                marker is not None and scheduled is not None and marker >= scheduled
            )

        self._mutate(observe)


def _fire(job: ScheduleJob, generation: str, scheduled: datetime) -> ScheduleFire:
    scheduled = _aware(scheduled, name="scheduled")
    scheduled_utc = _iso(scheduled)
    digest = hashlib.sha256(
        f"{generation}\0{job.id}\0{scheduled_utc}".encode("utf-8")
    ).hexdigest()[:24]
    return ScheduleFire(
        fire_key=f"{generation}:{job.id}:{digest}",
        generation=generation,
        job_id=job.id,
        scheduled_for=scheduled_utc,
        scheduled_local=scheduled.isoformat(),
    )


def due_fires(
    job: ScheduleJob,
    *,
    generation: str,
    now: datetime,
    activated_at: datetime | None = None,
    shadow: bool = False,
    shadow_grace_seconds: int = 120,
) -> list[ScheduleFire]:
    """Return the bounded fire set for one tick, newest last."""
    now = _aware(now, name="now")
    zone = ZoneInfo(job.timezone)
    local_now = now.astimezone(zone)
    iterator = croniter(job.cron, local_now + timedelta(seconds=1))
    newest = iterator.get_prev(datetime)
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=zone)

    grace = shadow_grace_seconds if shadow else job.grace_seconds
    if shadow or job.catch_up == "skip":
        if (local_now - newest).total_seconds() > grace:
            return []
        slots = [newest]
    else:
        cutoff = local_now - timedelta(seconds=job.max_catchup_seconds)
        if activated_at is not None:
            cutoff = max(cutoff, activated_at.astimezone(zone))
        slots = []
        cursor = local_now + timedelta(seconds=1)
        while True:
            slot = croniter(job.cron, cursor).get_prev(datetime)
            if slot.tzinfo is None:
                slot = slot.replace(tzinfo=zone)
            if slot < cutoff:
                break
            slots.append(slot)
            if job.catch_up == "latest_only":
                break
            if len(slots) >= 256:
                raise RuntimeError(f"{job.id}: replay_all exceeded 256 fires in one tick")
            cursor = slot
        slots.reverse()

    if activated_at is not None:
        slots = [slot for slot in slots if slot.astimezone(UTC) >= activated_at.astimezone(UTC)]
    return [_fire(job, generation, slot) for slot in slots]


def _tail(value: str, limit: int = 4_000) -> str:
    return value[-limit:]


def execute_wrapper(
    job: ScheduleJob,
    fire: ScheduleFire,
    *,
    repo_root: Path,
    now: Callable[[], datetime] = _utc_now,
) -> ExecutionResult:
    started = now()
    env = os.environ.copy()
    env.update(
        {
            "VOLPRED_SCHEDULE_FIRE_KEY": fire.fire_key,
            "VOLPRED_SCHEDULE_GENERATION": fire.generation,
            "VOLPRED_SCHEDULE_JOB_ID": fire.job_id,
            "VOLPRED_SCHEDULED_FOR": fire.scheduled_for,
            "VOLPRED_SCHEDULE_OWNER": "operations_core",
        }
    )
    try:
        completed = subprocess.run(
            [job.command],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=job.timeout_seconds,
            check=False,
        )
        finished = now()
        return ExecutionResult(
            state="succeeded" if completed.returncode == 0 else "failed",
            exit_code=completed.returncode,
            started_at=_iso(started),
            finished_at=_iso(finished),
            duration_seconds=max(0.0, (finished - started).total_seconds()),
            stdout_tail=_tail(completed.stdout or ""),
            stderr_tail=_tail(completed.stderr or ""),
        )
    except subprocess.TimeoutExpired as exc:
        finished = now()
        return ExecutionResult(
            state="timed_out",
            exit_code=None,
            started_at=_iso(started),
            finished_at=_iso(finished),
            duration_seconds=max(0.0, (finished - started).total_seconds()),
            stdout_tail=_tail(str(exc.stdout or "")),
            stderr_tail=_tail(str(exc.stderr or "")),
            error=f"timeout after {job.timeout_seconds}s",
        )
    except OSError as exc:
        finished = now()
        return ExecutionResult(
            state="failed",
            exit_code=None,
            started_at=_iso(started),
            finished_at=_iso(finished),
            duration_seconds=max(0.0, (finished - started).total_seconds()),
            error=f"{type(exc).__name__}: {exc}",
        )


class ScheduleMaterializer:
    """Plan, claim, execute, and settle one scheduler tick."""

    def __init__(
        self,
        *,
        policy: SchedulePolicy,
        jobs: Iterable[ScheduleJob],
        receipts: ReceiptStore,
        repo_root: Path,
        actor: str = "operations-core-scheduler",
        executor: Callable[[ScheduleJob, ScheduleFire], ExecutionResult] | None = None,
        legacy_last_success: Mapping[str, str] | None = None,
    ) -> None:
        self.policy = policy
        self.jobs = list(jobs)
        self.receipts = receipts
        self.repo_root = Path(repo_root)
        self.actor = actor
        self.legacy_last_success = dict(legacy_last_success or {})
        self.executor = executor or (
            lambda job, fire: execute_wrapper(job, fire, repo_root=self.repo_root)
        )
        ids = [job.id for job in self.jobs]
        duplicates = sorted({job_id for job_id in ids if ids.count(job_id) > 1})
        if duplicates:
            raise ScheduleConfigurationError(
                f"duplicate executable schedule ids: {duplicates}"
            )
        unknown = sorted(set(self.policy.active_jobs) - set(ids))
        if unknown:
            raise ScheduleConfigurationError(f"active_jobs not found in schedule: {unknown}")

    def tick(self, *, now: datetime | None = None) -> dict[str, Any]:
        tick_now = _aware(now or _utc_now(), name="now")
        report: dict[str, Any] = {
            "schema": 1,
            "generated_at": _iso(tick_now),
            "generation": self.policy.generation,
            "mode": self.policy.mode,
            "jobs_seen": len(self.jobs),
            "shadow": [],
            "claims": [],
            "completed": [],
            "blocked": [],
        }
        pending: list[tuple[ScheduleJob, Claim]] = []

        for job in self.jobs:
            if not job.enabled:
                continue
            owner = self.policy.owner_for(job.id)
            shadow = owner != "operations_core"
            fires = due_fires(
                job,
                generation=self.policy.generation,
                now=tick_now,
                activated_at=self.policy.activation_for(job.id),
                shadow=shadow,
                shadow_grace_seconds=self.policy.shadow_grace_seconds,
            )
            for fire in fires:
                if shadow:
                    marker = self.legacy_last_success.get(job.id)
                    self.receipts.observe_shadow(
                        fire,
                        now=tick_now,
                        legacy_last_success=marker,
                    )
                    report["shadow"].append(
                        {
                            **asdict(fire),
                            "owner": "legacy",
                            "legacy_last_success": marker,
                        }
                    )
                    continue
                claim = self.receipts.claim(
                    fire,
                    actor=self.actor,
                    now=tick_now,
                    lease_seconds=job.lease_seconds,
                    max_attempts=job.max_attempts,
                    retry_delay_seconds=job.retry_delay_seconds,
                )
                report["claims"].append(
                    {
                        "fire_key": fire.fire_key,
                        "job_id": job.id,
                        "acquired": claim.acquired,
                        "reason": claim.reason,
                        "attempt": claim.attempt,
                    }
                )
                if claim.acquired:
                    self.receipts.mark_running(claim, now=tick_now)
                    pending.append((job, claim))

        if not pending:
            return report

        with ThreadPoolExecutor(max_workers=self.policy.max_parallel) as pool:
            future_map = {
                pool.submit(self.executor, job, claim.fire): (job, claim)
                for job, claim in pending
            }
            for future in as_completed(future_map):
                job, claim = future_map[future]
                try:
                    result = future.result()
                except Exception as exc:  # executor failures must still settle the lease
                    failed_at = _utc_now()
                    result = ExecutionResult(
                        state="failed",
                        exit_code=None,
                        started_at=_iso(tick_now),
                        finished_at=_iso(failed_at),
                        duration_seconds=max(0.0, (failed_at - tick_now).total_seconds()),
                        error=f"{type(exc).__name__}: {exc}",
                    )
                self.receipts.settle(
                    claim,
                    result,
                    max_attempts=job.max_attempts,
                    retry_delay_seconds=job.retry_delay_seconds,
                )
                report["completed"].append(
                    {
                        "fire_key": claim.fire.fire_key,
                        "job_id": job.id,
                        "attempt": claim.attempt,
                        **asdict(result),
                    }
                )
        report["completed"].sort(key=lambda item: (item["job_id"], item["fire_key"]))
        return report


def load_schedule_policy(config: Mapping[str, Any]) -> SchedulePolicy:
    raw = config.get("schedule_materialization")
    if not isinstance(raw, Mapping):
        raise ScheduleConfigurationError("schedule_materialization policy is missing")
    timezone_name = str(
        raw.get("timezone")
        or (config.get("metadata") or {}).get("timezone")
        or "Asia/Taipei"
    )
    active_jobs_raw = raw.get("active_jobs") or {}
    if not isinstance(active_jobs_raw, Mapping):
        raise ScheduleConfigurationError("schedule_materialization.active_jobs must be an object")
    active_jobs: dict[str, datetime] = {}
    for job_id, item in active_jobs_raw.items():
        if isinstance(item, str):
            activated_at = _parse_iso(item)
        elif isinstance(item, Mapping):
            activated_at = _parse_iso(str(item.get("activated_at") or ""))
        else:
            activated_at = None
        if activated_at is None:
            raise ScheduleConfigurationError(
                f"active_jobs.{job_id} requires an explicit activated_at timestamp"
            )
        active_jobs[str(job_id)] = activated_at

    return SchedulePolicy(
        generation=str(raw.get("generation") or ""),
        mode=str(raw.get("mode") or "disabled"),
        timezone=timezone_name,
        active_jobs=active_jobs,
        active_since=_parse_iso(raw.get("active_since")),
        max_parallel=int(raw.get("max_parallel") or 4),
        shadow_grace_seconds=int(raw.get("shadow_grace_seconds") or 120),
    )


def load_schedule_jobs(config: Mapping[str, Any]) -> list[ScheduleJob]:
    policy_raw = config.get("schedule_materialization")
    if not isinstance(policy_raw, Mapping):
        raise ScheduleConfigurationError("schedule_materialization policy is missing")
    default_timezone = str(
        policy_raw.get("timezone")
        or (config.get("metadata") or {}).get("timezone")
        or "Asia/Taipei"
    )
    defaults = policy_raw.get("job_defaults") or {}
    if not isinstance(defaults, Mapping):
        raise ScheduleConfigurationError("schedule_materialization.job_defaults must be an object")
    overrides = policy_raw.get("job_overrides") or {}
    if not isinstance(overrides, Mapping):
        raise ScheduleConfigurationError("schedule_materialization.job_overrides must be an object")

    items = (config.get("system_crontab") or {}).get("items") or []
    jobs: list[ScheduleJob] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        job_id = str(item.get("id") or "")
        cron = item.get("cron")
        command = item.get("wrapper_script")
        if not job_id or not isinstance(cron, str) or not isinstance(command, str):
            continue
        if str(item.get("status") or "").lower() == "retired":
            continue
        override = overrides.get(job_id) or {}
        if not isinstance(override, Mapping):
            raise ScheduleConfigurationError(f"job_overrides.{job_id} must be an object")

        def setting(name: str, fallback: Any) -> Any:
            return override.get(name, item.get(name, defaults.get(name, fallback)))

        jobs.append(
            ScheduleJob(
                id=job_id,
                cron=cron,
                command=command,
                timezone=str(setting("timezone", default_timezone)),
                catch_up=str(setting("catch_up", "latest_only")),
                grace_seconds=int(setting("grace_seconds", 120)),
                max_catchup_seconds=int(setting("max_catchup_seconds", 86_400)),
                max_attempts=int(setting("max_attempts", 3)),
                retry_delay_seconds=int(setting("retry_delay_seconds", 300)),
                lease_seconds=int(setting("lease_seconds", 3_600)),
                timeout_seconds=int(setting("timeout_seconds", 3_000)),
                enabled=bool(setting("enabled", True)),
            )
        )
    return jobs


def load_legacy_success_markers(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:  # silent-ok: a fresh host has no legacy success markers yet
        return {}
    if not isinstance(payload, dict):
        raise RuntimeError(f"legacy marker must be an object: {path}")
    return {
        str(job_id): str(value)
        for job_id, value in payload.items()
        if not str(job_id).startswith("_") and isinstance(value, str)
    }
