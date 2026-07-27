from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


SOURCE_SCRIPT = Path(__file__).resolve().parents[1] / "backup_user_claude.sh"


def _sandbox_script(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "backup_user_claude.sh"
    shutil.copy2(SOURCE_SCRIPT, script)
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
    assert "outside approved roots" in result.stderr
    assert not (script.parent.parent / "ops" / "claude_user_backup" / "skills").exists()
