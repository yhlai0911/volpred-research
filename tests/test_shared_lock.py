"""Tests for volpred.ops.shared_lock.shared_state_lock."""
from __future__ import annotations

import multiprocessing
import os
import time
from pathlib import Path

import pytest


def _child(name: str, storage_dir: str, hold_secs: float, start_barrier_path: str) -> None:
    """Child process: acquire lock, signal ready, hold, release."""
    from volpred.ops.shared_lock import shared_state_lock

    with shared_state_lock(name, storage_dir=storage_dir):
        Path(start_barrier_path).write_text("ready")
        time.sleep(hold_secs)


def test_shared_state_lock_basic_acquire_and_release(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")
    from volpred.ops.shared_lock import shared_state_lock

    with shared_state_lock("test_lock", storage_dir=storage_dir):
        lock_file = tmp_path / "storage" / "ops" / "locks" / "test_lock.lock"
        assert lock_file.exists()

    # Can reacquire after release
    with shared_state_lock("test_lock", storage_dir=storage_dir):
        pass


def test_shared_state_lock_mutual_exclusion(tmp_path: Path):
    """Two processes acquiring the same name lock must not overlap."""
    storage_dir = str(tmp_path / "storage")
    from volpred.ops.shared_lock import shared_state_lock

    # Pre-create so child can acquire
    (tmp_path / "storage" / "ops" / "locks").mkdir(parents=True, exist_ok=True)

    barrier = tmp_path / "child_ready"
    hold = 0.8
    ctx = multiprocessing.get_context("fork")
    child = ctx.Process(target=_child, args=("concurrent", storage_dir, hold, str(barrier)))
    child.start()

    # Wait for child to signal it acquired the lock
    deadline = time.time() + 5
    while time.time() < deadline and not barrier.exists():
        time.sleep(0.02)
    assert barrier.exists(), "child failed to acquire lock in time"

    # Parent tries to acquire same lock — should block until child releases
    t0 = time.time()
    with shared_state_lock("concurrent", storage_dir=storage_dir):
        elapsed = time.time() - t0
    child.join(timeout=3)
    assert child.exitcode == 0
    assert elapsed >= hold * 0.5, f"parent not blocked, elapsed={elapsed:.3f}s"


def test_different_names_do_not_block(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")
    from volpred.ops.shared_lock import shared_state_lock

    (tmp_path / "storage" / "ops" / "locks").mkdir(parents=True, exist_ok=True)

    barrier = tmp_path / "child_ready2"
    ctx = multiprocessing.get_context("fork")
    child = ctx.Process(target=_child, args=("name_a", storage_dir, 1.0, str(barrier)))
    child.start()

    deadline = time.time() + 5
    while time.time() < deadline and not barrier.exists():
        time.sleep(0.02)
    assert barrier.exists()

    # Different lock name must NOT block
    t0 = time.time()
    with shared_state_lock("name_b", storage_dir=storage_dir):
        elapsed = time.time() - t0
    child.join(timeout=3)
    assert elapsed < 0.3, f"different-name locks should not block, elapsed={elapsed:.3f}s"


def test_nonblocking_shared_state_lock_reports_busy(tmp_path: Path):
    storage_dir = str(tmp_path / "storage")
    from volpred.ops.shared_lock import shared_state_lock

    with shared_state_lock("scheduler_tick", storage_dir=storage_dir):
        with shared_state_lock("scheduler_tick", storage_dir=storage_dir, blocking=False) as acquired:
            assert acquired is False
