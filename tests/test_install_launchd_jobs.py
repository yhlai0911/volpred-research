from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _environment(tmp_path: Path, config: Path) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "launchctl_calls.txt"
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" >> \"$FAKE_LAUNCHCTL_CALLS\"\n"
        "if [[ ${1:-} == list ]]; then\n"
        "  echo '- 0 com.volpred.fixture'\n"
        "fi\n",
        encoding="utf-8",
    )
    launchctl.chmod(launchctl.stat().st_mode | stat.S_IXUSR)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_LAUNCHCTL_CALLS": str(calls),
        "VOLPRED_PROJECT_ROOT": str(tmp_path / "repo"),
        "VOLPRED_SCHEDULE_JSON": str(config),
        "VOLPRED_LAUNCH_AGENTS_DIR": str(tmp_path / "LaunchAgents"),
        "VOLPRED_LAUNCHD_LOG_DIR": str(tmp_path / "logs"),
    }
    return env, calls


def _write_config(path: Path, *, mode: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schedule_materialization": {
                    "mode": mode,
                    "active_since": (
                        "2026-07-26T10:00:00Z" if mode == "active" else None
                    ),
                    "active_jobs": {},
                },
                "system_crontab": {
                    "items": [
                        {
                            "id": "fixture",
                            "cron": "50 * * * *",
                            "wrapper_script": "/bin/true",
                            "log_path": "storage/logs/cron/fixture.log",
                            "host_crontab_managed": False,
                            "launchagent_label": "com.volpred.fixture",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )


def test_legacy_target_bootstraps_when_decommission_array_is_empty(
    tmp_path: Path,
) -> None:
    config = tmp_path / "runtime_schedules.json"
    _write_config(config, mode="shadow")
    env, calls = _environment(tmp_path, config)

    result = subprocess.run(
        ["bash", "scripts/install_launchd_jobs.sh", "--id", "fixture"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "LaunchAgents" / "com.volpred.fixture.plist").is_file()
    assert "bootstrap" in calls.read_text(encoding="utf-8")


def test_active_target_boots_out_when_install_array_is_empty(
    tmp_path: Path,
) -> None:
    config = tmp_path / "runtime_schedules.json"
    _write_config(config, mode="active")
    env, calls = _environment(tmp_path, config)

    result = subprocess.run(
        ["bash", "scripts/install_launchd_jobs.sh", "--id", "fixture"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    text = calls.read_text(encoding="utf-8")
    assert "bootout" in text
    assert "bootstrap" not in text
