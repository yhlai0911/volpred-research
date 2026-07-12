"""Regression tests for the locked work_log append path.

2026-07-13 incident (hourly-02): the fire appended two entries to
storage/work_log.json, staged the file, and by commit time the file had reverted
to the previous writer's snapshot. Both entries were gone, silently — a lost
update. work_log.json has ~12 writers (dispatch, codex_loop,
backfill-from-commits, pregate, dashboard, ...), every one of them doing an
unlocked read-modify-write of the whole array.

next_tasks.json has held fcntl.LOCK_EX since the cross-session claim race; the
lesson was never carried over to the work log. These tests pin the carry-over.

The concurrency test uses real processes, not threads: the failure mode is two
interpreters racing on the filesystem, and a GIL-serialised thread test could
pass while the actual bug survives.
"""

from __future__ import annotations

import json
import multiprocessing
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from append_work_log import append_entry  # noqa: E402


def _entry(i: int) -> dict:
    return {"task_id": f"t{i}", "actor": "test", "task_type": "platform_ops", "summary": "s"}


def _worker(args) -> None:
    path, lock, i = args
    append_entry(_entry(i), path=Path(path), lock_path=Path(lock))


@pytest.fixture()
def log_paths(tmp_path):
    return tmp_path / "work_log.json", tmp_path / ".work_log.lock"


def test_append_to_missing_log_creates_it(log_paths):
    path, lock = log_paths
    assert append_entry(_entry(1), path=path, lock_path=lock) == 1
    assert json.loads(path.read_text())[0]["task_id"] == "t1"


def test_append_preserves_existing_entries(log_paths):
    path, lock = log_paths
    path.write_text(json.dumps([_entry(0)]), encoding="utf-8")
    append_entry(_entry(1), path=path, lock_path=lock)
    ids = [e["task_id"] for e in json.loads(path.read_text())]
    assert ids == ["t0", "t1"]


def test_concurrent_writers_do_not_lose_entries(log_paths):
    """The actual bug: 12 unlocked writers, and the loser's entries vanish."""
    path, lock = log_paths
    path.write_text("[]", encoding="utf-8")
    n = 12
    with multiprocessing.Pool(6) as pool:
        pool.map(_worker, [(str(path), str(lock), i) for i in range(n)])
    ids = sorted(e["task_id"] for e in json.loads(path.read_text()))
    assert ids == sorted(f"t{i}" for i in range(n)), "a concurrent append was lost"


def test_non_ascii_summary_survives(log_paths):
    """Summaries are Chinese prose; ensure_ascii=False must hold through the
    temp-file round trip."""
    path, lock = log_paths
    e = _entry(1) | {"summary": "詞彙相似度候選 — 重疊度 0.579"}
    append_entry(e, path=path, lock_path=lock)
    assert json.loads(path.read_text())[0]["summary"] == "詞彙相似度候選 — 重疊度 0.579"


def test_corrupt_log_is_not_silently_replaced(log_paths):
    """If the log is not an array, fail loudly. Overwriting it with a fresh
    one-element list would destroy the history we came to append to."""
    path, lock = log_paths
    path.write_text('{"not": "an array"}', encoding="utf-8")
    with pytest.raises(TypeError):
        append_entry(_entry(1), path=path, lock_path=lock)


def test_no_temp_files_left_behind(log_paths):
    path, lock = log_paths
    append_entry(_entry(1), path=path, lock_path=lock)
    assert not list(path.parent.glob(".work_log.*.tmp"))
