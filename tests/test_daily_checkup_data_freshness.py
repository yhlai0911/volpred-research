from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

from scripts import daily_checkup


def _only_file_jobs(monkeypatch, tmp_path: Path, jobs: list[tuple]) -> None:
    monkeypatch.setattr(daily_checkup, "ROOT", tmp_path)
    monkeypatch.setattr(daily_checkup, "STORAGE", tmp_path / "storage")
    monkeypatch.setattr(daily_checkup, "DATA_JOBS_EXPECTED_H", {})
    monkeypatch.setattr(daily_checkup, "DATA_FILE_JOBS", jobs)
    monkeypatch.setattr(daily_checkup, "_now", datetime.datetime(2026, 7, 11, 12, 0))


def test_taifex_missing_finding_has_source_specific_recovery(
    monkeypatch, tmp_path: Path
) -> None:
    recovery = "uv run python scripts/collect_taifex_tick.py"
    _only_file_jobs(
        monkeypatch,
        tmp_path,
        [("taifex_5min_rv", "data/intraday/taifex_5min_rv.csv", 80, "collect_tw", recovery)],
    )

    findings = daily_checkup.check_data_freshness()

    assert len(findings) == 1
    assert "taifex_5min_rv" in findings[0]["message"]
    assert findings[0]["recovery"] == recovery


def test_stale_and_fresh_file_jobs_keep_distinct_recoveries(
    monkeypatch, tmp_path: Path
) -> None:
    now = datetime.datetime(2026, 7, 11, 12, 0)
    stale = tmp_path / "data" / "intraday" / "taifex_5min_rv.csv"
    fresh = tmp_path / "data" / "intraday" / "twse" / "today.csv"
    stale.parent.mkdir(parents=True)
    fresh.parent.mkdir(parents=True)
    stale.write_text("date,rv\n2026-01-01,1\n")
    fresh.write_text("date,x\n2026-07-11,1\n")
    stale_ts = (now - datetime.timedelta(hours=130)).timestamp()
    fresh_ts = (now - datetime.timedelta(hours=1)).timestamp()
    os.utime(stale, (stale_ts, stale_ts))
    os.utime(fresh, (fresh_ts, fresh_ts))
    taifex_recovery = "uv run python scripts/collect_taifex_tick.py"
    twse_recovery = "uv run python scripts/collect_twse_orderflow.py --date today"
    _only_file_jobs(
        monkeypatch,
        tmp_path,
        [
            ("taifex_5min_rv", "data/intraday/taifex_5min_rv.csv", 80, "collect_tw", taifex_recovery),
            ("twse_orderflow", "data/intraday/twse/*.csv", 80, "collect_tw", twse_recovery),
        ],
    )

    findings = daily_checkup.check_data_freshness()

    assert len(findings) == 1
    assert "taifex_5min_rv" in findings[0]["message"]
    assert findings[0]["recovery"] == taifex_recovery


def test_taifex_increment_reuses_single_collect_tw_schedule() -> None:
    root = Path(__file__).resolve().parent.parent
    config = json.loads((root / "config" / "runtime_schedules.json").read_text())
    jobs = [
        job
        for job in config["system_crontab"]["items"]
        if job.get("id") == "collect_tw_data"
    ]

    assert len(jobs) == 1
    assert jobs[0]["cron"] == "0 15 * * 1-5"
    assert "TAIFEX" in jobs[0]["description"]
