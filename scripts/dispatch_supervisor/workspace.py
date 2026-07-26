"""Workspace — producer-scoped execution isolation for dispatch fires (WS-B pilot).

Why this module exists (refactor_plan_ops_master_2026_07 §WS-B; design:
docs/dispatch-writer-isolation-design.md): PHASE-Z's fire-start baseline can only
GUESS which dirty bytes a fire produced — "ownership must be produced by
execution isolation, not inferred by a cleanup layer afterwards" (external
adjudication, 2026-07). Six-plus authorship incidents share that single root
cause. The pilot gives every admitted fire (when `writer_isolation.mode ==
"pilot"`) its own registered linked worktree; the slot prompt directs all
isolated-lane repo-byte writes (platform_ops / governance code, config, docs,
tests) into it. Anything merged from that branch is that fire's BY CONSTRUCTION
— no snapshot arithmetic involved.

Mechanism reuse (deliberately zero new git machinery):

  - creation:   `git worktree add` under `.claude/worktrees/` — the exact
                substrate the experiment lane already uses (compute_queue
                enqueue-agent --cwd + run_agent_job --cwd), serialized through
                `volpred.ops.git_writer_lock` like every other repo mutation.
  - validation: `is_registered_linked_worktree` — same door run_agent_job uses.
  - merge gate: phase_z's `_resolve_test_targets` (changed files → concrete test
                files, single owner of that mapping) + `_run_clone_pytest`
                executed INSIDE the workspace checkout. Green (or provably no
                coverage to run) is required before integration.
  - landing:    `bash scripts/merge_worktree.sh <name>` — the battle-hardened
                integration door (K1032/K1143/K1262/K1618 defence layers),
                NOT a new merge implementation.

No-deadlock guarantee (owner hard rule, plan §2 principle 7): a red gate, a
failed merge, or a fire that died mid-flight NEVER strands its output. The
finalizer checkpoints uncommitted bytes on the producer branch, persists that
receipt, opens an idempotent aggregate adjudication task in the canonical
pending queue, then persists the task binding before the registered worktree is
removed without force. Failures therefore cannot exhaust live capacity or lose
their only recovery identity. Orphans from a supervisor crash are swept on the
next allocation pass through the same finalizer.

Cost controls (design §2 measured-cost snapshot): at most ONE live isolated
fire at a time (`active_cap`), a total registered-workspace cap, and a free-disk
floor below which allocation fails CLOSED (the fire still runs, just without
isolation — PHASE-Z's baseline fallback continues to cover that residue lane).
Every allocation/finalization appends a JSONL receipt with real measured
durations — never fabricated numbers.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from volpred.canonical_write import canonical_writes_disabled
from volpred.ops.git_writer_lock import (
    GitWriterLockError,
    git_writer_lock,
    is_registered_linked_worktree,
)
from volpred.ops.next_tasks import append_task_record
from volpred.ops.remediation_throttle import INCIDENT_ADJUDICATION_SOURCE

from . import phase_z

LOG = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DAEMON_ID = "volpred-dispatch-supervisor"

WORKTREES_RELDIR = Path(".claude") / "worktrees"
WORKSPACE_PREFIX = "dispatch-"
RECEIPTS_RELPATH = Path("storage") / "ops" / "dispatch_workspace_receipts.jsonl"
QUEUE_RELPATH = Path("storage") / "next_tasks.json"
MERGE_SCRIPT_RELPATH = Path("scripts") / "merge_worktree.sh"

_GIT_TIMEOUT_S = 300          # worktree add checks out the full tree (multi-GB)
_MERGE_TIMEOUT_S = 900
_GATE_TIMEOUT_S = phase_z._TEST_GATE_TIMEOUT_S

_DEFAULT_LANES = ("platform_ops",)
_DEFAULT_MAX_TOTAL = 3        # registered dispatch-* worktrees, incl. kept-for-remediation
_DEFAULT_DISK_FLOOR_GIB = 20.0
_ISOLATION_MODES = ("off", "pilot")

# Worker outcomes whose output may be integrated. Everything else (hang, retry
# exhaustion, auth/quota, superseded, orphan sweep) produced bytes nobody
# verified end-of-turn — those go to remediation, never silently to main.
_MERGEABLE_OUTCOMES = {"success", "codex_failover_recovered"}

_JOB8_RE = re.compile(
    r"^dispatch-slot-\d+-([0-9a-f]{8})(?:-[a-z0-9][a-z0-9._-]*)?$"
)


# ── config ───────────────────────────────────────────────────────────────────

def load_isolation_config(*, schedules_path: Path) -> dict[str, Any]:
    """`writer_isolation` block from the supervisor daemon entry.

    Hot-reloaded every tick like max_slots/pregate — flipping off→pilot (or
    adding "governance" to lanes for wave 2) is a config edit, no restart.
    Fail-open to mode "off": a broken config must never block dispatch, it just
    loses isolation for the fire (PHASE-Z fallback still covers it).
    """
    fallback = {
        "mode": "off",
        "lanes": list(_DEFAULT_LANES),
        "max_total": _DEFAULT_MAX_TOTAL,
        "disk_floor_gib": _DEFAULT_DISK_FLOOR_GIB,
    }
    try:
        data = json.loads(Path(schedules_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        LOG.warning("load_isolation_config fail-open mode=off: %s", exc)
        return fallback
    entry = next(
        (
            item for item in (data.get("daemons") or [])
            if isinstance(item, dict) and item.get("id") == DAEMON_ID
        ),
        None,
    )
    cfg = (entry or {}).get("writer_isolation")
    if not isinstance(cfg, dict):
        return fallback
    mode = str(cfg.get("mode", "off")).lower()
    if mode not in _ISOLATION_MODES:
        LOG.warning("writer_isolation mode %r invalid — fail-open mode=off", mode)
        mode = "off"
    lanes = cfg.get("lanes")
    if not isinstance(lanes, list) or not all(isinstance(x, str) for x in lanes) or not lanes:
        lanes = list(_DEFAULT_LANES)
    try:
        max_total = max(1, int(cfg.get("max_total", _DEFAULT_MAX_TOTAL)))
    except (TypeError, ValueError):
        max_total = _DEFAULT_MAX_TOTAL
    try:
        disk_floor_gib = float(cfg.get("disk_floor_gib", _DEFAULT_DISK_FLOOR_GIB))
    except (TypeError, ValueError):
        disk_floor_gib = _DEFAULT_DISK_FLOOR_GIB
    return {"mode": mode, "lanes": lanes, "max_total": max_total,
            "disk_floor_gib": disk_floor_gib}


# ── plumbing ─────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_repo_guarded(repo_root: Path) -> bool:
    """True when a TEST process is about to mutate the real checkout.

    `guard_canonical_write` only covers canonical FILE writers; `git worktree
    add/remove` is a subprocess mutation it never sees. Same class gate as
    project_canonical_write_test_leak_gate: under VOLPRED_NO_CANONICAL_WRITE=1
    (armed by conftest for every pytest run) the real repo is off limits while
    hermetic tmp repos stay writable.
    """
    return canonical_writes_disabled() and Path(repo_root).resolve() == ROOT.resolve()


def _git(repo: Path, *args: str, runner=subprocess.run,
         timeout_s: float = _GIT_TIMEOUT_S) -> subprocess.CompletedProcess:
    return runner(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=timeout_s, check=False,
    )


def _append_receipt(repo_root: Path, payload: dict[str, Any]) -> bool:
    """Durably append one workspace event; return whether fsync succeeded."""
    dest = Path(repo_root) / RECEIPTS_RELPATH
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {"receipt_id": uuid.uuid4().hex, "at": _now_iso(), **payload},
            ensure_ascii=False,
        )
        with dest.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return True
    except OSError as exc:
        LOG.warning("workspace receipt append failed (%s): %s", dest, exc)
        return False


def _latest_terminal_receipt(
    repo_root: Path,
    workspace_name: str,
) -> dict[str, Any] | None:
    """Return the last durable finalization for one workspace, if any."""
    source = Path(repo_root) / RECEIPTS_RELPATH
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:  # silent-ok: no prior receipt means this is the first finalization
        return None
    except OSError as exc:
        LOG.warning("workspace terminal receipt read failed (%s): %s", source, exc)
        return None
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            LOG.warning("workspace terminal receipt line unreadable (%s): %s", source, exc)
            continue
        if (
            isinstance(event, dict)
            and event.get("event") in {"finalized", "released"}
            and event.get("workspace") == workspace_name
            and (
                event.get("event") == "released"
                or event.get("disposition")
                in {"empty_removed", "merged", "remediation_opened"}
            )
        ):
            return {
                key: value
                for key, value in event.items()
                if key not in {"at", "event", "job_id", "worker_outcome"}
            }
    return None


def _active_allocated_workspace_names(repo_root: Path) -> set[str]:
    """Workspace identities declared by allocator receipts and not released."""
    source = Path(repo_root) / RECEIPTS_RELPATH
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:  # silent-ok: no allocator receipt means no owned workspace
        return set()
    except OSError as exc:
        LOG.warning("workspace allocation receipt read failed (%s): %s", source, exc)
        return set()
    active: set[str] = set()
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            LOG.warning("workspace allocation receipt line unreadable (%s): %s", source, exc)
            continue
        if not isinstance(event, dict):
            continue
        name = str(event.get("workspace") or event.get("name") or "")
        if not name:
            continue
        event_name = event.get("event")
        if event_name in {"allocation_intent", "allocated"}:
            active.add(name)
        elif event_name in {"allocation_aborted", "released"} or (
            event_name == "finalized"
            and event.get("disposition") in {"empty_removed", "merged"}
        ):
            active.discard(name)
    return active


def _registered_dispatch_worktrees(repo_root: Path, *, runner=subprocess.run) -> list[Path]:
    proc = _git(repo_root, "worktree", "list", "--porcelain",
                runner=runner, timeout_s=30)
    if proc.returncode != 0:
        LOG.warning("workspace: worktree list rc=%d: %s",
                    proc.returncode, (proc.stderr or "")[-200:])
        return []
    found: list[Path] = []
    marker = str(Path(repo_root) / WORKTREES_RELDIR) + os.sep
    allocated = _active_allocated_workspace_names(repo_root)
    for line in (proc.stdout or "").splitlines():
        if not line.startswith("worktree "):
            continue
        path = Path(line.removeprefix("worktree "))
        # A path shape is not provenance. Only the allocator's durable receipt
        # declares lifecycle ownership; other dispatch/compute worktrees may
        # share this historical directory prefix.
        if str(path).startswith(marker) and path.name in allocated:
            found.append(path)
    return found


def _worktree_branch(repo_root: Path, wt_path: Path, *, runner=subprocess.run) -> str | None:
    proc = _git(wt_path, "rev-parse", "--abbrev-ref", "HEAD", runner=runner, timeout_s=30)
    if proc.returncode != 0:
        return None
    branch = (proc.stdout or "").strip()
    return branch or None


def _du_bytes(path: Path, *, runner=subprocess.run) -> int | None:
    """Measured allocated bytes for S0 telemetry (`du -sk`, not inference)."""
    try:
        proc = runner(
            ["du", "-sk", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.warning("workspace du probe failed for %s: %s", path, exc)
        return None
    if proc.returncode != 0:
        LOG.warning("workspace du probe rc=%s for %s", proc.returncode, path)
        return None
    try:
        kib = int((proc.stdout or "").split()[0])
    except (IndexError, ValueError):
        LOG.warning("workspace du probe unreadable for %s", path)
        return None
    return kib * 1024


# ── allocation ───────────────────────────────────────────────────────────────

def allocate_workspace(
    *,
    repo_root: Path,
    slot_id: str,
    job_id: str,
    config: dict[str, Any],
    active_isolated: int = 0,
    runner=subprocess.run,
) -> dict[str, Any] | None:
    """Machine-build this fire's registered worktree BEFORE the agent starts.

    Returns a JSON-serializable workspace receipt (stored on the state job
    entry, echoed into the slot prompt) or None when isolation is skipped —
    the fire then runs unisolated and PHASE-Z's baseline fallback covers it.
    The name/branch are machine-derived from slot+job identity so an agent can
    never choose (or spoof) its own ownership namespace.
    """
    repo_root = Path(repo_root)
    if config.get("mode") != "pilot":
        return None
    if _canonical_repo_guarded(repo_root):
        LOG.warning("workspace allocation refused: test process on canonical checkout")
        return None

    def _skip(reason: str, **extra: Any) -> None:
        LOG.warning("workspace allocation skipped (%s) job_id=%s — firing unisolated",
                    reason, job_id[:8])
        _append_receipt(repo_root, {
            "event": "allocation_skipped", "reason": reason,
            "job_id": job_id, "slot_id": slot_id, **extra,
        })

    if active_isolated > 0:
        _skip("active_cap", active=active_isolated)
        return None
    try:
        free_gib = shutil.disk_usage(repo_root).free / 2**30
    except OSError as exc:  # silent-ok: _skip() logs WARNING + appends a JSONL receipt
        _skip("disk_probe_error", error=str(exc))
        return None
    floor = float(config.get("disk_floor_gib", _DEFAULT_DISK_FLOOR_GIB))
    if free_gib < floor:
        # design §2: fail CLOSED on low disk — do not create-then-pray.
        _skip("disk_floor", free_gib=round(free_gib, 1), floor_gib=floor)
        return None
    existing = _registered_dispatch_worktrees(repo_root, runner=runner)
    max_total = int(config.get("max_total", _DEFAULT_MAX_TOTAL))
    if len(existing) >= max_total:
        _skip("total_cap", existing=len(existing), max_total=max_total)
        return None

    name = f"{WORKSPACE_PREFIX}{slot_id}-{job_id[:8]}"
    path = repo_root / WORKTREES_RELDIR / name
    branch = f"worktree-{name}"
    if path.exists():
        _skip("name_collision", path=str(path))
        return None

    wall_start = _now_iso()
    started = time.monotonic()
    allocation_identity = {
        "workspace": name,
        "path": str(path),
        "branch": branch,
        "job_id": job_id,
        "slot_id": slot_id,
        "actor": f"dispatch-workspace:{job_id[:8]}",
    }
    if not _append_receipt(
        repo_root,
        {
            "event": "allocation_intent",
            "cleanup": "not_created",
            **allocation_identity,
        },
    ):
        LOG.error("workspace allocation intent not durable for %s", name)
        return None
    try:
        with git_writer_lock(repo_root, actor=f"dispatch-workspace:{job_id[:8]}",
                             timeout_s=60):
            add = _git(repo_root, "worktree", "add", "-b", branch, str(path), "HEAD",
                       runner=runner)
    except GitWriterLockError as exc:  # silent-ok: _skip() logs WARNING + appends a JSONL receipt
        _skip("writer_lock_busy", error=str(exc)[:200])
        return None
    except (subprocess.TimeoutExpired, OSError) as exc:  # silent-ok: _skip() logs WARNING + appends a JSONL receipt
        _skip("worktree_add_error", error=str(exc)[:200])
        return None
    if add.returncode != 0:
        _skip("worktree_add_error", rc=add.returncode,
              error=(add.stderr or "")[-300:])
        _append_receipt(
            repo_root,
            {"event": "allocation_aborted", "cleanup": "not_created",
             **allocation_identity},
        )
        return None
    setup_s = round(time.monotonic() - started, 2)

    if not is_registered_linked_worktree(repo_root, path):
        # Should be unreachable right after a successful add; treat as a broken
        # allocation and leave the directory for the orphan sweep (never rm -rf).
        _skip("verify_failed", path=str(path))
        return None
    base = _git(path, "rev-parse", "HEAD", runner=runner, timeout_s=30)
    base_sha = (base.stdout or "").strip() if base.returncode == 0 else ""
    common = _git(
        path,
        "rev-parse",
        "--git-common-dir",
        runner=runner,
        timeout_s=30,
    )
    common_dir = (common.stdout or "").strip() if common.returncode == 0 else ""
    disk_bytes = _du_bytes(path, runner=runner)
    wall_end = _now_iso()
    try:
        free_gib_after = shutil.disk_usage(repo_root).free / 2**30
    except OSError as exc:
        LOG.warning("workspace post-allocation disk probe failed: %s", exc)
        free_gib_after = free_gib
    workspace = {
        "name": name,
        "path": str(path),
        "branch": branch,
        "base_sha": base_sha,
        "lanes": list(config.get("lanes") or _DEFAULT_LANES),
        "created_at": _now_iso(),
        "setup_s": setup_s,
    }
    allocated = _append_receipt(repo_root, {
        "event": "allocated",
        "wall_start": wall_start,
        "wall_end": wall_end,
        "disk_bytes": disk_bytes,
        "free_gib_before": round(free_gib, 3),
        "free_gib_after": round(free_gib_after, 3),
        "disk_delta_gib": round(free_gib - free_gib_after, 3),
        "git_common_dir": common_dir,
        "write_intent": "repo_patch",
        "task_id": None,
        "claim_session_id": None,
        "task_binding_status": "pending_worker_claim",
        "declared_output_paths": [],
        "denied_canonical_paths": ["storage/**"],
        **allocation_identity,
        **workspace,
    })
    if not allocated:
        # An unreceipted checkout has no durable ownership identity. Roll the
        # allocation back while the path is still clean; never dispatch into it.
        try:
            with git_writer_lock(
                repo_root,
                actor=f"dispatch-workspace-receipt-rollback:{job_id[:8]}",
                timeout_s=60,
            ):
                removed = _git(
                    repo_root,
                    "worktree",
                    "remove",
                    str(path),
                    runner=runner,
                    timeout_s=60,
                )
                deleted = _git(
                    repo_root,
                    "branch",
                    "-D",
                    branch,
                    runner=runner,
                    timeout_s=30,
                )
                if removed.returncode == 0 and deleted.returncode == 0:
                    _append_receipt(
                        repo_root,
                        {
                            "event": "allocation_aborted",
                            "cleanup": "removed",
                            "reason": "allocated_receipt_failed",
                            **allocation_identity,
                        },
                    )
                else:
                    LOG.error(
                        "workspace receipt rollback incomplete name=%s remove_rc=%s "
                        "branch_rc=%s",
                        name,
                        removed.returncode,
                        deleted.returncode,
                    )
        except GitWriterLockError as exc:
            LOG.error("workspace allocation receipt rollback lock failed: %s", exc)
        return None
    LOG.info("workspace allocated job_id=%s path=%s branch=%s setup=%.1fs",
             job_id[:8], path, branch, setup_s)
    return workspace


# ── merge gate ───────────────────────────────────────────────────────────────

def _workspace_changed_paths(repo_root: Path, workspace: dict[str, Any],
                             *, runner=subprocess.run) -> list[str]:
    """Union of committed (merge-base..branch) and uncommitted workspace paths."""
    wt = Path(workspace["path"])
    changed: set[str] = set()
    diff = _git(repo_root, "diff", "--name-only", f"main...{workspace['branch']}",
                runner=runner, timeout_s=60)
    if diff.returncode == 0:
        changed.update(p for p in (diff.stdout or "").splitlines() if p)
    else:
        LOG.warning("workspace: branch diff rc=%d: %s",
                    diff.returncode, (diff.stderr or "")[-200:])
    status = _git(wt, "status", "--porcelain", "-z", "--untracked-files=all",
                  runner=runner, timeout_s=60)
    if status.returncode == 0:
        changed.update(phase_z._porcelain_paths(status.stdout or ""))
    return sorted(changed)


def _run_merge_gate(*, repo_root: Path, workspace: dict[str, Any],
                    runner=subprocess.run) -> dict[str, Any]:
    """Targeted pytest INSIDE the workspace checkout. Green (rc=0) or provable
    no-coverage passes; anything else is red. Reuses phase_z's changed-file →
    test-file mapping so there is exactly one owner of that policy."""
    wt = Path(workspace["path"])
    changed = _workspace_changed_paths(repo_root, workspace, runner=runner)
    code_files = [p for p in changed if p.startswith(phase_z._GATED_CODE_PREFIXES)]
    if not code_files:
        return {"verdict": "no_coverage", "rc": None, "targets": [],
                "changed": changed, "output_tail": "", "duration_s": 0.0}
    plan = phase_z._resolve_test_targets(wt, code_files)
    targets = plan["targets"]
    if not targets:
        return {"verdict": "no_coverage", "rc": None, "targets": [],
                "changed": changed, "unmapped": plan["unmapped"],
                "output_tail": "", "duration_s": 0.0}
    started = time.monotonic()
    result = phase_z._run_clone_pytest(
        wt, targets=targets, k_expr=None, test_runner=runner,
        timeout_s=_GATE_TIMEOUT_S,
    )
    duration_s = round(time.monotonic() - started, 2)
    rc = result.get("returncode")
    if rc == 0:
        verdict = "green"
    elif rc == phase_z._PYTEST_NO_TESTS_COLLECTED:
        verdict = "no_coverage"
    else:
        verdict = "red"
    return {"verdict": verdict, "rc": rc, "targets": targets, "changed": changed,
            "output_tail": (result.get("output") or "")[-1500:],
            "duration_s": duration_s}


def _run_merge_script(*, repo_root: Path, workspace: dict[str, Any],
                      runner=subprocess.run) -> dict[str, Any]:
    """Land the branch through the ONE existing integration door."""
    script = Path(repo_root) / MERGE_SCRIPT_RELPATH
    if not script.is_file():
        return {"ok": False, "rc": None, "reason": "merge_script_missing",
                "output_tail": str(script)}
    try:
        proc = runner(
            ["/bin/bash", str(script), workspace["name"]],
            capture_output=True, text=True, timeout=_MERGE_TIMEOUT_S,
            cwd=str(repo_root), check=False,  # K1618: never from inside the worktree
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "rc": None, "reason": "merge_timeout", "output_tail": ""}
    except OSError as exc:
        return {"ok": False, "rc": None, "reason": "merge_spawn_error",
                "output_tail": str(exc)[:300]}
    tail = ((proc.stdout or "") + (proc.stderr or ""))[-1500:]
    if proc.returncode != 0:
        return {"ok": False, "rc": proc.returncode, "reason": "merge_failed",
                "output_tail": tail}
    return {"ok": True, "rc": 0, "reason": "merged", "output_tail": tail}


def _open_remediation_task(
    *,
    repo_root: Path,
    workspace: dict[str, Any],
    reason: str,
    detail: str,
    queue_path: Path | None = None,
) -> dict[str, Any]:
    """The no-deadlock exit, incident-first (plan §3.3 ``worker_orphaned``).

    The old shape — one ``wsb_remed_<name>`` task per workspace — was plan
    §2.3's per-instance bug: 16 tasks, zero duplicates, one root cause.  Now
    every unmergeable workspace registers as an INSTANCE of the single
    ``worker_orphaned`` incident, and the incident carries at most ONE
    aggregate adjudication task per episode (deterministic id ⇒ idempotent
    across finalize/orphan-sweep re-runs).
    """
    from volpred.ops import incident as incident_store

    queue = Path(queue_path) if queue_path is not None else Path(repo_root) / QUEUE_RELPATH
    store = Path(repo_root) / "storage" / "ops" / "incidents.json"
    try:
        outcome = incident_store.route_breach(
            store,
            kind="worker_orphaned",
            instance_key=workspace["name"],
            instance_detail={
                "worktree": workspace["path"],
                "branch": workspace["branch"],
                "base_sha": workspace.get("base_sha", ""),
                "checkpoint_commit": workspace.get("checkpoint_commit", ""),
                "reason": reason,
                "detail_tail": detail[-400:],
            },
            details=f"WS-B workspace {workspace['name']} unmergeable ({reason})",
            task_status_probe=incident_store.next_tasks_status_probe(queue),
        )
    except Exception as exc:  # noqa: BLE001 — observable; next finalize pass retries
        LOG.error("workspace incident routing FAILED for %s: %s", workspace["name"], exc)
        return {"task_id": None, "created": False, "error": str(exc)[:300]}

    incident_id = str(outcome.get("incident_id") or "")
    action = str(outcome.get("action") or "")
    if action == "escalate":
        receipt = incident_store.actuate_escalation(
            store, incident_id, queue_path=queue
        )
        return {
            "task_id": receipt.get("root_cause_task_id"),
            "created": bool(receipt.get("task_created")),
            "incident_id": incident_id,
            "action": action,
        }
    if action != "create_task":
        # Aggregate task already in flight (or incident suppressed): the new
        # instance is recorded on the incident; no per-instance task is minted.
        return {
            "task_id": outcome.get("active_task_id"),
            "created": False,
            "incident_id": incident_id,
            "action": action,
        }

    record = {
        "id": str(outcome.get("suggested_task_id")),
        "title": (
            f"WS-B workspace 批次裁決（worker_orphaned，episode "
            f"{outcome.get('episode_count')}）"
        ),
        "description": (
            "一個或多個 producer-scoped workspace 無法自動 merge。branch 與 "
            "checkpoint SHA 一律保留；live worktree 在 receipt 持久化後可被釋放。這是 incident "
            f"`{incident_id}` 的唯一 aggregate 裁決任務 —— 全部未清實例見 "
            "`storage/ops/incidents.json` 該 row 的 instances[]（cleared_at 為空者）。\n"
            "若 worktree 已釋放，先依 instance.branch 重建："
            "`git worktree add .claude/worktrees/<name> <branch>`，並以 "
            "instance.checkpoint_commit 回讀確認。逐實例三選一：修復後 "
            "`bash scripts/merge_worktree.sh <name>`；"
            "path-scoped 抽取可救檔；或記明理由後 plain `git worktree remove` + "
            "`git branch -D`。裁決完把該實例自然清除（成功 merge 會自動 "
            "clear_instance）。來源: scripts/dispatch_supervisor/workspace.py。"
        ),
        "task_type": "platform_ops",
        "priority": 2,
        "status": "pending",
        "dispatch_lane": "main_thread",
        "source": INCIDENT_ADJUDICATION_SOURCE,
        "incident_id": incident_id,
        "created_at": _now_iso(),
    }
    try:
        created_record, created = append_task_record(record, path=queue, if_exists="skip")
    except (OSError, ValueError) as exc:
        # Queue write failed — the receipt + alert-visible log line keep this
        # observable; the next finalize pass (orphan sweep) retries the append.
        LOG.error("workspace remediation task append FAILED for %s: %s",
                  workspace["name"], exc)
        return {"task_id": None, "created": False, "error": str(exc)[:300]}
    if created_record.get("throttled_by_remediation_cap"):
        incident_store.record_throttled(store, incident_id)
        return {"task_id": None, "created": False, "incident_id": incident_id,
                "action": "throttled"}
    incident_store.bind_task(store, incident_id, str(created_record.get("id")))
    return {"task_id": created_record.get("id"), "created": created,
            "incident_id": incident_id, "action": action}


def _clear_workspace_instance(*, repo_root: Path, workspace_name: str) -> None:
    """Merged workspace ⇒ its ``worker_orphaned`` instance (if any) is cleared."""
    from volpred.ops import incident as incident_store

    store = Path(repo_root) / "storage" / "ops" / "incidents.json"
    try:
        incident_store.clear_instance(
            store,
            kind="worker_orphaned",
            instance_key=workspace_name,
            by="workspace_finalize",
        )
    except Exception as exc:  # noqa: BLE001 — bookkeeping; merge outcome already stands
        LOG.warning("workspace instance clear failed for %s: %s", workspace_name, exc)


def _receipt_exists(
    repo_root: Path,
    *,
    event_name: str,
    workspace_name: str,
    head_sha: str = "",
) -> bool:
    source = Path(repo_root) / RECEIPTS_RELPATH
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:  # silent-ok: no receipt store means no matching event
        return False
    except OSError as exc:
        LOG.warning("workspace receipt read failed (%s): %s", source, exc)
        return False
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            LOG.warning("workspace receipt line unreadable (%s): %s", source, exc)
            continue
        if (
            isinstance(event, dict)
            and event.get("event") == event_name
            and event.get("workspace") == workspace_name
            and (not head_sha or event.get("checkpoint_commit") == head_sha)
        ):
            return True
    return False


def _latest_workspace_event(
    repo_root: Path,
    *,
    event_name: str,
    workspace_name: str,
) -> dict[str, Any] | None:
    source = Path(repo_root) / RECEIPTS_RELPATH
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:  # silent-ok: no receipt store means no prior event
        return None
    except OSError as exc:
        LOG.warning("workspace event receipt read failed (%s): %s", source, exc)
        return None
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            LOG.warning("workspace event receipt line unreadable (%s): %s", source, exc)
            continue
        if (
            isinstance(event, dict)
            and event.get("event") == event_name
            and event.get("workspace") == workspace_name
        ):
            return event
    return None


def _checkpoint_workspace(
    *,
    repo_root: Path,
    workspace: dict[str, Any],
    reason: str,
    runner=subprocess.run,
) -> dict[str, Any]:
    """Preserve an unmerged producer result and durably receipt its branch.

    A registered worktree directory is a live execution resource, not the
    durable artifact.  The branch is the retrievable remediation artifact.  We
    checkpoint the exact dirty paths reported by the isolated checkout. This
    quarantine commit is not a formal landing and therefore uses ``--no-verify``:
    it preserves the exact red-gate bytes for adjudication. The checkout is not
    released here; a durable checkpoint receipt and remediation exit must exist
    first.
    """
    repo_root = Path(repo_root)
    wt = Path(workspace["path"])
    branch = str(workspace["branch"])
    name = str(workspace["name"])
    result: dict[str, Any] = {
        "ok": False,
        "branch": branch,
        "commit": "",
        "released": False,
    }
    try:
        with git_writer_lock(
            repo_root,
            actor=f"dispatch-workspace-checkpoint:{name}",
            timeout_s=60,
        ):
            status = _git(
                wt,
                "status",
                "--porcelain",
                "-z",
                "--untracked-files=all",
                runner=runner,
                timeout_s=60,
            )
            if status.returncode != 0:
                return {
                    **result,
                    "reason": "status_error",
                    "rc": status.returncode,
                }
            dirty_paths = sorted(
                set(phase_z._porcelain_paths(status.stdout or ""))
            )
            if dirty_paths:
                add = _git(
                    wt,
                    "add",
                    "--",
                    *dirty_paths,
                    runner=runner,
                    timeout_s=60,
                )
                if add.returncode != 0:
                    return {
                        **result,
                        "reason": "checkpoint_add_failed",
                        "rc": add.returncode,
                        "output_tail": (add.stderr or "")[-300:],
                    }
                commit = _git(
                    wt,
                    "-c",
                    "user.name=VolPred Dispatch",
                    "-c",
                    "user.email=dispatch@volpred.local",
                    "commit",
                    "--no-verify",
                    "-m",
                    f"checkpoint: preserve {name} after {reason}",
                    runner=runner,
                    timeout_s=60,
                )
                if commit.returncode != 0:
                    return {
                        **result,
                        "reason": "checkpoint_commit_failed",
                        "rc": commit.returncode,
                        "output_tail": (commit.stderr or commit.stdout or "")[-300:],
                    }
            head = _git(
                wt,
                "rev-parse",
                "HEAD",
                runner=runner,
                timeout_s=30,
            )
            if head.returncode != 0:
                return {
                    **result,
                    "reason": "checkpoint_readback_failed",
                    "rc": head.returncode,
                }
            checkpoint_sha = (head.stdout or "").strip()
    except GitWriterLockError as exc:
        return {**result, "reason": "writer_lock_busy", "error": str(exc)[:300]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {**result, "reason": "checkpoint_error", "error": str(exc)[:300]}

    if not _receipt_exists(
        repo_root,
        event_name="checkpointed",
        workspace_name=name,
        head_sha=checkpoint_sha,
    ) and not _append_receipt(
        repo_root,
        {
            "event": "checkpointed",
            "workspace": name,
            "branch": branch,
            "checkpoint_commit": checkpoint_sha,
            "reason": reason,
            "cleanup": "pending",
        },
    ):
        return {
            **result,
            "commit": checkpoint_sha,
            "reason": "checkpoint_receipt_failed",
        }

    return {
        **result,
        "ok": True,
        "commit": checkpoint_sha,
        "released": False,
        "reason": "checkpointed",
    }


def _release_checkpointed_workspace(
    *,
    repo_root: Path,
    workspace: dict[str, Any],
    reason: str,
    checkpoint: dict[str, Any],
    remediation: dict[str, Any],
    runner=subprocess.run,
) -> dict[str, Any]:
    """Free a checkout only after its durable branch receipt is readable."""
    name = str(workspace["name"])
    branch = str(workspace["branch"])
    checkpoint_sha = str(checkpoint.get("commit") or "")
    if not checkpoint.get("ok") or not _receipt_exists(
        repo_root,
        event_name="checkpointed",
        workspace_name=name,
        head_sha=checkpoint_sha,
    ):
        return {
            **checkpoint,
            "released": False,
            "reason": "checkpoint_not_durable",
        }
    binding = {
        "event": "remediation_bound",
        "workspace": name,
        "branch": branch,
        "checkpoint_commit": checkpoint_sha,
        "incident_id": remediation.get("incident_id"),
        "task_id": remediation.get("task_id"),
        "disposition": "remediation_opened",
        "reason": reason,
        "cleanup": "pending",
    }
    if not _receipt_exists(
        repo_root,
        event_name="remediation_bound",
        workspace_name=name,
        head_sha=checkpoint_sha,
    ) and not _append_receipt(repo_root, binding):
        return {
            **checkpoint,
            "released": False,
            "reason": "remediation_receipt_failed",
        }
    wt = Path(workspace["path"])
    try:
        with git_writer_lock(
            repo_root,
            actor=f"dispatch-workspace-release:{name}",
            timeout_s=60,
        ):
            remove = _git(
                repo_root,
                "worktree",
                "remove",
                str(wt),
                runner=runner,
                timeout_s=60,
            )
    except GitWriterLockError as exc:
        return {**checkpoint, "released": False, "reason": "writer_lock_busy",
                "error": str(exc)[:300]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {**checkpoint, "released": False, "reason": "release_error",
                "error": str(exc)[:300]}
    if remove.returncode != 0:
        return {
            **checkpoint,
            "released": False,
            "reason": "checkpoint_remove_failed",
            "rc": remove.returncode,
            "output_tail": (remove.stderr or "")[-300:],
        }
    released = _append_receipt(
        repo_root,
        {
            "event": "released",
            "workspace": name,
            "branch": branch,
            "checkpoint_commit": checkpoint_sha,
            "disposition": "remediation_opened",
            "reason": reason,
            "checkpoint": {
                **checkpoint,
                "released": True,
                "reason": "checkpointed",
            },
            "remediation": remediation,
            "cleanup": "removed",
        },
    )
    if not released:
        # The prior checkpoint receipt remains the durable recovery source.
        LOG.error("workspace released but release receipt failed for %s", name)
        return {
            **checkpoint,
            "released": False,
            "reason": "release_receipt_failed",
        }
    return {
        **checkpoint,
        "released": True,
        "reason": "checkpointed",
    }


def _remediate_workspace(
    *,
    repo_root: Path,
    workspace: dict[str, Any],
    reason: str,
    detail: str,
    queue_path: Path | None,
    runner=subprocess.run,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Checkpoint → durable task exit → release, in that order."""
    checkpoint = _checkpoint_workspace(
        repo_root=repo_root,
        workspace=workspace,
        reason=reason,
        runner=runner,
    )
    evidence = {
        **workspace,
        "checkpoint_commit": checkpoint.get("commit", ""),
    }
    remediation = _open_remediation_task(
        repo_root=repo_root,
        workspace=evidence,
        reason=reason,
        detail=detail,
        queue_path=queue_path,
    )
    if (
        not checkpoint.get("ok")
        or not remediation.get("incident_id")
        or not remediation.get("task_id")
    ):
        if checkpoint.get("ok"):
            checkpoint = {
                **checkpoint,
                "released": False,
                "reason": "remediation_not_durable",
            }
        return remediation, checkpoint
    checkpoint = _release_checkpointed_workspace(
        repo_root=repo_root,
        workspace=workspace,
        reason=reason,
        checkpoint=checkpoint,
        remediation=remediation,
        runner=runner,
    )
    return remediation, checkpoint


