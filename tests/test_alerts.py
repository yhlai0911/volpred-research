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
                "=== [daily_update] fire at Sun Apr 19 13:00:00 CST 2026 ===",
                "ERROR: yfinance rate limit exceeded",
                "=== [daily_update] exit 1 at Sun Apr 19 13:00:10 CST 2026 ===",
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


def test_release_pool_fallback_fire_marker_counts_as_machinery_health(tmp_path: Path):
    from volpred.ops.alerts import _parse_release_pool_state

    storage_dir = tmp_path / "storage"
    now = datetime(2026, 6, 21, 22, 24, tzinfo=timezone.utc)
    _write_json(
        storage_dir / ".release_settings.json",
        {
            "mode": "auto",
            "interval_minutes": 180,
            "last_released_at": "2026-06-21T18:00:21.110935+00:00",
            "updated_at": "2026-06-21T18:00:39.515139+00:00",
        },
    )
    _write_text(
        storage_dir / "logs" / "cron" / "release_pool.log",
        "\n".join(
            [
                "=== [release_pool] check_alerts fallback fire at 2026-06-21T22:00:56+00:00 ===",
                "=== [release_pool] exit 0 at 2026-06-21T22:00:56+00:00 (fallback) ===",
            ]
        ),
    )

    condition = _parse_release_pool_state(str(storage_dir), now)

    assert condition["breached"] is False
    assert condition["details"]["machinery_last_at"] == "2026-06-21T22:00:56+00:00"


def test_release_pool_starved_alert_includes_preview_counts(tmp_path: Path, monkeypatch):
    from volpred.ops.alerts import _parse_release_pool_state

    storage_dir = tmp_path / "storage"
    now = datetime(2026, 6, 22, 1, 30, tzinfo=timezone.utc)
    _write_json(
        storage_dir / ".release_settings.json",
        {
            "mode": "auto",
            "interval_minutes": 180,
            "last_released_at": "2026-06-21T18:00:21+00:00",
            "updated_at": "2026-06-22T01:00:00+00:00",
        },
    )
    _write_text(
        storage_dir / "logs" / "cron" / "release_pool.log",
        "=== [release_pool] check_alerts fallback fire at 2026-06-22T01:00:00+00:00 ===\n",
    )
    monkeypatch.setattr(
        "volpred.ops.alerts._release_pool_preview_for_alert",
        lambda storage_dir: {
            "pool_counts": {
                "draft": 46,
                "scheduled": 0,
                "eligible_before_dedup": 46,
                "dedup_flagged": 46,
                "eligible": 0,
            },
            "next_candidates": [],
        },
    )

    condition = _parse_release_pool_state(str(storage_dir), now)

    assert condition["breached"] is True
    assert condition["level"] == "warn"
    assert "dedup_flagged: 46" in condition["body"]
    assert "eligible_after_dedup: 0" in condition["body"]
    assert condition["details"]["release_preview"]["pool_counts"]["eligible"] == 0


