"""Every gate's tools must come from main — the ref the hook was deployed from.

Not just Gate 0's auditor: Gates 1-2 read their auditors and their baseline too, and
until 2026-07-15 they read them from the committing checkout's WORKING TREE. Same
contract, two different refs — so a worktree branched before those inputs existed
carried none of them, and Gate 2's fail-closed check hard-blocked every .py commit
inside it. That is the 2026-07-14 deadlock wearing a different hat; a4ecb962a fixed
the auditor and left the audits, and CI went red on this very file for three runs.

The original Gate 0 story, still enforced below:

The deployed hook (.git/hooks/pre-commit, shared by every linked worktree) drives
scripts/audit_test_imports.py with --index. A dispatch worktree branched before that
flag existed carries a base whose auditor argparse-rejects the invocation, so resolving
the auditor from `git show HEAD:` blocked every .py commit inside every stale worktree
and stranded agent work uncommitted (2026-07-14). Gate -1 cannot catch it: linked
worktrees have no $(git rev-parse --git-dir)/hooks/pre-commit, so it no-ops there.

Second property, same fix: on a feature branch HEAD is candidate-controlled, so a commit
could land a weakened auditor and have the next commit judged by it. main cannot be
written by the commit in flight.

Everything runs in a throwaway repo — these tests must never touch the real one.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SRC = REPO_ROOT / "scripts" / "git_hooks" / "pre-commit"

# Stands in for scripts/audit_test_imports.py before --index existed: argparse rejects
# the flag the deployed hook passes, exactly as the real pre-2026-07-14 copy does.
AUDITOR_WITHOUT_INDEX = """\
import argparse, sys
p = argparse.ArgumentParser()
p.add_argument("--root")
p.parse_args()
sys.exit(0)
"""

AUDITOR_WITH_INDEX = """\
import argparse, sys
p = argparse.ArgumentParser()
p.add_argument("--root")
p.add_argument("--index", action="store_true")
p.parse_args()
sys.exit(0)
"""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo whose main carries the --index auditor and whose branch `stale` predates it."""
    repo = tmp_path / "repo"
    (repo / "scripts" / "git_hooks").mkdir(parents=True)
    _git(repo.parent, "init", "-q", "-b", "main", str(repo))

    auditor = repo / "scripts" / "audit_test_imports.py"
    auditor.write_text(AUDITOR_WITHOUT_INDEX)
    shutil.copy(HOOK_SRC, repo / "scripts" / "git_hooks" / "pre-commit")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-verify", "-m", "base: auditor without --index")

    # Branch off the old base *before* main learns --index — this is the dispatch
    # worktree that was created hours earlier.
    _git(repo, "branch", "stale")

    auditor.write_text(AUDITOR_WITH_INDEX)

    # The gate inputs land on main only, so `stale` carries none of them. That is
    # not fixture convenience — it IS the second half of the regression: Gates 1-2
    # used to read these from the committing checkout's working tree, so a base
    # predating them hard-blocked every .py commit in the worktree. Every gate must
    # resolve from the ref the hook was deployed from, or the deadlock just moves
    # one gate down. Real auditors, not stubs: both are stdlib-only and it is their
    # actual behaviour the hook depends on.
    for tool in ("audit_silent_fallbacks.py", "audit_source_encoding.py"):
        shutil.copy(REPO_ROOT / "scripts" / tool, repo / "scripts" / tool)
    baseline = repo / "storage" / "qa" / "silent_fallback_baseline.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(
        '{"schema": "silent_fallback_baseline.v2", "count": 0, "findings": []}\n'
    )

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-verify", "-m", "main: auditor learns --index, gates land")

    # Deploy the hook the way the real repo does: one shared copy under .git/hooks,
    # matching main's source (so Gate -1 is satisfied in the main checkout).
    deployed = repo / ".git" / "hooks" / "pre-commit"
    shutil.copy(HOOK_SRC, deployed)
    deployed.chmod(0o755)
    return repo


def test_stale_worktree_can_still_commit_python(repo: Path, tmp_path: Path) -> None:
    """The regression: a worktree on a base predating --index must not be commit-locked."""
    wt = tmp_path / "wt"
    assert _git(repo, "worktree", "add", "-q", str(wt), "stale").returncode == 0
    # Gate -1 must be a no-op here, or the diagnosis is wrong and this test proves nothing.
    git_dir = _git(wt, "rev-parse", "--git-dir").stdout.strip()
    assert not (Path(git_dir) / "hooks" / "pre-commit").exists()

    (wt / "experiments").mkdir()
    (wt / "experiments" / "k9999.py").write_text("x = 1\n")
    assert _git(wt, "add", "experiments/k9999.py").returncode == 0

    got = _git(wt, "commit", "-m", "experiment output from a stale worktree")
    assert got.returncode == 0, f"stale worktree blocked by Gate 0:\n{got.stdout}{got.stderr}"
    assert "unrecognized arguments" not in (got.stdout + got.stderr)


