#!/usr/bin/env python3
"""Reconcile live schedule owners with ``runtime_schedules.json``.

This is the only cutover/rollback entrypoint for schedule ownership.  It does
not edit the canonical config; operators change the config first, inspect this
plan, then apply it:

    uv run python scripts/reconcile_schedule_owners.py
    uv run python scripts/reconcile_schedule_owners.py --apply
    uv run python scripts/reconcile_schedule_owners.py --apply --job-id feed_sync

The apply order is deliberate:

1. bootstrap the operations-core clock;
2. remove host-cron legs now owned by operations core;
3. boot out legacy LaunchAgents for those same jobs;
4. read the live surfaces back and emit a machine-readable audit.

Canary ``activated_at`` timestamps should be in the future when step 2 runs, so
the new owner cannot fire before the legacy owner has been removed.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from volpred.ops.schedule_materialization import (
    SchedulePolicy,
    load_schedule_jobs,
    load_schedule_policy,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "runtime_schedules.json"
CORE_LABEL = "com.volpred.operations-core-scheduler"
CORE_PLIST = ROOT / "ops" / "launchd" / f"{CORE_LABEL}.plist"
UTC = timezone.utc


def _load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected object in {path}")
    return payload


def _items_by_id(config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    items = (config.get("system_crontab") or {}).get("items") or []
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if isinstance(item, dict) and item.get("id"):
            result[str(item["id"])] = item
    return result


def _legacy_label(item: Mapping[str, Any]) -> str | None:
    configured = item.get("launchagent_label") or item.get("launchd_label")
    if configured:
        return str(configured)
    if item.get("mechanism") == "launchd":
        return f"com.volpred.{str(item.get('id') or '').replace('_', '-')}"
    return None


def build_owner_plan(
    config: Mapping[str, Any],
    *,
    job_id: str | None = None,
) -> dict[str, Any]:
    policy = load_schedule_policy(config)
    jobs = load_schedule_jobs(config)
    items = _items_by_id(config)
    known_ids = {job.id for job in jobs}
    if job_id is not None and job_id not in known_ids:
        raise ValueError(f"unknown executable schedule job: {job_id}")
    selected = sorted({job_id} if job_id else known_ids)
    core_owned = [value for value in selected if policy.owner_for(value) == "operations_core"]
    legacy_owned = [value for value in selected if policy.owner_for(value) == "legacy"]
    core_legacy_labels = sorted(
        {
            label
            for value in core_owned
            if (label := _legacy_label(items[value])) is not None
        }
    )
    legacy_launchagents = sorted(
        {
            label
            for value in legacy_owned
            if (label := _legacy_label(items[value])) is not None
        }
    )
    return {
        "schema": 1,
        "generation": policy.generation,
        "mode": policy.mode,
        "selected_job_ids": selected,
        "operations_core_job_ids": core_owned,
        "legacy_job_ids": legacy_owned,
        "legacy_labels_to_bootout": core_legacy_labels,
        "legacy_launchagent_labels": legacy_launchagents,
        "core_daemon_required": policy.mode != "disabled",
        "core_daemon_label": str(
            (config.get("schedule_materialization") or {}).get("daemon_label")
            or CORE_LABEL
        ),
    }


def audit_owner_plan(
    plan: Mapping[str, Any],
    *,
    crontab_text: str,
    loaded_labels: set[str],
) -> dict[str, Any]:
    conflicts: list[dict[str, str]] = []
    for job_id in plan["operations_core_job_ids"]:
        tag = f"# volpred-{job_id.replace('_', '-')}"
        if any(line.rstrip().endswith(tag) for line in crontab_text.splitlines()):
            conflicts.append(
                {
                    "job_id": job_id,
                    "surface": "host_crontab",
                    "reason": "legacy owner still installed",
                }
            )
    for label in plan["legacy_labels_to_bootout"]:
        if label in loaded_labels:
            conflicts.append(
                {
                    "job_id": "",
                    "surface": label,
                    "reason": "legacy LaunchAgent still loaded",
                }
            )
    core_label = str(plan["core_daemon_label"])
    if plan["core_daemon_required"] and core_label not in loaded_labels:
        conflicts.append(
            {
                "job_id": "",
                "surface": core_label,
                "reason": "operations-core clock not loaded",
            }
        )
    return {
        **dict(plan),
        "ok": not conflicts,
        "status": "owner_surfaces_verified" if not conflicts else "ownership_conflict",
        "conflicts": conflicts,
    }


def _read_crontab() -> str:
    result = subprocess.run(
        ["crontab", "-l"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError(f"crontab -l failed: {result.stderr.strip()}")
    return result.stdout


def _loaded_launchd_labels() -> set[str]:
    result = subprocess.run(
        ["launchctl", "list"],
        capture_output=True,
        text=True,
        check=True,
    )
    labels: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if parts:
            labels.add(parts[-1])
    return labels


def _install_core_plist() -> None:
    with CORE_PLIST.open("rb") as handle:
        plistlib.load(handle)
    destination = Path.home() / "Library" / "LaunchAgents" / CORE_PLIST.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(destination.parent), prefix=f".{destination.name}.", suffix=".tmp"
    )
    os.close(fd)
    try:
        shutil.copyfile(CORE_PLIST, tmp_name)
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, destination)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["launchctl", "bootout", f"{domain}/{CORE_LABEL}"],
        capture_output=True,
        text=True,
        check=False,
    )
    subprocess.run(
        ["launchctl", "bootstrap", domain, str(destination)],
        capture_output=True,
        text=True,
        check=True,
    )


def apply_owner_plan(
    config: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    config_path: Path,
    job_id: str | None,
) -> None:
    if plan["core_daemon_required"]:
        _install_core_plist()

    host_command = ["bash", str(ROOT / "scripts" / "install_host_crontab.sh")]
    if job_id:
        host_command.extend(["--id", job_id])
    env = {
        **os.environ,
        "VOLPRED_REPO_ROOT": str(ROOT),
        "VOLPRED_RUNTIME_SCHEDULES_PATH": str(config_path),
    }
    subprocess.run(host_command, cwd=ROOT, env=env, check=True)

    domain = f"gui/{os.getuid()}"
    for label in plan["legacy_labels_to_bootout"]:
        subprocess.run(
            ["launchctl", "bootout", f"{domain}/{label}"],
            capture_output=True,
            text=True,
            check=False,
        )

    # Targeted rollback: after config returns a job to legacy ownership, restore
    # its explicit LaunchAgent if it has one.  Host-owned jobs were restored by
    # install_host_crontab above.
    if job_id and job_id in plan["legacy_job_ids"]:
        item = _items_by_id(config)[job_id]
        if _legacy_label(item) is not None:
            subprocess.run(
                ["bash", str(ROOT / "scripts" / "install_launchd_jobs.sh"), "--id", job_id],
                cwd=ROOT,
                env=env,
                check=True,
            )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--job-id")
    parser.add_argument("--apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = _load_config(args.config)
    plan = build_owner_plan(config, job_id=args.job_id)
    if args.apply:
        apply_owner_plan(
            config,
            plan,
            config_path=args.config,
            job_id=args.job_id,
        )
    audit = audit_owner_plan(
        plan,
        crontab_text=_read_crontab(),
        loaded_labels=_loaded_launchd_labels(),
    )
    audit["audited_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    print(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if audit["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
