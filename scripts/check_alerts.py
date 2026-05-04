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
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
# Allow importing sibling script `run_due_jobs.py` (universal scheduler).
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


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
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    except Exception:
        state = {}
    if not isinstance(state, dict):
        state = {}
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


def _check_piggy_back_drift(due_summary: dict) -> dict:
    """Detect piggy-back scheduler health drift (B3.7 / finding #18).

    Signals:
    - run_due_jobs returned ok=False (croniter / config / import error)
    - any wrapper_script reported missing
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

    # Stale last_run check
    state_path = PROJECT_ROOT / "storage" / "ops" / "cron_last_run.json"
    config_path = PROJECT_ROOT / "config" / "runtime_schedules.json"
    try:
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        config = json.loads(config_path.read_text()) if config_path.exists() else {}
    except Exception:
        state = {}
        config = {}

    items = (config.get("system_crontab") or {}).get("items") or []
    now = datetime.now(timezone.utc)
    period_map = {
        "0 * * * *": 60,
        "0 */2 * * *": 120,
        "3 */2 * * *": 120,
        "0 */6 * * *": 360,
        "17 */6 * * *": 360,
        "0 0 * * *": 1440,
        "30 5 * * *": 1440,
    }
    for item in items:
        job_id = item.get("id")
        cron = item.get("cron")
        if item.get("host_crontab_managed") is False:
            continue
        if job_id in {"check_alerts"}:
            continue
        last_iso = state.get(job_id)
        if not last_iso:
            continue
        try:
            last_dt = datetime.fromisoformat(str(last_iso).replace("Z", "+00:00"))
        except Exception:
            continue
        period_min = period_map.get(cron)
        if period_min is None:
            continue
        age_min = (now - last_dt).total_seconds() / 60
        if age_min > 2 * period_min:
            drifts.append(
                f"stale_last_run: {job_id} age={age_min:.0f}min period={period_min}min"
            )

    if drifts:
        print("  piggy-back-drift:")
        for entry in drifts:
            print(f"    - {entry}")
    else:
        print("  piggy-back-drift: none")
    return {"drift_count": len(drifts), "drifts": drifts}


def main() -> int:
    from volpred.ops import check_alert_conditions  # noqa: WPS433 (deferred for sys.path)

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
    print(
        f"breaches={report.get('breach_count')} "
        f"sent={report.get('sent_count')} "
        f"skipped={report.get('skipped_count')}"
    )
    for condition in report.get("conditions", []):
        flag = "BREACH" if condition.get("breached") else "ok"
        print(
            f"- [{flag}] {condition.get('id')} "
            f"level={condition.get('level')} title={condition.get('title')}"
        )
        if condition.get("breached") and condition.get("body"):
            for line in str(condition["body"]).splitlines():
                print(f"    {line}")
    if report.get("alerts"):
        print("dispatched:")
        for entry in report["alerts"]:
            status = "sent" if entry.get("sent") else ("skipped" if entry.get("skipped") else "failed")
            print(
                f"  - {status}: level={entry.get('level')} title={entry.get('title')} "
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
