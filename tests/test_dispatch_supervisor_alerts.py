from __future__ import annotations

import logging
from types import SimpleNamespace

from scripts.dispatch_supervisor import alerts


def test_send_warns_when_temp_cleanup_fails(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        alerts.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stderr=""),
    )

    def _raise_unlink(path):
        raise OSError("unlink denied")

    monkeypatch.setattr(alerts.os, "unlink", _raise_unlink)

    with caplog.at_level(logging.WARNING, logger=alerts.__name__):
        rc = alerts._send("info", "test alert", "body")

    assert rc == 0
    assert "alert temp file cleanup failed" in caplog.text
    assert "unlink denied" in caplog.text


def test_send_alert_scrubs_supervisor_private_environment(monkeypatch) -> None:
    captured: dict[str, str] = {}
    monkeypatch.setenv("VOLPRED_SUPERVISOR_RELEASE_ID", "release")
    monkeypatch.setenv("VOLPRED_SUPERVISOR_FUTURE_MARKER", "future")
    monkeypatch.setenv("VOLPRED_DEFERRED_RELOAD_ROOT", "/tmp/reload")
    monkeypatch.setenv("VOLPRED_CANONICAL_REPO_ROOT", "/repo")
    monkeypatch.setenv("VOLPRED_ACTOR", "dispatch-supervisor")

    def run(*_args, **kwargs):
        captured.update(kwargs["env"])
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(alerts.subprocess, "run", run)

    assert alerts._send("info", "environment boundary", "body") == 0
    assert captured["VOLPRED_ACTOR"] == "dispatch-supervisor"
    assert not any(
        key.startswith(("VOLPRED_SUPERVISOR_", "VOLPRED_DEFERRED_RELOAD_"))
        for key in captured
    )
    assert "VOLPRED_CANONICAL_REPO_ROOT" not in captured
