from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.operations_core_scheduler import build_shadow_report, legacy_success_evidence

UTC = timezone.utc


def test_shadow_legacy_evidence_uses_log_banner_not_only_marker(
    tmp_path: Path,
) -> None:
    log = tmp_path / "storage" / "logs" / "cron" / "direct.log"
    log.parent.mkdir(parents=True)
    log.write_text(
        "=== [direct] exit 0 at 2026-07-26T10:00:03+00:00 "
        "(duration=1s) ===\n",
        encoding="utf-8",
    )
    marker = tmp_path / "storage" / "ops" / "cron_last_run.json"
    config = {
        "system_crontab": {
            "items": [
                {
                    "id": "direct",
                    "cron": "0 * * * *",
                    "wrapper_script": "/bin/true",
                    "host_crontab_managed": False,
                    "log_path": "storage/logs/cron/direct.log",
                }
            ]
        }
    }

    assert legacy_success_evidence(
        config,
        repo_root=tmp_path,
        marker_path=marker,
    ) == {"direct": "2026-07-26T10:00:03+00:00"}


def test_shadow_report_separates_match_missing_and_open_window(
    tmp_path: Path,
) -> None:
    config = tmp_path / "runtime_schedules.json"
    receipts = tmp_path / "receipts.json"
    config.write_text(
        json.dumps(
            {
                "metadata": {"timezone": "Asia/Taipei"},
                "schedule_materialization": {
                    "generation": "g1",
                    "mode": "shadow",
                    "shadow_grace_seconds": 120,
                },
                "system_crontab": {"items": []},
            }
        ),
        encoding="utf-8",
    )
    receipts.write_text(
        json.dumps(
            {
                "schema": 1,
                "fires": {},
                "shadow": {
                    "g1:matched": {
                        "generation": "g1",
                        "job_id": "matched",
                        "scheduled_for": "2026-07-26T10:00:00Z",
                        "legacy_observed": True,
                        "observations": 4,
                    },
                    "g1:missing": {
                        "generation": "g1",
                        "job_id": "missing",
                        "scheduled_for": "2026-07-26T10:00:00Z",
                        "legacy_observed": False,
                        "observations": 4,
                    },
                    "g1:pending": {
                        "generation": "g1",
                        "job_id": "pending",
                        "scheduled_for": "2026-07-26T10:09:00Z",
                        "legacy_observed": False,
                        "observations": 1,
                    },
                    "old:ignored": {
                        "generation": "old",
                        "job_id": "ignored",
                        "scheduled_for": "2026-07-26T10:00:00Z",
                        "legacy_observed": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    report = build_shadow_report(
        config_path=config,
        receipts_path=receipts,
        now=datetime(2026, 7, 26, 10, 10, tzinfo=UTC),
    )

    assert report["counts"] == {
        "settled": 2,
        "matched": 1,
        "missing": 1,
        "pending": 1,
    }
    assert report["parity_rate"] == 0.5
    assert [item["job_id"] for item in report["matched"]] == ["matched"]
    assert [item["job_id"] for item in report["missing"]] == ["missing"]
    assert [item["job_id"] for item in report["pending"]] == ["pending"]
