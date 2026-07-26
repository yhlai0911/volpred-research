#!/usr/bin/env python3
"""Check monthly NDC freshness and materialize work only when admission is open.

During Operations Core direct-execution cutovers the legacy ``next_tasks`` queue
is intentionally closed to new identities.  A stale indicator must therefore
fail visibly instead of bypassing the gate or returning a false-success receipt.
The operator can register the work in the active control plane (GitHub Issues)
and execute it directly; queued mode keeps the deterministic legacy hand-off.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from volpred.ops.next_tasks import append_task_record
from volpred.ops.summaries import build_ndc_indicator_maintenance
from volpred.ops.task_pool_mode import TaskPoolAdmissionClosed

ROOT = Path(__file__).resolve().parents[1]


def run(
    *,
    storage_dir: str = "storage",
    next_tasks_path: Path = ROOT / "storage" / "next_tasks.json",
) -> dict[str, Any]:
    check = build_ndc_indicator_maintenance(storage_dir=storage_dir)
    if check.get("skip"):
        return {
            "ok": True,
            "action": "skip",
            "reason": check.get("reason"),
            "expected_period": check.get("expected_period"),
            "task_created": False,
        }

    expected = str(check.get("expected_period") or "unknown")
    task_id = f"ndc_indicator_refresh_{expected.lower()}"
    stale_series = [
        str(value) for value in (check.get("stale_series") or []) if value
    ]
    commands = [
        str(value) for value in (check.get("followup_commands") or []) if value
    ]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record = {
        "id": task_id,
        "title": f"NDC 景氣指標更新：補齊 {expected} canonical CSV",
        "description": (
            "Operations Core 月度 freshness gate 判定 NDC canonical CSV 落後。"
            f" stale_series={stale_series}; 先執行 check，再依既有收集流程更新並回讀："
            f" {'; '.join(commands)}"
        ),
        "task_type": "platform_ops",
        "priority": 3,
        "status": "pending",
        "dispatch_lane": "agent",
        "source": "operations_core_ndc_indicator_schedule",
        "tags": ["scheduled", "ndc-indicator", "data-freshness"],
        "created_at": now,
        "schedule_fire_key": os.environ.get("VOLPRED_SCHEDULE_FIRE_KEY"),
        "expected_period": expected,
        "stale_series": stale_series,
        "followup_commands": commands,
    }
    try:
        persisted, created = append_task_record(
            record,
            path=next_tasks_path,
            if_exists="skip",
            semantic_dedupe=False,
        )
    except TaskPoolAdmissionClosed as exc:
        return {
            "ok": False,
            "action": "blocked_direct_execution",
            "reason": str(exc),
            "expected_period": expected,
            "task_created": False,
            "task_id": task_id,
            "stale_series": stale_series,
            "followup_commands": commands,
            "operator_action": (
                "Register or update a GitHub Issue, then execute the NDC refresh "
                "directly; do not reopen or bypass legacy task-pool admission."
            ),
        }
    return {
        "ok": True,
        "action": "materialize" if created else "already_materialized",
        "reason": check.get("reason"),
        "expected_period": expected,
        "task_created": created,
        "task_id": persisted.get("id"),
        "stale_series": stale_series,
    }


def main() -> int:
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
