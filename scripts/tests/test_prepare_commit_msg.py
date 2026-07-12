"""Regression tests for the actual commit-message encoding boundary."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "scripts/git_hooks/prepare-commit-msg"


def _run_hook(tmp_path: Path, content: bytes) -> subprocess.CompletedProcess[str]:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_bytes(content)
    return subprocess.run(
        ["bash", str(HOOK), str(message), "message"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize(
    "content",
    [
        b"[codex] fix parser\n",
        "以 UTF-8 訊息檔提交中文\n".encode(),
        b"subject\n\nbody\twith allowed whitespace\r\n",
    ],
)
def test_valid_utf8_messages_are_allowed(tmp_path: Path, content: bytes) -> None:
    assert _run_hook(tmp_path, content).returncode == 0


@pytest.mark.parametrize(
    "content, marker",
    [
        (b"bad byte: \xff\n", "not strict UTF-8"),
        ("bad replacement: \ufffd\n".encode(), "U+FFFD"),
        ("bad C1: \u0085\n".encode(), "control U+0085"),
        (b"bad C0: \x1b[31m\n", "control U+001B"),
    ],
)
def test_corrupted_or_control_messages_are_blocked(
    tmp_path: Path, content: bytes, marker: str
) -> None:
    result = _run_hook(tmp_path, content)
    assert result.returncode == 1
    assert marker in result.stderr


def test_prepare_hook_cannot_be_skipped_with_no_verify(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "gate-test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "gate@example.com"], check=True)
    hooks = repo / ".git/hooks"
    installed = hooks / "prepare-commit-msg"
    shutil.copy2(HOOK, installed)
    installed.chmod(0o755)

    message = tmp_path / "bad-message.txt"
    message.write_bytes("broken \ufffd \u0085\n".encode())
    result = subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "--no-verify", "-F", str(message)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "prepare-commit-msg] BLOCKED" in result.stderr


def test_prepare_hook_preserves_utf8_file_escape_hatch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "gate-test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "gate@example.com"], check=True)
    installed = repo / ".git/hooks/prepare-commit-msg"
    shutil.copy2(HOOK, installed)
    installed.chmod(0o755)

    message = tmp_path / "valid-message.txt"
    message.write_text("合法的 UTF-8 中文訊息\n", encoding="utf-8")
    result = subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "--no-verify", "-F", str(message)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
