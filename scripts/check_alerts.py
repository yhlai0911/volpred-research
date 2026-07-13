"""Run all built-in ops alert checkers and dispatch deduped emails.

Hook points:
- Called at the end of `scripts/daily_update.py` so daily run prints alert state.
- Suitable for a host crontab hourly invocation:
    0 * * * * cd /path/to/volpred-research && uv run python scripts/check_alerts.py >> storage/logs/cron/check_alerts.log 2>&1

Behavior:
- 3 conditions: release_pool_gap (>2h since last release-pool fire),
  draft_pool_low (<4 drafts), host_cron_fail (scheduler stale or
  cron wrapper exit != 0).
- Dedup window 24h via storage/ops/alert_dedup.json (sha256(level + title)).
- Recipient defaults to alerts.ALERT_RECIPIENT (yihao.lai@gmail.com).

Exit code:
- 0 always (even on breach) — this is observability, not a gating step.
"""
from __future__ import annotations

import json
import sys
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
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"=== [release_pool] check_alerts fallback fire at {start_iso} ===\n")
        handle.write(f"=== [release_pool] exit {returncode} at {end_iso} (fallback) ===\n")

    state_path = PROJECT_ROOT / "storage" / "ops" / "cron_last_run.json"
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
# so main stayed red for 12+ hours with the ops loop blind to it. Poll the
# latest completed main-branch run every hourly tick; on failure, immediately
# append a P1 platform_ops repair task (deduped by run id) so the
# dispatch-supervisor's next tick dispatches the fix without the boss relaying
# anything. Enforcement owner for "CI is red" = this check (anti-stacking).
# ---------------------------------------------------------------------------
CI_WATCH_STATE = PROJECT_ROOT / "storage" / "ops" / "ci_watch_state.json"
CI_NEXT_TASKS = PROJECT_ROOT / "storage" / "next_tasks.json"
CI_WORKFLOW = "Test Suite"


def _gh_bin() -> str | None:
    import shutil

    found = shutil.which("gh")
    if found:
        return found
    brew_gh = Path("/opt/homebrew/bin/gh")  # cron env PATH omits homebrew
    return str(brew_gh) if brew_gh.exists() else None


def _ci_latest_completed_run() -> dict | None:
    """Latest completed main-branch Test Suite run via gh CLI; None on any failure."""
    import subprocess

    gh = _gh_bin()
    if gh is None:
        warn("ci_watch", "gh CLI not found; CI watchdog skipped")
        return None
    try:
        proc = subprocess.run(
            [gh, "run", "list", "--workflow", CI_WORKFLOW, "--branch", "main",
             "--status", "completed", "--limit", "1",
             "--json", "databaseId,conclusion,url,headSha,displayTitle,createdAt"],
            capture_output=True, text=True, timeout=60, cwd=str(PROJECT_ROOT),
        )
        if proc.returncode != 0:
            warn("ci_watch", "gh run list failed",
                 rc=proc.returncode, stderr_tail=(proc.stderr or "")[-200:])
            return None
        runs = json.loads(proc.stdout or "[]")
        return runs[0] if isinstance(runs, list) and runs else None
    except Exception as exc:  # noqa: BLE001
        warn("ci_watch", "gh run list error", err=str(exc))
        return None


def _append_next_task_locked(task: dict, next_tasks_path: Path) -> bool:
    """flock-append one task to the pending queue (same discipline as refill scripts)."""
    import fcntl

    from volpred.ops.next_tasks import normalize_task_priorities, normalize_task_priority

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
            normalize_task_priorities(data)
            fh.seek(0)
            fh.truncate()
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            return True
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _build_ci_repair_task(run: dict, *, now_iso: str) -> dict:
    run_id = run.get("databaseId")
    url = run.get("url") or f"https://github.com/yhlai0911/volpred-research/actions/runs/{run_id}"
    sha = (run.get("headSha") or "")[:9]
    return {
        "id": f"ci-red-{run_id}",
        "task_type": "platform_ops",
        "priority": 1,
        "source": "auto_discovered",
        "status": "pending",
        "created_at": now_iso,
        "title": f"CI 紅燈修復（run {run_id}）— main Test Suite 最新班次 failure",
        "description": (
            f"GitHub Actions Test Suite 於 main 最新完成班次 failure。\n"
            f"Run: {url}\nhead_sha: {sha}\n\n"
            "行動（當班修到綠，不許只報告）：\n"
            f"1. `gh run view {run_id} --log-failed | tail -300` 讀失敗測試與根因\n"
            "2. 本地重現 → 修根因；同類站點做 class sweep"
            "（per feedback_declare_complete_requires_class_sweep），禁 surface patch\n"
            "3. 卡住即改派 `codex exec`（gpt-5.6-sol ultra）做獨立診斷/第二實作，"
            "不等下一班（老闆指示：強模型直接嘗試）\n"
            "4. commit + push 後 `gh run watch` 盯到綠燈才 finish\n"
            "成功標準：main 最新 Test Suite run conclusion=success。"
        ),
    }


