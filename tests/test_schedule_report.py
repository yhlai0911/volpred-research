from datetime import date

from volpred.ops import schedules


def test_build_schedule_report_matches_live_items(monkeypatch):
    monkeypatch.setattr(
        schedules,
        "load_runtime_schedules",
        lambda: {
            "system_crontab": {
                "items": [
                    {
                        "id": "collect_tw_data",
                        "label": "台股收集",
                        "matchers": ["collect_tw_data.py"],
                    },
                    {
                        "id": "daily_update",
                        "label": "每日更新",
                        "matchers": ["daily_update.py"],
                    },
                ]
            },
            "session_crons": {"items": [{"id": "planning"}, {"id": "questions"}]},
            "remote_triggers": {"items": [{"id": "ops_patrol"}]},
        },
    )
    monkeypatch.setattr(
        schedules,
        "read_system_crontab",
        lambda: {
            "available": True,
            "items": [
                {
                    "cron": "0 15 * * 1-5",
                    "command": ".venv/bin/python scripts/collect_tw_data.py",
                    "raw": "0 15 * * 1-5 .venv/bin/python scripts/collect_tw_data.py",
                }
            ],
            "note": "ok",
        },
    )

    report = schedules.build_schedule_report()

    assert report["session_cron_count"] == 2
    assert report["remote_trigger_count"] == 1
    assert report["expected_system_task_count"] == 2
    assert report["matched_system_tasks"] == ["台股收集"]
    assert report["missing_system_tasks"] == ["每日更新"]


def test_cron_matches_date_weekday_guard():
    # 2026-06-21 is Sunday; daily_update cron is Monday-Saturday.
    assert schedules.cron_matches_date("3 8 * * 1-6", date(2026, 6, 21)) is False
    assert schedules.cron_matches_date("3 8 * * 1-6", date(2026, 6, 22)) is True

    # Sunday may be written as either 0 or 7.
    assert schedules.cron_matches_date("0 8 * * 0", date(2026, 6, 21)) is True
    assert schedules.cron_matches_date("0 8 * * 7", date(2026, 6, 21)) is True

    # Standard cron OR semantics when both day-of-month and day-of-week are restricted.
    assert schedules.cron_matches_date("0 8 1 * 1", date(2026, 6, 8)) is True
    assert schedules.cron_matches_date("0 8 1 * 1", date(2026, 6, 9)) is False


def test_build_schedule_due_report_for_daily_update():
    config = {
        "system_crontab": {
            "items": [
                {
                    "id": "daily_update",
                    "label": "daily_update 每日更新與同步",
                    "cron": "3 8 * * 1-6",
                    "log_path": "storage/logs/cron/daily_update.log",
                }
            ]
        },
        "session_crons": {"items": []},
        "remote_triggers": {"items": []},
    }

    sunday = schedules.build_schedule_due_report(
        "daily_update",
        target_date="2026-06-21",
        config=config,
    )
    monday = schedules.build_schedule_due_report(
        "daily_update",
        target_date="2026-06-22",
        config=config,
    )

    assert sunday["scheduled"] is False
    assert sunday["reason"] == "2026-06-21 (Sunday) does not match cron '3 8 * * 1-6'"
    assert monday["scheduled"] is True
    assert monday["log_path"] == "storage/logs/cron/daily_update.log"
