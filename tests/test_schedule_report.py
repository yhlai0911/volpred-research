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
