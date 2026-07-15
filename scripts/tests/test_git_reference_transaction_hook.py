from __future__ import annotations

import os
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from volpred.ops.git_writer_lock import git_writer_lock  # noqa: E402


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=check,
    )


def _install_fixture(repo: Path) -> None:
    (repo / "scripts" / "git_hooks").mkdir(parents=True)
    (repo / "src" / "volpred" / "ops").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts/git_writer_lock.py", repo / "scripts/git_writer_lock.py")
    shutil.copy2(
        ROOT / "src/volpred/ops/git_writer_lock.py",
        repo / "src/volpred/ops/git_writer_lock.py",
    )
    hook_source = ROOT / "scripts/git_hooks/reference-transaction"
    shutil.copy2(hook_source, repo / "scripts/git_hooks/reference-transaction")
    hook = repo / ".git" / "hooks" / "reference-transaction"
    shutil.copy2(hook_source, hook)
    hook.chmod(0o755)
    verifier_source = ROOT / "scripts/git_hooks/git-writer-lease-verify.py"
    shutil.copy2(verifier_source, repo / "scripts/git_hooks/git-writer-lease-verify.py")
    verifier = repo / ".git" / "hooks" / "git-writer-lease-verify.py"
    shutil.copy2(verifier_source, verifier)
    verifier.chmod(0o755)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "lease-hook@example.com")
    _git(repo, "config", "user.name", "Lease Hook Test")
    (repo / "owned.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "owned.txt")
    _git(repo, "commit", "-m", "base")
    _install_fixture(repo)
    return repo


def _candidate_commit(repo: Path, parent: str, message: str) -> str:
    tree = _git(repo, "rev-parse", "HEAD^{tree}").stdout.strip()
    return subprocess.run(
        ["git", "commit-tree", tree, "-p", parent],
        cwd=repo,
        input=message + "\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_raw_main_commit_and_update_ref_are_blocked_but_locked_commit_lands(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()

    (repo / "owned.txt").write_text("raw\n", encoding="utf-8")
    _git(repo, "add", "owned.txt")
    raw = _git(repo, "commit", "--no-verify", "-m", "raw bypass", check=False)
    assert raw.returncode != 0
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == base
    assert "requires an active canonical" in raw.stderr
    _git(repo, "restore", "--source=HEAD", "--staged", "--worktree", "owned.txt")

    commit = _candidate_commit(repo, base, "raw update-ref")
    update = _git(repo, "update-ref", "refs/heads/main", commit, base, check=False)
    assert update.returncode != 0
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == base

    (repo / "owned.txt").write_text("locked\n", encoding="utf-8")
    locked = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts/git_writer_lock.py"),
            "commit",
            "--repo",
            str(repo),
            "--actor",
            "test-locked",
            "--message",
            "locked commit",
            "--",
            "owned.txt",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
    )
    assert locked.returncode == 0, locked.stderr
    assert _git(repo, "log", "-1", "--format=%s").stdout.strip() == "locked commit"


def test_mutating_worktree_helper_cannot_weaken_installed_gate(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    candidate = _candidate_commit(repo, base, "candidate")
    (repo / "scripts/git_writer_lock.py").write_text(
        "raise SystemExit(0)\n", encoding="utf-8"
    )

    update = _git(
        repo, "update-ref", "refs/heads/main", candidate, base, check=False
    )
    assert update.returncode != 0
    assert _git(repo, "rev-parse", "refs/heads/main").stdout.strip() == base


def test_unlocked_fd_with_copied_token_cannot_impersonate_holder(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    candidate = _candidate_commit(repo, base, "forged fd")
    with git_writer_lock(repo, actor="real-holder") as lease:
        lock_path = lease.path
        metadata = json.loads(lock_path.read_text(encoding="utf-8"))
        forged_fd = os.open(lock_path, os.O_RDWR)
        assert lease.capability_fd is not None
        try:
            env = {
                **os.environ,
                "VOLPRED_GIT_WRITER_LOCK_TOKEN": metadata["token"],
                "VOLPRED_GIT_WRITER_LOCK_PATH": str(lock_path),
                "VOLPRED_GIT_WRITER_LOCK_FD": str(forged_fd),
                "VOLPRED_GIT_WRITER_CAP_FD": str(lease.capability_fd),
            }
            forged = subprocess.run(
                ["git", "update-ref", "refs/heads/main", candidate, base],
                cwd=repo,
                env=env,
                pass_fds=(forged_fd, lease.capability_fd),
                capture_output=True,
                text=True,
                check=False,
            )
            assert forged.returncode != 0
            assert "kind=lease_evidence_invalid" in forged.stderr
            assert "reason=BlockingIOError" in forged.stderr
            assert "exit_semantics=deny" in forged.stderr
            assert "dedupe_key=git_writer_lease_verify" in forged.stderr
            assert _git(repo, "rev-parse", "refs/heads/main").stdout.strip() == base
        finally:
            os.close(forged_fd)


def test_stale_metadata_after_holder_crash_cannot_recreate_capability(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    candidate = _candidate_commit(repo, base, "stale crash forgery")
    acquired = tmp_path / "crash-acquired"
    holder_code = (
        "import pathlib,time; "
        "from volpred.ops.git_writer_lock import git_writer_lock; "
        f"repo=pathlib.Path({str(repo)!r}); acquired=pathlib.Path({str(acquired)!r}); "
        "cm=git_writer_lock(repo, actor='crash-holder'); cm.__enter__(); "
        "acquired.touch(); time.sleep(60)"
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code],
        cwd=repo,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while not acquired.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert acquired.exists()
    lock_path = repo / ".git" / "volpred-git-writer.lock"
    metadata = json.loads(lock_path.read_text(encoding="utf-8"))
    holder.kill()
    holder.communicate(timeout=5)

    forged_fd = os.open(lock_path, os.O_RDWR)
    forged_cap_fd, forged_cap_write = os.pipe()
    os.close(forged_cap_write)
    try:
        env = {
            **os.environ,
            "VOLPRED_GIT_WRITER_LOCK_TOKEN": metadata["token"],
            "VOLPRED_GIT_WRITER_LOCK_PATH": str(lock_path),
            "VOLPRED_GIT_WRITER_LOCK_FD": str(forged_fd),
            "VOLPRED_GIT_WRITER_CAP_FD": str(forged_cap_fd),
        }
        forged = subprocess.run(
            ["git", "update-ref", "refs/heads/main", candidate, base],
            cwd=repo,
            env=env,
            pass_fds=(forged_fd, forged_cap_fd),
            capture_output=True,
            text=True,
            check=False,
        )
        assert forged.returncode != 0
        assert _git(repo, "rev-parse", "refs/heads/main").stdout.strip() == base
    finally:
        os.close(forged_fd)
        os.close(forged_cap_fd)


def test_fake_path_python_cannot_replace_installed_verifier(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    candidate = _candidate_commit(repo, base, "fake interpreter")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o755)
    attempt = subprocess.run(
        ["/usr/bin/git", "update-ref", "refs/heads/main", candidate, base],
        cwd=repo,
        env={**os.environ, "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert attempt.returncode != 0
    assert _git(repo, "rev-parse", "refs/heads/main").stdout.strip() == base


def test_main_worktree_head_pseudoref_requires_lease(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    candidate = _candidate_commit(repo, base, "detach attempt")
    detached = _git(
        repo,
        "update-ref", "--no-deref", "HEAD", candidate, base,
        check=False,
    )
    assert detached.returncode != 0
    assert _git(repo, "symbolic-ref", "HEAD").stdout.strip() == "refs/heads/main"


def test_non_main_branch_ref_is_not_subject_to_main_lease(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    linked = tmp_path / "side-worktree"
    _git(repo, "worktree", "add", "-b", "side", str(linked))
    (linked / "owned.txt").write_text("side\n", encoding="utf-8")
    _git(linked, "add", "owned.txt")
    side = _git(linked, "commit", "--no-verify", "-m", "side commit", check=False)
    assert side.returncode == 0, side.stderr


def test_installer_from_linked_worktree_targets_common_hook_directory(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "install-repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "hook-install@example.com")
    _git(repo, "config", "user.name", "Hook Install Test")
    source_dir = repo / "scripts" / "git_hooks"
    source_dir.mkdir(parents=True)
    (repo / "src" / "volpred" / "ops").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "git_writer_lock.py", repo / "scripts" / "git_writer_lock.py")
    shutil.copy2(
        ROOT / "src" / "volpred" / "ops" / "git_writer_lock.py",
        repo / "src" / "volpred" / "ops" / "git_writer_lock.py",
    )
    for name in (
        "install.sh",
        "pre-push",
        "pre-commit",
        "prepare-commit-msg",
        "reference-transaction",
        "git-writer-lease-verify.py",
    ):
        shutil.copy2(ROOT / "scripts" / "git_hooks" / name, source_dir / name)
    _git(repo, "add", "scripts", "src")
    _git(repo, "commit", "-m", "hook sources")
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-b", "hook-install-side", str(linked))

    refused = subprocess.run(
        ["bash", str(linked / "scripts/git_hooks/install.sh")],
        cwd=linked,
        capture_output=True,
        text=True,
        check=False,
    )
    assert refused.returncode != 0
    assert "canonical main root" in refused.stderr

    installed = subprocess.run(
        ["bash", str(repo / "scripts/git_hooks/install.sh")],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert installed.returncode == 0, installed.stderr
    common_dir = Path(
        _git(linked, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    )
    assert (common_dir / "hooks" / "reference-transaction").is_file()
    assert not (linked / ".git" / "hooks").exists()


def test_installer_replaces_live_gate_atomically() -> None:
    source = (ROOT / "scripts" / "git_hooks" / "install.sh").read_text(encoding="utf-8")
    assert 'tmp="$HOOK_DIR/.$1.tmp.$$"' in source
    assert '/bin/mv -f "$tmp" "$dst"' in source
    assert 'for h in git-writer-lease-verify.py' in source
    assert source.index("git-writer-lease-verify.py") < source.rindex("reference-transaction")