def _reconcile_terminal_intent(
    *,
    repo_root: Path,
    workspace: dict[str, Any],
    queue_path: Path | None,
    runner=subprocess.run,
) -> dict[str, Any] | None:
    """Finish a destructive terminal transition after a crash/restart."""
    name = str(workspace.get("name") or "")
    intent = _latest_workspace_event(
        repo_root,
        event_name="terminal_intent",
        workspace_name=name,
    )
    if intent is None:
        return None
    target = str(intent.get("target_disposition") or "")
    wt = Path(str(workspace.get("path") or ""))
    branch = str(intent.get("branch") or workspace.get("branch") or "")
    if target == "merged":
        head_sha = str(intent.get("head_sha") or "")
        if not head_sha:
            return None
        if wt.exists():
            current_head = _git(
                wt,
                "rev-parse",
                "HEAD",
                runner=runner,
                timeout_s=30,
            )
            current_sha = (
                (current_head.stdout or "").strip()
                if current_head.returncode == 0
                else ""
            )
            if current_sha and current_sha != head_sha:
                remediation, checkpoint = _remediate_workspace(
                    repo_root=repo_root,
                    workspace=workspace,
                    reason="post_gate_branch_advanced",
                    detail=(
                        f"terminal intent gated {head_sha}, branch advanced "
                        f"to {current_sha}"
                    ),
                    queue_path=queue_path,
                    runner=runner,
                )
                return {
                    "workspace": name,
                    "branch": branch,
                    "disposition": "remediation_opened",
                    "reason": "post_gate_branch_advanced",
                    "remediation": remediation,
                    "checkpoint": checkpoint,
                }
        else:
            ancestor_probe = _git(
                repo_root,
                "merge-base",
                "--is-ancestor",
                head_sha,
                "main",
                runner=runner,
                timeout_s=30,
            )
            if ancestor_probe.returncode != 0:
                return _quarantine_missing_workspace(
                    repo_root=repo_root,
                    workspace={**workspace, "checkpoint_commit": head_sha},
                    reason="merge_readback_failed",
                    detail=(
                        f"gated head {head_sha} is absent from main and the "
                        "original workspace path is gone"
                    ),
                    queue_path=queue_path,
                )
        try:
            with git_writer_lock(
                repo_root,
                actor=f"dispatch-workspace-reconcile:{name}",
                timeout_s=60,
            ):
                # Re-read under the mutation lease: a stale PASS may never
                # clean a branch that advanced after the gate.
                current = _git(
                    repo_root,
                    "rev-parse",
                    branch,
                    runner=runner,
                    timeout_s=30,
                )
                if (
                    current.returncode == 0
                    and (current.stdout or "").strip() != head_sha
                ):
                    return {
                        "workspace": name,
                        "branch": branch,
                        "disposition": "reconcile_pending",
                        "reason": "branch_advanced_during_reconcile",
                    }
                ancestor = _git(
                    repo_root,
                    "merge-base",
                    "--is-ancestor",
                    head_sha,
                    "main",
                    runner=runner,
                    timeout_s=30,
                )
                if ancestor.returncode != 0:
                    return None
                if wt.exists():
                    removed = _git(
                        repo_root,
                        "worktree",
                        "remove",
                        str(wt),
                        runner=runner,
                        timeout_s=60,
                    )
                    if removed.returncode != 0:
                        return {
                            "workspace": name,
                            "branch": branch,
                            "disposition": "reconcile_pending",
                            "reason": "integrated_cleanup_failed",
                            "rc": removed.returncode,
                        }
                branch_probe = _git(
                    repo_root,
                    "rev-parse",
                    "--verify",
                    branch,
                    runner=runner,
                    timeout_s=30,
                )
                if branch_probe.returncode == 0:
                    deleted = _git(
                        repo_root,
                        "branch",
                        "-d",
                        branch,
                        runner=runner,
                        timeout_s=30,
                    )
                    if deleted.returncode != 0:
                        return {
                            "workspace": name,
                            "branch": branch,
                            "disposition": "reconcile_pending",
                            "reason": "integrated_branch_cleanup_failed",
                            "rc": deleted.returncode,
                        }
        except GitWriterLockError as exc:
            return {
                "workspace": name,
                "branch": branch,
                "disposition": "reconcile_pending",
                "reason": "writer_lock_busy",
                "error": str(exc)[:300],
            }
        main_head = _git(
            repo_root,
            "rev-parse",
            "main",
            runner=runner,
            timeout_s=30,
        )
        if main_head.returncode != 0 or not (main_head.stdout or "").strip():
            return {
                "workspace": name,
                "branch": branch,
                "disposition": "reconcile_pending",
                "reason": "main_head_readback_failed",
            }
        outcome = {
            "workspace": name,
            "branch": branch,
            "disposition": "merged",
            "gated_head_sha": head_sha,
            "main_sha": (main_head.stdout or "").strip(),
            "cleanup": "reconciled",
        }
    elif target == "empty_removed" and not wt.exists():
        try:
            with git_writer_lock(
                repo_root,
                actor=f"dispatch-workspace-reconcile-empty:{name}",
                timeout_s=60,
            ):
                branch_probe = _git(
                    repo_root,
                    "rev-parse",
                    "--verify",
                    branch,
                    runner=runner,
                    timeout_s=30,
                )
                if branch_probe.returncode == 0:
                    deleted = _git(
                        repo_root,
                        "branch",
                        "-d",
                        branch,
                        runner=runner,
                        timeout_s=30,
                    )
                    if deleted.returncode != 0:
                        return {
                            "workspace": name,
                            "branch": branch,
                            "disposition": "reconcile_pending",
                            "reason": "empty_branch_cleanup_failed",
                            "rc": deleted.returncode,
                        }
        except GitWriterLockError as exc:
            return {
                "workspace": name,
                "branch": branch,
                "disposition": "reconcile_pending",
                "reason": "writer_lock_busy",
                "error": str(exc)[:300],
            }
        outcome = {
            "workspace": name,
            "branch": branch,
            "disposition": "empty_removed",
            "cleanup": "reconciled",
        }
    else:
        return None
    if not _append_receipt(repo_root, {"event": "finalized", **outcome}):
        return {
            **outcome,
            "disposition": "reconcile_pending",
            "reason": "terminal_receipt_failed",
        }
    return {**outcome, "replayed": True}


