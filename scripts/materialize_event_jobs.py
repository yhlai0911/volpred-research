#!/usr/bin/env python3
"""Materialize due event windows through the canonical event-jobs owner."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from volpred.ops.event_jobs import expand_due_event_jobs

ROOT = Path(__file__).resolve().parents[1]
STRUCTURAL_FAILURE_REASONS = frozenset(
    {
        "missing_id",
        "missing_dedupe_key",
        "missing_deadline",
        "invalid_deadline",
        "invalid_event_window",
    }
)


def run(*, storage_dir: Path = ROOT / "storage") -> dict[str, Any]:
    result = expand_due_event_jobs(storage_dir=str(storage_dir))
    structural_failures = [
        item
        for item in result.get("skipped", [])
        if isinstance(item, dict)
        and str(item.get("reason") or "") in STRUCTURAL_FAILURE_REASONS
    ]
    return {
        "ok": not structural_failures,
        "owner": "operations_core",
        "created_count": len(result.get("created") or []),
        "structural_failures": structural_failures,
        "result": result,
    }


def main() -> int:
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
