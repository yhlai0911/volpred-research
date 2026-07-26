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
from datetime import datetime
from pathlib import Path
from typing import Any

from croniter import croniter

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
from volpred.ops.timestamps import parse_iso_warn  # noqa: E402

from . import alerts, decision, identity, phase_z, state, worker, workspace as workspace_mod
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
QUOTA_DERATE_STREAK = 2

# Strong references keep launched fire tasks alive until their done callback
# observes the result. Keys are immutable state job_ids, never reusable slots.
_ACTIVE_FIRE_TASKS: dict[str, asyncio.Task] = {}
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
    or invalid values fall back to two; bool is rejected even though it is an
    ``int`` subclass.  A config reduction never kills existing workers — it
    only blocks new admission until occupancy falls below the new limit.

    The configured value is a ceiling, not a promise: while a quota streak is
    active the pool is clamped back to ``DEFAULT_MAX_SLOTS``. Keeping that here
    rather than in the caller preserves the single-owner rule — everyone who
    asks "how many slots exist" gets the same answer, de-rate included.
    """
    try:
        data = json.loads(schedules_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        LOG.warning("load_max_slots fallback=%d: %s", DEFAULT_MAX_SLOTS, exc)
        return DEFAULT_MAX_SLOTS
    for item in data.get("daemons") or []:
        if not isinstance(item, dict) or item.get("id") != daemon_id:
            continue
        value = item.get("max_slots", DEFAULT_MAX_SLOTS)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            LOG.warning("max_slots %r invalid — using %d", value, DEFAULT_MAX_SLOTS)
            return DEFAULT_MAX_SLOTS
        if value > DEFAULT_MAX_SLOTS and quota_derate_active(state_path):
            LOG.warning(
                "max_slots %d de-rated to %d: last %d completions were quota_blocked "
                "(self-clears on the next successful fire)",
                value, DEFAULT_MAX_SLOTS, QUOTA_DERATE_STREAK,
            )
            return DEFAULT_MAX_SLOTS
        return value
    LOG.warning("daemon %s missing max_slots — using %d", daemon_id, DEFAULT_MAX_SLOTS)
    return DEFAULT_MAX_SLOTS


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
    base_prompt = (
        "[Supervisor multi-slot context]\n"
        f"slot_id={slot_id}; job_id={job_id}; worktree_prefix={prefix}.\n"
        f"launcher_cwd={workdir}（刻意不是 Git repo）；canonical_root={repo_root}.\n"
        "本 fire 的 task-pool ownership token 已由 supervisor 放在"
        "$VOLPRED_TASK_CLAIM_OWNER；所有 claim、work_log owner/actor 都必須逐字使用它。"
        "缺少此環境變數即停止且回報 dispatcher identity error，禁止退回日期/小時或自訂名稱。"
        "此段規則優先於後文 PHASE-Z：先從 canonical_root 讀 AGENTS.md 與 handoff。"
        "inline task 可用絕對路徑編輯 canonical_root，但禁止 cd 回 shared checkout 後裸跑"
        "任何 Git mutation；本班 canonical 變更由 cohort-drained PHASE-Z 單一提交。"
        "若 task routing 明定 worktree，才用 canonical git_writer_lock.py run 建立名稱含"
        "worktree_prefix 的 registered linked worktree，並在本班結束前透過正式"
        "merge_worktree.sh 完整整合；不得留下未合併 branch/worktree。"
        "task-pool claim/complete 必須用 canonical_root 的絕對 script path，讓 fcntl control"
        "plane 寫 canonical queue。最後依原 PHASE Z 只留 fire receipt，不自行 git add/commit。\n\n"
        + workspace_section
        + prompt
    )
    return inject_external_report_contract(base_prompt)


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
        if own is not None and own.get("pid") is None and own.get("phase") not in {
            "kill_failed_orphan", "timeout_unverified", "orphan_unverified_not_killed",
        }:
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
            state.record_completion(
                job_id=job_id, expected_attempt=int(own.get("attempt", 1)),
                exit_code=-1, outcome="failure", final_model=str(own.get("model") or "unknown"),
                path=state_path,
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
                worker_outcome = result.outcome if result is not None else "failure"
                workspace_outcome = await asyncio.to_thread(
                    workspace_mod.finalize_workspace,
                    repo_root=repo_root, workspace=fire_workspace,
                    worker_outcome=worker_outcome, job_id=job_id,
                )
                LOG.info("workspace finalize job_id=%s disposition=%s",
                         job_id, (workspace_outcome or {}).get("disposition"))
            except Exception as exc:  # noqa: BLE001
                LOG.exception("workspace finalize crashed job_id=%s: %s", job_id, exc)
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
                    cleared = state.finish_phase_z(cohort_id=cohort_id, path=state_path)
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
) -> dict[str, Any]:
    """One tick. Returns a small dict describing the decision (for tests + audit log)."""
    state.heartbeat(path=state_path)
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
            outcome = await asyncio.to_thread(
                phase_z.run_phase_z, repo_root=repo_root,
                isolated_cohort=recovery_isolated,
                claim_owners=_phase_z_claim_owners(pending_phase_z),
                pre_fire_dirty=durable_baseline,
                fire_ids={
                    str(item["job_id"])
                    for item in pending_phase_z
                    if item.get("job_id")
                },
            )
            if _phase_z_terminal(outcome):
                for cohort in {str(item.get("cohort_id")) for item in pending_phase_z}:
                    state.finish_phase_z(cohort_id=cohort, path=state_path)
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
    peeked_request = (
        str(snap.get("fire_request_reason") or "unspecified")
        if snap.get("fire_requested_at") else None
    )
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
    # Admission gates passed — consume any pending request atomically NOW
    # (one request produces exactly one fire; consumed even when cron was due
    # anyway so it cannot cause a SECOND fire right after this one).
    consumed = state.consume_fire_request(state_path)
    if consumed != dec_input.fire_request:
        # Lost the atomic-consume race, or a request landed after the snapshot:
        # re-decide with the value this tick actually owns.
        dec_input = dataclasses.replace(dec_input, fire_request=consumed)
        dec = decision.decide(dec_input)
        if dec.action == decision.ACTION_SKIP:
            return {"action": "skip", "reason": "not_due", "prev_fire": prev_fire.isoformat()}
    if consumed is not None and not due:
        LOG.info("fire request consumed (reason=%s) — firing off-cadence", consumed)
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
    fire_reason = dec.fire_reason or "cron"
    if dry_run:
        LOG.info("DRY-RUN would fire (prev_scheduled=%s)", prev_fire.isoformat())
        # update last_fire_at so we don't re-log every tick — shadow run still tracks
        with state._locked_state(state_path) as (_fh, data):
            data["last_fire_at"] = state._now()
        return {"action": "dry_run_fire", "prev_fire": prev_fire.isoformat()}
    prompt = _load_prompt(prompt_path)
    if not prompt:
        LOG.error("empty prompt — refusing to fire")
        return {"action": "skip", "reason": "empty_prompt"}
    cohort_id = str(current_jobs[0].get("cohort_id")) if current_jobs else None
    lease = state.reserve_fire(
        schedule_id=SCHEDULE_ID, attempt=1, model=worker.OPUS_MODEL,
        log_path=str(log_path), scheduled_for=prev_fire.isoformat(),
        fire_reason=fire_reason, max_slots=capacity, cohort_id=cohort_id,
        fire_key=(f"cron:{prev_fire.isoformat()}" if fire_reason.startswith("cron") else None),
        path=state_path,
    )
    job_id = lease.job_id
    if fire_lifecycle is not None:
        state.attach_fire_lifecycle(
            job_id=job_id, lifecycle=fire_lifecycle, path=state_path,
        )
    slot_id = f"slot-{lease.slot_id}"
    job_log_path = _slot_log_path(log_path, slot_id=slot_id, job_id=job_id)
    try:
        workdir = _slot_workdir(
            job_log_path, slot_id=slot_id, job_id=job_id, repo_root=repo_root
        )
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        state.release_reservation(job_id=job_id, path=state_path)
        LOG.error("cannot create repo-external dispatch cwd job_id=%s: %s", job_id, exc)
        return {"action": "skip", "reason": "scratch_workdir_error", "error": str(exc)}
    # ── WS-B producer-scoped workspace (pilot) ──────────────────────────────
    # Allocation is strictly fail-open: any refusal (mode off, caps, disk floor,
    # writer-lock busy, git error) fires the slot UNISOLATED and PHASE-Z's
    # baseline fallback keeps covering it. Runs in a thread: `git worktree add`
    # checks out the full tree and must not stall the event loop (health_loop
    # heartbeats share it).
    fire_workspace: dict[str, Any] | None = None
    iso_cfg = workspace_mod.load_isolation_config(schedules_path=schedules_path)
    if iso_cfg["mode"] == "pilot":
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
                config=iso_cfg, active_isolated=active_isolated,
            )
        except Exception as exc:  # noqa: BLE001 — isolation must never veto dispatch
            LOG.warning("workspace allocation crashed (non-fatal, firing unisolated): %s", exc)
            fire_workspace = None
        if fire_workspace is not None:
            state.attach_workspace(
                job_id=job_id, workspace=fire_workspace, path=state_path,
            )
    prompt = _slot_prompt(
        prompt,
        slot_id=slot_id,
        job_id=job_id,
        workdir=workdir,
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
        workdir=workdir, fire_workspace=fire_workspace,
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
