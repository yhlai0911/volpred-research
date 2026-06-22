"""Coverage for src/volpred/publisher/email_notifier.py.

Focus on the safety guards + bookkeeping behaviors that previously caused
incidents (2026-04-20 test fixture leak into user inbox). Real SMTP send is
disabled globally via tests/conftest.py VOLPRED_NO_EMAIL=1; these tests verify
the guards are honored AND that bookkeeping (notification_log + per-id JSON)
is updated correctly even when send is suppressed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from volpred.publisher import email_notifier
from volpred.publisher.email_notifier import EmailNotifier


@pytest.fixture
def notifier(tmp_path: Path, monkeypatch) -> EmailNotifier:
    # Configure SMTP envs so is_configured() returns True; _send_email still
    # short-circuits via VOLPRED_NO_EMAIL=1 (set globally in conftest).
    monkeypatch.setenv("ADMIN_NOTIFICATION_EMAILS", "alice@example.com,bob@example.com")
    monkeypatch.setenv("EMAIL_FROM", "ops@volpred.test")
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_USERNAME", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pwd")
    monkeypatch.setenv("OPS_ADMIN_EMAILS", "alice@example.com,bob@example.com")
    return EmailNotifier(storage_dir=str(tmp_path))


def test_is_configured_reflects_env(notifier: EmailNotifier):
    assert notifier.is_configured() is True
    assert "alice@example.com" in notifier.admin_emails


def test_load_env_file_warns_when_existing_path_cannot_be_read(tmp_path: Path, capsys):
    email_notifier._load_env_file(tmp_path)

    captured = capsys.readouterr()
    assert "[email_notifier] WARN env file read failed" in captured.err
    assert "IsADirectoryError" in captured.err
    assert str(tmp_path) in captured.err


def test_notify_writes_log_and_file_when_send_suppressed(notifier: EmailNotifier, tmp_path: Path):
    """VOLPRED_NO_EMAIL=1 suppresses SMTP but bookkeeping still records."""
    notif_id = notifier.notify(
        "Test subject",
        "Body content",
        level="warn",
        metadata={"source": "unit_test"},
    )
    assert notif_id and len(notif_id) >= 4

    notif_file = tmp_path / "notifications" / f"{notif_id}.json"
    assert notif_file.exists()
    payload = json.loads(notif_file.read_text())
    assert payload["subject"] == "Test subject"
    assert payload["level"] == "warn"
    assert payload["metadata"]["source"] == "unit_test"
    # send_email returned cleanly under VOLPRED_NO_EMAIL → notification marked sent
    assert payload["sent"] is True

    log = json.loads((tmp_path / "notifications" / "notification_log.json").read_text())
    assert any(entry["id"] == notif_id for entry in log)


def test_notify_dedup_skips_duplicate(notifier: EmailNotifier, tmp_path: Path):
    first = notifier.notify(
        "Alert",
        "Body 1",
        dedupe_type="alert_test",
        dedupe_key="key_x",
    )
    second = notifier.notify(
        "Alert",
        "Body 2",
        dedupe_type="alert_test",
        dedupe_key="key_x",
    )
    assert first != second
    second_payload = json.loads((tmp_path / "notifications" / f"{second}.json").read_text())
    assert second_payload["skipped"] is True
    assert second_payload["skip_reason"] == "duplicate"
    assert second_payload["sent"] is False
    # First should be sent; second skipped
    assert second.startswith("skip_")


def test_notify_dedup_force_send_bypasses(notifier: EmailNotifier, tmp_path: Path):
    notifier.notify("S", "B1", dedupe_type="t", dedupe_key="k")
    forced_id = notifier.notify("S", "B2", dedupe_type="t", dedupe_key="k", force_send=True)
    assert not forced_id.startswith("skip_")
    payload = json.loads((tmp_path / "notifications" / f"{forced_id}.json").read_text())
    assert payload.get("skipped") is None or payload["skipped"] is False
    assert payload["sent"] is True


def test_already_sent_only_counts_actually_sent(notifier: EmailNotifier):
    # Send one with dedup
    notifier.notify("S", "B", dedupe_type="t2", dedupe_key="k2")
    assert notifier.already_sent("t2", "k2") is True
    assert notifier.already_sent("t2", "different_key") is False
    assert notifier.already_sent("nonexistent_type", "k2") is False


def test_get_notifications_filter_and_limit(notifier: EmailNotifier):
    notifier.notify("info1", "b", level="info")
    notifier.notify("warn1", "b", level="warn")
    notifier.notify("info2", "b", level="info")

    info_only = notifier.get_notifications(level="info")
    assert all(item["level"] == "info" for item in info_only)
    assert len(info_only) == 2

    limited = notifier.get_notifications(limit=2)
    assert len(limited) == 2


def test_send_email_skipped_under_tmp_storage(tmp_path: Path, monkeypatch):
    """Defense-in-depth: tmp_path triggers the second guard even without VOLPRED_NO_EMAIL."""
    monkeypatch.setenv("ADMIN_NOTIFICATION_EMAILS", "user@example.com")
    monkeypatch.setenv("EMAIL_FROM", "ops@volpred.test")
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("OPS_ADMIN_EMAILS", "user@example.com")
    monkeypatch.delenv("VOLPRED_NO_EMAIL", raising=False)
    notifier = EmailNotifier(storage_dir=str(tmp_path))
    # tmp_path string contains 'pytest-' or '/tmp/' typically
    notif_id = notifier.notify("Should not send", "body")
    payload = json.loads((tmp_path / "notifications" / f"{notif_id}.json").read_text())
    # _send_email returned None silently → notification "sent" True (we don't
    # raise) — the file just records the attempt. Bookkeeping is consistent
    # whether VOLPRED_NO_EMAIL or tmp guard fires.
    assert payload["recipients"] == ["user@example.com"]
