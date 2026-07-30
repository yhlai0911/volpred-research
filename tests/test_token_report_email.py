from __future__ import annotations

import ast
import hashlib
import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    path = ROOT / "scripts" / "token_report_email.py"
    spec = importlib.util.spec_from_file_location(
        "token_report_email_contract",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _canonical_fire(
    *,
    scheduled_for: str = "2026-07-30T00:00:00Z",
) -> str:
    generation = "operations-core-v1"
    digest = hashlib.sha256(
        (
            f"{generation}\0token_report_daily\0{scheduled_for}"
        ).encode()
    ).hexdigest()[:24]
    return f"{generation}:token_report_daily:{digest}"


def _set_scheduled_environment(
    monkeypatch: pytest.MonkeyPatch,
    *,
    scheduled_for: str = "2026-07-30T00:00:00Z",
) -> str:
    fire_key = _canonical_fire(scheduled_for=scheduled_for)
    monkeypatch.setenv("VOLPRED_SCHEDULE_OWNER", "operations_core")
    monkeypatch.setenv("VOLPRED_SCHEDULE_JOB_ID", "token_report_daily")
    monkeypatch.setenv("VOLPRED_SCHEDULE_FIRE_KEY", fire_key)
    monkeypatch.setenv(
        "VOLPRED_SCHEDULE_GENERATION",
        "operations-core-v1",
    )
    monkeypatch.setenv("VOLPRED_SCHEDULED_FOR", scheduled_for)
    return fire_key


def test_scheduled_token_report_uses_exact_fire_owned_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_module()
    fire_key = _set_scheduled_environment(monkeypatch)
    captured: list[object] = []

    monkeypatch.setattr(
        report,
        "_report",
        lambda *flags: {
            "totals": {"billable_total": 1},
            "week_range": "2026-07-27 → 2026-08-02",
        },
    )
    monkeypatch.setattr(
        report,
        "build_html",
        lambda *_args, **_kwargs: (
            "<p>token report</p>",
            "token report",
        ),
    )

    from volpred.ops.delivery import owned_email

    monkeypatch.setattr(
        owned_email,
        "read_existing_owned_email_request",
        lambda _key: None,
    )
    monkeypatch.setattr(
        owned_email,
        "dispatch_email_by_current_owner",
        lambda command, **_kwargs: (
            captured.append(command)
            or {
                "sent": True,
                "notification_id": "effect-token-report",
                "delivery_owner": "operations_core",
                "effect_status": "delivered",
                "evidence_ref": "imap-sent:token-report",
            }
        ),
    )

    class ForbiddenDirectNotifier:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("scheduled report used direct EmailNotifier")

    monkeypatch.setattr(
        "volpred.publisher.email_notifier.EmailNotifier",
        ForbiddenDirectNotifier,
    )

    assert report.main([]) == 0
    assert len(captured) == 1
    command = captured[0]
    assert command.idempotency_key == fire_key
    assert command.actor_ref == (
        f"schedule:token_report_daily:{fire_key}"
    )
    assert command.recipient == "yihao.lai@gmail.com"
    assert command.title.startswith(
        "[新架構派發][VolPred Token 報表]"
    )
    assert command.title.count("[新架構派發]") == 1


def test_scheduled_retry_replays_durable_command_without_rebuilding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_module()
    fire_key = _set_scheduled_environment(monkeypatch)

    from volpred.ops.delivery import owned_email

    durable = owned_email.OwnedEmailCommand(
        idempotency_key=fire_key,
        level="info",
        title="[VolPred Token 報表] historical immutable subject",
        recipient="yihao.lai@gmail.com",
        text_body="durable token report",
        html_body="<p>durable token report</p>",
        actor_ref=f"schedule:token_report_daily:{fire_key}",
    )
    monkeypatch.setattr(
        owned_email,
        "read_existing_owned_email_request",
        lambda _key: type("Existing", (), {"command": durable})(),
    )
    captured: list[object] = []
    monkeypatch.setattr(
        owned_email,
        "dispatch_email_by_current_owner",
        lambda command, **_kwargs: (
            captured.append(command)
            or {
                "sent": True,
                "notification_id": "effect-token-replay",
                "delivery_owner": "operations_core",
                "effect_status": "delivered",
                "evidence_ref": "imap-sent:token-replay",
            }
        ),
    )
    monkeypatch.setattr(
        report,
        "_report",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("durable retry rebuilt the report")
        ),
    )

    assert report.main([]) == 0
    assert captured == [durable]


