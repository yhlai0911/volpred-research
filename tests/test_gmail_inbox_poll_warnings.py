from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gmail_inbox_poll.py"
spec = importlib.util.spec_from_file_location("gmail_inbox_poll_warnings", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["gmail_inbox_poll_warnings"] = mod
spec.loader.exec_module(mod)


def _redirect_logs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "LOG_PATH", tmp_path / "gmail_poll.log")


def test_load_state_warns_on_invalid_json(tmp_path, monkeypatch, capsys) -> None:
    _redirect_logs(tmp_path, monkeypatch)
    state_path = tmp_path / "gmail_inbox_state.json"
    state_path.write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(mod, "STATE_PATH", state_path)

    state = mod._load_state()
    err = capsys.readouterr().err

    assert state == {"last_uid": 0, "processed_message_ids": [], "last_poll_at": None}
    assert "state JSON parse failed" in err
    assert "JSONDecodeError" in err


def test_decode_warns_and_returns_raw_value_on_decode_failure(tmp_path, monkeypatch, capsys) -> None:
    _redirect_logs(tmp_path, monkeypatch)

    def _raise_decode_failure(_value):
        raise RuntimeError("decode broke")

    monkeypatch.setattr(mod, "decode_header", _raise_decode_failure)

    assert mod._decode("=?bad?=") == "=?bad?="
    err = capsys.readouterr().err
    assert "header decode failed" in err
    assert "RuntimeError: decode broke" in err


def test_trigger_immediate_dispatch_warns_when_pgrep_guard_fails(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _redirect_logs(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "_TRIGGER_MARKER", tmp_path / ".last_email_immediate_dispatch")
    monkeypatch.setattr(mod, "_DISPATCH_WRAPPER", str(tmp_path / "missing_dispatch.sh"))

    def _raise_pgrep_failure(*args, **kwargs):
        raise RuntimeError("pgrep unavailable")

    import subprocess

    monkeypatch.setattr(subprocess, "run", _raise_pgrep_failure)

    result = mod._trigger_immediate_dispatch([{"task_id": "email_task_1"}])
    err = capsys.readouterr().err

    assert result == {"fired": False, "reason": "wrapper_missing"}
    assert "immediate dispatch pgrep guard failed" in err
    assert "RuntimeError: pgrep unavailable" in err
