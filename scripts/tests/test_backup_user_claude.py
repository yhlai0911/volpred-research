from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


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
