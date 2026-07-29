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
    registry = tmp_path / "config" / "orphan_namespaces.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        (
            Path(__file__).resolve().parents[1]
            / "config"
            / "orphan_namespaces.json"
        ).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")

    mod = _load_module()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "REGISTRY_PATH", registry)
    monkeypatch.setattr(mod, "DRAFTS_DIR", tmp_path / "storage" / "drafts")
    monkeypatch.setattr(mod, "TASKS_PATH", tmp_path / "storage" / "next_tasks.json")
    mod.load_registry(refresh=True)
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
    # Reported under its directory as an uncommitted rename/edit, not adopted.
    assert scan["held"][0]["reason"] == "pending_rename"
    assert "storage/drafts/K8_general_draft.md" in scan["held"][0]["members"]
    # Still in HEAD: the reaper reported the deletion, it did not ratify it.
    assert _git(root, "cat-file", "-e", "HEAD:storage/drafts/K8_general_draft.md").returncode == 0


# ---------------------------------------------------------------------------
# 2026-07-19 false-positive triad (assign_c0ad1962). Every one of these produced
# a "無主產物" escalation task for something that was never ownerless. The cost
# is not the alert — it is that a human opened 23 files to conclude "all fine".
# ---------------------------------------------------------------------------


def _feed(root: Path, articles: list[dict]) -> None:
    _write(root / "storage" / "reports" / "feed.json",
           json.dumps(articles, ensure_ascii=False))


def test_derivative_of_published_article_is_not_an_orphan(repo, monkeypatch):
    """`fb_mile_<id>.md` / `k841_mile_<id>_correction.md` name their article.

    They carry no frontmatter title on purpose — they were never meant to enter
    the draft pool — so the title/source_draft/K-coverage probes all miss and
    they sat in `no_title` held for 14 shifts. The id in the filename is an
    exact back-link to an already-published article.
    """
    mod, root = repo
    monkeypatch.setattr(mod, "FEED_PATH", root / "storage" / "reports" / "feed.json")
    _feed(root, [{"id": "mile_29018fa1", "title": "事件溫度計", "audience": "event"}])
    for name in ("fb_mile_29018fa1.md", "k841_mile_29018fa1_correction.md"):
        _write(root / "storage" / "drafts" / name,
               "# mile_id: mile_29018fa1\n主貼文正文", mtime=OLD)

    scan = mod.scan()
    assert scan["held"] == []
    assert scan["adoptable"] == []
    assert scan["skipped"]["registered"] == 2


def test_draft_naming_an_unpublished_id_is_still_held(repo, monkeypatch):
    """The probe must be a back-link, not a filename-shaped excuse to skip."""
    mod, root = repo
    monkeypatch.setattr(mod, "FEED_PATH", root / "storage" / "reports" / "feed.json")
    _feed(root, [{"id": "mile_deadbeef", "title": "other"}])
    _write(root / "storage" / "drafts" / "fb_mile_29018fa1.md", "body", mtime=OLD)

    scan = mod.scan()
    assert [e["reason"] for e in scan["held"]] == ["no_title"]


def _job(root: Path, job_id: str, **fields) -> None:
    _write(root / "storage" / "ops" / "compute_queue" / f"{job_id}.json",
           json.dumps({"id": job_id, **fields}))


def test_merged_worktree_output_is_not_held(repo, monkeypatch):
    """A job declares `.claude/worktrees/<wt>/…`; merge removes the worktree.

    The deliverable is then safe in the checkout under the same repo-relative
    path, but the declared path stops existing — which is how five k1704 jobs
    became `no_existing_declared_files` holds while K1704 sat certified in main.
    """
    mod, root = repo
    monkeypatch.setattr(mod, "QUEUE_DIR", root / "storage" / "ops" / "compute_queue")
    _write(root / "experiments" / "k1704" / "K1704_results.json", "{}")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "merged result")
    _job(root, "k1704-formal-cache-rerun", status="completed", output_paths=[
        ".claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/k1704/K1704_results.json"])

    out = mod.scan_job_deliverables()
    assert out["held"] == []
    assert out["candidates"] == []


def test_worktree_output_still_missing_is_held(repo, monkeypatch):
    """k1730's shape: completed, unmerged, nothing in main — that one is real."""
    mod, root = repo
    monkeypatch.setattr(mod, "QUEUE_DIR", root / "storage" / "ops" / "compute_queue")
    _job(root, "compute-k1730-arm-a", status="completed", output_paths=[
        ".claude/worktrees/dispatch-slot-1-558d7893-k1730/experiments/k1730/results.json"])

    out = mod.scan_job_deliverables()
    assert [h["reason"] for h in out["held"]] == ["no_existing_declared_files"]


