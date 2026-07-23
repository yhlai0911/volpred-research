from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PRETOOLUSE_SCRIPT = REPO_ROOT / ".claude" / "hooks" / "pretooluse-bash-optimizer.sh"
COMPACT_SCRIPT = REPO_ROOT / ".claude" / "hooks" / "run-compact-bash.sh"


def _run_pretooluse(command: str, *, hook_root: str | None = None) -> dict:
    env = os.environ.copy()
    if hook_root is not None:
        env["VOLPRED_HOOK_ROOT"] = hook_root
    payload = {"tool_input": {"command": command}}
    result = subprocess.run(
        ["/bin/bash", str(PRETOOLUSE_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=REPO_ROOT,
    )
    return json.loads(result.stdout)


def _run_compact_test(command: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["VOLPRED_HOOK_ROOT"] = str(tmp_path)
    return subprocess.run(
        ["/bin/bash", str(COMPACT_SCRIPT), "test", command],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=REPO_ROOT,
    )


def test_pretooluse_rewrites_git_status_to_compact_runner(tmp_path: Path):
    result = _run_pretooluse("git status --short --branch", hook_root=str(tmp_path))

    hook_output = result["hookSpecificOutput"]
    assert hook_output["permissionDecision"] == "allow"
    assert hook_output["permissionDecisionReason"] == "Compact noisy git status output to reduce dirty-worktree context tax"
    assert hook_output["updatedInput"]["command"] == (
        f'/bin/bash "{tmp_path}/.claude/hooks/run-compact-bash.sh" '
        "git_status git\\ status\\ --short\\ --branch"
    )


def test_pretooluse_keeps_machine_readable_git_status_untouched():
    result = _run_pretooluse("git status --porcelain")

    assert result == {}


def test_pretooluse_rewrites_log_tail_to_compact_runner(tmp_path: Path):
    result = _run_pretooluse(
        "tail -n 200 storage/logs/cron/release_pool.log",
        hook_root=str(tmp_path),
    )

    hook_output = result["hookSpecificOutput"]
    assert hook_output["permissionDecision"] == "allow"
    assert hook_output["permissionDecisionReason"] == "Compact large log tail output to reduce context noise"
    assert hook_output["updatedInput"]["command"] == (
        f'/bin/bash "{tmp_path}/.claude/hooks/run-compact-bash.sh" '
        "tail_log tail\\ -n\\ 200\\ storage/logs/cron/release_pool.log"
    )


def test_pretooluse_returns_empty_for_unmatched_command():
    result = _run_pretooluse("echo hi")

    assert result == {}


def test_run_compact_bash_git_status_summarizes_changes(tmp_path: Path):
    env = os.environ.copy()
    env["VOLPRED_HOOK_ROOT"] = str(tmp_path)

    result = subprocess.run(
        [
            "/bin/bash",
            str(COMPACT_SCRIPT),
            "git_status",
            "printf '## main...origin/main\\n M foo.py\\n?? bar.txt\\n'",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=REPO_ROOT,
    )

    assert "Branch: main...origin/main" in result.stdout
    assert "Git status compacted: 2 changed paths." in result.stdout
    assert "Counts: staged=0 unstaged=1 untracked=1 deleted=0 conflicts=0" in result.stdout
    assert " M foo.py" in result.stdout
    assert "?? bar.txt" in result.stdout
    assert "Full log:" in result.stdout


def test_run_compact_bash_tail_log_keeps_only_last_lines(tmp_path: Path):
    env = os.environ.copy()
    env["VOLPRED_HOOK_ROOT"] = str(tmp_path)

    result = subprocess.run(
        ["/bin/bash", str(COMPACT_SCRIPT), "tail_log", "seq 1 120"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=REPO_ROOT,
    )

    assert "Log tail compacted to last 40 lines (original 120 lines)." in result.stdout
    assert "\n81\n" in result.stdout
    assert "\n120\n" in result.stdout
    assert "\n80\n" not in result.stdout
    assert "Full log:" in result.stdout


def test_run_compact_bash_missing_pytest_path_is_not_false_green(tmp_path: Path):
    result = _run_compact_test(
        "uv run python -m pytest tests/definitely_does_not_exist.py -q | tail -20",
        tmp_path,
    )

    assert result.returncode != 0
    assert "Tests FAILED — pytest collected no tests." in result.stdout
    assert "ERROR: file or directory not found" in result.stdout
    assert "Tests passed" not in result.stdout


def test_run_compact_bash_zero_selected_tests_is_not_success(tmp_path: Path):
    result = _run_compact_test(
        "uv run python -m pytest -q -k definitely_no_such_test "
        "tests/test_hook_bash_optimizer.py | tail -20",
        tmp_path,
    )

    assert result.returncode != 0
    assert "Tests FAILED — pytest collected no tests." in result.stdout
    assert "deselected" in result.stdout
    assert "Tests passed" not in result.stdout


def test_run_compact_bash_still_accepts_positive_pytest_summary(tmp_path: Path):
    result = _run_compact_test("printf '2 passed in 0.01s\\n' | tail -1", tmp_path)

    assert result.returncode == 0
    assert "Tests passed." in result.stdout
    assert "2 passed in 0.01s" in result.stdout
