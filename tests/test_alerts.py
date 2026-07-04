from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from volpred.ops.alerts import (
    _format_telegram_alert_text,
    _parse_content_quality_state,
    _parse_draft_pool_state,
    _parse_loop_health_state,
    _parse_paper_website_drift_state,
    build_alert_condition_report,
    check_alert_conditions,
    send_alert,
)
from volpred.ops.boss_facing import boss_facing_alert, plainify_boss_text


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_parse_loop_health_breaches_on_task_outcome_with_stable_title(tmp_path: Path):
    storage_dir = tmp_path / "storage"
    now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    # Mostly-failed terminal tasks → task_outcome degrading → breach.
    _write_json(
        storage_dir / "next_tasks.json",
        [{"id": f"f{i}", "status": "failed", "completed_at": recent} for i in range(8)]
        + [{"id": "s1", "status": "succeeded", "completed_at": recent}],
    )
    result = _parse_loop_health_state(str(storage_dir), now)
    assert result["breached"] is True
    assert result["id"] == "loop_health"
    # Title lists the metric NAME (stable for sha256(level+title) dedup), not numbers.
    assert "task_outcome" in result["title"]
    assert "Loop-health" in result["title"]


def test_parse_loop_health_not_breached_on_clean_state(tmp_path: Path):
    storage_dir = tmp_path / "storage"
    now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
    recent = (now - timedelta(days=1)).isoformat()
    _write_json(
        storage_dir / "next_tasks.json",
        [{"id": f"s{i}", "status": "succeeded", "completed_at": recent} for i in range(10)],
    )
    result = _parse_loop_health_state(str(storage_dir), now)
    assert result["breached"] is False
    assert result["title"] == "loop_health ok"


def test_parse_content_quality_breaches_on_lazypack_gap(tmp_path: Path):
    storage_dir = tmp_path / "storage"
    now = datetime(2026, 6, 30, 4, 0, tzinfo=timezone.utc)
    base = datetime(2026, 6, 30, 3, 0, tzinfo=timezone.utc)
    good = (
        "本文引用 K123，資料來源：yfinance。\n\n"
        "![主圖](https://example.com/chart.png)\n\n"
        "## 懶人包圖組\n\n"
        "![概念](https://example.com/lazypack.png)\n"
    )
    missing = "本文引用 K124，資料來源：yfinance。\n\n![主圖](https://example.com/chart.png)\n"
    _write_json(
        storage_dir / "reports" / "feed.json",
        [
            {
                "id": "m1",
                "status": "published",
                "audience": "general",
                "title": "有懶人包",
                "content": good,
                "published_at": base.isoformat(),
            },
            {
                "id": "m2",
                "status": "published",
                "audience": "general",
                "title": "缺懶人包 A",
                "content": missing,
                "published_at": (base - timedelta(minutes=60)).isoformat(),
            },
            {
                "id": "m3",
                "status": "published",
                "audience": "general",
                "title": "缺懶人包 B",
                "content": missing,
                "published_at": (base - timedelta(minutes=120)).isoformat(),
            },
        ],
    )

    result = _parse_content_quality_state(str(storage_dir), now)

    assert result["breached"] is True
    assert result["level"] == "warn"
    assert "懶人包覆蓋不足" in result["title"]
    assert "content_completeness:lazypack_gap" not in result["title"]
    assert "m2, m3" in result["body"]
    assert "content_completeness:lazypack_gap" not in result["body"]
    assert "content_completeness" in result["details"]


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


