from __future__ import annotations

import importlib.util
import json
import os
import time
from datetime import datetime, timedelta, timezone
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
    fresh_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S+0000")
    (cron_logs / "daily_update.log").write_text(
        f"=== [daily_update] exit 0 at {fresh_ts} (duration=759s) ===\n",
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


def test_piggy_back_skip_with_custom_log_path_uses_mtime_no_false_positive(tmp_path, monkeypatch) -> None:
    """Regression: 2026-06-08 market_calendar_sync false-positive.

    piggy_back_skip=true 的 host-only job，cron_last_run.json 永不更新；
    且 log_path 與 {cid}.log 不同名 → detector 必須 fallback 到 log file mtime."""
    cron_last_run = tmp_path / "cron_last_run.json"
    runtime_schedules = tmp_path / "runtime_schedules.json"
    cron_logs = tmp_path / "cron"
    cron_logs.mkdir()

    cron_last_run.write_text(
        json.dumps({"market_calendar_sync": "2026-05-25T00:00:14+00:00"}, ensure_ascii=False),
        encoding="utf-8",
    )
    custom_log = cron_logs / "market_cal.log"
    custom_log.write_text("Trading calendar synced: 30 days (2026-06-08 ~ 2026-07-07)\n", encoding="utf-8")
    fresh = time.time() - 3600
    os.utime(custom_log, (fresh, fresh))
    runtime_schedules.write_text(
        json.dumps(
            {
                "system_crontab": {
                    "items": [
                        {
                            "id": "market_calendar_sync",
                            "cron": "0 8 * * 1",
                            "log_path": str(custom_log.relative_to(tmp_path)),
                            "piggy_back_skip": True,
                        },
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(generate_diverse_tasks, "ROOT", tmp_path)
    monkeypatch.setattr(generate_diverse_tasks, "CRON_LAST_RUN", cron_last_run)
    monkeypatch.setattr(generate_diverse_tasks, "RUNTIME_SCHEDULES", runtime_schedules)
    monkeypatch.setattr(generate_diverse_tasks, "CRON_LOGS", cron_logs)

    tasks = generate_diverse_tasks.gen_platform_ops_tasks(existing=set())

    assert tasks == []


def test_host_crontab_unmanaged_advisory_items_skipped(tmp_path, monkeypatch) -> None:
    """Regression: shared_scheduler_tick (host_crontab_managed=false, advisory)
    must never appear in cron-stale candidates."""
    cron_last_run = tmp_path / "cron_last_run.json"
    runtime_schedules = tmp_path / "runtime_schedules.json"
    cron_logs = tmp_path / "cron"
    cron_logs.mkdir()

    cron_last_run.write_text(
        json.dumps({"shared_scheduler_tick": "2026-04-19T00:00:00+00:00"}, ensure_ascii=False),
        encoding="utf-8",
    )
    runtime_schedules.write_text(
        json.dumps(
            {
                "system_crontab": {
                    "items": [
                        {
                            "id": "shared_scheduler_tick",
                            "cron": "*/10 * * * *",
                            "host_crontab_managed": False,
                        },
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(generate_diverse_tasks, "ROOT", tmp_path)
    monkeypatch.setattr(generate_diverse_tasks, "CRON_LAST_RUN", cron_last_run)
    monkeypatch.setattr(generate_diverse_tasks, "RUNTIME_SCHEDULES", runtime_schedules)
    monkeypatch.setattr(generate_diverse_tasks, "CRON_LOGS", cron_logs)

    tasks = generate_diverse_tasks.gen_platform_ops_tasks(existing=set())

    assert tasks == []


def test_governance_skill_audit_warns_when_skill_stat_fails(
    tmp_path, monkeypatch, capsys
) -> None:
    skills_dir = tmp_path / ".claude" / "skills"
    skill_md = skills_dir / "bad-skill" / "SKILL.md"
    skill_md.parent.mkdir(parents=True)
    skill_md.write_text("# bad skill\n", encoding="utf-8")

    monkeypatch.setattr(generate_diverse_tasks, "SKILLS_DIR", skills_dir)
    monkeypatch.setattr(generate_diverse_tasks, "ERROR_LOG", tmp_path / "missing_error_log.md")
    original_stat = Path.stat

    def flaky_stat(self: Path, *args, **kwargs):
        if self == skill_md:
            raise OSError("stat denied")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", flaky_stat)

    tasks = generate_diverse_tasks.gen_governance_tasks(existing=set())

    assert tasks == []
    err = capsys.readouterr().err
    assert "[diverse_gen] WARN skill mtime stat failed; excluding skill from stale audit" in err
    assert "stat denied" in err


def test_parse_banner_ts_accepts_hhmm_without_seconds() -> None:
    """Python script banners like `=== 台股數據收集: 2026-06-11 15:00 ===` use HH:MM
    (no seconds). _parse_banner_ts must accept them, otherwise _latest_cron_log_ts
    walks backward past every recent run and returns an ancient cron_lib banner —
    triggering a false 'cron staleness' alarm (2026-06-11 root cause)."""
    ts = generate_diverse_tasks._parse_banner_ts(
        "=== 台股數據收集: 2026-06-11 15:00 ==="
    )
    assert ts is not None
    # 15:00 Asia/Taipei = 07:00 UTC
    assert ts.hour == 7 and ts.minute == 0
    assert ts.year == 2026 and ts.month == 6 and ts.day == 11


def test_latest_cron_log_ts_picks_latest_hhmm_banner_over_old_seconds_banner(
    tmp_path, monkeypatch
) -> None:
    """Regression: when a log contains old cron_lib banners (with seconds) followed
    by newer python-print banners (HH:MM only), detector must return the newer one."""
    monkeypatch.setattr(generate_diverse_tasks, "ROOT", tmp_path)
    monkeypatch.setattr(generate_diverse_tasks, "CRON_LOGS", tmp_path / "cron")
    (tmp_path / "cron").mkdir()
    log = tmp_path / "cron" / "x.log"
    log.write_text(
        "=== [collect_tw_data] exit 0 at 2026-05-28T07:00:24.467842+00:00 (duration=16.7s) ===\n"
        "=== 台股數據收集: 2026-06-11 15:00 ===\n",
        encoding="utf-8",
    )
    ts = generate_diverse_tasks._latest_cron_log_ts("x", "cron/x.log")
    assert ts is not None
    assert ts.year == 2026 and ts.month == 6 and ts.day == 11


def test_latest_cron_log_ts_warns_on_unreadable_log(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(generate_diverse_tasks, "ROOT", tmp_path)
    monkeypatch.setattr(generate_diverse_tasks, "CRON_LOGS", tmp_path / "cron")
    (tmp_path / "cron" / "x.log").mkdir(parents=True)

    ts = generate_diverse_tasks._latest_cron_log_ts("x", "cron/x.log")

    assert ts is None
    captured = capsys.readouterr()
    assert "[diverse_gen] WARN cron log read failed; skipping log timestamp" in captured.err
    assert "x.log" in captured.err
    assert "IsADirectoryError" in captured.err


def test_experiment_dir_with_descriptive_suffix_covers_kid() -> None:
    assert generate_diverse_tasks._experiment_dir_covers_kid(
        "k1458_h1_trough_decomposition",
        "k1458",
    )
    assert not generate_diverse_tasks._experiment_dir_covers_kid("k14580", "k1458")


def test_paper_review_tasks_are_codex_agentable_not_main_thread_only(tmp_path, monkeypatch) -> None:
    feed = tmp_path / "feed.json"
    feed.write_text(
        json.dumps(
            [
                {
                    "id": "mile_review_me",
                    "title": "Review target",
                    "status": "published",
                    "published_at": datetime.now(timezone.utc).isoformat(),
                    "tags": ["research"],
                    "audience": "research",
                    "details": {"experiment_refs": ["K9999"]},
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(generate_diverse_tasks, "FEED", feed)

    tasks = generate_diverse_tasks.gen_paper_review_tasks(
        existing=set(),
        rng=generate_diverse_tasks.random.Random(42),
    )

    assert len(tasks) == 1
    assert tasks[0]["task_type"] == "paper_review"
    assert "main-thread-only" not in tasks[0]["tags"]


def test_gen_experiment_tasks_warns_when_research_program_unreadable(
    tmp_path, monkeypatch, capsys
) -> None:
    research_program = tmp_path / "research_program.md"
    research_program.mkdir()
    experiments = tmp_path / "experiments"
    experiments.mkdir()

    monkeypatch.setattr(generate_diverse_tasks, "RESEARCH_PROGRAM", research_program)
    monkeypatch.setattr(generate_diverse_tasks, "EXPERIMENTS_DIR", experiments)

    tasks = generate_diverse_tasks.gen_experiment_tasks(
        existing=set(),
        rng=generate_diverse_tasks.random.Random(1533),
    )

    assert tasks == []
    err = capsys.readouterr().err
    assert "[diverse_gen] WARN research_program read failed; skipping experiment backlog" in err
    assert "IsADirectoryError" in err


def test_gen_experiment_tasks_warns_when_experiments_dir_unreadable(
    tmp_path, monkeypatch, capsys
) -> None:
    research_program = tmp_path / "research_program.md"
    research_program.write_text("Backlog: K9999 should become an experiment.\n", encoding="utf-8")
    experiments = tmp_path / "experiments"
    experiments.write_text("not a directory", encoding="utf-8")

    monkeypatch.setattr(generate_diverse_tasks, "RESEARCH_PROGRAM", research_program)
    monkeypatch.setattr(generate_diverse_tasks, "EXPERIMENTS_DIR", experiments)

    tasks = generate_diverse_tasks.gen_experiment_tasks(
        existing=set(),
        rng=generate_diverse_tasks.random.Random(1533),
    )

    assert tasks == []
    err = capsys.readouterr().err
    assert "[diverse_gen] WARN experiments directory scan failed; skipping experiment backlog" in err
    assert "NotADirectoryError" in err


def test_gen_experiment_tasks_warns_when_knowledge_filter_unreadable(
    tmp_path, monkeypatch, capsys
) -> None:
    research_program = tmp_path / "research_program.md"
    research_program.write_text("Backlog: K9999 should become an experiment.\n", encoding="utf-8")
    experiments = tmp_path / "experiments"
    experiments.mkdir()
    knowledge = tmp_path / "storage" / "memory" / "knowledge.json"
    knowledge.mkdir(parents=True)

    monkeypatch.setattr(generate_diverse_tasks, "ROOT", tmp_path)
    monkeypatch.setattr(generate_diverse_tasks, "RESEARCH_PROGRAM", research_program)
    monkeypatch.setattr(generate_diverse_tasks, "EXPERIMENTS_DIR", experiments)

    tasks = generate_diverse_tasks.gen_experiment_tasks(
        existing=set(),
        rng=generate_diverse_tasks.random.Random(1533),
    )

    assert len(tasks) == 1
    assert tasks[0]["id"] == "experiment_scaffold_k9999"
    err = capsys.readouterr().err
    assert "[diverse_gen] WARN knowledge completed-K scan failed; continuing without knowledge filter" in err
    assert "IsADirectoryError" in err


def test_gen_experiment_tasks_warns_when_archive_filter_file_unreadable(
    tmp_path, monkeypatch, capsys
) -> None:
    research_program = tmp_path / "research_program.md"
    research_program.write_text("Backlog: K9999 should become an experiment.\n", encoding="utf-8")
    experiments = tmp_path / "experiments"
    experiments.mkdir()
    archive_file = tmp_path / "docs" / "research_archive" / "completed_phases_bad.md"
    archive_file.mkdir(parents=True)

    monkeypatch.setattr(generate_diverse_tasks, "ROOT", tmp_path)
    monkeypatch.setattr(generate_diverse_tasks, "RESEARCH_PROGRAM", research_program)
    monkeypatch.setattr(generate_diverse_tasks, "EXPERIMENTS_DIR", experiments)

    tasks = generate_diverse_tasks.gen_experiment_tasks(
        existing=set(),
        rng=generate_diverse_tasks.random.Random(1533),
    )

    assert len(tasks) == 1
    assert tasks[0]["id"] == "experiment_scaffold_k9999"
    err = capsys.readouterr().err
    assert "[diverse_gen] WARN research archive completed-K scan failed" in err
    assert "IsADirectoryError" in err