def test_scheduled_retry_rejects_durable_recipient_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_module()
    fire_key = _set_scheduled_environment(monkeypatch)

    from volpred.ops.delivery import owned_email

    durable = owned_email.OwnedEmailCommand(
        idempotency_key=fire_key,
        level="info",
        title="[VolPred Token 報表] historical immutable subject",
        recipient="attacker@example.com",
        text_body="durable token report",
        html_body="<p>durable token report</p>",
        actor_ref=f"schedule:token_report_daily:{fire_key}",
    )
    monkeypatch.setattr(
        owned_email,
        "read_existing_owned_email_request",
        lambda _key: type("Existing", (), {"command": durable})(),
    )
    dispatched: list[object] = []
    monkeypatch.setattr(
        owned_email,
        "dispatch_email_by_current_owner",
        lambda command, **_kwargs: dispatched.append(command),
    )
    monkeypatch.setattr(
        report,
        "_report",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("drifted command rebuilt the report")
        ),
    )

    assert report.main([]) == 1
    assert dispatched == []


def test_scheduled_dry_run_never_replays_an_existing_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_module()
    fire_key = _set_scheduled_environment(monkeypatch)
    (tmp_path / "storage" / "logs").mkdir(parents=True)
    monkeypatch.setattr(report, "ROOT", tmp_path)
    monkeypatch.setattr(
        report,
        "_report",
        lambda *flags: {
            "totals": {"billable_total": 1},
            "week_range": "2026-07-27 → 2026-08-02",
        },
    )
    monkeypatch.setattr(
        report,
        "build_html",
        lambda *_args, **_kwargs: ("<p>dry run</p>", "dry run"),
    )

    from volpred.ops.delivery import owned_email

    durable = owned_email.OwnedEmailCommand(
        idempotency_key=fire_key,
        level="info",
        title="[VolPred Token 報表] historical immutable subject",
        recipient="yihao.lai@gmail.com",
        text_body="durable token report",
        html_body="<p>durable token report</p>",
        actor_ref=f"schedule:token_report_daily:{fire_key}",
    )
    monkeypatch.setattr(
        owned_email,
        "read_existing_owned_email_request",
        lambda _key: type("Existing", (), {"command": durable})(),
    )
    dispatched: list[object] = []
    monkeypatch.setattr(
        owned_email,
        "dispatch_email_by_current_owner",
        lambda command, **_kwargs: dispatched.append(command),
    )

    assert report.main(["--dry-run"]) == 0
    assert dispatched == []
    assert len(list((tmp_path / "storage" / "logs").glob("*.html"))) == 1


def test_invalid_scheduled_fire_fails_before_report_or_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_module()
    _set_scheduled_environment(monkeypatch)
    monkeypatch.setenv(
        "VOLPRED_SCHEDULE_GENERATION",
        "operations-core-v0",
    )
    monkeypatch.setattr(
        report,
        "_report",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("invalid fire generated a report")
        ),
    )

    from volpred.ops.delivery import owned_email

    monkeypatch.setattr(
        owned_email,
        "read_existing_owned_email_request",
        lambda _key: (_ for _ in ()).throw(
            AssertionError("invalid fire read the outbox")
        ),
    )
    monkeypatch.setattr(
        owned_email,
        "dispatch_email_by_current_owner",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid fire reached the provider")
        ),
    )

    assert report.main([]) == 1


@pytest.mark.parametrize(
    ("environment_name", "environment_value"),
    [
        ("VOLPRED_SCHEDULE_JOB_ID", "boss_report_4h"),
        ("VOLPRED_SCHEDULED_FOR", "2026-07-30T00:01:00Z"),
    ],
)
def test_wrong_job_or_noncanonical_minute_fails_before_report(
    environment_name: str,
    environment_value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_module()
    _set_scheduled_environment(monkeypatch)
    monkeypatch.setenv(environment_name, environment_value)
    monkeypatch.setattr(
        report,
        "_report",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("invalid fire generated a report")
        ),
    )

    assert report.main([]) == 1


def test_partial_scheduled_identity_fails_before_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_module()
    monkeypatch.setenv("VOLPRED_SCHEDULE_OWNER", "operations_core")
    monkeypatch.setattr(
        report,
        "_report",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("partial fire generated a report")
        ),
    )

    assert report.main([]) == 1