def test_send_alert_telegram_mirror_formats_markdown_without_mutating_email_body(
    tmp_path: Path, monkeypatch
):
    storage_dir = tmp_path / "storage"
    email_bodies: list[str] = []
    telegram_calls: list[dict[str, object]] = []
    body = (
        "# Hourly-22 send-alert smoke\n\n"
        "## 觸發條件\n"
        "- queue mirror check\n"
        "| 項目 | 結果 |\n"
        "|---|---|\n"
        "| emoji | ok |\n"
    )

    def fake_dispatch(*, level: str, title: str, body: str, recipient: str, storage_dir: str):
        email_bodies.append(body)
        return {
            "notification_id": "notif-tg-format",
            "subject": f"[VolPred Alert][{level.upper()}] {title}",
            "sent": True,
            "configured": True,
            "send_error": None,
        }

    def fake_send_telegram(text: str, *, storage_dir: str, disable_notification: bool):
        telegram_calls.append(
            {
                "text": text,
                "storage_dir": storage_dir,
                "disable_notification": disable_notification,
            }
        )
        return {"sent": True, "message_ids": [123]}

    monkeypatch.setattr("volpred.ops.alerts._dispatch_alert_email", fake_dispatch)
    monkeypatch.setattr("volpred.ops.telegram.send_telegram", fake_send_telegram)

    result = send_alert(
        "info",
        "tg mirror format",
        body,
        recipient="yihao.lai@gmail.com",
        storage_dir=str(storage_dir),
        force_send=True,
    )

    assert email_bodies == [body]
    assert result["telegram"] == {"sent": True, "message_ids": [123]}
    assert len(telegram_calls) == 1
    tg_text = str(telegram_calls[0]["text"])
    assert telegram_calls[0]["disable_notification"] is True
    assert tg_text.startswith("ℹ️ [INFO] tg mirror format")
    assert "📌 白話結論" in tg_text
    assert "系統偵測到需要處理的營運風險" in tg_text
    assert "📌 Hourly-22 發送警報 smoke" in tg_text
    assert "🚦 觸發條件" in tg_text
    assert "• queue mirror check" in tg_text
    assert "• 項目: 結果" in tg_text
    assert "• emoji: ok" in tg_text
    assert "## " not in tg_text
    assert "|---" not in tg_text


def test_boss_facing_alert_plainifies_jargon_and_keeps_commands():
    title = "內容品質巡檢觸發（publish_rhythm:drought / content_completeness:lazypack_gap）"
    body = "\n".join(
        [
            "## 觸發條件",
            "- `publish_rhythm=drought` → `daily_digest_uniqueness=duplicate`",
            "1. `content_completeness:lazypack_gap` → 補圖",
            "   uv run volpred ops release-pool-by-settings",
        ]
    )

    plain_title, plain_body = boss_facing_alert(title, body)

    assert "發文間隔過久" in plain_title
    assert "懶人包覆蓋不足" in plain_title
    assert "publish_rhythm:drought" not in plain_title
    assert "## 白話結論" in plain_body
    assert "發文間隔過久" in plain_body
    assert "同一天出現超過一篇每日精選導讀" in plain_body
    assert "content_completeness:lazypack_gap" not in plain_body
    assert "uv run volpred ops release-pool-by-settings" in plain_body


def test_plainify_boss_text_replaces_known_terms_without_touching_paths():
    text = (
        "cluster-pressure and arc-dup hit content_quality, "
        "see `storage/ops/content_quality_report.json`"
    )

    out = plainify_boss_text(text)

    assert "主題集中壓力" in out
    assert "舊題材重複" in out
    assert "`storage/ops/content_quality_report.json`" in out


def test_format_telegram_alert_text_truncates_to_telegram_limit():
    text = _format_telegram_alert_text(
        level="warn",
        title="long body",
        body="x" * 5000,
    )

    assert len(text) <= 4096
    assert text.startswith("⚠️ [WARN] long body")
    assert text.endswith("…（已截斷，完整內容請看 email）")


def test_parse_draft_pool_nonzero_deficit_is_info_observation(tmp_path: Path):
    storage_dir = tmp_path / "storage"
    _write_json(
        storage_dir / "reports" / "feed.json",
        [
            {"id": "d1", "status": "draft"},
            {"id": "d2", "status": "draft"},
            {"id": "d3", "status": "draft"},
        ],
    )

    condition = _parse_draft_pool_state(str(storage_dir))

    assert condition["breached"] is False
    assert condition["level"] == "info"
    assert condition["body"] == ""
    assert condition["details"]["draft_count"] == 3
    assert condition["details"]["self_healing"] is True
    assert condition["details"]["escalates_when_draft_count"] == 0