def test_live_followup_owns_modified_worktree_outputs(repo, monkeypatch):
    """K1708 shape: rerun bytes wait in a worktree while review is queued.

    They are not ownerless, even though Git still reports them modified.  The
    child receipt is the escalation owner until it commits or terminates.
    """
    mod, root = repo
    queue = root / "storage" / "ops" / "compute_queue"
    monkeypatch.setattr(mod, "QUEUE_DIR", queue)
    _write(root / ".gitignore", ".claude/worktrees/\n")
    worktree = root / ".claude" / "worktrees" / "dispatch-k1708"
    _write(worktree / ".git", "gitdir: /tmp/common/worktrees/dispatch-k1708\n")
    output = worktree / "experiments" / "k1708" / "K1708_results.json"
    _write(output, "{}")
    _job(root, "k1708-stage2", status="queued", kind="agent", cwd=str(worktree))
    _job(
        root,
        "compute-k1708",
        status="completed",
        output_paths=[str(output)],
        followup_dispatched=True,
        followup_next_task_id="k1708-stage2",
    )

    out = mod.scan_job_deliverables()
    assert out["held"] == []
    assert out["candidates"] == []


@pytest.mark.parametrize(
    ("followup_status", "followup_cwd"),
    [("failed", None), ("queued", "different-worktree")],
)
def test_terminal_or_unrelated_followup_does_not_hide_worktree_hold(
        repo, monkeypatch, followup_status, followup_cwd):
    """Only a live child operating in the exact worktree can suppress a hold."""
    mod, root = repo
    queue = root / "storage" / "ops" / "compute_queue"
    monkeypatch.setattr(mod, "QUEUE_DIR", queue)
    _write(root / ".gitignore", ".claude/worktrees/\n")
    worktree = root / ".claude" / "worktrees" / "dispatch-k1708"
    _write(worktree / ".git", "gitdir: /tmp/common/worktrees/dispatch-k1708\n")
    output = worktree / "experiments" / "k1708" / "K1708_results.json"
    _write(output, "{}")
    cwd = worktree if followup_cwd is None else worktree.parent / followup_cwd
    _job(root, "k1708-stage2", status=followup_status, kind="agent", cwd=str(cwd))
    _job(
        root,
        "compute-k1708",
        status="completed",
        output_paths=[str(output)],
        followup_dispatched=True,
        followup_next_task_id="k1708-stage2",
    )

    out = mod.scan_job_deliverables()
    assert [h["reason"] for h in out["held"]] == ["no_existing_declared_files"]


def test_failed_job_with_no_output_is_not_held(repo, monkeypatch):
    """A job that exited non-zero produced nothing to preserve. Asking a human
    to find an exit for a file that never existed is pure noise."""
    mod, root = repo
    monkeypatch.setattr(mod, "QUEUE_DIR", root / "storage" / "ops" / "compute_queue")
    _job(root, "K1694-script-rerun-1211", status="failed",
         output_paths=["experiments/K1694/K1694_results.json"])

    assert mod.scan_job_deliverables()["held"] == []


def test_gitignored_leftovers_do_not_hold_a_delivered_job(repo, monkeypatch):
    """Every real output landed; the stragglers are `__pycache__` and a scratch
    `*_article.md` that .gitignore excludes. Unreachable by design ≠ orphaned."""
    mod, root = repo
    monkeypatch.setattr(mod, "QUEUE_DIR", root / "storage" / "ops" / "compute_queue")
    panels = root / "storage" / "lazypack_jobs" / "mile_a8d79d6a" / "panels"
    _write(root / ".gitignore", "__pycache__/\n*_article.md\n")
    _write(panels / "1_framework.png", "png")
    _write(panels / "mile_a8d79d6a_article.md", "scratch")
    _write(panels / "__pycache__" / "render.cpython-312.pyc", "pyc")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "panels delivered")
    rel = "storage/lazypack_jobs/mile_a8d79d6a/panels"
    _job(root, "lazypack-mile_a8d79d6a-r2", status="completed",
         output_paths=[f"{rel}/1_framework.png", f"{rel}/mile_a8d79d6a_article.md",
                       f"{rel}/__pycache__/render.cpython-312.pyc"],
         delivered_paths=[f"{rel}/1_framework.png"])

    assert mod.scan_job_deliverables()["held"] == []


def test_pending_rename_is_one_held_row_not_eight(repo):
    """k1380 deliberately archived a bad run as `*_INVALID_20260716.*`. The
    reaper reported the three deletions and five surviving files as eight
    separate ownerless artifacts across two reasons. It is one directory
    mid-rename, and its exit is a commit — say that once."""
    mod, root = repo
    drafts = root / "storage" / "drafts"
    for name in ("k1380_results.json", "k1380_losses_all.npy", "README.md"):
        _write(drafts / name, "payload")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "k1380 run")
    for name in ("k1380_results.json", "k1380_losses_all.npy"):
        (drafts / name).unlink()
        _write(drafts / name.replace(".", "_INVALID_20260716."), "payload", mtime=OLD)
    _write(drafts / "README.md", "run voided, re-run queued", mtime=OLD)

    scan = mod.scan_namespace("drafts")
    assert scan["collectable"] == []
    assert len(scan["held"]) == 1
    entry = scan["held"][0]
    assert entry["reason"] == "pending_rename"
    assert entry["path"] == "storage/drafts"
    assert len(entry["members"]) == 5


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
