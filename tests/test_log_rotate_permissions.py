from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "cron_log_rotate.sh"


def test_log_rotation_preserves_private_mode_on_replaced_inode(
    tmp_path: Path,
) -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "VOLPRED_LOG_ROTATE_LOG_DIR" in source
    assert "VOLPRED_LOG_ROTATE_STDIO_PATH" in source

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    target = log_dir / "telegram_poll.log"
    target.write_text(
        "".join(f"private boss message {index:03d}\n" for index in range(20)),
        encoding="utf-8",
    )
    target.chmod(0o600)
    before_inode = target.stat().st_ino
    output = tmp_path / "rotate.out"

    env = {
        **os.environ,
        "VOLPRED_LOG_ROTATE_LOG_DIR": str(log_dir),
        "VOLPRED_LOG_ROTATE_MAX_BYTES": "64",
        "VOLPRED_LOG_ROTATE_KEEP_LINES": "2",
        "VOLPRED_LOG_ROTATE_STDIO_PATH": str(output),
        "VOLPRED_LOG_ROTATE_SKIP_RETENTION": "1",
    }
    subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        check=True,
    )

    assert target.stat().st_ino != before_inode
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert target.read_text(encoding="utf-8").splitlines() == [
        "private boss message 018",
        "private boss message 019",
    ]
