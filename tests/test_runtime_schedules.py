from volpred.config import (
    get_runtime_schedules_path,
    get_schedule_items,
    load_runtime_schedules,
)


def test_runtime_schedules_config_has_required_sections():
    data = load_runtime_schedules()

    assert get_runtime_schedules_path().exists()
    assert data["metadata"]["canonical_path"] == "config/runtime_schedules.json"
    assert len(get_schedule_items("system_crontab")) >= 4
    # WS-H2 2026-07-20: token_usage_daily_report removed (token convergence);
    # only the disabled platform_ops_patrol declaration remains.
    assert len(get_schedule_items("remote_triggers")) >= 1
    assert len(get_schedule_items("session_crons")) >= 5
