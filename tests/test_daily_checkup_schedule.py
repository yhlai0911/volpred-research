from __future__ import annotations

import json
import os
import plistlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _schedule() -> dict:
    data = json.loads((ROOT / "config/runtime_schedules.json").read_text(encoding="utf-8"))
    matches = [item for item in data["system_crontab"]["items"] if item.get("id") == "daily_checkup"]
    assert len(matches) == 1
    return matches[0]


def test_daily_checkup_has_one_launchagent_owner() -> None:
    item = _schedule()
    assert item["cron"] == "40 9 * * *"
    assert item["mechanism"] == "launchd"
    assert item["launchagent_label"] == "com.volpred.daily-checkup"
    assert item["host_crontab_managed"] is False
    assert item.get("piggy_back_enabled") is not True
    assert item["wrapper_script"] == "/Users/yhlai0911/.volpred/bin/cron_daily_checkup.sh"
    assert item["log_path"] == "storage/logs/cron/daily_checkup.log"


def test_daily_checkup_wrapper_emits_observable_completion() -> None:
    text = (ROOT / "scripts/cron_daily_checkup.sh").read_text(encoding="utf-8")
    assert "storage/logs/cron/daily_checkup.log" in text
    assert "source scripts/cron_lib.sh" in text
    assert 'cron_emit_start "daily_checkup"' in text
    assert 'cron_emit_exit "daily_checkup"' in text
    assert "daily_checkup.py --alert" in text
    assert "CHECKUP_CAP_SEC=300" in text


def test_targeted_launchagent_render_matches_canonical_schedule(tmp_path: Path) -> None:
    launchagents = tmp_path / "LaunchAgents"
    env = os.environ.copy()
    env.update(
        {
            "VOLPRED_PROJECT_ROOT": str(ROOT),
            "VOLPRED_SCHEDULE_JSON": str(ROOT / "config/runtime_schedules.json"),
            "VOLPRED_LAUNCH_AGENTS_DIR": str(launchagents),
            "VOLPRED_LAUNCHD_LOG_DIR": str(tmp_path / "logs"),
        }
    )
    subprocess.run(
        ["bash", str(ROOT / "scripts/install_launchd_jobs.sh"), "--id", "daily_checkup", "--render-only"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    rendered = list(launchagents.glob("com.volpred.*.plist"))
    assert [path.name for path in rendered] == ["com.volpred.daily-checkup.plist"]
    with rendered[0].open("rb") as handle:
        plist = plistlib.load(handle)

    item = _schedule()
    assert plist["Label"] == item["launchagent_label"]
    assert plist["ProgramArguments"] == ["/bin/bash", "-c", item["wrapper_script"]]
    assert plist["StartCalendarInterval"] == {"Minute": 40, "Hour": 9}
    assert plist["RunAtLoad"] is False
