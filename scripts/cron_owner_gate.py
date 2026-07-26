#!/usr/bin/env python3
"""Fail-closed ownership gate for legacy cron/LaunchAgent wrappers.

Exit codes:
  0  legacy wrapper owns the job and may continue
  75 Operations Core owns the job; legacy wrapper must exit successfully
  2  ownership is ambiguous or canonical config is invalid; fail closed
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "runtime_schedules.json"
LEGACY_ALLOWED = 0
OPERATIONS_CORE_OWNS = 75
INVALID_OWNERSHIP = 2


def owner_for_wrapper(
    wrapper: str,
    *,
    config_path: Path = CONFIG,
) -> tuple[str, str | None]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("runtime schedule root must be an object")
    basename = Path(wrapper).name
    items = (payload.get("system_crontab") or {}).get("items") or []
    matches = [
        item
        for item in items
        if isinstance(item, dict)
        and Path(str(item.get("wrapper_script") or "")).name == basename
    ]
    if not matches:
        return "unmanaged", None
    if len(matches) != 1:
        raise ValueError(f"wrapper basename is not unique: {basename}")
    job_id = str(matches[0].get("id") or "")
    if not job_id:
        raise ValueError(f"wrapper has no job id: {basename}")

    raw_policy: Any = payload.get("schedule_materialization")
    if raw_policy is None:
        return "legacy", job_id
    if not isinstance(raw_policy, dict):
        raise ValueError("schedule_materialization must be an object")
    mode = str(raw_policy.get("mode") or "disabled")
    if mode not in {"disabled", "shadow", "canary", "active"}:
        raise ValueError(f"invalid schedule materialization mode: {mode}")
    active_jobs = raw_policy.get("active_jobs") or {}
    if not isinstance(active_jobs, dict):
        raise ValueError("schedule_materialization.active_jobs must be an object")
    if mode == "active" or (mode == "canary" and job_id in active_jobs):
        return "operations_core", job_id
    return "legacy", job_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--wrapper", required=True)
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args(argv)
    try:
        owner, job_id = owner_for_wrapper(args.wrapper, config_path=args.config)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            f"[cron-owner-gate] ERROR fail-closed wrapper={args.wrapper} "
            f"error={type(exc).__name__}: {exc}"
        )
        return INVALID_OWNERSHIP
    if owner == "operations_core":
        print(
            f"[cron-owner-gate] skip legacy owner job_id={job_id} "
            "owner=operations_core"
        )
        return OPERATIONS_CORE_OWNS
    return LEGACY_ALLOWED


if __name__ == "__main__":
    raise SystemExit(main())