def _quarantine_missing_workspace(
    *,
    repo_root: Path,
    workspace: dict[str, Any],
    reason: str,
    detail: str,
    queue_path: Path | None,
) -> dict[str, Any]:
    """Create and verify a recovery ref before terminally releasing no-path output."""
    name = str(workspace.get("name") or "")
    checkpoint_sha = str(workspace.get("checkpoint_commit") or "")
    recovery_branch = f"recovery-{name}-{checkpoint_sha[:8]}"
    if not checkpoint_sha:
        return {
            "workspace": name,
            "branch": workspace.get("branch"),
            "disposition": "reconcile_pending",
            "reason": "missing_checkpoint_identity",
        }
    try:
        with git_writer_lock(
            repo_root,
            actor=f"dispatch-workspace-recovery-ref:{name}",
            timeout_s=60,
        ):
            created = _git(
                repo_root,
                "branch",
                recovery_branch,
                checkpoint_sha,
                runner=subprocess.run,
                timeout_s=30,
            )
            if created.returncode != 0:
                existing = _git(
                    repo_root,
                    "rev-parse",
                    recovery_branch,
                    timeout_s=30,
                )
                if (
                    existing.returncode != 0
                    or (existing.stdout or "").strip() != checkpoint_sha
                ):
                    return {
                        "workspace": name,
                        "branch": recovery_branch,
                        "disposition": "reconcile_pending",
                        "reason": "recovery_ref_failed",
                    }
    except GitWriterLockError as exc:
        return {
            "workspace": name,
            "branch": recovery_branch,
            "disposition": "reconcile_pending",
            "reason": "writer_lock_busy",
            "error": str(exc)[:300],
        }
    if not _receipt_exists(
        repo_root,
        event_name="checkpointed",
        workspace_name=name,
        head_sha=checkpoint_sha,
    ) and not _append_receipt(
        repo_root,
        {
            "event": "checkpointed",
            "workspace": name,
            "branch": recovery_branch,
            "checkpoint_commit": checkpoint_sha,
            "reason": reason,
            "cleanup": "already_absent",
        },
    ):
        return {
            "workspace": name,
            "branch": recovery_branch,
            "disposition": "reconcile_pending",
            "reason": "checkpoint_receipt_failed",
        }
    evidence = {
        **workspace,
        "branch": recovery_branch,
        "checkpoint_commit": checkpoint_sha,
    }
    remediation = _open_remediation_task(
        repo_root=repo_root,
        workspace=evidence,
        reason=reason,
        detail=detail,
        queue_path=queue_path,
    )
    if not remediation.get("incident_id") or not remediation.get("task_id"):
        return {
            "workspace": name,
            "branch": recovery_branch,
            "disposition": "reconcile_pending",
            "reason": "remediation_not_durable",
            "remediation": remediation,
            "checkpoint": {
                "ok": True,
                "branch": recovery_branch,
                "commit": checkpoint_sha,
                "released": False,
                "reason": "remediation_not_durable",
            },
        }
    binding = {
        "event": "remediation_bound",
        "workspace": name,
        "branch": recovery_branch,
        "checkpoint_commit": checkpoint_sha,
        "incident_id": remediation.get("incident_id"),
        "task_id": remediation.get("task_id"),
        "disposition": "remediation_opened",
        "reason": reason,
        "cleanup": "already_absent",
    }
    if not _receipt_exists(
        repo_root,
        event_name="remediation_bound",
        workspace_name=name,
        head_sha=checkpoint_sha,
    ) and not _append_receipt(repo_root, binding):
        return {
            "workspace": name,
            "branch": recovery_branch,
            "disposition": "reconcile_pending",
            "reason": "remediation_receipt_failed",
            "remediation": remediation,
        }
    outcome = {
        "workspace": workspace.get("name"),
        "branch": recovery_branch,
        "disposition": "remediation_opened",
        "reason": reason,
        "remediation": remediation,
        "checkpoint": {
            "ok": bool(workspace.get("checkpoint_commit")),
            "branch": recovery_branch,
            "commit": checkpoint_sha,
            "released": True,
            "reason": "checkpointed",
        },
    }
    if not _append_receipt(
        repo_root,
        {
            "event": "released",
            **outcome,
            "checkpoint_commit": checkpoint_sha,
            "cleanup": "already_absent",
        },
    ):
        return {
            **outcome,
            "disposition": "reconcile_pending",
            "checkpoint": {
                **outcome["checkpoint"],
                "released": False,
                "reason": "release_receipt_failed",
            },
            "reason": "release_receipt_failed",
        }
    return outcome