def test_invalid_scheduled_calibration_fails_before_report_or_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_module()
    _set_scheduled_environment(monkeypatch)
    monkeypatch.setenv(
        "VOLPRED_SCHEDULE_GENERATION",
        "operations-core-v0",
    )
    monkeypatch.setattr(report, "CALIB_PATH", tmp_path / "calibration.json")
    monkeypatch.setattr(
        report,
        "_report",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("invalid scheduled calibration read a report")
        ),
    )

    assert report.main(["--calibrate", "0.5"]) == 1
    assert not report.CALIB_PATH.exists()


@pytest.mark.parametrize("argv", [["--force"], ["--to", "reader@example.com"]])
def test_scheduled_fire_rejects_manual_delivery_modifiers(
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_module()
    _set_scheduled_environment(monkeypatch)
    monkeypatch.setattr(
        report,
        "_report",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("invalid modifier generated a report")
        ),
    )

    assert report.main(argv) == 1


def test_unacknowledged_scheduled_delivery_fails_the_fire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_module()
    _set_scheduled_environment(monkeypatch)
    monkeypatch.setattr(
        report,
        "_report",
        lambda *flags: {
            "totals": {"billable_total": 1},
            "week_range": "2026-07-27 → 2026-08-02",
        },
    )
    monkeypatch.setattr(
        report,
        "build_html",
        lambda *_args, **_kwargs: ("<p>report</p>", "report"),
    )

    from volpred.ops.delivery import owned_email

    monkeypatch.setattr(
        owned_email,
        "read_existing_owned_email_request",
        lambda _key: None,
    )
    monkeypatch.setattr(
        owned_email,
        "dispatch_email_by_current_owner",
        lambda *_args, **_kwargs: {
            "sent": False,
            "delivery_owner": "operations_core",
            "effect_status": "started",
            "send_error": "provider unavailable",
        },
    )

    assert report.main([]) == 1


def test_token_report_has_no_direct_email_notifier_import() -> None:
    path = ROOT / "scripts" / "token_report_email.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    direct_imports = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "volpred.publisher.email_notifier"
    ]

    assert direct_imports == []


def test_manual_token_report_uses_recipient_bound_owned_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_module()
    captured: list[object] = []

    class FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 7, 30, 8, 0, tzinfo=tz)

    monkeypatch.setattr(report, "datetime", FixedDateTime)
    monkeypatch.setattr(
        report,
        "_report",
        lambda *flags: {
            "totals": {"billable_total": 1},
            "week_range": "2026-07-27 → 2026-08-02",
        },
    )
    monkeypatch.setattr(
        report,
        "build_html",
        lambda *_args, **_kwargs: (
            "<p>manual token report</p>",
            "manual token report",
        ),
    )

    from volpred.ops.delivery import owned_email

    monkeypatch.setattr(
        owned_email,
        "read_existing_owned_email_request",
        lambda _key: None,
    )
    monkeypatch.setattr(
        owned_email,
        "dispatch_email_by_current_owner",
        lambda command, **_kwargs: (
            captured.append(command)
            or {
                "sent": True,
                "notification_id": "effect-manual-token-report",
                "delivery_owner": "operations_core",
                "effect_status": "delivered",
                "evidence_ref": "imap-sent:manual-token-report",
            }
        ),
    )

    class ForbiddenDirectNotifier:
        def __init__(self, *_args, **_kwargs) -> None:
            raise AssertionError("manual report used direct EmailNotifier")

    monkeypatch.setattr(
        "volpred.publisher.email_notifier.EmailNotifier",
        ForbiddenDirectNotifier,
    )

    assert report.main(["--to", "reader@example.com"]) == 0
    assert len(captured) == 1
    command = captured[0]
    assert command.idempotency_key == (
        "manual:token_report:2026-07-30:d108b279434fe1d5"
    )
    assert command.actor_ref == (
        "manual:token_report:"
        "manual:token_report:2026-07-30:d108b279434fe1d5"
    )
    assert command.recipient == "reader@example.com"
    assert command.title.startswith(
        "[新架構派發][VolPred Token 報表]"
    )


