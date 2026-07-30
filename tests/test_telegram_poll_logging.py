from __future__ import annotations

import stat
from pathlib import Path

import scripts.telegram_poll as telegram_poll


def test_daemon_log_reopens_rotated_path_on_every_record(
    tmp_path: Path,
    monkeypatch,
) -> None:
    log_path = tmp_path / "telegram_poll.log"
    rotated_path = tmp_path / "telegram_poll.log.1"
    monkeypatch.setattr(telegram_poll, "TELEGRAM_POLL_LOG", log_path)

    telegram_poll._log("before rotation")
    log_path.replace(rotated_path)
    telegram_poll._log("after rotation")

    assert "before rotation" in rotated_path.read_text(encoding="utf-8")
    assert "after rotation" not in rotated_path.read_text(encoding="utf-8")
    assert "after rotation" in log_path.read_text(encoding="utf-8")
    assert "before rotation" not in log_path.read_text(encoding="utf-8")
    assert stat.S_IMODE(log_path.stat().st_mode) == 0o600


def test_daemon_wrapper_does_not_hold_the_rotated_log_inode() -> None:
    wrapper = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "cron_telegram_poll.sh"
    ).read_text(encoding="utf-8")

    assert "exec >> /Users/yhlai0911/.volpred/logs/telegram_poll.log" not in wrapper
