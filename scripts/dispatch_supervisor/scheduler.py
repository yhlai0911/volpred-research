"""Scheduler — asyncio tick → "is it time to fire?" → worker.run_worker.

Tick every TICK_INTERVAL_S (=60s). On each tick:

  1. `state.heartbeat()` — belt-and-suspenders only. This tick BLOCKS in step 6
     for the entire worker run, so it cannot keep the heartbeat fresh; the
     liveness owner is `health.health_loop()` (30s, never blocks). Kept here so
     `--once` smoke runs, which skip health_loop, still stamp one beat.
  2. If `auth_blocked` true → log + skip (manual unblock via CLI)
  3. If `len(current_jobs) >= max_slots` → skip; otherwise another fire may run
  4. Compute most recent scheduled fire time via croniter
  5. If due (and not dry_run) → `phase_z.run_pre_fire_guard()` — fail-open git
     conflict backstop, so the slot starts on a clean, valid tree
  6. If `last_fire_at < that fire time` → spawn worker (or DRY-RUN log only)
  7. Launch the worker as a supervised background asyncio task. The scheduler
     keeps ticking so a later cron/request can fill another free slot.

The worker call is blocking; each admitted fire runs inside `asyncio.to_thread()`.
Overlapping fires share one checkout, so PHASE-Z is cohort-drained: an early
finisher defers the safety commit and the final sibling runs it once all writers
have stopped. This avoids committing a sibling's half-written files.

In `dry_run=True` mode (shadow phase per refactor_plan §4 phase 2) the
scheduler logs "WOULD enqueue at <fire_at>" + updates last_fire_at but
does NOT spawn a worker. Used to diff against legacy shell decisions.
WS-H4 (2026-07-20): a dry-run tick walks the SAME pregate judgment as a
cron fire (it used to bypass it) — dry-run and fire may only diverge at
the write boundary (reserve_fire / worker spawn), never in the decision.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import subprocess
import sys
import tempfile
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from croniter import croniter

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
from volpred.ops.timestamps import parse_iso_warn  # noqa: E402

from . import (
    alerts,
    custody_receipt,
    decision,
    deferred_reload,
    identity,
    isolation,
    phase_z,
    procutil,
    state,
    worker,
)
from . import workspace as workspace_mod
from .child_env import external_child_environment
from .report_contract import inject_external_report_contract

LOG = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SCHEDULES_PATH = ROOT / "config" / "runtime_schedules.json"
DEFAULT_PROMPT_PATH = ROOT / "scripts" / "cron_hourly_dispatch_prompt.md"
DEFAULT_LOG_DIR = Path(os.environ.get("VOLPRED_HOME_DIR", str(Path.home() / ".volpred"))) / "logs"
DEFAULT_LOG_PATH = DEFAULT_LOG_DIR / "dispatch_supervisor_worker.log"

TICK_INTERVAL_S = 60
FALLBACK_CRON = "7 * * * *"
# config/runtime_schedules.json id; cron field is often null because legacy
# scheduling lived in LaunchAgent plist. Supervisor falls back to "7 * * * *".
SCHEDULE_ID = "volpred-hourly-dispatch"
DAEMON_ID = "volpred-dispatch-supervisor"
# Also the floor the pool de-rates to during a quota outage: the capacity that
# ran for months without exhausting the window is the safe thing to fall back to.
DEFAULT_MAX_SLOTS = 2
FAIL_CLOSED_MAX_SLOTS = 1
QUOTA_DERATE_STREAK = 2
SHARED_LAUNCHD_COALITION_MODE = "shared_launchd_coalition"

# Strong references keep launched fire tasks alive until their done callback
# observes the result. Keys are immutable state job_ids, never reusable slots.
_ACTIVE_FIRE_TASKS: dict[str, asyncio.Task] = {}
_ACTIVE_PHASE_Z_RECOVERY_TASK: asyncio.Task | None = None
_BACKGROUND_ALERT_TASKS: set[asyncio.Task] = set()
_PHASE_Z_LOCK: asyncio.Lock | None = None
_PHASE_Z_TERMINAL_REASONS = {"committed", "clean", "nothing_owned", "nothing_to_commit",
                             # ownership_unknown = no fire-start baseline. The baseline is
                             # written ONLY by the pre-fire guard at fire time, so no amount
                             # of retrying can produce one — retrying is a livelock, and the
                             # alert inside run_phase_z re-fires every tick (2026-07-13:
                             # 12+ identical warns to the boss in 14 min). One alert, done.
                             "ownership_unknown",
                             "missing_generation", "generation_mismatch",
                             "invalid_generation_baseline",
                             "generation_baseline_mismatch"}
# Retrying a non-terminal drain only helps transient git hiccups (index.lock,
# probe timeout). Deterministic failures (a pre-commit gate block) would retry
# every ~64s tick forever. Three attempts ≈ 3 min of transient tolerance, then
# one give-up alert and the token is released.
_PHASE_Z_MAX_DRAIN_ATTEMPTS = 3
_PHASE_Z_GENERATION_TRAILER = "VolPred-Phase-Z-Generation"


def _phase_z_claim_owners(pending: list[dict[str, Any]]) -> set[str]:
    """Return every executor identity that could have owned a drained fire."""
    owners: set[str] = set()
    for item in pending:
        job_id = str(item.get("job_id") or "").strip()
        raw_slot = str(item.get("slot_id") or "").strip()
        if not job_id or not raw_slot:
            continue
        slot_id = raw_slot if raw_slot.startswith("slot-") else f"slot-{raw_slot}"
        owners.update(identity.task_claim_owners_for_job(slot_id=slot_id, job_id=job_id))
    return owners


def _matching_fire_lifecycle(
    pending: list[dict[str, Any]],
) -> tuple[set[str] | None, str]:
    """Return the durable baseline only when every token names one generation.

    A process restart is precisely where the old singleton snapshot became
    ambiguous.  Missing, mixed, or differently-captured generations therefore
    carry no authority to execute closeout.
    """
    lifecycles = [item.get("fire_lifecycle") for item in pending]
    if not lifecycles or any(not isinstance(item, dict) for item in lifecycles):
        return None, "missing_generation"
    generation_ids = {
        str(item.get("generation_id") or "").strip() for item in lifecycles
    }
    if "" in generation_ids or len(generation_ids) != 1:
        return None, "generation_mismatch"
    baselines = [item.get("pre_fire_dirty") for item in lifecycles]
    if any(not isinstance(paths, list) for paths in baselines):
        return None, "invalid_generation_baseline"
    normalized = [{str(path) for path in paths} for paths in baselines]
    if any(paths != normalized[0] for paths in normalized[1:]):
        return None, "generation_baseline_mismatch"
    return normalized[0], next(iter(generation_ids))


def _git_head(repo_root: Path) -> str:
    """Return the current HEAD OID, or an empty string for non-git test seams."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        if (repo_root / ".git").exists():
            raise RuntimeError(f"PHASE-Z HEAD probe unavailable: {exc}") from exc
        return ""
    if proc.returncode != 0 and (repo_root / ".git").exists():
        raise RuntimeError(
            "PHASE-Z HEAD probe failed: " + (proc.stderr or "")[-300:]
        )
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def _phase_z_terminal_commit(
    *,
    repo_root: Path,
    pending: list[dict[str, Any]],
    generation_id: str,
) -> str | None:
    """Recover a terminal PHASE-Z commit after process death.

    ``begin_phase_z`` binds the pre-mutation HEAD into every pending token.
    PHASE-Z writes the generation as a commit trailer.  A new process searches
    only descendants of that exact HEAD, so an old receipt with the same text
    cannot release a newer lifecycle.
    """
    attempts = {
        (
            str(item.get("closeout_generation_id") or ""),
            str(item.get("closeout_base_head") or ""),
        )
        for item in pending
        if item.get("closeout_generation_id") is not None
    }
    if not attempts:
        return None
    if len(attempts) != 1 or any(
        item.get("closeout_generation_id") is None for item in pending
    ):
        raise RuntimeError("mixed PHASE-Z closeout attempt identities")
    attempt_generation, base_head = next(iter(attempts))
    if attempt_generation != str(generation_id):
        raise RuntimeError("PHASE-Z closeout attempt does not match lifecycle generation")
    if not base_head and (repo_root / ".git").exists():
        raise RuntimeError("PHASE-Z closeout attempt has no verified base HEAD")
    if not base_head:
        return None
    try:
        proc = subprocess.run(
            [
                "git", "-C", str(repo_root), "log",
                "--format=%H%x00%B%x00%x1e",
                f"{base_head}..HEAD",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(
            f"PHASE-Z terminal receipt probe unavailable: {exc}"
        ) from exc
    if proc.returncode != 0:
        raise RuntimeError(
            "cannot inspect PHASE-Z terminal commit "
            f"generation={generation_id} base={base_head}: "
            + (proc.stderr or "")[-300:]
        )
    expected = f"{_PHASE_Z_GENERATION_TRAILER}: {generation_id}"
    for raw_record in (proc.stdout or "").split("\x1e"):
        record = raw_record.strip("\n\x00 ")
        if not record or "\x00" not in record:
            continue
        commit_sha, body = record.split("\x00", 1)
        if any(line.strip() == expected for line in body.splitlines()):
            return commit_sha.strip()
    return None


def _reject_unmatched_generation(
    *, pending: list[dict[str, Any]], reason: str, state_path: Path,
) -> dict[str, Any]:
    """Atomically quarantine unmatched tokens and route one durable incident."""
    cohorts = {str(item.get("cohort_id")) for item in pending}
    rejected = state.reject_phase_z(
        cohort_ids=cohorts, reason=reason, path=state_path,
    )
    LOG.error(
        "phase_z rejected closeout without matching durable generation "
        "reason=%s jobs=%s",
        reason,
        [item.get("job_id") for item in pending],
    )
    alert = phase_z._default_internal_alert(
        alert_key="phase_z_generation_rejected",
        level="warn",
        title="PHASE-Z closeout generation 無法驗證 — 已隔離且未執行",
        body="\n".join([
            "## 發生什麼",
            "Supervisor 找到待 closeout 的 fire，但 durable generation "
            f"無法驗證（{reason}）。",
            "",
            "## 安全處置",
            "沒有執行 PHASE-Z、沒有提交任何檔案。原 token 已原樣移入 "
            "`dispatch_state.json.phase_z_rejections`，不會靜默消失。",
            "",
            "## 行動",
            "依 rejection receipt 的 job_id / cohort_id 查明原 generation；"
            "不得用目前工作區的 singleton baseline 代替。",
        ]),
        fingerprint=f"phase_z_generation_rejected:{reason}",
    )
    return {
        "committed": False,
        "reason": reason,
        "generation_rejected": True,
        "rejected": len(rejected),
        "alert": alert,
    }


def _phase_z_drain_exhausted(*, cohort_id: str, outcome: dict[str, Any] | None,
                             state_path: Path) -> bool:
    """Bump the cohort's drain-attempt counter; True → retries exhausted.

    The counter lives on the pending token itself so it survives daemon
    restarts — a restart must not grant a stuck cohort three fresh retries
    per boot, which is just the livelock with extra steps.
    """
    if (outcome or {}).get("head_committed"):
        # HEAD already contains this generation.  Releasing after a retry cap
        # would permanently skip index/claim/test closeout.  Keep retrying the
        # idempotent downstream finisher until it emits a terminal receipt.
        return False
    attempts = 0
    with state._locked_state(state_path) as (_fh, data):
        for item in data.get("phase_z_pending") or []:
            if str(item.get("cohort_id")) == str(cohort_id):
                attempts = int(item.get("drain_attempts") or 0) + 1
                item["drain_attempts"] = attempts
                break
    if attempts < _PHASE_Z_MAX_DRAIN_ATTEMPTS:
        return False
    reason = (outcome or {}).get("reason", "crashed")
    detail = str((outcome or {}).get("commit_tail") or "").strip()
    alert_payload = {
        "level": "warn",
        "title": f"PHASE-Z 重試 {attempts} 次仍無法收班（{reason}）— 停止重試，不再連發此警報",
        "body": "\n".join([
            "## 發生什麼",
            f"PHASE-Z 連續 {attempts} 次無法完成這班的自動 commit（原因：{reason}）。"
            "已停止重試 —— 同一班不再重跑。",
            "檔案仍在工作區、沒有遺失。",
            "",
            "## 現在該做什麼",
            "確認未提交檔案的作者後由該作者 commit。"
            "若下方顯示被 pre-commit gate 擋下，先修 gate 指出的問題再 commit。",
            *(["", "## git commit 輸出（尾段）", detail] if detail else []),
        ]),
    }
    if str((outcome or {}).get("internal_alert_key") or "") == "silent_fallback_new":
        # The candidate already created one stable P1 task.  Drain retries are
        # transport retries, not failed task attempts, so they must not page the
        # owner or advance the two-attempt escalation threshold.
        phase_z._default_internal_alert(
            alert_key="silent_fallback_new",
            observed_at=(outcome or {}).get("internal_alert_observed_at"),
            **alert_payload,
        )
    else:
        phase_z._default_alert(**alert_payload)
    return True


def load_cron_expr(*, schedules_path: Path = SCHEDULES_PATH, schedule_id: str = SCHEDULE_ID) -> str:
    """Read the schedule cron expression for the named schedule.

    Codex-review §10 #6 fix: canonical field is `schedule` (the `cron` field
    is `null` for `volpred-hourly-dispatch` because legacy scheduling lived
    in the LaunchAgent plist — see config/runtime_schedules.json). Reading
    only `cron` worked by coincidence (fallback `7 * * * *` matched), but if
    ops bumped `schedule` in config the supervisor would silently ignore it.

    Tries `schedule` first (canonical), falls back to `cron` (legacy),
    then FALLBACK_CRON. Looks in `cron_jobs[]` (canonical) and legacy
    `items[]`.
    """
    try:
        data = json.loads(schedules_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        LOG.warning("load_cron_expr fallback (%s): %s", FALLBACK_CRON, exc)
        return FALLBACK_CRON
    for key in ("cron_jobs", "items"):
        entries = data.get(key) or []
        if not isinstance(entries, list):
            continue
        for item in entries:
            if not isinstance(item, dict):
                continue
            if item.get("id") != schedule_id:
                continue
            for field in ("schedule", "cron"):
                cron_expr = item.get(field)
                if isinstance(cron_expr, str) and cron_expr.strip():
                    LOG.debug("schedule id=%s using field=%r expr=%r",
                              schedule_id, field, cron_expr.strip())
                    return cron_expr.strip()
    LOG.info("schedule id=%s has no schedule/cron field; supervisor using fallback %r",
             schedule_id, FALLBACK_CRON)
    return FALLBACK_CRON


def quota_derate_active(state_path: Path) -> bool:
    """True while the newest completions are an unbroken quota_blocked streak.

    A quota block is not a failure of one fire — it says the WINDOW is spent,
    so every additional slot burns its ~95K cold-load on a run that cannot do
    any work. Above the baseline capacity that turns a surge into an amplifier
    of the outage, which is why the de-rate exists at all.

    Unlike ``auth_blocked`` (a latched flag needing `cli unblock-auth`), quota
    resolves on a clock. So the signal must self-clear: one successful
    completion breaks the streak and the configured capacity comes straight
    back, with no human in the loop. Requiring two in a row keeps a single
    unlucky fire from de-rating the pool.
    """
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logging.warning("quota_streak_state_unreadable: %s (%s) — treating as no streak", state_path, exc)
        return False
    completions = data.get("completions")
    if not isinstance(completions, list):
        return False
    streak = 0
    for item in reversed(completions):
        if not isinstance(item, dict) or item.get("outcome") != "quota_blocked":
            break
        streak += 1
        if streak >= QUOTA_DERATE_STREAK:
            return True
    return False


def load_max_slots(
    *, schedules_path: Path = SCHEDULES_PATH, daemon_id: str = DAEMON_ID,
    state_path: Path = state.STATE_PATH,
) -> int:
    """Hot-load the daemon pool capacity from runtime_schedules.json.

    The owner is ``daemons[id=volpred-dispatch-supervisor].max_slots``. Missing
    or invalid/ambiguous values fail closed to one; bool is rejected even
    though it is an ``int`` subclass. A config reduction never kills existing workers — it
    only blocks new admission until occupancy falls below the new limit.

    The configured value is a ceiling, not a promise.  Shared launchd-coalition
    producer custody cannot safely distinguish concurrently-started fires, so
    that mode always returns one even if either capacity field drifts.  While a
    quota streak is active other custody modes are clamped back to
    ``DEFAULT_MAX_SLOTS``. Keeping these guards here rather than in the caller
    preserves the single-owner rule — everyone who asks "how many slots exist"
    gets the same answer.
    """
    try:
        data = json.loads(schedules_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        LOG.warning(
            "load_max_slots fail-closed=%d: %s",
            FAIL_CLOSED_MAX_SLOTS,
            exc,
        )
        return FAIL_CLOSED_MAX_SLOTS
    for item in data.get("daemons") or []:
        if not isinstance(item, dict) or item.get("id") != daemon_id:
            continue
        value = item.get("max_slots", DEFAULT_MAX_SLOTS)
        custody = item.get("producer_custody")
        custody_mode = custody.get("mode") if isinstance(custody, dict) else None
        writer_cfg = item.get("writer_isolation")
        writer_max_active = (
            writer_cfg.get("max_active")
            if isinstance(writer_cfg, dict)
            else None
        )
        if (
            value != 1
            or writer_max_active != 1
            or custody_mode != SHARED_LAUNCHD_COALITION_MODE
        ):
            LOG.warning(
                "per-fire producer coalition isolation is not implemented; "
                "admission remains single-slot shared custody "
                "(configured mode/slots/writers=%r/%r/%r)",
                custody_mode,
                value,
                writer_max_active,
            )
        return FAIL_CLOSED_MAX_SLOTS
    LOG.warning(
        "daemon %s missing max_slots — fail-closed to %d",
        daemon_id,
        FAIL_CLOSED_MAX_SLOTS,
    )
    return FAIL_CLOSED_MAX_SLOTS


def load_producer_custody_mode(
    *,
    schedules_path: Path = SCHEDULES_PATH,
    daemon_id: str = DAEMON_ID,
) -> str:
    """Read custody mode; ambiguity retains the strict shared-coalition gate."""
    try:
        data = json.loads(schedules_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        LOG.warning(
            "producer custody mode unavailable — fail-closed shared: %s",
            exc,
        )
        return SHARED_LAUNCHD_COALITION_MODE
    for item in data.get("daemons") or []:
        if not isinstance(item, dict) or item.get("id") != daemon_id:
            continue
        custody = item.get("producer_custody")
        mode = custody.get("mode") if isinstance(custody, dict) else None
        if mode == SHARED_LAUNCHD_COALITION_MODE:
            return SHARED_LAUNCHD_COALITION_MODE
        LOG.warning(
            "producer custody mode %r is not implemented — fail-closed shared",
            mode,
        )
        return SHARED_LAUNCHD_COALITION_MODE
    LOG.warning("producer custody daemon row missing — fail-closed shared")
    return SHARED_LAUNCHD_COALITION_MODE


def _slot_log_path(base: Path, *, slot_id: str, job_id: str) -> Path:
    """Per-job output prevents sibling auth/quota text contaminating classify."""
    suffix = base.suffix or ".log"
    return base.with_name(f"{base.stem}.{slot_id}.{job_id[:8]}{suffix}")


def _slot_workdir(
    log_path: Path, *, slot_id: str, job_id: str, repo_root: Path
) -> Path:
    """Create a non-repository cwd so an agent cannot mutate main by default."""
    prefix = f"dispatch-{slot_id}-{job_id[:8]}"
    parent = log_path.parent
    root = (
        parent.parent / "run" / "dispatch_workdirs"
        if parent.name == "logs"
        else parent / ".dispatch-workdirs"
    )
    resolved_repo = repo_root.resolve()
    candidate = (root / prefix).resolve()
    if candidate == resolved_repo or resolved_repo in candidate.parents:
        root = Path(tempfile.gettempdir()) / "volpred-dispatch-workdirs" / resolved_repo.name
        candidate = (root / prefix).resolve()
    path = candidate
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    probe = subprocess.run(
        ["/usr/bin/git", "-C", str(path), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, timeout=5, check=False,
    )
    if probe.returncode == 0:
        raise RuntimeError(f"dispatch scratch cwd unexpectedly belongs to Git: {path}")
    return path


def _slot_prompt(
    prompt: str,
    *,
    slot_id: str,
    job_id: str,
    workdir: Path,
    repo_root: Path,
    workspace: dict[str, Any] | None = None,
) -> str:
    """Inject the stable namespace and non-main launch boundary."""
    prefix = f"dispatch-{slot_id}-{job_id[:8]}"
    workspace_section = (
        workspace_mod.prompt_fragment(workspace) + "\n" if workspace else ""
    )
    assigned_contract = (
        workspace
        if workspace and workspace.get("task_id")
        else None
    )
    repo_write_policy = (
        "本 fire 已由 OS sandbox 綁定 producer workspace；canonical_root 僅供讀取。"
        "task lifecycle 與 canonical/external effects 都由 supervisor 在 sandbox 外執行。"
        "禁止對 canonical_root 的 storage、程式、設定、文件、測試或 Git metadata 寫入；"
        "shell redirect 亦會被機械拒絕。"
        if workspace
        else
        "inline task 可用絕對路徑編輯 canonical_root，但禁止 cd 回 shared checkout 後裸跑"
        "任何 Git mutation；本班 canonical 變更由 cohort-drained PHASE-Z 單一提交。"
    )
    cwd_note = (
        "registered producer workspace" if workspace else "刻意不是 Git repo"
    )
    worktree_routing_policy = (
        "本 fire 已配發唯一 registered workspace，禁止另建 worktree；由 supervisor "
        "finalizer 負責 gate 與 landing。"
        if workspace
        else
        "若 task routing 明定 worktree，才用 canonical git_writer_lock.py run 建立名稱含"
        "worktree_prefix 的 registered linked worktree，並在本班結束前透過正式"
        "merge_worktree.sh 完整整合；不得留下未合併 branch/worktree。"
    )
    task_assignment = ""
    if assigned_contract is not None:
        task_assignment = (
            "[Supervisor-assigned mutating task]\n"
            f"task_id={assigned_contract['task_id']}; "
            f"claim_session_id={assigned_contract['claim_session_id']}; "
            f"declared_output_paths={json.dumps(assigned_contract.get('declared_output_paths') or [], ensure_ascii=False)}.\n"
            f"title={assigned_contract.get('task_title', '')}\n"
            f"description={assigned_contract.get('task_description', '')}\n"
            "這張 task 已由 supervisor 原子 claim+start。只完成這張，不跑 PHASE 0/A/B 的"
            "選工流程；不得再 claim/start/complete/release。只可修改 declared paths，"
            "不得 git add/commit；完成檔案與測試後停止。machine finalizer 會只 stage declared "
            "paths 並建立 candidate commit；landing、post-actions 與 complete 由 supervisor"
            "回讀後處理。\n\n"
        )
    base_prompt = (
        "[Supervisor multi-slot context]\n"
        f"slot_id={slot_id}; job_id={job_id}; worktree_prefix={prefix}.\n"
        f"launcher_cwd={workdir}（{cwd_note}）；canonical_root={repo_root}.\n"
        "本 fire 的 task-pool ownership token 已由 supervisor 放在"
        "$VOLPRED_TASK_CLAIM_OWNER；所有 claim、work_log owner/actor 都必須逐字使用它。"
        "缺少此環境變數即停止且回報 dispatcher identity error，禁止退回日期/小時或自訂名稱。"
        "此段規則優先於後文 PHASE-Z：先從 canonical_root 讀 AGENTS.md 與 handoff。"
        + repo_write_policy
        + worktree_routing_policy
        + (
            "task-pool lifecycle 已由 supervisor 擁有，worker 不得執行 canonical task CLI。"
            if assigned_contract
            else
            "若選到 platform_ops/governance，task CLI 會以 "
            "supervisor_preassignment_required 機械拒絕；換非 mutating task，禁止繞過。"
        )
        + "最後依原 PHASE Z 只留 fire receipt。\n\n"
        + task_assignment
        + workspace_section
        + prompt
    )
    return inject_external_report_contract(base_prompt)


def _task_pool_command(
    *,
    repo_root: Path,
    args: list[str],
) -> dict[str, Any]:
    """Run the canonical queue owner outside the producer sandbox."""
    proc = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "task_pool_claim.py"), *args],
        cwd=repo_root,
        env=external_child_environment(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {
            "ok": False,
            "reason": "task_pool_cli_unreadable",
            "rc": proc.returncode,
            "detail": (proc.stderr or proc.stdout or "")[-500:],
        }
    if proc.returncode != 0:
        existing_detail = payload.get("detail")
        detail = (
            proc.stderr
            or (existing_detail if isinstance(existing_detail, str) else "")
            or proc.stdout
            or ""
        )[-1000:]
        payload = {
            **payload,
            "ok": False,
            "reason": payload.get("reason") or "task_pool_cli_failed",
            "rc": proc.returncode,
            **({"detail": detail} if detail else {}),
        }
    return payload


def _preassign_mutating_task(
    *,
    repo_root: Path,
    slot_id: str,
    job_id: str,
) -> dict[str, Any]:
    owner = identity.task_claim_owner(
        role="hourly", slot_id=slot_id, job_id=job_id,
    )
    session = f"dispatch-{job_id[:8]}-{uuid.uuid4().hex[:8]}"
    return _task_pool_command(
        repo_root=repo_root,
        args=[
            "dispatch-preassign",
            "--owner",
            owner,
            "--session",
            session,
            "--job-id",
            job_id,
        ],
    )


def _settle_mutating_task(
    *,
    repo_root: Path,
    workspace: dict[str, Any],
    disposition: str,
    result: str,
) -> dict[str, Any]:
    return _task_pool_command(
        repo_root=repo_root,
        args=[
            "dispatch-settle",
            "--id",
            str(workspace["task_id"]),
            "--session",
            str(workspace["claim_session_id"]),
            "--disposition",
            disposition,
            "--result",
            result[:800],
        ],
    )


def _settlement_disposition(workspace_outcome: dict[str, Any]) -> str | None:
    disposition = str(workspace_outcome.get("disposition") or "")
    if disposition == "merged":
        return "merged"
    if (
        disposition == "remediation_opened"
        and bool((workspace_outcome.get("checkpoint") or {}).get("released"))
    ):
        return "remediation"
    if disposition == "empty_removed":
        return "empty"
    return None


def reconcile_task_settlements(
    *,
    repo_root: Path,
    state_path: Path,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Converge completion→finalize→queue settlement across daemon crashes."""
    snap = state.read_state(state_path)
    receipt_error = False
    for completion in reversed(snap.get("completions") or []):
        workspace = completion.get("workspace")
        if not isinstance(workspace, dict) or not workspace.get("task_id"):
            continue
        if not workspace_mod.ensure_task_settlement_pending(
            repo_root,
            workspace=workspace,
            job_id=str(completion.get("job_id") or ""),
            worker_outcome=str(completion.get("outcome") or "failure"),
            producer_custody=(
                completion.get("producer_custody")
                if isinstance(completion.get("producer_custody"), dict)
                else None
            ),
        ):
            receipt_error = True
    if receipt_error:
        return [{
            "ok": False,
            "reason": "completion_settlement_intent_not_durable",
        }]
    results: list[dict[str, Any]] = []
    for pending in workspace_mod.pending_task_settlements(repo_root, limit=limit):
        pending_job_id = str(pending.get("job_id") or "")
        active = _ACTIVE_FIRE_TASKS.get(pending_job_id)
        if active is not None and not active.done():
            # The owning fire task is between durable intent and settlement.
            # A new daemon has an empty process-local map and will reconcile;
            # this daemon must not race its own finalizer.
            continue
        workspace = pending.get("workspace")
        if not isinstance(workspace, dict):
            results.append({"ok": False, "reason": "pending_workspace_missing"})
            continue
        final = workspace_mod.finalize_workspace(
            repo_root=repo_root,
            workspace=workspace,
            worker_outcome=str(pending.get("worker_outcome") or "failure"),
            job_id=str(pending.get("job_id") or ""),
            producer_custody=(
                pending.get("producer_custody")
                if isinstance(pending.get("producer_custody"), dict)
                else None
            ),
            producer_drain_confirmed=(
                workspace_mod.legacy_workspace_producer_drain_confirmed(
                    repo_root,
                    workspace_name=str(workspace.get("name") or ""),
                    job_id=pending_job_id,
                )
            ),
        )
        disposition = _settlement_disposition(final)
        if disposition is None:
            results.append({
                "ok": False,
                "task_id": workspace.get("task_id"),
                "reason": "workspace_not_terminal",
                "workspace_disposition": final.get("disposition"),
            })
            continue
        settled = _settle_mutating_task(
            repo_root=repo_root,
            workspace=workspace,
            disposition=disposition,
            result=(
                f"reconciled workspace={final.get('disposition')}; "
                f"main_sha={final.get('main_sha', '')}"
            ),
        )
        if settled.get("ok") and workspace_mod.complete_task_settlement(
            repo_root,
            task_id=str(workspace["task_id"]),
            claim_session_id=str(workspace["claim_session_id"]),
            disposition=disposition,
            status=str(settled.get("status") or ""),
        ):
            state.defer_reserved_fire(
                job_id=str(pending.get("job_id") or ""),
                reason=(
                    "workspace_settlement_reconciled:"
                    f"{str(pending.get('job_id') or '')[:8]}"
                ),
                path=state_path,
            )
            results.append({**settled, "settlement_completed": True})
        else:
            results.append({**settled, "settlement_completed": False})
    return results


def reconcile_admission_settlements(
    *,
    repo_root: Path,
    state_path: Path,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Requeue preassigned tasks whose fire died before workspace binding."""
    outbox = _task_pool_command(
        repo_root=repo_root,
        args=["dispatch-pending", "--limit", str(limit)],
    )
    if not outbox.get("ok"):
        return [outbox]
    snap = state.read_state(state_path)
    active_job_ids = {
        str(job.get("job_id") or "")
        for job in (snap.get("current_jobs") or [])
        if isinstance(job, dict)
    }
    active_job_ids.update(
        job_id
        for job_id, task in _ACTIVE_FIRE_TASKS.items()
        if not task.done()
    )
    ownership = workspace_mod.task_settlement_ownership(repo_root)
    if not ownership.get("ok"):
        return [{
            "ok": False,
            "reason": str(
                ownership.get("reason") or "workspace_ownership_unavailable"
            ),
        }]
    workspace_owned = {
        (
            str(item.get("task_id") or ""),
            str(item.get("claim_session_id") or ""),
        )
        for item in (ownership.get("pending") or [])
    }
    workspace_owned.update(
        (
            str(workspace.get("task_id") or ""),
            str(workspace.get("claim_session_id") or ""),
        )
        for completion in (snap.get("completions") or [])
        if isinstance(completion, dict)
        for workspace in [completion.get("workspace")]
        if isinstance(workspace, dict) and workspace.get("task_id")
    )
    results: list[dict[str, Any]] = []
    for item in outbox.get("pending") or []:
        key = (
            str(item.get("task_id") or ""),
            str(item.get("claim_session_id") or ""),
        )
        if (
            not all(key)
            or str(item.get("dispatch_job_id") or "") in active_job_ids
            or key in workspace_owned
        ):
            continue
        settled = _settle_mutating_task(
            repo_root=repo_root,
            workspace={"task_id": key[0], "claim_session_id": key[1]},
            disposition="retry",
            result=(
                "reconciled admission crash before workspace binding; "
                f"job_id={item.get('dispatch_job_id', '')}"
            ),
        )
        results.append(settled)
    return results


def _phase_z_terminal(outcome: dict[str, Any] | None) -> bool:
    """Only release persistent drain tokens after a verified terminal outcome."""
    if not isinstance(outcome, dict):
        return False
    if outcome.get("committed") is True:
        return True
    reason = outcome.get("reason")
    if reason is None:  # compatibility with injected legacy hooks in tests
        return True
    return reason in _PHASE_Z_TERMINAL_REASONS


def _reap_fire_task(job_id: str, task: asyncio.Task) -> None:
    _ACTIVE_FIRE_TASKS.pop(job_id, None)
    if task.cancelled():
        LOG.warning("fire task cancelled job_id=%s", job_id)
        return
    exc = task.exception()
    if exc is not None:
        LOG.error("fire task crashed job_id=%s: %s", job_id, exc, exc_info=exc)
        alerts.send_loop_crash(
            f"fire_task:{job_id[:8]}",
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        )


def _reap_phase_z_recovery_task(task: asyncio.Task) -> None:
    """Observe a detached closeout and release the single-flight marker."""
    global _ACTIVE_PHASE_Z_RECOVERY_TASK
    if _ACTIVE_PHASE_Z_RECOVERY_TASK is task:
        _ACTIVE_PHASE_Z_RECOVERY_TASK = None
    if task.cancelled():
        LOG.warning("background PHASE-Z recovery task cancelled")
        return
    exc = task.exception()
    if exc is not None:
        LOG.error("background PHASE-Z recovery task crashed: %s", exc, exc_info=exc)
        alert_task = asyncio.create_task(
            asyncio.to_thread(
                alerts.send_loop_crash,
                "phase_z_recovery_task",
                "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                ),
            ),
            name="dispatch-phase-z-recovery-alert",
        )
        _BACKGROUND_ALERT_TASKS.add(alert_task)
        alert_task.add_done_callback(_reap_background_alert_task)
        return
    LOG.info("background PHASE-Z recovery task completed outcome=%s", task.result())


def _reap_background_alert_task(task: asyncio.Task) -> None:
    """Keep slow alert delivery observed without blocking the trigger loop."""
    _BACKGROUND_ALERT_TASKS.discard(task)
    if task.cancelled():
        LOG.warning("background dispatch alert task cancelled")
        return
    exc = task.exception()
    if exc is not None:
        LOG.error("background dispatch alert task crashed: %s", exc, exc_info=exc)


async def _run_reserved_fire(
    *,
    job_id: str,
    cohort_id: str,
    slot_id: str,
    prompt: str,
    scheduled_for: str,
    fire_reason: str,
    log_path: Path,
    state_path: Path,
    repo_root: Path,
    workdir: Path | None = None,
    fire_workspace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one already-admitted logical fire and close its cohort safely."""
    phase_z_outcome: dict | None = None
    workspace_outcome: dict | None = None
    result = None
    worker_exc: BaseException | None = None
    try:
        result = await asyncio.to_thread(
            worker.run_worker,
            prompt_text=prompt, schedule_id=SCHEDULE_ID,
            scheduled_for=scheduled_for, fire_reason=fire_reason,
            log_path=log_path, state_path=state_path,
            job_id=job_id, slot_id=slot_id,
            workdir=workdir,
            isolated_workspace=fire_workspace,
        )
        LOG.info(
            "worker returned job_id=%s slot=%s outcome=%s attempts=%d duration=%.1fs",
            job_id, slot_id, result.outcome, result.attempts, result.duration_s,
        )
        # Worker owns the normal close. This exact-id safety net covers a
        # crashed/mocked worker that returned without recording completion; it
        # can never close a sibling or a later job that reused the slot.
        own = next(
            (job for job in (state.read_state(state_path).get("current_jobs") or [])
             if str(job.get("job_id")) == job_id),
            None,
        )
        if (
            own is not None
            and own.get("pid") is None
            and own.get("phase") not in {
                "kill_failed_orphan",
                "timeout_unverified",
                "orphan_unverified_not_killed",
            }
            and result.outcome not in {
                "kill_failed_orphan",
                "timeout_unverified",
                "orphan_unverified_not_killed",
            }
        ):
            state.record_completion(
                job_id=job_id, expected_attempt=int(own.get("attempt", result.attempts)),
                expected_pid=own.get("pid"), exit_code=result.exit_code,
                outcome=result.outcome,
                final_model=getattr(result, "final_model", str(own.get("model") or "unknown")),
                path=state_path,
            )
    except BaseException as exc:  # preserve traceback after cohort cleanup
        worker_exc = exc
        own = next(
            (job for job in (state.read_state(state_path).get("current_jobs") or [])
             if str(job.get("job_id")) == job_id),
            None,
        )
        if own is not None and own.get("pid") is None:
            producer_custody = (
                own.get("producer_custody")
                if isinstance(own.get("producer_custody"), dict)
                else None
            )
            members = (
                procutil.producer_cohort_members_checked(
                    0,
                    job_id=job_id,
                    custody=producer_custody,
                )
                if producer_custody is not None
                else []
                if own.get("producer_spawn_state") == "not_started"
                else None
            )
            if members == []:
                state.record_completion(
                    job_id=job_id,
                    expected_attempt=int(own.get("attempt", 1)),
                    exit_code=-1,
                    outcome=(
                        "failure"
                        if producer_custody is not None
                        else "spawn_not_started"
                    ),
                    final_model=str(own.get("model") or "unknown"),
                    path=state_path,
                )
            else:
                state.mark_job_phase(
                    job_id=job_id,
                    phase="orphan_unverified_no_pid",
                    expected_attempt=int(own.get("attempt", 1)),
                    path=state_path,
                )
                LOG.error(
                    "worker failed before pid attach and custody is %s; "
                    "retaining slot job_id=%s members=%s",
                    "unverified" if members is None else "active",
                    job_id,
                    members,
                )
    finally:
        # Close the producer-side state machine before any workspace/PHASE-Z
        # consumer reads it. fire_receipt normally seals successful output;
        # this also seals a genuinely no-output success and gives failed/dead
        # producers the named ABANDONED exit instead of a six-hour anonymous
        # open claim. The ledger remains shadow-only here.
        try:
            from volpred.ops import fire_manifest

            manifest = fire_manifest.read(repo_root, job_id)
            if manifest and manifest.get("state") == fire_manifest.STATE_OPEN:
                worker_outcome = result.outcome if result is not None else "failure"
                if worker_outcome in {"success", "codex_failover_recovered"}:
                    fire_manifest.seal(repo_root, job_id)
                else:
                    fire_manifest.close(
                        repo_root, job_id, state=fire_manifest.STATE_ABANDONED,
                        reason=f"worker_outcome={worker_outcome}",
                    )
        except Exception as exc:  # noqa: BLE001 — attribution must never skip closeout
            LOG.warning("fire manifest closeout failed job_id=%s: %s", job_id, exc)
        # ── WS-B workspace finalize (before the PHASE-Z drain) ──────────────
        # The isolated lane's output lands (or goes to remediation) through its
        # OWN gate here, so PHASE-Z only ever sees canonical-root residue.
        # finalize_workspace never raises; belt-and-suspenders anyway because a
        # crash here must not skip the cohort drain below.
        if fire_workspace is not None:
            try:
                custody_snapshot = state.read_state(state_path)
                custody_sources = [
                    *(custody_snapshot.get("current_jobs") or []),
                    *reversed(custody_snapshot.get("completions") or []),
                ]
                terminal_record = next(
                    (
                        item
                        for item in custody_sources
                        if str(item.get("job_id") or "") == job_id
                    ),
                    {},
                )
                worker_outcome = (
                    result.outcome
                    if result is not None
                    else str(
                        terminal_record.get("outcome")
                        or terminal_record.get("phase")
                        or "failure"
                    )
                )
                producer_custody = (
                    terminal_record.get("producer_custody")
                    if isinstance(terminal_record.get("producer_custody"), dict)
                    else None
                )
                workspace_outcome = await asyncio.to_thread(
                    workspace_mod.finalize_workspace,
                    repo_root=repo_root, workspace=fire_workspace,
                    worker_outcome=worker_outcome, job_id=job_id,
                    producer_custody=producer_custody,
                )
                LOG.info("workspace finalize job_id=%s disposition=%s",
                         job_id, (workspace_outcome or {}).get("disposition"))
            except Exception as exc:  # noqa: BLE001
                LOG.exception("workspace finalize crashed job_id=%s: %s", job_id, exc)
            if fire_workspace.get("task_id"):
                workspace_disposition = str(
                    (workspace_outcome or {}).get("disposition") or "failure"
                )
                settlement_disposition = _settlement_disposition(
                    workspace_outcome or {}
                )
                settlement = {"ok": False, "reason": "workspace_not_terminal"}
                if settlement_disposition is not None:
                    settlement = await asyncio.to_thread(
                        _settle_mutating_task,
                        repo_root=repo_root,
                        workspace=fire_workspace,
                        disposition=settlement_disposition,
                        result=(
                            f"worker={getattr(result, 'outcome', 'failure')}; "
                            f"workspace={workspace_disposition}; "
                            f"main_sha={(workspace_outcome or {}).get('main_sha', '')}"
                        ),
                    )
                    if settlement.get("ok"):
                        await asyncio.to_thread(
                            workspace_mod.complete_task_settlement,
                            repo_root,
                            task_id=str(fire_workspace["task_id"]),
                            claim_session_id=str(
                                fire_workspace["claim_session_id"]
                            ),
                            disposition=settlement_disposition,
                            status=str(settlement.get("status") or ""),
                        )
                LOG.info(
                    "workspace task settlement job_id=%s task_id=%s result=%s",
                    job_id,
                    fire_workspace.get("task_id"),
                    settlement,
                )
        global _PHASE_Z_LOCK
        if _PHASE_Z_LOCK is None:
            _PHASE_Z_LOCK = asyncio.Lock()
        async with _PHASE_Z_LOCK:
            fresh = state.read_state(state_path)
            remaining = fresh.get("current_jobs") or []
            cohort_pending = [
                item for item in (fresh.get("phase_z_pending") or [])
                if str(item.get("cohort_id")) == cohort_id
            ]
            if remaining:
                phase_z_outcome = {
                    "committed": False,
                    "reason": "deferred_until_cohort_drain",
                    "remaining_jobs": len(remaining),
                }
                LOG.info(
                    "phase_z deferred job_id=%s slot=%s remaining=%d",
                    job_id, slot_id, len(remaining),
                )
            elif not cohort_pending:
                phase_z_outcome = {
                    "committed": False, "reason": "already_drained",
                }
            else:
                try:
                    # WS-B: baseline authorship guessing is demoted to fallback
                    # only when EVERY fire in the drained cohort was isolated
                    # (state.record_completion stamps `isolated` per fire). One
                    # unisolated sibling keeps the full legacy behaviour.
                    isolated_cohort = all(
                        bool(item.get("isolated")) for item in cohort_pending
                    )
                    durable_baseline, generation = _matching_fire_lifecycle(
                        cohort_pending
                    )
                    cohort_ids = {
                        str(item.get("cohort_id")) for item in cohort_pending
                    }
                    phase_z_kwargs = {
                        "repo_root": repo_root,
                        "isolated_cohort": isolated_cohort,
                        "claim_owners": _phase_z_claim_owners(cohort_pending),
                        "fire_ids": {
                            str(item["job_id"])
                            for item in cohort_pending
                            if item.get("job_id")
                        },
                    }
                    if durable_baseline is not None:
                        phase_z_kwargs["pre_fire_dirty"] = durable_baseline
                        state.begin_phase_z(
                            cohort_ids=cohort_ids,
                            generation_id=generation,
                            base_head=_git_head(repo_root),
                            path=state_path,
                        )
                        recovered_commit = _phase_z_terminal_commit(
                            repo_root=repo_root,
                            pending=state.read_state(state_path).get(
                                "phase_z_pending"
                            ) or [],
                            generation_id=generation,
                        )
                        if recovered_commit:
                            phase_z_outcome = await asyncio.to_thread(
                                phase_z.recover_committed_closeout,
                                repo_root=repo_root,
                                commit_sha=recovered_commit,
                                generation_id=generation,
                                claim_owners=_phase_z_claim_owners(
                                    cohort_pending
                                ),
                            )
                        else:
                            phase_z_kwargs["closeout_generation"] = generation
                    else:
                        phase_z_outcome = _reject_unmatched_generation(
                            pending=cohort_pending,
                            reason=generation,
                            state_path=state_path,
                        )
                    if phase_z_outcome is None:
                        phase_z_outcome = await asyncio.to_thread(
                            phase_z.run_phase_z, **phase_z_kwargs,
                        )
                    LOG.info("phase_z cohort drain job_id=%s outcome=%s", job_id, phase_z_outcome)
                except Exception as exc:  # noqa: BLE001
                    LOG.warning("phase_z safety-net failed (non-fatal): %s", exc)
                if _phase_z_terminal(phase_z_outcome):
                    cleared = state.finish_phase_z(
                        cohort_id=cohort_id,
                        path=state_path,
                        terminal_outcome=phase_z_outcome,
                        generation_id=generation,
                    )
                    LOG.info("phase_z cohort released cohort=%s pending=%d", cohort_id, cleared)
                elif _phase_z_drain_exhausted(cohort_id=cohort_id, outcome=phase_z_outcome,
                                              state_path=state_path):
                    cleared = state.finish_phase_z(cohort_id=cohort_id, path=state_path)
                    LOG.error("phase_z gave up after retries; token released cohort=%s "
                              "outcome=%s pending=%d", cohort_id, phase_z_outcome, cleared)
                else:
                    LOG.error(
                        "phase_z non-terminal; retaining drain token cohort=%s outcome=%s",
                        cohort_id, phase_z_outcome,
                    )
    if worker_exc is not None:
        raise worker_exc
    assert result is not None
    return {
        "action": "fired", "outcome": result.outcome,
        "attempts": result.attempts, "exit_code": result.exit_code,
        "phase_z": phase_z_outcome, "fire_reason": fire_reason,
        "job_id": job_id, "slot_id": slot_id,
        "workspace": workspace_outcome,
    }


PREGATE_SCRIPT = ROOT / "scripts" / "hourly_dispatch_pregate.py"
PREGATE_TIMEOUT_S = 60
PREGATE_MODES = ("off", "shadow", "enforce")


def load_pregate_config(*, schedules_path: Path = SCHEDULES_PATH, schedule_id: str = SCHEDULE_ID) -> dict[str, Any]:
    """Read the pregate config from the canonical schedule entry.

    2026-07-10 rewire: scripts/hourly_dispatch_pregate.py (zero-token "is this
    cron slot worth the ~95K claude -p cold-load?" triage) was orphaned by the
    7/4 supervisor cutover — it was only wired into the legacy shell. This
    reads `pregate: {mode, window_hours}` from the volpred-hourly-dispatch
    entry so the flip shadow→enforce is a config edit, no daemon restart
    (scheduler_loop re-reads config every tick).

    Fail-open: missing/invalid config → mode "off" (never skip on uncertainty).
    """
    fallback = {"mode": "off", "window_hours": 3.0}
    try:
        data = json.loads(schedules_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        LOG.warning("load_pregate_config fail-open mode=off: %s", exc)
        return fallback
    for key in ("cron_jobs", "items"):
        entries = data.get(key) or []
        if not isinstance(entries, list):
            continue
        for item in entries:
            if not isinstance(item, dict) or item.get("id") != schedule_id:
                continue
            cfg = item.get("pregate")
            if not isinstance(cfg, dict):
                return fallback
            mode = str(cfg.get("mode", "off")).lower()
            if mode not in PREGATE_MODES:
                LOG.warning("pregate mode %r invalid — fail-open mode=off", mode)
                mode = "off"
            try:
                window_hours = float(cfg.get("window_hours", 3.0))
            except (TypeError, ValueError):
                LOG.warning("pregate window_hours %r invalid — using 3.0", cfg.get("window_hours"))
                window_hours = 3.0
            return {"mode": mode, "window_hours": window_hours}
    return fallback


def _run_pregate(*, mode: str, window_hours: float) -> bool:
    """Run the zero-token pregate as a subprocess. Returns True = SKIP this fire.

    Subprocess (not import) so a pregate crash can never take down the daemon.
    Pregate CLI exit semantics: 0 = SKIP, anything else = PROCEED — a crash
    (exit≠0) or timeout is therefore inherently fail-open. In shadow mode we
    pass --shadow: pregate always exits 1 (proceed) but appends the would-be
    decision to storage/logs/hourly_pregate.jsonl for the observation window.
    """
    cmd = [sys.executable, str(PREGATE_SCRIPT), "--window-hours", str(window_hours),
           "--invoker", "supervisor"]
    if mode == "shadow":
        cmd.append("--shadow")
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=PREGATE_TIMEOUT_S, cwd=str(ROOT), check=False,
            env=external_child_environment(),
        )
    except subprocess.TimeoutExpired:
        LOG.warning("pregate timeout after %ss — fail-open PROCEED", PREGATE_TIMEOUT_S)
        return False
    except OSError as exc:
        LOG.warning("pregate spawn failed (%s) — fail-open PROCEED", exc)
        return False
    if proc.returncode == 0:
        return True
    if proc.returncode != 1:
        LOG.warning("pregate unexpected exit=%s stderr=%s — fail-open PROCEED",
                    proc.returncode, (proc.stderr or "")[-300:])
    return False


def _prev_fire(cron_expr: str, *, now: datetime | None = None) -> datetime:
    base = now or datetime.now()
    return croniter(cron_expr, base).get_prev(datetime)


def _next_fire(cron_expr: str, *, now: datetime | None = None) -> datetime:
    base = now or datetime.now()
    return croniter(cron_expr, base).get_next(datetime)


def _parse_last_fire(raw: str | None) -> datetime | None:
    """`last_fire_at` as a naive-local datetime, or None if missing/unparseable.

    tz-naive cron + tz-aware state: croniter's `prev` is naive local, so an
    aware stored value must be converted to the same frame before comparing.
    """
    if not raw:
        return None
    dt = parse_iso_warn(
        raw,
        tag="supervisor",
        field_name="last_fire_at",
        fallback=None,
        assume_tz=None,
    )
    if dt is None:
        return None  # parse failed → parse_iso_warn already emitted a WARN
    return dt.astimezone().replace(tzinfo=None) if dt.tzinfo is not None else dt


def _due_to_fire(*, cron_expr: str, last_fire_at: str | None, now: datetime | None = None) -> tuple[bool, datetime]:
    """Decide if we should fire now. Returns (due, prev_scheduled_fire).

    2026-07-10 root-cause fix. This used to `return True` when `last_fire_at`
    was missing or unparseable — "we don't know when we last fired" was treated
    as "fire right now". In a 60s-tick daemon that turns any loss of
    `dispatch_state.json` into an immediate ~95K opus cold-load, and keeps
    firing every tick until something writes the field back.

    That is exactly what happened: an external writer reset production state
    (daemon never logged a reset of its own), and the very next tick fired an
    off-slot duplicate of the 22:07 slot at 22:58. Log audit: 9 such off-slot
    fires in 159 (+24…+54 min after their slot), each a full cold-load.

    Unknown is now NOT due. `_tick_once` bootstraps the field and we resume on
    the next real cron slot — worst case one skipped hour, never a burn.
    """
    prev = _prev_fire(cron_expr, now=now)
    last_dt = _parse_last_fire(last_fire_at)
    if last_dt is None:
        return False, prev
    return last_dt < prev, prev


def _load_prompt(path: Path = DEFAULT_PROMPT_PATH) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        LOG.error("prompt file missing: %s", path)
        return ""


async def scheduler_loop(
    *,
    state_path: Path = state.STATE_PATH,
    schedules_path: Path = SCHEDULES_PATH,
    prompt_path: Path = DEFAULT_PROMPT_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
    tick_interval_s: int = TICK_INTERVAL_S,
    dry_run: bool = False,
) -> None:
    """Long-running scheduler. Loops until cancelled."""
    cron_expr = load_cron_expr(schedules_path=schedules_path)
    LOG.info("scheduler_loop start cron=%r dry_run=%s tick=%ds", cron_expr, dry_run, tick_interval_s)
    while True:
        try:
            await asyncio.sleep(tick_interval_s)
            await _tick_once(
                state_path=state_path, cron_expr=cron_expr,
                prompt_path=prompt_path, log_path=log_path,
                dry_run=dry_run, schedules_path=schedules_path,
                background=True,
            )
            # reload cron expr in case ops changed config mid-run
            cron_expr = load_cron_expr(schedules_path=schedules_path)
        except asyncio.CancelledError:
            LOG.info("scheduler_loop cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            # Codex review §10 #7 fix: this used to only LOG.exception — a
            # crash-looping scheduler (the ONLY thing that ever fires
            # hourly-dispatch) would silently stop dispatching with zero
            # alert. Escalate so the boss sees it instead of discovering a
            # dispatch drought hours later.
            LOG.exception("scheduler tick crashed: %s", exc)
            alerts.send_loop_crash("scheduler_loop", traceback.format_exc(), state_path=state_path)


async def _tick_once(
    *,
    state_path: Path,
    cron_expr: str,
    prompt_path: Path,
    log_path: Path,
    dry_run: bool,
    repo_root: Path = ROOT,
    schedules_path: Path = SCHEDULES_PATH,
    background: bool = False,
    max_slots: int | None = None,
    _closeout_only: bool = False,
) -> dict[str, Any]:
    """One tick. Returns a small dict describing the decision (for tests + audit log)."""
    global _ACTIVE_PHASE_Z_RECOVERY_TASK
    state.heartbeat(path=state_path)
    pre_reconcile = state.read_state(state_path)
    active_jobs = list(pre_reconcile.get("current_jobs") or [])
    if active_jobs:
        # Shared-coalition safety mode: any scheduler subprocess started while a
        # producer reservation is crossing capture/Popen, or while its producer
        # is live, would inherit the same coalition and become indistinguishable
        # from producer output. Do no reconciliation, git, task-pool, or
        # admission work until the sole slot drains.
        return {
            "action": "skip",
            "reason": "producer_slot_in_flight",
            "active_jobs": len(active_jobs),
        }
    pending_at_entry = list(pre_reconcile.get("phase_z_pending") or [])
    if background and pending_at_entry:
        active_recovery = _ACTIVE_PHASE_Z_RECOVERY_TASK
        if active_recovery is not None and not active_recovery.done():
            return {
                "action": "skip",
                "reason": "phase_z_recovery_in_progress",
                "phase_z_pending": len(pending_at_entry),
            }
        recovery = asyncio.create_task(
            _tick_once(
                state_path=state_path,
                cron_expr=cron_expr,
                prompt_path=prompt_path,
                log_path=log_path,
                dry_run=dry_run,
                repo_root=repo_root,
                schedules_path=schedules_path,
                background=False,
                max_slots=max_slots,
                _closeout_only=True,
            ),
            name="dispatch-phase-z-recovery",
        )
        _ACTIVE_PHASE_Z_RECOVERY_TASK = recovery
        recovery.add_done_callback(_reap_phase_z_recovery_task)
        return {
            "action": "phase_z_recovery_started",
            "phase_z_pending": len(pending_at_entry),
        }
    try:
        custody_recovery = await asyncio.to_thread(
            custody_receipt.reconcile_pending_producer_custodies,
            repo_root,
        )
    except custody_receipt.CustodyReceiptError as exc:
        LOG.error("producer custody admission gate unavailable: %s", exc)
        return {
            "action": "skip",
            "reason": "producer_custody_ledger_unavailable",
        }
    if not custody_recovery.get("ok"):
        LOG.error(
            "producer custody admission gate unresolved: %s",
            custody_recovery,
        )
        return {
            "action": "skip",
            "reason": "producer_custody_recovery_unresolved",
            "unresolved": len(custody_recovery.get("unresolved") or []),
        }
    if custody_recovery.get("released"):
        LOG.warning(
            "producer custody admission recovered=%s",
            custody_recovery["released"],
        )
    if (Path(repo_root) / ".git").exists():
        protected_workspace_jobs = (
            [
                str(job.get("job_id") or "")
                for job in (pre_reconcile.get("current_jobs") or [])
            ]
            + [
                str(item.get("job_id") or "")
                for item in (pre_reconcile.get("phase_z_pending") or [])
            ]
            + [
                str(item.get("job_id") or "")
                for item in (pre_reconcile.get("completions") or [])
            ]
        )
        swept = await asyncio.to_thread(
            workspace_mod.sweep_orphan_workspaces,
            repo_root=repo_root,
            protected_job_ids=protected_workspace_jobs,
        )
        if swept:
            LOG.info(
                "pre-admission orphan workspace reconciliation=%s",
                [item.get("disposition") for item in swept],
            )
    settlements = await asyncio.to_thread(
        reconcile_task_settlements,
        repo_root=repo_root,
        state_path=state_path,
    )
    if settlements:
        LOG.info("task settlement reconciliation results=%s", settlements)
    admission_settlements: list[dict[str, Any]] = []
    if (Path(repo_root) / "scripts" / "task_pool_claim.py").is_file():
        admission_settlements = await asyncio.to_thread(
            reconcile_admission_settlements,
            repo_root=repo_root,
            state_path=state_path,
        )
    if admission_settlements:
        LOG.info(
            "admission settlement reconciliation results=%s",
            admission_settlements,
        )
    snap = state.read_state(state_path)
    pending_phase_z = snap.get("phase_z_pending") or []
    if pending_phase_z:
        still_running = snap.get("current_jobs") or []
        if still_running:
            return {
                "action": "skip", "reason": "cohort_still_running",
                "active_slots": len(still_running),
                "phase_z_pending": len(pending_phase_z),
            }
        outcome: dict[str, Any] | None = None
        global _PHASE_Z_LOCK
        if _PHASE_Z_LOCK is None:
            _PHASE_Z_LOCK = asyncio.Lock()
        async with _PHASE_Z_LOCK:
            # Re-read inside the process-local git mutex. A fire task may have
            # drained/finished the cohort while this tick waited for the lock.
            fresh = state.read_state(state_path)
            pending_phase_z = fresh.get("phase_z_pending") or []
            if fresh.get("current_jobs"):
                return {"action": "skip", "reason": "cohort_still_running"}
            if not pending_phase_z:
                return {"action": "phase_z_already_drained", "phase_z": None}
            durable_baseline, generation = _matching_fire_lifecycle(pending_phase_z)
            if durable_baseline is None:
                # A fresh process may observe a token written by an older daemon
                # or a crash between reservation and lifecycle binding. It must
                # not execute that old closeout against whichever singleton
                # snapshot happens to exist now.
                rejection = _reject_unmatched_generation(
                    pending=pending_phase_z,
                    reason=generation,
                    state_path=state_path,
                )
                return {
                    "action": "phase_z_generation_rejected",
                    "reason": generation,
                    "pending_jobs": len(pending_phase_z),
                    "rejected": rejection["rejected"],
                    "alert": rejection["alert"],
                }
            # WS-B: same demotion rule as the fire-task drain — every pending
            # fire must have been isolated for the recovery drain to skip
            # baseline authorship guessing on repo bytes.
            recovery_isolated = all(
                bool(item.get("isolated")) for item in pending_phase_z
            )
            cohorts = {
                str(item.get("cohort_id")) for item in pending_phase_z
            }
            state.begin_phase_z(
                cohort_ids=cohorts,
                generation_id=generation,
                base_head=_git_head(repo_root),
                path=state_path,
            )
            pending_phase_z = (
                state.read_state(state_path).get("phase_z_pending") or []
            )
            recovered_commit = _phase_z_terminal_commit(
                repo_root=repo_root,
                pending=pending_phase_z,
                generation_id=generation,
            )
            if recovered_commit:
                outcome = await asyncio.to_thread(
                    phase_z.recover_committed_closeout,
                    repo_root=repo_root,
                    commit_sha=recovered_commit,
                    generation_id=generation,
                    claim_owners=_phase_z_claim_owners(pending_phase_z),
                )
            else:
                outcome = await asyncio.to_thread(
                    phase_z.run_phase_z, repo_root=repo_root,
                    isolated_cohort=recovery_isolated,
                    claim_owners=_phase_z_claim_owners(pending_phase_z),
                    pre_fire_dirty=durable_baseline,
                    closeout_generation=generation,
                    fire_ids={
                        str(item["job_id"])
                        for item in pending_phase_z
                        if item.get("job_id")
                    },
                )
            if _phase_z_terminal(outcome):
                for cohort in cohorts:
                    state.finish_phase_z(
                        cohort_id=cohort,
                        path=state_path,
                        terminal_outcome=outcome,
                        generation_id=generation,
                    )
                if recovered_commit:
                    return {
                        "action": "phase_z_receipt_recovered",
                        "phase_z": outcome,
                        "generation_id": generation,
                        "commit_sha": recovered_commit,
                    }
            else:
                # Same bounded retry as the fire-time drain: one run_phase_z per
                # tick serves the whole backlog, so every pending cohort's counter
                # moves together and exhausted ones die instead of spinning.
                released = 0
                for cohort in {str(item.get("cohort_id")) for item in pending_phase_z}:
                    if _phase_z_drain_exhausted(cohort_id=cohort, outcome=outcome,
                                                state_path=state_path):
                        state.finish_phase_z(cohort_id=cohort, path=state_path)
                        released += 1
                if released:
                    LOG.error("phase_z gave up after retries; released %d token(s) outcome=%s",
                              released, outcome)
                    return {
                        "action": "phase_z_gave_up", "phase_z": outcome,
                        "released": released,
                    }
                return {
                    "action": "phase_z_recovery_pending", "phase_z": outcome,
                    "pending_jobs": len(pending_phase_z),
                }
        return {
            "action": "phase_z_recovered", "phase_z": outcome,
            "pending_jobs": len(pending_phase_z),
        }
    if _closeout_only:
        return {
            "action": "skip",
            "reason": "phase_z_already_drained",
        }
    # Issue #42 deployment-drain gate.  The health loop can activate an
    # immutable release only when both current_jobs and phase_z_pending are
    # empty.  Without this admission stop, the scheduler can fill the just-
    # drained slot before the next health tick and starve a durable reload
    # request indefinitely (live request 749b49b3 -> job 5738de9c, 2026-07-30).
    try:
        if deferred_reload.active_request_pending():
            return {
                "action": "skip",
                "reason": "deferred_reload_pending",
            }
    except deferred_reload.DeferredReloadError as exc:
        LOG.error("deferred reload admission state unavailable: %s", exc)
        return {
            "action": "skip",
            "reason": "deferred_reload_intent_unreadable",
        }
    # ── WS-H4 step 2: collect inputs, let decision.decide() own the verdict ──
    # All reads happen here; decide() is pure. Dry-run and fire consume the
    # SAME Decision — they may only diverge at the write boundary below.
    current_jobs = snap.get("current_jobs") or []
    # Concurrent members of one cohort share the first fire's exact baseline.
    # The value is copied into every reserved job before its worker can spawn.
    fire_lifecycle = (
        dict(current_jobs[0]["fire_lifecycle"])
        if current_jobs and isinstance(current_jobs[0].get("fire_lifecycle"), dict)
        else None
    )
    capacity = max_slots if max_slots is not None else load_max_slots(schedules_path=schedules_path)
    due, prev_fire = _due_to_fire(cron_expr=cron_expr, last_fire_at=snap.get("last_fire_at"))
    pregate_cfg = load_pregate_config(schedules_path=schedules_path)
    # Peek (not consume) the out-of-band request: a request deliberately
    # survives auth / full-pool / bootstrap skips, so consumption may only
    # happen after the admission gates pass (below).
    peeked_request, peeked_request_id = state.fire_request_snapshot(snap)
    dec_input = decision.DecisionInput(
        auth_blocked=bool(snap.get("auth_blocked")),
        active_slots=len(current_jobs),
        capacity=capacity,
        quota_derated=quota_derate_active(state_path),
        last_fire_known=_parse_last_fire(snap.get("last_fire_at")) is not None,
        due=due,
        prev_fire=prev_fire.isoformat(),
        fire_request=peeked_request,
        pregate_mode=pregate_cfg["mode"],
    )
    dec = decision.decide(dec_input)
    if dec.action == decision.ACTION_SKIP:
        if dec.reason == "auth_blocked":
            return {"action": "skip", "reason": "auth_blocked"}
        if dec.reason == "slots_full":
            return {
                "action": "skip", "reason": "slots_full",
                "active_slots": len(current_jobs), "max_slots": capacity,
            }
        if dec.reason == "bootstrap_last_fire_at":
            # Cold start, or `dispatch_state.json` was lost / clobbered by an
            # external writer (the daemon logs its own resets; a silent loss is
            # someone else's write). `_due_to_fire` refuses to treat "unknown"
            # as "due" — so stamp the field and let the NEXT real slot fire.
            # Without this bootstrap the daemon would never fire again.
            with state._locked_state(state_path) as (_fh, data):
                if _parse_last_fire(data.get("last_fire_at")) is None:
                    data["last_fire_at"] = state._now()
            LOG.warning(
                "last_fire_at missing/unparseable (cold start or external state loss) — "
                "bootstrapped to now; the next scheduled slot fires normally. "
                "NOT firing an off-slot catch-up (2026-07-10: that cost 9 stray ~95K cold-loads)."
            )
            return {"action": "skip", "reason": "bootstrap_last_fire_at"}
        return {"action": "skip", "reason": "not_due", "prev_fire": prev_fire.isoformat()}
    # Git conflict guard (2026-07-10 rewire; see phase_z.run_pre_fire_guard).
    # Orphaned by the 7/4 cutover — its only caller was the now-unloaded
    # cron_hourly_dispatch.sh, while the concurrent-writer risk it backstops
    # (dispatcher + always-on codex_loop on one branch) never went away.
    #
    # Ordered BEFORE the pregate, exactly as the legacy shell had it ("run the
    # watchdog FIRST so every hourly slot starts on a clean, valid tree"): the
    # files it repairs are read by the live site AND by the pregate itself, not
    # only by the dispatched agent, so a pregate-skipped slot still deserves a
    # clean tree. dry_run touches no repo → never guards.
    #
    # try/except is belt-and-suspenders: run_pre_fire_guard is already no-raise
    # and fail-open, but a guard must never be able to veto the dispatch it
    # guards (same rationale as the phase_z call below).
    if not dry_run and not current_jobs:
        try:
            recovery_outcome = await asyncio.to_thread(
                phase_z.recover_failed_closeout, repo_root=repo_root,
            )
            LOG.info("phase_z failed-closeout recovery outcome=%s", recovery_outcome)
        except Exception as exc:  # noqa: BLE001
            # Recovery is additive. It must never suppress the pre-existing
            # conflict guard or veto the fire if its own receipt is damaged.
            LOG.warning("phase_z failed-closeout recovery failed (non-fatal): %s", exc)
        try:
            guard_outcome = await asyncio.to_thread(phase_z.run_pre_fire_guard, repo_root=repo_root)
            if (
                isinstance(guard_outcome, dict)
                and isinstance(guard_outcome.get("fire_lifecycle"), dict)
            ):
                fire_lifecycle = dict(guard_outcome["fire_lifecycle"])
            LOG.info("pre_fire_guard outcome=%s", guard_outcome)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("pre_fire_guard failed (non-fatal, firing anyway): %s", exc)
    # Zero-token pregate (2026-07-10 rewire; see load_pregate_config docstring).
    # Gates ONLY plain cron fires — requested fires always run. Shadow mode
    # never skips (pregate exits 1) but logs the would-be decision for the
    # observation window before the config flip to enforce.
    #
    # WS-H4 (2026-07-20): dry-run used to bypass the pregate entirely, which made
    # "--dry-run output == real fire decision" structurally impossible whenever
    # mode != off (docs/dispatch-decision-pipeline-design.md §1.1). Both paths
    # now collect the demand signal here and hand it to the SAME decide(); only
    # the write boundary (reserve_fire / worker spawn) differs.
    if dec.action == decision.ACTION_COLLECT_DEMAND:
        pregate_skip = await asyncio.to_thread(
            _run_pregate,
            mode=pregate_cfg["mode"], window_hours=pregate_cfg["window_hours"],
        )
        dec_input = dataclasses.replace(dec_input, demand={"pregate_skip": bool(pregate_skip)})
        dec = decision.decide(dec_input)
        if dec.action == decision.ACTION_SKIP:  # reason=pregate_skip, enforce mode only
            LOG.info("pregate SKIP — no work worth the cold-load; slot consumed (prev_scheduled=%s)",
                     prev_fire.isoformat())
            # consume the slot like dry_run does, so we don't re-evaluate
            # every tick for the rest of the hour
            with state._locked_state(state_path) as (_fh, data):
                data["last_fire_at"] = state._now()
            result = {"action": "pregate_skip", "prev_fire": prev_fire.isoformat()}
            if dry_run:
                result["dry_run"] = True
            return result
    if dec.action != decision.ACTION_FIRE:  # decide() contract: fire is all that remains
        LOG.error("decision pipeline returned unexpected action=%r reason=%r — skipping tick",
                  dec.action, dec.reason)
        return {"action": "skip", "reason": f"decision_error:{dec.action}"}
    if dry_run:
        LOG.info("DRY-RUN would fire (prev_scheduled=%s)", prev_fire.isoformat())
        # H4 dry-run is observational for demand: it tracks the schedule slot
        # but must not consume an owner request or reserve/spawn a worker.
        with state._locked_state(state_path) as (_fh, data):
            data["last_fire_at"] = state._now()
        return {"action": "dry_run_fire", "prev_fire": prev_fire.isoformat()}
    prompt = _load_prompt(prompt_path)
    if not prompt:
        LOG.error("empty prompt — refusing to fire")
        return {"action": "skip", "reason": "empty_prompt"}
    cohort_id = str(current_jobs[0].get("cohort_id")) if current_jobs else None
    try:
        with deferred_reload.admission_gate() as admission_open:
            if not admission_open:
                return {
                    "action": "skip",
                    "reason": "deferred_reload_pending",
                }
            final_input = dec_input
            final_dec = dec
            expected_request = dec_input.fire_request
            expected_request_id = peeked_request_id
            for request_attempt in range(2):
                fire_reason = final_dec.fire_reason or "cron"
                try:
                    lease = state.reserve_fire(
                        schedule_id=SCHEDULE_ID,
                        attempt=1,
                        model=worker.OPUS_MODEL,
                        log_path=str(log_path),
                        scheduled_for=prev_fire.isoformat(),
                        fire_reason=fire_reason,
                        max_slots=capacity,
                        cohort_id=cohort_id,
                        fire_key=(
                            f"cron:{prev_fire.isoformat()}"
                            if fire_reason.startswith("cron")
                            else None
                        ),
                        consume_request=True,
                        expected_fire_request=expected_request,
                        expected_fire_request_id=expected_request_id,
                        path=state_path,
                    )
                    break
                except state.FireRequestChanged as exc:
                    # Nothing was consumed or reserved. Re-decide once from
                    # the exact demand observed under the state lock. If it
                    # changes again, leave the newest demand durable for the
                    # next tick instead of spinning or guessing.
                    if request_attempt:
                        return {
                            "action": "skip",
                            "reason": "fire_request_changed",
                        }
                    expected_request = exc.actual
                    expected_request_id = exc.actual_request_id
                    final_input = dataclasses.replace(
                        dec_input,
                        fire_request=expected_request,
                    )
                    final_dec = decision.decide(final_input)
                    if final_dec.action == decision.ACTION_SKIP:
                        return {
                            "action": "skip",
                            "reason": "not_due",
                            "prev_fire": prev_fire.isoformat(),
                        }
                    if final_dec.action == decision.ACTION_COLLECT_DEMAND:
                        # The original request bypassed pregate, but it no
                        # longer exists. Do not run slow subprocess I/O while
                        # holding both admission locks and do not fire an
                        # ungated plain cron. Leave last_fire_at unchanged so
                        # the next tick evaluates the full pregate path.
                        return {
                            "action": "skip",
                            "reason": "fire_request_changed",
                        }
                    if final_dec.action != decision.ACTION_FIRE:
                        LOG.error(
                            "request CAS re-decision returned unexpected "
                            "action=%r reason=%r",
                            final_dec.action,
                            final_dec.reason,
                        )
                        return {
                            "action": "skip",
                            "reason": f"decision_error:{final_dec.action}",
                        }
            if expected_request is not None and not due:
                LOG.info(
                    "fire request consumed (reason=%s) — firing off-cadence",
                    expected_request,
                )
    except deferred_reload.DeferredReloadError as exc:
        LOG.error("deferred reload admission gate unavailable: %s", exc)
        return {
            "action": "skip",
            "reason": "deferred_reload_intent_unreadable",
        }
    job_id = lease.job_id
    if fire_lifecycle is not None:
        state.attach_fire_lifecycle(
            job_id=job_id, lifecycle=fire_lifecycle, path=state_path,
        )
    slot_id = f"slot-{lease.slot_id}"
    job_log_path = _slot_log_path(log_path, slot_id=slot_id, job_id=job_id)
    iso_cfg = workspace_mod.load_isolation_config(schedules_path=schedules_path)
    if (
        Path(schedules_path).resolve() == SCHEDULES_PATH.resolve()
        and Path(repo_root).resolve() != ROOT.resolve()
    ):
        iso_cfg = {**iso_cfg, "mode": "off"}
    preassignment: dict[str, Any] = {"ok": True, "assigned": False}
    task_binding: dict[str, Any] | None = None
    if iso_cfg["mode"] in {"pilot", "enforce"}:
        preassignment = await asyncio.to_thread(
            _preassign_mutating_task,
            repo_root=repo_root,
            slot_id=slot_id,
            job_id=job_id,
        )
        if not preassignment.get("ok"):
            deferred = state.defer_reserved_fire(
                job_id=job_id,
                reason=f"mutating_preassignment_failed:{job_id[:8]}",
                path=state_path,
            )
            return {
                "action": "isolation_deferred",
                "reason": "mutating_preassignment_failed",
                "detail": preassignment,
                "state_deferred": deferred is not None,
            }
        if preassignment.get("assigned"):
            task_binding = dict(preassignment["contract"])
        elif preassignment.get("blocked_contracts"):
            LOG.warning(
                "mutating tasks lack execution contracts; hourly workers cannot "
                "claim them: %s",
                preassignment["blocked_contracts"],
            )
    try:
        workdir = _slot_workdir(
            job_log_path, slot_id=slot_id, job_id=job_id, repo_root=repo_root
        )
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        if task_binding is not None:
            await asyncio.to_thread(
                _settle_mutating_task,
                repo_root=repo_root,
                workspace=task_binding,
                disposition="retry",
                result=f"scratch_workdir_error: {exc}",
            )
        state.defer_reserved_fire(
            job_id=job_id,
            reason=f"scratch_workdir_error:{job_id[:8]}",
            path=state_path,
        )
        LOG.error("cannot create repo-external dispatch cwd job_id=%s: %s", job_id, exc)
        return {"action": "skip", "reason": "scratch_workdir_error", "error": str(exc)}
    # ── WS-B producer-scoped workspace ───────────────────────────────────────
    # `pilot` retains the observation-period fallback. `enforce` (or the
    # launchd-required env fence) has exactly two outcomes: isolated workspace
    # or durable requeue. There is deliberately no shared-main third outcome.
    fire_workspace: dict[str, Any] | None = None
    # Once a mutating task is preassigned there is no observation-only
    # fallback, even if an old config still says pilot. Pilot may observe
    # non-mutating fires; mutating execution is isolated-or-requeued.
    isolation_required = task_binding is not None
    if task_binding is not None and isolation_required and iso_cfg["mode"] == "off":
        iso_cfg = {**iso_cfg, "mode": "enforce"}
    allocation_error = ""
    if task_binding is not None and iso_cfg["mode"] in {"pilot", "enforce"}:
        try:
            # Protect every job the state file still remembers (live, draining,
            # or completed) — the sweep may only close TRUE orphans whose fire
            # left no state behind. See sweep_orphan_workspaces docstring.
            fresh = state.read_state(state_path)
            protected = (
                [str(j.get("job_id")) for j in (fresh.get("current_jobs") or [])]
                + [str(i.get("job_id")) for i in (fresh.get("phase_z_pending") or [])]
                + [str(c.get("job_id")) for c in (fresh.get("completions") or [])]
                + [job_id]
            )
            swept = await asyncio.to_thread(
                workspace_mod.sweep_orphan_workspaces,
                repo_root=repo_root, protected_job_ids=protected,
            )
            if swept:
                LOG.info("workspace orphan sweep closed %d workspace(s): %s",
                         len(swept), [s.get("disposition") for s in swept])
            active_isolated = sum(
                1 for j in current_jobs if j.get("workspace") is not None
            )
            fire_workspace = await asyncio.to_thread(
                workspace_mod.allocate_workspace,
                repo_root=repo_root, slot_id=slot_id, job_id=job_id,
                config=iso_cfg, task_binding=task_binding,
                active_isolated=active_isolated,
            )
        except Exception as exc:  # noqa: BLE001 — enforce converts this to requeue
            allocation_error = str(exc)
            LOG.warning("workspace allocation crashed job_id=%s: %s", job_id, exc)
            fire_workspace = None
        if fire_workspace is not None:
            # Bind the allocator's durable task/workspace identity before the
            # first fallible sandbox-preflight operation. A restart can now
            # adjudicate this exact workspace instead of leaving a zombie
            # queue claim.
            attached = state.attach_workspace(
                job_id=job_id, workspace=fire_workspace, path=state_path,
            )
            if not attached:
                attach_final = await asyncio.to_thread(
                    workspace_mod.finalize_workspace,
                    repo_root=repo_root,
                    workspace=fire_workspace,
                    worker_outcome="reservation_lost",
                    job_id=job_id,
                )
                attach_disposition = _settlement_disposition(attach_final)
                if attach_disposition is not None:
                    lost_settlement = await asyncio.to_thread(
                        _settle_mutating_task,
                        repo_root=repo_root,
                        workspace=task_binding,
                        disposition=attach_disposition,
                        result=(
                            "reservation lost before preflight; "
                            f"workspace={attach_final.get('disposition')}"
                        ),
                    )
                    if lost_settlement.get("ok"):
                        await asyncio.to_thread(
                            workspace_mod.complete_task_settlement,
                            repo_root,
                            task_id=str(task_binding["task_id"]),
                            claim_session_id=str(
                                task_binding["claim_session_id"]
                            ),
                            disposition=attach_disposition,
                            status=str(lost_settlement.get("status") or ""),
                        )
                return {
                    "action": "isolation_deferred",
                    "reason": (
                        "reservation_lost"
                        if attach_disposition is not None
                        else "workspace_finalize_pending"
                    ),
                    "job_id": job_id,
                    "slot_id": slot_id,
                    "workspace": attach_final,
                }
        if fire_workspace is not None and isolation_required:
            try:
                prepared = await asyncio.to_thread(
                    isolation.prepare,
                    canonical_root=repo_root,
                    workspace=Path(str(fire_workspace["path"])),
                    job_id=job_id,
                    profile_root=Path(tempfile.gettempdir())
                    / "volpred-dispatch-isolation",
                )
                fire_workspace.update({
                    f"isolation_{key}": value
                    for key, value in prepared.to_dict().items()
                })
                if not state.attach_workspace(
                    job_id=job_id, workspace=fire_workspace, path=state_path,
                ):
                    raise RuntimeError(
                        "reservation lost while binding sandbox receipt"
                    )
            except Exception as exc:  # noqa: BLE001 — substrate failure requeues
                allocation_error = f"isolation_preflight: {exc}"
                LOG.warning(
                    "writer isolation preflight failed job_id=%s: %s",
                    job_id,
                    exc,
                )
                preflight_final = await asyncio.to_thread(
                    workspace_mod.finalize_workspace,
                    repo_root=repo_root,
                    workspace=fire_workspace,
                    worker_outcome="isolation_preflight_failed",
                    job_id=job_id,
                )
                preflight_disposition = _settlement_disposition(preflight_final)
                settlement: dict[str, Any] = {
                    "ok": False,
                    "reason": "workspace_finalize_pending",
                }
                if preflight_disposition is not None:
                    settlement = await asyncio.to_thread(
                        _settle_mutating_task,
                        repo_root=repo_root,
                        workspace=fire_workspace,
                        disposition=preflight_disposition,
                        result=(
                            f"writer isolation preflight failed: {exc}; "
                            f"workspace={preflight_final.get('disposition')}"
                        ),
                    )
                    if settlement.get("ok"):
                        await asyncio.to_thread(
                            workspace_mod.complete_task_settlement,
                            repo_root,
                            task_id=str(fire_workspace["task_id"]),
                            claim_session_id=str(
                                fire_workspace["claim_session_id"]
                            ),
                            disposition=preflight_disposition,
                            status=str(settlement.get("status") or ""),
                        )
                        state.defer_reserved_fire(
                            job_id=job_id,
                            reason=f"writer_isolation_preflight:{job_id[:8]}",
                            path=state_path,
                        )
                return {
                    "action": "isolation_deferred",
                    "reason": (
                        "isolation_preflight_failed"
                        if preflight_disposition is not None
                        else "workspace_finalize_pending"
                    ),
                    "job_id": job_id,
                    "slot_id": slot_id,
                    "workspace": preflight_final,
                    "task_settlement": settlement,
                }
        if fire_workspace is None and isolation_required:
            durable = workspace_mod.record_allocation_deferred(
                repo_root,
                job_id=job_id,
                slot_id=slot_id,
                reason="workspace_unavailable",
                error=allocation_error,
                task_binding=task_binding,
            )
            deferred = state.defer_reserved_fire(
                job_id=job_id,
                reason=f"writer_isolation_deferred:{job_id[:8]}",
                path=state_path,
            )
            settlement = await asyncio.to_thread(
                _settle_mutating_task,
                repo_root=repo_root,
                workspace=task_binding,
                disposition="retry",
                result=f"writer isolation unavailable: {allocation_error}",
            )
            LOG.warning(
                "writer isolation deferred job_id=%s receipt_durable=%s; "
                "atomic_state_transition=%s",
                job_id,
                durable,
                deferred is not None,
            )
            return {
                "action": "isolation_deferred",
                "reason": "workspace_unavailable",
                "job_id": job_id,
                "slot_id": slot_id,
                "receipt_durable": durable,
                "state_deferred": deferred is not None,
                "task_settlement": settlement,
            }
    execution_workdir = (
        Path(str(fire_workspace["path"]))
        if fire_workspace is not None
        else workdir
    )
    prompt = _slot_prompt(
        prompt,
        slot_id=slot_id,
        job_id=job_id,
        workdir=execution_workdir,
        repo_root=repo_root,
        workspace=fire_workspace,
    )
    LOG.info(
        "firing worker job_id=%s slot=%s prev_scheduled=%s log=%s",
        job_id, slot_id, prev_fire.isoformat(), job_log_path,
    )
    # PHASE-Z safety net (post-fire deterministic commit) — port of the legacy
    # cron_hourly_dispatch.sh PHASE-Z block. Runs ONCE per real fire regardless
    # of worker outcome — success / hang / failure AND the case where the worker
    # call itself raises (Codex review #2): a crashed worker is exactly when the
    # tree is most likely left dirty, so PHASE-Z lives in `finally`. The
    # dispatched agent now leaves a receipt and never runs Git; this owner
    # captures only its attributed paths. Run in a thread (git
    # subprocess) so the event loop stays responsive; a git hiccup is logged,
    # never crashes the tick (run_phase_z is itself no-raise, belt-and-suspenders
    # here too). If the worker raised, PHASE-Z still runs, then the exception
    # propagates to scheduler_loop's crash handler (which alerts).
    coro = _run_reserved_fire(
        job_id=job_id, cohort_id=lease.cohort_id, slot_id=slot_id, prompt=prompt,
        scheduled_for=prev_fire.isoformat(), fire_reason=fire_reason,
        log_path=job_log_path, state_path=state_path, repo_root=repo_root,
        workdir=execution_workdir, fire_workspace=fire_workspace,
    )
    if not background:
        return await coro
    task = asyncio.create_task(coro, name=f"dispatch-{slot_id}-{job_id[:8]}")
    _ACTIVE_FIRE_TASKS[job_id] = task
    task.add_done_callback(lambda done, jid=job_id: _reap_fire_task(jid, done))
    return {
        "action": "launched", "job_id": job_id, "slot_id": slot_id,
        "fire_reason": fire_reason, "active_slots": len(current_jobs) + 1,
        "max_slots": capacity,
    }
