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


def main() -> int:
    from volpred.ops import check_alert_conditions  # noqa: WPS433 (deferred for sys.path)

    report = check_alert_conditions(storage_dir="storage")
    print("=== ops check-alerts ===")
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