def test_parse_draft_pool_empty_still_escalates(tmp_path: Path):
    storage_dir = tmp_path / "storage"
    _write_json(
        storage_dir / "reports" / "feed.json",
        [{"id": "p1", "status": "published"}],
    )

    condition = _parse_draft_pool_state(str(storage_dir))

    assert condition["breached"] is True
    assert condition["level"] == "critical"
    assert condition["details"]["draft_count"] == 0
    assert condition["details"]["self_healing"] is False
    assert "Draft 池已空" in condition["body"]


def test_check_alert_conditions_does_not_send_nonbreached_info_observations(
    tmp_path: Path, monkeypatch
):
    send_calls: list[tuple[str, str, str]] = []

    monkeypatch.setattr(
        "volpred.ops.alerts.build_alert_condition_report",
        lambda **kwargs: {
            "generated_at": "2026-07-03T00:00:00+00:00",
            "recipient": "yihao.lai@gmail.com",
            "breach_count": 0,
            "conditions": [
                {
                    "id": "draft_pool_low",
                    "breached": False,
                    "level": "info",
                    "title": "Draft pool below threshold (<4)",
                    "body": "",
                    "details": {"draft_count": 3, "self_healing": True},
                }
            ],
        },
    )

    def fake_send_alert(level: str, title: str, body: str, **kwargs):
        send_calls.append((level, title, body))
        return {"sent": True, "skipped": False}

    monkeypatch.setattr("volpred.ops.alerts.send_alert", fake_send_alert)

    result = check_alert_conditions(storage_dir=str(tmp_path / "storage"))

    assert send_calls == []
    assert result["sent_count"] == 0
    assert result["skipped_count"] == 0


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
    # cluster_cap_drift reads the REAL feed via topic_clusters.recent_cluster_counts
    # (it does not honour storage_dir), so without this stub it leaks production
    # cluster overshoot into the fixture and breaches non-deterministically. Quiet
    # it so this test isolates only the cron/pool set. (storage_dir bug tracked
    # separately — surfaced by the 2026-06-29 loop-health work.)
    monkeypatch.setattr("volpred.topic_clusters.recent_cluster_counts", lambda days=30: ({}, 0))
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
    """2026-06-15 email-11745 + 2026-07-04 recalibration (boss Telegram msg 114/121/
    141): a self-recovering SIGALRM hang (exit=142) is WARN, not CRITICAL noise —
    including a consecutive-142 chain, which still self-recovers on the next fire.
    Only a non-self-recovering hard failure (exit != {142,75}) stays CRITICAL."""
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

    # 3) sustained self-recovering hang (2 consecutive 142) → WARN, NOT CRITICAL
    #    (2026-07-04 recalibration, boss Telegram msg 114/121/141): 142 self-recovers
    #    on the next fire; consecutive hangs still self-recover, so they are noise at
    #    CRITICAL. Real sustained outage is caught by the outcome-level dead-man
    #    switches (release_pool_gap / publishing_freshness), not by paging on 142.
    write_exits([0, 142, 142])
    r = _parse_host_cron_state(str(storage), now)
    assert r["breached"] is True and r["level"] == "warn"

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


