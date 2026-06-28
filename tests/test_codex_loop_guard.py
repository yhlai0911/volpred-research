import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "codex_loop.sh"


def run_guard(lock_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CODEX_LOOP_GUARD_ONLY"] = "1"
    env["CODEX_LOOP_SKIP_LEGACY_CLEANUP"] = "1"
    env["CODEX_LOOP_LOCK_DIR"] = str(lock_dir)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


def test_codex_loop_guard_acquires_and_releases_lock(tmp_path):
    lock_dir = tmp_path / "codex-loop.lock"

    result = run_guard(lock_dir)

    assert result.returncode == 0
    assert "guard-only mode" in result.stdout
    assert not lock_dir.exists()


def test_codex_loop_guard_exits_when_live_lock_exists(tmp_path):
    lock_dir = tmp_path / "codex-loop.lock"
    lock_dir.mkdir()
    (lock_dir / "pid").write_text(str(os.getpid()), encoding="utf-8")

    result = run_guard(lock_dir)

    assert result.returncode == 0
    assert "already running" in result.stdout
    assert lock_dir.exists()


def test_codex_loop_guard_reclaims_stale_lock(tmp_path):
    lock_dir = tmp_path / "codex-loop.lock"
    lock_dir.mkdir()
    (lock_dir / "pid").write_text("999999999", encoding="utf-8")

    result = run_guard(lock_dir)

    assert result.returncode == 0
    assert "removing stale lock" in result.stdout
    assert "guard-only mode" in result.stdout
    assert not lock_dir.exists()


def test_codex_loop_hook_invokes_work_log_backfill_after_new_commit(tmp_path):
    lock_dir = tmp_path / "codex-loop.lock"
    uv = tmp_path / "uv"
    uv_args = tmp_path / "uv_args.txt"
    uv.write_text(
        "#!/bin/bash\n"
        "printf '%s\\n' \"$@\" > \"$UV_ARGS_OUT\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    uv.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "CODEX_LOOP_BACKFILL_HOOK_ONLY": "1",
            "CODEX_LOOP_SKIP_LEGACY_CLEANUP": "1",
            "CODEX_LOOP_LOCK_DIR": str(lock_dir),
            "CODEX_LOOP_HOOK_RC": "0",
            "CODEX_LOOP_HOOK_BEFORE": "1111111111111111111111111111111111111111",
            "CODEX_LOOP_HOOK_AFTER": "2222222222222222222222222222222222222222",
            "CODEX_WORK_LOG_BACKFILL_SINCE": "2026-06-26 00:00 +0800",
            "CODEX_WORK_LOG_BACKFILL_AUTOCOMMIT": "0",
            "UV_BIN": str(uv),
            "UV_ARGS_OUT": str(uv_args),
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    args = uv_args.read_text(encoding="utf-8").splitlines()
    assert args == [
        "run",
        "python",
        "scripts/backfill_work_log_from_commits.py",
        "--since",
        "2026-06-26 00:00 +0800",
        "--apply",
    ]
    assert "codex HEAD advanced" in result.stdout


def test_codex_loop_hook_skips_backfill_when_no_new_commit(tmp_path):
    lock_dir = tmp_path / "codex-loop.lock"
    uv = tmp_path / "uv"
    uv_args = tmp_path / "uv_args.txt"
    uv.write_text(
        "#!/bin/bash\n"
        "touch \"$UV_ARGS_OUT\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    uv.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "CODEX_LOOP_BACKFILL_HOOK_ONLY": "1",
            "CODEX_LOOP_SKIP_LEGACY_CLEANUP": "1",
            "CODEX_LOOP_LOCK_DIR": str(lock_dir),
            "CODEX_LOOP_HOOK_RC": "0",
            "CODEX_LOOP_HOOK_BEFORE": "1111111111111111111111111111111111111111",
            "CODEX_LOOP_HOOK_AFTER": "1111111111111111111111111111111111111111",
            "UV_BIN": str(uv),
            "UV_ARGS_OUT": str(uv_args),
        }
    )

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    assert not uv_args.exists()
    assert "skip: no new commit" in result.stdout
