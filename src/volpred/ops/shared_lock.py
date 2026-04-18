"""Shared state lock for cross-writer coordination.

All writers that mutate shared JSON files (memory/*.json, reports/feed.json,
ops/control plane state, etc.) should acquire the corresponding lock before
reading-modifying-writing the file.

Usage:
    from volpred.ops.shared_lock import shared_state_lock

    with shared_state_lock("memory_knowledge"):
        data = read()
        data["new"] = ...
        write_atomic(data)

Lock naming convention (see docs/agent-collab-invariants.md):
    - control_plane           : ops task/agent/approval/execution JSONs
    - memory_<filename>       : storage/memory/<filename>.json
    - publisher_feed          : storage/reports/feed.json
    - publisher_<report_id>   : (reserved) per-report lock if ever needed

Locks are advisory fcntl.LOCK_EX on a sentinel file under
storage/ops/locks/<name>.lock. Locks cooperate across Python processes on the
same host (Claude Code, Codex VS Code extension, cron workers, CLI runs).
"""
from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from .common import project_path


def _lock_dir(storage_dir: str = "storage") -> Path:
    path = project_path(storage_dir, "ops", "locks")
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def shared_state_lock(name: str, storage_dir: str = "storage", *, blocking: bool = True) -> Iterable[bool]:
    """Acquire an exclusive advisory lock keyed on `name`.

    Blocks until the lock is acquired. Cooperative across processes on the same
    host; opt-in (readers/writers that ignore the lock still race).
    """
    lock_file = _lock_dir(storage_dir) / f"{name}.lock"
    if not lock_file.exists():
        lock_file.touch()
    with lock_file.open("a+", encoding="utf-8") as handle:
        acquired = False
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(handle.fileno(), flags)
            acquired = True
        except BlockingIOError:
            acquired = False
        try:
            yield acquired
        finally:
            if acquired:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
