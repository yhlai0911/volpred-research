#!/usr/bin/env python3
"""CI invariant: out-of-vocab task-status AND blocked_reason counts in
next_tasks.json must not exceed their frozen baselines.

Usage:
    uv run python scripts/validate_next_tasks_status.py \
        [--path PATH] [--baseline N] [--blocked-reason-baseline M]

Exit codes:
    0 = OK (both counts <= their baselines)
    1 = REGRESSION (either count > its baseline)
    2 = file missing / unreadable

Background:
- The canonical status vocabulary lives in src/volpred/ops/next_tasks.py
  (TASK_STATUSES); the canonical blocked_reason vocabulary in
  src/volpred/ops/blocked_reasons.py (BLOCKED_REASONS). Writers route through
  write_tasks_to_handle there, so new rows carry in-vocab values.
- 27 pre-existing out-of-vocab status rows and 3 out-of-vocab blocked_reason
  rows were frozen as baselines. The one-time scripts/migrate_status_vocab.py
  (WS-A3) maps them back to the controlled vocab (originals preserved in
  status_original / blocked_reason_original); its --update-baselines step drops
  both baselines here to the post-migration residue (target 0).
- A baseline OVERFLOW means someone bypassed the Python writer with a jq/Edit
  hand-write and introduced a new out-of-vocab value. This script is the
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
DEFAULT_BASELINE = 0
DEFAULT_BLOCKED_REASON_BASELINE = 0


def _light_load_vocab():
    """Load the vocab validators without executing volpred.ops.__init__.

    volpred.ops.__init__ transitively imports yaml/pandas (via publisher and
    topic_clusters), which are absent on the deps-free provenance CI runner.
    Register lightweight namespace stubs so next_tasks.py's `from .diagnostics
    import warn` / `from .blocked_reasons import ...` still resolve to the real
    stdlib-only sibling modules. Same light-import property that lets
    validate_knowledge_provenance.py import volpred.memory.provenance plainly.
    """
    for name, path in (("volpred", ROOT / "src" / "volpred"), ("volpred.ops", ROOT / "src" / "volpred" / "ops")):
        if name not in sys.modules:
            stub = types.ModuleType(name)
            stub.__path__ = [str(path)]
            sys.modules[name] = stub
    mod = importlib.import_module("volpred.ops.next_tasks")
    return (
        mod.TASK_STATUSES,
        mod.is_valid_status,
        mod.is_valid_blocked_reason,
        mod.read_tasks_locked,
    )


try:
    from volpred.ops.next_tasks import (  # noqa: F401
        TASK_STATUSES,
        is_valid_blocked_reason,
        is_valid_status,
        read_tasks_locked,
    )
except ModuleNotFoundError as exc:
    # Observable (not silent): ops deps absent on the deps-free CI runner, fall
    # back to the light import that bypasses the heavy package __init__.
    print(f"[validate-next-tasks-status] light-load (ops deps absent: {exc})", file=sys.stderr)
    (
        TASK_STATUSES,
        is_valid_status,
        is_valid_blocked_reason,
        read_tasks_locked,
    ) = _light_load_vocab()


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


def count_out_of_vocab_blocked_reasons(tasks: list) -> int:
    """Count rows carrying a set blocked_reason that is not in BLOCKED_REASONS.

    The field is audited wherever it is set (terminal rows keep it as audit
    trail after review-gate release), so pollution cannot hide behind a status
    flip. ``blocked_reason_original`` (migration preservation field) is a
    different key and deliberately not counted.
    """
    n = 0
    for task in tasks:
        if not isinstance(task, dict):
            continue
        reason = task.get("blocked_reason")
        if reason is None:
            continue
        if not isinstance(reason, str):
            n += 1  # non-string value is never in-vocab
            continue
        if not reason.strip():
            continue  # empty string == absent
        if not is_valid_blocked_reason(reason):
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--path", default=str(DEFAULT_PATH))
    ap.add_argument(
        "--baseline",
        type=int,
        default=DEFAULT_BASELINE,
        help=f"Max tolerated out-of-vocab status count (default: {DEFAULT_BASELINE})",
    )
    ap.add_argument(
        "--blocked-reason-baseline",
        type=int,
        default=DEFAULT_BLOCKED_REASON_BASELINE,
        help=(
            "Max tolerated out-of-vocab blocked_reason count "
            f"(default: {DEFAULT_BLOCKED_REASON_BASELINE})"
        ),
    )
    ap.add_argument("--verbose", action="store_true", help="Print sample violating (id, status) pairs")
    args = ap.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"[validate-next-tasks-status] FAIL: {path} not found", file=sys.stderr)
        return 2

    try:
        tasks = read_tasks_locked(path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"[validate-next-tasks-status] FAIL: cannot parse {path}: {exc}", file=sys.stderr)
        return 2

    n = count_out_of_vocab(tasks)
    total = len(tasks)
    msg = (
        f"[validate-next-tasks-status] next_tasks.json: {n}/{total} out-of-vocab "
        f"statuses (baseline={args.baseline})"
    )
    nb = count_out_of_vocab_blocked_reasons(tasks)
    msg_b = (
        f"[validate-next-tasks-status] next_tasks.json: {nb}/{total} out-of-vocab "
        f"blocked_reasons (baseline={args.blocked_reason_baseline})"
    )

    failed = False
    if n > args.baseline:
        failed = True
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
    else:
        print(msg + "  -> OK")

    if nb > args.blocked_reason_baseline:
        failed = True
        print(msg_b + "  -> REGRESSION", file=sys.stderr)
        print(
            "[validate-next-tasks-status] New out-of-vocab blocked_reason introduced. "
            "The canonical vocab is src/volpred/ops/blocked_reasons.py; writers must "
            "use it (validate_blocked_reason / mark_task_blocked.py).",
            file=sys.stderr,
        )
        if args.verbose:
            bad_b = [
                (t.get("id") or t.get("task_id") or "?", str(t.get("blocked_reason"))[:60])
                for t in tasks
                if isinstance(t, dict)
                and isinstance(t.get("blocked_reason"), str)
                and t.get("blocked_reason").strip()
                and not is_valid_blocked_reason(t.get("blocked_reason"))
            ]
            print(f"[validate-next-tasks-status] sample: {bad_b[:10]}", file=sys.stderr)
    else:
        print(msg_b + "  -> OK")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
