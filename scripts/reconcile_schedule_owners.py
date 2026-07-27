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
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from volpred.ops.schedule_materialization import (
    SchedulePolicy,
    load_schedule_jobs,
    load_schedule_policy,
)
from volpred.ops import termination

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "runtime_schedules.json"
CORE_LABEL = "com.volpred.operations-core-scheduler"
CORE_PLIST = ROOT / "ops" / "launchd" / f"{CORE_LABEL}.plist"
UTC = timezone.utc
HOST_RECONCILE_TIMEOUT_SECONDS = 10


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


def _possible_legacy_label(item: Mapping[str, Any]) -> str | None:
    configured = item.get("launchagent_label") or item.get("launchd_label")
    if configured:
        return str(configured)
    job_id = str(item.get("id") or "")
    return f"com.volpred.{job_id.replace('_', '-')}" if job_id else None


def _direct_legacy_label(item: Mapping[str, Any]) -> str | None:
    if (
        item.get("launchagent_label")
        or item.get("launchd_label")
        or item.get("mechanism") == "launchd"
    ):
        return _possible_legacy_label(item)
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
            if (label := _possible_legacy_label(items[value])) is not None
        }
    )
    legacy_launchagents = sorted(
        {
            label
            for value in legacy_owned
            if (label := _direct_legacy_label(items[value])) is not None
        }
    )
    daemon_registry = config.get("daemons")
    if not isinstance(daemon_registry, list):
        raise RuntimeError(
            "invalid daemons registry: expected a list of daemon objects"
        )
    required_daemons: list[dict[str, str]] = []
    for index, daemon in enumerate(daemon_registry):
        if not isinstance(daemon, Mapping):
            raise RuntimeError(
                f"invalid daemons registry row {index}: expected an object"
            )
        daemon_type = daemon.get("type")
        if daemon_type != "launchd_keepalive_daemon":
            raise RuntimeError(
                f"unsupported daemon type at row {index}: {daemon_type!r}"
            )
        if daemon.get("status") in {"disabled", "retired"}:
            continue
        for field in ("id", "label", "plist"):
            value = daemon.get(field)
            if not isinstance(value, str) or not value.strip():
                raise RuntimeError(
                    "active launchd_keepalive_daemon has invalid "
                    f"{field}: {value!r}"
                )
        required_daemons.append(
            {
                "id": daemon["id"],
                "label": daemon["label"],
                "plist": daemon["plist"],
            }
        )
    required_daemons.sort(key=lambda daemon: daemon["id"])
    return {
        "schema": 1,
        "generation": policy.generation,
        "mode": policy.mode,
        "selected_job_ids": selected,
        "operations_core_job_ids": core_owned,
        "legacy_job_ids": legacy_owned,
        "legacy_labels_to_bootout": core_legacy_labels,
        "legacy_label_jobs": {
            label: value
            for value in core_owned
            if (label := _possible_legacy_label(items[value])) is not None
        },
        "legacy_launchagent_labels": legacy_launchagents,
        "required_daemons": required_daemons,
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
    gated_job_ids: set[str] | None = None,
) -> dict[str, Any]:
    conflicts: list[dict[str, str]] = []
    dormant: list[dict[str, str]] = []
    gated = gated_job_ids or set()
    for job_id in plan["operations_core_job_ids"]:
        tag = f"# volpred-{job_id.replace('_', '-')}"
        if any(line.rstrip().endswith(tag) for line in crontab_text.splitlines()):
            target = dormant if job_id in gated else conflicts
            target.append(
                {
                    "job_id": job_id,
                    "surface": "host_crontab",
                    "reason": (
                        "legacy clock present but business action suppressed by owner gate"
                        if job_id in gated
                        else "legacy owner still installed"
                    ),
                }
            )
    label_jobs = plan.get("legacy_label_jobs") or {}
    for label in plan["legacy_labels_to_bootout"]:
        if label in loaded_labels:
            job_id = str(label_jobs.get(label) or "")
            target = dormant if job_id in gated else conflicts
            target.append(
                {
                    "job_id": job_id,
                    "surface": label,
                    "reason": (
                        "legacy clock present but business action suppressed by owner gate"
                        if job_id in gated
                        else "legacy LaunchAgent still loaded"
                    ),
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
    for daemon in plan.get("required_daemons") or []:
        label = str(daemon["label"])
        if label not in loaded_labels:
            conflicts.append(
                {
                    "job_id": str(daemon["id"]),
                    "surface": label,
                    "reason": "required control-plane daemon not loaded",
                }
            )
    return {
        **dict(plan),
        "ok": not conflicts,
        "status": "owner_surfaces_verified" if not conflicts else "ownership_conflict",
        "conflicts": conflicts,
        "dormant_legacy_surfaces": dormant,
    }


def _legacy_gate_covered_job_ids(config: Mapping[str, Any]) -> set[str]:
    """Jobs whose live wrapper calls the canonical pre-action owner gate."""
    covered: set[str] = set()
    for job_id, item in _items_by_id(config).items():
        raw = item.get("wrapper_script")
        if not isinstance(raw, str) or not raw:
            continue
        live = Path(raw).expanduser()
        canonical = ROOT / "scripts" / live.name
        candidates = [path for path in (live, canonical) if path.is_file()]
        if not candidates:
            continue
        if all(
            "cron_lib.sh" in path.read_text(encoding="utf-8", errors="ignore")
            and "cron_emit_start" in path.read_text(encoding="utf-8", errors="ignore")
            for path in candidates
        ):
            covered.add(job_id)
    return covered


def _run_host_reconcile(
    command: list[str],
    *,
    env: Mapping[str, str],
    gated_job_ids: set[str],
    required_job_ids: set[str],
) -> None:
    """Bound macOS crontab writes; a verified pre-action gate is the fallback."""
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=HOST_RECONCILE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        intent = termination.arm(
            target_kind="pgid", target_id=process.pid,
            reason="schedule_owner_reconcile_timeout",
            actor="reconcile_schedule_owners",
            signal_sequence=[signal.SIGTERM, signal.SIGKILL],
        )
        termination.send_pgid(intent, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            termination.send_pgid(intent, signal.SIGKILL)
            stdout, stderr = process.communicate()
        uncovered = sorted(required_job_ids - gated_job_ids)
        if uncovered:
            raise RuntimeError(
                "host crontab reconciliation timed out and owner gate is missing "
                f"for {uncovered}"
            )
        print(
            "[reconcile_schedule_owners] WARN host crontab rewrite timed out; "
            "verified legacy owner gates remain fail-closed"
        )
        return
    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, end="", file=sys.stderr)
    if process.returncode != 0:
        uncovered = sorted(required_job_ids - gated_job_ids)
        if uncovered:
            raise subprocess.CalledProcessError(
                process.returncode, command, output=stdout, stderr=stderr
            )
        print(
            "[reconcile_schedule_owners] WARN host crontab rewrite failed; "
            "verified legacy owner gates remain fail-closed"
        )


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


def _install_core_plist(*, restart: bool = False) -> None:
    with CORE_PLIST.open("rb") as handle:
        plistlib.load(handle)
    destination = Path.home() / "Library" / "LaunchAgents" / CORE_PLIST.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"

    def loaded() -> bool:
        return (
            subprocess.run(
                ["launchctl", "print", f"{domain}/{CORE_LABEL}"],
                capture_output=True,
                text=True,
                check=False,
            ).returncode
            == 0
        )

    # Reconcile is run for each canary class.  Restarting an unchanged healthy
    # clock on every invocation creates a launchd bootout/bootstrap race (exit
    # 5 while the old service is still unloading) and an unnecessary schedule
    # observation gap.
    if (
        not restart
        and destination.exists()
        and destination.read_bytes() == CORE_PLIST.read_bytes()
        and loaded()
    ):
        return

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
    if loaded():
        subprocess.run(
            ["launchctl", "bootout", f"{domain}/{CORE_LABEL}"],
            capture_output=True,
            text=True,
            check=False,
        )
        deadline = time.monotonic() + 5.0
        while loaded() and time.monotonic() < deadline:
            time.sleep(0.1)
        if loaded():
            raise RuntimeError(f"{CORE_LABEL} did not unload within 5 seconds")
    subprocess.run(
        ["launchctl", "bootstrap", domain, str(destination)],
        capture_output=True,
        text=True,
        check=True,
    )


def _restore_missing_required_daemons(
    required_daemons: list[Mapping[str, str]],
) -> None:
    """Bootstrap canonical KeepAlive daemons that disappeared during cutover."""
    domain = f"gui/{os.getuid()}"
    root = ROOT.resolve()
    destination_dir = Path.home() / "Library" / "LaunchAgents"
    destination_dir.mkdir(parents=True, exist_ok=True)
    for daemon in required_daemons:
        label = str(daemon["label"])
        relative = Path(str(daemon["plist"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(
                f"required daemon plist must be repo-relative: {relative}"
            )
        source = (ROOT / relative).resolve()
        if not source.is_relative_to(root):
            raise RuntimeError(
                f"required daemon plist escapes repository: {relative}"
            )
        plist_label = subprocess.run(
            ["plutil", "-extract", "Label", "raw", "-o", "-", str(source)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if plist_label != label:
            raise RuntimeError(
                f"required daemon plist label mismatch: {relative}"
            )
        loaded = subprocess.run(
            ["launchctl", "print", f"{domain}/{label}"],
            capture_output=True,
            text=True,
            check=False,
        ).returncode == 0
        if loaded:
            continue
        destination = destination_dir / source.name
        fd, tmp_name = tempfile.mkstemp(
            dir=str(destination_dir),
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        os.close(fd)
        try:
            shutil.copyfile(source, tmp_name)
            os.chmod(tmp_name, 0o644)
            os.replace(tmp_name, destination)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        bootstrap_command = [
            "launchctl",
            "bootstrap",
            domain,
            str(destination),
        ]
        bootstrap = subprocess.run(
            bootstrap_command,
            capture_output=True,
            text=True,
            check=False,
        )
        if bootstrap.returncode != 0:
            converged = subprocess.run(
                ["launchctl", "print", f"{domain}/{label}"],
                capture_output=True,
                text=True,
                check=False,
            ).returncode == 0
            if not converged:
                raise subprocess.CalledProcessError(
                    bootstrap.returncode,
                    bootstrap_command,
                    output=bootstrap.stdout,
                    stderr=bootstrap.stderr,
                )


def apply_owner_plan(
    config: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    config_path: Path,
    job_id: str | None,
    restart_core: bool = False,
) -> None:
    gated_job_ids = _legacy_gate_covered_job_ids(config)
    if plan["core_daemon_required"]:
        _install_core_plist(restart=restart_core)
    _restore_missing_required_daemons(
        list(plan.get("required_daemons") or [])
    )

    host_command = ["bash", str(ROOT / "scripts" / "install_host_crontab.sh")]
    if job_id:
        host_command.extend(["--id", job_id])
    env = {
        **os.environ,
        "VOLPRED_REPO_ROOT": str(ROOT),
        "VOLPRED_RUNTIME_SCHEDULES_PATH": str(config_path),
    }
    _run_host_reconcile(
        host_command,
        env=env,
        gated_job_ids=gated_job_ids,
        required_job_ids=set(plan["operations_core_job_ids"]),
    )

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
        if _direct_legacy_label(item) is not None:
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
    parser.add_argument(
        "--restart-core",
        action="store_true",
        help="restart the clock after deploying Python code even when the plist is unchanged",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.restart_core and not args.apply:
        raise SystemExit("--restart-core requires --apply")
    config = _load_config(args.config)
    plan = build_owner_plan(config, job_id=args.job_id)
    if args.apply:
        apply_owner_plan(
            config,
            plan,
            config_path=args.config,
            job_id=args.job_id,
            restart_core=args.restart_core,
        )
    audit = audit_owner_plan(
        plan,
        crontab_text=_read_crontab(),
        loaded_labels=_loaded_launchd_labels(),
        gated_job_ids=_legacy_gate_covered_job_ids(config),
    )
    audit["audited_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    print(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if audit["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