def _adjudicate_unverified_workspace(
    *,
    repo_root: Path,
    workspace: dict[str, Any],
    reason: str,
    detail: str,
    queue_path: Path | None,
    runner=subprocess.run,
) -> dict[str, Any]:
    """Preserve the expected repo ref without executing Git in an unsafe path."""
    name = str(workspace.get("name") or "")
    branch = str(workspace.get("branch") or "")
    branch_head = _git(
        repo_root,
        "rev-parse",
        branch,
        runner=runner,
        timeout_s=30,
    )
    checkpoint_sha = (
        (branch_head.stdout or "").strip()
        if branch_head.returncode == 0
        else ""
    )
    if not checkpoint_sha:
        return {
            "workspace": name,
            "branch": branch,
            "disposition": "reconcile_pending",
            "reason": "unverified_branch_unreadable",
        }
    if not _receipt_exists(
        repo_root,
        event_name="checkpointed",
        workspace_name=name,
        head_sha=checkpoint_sha,
    ) and not _append_receipt(
        repo_root,
        {
            "event": "checkpointed",
            "workspace": name,
            "branch": branch,
            "checkpoint_commit": checkpoint_sha,
            "reason": reason,
            "cleanup": "manual_unverified_path",
        },
    ):
        return {
            "workspace": name,
            "branch": branch,
            "disposition": "reconcile_pending",
            "reason": "checkpoint_receipt_failed",
        }
    evidence = {
        **workspace,
        "checkpoint_commit": checkpoint_sha,
    }
    remediation = _open_remediation_task(
        repo_root=repo_root,
        workspace=evidence,
        reason=reason,
        detail=detail,
        queue_path=queue_path,
    )
    if remediation.get("incident_id") and remediation.get("task_id"):
        binding = {
            "event": "remediation_bound",
            "workspace": name,
            "branch": branch,
            "checkpoint_commit": checkpoint_sha,
            "incident_id": remediation.get("incident_id"),
            "task_id": remediation.get("task_id"),
            "disposition": "remediation_opened",
            "reason": reason,
            "cleanup": "manual_unverified_path",
        }
        if not _receipt_exists(
            repo_root,
            event_name="remediation_bound",
            workspace_name=name,
            head_sha=checkpoint_sha,
        ):
            _append_receipt(repo_root, binding)
    return {
        "workspace": name,
        "branch": branch,
        "disposition": "remediation_opened",
        "reason": reason,
        "remediation": remediation,
        "checkpoint": {
            "ok": True,
            "branch": branch,
            "commit": checkpoint_sha,
            "released": False,
            "reason": "manual_unverified_path",
        },
    }


