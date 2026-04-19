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
    # extra hour, making 120-min interval behave as 180-min. Allow 3-min slack
    # so hourly checks at the interval boundary fire the release instead of
    # deferring to the next hourly check.
    if age_min < interval_min - 3:
        return {"triggered": False, "reason": f"interval_not_due_age={age_min:.0f}min"}

    # Due: attempt release via CLI. Use non-blocking subprocess to avoid
    # any hang in hourly cron; limit runtime; don't fail alert run if this fails.
    try:
        result = subprocess.run(
            ["/opt/homebrew/bin/uv", "run", "volpred", "ops", "release-pool-by-settings"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        ok = result.returncode == 0
        return {
            "triggered": True,
            "ok": ok,
            "returncode": result.returncode,
            "age_min": round(age_min),
            "stdout_tail": (result.stdout or "")[-200:],
            "stderr_tail": (result.stderr or "")[-200:],
        }
    except Exception as exc:
        return {"triggered": True, "ok": False, "error": str(exc)}


def main() -> int:
    from volpred.ops import check_alert_conditions  # noqa: WPS433 (deferred for sys.path)

    # 2026-04-19 auto-remediation piggy-back: host cron for release_pool is
    # unreliable; check_alerts runs hourly and reliably, so trigger release
    # here when interval_minutes threshold is exceeded.
    release_trigger = _auto_trigger_release_pool_if_due()

    report = check_alert_conditions(storage_dir="storage")
    print("=== ops check-alerts ===")
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
