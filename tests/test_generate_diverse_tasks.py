from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_diverse_tasks.py"
SPEC = importlib.util.spec_from_file_location("generate_diverse_tasks", MODULE_PATH)
generate_diverse_tasks = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(generate_diverse_tasks)


def test_gen_platform_ops_tasks_prefers_fresh_log_over_stale_last_run(tmp_path, monkeypatch) -> None:
    cron_last_run = tmp_path / "cron_last_run.json"
    runtime_schedules = tmp_path / "runtime_schedules.json"
    cron_logs = tmp_path / "cron"
    cron_logs.mkdir()

    cron_last_run.write_text(
        json.dumps({"daily_update": "2026-04-25T01:05:47+00:00"}, ensure_ascii=False),
        encoding="utf-8",
    )
    runtime_schedules.write_text(
        json.dumps(
            {
                "system_crontab": {
                    "items": [
                        {"id": "daily_update", "cron": "3 8 * * 1-6"},
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (cron_logs / "daily_update.log").write_text(
        "=== [daily_update] exit 0 at 2026-05-27T08:15:44+0800 (duration=759s) ===\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(generate_diverse_tasks, "CRON_LAST_RUN", cron_last_run)
    monkeypatch.setattr(generate_diverse_tasks, "RUNTIME_SCHEDULES", runtime_schedules)
    monkeypatch.setattr(generate_diverse_tasks, "CRON_LOGS", cron_logs)

    tasks = generate_diverse_tasks.gen_platform_ops_tasks(existing=set())

    assert tasks == []


def test_gen_platform_ops_tasks_still_emits_when_log_missing_and_last_run_stale(tmp_path, monkeypatch) -> None:
    cron_last_run = tmp_path / "cron_last_run.json"
    runtime_schedules = tmp_path / "runtime_schedules.json"
    cron_logs = tmp_path / "cron"
    cron_logs.mkdir()

    cron_last_run.write_text(
        json.dumps({"daily_update": "2026-04-25T01:05:47+00:00"}, ensure_ascii=False),
        encoding="utf-8",
    )
    runtime_schedules.write_text(
        json.dumps(
            {
                "system_crontab": {
                    "items": [
                        {"id": "daily_update", "cron": "3 8 * * 1-6"},
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(generate_diverse_tasks, "CRON_LAST_RUN", cron_last_run)
    monkeypatch.setattr(generate_diverse_tasks, "RUNTIME_SCHEDULES", runtime_schedules)
    monkeypatch.setattr(generate_diverse_tasks, "CRON_LOGS", cron_logs)

    tasks = generate_diverse_tasks.gen_platform_ops_tasks(existing=set())

    assert len(tasks) == 1
    assert tasks[0]["id"] == "platform_ops_cron_stale_daily_update"
