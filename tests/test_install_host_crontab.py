from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_codex_update_has_one_canonical_schedule_owner() -> None:
    """The 2026-07-20 host + piggy-back race corrupted the version receipt."""
    config = json.loads((ROOT / "config" / "runtime_schedules.json").read_text(encoding="utf-8"))
    item = next(
        entry
        for entry in config["system_crontab"]["items"]
        if entry["id"] == "codex_update"
    )

    assert item["host_crontab_managed"] is False
    assert item["piggy_back_enabled"] is True


def test_git_push_backup_has_one_canonical_schedule_owner() -> None:
    config = json.loads((ROOT / "config" / "runtime_schedules.json").read_text(encoding="utf-8"))
    item = next(
        entry
        for entry in config["system_crontab"]["items"]
        if entry["id"] == "git_push_backup"
    )

    assert item["host_crontab_managed"] is False
    assert item["piggy_back_enabled"] is True


def test_market_closure_detector_has_one_canonical_schedule_owner() -> None:
    """The :00 host-cron fallback really fires on macOS and duplicated launchd."""
    config = json.loads((ROOT / "config" / "runtime_schedules.json").read_text(encoding="utf-8"))
    item = next(
        entry
        for entry in config["system_crontab"]["items"]
        if entry["id"] == "market_closure_detect"
    )

    assert item["mechanism"] == "launchd"
    assert item["host_crontab_managed"] is False


def test_targeted_reconcile_removes_git_push_host_leg(tmp_path: Path) -> None:
    state = tmp_path / "crontab.txt"
    state.write_text(
        "15 1 * * * /usr/bin/true # personal\n"
        "0 * * * * /Users/yhlai0911/.volpred/bin/cron_git_push_backup.sh "
        ">> /tmp/git_push.log 2>&1 # volpred-git-push-backup\n"
        "10 8,14,20 * * * /tmp/boss >> /tmp/boss.log 2>&1 "
        "# volpred-boss-report-4h\n",
        encoding="utf-8",
    )
    env = _fake_crontab_env(tmp_path, state)

    result = subprocess.run(
        ["bash", "scripts/install_host_crontab.sh", "--id", "git_push_backup"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    installed = state.read_text(encoding="utf-8")
    assert "# volpred-git-push-backup" not in installed
    assert "15 1 * * * /usr/bin/true # personal" in installed
    assert "# volpred-boss-report-4h" in installed


def test_targeted_reconcile_removes_codex_update_host_leg(tmp_path: Path) -> None:
    state = tmp_path / "crontab.txt"
    state.write_text(
        "15 1 * * * /usr/bin/true # personal\n"
        "0 9 * * 1 /Users/yhlai0911/.volpred/bin/cron_codex_update.sh "
        ">> /tmp/codex_update.log 2>&1 # volpred-codex-update\n"
        "10 8,14,20 * * * /tmp/boss >> /tmp/boss.log 2>&1 "
        "# volpred-boss-report-4h\n",
        encoding="utf-8",
    )
    env = _fake_crontab_env(tmp_path, state)

    result = subprocess.run(
        ["bash", "scripts/install_host_crontab.sh", "--id", "codex_update"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    installed = state.read_text(encoding="utf-8")
    assert "# volpred-codex-update" not in installed
    assert "15 1 * * * /usr/bin/true # personal" in installed
    assert "# volpred-boss-report-4h" in installed


def _fake_crontab_env(tmp_path: Path, state: Path) -> dict[str, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    fake_crontab = fake_bin / "crontab"
    fake_crontab.write_text(
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "if [[ ${1:-} == '-l' ]]; then\n"
        "  cat \"$FAKE_CRONTAB_STATE\"\n"
        "else\n"
        "  cp \"$1\" \"$FAKE_CRONTAB_STATE\"\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_crontab.chmod(fake_crontab.stat().st_mode | stat.S_IXUSR)
    return {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_CRONTAB_STATE": str(state),
    }


def test_targeted_reconcile_removes_only_requested_schedule(tmp_path: Path) -> None:
    state = tmp_path / "crontab.txt"
    state.write_text(
        "15 1 * * * /usr/bin/true # personal\n"
        "7 */6 * * * /tmp/release >> /tmp/release.log 2>&1 # volpred-release-pool\n"
        "10 8,14,20 * * * /tmp/boss >> /tmp/boss.log 2>&1 # volpred-boss-report-4h\n",
        encoding="utf-8",
    )
    env = _fake_crontab_env(tmp_path, state)

    result = subprocess.run(
        ["bash", "scripts/install_host_crontab.sh", "--id", "release_pool"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    installed = state.read_text(encoding="utf-8")
    assert "# volpred-release-pool" not in installed
    assert "15 1 * * * /usr/bin/true # personal" in installed
    assert "# volpred-boss-report-4h" in installed


def test_targeted_reconcile_preserves_empty_log_field_and_removes_legacy_line(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    wrapper = tmp_path / "fixture_wrapper.sh"
    wrapper.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    config = tmp_path / "runtime_schedules.json"
    config.write_text(
        "{\n"
        '  "system_crontab": {"items": [{\n'
        '    "id": "missing_log_job",\n'
        '    "cron": "0 * * * *",\n'
        f'    "wrapper_script": "{wrapper}"\n'
        "  }]}\n"
        "}\n",
        encoding="utf-8",
    )
    state = tmp_path / "crontab.txt"
    state.write_text(
        f"0 * * * * {wrapper} >> /wrong/path 2>&1 # volpred-\n"
        "15 1 * * * /usr/bin/true # personal\n",
        encoding="utf-8",
    )
    env = {
        **_fake_crontab_env(tmp_path, state),
        "VOLPRED_REPO_ROOT": str(repo_root),
        "VOLPRED_RUNTIME_SCHEDULES_PATH": str(config),
    }

    result = subprocess.run(
        ["bash", "scripts/install_host_crontab.sh", "--id", "missing_log_job"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    lines = state.read_text(encoding="utf-8").splitlines()
    generated = [line for line in lines if str(wrapper) in line]
    assert generated == [
        f"0 * * * * {wrapper} >> "
        f"{repo_root}/storage/logs/cron/missing_log_job.log 2>&1 "
        "# volpred-missing-log-job"
    ]
    assert "15 1 * * * /usr/bin/true # personal" in lines
