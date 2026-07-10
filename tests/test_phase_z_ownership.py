"""PHASE-Z must commit what the fire produced — and nothing else.

`git add -A` has no notion of authorship. Three incidents came out of that one
assumption (docs/error_log.md 2026-07-10): a truncated `next_tasks.json`
committed as history, a rewrite smuggled past the test gate, and an interactive
session's half-finished `merge_worktree.sh` swept into an unrelated agent's
commit. The fix is a fire-start baseline: dirty now minus dirty then.

These tests drive real git in a temp repo (same style as
tests/test_phase_z_test_gate.py) because the bug lives in git's staging
semantics, not in Python. A fake `git` would have happily agreed with the bug.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.dispatch_supervisor import phase_z

SNAPSHOT = Path(*phase_z._PRE_FIRE_SNAPSHOT_RELPATH)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True,
    )


def _init_repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@volpred.local")
    _git(root, "config", "user.name", "phase-z-ownership-test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")


def _write(root: Path, rel: str, text: str) -> None:
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")


def _head_files(root: Path) -> set[str]:
    out = _git(root, "show", "--pretty=", "--name-only", "HEAD").stdout
    return {line for line in out.splitlines() if line}


def _dirty(root: Path) -> set[str]:
    return phase_z._porcelain_paths(
        subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "-z", "--untracked-files=all"],
            capture_output=True, text=True, check=True,
        ).stdout
    )


def _no_tests(*_a, **_k):
    """Neutralise the post-commit test gate — it is covered by its own suite and
    would otherwise spawn pytest recursively."""
    return subprocess.CompletedProcess(args=[], returncode=5, stdout="", stderr="")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _init_repo(tmp_path)
    return tmp_path


def _fire(repo: Path, alerts: list | None = None, **kw) -> dict:
    def _alert(*, level, title, body):
        if alerts is not None:
            alerts.append((level, title))
        return {"sent": True}

    return phase_z.run_phase_z(
        repo_root=repo, now_hhmm="03:00", test_runner=_no_tests, alert_fn=_alert, **kw
    )


# ── the incident ─────────────────────────────────────────────────────────────

def test_another_writers_edit_is_not_committed(repo: Path) -> None:
    """The 2026-07-10 incident, reduced: someone is mid-edit when the fire runs."""
    _write(repo, "scripts/merge_worktree.sh", "half-finished edit\n")  # theirs, dirty BEFORE
    phase_z.run_pre_fire_guard(repo_root=repo)

    _write(repo, "experiments/k1/k1.py", "agent output\n")  # ours, during the fire
    outcome = _fire(repo)

    assert outcome["committed"] is True
    assert _head_files(repo) == {"experiments/k1/k1.py"}
    assert "scripts/merge_worktree.sh" in _dirty(repo), "their edit must survive uncommitted"
    assert outcome["foreign"] == ["scripts/merge_worktree.sh"]


def test_foreign_path_staged_by_another_writer_is_unstaged_not_committed(repo: Path) -> None:
    """Scoping only `git add` is not enough: a plain `git commit` writes the whole
    index, so a file the other writer had already `git add`ed would still land."""
    _write(repo, "theirs.txt", "staged by someone else\n")
    _git(repo, "add", "theirs.txt")  # in the index, before the fire
    phase_z.run_pre_fire_guard(repo_root=repo)

    _write(repo, "ours.txt", "agent output\n")
    outcome = _fire(repo)

    assert outcome["committed"] is True
    assert _head_files(repo) == {"ours.txt"}
    assert (repo / "theirs.txt").read_text(encoding="utf-8") == "staged by someone else\n"


def test_nothing_owned_commits_nothing_and_alerts(repo: Path) -> None:
    _write(repo, "theirs.txt", "mid-edit\n")
    phase_z.run_pre_fire_guard(repo_root=repo)

    alerts: list = []
    before = _git(repo, "rev-parse", "HEAD").stdout
    outcome = _fire(repo, alerts=alerts)

    assert outcome["reason"] == "nothing_owned"
    assert outcome["committed"] is False
    assert _git(repo, "rev-parse", "HEAD").stdout == before, "no commit may be created"
    assert alerts and alerts[0][0] == "warn"


# ── the fire's own work still lands ──────────────────────────────────────────

def test_agent_work_is_committed_when_tree_was_clean(repo: Path) -> None:
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "experiments/k2/k2.py", "x\n")
    _write(repo, "docs/note.md", "y\n")

    outcome = _fire(repo)

    assert outcome["committed"] is True
    assert _head_files(repo) == {"experiments/k2/k2.py", "docs/note.md"}
    assert outcome["foreign"] == []


def test_agent_deletion_is_committed(repo: Path) -> None:
    """`git add -A -- <path>` stages the removal; a naive `git add <path>` does not."""
    phase_z.run_pre_fire_guard(repo_root=repo)
    (repo / "seed.txt").unlink()

    outcome = _fire(repo)

    assert outcome["committed"] is True
    still_in_head = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", "HEAD:seed.txt"], capture_output=True,
    ).returncode == 0
    assert not still_in_head, "deletion must be recorded, not just left in the worktree"


def test_path_with_spaces_survives(repo: Path) -> None:
    """Argv-joined pathspecs and `core.quotePath` both mangle these; NUL does not."""
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "storage/drafts/a draft with spaces.md", "z\n")

    outcome = _fire(repo)

    assert outcome["committed"] is True
    assert _head_files(repo) == {"storage/drafts/a draft with spaces.md"}


def test_clean_tree_is_a_noop(repo: Path) -> None:
    phase_z.run_pre_fire_guard(repo_root=repo)
    assert _fire(repo)["reason"] == "clean"


# ── ownership unknown → decline, never guess ─────────────────────────────────

def test_missing_baseline_declines_to_commit(repo: Path) -> None:
    """No pre-fire guard ran. The old code would `git add -A` here — that is the bug."""
    _write(repo, "someones_work.txt", "who wrote this?\n")

    alerts: list = []
    before = _git(repo, "rev-parse", "HEAD").stdout
    outcome = _fire(repo, alerts=alerts)

    assert outcome["reason"] == "ownership_unknown"
    assert _git(repo, "rev-parse", "HEAD").stdout == before
    assert "someones_work.txt" in _dirty(repo)
    assert alerts and alerts[0][0] == "warn"


def test_stale_baseline_is_refused(repo: Path) -> None:
    """A daemon killed mid-fire leaves yesterday's baseline behind. Judging today's
    dirt against it would call another writer's files 'ours'."""
    phase_z.run_pre_fire_guard(repo_root=repo)
    snap = repo / SNAPSHOT
    payload = json.loads(snap.read_text(encoding="utf-8"))
    payload["taken_at"] -= phase_z._SNAPSHOT_MAX_AGE_S + 60
    snap.write_text(json.dumps(payload), encoding="utf-8")

    _write(repo, "x.txt", "x\n")
    assert _fire(repo)["reason"] == "ownership_unknown"


