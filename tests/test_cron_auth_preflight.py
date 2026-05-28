from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cron_hourly_dispatch.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _base_env(tmp_path: Path, claude_bin: Path, uv_bin: Path, zshrc: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "VOLPRED_REPO_ROOT": str(tmp_path),
            "VOLPRED_HOME_DIR": str(tmp_path / ".volpred"),
            "HOURLY_LOG_PATH": str(tmp_path / ".volpred" / "logs" / "hourly_dispatch.log"),
            "CLAUDE_BIN": str(claude_bin),
            "UV_BIN": str(uv_bin),
            "ZSHRC_PATH": str(zshrc),
            "HOURLY_PREFLIGHT_ONLY": "1",
            "HOME": str(tmp_path),
        }
    )
    return env


def test_auth_preflight_passes_without_fallback(tmp_path: Path) -> None:
    claude = tmp_path / "claude"
    uv = tmp_path / "uv"
    zshrc = tmp_path / ".zshrc"

    _write_executable(
        claude,
        "#!/bin/bash\n"
        "echo 'Hi'\n"
        "exit 0\n",
    )
    _write_executable(
        uv,
        "#!/bin/bash\n"
        "echo \"$@\" > \"$HOME/uv_called.txt\"\n",
    )
    zshrc.write_text("# no-op\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=_base_env(tmp_path, claude, uv, zshrc),
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert not (tmp_path / "uv_called.txt").exists()
    log = (tmp_path / ".volpred" / "logs" / "hourly_dispatch.log").read_text(encoding="utf-8")
    assert "[AUTH-PREFLIGHT] ok" in log


def test_auth_preflight_recovers_after_sourcing_zshrc(tmp_path: Path) -> None:
    claude = tmp_path / "claude"
    uv = tmp_path / "uv"
    zshrc = tmp_path / ".zshrc"

    _write_executable(
        claude,
        "#!/bin/bash\n"
        "if [ \"${AUTH_OK:-0}\" = \"1\" ]; then\n"
        "  echo 'Hi'\n"
        "  exit 0\n"
        "fi\n"
        "echo 'Not logged in · Please run /login' >&2\n"
        "exit 1\n",
    )
    _write_executable(
        uv,
        "#!/bin/bash\n"
        "echo \"$@\" > \"$HOME/uv_called.txt\"\n",
    )
    zshrc.write_text("export AUTH_OK=1\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=_base_env(tmp_path, claude, uv, zshrc),
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert not (tmp_path / "uv_called.txt").exists()
    log = (tmp_path / ".volpred" / "logs" / "hourly_dispatch.log").read_text(encoding="utf-8")
    assert "[AUTH-PREFLIGHT] recovered after sourcing zshrc" in log


def test_auth_preflight_sends_actionable_alert_on_double_failure(tmp_path: Path) -> None:
    claude = tmp_path / "claude"
    uv = tmp_path / "uv"
    zshrc = tmp_path / ".zshrc"

    _write_executable(
        claude,
        "#!/bin/bash\n"
        "echo 'Not logged in · Please run /login' >&2\n"
        "exit 1\n",
    )
    _write_executable(
        uv,
        "#!/bin/bash\n"
        "out=\"$HOME/uv_args.txt\"\n"
        "body=\"$HOME/uv_body.txt\"\n"
        "echo \"$@\" > \"$out\"\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = \"--body-md\" ]; then\n"
        "    shift\n"
        "    cat \"$1\" > \"$body\"\n"
        "    break\n"
        "  fi\n"
        "  shift\n"
        "done\n"
        "echo '{\"ok\":true}'\n",
    )
    zshrc.write_text("# no-op\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=_base_env(tmp_path, claude, uv, zshrc),
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 1
    args_text = (tmp_path / "uv_args.txt").read_text(encoding="utf-8")
    body_text = (tmp_path / "uv_body.txt").read_text(encoding="utf-8")
    assert "send-alert" in args_text
    assert "hourly-dispatch auth preflight failed" in args_text
    assert "security set-generic-password-partition-list" in body_text
    assert "Not logged in · Please run /login" in body_text