def test_host_cron_fail_quota_window_is_self_recovering(tmp_path: Path):
    """2026-07-02: Claude Max rolling-5h session-limit exhaustion (wrapper exit=75)
    is an expected, scheduled, self-resetting quota window — Codex failover covers
    the slot and Claude auth returns on its own at reset. It must never fire a
    CRITICAL host_cron_fail, even across >=2 consecutive fires (a quota window
    legitimately spans multiple fires). Post-2026-07-04, a 142 hang chain is also
    self-recovering → WARN (both codes are exempt from CRITICAL escalation)."""
    from datetime import datetime, timezone

    from volpred.ops.alerts import _parse_host_cron_state

    storage = tmp_path / "storage"
    _write_json(
        storage / "ops" / "scheduler_state.json",
        {"last_tick_at": "2026-07-02T00:00:00+00:00", "last_status": "ok"},
    )
    now = datetime.now(timezone.utc)

    def write_exits(codes):
        lines = []
        for i, c in enumerate(codes):
            lines.append(f"=== [hourly_dispatch] fire run {i} ===")
            lines.append(
                f"=== [hourly_dispatch] exit {c} at Thu Jul 2 1{i}:00:00 CST 2026 ==="
            )
        _write_text(storage / "logs" / "cron" / "hourly_dispatch.log", "\n".join(lines))

    # 1) lone quota window (latest=75) → breached WARN, not critical
    write_exits([0, 0, 0, 75])
    r = _parse_host_cron_state(str(storage), now)
    assert r["breached"] is True and r["level"] == "warn"

    # 2) sustained quota window (2 consecutive 75) → still WARN (expected gap,
    #    NOT a sustained-outage critical like 2x 142 would be)
    write_exits([0, 75, 75])
    r = _parse_host_cron_state(str(storage), now)
    assert r["breached"] is True and r["level"] == "warn"

    # 3) quota then recovered (75 then 0) → not breached
    write_exits([0, 75, 0])
    r = _parse_host_cron_state(str(storage), now)
    assert r["breached"] is False

    # 4) a real error AFTER a quota window (latest=1) → CRITICAL (quota does not
    #    mask a genuine current failure)
    write_exits([0, 75, 1])
    r = _parse_host_cron_state(str(storage), now)
    assert r["breached"] is True and r["level"] == "critical"

    # 5) quota AFTER a real error (latest=75) → WARN (the old error is history;
    #    if it were ongoing this fire would also be a hard fail, not quota)
    write_exits([0, 1, 75])
    r = _parse_host_cron_state(str(storage), now)
    assert r["breached"] is True and r["level"] == "warn"

    # 6) 142 hang chain is self-recovering → WARN, same as a 75 quota chain
    #    (2026-07-04 recalibration): excluding 75 from the consecutive count must not
    #    resurrect a 2x-142 → CRITICAL rule. Both 142 and 75 self-recover; only a
    #    non-self-recovering hard failure escalates.
    write_exits([0, 142, 142])
    r = _parse_host_cron_state(str(storage), now)
    assert r["breached"] is True and r["level"] == "warn"


def test_host_cron_fail_git_push_held_is_benign(tmp_path: Path):
    """2026-07-03: cron_git_push_backup.sh HOLDS a push (distinct exit 120) when HEAD
    carries a NEW silent fallback, and self-sends its own targeted WARN. That hold is
    the guard working as designed — NOT a cron infra failure. It must be fully exempt
    from host_cron_fail (no CRITICAL), while its REAL failures (origin divergence /
    real push failure = exit 1) still escalate. Root cause guard for the 4-day 28x
    false-CRITICAL cascade (a single line-38 false-positive silent-fallback flag)."""
    from datetime import datetime, timezone

    from volpred.ops.alerts import _parse_host_cron_state

    storage = tmp_path / "storage"
    _write_json(
        storage / "ops" / "scheduler_state.json",
        {"last_tick_at": "2026-07-03T00:00:00+00:00", "last_status": "ok"},
    )
    now = datetime.now(timezone.utc)

    def write_push_exits(codes):
        lines = []
        for i, c in enumerate(codes):
            lines.append(f"=== [git_push_backup] fire run {i} ===")
            lines.append(
                f"=== [git_push_backup] exit {c} at Fri Jul 3 1{i}:00:00 CST 2026 ==="
            )
        _write_text(storage / "logs" / "cron" / "git_push_backup.log", "\n".join(lines))

    # 1) lone held push (latest=120) → NOT breached (benign, self-reported WARN)
    write_push_exits([0, 0, 120])
    r = _parse_host_cron_state(str(storage), now)
    assert r["breached"] is False

    # 2) sustained held pushes (many 120 in a row, the 4-day cascade shape) → still
    #    NOT breached: no matter how long a hold persists, it is never host_cron_fail
    write_push_exits([120, 120, 120, 120])
    r = _parse_host_cron_state(str(storage), now)
    assert r["breached"] is False

    # 3) a REAL push failure (latest=1) still fires CRITICAL — the held exemption must
    #    not mask genuine backup failures (credential/network/divergence)
    write_push_exits([0, 120, 1])
    r = _parse_host_cron_state(str(storage), now)
    assert r["breached"] is True and r["level"] == "critical"

    # 4) held push breaks the consecutive-failure chain: [1, 1, 120] latest is benign
    #    → not breached (current state is a benign hold, past failures superseded)
    write_push_exits([1, 1, 120])
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


