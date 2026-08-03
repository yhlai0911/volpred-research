#!/usr/bin/env python3
"""Operations Core scheduler clock.

The launchd service runs ``daemon``.  It reloads the canonical policy on every
tick, so shadow/canary/active ownership changes do not require a process restart.

Examples:
    uv run python -m scripts.operations_core_scheduler validate
    uv run python -m scripts.operations_core_scheduler tick
    uv run python -m scripts.operations_core_scheduler daemon
"""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import signal
import sys
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from volpred.ops.schedule_materialization import (
    FileReceiptStore,
    ScheduleMaterializer,
    load_schedule_jobs,
    load_schedule_policy,
)
from volpred.ops.schedules import job_liveness, load_cron_marker_state

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "runtime_schedules.json"
DEFAULT_RECEIPTS = ROOT / "storage" / "ops" / "schedule_receipts.json"
DEFAULT_LEGACY_MARKERS = ROOT / "storage" / "ops" / "cron_last_run.json"
DEFAULT_LOCK = Path.home() / ".volpred" / "operations_core_scheduler.lock"
DEFAULT_LOG = Path.home() / ".volpred" / "logs" / "operations_core_scheduler.log"
LOG = logging.getLogger("operations-core-scheduler")
UTC = timezone.utc


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected object in {path}")
    return payload


def _receipt_path(config: dict[str, Any], *, override: Path | None) -> Path:
    if override is not None:
        return override
    policy = config.get("schedule_materialization") or {}
    configured = policy.get("receipt_path")
    if not configured:
        return DEFAULT_RECEIPTS
    path = Path(str(configured)).expanduser()
    return path if path.is_absolute() else ROOT / path


def build_materializer(
    *,
    config_path: Path = DEFAULT_CONFIG,
    receipts_path: Path | None = None,
    mode_override: str | None = None,
) -> ScheduleMaterializer:
    config = _load_json(config_path)
    policy = load_schedule_policy(config)
    if mode_override is not None:
        policy = replace(policy, mode=mode_override)
    jobs = load_schedule_jobs(config)
    retention = (config.get("schedule_materialization") or {}).get(
        "receipt_retention"
    ) or {}
    return ScheduleMaterializer(
        policy=policy,
        jobs=jobs,
        receipts=FileReceiptStore(
            _receipt_path(config, override=receipts_path),
            max_terminal_records=int(
                retention.get("max_terminal_records", 6_000)
            ),
            max_shadow_records=int(
                retention.get("max_shadow_records", 2_000)
            ),
        ),
        repo_root=ROOT,
        legacy_last_success=legacy_success_evidence(
            config,
            repo_root=ROOT,
            marker_path=DEFAULT_LEGACY_MARKERS,
        ),
    )


def legacy_success_evidence(
    config: dict[str, Any],
    *,
    repo_root: Path,
    marker_path: Path,
) -> dict[str, str]:
    """Resolve legacy success without consulting Operations Core receipts.

    Shadow comparison used to read ``cron_last_run`` directly, recreating the
    exact observability bug WS-D1 removed: direct LaunchAgents can run
    successfully without stamping that marker.
    """
    markers = load_cron_marker_state(marker_path)
    items = (config.get("system_crontab") or {}).get("items") or []
    evidence: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        live = job_liveness(
            item,
            marker_state=markers,
            receipt_state={},
            repo_root=repo_root,
        )
        if live.last_success is not None:
            evidence[str(item["id"])] = live.last_success.isoformat()
    return evidence


