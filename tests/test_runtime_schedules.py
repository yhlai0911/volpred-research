import plistlib
from pathlib import Path

from volpred.config import (
    get_runtime_schedules_path,
    get_schedule_items,
    load_runtime_schedules,
)

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_schedules_config_has_required_sections():
    data = load_runtime_schedules()

    assert get_runtime_schedules_path().exists()
    assert data["metadata"]["canonical_path"] == "config/runtime_schedules.json"
    assert len(get_schedule_items("system_crontab")) >= 4
    # WS-H2 2026-07-20: token_usage_daily_report removed (token convergence);
    # only the disabled platform_ops_patrol declaration remains.
    assert len(get_schedule_items("remote_triggers")) >= 1
    assert get_schedule_items("session_crons") == []
    assert data["session_crons"]["status"] == "retired"
    assert (
        data["session_crons"]["replacement_jobs"]["knowledge_index_check"]
        == ["knowledge_index_maintain"]
    )


def test_dispatch_writer_isolation_is_fail_closed_in_config_and_launchd():
    data = load_runtime_schedules()
    daemon = next(
        item
        for item in data["daemons"]
        if item["id"] == "volpred-dispatch-supervisor"
    )
    isolation = daemon["writer_isolation"]
    assert isolation["mode"] == "enforce"
    assert isolation["max_active"] == 2
    assert isolation["max_total"] >= isolation["max_active"]

    with (
        ROOT / "ops" / "launchd" / "com.volpred.dispatch-supervisor.plist"
    ).open("rb") as handle:
        plist = plistlib.load(handle)
    assert (
        plist["EnvironmentVariables"]["VOLPRED_WRITER_ISOLATION_REQUIRED"]
        == "1"
    )
