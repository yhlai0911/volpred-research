"""Run all built-in ops alert checkers and dispatch deduped emails.

Hook points:
- Called at the end of `scripts/daily_update.py` so daily run prints alert state.
- Suitable for a host crontab hourly invocation:
    0 * * * * cd /path/to/volpred-research && uv run python scripts/check_alerts.py >> storage/logs/cron/check_alerts.log 2>&1

Behavior:
- Runs the condition registry owned by
  ``volpred.ops.alerts.build_alert_condition_report``. Do not duplicate its
  changing condition count or inventory in this wrapper docstring.
- Dedup window 24h via storage/ops/alert_dedup.json (sha256(level + title)).
- Recipient defaults to alerts.ALERT_RECIPIENT (yihao.lai@gmail.com).

Exit code:
- 0 always (even on breach) — this is observability, not a gating step.
"""
from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

try:
    from croniter import croniter
except ImportError:  # pragma: no cover — surfaces as bad_cron on every job
    croniter = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
# Allow importing sibling script `run_due_jobs.py` (universal scheduler).
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops.diagnostics import warn  # noqa: E402 — needs SRC_DIR on sys.path above


def _warn_check_alerts(message: str, path: Path, exc: Exception) -> None:
    print(
        f"[check_alerts] WARN {message}: "
        f"path={path} error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


def _load_json_dict(path: Path, *, label: str) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _warn_check_alerts(f"{label} JSON read failed; using empty object", path, exc)
        return {}
    if not isinstance(payload, dict):
        _warn_check_alerts(
            f"{label} JSON schema invalid; using empty object",
            path,
            TypeError(f"expected dict, got {type(payload).__name__}"),
        )
        return {}
    return payload


def _record_release_pool_fallback_fire(*, start_iso: str, end_iso: str, returncode: int) -> None:
    """Keep fallback-triggered release runs visible in the canonical observability files.

    The actual release still runs through `volpred ops release-pool-by-settings`;
    this helper only mirrors the fire into the same log/state surfaces that the
    host cron path updates, so operators don't misdiagnose a successful fallback
    run as a skipped cron.
    """
    log_path = PROJECT_ROOT / "storage" / "logs" / "cron" / "release_pool.log"
    guard_canonical_write(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"=== [release_pool] check_alerts fallback fire at {start_iso} ===\n")
        handle.write(f"=== [release_pool] exit {returncode} at {end_iso} (fallback) ===\n")

    state_path = PROJECT_ROOT / "storage" / "ops" / "cron_last_run.json"
    guard_canonical_write(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = _load_json_dict(state_path, label="cron_last_run")
    state["release_pool"] = end_iso
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _auto_trigger_release_pool_if_due() -> dict:
    """2026-04-19 workaround: host cron `3 */2 * * *` fires release_pool unreliably
    on this machine (see docs/error_log.md 2026-04-19 "Host cron selective skip").
    check_alerts cron (`0 * * * *`) fires reliably; piggy-back release-pool trigger
    here so release cadence honors settings.interval_minutes even when the 2-hour
    host cron is silently skipped by launchd.
    """
    from datetime import datetime, timezone
    import subprocess

    settings_path = PROJECT_ROOT / "storage" / ".release_settings.json"
    if not settings_path.exists():
        return {"triggered": False, "reason": "no_settings_file"}
    try:
        settings = json.loads(settings_path.read_text())
    except Exception as exc:
        return {"triggered": False, "reason": f"settings_read_error:{exc}"}

    interval_min = int(settings.get("interval_minutes") or 120)
    last_iso = settings.get("last_released_at")
    if not last_iso:
        return {"triggered": False, "reason": "no_last_released_at"}
    try:
        last_dt = datetime.fromisoformat(str(last_iso).replace("Z", "+00:00"))
    except Exception:
        return {"triggered": False, "reason": "last_released_at_parse_error"}
    now = datetime.now(timezone.utc)
    age_min = (now - last_dt).total_seconds() / 60
    # Tolerance: check_alerts cron fires hourly at :00:00 but release-pool CLI
    # writes last_released_at at :00:01-02 UTC. On exactly-interval boundaries
    # (age=119.98 min at hour-aligned check) this skips by ~2s and adds a full
    # extra hour, making 120-min interval behave as 180-min. Allow 5-min slack
    # (2026-04-19 22:27 UTC bump: 3→5 min after 22:00 UTC edge case where
    # manual run 20:03:01 off-alignment gave age=116.985 < 117 boundary)
    # so hourly checks at the interval boundary fire the release instead of
    # deferring to the next hourly check.
    if age_min < interval_min - 5:
        # 2026-05-04 finding #18 修整：drift defensive log。
        # 2026-04-19 incident: piggy-back 1.5s drift 致 age=119.985 < interval-3
        # → not-due → 整輪 hour 跳過 → 實際 interval 變 180min（流量損失 33%）。
        # tolerance 從 3→5 已修，但若 drift 累積至接近 tolerance edge
        # （interval-7 ≤ age < interval-5）log warning，operator 可監控 drift
        # 是否單調增長（symptom of cron schedule 與 interval 漂移）。
        if age_min >= interval_min - 7:
            print(
                f"  [release_pool drift-watch] near-tolerance: "
                f"expected_interval={interval_min}min actual_age={age_min:.1f}min "
                f"gap_to_tolerance={interval_min - 5 - age_min:.1f}min — "
                f"check if drift accumulates across hourly fires"
            )
        return {"triggered": False, "reason": f"interval_not_due_age={age_min:.0f}min"}

    # Due: attempt release via CLI. Use non-blocking subprocess to avoid
    # any hang in hourly cron; limit runtime; don't fail alert run if this fails.
    try:
        start = datetime.now(timezone.utc)
        result = subprocess.run(
            ["/opt/homebrew/bin/uv", "run", "volpred", "ops", "release-pool-by-settings"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        end = datetime.now(timezone.utc)
        ok = result.returncode == 0
        if ok:
            _record_release_pool_fallback_fire(
                start_iso=start.isoformat(timespec="seconds"),
                end_iso=end.isoformat(timespec="seconds"),
                returncode=result.returncode,
            )
        return {
            "triggered": True,
            "ok": ok,
            "returncode": result.returncode,
            "age_min": round(age_min),
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
            "stdout_tail": (result.stdout or "")[-200:],
            "stderr_tail": (result.stderr or "")[-200:],
        }
    except Exception as exc:
        return {"triggered": True, "ok": False, "error": str(exc)}


def _auto_remediate_publish_drought() -> dict:
    """2026-07-03 boss email-12559: the 發文脫班 (publishing_freshness) dead-man
    switch must DIRECTLY REMEDIATE, not email the boss a to-do list.

    Delegates to the single-owner ladder `scripts/remediate_publish_drought.py`
    (force-release drought circuit-breaker → refill fresh topics for next hourly
    dispatch). Runs as a bounded subprocess so any Supabase/Mirror sync hang in
    the release path can't stall the hourly alert fire. Non-fatal: failures are
    captured and logged, never raised.
    """
    from datetime import datetime, timezone
    import subprocess

    script = PROJECT_ROOT / "scripts" / "remediate_publish_drought.py"
    try:
        start = datetime.now(timezone.utc)
        proc = subprocess.run(
            ["/opt/homebrew/bin/uv", "run", "python", str(script), "--apply", "--json"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=240,
        )
        # The ladder prints a single clean JSON line on stdout (--json). Parse
        # the last JSON object; ignore any stray warn lines on stderr.
        summary: dict = {}
        for line in reversed((proc.stdout or "").splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    summary = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue  # silent-ok: scanning stdout in reverse for last valid JSON line; non-JSON candidates expected
        summary["returncode"] = proc.returncode
        summary["ran_at"] = start.isoformat()
        if not summary.get("attempted"):
            return summary or {"attempted": False, "reason": "no_json_output",
                               "stderr_tail": (proc.stderr or "")[-200:]}
        return summary
    except Exception as exc:  # noqa: BLE001
        return {"attempted": False, "error": str(exc)}


def _write_json_atomic(path: Path, payload: dict) -> None:
    """Serialize fully, then replace. A half-written receipt would make the alert
    body lie about what the system did (per control-plane rule: never leave partial
    JSON behind a truncate)."""
    guard_canonical_write(path)
    blob = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(blob, encoding="utf-8")
    tmp.replace(path)


def _auto_remediate_release_deadlock() -> dict:
    """2026-07-13 boss msg 660: 「不是補救，是立刻從底層徹底處理。」

    Deadlock = a release is due, the pool has drafts, and every one of them is
    blocked by a gate. The pool is not empty, so refilling it *by count* — which is
    all `refill_reader_facing_pool` ever knew how to do — would add more drafts that
    are just as blocked. What is scarce is not drafts; it is drafts in a cluster the
    gate will still let through.

    So the remediation is to refill with a *shape* constraint: `required_clusters` =
    the clusters that are not currently blocked. That is the one fact the deadlock
    detector has and a count-based refiller does not.

    Writes a receipt to storage/ops/release_deadlock_remediation.json, which
    `volpred.ops.alerts` reads to tell the boss what was already done (rather than
    handing him a to-do list — per `.claude/rules/alert.md`).
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    receipt_path = PROJECT_ROOT / "storage" / "ops" / "release_deadlock_remediation.json"
    receipt: dict = {"attempted": False, "ran_at": now.isoformat()}
    try:
        from volpred.ops.content import preview_release_pool_by_settings

        preview = preview_release_pool_by_settings(storage_dir="storage")
        counts = preview.get("pool_counts") or {}
        pressure = preview.get("narrative_cluster_pressure") or {}
        draft = counts.get("draft")
        eligible = counts.get("eligible")
        deadlocked = (
            preview.get("due_now") is True
            and isinstance(draft, int)
            and draft > 0
            and isinstance(eligible, int)
            and eligible == 0
        )
        if not deadlocked:
            receipt.update({"reason": "not_deadlocked", "draft": draft, "eligible": eligible})
            _write_json_atomic(receipt_path, receipt)
            return receipt

        blocked = [str(c) for c in (pressure.get("blocked_clusters") or [])]
        known = [str(c) for c in (pressure.get("clusters") or [])]
        # Clusters the gate would still pass. If every known cluster is blocked we
        # cannot name a safe one — say so rather than guessing, and let the writer
        # pick any cluster outside the blocked set.
        required = [c for c in known if c not in blocked]

        task_id = f"release_deadlock_refill_{now.strftime('%Y%m%d_%H')}"
        task = {
            "id": task_id,
            "title": "【P1 自動補救】release 死鎖：補可放行 cluster 的草稿",
            "description": (
                "release_pool 偵測到死鎖：草稿池有 "
                f"{draft} 篇但 eligible=0（due_now=true）。\n\n"
                f"目前被 narrative_cluster gate 擋住的 cluster：{', '.join(blocked) or '(none)'}\n"
                f"**只准補這些 cluster 的草稿**：{', '.join(required) or '(blocked 集合以外的任一 cluster)'}\n\n"
                "重點：池子不缺草稿，缺的是**還能通過 gate 的 cluster** 的草稿。"
                "補同 cluster 的稿子只會再被擋一次。\n"
                "選題走 publication-candidates skill；寫作前必跑 check_arc_dedup.py（帶 --audience）。"
            ),
            "task_type": "daily_article",
            "priority": 1,
            "status": "pending",
            "source": "auto_remediation",
            "created_at": now.isoformat(),
            "required_clusters": required,
            "blocked_clusters": blocked,
            "trigger": "release_pool_deadlock",
        }
        created = _append_next_task_locked(task, PROJECT_ROOT / "storage" / "next_tasks.json")
        receipt.update(
            {
                "attempted": True,
                "draft": draft,
                "eligible": eligible,
                "blocked_clusters": blocked,
                "required_clusters": required,
                ("task_id" if created else "existing_task_id"): task_id,
            }
        )
    except Exception as exc:  # noqa: BLE001 — fail-open, but never silently
        warn(
            "release_deadlock_remediation",
            "auto-remediation failed",
            err=f"{type(exc).__name__}: {exc}",
        )
        receipt.update({"attempted": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
    _write_json_atomic(receipt_path, receipt)
    return receipt


def _auto_reap_orphan_deliverables() -> dict:
    """2026-07-13 boss msg 624: a finished article must never end up discarded.

    Same shape as `_auto_remediate_publish_drought` above, and for the same reason:
    a producer outside the fire lane (a codex-vscode session, an async render job)
    can write a complete draft and exit without registering it. Nothing then owns
    it — feed has never heard of it, release cron cannot schedule it, and its only
    trace is a line in `git status`. PHASE-Z rightly declines to blind-commit
    foreign paths, so the file sat there until an alert asked the boss to choose
    between committing it and throwing it away. Deep articles were dying in that
    second column.

    The reaper routes such drafts through the canonical intake instead, so the fix
    is a delivery fix, not a git fix. Bounded subprocess (publish does network I/O);
    non-fatal — a failure here must never stop the alert fire.
    """
    from datetime import datetime, timezone
    import subprocess

    script = PROJECT_ROOT / "scripts" / "reap_orphan_deliverables.py"
    try:
        start = datetime.now(timezone.utc)
        proc = subprocess.run(
            ["/opt/homebrew/bin/uv", "run", "python", str(script), "--apply", "--json"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=600,
        )
        summary: dict = {}
        for line in reversed((proc.stdout or "").splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    summary = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue  # silent-ok: scanning stdout in reverse for last valid JSON line
        summary["returncode"] = proc.returncode
        summary["ran_at"] = start.isoformat()
        return summary or {"attempted": False, "reason": "no_json_output",
                           "stderr_tail": (proc.stderr or "")[-200:]}
    except Exception as exc:  # noqa: BLE001
        return {"attempted": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# CI red watchdog (2026-07-13, boss msgs 632/633/635/647/653): the boss saw a
# red Test Suite before the system did — GitHub Actions failure notifications
# only reach the boss's inbox, nothing on this machine subscribed to CI state,
# so main stayed red for 12+ hours with the ops loop blind to it. Since boss
# msg 738 (2026-07-14), this owner is fix-first: reduce recent run history into
# one cross-tick incident, queue + request-fire the repair, push and wait for
# GitHub verification, and notify only on verified recovery or exhausted/failed
# remediation. Enforcement owner for "CI is red" = this check (anti-stacking).
# ---------------------------------------------------------------------------
CI_WATCH_STATE = PROJECT_ROOT / "storage" / "ops" / "ci_watch_state.json"
CI_NEXT_TASKS = PROJECT_ROOT / "storage" / "next_tasks.json"
CI_WORKFLOW = "Test Suite"
CI_RUN_HISTORY_LIMIT = 20
CI_ATTEMPT_FETCH_LIMIT = 40
CI_FAILURE_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})
CI_ACTIVE_TASK_STATUSES = frozenset({"pending", "claimed", "in_progress"})
CI_FAILED_TASK_STATUSES = frozenset(
    {"failed", "blocked", "blocked_on_user", "cancelled", "expired", "superseded", "closed_no_action"}
)
CI_MAX_SILENT_FAILURE_CYCLES = 2


def _gh_bin() -> str | None:
    import shutil

    found = shutil.which("gh")
    if found:
        return found
    brew_gh = Path("/opt/homebrew/bin/gh")  # cron env PATH omits homebrew
    return str(brew_gh) if brew_gh.exists() else None


def _ci_attempt_request_window(
    requests: list[tuple[int, int]],
    *,
    limit: int = CI_ATTEMPT_FETCH_LIMIT,
    cycle: int | None = None,
) -> list[tuple[int, int]]:
    """Rotate a bounded API window so a large attempt history eventually converges."""
    if len(requests) <= limit:
        return requests
    import math
    import time

    chunks = math.ceil(len(requests) / limit)
    cycle = int(time.time() // 3600) if cycle is None else cycle
    start = (cycle % chunks) * limit
    return requests[start : start + limit]


def _ci_historical_attempts(gh: str, runs: list[dict]) -> list[dict]:
    """Fetch attempts hidden by ``gh run list``.

    GitHub's run-list endpoint returns only the latest attempt for each run id.
    Without expanding attempt 1..N-1, three rerun failures between hourly polls
    collapse into one row and can never satisfy the promised escalation gate.
    Bound and parallelize the extra reads so this owner still fits its host cap.
    """
    import concurrent.futures
    import subprocess

    fields = (
        "databaseId,attempt,status,conclusion,url,headSha,displayTitle,"
        "createdAt,startedAt,updatedAt"
    )
    requests: list[tuple[int, int]] = []
    required_by_run: dict[int, set[int]] = {}
    for run in runs:
        run_id = int(run.get("databaseId") or 0)
        latest_attempt = int(run.get("attempt") or 1)
        if run_id:
            required = set(range(1, latest_attempt))
            required_by_run[run_id] = required
            requests.extend((run_id, attempt) for attempt in sorted(required))
    if len(requests) > CI_ATTEMPT_FETCH_LIMIT:
        warn(
            "ci_watch",
            "historical attempt expansion truncated",
            requested=len(requests),
            limit=CI_ATTEMPT_FETCH_LIMIT,
        )
        # Rotate the bounded slice each hour. The incident's processed-key ledger
        # accumulates successful slices, so even pathological >40-attempt runs do
        # not remain permanently incomplete.
        requests = _ci_attempt_request_window(requests)

    def fetch(item: tuple[int, int]) -> dict | None:
        run_id, attempt = item
        try:
            proc = subprocess.run(
                [
                    gh,
                    "run",
                    "view",
                    str(run_id),
                    "--attempt",
                    str(attempt),
                    "--json",
                    fields,
                ],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(PROJECT_ROOT),
            )
        except Exception as exc:  # noqa: BLE001
            warn(
                "ci_watch",
                "historical attempt fetch error",
                run_id=run_id,
                attempt=attempt,
                err=str(exc),
            )
            return None
        if proc.returncode != 0:
            warn(
                "ci_watch",
                "historical attempt fetch failed",
                run_id=run_id,
                attempt=attempt,
                rc=proc.returncode,
            )
            return None
        try:
            payload = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError as exc:
            warn(
                "ci_watch",
                "historical attempt JSON invalid",
                run_id=run_id,
                attempt=attempt,
                err=str(exc),
            )
            return None
        return payload if isinstance(payload, dict) else None

    fetched: list[dict] = []
    if requests:
        workers = min(8, len(requests))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            fetched = [attempt for attempt in pool.map(fetch, requests) if attempt is not None]
    fetched_keys = {
        (int(item.get("databaseId") or 0), int(item.get("attempt") or 1))
        for item in fetched
    }
    for run in runs:
        run_id = int(run.get("databaseId") or 0)
        required = required_by_run.get(run_id, set())
        run["attemptHistoryComplete"] = all((run_id, attempt) in fetched_keys for attempt in required)
    for item in fetched:
        run_id = int(item.get("databaseId") or 0)
        attempt = int(item.get("attempt") or 1)
        item["attemptHistoryComplete"] = all(
            (run_id, prior) in fetched_keys for prior in range(1, attempt)
        )
    return fetched


def _ci_recent_runs(*, limit: int = CI_RUN_HISTORY_LIMIT) -> list[dict]:
    """Recent main Test Suite runs, including queued/in-progress runs.

    The old watchdog fetched only the latest completed run. Three CI attempts can
    finish between hourly polls, so latest-only observation made the promised
    ``>2 cycles`` timeout mathematically impossible to count. Keep enough history
    to reduce every unseen attempt in chronological order.
    """
    import subprocess

    gh = _gh_bin()
    if gh is None:
        warn("ci_watch", "gh CLI not found; CI watchdog skipped")
        return []
    try:
        proc = subprocess.run(
            [gh, "run", "list", "--workflow", CI_WORKFLOW, "--branch", "main",
             "--limit", str(limit),
             "--json", (
                 "databaseId,attempt,status,conclusion,url,headSha,displayTitle,"
                 "createdAt,startedAt,updatedAt"
             )],
            capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT),
        )
        if proc.returncode != 0:
            warn("ci_watch", "gh run list failed",
                 rc=proc.returncode, stderr_tail=(proc.stderr or "")[-200:])
            return []
        runs = json.loads(proc.stdout or "[]")
        latest = [run for run in runs if isinstance(run, dict)] if isinstance(runs, list) else []
        expanded = latest + _ci_historical_attempts(gh, latest)
        return list({_ci_run_key(run): run for run in expanded}.values())
    except Exception as exc:  # noqa: BLE001
        warn("ci_watch", "gh run list error", err=str(exc))
        return []


def _ci_latest_completed_run() -> dict | None:
    """Compatibility helper for callers that only need the latest completed run."""
    return next(
        (run for run in _ci_recent_runs() if str(run.get("status") or "completed") == "completed"),
        None,
    )


def _append_next_task_locked(task: dict, next_tasks_path: Path) -> bool:
    """flock-append one task to the pending queue (same discipline as refill scripts)."""
    import fcntl

    from volpred.ops.next_tasks import normalize_task_priority, write_tasks_to_handle

    guard_canonical_write(next_tasks_path)
    normalize_task_priority(task)
    next_tasks_path.parent.mkdir(parents=True, exist_ok=True)
    if not next_tasks_path.exists():
        next_tasks_path.write_text("[]\n", encoding="utf-8")
    with next_tasks_path.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            data = json.load(fh)
            if not isinstance(data, list):
                raise ValueError("next_tasks.json is not a list")
            if any(isinstance(t, dict) and t.get("id") == task["id"] for t in data):
                return False
            data.append(task)
            write_tasks_to_handle(fh, data)
            return True
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _ci_run_key(run: dict) -> str:
    return f"{run.get('databaseId')}:{int(run.get('attempt') or 1)}"


def _ci_task_id(run: dict) -> str:
    run_id = run.get("databaseId")
    attempt = int(run.get("attempt") or 1)
    return f"ci-red-{run_id}" if attempt == 1 else f"ci-red-{run_id}-a{attempt}"


def _build_ci_repair_task(
    run: dict,
    *,
    now_iso: str,
    failure_cause: str | None = None,
    incident_id: str | None = None,
) -> dict:
    run_id = run.get("databaseId")
    attempt = int(run.get("attempt") or 1)
    url = run.get("url") or f"https://github.com/yhlai0911/volpred-research/actions/runs/{run_id}"
    sha = (run.get("headSha") or "")[:9]
    task_id = _ci_task_id(run)
    incident_id = incident_id or task_id
    cause = failure_cause or "failed log 未提供可解析的一行根因；以 run URL 為準"
    return {
        "id": task_id,
        "task_type": "platform_ops",
        "priority": 1,
        "source": "auto_discovered",
        "status": "pending",
        "dispatch_lane": "agent",
        # ``request_fire`` wakes the generic dispatcher rather than targeting a
        # task id. This schema flag lets a fresh CI P1 pierce starvation lockout.
        "dispatch_preempt": True,
        "ci_incident_id": incident_id,
        "ci_run_key": _ci_run_key(run),
        "created_at": now_iso,
        "title": f"CI 紅燈修復（run {run_id}, attempt {attempt}）— main Test Suite",
        "description": (
            f"GitHub Actions Test Suite 於 main 完成 failure-like 班次。\n"
            f"Run: {url}\nattempt: {attempt}\nhead_sha: {sha}\n"
            f"偵測摘要（仍須讀完整 failed log）：{cause}\n\n"
            "行動（當班修到綠，不許只報告）：\n"
            f"1. `gh run view {run_id} --attempt {attempt} --log-failed | tail -300` 讀失敗測試與根因\n"
            "2. 本地重現 → 修根因；同類站點做 class sweep"
            "（per feedback_declare_complete_requires_class_sweep），禁 surface patch\n"
            "3. 卡住即改派 `codex exec`（gpt-5.6-sol ultra）做獨立診斷/第二實作，"
            "不等下一班（老闆指示：強模型直接嘗試）\n"
            "4. commit + push；result 必須帶機器可讀的 `root_cause=<一行>; "
            "repair_commit=<sha>`\n"
            "5. fixer 不得自行寄 email/Telegram；CI watcher 是唯一通知 owner，會等 GitHub 綠燈後收口\n"
            "成功標準：修復已 push；最終 GitHub success 由 CI watcher 獨立驗證。"
        ),
    }


def _ci_local_ahead(run: dict) -> dict:
    """Does this machine hold commits GitHub has never seen?

    While main is red, the repair commit lives locally until something pushes it.
    Nothing did: `push_backlog` only fires at 3h, the push-backup cron runs hourly
    on its own clock, and the red run itself is `already_handled` after the first
    tick. 2026-07-13 (boss msg 677) that gap ran 75 minutes with CI re-testing
    stale code and the boss collecting failure mail the whole time.
    """
    import subprocess

    def _git(*args: str) -> str | None:
        try:
            proc = subprocess.run(["git", *args], capture_output=True, text=True,
                                  timeout=30, cwd=str(PROJECT_ROOT))
        except Exception as exc:  # noqa: BLE001
            warn("ci_watch", "git probe error", args=" ".join(args), err=str(exc))
            return None
        if proc.returncode != 0:
            warn("ci_watch", "git probe failed", args=" ".join(args),
                 rc=proc.returncode, stderr_tail=(proc.stderr or "")[-160:])
            return None
        return proc.stdout.strip()

    ahead_raw = _git("rev-list", "--count", "origin/main..main")
    head_sha = _git("rev-parse", "main")
    if ahead_raw is None or head_sha is None:
        return {"probe_ok": False, "ahead": 0}
    try:
        ahead = int(ahead_raw)
    except ValueError:
        warn("ci_watch", "git rev-list count not an int", raw=ahead_raw[:40])
        return {"probe_ok": False, "ahead": 0}
    run_sha = run.get("headSha") or ""
    return {
        "probe_ok": True,
        "ahead": ahead,
        "head_sha": head_sha,
        "run_sha": run_sha,
        # CI already tested this exact tree → pushing changes nothing; the red is real.
        "ci_saw_head": bool(run_sha) and run_sha == head_sha,
    }


def _ci_push_local_commits() -> dict:
    """Push via the existing backup script and verify its postcondition.

    The wrapper intentionally exits 0 when a real push failure is transiently
    suppressed. A zero exit code therefore means "wrapper handled the event",
    not "origin contains HEAD". CI remediation may only call it a push after
    ``origin/main..main`` is empty.
    """
    import os
    import subprocess

    from volpred.ops.alerts import _PUSH_HELD_EXIT_CODE  # single source for exit 120

    script = PROJECT_ROOT / "scripts" / "cron_git_push_backup.sh"
    env = dict(os.environ)
    # The CI incident state machine is the sole notification owner. The child
    # wrapper may still log divergence/hold/failure, but must not fan out an
    # intermediate email + Telegram alert of its own.
    env["VOLPRED_SUPPRESS_PUSH_ALERTS"] = "1"
    try:
        proc = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                              timeout=120, cwd=str(PROJECT_ROOT), env=env)
    except Exception as exc:  # noqa: BLE001
        warn("ci_watch", "push script error", err=str(exc))
        return {"pushed": False, "rc": None, "outcome": "error", "err": str(exc)}
    rc = proc.returncode
    if rc == 0:
        try:
            verify = subprocess.run(
                ["git", "rev-list", "--count", "origin/main..main"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(PROJECT_ROOT),
            )
            ahead_after = int((verify.stdout or "").strip()) if verify.returncode == 0 else None
        except Exception as exc:  # noqa: BLE001
            warn("ci_watch", "push postcondition probe failed", err=str(exc))
            ahead_after = None
        if ahead_after == 0:
            return {"pushed": True, "rc": 0, "outcome": "pushed", "ahead_after": 0}
        warn(
            "ci_watch",
            "push wrapper returned 0 but origin still lacks local commits",
            ahead_after=ahead_after,
        )
        return {
            "pushed": False,
            "rc": 0,
            "outcome": "push_unverified",
            "ahead_after": ahead_after,
        }
    if rc == _PUSH_HELD_EXIT_CODE:
        # Guard held on purpose (new silent fallback at HEAD). Never bypass it —
        # surface the hold so the class fix, not the push, is the next action.
        warn("ci_watch", "push HELD by pre-push gate while CI is red",
             rc=rc, hint="scripts/audit_silent_fallbacks.py --strict")
        return {"pushed": False, "rc": rc, "outcome": "held"}
    warn("ci_watch", "push failed while CI is red", rc=rc,
         stderr_tail=(proc.stderr or "")[-200:])
    return {"pushed": False, "rc": rc, "outcome": "failed"}


def _remediate_unpushed_fix(
    run: dict,
    *,
    ahead_probe=None,
    pusher=None,
    before_push=None,
) -> dict:
    """Red CI + local commits GitHub hasn't seen → push them now."""
    probe = (ahead_probe or _ci_local_ahead)(run)
    if not probe.get("probe_ok"):
        return {"attempted": False, "reason": "git_probe_failed"}
    if probe.get("ahead", 0) <= 0:
        return {"attempted": False, "reason": "nothing_unpushed"}
    if probe.get("ci_saw_head"):
        return {"attempted": False, "reason": "ci_already_tested_head",
                "ahead": probe["ahead"]}
    if before_push is not None:
        before_push(probe)
    result = (pusher or _ci_push_local_commits)()
    return {"attempted": True, "ahead": probe["ahead"],
            "head_sha": probe.get("head_sha") or "", **result}


def _ci_run_record(run: dict) -> dict:
    return {
        "key": _ci_run_key(run),
        "run_id": run.get("databaseId"),
        "attempt": int(run.get("attempt") or 1),
        "status": str(run.get("status") or "completed").lower(),
        "conclusion": str(run.get("conclusion") or "").lower(),
        "url": run.get("url"),
        "head_sha": run.get("headSha") or "",
        "created_at": run.get("createdAt"),
        "started_at": run.get("startedAt") or run.get("createdAt"),
        "updated_at": run.get("updatedAt"),
        "attempt_history_complete": bool(
            run.get("attemptHistoryComplete", int(run.get("attempt") or 1) <= 1)
        ),
    }


def _ci_record_as_run(record: dict) -> dict:
    return {
        "databaseId": record.get("run_id"),
        "attempt": record.get("attempt"),
        "status": record.get("status"),
        "conclusion": record.get("conclusion"),
        "url": record.get("url"),
        "headSha": record.get("head_sha"),
        "createdAt": record.get("created_at"),
        "startedAt": record.get("started_at"),
        "updatedAt": record.get("updated_at"),
        "attemptHistoryComplete": record.get("attempt_history_complete"),
    }


def _ci_run_sort_key(run: dict) -> tuple[str, int, int]:
    record = _ci_run_record(run)
    return (
        str(record.get("started_at") or record.get("created_at") or ""),
        int(record.get("run_id") or 0),
        int(record.get("attempt") or 1),
    )


def _ci_record_sort_key(record: dict) -> tuple[str, int, int]:
    return (
        str(record.get("started_at") or record.get("created_at") or ""),
        int(record.get("run_id") or 0),
        int(record.get("attempt") or 1),
    )


def _ci_record_failure(incident: dict, run: dict) -> bool:
    """Record one failure without regressing latest-failure chronology."""
    run_key = _ci_run_key(run)
    failure_keys = incident.setdefault("failure_run_keys", [])
    if run_key in failure_keys:
        return False
    failure_keys.append(run_key)
    record = _ci_run_record(run)
    latest = incident.get("latest_failure") or {}
    if not latest or _ci_record_sort_key(record) >= _ci_record_sort_key(latest):
        incident["latest_failure"] = record
    failure_heads = incident.setdefault("failure_heads", [])
    if record.get("head_sha") and record["head_sha"] not in failure_heads:
        failure_heads.append(record["head_sha"])
    incident["failure_cycles"] = len(failure_keys)
    return True


def _ci_attempt_history_complete(state: dict, run_or_record: dict) -> bool:
    attempt = int(run_or_record.get("attempt") or 1)
    if attempt <= 1:
        return True
    explicit = run_or_record.get(
        "attemptHistoryComplete",
        run_or_record.get("attempt_history_complete"),
    )
    if explicit is True:
        return True
    run_id = int(run_or_record.get("databaseId") or run_or_record.get("run_id") or 0)
    processed = set(state.get("processed_run_keys") or [])
    return bool(run_id) and all(
        f"{run_id}:{prior}" in processed for prior in range(1, attempt)
    )


def _ci_runs_to_process(runs: list[dict], state: dict) -> list[dict]:
    """Return unseen completed attempts in order, or repeat latest for retries.

    Repeating the latest completed failure is intentional: a repair commit can
    appear locally after the first sighting, and notification delivery can fail.
    Neither retry may increment the CI-cycle count.
    """
    deduped = {_ci_run_key(run): run for run in runs}
    completed = sorted(
        (
            run
            for run in deduped.values()
            if str(run.get("status") or "completed").lower() == "completed"
        ),
        key=_ci_run_sort_key,
    )
    if not completed:
        return []

    last = state.get("last_processed_run") or {}
    last_key = last.get("key")
    if not last_key and state.get("last_seen_run_id") is not None:
        # v1 migration: attempt did not exist, so match the legacy run id.
        legacy_id = str(state.get("last_seen_run_id"))
        match = next(
            (run for run in completed if str(run.get("databaseId")) == legacy_id),
            None,
        )
        if match:
            last = _ci_run_record(match)
            state["last_processed_run"] = last
            last_key = last["key"]

    # Attempt expansion is a separate API fan-out and can partially fail. Keep a
    # bounded processed-key ledger so an older attempt that appears on the next
    # poll is still reduced even though the chronological cursor already reached
    # attempt N. ``processing_floor_started_at`` prevents this from replaying old
    # incidents when the watchdog first boots or migrates from v1/v2 state.
    processed_keys = set(state.get("processed_run_keys") or [])
    if processed_keys:
        floor = str(
            state.get("processing_floor_started_at")
            or last.get("started_at")
            or last.get("created_at")
            or ""
        )
        unseen = [
            run
            for run in completed
            if _ci_run_key(run) not in processed_keys
            and (not floor or _ci_run_sort_key(run)[0] >= floor)
        ]
        return unseen or [completed[-1]]

    keys = [_ci_run_key(run) for run in completed]
    if last_key in keys:
        unseen = completed[keys.index(last_key) + 1 :]
        return unseen or [completed[-1]]

    last_started = str(last.get("started_at") or last.get("created_at") or "")
    if last_started:
        unseen = [run for run in completed if _ci_run_sort_key(run)[0] > last_started]
        return unseen or [completed[-1]]

    # First boot (or an old state whose cursor fell outside the 20-run window):
    # start from the latest completed state, never replay historical incidents.
    return [completed[-1]]


@contextmanager
def _ci_state_lock(state_path: Path):
    """Serialize the incident read/transition/write across duplicate host fires."""
    import fcntl

    lock_path = state_path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


def _write_ci_state_if_changed(path: Path, state: dict, original: dict) -> None:
    """Avoid hourly tracked-file churn when no semantic CI state changed."""
    if state != original:
        _write_json_atomic(path, state)


def _ci_pick_failure_cause(log_text: str) -> str:
    """Extract one high-signal, boss-readable line from ``gh --log-failed``."""
    import re

    ansi = re.compile(r"\x1b\[[0-9;]*m")
    candidates: list[tuple[int, str]] = []
    for raw in log_text.splitlines():
        line = ansi.sub("", raw).split("\t")[-1].strip()
        if not line or "Process completed with exit code" in line:
            continue
        score = 0
        if line.startswith("E   ") or "AssertionError" in line:
            score = 4
        elif any(token in line for token in ("ImportError", "ModuleNotFoundError", "ValueError")):
            score = 3
        elif line.startswith(("FAILED ", "ERROR ")) or "##[error]" in line:
            score = 2
        elif "Error:" in line:
            score = 1
        if score:
            candidates.append((score, " ".join(line.split())))
    if not candidates:
        return "failed log 未提供可解析的一行根因；請見 GitHub run"
    best = max(candidates, key=lambda item: item[0])[1]
    return best[:280]


def _ci_failure_summary(run: dict) -> str:
    import subprocess

    gh = _gh_bin()
    run_id = run.get("databaseId")
    if gh is None:
        return "failed log 無法取得：gh CLI 不可用"
    try:
        proc = subprocess.run(
            [
                gh,
                "run",
                "view",
                str(run_id),
                "--attempt",
                str(int(run.get("attempt") or 1)),
                "--log-failed",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(PROJECT_ROOT),
        )
    except Exception as exc:  # noqa: BLE001
        warn("ci_watch", "failed log fetch error", run_id=run_id, err=str(exc))
        return f"failed log 無法取得：{type(exc).__name__}"
    if proc.returncode != 0:
        warn(
            "ci_watch",
            "gh run view --log-failed failed",
            run_id=run_id,
            rc=proc.returncode,
            stderr_tail=(proc.stderr or "")[-160:],
        )
        return f"failed log 無法取得：gh rc={proc.returncode}"
    return _ci_pick_failure_cause(proc.stdout or "")


def _ci_task_records(task_ids: list[str], next_tasks_path: Path) -> dict[str, dict]:
    import fcntl

    wanted = set(task_ids)
    if not wanted or not next_tasks_path.exists():
        return {}
    try:
        with next_tasks_path.open("r", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
            try:
                tasks = json.load(fh)
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception as exc:  # noqa: BLE001
        warn("ci_watch", "repair task snapshot failed", err=str(exc))
        return {}
    return {
        str(task.get("id")): task
        for task in tasks
        if isinstance(task, dict) and str(task.get("id")) in wanted
    }


def _ci_close_pending_repair_tasks(
    task_ids: list[str],
    next_tasks_path: Path,
    *,
    now_iso: str,
    green_run: dict,
) -> list[str]:
    """Atomically retire incident-owned tasks that never started.

    Claimed/in-progress work belongs to another worker and is never rewritten.
    Only still-pending rows become canonical ``closed_no_action`` after a verified
    green run, preventing a queued fire from claiming stale repair work.
    """
    import fcntl

    from volpred.ops.next_tasks import write_tasks_to_handle

    wanted = set(task_ids)
    if not wanted or not next_tasks_path.exists():
        return []
    guard_canonical_write(next_tasks_path)
    retired: list[str] = []
    changed = False
    with next_tasks_path.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            tasks = json.load(fh)
            if not isinstance(tasks, list):
                raise ValueError("next_tasks.json is not a list")
            for task in tasks:
                if not isinstance(task, dict) or str(task.get("id")) not in wanted:
                    continue
                if (
                    str(task.get("status") or "").lower() == "closed_no_action"
                    and task.get("ci_closed_after_green")
                ):
                    retired.append(str(task.get("id")))
                    continue
                if str(task.get("status") or "").lower() != "pending":
                    continue
                task["status"] = "closed_no_action"
                task["completed_at"] = now_iso
                task["result"] = (
                    "CI watcher verified recovery before this repair task started; "
                    f"green_run={green_run.get('run_id')}; no action required"
                )
                task["ci_closed_after_green"] = True
                retired.append(str(task.get("id")))
                changed = True
            if changed:
                write_tasks_to_handle(fh, tasks)
            return retired
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _ci_structured_repair_result(records: dict[str, dict]) -> dict[str, str]:
    import re

    for record in reversed(list(records.values())):
        if str(record.get("status") or "").lower() not in {
            "succeeded",
            "succeeded_null_result",
        }:
            continue
        result = str(record.get("result") or "")
        commit_match = re.search(r"\brepair_commit\s*[:=]\s*([0-9a-f]{7,40})\b", result, re.I)
        if not commit_match:
            continue
        cause_match = re.search(r"\broot_cause\s*[:=]\s*([^;\r\n]+)", result, re.I)
        parsed = {"repair_commit": commit_match.group(1).lower()}
        if cause_match:
            parsed["root_cause"] = " ".join(cause_match.group(1).split())[:280]
        return parsed
    return {}


def _ci_structured_repair_commit(records: dict[str, dict]) -> str | None:
    return _ci_structured_repair_result(records).get("repair_commit")


def _ci_apply_structured_repair_result(incident: dict, records: dict[str, dict]) -> str | None:
    parsed = _ci_structured_repair_result(records)
    commit = parsed.get("repair_commit")
    if commit:
        incident["repair_commit"] = commit
        incident["repair_commit_source"] = "task_result"
    if parsed.get("root_cause"):
        incident["confirmed_root_cause"] = parsed["root_cause"]
        incident["root_cause_source"] = "task_result"
    return commit


def _ci_commit_covered(repair_commit: str, green_head: str) -> bool:
    import subprocess

    if not repair_commit or not green_head:
        return False
    try:
        proc = subprocess.run(
            ["git", "merge-base", "--is-ancestor", repair_commit, green_head],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(PROJECT_ROOT),
        )
    except Exception as exc:  # noqa: BLE001
        warn("ci_watch", "repair commit ancestry probe failed", err=str(exc))
        return False
    return proc.returncode == 0


def _request_ci_repair_dispatch(task_id: str) -> dict:
    """Use the existing supervisor fire request; never start a second dispatcher."""
    try:
        from dispatch_supervisor import state as dispatch_state  # noqa: WPS433

        dispatch_state.request_fire(f"ci_red:{task_id}")
        return {"requested": True, "task_id": task_id}
    except Exception as exc:  # noqa: BLE001
        warn("ci_watch", "repair dispatch request failed", task_id=task_id, err=str(exc))
        return {"requested": False, "task_id": task_id, "error": str(exc)}


def _ci_delivery_accepted(result) -> bool:
    if not isinstance(result, dict):
        return result is True
    if result.get("sent"):
        return True
    # If the process died after delivery but before state save, send_alert's
    # stable-title ledger returns dedup_24h. Treat that as delivered, not an
    # outbox that retries forever.
    return bool(result.get("skipped") and result.get("skip_reason") == "dedup_24h")


def _ci_set_latest_observed(state: dict, run: dict) -> None:
    record = _ci_run_record(run)
    if state.get("latest_observed_run") != record:
        state["latest_observed_run"] = record


def _ci_mark_processed(state: dict, run: dict) -> None:
    record = _ci_run_record(run)
    prior = state.get("last_processed_run") or {}
    processed = state.setdefault("processed_run_keys", [])
    prior_key = prior.get("key")
    if prior_key and prior_key not in processed:
        processed.append(prior_key)
    if record["key"] not in processed:
        processed.append(record["key"])
    if len(processed) > 500:
        del processed[:-500]
    if not state.get("processing_floor_started_at"):
        state["processing_floor_started_at"] = (
            prior.get("started_at")
            or prior.get("created_at")
            or record.get("started_at")
            or record.get("created_at")
        )
    prior_sort = (
        str(prior.get("started_at") or prior.get("created_at") or ""),
        int(prior.get("run_id") or 0),
        int(prior.get("attempt") or 1),
    )
    record_sort = (
        str(record.get("started_at") or record.get("created_at") or ""),
        int(record.get("run_id") or 0),
        int(record.get("attempt") or 1),
    )
    if not prior or record_sort >= prior_sort:
        state["last_processed_run"] = record
    if record.get("conclusion") == "success":
        prior_success = state.get("latest_completed_success") or {}
        if not prior_success or record_sort >= _ci_record_sort_key(prior_success):
            state["latest_completed_success"] = record
    # Legacy projection retained for old dashboards/readers during migration.
    latest = state.get("last_processed_run") or record
    state["last_seen_run_id"] = latest["run_id"]
    state["last_seen_conclusion"] = latest["conclusion"]


def _ci_dispatch_pending_task(
    incident: dict,
    records: dict[str, dict],
    *,
    dispatcher,
    now_iso: str,
) -> tuple[dict | None, str | None]:
    dispatched = incident.setdefault("dispatch_requested_task_ids", [])
    for task_id in incident.get("repair_task_ids") or []:
        status = str((records.get(task_id) or {}).get("status") or "pending").lower()
        if status != "pending":
            continue
        # request_fire is a generic wake-up, not a targeted claim. Re-request on
        # every still-red poll until this task actually leaves pending; a previous
        # request may have been consumed while all slots were full or by another
        # candidate. ``dispatch_preempt`` on the row makes it lead the menu.
        result = dispatcher(task_id)
        ok = bool(result.get("requested")) if isinstance(result, dict) else bool(result)
        if ok:
            if task_id not in dispatched:
                dispatched.append(task_id)
            incident["dispatch_request_count"] = int(incident.get("dispatch_request_count") or 0) + 1
            incident["last_dispatch_request_at"] = now_iso
            return result if isinstance(result, dict) else {"requested": True}, None
        error = (result or {}).get("error") if isinstance(result, dict) else "request returned false"
        return result if isinstance(result, dict) else {"requested": False}, f"dispatch_failed: {error}"
    return None, None


def _ci_failed_task_ids(records: dict[str, dict]) -> list[str]:
    return [
        task_id
        for task_id, record in records.items()
        if str(record.get("status") or "").lower() in CI_FAILED_TASK_STATUSES
        and not record.get("ci_closed_after_green")
    ]


def _ci_set_escalation(incident: dict, reason: str) -> None:
    incident["escalation_reason"] = reason
    notice = incident.setdefault("notifications", {}).setdefault("escalation", {})
    if notice.get("status") != "sent":
        notice["status"] = "pending"
        incident["phase"] = "escalation_pending"


def _ci_mark_recovery_candidate(incident: dict, green: dict) -> None:
    incident.pop("verification_blocked", None)
    incident.pop("unverified_green_candidate", None)
    incident["phase"] = "recovery_pending"
    incident["recovery_candidate"] = _ci_run_record(green)
    notice = incident.setdefault("notifications", {}).setdefault("recovery", {})
    if notice.get("status") != "sent":
        notice["status"] = "pending"


def _ci_green_supersedes_failures(
    green_head: str,
    failed_heads: set[str],
    *,
    commit_covered_probe,
) -> bool:
    """True when a green head carries every failing commit in its history.

    Fails closed: an unknown/ungraftable failed head makes the ancestry probe
    return False, so a green run cannot close an incident it does not provably
    supersede.
    """
    if not green_head or not failed_heads or green_head in failed_heads:
        return False
    return all(
        commit_covered_probe(failed_head, green_head) for failed_head in failed_heads
    )


def _ci_repair_verification_error(
    incident: dict,
    *,
    repair_commit: str,
    green_head: str,
    commit_covered_probe,
) -> str | None:
    """Return why a green run is not proof of a post-failure repair.

    A rerun can turn green on the exact code that already failed. More subtly, a
    proposed repair commit can itself have been covered by a later failed run in
    the same incident. Both are flaky/re-failure evidence, not a verified fix.

    A repair-task receipt is not the only admissible proof. When every failing
    commit is an ancestor of a green head, main passes CI with all of the failing
    code in its history — the failure is gone no matter which path fixed it. That
    edge has to exist: a fix landing outside the repair task (a refactor, a
    revert, a human commit) would otherwise leave the incident escalating forever
    against an already-green main.
    """
    failed_heads = {
        str(head)
        for head in incident.get("failure_heads") or []
        if str(head)
    }
    for record_name in ("first_failure", "latest_failure"):
        head = str((incident.get(record_name) or {}).get("head_sha") or "")
        if head:
            failed_heads.add(head)
    if _ci_green_supersedes_failures(
        green_head,
        failed_heads,
        commit_covered_probe=commit_covered_probe,
    ):
        return None
    if not repair_commit:
        return "green_without_repair_commit_evidence"
    if not green_head:
        return "green_run_missing_head_sha"
    if green_head in failed_heads:
        return "green_head_already_observed_failing"
    for failed_head in failed_heads:
        if commit_covered_probe(repair_commit, failed_head):
            return "repair_commit_already_observed_failing"
    if not commit_covered_probe(repair_commit, green_head):
        return "green_head_does_not_cover_known_repair_commit"
    return None


def _reduce_ci_run(
    state: dict,
    run: dict,
    *,
    now_iso: str,
    next_tasks_path: Path,
    ahead_probe,
    pusher,
    failure_summarizer,
    task_status_probe,
    dispatcher,
    commit_covered_probe,
    checkpoint,
) -> dict:
    """Mutate incident state and trigger repair effects; never notify the boss."""
    run_id = run.get("databaseId")
    conclusion = str(run.get("conclusion") or "").lower()
    status = str(run.get("status") or "completed").lower()
    summary = {
        "checked": True,
        "run_id": run_id,
        "run_key": _ci_run_key(run),
        "status": status,
        "conclusion": conclusion,
        "task_added": False,
        "alert_sent": False,
    }
    if status != "completed":
        summary["reason"] = "run_not_completed"
        return summary

    incident = state.get("active_incident")
    if conclusion in CI_FAILURE_CONCLUSIONS:
        run_key = _ci_run_key(run)
        is_new_incident = not isinstance(incident, dict)
        if is_new_incident:
            closed = state.get("last_closed_incident") or {}
            closed_green = closed.get("verified_green_run") or {}
            latest_success = state.get("latest_completed_success") or {}
            boundaries = [record for record in (closed_green, latest_success) if record]
            green_boundary = max(boundaries, key=_ci_record_sort_key) if boundaries else {}
            if green_boundary and _ci_run_sort_key(run) <= _ci_record_sort_key(green_boundary):
                if closed_green and _ci_run_sort_key(run) <= _ci_record_sort_key(closed_green):
                    _ci_record_failure(closed, run)
                    late = closed.setdefault("late_discovered_failure_run_keys", [])
                    if run_key not in late:
                        late.append(run_key)
                    summary["failure_cycles"] = len(closed.get("failure_run_keys") or [])
                    summary["phase"] = "recovered"
                    summary["reason"] = "late_failure_precedes_closed_green"
                else:
                    late = state.setdefault("late_discovered_failure_run_keys", [])
                    if run_key not in late:
                        late.append(run_key)
                    summary["failure_cycles"] = 0
                    summary["phase"] = "idle"
                    summary["reason"] = "late_failure_precedes_completed_green"
                _ci_mark_processed(state, run)
                return summary

        if isinstance(incident, dict):
            green_boundary = (
                incident.get("recovery_candidate")
                or incident.get("unverified_green_candidate")
                or {}
            )
            if green_boundary and _ci_run_sort_key(run) <= _ci_record_sort_key(green_boundary):
                _ci_record_failure(incident, run)
                _ci_mark_processed(state, run)
                summary["reason"] = "late_failure_precedes_observed_green"
                summary["failure_cycles"] = len(incident.get("failure_run_keys") or [])
                summary["phase"] = incident.get("phase")
                return summary

        if is_new_incident:
            incident_id = _ci_task_id(run)
            incident = {
                "incident_id": incident_id,
                "phase": "remediating",
                "opened_at": now_iso,
                "first_failure": _ci_run_record(run),
                "root_cause": "failed log 摘要擷取中",
                "root_cause_status": "pending",
                "failure_run_keys": [],
                "repair_task_ids": [],
                "dispatch_requested_task_ids": [],
                "notifications": {},
            }
            state["active_incident"] = incident
            # Persist the incident shell before the network-bound log read. The
            # outer cron may kill this process at 300s, but the next poll must still
            # know a red incident existed.
            checkpoint()

        if incident.get("root_cause_status") != "complete":
            incident["root_cause"] = failure_summarizer(run)
            incident["root_cause_status"] = "complete"
            checkpoint()

        is_new_failure = _ci_record_failure(incident, run)
        failure_keys = incident.setdefault("failure_run_keys", [])
        incident.pop("recovery_candidate", None)
        incident.pop("unverified_green_candidate", None)

        task_ids = incident.setdefault("repair_task_ids", [])
        records = task_status_probe(task_ids)
        _ci_apply_structured_repair_result(incident, records)

        statuses = {
            task_id: str(record.get("status") or "").lower()
            for task_id, record in records.items()
        }
        has_active_task = any(value in CI_ACTIVE_TASK_STATUSES for value in statuses.values())
        failed_tasks = _ci_failed_task_ids(records)
        should_ensure = not task_ids or (is_new_failure and not has_active_task and not failed_tasks)
        hard_failure: str | None = None
        if should_ensure:
            task = _build_ci_repair_task(
                run,
                now_iso=now_iso,
                failure_cause=incident.get("root_cause"),
                incident_id=incident.get("incident_id"),
            )
            try:
                summary["task_added"] = _append_next_task_locked(task, next_tasks_path)
                if task["id"] not in task_ids:
                    task_ids.append(task["id"])
                state["last_task_id"] = task["id"]
                summary["task_id"] = task["id"]
            except Exception as exc:  # noqa: BLE001
                warn("ci_watch", "P1 repair task append failed", err=str(exc), task_id=task["id"])
                hard_failure = f"append_failed: {type(exc).__name__}: {exc}"

        records = task_status_probe(task_ids)
        _ci_apply_structured_repair_result(incident, records)
        statuses = {
            task_id: str(record.get("status") or "").lower()
            for task_id, record in records.items()
        }
        incident["repair_task_statuses"] = statuses

        dispatch_result, dispatch_error = _ci_dispatch_pending_task(
            incident,
            records,
            dispatcher=dispatcher,
            now_iso=now_iso,
        )
        if dispatch_result is not None:
            summary["dispatch"] = dispatch_result
        if dispatch_error:
            hard_failure = dispatch_error

        failed_tasks = _ci_failed_task_ids(records)
        if failed_tasks:
            hard_failure = f"repair_task_terminal_failure: {', '.join(failed_tasks)}"
        elif len(failure_keys) > CI_MAX_SILENT_FAILURE_CYCLES:
            hard_failure = f"ci_failed_more_than_two_cycles: {len(failure_keys)}"
        if hard_failure:
            _ci_set_escalation(incident, hard_failure)

        # Task, fire request, and any terminal outbox are durable before git/network
        # work. This is the last guaranteed checkpoint under the wrapper's hard cap.
        checkpoint()

        def persist_push_intent(probe: dict) -> None:
            incident["push_intent"] = {
                "head_sha": probe.get("head_sha") or "",
                "run_key": run_key,
                "recorded_at": now_iso,
            }
            checkpoint()

        push = _remediate_unpushed_fix(
            run,
            ahead_probe=ahead_probe,
            pusher=pusher,
            before_push=persist_push_intent,
        )
        summary["push"] = push
        push_snapshot = {key: value for key, value in push.items() if key != "at"}
        if incident.get("last_push_remediation") != push_snapshot:
            incident["last_push_remediation"] = push_snapshot
            incident["last_push_remediation_at"] = now_iso
        state["last_push_remediation"] = push_snapshot
        if push.get("pushed") and push.get("head_sha"):
            # A shared-main HEAD can contain unrelated work. Record the verified
            # push for ops/durability, but only the repair worker's structured
            # result may attribute a specific commit as the CI repair.
            incident["last_verified_push_head"] = push["head_sha"]

        if incident.get("escalation_reason"):
            summary["reason"] = incident["escalation_reason"]
        elif incident.get("repair_commit") or incident.get("push_intent"):
            incident["phase"] = "verifying"
            summary["reason"] = "repair_verifying"
        else:
            incident["phase"] = "remediating"
            summary["reason"] = "repair_dispatched" if summary["task_added"] else "repair_in_progress"

        _ci_mark_processed(state, run)
        summary["failure_cycles"] = len(failure_keys)
        summary["phase"] = incident.get("phase")
        return summary

    if conclusion == "success" and isinstance(incident, dict):
        latest_failure = incident.get("latest_failure") or {}
        if latest_failure and _ci_run_sort_key(run) <= _ci_record_sort_key(latest_failure):
            _ci_mark_processed(state, run)
            summary["reason"] = "late_success_precedes_latest_failure"
            summary["failure_cycles"] = len(incident.get("failure_run_keys") or [])
            summary["phase"] = incident.get("phase")
            return summary
        records = task_status_probe(incident.get("repair_task_ids") or [])
        _ci_apply_structured_repair_result(incident, records)

        repair_commit = str(incident.get("repair_commit") or "")
        green_head = str(run.get("headSha") or "")
        attempt = int(run.get("attempt") or 1)
        history_complete = _ci_attempt_history_complete(state, run)
        verification_error = (
            "rerun_attempt_history_incomplete"
            if attempt > 1 and not history_complete
            else _ci_repair_verification_error(
                incident,
                repair_commit=repair_commit,
                green_head=green_head,
                commit_covered_probe=commit_covered_probe,
            )
        )
        if verification_error:
            # A flaky rerun or a commit already covered by any failed run is not a
            # code repair. Retain the green for later evidence, but do not tell the
            # boss it was "fixed".
            incident["phase"] = "verifying"
            incident["unverified_green_candidate"] = _ci_run_record(run)
            incident["verification_blocked"] = {
                "reason": verification_error,
                "repair_commit": repair_commit,
                "green_run": _ci_run_record(run),
            }
            summary["reason"] = {
                "green_without_repair_commit_evidence": "green_without_repair_evidence",
                "green_head_does_not_cover_known_repair_commit": (
                    "green_does_not_cover_repair_commit"
                ),
            }.get(verification_error, verification_error)
        else:
            if not repair_commit:
                incident["repair_commit_source"] = "green_descendant"
            _ci_mark_recovery_candidate(incident, run)
            summary["reason"] = "recovery_pending_notification"
        _ci_mark_processed(state, run)
        summary["failure_cycles"] = len(incident.get("failure_run_keys") or [])
        summary["phase"] = incident.get("phase")
        return summary

    # Cancelled/skipped/neutral is neither a failure cycle nor proof of recovery.
    _ci_mark_processed(state, run)
    summary["reason"] = "healthy_no_incident" if conclusion == "success" else "neutral_run"
    summary["phase"] = (incident or {}).get("phase") if isinstance(incident, dict) else "idle"
    return summary


def _ci_refresh_recovery_evidence(state: dict, *, task_status_probe, commit_covered_probe) -> None:
    """Promote a stored green once a repair task later supplies its commit."""
    incident = state.get("active_incident")
    if not isinstance(incident, dict) or incident.get("recovery_candidate"):
        return
    green = incident.get("unverified_green_candidate")
    if not isinstance(green, dict):
        return
    records = task_status_probe(incident.get("repair_task_ids") or [])
    incident["repair_task_statuses"] = {
        task_id: str(record.get("status") or "").lower()
        for task_id, record in records.items()
    }
    failed_tasks = _ci_failed_task_ids(records)
    if failed_tasks:
        _ci_set_escalation(
            incident,
            f"repair_task_terminal_failure: {', '.join(failed_tasks)}",
        )
        return
    repair_commit = _ci_apply_structured_repair_result(incident, records)
    green_head = str(green.get("head_sha") or "")
    verification_error = (
        "rerun_attempt_history_incomplete"
        if int(green.get("attempt") or 1) > 1
        and not _ci_attempt_history_complete(state, green)
        else _ci_repair_verification_error(
            incident,
            repair_commit=repair_commit,
            green_head=green_head,
            commit_covered_probe=commit_covered_probe,
        )
    )
    if not verification_error:
        incident["repair_commit"] = repair_commit
        incident["repair_commit_source"] = "task_result" if repair_commit else "green_descendant"
        _ci_mark_recovery_candidate(incident, _ci_record_as_run(green))
    else:
        incident["verification_blocked"] = {
            "reason": verification_error,
            "repair_commit": repair_commit,
            "green_run": green,
        }


def _ci_refresh_attempt_completeness(state: dict, runs: list[dict]) -> None:
    incident = state.get("active_incident")
    if not isinstance(incident, dict):
        return
    candidate = incident.get("unverified_green_candidate")
    if not isinstance(candidate, dict):
        return
    current = next(
        (run for run in runs if _ci_run_key(run) == candidate.get("key")),
        None,
    )
    if current is not None:
        incident["unverified_green_candidate"] = _ci_run_record(current)


def _ci_advance_remediation_watchdog(state: dict, *, now_iso: str) -> None:
    """Escalate an incident that makes no terminal progress for >2 polls."""
    incident = state.get("active_incident")
    if not isinstance(incident, dict) or incident.get("recovery_candidate"):
        return
    checks = incident.setdefault("remediation_poll_keys", [])
    # Count scheduled hourly cycles, not duplicate processes or manual retries in
    # the same hour. The incident flock serializes them, and this bucket dedupes
    # them so a launchd double-fire cannot manufacture a three-cycle timeout.
    poll_key = now_iso[:13]
    if poll_key not in checks:
        checks.append(poll_key)
    incident["remediation_checks"] = len(checks)
    if len(checks) > CI_MAX_SILENT_FAILURE_CYCLES and not incident.get("escalation_reason"):
        _ci_set_escalation(
            incident,
            f"remediation_stalled_more_than_two_checks: {len(checks)}",
        )


def _notify_ci_incident(
    state: dict,
    run: dict,
    *,
    now_iso: str,
    next_tasks_path: Path,
    sender=None,
    task_closer=None,
) -> dict:
    incident = state.get("active_incident")
    summary = {"alert_sent": False, "notification_delivered": False}
    if not isinstance(incident, dict):
        return summary

    candidate = incident.get("recovery_candidate") or {}
    notices = incident.setdefault("notifications", {})
    kind: str | None = None
    observed_status = str(run.get("status") or "completed").lower()
    observed_record = _ci_run_record(run)
    if (
        candidate
        and observed_status == "completed"
        and observed_record.get("conclusion") in CI_FAILURE_CONCLUSIONS
        and _ci_record_sort_key(observed_record) > _ci_record_sort_key(candidate)
    ):
        incident.pop("recovery_candidate", None)
        candidate = {}
    if candidate and observed_status != "completed":
        # A newer run in progress may invalidate the prior green. Keep both
        # recovery and any same-batch escalation in ops until it finishes.
        summary["reason"] = "newer_run_in_progress"
        return summary
    if candidate:
        # A later cancelled/skipped run is neutral, not evidence that the verified
        # green vanished. Notify from the stored green candidate, never from the
        # neutral row that happened to be latest.
        kind = "recovery"
    elif incident.get("escalation_reason"):
        # Once the >2-cycle/task-terminal outbox exists, a neutral or in-progress
        # run cannot suppress it. There is no verified recovery candidate to prefer.
        kind = "escalation"
    if kind is None:
        return summary

    notice = notices.setdefault(kind, {})
    if notice.get("status") == "sent":
        summary["reason"] = f"{kind}_already_notified"
        return summary

    incident_id = incident.get("incident_id") or "ci-red-unknown"
    reported_cause = (
        incident.get("confirmed_root_cause")
        or incident.get("root_cause")
        or "failed log 無可解析摘要"
    )
    if kind == "recovery":
        green_head = str(candidate.get("head_sha") or "")
        repair_commit = str(incident.get("repair_commit") or "")
        if repair_commit:
            commit_line = (
                f"修復 commit：{repair_commit[:12]}；綠燈驗證 head：{green_head[:12]}。"
            )
        elif incident.get("repair_commit_source") == "green_descendant":
            # Nobody claimed the fix, so no commit may be named as the repair.
            # The green head carrying every failing commit is the evidence.
            commit_line = (
                f"無單一修復 commit（修復由 repair task 以外的路徑落地）；"
                f"綠燈驗證 head：{green_head[:12]}，該 head 已涵蓋全部失敗 commit。"
            )
        else:
            summary["reason"] = "recovery_missing_repair_commit"
            return summary
        level = "info"
        title = f"CI 已修復並驗證（{incident_id}）"
        body = (
            "## 已修復並驗證\n"
            f"失敗原因：{reported_cause}\n\n"
            f"{commit_line}\n"
            f"綠燈 run：{candidate.get('run_id')}（attempt {int(candidate.get('attempt') or 1)}）\n"
            f"{candidate.get('url')}\n\n"
            f"自動修復期間共觀察 {len(incident.get('failure_run_keys') or [])} 個 failure cycle；"
            "中間派工與驗證狀態只留在 ops。"
        )
    else:
        latest = incident.get("latest_failure") or {}
        level = "critical"
        title = f"CI 自動修復未成功（{incident_id}）"
        body = (
            "## 自動修復需要支援\n"
            f"原因：{incident.get('escalation_reason')}\n"
            f"原始失敗：{reported_cause}\n"
            f"已失敗 cycles：{len(incident.get('failure_run_keys') or [])}\n"
            f"repair tasks：{incident.get('repair_task_statuses') or {}}\n\n"
            f"最新 failure run：{latest.get('run_id')}\n{latest.get('url')}"
        )

    if kind == "recovery" and not notice.get("task_cleanup_complete"):
        task_closer = task_closer or _ci_close_pending_repair_tasks
        try:
            retired = task_closer(
                incident.get("repair_task_ids") or [],
                next_tasks_path,
                now_iso=now_iso,
                green_run=candidate,
            )
        except Exception as exc:  # noqa: BLE001
            warn("ci_watch", "verified recovery task cleanup failed", err=str(exc))
            notice["status"] = "cleanup_pending"
            notice["last_cleanup_error"] = f"{type(exc).__name__}: {exc}"
            incident["phase"] = "recovery_cleanup_pending"
            summary["notification_kind"] = kind
            summary["reason"] = "recovery_task_cleanup_pending"
            return summary
        notice["task_cleanup_complete"] = True
        notice["task_cleanup_at"] = now_iso
        incident["retired_pending_task_ids"] = retired
        statuses = incident.setdefault("repair_task_statuses", {})
        for task_id in retired:
            statuses[task_id] = "closed_no_action"

    accepted = bool(notice.get("delivery_accepted"))
    if not accepted:
        if sender is None:
            from volpred.ops.alerts import send_alert as sender  # noqa: WPS433
        notice["attempts"] = int(notice.get("attempts") or 0) + 1
        notice["last_attempt_at"] = now_iso
        try:
            result = sender(
                level,
                title,
                body,
                storage_dir=str(PROJECT_ROOT / "storage"),
            )
            accepted = _ci_delivery_accepted(result)
            notice["last_delivery"] = {
                key: result.get(key)
                for key in ("sent", "skipped", "skip_reason", "notification_id", "send_error")
                if isinstance(result, dict) and key in result
            }
            summary["alert_sent"] = bool(result.get("sent")) if isinstance(result, dict) else accepted
        except Exception as exc:  # noqa: BLE001
            warn("ci_watch", "terminal notification send failed", kind=kind, err=str(exc))
            accepted = False
            notice["last_error"] = f"{type(exc).__name__}: {exc}"

    summary["notification_kind"] = kind
    summary["notification_delivered"] = accepted
    if not accepted:
        notice["status"] = "pending"
        incident["phase"] = f"{kind}_notification_pending"
        summary["reason"] = f"{kind}_notification_pending"
        return summary

    notice["delivery_accepted"] = True
    notice.setdefault("delivery_accepted_at", now_iso)
    if kind == "escalation":
        notice["status"] = "sent"
        notice["sent_at"] = now_iso
        incident["phase"] = "escalated"
        summary["reason"] = "escalation_notified"
        return summary

    import copy

    notice["status"] = "sent"
    notice["sent_at"] = now_iso
    incident["phase"] = "recovered"
    incident["recovered_at"] = now_iso
    incident["verified_green_run"] = candidate
    state["last_closed_incident"] = copy.deepcopy(incident)
    state.pop("active_incident", None)
    summary["reason"] = "recovery_notified"
    return summary


def _ci_result_summary(state: dict, transitions: list[dict], notification: dict, observed: dict) -> dict:
    last = transitions[-1] if transitions else {
        "checked": True,
        "run_id": observed.get("databaseId"),
        "status": observed.get("status"),
        "conclusion": observed.get("conclusion"),
        "task_added": False,
    }
    result = dict(last)
    result["processed_run_ids"] = [item.get("run_id") for item in transitions]
    result["task_added"] = any(item.get("task_added") for item in transitions)
    result.update(notification)
    incident = state.get("active_incident") or state.get("last_closed_incident") or {}
    result["phase"] = incident.get("phase", "idle")
    result["failure_cycles"] = len(incident.get("failure_run_keys") or [])
    if notification.get("reason"):
        result["reason"] = notification["reason"]
    for item in reversed(transitions):
        if item.get("push"):
            result["push"] = item["push"]
            break
    return result


def _handle_ci_runs(
    runs: list[dict],
    *,
    now_iso: str,
    next_tasks_path: Path = CI_NEXT_TASKS,
    state_path: Path = CI_WATCH_STATE,
    sender=None,
    ahead_probe=None,
    pusher=None,
    failure_summarizer=None,
    task_status_probe=None,
    dispatcher=None,
    commit_covered_probe=None,
    task_closer=None,
) -> dict:
    if not runs:
        return {"checked": False, "reason": "gh_unavailable_or_no_runs"}
    failure_summarizer = failure_summarizer or _ci_failure_summary
    task_status_probe = task_status_probe or (
        lambda ids: _ci_task_records(ids, next_tasks_path)
    )
    dispatcher = dispatcher or _request_ci_repair_dispatch
    commit_covered_probe = commit_covered_probe or _ci_commit_covered

    with _ci_state_lock(state_path):
        state = _load_json_dict(state_path, label="ci_watch_state")
        import copy

        original = copy.deepcopy(state)
        state["schema_version"] = 3

        def checkpoint() -> None:
            state["updated_at"] = now_iso
            _write_json_atomic(state_path, state)

        observed = max(runs, key=_ci_run_sort_key)
        _ci_set_latest_observed(state, observed)
        transitions = []
        for run in _ci_runs_to_process(runs, state):
            transitions.append(
                _reduce_ci_run(
                    state,
                    run,
                    now_iso=now_iso,
                    next_tasks_path=next_tasks_path,
                    ahead_probe=ahead_probe,
                    pusher=pusher,
                    failure_summarizer=failure_summarizer,
                    task_status_probe=task_status_probe,
                    dispatcher=dispatcher,
                    commit_covered_probe=commit_covered_probe,
                    checkpoint=checkpoint,
                )
            )
        _ci_refresh_attempt_completeness(state, runs)
        _ci_refresh_recovery_evidence(
            state,
            task_status_probe=task_status_probe,
            commit_covered_probe=commit_covered_probe,
        )
        _ci_advance_remediation_watchdog(state, now_iso=now_iso)
        # Persist the terminal outbox before network delivery. Recovery wins over
        # a same-poll escalation; a newer in-progress run still defers recovery.
        if isinstance(state.get("active_incident"), dict):
            checkpoint()
        notification = _notify_ci_incident(
            state,
            observed,
            now_iso=now_iso,
            next_tasks_path=next_tasks_path,
            sender=sender,
            task_closer=task_closer,
        )
        state["updated_at"] = now_iso if state != original else state.get("updated_at")
        _write_ci_state_if_changed(state_path, state, original)
        return _ci_result_summary(state, transitions, notification, observed)


def _handle_ci_run(
    run: dict,
    *,
    now_iso: str,
    next_tasks_path: Path = CI_NEXT_TASKS,
    state_path: Path = CI_WATCH_STATE,
    sender=None,
    ahead_probe=None,
    pusher=None,
    failure_summarizer=None,
    task_status_probe=None,
    dispatcher=None,
    commit_covered_probe=None,
    task_closer=None,
) -> dict:
    """Single-run injectable wrapper around the history-aware incident reducer."""
    return _handle_ci_runs(
        [run],
        now_iso=now_iso,
        next_tasks_path=next_tasks_path,
        state_path=state_path,
        sender=sender,
        ahead_probe=ahead_probe,
        pusher=pusher,
        failure_summarizer=failure_summarizer,
        task_status_probe=task_status_probe,
        dispatcher=dispatcher,
        commit_covered_probe=commit_covered_probe,
        task_closer=task_closer,
    )


def _handle_ci_unavailable(
    *,
    now_iso: str,
    next_tasks_path: Path = CI_NEXT_TASKS,
    state_path: Path = CI_WATCH_STATE,
    sender=None,
    task_status_probe=None,
    dispatcher=None,
) -> dict:
    """Keep an existing repair incident moving when GitHub polling is unavailable."""
    task_status_probe = task_status_probe or (
        lambda ids: _ci_task_records(ids, next_tasks_path)
    )
    dispatcher = dispatcher or _request_ci_repair_dispatch
    with _ci_state_lock(state_path):
        state = _load_json_dict(state_path, label="ci_watch_state")
        incident = state.get("active_incident")
        if not isinstance(incident, dict):
            return {"checked": False, "reason": "gh_unavailable_or_no_runs"}
        import copy

        original = copy.deepcopy(state)
        state["schema_version"] = 3
        task_ids = incident.get("repair_task_ids") or []
        records = task_status_probe(task_ids)
        _ci_apply_structured_repair_result(incident, records)
        incident["repair_task_statuses"] = {
            task_id: str(record.get("status") or "").lower()
            for task_id, record in records.items()
        }
        dispatch_result, dispatch_error = _ci_dispatch_pending_task(
            incident,
            records,
            dispatcher=dispatcher,
            now_iso=now_iso,
        )
        failed_tasks = _ci_failed_task_ids(records)
        if failed_tasks:
            _ci_set_escalation(
                incident,
                f"repair_task_terminal_failure: {', '.join(failed_tasks)}",
            )
        elif dispatch_error:
            _ci_set_escalation(incident, dispatch_error)
        _ci_advance_remediation_watchdog(state, now_iso=now_iso)
        state["updated_at"] = now_iso
        _write_json_atomic(state_path, state)

        notification: dict = {"alert_sent": False, "notification_delivered": False}
        observed_record = (
            state.get("latest_observed_run")
            or incident.get("latest_failure")
            or incident.get("first_failure")
            or {}
        )
        observed = _ci_record_as_run(observed_record)
        # A provider outage must not strand a terminal outbox created by the
        # previous available poll. In particular, retry a verified recovery
        # notification whose first delivery failed; the notifier itself safely
        # no-ops when there is no recovery/escalation and defers on an observed
        # newer in-progress run.
        notification = _notify_ci_incident(
            state,
            observed,
            now_iso=now_iso,
            next_tasks_path=next_tasks_path,
            sender=sender,
        )
        _write_ci_state_if_changed(state_path, state, original)
        result = _ci_result_summary(state, [], notification, observed)
        result["ci_provider_available"] = False
        if dispatch_result is not None:
            result["dispatch"] = dispatch_result
        return result


def _auto_remediate_ci_red() -> dict:
    from datetime import timezone

    runs = _ci_recent_runs()
    if not runs:
        return _handle_ci_unavailable(now_iso=datetime.now(timezone.utc).isoformat())
    return _handle_ci_runs(runs, now_iso=datetime.now(timezone.utc).isoformat())


# The monitor cannot meaningfully monitor itself; `host_crontab_managed: false`
# means the entry documents something this host does not schedule.
STALENESS_EXCLUDED_JOB_IDS = frozenset({"check_alerts"})
STALENESS_TOLERANCE = 2.0  # a job is stale past 2× its longest legitimate gap


def cron_max_gap_min(cron_expr: str, *, base=None, samples: int = 12) -> float:
    """Longest legitimate gap, in minutes, between consecutive fires of `cron_expr`.

    Replaces a hardcoded 7-entry `period_map` (2026-07-10). That table covered 7 of
    the 32 monitored jobs — the other 24 hit `period_min is None` and were skipped
    *silently*, so a dead `daily_update` or `release_pool` could never surface. It
    also carried 3 entries (`0 */2 * * *`, `3 */2 * * *`, `0 0 * * *`) matching no
    job at all.

    MAX gap, not mean: `0 15 * * 1-5` fires each weekday, so its longest honest gap
    is Fri→Mon (3 days), not 24h. Using the mean would alert every weekend.
    """
    from datetime import datetime as _dt

    if croniter is None:
        raise RuntimeError("croniter not installed")
    it = croniter(cron_expr, base or _dt.now())
    times = [it.get_next(_dt) for _ in range(samples)]
    return max((b - a).total_seconds() / 60 for a, b in zip(times, times[1:]))


def evaluate_cron_staleness(items, state, now, *, state_path=None, base=None) -> list[dict]:
    """One record per configured job — nothing is silently skipped.

    Every entry in `system_crontab.items` gets a verdict:
      excluded / unmanaged   — deliberately not checked, with a reason
      never_ran              — configured but has NEVER recorded a run
      bad_cron               — cron expression croniter cannot parse
      unparsable_marker      — marker exists but is not a timestamp
      stale / ok             — compared against 2× the cron's longest legit gap

    Returning `never_ran` and `bad_cron` as verdicts rather than `continue`
    statements is the point: the old loop dropped both on the floor, which is how
    `indicator_arena_daily` (never once recorded) stayed invisible.
    """
    records: list[dict] = []
    for item in items:
        job_id = item.get("id")
        cron = item.get("cron")
        if not job_id:
            continue
        if item.get("host_crontab_managed") is False:
            records.append({"job_id": job_id, "status": "unmanaged", "detail": "host_crontab_managed=false"})
            continue
        if job_id in STALENESS_EXCLUDED_JOB_IDS:
            records.append({"job_id": job_id, "status": "excluded", "detail": "the monitor itself"})
            continue

        try:
            period_min = cron_max_gap_min(cron, base=base)
        except Exception as exc:  # noqa: BLE001
            # The bad_cron record below is the machine-readable trace, but a
            # record in a returned list is invisible to audit_silent_fallbacks
            # (it only recognises logging-shaped calls). Emit the sanctioned
            # diagnostic too, per .claude/rules/no-silent-fallback.md.
            warn("check_alerts", "cron expression unparseable; job marked bad_cron",
                 job_id=job_id, cron=cron, err=str(exc))
            records.append({"job_id": job_id, "status": "bad_cron", "detail": f"cron={cron!r} ({exc})"})
            continue

        last_iso = state.get(job_id)
        if not last_iso:
            records.append({"job_id": job_id, "status": "never_ran",
                            "detail": f"no cron_last_run entry (cron={cron})",
                            "period_min": period_min})
            continue
        try:
            last_dt = datetime.fromisoformat(str(last_iso).replace("Z", "+00:00"))
        except Exception as exc:  # noqa: BLE001
            _warn_check_alerts(
                f"cron_last_run timestamp parse failed for job_id={job_id}",
                state_path, exc,
            )
            records.append({"job_id": job_id, "status": "unparsable_marker", "detail": repr(last_iso)})
            continue

        age_min = (now - last_dt).total_seconds() / 60
        records.append({
            "job_id": job_id,
            "status": "stale" if age_min > STALENESS_TOLERANCE * period_min else "ok",
            "age_min": age_min,
            "period_min": period_min,
        })
    return records


def _wrapper_drift_entries() -> list[str]:
    """Does the wrapper launchd execs still match the one in the repo?

    launchd runs ~/.volpred/bin/cron_<x>.sh; `scripts/cron_<x>.sh` is only its
    source. Editing the canonical copy silently changes nothing until someone
    syncs — on 2026-07-10, 11 of 40 wrappers had drifted, `cron_market_cal.sh`
    by three months and `cron_hourly_dispatch.sh` (the dispatch backbone) by a
    portability fix. This is the same bug class as the cron freshness marker:
    the artifact you edit is decoupled from the thing that runs.

    Fail loud, never silently: a broken detector must not read as "no drift".
    """
    try:
        from sync_cron_wrappers import detect_live_drift  # noqa: WPS433 (scripts/ on sys.path)

        findings = detect_live_drift(PROJECT_ROOT)
    except Exception as exc:  # noqa: BLE001 — a dead detector is itself a drift signal
        return [f"wrapper_drift_check_failed: {type(exc).__name__}: {exc}"]

    return [f"{f['kind']}: {f['job_id']} {f['detail']}" for f in findings]


def _check_piggy_back_drift(due_summary: dict) -> dict:
    """Detect piggy-back scheduler health drift (B3.7 / finding #18).

    Signals:
    - run_due_jobs returned ok=False (croniter / config / import error)
    - any wrapper_script reported missing
    - any wrapper whose live ~/.volpred/bin copy drifts from its repo canonical
      (`wrapper_drift`) or was never installed (`wrapper_not_installed`)
    - any non-skipped job's cron_last_run is older than 2× its cron period
      (host cron alone could not reliably fire that cadence — piggy-back is
      our only safety net; if last_run goes stale, the safety net is broken)

    Print warnings inline; return summary dict for log scrapers. Does NOT
    escalate to alert (avoids alert noise; observability-only for now).
    """
    from datetime import datetime, timezone

    drifts: list[str] = []

    if not due_summary.get("ok") and due_summary.get("reason"):
        drifts.append(f"run_due_jobs error: {due_summary.get('reason')}")

    for job in due_summary.get("jobs", []) or []:
        if job.get("action") == "skip" and job.get("reason") == "wrapper_missing":
            drifts.append(f"wrapper_missing: {job.get('job_id')} path={job.get('path')}")

    drifts.extend(_wrapper_drift_entries())

    # Stale last_run check
    state_path = PROJECT_ROOT / "storage" / "ops" / "cron_last_run.json"
    config_path = PROJECT_ROOT / "config" / "runtime_schedules.json"
    state = _load_json_dict(state_path, label="cron_last_run")
    config = _load_json_dict(config_path, label="runtime_schedules")

    items = (config.get("system_crontab") or {}).get("items") or []
    now = datetime.now(timezone.utc)
    for record in evaluate_cron_staleness(items, state, now, state_path=state_path):
        if record["status"] == "stale":
            drifts.append(
                f"stale_last_run: {record['job_id']} age={record['age_min']:.0f}min "
                f"period={record['period_min']:.0f}min"
            )
        elif record["status"] in ("never_ran", "bad_cron", "unparsable_marker"):
            drifts.append(f"{record['status']}: {record['job_id']} {record['detail']}")

    if drifts:
        print("  piggy-back-drift:")
        for entry in drifts:
            print(f"    - {entry}")
    else:
        print("  piggy-back-drift: none")
    return {"drift_count": len(drifts), "drifts": drifts}


def main() -> int:
    import os

    from volpred.ops import check_alert_conditions  # noqa: WPS433 (deferred for sys.path)
    from volpred.ops.boss_facing import plainify_boss_text  # noqa: WPS433

    # 2026-06-29: this is the canonical hourly alert path — opt into the
    # content-quality frontend render probe here (network call). content_quality_
    # snapshot defaults it OFF so tests/dashboard stay offline; turning it on for
    # the hourly check gives live React-error / 5xx detection (2026-06-24 #418).
    os.environ.setdefault("VOLPRED_FRONTEND_PROBE", "1")

    # CI is the most time-sensitive check and owns a cross-tick repair state
    # machine. Run it before release/drought/orphan subprocesses: some of those
    # have 240-600s internal caps while this wrapper itself is capped at 300s,
    # which previously meant the CI poll could be killed before it even started.
    ci_watch = _auto_remediate_ci_red()

    # 2026-04-20 universal piggy-back scheduler: macOS host cron daemon only
    # reliably fires `0 * * * *` pattern on this machine (confirmed via
    # 180s diagnostic test of `* * * * *` that never fired). All other cron
    # patterns (`3 */2`, `0 8 * * 1`, `3 7 * * 2-6`, etc.) silently skip
    # despite `crontab -l` showing the entries. Root-cause fix: since
    # check_alerts (`0 * * * *`) fires reliably hourly, it serves as the
    # canonical scheduler — iterate `config/runtime_schedules.json` via
    # `scripts/run_due_jobs.py` and invoke due jobs' wrappers directly.
    try:
        from run_due_jobs import run_due_jobs as _run_due_jobs  # noqa: WPS433
        due_summary = _run_due_jobs()
    except Exception as exc:  # noqa: BLE001
        due_summary = {"ok": False, "error": str(exc), "jobs": []}

    # 2026-04-19 release-pool piggy-back (interval-based, independent of cron
    # schedule). Kept alongside run_due_jobs because release_pool honors
    # settings.interval_minutes not fixed crontab, and catches drift between
    # cron :03 boundaries and .release_settings.json last_released_at.
    release_trigger = _auto_trigger_release_pool_if_due()

    # 2026-07-13 (boss msg 660): if the release we just attempted was due, had drafts
    # to choose from, and still released nothing, the pool is gate-deadlocked. Run
    # this AFTER the release attempt (so we judge the real outcome, not a prediction)
    # and BEFORE the report, so the alert can say what was already done instead of
    # asking the boss to go write an article.
    deadlock_remediation = _auto_remediate_release_deadlock()

    # 2026-07-03 (boss email-12559): the 發文脫班 (publishing_freshness) dead-man
    # switch must DIRECTLY REMEDIATE, not email the boss a to-do list. Run the
    # single-owner remediation ladder (force-release → refill fresh topics)
    # BEFORE building/sending the alert, so a genuine drought self-heals and the
    # email (if it still fires) truthfully reports what the system already did.
    drought_remediation = _auto_remediate_publish_drought()

    # 2026-07-13 (boss msg 624): adopt finished-but-unregistered deliverables into
    # the pool before the alert fires, so a completed article is delivered rather
    # than surfaced as a discard/keep decision for the boss.
    orphan_reap = _auto_reap_orphan_deliverables()

    report = check_alert_conditions(storage_dir="storage")
    print("=== ops check-alerts ===")
    if due_summary.get("ok"):
        fired = due_summary.get("fired_count", 0)
        skipped = due_summary.get("skipped_count", 0)
        fired_ids = [j["job_id"] for j in due_summary.get("jobs", []) if j.get("action") == "fired"]
        print(f"  run-due-jobs: fired={fired} skipped={skipped} ids={fired_ids}")
    else:
        print(f"  run-due-jobs: error reason={due_summary.get('reason') or due_summary.get('error')}")

    # 2026-05-04 finding #18 / B3.7: piggy-back scheduler drift assertion
    _check_piggy_back_drift(due_summary)
    if release_trigger.get("triggered"):
        status = "ok" if release_trigger.get("ok") else "fail"
        print(
            f"  release-pool-auto: {status} "
            f"age={release_trigger.get('age_min')}min "
            f"reason={release_trigger.get('reason') or release_trigger.get('error') or 'done'}"
        )
    else:
        # 2026-04-19: Log skip state for debugging (piggy-back health check).
        print(
            f"  release-pool-auto: skip "
            f"reason={release_trigger.get('reason', 'unknown')}"
        )
    # 2026-07-13: release gate-deadlock auto-remediation (boss msg 660)
    if deadlock_remediation.get("attempted"):
        _task = deadlock_remediation.get("task_id") or deadlock_remediation.get("existing_task_id")
        print(
            f"  release-deadlock-remediation: draft={deadlock_remediation.get('draft')} "
            f"eligible=0 blocked={deadlock_remediation.get('blocked_clusters')} "
            f"required={deadlock_remediation.get('required_clusters')} task={_task}"
        )
    elif deadlock_remediation.get("error"):
        print(f"  release-deadlock-remediation: ERROR {deadlock_remediation['error']}")

    # 2026-07-03: publish-drought auto-remediation ladder (boss email-12559)
    if drought_remediation.get("attempted"):
        steps = drought_remediation.get("steps", [])
        step_summary = "; ".join(
            f"{s.get('step')}="
            f"{s.get('released', s.get('added', s.get('error', 'ok')))}"
            for s in steps
        )
        print(
            f"  publish-drought-remediation: attempted "
            f"gap={drought_remediation.get('gap_hours')}h [{step_summary}]"
        )
    else:
        print(
            f"  publish-drought-remediation: skip "
            f"reason={drought_remediation.get('reason', drought_remediation.get('error', 'unknown'))}"
        )
    # 2026-07-13: orphan deliverable adoption (boss msg 624 — 產出即交付)
    adopted = [a for a in (orphan_reap.get("adopted") or []) if a.get("adopted")]
    delivered_jobs = [
        item for item in (orphan_reap.get("job_deliveries") or [])
        if item.get("delivered")
    ]
    print(
        f"  orphan-reap: orphans={orphan_reap.get('orphan_count', '?')} "
        f"adopted={len(adopted)} held={len(orphan_reap.get('held') or [])} "
        f"job_deliveries={len(delivered_jobs)} "
        f"reason={orphan_reap.get('error') or orphan_reap.get('reason') or 'ok'}"
    )
    ci_push = (
        (ci_watch.get("push") or {}).get("outcome")
        or (ci_watch.get("push") or {}).get("reason")
        or "-"
    )
    print(
        f"  ci-watch: run={ci_watch.get('run_id')} "
        f"conclusion={ci_watch.get('conclusion')} "
        f"phase={ci_watch.get('phase') or '-'} "
        f"failure_cycles={ci_watch.get('failure_cycles', 0)} "
        f"task_added={ci_watch.get('task_added')} "
        f"notification={ci_watch.get('notification_kind') or '-'}:"
        f"{'delivered' if ci_watch.get('notification_delivered') else 'none'} "
        f"push={ci_push} "
        f"reason={ci_watch.get('reason') or 'ok'}"
    )
    print(
        f"breaches={report.get('breach_count')} "
        f"sent={report.get('sent_count')} "
        f"skipped={report.get('skipped_count')}"
    )
    for condition in report.get("conditions", []):
        flag = "BREACH" if condition.get("breached") else "ok"
        print(
            f"- [{flag}] {plainify_boss_text(condition.get('id'))} "
            f"level={condition.get('level')} title={plainify_boss_text(condition.get('title'))}"
        )
        if condition.get("breached") and condition.get("body"):
            for line in plainify_boss_text(condition["body"]).splitlines():
                print(f"    {line}")
    if report.get("alerts"):
        print("dispatched:")
        for entry in report["alerts"]:
            status = "sent" if entry.get("sent") else ("skipped" if entry.get("skipped") else "failed")
            print(
                f"  - {status}: level={entry.get('level')} title={plainify_boss_text(entry.get('title'))} "
                f"notif_id={entry.get('notification_id')} reason={entry.get('skip_reason') or entry.get('send_error') or 'ok'}"
            )
    # Print compact JSON tail for log scrapers.
    summary = {
        "breach_count": report.get("breach_count"),
        "sent_count": report.get("sent_count"),
        "skipped_count": report.get("skipped_count"),
        "generated_at": report.get("generated_at"),
    }
    print("JSON: " + json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
