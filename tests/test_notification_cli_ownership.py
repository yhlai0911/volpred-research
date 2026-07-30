from __future__ import annotations

import pytest
from click.testing import CliRunner

from volpred.cli import cli


@pytest.mark.parametrize(
    ("input_level", "routed_level"),
    [
        ("info", "info"),
        ("milestone", "info"),
        ("alert", "warn"),
        ("error", "critical"),
        ("warn", "warn"),
        ("critical", "critical"),
    ],
)
def test_legacy_notify_command_uses_formal_alert_router(
    monkeypatch,
    input_level: str,
    routed_level: str,
) -> None:
    captured: dict[str, object] = {}

    class ForbiddenLegacyNotifier:
        def __init__(self, *args, **kwargs):
            raise AssertionError("notify CLI used direct notifier")

    def fake_send_alert(level, title, body):
        captured.update(level=level, title=title, body=body)
        return {
            "notification_id": "owned-notification",
            "sent": True,
            "delivery_owner": "operations_core",
            "effect_status": "delivered",
        }

    monkeypatch.setattr(
        "volpred.publisher.email_notifier.EmailNotifier",
        ForbiddenLegacyNotifier,
    )
    monkeypatch.setattr(
        "volpred.ops.alerts.send_alert",
        fake_send_alert,
    )

    result = CliRunner().invoke(
        cli,
        [
            "notify",
            "--subject",
            "Owner-routed notice",
            "--body",
            "Evidence body",
            "--level",
            input_level,
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "level": routed_level,
        "title": "Owner-routed notice",
        "body": "Evidence body",
    }
    assert "owned-notification" in result.output
    assert "operations_core" in result.output


def test_legacy_notify_command_rejects_unknown_level() -> None:
    result = CliRunner().invoke(
        cli,
        [
            "notify",
            "--subject",
            "Unknown level",
            "--body",
            "Must not route",
            "--level",
            "debug",
        ],
    )

    assert result.exit_code == 2
    assert "Invalid value for '--level'" in result.output
