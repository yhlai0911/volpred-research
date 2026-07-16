"""Cross-process regression for the one canonical Git-writer lease."""
from __future__ import annotations

import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from volpred.ops.git_writer_lock import (  # noqa: E402
    LOCK_BASENAME,
    GitWriterLockTimeout,
    git_writer_lock,
    git_writer_lock_path,
    is_registered_linked_worktree,
)

CLI = ROOT / "scripts" / "git_writer_lock.py"


def _run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), cwd=repo, capture_output=True, text=True, check=check
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-b", "main", "-q")
    _run(repo, "git", "config", "user.name", "Lock Test")
    _run(repo, "git", "config", "user.email", "lock@example.invalid")
    (repo / "seed.txt").write_text("seed\n")
    _run(repo, "git", "add", "seed.txt")
    _run(repo, "git", "commit", "-qm", "seed")
    return repo


def _cli(repo: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=check,
    )


def test_main_and_linked_worktree_share_one_stable_lock_inode(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    worktree = tmp_path / "linked"
    _run(repo, "git", "worktree", "add", "-qb", "worktree-agent-lock-test", str(worktree))

    main_lock = git_writer_lock_path(repo)
    linked_lock = git_writer_lock_path(worktree)
    assert main_lock == linked_lock
    assert main_lock.name == LOCK_BASENAME
    with git_writer_lock(repo, actor="inode-test", timeout_s=0):
        assert main_lock.stat().st_ino == linked_lock.stat().st_ino
        assert stat.S_IMODE(main_lock.stat().st_mode) == 0o600
    assert is_registered_linked_worktree(repo, worktree)
    assert not is_registered_linked_worktree(repo, repo)


def test_only_an_active_outer_holder_can_validate_inherited_lease(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    bare = _cli(repo, "validate-inherited", "--repo", str(repo))
    assert bare.returncode == 1

    nested = _cli(
        repo,
        "run",
        "--repo",
        str(repo),
        "--actor",
        "outer-test",
        "--",
        sys.executable,
        str(CLI),
        "validate-inherited",
        "--repo",
        str(repo),
        "--actor",
        "inner-test",
    )
    assert nested.returncode == 0, nested.stderr

    fake_env = os.environ.copy()
    fake_env["VOLPRED_GIT_WRITER_LOCK_TOKEN"] = "forged"
    fake_env["VOLPRED_GIT_WRITER_LOCK_PATH"] = str(git_writer_lock_path(repo))
    forged = subprocess.run(
        [sys.executable, str(CLI), "validate-inherited", "--repo", str(repo)],
        cwd=repo,
        env=fake_env,
        capture_output=True,
        text=True,
    )
    assert forged.returncode == 1


def test_relative_repo_argument_resolves_from_callers_cwd(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    invoked = _cli(
        repo,
        "run",
        "--repo",
        ".",
        "--actor",
        "relative-repo-test",
        "--",
        "/usr/bin/true",
    )
    assert invoked.returncode == 0, invoked.stderr
    assert git_writer_lock_path(repo).exists()


def test_busy_writer_fails_closed_then_both_commits_land_linearly(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    acquired = tmp_path / "a-acquired"
    release = tmp_path / "release-a"
    holder_script = (
        f"touch {acquired!s}; "
        f"while [ ! -e {release!s} ]; do sleep 0.02; done; "
        "printf 'A\\n' > a.txt; git add -- a.txt; git commit -qm writer-a -- a.txt"
    )
    holder = subprocess.Popen(
        [
            sys.executable,
            str(CLI),
            "run",
            "--repo",
            str(repo),
            "--actor",
            "test-writer-a",
            "--timeout",
            "5",
            "--",
            "/bin/sh",
            "-c",
            holder_script,
        ],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while not acquired.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert acquired.exists(), holder.communicate(timeout=1)

    (repo / "b.txt").write_text("B\n")
    before_head = _run(repo, "git", "rev-parse", "HEAD").stdout.strip()
    before_status = _run(repo, "git", "status", "--porcelain=v1", "-uall").stdout
    blocked = _cli(
        repo,
        "commit",
        "--repo",
        str(repo),
        "--actor",
        "test-writer-b",
        "--timeout",
        "0",
        "--message",
        "writer-b",
        "--",
        "b.txt",
    )
    assert blocked.returncode == 75
    assert "BUSY" in blocked.stderr
    assert _run(repo, "git", "rev-parse", "HEAD").stdout.strip() == before_head
    assert _run(repo, "git", "status", "--porcelain=v1", "-uall").stdout == before_status

    release.touch()
    stdout, stderr = holder.communicate(timeout=10)
    assert holder.returncode == 0, stdout + stderr
    committed_b = _cli(
        repo,
        "commit",
        "--repo",
        str(repo),
        "--actor",
        "test-writer-b",
        "--timeout",
        "5",
        "--message",
        "writer-b",
        "--",
        "b.txt",
    )
    assert committed_b.returncode == 0, committed_b.stderr
    assert _run(repo, "git", "rev-list", "--count", "HEAD").stdout.strip() == "3"
    assert _run(repo, "git", "log", "-2", "--format=%s").stdout.splitlines() == [
        "writer-b",
        "writer-a",
    ]
    git_dir = Path(_run(repo, "git", "rev-parse", "--absolute-git-dir").stdout.strip())
    assert not (git_dir / "AUTO_MERGE").exists()
    assert not (git_dir / "MERGE_HEAD").exists()
    assert not (git_dir / "index.lock").exists()
    assert not _run(repo, "git", "ls-files", "-u").stdout


def test_parent_sigkill_does_not_release_lease_while_managed_child_runs(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    child_pid_path = tmp_path / "child-pid"
    release = tmp_path / "release-child"
    command = (
        f"echo $$ > {child_pid_path!s}; "
        f"while [ ! -e {release!s} ]; do sleep 0.02; done"
    )
    wrapper = subprocess.Popen(
        [
            sys.executable,
            str(CLI),
            "run",
            "--repo",
            str(repo),
            "--actor",
            "crash-parent",
            "--",
            "/bin/sh",
            "-c",
            command,
        ],
        cwd=repo,
    )
    deadline = time.monotonic() + 5
    while not child_pid_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert child_pid_path.exists()
    child_pid = int(child_pid_path.read_text().strip())

    os.kill(wrapper.pid, signal.SIGKILL)
    wrapper.wait(timeout=5)
    assert wrapper.returncode == -signal.SIGKILL
    os.kill(child_pid, 0)  # managed command survived and still owns the FD

    busy = _cli(
        repo,
        "run",
        "--repo",
        str(repo),
        "--actor",
        "contender",
        "--timeout",
        "0",
        "--",
        "/usr/bin/true",
    )
    assert busy.returncode == 75

    release.touch()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        available = _cli(
            repo,
            "run",
            "--repo",
            str(repo),
            "--actor",
            "after-child",
            "--timeout",
            "0",
            "--",
            "/usr/bin/true",
        )
        if available.returncode == 0:
            break
        time.sleep(0.02)
    else:
        raise AssertionError("child exit did not release inherited kernel lease")


def test_parent_sigterm_is_forwarded_and_releases_only_after_tree_exits(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    child_pid_path = tmp_path / "term-child-pid"
    wrapper = subprocess.Popen(
        [
            sys.executable,
            str(CLI),
            "run", "--repo", str(repo), "--actor", "term-parent", "--",
            "/bin/sh", "-c", f"echo $$ > {child_pid_path}; sleep 30",
        ],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 5
    while not child_pid_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert child_pid_path.exists()
    os.kill(wrapper.pid, signal.SIGTERM)
    stdout, stderr = wrapper.communicate(timeout=5)
    assert wrapper.returncode == 128 + signal.SIGTERM, stdout + stderr
    assert _cli(
        repo,
        "run", "--repo", str(repo), "--actor", "after-term",
        "--timeout", "0", "--", "/usr/bin/true",
    ).returncode == 0


def test_exact_path_commit_preserves_foreign_index_and_worktree(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    foreign = repo / "foreign.txt"
    foreign.write_text("base\n")
    _run(repo, "git", "add", "foreign.txt")
    _run(repo, "git", "commit", "-qm", "add foreign")

    foreign.write_text("foreign staged\n")
    _run(repo, "git", "add", "foreign.txt")
    staged_blob = _run(repo, "git", "show", ":foreign.txt").stdout
    foreign.write_text("foreign working\n")
    (repo / "owned.txt").write_text("owned\n")

    commit = _cli(
        repo,
        "commit",
        "--repo",
        str(repo),
        "--actor",
        "exact-owner",
        "--message",
        "owned only",
        "--",
        "owned.txt",
    )
    assert commit.returncode == 0, commit.stderr
    assert _run(repo, "git", "show", "--format=", "--name-only", "HEAD").stdout.strip() == "owned.txt"
    assert _run(repo, "git", "show", ":foreign.txt").stdout == staged_blob
    assert foreign.read_text() == "foreign working\n"


def test_same_process_nested_lease_borrows_without_unlocking_outer(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with git_writer_lock(repo, actor="outer", timeout_s=0) as outer:
        with git_writer_lock(repo, actor="nested", timeout_s=0) as nested:
            assert nested.token == outer.token
            blocked = _cli(
                repo,
                "run", "--repo", str(repo), "--actor", "external",
                "--timeout", "0", "--", "/usr/bin/true",
            )
            assert blocked.returncode == 75
        still_blocked = _cli(
            repo,
            "run", "--repo", str(repo), "--actor", "external-2",
            "--timeout", "0", "--", "/usr/bin/true",
        )
        assert still_blocked.returncode == 75
    assert _cli(
        repo,
        "run", "--repo", str(repo), "--actor", "after-outer",
        "--timeout", "0", "--", "/usr/bin/true",
    ).returncode == 0


def test_forked_child_cannot_release_or_borrow_parent_lease(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with git_writer_lock(repo, actor="fork-parent", timeout_s=0):
        child = os.fork()
        if child == 0:  # pragma: no cover - assertion observed via exit status
            try:
                with git_writer_lock(repo, actor="fork-child", timeout_s=0):
                    os._exit(3)
            except GitWriterLockTimeout:
                os._exit(0)
            except BaseException:
                os._exit(4)
        _, status = os.waitpid(child, 0)
        assert os.waitstatus_to_exitcode(status) == 0
        metadata = git_writer_lock_path(repo).read_text(encoding="utf-8")
        assert '"state": "held"' in metadata
        assert '"actor": "fork-parent"' in metadata


def test_nonfinite_timeout_is_rejected_instead_of_waiting_forever(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    started = time.monotonic()
    rejected = _cli(
        repo,
        "run", "--repo", str(repo), "--actor", "nan-timeout",
        "--timeout", "nan", "--", "/usr/bin/true",
    )
    assert rejected.returncode == 2
    assert time.monotonic() - started < 2
    assert "finite" in rejected.stderr


def test_run_kills_background_descendants_before_releasing_metadata(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    child_pid_path = tmp_path / "background-pid"
    started = time.monotonic()
    ran = _cli(
        repo,
        "run", "--repo", str(repo), "--actor", "background-test",
        "--timeout", "2", "--", "/bin/sh", "-c",
        f"sleep 30 >/dev/null 2>&1 & echo $! > {child_pid_path}",
    )
    assert ran.returncode == 0, ran.stderr
    assert time.monotonic() - started < 4
    assert child_pid_path.exists()
    assert _cli(
        repo,
        "run", "--repo", str(repo), "--actor", "after-background",
        "--timeout", "0", "--", "/usr/bin/true",
    ).returncode == 0
    assert '"state": "released"' in git_writer_lock_path(repo).read_text()


def test_run_timeout_kills_foreground_tree_and_returns_124(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    started = time.monotonic()
    timed_out = _cli(
        repo,
        "run", "--repo", str(repo), "--actor", "command-timeout",
        "--command-timeout", "0.1", "--", "/bin/sh", "-c", "sleep 30",
    )
    assert timed_out.returncode == 124
    assert time.monotonic() - started < 4
    assert _cli(
        repo,
        "run", "--repo", str(repo), "--actor", "after-timeout",
        "--timeout", "0", "--", "/usr/bin/true",
    ).returncode == 0


def test_commit_rejects_magic_directories_and_outside_paths(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "a1.txt").write_text("a1\n")
    (repo / "a2.txt").write_text("a2\n")
    deleted_dir = repo / "deleted-dir"
    deleted_dir.mkdir()
    (deleted_dir / "one.txt").write_text("one\n")
    (deleted_dir / "two.txt").write_text("two\n")
    _run(repo, "git", "add", "deleted-dir")
    _run(repo, "git", "commit", "-qm", "tracked directory")
    for child in deleted_dir.iterdir():
        child.unlink()
    deleted_dir.rmdir()
    for unsafe in (
        ":(glob)a*.txt",
        ".",
        ".git/index",
        "deleted-dir",
        str(tmp_path / "outside.txt"),
    ):
        result = _cli(
            repo,
            "commit", "--repo", str(repo), "--actor", "unsafe-path",
            "--message", "must reject", "--", unsafe,
        )
        assert result.returncode == 2, (unsafe, result.stderr)
    assert _run(repo, "git", "rev-list", "--count", "HEAD").stdout.strip() == "2"
    assert not _run(repo, "git", "diff", "--cached", "--name-only").stdout


def test_commit_refuses_prestaged_target_without_changing_either_layer(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    target = repo / "seed.txt"
    target.write_text("foreign staged\n")
    _run(repo, "git", "add", "seed.txt")
    staged = _run(repo, "git", "show", ":seed.txt").stdout
    target.write_text("foreign working\n")
    before = _run(repo, "git", "rev-parse", "HEAD").stdout.strip()
    result = _cli(
        repo,
        "commit", "--repo", str(repo), "--actor", "collision",
        "--message", "must reject", "--", "seed.txt",
    )
    assert result.returncode == 2
    assert _run(repo, "git", "rev-parse", "HEAD").stdout.strip() == before
    assert _run(repo, "git", "show", ":seed.txt").stdout == staged
    assert target.read_text() == "foreign working\n"


def test_commit_helper_rejects_linked_worktree_and_detached_main(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    linked = tmp_path / "linked"
    _run(repo, "git", "worktree", "add", "-qb", "agent-side", str(linked))
    (linked / "side.txt").write_text("side\n")
    side = _cli(
        linked,
        "commit", "--repo", str(linked), "--actor", "wrong-checkout",
        "--message", "must reject", "--", "side.txt",
    )
    assert side.returncode == 2
    assert "canonical Git writer requires the main checkout" in side.stderr

    _run(repo, "git", "checkout", "--detach", "-q", "HEAD")
    (repo / "detached.txt").write_text("detached\n")
    detached = _cli(
        repo,
        "commit", "--repo", str(repo), "--actor", "detached",
        "--message", "must reject", "--", "detached.txt",
    )
    assert detached.returncode == 2
    assert "symbolic HEAD" in detached.stderr


def test_failed_commit_hook_restores_owned_index_but_keeps_worktree(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    target = repo / "owned.txt"
    target.write_text("owned\n")
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    result = _cli(
        repo,
        "commit", "--repo", str(repo), "--actor", "hook-failure",
        "--message", "blocked", "--", "owned.txt",
    )
    assert result.returncode != 0
    assert not _run(repo, "git", "diff", "--cached", "--name-only").stdout
    assert target.read_text() == "owned\n"


def test_repo_owned_writers_route_through_canonical_lease() -> None:
    expected = {
        "src/volpred/ops/scheduled_writer_commit.py": "git_writer_lock(",
        "scripts/dispatch_supervisor/phase_z.py": "git_writer_lock(",
        "scripts/reap_orphan_deliverables.py": "git_writer_lock(",
        "scripts/merge_worktree.sh": "scripts/git_writer_lock.py\" run",
        "scripts/codex_loop.sh": "scripts/git_writer_lock.py\" commit",
        "scripts/cron_backfill_work_log_from_commits.sh": "scripts/git_writer_lock.py\" commit",
        "scripts/cron_hourly_dispatch.sh": "scripts/git_writer_lock.py\" run",
        "src/volpred/ops/rollback.py": "git_writer_lock(",
        "scripts/reclaim_stale_worktrees.py": "git_writer_lock(",
    }
    for rel, needle in expected.items():
        assert needle in (ROOT / rel).read_text(), f"{rel} bypasses canonical Git lease"
    canonical_writers = {
        "src/volpred/ops/scheduled_writer_commit.py",
        "scripts/dispatch_supervisor/phase_z.py",
        "scripts/reap_orphan_deliverables.py",
        "src/volpred/ops/rollback.py",
    }
    for rel in canonical_writers:
        assert "require_canonical_main_checkout" in (ROOT / rel).read_text(), (
            f"{rel} holds the lease but can publish to side/detached HEAD"
        )
    phase_z = (ROOT / "scripts/dispatch_supervisor/phase_z.py").read_text()
    assert '"update-ref", "refs/heads/main"' in phase_z
    merge = (ROOT / "scripts/merge_worktree.sh").read_text()
    assert '/usr/bin/python3 "$MAIN_DIR/scripts/git_writer_lock.py"' in merge
    assert '[[ "$_mdir_head" != "main" ]]' in merge
    worker = (ROOT / "scripts/dispatch_supervisor/worker.py").read_text()
    assert '"--add-dir", str(PROJECT_ROOT)' in worker
    assert '"--settings", str(PROJECT_ROOT / ".claude" / "settings.json")' in worker
    pretool = (ROOT / ".claude/hooks/pretooluse-bash-optimizer.sh").read_text()
    assert "git_mutation_guard.py" in pretool
    telegram = (ROOT / "scripts/telegram_responder.sh").read_text()
    assert 'git -C "$RESPONDER_REAL" rev-parse --show-toplevel' in telegram
    assert 'AUTO_MEMORY_DIR="/Users/yhlai0911/.claude/projects/-Users-yhlai0911-volpred-research/memory"' in telegram
    assert ".autoMemoryDirectory = $directory" in telegram
    assert '--add-dir "$REPO_ROOT" --add-dir "$AUTO_MEMORY_DIR"' in telegram
    assert '--settings "$RESPONDER_SETTINGS_JSON"' in telegram
    assert "telegram_memory.py list" not in telegram
    assert "telegram_memory.py add" not in telegram
    attributes = ROOT / ".gitattributes"
    assert not attributes.exists() or "merge=ours" not in attributes.read_text()
    if not attributes.exists():
        effective = _run(
            ROOT,
            "git", "check-attr", "merge", "--",
            "storage/next_tasks.json", "storage/work_log.json", "storage/reports/feed.json",
        ).stdout
        assert "merge: ours" not in effective, (
            "working-tree deletion is not enough; .gitattributes must leave the index/HEAD"
        )
    guard = (ROOT / "scripts/git_conflict_guard.py").read_text()
    assert "merge.ours.driver" not in guard
    assert '_run(["reset"' not in guard
    assert '_run(["checkout"' not in guard
    scheduler_text = (ROOT / "scripts/dispatch_supervisor/scheduler.py").read_text()
    assert "launcher_cwd=" in scheduler_text and "_slot_workdir" in scheduler_text
    telegram_text = (ROOT / "scripts/telegram_responder.sh").read_text()
    assert "RESPONDER_WORKDIR" in telegram_text
    assert 'cd "$RESPONDER_WORKDIR"' in telegram_text
