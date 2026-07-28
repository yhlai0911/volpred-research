"""Regression for the one-time, restartable runtime-signal Git migration."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "scripts" / "migrate_legacy_retirement_signal_git_ownership.py"
SIGNAL_DIR = Path("storage/ops/legacy_retirement_signals")


def _run(
    repo: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=repo,
        capture_output=True,
        text=True,
        check=check,
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-b", "main", "-q")
    _run(repo, "git", "config", "user.name", "Migration Test")
    _run(repo, "git", "config", "user.email", "migration@example.invalid")
    signal_dir = repo / SIGNAL_DIR
    signal_dir.mkdir(parents=True)
    for name in (
        ".materialize.lock",
        "duplicate_effect.json",
        "legacy_business_fire.json",
        "orphan_work.json",
        "silent_loss.json",
    ):
        target = signal_dir / name
        target.write_text(f"{name}: tracked\n", encoding="utf-8")
        target.chmod(0o600)
    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-qm", "track legacy runtime signals")
    (repo / ".gitignore").write_text(
        "storage/ops/legacy_retirement_signals/\n",
        encoding="utf-8",
    )
    _run(repo, "git", "add", ".gitignore")
    _run(repo, "git", "commit", "-qm", "declare signal runtime ownership")
    return repo


def test_migration_preserves_live_signals_and_is_restartable(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    signal_dir = repo / SIGNAL_DIR
    before: dict[str, tuple[bytes, int]] = {}
    for target in sorted(signal_dir.iterdir()):
        if target.name == ".batch.lock":
            continue
        target.write_text(f"{target.name}: live\n", encoding="utf-8")
        target.chmod(0o600)
        before[target.name] = (
            target.read_bytes(),
            stat.S_IMODE(target.stat().st_mode),
        )
    foreign = repo / "foreign.txt"
    foreign.write_text("foreign staged\n", encoding="utf-8")
    _run(repo, "git", "add", "foreign.txt")
    foreign.write_text("foreign working\n", encoding="utf-8")
    staged_foreign = _run(repo, "git", "show", ":foreign.txt").stdout

    first = _run(
        repo,
        sys.executable,
        str(MIGRATION),
        "--repo",
        str(repo),
        "--actor",
        "migration-test",
    )

    report = json.loads(first.stdout)
    assert report["status"] == "migrated"
    assert report["tracked_before"] == sorted(
        f"{SIGNAL_DIR.as_posix()}/{name}" for name in before
    )
    assert report["tracked_after"] == []
    assert _run(
        repo,
        "git",
        "ls-files",
        "--",
        SIGNAL_DIR.as_posix(),
    ).stdout == ""
    for name, identity in before.items():
        target = signal_dir / name
        assert (
            target.read_bytes(),
            stat.S_IMODE(target.stat().st_mode),
        ) == identity
    assert _run(repo, "git", "show", ":foreign.txt").stdout == staged_foreign
    assert foreign.read_text(encoding="utf-8") == "foreign working\n"

    second = _run(
        repo,
        sys.executable,
        str(MIGRATION),
        "--repo",
        str(repo),
        "--actor",
        "migration-test",
    )
    repeated = json.loads(second.stdout)
    assert repeated["status"] == "already_migrated"
    assert repeated["head_before"] == repeated["head_after"]


def test_already_migrated_requires_committed_ignore_policy(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-b", "main", "-q")
    _run(repo, "git", "config", "user.name", "Migration Test")
    _run(repo, "git", "config", "user.email", "migration@example.invalid")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _run(repo, "git", "add", "seed.txt")
    _run(repo, "git", "commit", "-qm", "seed")
    info_exclude = repo / ".git" / "info" / "exclude"
    info_exclude.write_text(
        "storage/ops/legacy_retirement_signals/\n",
        encoding="utf-8",
    )

    blocked = _run(
        repo,
        sys.executable,
        str(MIGRATION),
        "--repo",
        str(repo),
        "--actor",
        "migration-test",
        check=False,
    )

    assert blocked.returncode == 2
    assert "committed ignore" in blocked.stderr


def test_already_migrated_rejects_symlinked_signal_directory(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-b", "main", "-q")
    _run(repo, "git", "config", "user.name", "Migration Test")
    _run(repo, "git", "config", "user.email", "migration@example.invalid")
    (repo / ".gitignore").write_text(
        "storage/ops/legacy_retirement_signals/\n",
        encoding="utf-8",
    )
    _run(repo, "git", "add", ".gitignore")
    _run(repo, "git", "commit", "-qm", "declare signal runtime ownership")
    external = tmp_path / "external-signals"
    external.mkdir()
    external_signal = external / "silent_loss.json"
    external_signal.write_text("external live\n", encoding="utf-8")
    signal_dir = repo / SIGNAL_DIR
    signal_dir.parent.mkdir(parents=True)
    signal_dir.symlink_to(external, target_is_directory=True)

    blocked = _run(
        repo,
        sys.executable,
        str(MIGRATION),
        "--repo",
        str(repo),
        "--actor",
        "migration-test",
        check=False,
    )

    assert blocked.returncode == 2
    assert "traverse symlink" in blocked.stderr
    assert external_signal.read_text(encoding="utf-8") == "external live\n"


def test_clean_checkout_rerun_materializes_only_ignored_batch_lock(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-b", "main", "-q")
    _run(repo, "git", "config", "user.name", "Migration Test")
    _run(repo, "git", "config", "user.email", "migration@example.invalid")
    (repo / ".gitignore").write_text(
        "storage/ops/legacy_retirement_signals/\n",
        encoding="utf-8",
    )
    _run(repo, "git", "add", ".gitignore")
    _run(repo, "git", "commit", "-qm", "declare signal runtime ownership")

    completed = _run(
        repo,
        sys.executable,
        str(MIGRATION),
        "--repo",
        str(repo),
        "--actor",
        "migration-test",
    )

    report = json.loads(completed.stdout)
    assert report["status"] == "already_migrated"
    assert report["tracked_before"] == []
    assert (
        repo / SIGNAL_DIR / ".batch.lock"
    ).is_file()
