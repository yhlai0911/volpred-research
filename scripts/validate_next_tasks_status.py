#!/usr/bin/env python3
"""CI invariant: out-of-vocab task-status count in next_tasks.json must not
exceed the 2026-07 baseline (27 legacy rows).

Usage:
    uv run python scripts/validate_next_tasks_status.py [--path PATH] [--baseline N]

Exit codes:
    0 = OK (count <= baseline)
    1 = REGRESSION (count > baseline)
    2 = file missing / unreadable

Background:
- The canonical status vocabulary lives in src/volpred/ops/next_tasks.py
  (TASK_STATUSES). Writers route through write_tasks_to_handle there, so new
  rows carry an in-vocab status.
- 27 pre-existing out-of-vocab rows (completed x11, superseded_audience_null_fix
  x5, partially_completed x2, plus a one-off tail) are frozen as the baseline:
  they predate the vocabulary and must not be rewritten (永遠修流程，不修資料).
- A baseline OVERFLOW means someone bypassed the Python writer with a jq/Edit
  hand-write and introduced a new out-of-vocab status. This script is the
  mechanical stop that catches those hand-edits, mirroring
  scripts/validate_knowledge_provenance.py's provenance baseline gate.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_PATH = ROOT / "storage" / "next_tasks.json"
DEFAULT_BASELINE = 27


def _light_load_vocab():
    """Load TASK_STATUSES/is_valid_status without executing volpred.ops.__init__.

    volpred.ops.__init__ transitively imports yaml/pandas (via publisher and
    topic_clusters), which are absent on the deps-free provenance CI runner.
    Register lightweight namespace stubs so next_tasks.py's `from .diagnostics
    import warn` still resolves to the real stdlib-only sibling module. Same
    light-import property that lets validate_knowledge_provenance.py import
    volpred.memory.provenance plainly.
    """
    for name, path in (("volpred", ROOT / "src" / "volpred"), ("volpred.ops", ROOT / "src" / "volpred" / "ops")):
        if name not in sys.modules:
            stub = types.ModuleType(name)
            stub.__path__ = [str(path)]
            sys.modules[name] = stub
    mod = importlib.import_module("volpred.ops.next_tasks")
    return mod.TASK_STATUSES, mod.is_valid_status


try:
    from volpred.ops.next_tasks import TASK_STATUSES, is_valid_status  # noqa: F401
except ModuleNotFoundError as exc:
    # Observable (not silent): ops deps absent on the deps-free CI runner, fall
    # back to the light import that bypasses the heavy package __init__.
    print(f"[validate-next-tasks-status] light-load (ops deps absent: {exc})", file=sys.stderr)
    TASK_STATUSES, is_valid_status = _light_load_vocab()


def count_out_of_vocab(tasks: list) -> int:
    """Count rows carrying a status that is not in TASK_STATUSES."""
    n = 0
    for task in tasks:
        if not isinstance(task, dict):
            continue
        status = task.get("status")
        if status is not None and not is_valid_status(status):
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", default=str(DEFAULT_PATH))
    ap.add_argument(
        "--baseline",
        type=int,
        default=DEFAULT_BASELINE,
        help=f"Max tolerated out-of-vocab count (default: {DEFAULT_BASELINE})",
    )
    ap.add_argument("--verbose", action="store_true", help="Print sample violating (id, status) pairs")
    args = ap.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"[validate-next-tasks-status] FAIL: {path} not found", file=sys.stderr)
        return 2

    try:
        with open(path, encoding="utf-8") as f:
            tasks = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[validate-next-tasks-status] FAIL: cannot parse {path}: {exc}", file=sys.stderr)
        return 2

    if not isinstance(tasks, list):
        print(f"[validate-next-tasks-status] FAIL: {path} is not a list", file=sys.stderr)
        return 2

    n = count_out_of_vocab(tasks)
    total = len(tasks)
    msg = (
        f"[validate-next-tasks-status] next_tasks.json: {n}/{total} out-of-vocab "
        f"statuses (baseline={args.baseline})"
    )

    if n > args.baseline:
        print(msg + "  -> REGRESSION", file=sys.stderr)
        print(
            "[validate-next-tasks-status] New out-of-vocab status introduced since "
            "the 2026-07 baseline. Likely a jq/Edit hand-write bypassed the Python "
            "writer (write_tasks_to_handle in src/volpred/ops/next_tasks.py).",
            file=sys.stderr,
        )
        if args.verbose:
            bad = [
                (t.get("id") or t.get("task_id") or "?", t.get("status"))
                for t in tasks
                if isinstance(t, dict)
                and t.get("status") is not None
                and not is_valid_status(t.get("status"))
            ]
            print(f"[validate-next-tasks-status] sample: {bad[:10]}", file=sys.stderr)
        return 1

    print(msg + "  -> OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
