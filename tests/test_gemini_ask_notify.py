from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


class _Completed:
    stdout = "pytest\n"


def test_notify_usage_warns_when_ledger_write_fails(tmp_path, monkeypatch, capsys) -> None:
    import gemini_ask  # type: ignore

    monkeypatch.setattr(gemini_ask, "_USAGE_LOG", tmp_path)
    monkeypatch.setattr(gemini_ask.subprocess, "run", lambda *args, **kwargs: _Completed())

    gemini_ask._notify_usage("gemini-test", "prompt", 12)
    stderr = capsys.readouterr().err

    assert "usage ledger write failed" in stderr
    assert "IsADirectoryError" in stderr


def test_notify_usage_warns_when_admin_alert_fails(tmp_path, monkeypatch, capsys) -> None:
    import gemini_ask  # type: ignore

    usage_log = tmp_path / "usage.jsonl"
    monkeypatch.setattr(gemini_ask, "_USAGE_LOG", usage_log)

    def _raise_send_failure(*args, **kwargs):
        raise RuntimeError("send-alert down")

    monkeypatch.setattr(gemini_ask.subprocess, "run", _raise_send_failure)

    gemini_ask._notify_usage("gemini-test", "prompt", 12)
    stderr = capsys.readouterr().err

    assert usage_log.exists()
    assert "admin alert send failed" in stderr
    assert "RuntimeError: send-alert down" in stderr
