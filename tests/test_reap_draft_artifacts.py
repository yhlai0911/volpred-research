"""Hermetic tests for the draft-family recognizer in reap_orphan_deliverables.

Regression target (2026-07-15, task fix_reap_orphan_deliverables_gap): the K1572
/ K1681 / K1685 drafts, lazypack plans and figures sat untracked in the working
tree for several fires. The reaper's draft path only asked "is this draft in the
feed?" — an already-published draft answered yes and was skipped, so its files
were never committed by anyone, and every PHASE-Z re-alerted the owner about
finished work.

Every test runs against a throwaway git repo (monkeypatched ROOT). Nothing here
may touch the real repository — that is the point of the fixture, not a nicety.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

GRACE = 2 * 3600
OLD = time.time() - (GRACE + 600)  # comfortably past the grace window


def _load_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "reap_orphan_deliverables.py"
    spec = importlib.util.spec_from_file_location("reap_orphan_deliverables", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)


def _write(path: Path, text: str, *, mtime: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A real but disposable git repo, with the module pointed at it."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    (tmp_path / "storage" / "drafts").mkdir(parents=True)
    (tmp_path / "storage" / "next_tasks.json").write_text("[]", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")

    mod = _load_module()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "DRAFTS_DIR", tmp_path / "storage" / "drafts")
    monkeypatch.setattr(mod, "TASKS_PATH", tmp_path / "storage" / "next_tasks.json")
    return mod, tmp_path


def test_published_draft_and_its_assets_are_collected(repo):
    """The exact shape that leaked: a draft already in the feed, plus its family."""
    mod, root = repo
    drafts = root / "storage" / "drafts"
    _write(drafts / "K1685_general_draft.md", "---\ntitle: x\n---\nbody", mtime=OLD)
    _write(drafts / "K1685_lazypack_plan.json", "{}", mtime=OLD)
    _write(drafts / "assets" / "k1685_lazypack" / "1_concept.png", "png", mtime=OLD)

    scan = mod.scan_namespace("drafts")
    paths = {e["path"] for e in scan["collectable"]}
    assert paths == {
        "storage/drafts/K1685_general_draft.md",
        "storage/drafts/K1685_lazypack_plan.json",
        "storage/drafts/assets/k1685_lazypack/1_concept.png",
    }
    assert scan["held"] == []

    out = mod.collect_namespace("drafts", scan["collectable"])
    assert out[0]["committed"] is True
    # The whole point: nothing left for PHASE-Z to re-alert about.
    assert _git(root, "status", "--porcelain", "--", "storage/drafts/").stdout.strip() == ""


def test_draft_still_being_written_is_left_alone(repo):
    """Inside the grace window an author may still be typing — never grab it."""
    mod, root = repo
    _write(root / "storage" / "drafts" / "K9_general_draft.md", "fresh")  # mtime = now

    scan = mod.scan_namespace("drafts")
    assert scan["collectable"] == []
    assert scan["skipped"]["grace"] == 1


def test_draft_owned_by_a_live_task_is_left_alone(repo):
    """A claimed task still owns its draft; the reaper only takes orphans."""
    mod, root = repo
    _write(root / "storage" / "drafts" / "K9_general_draft.md", "body", mtime=OLD)
    (root / "storage" / "next_tasks.json").write_text(json.dumps([
        {"id": "t1", "status": "in_progress",
         "description": "writing storage/drafts/K9_general_draft.md"},
    ]), encoding="utf-8")

    scan = mod.scan_namespace("drafts")
    assert scan["collectable"] == []
    assert scan["skipped"]["inflight"] == 1


def test_novel_suffix_is_collected_by_default(repo):
    """The default is COLLECT, and this test exists to keep it that way.

    Do not read this as ".parquet is supported" — that reading is the bug. An
    allowlist of draft suffixes was tried twice and leaked twice (2026-07-14
    3b2c10375, then .csv/.py three days later) because a draft's asset suffixes
    are an OPEN set: the next one is .txt or .ipynb or something unnamed today.
    The assertion is that a suffix nobody anticipated lands in `collectable`
    anyway, purely by living under storage/drafts/. If a future change makes an
    unknown suffix held again, this test must fail — that is its whole job.
    """
    mod, root = repo
    _write(root / "storage" / "drafts" / "assets" / "e1" / "series.parquet",
           "PAR1", mtime=OLD)
    _write(root / "storage" / "drafts" / "assets" / "e1" / "notebook.ipynb",
           "{}", mtime=OLD)
    _write(root / "storage" / "drafts" / "assets" / "e1" / "Makefile",
           "all:\n", mtime=OLD)  # no suffix at all

    scan = mod.scan_namespace("drafts")
    assert {e["path"] for e in scan["collectable"]} == {
        "storage/drafts/assets/e1/series.parquet",
        "storage/drafts/assets/e1/notebook.ipynb",
        "storage/drafts/assets/e1/Makefile",
    }
    assert scan["held"] == []


def test_junk_file_is_held_not_committed(repo):
    """Held + reported beats guessing — the denylist side of the same coin.

    Renamed from test_unrecognised_file_is_held_not_committed: under the
    inverted default nothing is held for being *unrecognised*; a file is held
    only when it is positively identified as junk.
    """
    mod, root = repo
    _write(root / "storage" / "drafts" / "scratch.tmp", "junk", mtime=OLD)
    _write(root / "storage" / "drafts" / "assets" / "__pycache__" / "b.cpython-312.pyc",
           "x", mtime=OLD)
    _write(root / "storage" / "drafts" / ".DS_Store", "x", mtime=OLD)
    _write(root / "storage" / "drafts" / "notes.md~", "x", mtime=OLD)

    scan = mod.scan_namespace("drafts")
    assert scan["collectable"] == []
    reasons = {e["path"]: e["reason"] for e in scan["held"]}
    assert reasons["storage/drafts/scratch.tmp"] == "excluded_suffix:.tmp"
    assert reasons["storage/drafts/.DS_Store"] == "excluded_dotfile"
    assert reasons["storage/drafts/notes.md~"] == "excluded_editor_backup"
    assert (reasons["storage/drafts/assets/__pycache__/b.cpython-312.pyc"]
            == "excluded_suffix:.pyc")


def test_oversize_file_is_held_not_committed(repo):
    """Version control does not take data dumps; the reaper reports, never deletes."""
    mod, root = repo
    big = root / "storage" / "drafts" / "assets" / "e1" / "dump.csv"
    big.parent.mkdir(parents=True, exist_ok=True)
    big.write_bytes(b"0" * (mod.get_namespace("drafts")["max_file_bytes"] + 1))
    os.utime(big, (OLD, OLD))

    scan = mod.scan_namespace("drafts")
    assert scan["collectable"] == []
    assert scan["held"][0]["reason"].startswith("excluded_oversize:")
    assert big.exists()  # invariant: held means held, not removed


def test_symlink_is_held_not_committed(repo):
    """Invariant 4: git ownership only recognises exact regular files."""
    mod, root = repo
    real = root / "outside.csv"
    real.write_text("a,b\n", encoding="utf-8")
    link = root / "storage" / "drafts" / "assets" / "e1" / "link.csv"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(real)

    scan = mod.scan_namespace("drafts")
    assert scan["collectable"] == []
    assert scan["held"][0]["reason"] == "excluded_symlink"


def test_deletion_is_never_committed(repo):
    """A vanished file is not a deliverable. Committing the deletion would be the
    script's first destructive act — the top-of-file invariant forbids it."""
    mod, root = repo
    tracked = root / "storage" / "drafts" / "K8_general_draft.md"
    _write(tracked, "body")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "add draft")
    tracked.unlink()

    scan = mod.scan_namespace("drafts")
    assert scan["collectable"] == []
    assert scan["held"][0]["reason"] == "deletion_not_owned"
    # Still in HEAD: the reaper reported the deletion, it did not ratify it.
    assert _git(root, "cat-file", "-e", "HEAD:storage/drafts/K8_general_draft.md").returncode == 0


def test_draft_collector_refuses_late_prestaged_collision(repo):
    mod, root = repo
    target = root / "storage" / "drafts" / "K10_general_draft.md"
    _write(target, "first complete draft", mtime=OLD)
    entries = mod.scan_namespace("drafts")["collectable"]
    assert entries

    _git(root, "add", "storage/drafts/K10_general_draft.md")
    staged = _git(root, "show", ":storage/drafts/K10_general_draft.md").stdout
    _write(target, "later working bytes", mtime=OLD)
    out = mod.collect_namespace("drafts", entries)
    assert out[0]["committed"] is False
    assert out[0]["err"] == "pre_staged_collision"
    assert _git(root, "show", ":storage/drafts/K10_general_draft.md").stdout == staged
    assert target.read_text(encoding="utf-8") == "later working bytes"