def test_snapshot_is_consumed_so_the_next_fire_rebaselines(repo: Path) -> None:
    """One snapshot, one fire. A leftover baseline would let the next fire judge
    its output against a window taken before someone else started typing."""
    phase_z.run_pre_fire_guard(repo_root=repo)
    _write(repo, "a.txt", "a\n")
    _fire(repo)
    assert not (repo / SNAPSHOT).exists()


def test_guard_baselines_even_when_guard_script_is_absent(repo: Path) -> None:
    """The baseline must not be collateral damage of a missing guard script —
    losing it costs PHASE-Z its ability to commit at all."""
    _write(repo, "pre.txt", "dirty before\n")
    outcome = phase_z.run_pre_fire_guard(repo_root=repo)

    assert outcome["reason"] == "guard_missing"
    assert outcome["dirty_at_fire_start"] == 1
    assert (repo / SNAPSHOT).exists()


# ── porcelain parsing ────────────────────────────────────────────────────────

def test_porcelain_parses_renames_and_spaces() -> None:
    raw = "R  new name.txt\0old name.txt\0 M src/a.py\0?? untracked file.md\0"
    assert phase_z._porcelain_paths(raw) == {
        "new name.txt", "old name.txt", "src/a.py", "untracked file.md",
    }


def test_dirty_probe_distinguishes_clean_from_unknown(tmp_path: Path) -> None:
    """`None` (git failed) and `set()` (clean) must never collapse: the old code
    read an empty stdout on a failed `git status` as 'clean' and skipped."""
    assert phase_z._dirty_paths(tmp_path, subprocess.run) is None  # not a git repo
    _init_repo(tmp_path)
    assert phase_z._dirty_paths(tmp_path, subprocess.run) == set()
