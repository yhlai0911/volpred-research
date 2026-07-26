from __future__ import annotations

from pathlib import Path

from scripts.operations_core_scheduler import legacy_success_evidence


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
