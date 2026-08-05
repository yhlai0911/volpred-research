#!/usr/bin/env python3
"""Dept routing projection: live (model, effort) per department task_type.

RUNTIME PROJECTION, not stored config. The org layer must never persist a
model/effort snapshot (CLAUDE.md 全量架構 gate): departments own task_types in
storage/org/registry.json; the canonical (model, effort) map lives in
scripts/model_router.py (owner) under config/models.json's all-opus subagent
policy. This module joins the two at call time so org surfaces (org_status,
cockpit, manager_tick) can display routing without creating a second
drift-prone mapping.

  uv run python scripts/org/dept_routing.py [--json] [--dept NAME]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _core import DEFAULT_ORG_ROOT, load_registry  # noqa: E402
from model_router import (  # noqa: E402
    TASK_TYPE_TO_MODEL,
    normalize_task_type_value,
    pick_model,
)

ROUTING_SOURCES = {
    "registry": "storage/org/registry.json (owned_task_types)",
    "mapping": "scripts/model_router.py:TASK_TYPE_TO_MODEL",
    "policy": "config/models.json subagent_policy (all-opus; effort varies)",
}


def resolve_dept_routing(registry: dict) -> dict:
    """Join registry departments with model_router's canonical mapping.

    Returns {"sources": ..., "departments": {name: {title, task_routing}}}.
    task_routing rows carry mapped=False when the task_type is unknown to
    model_router (falls back to its DEFAULT) so drift between the registry
    and the canonical table is visible instead of silently absorbed.
    """
    departments: dict[str, dict] = {}
    for name, meta in sorted(registry.get("departments", {}).items()):
        if meta.get("status") == "retired":
            continue
        rows: dict[str, dict] = {}
        for task_type in meta.get("owned_task_types", []):
            normalized = normalize_task_type_value(task_type)
            model, effort = pick_model(task_type)
            rows[task_type] = {
                "model": model,
                "effort": effort,
                "mapped": bool(normalized and normalized in TASK_TYPE_TO_MODEL),
            }
        entry: dict = {"title": meta.get("title"), "task_routing": rows}
        entry["session"] = session_routing(rows)
        if not rows:
            entry["note"] = (
                "no owned task_types — dept work runs via scripts/cron, "
                "not routed subagents"
            )
        departments[name] = entry
    return {"sources": ROUTING_SOURCES, "departments": departments}


# Ordered weakest → strongest so a session can be staffed for its hardest work.
EFFORT_LADDER = ("low", "medium", "high", "xhigh", "max")


def session_routing(rows: dict) -> dict:
    """(model, effort) for a whole long-lived department session.

    A task_type maps to one effort, but a cockpit pane is a single session that
    outlives any one work item and cannot downshift mid-flight. It is therefore
    staffed at the CEILING of the work it owns: running an xhigh experiment at
    low effort produces bad research (mission 2), while running a lookup at
    xhigh only costs tokens. Cost stays visible — resource_monitor audits it.
    """
    if not rows:
        model, effort = pick_model(None)
        return {"model": model, "effort": effort, "basis": "router default (no owned task_types)"}

    models = sorted({r["model"] for r in rows.values()})
    ceiling = max(
        rows.values(),
        key=lambda r: EFFORT_LADDER.index(r["effort"]) if r["effort"] in EFFORT_LADDER else -1,
    )
    driver = next(tt for tt, r in rows.items() if r["effort"] == ceiling["effort"])
    routing = {
        "model": models[0],
        "effort": ceiling["effort"],
        "basis": f"ceiling of owned task_types (driven by {driver})",
    }
    if len(models) > 1:
        # Surfacing beats silently picking one: a department spanning two models
        # cannot be one session, and that is a registry problem to fix.
        routing["conflict"] = f"owned task_types span multiple models: {', '.join(models)}"
    return routing


def format_text(projection: dict) -> str:
    lines = ["dept routing (live projection — canonical map: scripts/model_router.py)"]
    for name, entry in projection["departments"].items():
        s = entry.get("session") or {}
        session_note = f"  → session {s.get('model')}/{s.get('effort')}" if s else ""
        lines.append(f"  {name:<18} {entry.get('title') or ''}{session_note}")
        if s.get("conflict"):
            lines.append(f"    ⚠️ {s['conflict']}")
        rows = entry["task_routing"]
        if not rows:
            lines.append(f"    (no owned task_types) {entry.get('note', '')}".rstrip())
            continue
        for task_type, row in rows.items():
            flag = "" if row["mapped"] else "  [UNMAPPED → router default]"
            lines.append(
                f"    {task_type:<20} {row['model']}/{row['effort']}{flag}"
            )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ORG_ROOT)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--dept", help="limit output to one department")
    args = parser.parse_args()

    projection = resolve_dept_routing(load_registry(args.root))
    if args.dept:
        if args.dept not in projection["departments"]:
            print(f"unknown or retired department: {args.dept}", file=sys.stderr)
            return 1
        projection["departments"] = {args.dept: projection["departments"][args.dept]}

    if args.as_json:
        print(json.dumps(projection, ensure_ascii=False, indent=2))
    else:
        print(format_text(projection))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