def test_manual_default_recipient_is_bound_into_effect_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_module()
    captured: list[object] = []

    class FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 7, 30, 8, 0, tzinfo=tz)

    monkeypatch.setattr(report, "datetime", FixedDateTime)
    monkeypatch.setattr(
        report,
        "_report",
        lambda *flags: {
            "totals": {"billable_total": 1},
            "week_range": "2026-07-27 → 2026-08-02",
        },
    )
    monkeypatch.setattr(
        report,
        "build_html",
        lambda *_args, **_kwargs: ("<p>default</p>", "default"),
    )

    from volpred.ops.delivery import owned_email

    monkeypatch.setattr(
        owned_email,
        "read_existing_owned_email_request",
        lambda _key: None,
    )
    monkeypatch.setattr(
        owned_email,
        "dispatch_email_by_current_owner",
        lambda command, **_kwargs: (
            captured.append(command)
            or {
                "sent": True,
                "notification_id": "effect-default-recipient",
                "delivery_owner": "operations_core",
                "effect_status": "delivered",
                "evidence_ref": "imap-sent:default-recipient",
            }
        ),
    )

    assert report.main([]) == 0
    assert len(captured) == 1
    command = captured[0]
    expected_digest = hashlib.sha256(
        command.recipient.encode()
    ).hexdigest()[:16]
    assert command.recipient == "yihao.lai@gmail.com"
    assert command.idempotency_key == (
        f"manual:token_report:2026-07-30:{expected_digest}"
    )


def test_calibrate_does_not_create_owned_email_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_module()
    monkeypatch.setattr(report, "CALIB_PATH", tmp_path / "calibration.json")
    monkeypatch.setattr(
        report,
        "_report",
        lambda *flags: {"totals": {"billable_total": 50}},
    )

    from volpred.ops.delivery import owned_email

    monkeypatch.setattr(
        owned_email,
        "dispatch_email_by_current_owner",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("calibration created an effect")
        ),
    )

    assert report.main(["--calibrate", "0.5"]) == 0
    assert report.CALIB_PATH.exists()


def test_manual_daily_retry_replays_before_report_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_module()

    class FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 7, 30, 8, 0, tzinfo=tz)

    monkeypatch.setattr(report, "datetime", FixedDateTime)
    monkeypatch.setattr(
        report,
        "_report",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("manual retry rebuilt the report")
        ),
    )

    from volpred.ops.delivery import owned_email

    durable = owned_email.OwnedEmailCommand(
        idempotency_key=(
            "manual:token_report:2026-07-30:d108b279434fe1d5"
        ),
        level="info",
        title="[VolPred Token 報表] historical immutable subject",
        recipient="reader@example.com",
        text_body="durable token report",
        html_body="<p>durable token report</p>",
        actor_ref=(
            "manual:token_report:"
            "manual:token_report:2026-07-30:d108b279434fe1d5"
        ),
    )
    monkeypatch.setattr(
        owned_email,
        "read_existing_owned_email_request",
        lambda _key: type("Existing", (), {"command": durable})(),
    )
    captured: list[object] = []
    monkeypatch.setattr(
        owned_email,
        "dispatch_email_by_current_owner",
        lambda command, **_kwargs: (
            captured.append(command)
            or {
                "sent": True,
                "notification_id": "effect-manual-replay",
                "delivery_owner": "operations_core",
                "effect_status": "delivered",
                "evidence_ref": "imap-sent:manual-replay",
            }
        ),
    )

    assert report.main(["--to", "reader@example.com"]) == 0
    assert captured == [durable]


def test_manual_force_creates_a_new_effect_identity_each_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _load_module()
    moments = iter(
        [
            datetime(2026, 7, 30, 8, 0, 0, 1, tzinfo=UTC),
            datetime(2026, 7, 30, 8, 0, 0, 1, tzinfo=UTC),
        ]
    )

    class SequencedDateTime:
        @classmethod
        def now(cls, tz=None):
            return next(moments).replace(tzinfo=tz)

    monkeypatch.setattr(report, "datetime", SequencedDateTime)
    monkeypatch.setattr(
        report,
        "_report",
        lambda *flags: {
            "totals": {"billable_total": 1},
            "week_range": "2026-07-27 → 2026-08-02",
        },
    )
    monkeypatch.setattr(
        report,
        "build_html",
        lambda *_args, **_kwargs: ("<p>force</p>", "force"),
    )

    from volpred.ops.delivery import owned_email

    commands: list[object] = []
    monkeypatch.setattr(
        owned_email,
        "dispatch_email_by_current_owner",
        lambda command, **_kwargs: (
            commands.append(command)
            or {
                "sent": True,
                "notification_id": f"effect-{len(commands)}",
                "delivery_owner": "operations_core",
                "effect_status": "delivered",
                "evidence_ref": f"imap-sent:{len(commands)}",
            }
        ),
    )

    assert report.main(["--to", "reader@example.com", "--force"]) == 0
    assert report.main(["--to", "reader@example.com", "--force"]) == 0
    assert len(commands) == 2
    assert commands[0].idempotency_key != commands[1].idempotency_key
