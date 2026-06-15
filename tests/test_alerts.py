from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from volpred.ops.alerts import build_alert_condition_report, check_alert_conditions, send_alert


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_send_alert_persists_dedup_and_skips_within_24h(tmp_path: Path, monkeypatch):
    storage_dir = tmp_path / "storage"
    calls: list[tuple[str, str, str, str, str]] = []

    def fake_dispatch(*, level: str, title: str, body: str, recipient: str, storage_dir: str):
        calls.append((level, title, body, recipient, storage_dir))
        return {
            "notification_id": f"notif-{len(calls)}",
            "subject": f"[VolPred Alert][{level.upper()}] {title}",
            "sent": True,
            "configured": True,
            "send_error": None,
        }

    monkeypatch.setattr("volpred.ops.alerts._dispatch_alert_email", fake_dispatch)

    first = send_alert(
        "info",
        "test alert",
        "email alert system online",
        recipient="yihao.lai@gmail.com",
        storage_dir=str(storage_dir),
    )
    second = send_alert(
        "info",
        "test alert",
        "email alert system online",
        recipient="yihao.lai@gmail.com",
        storage_dir=str(storage_dir),
    )

    assert first["sent"] is True
    assert second["skipped"] is True
    assert len(calls) == 1

    dedup_path = storage_dir / "ops" / "alert_dedup.json"
    dedup = json.loads(dedup_path.read_text(encoding="utf-8"))
    assert dedup["alerts"][first["alert_key"]]["last_notification_id"] == "notif-1"


def test_build_alert_condition_report_flags_required_breaches(tmp_path: Path):
    storage_dir = tmp_path / "storage"
    now = datetime(2026, 4, 19, 5, 30, tzinfo=timezone.utc)

    _write_json(
        storage_dir / ".release_settings.json",
        {
            "mode": "auto",
            "interval_minutes": 60,
            "max_articles_per_run": 1,
            "due_only": True,
            "include_drafts": True,
            "preferred_audiences": [],
            "last_released_at": "2026-04-19T01:27:42+00:00",
            "updated_at": "2026-04-19T01:28:01+00:00",
        },
    )
    _write_json(storage_dir / "reports" / "feed.json", [])
    _write_text(
        storage_dir / "logs" / "cron" / "release_pool.log",
        "\n".join(
            [
                "=== [release-pool] fire at Sun Apr 19 09:00:00 CST 2026 ===",
                "=== exit 0 at Sun Apr 19 09:00:02 CST 2026 ===",
            ]
        ),
    )
    # Simulate a failing host cron so host_cron_fail breach triggers.
    # Per control-plane rule (v12): host_cron_fail 只看 storage/logs/cron/*.log 最新
    # "=== exit N ===" 非 0。scheduler_state staleness 不再 count (advisory only).
    _write_text(
        storage_dir / "logs" / "cron" / "daily_update.log",
        "\n".join(
            [
                "=== [daily-update] fire at Sun Apr 19 13:00:00 CST 2026 ===",
                "ERROR: yfinance rate limit exceeded",
                "=== exit 1 at Sun Apr 19 13:00:10 CST 2026 ===",
            ]
        ),
    )
    _write_json(
        storage_dir / "ops" / "scheduler_state.json",
        {
            "last_tick_at": (now - timedelta(hours=1)).isoformat(),
            "last_status": "ok",
            "last_reason": None,
            "last_result": None,
        },
    )

    report = build_alert_condition_report(storage_dir=str(storage_dir), now=now)
    conditions = {item["id"]: item for item in report["conditions"]}

    assert conditions["release_pool_gap"]["breached"] is True
    assert conditions["draft_pool_low"]["breached"] is True
    assert conditions["host_cron_fail"]["breached"] is True


def test_check_alert_conditions_sends_each_breached_condition_once(tmp_path: Path, monkeypatch):
    storage_dir = tmp_path / "storage"
    _write_json(storage_dir / ".release_settings.json", {"mode": "auto", "include_drafts": True})
    _write_json(storage_dir / "reports" / "feed.json", [])
    _write_text(
        storage_dir / "logs" / "cron" / "release_pool.log",
        "=== [release-pool] fire at Sun Apr 19 09:00:00 CST 2026 ===\n=== exit 1 at Sun Apr 19 09:00:02 CST 2026 ===\n",
    )
    _write_json(
        storage_dir / "ops" / "scheduler_state.json",
        {"last_tick_at": "2026-04-19T00:00:00+00:00", "last_status": "invalid_state"},
    )

    sent_titles: list[str] = []

    def fake_send_alert(level: str, title: str, body: str, recipient: str = "", **kwargs):
        sent_titles.append(title)
        return {
            "level": level,
            "title": title,
            "recipient": recipient,
            "sent": True,
            "skipped": False,
            "notification_id": f"notif-{len(sent_titles)}",
        }

    monkeypatch.setattr("volpred.ops.alerts.send_alert", fake_send_alert)

    result = check_alert_conditions(storage_dir=str(storage_dir))

    assert result["breach_count"] == 3
    assert result["sent_count"] == 3
    assert sent_titles == [
        "Release pool cron gap > 2.5h (interval=120min)",
        "Draft pool below threshold (<4)",
        "Host cron failure detected",
    ]


def test_host_cron_fail_severity_calibration(tmp_path: Path):
    """2026-06-15 email-11745: a single self-recovering SIGALRM hang (exit=142)
    must be WARN, not CRITICAL noise; sustained (>=2 consec) or non-hang failure
    stays CRITICAL."""
    from datetime import datetime, timezone

    from volpred.ops.alerts import _parse_host_cron_state

    storage = tmp_path / "storage"
    _write_json(
        storage / "ops" / "scheduler_state.json",
        {"last_tick_at": "2026-06-15T00:00:00+00:00", "last_status": "ok"},
    )
    now = datetime.now(timezone.utc)

    def write_exits(codes):
        lines = []
        for i, c in enumerate(codes):
            lines.append(f"=== [hourly_dispatch] fire run {i} ===")
            lines.append(f"=== exit {c} at Sun Jun 15 1{i}:00:00 CST 2026 ===")
        _write_text(storage / "logs" / "cron" / "hourly_dispatch.log", "\n".join(lines))

    # 1) lone hang (latest=142, consec=1) → breached WARN
    write_exits([0, 0, 0, 142])
    r = _parse_host_cron_state(str(storage), now)
    assert r["breached"] is True and r["level"] == "warn"

    # 2) recovered (142 then 0) → not breached
    write_exits([0, 142, 0])
    r = _parse_host_cron_state(str(storage), now)
    assert r["breached"] is False

    # 3) sustained (2 consecutive 142) → CRITICAL
    write_exits([0, 142, 142])
    r = _parse_host_cron_state(str(storage), now)
    assert r["breached"] is True and r["level"] == "critical"

    # 4) non-hang failure (exit 1: perm/path/FDA) even single → CRITICAL
    write_exits([0, 0, 1])
    r = _parse_host_cron_state(str(storage), now)
    assert r["breached"] is True and r["level"] == "critical"
