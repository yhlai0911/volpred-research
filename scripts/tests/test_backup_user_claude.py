from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import snapshot_skill_tree as snapshot_module


SOURCE_SCRIPT = Path(__file__).resolve().parents[1] / "backup_user_claude.sh"
SNAPSHOT_SCRIPT = Path(__file__).resolve().parents[1] / "snapshot_skill_tree.py"


def _sandbox_script(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "backup_user_claude.sh"
    shutil.copy2(SOURCE_SCRIPT, script)
    shutil.copy2(SNAPSHOT_SCRIPT, scripts / "snapshot_skill_tree.py")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    home = tmp_path / "home"
    home.mkdir()
    return script, home


def _run(script: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        ["/bin/bash", str(script)],
        cwd=script.parent.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_skill_snapshot_dereferences_approved_agent_skill_links(
    tmp_path: Path,
) -> None:
    script, home = _sandbox_script(tmp_path)
    agent_skill = home / ".agents" / "skills" / "ask-matt"
    agent_skill.mkdir(parents=True)
    (agent_skill / "SKILL.md").write_text("router\n", encoding="utf-8")
    claude_skills = home / ".claude" / "skills"
    claude_skills.mkdir(parents=True)
    (claude_skills / "ask-matt").symlink_to(agent_skill, target_is_directory=True)

    result = _run(script, home)

    snapshot = script.parent.parent / "ops" / "claude_user_backup" / "skills" / "ask-matt"
    assert result.returncode == 0, result.stderr
    assert snapshot.is_dir()
    assert not snapshot.is_symlink()
    assert (snapshot / "SKILL.md").read_text(encoding="utf-8") == "router\n"
    assert list(snapshot.rglob("*"))
    assert not any(path.is_symlink() for path in snapshot.rglob("*"))


def test_skill_snapshot_refuses_symlink_outside_approved_roots(
    tmp_path: Path,
) -> None:
    script, home = _sandbox_script(tmp_path)
    secret = home / "secret.txt"
    secret.write_text("do not snapshot\n", encoding="utf-8")
    claude_skills = home / ".claude" / "skills"
    claude_skills.mkdir(parents=True)
    (claude_skills / "unsafe").symlink_to(secret)

    result = _run(script, home)

    assert result.returncode != 0
    assert "escapes approved roots" in result.stderr
    assert not (script.parent.parent / "ops" / "claude_user_backup" / "skills").exists()


def test_skill_snapshot_refuses_nested_escape_inside_approved_agent_skill(
    tmp_path: Path,
) -> None:
    script, home = _sandbox_script(tmp_path)
    secret = home / "secret.txt"
    secret.write_text("do not snapshot\n", encoding="utf-8")
    agent_skill = home / ".agents" / "skills" / "ask-matt"
    agent_skill.mkdir(parents=True)
    (agent_skill / "nested-secret").symlink_to(secret)
    claude_skills = home / ".claude" / "skills"
    claude_skills.mkdir(parents=True)
    (claude_skills / "ask-matt").symlink_to(agent_skill, target_is_directory=True)

    result = _run(script, home)

    assert result.returncode != 0
    assert "escapes approved roots" in result.stderr
    assert not (script.parent.parent / "ops" / "claude_user_backup" / "skills").exists()


def test_skill_snapshot_refuses_non_skill_file_inside_claude_home(
    tmp_path: Path,
) -> None:
    script, home = _sandbox_script(tmp_path)
    claude = home / ".claude"
    claude_skills = claude / "skills"
    claude_skills.mkdir(parents=True)
    settings = claude / "settings.json"
    settings.write_text('{"token": "secret"}\n', encoding="utf-8")
    (claude_skills / "unsafe").symlink_to(settings)

    result = _run(script, home)

    assert result.returncode != 0
    assert "escapes approved roots" in result.stderr


def test_failed_snapshot_removes_preexisting_symlink_destination(
    tmp_path: Path,
) -> None:
    script, home = _sandbox_script(tmp_path)
    secret = home / "secret.txt"
    secret.write_text("do not snapshot\n", encoding="utf-8")
    claude_skills = home / ".claude" / "skills"
    claude_skills.mkdir(parents=True)
    (claude_skills / "unsafe").symlink_to(secret)
    destination = script.parent.parent / "ops" / "claude_user_backup" / "skills"
    destination.parent.mkdir(parents=True)
    destination.symlink_to(secret)

    result = _run(script, home)

    assert result.returncode != 0
    assert not destination.exists()
    assert not destination.is_symlink()


def test_source_skill_root_cannot_approve_its_own_external_symlink(
    tmp_path: Path,
) -> None:
    script, home = _sandbox_script(tmp_path)
    external = home / "secret-dir"
    external.mkdir()
    (external / "secret.txt").write_text("do not snapshot\n", encoding="utf-8")
    claude = home / ".claude"
    claude.mkdir()
    (claude / "skills").symlink_to(external, target_is_directory=True)

    result = _run(script, home)

    assert result.returncode != 0
    assert "source skill root must not be a symlink" in result.stderr
    assert not (script.parent.parent / "ops" / "claude_user_backup" / "skills").exists()


def test_ancestor_swap_cannot_redirect_descriptor_traversal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "home" / ".claude" / "skills"
    child = source / "ask-matt"
    child.mkdir(parents=True)
    (child / "SKILL.md").write_text("safe\n", encoding="utf-8")
    external = tmp_path / "secret-dir"
    external.mkdir()
    (external / "SKILL.md").write_text("secret\n", encoding="utf-8")
    destination = tmp_path / "repo" / "ops" / "claude_user_backup" / "skills"
    temp_root = tmp_path / "repo" / ".git"
    child_inode = child.stat().st_ino
    real_listdir = os.listdir
    swapped = False

    def racing_listdir(fd):
        nonlocal swapped
        names = real_listdir(fd)
        if not swapped and os.fstat(fd).st_ino == child_inode:
            child.rename(source / "ask-matt.original")
            child.symlink_to(external, target_is_directory=True)
            swapped = True
        return names

    monkeypatch.setattr(snapshot_module.os, "listdir", racing_listdir)

    with pytest.raises(snapshot_module.SnapshotError):
        snapshot_module.snapshot_skill_tree(
            source,
            destination,
            approved_roots=[source],
            temp_root=temp_root,
        )

    assert swapped is True
    assert not destination.exists()


def test_special_file_is_rejected_without_opening_it(tmp_path: Path) -> None:
    script, home = _sandbox_script(tmp_path)
    claude_skills = home / ".claude" / "skills"
    claude_skills.mkdir(parents=True)
    os.mkfifo(claude_skills / "unsafe.fifo")

    result = _run(script, home)

    assert result.returncode != 0
    assert "non-regular skill entry" in result.stderr


def test_failed_candidate_preserves_previous_valid_snapshot(tmp_path: Path) -> None:
    script, home = _sandbox_script(tmp_path)
    secret = home / "secret.txt"
    secret.write_text("do not snapshot\n", encoding="utf-8")
    claude_skills = home / ".claude" / "skills"
    claude_skills.mkdir(parents=True)
    (claude_skills / "unsafe").symlink_to(secret)
    destination = script.parent.parent / "ops" / "claude_user_backup" / "skills"
    destination.mkdir(parents=True)
    (destination / "previous.txt").write_text("last good\n", encoding="utf-8")

    result = _run(script, home)

    assert result.returncode != 0
    assert (destination / "previous.txt").read_text(encoding="utf-8") == "last good\n"
    assert not destination.is_symlink()


def test_skill_directory_cycle_is_rejected(tmp_path: Path) -> None:
    script, home = _sandbox_script(tmp_path)
    claude_skills = home / ".claude" / "skills"
    claude_skills.mkdir(parents=True)
    (claude_skills / "loop").symlink_to(claude_skills, target_is_directory=True)

    result = _run(script, home)

    assert result.returncode != 0
    assert "cycle detected" in result.stderr