def _handle_ci_run(
    run: dict,
    *,
    now_iso: str,
    next_tasks_path: Path = CI_NEXT_TASKS,
    state_path: Path = CI_WATCH_STATE,
    sender=None,
) -> dict:
    """Pure decision core (injectable for tests): red run → P1 task + critical alert."""
    run_id = run.get("databaseId")
    conclusion = (run.get("conclusion") or "").lower()
    summary = {
        "checked": True, "run_id": run_id, "conclusion": conclusion,
        "task_added": False, "alert_sent": False,
    }
    state = _load_json_dict(state_path, label="ci_watch_state")
    if conclusion != "failure":
        # success / cancelled / skipped — record recovery, nothing to remediate.
        state.update({"last_seen_run_id": run_id, "last_seen_conclusion": conclusion,
                      "checked_at": now_iso})
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    task = _build_ci_repair_task(run, now_iso=now_iso)
    if state.get("last_task_id") == task["id"]:
        summary["reason"] = "already_handled"
        return summary
    try:
        summary["task_added"] = _append_next_task_locked(task, next_tasks_path)
    except Exception as exc:  # noqa: BLE001
        warn("ci_watch", "P1 repair task append failed", err=str(exc), task_id=task["id"])
        summary["reason"] = f"append_failed: {exc}"
        return summary

    if sender is None:
        from volpred.ops.alerts import send_alert as sender  # noqa: WPS433
    body = (
        "## 觸發條件\n"
        f"main 最新 Test Suite run failure：{run.get('url')}（head {(run.get('headSha') or '')[:9]}）。\n\n"
        "## 影響\n"
        "CI 紅 = 之後所有 push 失去回歸保護；紅燈只有老闆看得到 = 巡檢缺口。\n\n"
        "## 系統已自動執行\n"
        f"已建 P1 修復任務 {task['id']}（pending queue 隊首），dispatch-supervisor 下一 tick 即派工；"
        "任務含失敗 log 取得步驟與 codex(gpt-5.6-sol) 第二實作路徑。無需老闆行動。"
    )
    try:
        sent = sender("critical", f"CI 紅燈（run {run_id}）→ 已自動建 P1 修復任務", body,
                      storage_dir=str(PROJECT_ROOT / "storage"))
        summary["alert_sent"] = bool(sent.get("sent")) if isinstance(sent, dict) else True
    except Exception as exc:  # noqa: BLE001
        warn("ci_watch", "alert send failed (task still queued)", err=str(exc))

    state.update({"last_seen_run_id": run_id, "last_seen_conclusion": conclusion,
                  "last_task_id": task["id"], "checked_at": now_iso})
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _auto_remediate_ci_red() -> dict:
    from datetime import timezone

    run = _ci_latest_completed_run()
    if run is None:
        return {"checked": False, "reason": "gh_unavailable_or_no_runs"}
    return _handle_ci_run(run, now_iso=datetime.now(timezone.utc).isoformat())


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

    # 2026-07-13 (boss msgs 632-653): CI red must become a P1 repair task the
    # hour it happens, not when the boss forwards the GitHub notification.
    ci_watch = _auto_remediate_ci_red()

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
    print(
        f"  ci-watch: run={ci_watch.get('run_id')} "
        f"conclusion={ci_watch.get('conclusion')} "
        f"task_added={ci_watch.get('task_added')} "
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
