"""`.git/index.lock` must survive its holder's death without blocking the repo.

PHASE-Z does not merely wait on Git's index lock — it *creates* it, copies the
index into it, and adopts it (`_refresh_shared_index_cas`). Release depends on
an in-process `finally`, in a process that is designed to be signalled: the
stale-code reloader SIGTERMs the supervisor, and custody loss SIGKILLs workers.
Neither runs `finally`.

On 2026-08-04 that leaked three times in one session (43 min, 80 s, 43 min).
Every `git_writer_lock.py commit` failed with "cannot snapshot current index"
and a human had to decide the lock looked stale enough to delete.

The fix is an owner sidecar plus a reclaim that fails closed. These tests pin
both halves, and above all the case that must NEVER reclaim: a lock with no
sidecar belongs to real Git or another tool, and removing it corrupts a live
index update.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import phase_z
from scripts.dispatch_supervisor.procutil import (
    IDENTITY_DEAD,
    IDENTITY_MATCH,
    IDENTITY_MISMATCH,
    IDENTITY_UNVERIFIED,
)

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    return tmp_path


def _lock(repo: Path) -> Path:
    path = repo / ".git" / "index.lock"
    path.write_bytes(b"DIRC-scratch-index")
    return path


def _sidecar(repo: Path, **overrides) -> Path:
    payload = {
        "actor": "phase_z",
        "pid": 999_999,
        "pid_start_wall": "Mon Aug  4 09:00:00 2026",
        "host": os.uname().nodename,
        "created_at": (NOW - timedelta(minutes=30)).isoformat(),
    }
    payload.update(overrides)
    path = phase_z._index_lock_owner_path(repo / ".git" / "index.lock")
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_lock_without_a_sidecar_is_never_reclaimed(repo: Path, monkeypatch) -> None:
    """This is real Git mid-write. Deleting it corrupts the index update.

    The whole reason a naive stale-lock cleaner is unacceptable.
    """
    lock = _lock(repo)
    monkeypatch.setattr(phase_z, "check_identity", lambda *_a, **_k: IDENTITY_DEAD)

    result = phase_z.reclaim_leaked_index_lock(repo, now=NOW)

    assert result == {"reclaimed": False, "reason": "not_ours"}
    assert lock.exists()


def test_dead_holder_lock_is_reclaimed_with_a_receipt(repo: Path, monkeypatch) -> None:
    lock = _lock(repo)
    sidecar = _sidecar(repo)
    monkeypatch.setattr(phase_z, "check_identity", lambda *_a, **_k: IDENTITY_DEAD)

    result = phase_z.reclaim_leaked_index_lock(repo, now=NOW)

    assert result["reclaimed"] is True
    assert result["holder_pid"] == 999_999
    assert result["holder_identity"] == IDENTITY_DEAD
    assert result["age_s"] == pytest.approx(1800.0)
    assert not lock.exists()
    assert not sidecar.exists()


def test_reused_pid_counts_as_gone(repo: Path, monkeypatch) -> None:
    """A different process wearing the old pid is not the holder."""
    _lock(repo)
    _sidecar(repo)
    monkeypatch.setattr(phase_z, "check_identity", lambda *_a, **_k: IDENTITY_MISMATCH)

    assert phase_z.reclaim_leaked_index_lock(repo, now=NOW)["reclaimed"] is True


@pytest.mark.parametrize("identity", [IDENTITY_MATCH, IDENTITY_UNVERIFIED])
def test_live_or_unproven_holder_is_left_alone(
    repo: Path, monkeypatch, identity: str
) -> None:
    """`unverified` means the probe failed — it proves nothing, so fail closed."""
    lock = _lock(repo)
    _sidecar(repo)
    monkeypatch.setattr(phase_z, "check_identity", lambda *_a, **_k: identity)

    result = phase_z.reclaim_leaked_index_lock(repo, now=NOW)

    assert result["reclaimed"] is False
    assert result["reason"] == f"holder_{identity}"
    assert lock.exists()


def test_a_fresh_lock_is_not_raced_even_if_the_holder_looks_dead(
    repo: Path, monkeypatch
) -> None:
    lock = _lock(repo)
    _sidecar(repo, created_at=(NOW - timedelta(seconds=5)).isoformat())
    monkeypatch.setattr(phase_z, "check_identity", lambda *_a, **_k: IDENTITY_DEAD)

    result = phase_z.reclaim_leaked_index_lock(repo, now=NOW)

    assert result["reclaimed"] is False
    assert result["reason"] == "too_fresh"
    assert lock.exists()


def test_foreign_host_and_self_held_and_corrupt_sidecar_all_fail_closed(
    repo: Path, monkeypatch
) -> None:
    monkeypatch.setattr(phase_z, "check_identity", lambda *_a, **_k: IDENTITY_DEAD)

    _lock(repo)
    _sidecar(repo, host="some-other-machine")
    assert phase_z.reclaim_leaked_index_lock(repo, now=NOW)["reason"] == "foreign_host"

    _sidecar(repo, pid=os.getpid())
    assert phase_z.reclaim_leaked_index_lock(repo, now=NOW)["reason"] == "self_held"

    _sidecar(repo, created_at="not-a-timestamp")
    assert (
        phase_z.reclaim_leaked_index_lock(repo, now=NOW)["reason"]
        == "owner_timestamp_invalid"
    )

    phase_z._index_lock_owner_path(repo / ".git" / "index.lock").write_text(
        "{broken", encoding="utf-8"
    )
    assert (
        phase_z.reclaim_leaked_index_lock(repo, now=NOW)["reason"] == "owner_unreadable"
    )
    assert (repo / ".git" / "index.lock").exists()


def test_sidecar_is_written_on_acquire_and_cleared_on_both_exits(
    repo: Path,
) -> None:
    """Adopt consumes the lock via os.replace but leaves the sidecar behind.

    A stray sidecar is worse than none: it would describe a lock some *other*
    writer later creates, and invite reclaiming a live one.
    """
    lock = repo / ".git" / "index.lock"

    phase_z._write_index_lock_owner(lock)
    owner = json.loads(
        phase_z._index_lock_owner_path(lock).read_text(encoding="utf-8")
    )
    assert owner["pid"] == os.getpid()
    assert owner["actor"] == "phase_z"
    assert owner["host"] == os.uname().nodename

    phase_z._clear_index_lock_owner(lock)
    assert not phase_z._index_lock_owner_path(lock).exists()
    # Idempotent: the finally path runs on every exit, adopted or not.
    phase_z._clear_index_lock_owner(lock)
