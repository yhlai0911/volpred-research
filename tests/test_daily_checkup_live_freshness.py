"""live_freshness 必須依「排程 + 交易日曆」判斷資料該有多新，不是數日曆天。

回歸的是 2026-07-14 04:52 那封誤報信：daily-checkup 排 09:40，但 launchd 睡眠喚醒後
補跑了漏掉的班，於是它在週二凌晨（collect_us 07:03 還沒跑）看到上週五的 data_date，
用「>3 個日曆天」判準報 warn 並寄信給老闆 —— 而那個時點資料本來就只該有上週五的。

同一個粗判準的另一面是漏報：週間真的落後 2 個交易日只有 3 個日曆天，躲得過 >3。
所以測試兩面都要壓：正常時點不准叫，真落後不准不叫。
"""

from __future__ import annotations

import datetime

from scripts import daily_checkup


def _fake_overview(data_date: str):
    return lambda url, timeout=25: (
        200,
        {"items": [{"paper_trading": {"entries": [{"data_date": data_date}]}}]},
        {},
    )


def _run(monkeypatch, now: datetime.datetime, data_date: str) -> list[dict]:
    monkeypatch.setattr(daily_checkup, "_now", now)
    monkeypatch.setattr(daily_checkup, "_get_json", _fake_overview(data_date))
    return daily_checkup.check_live_freshness()


def test_tuesday_predawn_catchup_run_is_not_stale(monkeypatch) -> None:
    """2026-07-14 04:52（週二，collect_us 07:03 未跑）看到 07-10（週五）= 正常，不得報警。

    這正是舊判準寄信給老闆的那個時點：4 個日曆天 > 3 → warn。
    """
    findings = _run(
        monkeypatch,
        now=datetime.datetime(2026, 7, 14, 4, 52),
        data_date="2026-07-10",
    )
    assert findings == [], f"設計上正常的時點不該報警，卻得到 {findings}"


def test_after_collection_window_missing_session_is_flagged(monkeypatch) -> None:
    """同一天 10:00（collect_us 07:03 已跑完 + grace）還停在 07-10 = 真的漏收，要報警。"""
    findings = _run(
        monkeypatch,
        now=datetime.datetime(2026, 7, 14, 10, 0),
        data_date="2026-07-10",
    )
    assert len(findings) == 1
    assert findings[0]["dimension"] == "live_freshness"
    assert findings[0]["severity"] == "warn"  # 落後 1 個交易日（07-13）
    assert "2026-07-13" in findings[0]["message"]


def test_fresh_data_after_collection_is_silent(monkeypatch) -> None:
    """10:00 已經收到 07-13（週一 session）= 完全正常。"""
    findings = _run(
        monkeypatch,
        now=datetime.datetime(2026, 7, 14, 10, 0),
        data_date="2026-07-13",
    )
    assert findings == []


def test_two_sessions_behind_midweek_escalates_to_critical(monkeypatch) -> None:
    """舊判準的漏報面：週四還停在週一，只有 3 個日曆天（躲過 >3），實際落後 2 個交易日。"""
    findings = _run(
        monkeypatch,
        now=datetime.datetime(2026, 7, 16, 10, 0),  # 週四
        data_date="2026-07-13",  # 週一；應已收到 07-15（週三）
    )
    assert len(findings) == 1
    assert findings[0]["severity"] == "critical", findings[0]
    assert "落後 2 個交易日" in findings[0]["message"]


def test_expected_session_skips_weekend(monkeypatch) -> None:
    """週一早上（collect_us 週一不跑）應該預期的是上週五，不是週日。"""
    expected = daily_checkup._expected_live_session(datetime.datetime(2026, 7, 13, 10, 0))
    assert expected == datetime.date(2026, 7, 10)
