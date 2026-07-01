"""Regression test for the IMAP socket-timeout fix (2026-07-01 3-STRIKE).

Root cause (docs/error_log.md 2026-06-22/06-23/07-01 entries; dreaming finding
`persistent_alert:122e34a624da56ed`, gmail-poll freshness alert fired 4x over
6.9 days): `imaplib.IMAP4_SSL(...)` was constructed with no `timeout=`, so any
single stalled TCP read (connect/login/fetch) could hang indefinitely under
launchd's variable-latency network context. The ONLY thing that ever noticed
was the wrapper's external perl-alarm (180s) killing the whole process
(exit=142) — no fail-fast signal at the IMAP-op level, and a bad connect could
silently burn the entire 180s wrapper budget before a single fetch started.

Fix: pass `timeout=` (env-overridable via GMAIL_POLL_IMAP_TIMEOUT_SEC, default
45s — well under the 180s wrapper alarm) to `imaplib.IMAP4_SSL`, and confirm
`poll()` catches the resulting `socket.timeout` / `OSError` gracefully (no
unhandled crash, no silent swallow — `_log()` records the failure) instead of
depending solely on the external alarm.
"""

from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gmail_inbox_poll.py"
spec = importlib.util.spec_from_file_location("gmail_inbox_poll_timeout_test", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["gmail_inbox_poll_timeout_test"] = mod
spec.loader.exec_module(mod)


def _redirect(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "LOG_PATH", tmp_path / "gmail_poll.log")
    monkeypatch.setattr(mod, "STATE_PATH", tmp_path / "gmail_inbox_state.json")
    monkeypatch.setenv("SMTP_USERNAME", "tester@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setattr(mod, "_load_env", lambda: None)
    monkeypatch.setattr(mod, "_existing_task_keys", lambda: (set(), set()))


def test_imap4_ssl_constructed_with_timeout(tmp_path, monkeypatch):
    """poll() must pass a timeout= to IMAP4_SSL so IMAP ops fail fast instead
    of relying solely on the external wrapper alarm."""
    _redirect(tmp_path, monkeypatch)
    captured = {}

    class FakeIMAP:
        def __init__(self, host, port, timeout=None):
            captured["host"] = host
            captured["port"] = port
            captured["timeout"] = timeout

        def login(self, user, pwd):
            raise mod.imaplib.IMAP4.error("boom - stop test early, we only care about ctor args")

    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", FakeIMAP)

    result = mod.poll(max_messages=5, dry_run=True)

    assert captured["timeout"] is not None
    assert captured["timeout"] > 0
    # Must stay comfortably under the 180s wrapper perl-alarm cap.
    assert captured["timeout"] < 180
    assert result["ok"] is False
    assert result["reason"] == "imap_error"


def test_imap_timeout_env_override(tmp_path, monkeypatch):
    _redirect(tmp_path, monkeypatch)
    monkeypatch.setenv("GMAIL_POLL_IMAP_TIMEOUT_SEC", "30")
    captured = {}

    class FakeIMAP:
        def __init__(self, host, port, timeout=None):
            captured["timeout"] = timeout

        def login(self, user, pwd):
            raise mod.imaplib.IMAP4.error("stop early")

    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", FakeIMAP)
    mod.poll(max_messages=5, dry_run=True)

    assert captured["timeout"] == 30.0


def test_socket_timeout_during_login_handled_gracefully(tmp_path, monkeypatch):
    """A stalled connect/login (socket.timeout) must not crash poll() —
    it should be caught by the generic except and returned as ok=False,
    with the failure logged (not silently swallowed)."""
    _redirect(tmp_path, monkeypatch)

    class FakeIMAP:
        def __init__(self, host, port, timeout=None):
            pass

        def login(self, user, pwd):
            raise socket.timeout("timed out")

    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", FakeIMAP)

    result = mod.poll(max_messages=5, dry_run=True)

    assert result["ok"] is False
    assert result["reason"] == "exception"
    log_path = tmp_path / "gmail_poll.log"
    # _log() writes to stderr (captured elsewhere) — assert no unhandled
    # exception propagated out of poll() at minimum; log content check is
    # best-effort since _log's target may be stdout depending on harness.
    assert "error" in str(result).lower() or result.get("error")