def test_runtime_schedule_marks_known_findings_exit_jobs():
    from volpred.ops.alerts import _findings_exit_logs_from_schedule_config

    config = json.loads(Path("config/runtime_schedules.json").read_text(encoding="utf-8"))
    logs = _findings_exit_logs_from_schedule_config(config)

    assert {
        "audit_publish_sync.log",
        "audit_fb_pipeline.log",
        "indicator_arena_daily.log",
        "dreaming_review.log",
    } <= logs
    assert "git_push_backup.log" not in logs
    assert "gmail_poll.log" not in logs


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


# ─── paper_website_drift（2026-07-01 loop-eng：網站論文卡片 status vs pipeline 決策 drift）───
def _patch_drift_sources(monkeypatch, pipeline_papers, website_rows):
    monkeypatch.setattr(
        "volpred.ops.alerts.load_json",
        lambda path, default=None: {"papers": pipeline_papers},
    )
    monkeypatch.setattr(
        "volpred.ops.papers.list_papers",
        lambda: website_rows,
    )


def test_paper_website_drift_breaches_on_overclaim(monkeypatch):
    # pipeline stage=revision（最高 working）但網站顯示 submitted → over-claim。
    _patch_drift_sources(
        monkeypatch,
        pipeline_papers=[{"paper": "demo-A", "stage": "revision", "journal_target": "IJF (primary)"}],
        website_rows=[{"id": "demo-A", "status": "submitted", "target_journal": None}],
    )
    r = _parse_paper_website_drift_state(datetime.now(timezone.utc))
    assert r["breached"] is True
    assert r["level"] == "warn"
    assert r["details"]["over_claims"][0]["paper"] == "demo-A"
    assert r["details"]["over_claims"][0]["max_acceptable_status"] == "working"
    # journal 缺口附註（pipeline 有 target 但網站 null），但非 breach（資訊性）
    assert r["details"]["journal_gaps"][0]["paper"] == "demo-A"


def test_paper_website_drift_underclaim_is_not_a_breach(monkeypatch):
    # pipeline stage=under_journal_review（允許到 submitted）但網站保守顯示 working → under-claim，不 breach。
    # 這是刻意設計：「pipeline aspirational 但尚未驗證的長期投稿」時網站保守顯示不被誤判為升級。
    _patch_drift_sources(
        monkeypatch,
        pipeline_papers=[{"paper": "demo-B", "stage": "under_journal_review", "journal_target": "decide"}],
        website_rows=[{"id": "demo-B", "status": "working", "target_journal": None}],
    )
    r = _parse_paper_website_drift_state(datetime.now(timezone.utc))
    assert r["breached"] is False
    assert r["details"]["over_claims"] == []
    # journal_target=decide 不算缺口
    assert r["details"]["journal_gaps"] == []


def test_paper_website_drift_in_sync_no_breach(monkeypatch):
    _patch_drift_sources(
        monkeypatch,
        pipeline_papers=[{"paper": "demo-C", "stage": "working", "journal_target": "FRL"}],
        website_rows=[{"id": "demo-C", "status": "working", "target_journal": "Finance Research Letters"}],
    )
    r = _parse_paper_website_drift_state(datetime.now(timezone.utc))
    assert r["breached"] is False
    assert r["title"] == "Paper website in sync with pipeline"