def validate_config(*, config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    config = _load_json(config_path)
    policy = load_schedule_policy(config)
    jobs = load_schedule_jobs(config)
    # Construction performs the cross-object duplicate/unknown-owner gates.
    ScheduleMaterializer(
        policy=policy,
        jobs=jobs,
        receipts=FileReceiptStore(Path("/dev/null")),
        repo_root=ROOT,
    )
    owner_counts = {"operations_core": 0, "legacy": 0}
    for job in jobs:
        owner_counts[policy.owner_for(job.id)] += 1
    return {
        "ok": True,
        "generation": policy.generation,
        "mode": policy.mode,
        "job_count": len(jobs),
        "owner_counts": owner_counts,
        "active_jobs": sorted(policy.active_jobs),
    }


def build_shadow_report(
    *,
    config_path: Path = DEFAULT_CONFIG,
    receipts_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Summarize settled new-vs-legacy fire predictions as machine-readable parity."""
    config = _load_json(config_path)
    policy = load_schedule_policy(config)
    path = _receipt_path(config, override=receipts_path)
    payload: dict[str, Any] = {}
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise RuntimeError(f"expected object in {path}")
        payload = loaded
    observations = payload.get("shadow") or {}
    if not isinstance(observations, dict):
        raise RuntimeError(f"expected shadow object in {path}")

    current = now or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(UTC)
    matched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for fire_key, raw in observations.items():
        if not isinstance(raw, dict) or raw.get("generation") != policy.generation:
            continue
        scheduled_raw = raw.get("scheduled_for")
        if not isinstance(scheduled_raw, str):
            missing.append(
                {
                    "fire_key": str(fire_key),
                    "job_id": raw.get("job_id"),
                    "reason": "invalid_scheduled_for",
                }
            )
            continue
        scheduled = datetime.fromisoformat(scheduled_raw.replace("Z", "+00:00"))
        row = {
            "fire_key": str(fire_key),
            "job_id": raw.get("job_id"),
            "scheduled_for": scheduled_raw,
            "legacy_last_success": raw.get("legacy_last_success"),
            "observations": int(raw.get("observations") or 0),
            "first_seen_at": raw.get("first_seen_at"),
            "last_seen_at": raw.get("last_seen_at"),
        }
        if current <= scheduled.astimezone(UTC) + timedelta(
            seconds=policy.shadow_grace_seconds
        ):
            row["reason"] = "observation_window_open"
            pending.append(row)
        elif raw.get("legacy_observed") is True:
            row["reason"] = "legacy_fire_observed"
            matched.append(row)
        else:
            row["reason"] = "legacy_fire_missing"
            missing.append(row)

    matched.sort(key=lambda item: (str(item.get("scheduled_for")), str(item.get("job_id"))))
    missing.sort(key=lambda item: (str(item.get("scheduled_for")), str(item.get("job_id"))))
    pending.sort(key=lambda item: (str(item.get("scheduled_for")), str(item.get("job_id"))))
    settled = len(matched) + len(missing)
    return {
        "schema": 1,
        "generated_at": current.isoformat().replace("+00:00", "Z"),
        "generation": policy.generation,
        "receipt_path": str(path),
        "shadow_grace_seconds": policy.shadow_grace_seconds,
        "counts": {
            "settled": settled,
            "matched": len(matched),
            "missing": len(missing),
            "pending": len(pending),
        },
        "parity_rate": (len(matched) / settled) if settled else None,
        "matched": matched,
        "missing": missing,
        "pending": pending,
    }


def run_tick(
    *,
    config_path: Path = DEFAULT_CONFIG,
    receipts_path: Path | None = None,
    mode_override: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    return build_materializer(
        config_path=config_path,
        receipts_path=receipts_path,
        mode_override=mode_override,
    ).tick(now=now)


@contextmanager
def daemon_lock(path: Path = DEFAULT_LOCK) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"another operations-core scheduler holds {path}") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()}\n")
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _setup_logging(log_path: Path = DEFAULT_LOG) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


def run_daemon(
    *,
    config_path: Path = DEFAULT_CONFIG,
    receipts_path: Path | None = None,
    tick_seconds: int = 30,
) -> int:
    if tick_seconds < 5:
        raise ValueError("tick_seconds must be >= 5")
    stopping = False

    def stop(_signum, _frame) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with daemon_lock():
        LOG.info("daemon started pid=%s tick_seconds=%s", os.getpid(), tick_seconds)
        while not stopping:
            began = time.monotonic()
            try:
                report = run_tick(
                    config_path=config_path,
                    receipts_path=receipts_path,
                )
                LOG.info(
                    "tick mode=%s generation=%s shadow=%d claims=%d completed=%d blocked=%d",
                    report["mode"],
                    report["generation"],
                    len(report["shadow"]),
                    len(report["claims"]),
                    len(report["completed"]),
                    len(report["blocked"]),
                )
            except Exception:
                LOG.exception("scheduler tick failed")
            remaining = max(0.0, tick_seconds - (time.monotonic() - began))
            deadline = time.monotonic() + remaining
            while not stopping and time.monotonic() < deadline:
                time.sleep(min(0.5, deadline - time.monotonic()))
        LOG.info("daemon stopped")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="operations-core-scheduler")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--receipts", type=Path, default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    shadow_report = subparsers.add_parser("shadow-report")
    shadow_report.add_argument(
        "--fail-on-mismatch",
        action="store_true",
        help="exit 1 when a settled shadow fire has no matching legacy success",
    )
    tick = subparsers.add_parser("tick")
    tick.add_argument("--mode", choices=["shadow", "canary", "active", "disabled"])
    daemon = subparsers.add_parser("daemon")
    daemon.add_argument("--tick-seconds", type=int, default=30)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "validate":
        result = validate_config(config_path=args.config)
    elif args.command == "shadow-report":
        result = build_shadow_report(
            config_path=args.config,
            receipts_path=args.receipts,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if args.fail_on_mismatch and result["missing"] else 0
    elif args.command == "tick":
        result = run_tick(
            config_path=args.config,
            receipts_path=args.receipts,
            mode_override=args.mode,
        )
    else:
        _setup_logging()
        return run_daemon(
            config_path=args.config,
            receipts_path=args.receipts,
            tick_seconds=args.tick_seconds,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
