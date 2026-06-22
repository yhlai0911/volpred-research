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
