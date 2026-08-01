#!/usr/bin/env python3
"""Slot budget for one hourly dispatch fire — mechanical, not model discretion.

This module is the SINGLE owner of both halves of the slot question:
"how many slots exist" (cap) and "how many are taken" (occupancy). Do not
re-derive either one anywhere else — that is exactly what broke.

## Cap

Until 2026-07-13 the cap lived as prose in `scripts/cron_hourly_dispatch_prompt.md`
("total slot cap=4"). A fixed 4 is wrong in both directions: it starves a P1
backlog, and it happily surges straight into a quota outage — and a quota outage
takes the whole loop down, not just one fire.

Rules (owner decision, Telegram msg 596/600; open-incident added 2026-07-19):
  auth_blocked (supervisor saw an auth/quota block)  -> 2   ride it out, don't burn
  open PHASE-Z stuck-path incident                   -> 2   de-rate until it closes
  pending P1 >= P1_SURGE_AT                          -> 6   slots 5-6 reserved for P1/P2
  otherwise                                          -> 4   baseline

The open-incident rule is the whole point of `volpred.ops.foreign_incident`, and
it is deliberately the SAME shape as auth_blocked rather than a second gate
somewhere else: a condition that does not change what the scheduler does is a
red log, and PHASE-Z proved that empirically over 78 fires of correctly-sent
CRITICAL alerts and zero action. It is checked BEFORE the P1 surge on purpose —
surging concurrency while the working tree is full of paths nobody can attribute
is how the ownership signal got unreliable in the first place, and a backlog of
P1s is not a reason to make that worse.

## Occupancy (2026-07-13, task `ops_slot_capacity_and_zombie_worktrees`)

Occupancy used to mean "a directory exists under .claude/worktrees/", counted by
`continue_task_dispatch.count_active_slots`. A directory is an ARTIFACT of work,
not a LEASE on capacity: it has no holder, no heartbeat, and no expiry, so a hung
agent holds a slot forever and silently. On 2026-07-13 02:00 four worktrees held
4/4 slots while only two were doing anything; the dispatcher printed "NO agent
dispatch candidates" for hours with 34 tasks pending, six of them P1.

The first fix measured commit/dirty-file progress and expired a worktree after
four hours. 2026-08-01 proved that was still the same category error with a
timer: three timed-out result worktrees looked "fresh" and consumed 3/2 slots,
blocking both article and incident repair admission. A directory and its mtimes
are artifact custody, never an execution lease.

Only typed schema-v2 lifecycle receipts may now hold worktree capacity. The
runner atomically writes `running + execution_id` before provider spawn and
settles that same generation as either verified `terminal` or
`termination_unverified`. Running/unverified generations hold capacity while
fresh; verified terminal generations release immediately. A newer malformed
generation quarantines the slot rather than exposing an older terminal receipt.
Commit/dirty/reflog progress remains evidence for lease expiry and salvage, but
can never manufacture a lease by itself.

The worktree is NOT deleted here: reclaiming capacity must not depend on a
destructive cleanup succeeding. Hygiene (kill the holder, remove the worktree,
keep the branch) is a separate explicit step —
`scripts/reclaim_stale_worktrees.py`.

The same "artifact nobody expires" bug applies to `storage/ops/agents/*.json`
records stuck at status=running, so the same staleness rule is applied to them.

Usage:
    uv run python scripts/dispatch_slot_budget.py          # JSON
    uv run python scripts/dispatch_slot_budget.py --cap    # just the integer
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from volpred.ops.diagnostics import warn
from volpred.ops.foreign_incident import open_incidents

REPO = Path(__file__).resolve().parent.parent
TASKS_PATH = REPO / "storage" / "next_tasks.json"
STATE_PATH = REPO / "storage" / "ops" / "dispatch_state.json"
WORKTREES_DIR = REPO / ".claude" / "worktrees"
AGENTS_DIR = REPO / "storage" / "ops" / "agents"
AGENT_JOBS_DIR = REPO / "storage" / "ops" / "agent_jobs"

BASE_CAP = 4
SURGE_CAP = 6
DERATE_CAP = 2
P1_SURGE_AT = 3

# Hours a formal running/unverified execution lease may show zero progress before
# capacity expires. The artifact remains; only the scheduling lease is released.
STALE_HOURS = 4.0
MAX_RECEIPT_CLOCK_SKEW_S = 300.0
ACTIVE_AGENT_STATUSES = {"running", "active", "in_progress", "claimed"}
# Bound the stat() cost on a worktree with a large untracked tree.
_MAX_DIRTY_FILES_STATTED = 200


def _pending_by_priority(tasks_path: Path) -> Counter:
    try:
        tasks = json.loads(tasks_path.read_text())
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        warn("slot-budget", f"讀不到任務池 {tasks_path} ({exc}) — 退回 baseline cap")
        return Counter()
    if isinstance(tasks, dict):
        tasks = tasks.get("tasks", [])
    if not isinstance(tasks, list):
        warn("slot-budget", f"任務池 {tasks_path} root 不是 list — 退回 baseline cap")
        return Counter()
    pending = Counter()
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            warn(
                "slot-budget",
                f"任務池 {tasks_path} row {index} 不是 object — 退回 baseline cap",
            )
            return Counter()
        if task.get("status") != "pending":
            continue
        try:
            pending[int(task.get("priority", 4))] += 1
        except (TypeError, ValueError):
            warn(
                "slot-budget",
                f"任務池 {tasks_path} row {index} priority 無效 — 退回 baseline cap",
            )
            return Counter()
    return pending


def _auth_blocked(state_path: Path) -> bool:
    try:
        return bool(json.loads(state_path.read_text()).get("auth_blocked"))
    except (OSError, json.JSONDecodeError) as exc:
        warn("slot-budget", f"讀不到 supervisor state {state_path} ({exc}) — 當作未被擋")
        return False


def _last_commit_epoch(worktree: Path) -> float:
    try:
        out = subprocess.run(
            ["git", "-C", str(worktree), "log", "-1", "--format=%ct"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
        return float(out) if out else 0.0
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        warn("slot-budget", f"讀不到 {worktree.name} 的 HEAD commit time ({exc}) — 當作無 commit 進度")
        return 0.0


def _last_dirty_mtime(worktree: Path) -> float:
    """Newest mtime among dirty/untracked files — uncommitted work in flight."""
    try:
        out = subprocess.run(
            ["git", "-C", str(worktree), "status", "--porcelain"],
            capture_output=True, text=True, timeout=20, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        warn("slot-budget", f"讀不到 {worktree.name} 的 git status ({exc}) — 當作無未提交進度")
        return 0.0

    newest = 0.0
    for line in out.splitlines()[:_MAX_DIRTY_FILES_STATTED]:
        rel = line[3:].strip().strip('"')
        if " -> " in rel:  # rename: take the destination
            rel = rel.split(" -> ", 1)[1]
        try:
            newest = max(newest, (worktree / rel).stat().st_mtime)
        except OSError:
            continue  # silent-ok: path vanished mid-scan (agent still writing)
    return newest


def _last_git_metadata_mtime(worktree: Path) -> float:
    """High-resolution checkout/ref progress missing from Git commit objects."""
    try:
        output = subprocess.run(
            [
                "git", "-C", str(worktree), "rev-parse",
                "--git-path", "logs/HEAD",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        warn(
            "slot-budget",
            f"讀不到 {worktree.name} 的 Git metadata path ({exc}) — "
            "terminal receipt 不取得同秒 release authority",
        )
        return 0.0
    newest = 0.0
    for raw in output.splitlines():
        path = Path(raw.strip())
        if not path.is_absolute():
            path = worktree / path
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:  # silent-ok: Git metadata paths may disappear mid-read
            continue
    return newest


def _iso_epoch(value: object) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:  # silent-ok: parser is a validation predicate
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.timestamp()


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _legacy_agent_job_receipt(data: dict, *, now: float) -> bool:
    """Recognize v1 archive rows without granting them release authority."""
    cwd = data.get("cwd")
    started = _iso_epoch(data.get("started_at"))
    finished = _iso_epoch(data.get("finished_at"))
    try:
        path_valid = isinstance(cwd, str) and bool(cwd.strip()) and bool(Path(cwd).resolve())
    except (OSError, ValueError):
        path_valid = False
    return (
        path_valid
        and started is not None
        and finished is not None
        and started <= finished <= now + MAX_RECEIPT_CLOCK_SKEW_S
        and isinstance(data.get("timed_out"), bool)
        and _is_int(data.get("exit_code"))
        and _is_int(data.get("runner_exit_code"))
    )


def agent_job_leases(
    agent_jobs_dir: Path | None = None,
    *,
    now: float | None = None,
) -> dict[Path, dict]:
    """Newest schema-v2 execution generation for each worktree path."""
    now = time.time() if now is None else now
    agent_jobs_dir = AGENT_JOBS_DIR if agent_jobs_dir is None else agent_jobs_dir
    latest: dict[Path, dict] = {}
    if not agent_jobs_dir.exists():
        return latest

    def quarantine_invalid(receipt_path: Path, data: dict) -> None:
        cwd = data.get("cwd")
        if not isinstance(cwd, str) or not cwd.strip():
            return
        try:
            key = Path(cwd).resolve()
            observed_epoch = receipt_path.stat().st_mtime
        except (OSError, ValueError):  # silent-ok: caller already emitted receipt warning
            return
        claimed_start = _iso_epoch(data.get("started_at"))
        if (
            claimed_start is not None
            and claimed_start <= now + MAX_RECEIPT_CLOCK_SKEW_S
        ):
            observed_epoch = max(observed_epoch, claimed_start)
        generation = {
            "receipt": str(receipt_path),
            "schema_version": data.get("schema_version"),
            "execution_id": data.get("execution_id"),
            "state": "invalid",
            "runner_pid": data.get("runner_pid"),
            "started_at": data.get("started_at"),
            "started_epoch": observed_epoch,
            "finished_at": data.get("finished_at"),
            "finished_epoch": None,
            "termination_confirmed": False,
            "timed_out": data.get("timed_out") is True,
            "exit_code": data.get("exit_code"),
            "runner_exit_code": data.get("runner_exit_code"),
            "result_artifact_exists": data.get("result_artifact_exists") is True,
            "validation_ok": False,
            "invalid_reason": "lifecycle_schema_invalid",
        }
        previous = latest.get(key)
        if previous is None or previous["started_epoch"] < observed_epoch:
            latest[key] = generation

    for receipt_path in sorted(agent_jobs_dir.glob("*.json")):
        try:
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError) as exc:
            warn(
                "slot-budget",
                f"agent job receipt 讀不到 {receipt_path.name} "
                f"({type(exc).__name__}: {exc}) — 不用它釋放 slot",
            )
            continue
        if not isinstance(data, dict):
            warn(
                "slot-budget",
                f"agent job receipt {receipt_path.name} root 不是 object — 不用它釋放 slot",
            )
            continue
        if data.get("schema_version") != 2:
            if _legacy_agent_job_receipt(data, now=now):
                continue
            warn(
                "slot-budget",
                f"agent job receipt {receipt_path.name} schema 不完整 — 不用它釋放 slot",
            )
            quarantine_invalid(receipt_path, data)
            continue
        cwd = data.get("cwd")
        execution_id = data.get("execution_id")
        state = data.get("state")
        runner_pid = data.get("runner_pid")
        started_epoch = _iso_epoch(data.get("started_at"))
        finished_epoch = _iso_epoch(data.get("finished_at"))
        valid_identity = (
            isinstance(cwd, str)
            and bool(cwd.strip())
            and isinstance(execution_id, str)
            and bool(execution_id.strip())
            and state in {"running", "terminal", "termination_unverified"}
            and _is_int(runner_pid)
            and runner_pid > 0
            and started_epoch is not None
            and started_epoch <= now + MAX_RECEIPT_CLOCK_SKEW_S
        )
        valid_running = (
            state == "running"
            and data.get("finished_at") is None
            and data.get("termination_confirmed") is None
            and data.get("exit_code") is None
            and data.get("runner_exit_code") is None
        )
        valid_settled = (
            state in {"terminal", "termination_unverified"}
            and finished_epoch is not None
            and started_epoch is not None
            and started_epoch <= finished_epoch <= now + MAX_RECEIPT_CLOCK_SKEW_S
            and isinstance(data.get("timed_out"), bool)
            and _is_int(data.get("exit_code"))
            and _is_int(data.get("runner_exit_code"))
            and isinstance(data.get("termination_confirmed"), bool)
            and (
                (state == "terminal" and data.get("termination_confirmed") is True)
                or (
                    state == "termination_unverified"
                    and data.get("termination_confirmed") is False
                )
            )
        )
        if not valid_identity or not (valid_running or valid_settled):
            warn(
                "slot-budget",
                f"agent job receipt {receipt_path.name} lifecycle schema 無效 — "
                "不用它釋放 slot",
            )
            quarantine_invalid(receipt_path, data)
            continue
        try:
            key = Path(cwd).resolve()
        except (OSError, ValueError) as exc:
            warn(
                "slot-budget",
                f"agent job receipt {receipt_path.name} cwd 無效 ({exc}) — "
                "不用它釋放 slot",
            )
            continue
        generation = {
            "receipt": str(receipt_path),
            "schema_version": 2,
            "execution_id": execution_id,
            "state": state,
            "runner_pid": runner_pid,
            "started_at": data["started_at"],
            "started_epoch": started_epoch,
            "finished_at": data.get("finished_at"),
            "finished_epoch": finished_epoch,
            "termination_confirmed": data.get("termination_confirmed"),
            "timed_out": data.get("timed_out") is True,
            "exit_code": data.get("exit_code"),
            "runner_exit_code": data.get("runner_exit_code"),
            "result_artifact_exists": data.get("result_artifact_exists") is True,
            "validation_ok": data.get("validation_ok") is True,
        }
        previous = latest.get(key)
        if previous is not None and previous["started_epoch"] >= started_epoch:
            continue
        latest[key] = generation
    return latest


def worktree_slots(
    now: float | None = None,
    worktrees_dir: Path | None = None,
    agent_jobs_dir: Path | None = None,
) -> list[dict]:
    """Join artifact custody to formal execution leases; artifacts never own slots."""
    now = time.time() if now is None else now
    # Resolved at call time, not bound as a default: a default arg freezes the
    # module constant and makes the dir un-injectable in tests.
    worktrees_dir = WORKTREES_DIR if worktrees_dir is None else worktrees_dir
    jobs_by_cwd = agent_job_leases(agent_jobs_dir, now=now)
    slots: list[dict] = []
    if not worktrees_dir.exists():
        return slots

    for path in sorted(worktrees_dir.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        worktree_progress_at = max(
            _last_commit_epoch(path),
            _last_git_metadata_mtime(path),
            _last_dirty_mtime(path),
        )
        job = jobs_by_cwd.get(path.resolve())
        lease_progress_at = 0.0
        if job and job["state"] in {"running", "invalid"}:
            lease_progress_at = job["started_epoch"]
        elif job and job["state"] == "termination_unverified":
            lease_progress_at = job["finished_epoch"]
        progress_at = max(worktree_progress_at, lease_progress_at)
        idle_hours = (now - progress_at) / 3600.0 if progress_at else float("inf")
        terminal_release = bool(
            job
            and job["state"] == "terminal"
            and job["termination_confirmed"] is True
            and job["finished_epoch"] >= worktree_progress_at
        )
        active_lease = bool(
            job
            and job["state"] in {"running", "termination_unverified", "invalid"}
        )
        slot = {
            "name": path.name,
            "progress_at": progress_at or None,
            "idle_hours": None if idle_hours == float("inf") else round(idle_hours, 1),
            "live": active_lease and idle_hours < STALE_HOURS,
        }
        if terminal_release:
            slot["release_reason"] = "terminal_agent_job"
            slot["terminal_job"] = job
        elif active_lease:
            slot["active_job"] = job
            if idle_hours >= STALE_HOURS:
                slot["release_reason"] = "no_progress_timeout"
        elif job and job["state"] == "terminal":
            slot["release_reason"] = "unowned_progress_after_terminal"
        else:
            slot["release_reason"] = "artifact_without_execution_lease"
        slots.append(slot)
    return slots


def agent_slots(now: float | None = None, agents_dir: Path | None = None) -> list[dict]:
    """Agent records claiming to be running. A record whose file has not been
    touched in STALE_HOURS is the same 'artifact nobody expires' bug as a hung
    worktree, so it stops holding a slot too."""
    now = time.time() if now is None else now
    agents_dir = AGENTS_DIR if agents_dir is None else agents_dir
    slots: list[dict] = []
    if not agents_dir.exists():
        return slots

    for f in sorted(agents_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError) as exc:
            warn(
                "slot-budget",
                f"agent record 讀不到 {f.name} "
                f"({type(exc).__name__}: {exc}) — 不計入佔用",
            )
            continue
        if not isinstance(data, dict):
            warn(
                "slot-budget",
                f"agent record {f.name} root 不是 object — 不計入佔用",
            )
            continue
        status_raw = data.get("status")
        if not isinstance(status_raw, str):
            warn(
                "slot-budget",
                f"agent record {f.name} status 不是 string — 不計入佔用",
            )
            continue
        status = status_raw.lower()
        if status not in ACTIVE_AGENT_STATUSES:
            continue
        try:
            idle_hours = (now - f.stat().st_mtime) / 3600.0
        except OSError as exc:
            warn("slot-budget", f"agent record stat 失敗 {f.name} ({exc}) — 不計入佔用")
            continue
        slots.append({
            "name": f.stem,
            "status": status,
            "task_type": data.get("task_type"),
            "started_at": data.get("started_at") or data.get("claimed_at"),
            "idle_hours": round(idle_hours, 1),
            "live": idle_hours < STALE_HOURS,
        })
    return slots


def occupancy(
    now: float | None = None,
    *,
    worktrees_dir: Path | None = None,
    agents_dir: Path | None = None,
    agent_jobs_dir: Path | None = None,
) -> dict:
    """How many slots are actually held. Single owner — do not re-derive."""
    # AGENTS_DIR is intentionally monkeypatchable: existing callers use it to
    # establish an isolated ops-state root.  Resolve it before deriving the
    # sibling execution-receipt directory, otherwise a clean fixture can still
    # leak reads from live storage/ops/agent_jobs.
    effective_agents_dir = AGENTS_DIR if agents_dir is None else agents_dir
    if agent_jobs_dir is None:
        agent_jobs_dir = effective_agents_dir.parent / "agent_jobs"
    wts = worktree_slots(
        now=now,
        worktrees_dir=worktrees_dir,
        agent_jobs_dir=agent_jobs_dir,
    )
    agents = agent_slots(now=now, agents_dir=effective_agents_dir)
    live_wt = [w["name"] for w in wts if w["live"]]
    live_agents = [a["name"] for a in agents if a["live"]]
    stale = [w for w in wts if not w["live"]] + [a for a in agents if not a["live"]]

    return {
        # Keys `worktrees` / `active_agents` / `occupied` are the legacy shape
        # `continue_task_dispatch` and its report consumers already read.
        "worktrees": live_wt,
        "active_agents": live_agents,
        "occupied": len(live_wt) + len(live_agents),
        "stale": stale,
        "worktree_detail": wts,
        "agent_detail": agents,
    }


def _open_incident_signal(tasks_path: Path) -> dict | None:
    """The oldest unclosed PHASE-Z stuck-path incident, or None.

    Read-only, and `open_incidents` never raises: a queue this cannot parse must
    not take dispatch down. Oldest-first so the reason string names the incident
    that has been costing capacity longest, not whichever one sorted last.

    An incident whose remaining paths are all *live authoring* is skipped: the
    files are covered and somebody is still editing them, which is not the
    "nobody is coming back for these" condition the de-rate exists to price. That
    verdict is computed by `foreign_incident.reconcile_incidents` each fire and
    stamped into the payload — this stays read-only and runs no git. Missing flag
    means never reconciled, and the fail-safe there is to de-rate (an unknown
    stuck set is exactly what the mechanism is for).
    """
    incidents = [t for t in open_incidents(tasks_path)
                 if (t.get("payload") or {}).get("derates", True)]
    if not incidents:
        return None
    incidents.sort(key=lambda t: str(t.get("created_at") or ""))
    return incidents[0]


def budget(
    tasks_path: Path = TASKS_PATH,
    state_path: Path = STATE_PATH,
    *,
    now: float | None = None,
    worktrees_dir: Path | None = None,
    agents_dir: Path | None = None,
    agent_jobs_dir: Path | None = None,
) -> dict:
    pending = _pending_by_priority(tasks_path)
    blocked = _auth_blocked(state_path)
    incident = _open_incident_signal(tasks_path)
    p1 = pending.get(1, 0)

    if blocked:
        cap, reason = DERATE_CAP, "auth/quota blocked — de-rated, 先保住 loop 存活"
    elif incident is not None:
        payload = incident.get("payload") or {}
        stuck_n = len(payload.get("paths") or [])
        cap = DERATE_CAP
        reason = (
            f"PHASE-Z 卡住檔案 incident {incident.get('id')} 未關"
            f"（fingerprint {payload.get('fingerprint')}，{stuck_n} 個檔案無人收）"
            " — de-rated，先收拾工作區再加班"
        )
    elif p1 >= P1_SURGE_AT:
        cap, reason = SURGE_CAP, f"P1 backlog={p1} — surge；slot 5-6 只給 P1/P2"
    else:
        cap, reason = BASE_CAP, f"baseline（P1 backlog={p1}）"

    occ = occupancy(
        now=now,
        worktrees_dir=worktrees_dir,
        agents_dir=agents_dir,
        agent_jobs_dir=agent_jobs_dir,
    )
    return {
        "cap": cap,
        "reason": reason,
        "p1_only_slots": max(0, cap - BASE_CAP),
        "auth_blocked": blocked,
        "open_incident": None if incident is None else {
            "task_id": incident.get("id"),
            "fingerprint": (incident.get("payload") or {}).get("fingerprint"),
            "paths": len((incident.get("payload") or {}).get("paths") or []),
        },
        "pending_by_priority": {str(k): v for k, v in sorted(pending.items())},
        "occupied": occ["occupied"],
        "free": max(0, cap - occ["occupied"]),
        "occupancy": occ,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", action="store_true", help="只印 cap 整數")
    args = ap.parse_args()
    result = budget()
    print(result["cap"] if args.cap else json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
