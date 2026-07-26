from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_session_start_does_not_restore_legacy_codex_clock(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "codex_loop.log"
    env = {
        **os.environ,
        "VOLPRED_REPO_ROOT": str(ROOT),
        "VOLPRED_CODEX_LOOP_LOG": str(log_path),
    }

    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "auto_start_codex_loop.sh")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0
    assert "retired: Operations Core agent_dispatch_tick owns the clock" in (
        log_path.read_text(encoding="utf-8")
    )
    processes = subprocess.run(
        ["ps", "-axo", "command="],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert str(ROOT / "scripts" / "codex_loop.sh") not in processes