# ── finalization ─────────────────────────────────────────────────────────────

def finalize_workspace(
    *,
    repo_root: Path,
    workspace: dict[str, Any],
    worker_outcome: str,
    job_id: str = "",
    queue_path: Path | None = None,
    runner=subprocess.run,
    gate_fn: Callable[..., dict[str, Any]] | None = None,
    merge_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Close out one fire's workspace: empty → remove; output → gate → merge;
    red/failed/unverified → durable branch + idempotent adjudication task.

    Every exit appends a receipt line. Never raises — a finalizer crash must not
    take down the fire task (the orphan sweep is the retry path).
    """
    repo_root = Path(repo_root)
    if _canonical_repo_guarded(repo_root):
        LOG.warning("workspace finalize refused: test process on canonical checkout")
        return {"disposition": "canonical_guard", "workspace": workspace.get("name")}
    workspace_name = str(workspace.get("name") or "")
    prior = _latest_terminal_receipt(repo_root, workspace_name)
    if prior is not None:
        return {**prior, "replayed": True}
    reconciled = _reconcile_terminal_intent(
        repo_root=repo_root,
        workspace=workspace,
        queue_path=queue_path,
        runner=runner,
    )
    if reconciled is not None:
        return reconciled
    if not Path(str(workspace.get("path") or "")).exists():
        # Crash window: removal succeeded but the final `released` fsync did
        # not. The durable remediation binding proves both recovery identities
        # existed before cleanup, so reconstruct the terminal receipt.
        binding = _latest_workspace_event(
            repo_root,
            event_name="remediation_bound",
            workspace_name=workspace_name,
        )
        if binding is not None:
            recovered = {
                "event": "released",
                "workspace": workspace_name,
                "branch": binding.get("branch", workspace.get("branch", "")),
                "checkpoint_commit": binding.get("checkpoint_commit", ""),
                "disposition": "remediation_opened",
                "reason": binding.get("reason", "recovered_release"),
                "checkpoint": {
                    "ok": True,
                    "branch": binding.get("branch", workspace.get("branch", "")),
                    "commit": binding.get("checkpoint_commit", ""),
                    "released": True,
                    "reason": "checkpointed",
                },
                "remediation": {
                    "incident_id": binding.get("incident_id"),
                    "task_id": binding.get("task_id"),
                },
                "cleanup": "recovered_absent",
            }
            if _append_receipt(repo_root, recovered):
                return {
                    key: value
                    for key, value in recovered.items()
                    if key != "event"
                } | {"replayed": True}
    outcome: dict[str, Any] = {"disposition": "error", "workspace": workspace.get("name")}
    try:
        outcome = _finalize_inner(
            repo_root=repo_root, workspace=workspace, worker_outcome=worker_outcome,
            queue_path=queue_path, runner=runner,
            gate_fn=gate_fn or _run_merge_gate, merge_fn=merge_fn or _run_merge_script,
        )
    except Exception as exc:  # noqa: BLE001 — belt-and-suspenders, logged not swallowed
        LOG.exception("workspace finalize crashed for %s: %s", workspace.get("name"), exc)
        outcome = {"disposition": "error", "workspace": workspace.get("name"),
                   "error": str(exc)[:300]}
    disposition = outcome.get("disposition")
    released = bool((outcome.get("checkpoint") or {}).get("released"))
    # A remediation release already owns its terminal receipt. All other
    # incomplete attempts remain retryable; only genuinely terminal outcomes
    # receive `finalized`.
    if disposition in {"empty_removed", "merged"}:
        _append_receipt(repo_root, {
            "event": "finalized", "job_id": job_id,
            "worker_outcome": worker_outcome,
            **{k: v for k, v in outcome.items() if k != "output_tail"},
        })
    elif not (disposition == "remediation_opened" and released):
        _append_receipt(repo_root, {
            "event": "finalize_attempt", "job_id": job_id,
            "worker_outcome": worker_outcome,
            **{k: v for k, v in outcome.items() if k != "output_tail"},
        })
    return outcome


def _finalize_inner(
    *,
    repo_root: Path,
    workspace: dict[str, Any],
    worker_outcome: str,
    queue_path: Path | None,
    runner,
    gate_fn,
    merge_fn,
) -> dict[str, Any]:
    name = workspace["name"]
    wt = Path(workspace["path"])
    branch = workspace["branch"]
    base: dict[str, Any] = {"workspace": name, "branch": branch}
    if not wt.exists():
        return {**base, "disposition": "missing"}
    if not is_registered_linked_worktree(repo_root, wt):
        # An allocator receipt proves lifecycle ownership, but a strict Git
        # registration failure makes mutation unsafe. Quarantine it with a
        # durable adjudication exit and remove it from live capacity; never
        # delete an unverifiable checkout automatically.
        if name in _active_allocated_workspace_names(repo_root):
            return _adjudicate_unverified_workspace(
                repo_root=repo_root,
                workspace=workspace,
                reason="registration_verify_failed",
                detail=f"allocator-owned path failed strict registration: {wt}",
                queue_path=queue_path,
                runner=runner,
            )
        # No allocator provenance: a directory squatting on the namespace must
        # never be removed, merged, or assigned to our incident.
        return {**base, "disposition": "unregistered"}

    status = _git(wt, "status", "--porcelain", runner=runner, timeout_s=60)
    if status.returncode != 0:
        return {**base, "disposition": "status_error", "rc": status.returncode}
    dirty = bool((status.stdout or "").strip())
    ahead = _git(repo_root, "rev-list", "--count", branch, "--not", "main",
                 runner=runner, timeout_s=60)
    if ahead.returncode != 0:
        return {**base, "disposition": "revlist_error", "rc": ahead.returncode}
    unique_commits = int((ahead.stdout or "0").strip() or 0)

    if not dirty and unique_commits == 0:
        # Nothing produced. Plain (never --force) removal; a refusal is left
        # for the next orphan sweep rather than escalated.
        if not _append_receipt(
            repo_root,
            {
                "event": "terminal_intent",
                "workspace": name,
                "branch": branch,
                "target_disposition": "empty_removed",
                "cleanup": "pending",
            },
        ):
            return {**base, "disposition": "receipt_failed",
                    "reason": "empty_intent_not_durable"}
        try:
            with git_writer_lock(
                repo_root,
                actor=f"dispatch-workspace-empty:{name}",
                timeout_s=60,
            ):
                remove = _git(
                    repo_root,
                    "worktree",
                    "remove",
                    str(wt),
                    runner=runner,
                    timeout_s=60,
                )
                if remove.returncode != 0:
                    return {**base, "disposition": "remove_failed",
                            "rc": remove.returncode,
                            "output_tail": (remove.stderr or "")[-300:]}
                deleted = _git(
                    repo_root,
                    "branch",
                    "-d",
                    branch,
                    runner=runner,
                    timeout_s=30,
                )
        except GitWriterLockError as exc:
            return {**base, "disposition": "remove_failed",
                    "reason": "writer_lock_busy", "error": str(exc)[:300]}
        if deleted.returncode != 0:
            return {**base, "disposition": "remove_failed",
                    "reason": "branch_delete_failed", "rc": deleted.returncode,
                    "output_tail": (deleted.stderr or "")[-300:]}
        return {**base, "disposition": "empty_removed"}

    if worker_outcome not in _MERGEABLE_OUTCOMES:
        # The producer never finished cleanly — its bytes are unverified.
        reason = f"worker_{worker_outcome}"
        detail = (
            f"fire ended with outcome={worker_outcome}; "
            f"dirty={dirty} unique_commits={unique_commits}"
        )
        remediation, checkpoint = _remediate_workspace(
            repo_root=repo_root, workspace=workspace,
            reason=reason,
            detail=detail,
            queue_path=queue_path,
            runner=runner,
        )
        return {**base, "disposition": "remediation_opened",
                "reason": reason, "remediation": remediation,
                "checkpoint": checkpoint,
                "dirty": dirty, "unique_commits": unique_commits}

    gate = gate_fn(repo_root=repo_root, workspace=workspace, runner=runner)
    if gate.get("verdict") == "red":
        detail = (
            f"merge gate rc={gate.get('rc')} targets={gate.get('targets')}\n"
            + str(gate.get("output_tail") or "")
        )
        remediation, checkpoint = _remediate_workspace(
            repo_root=repo_root, workspace=workspace, reason="gate_red",
            detail=detail,
            queue_path=queue_path,
            runner=runner,
        )
        return {**base, "disposition": "remediation_opened", "reason": "gate_red",
                "gate": {k: gate.get(k) for k in ("verdict", "rc", "targets", "duration_s")},
                "remediation": remediation, "checkpoint": checkpoint}

    branch_head = _git(
        wt,
        "rev-parse",
        "HEAD",
        runner=runner,
        timeout_s=30,
    )
    if branch_head.returncode != 0:
        return {**base, "disposition": "head_read_error",
                "rc": branch_head.returncode}
    gated_head_sha = (branch_head.stdout or "").strip()
    if not _append_receipt(
        repo_root,
        {
            "event": "terminal_intent",
            "workspace": name,
            "branch": branch,
            "target_disposition": "merged",
            "head_sha": gated_head_sha,
            "gate": {
                key: gate.get(key)
                for key in ("verdict", "rc", "targets", "duration_s")
            },
            "cleanup": "pending",
        },
    ):
        return {**base, "disposition": "receipt_failed",
                "reason": "merge_intent_not_durable"}

    merge = merge_fn(repo_root=repo_root, workspace=workspace, runner=runner)
    if not merge.get("ok"):
        reason = str(merge.get("reason") or "merge_failed")
        remediation, checkpoint = _remediate_workspace(
            repo_root=repo_root, workspace=workspace,
            reason=reason,
            detail=str(merge.get("output_tail") or ""),
            queue_path=queue_path,
            runner=runner,
        )
        return {**base, "disposition": "remediation_opened",
                "reason": reason,
                "gate": {k: gate.get(k) for k in ("verdict", "rc", "targets", "duration_s")},
                "remediation": remediation, "checkpoint": checkpoint}

    integrated = _git(
        repo_root,
        "merge-base",
        "--is-ancestor",
        gated_head_sha,
        "main",
        runner=runner,
        timeout_s=30,
    )
    head = _git(repo_root, "rev-parse", "main", runner=runner, timeout_s=30)
    main_sha = (head.stdout or "").strip() if head.returncode == 0 else ""
    if integrated.returncode != 0 or not main_sha:
        reason = "merge_readback_failed"
        detail = (
            f"merge reported ok but gated head {gated_head_sha} is not an "
            f"ancestor of main={main_sha or '<unreadable>'}"
        )
        if wt.exists():
            remediation, checkpoint = _remediate_workspace(
                repo_root=repo_root,
                workspace=workspace,
                reason=reason,
                detail=detail,
                queue_path=queue_path,
                runner=runner,
            )
            return {
                **base,
                "disposition": "remediation_opened",
                "reason": reason,
                "remediation": remediation,
                "checkpoint": checkpoint,
            }
        return _quarantine_missing_workspace(
            repo_root=repo_root,
            workspace={**workspace, "checkpoint_commit": gated_head_sha},
            reason=reason,
            detail=detail,
            queue_path=queue_path,
        )
    # Landed: if an earlier failure registered this workspace on the
    # worker_orphaned incident, its instance is now cleared (incident resolves
    # once ALL instances are cleared and quiet >=24h — plan §4).
    _clear_workspace_instance(repo_root=repo_root, workspace_name=name)
    return {**base, "disposition": "merged",
            "gate": {k: gate.get(k) for k in ("verdict", "rc", "targets", "duration_s")},
            "gated_head_sha": gated_head_sha,
            "main_sha": main_sha}


# ── orphan sweep ─────────────────────────────────────────────────────────────

def sweep_orphan_workspaces(
    *,
    repo_root: Path,
    protected_job_ids: list[str],
    queue_path: Path | None = None,
    runner=subprocess.run,
) -> list[dict[str, Any]]:
    """Close out dispatch workspaces whose fire is GONE FROM STATE ENTIRELY
    (supervisor crash losing the state file, spawn-failure release).

    `protected_job_ids` must cover every job the state file still knows about —
    current_jobs, phase_z_pending AND the completions ring — not just live
    ones. A completed fire's own finalize already ran (or is running right now,
    in its fire task's `finally`); sweeping it here would double-finalize and
    could race the merge script against itself. A remediation-kept workspace
    likewise stays in the completions ring, so the sweep leaves it to its
    remediation task instead of re-filing hourly. Same finalizer,
    worker_outcome="orphaned": a non-empty true orphan goes to remediation, an
    empty one is removed. Runs on the allocation path of the next fire.
    """
    repo_root = Path(repo_root)
    if _canonical_repo_guarded(repo_root):
        LOG.warning("workspace sweep refused: test process on canonical checkout")
        return []
    active8 = {str(j)[:8] for j in protected_job_ids}
    results: list[dict[str, Any]] = []
    for wt_path in _registered_dispatch_worktrees(repo_root, runner=runner):
        match = _JOB8_RE.match(wt_path.name)
        job8 = match.group(1) if match else None
        if job8 is not None and job8 in active8:
            continue
        branch = _worktree_branch(repo_root, wt_path, runner=runner)
        if branch is None:
            LOG.warning("workspace sweep: cannot resolve branch for %s — leaving alone",
                        wt_path)
            continue
        workspace = {"name": wt_path.name, "path": str(wt_path), "branch": branch,
                     "base_sha": ""}
        results.append(finalize_workspace(
            repo_root=repo_root, workspace=workspace, worker_outcome="orphaned",
            job_id=job8 or "", queue_path=queue_path, runner=runner,
        ))
    return results


# ── prompt fragment ──────────────────────────────────────────────────────────

def prompt_fragment(workspace: dict[str, Any]) -> str:
    """Slot-prompt section binding isolated-lane repo writes to the workspace."""
    lanes = "／".join(workspace.get("lanes") or _DEFAULT_LANES)
    return (
        "[Producer-scoped workspace — WS-B pilot]\n"
        f"isolated_lanes={lanes}; workspace={workspace['path']}; "
        f"branch={workspace['branch']}.\n"
        f"本班執行上述 lane 任務時，所有 repo-byte 變更（scripts/src/tests/config/docs/"
        f".claude 等 Git-tracked 檔案）一律寫進 workspace（可 cd 進去；它是本 fire 專屬的 "
        "registered worktree），並在 workspace 內以 ASCII commit message（含 task id）提交。"
        "禁止為這些 lane 另建 worktree、禁止把這些 lane 的 repo 變更直接寫進 canonical_root。"
        "此 workspace 由 supervisor 管理：**不得自行 merge、也不適用「本班結束前完整整合」**"
        "—— supervisor 會在本班結束後跑測試 gate，綠才併入 main；紅則自動開 aggregate "
        "adjudication 單、checkpoint branch 並釋放 live worktree。canonical state"
        "（storage/ 任務池、feed、work_log 等）仍走 "
        "canonical_root 的既有 CLI，不寫進 workspace。其他 lane（experiment 等）的既有 "
        "worktree 流程不變。\n"
    )
