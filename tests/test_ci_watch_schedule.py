from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ci_watch_has_a_dedicated_five_minute_operations_core_job() -> None:
    config = json.loads(
        (ROOT / "config" / "runtime_schedules.json").read_text(encoding="utf-8")
    )
    jobs = {
        item["id"]: item
        for item in config["system_crontab"]["items"]
    }

    ci_watch = jobs["ci_watch"]
    assert ci_watch["cron"] == "*/5 * * * *"
    assert ci_watch["wrapper_script"].endswith("/cron_ci_watch.sh")
    assert ci_watch["host_crontab_managed"] is False
    assert ci_watch["piggy_back_skip"] is True
    assert (ROOT / "scripts" / "cron_ci_watch.sh").exists()
