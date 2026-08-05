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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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
from model_router import pick_model  # noqa: E402

MANAGER = "manager"
MANAGER_TASK_TYPE = "org_manager"
CLAUDE = "claude"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ORG_ROOT)
    parser.add_argument("--reason", default="manager_tick gate fired")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    root: Path = args.root

    existing = read_lease(root, MANAGER)
    if existing:
        print(f"manager already held by {existing.get('runner')} — refusing to stack", file=sys.stderr)
        return 0

    model, effort = pick_model(MANAGER_TASK_TYPE)
    runtime_dir(root).mkdir(parents=True, exist_ok=True)
    ipath = identity_path(root, MANAGER)
    ipath.write_text(build_manager_brief(root), encoding="utf-8")

    write_lease(root, MANAGER, {
        "runner": "headless", "model": model, "effort": effort,
        "reason": args.reason, "since": now_iso(),
    })
    log = REPO_ROOT / "storage" / "logs" / "cron" / "org_manager_run.log"
    log.parent.mkdir(parents=True, exist_ok=True)

    started = datetime.now(timezone.utc)
    outcome = {"reason": args.reason, "model": model, "effort": effort}
    try:
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"\n=== manager run {now_iso()} ({args.reason}) ===\n")
            fh.flush()
            proc = subprocess.run(
                [CLAUDE, "-p", "--model", model, "--effort", effort,
                 "--append-system-prompt-file", str(ipath),
                 "開始本輪協調：讀你的收件匣與組織現況，依優先序處理並派工。"
                 "判斷與理由記進 bulletin。沒有該做的事就明說 noop 後結束。"],
                cwd=str(REPO_ROOT), stdout=fh, stderr=subprocess.STDOUT,
                timeout=args.timeout,
            )
        outcome["exit_code"] = proc.returncode
    except subprocess.TimeoutExpired:
        outcome["exit_code"] = "timeout"
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
