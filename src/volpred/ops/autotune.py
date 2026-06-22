"""Pacing / rules autotune — let supervisor rewrite `config/supervisor_rules.json`
based on actual 7-day throughput data from `build_supervisor_snapshot()`.

Self-improvement mechanism: if a family consistently under-fires (actual <<
floor for multiple windows), lower its floor; if a family over-fires past
its cap, raise the cap. Keeps a history trail in the config itself so
operators can see drift over time.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .supervisor import build_supervisor_snapshot, load_supervisor_rules


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _warn_autotune(message: str, *, family: str, value: Any, exc: Exception) -> None:
    print(
        "[autotune] WARN "
        f"{message} family={family!r} value={value!r} "
        f"error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


def autotune_supervisor_rules(
    *,
    days: int = 7,
    storage_dir: str = "storage",
    rules_path: str = "config/supervisor_rules.json",
    dry_run: bool = False,
    aggressiveness: float = 0.3,
) -> dict[str, Any]:
    """Adjust family_minimums floors/caps based on recent throughput.

    Strategy:
      - If actual < 50% of floor for the window → lower floor by `aggressiveness
        * gap`, clamp to [0, current_floor].
      - If actual > 90% of cap → raise cap by `aggressiveness * (actual - cap)`,
        clamp to [current_cap, current_cap + 10].
      - Write changes back to `config/supervisor_rules.json` atomically,
        append to `_autotune.history` with timestamp + rationale.

    Returns diff report: which floors/caps changed, why, and what the new
    config looks like. Writes immediately so next supervisor tick uses
    updated rules without session restart.
    """
    snapshot = build_supervisor_snapshot(
        days=days, storage_dir=storage_dir, rules_path=rules_path
    )
    rules = load_supervisor_rules(rules_path)
    if not rules:
        return {
            "ok": False,
            "error": "supervisor_rules.json missing or unreadable",
            "rules_path": rules_path,
        }

    family_rules = rules.setdefault("family_minimums", {})
    floors = family_rules.setdefault("floors", {})
    caps = family_rules.setdefault("weekly_caps", {})
    activity = snapshot["task_activity"]["by_family"]

    floor_changes: list[dict[str, Any]] = []
    cap_changes: list[dict[str, Any]] = []

    for family, current_floor in list(floors.items()):
        if family.startswith("_"):
            continue
        try:
            floor_int = int(current_floor)
        except (TypeError, ValueError) as exc:
            _warn_autotune(
                "family floor parse failed; skipping",
                family=family,
                value=current_floor,
                exc=exc,
            )
            continue
        actual = int(activity.get(family, 0))
        if floor_int <= 0:
            continue
        if actual < floor_int * 0.5:
            gap = floor_int - actual
            reduction = max(1, int(round(aggressiveness * gap)))
            new_floor = _clamp(floor_int - reduction, 0, floor_int)
            if new_floor != floor_int:
                floors[family] = new_floor
                floor_changes.append(
                    {
                        "family": family,
                        "old_floor": floor_int,
                        "new_floor": new_floor,
                        "actual": actual,
                        "rationale": f"actual({actual}) < 50% of floor({floor_int}); lowered by {reduction}",
                    }
                )

    for family, current_cap in list(caps.items()):
        if family.startswith("_"):
            continue
        try:
            cap_int = int(current_cap)
        except (TypeError, ValueError) as exc:
            _warn_autotune(
                "family weekly cap parse failed; skipping",
                family=family,
                value=current_cap,
                exc=exc,
            )
            continue
        if cap_int <= 0:
            continue
        family_actual = int(activity.get(family, 0))
        actual = family_actual
        if actual > cap_int * 0.9:
            excess = max(1, actual - cap_int)
            increase = max(1, int(round(aggressiveness * excess)))
            new_cap = _clamp(cap_int + increase, cap_int, cap_int + 10)
            if new_cap != cap_int:
                caps[family] = new_cap
                cap_changes.append(
                    {
                        "family": family,
                        "old_cap": cap_int,
                        "new_cap": new_cap,
                        "actual": actual,
                        "rationale": f"actual({actual}) >= 90% of cap({cap_int}); raised by {increase}",
                    }
                )

    autotune_meta = rules.setdefault("_autotune", {})
    autotune_meta["last_run_at"] = _utc_now_iso()
    autotune_meta["last_run_notes"] = (
        f"days={days}, floor_changes={len(floor_changes)}, cap_changes={len(cap_changes)}"
    )
    history = autotune_meta.setdefault("history", [])
    if floor_changes or cap_changes:
        history.append(
            {
                "timestamp": _utc_now_iso(),
                "days_window": days,
                "floor_changes": floor_changes,
                "cap_changes": cap_changes,
            }
        )
        # Keep last 50 history entries
        if len(history) > 50:
            del history[:-50]

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "rules_path": rules_path,
            "floor_changes": floor_changes,
            "cap_changes": cap_changes,
            "no_changes": not (floor_changes or cap_changes),
        }

    if floor_changes or cap_changes:
        rules_path_obj = Path(rules_path)
        tmp = rules_path_obj.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(rules_path_obj)
        written = True
    else:
        written = False

    return {
        "ok": True,
        "dry_run": False,
        "written": written,
        "rules_path": rules_path,
        "floor_changes": floor_changes,
        "cap_changes": cap_changes,
        "no_changes": not (floor_changes or cap_changes),
        "snapshot_summary": {
            "window_days": days,
            "by_family": activity,
            "deficit": snapshot["family_coverage_deficit"]["families_below_floor"],
        },
    }
