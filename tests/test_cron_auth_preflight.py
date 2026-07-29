from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

# The production wrapper was physically retired on 2026-07-30.  These tests
# preserve audit coverage for the historical auth-preflight incident without
# resurrecting a live entrypoint.
SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "_legacy"
    / "cron_hourly_dispatch.sh"
)


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
        "echo \"$@\" >> \"$HOME/uv_called.txt\"\n"
        "if [[ \"$*\" == *\"hourly_dispatch_pregate.py\"* ]]; then\n"
        "  exit 1\n"
        "fi\n",
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
    uv_calls = (tmp_path / "uv_called.txt").read_text(encoding="utf-8")
    assert "git_conflict_guard.py --quiet" in uv_calls
    assert "send-alert" not in uv_calls
    log = (tmp_path / ".volpred" / "logs" / "hourly_dispatch.log").read_text(encoding="utf-8")
    assert "[AUTH-PREFLIGHT] ok" in log
    assert "=== [hourly_dispatch] exit 0 at " in log


def test_auth_preflight_recovers_after_sourcing_zshrc(tmp_path: Path) -> None:
    claude = tmp_path / "claude"
    uv = tmp_path / "uv"
    zshrc = tmp_path / ".zshrc"

    _write_executable(
        claude,
        "#!/bin/bash\n"
        "count_file=\"$HOME/claude_calls.txt\"\n"
        "count=0\n"
        "if [ -f \"$count_file\" ]; then\n"
        "  count=$(cat \"$count_file\")\n"
        "fi\n"
        "count=$((count + 1))\n"
        "echo \"$count\" > \"$count_file\"\n"
        "if [ \"$count\" -ge 2 ]; then\n"
        "  echo 'Hi'\n"
        "  exit 0\n"
        "fi\n"
        "echo 'Not logged in · Please run /login' >&2\n"
        "exit 1\n",
    )
    _write_executable(
        uv,
        "#!/bin/bash\n"
        "echo \"$@\" >> \"$HOME/uv_called.txt\"\n"
        "if [[ \"$*\" == *\"hourly_dispatch_pregate.py\"* ]]; then\n"
        "  exit 1\n"
        "fi\n",
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
    uv_calls = (tmp_path / "uv_called.txt").read_text(encoding="utf-8")
    assert "git_conflict_guard.py --quiet" in uv_calls
    assert "send-alert" not in uv_calls
    log = (tmp_path / ".volpred" / "logs" / "hourly_dispatch.log").read_text(encoding="utf-8")
    assert "[AUTH-PREFLIGHT] recovered after sourcing zshrc" in log
    assert "=== [hourly_dispatch] exit 0 at " in log


def test_auth_preflight_sends_actionable_alert_on_double_failure(tmp_path: Path) -> None:
    claude = tmp_path / "claude"
    codex = tmp_path / "codex"
    uv = tmp_path / "uv"
    zshrc = tmp_path / ".zshrc"

    _write_executable(
        claude,
        "#!/bin/bash\n"
        "echo 'Not logged in · Please run /login' >&2\n"
        "exit 1\n",
    )
    _write_executable(
        codex,
        "#!/bin/bash\n"
        "echo 'codex failover unavailable' >&2\n"
        "exit 1\n",
    )
    _write_executable(
        uv,
        "#!/bin/bash\n"
        "out=\"$HOME/uv_args.txt\"\n"
        "body=\"$HOME/uv_body.txt\"\n"
        "echo \"CALL: $@\" >> \"$out\"\n"
        "if [[ \"$*\" == *\"hourly_dispatch_pregate.py\"* ]]; then\n"
        "  exit 1\n"
        "fi\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = \"--body-md\" ]; then\n"
        "    shift\n"
        "    cat \"$1\" >> \"$body\"\n"
        "    printf '\\n---\\n' >> \"$body\"\n"
        "    break\n"
        "  fi\n"
        "  shift\n"
        "done\n"
        "echo '{\"ok\":true}'\n",
    )
    zshrc.write_text("# no-op\n", encoding="utf-8")
    env = _base_env(tmp_path, claude, uv, zshrc)
    env["AUTH_PREFLIGHT_BACKOFF_SEC"] = "0"
    env["CODEX_BIN"] = str(codex)

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    log_path = tmp_path / ".volpred" / "logs" / "hourly_dispatch.log"
    assert result.returncode == 1, log_path.read_text(encoding="utf-8")
    args_text = (tmp_path / "uv_args.txt").read_text(encoding="utf-8")
    body_text = (tmp_path / "uv_body.txt").read_text(encoding="utf-8")
    assert "send-alert" in args_text
    assert "hourly-dispatch auth preflight failed" in args_text
    assert "security set-generic-password-partition-list" in body_text
    assert "Not logged in · Please run /login" in body_text


def test_auth_preflight_runtime_fs_failure_uses_neutral_diagnosis(tmp_path: Path) -> None:
    # 2026-07-15 correction: Operation-not-permitted / getcwd / EINTR are
    # low-level runtime/filesystem evidence, not proof that a claude update lost
    # Desktop TCC access. The repo moved out of Desktop on 2026-07-02, so the
    # legacy causal claim and interactive-session remediation must not return.
    claude = tmp_path / "claude"
    codex = tmp_path / "codex"
    uv = tmp_path / "uv"
    zshrc = tmp_path / ".zshrc"

    _write_executable(
        claude,
        "#!/bin/bash\n"
        "echo 'getcwd: cannot access parent directories: Interrupted system call' >&2\n"
        "echo 'Operation not permitted' >&2\n"
        "exit 1\n",
    )
    _write_executable(
        codex,
        "#!/bin/bash\n"
        "echo 'codex failover unavailable' >&2\n"
        "exit 1\n",
    )
    _write_executable(
        uv,
        "#!/bin/bash\n"
        "out=\"$HOME/uv_args.txt\"\n"
        "body=\"$HOME/uv_body.txt\"\n"
        "echo \"CALL: $@\" >> \"$out\"\n"
        "if [[ \"$*\" == *\"hourly_dispatch_pregate.py\"* ]]; then\n"
        "  exit 1\n"
        "fi\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = \"--body-md\" ]; then\n"
        "    shift\n"
        "    cat \"$1\" >> \"$body\"\n"
        "    printf '\\n---\\n' >> \"$body\"\n"
        "    break\n"
        "  fi\n"
        "  shift\n"
        "done\n"
        "echo '{\"ok\":true}'\n",
    )
    zshrc.write_text("# no-op\n", encoding="utf-8")
    env = _base_env(tmp_path, claude, uv, zshrc)
    env["AUTH_PREFLIGHT_BACKOFF_SEC"] = "0"
    env["CODEX_BIN"] = str(codex)

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    log_path = tmp_path / ".volpred" / "logs" / "hourly_dispatch.log"
    assert result.returncode == 1, log_path.read_text(encoding="utf-8")
    args_text = (tmp_path / "uv_args.txt").read_text(encoding="utf-8")
    body_text = (tmp_path / "uv_body.txt").read_text(encoding="utf-8")
    assert "send-alert" in args_text
    # Runtime/filesystem branch chosen — visible but non-critical because Codex
    # failover still owns the slot and the next tick retries automatically.
    assert "transient runtime/filesystem failure" in args_text
    assert "--level warn" in args_text
    assert "hourly-dispatch auth preflight failed" not in args_text
    assert "暫時性 runtime/filesystem 失敗" in body_text
    assert "單憑 preflight 輸出無法決定根因" in body_text
    assert "Codex failover" in body_text
    # Mechanical anti-regression gate for the retired Desktop-TCC copy.
    assert "TCC 授權失效" not in args_text + body_text
    assert "開一個互動 Claude session" not in body_text
    assert "新版 binary 尚未取得 Desktop TCC 授權" not in body_text
    assert "這就是根因" not in body_text
    # Runtime failure without explicit auth rejection must not recommend the
    # credential hotfix either.
    assert "security set-generic-password-partition-list" not in body_text
