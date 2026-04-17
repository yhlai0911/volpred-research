from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .runtime import get_project_root

RUNTIME_SCHEDULES_PATH = get_project_root() / "config" / "runtime_schedules.json"


def get_runtime_schedules_path() -> Path:
    return RUNTIME_SCHEDULES_PATH


@lru_cache(maxsize=1)
def load_runtime_schedules() -> dict[str, Any]:
    if not RUNTIME_SCHEDULES_PATH.exists():
        raise RuntimeError(f"Missing runtime schedules config: {RUNTIME_SCHEDULES_PATH}")

    data = json.loads(RUNTIME_SCHEDULES_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid runtime schedules config: {RUNTIME_SCHEDULES_PATH}")

    required_sections = ("metadata", "system_crontab", "remote_triggers", "session_crons")
    missing = [name for name in required_sections if name not in data]
    if missing:
        raise RuntimeError(
            f"runtime_schedules.json is missing required sections: {', '.join(missing)}"
        )
    return data


def get_schedule_section(name: str) -> dict[str, Any]:
    section = load_runtime_schedules().get(name)
    if not isinstance(section, dict):
        raise RuntimeError(f"runtime_schedules.json section '{name}' must be an object")
    return section


def get_schedule_items(name: str) -> list[dict[str, Any]]:
    items = get_schedule_section(name).get("items")
    if not isinstance(items, list):
        raise RuntimeError(f"runtime_schedules.json section '{name}.items' must be a list")
    return [item for item in items if isinstance(item, dict)]
