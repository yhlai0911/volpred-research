#!/usr/bin/env python3
"""Run one coordinator round headless, holding a lease for its duration.

Spawned detached by manager_tick when the gate fires and no cockpit pane is
available. The lease is what keeps a 30-minute tick from stacking coordinators
on top of each other; it is released in a finally so a crash cannot wedge the
org shut.

  uv run python scripts/org/manager_run.py [--reason "..."] [--timeout 1800]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from _core import (  # noqa: E402
    DEFAULT_ORG_ROOT,
    REPO_ROOT,
    build_manager_brief,
    clear_lease,
    identity_path,
    now_iso,
    read_lease,
    runtime_dir,
    write_lease,
    write_receipt,
)
from model_router import cli_flag, pick_model  # noqa: E402
from scripts.dispatch_supervisor import procutil  # noqa: E402
from volpred.ops import termination  # noqa: E402
from volpred.ops.execution.registry import (  # noqa: E402
    ProviderRegistryError,
    authorize_provider_spawn,
    sanitize_provider_spawn_environment,
    verify_spawn_receipt,
)

MANAGER = "manager"
MANAGER_TASK_TYPE = "org_manager"
CLAUDE = "claude"
LAUNCH_CONTRACT = "org-manager.claude"
_CLAUDE_FALLBACK_PATHS = (
    Path.home() / ".local" / "bin" / "claude",
    Path("/opt/homebrew/bin/claude"),
    Path("/usr/local/bin/claude"),
)


def _resolve_claude_bin() -> str:
    """Resolve Claude explicitly so launchd's minimal PATH cannot break a run."""
    override = os.environ.get("VOLPRED_CLAUDE_BIN") or os.environ.get("CLAUDE_BIN")
    if override:
        found = shutil.which(override)
        if found:
            return found
        raise FileNotFoundError(
            f"configured Claude executable is unavailable: {override!r}"
        )
    if found := shutil.which(CLAUDE):
        return found
    for candidate in _CLAUDE_FALLBACK_PATHS:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise FileNotFoundError(
        "Claude CLI is unavailable; set VOLPRED_CLAUDE_BIN to an executable path"
    )


def _authorized_launch(model: str) -> tuple[object, dict[str, str], tuple[str, ...], str]:
    """Authorize one zero-paid Claude spawn and return its pinned environment."""
    model_id = cli_flag(model)
    clean_env, stripped = sanitize_provider_spawn_environment(
        contract_id=LAUNCH_CONTRACT,
        environment=os.environ,
    )
    receipt = authorize_provider_spawn(
        contract_id=LAUNCH_CONTRACT,
        model_id=model_id,
        executable_path=_resolve_claude_bin(),
        environment=clean_env,
    )
    verify_spawn_receipt(receipt)
    return receipt, {**clean_env, **receipt.environment()}, stripped, model_id


def _terminate_manager(proc: subprocess.Popen) -> tuple[bool, str | None]:
    """Kill the provider process and escaped descendants, then confirm reaping."""
    ledger = termination.DEFAULT_LEDGER_PATH
    try:
        intent = termination.arm(
            target_kind="pgid",
            target_id=proc.pid,
            reason="org_manager_timeout",
            actor="org_manager",
            signal_sequence=termination.terminating_signals(),
            ledger_path=ledger,
        )
        confirmed = procutil.kill_tree(
            proc.pid,
            intent=intent,
            ledger_path=ledger,
        )
    except Exception as exc:  # noqa: BLE001 - timeout receipt must preserve the failure
        return False, f"{type(exc).__name__}: {exc}"
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        return False, "process tree did not reap after termination"
    return bool(confirmed), None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ORG_ROOT)
    parser.add_argument("--reason", default="manager_tick gate fired")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    root: Path = args.root

    existing = read_lease(root, MANAGER)
    if existing:
        print(
            f"manager already held by {existing.get('runner')} — refusing to stack",
            file=sys.stderr,
        )
        return 0

    model, effort = pick_model(MANAGER_TASK_TYPE)
    runtime_dir(root).mkdir(parents=True, exist_ok=True)
    ipath = identity_path(root, MANAGER)
    ipath.write_text(build_manager_brief(root), encoding="utf-8")

    write_lease(
        root,
        MANAGER,
        {
            "runner": "headless",
            "model": model,
            "effort": effort,
            "reason": args.reason,
            "since": now_iso(),
        },
    )
    log = REPO_ROOT / "storage" / "logs" / "cron" / "org_manager_run.log"
    log.parent.mkdir(parents=True, exist_ok=True)

    started = datetime.now(timezone.utc)
    outcome: dict[str, object] = {
        "reason": args.reason,
        "model": model,
        "effort": effort,
    }
    proc: subprocess.Popen | None = None
    try:
        receipt, child_env, stripped, model_id = _authorized_launch(model)
        outcome.update(
            {
                "provider_id": receipt.provider_id,
                "model_id": model_id,
                "provider_registry_sha256": receipt.registry_sha256,
            }
        )
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"\n=== manager run {now_iso()} ({args.reason}) ===\n")
            if stripped:
                fh.write(
                    "provider environment stripped forbidden names: "
                    + ", ".join(stripped)
                    + "\n"
                )
            fh.flush()
            proc = subprocess.Popen(
                [
                    receipt.resolved_executable,
                    "-p",
                    "--model",
                    model_id,
                    "--effort",
                    effort,
                    "--append-system-prompt-file",
                    str(ipath),
                    "開始本輪協調：讀你的收件匣與組織現況，依優先序處理並派工。"
                    "判斷與理由記進 bulletin。沒有該做的事就明說 noop 後結束。",
                ],
                cwd=str(REPO_ROOT),
                stdout=fh,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
                env=child_env,
            )
            proc.wait(timeout=args.timeout)
        outcome["exit_code"] = proc.returncode
    except subprocess.TimeoutExpired:
        outcome["exit_code"] = "timeout"
        if proc is not None:
            confirmed, error = _terminate_manager(proc)
            outcome["termination_confirmed"] = confirmed
            if error:
                outcome["termination_error"] = error
        else:
            outcome["termination_confirmed"] = False
            outcome["termination_error"] = "timeout occurred before process creation"
    except ProviderRegistryError as exc:
        outcome["exit_code"] = "provider_policy_denied"
        outcome["provider_policy_error"] = str(exc)
    except (OSError, subprocess.SubprocessError) as exc:
        outcome["exit_code"] = f"{type(exc).__name__}: {exc}"
    finally:
        clear_lease(root, MANAGER)
        outcome["duration_seconds"] = round(
            (datetime.now(timezone.utc) - started).total_seconds(), 1
        )
        write_receipt(root, "manager_run", outcome)

    print(json.dumps(outcome, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