def test_check_alert_conditions_sends_each_breached_condition_once(tmp_path: Path, monkeypatch):
    storage_dir = tmp_path / "storage"
    now = datetime(2026, 4, 19, 12, 0, tzinfo=timezone.utc)
    _write_json(storage_dir / ".release_settings.json", {"mode": "auto", "include_drafts": True})
    # Published (not draft) item keeps draft_pool_low breaching (0 drafts) while
    # quieting publishing_freshness (a recent published_at < 5h before `now`).
    _write_json(
        storage_dir / "reports" / "feed.json",
        [{"status": "published", "published_at": "2026-04-19T11:00:00+00:00"}],
    )
    # Isolate the newer (non cron/pool) conditions so this test asserts only the
    # cron/pool set: strategy_metrics + gmail-poll state present (fresh mtime),
    # disk usage forced low. (paper_trading absent → gap check is ok.)
    _write_json(storage_dir / "strategy_metrics.json", {"x": 1})
    _write_json(storage_dir / "ops" / "gmail_inbox_state.json", {"last_poll": "ok"})
    _write_json(
        storage_dir / "work_log.json",
        [{"timestamp": now.isoformat(), "task_type": "platform_ops"}],
    )
    monkeypatch.setattr(
        "volpred.ops.health.shutil.disk_usage",
        lambda _p: __import__("collections").namedtuple("U", ["total", "used", "free"])(100, 10, 90),
    )
    # exit 1 in the NEW canonical wrapper format (`=== [job] exit N at ... ===`) so
    # both release_pool_gap (no recent fire) and host_cron_fail (non-zero exit) breach.
    _write_text(
        storage_dir / "logs" / "cron" / "release_pool.log",
        "=== [release-pool] fire at Sun Apr 19 09:00:00 CST 2026 ===\n"
        "=== [release-pool] exit 1 at Sun Apr 19 09:00:02 CST 2026 ===\n",
    )
    _write_json(
        storage_dir / "ops" / "scheduler_state.json",
        {"last_tick_at": "2026-04-19T00:00:00+00:00", "last_status": "invalid_state"},
    )
    # Isolate M2/M3 staleness conditions so this test asserts only the cron/pool set.
    # Fresh knowledge entry (< 2d before `now`) keeps knowledge_stale quiet.
    _write_json(
        storage_dir / "memory" / "knowledge.json",
        [{"id": "k-test", "created_at": "2026-04-19T10:00:00+00:00"}],
    )
    # Fresh paper-line activity (injected paper_root with a .tex) keeps paper_stale quiet.
    paper_root = tmp_path / "paper"
    _write_text(paper_root / "demo" / "body.tex", "\\documentclass{article}")

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

    result = check_alert_conditions(
        storage_dir=str(storage_dir), now=now, paper_root=paper_root
    )

    assert result["breach_count"] == 3
    assert result["sent_count"] == 3
    # each breached condition sends exactly once (unique titles), in condition order
    assert len(sent_titles) == 3 and len(set(sent_titles)) == 3
    assert sent_titles[0].startswith("Release pool cron gap")
    assert sent_titles[1] == "Draft pool below threshold (<4)"
    assert sent_titles[2] == "Host cron failure detected"


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
            lines.append(
                f"=== [hourly_dispatch] exit {c} at Sun Jun 15 1{i}:00:00 CST 2026 ==="
            )
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

    # 5) non-audit jobs can explicitly declare exit_semantics=findings in
    # config/runtime_schedules.json; indicator_arena_daily uses exit 1 for
    # skip/findings signals and should not be counted as host-cron infra down.
    write_exits([0])
    _write_text(
        storage / "logs" / "cron" / "indicator_arena_daily.log",
        "=== [indicator_arena_daily] fire at Sun Jun 15 10:00:00 CST 2026 ===\n"
        "=== [indicator_arena_daily] exit 1 at Sun Jun 15 10:01:00 CST 2026 ===\n",
    )
    r = _parse_host_cron_state(str(storage), now)
    assert r["breached"] is False


def test_findings_exit_logs_from_schedule_config():
    from volpred.ops.alerts import _findings_exit_logs_from_schedule_config

    config = {
        "system_crontab": {
            "items": [
                {
                    "id": "indicator_arena_daily",
                    "log_path": "storage/logs/cron/indicator_arena_daily.log",
                    "exit_semantics": "findings",
                },
                {
                    "id": "daily_update",
                    "log_path": "storage/logs/cron/daily_update.log",
                },
            ]
        },
        "cron_jobs": [
            {
                "id": "legacy_findings_job",
                "log": "storage/logs/cron/legacy_findings.log",
                "exit_semantics": "findings",
            }
        ],
    }

    assert _findings_exit_logs_from_schedule_config(config) == {
        "indicator_arena_daily.log",
        "legacy_findings.log",
    }


def test_paper_stale_severity_and_isolation(tmp_path: Path):
    """M3 paper-line staleness (2026-06-21 boss email-11851/11854 對稱補強): the whole
    paper/ line going >7d without any .tex/.md edit = warn, >14d = critical. Signal is
    max mtime across the injected paper_root so it is unit-testable."""
    import os

    from volpred.ops.alerts import _parse_paper_stale_state

    paper_root = tmp_path / "paper"
    tex = paper_root / "p1" / "body.tex"
    _write_text(tex, "\\documentclass{article}")
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    os.utime(tex, (base.timestamp(), base.timestamp()))

    # fresh (3d) → not breached
    r = _parse_paper_stale_state(base + timedelta(days=3), paper_root)
    assert r["breached"] is False and r["id"] == "paper_stale"

    # 8d → warn
    r = _parse_paper_stale_state(base + timedelta(days=8), paper_root)
    assert r["breached"] is True and r["level"] == "warn"

    # 15d → critical
    r = _parse_paper_stale_state(base + timedelta(days=15), paper_root)
    assert r["breached"] is True and r["level"] == "critical"

    # a non-manuscript file (figure/data) must NOT count as paper-line activity
    _write_text(paper_root / "p1" / "fig.pdf", "binary-ish")
    os.utime(paper_root / "p1" / "fig.pdf", (base.timestamp() + 86400 * 30, base.timestamp() + 86400 * 30))
    r = _parse_paper_stale_state(base + timedelta(days=8), paper_root)
    assert r["breached"] is True and r["level"] == "warn"  # still keyed off the .tex mtime

    # empty paper line (no .tex/.md anywhere) → critical
    empty_root = tmp_path / "empty_paper"
    empty_root.mkdir()
    r = _parse_paper_stale_state(base, empty_root)
    assert r["breached"] is True and r["level"] == "critical"
