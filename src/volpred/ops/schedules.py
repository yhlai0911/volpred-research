from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from typing import Any

from volpred.config import get_runtime_schedules_path, load_runtime_schedules


def _parse_crontab(raw: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for line in raw.splitlines():
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue
        parts = trimmed.split()
        if len(parts) < 6:
            continue
        items.append(
            {
                "cron": " ".join(parts[:5]),
                "command": " ".join(parts[5:]),
                "raw": trimmed,
            }
        )
    return items


def read_system_crontab() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            check=True,
            capture_output=True,
            text=True,
        )
        raw = f"{result.stdout}{result.stderr}".strip()
        return {
            "available": True,
            "items": _parse_crontab(raw),
            "note": "Live `crontab -l` read succeeded.",
        }
    except Exception as exc:
        return {
            "available": False,
            "items": [],
            "note": f"Unable to read live `crontab -l`: {exc}",
        }


def build_schedule_report() -> dict[str, Any]:
    config = load_runtime_schedules()
    system_spec_items = config.get("system_crontab", {}).get("items", [])
    session_items = config.get("session_crons", {}).get("items", [])
    remote_items = config.get("remote_triggers", {}).get("items", [])
    live = read_system_crontab()

    matched: list[str] = []
    missing: list[str] = []
    for item in system_spec_items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("id") or "unknown")
        matchers = item.get("matchers") or []
        if not isinstance(matchers, list):
            matchers = []
        has_match = any(
            any(str(matcher) in crontab_item.get("command", "") for matcher in matchers)
            for crontab_item in live["items"]
        )
        if has_match:
            matched.append(label)
        else:
            missing.append(label)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "canonical_path": str(get_runtime_schedules_path()),
        "session_cron_count": len(session_items),
        "remote_trigger_count": len(remote_items),
        "expected_system_task_count": len(system_spec_items),
        "matched_system_tasks": matched,
        "missing_system_tasks": missing,
        "live_system_crontab_available": live["available"],
        "live_system_crontab_count": len(live["items"]),
        "live_system_crontab_note": live["note"],
        "system_crontab_items": live["items"],
    }
