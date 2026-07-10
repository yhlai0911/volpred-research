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


def _dispatch_state_module():
    root = SCRIPT.parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from scripts.dispatch_supervisor import state as dispatch_state

    return dispatch_state


def test_trigger_immediate_dispatch_skips_when_supervisor_job_in_flight(
    tmp_path,
    monkeypatch,
) -> None:
    """07-04 cutover: the in-flight guard is the supervisor's current_job, not
    a pgrep on the (now unused) legacy wrapper."""
    _redirect_logs(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "_TRIGGER_MARKER", tmp_path / ".last_email_immediate_dispatch")

    dispatch_state = _dispatch_state_module()
    monkeypatch.setattr(dispatch_state, "read_state", lambda: {"current_job": {"pid": 123}})

    def _unexpected_fire(*args, **kwargs):
        raise AssertionError("must not fire while a dispatch job is in flight")

    monkeypatch.setattr(dispatch_state, "request_fire", _unexpected_fire)

    result = mod._trigger_immediate_dispatch([{"task_id": "email_task_1"}])

    assert result == {"fired": False, "reason": "dispatch_already_running"}


def test_trigger_immediate_dispatch_warns_when_supervisor_state_unreadable(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """If the in-flight guard itself fails we must fail closed (no unmanaged
    second dispatch) and leave a trace — the hourly fire picks the reply up."""
    _redirect_logs(tmp_path, monkeypatch)
    monkeypatch.setattr(mod, "_TRIGGER_MARKER", tmp_path / ".last_email_immediate_dispatch")

    dispatch_state = _dispatch_state_module()

    def _raise_state_failure(*args, **kwargs):
        raise RuntimeError("state unavailable")

    monkeypatch.setattr(dispatch_state, "read_state", _raise_state_failure)

    def _unexpected_fire(*args, **kwargs):
        raise AssertionError("must not fire when the in-flight guard is blind")

    monkeypatch.setattr(dispatch_state, "request_fire", _unexpected_fire)

    result = mod._trigger_immediate_dispatch([{"task_id": "email_task_1"}])
    err = capsys.readouterr().err

    assert result == {"fired": False, "reason": "error:state unavailable"}
    assert "immediate dispatch request FAILED" in err
    assert "RuntimeError('state unavailable')" in err
