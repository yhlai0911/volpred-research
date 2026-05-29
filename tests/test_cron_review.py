from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cron_review.py"
SPEC = importlib.util.spec_from_file_location("cron_review_module", MODULE_PATH)
assert SPEC and SPEC.loader
cron_review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cron_review)

TPE = cron_review.TPE
expected_prev_fire = cron_review.expected_prev_fire
is_stale = cron_review.is_stale
last_log_run = cron_review.last_log_run


def test_last_log_run_returns_mtime_when_completion_marker_not_banner(tmp_path):
    """collect_tw 假 stale regression（2026-05-29）：完成標記 `✓ 台股數據收集完成`
    不是 ===exit/end banner，banner parser 抓不到 end；log-mtime 必須回傳，
    供 main() override 過舊的 banner/piggy-back end，消除假 30h stale。"""
    log = tmp_path / "collect_tw.log"
    log.write_text(
        "=== 台股數據收集: 2026-05-29 15:00 ===\n"
        "  0050.TW: 2026-05-29 close=105.40 (1552 rows)\n"
        "✓ 台股數據收集完成\n",
        encoding="utf-8",
    )
    res = last_log_run(log)
    # 完成標記非 banner → banner end 抓不到，但 mtime 必在且為近期
    assert res.get("mtime") is not None
    assert res["mtime"].tzinfo is not None  # tz-aware TPE
    # mtime 應約等於剛寫入的當下（寬鬆 24h 容差，跨時區安全）
    now = datetime.now(TPE)
    assert abs((now - res["mtime"]).total_seconds()) < 86400


def test_expected_prev_fire_respects_weekday_restricted_collect_us_cron():
    now = datetime(2026, 5, 25, 22, 0, tzinfo=TPE)  # Sunday night Taipei
    prev_fire = expected_prev_fire(now, "3 7 * * 2-6")

    assert prev_fire is not None
    assert prev_fire == datetime(2026, 5, 23, 7, 3, tzinfo=TPE)  # Saturday


def test_is_stale_does_not_false_alarm_on_weekend_gap_for_collect_us():
    now = datetime(2026, 5, 25, 22, 0, tzinfo=TPE)  # Sunday night Taipei
    last_end = datetime(2026, 5, 23, 8, 0, tzinfo=TPE)  # Saturday after run

    stale, flag = is_stale(
        now=now,
        last_end=last_end,
        cron_expr="3 7 * * 2-6",
        fallback_max_gap_h=30,
    )

    assert stale is False
    assert flag is None


def test_is_stale_flags_when_missing_expected_weekday_fire():
    now = datetime(2026, 5, 26, 12, 0, tzinfo=TPE)  # Tuesday noon
    last_end = datetime(2026, 5, 23, 8, 0, tzinfo=TPE)  # still last Saturday

    stale, flag = is_stale(
        now=now,
        last_end=last_end,
        cron_expr="3 7 * * 2-6",
        fallback_max_gap_h=30,
    )

    assert stale is True
    assert flag is not None
