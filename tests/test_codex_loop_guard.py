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
