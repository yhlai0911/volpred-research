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
    assert len(get_schedule_items("remote_triggers")) >= 2
    assert len(get_schedule_items("session_crons")) >= 5