def test_branch_copy_of_the_auditor_is_not_the_one_that_judges_it(repo: Path, tmp_path: Path) -> None:
    """The auditor a branch commits must not become the auditor that judges the branch.

    Discriminating by behaviour, not by flags: the branch lands an auditor that rejects
    everything. If the hook read HEAD, the next commit dies with BRANCH_AUDITOR_RAN.
    Reading main, it never runs at all.
    """
    wt = tmp_path / "wt2"
    assert _git(repo, "worktree", "add", "-q", str(wt), "-b", "tamper", "main").returncode == 0

    (wt / "scripts" / "audit_test_imports.py").write_text(
        'import sys; print("BRANCH_AUDITOR_RAN"); sys.exit(1)\n'
    )
    _git(wt, "add", "-A")
    assert _git(wt, "commit", "-q", "-m", "swap in a branch-local auditor").returncode == 0

    (wt / "payload.py").write_text("y = 2\n")
    _git(wt, "add", "payload.py")
    got = _git(wt, "commit", "-m", "judged by main, not by the commit above")
    out = got.stdout + got.stderr
    assert "BRANCH_AUDITOR_RAN" not in out, f"hook ran the branch's own auditor:\n{out}"
    assert got.returncode == 0, out


def test_missing_main_falls_back_to_head(repo: Path, tmp_path: Path) -> None:
    """A checkout with no local main (bare CI clone) keeps the old HEAD-based behaviour."""
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--branch", "main", str(repo), str(clone)], check=True)
    _git(clone, "checkout", "-q", "-b", "detached-work")
    _git(clone, "branch", "-q", "-D", "main")
    assert _git(clone, "rev-parse", "--verify", "refs/heads/main").returncode != 0

    deployed = clone / ".git" / "hooks" / "pre-commit"
    shutil.copy(HOOK_SRC, deployed)
    deployed.chmod(0o755)

    (clone / "thing.py").write_text("z = 3\n")
    _git(clone, "add", "thing.py")
    got = _git(clone, "commit", "-m", "no local main")
    assert got.returncode == 0, f"fallback to HEAD broke:\n{got.stdout}{got.stderr}"


# --- Gate 2 reads the same trusted ref, and must not go soft doing it ---------

SILENT_FALLBACK = """\
import json


def load(raw):
    try:
        return json.loads(raw)
    except Exception:
        return None
"""


def _rewrite_baseline(wt: Path, target: str) -> None:
    """Regenerate the worktree's baseline the way a human accepting a finding would."""
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "audit_silent_fallbacks.py"),
            "--root", str(wt),
            "--write-baseline", str(wt / "storage" / "qa" / "silent_fallback_baseline.json"),
            target,
        ],
        check=True,
        capture_output=True,
    )


def test_gate2_still_fails_closed_when_the_trusted_ref_has_no_auditor(tmp_path: Path) -> None:
    """Resolving from main must not turn a missing auditor into a silent skip.

    The whole point of Gate 2 is that a repo without the audit cannot commit Python.
    Sourcing it from main instead of the working tree changes WHERE it is read, never
    WHETHER it is enforced.
    """
    repo = tmp_path / "bare"
    (repo / "scripts" / "git_hooks").mkdir(parents=True)
    _git(repo.parent, "init", "-q", "-b", "main", str(repo))
    (repo / "scripts" / "audit_test_imports.py").write_text(AUDITOR_WITH_INDEX)
    shutil.copy(HOOK_SRC, repo / "scripts" / "git_hooks" / "pre-commit")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-verify", "-m", "base: no silent-fallback gate inputs")
    deployed = repo / ".git" / "hooks" / "pre-commit"
    shutil.copy(HOOK_SRC, deployed)
    deployed.chmod(0o755)

    (repo / "payload.py").write_text("x = 1\n")
    _git(repo, "add", "payload.py")
    got = _git(repo, "commit", "-m", "should not pass")
    out = got.stdout + got.stderr
    assert got.returncode != 0, f"gate went soft — missing auditor let a .py through:\n{out}"
    assert "silent-fallback gate inputs" in out, out


def test_a_commit_that_accepts_a_finding_can_land_its_own_baseline(repo: Path, tmp_path: Path) -> None:
    """The baseline is the one input read from the candidate, and it has to be.

    Regenerating it is the sanctioned way to accept a finding, so judging that commit
    against main's older baseline would make an accepted finding permanently unlandable
    — a deadlock, just spelled differently. Pinning the AUDITOR to main is what keeps
    this safe: the candidate supplies the ledger, never the judge.
    """
    wt = tmp_path / "accept"
    assert _git(repo, "worktree", "add", "-q", str(wt), "-b", "accept", "main").returncode == 0

    (wt / "scripts" / "leaky.py").write_text(SILENT_FALLBACK)
    _git(wt, "add", "scripts/leaky.py")

    # Without the baseline update the gate must bite — otherwise this test proves nothing.
    blocked = _git(wt, "commit", "-m", "new silent fallback, no baseline update")
    out = blocked.stdout + blocked.stderr
    assert blocked.returncode != 0, f"gate missed a new silent fallback:\n{out}"
    assert "new silent fallback" in out, out

    _rewrite_baseline(wt, "scripts/leaky.py")
    _git(wt, "add", "storage/qa/silent_fallback_baseline.json")
    got = _git(wt, "commit", "-m", "accept the finding into the baseline")
    assert got.returncode == 0, f"accepting a finding is unlandable:\n{got.stdout}{got.stderr}"