def test_paper_website_drift_supabase_failure_is_fail_open(monkeypatch):
    # Supabase 查詢失敗 → degraded、不 crash、不誤 breach。
    monkeypatch.setattr(
        "volpred.ops.alerts.load_json",
        lambda path, default=None: {"papers": [{"paper": "x", "stage": "revision"}]},
    )

    def _boom():
        raise RuntimeError("supabase down")

    monkeypatch.setattr("volpred.ops.papers.list_papers", _boom)
    r = _parse_paper_website_drift_state(datetime.now(timezone.utc))
    assert r["breached"] is False
    assert r["details"]["degraded"] is True


# ---------------------------------------------------------------------------
# push_backlog — 2026-07-04 26h push-hold incident: the silent-fallback gate
# correctly held pushes but nothing escalated a PERSISTENT hold (the job's own
# warn was deduped 24h). This condition watches the harm directly: the age of
# the oldest commit not on origin/main.
# ---------------------------------------------------------------------------


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _patch_git(monkeypatch, *, ahead: int, oldest_epoch: int | None):
    import subprocess as _sp

    def fake_run(argv, **kwargs):
        if "rev-list" in argv:
            return _FakeCompleted(0, f"{ahead}\n")
        if "log" in argv:
            stamps = "\n".join(str(oldest_epoch + i * 60) for i in range(ahead)) if oldest_epoch else ""
            return _FakeCompleted(0, stamps)
        raise AssertionError(f"unexpected git argv: {argv}")

    monkeypatch.setattr(_sp, "run", fake_run)


def test_push_backlog_ok_when_nothing_unpushed(tmp_path: Path, monkeypatch):
    from volpred.ops.alerts import _parse_push_backlog_state

    _patch_git(monkeypatch, ahead=0, oldest_epoch=None)
    now = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
    result = _parse_push_backlog_state(str(tmp_path / "storage"), now)
    assert result["breached"] is False
    assert result["details"]["ahead_count"] == 0


def test_push_backlog_warns_after_3h(tmp_path: Path, monkeypatch):
    from volpred.ops.alerts import _parse_push_backlog_state

    now = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
    oldest = int((now - timedelta(hours=4)).timestamp())
    _patch_git(monkeypatch, ahead=5, oldest_epoch=oldest)
    result = _parse_push_backlog_state(str(tmp_path / "storage"), now)
    assert result["breached"] is True
    assert result["level"] == "warn"
    assert result["details"]["ahead_count"] == 5
    assert "建議行動" in result["body"]


def test_push_backlog_critical_after_8h(tmp_path: Path, monkeypatch):
    from volpred.ops.alerts import _parse_push_backlog_state

    now = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
    oldest = int((now - timedelta(hours=26)).timestamp())
    _patch_git(monkeypatch, ahead=47, oldest_epoch=oldest)
    result = _parse_push_backlog_state(str(tmp_path / "storage"), now)
    assert result["breached"] is True
    assert result["level"] == "critical"


def test_push_backlog_recent_commits_within_grace_not_breached(tmp_path: Path, monkeypatch):
    """Commits made minutes ago that simply haven't hit the next hourly push
    yet must NOT breach — that's normal operation, not a stuck backlog."""
    from volpred.ops.alerts import _parse_push_backlog_state

    now = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
    oldest = int((now - timedelta(minutes=40)).timestamp())
    _patch_git(monkeypatch, ahead=3, oldest_epoch=oldest)
    result = _parse_push_backlog_state(str(tmp_path / "storage"), now)
    assert result["breached"] is False


def test_push_backlog_probe_failure_is_logged_not_breached(tmp_path: Path, monkeypatch):
    """A git probe failure must fail open (no false alarm) but leave a trace."""
    import subprocess as _sp

    from volpred.ops.alerts import _parse_push_backlog_state

    def boom(argv, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr(_sp, "run", boom)
    now = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
    result = _parse_push_backlog_state(str(tmp_path / "storage"), now)
    assert result["breached"] is False
    assert "probe failed" in result["details"]["note"]
