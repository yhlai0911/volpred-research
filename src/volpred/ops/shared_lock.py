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

That last sentence is exactly why a test must never take one. Under
VOLPRED_NO_CANONICAL_WRITE the lock file is relocated out of the checkout (see
`sandboxed_lock_path`) — the fcntl path still runs, it just cannot contend with
the live dispatch supervisor.
"""
from __future__ import annotations

import fcntl
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from volpred.canonical_write import canonical_writes_disabled, is_canonical_path
from .common import project_path

# Shared by every process running with the gate on, so mutual exclusion between
# two test processes still holds — they just serialize against each other rather
# than against production.
_SANDBOX_LOCK_DIR = Path(tempfile.gettempdir()) / "volpred-sandboxed-locks"


def sandboxed_lock_path(path: Path) -> Path:
    """Relocate a canonical lock file out of the checkout when the gate is on.

    Locks are the one canonical write that must not merely be *blocked*: the code
    under test needs a real fcntl lock to exercise, and a `CanonicalWriteBlocked`
    would just delete the coverage. So the gate redirects instead of raising.

    Blocking on a production lock is not a cosmetic leak. `shared_state_lock`
    defaults to `blocking=True`, so a test reaching `control_plane` waits on
    whatever cron writer holds it; and `remediate_publish_drought` takes its
    single-flight lock LOCK_NB, so a test holding it makes the real remediation
    take its `# silent-ok` skip branch and do nothing that hour. Six tests were
    doing one or the other (2026-07-10 sweep).

    Names are flattened, not basenamed: storage/ops/locks/x.lock and
    storage/ops/x.lock must not collide into one sandbox file.
    """
    if not (canonical_writes_disabled() and is_canonical_path(path)):
        return path
    _SANDBOX_LOCK_DIR.mkdir(parents=True, exist_ok=True)
    flat = str(path.resolve()).lstrip("/").replace("/", "__")
    return _SANDBOX_LOCK_DIR / flat


@contextmanager
def shared_state_lock(name: str, storage_dir: str = "storage", *, blocking: bool = True) -> Iterable[bool]:
    """Acquire an exclusive advisory lock keyed on `name`.

    Blocks until the lock is acquired. Cooperative across processes on the same
    host; opt-in (readers/writers that ignore the lock still race).
    """
    lock_file = sandboxed_lock_path(project_path(storage_dir, "ops", "locks") / f"{name}.lock")
    # mkdir the resolved parent, never the canonical one: creating
    # storage/ops/locks/ is itself a write into the checkout.
    lock_file.parent.mkdir(parents=True, exist_ok=True)
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
