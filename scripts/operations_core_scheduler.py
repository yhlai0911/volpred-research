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
from datetime import datetime
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
    return ScheduleMaterializer(
        policy=policy,
        jobs=jobs,
        receipts=FileReceiptStore(_receipt_path(config, override=receipts_path)),
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
    tick = subparsers.add_parser("tick")
    tick.add_argument("--mode", choices=["shadow", "canary", "active", "disabled"])
    daemon = subparsers.add_parser("daemon")
    daemon.add_argument("--tick-seconds", type=int, default=30)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "validate":
        result = validate_config(config_path=args.config)
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
